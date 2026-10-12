import json
import tempfile
import threading
import time
import unittest
from pathlib import Path

from services.douyin.mention_monitor import MentionMonitor


class QuietMonitor(MentionMonitor):
    def _loop(self):
        pass


class MentionTests(unittest.TestCase):
    def setUp(self):
        cache = Path(__file__).resolve().parents[3] / 'cache'
        cache.mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=cache)
        self.monitor = QuietMonitor(Path(self.temp.name), lambda *_: {'summary': '内容'}, lambda *_: '这是摘要')
        self.monitor.enabled = True
        self.monitor.session = 'test'

    def tearDown(self):
        self.temp.cleanup()

    def snapshot(self, comments, **extra):
        self.monitor.command = {'id': 'collect', 'action': 'collectMentions'}
        self.monitor.accept(dict(id='collect', ok=True, ready=True, fresh=True, account_id='123',
                                 items=[dict(work_id='456', comment_id=c) for c in comments], **extra))

    def test_baseline_and_persistent_dedup(self):
        self.snapshot(['100'])
        self.snapshot(['100', '101'])
        rows = self.monitor.status()['items']
        self.assertEqual({r['comment_id']: r['status'] for r in rows}, {'100': 'baseline', '101': 'pending'})
        restarted = QuietMonitor(Path(self.temp.name), None, None)
        self.assertEqual(len(restarted.status()['items']), 2)
        self.assertEqual(restarted.status()['items'][0]['status'], 'pending')

    def test_restart_collects_new_mentions_since_saved_checkpoint(self):
        self.snapshot(['100'])
        with self.monitor.db() as db:
            db.execute('UPDATE mention_checkpoints SET observed_at=1000 WHERE account_id=?', ('123',))
        restarted = QuietMonitor(Path(self.temp.name), None, None)
        restarted.enabled = True
        restarted.session = 'restart'
        restarted.listen_started_at = 2000
        restarted.command = {'id': 'collect', 'action': 'collectMentions'}
        restarted.accept(dict(id='collect', ok=True, ready=True, fresh=True, account_id='123', items=[
            dict(work_id='456', comment_id='101', source_timestamp=1500),
            dict(work_id='456', comment_id='102', source_timestamp=900),
            dict(work_id='456', comment_id='103')]))
        rows = {row['comment_id']: row['status'] for row in restarted.status()['items']}
        self.assertEqual(rows['101'], 'pending')
        self.assertEqual(rows['102'], 'baseline')
        self.assertEqual(rows['103'], 'baseline')

    def test_prepare_runs_while_model_consumer_is_busy(self):
        self.snapshot([])
        self.snapshot(['101'])
        entered, release = threading.Event(), threading.Event()
        prepared = []
        class Agent:
            def prepare(self, row, root, progress):
                prepared.append(row['comment_id'])
                progress('正在下载', None)
                entered.set()
                release.wait(2)
        self.monitor.agent = Agent()
        busy = threading.Event()
        self.monitor.worker = threading.Thread(target=lambda: busy.wait(3))
        self.monitor.worker.start()
        try:
            self.monitor.dispatch_next()
            self.assertTrue(entered.wait(1))
            self.monitor.dispatch_next()
            self.assertEqual(prepared, ['101'])
            row = self.monitor.status()['items'][0]
            self.assertEqual(row['status'], 'pending')
            self.assertEqual(row['preparation_status'], 'running')
            release.set()
            self.monitor.preparer.join(2)
            self.assertEqual(self.monitor.status()['items'][0]['preparation_status'], 'done')
        finally:
            release.set()
            busy.set()
            self.monitor.worker.join(2)

    def test_fifo_single_consumer_and_failure_continues(self):
        self.snapshot([])
        self.snapshot(['101', '102', '103'])
        entered, release = threading.Event(), threading.Event()
        calls = []
        def analyze(*_):
            calls.append(threading.get_ident())
            entered.set()
            release.wait(3)
            raise RuntimeError('分析失败')
        self.monitor.analyze = analyze
        self.monitor.dispatch_next()
        self.assertTrue(entered.wait(2))
        first = self.monitor.worker
        self.monitor.dispatch_next()
        self.assertIs(self.monitor.worker, first)
        self.assertEqual(len(calls), 1)
        state = self.monitor.status()
        self.assertEqual(state['queue'], {'pending': 2, 'active': 1, 'concurrency': 1})
        self.assertEqual(next(r for r in state['items'] if r['status']=='running')['comment_id'], '101')
        self.assertEqual(next(r for r in state['items'] if r['comment_id']=='102')['queue_position'], 1)
        release.set()
        first.join(3)
        self.monitor.dispatch_next()
        self.monitor.worker.join(3)
        self.assertEqual(len(calls), 2)
        self.assertEqual(next(r for r in self.monitor.status()['items'] if r['comment_id']=='102')['status'], 'error')

    def test_restart_queue_requires_verified_matching_account(self):
        self.snapshot([])
        self.snapshot(['101'])
        restarted = QuietMonitor(Path(self.temp.name), lambda *_: {'summary': '内容'}, lambda *_: '摘要')
        restarted.enabled = True
        restarted.session = 'new-session'
        restarted.dispatch_next()
        self.assertIsNone(restarted.worker)
        restarted.baseline = False
        restarted.account_id = '789'
        restarted.dispatch_next()
        self.assertIsNone(restarted.worker)
        restarted.account_id = '123'
        restarted.dispatch_next()
        restarted.worker.join(3)
        self.assertEqual(restarted.status()['items'][0]['status'], 'draft')

    def test_draft_does_not_send_and_stop_cancels(self):
        self.snapshot([])
        self.snapshot(['101'])
        row = self.monitor.status()['items'][0]
        self.monitor.process(row)
        self.assertEqual(self.monitor.status()['items'][0]['status'], 'draft')
        self.assertIsNone(self.monitor.command)
        self.snapshot(['102'])
        self.monitor.stop()
        self.assertEqual(self.monitor.status()['items'][0]['status'], 'cancelled')

    def test_reply_receives_only_video_analysis(self):
        self.snapshot([])
        self.snapshot(['101'])
        row = self.monitor.status()['items'][0]
        row['text'] = '@Benyl test 请回答我的问题'
        seen = []
        def summary_only(analysis):
            seen.append(analysis)
            return '视频内容摘要'
        self.monitor.reply = summary_only
        self.monitor.process(row)
        self.assertEqual(seen, [{'summary': '内容'}])
        saved = self.monitor.status()['items'][0]
        self.assertEqual(saved['reply'], '视频内容摘要')
        self.assertEqual(saved['status'], 'draft')

    def test_reply_result_and_wrong_account_dedup_scope(self):
        self.monitor.auto_reply = True
        self.snapshot([])
        self.snapshot(['101'])
        worker = threading.Thread(target=self.monitor.process, args=(self.monitor.status()['items'][0],))
        worker.start()
        deadline = time.time() + 3
        while not self.monitor.command and time.time() < deadline:
            time.sleep(.01)
        command = self.monitor.command
        self.assertEqual(command['replyId'], '101')
        self.monitor.accept({'id': command['id'], 'ok': False, 'error': '发送结果未知'})
        worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(self.monitor.status()['items'][0]['status'], 'error')
        self.snapshot(['101'])
        self.assertEqual(len(self.monitor.status()['items']), 1)

    def test_missing_account_keeps_baseline_and_analysis_failure_never_sends(self):
        self.monitor.command = {'id':'bad', 'action':'collectMentions'}
        self.monitor.accept({'id':'bad','ok':True,'ready':True,'fresh':True,'items':[{'work_id':'1','comment_id':'2'}]})
        self.assertTrue(self.monitor.baseline)
        self.assertEqual(self.monitor.status()['items'], [])
        self.snapshot([])
        self.snapshot(['101'])
        def fail(*_):
            raise RuntimeError('下载失败')
        self.monitor.analyze = fail
        self.monitor.process(self.monitor.status()['items'][0])
        self.assertIsNone(self.monitor.command)
        self.assertEqual(self.monitor.status()['items'][0]['error'], '下载失败')

    def test_account_switch_establishes_new_baseline(self):
        self.snapshot([])
        self.monitor.command = {'id':'other', 'action':'collectMentions'}
        self.monitor.accept({'id':'other','ok':True,'ready':True,'fresh':True,'account_id':'789',
                             'items':[{'work_id':'456','comment_id':'101'}]})
        row = self.monitor.status()['items'][0]
        self.assertEqual(row['status'], 'baseline')
        self.assertTrue(row['id'].startswith('789:'))

    def test_stale_cache_is_not_enqueued_or_used_as_baseline(self):
        self.monitor.command = {'id':'stale','action':'collectMentions'}
        self.monitor.accept({'id':'stale','ok':True,'ready':True,'fresh':False,'account_id':'123',
                             'items':[{'work_id':'456','comment_id':'101'}],'warning':'签名过期'})
        self.assertEqual(self.monitor.status()['items'], [])
        self.assertTrue(self.monitor.baseline)
        self.assertEqual(self.monitor.error, '签名过期')

    def test_later_discovered_old_notice_is_baseline(self):
        self.monitor.listen_started_at = 100
        self.snapshot([])
        self.monitor.command = {'id':'later','action':'collectMentions'}
        self.monitor.accept({'id':'later','ok':True,'ready':True,'fresh':True,'account_id':'123',
                             'items':[{'work_id':'456','comment_id':'101','source_timestamp':99},
                                      {'work_id':'456','comment_id':'102','source_timestamp':101}]})
        self.assertEqual({r['comment_id']:r['status'] for r in self.monitor.status()['items']},
                         {'101':'baseline','102':'pending'})

    def test_request_diagnostics_do_not_expose_templates(self):
        safe = self.monitor._safe_diagnostics([{'path':'/notice/multi/?msToken=secret', 'method':'GET',
                    'headers':{'Authorization':'secret'}, 'body':'private', 'url':'https://host?key=secret',
                    'item_count':1}])
        self.assertEqual(safe[0]['path'],'/notice/multi/')
        self.assertNotIn('secret', json.dumps(safe))

    def test_autostart_retries_config_and_stop_disables_retry(self):
        self.monitor.enabled = False
        def unavailable():
            raise ValueError('未配置模型')
        self.monitor.configure_autostart(unavailable)
        self.monitor.try_autostart()
        self.assertTrue(self.monitor.status()['autostart_pending'])
        self.assertIn('未配置模型', self.monitor.error)
        # Avoid opening a real transport in this unit test.
        self.monitor._start_transport = lambda: None
        self.monitor.configure_autostart(lambda: None)
        self.monitor.try_autostart()
        self.assertTrue(self.monitor.enabled)
        self.assertTrue(self.monitor.auto_reply)
        self.monitor.stop()
        self.monitor.try_autostart()
        self.assertFalse(self.monitor.enabled)
        self.assertFalse(self.monitor.status()['autostart_pending'])

    def test_only_explicit_unsent_baseline_can_be_processed(self):
        self.snapshot(['101','102'])
        key = next(r['id'] for r in self.monitor.status()['items'] if r['comment_id']=='101')
        row = self.monitor.queue_existing(key)
        self.assertEqual(row['status'],'pending')
        self.assertEqual(next(r for r in self.monitor.status()['items'] if r['comment_id']=='102')['status'],'baseline')
        with self.assertRaises(ValueError):
            self.monitor.queue_existing(key)
        row.update(status='done')
        self.monitor.save(row)
        with self.assertRaises(ValueError):
            self.monitor.queue_existing(key)


if __name__ == '__main__':
    unittest.main()
