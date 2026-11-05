"""Douyin creator-center adapter using the shared durable publication queue."""
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from services.core.storage import service_store
from . import xiaohongshu as queue

CREATOR = 'https://creator.douyin.com'


def start(action, payload=None):
    return queue.start(action, {**(payload or {}), 'platform': 'douyin', 'created_at': time.time()})


def status(identifier=None):
    if identifier:
        with queue.connect() as db:
            row = db.execute('SELECT input_json FROM jobs WHERE id=?', (identifier,)).fetchone()
        if not row or json.loads(row['input_json']).get('platform') != 'douyin':
            raise ValueError('抖音发布任务不存在')
        return queue.status(identifier)
    with queue.connect() as db:
        rows = db.execute('SELECT id,input_json FROM jobs ORDER BY rowid DESC').fetchall()
    identifier = next((r['id'] for r in rows if json.loads(r['input_json']).get('platform') == 'douyin'), None)
    return queue.status(identifier) if identifier else {'status': 'not_connected', 'message': '请先登录抖音创作者中心'}


def publication_title(content):
    title = content.get('title', '').strip()
    if len(title) > 20:
        # Reuse a short title already authored by the configured editorial LLM.
        title = str((content.get('cover') or {}).get('headline') or '').strip()
    if not 1 <= len(title) <= 20:
        raise ValueError('抖音网页标题需1–20字，请重新生成短标题')
    return title


def normalized_editor_text(text):
    # Douyin adds U+200B paragraph sentinels; preserve meaningful ZWJ/emoji text.
    return re.sub(r'[\s\u200b]+', '', text)


def require_text_payload(payload, media):
    item = payload.get('item') if isinstance(payload, dict) else None
    common = item.get('common') if isinstance(item, dict) else None
    text = common.get('text') if isinstance(common, dict) else None
    if not isinstance(text, str) or not media.get('body'):
        raise ValueError('发布请求缺少完整正文，已拦截提交')
    canonical = lambda value: value.replace('\u200b', '').replace('\r\n', '\n').replace('\r', '\n').strip()
    title = canonical(media['title'])
    body = canonical(media['body'])
    actual = canonical(text)
    if actual not in (title + '。' + body, title + body):
        raise ValueError('发布正文与预览不一致，已拦截提交')
    return {'text_verified': True, 'text_characters': len(text)}


def fill_description(page, editor, text):
    """Use editor-native paragraph events instead of pasting multiline DOM text."""
    editor.fill('')
    for index, line in enumerate(text.splitlines()):
        if index:
            editor.press('Escape')
            editor.press('Enter')
        if line:
            page.keyboard.insert_text(line)
    editor.press('Escape')


def upload_in_progress(text):
    return any(int(done) < int(total) for done, total in
               re.findall(r'(\d+)\s*/\s*(\d+)\s*取消上传', text))


def prepare(content, directory):
    title = publication_title(content)
    body = content.get('body', '').strip()
    if content.get('theme') == 'finance':
        body += '\n\n根据来源内容观点整理，金额为原作者测算示例。'
    tags = content.get('tags', [])
    if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
        raise ValueError('话题格式无效')
    body = (body + '\n\n' + ' '.join('#' + t for t in tags)).strip()
    if not body or len(body) > 1000:
        raise ValueError('抖音正文含来源说明及话题不得超过1000字')
    directory = Path(directory).resolve()
    files = []
    for index, item in enumerate(content.get('images', [])):
        name = f'card-{index+1:02d}.png'
        if Path(urlsplit(item.get('href', '')).path).name != name:
            raise ValueError('发布图片必须使用本版本的顺序卡片')
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file() or path.stat().st_size > 20*1024*1024:
            raise ValueError('发布图片不存在或超过20MB')
        files.append(str(path))
    if not 1 <= len(files) <= 30:
        raise ValueError('图文需要1–30张图片')
    return {'title': title, 'body': body, 'files': files}


def receipt(value):
    if not isinstance(value, dict) or type(value.get('status_code')) is not int or value['status_code'] != 0:
        return None
    data = value.get('aweme') or value.get('data') or value
    if not isinstance(data, dict):
        return None
    data = data.get('aweme') or data
    if not isinstance(data, dict):
        return None
    identifier = data.get('aweme_id') or data.get('item_id')
    if not isinstance(identifier, str) or not re.fullmatch(r'\d{15,25}', identifier):
        return None
    return {'item_id': identifier, 'url': 'https://www.douyin.com/note/' + identifier,
            'submitted_at': time.time(), 'verification': 'creator_publish_response', 'music_status': 'unknown'}


