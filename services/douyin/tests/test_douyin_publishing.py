import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch, Mock, MagicMock
from services.douyin.publishing import douyin
from services.douyin.publishing.store import PublicationStore


class DouyinPublishingTests(unittest.TestCase):
    def test_pending_identity_verification_blocks_fresh_send_before_browser_or_upload(self):
        cache = Path(__file__).resolve().parents[3] / 'cache'
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            root = Path(tmp) / 'douyin_publisher'; root.mkdir()
            (root / 'verification_required.json').write_text('{}', encoding='utf-8')
            with patch.object(douyin, 'service_store', return_value=Path(tmp)), \
                 patch.object(douyin, 'has_previous_publish', return_value=False), \
                 patch('playwright.sync_api.sync_playwright') as browser, \
                 patch.object(douyin.queue, 'save') as save:
                douyin.run('blocked', {'action':'publish'}, {'batch':'batch','db':'db'}, None)
            browser.assert_not_called()
            self.assertEqual(save.call_args.args[1], 'error')
            self.assertIn('本人验证尚未完成', save.call_args.kwargs['message'])
            self.assertFalse(save.call_args.kwargs['submission_uncertain'])

    def test_verification_retry_requires_same_platform_batch_and_database(self):
        context = MagicMock()
        context.__enter__.return_value.execute.return_value.fetchall.return_value = [
            {'input_json':json.dumps({'platform':'douyin','batch':'same','db':'same-db'})}]
        with patch.object(douyin.queue, 'connect', return_value=context):
            self.assertTrue(douyin.has_previous_publish('retry', {'batch':'same','db':'same-db'}))
            self.assertFalse(douyin.has_previous_publish('other', {'batch':'different','db':'same-db'}))
            self.assertFalse(douyin.has_previous_publish('other', {'batch':'same','db':'different-db'}))
            self.assertFalse(douyin.has_previous_publish('orphan', {}))

    def test_hidden_sms_prompt_does_not_block_a_completed_verification(self):
        page = Mock()
        page.get_by_text.return_value.count.return_value = 1
        page.get_by_text.return_value.first.is_visible.return_value = False
        self.assertFalse(douyin.identity_verification_visible(page))
        page.get_by_text.return_value.first.is_visible.return_value = True
        self.assertTrue(douyin.identity_verification_visible(page))

    def test_management_lookup_requires_unique_recent_match_and_cleans_listener(self):
        for matches in ([], ['1234567890123456789'], ['1234567890123456789','2234567890123456789']):
            page = Mock()
            response = Mock(url='https://creator.douyin.com/web/api/aweme/post/')
            response.json.return_value = [{'aweme_id': item, 'desc': '内容标题', 'create_time': 100} for item in matches]
            page.wait_for_timeout.side_effect = lambda _: page.on.call_args.args[1](response)
            result = douyin.management_receipt(page, {'title': '内容标题'}, 100)
            self.assertEqual(bool(result), len(matches) == 1)
            page.remove_listener.assert_called_once_with('response', page.on.call_args.args[1])

    def test_receipt_requires_success_and_real_id(self):
        for value in ({}, {'status_code': 1, 'aweme_id': '1234567890123456789'},
                      {'status_code': 0}, {'status_code': 0, 'aweme_id': 'invalid'},
                      {'status_code': False, 'aweme_id': '1234567890123456789'}):
            self.assertIsNone(douyin.receipt(value))
        result = douyin.receipt({'status_code': 0, 'data': {'aweme_id': '1234567890123456789'}})
        self.assertEqual(result['url'], 'https://www.douyin.com/note/1234567890123456789')

    def test_cards_are_ordered_local_files(self):
        with tempfile.TemporaryDirectory(dir='cache') as folder:
            root = Path(folder)
            (root / 'card-01.png').write_bytes(b'image')
            content = {'title': '标题', 'body': '正文', 'tags': ['知识'],
                       'images': [{'href': '/downloads/version/douyin/card-01.png'}]}
            result = douyin.prepare(content, root)
            self.assertEqual(result['body'], '正文\n\n#知识')
            self.assertEqual(result['files'], [str((root / 'card-01.png').resolve())])
            content['images'][0]['href'] = '/downloads/card-02.png'
            with self.assertRaises(ValueError):
                douyin.prepare(content, root)

    def test_management_does_not_claim_old_matching_title(self):
        post = {'aweme_id': '1234567890123456789', 'desc': '标题', 'create_time': 100}
        self.assertEqual(douyin.matching_posts(post, '标题', 200), set())
        self.assertEqual(douyin.matching_posts(post, '标题'), set())
        self.assertEqual(douyin.matching_posts(post, '标题', 100), {'1234567890123456789'})

    def test_finance_publication_keeps_source_attribution(self):
        with tempfile.TemporaryDirectory(dir='cache') as folder:
            root = Path(folder)
            (root / 'card-01.png').write_bytes(b'image')
            value = {'title': '标题', 'body': '作者的测算', 'theme': 'finance', 'tags': [],
                     'images': [{'href': '/downloads/card-01.png'}]}
            self.assertIn('不构成收益保证', douyin.prepare(value, root)['body'])
            self.assertEqual(value['body'], '作者的测算')

    def test_web_title_reuses_llm_cover_title_without_truncating(self):
        self.assertEqual(douyin.publication_title({'title': '长标题' * 10, 'cover': {'headline': '本地模型短标题'}}), '本地模型短标题')
        with self.assertRaises(ValueError):
            douyin.publication_title({'title': '长标题' * 10})

    def test_editor_paragraph_sentinels_are_not_content_changes(self):
        self.assertEqual(douyin.normalized_editor_text('第一段\u200b\n第二段\u200b'), douyin.normalized_editor_text('第一段\n\n第二段'))
        self.assertNotEqual(douyin.normalized_editor_text('第一段'), douyin.normalized_editor_text('第二段'))
        self.assertIn('\u200d', douyin.normalized_editor_text('👩\u200d💻'))

    def test_submission_must_contain_title_and_complete_body(self):
        media={'title':'财富自由','body':'第一段\n\n第二段 #知识'}
        valid={'item':{'common':{'text':'财富自由。第一段\n\n第二段 #知识'}}}
        self.assertTrue(douyin.require_text_payload(valid,media)['text_verified'])
        for text in ('财富自由','财富自由。第一段','财富自由。第一段第二段 #知识','财富自由。第一段\n*第二段 #知识'):
            with self.assertRaises(ValueError):
                douyin.require_text_payload({'item':{'common':{'text':text}}},media)
        with self.assertRaises(ValueError):douyin.require_text_payload({'item':{'common':{}}},media)

    def test_upload_counter_must_finish(self):
        self.assertTrue(douyin.upload_in_progress('0/5 取消上传'))
        self.assertTrue(douyin.upload_in_progress('4/5\n取消上传'))
        self.assertFalse(douyin.upload_in_progress('5/5 取消上传'))
        self.assertFalse(douyin.upload_in_progress('上传完成'))

    def test_shared_queue_marks_platform(self):
        with patch.object(douyin.time, 'time', return_value=100), patch.object(douyin.queue, 'start', return_value={'id': 'job'}) as start:
            douyin.start('publish', {'batch': 'version'})
            start.assert_called_once_with('publish', {'batch': 'version', 'platform': 'douyin', 'created_at': 100})

    def test_platform_claim_does_not_lock_xiaohongshu(self):
        with tempfile.TemporaryDirectory(dir='cache') as folder:
            store = PublicationStore(Path(folder) / 'history.sqlite3')
            with store.connect() as db:
                db.execute("INSERT INTO publication_batches VALUES ('b','h','r',0,'done',0,0)")
                for platform in ('douyin', 'xiaohongshu'):
                    db.execute("INSERT INTO publication_targets(batch_id,platform,status) VALUES ('b',?,'generated')", (platform,))
            store.claim_publish('h', 'b', 'douyin')
            with self.assertRaises(ValueError):
                store.claim_publish('h', 'b', 'douyin')
            store.claim_publish('h', 'b', 'xiaohongshu')
            with self.assertRaises(ValueError):
                store.claim_publish('h', 'b', 'wechat')


if __name__ == '__main__':
    unittest.main()
