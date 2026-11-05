import json
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.request import urlopen

from playwright.sync_api import sync_playwright
from services.youtube.service import make_server


class YouTubeUITests(unittest.TestCase):
    def test_continuous_submission_refresh_and_history_detail(self):
        release = threading.Event()
        calls = []
        def understand(url, root, download, config, progress):
            calls.append(url)
            progress('测试任务处理中')
            if len(calls) == 1:
                release.wait(10)
                raise RuntimeError('测试 Provider 失败')
            root.mkdir(parents=True)
            now = time.time()
            (root / 'task.json').write_text(json.dumps({'status':'done', 'nodes':[{'name':'test', 'status':'success', 'started_at':now, 'ended_at':now}], 'artifacts':{}}))
            return {'title':'测试理解结果', 'summary':'测试摘要', 'format':'口播', 'topic':'测试',
                    'source_url':url, 'duration_seconds':1, 'frame_count':0, 'model':'mock',
                    'key_points':[], 'timeline':[], 'limitations':[], 'transcript':[]}
        with tempfile.TemporaryDirectory(dir='cache') as directory, \
             patch('services.youtube.service.understanding_config', return_value={'model':'mock'}), \
             patch('services.douyin.video_understanding.understand_work', side_effect=understand):
            server = make_server('127.0.0.1', 0, directory)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport={'width':1280, 'height':900})
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.goto(base)
                    self.assertEqual(page.locator('nav [data-mode]').count(), 2)
                    page.locator('[data-mode=understand]').click()
                    self.assertTrue(page.locator('#historyBtn').is_visible())
                    for video_id in ['8yImjbZcsCo', 'abcdefghijk']:
                        page.locator('#url').fill('https://youtu.be/' + video_id)
                        page.locator('#start').click()
                        page.wait_for_function("!document.querySelector('#start').disabled && !document.querySelector('#url').value")
                    self.assertEqual(len(calls), 1)
                    page.wait_for_function("document.querySelectorAll('.history-row').length===2")
                    self.assertIn('排队第 1 位', page.locator('#history').inner_text())
                    self.assertIn('队列等待 1 条', page.locator('#queueStatus').inner_text())
                    page.reload()
                    page.locator('#history .history-row').first.wait_for()
                    self.assertTrue(page.locator('#historyBtn').is_visible())
                    self.assertTrue(page.locator('#start').is_enabled())
                    page.set_viewport_size({'width':390, 'height':844})
                    self.assertTrue(page.evaluate('document.documentElement.scrollWidth<=innerWidth'))
                    release.set()
                    deadline = time.monotonic() + 8
                    while time.monotonic() < deadline:
                        state = json.load(urlopen(base + '/api/queue'))
                        if state['active'] == state['pending'] == 0:
                            break
                        time.sleep(.03)
                    self.assertEqual(len(calls), 2)
                    data = json.load(urlopen(base + '/api/history'))
                    self.assertEqual({x['reply_status'] for x in data['items']}, {'done','error'})
                    done = next(x for x in data['items'] if x['reply_status'] == 'done')
                    page.goto(base + '/understanding/' + done['id'])
                    page.wait_for_function("document.querySelector('#understandResult').hidden===false")
                    self.assertIn('测试摘要', page.locator('#understandResult').inner_text())
                    self.assertEqual(errors, [])
                    browser.close()
            finally:
                release.set()
                server.shutdown()
                server.server_close()
                thread.join()
