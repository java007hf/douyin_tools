import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from unittest.mock import patch
from services.youtube.downloader import normalize_url
from services.youtube.service import make_server

class YouTubeTests(unittest.TestCase):
    def test_single_video_urls(self):
        for url in ['https://youtu.be/8yImjbZcsCo?t=4', 'https://www.youtube.com/shorts/8yImjbZcsCo', 'https://youtube.com/live/8yImjbZcsCo', 'https://www.youtube.com/watch?v=8yImjbZcsCo&list=abc']:
            self.assertEqual(normalize_url(url), 'https://www.youtube.com/watch?v=8yImjbZcsCo')
    def test_reject_unrelated_urls(self):
        for url in ['https://youtube.com.evil.test/watch?v=8yImjbZcsCo', 'https://youtube.com/playlist?list=x', 'https://youtube.com/@someone', 'file:///etc/passwd', 'https://youtube.com/watch?v=bad', 'https://youtube.com:99/watch?v=8yImjbZcsCo']:
            with self.assertRaises(ValueError): normalize_url(url)
    def test_understand_rejects_missing_model_config(self):
        with tempfile.TemporaryDirectory(dir='cache') as directory:
            server = make_server('127.0.0.1', 0, directory)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with patch('services.video_creator.tools.ai.config_store.ProviderConfigStore.get_by_provider', return_value=None):
                    request = Request('http://127.0.0.1:'+str(server.server_port)+'/api/understand', json.dumps({'url':'https://youtu.be/8yImjbZcsCo'}).encode(), {'Content-Type':'application/json'})
                    with self.assertRaises(HTTPError) as failure:
                        urlopen(request)
                    self.assertEqual(failure.exception.code, 400)
                    self.assertEqual(list((Path(directory)/'web_jobs').glob('*.json')), [])
            finally:
                server.shutdown()
                server.server_close()
                thread.join()

    def test_restart_reconciles_trace_and_job(self):
        from services.douyin.service import WebJobStore
        with tempfile.TemporaryDirectory(dir='cache') as directory:
            root = Path(directory)
            trace_file = root / 'web_downloads/understanding/test/task.json'
            trace_file.parent.mkdir(parents=True)
            trace_file.write_text(json.dumps({'status': 'running', 'nodes': [{'name':'transcribe','status':'running'}]}))
            jobs = WebJobStore(root / 'web_jobs')
            identifier = jobs.create('working')
            server = make_server('127.0.0.1', 0, root)
            try:
                trace = json.loads(trace_file.read_text(encoding='utf-8'))
                self.assertEqual(trace['status'], 'error')
                self.assertEqual(trace['nodes'][0]['status'], 'failed')
                self.assertEqual(WebJobStore(root / 'web_jobs').get(identifier)['status'], 'error')
            finally:
                server.server_close()

    def test_http_download_and_restart(self):
        with tempfile.TemporaryDirectory(dir='cache') as directory:
            def download(url, target, progress):
                target.mkdir(parents=True); p=target/'test.mp4';p.write_bytes(b'test');progress('downloaded');return [p]
            server=make_server('127.0.0.1',0,directory)
            thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
            base='http://127.0.0.1:'+str(server.server_port)
            try:
                with patch('services.youtube.service.download_video',download):
                    request=Request(base+'/api/download',json.dumps({'url':'https://youtu.be/8yImjbZcsCo'}).encode(),{'Content-Type':'application/json'})
                    job=json.load(urlopen(request))['jobId']
                    import time
                    for _ in range(50):
                        state=json.load(urlopen(base+'/api/jobs/'+job))
                        if state['status'] in ('done','error'):break
                        time.sleep(.02)
                    self.assertEqual(state['status'],'done')
                    self.assertEqual(urlopen(base+state['result']['files'][0]['href']).read(),b'test')
                self.assertIn('YouTube'.encode(),urlopen(base+'/').read())
                self.assertEqual(json.load(urlopen(base+'/api/history'))['total'],0)
                with self.assertRaises(HTTPError):urlopen(base+'/downloads/%2e%2e/%2e%2e/README.md')
            finally:
                server.shutdown();server.server_close();thread.join()

if __name__=='__main__': unittest.main()
