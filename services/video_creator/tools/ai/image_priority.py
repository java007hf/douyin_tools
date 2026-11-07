"""Doubao-first image tool with an account-scoped daily-quota fallback."""
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from PIL import Image

from services.core.storage import service_store
from .comfyui_client import ComfyUIClient
from .config_store import ProviderConfigStore
from .providers import ProviderError


def china_day():
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def daily_quota_exhausted(error):
    text = str(error).lower()
    if re.search(r'710022002|访问频繁|访问频率|rate.?limit|too many requests|登录|签名|http (401|403)', text):
        return False
    return bool(re.search(r'今日|今天|当日|本日|每日|每天|明日|明天|daily|per day|tomorrow', text)
                and re.search(r'额度|配额|次数|quota|limit|credits?', text)
                and re.search(r'用完|用尽|耗尽|已达|达到|超出|上限|不足|exhaust|exceed|reached|no .{0,30}(left|remaining)', text))


class DailyQuotaState:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS daily_image_quota (account TEXT PRIMARY KEY, day TEXT NOT NULL)')

    def exhausted(self, account, day):
        with closing(sqlite3.connect(self.path, timeout=30)) as db:
            return bool(db.execute('SELECT 1 FROM daily_image_quota WHERE account=? AND day=?', (account, day)).fetchone())

    def mark(self, account, day):
        with closing(sqlite3.connect(self.path, timeout=30)) as db, db:
            db.execute('INSERT INTO daily_image_quota VALUES (?,?) ON CONFLICT(account) DO UPDATE SET day=excluded.day WHERE excluded.day>=daily_image_quota.day', (account, day))


def save_image(url, target):
    """Persist expiring provider output, verify decoding, and normalize to PNG."""
    scratch = target.with_suffix('.download')
    try:
        with requests.get(url, stream=True, timeout=(15, 180)) as response:
            response.raise_for_status()
            size = 0
            with scratch.open('wb') as output:
                for block in response.iter_content(256 * 1024):
                    size += len(block)
                    if size > 40 * 1024 * 1024:
                        raise ProviderError('生图结果超过40MB，已停止下载')
                    output.write(block)
        with Image.open(scratch) as image:
            image.load()
            if min(image.size) < 128:
                raise ProviderError('生图结果尺寸过小')
            image.convert('RGB').save(target, 'PNG')
    except requests.RequestException:
        raise ProviderError('图片下载失败；生成可能已经完成，未重复提交') from None
    finally:
        scratch.unlink(missing_ok=True)


