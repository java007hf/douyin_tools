"""Deterministic content preparation and explicit platform publication."""
import json
import os
import re
import shutil
import threading
import time
import uuid
from copy import deepcopy
from urllib.parse import quote

from .content import generate_content
from .images import prepare_images


class PublicationEngine:
    def __init__(self, history, provider_factory=None, image_factory=None):
        self.history = history
        self.store = history.publications
        self.provider_factory = provider_factory or self.default_provider
        self.image_factory = image_factory or self.default_images

    @staticmethod
    def capabilities():
        return {'version': 2, 'douyin': {'music_required': True, 'text_validation': True,
                                         'relayout': True, 'image_aspect': '9:16'}}

    @staticmethod
    def default_images():
        from services.video_creator.tools.ai.stock_images import StockFirstImageTool
        return StockFirstImageTool()

    def recover(self, client=None):
        """Reconcile this service's local children before marking parents interrupted."""
        for target in self.store.active_targets():
            content = target['content']
            for index, trace in enumerate(content.get('image_traces', [])):
                if trace.get('status') not in {'pending', 'running'}:
                    continue
                if trace.get('provider') == 'local':
                    try:
                        if client is None:
                            from services.video_creator.tools.ai.comfyui_client import ComfyUIClient
                            client = ComfyUIClient(os.environ.get('COMFYUI_URL', 'http://127.0.0.1:8188'))
                        ids = {trace['prompt_id']} if trace.get('prompt_id') else set()
                        if trace.get('client_id'):
                            queue = client.queue_state()
                            for row in [*queue.get('queue_pending', []), *queue.get('queue_running', [])]:
                                if len(row) > 3 and isinstance(row[3], dict) and row[3].get('client_id') == trace['client_id']:
                                    ids.add(str(row[1]))
                        for prompt_id in ids:
                            client.cancel(prompt_id)
                        trace['recovery'] = '已核对并停止匹配的本地子任务；父任务中断，可重新生成'
                    except Exception:
                        trace['recovery'] = '无法确认本地子任务已停止，请按 prompt_id / client_id 检查 ComfyUI'
                else:
                    trace['recovery'] = '豆包原请求可能已提交，未自动重新发送'
                trace['status'] = 'interrupted'
                path = self.history.download_root / 'publications' / target['history_id'] / target['batch_id'] / target['platform'] / f'illustration-{index+1:02d}-trace.json'
                if path.is_file():
                    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding='utf-8')
            self.store.update(target['batch_id'], target['platform'], status='error', progress='服务重启，内容生成已中断',
                              error='服务重启，内容生成已中断，可重新生成', content=content)
        self.store.interrupt()
        from .xiaohongshu import recover_queue
        recover_queue()

    @staticmethod
    def default_provider():
        from services.core.storage import service_store
        from services.douyin.video_understanding import UnderstandingProvider
        from services.video_creator.tools.ai.config_store import ProviderConfigStore
        config = ProviderConfigStore(service_store('video_creator') / 'provider_configs.json').get_by_provider('douyin_understanding')
        return UnderstandingProvider(config)

    def submit(self, history_id, platforms, auto_publish, request_id):
        source = self.history.get(history_id)
        if not source:
            raise ValueError('理解历史不存在')
        if source.get('analysis_ready') is False or not source.get('summary'):
            raise ValueError('请等待内容理解成功后再生成发布内容')
        # Validate local configuration before creating a durable task, without inference.
        provider = self.provider_factory()
        batch, created = self.store.create(history_id, platforms, auto_publish, request_id)
        if created:
            threading.Thread(target=self.run, args=(history_id, batch, list(dict.fromkeys(platforms)), source, provider), daemon=True).start()
        return {'batch_id': batch, 'created': created, 'connection_status': 'not_connected'}

    def send(self, history_id, batch, *, preview=False, platform="xiaohongshu"):
        from . import xiaohongshu, douyin
        adapter = {"xiaohongshu": xiaohongshu, "douyin": douyin}.get(platform)
        if adapter is None:
            raise ValueError("该平台尚未接入发布")
        content = self.store.claim_publish(history_id, batch, platform)
        directory = self.history.download_root / 'publications' / history_id / batch / platform
        try:
            adapter.prepare(content, directory)
            result = adapter.start('preview' if preview else 'publish', {
                'db': str(self.store.path.resolve()), 'batch': batch,
                'directory': str(directory.resolve()), 'content': content})
            self.store.set_publish(batch, platform, 'queued', {'job_id':result['id'], 'message':result.get('message', '等待发布队列')})
            return result
        except Exception:
            self.store.set_publish(batch, platform, 'failed', {'message':'未启动发送，请检查账号任务与素材'})
            raise

    def verify_send(self, history_id, batch, platform="xiaohongshu"):
        from . import xiaohongshu, douyin
        adapter = {"xiaohongshu": xiaohongshu, "douyin": douyin}.get(platform)
        if adapter is None:
            raise ValueError("该平台尚未接入发布")
        version = next((b for b in self.store.list(history_id) if b['id']==batch),None)
        target = next((t for t in version['targets'] if t['platform']==platform),None) if version else None
        if not target or target['publish_status']!='unknown':
            raise ValueError('仅对发送结果待核实的版本执行核对')
        return adapter.start('verify',{'db':str(self.store.path.resolve()),'batch':batch,'content':target['content'],
            'original_job_id':target.get('publication', {}).get('job_id')})

    def relayout(self, history_id, batch, *, platform='douyin', request_id=None):
        """Create an unpublished layout version from existing LLM text and originals."""
        if platform != 'douyin':
            raise ValueError('当前仅支持抖音竖版重新排版')
        version = next((v for v in self.store.list(history_id) if v['id'] == batch), None)
        target = next((t for t in version['targets'] if t['platform'] == platform), None) if version else None
        if not target or target['status'] != 'generated':
            raise ValueError('请先生成完整的平台内容')
        content = deepcopy(target['content'])
        originals = content.get('illustration_files', [])
        if len(originals) != len(content.get('cards', [])) or len(content.get('images', [])) != len(originals):
            raise ValueError('旧版本原图不完整，请重新生成内容')
        identifier, created = self.store.create(history_id, [platform], False, request_id or 'layout-' + uuid.uuid4().hex)
        if not created:
            existing = next(v for v in self.store.list(history_id) if v['id'] == identifier)
            derivation = existing['targets'][0]['content'].get('derivation', {})
            if derivation.get('source_batch_id') != batch or derivation.get('operation') != 'relayout':
                raise ValueError('请求标识已用于其他来源或操作，请重新提交')
            return {'batch_id': identifier, 'created': False}
        source = self.history.download_root / 'publications' / history_id / batch / platform
        directory = self.history.download_root / 'publications' / history_id / identifier / platform
        try:
            directory.mkdir(parents=True, exist_ok=True)
            self.store.update(identifier, platform, status='running', progress='正在使用原文与原图重新排版，不调用LLM')
            for index, name in enumerate(originals):
                if name != f'illustration-{index+1:02d}.png' or not (source / name).is_file():
                    raise ValueError('旧版本原图缺失或文件名无效')
                shutil.copyfile(source / name, directory / name)
            if (source / 'source.json').is_file():
                shutil.copyfile(source / 'source.json', directory / 'source.json')
            else:
                record = self.history.get(history_id)
                evidence = {k: record.get(k) for k in ('title','summary','key_points','timeline','limitations','source_url')}
                (directory / 'source.json').write_text(json.dumps(evidence, ensure_ascii=False), encoding='utf-8')
            from .cards import render_cards
            from .douyin_layout import spec
            from .exports import write_exports
            names = render_cards(content, platform, directory, illustrations=[directory / n for n in originals])
            content['rendering'] = spec()
            content['derivation'] = {'source_batch_id': batch, 'operation': 'relayout', 'text_unchanged': True}
            shutil.copyfile(directory / names[0], directory / 'cover.png')
            relative = directory.relative_to(self.history.download_root).as_posix()
            href = lambda name: '/downloads/' + quote(relative + '/' + name, safe='/')
            content['cover']['href'] = href('cover.png')
            content['images'] = [{**image, 'href': href(name), 'original_href': href(original),
                                  'width': 1080, 'height': 1920}
                                 for image, name, original in zip(content['images'], names, originals)]
            content['exports'] = {'markdown': href('content.md'), 'json': href('content.json'), 'package': href('package.zip')}
            write_exports(directory, content, names)
            self.store.update(identifier, platform, status='generated', progress='新版9:16图文已准备，未发布', content=content)
            self.store.finish(identifier)
            return {'batch_id': identifier, 'created': True, 'rendering': content['rendering']}
        except Exception as exc:
            self.store.update(identifier, platform, status='error', progress='重新排版失败', error=str(exc)[:500])
            self.store.finish(identifier)
            raise

    def run(self, history_id, batch, platforms, source, provider):
        snapshot = {k: source.get(k) for k in ('title', 'summary', 'key_points', 'timeline', 'limitations', 'source_url')}
        for platform in platforms:
            try:
                self.store.update(batch, platform, status='running', progress='等待模型队列并生成平台文案')
                directory = self.history.download_root / 'publications' / history_id / batch / platform
                directory.mkdir(parents=True, exist_ok=True)
                (directory / 'source.json').write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding='utf-8')
                started = time.time()
                stages = []
                def editorial_progress(message):
                    stages.append({'at': time.time(), 'message': message})
                    self.store.update(batch, platform, status='running', progress=message,
                                      content={'editorial_trace': {'stages': stages}})
                from services.douyin.video_understanding import UnderstandingProvider
                if isinstance(provider, UnderstandingProvider):
                    from services.core.understanding_queue import shared_slot
                    from .content import PLATFORMS
                    def waiting(message):
                        self.store.update(batch, platform, status='running', progress=message)
                    with shared_slot(task_id=f'publication:{batch}:{platform}',
                                     platform=PLATFORMS[platform]['name'] + '改写', progress=waiting):
                        waiting('正在使用视频理解LLM改写：' + str(provider.config.get('model', '')))
                        content = generate_content(provider, snapshot, platform, progress=editorial_progress)
                else:
                    content = generate_content(provider, snapshot, platform, progress=editorial_progress)
                config = getattr(provider, 'config', {})
                content['editorial_trace'] = {
                    'provider_config': config.get('provider', ''),
                    'model': config.get('model', ''),
                    'api_format': config.get('api_format', ''),
                    'source_history_id': history_id,
                    'platform': platform,
                    'style_file': platform + '.md',
                    'started_at': started,
                    'finished_at': time.time(),
                    'pipeline': 'understanding_llm_platform_rewrite',
                    'stages': stages,
                }
                relative = directory.relative_to(self.history.download_root).as_posix()
                href = lambda name: '/downloads/' + quote(relative + '/' + name, safe='/')
                self.store.update(batch, platform, status='running', progress='文案已生成，优先检索图库照片', content=content)
                def changed(message):
                    content['images'] = [{'href': href(name), 'heading': content['cards'][index]['heading'],
                                          'kind': 'ai_illustration', 'provider': content['image_traces'][index].get('provider', ''),
                                          'model': content['image_traces'][index].get('model', ''),
                                          'fallback_reason': content['image_traces'][index].get('fallback_reason', '')}
                                         for index, name in enumerate(content.get('illustration_files', []))]
                    self.store.update(batch, platform, status='running', progress=message, content=content)
                names = prepare_images(self.image_factory(), content, platform, directory, changed)
                if platform == 'douyin':
                    from .douyin_layout import spec
                    content['rendering'] = spec()
                shutil.copyfile(directory / names[0], directory / 'cover.png')
                content['cover']['href'] = href('cover.png')
                content['images'] = [{'href': href(name), 'original_href': href(original), 'heading': card['heading'],
                                      'kind': 'stock_photo_card' if trace.get('ai_generated') is False else 'ai_illustrated_card', 'provider': trace['provider'], 'model': trace.get('model', ''),
                                      'fallback_reason': trace.get('fallback_reason', ''), 'is_cover': index == 0,
                                      'attribution': trace.get('attribution', ''), 'source_url': trace.get('page_url', ''),
                                      'license': trace.get('license', ''), 'license_url': trace.get('license_url', ''),
                                      'ai_generated': trace.get('ai_generated', True)}
                                     for index, (name, original, card, trace) in enumerate(zip(names, content['illustration_files'], content['cards'], content['image_traces']))]
                content['exports'] = {'markdown': href('content.md'), 'json': href('content.json'), 'package': href('package.zip')}
                from .exports import write_exports
                write_exports(directory, content, names)
                self.store.update(batch, platform, status='generated', progress='内容已生成', content=content)
                if platform in ('xiaohongshu', 'douyin'):
                    with self.store.connect() as db:
                        auto = db.execute('SELECT auto_publish FROM publication_batches WHERE id=?', (batch,)).fetchone()[0]
                    # Runs only for this fresh generation, never backfill historical intentions.
                    if auto:
                        try:
                            self.send(history_id, batch, platform=platform)
                        except Exception:
                            pass  # Publishing failure is stored separately from generated content.
            except Exception as exc:
                message = str(exc)
                for key in ('api_key', 'token', 'secret'):
                    secret = getattr(provider, 'config', {}).get(key)
                    if secret:
                        message = message.replace(str(secret), '********')
                message = re.sub(r'(?i)(Bearer\s+)[\w.\-]+', r'\1********', message)
                self.store.update(batch, platform, status='error', progress='内容生成失败', error=message[:1000])
        self.store.finish(batch)