def matching_posts(value, title, created_since=None):
    found = set()
    if isinstance(value, dict):
        identifier = value.get('aweme_id')
        if (created_since is not None and isinstance(value.get('create_time'), (int, float))
                and value['create_time'] >= created_since - 5 and value.get('desc') == title
                and isinstance(identifier, str) and re.fullmatch(r'\d{15,25}', identifier)):
            found.add(identifier)
        for child in value.values():
            found.update(matching_posts(child, title, created_since))
    elif isinstance(value, list):
        for child in value:
            found.update(matching_posts(child, title, created_since))
    return found


def run(identifier, job, payload, store):
    from playwright.sync_api import sync_playwright
    root = service_store('douyin') / 'douyin_publisher'
    folder = root / 'jobs' / identifier
    folder.mkdir(parents=True, exist_ok=True)
    submitted = False
    music_binding = None
    page = None
    stage = 'open_browser'

    def update(state, **values):
        if music_binding is not None:
            values.setdefault('music', music_binding)
        queue.save(identifier, state, **values)
        if store:
            mapped = {'done': 'published', 'preview': 'ready', 'awaiting_login': 'awaiting_login',
                      'unknown': 'unknown', 'error': 'failed'}.get(state, 'sending')
            if job['action'] == 'verify' and state == 'error':
                mapped = 'unknown'
            store.set_publish(payload['batch'], 'douyin', mapped, {'job_id': identifier, **values})

    try:
        with sync_playwright() as pw:
            context = pw.chromium.launch_persistent_context(str(root / 'browser'), channel='chrome',
                        headless=False, service_workers='block', viewport={'width': 1280, 'height': 900})
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.set_default_timeout(20000)
                update('running', message='正在打开抖音创作者中心')
                page.goto(CREATOR + '/creator-micro/content/upload', wait_until='domcontentloaded', timeout=60000)
                deadline = time.monotonic() + 600
                while not page.get_by_text('发布图文', exact=True).count():
                    if page.is_closed():
                        raise ValueError('登录窗口已关闭')
                    if time.monotonic() > deadline:
                        raise ValueError('等待登录或图文入口超时，请检查账号权限与页面')
                    update('awaiting_login', message='请在Chrome窗口登录抖音；验证码需手动处理，完成后继续')
                    page.wait_for_timeout(3000)
                if job['action'] == 'login':
                    update('connected', message='抖音登录态已保存，之后可直接发布')
                    queue.keep_login_window(page, identifier)
                    return
                if job['action'] == 'verify':
                    stage = 'verify_management'
                    found = set()
                    created_since = None
                    with queue.connect() as db:
                        original = db.execute('SELECT input_json FROM jobs WHERE id=?', (payload.get('original_job_id'),)).fetchone()
                    if original:
                        created_since = json.loads(original['input_json']).get('created_at')
                    def managed(response):
                        parts = urlsplit(response.url)
                        if parts.hostname != 'creator.douyin.com' or 'aweme' not in parts.path or 'post' not in parts.path:
                            return
                        try:
                            found.update(matching_posts(response.json(), publication_title(payload['content']), created_since))
                        except Exception:
                            pass
                    page.on('response', managed)
                    page.goto(CREATOR + '/creator-micro/content/manage', wait_until='domcontentloaded')
                    page.wait_for_timeout(8000)
                    if len(found) == 1:
                        item = found.pop()
                        result = {'item_id': item, 'url': 'https://www.douyin.com/note/' + item,
                                  'verification': 'creator_management_exact_title', 'music_status': 'unknown'}
                        (folder / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
                        update('done', message='已核对创作者中心作品记录', receipt=result)
                    else:
                        update('unknown', message='未取得唯一匹配记录，请手动核对；未重复发送')
                    return
                media = prepare(payload['content'], payload['directory'])
                stage = 'upload'
                page.get_by_text('发布图文', exact=True).first.click()
                uploads = {'pending': set(), 'failed': False, 'last': time.monotonic()}
                def requested(request):
                    parts = urlsplit(request.url)
                    if request.method in ('PUT', 'POST') and parts.hostname and ('upload' in parts.hostname or 'upload' in parts.path.lower()):
                        uploads['pending'].add(request)
                        uploads['last'] = time.monotonic()
                def finished(request):
                    if request in uploads['pending']:
                        uploads['pending'].discard(request)
                        uploads['last'] = time.monotonic()
                def failed(request):
                    if request in uploads['pending']:
                        uploads['failed'] = True
                    finished(request)
                page.on('request', requested)
                page.on('requestfinished', finished)
                page.on('requestfailed', failed)
                page.locator('input[type=file][accept*="image"]').first.set_input_files(media['files'])
                stage = 'wait_upload_form'
                title = page.get_by_placeholder(re.compile('填写作品标题|填写标题|添加作品标题'))
                title.first.wait_for(state='visible', timeout=120000)
                stage = 'fill_form'
                title.first.fill(media['title'])
                editor = page.locator('[contenteditable="true"]').first
                fill_description(page, editor, media['body'])
                title.first.click()
                (folder / 'form.json').write_text(json.dumps({'title': title.first.input_value(), 'body': editor.inner_text(), 'expected_title': media['title'], 'expected_body': media['body']}, ensure_ascii=False, indent=2), encoding='utf-8')
                if title.first.input_value() != media['title'] or normalized_editor_text(editor.inner_text()) != normalized_editor_text(media['body']):
                    raise ValueError('发布表单内容校验失败，未提交')
                stage = 'wait_upload_complete'
                deadline = time.monotonic() + 120
                while uploads['pending'] or time.monotonic() - uploads['last'] < 5 or upload_in_progress(page.locator('body').inner_text()):
                    if time.monotonic() > deadline or uploads['failed']:
                        raise ValueError('图片上传失败或超时，未提交')
                    page.wait_for_timeout(500)
                if uploads['failed'] or page.get_by_text(re.compile('上传失败|上传中')).count():
                    raise ValueError('图片尚未上传成功，未提交')
                guide = page.get_by_text('完成', exact=True)
                for index in range(guide.count()):
                    if guide.nth(index).is_visible():
                        guide.nth(index).click()
                        break
                stage = 'select_music'
                from .douyin_music import select_music, guard_music_request
                music_binding = select_music(page, payload['content'], folder,
                    lambda message: update('running', message=message))
                page.screenshot(path=str(folder / 'preview.png'), full_page=True)
                if job['action'] == 'preview':
                    update('preview', message='图文与真实曲库配乐已准备，未提交发布；窗口保留10分钟')
                    page.wait_for_timeout(600000)
                    return
                responses = []
                def received(response):
                    parts = urlsplit(response.url)
                    if response.request.method != 'POST' or parts.hostname != 'creator.douyin.com' or not re.search(r'/aweme/.*(?:create|publish)', parts.path):
                        return
                    try:
                        value = response.json()
                        responses.append({'path': parts.path, 'http_status': response.status,
                                          'status_code': value.get('status_code'), 'receipt': receipt(value)})
                    except Exception:
                        pass
                page.on('response', received)
                binding_check = {'blocked': None, 'submitted': None}
                def mark_submitted():
                    nonlocal submitted
                    submitted = True
                def guard_publication(route):
                    req = route.request
                    parts = urlsplit(req.url)
                    if req.method == 'POST' and parts.hostname == 'creator.douyin.com' and re.search(r'/aweme/.*(?:create|publish)', parts.path):
                        try:
                            binding_check['text'] = require_text_payload(req.post_data_json, media)
                        except Exception:
                            binding_check['blocked'] = '发布正文缺失或与预览不一致，已拦截提交'
                            route.abort()
                            return
                    guard_music_request(route, music_binding, binding_check, mark_submitted)
                page.route('**/web/api/media/aweme/**', guard_publication)
                stage = 'find_publish_button'
                button = page.get_by_role('button', name=re.compile(r'^\s*发\s*布\s*$'))
                button.wait_for(state='visible')
                if not button.is_enabled():
                    raise ValueError('发布按钮不可用，请核对图片与表单')
                stage = 'submit'
                update('submitting', message='正在提交抖音图文，禁止重复发送')
                button.click()
                stage = 'await_receipt'
                deadline = time.monotonic() + 60
                result = None
                while time.monotonic() < deadline:
                    if binding_check['blocked']:
                        raise ValueError(binding_check['blocked'])
                    result = next((r['receipt'] for r in responses if r['receipt']), None)
                    if result:
                        break
                    page.wait_for_timeout(500)
                (folder / 'responses.json').write_text(json.dumps(responses, ensure_ascii=False, indent=2), encoding='utf-8')
                if not result:
                    raise ValueError('未取得平台作品ID，请核对发布结果；禁止自动重发')
                if not submitted or not binding_check['submitted'] or not binding_check.get('text'):
                    raise ValueError('无法核实发布请求配乐参数，请核对结果，禁止自动重发')
                music_binding = {**music_binding, **binding_check['submitted'], 'status': 'confirmed'}
                result.update(music_status='attached', music=music_binding, **binding_check['text'])
                (folder / 'music-submission.json').write_text(json.dumps(music_binding, ensure_ascii=False, indent=2), encoding='utf-8')
                result['title'] = media['title']
                (folder / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
                update('done', message='抖音已返回作品ID，审核和可见性以平台为准', receipt=result)
            except Exception:
                if page and not page.is_closed():
                    try:
                        page.screenshot(path=str(folder / 'failure.png'), full_page=True)
                    except Exception:
                        pass
                raise
            finally:
                context.close()
    except Exception as exc:
        (folder / 'diagnostic.json').write_text(json.dumps({'stage': stage, 'exception': type(exc).__name__}), encoding='utf-8')
        update('unknown' if submitted else 'error', stage=stage,
               message=str(exc)[:300] if isinstance(exc, ValueError) else '创作者中心操作失败，请检查登录、上传与页面变化')
