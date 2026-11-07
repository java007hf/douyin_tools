import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
from services.douyin.publishing.xiaohongshu import prepare, receipt, publish_control, matching_notes
from services.douyin.understanding_history import UnderstandingHistory


class PublishingTests(unittest.TestCase):
    def test_loading_editor_and_hidden_login_copy_do_not_mean_login_expired(self):
        from services.douyin.publishing.xiaohongshu import login_prompt_visible
        page = MagicMock(url='https://creator.douyin.com/creator-micro/content/upload')
        page.get_by_text.return_value.count.return_value = 0
        self.assertFalse(login_prompt_visible(page))
        page.get_by_text.return_value.count.return_value = 1
        page.get_by_text.return_value.nth.return_value.is_visible.return_value = False
        self.assertFalse(login_prompt_visible(page))
        page.get_by_text.return_value.nth.return_value.is_visible.return_value = True
        self.assertTrue(login_prompt_visible(page))
        page.url = 'https://creator.xiaohongshu.com/login'
        self.assertTrue(login_prompt_visible(page))

    def test_reconciliation_requires_exact_title_and_valid_note_id(self):
        data={'data':{'notes':[{'title':'当前笔记','note_id':'a'*24},
            {'title':'当前笔记旧版','note_id':'b'*24}, {'title':'当前笔记','id':'unsafe'}]}}
        self.assertEqual(matching_notes(data,'当前笔记'),{'a'*24})

    def test_custom_publish_widget_is_not_an_aria_button(self):
        page=MagicMock()
        page.locator.return_value.count.return_value=1
        widget=page.locator.return_value.nth.return_value
        widget.is_visible.return_value=True
        widget.get_attribute.return_value='false'
        control,custom=publish_control(page)
        self.assertIs(control,widget)
        self.assertTrue(custom)
        page.get_by_role.assert_not_called()

    def test_disabled_widget_never_submits(self):
        page=MagicMock()
        page.locator.return_value.count.return_value=1
        widget=page.locator.return_value.nth.return_value
        widget.is_visible.return_value=True
        widget.get_attribute.return_value='true'
        with self.assertRaises(ValueError):publish_control(page)
        widget.click.assert_not_called()

    def test_receipt_requires_success_and_real_identifier(self):
        self.assertIsNone(receipt({'success':False,'data':{'id':'a'*24}}))
        self.assertIsNone(receipt({'success':True,'data':{}}))
        self.assertIsNone(receipt({'success':True,'data':{'id':'javascript:alert(1)'}}))
        self.assertEqual(receipt({'success':True,'data':{'note_id':'a'*24}})['note_id'],'a'*24)

    def test_uploads_only_ordered_generated_cards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'card-01.png').write_bytes(b'photo')
            value={'title':'标题','body':'内容','tags':['话题'],'images':[{'href':'/downloads/card-01.png'}]}
            self.assertEqual(prepare(value,root)['files'],[str((root/'card-01.png').resolve())])
            value['images'][0]['href']='/downloads/illustration-01.png'
            with self.assertRaises(ValueError):prepare(value,root)

    def test_never_silently_truncate_published_copy(self):
        with self.assertRaises(ValueError):prepare({'title':'长'*21,'body':'内容'},Path('.'))
        with self.assertRaises(ValueError):prepare({'title':'标题','body':'长'*1001},Path('.'))

    def test_atomic_send_claim_and_history_ownership(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            history=UnderstandingHistory(path/'history.sqlite3',path/'downloads')
            with history.publications.connect() as db:
                db.execute("INSERT INTO publication_batches VALUES (?,?,?,?,?,?,?)",('b'*32,'h'*32,'key',0,'done',1,1))
                db.execute("INSERT INTO publication_targets(batch_id,platform,status) VALUES (?,?,?)",('b'*32,'xiaohongshu','generated'))
            store=history.publications
            with self.assertRaises(ValueError):store.claim_publish('wrong','b'*32)
            store.claim_publish('h'*32,'b'*32)
            with self.assertRaises(ValueError):store.claim_publish('h'*32,'b'*32)
            store.set_publish('b'*32,'xiaohongshu','unknown',{'message':'receipt lost'})
            with self.assertRaises(ValueError):store.claim_publish('h'*32,'b'*32)


class QueueTests(unittest.TestCase):
    def setUp(self):
        import shutil
        self.directory = Path('cache/publishing-queue-tests') / uuid.uuid4().hex
        self.directory.mkdir(parents=True)
        self.patch = patch('services.douyin.publishing.xiaohongshu.root', return_value=self.directory)
        self.patch.start()

    def tearDown(self):
        import shutil
        self.patch.stop()
        shutil.rmtree(self.directory)

    def insert(self, identifier, state='queued', pid=0, updated=1):
        from services.douyin.publishing import xiaohongshu as x
        with x.connect() as db:
            db.execute('INSERT INTO jobs(id,action,status,pid,input_json,updated) VALUES (?,?,?,?,?,?)',
                       (identifier, 'publish', state, pid, '{}', updated))

    def test_fifo_and_browser_lock_survives_terminal_status_until_cleanup(self):
        from services.douyin.publishing import xiaohongshu as x
        self.insert('first'); self.insert('second')
        self.assertEqual(x.status('second')['queue_position'], 2)
        self.assertFalse(x.acquire('second'))
        self.assertTrue(x.acquire('first'))
        self.assertFalse(x.acquire('second'))
        x.save('first', 'done')
        self.assertFalse(x.acquire('second'))  # Browser still closing.
        x.release('first')
        self.assertTrue(x.acquire('second'))
        x.release('second')

    def test_dead_submitting_owner_is_unknown_and_never_resubmitted(self):
        from services.douyin.publishing import xiaohongshu as x
        self.insert('old', 'submitting', 99999999)
        self.insert('next')
        with x.connect() as db:
            db.execute('INSERT INTO browser_lock VALUES (1,?,?)', ('old', 99999999))
        with patch.object(x, 'alive', return_value=False):
            self.assertTrue(x.acquire('next'))
        self.assertEqual(x.status('old')['status'], 'unknown')
        x.release('next')

    def test_concurrent_submissions_all_queue_instead_of_rejecting_busy_browser(self):
        from concurrent.futures import ThreadPoolExecutor
        from services.douyin.publishing import xiaohongshu as x
        self.insert('active', 'running', 12345)
        with patch.object(x, 'spawn'), patch.object(x, 'recover_queue'):
            with ThreadPoolExecutor(max_workers=5) as pool:
                jobs = list(pool.map(lambda _: x.start('publish', {'batch': uuid.uuid4().hex}), range(5)))
        self.assertEqual(len({j['id'] for j in jobs}), 5)
        self.assertTrue(all(j['status']=='queued' for j in jobs))
        self.assertEqual(sorted(x.status(j['id'])['queue_position'] for j in jobs), [1,2,3,4,5])

    def test_queued_jobs_recover_but_live_workers_and_unknown_jobs_do_not(self):
        from services.douyin.publishing import xiaohongshu as x
        self.insert('orphan', pid=99999999)
        self.insert('live', pid=12345)
        self.insert('ambiguous', state='unknown')
        with patch.object(x, 'alive', side_effect=lambda pid: pid in (12345, os.getpid())), patch.object(x, 'spawn') as spawn:
            x.recover_queue()
            spawn.assert_called_once_with('orphan')
            x.recover_queue()  # Reservation prevents a second service from spawning it again.
            spawn.assert_called_once()
        self.assertEqual(x.status('orphan')['status'], 'queued')

    def test_separate_processes_execute_fifo_without_browser_overlap(self):
        import subprocess
        import sys
        from services.douyin.publishing import xiaohongshu as x
        self.insert('first'); self.insert('second')
        script = r"""
import sys,time,json
from pathlib import Path
from services.douyin.publishing import xiaohongshu as x
x.root=lambda: Path(sys.argv[1])
def simulated_run(identifier):
    with open(x.root()/'events.txt','a') as f:f.write(identifier+' start\n')
    time.sleep(.2)
    x.save(identifier,'done')
    time.sleep(.2)
    with open(x.root()/'events.txt','a') as f:f.write(identifier+' close\n')
x.run=simulated_run
x.worker(sys.argv[2])
"""
        processes = [subprocess.Popen([sys.executable, '-B', '-c', script, str(self.directory.resolve()), name],
                      stdout=subprocess.PIPE, stderr=subprocess.PIPE) for name in ('second','first')]
        try:
            for process in processes:
                _, error = process.communicate(timeout=20)
                self.assertEqual(process.returncode, 0, error.decode(errors='replace'))
        finally:
            for process in processes:
                if process.poll() is None:
                    process.kill(); process.communicate()
        self.assertEqual((self.directory/'events.txt').read_text().splitlines(),
                         ['first start','first close','second start','second close'])

    def test_login_window_remains_open_until_closed(self):
        from services.douyin.publishing import xiaohongshu as x
        page = MagicMock()
        page.is_closed.side_effect = [False, False, True]
        x.keep_login_window(page, 'login')
        self.assertEqual(page.wait_for_timeout.call_count, 2)

    def test_login_window_yields_immediately_to_queued_publish(self):
        from services.douyin.publishing import xiaohongshu as x
        self.insert('publish')
        page = MagicMock()
        page.is_closed.return_value = False
        x.keep_login_window(page, 'login')
        page.wait_for_timeout.assert_not_called()

    def test_manual_login_window_close_during_wait_is_successful(self):
        from services.douyin.publishing import xiaohongshu as x
        page = MagicMock()
        page.is_closed.side_effect = [False, True]
        page.wait_for_timeout.side_effect = RuntimeError('Target closed')
        x.keep_login_window(page, 'login')

    def test_worker_releases_browser_after_exception(self):
        from services.douyin.publishing import xiaohongshu as x
        self.insert('broken')
        with patch.object(x, 'run', side_effect=RuntimeError('failure')):
            x.worker('broken')
        self.assertEqual(x.status('broken')['status'], 'error')
        with x.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM browser_lock').fetchone()[0], 0)


if __name__=='__main__':unittest.main()