class PriorityImageTool:
    def __init__(self, store_dir=None, *, quota=None, day=china_day):
        self.directory = Path(store_dir or service_store('video_creator'))
        self.config_path = self.directory / 'mock_doubao.json'
        self.providers = ProviderConfigStore(self.directory / 'provider_configs.json')
        self.quota = quota or DailyQuotaState(self.directory / 'image_route_state.sqlite3')
        self.day = day

    def route_config(self):
        config = self.providers.get_by_provider('mock_doubao')
        if not config or config.get('enabled') is False:
            raise ProviderError('请在后台启用豆包 Mock 生图 Provider')
        try:
            private = json.loads(self.config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise ProviderError('豆包 Mock 登录请求模板未配置') from None
        # Hash only account/session headers; never persist raw credentials in route state.
        headers = private.get('web_request', {}).get('headers') or private.get('headers') or {}
        account = hashlib.sha256(json.dumps({'provider': config['id'], 'headers': headers}, sort_keys=True).encode()).hexdigest()
        return config, private, account

    def generate(self, prompt, target, progress=lambda trace: None, *, aspect='16:9'):
        if aspect not in {'16:9', '4:3', '3:4', '9:16'}:
            raise ValueError('发布配图仅支持16:9、4:3、3:4或9:16画幅')
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        config, private, account = self.route_config()
        # Keep the submission's day: a response arriving after midnight must not block the new day.
        day = self.day()
        trace = {'status': 'running', 'provider': 'mock_doubao', 'provider_id': config['id'],
                 'model': config.get('model') or 'mock_doubao_seedream', 'day': day,
                 'started_at': time.time(), 'fallback_reason': '', 'prompt': prompt, 'aspect': aspect}
        trace_path = target.with_name(target.stem + '-trace.json')

        def report(**values):
            trace.update(values, heartbeat_at=time.time())
            trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            progress(dict(trace))

        try:
            if self.quota.exhausted(account, day):
                trace['fallback_reason'] = '豆包当天额度已用尽，使用本地生图'
            else:
                report(message='等待豆包 Mock 生图')
                try:
                    self.doubao(prompt, target, config, private, report, aspect=aspect)
                    report(status='done', message='豆包 Mock 生图完成', ended_at=time.time(), file=target.name)
                    return dict(trace)
                except ProviderError as exc:
                    if not daily_quota_exhausted(exc):
                        raise
                    self.quota.mark(account, day)
                    trace['fallback_reason'] = '豆包明确返回当天生图额度用尽，切换本地生图'
            report(provider='local', provider_id='local', model='', message=trace['fallback_reason'])
            self.local(prompt, target, report, aspect=aspect)
            report(status='done', message='本地生图完成', ended_at=time.time(), file=target.name)
            return dict(trace)
        except Exception as exc:
            # Provider adapters sanitize session failures; do not save arbitrary response objects.
            report(status='error', message='配图生成失败', error=self.safe_error(exc, private), ended_at=time.time())
            raise ProviderError(trace['error']) from None

    @staticmethod
    def safe_error(error, private):
        text = str(error)
        for group in (private.get('headers', {}), private.get('web_request', {}).get('headers', {}), private.get('query', {})):
            for value in group.values():
                if isinstance(value, str) and len(value) >= 8:
                    text = text.replace(value, '********')
        text = re.sub(r'https?://[^\s\"<>]+', '[URL]', text)
        return re.sub(r'(?i)(bearer\s+)[^\s,;]+', r'\1********', text)[:1000]

    def doubao(self, prompt, target, config, private, report, *, aspect='16:9'):
        from .doubao_web import DoubaoWebImageProvider
        from .mock_doubao import MockDoubaoImageProvider
        adapter = (DoubaoWebImageProvider if private.get('web_request') else MockDoubaoImageProvider)(self.config_path)
        diagnostics, outputs, failures = {}, [], []

        def submit_once():
            try:
                outputs.extend(adapter.generate(prompt, model=config.get('model'), aspect=aspect, count=1, diagnostics=diagnostics))
            except Exception as exc:
                failures.append(exc)

        worker = threading.Thread(target=submit_once, daemon=True)
        worker.start()
        while worker.is_alive():
            report(message='豆包 Mock 生图中', provider_progress={k: diagnostics[k] for k in ('protocol', 'http_status', 'parsed_events', 'reply_end', 'event_types', 'response_text', 'failure_kind') if k in diagnostics})
            worker.join(2)
        report(provider_progress={k: diagnostics[k] for k in ('protocol', 'http_status', 'parsed_events', 'reply_end', 'event_types', 'response_text', 'failure_kind') if k in diagnostics})
        if failures:
            raise failures[0]
        if not outputs:
            raise ProviderError('豆包未返回可下载图片；未重新提交')
        report(message='正在保存豆包图片')
        save_image(outputs[0], target)
        from .doubao_image_cleanup import prepare_publication_image
        cleanup=prepare_publication_image(target)
        report(image_cleanup=cleanup,message='豆包原图已保留，排版用图已裁除底部5%水印带')

    def local(self, prompt, target, report, *, aspect='16:9'):
        from services.core.understanding_queue import shared_slot
        from services.douyin.video_understanding import release_understanding_model
        from services.video_creator.workflow.generation import flux_image, qwen_image
        client = ComfyUIClient(os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188'))
        # Join understanding admission before unloading its model and using local GPU memory.
        with shared_slot(platform='发布配图/本地生图', progress=lambda message: report(message=message)):
            llm = self.providers.get_by_provider('douyin_understanding') or {}
            release_understanding_model(llm, lambda message: report(message=message))
            info = client.object_info()
            models = info.get('UNETLoader', {}).get('input', {}).get('required', {}).get('unet_name', [[]])[0]
            requested = os.environ.get('PUBLICATION_LOCAL_IMAGE_MODEL')
            supported = ['flux1-krea-dev_fp8_scaled.safetensors', 'qwen_image_fp8_e4m3fn.safetensors']
            model = requested or next((m for m in supported if m in models), '')
            if model not in supported or model not in models:
                raise ProviderError('本地未安装可用的 Flux / Qwen 生图模型，请检查 ComfyUI')
            seed = uuid.uuid4().int % 2**31
            width, height = {'4:3': (1152, 864), '3:4': (896, 1216), '9:16': (768, 1344)}.get(aspect, (1344, 768))
            graph = flux_image(prompt, '', width, height, 1, seed) if model == supported[0] else qwen_image(prompt, width, height, 1, seed)
            if model == supported[0]:
                # Flux 1 uses 16-channel latents; EmptyFlux2LatentImage is for Flux 2.
                graph['6']['class_type'] = 'EmptySD3LatentImage'
            graph['9' if model == supported[0] else '10']['inputs']['filename_prefix'] = 'douyin_publications/image'
            target.with_name(target.stem + '-workflow.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
            client.validate_graph(graph)
            report(model=model, seed=seed, message='本地工作流验证通过，正在提交')
            client_id = 'publication_' + uuid.uuid4().hex
            report(client_id=client_id, message='正在提交本地生图任务')
            prompt_id = client.queue(graph, client_id=client_id)
            report(prompt_id=prompt_id, message='本地生图任务已提交')
            try:
                result = client.wait(prompt_id, lambda percent, message: report(percent=percent, message=message), timeout=1800)
                images = [image for node in result.get('outputs', {}).values() for image in node.get('images', []) if image.get('type', 'output') == 'output']
                if not images:
                    raise ProviderError('本地生图任务完成但没有输出图片')
                save_image(client.view_url(images[0]), target)
            except Exception:
                # Never leave a timed-out or invalid child running without its parent.
                try:
                    client.cancel(prompt_id)
                except Exception:
                    report(cancellation_error='无法确认本地子任务取消，请按 prompt_id 检查 ComfyUI')
                raise
            finally:
                report(message='正在释放本地生图模型内存')
                try:
                    client.release_models()
                except Exception as exc:
                    report(release_error=str(exc)[:500])
