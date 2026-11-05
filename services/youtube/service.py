"""YouTube workbench HTTP transport; processing uses existing understanding tools."""
import argparse
import http.server
import json
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit, unquote, parse_qs

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from services.core.storage import service_store
from services.youtube.downloader import normalize_url, download_video
from services.douyin.service import WebJobStore, start_web_job, web_json_response, web_text_response, read_json_request, file_result, understanding_detail_html
from services.douyin.understanding_history import UnderstandingHistory, render_report
from services.youtube.task_queue import UnderstandingQueue
from services.core.understanding_queue import reserve, shared_slot, annotate, discard, snapshot as shared_snapshot


def understanding_config():
    from services.douyin.video_understanding import validate_config
    from services.video_creator.tools.ai.config_store import ProviderConfigStore
    return validate_config(ProviderConfigStore(service_store('video_creator') / 'provider_configs.json').get_by_provider('douyin_understanding'))


def make_server(host, port, directory):
    directory = Path(directory).resolve()
    downloads = directory / 'web_downloads'
    downloads.mkdir(parents=True, exist_ok=True)
    jobs = WebJobStore(directory / 'web_jobs')
    aliases_file = directory / 'legacy_job_aliases.json'
    aliases = json.loads(aliases_file.read_text(encoding='utf-8')) if aliases_file.exists() else {}
    history = UnderstandingHistory(directory / 'understanding_history.sqlite3', downloads)
    from services.douyin.publishing.engine import PublicationEngine
    publications = PublicationEngine(history)
    publications.recover()
    for trace_file in (downloads / 'understanding').glob('*/task.json'):
        try:
            trace = json.loads(trace_file.read_text(encoding='utf-8'))
            if trace.get('status') not in {'done', 'error'}:
                trace.update(status='error', error='服务重启，任务已中断')
                for node in trace.get('nodes', []):
                    if node.get('status') == 'running':
                        node.update(status='failed', error=trace['error'])
                trace_file.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, ValueError):
            pass
    history.interrupt_manual_tasks()
    history.backfill()

    def execute_understanding(identifier, url, progress):
        from services.douyin.video_understanding import understand_work
        task_root = downloads / 'understanding' / identifier
        def tracked(message, partial_result=None):
            status = 'pending' if message.startswith('等待共享视频理解队列') else 'running'
            history.update_manual(task_root, url, status, message)
            progress(message, partial_result)
        try:
            with shared_slot(identifier, 'YouTube', tracked):
                tracked('正在开始视频理解')
                result = understand_work(url, task_root, download_video, understanding_config(), tracked)
            return history.save(task_root, {**result, 'record_source': 'manual', 'reply_status': 'done', 'analysis_ready': True, 'platform': 'youtube'})
        except Exception as exc:
            history.update_manual(task_root, url, 'error', '失败', str(exc))
            raise

    queue = UnderstandingQueue(directory / 'understanding_queue.sqlite3', execute_understanding)
    for item in queue.snapshot()['items']:
        history.update_manual(downloads / 'understanding' / item['id'], item['source_url'], 'pending', '等待视频理解队列')
        reserve(item['id'], 'YouTube')

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(downloads), **kwargs)
        def log_message(self, *args): pass
        def do_GET(self):
            path = urlsplit(self.path).path
            path = path.replace('/api/understanding-history', '/api/history', 1)
            if path == '/api/publications/capabilities':
                return web_json_response(self, 200, publications.capabilities())
            if path == '/assets/publishing.js':
                asset = ROOT / 'services/douyin/publishing/ui.js'
                return web_text_response(self, 200, asset.read_text(encoding='utf-8'), 'text/javascript; charset=utf-8')
            if path == '/':
                return web_text_response(self, 200, (Path(__file__).with_name('index.html')).read_text(encoding='utf-8'))
            if path == '/assets/app.js':
                return web_text_response(self, 200, Path(__file__).with_name('app.js').read_text(encoding='utf-8'), 'text/javascript; charset=utf-8')
            if path.startswith('/understanding/'):
                return web_text_response(self, 200, understanding_detail_html())
            if path == '/api/history':
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    limit = min(100, max(1, int(query.get('limit', ['30'])[0])))
                    offset = max(0, int(query.get('offset', ['0'])[0]))
                except ValueError:
                    return web_json_response(self, 400, {'error': '历史分页参数无效'})
                data = history.list(limit=limit, offset=offset)
                state = shared_snapshot()
                for item in data['items']:
                    annotate(item, item['id'], state)
                data['queue'] = state
                return web_json_response(self, 200, data)
            if path == '/api/queue':
                return web_json_response(self, 200, shared_snapshot())
            if path.startswith('/api/jobs/'):
                identifier = path.rsplit('/', 1)[-1]
                job = queue.get(aliases.get(identifier, identifier)) or jobs.get(identifier)
                if job and job['status'] in {'pending', 'running'}:
                    shared = annotate({}, job['id'])
                    if shared:
                        job.update(status='pending', message=shared['progress'], queue_position=shared['queue_position'])
                return web_json_response(self, 200 if job else 404, job or {'error': '任务不存在'})
            if path.startswith('/api/history/'):
                identifier = path.split('/')[3]
                result = history.get(identifier)
                if not result:
                    return web_json_response(self, 404, {'error': '记录不存在'})
                job = queue.get(identifier)
                if job and job['status'] in {'pending', 'running'}:
                    result.update(reply_status=job['status'], progress=job['message'], queue_position=job['queue_position'])
                    annotate(result, identifier)
                if path.endswith('/report') and result.get('analysis_ready'):
                    task_root = downloads / result['artifact_directory']
                    trace = json.loads((task_root / 'task.json').read_text(encoding='utf-8'))
                    return web_text_response(self, 200, render_report(task_root, result, trace, '../../../downloads/' + result['artifact_directory'] + '/'))
                return web_json_response(self, 200, result)
            if path.startswith('/downloads/'):
                target = (downloads / unquote(path[len('/downloads/'):])).resolve()
                if not target.is_relative_to(downloads) or not target.is_file():
                    return self.send_error(404)
                self.path = '/' + path[len('/downloads/'):]
                return super().do_GET()
            self.send_error(404)
        def do_DELETE(self):
            path = urlsplit(self.path).path
            if not path.startswith('/api/history/'):
                return self.send_error(404)
            identifier = path.rsplit('/', 1)[-1]
            job = queue.get(identifier)
            if job and job['status'] in {'pending', 'running'}:
                return web_json_response(self, 409, {'error': '排队和处理中的任务暂不能删除历史'})
            try:
                deleted = history.delete(identifier)
            except ValueError as exc:
                return web_json_response(self, 409, {'error': str(exc)})
            return web_json_response(self, 200 if deleted else 404, {'deleted': deleted})
        def do_POST(self):
            path = urlsplit(self.path).path
            try:
                if path in ('/api/publications/xiaohongshu/login','/api/publications/xiaohongshu/status','/api/publications/douyin/login','/api/publications/douyin/status'):
                    from services.douyin.publishing import xiaohongshu, douyin
                    adapter = douyin if "/douyin/" in path else xiaohongshu
                    data = read_json_request(self)
                    result = adapter.start('login') if path.endswith('/login') else adapter.status(data.get('job_id'))
                    return web_json_response(self, 202 if path.endswith('/login') else 200, result)
                send_match = re.fullmatch(r'/api/(?:understanding-history|history)/([0-9a-f]{32})/publications/([0-9a-f]{32})/(send|preview|verify|relayout)', path)
                if send_match:
                    data = read_json_request(self)
                    if send_match[3] == 'relayout':
                        result = publications.relayout(send_match[1], send_match[2], platform=data.get('platform', 'douyin'), request_id=data.get('request_id'))
                        web_json_response(self, 200, result)
                        return
                    result = publications.verify_send(send_match[1],send_match[2],platform=data.get("platform", "xiaohongshu")) if send_match[3]=='verify' else publications.send(send_match[1],send_match[2],preview=send_match[3]=='preview',platform=data.get('platform', 'xiaohongshu'))
                    return web_json_response(self, 202, result)
                publication_match = re.fullmatch(r'/api/(?:understanding-history|history)/([0-9a-f]{32})/publications', path)
                if publication_match:
                    data = read_json_request(self)
                    result = publications.submit(publication_match[1], data.get('platforms'), data.get('auto_publish', False), data.get('request_id'))
                    return web_json_response(self, 202, result)
                if path not in {'/api/download', '/api/understand'}:
                    return self.send_error(404)
                data = read_json_request(self)
                url = normalize_url(data.get('url', ''))
                if path == '/api/understand':
                    understanding_config()
                    identifier = uuid.uuid4().hex
                    task_root = downloads / 'understanding' / identifier
                    history.update_manual(task_root, url, 'pending', '等待视频理解')
                    try:
                        reserve(identifier, 'YouTube')
                        job = queue.enqueue(identifier, url)
                    except Exception as exc:
                        discard(identifier)
                        history.update_manual(task_root, url, 'error', '入队失败', str(exc))
                        raise
                    return web_json_response(self, 202, {'jobId': identifier, 'status': job['status'], 'queue_position': job['queue_position']})
                task_root = downloads / 'videos' / uuid.uuid4().hex
                def run(progress):
                    return {'files': [file_result(p, downloads) for p in download_video(url, task_root, progress)]}
                job_id = start_web_job(jobs, '正在创建任务', run)
                return web_json_response(self, 202, {'jobId': job_id})
            except (ValueError, TypeError) as exc:
                return web_json_response(self, 400, {'error': str(exc)})
            except Exception:
                return web_json_response(self, 500, {'error': '任务创建失败，请检查视频理解配置'})
    class Server(http.server.ThreadingHTTPServer):
        def server_close(self):
            queue.close(wait=True)
            super().server_close()
    server = Server((host, port), Handler)
    server.understanding_queue = queue
    queue.start()
    return server


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8104)
    parser.add_argument('--store-dir', type=Path, default=service_store('youtube'))
    args = parser.parse_args()
    with make_server(args.host, args.port, args.store_dir) as server:
        server.serve_forever()

if __name__ == '__main__':
    main()
