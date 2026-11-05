"""Local creator-center publisher. One durable browser job, no blind send retries."""
import json
from contextlib import contextmanager
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from services.core.storage import service_store

CREATOR = 'https://creator.xiaohongshu.com'


def publish_control(page):
    """Support both the creator center's custom element and legacy button."""
    widgets = page.locator('xhs-publish-btn:not([is-publish="false"])')
    for index in range(widgets.count()):
        button = widgets.nth(index)
        if button.is_visible():
            if button.get_attribute('submit-disabled') == 'true':
                raise ValueError('图片仍在上传或发布表单尚未通过校验，未提交')
            return button, True
    return page.get_by_role('button', name=re.compile(r'^\s*发\s*布\s*$')), False


def root():
    path = service_store('douyin') / 'xiaohongshu_publisher'
    path.mkdir(parents=True, exist_ok=True)
    return path


@contextmanager
def connect():
    db = sqlite3.connect(root() / 'jobs.sqlite3', timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('''CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, action TEXT, status TEXT, pid INTEGER DEFAULT 0,
        input_json TEXT, result_json TEXT DEFAULT '{}', updated REAL)''')
    db.execute('CREATE TABLE IF NOT EXISTS browser_lock (slot INTEGER PRIMARY KEY, job_id TEXT, pid INTEGER)')
    try:
        with db:
            yield db
    finally:
        db.close()


def alive(pid):
    if not pid:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            return False
        try:
            return kernel.WaitForSingleObject(handle, 0) == 258
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def status(identifier=None):
    with connect() as db:
        row = db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone() if identifier else db.execute('SELECT * FROM jobs ORDER BY rowid DESC LIMIT 1').fetchone()
        if not row:
            return {'status': 'not_connected', 'message': '请先登录小红书创作中心'}
        state = row['status']
        if state in ('running', 'awaiting_login', 'submitting') and time.time()-row['updated'] > 20 and not alive(row['pid']):
            state = 'unknown' if state == 'submitting' else 'interrupted'
            db.execute('UPDATE jobs SET status=?,updated=? WHERE id=?', (state, time.time(), row['id']))
        result = {'id': row['id'], 'action': row['action'], **json.loads(row['result_json']), 'status': state}
        if state == 'queued':
            position = db.execute("SELECT count(*) FROM jobs WHERE status='queued' AND rowid <= (SELECT rowid FROM jobs WHERE id=?)", (row['id'],)).fetchone()[0]
            result.update(queue_position=position, message=f'等待发布队列，第 {position} 位')
        return result


def save(identifier, state, **result):
    with connect() as db:
        db.execute('UPDATE jobs SET status=?,pid=?,result_json=?,updated=? WHERE id=?',
                   (state, os.getpid(), json.dumps(result, ensure_ascii=False), time.time(), identifier))


def spawn(identifier):
    process = subprocess.Popen([sys.executable, '-B', '-m', 'services.douyin.publishing.xiaohongshu', identifier],
        cwd=Path(__file__).resolve().parents[3], stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    with connect() as db:
        db.execute('UPDATE jobs SET pid=? WHERE id=? AND pid IN (0,?)', (process.pid, identifier, os.getpid()))


def recover_queue():
    # Reserve orphaned queued jobs atomically across both history services.
    reserved = []
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        for row in db.execute("SELECT * FROM jobs WHERE status='queued' ORDER BY rowid").fetchall():
            if alive(row['pid']) or (not row['pid'] and time.time()-row['updated'] < 20):
                continue
            db.execute('UPDATE jobs SET pid=?,updated=? WHERE id=?', (os.getpid(), time.time(), row['id']))
            reserved.append(row['id'])
    for identifier in reserved:
        try:
            spawn(identifier)
        except Exception:
            save(identifier, 'error', message='无法恢复发布队列任务')


def acquire(identifier):
    """Claim the shared browser only for the oldest queued job, across processes."""
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        owner = db.execute('SELECT * FROM browser_lock WHERE slot=1').fetchone()
        if owner and alive(owner['pid']):
            return False
        if owner:
            db.execute("UPDATE jobs SET status=CASE WHEN status='submitting' THEN 'unknown' ELSE 'interrupted' END WHERE id=? AND status IN ('running','awaiting_login','submitting')", (owner['job_id'],))
            db.execute('DELETE FROM browser_lock WHERE slot=1')
        first = db.execute("SELECT id FROM jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if not first or first['id'] != identifier:
            return False
        # Include workers launched before this queue implementation.
        for row in db.execute("SELECT * FROM jobs WHERE status IN ('running','awaiting_login','submitting','preview')").fetchall():
            if alive(row['pid']):
                return False
            db.execute("UPDATE jobs SET status=? WHERE id=?", ('unknown' if row['status']=='submitting' else 'interrupted', row['id']))
        db.execute('INSERT INTO browser_lock VALUES (1,?,?)', (identifier, os.getpid()))
        db.execute("UPDATE jobs SET status='running',pid=?,updated=? WHERE id=?", (os.getpid(), time.time(), identifier))
        return True


def release(identifier):
    with connect() as db:
        db.execute('DELETE FROM browser_lock WHERE slot=1 AND job_id=? AND pid=?', (identifier, os.getpid()))


def start(action, payload=None):
    if action not in ('login', 'preview', 'publish', 'verify'):
        raise ValueError('无效的小红书操作')
    recover_queue()
    identifier = uuid.uuid4().hex
    with connect() as db:
        db.execute('INSERT INTO jobs(id,action,status,pid,input_json,updated) VALUES (?,?,?,?,?,?)',
                   (identifier, action, 'queued', os.getpid(), json.dumps(payload or {}, ensure_ascii=False), time.time()))
    try:
        spawn(identifier)
    except Exception:
        save(identifier, 'error', message='无法启动小红书浏览器任务')
        raise
    return status(identifier)


def prepare(content, directory):
    """Validate and resolve only generated cards from this target's directory."""
    title = content.get('title', '').strip()
    body = content.get('body', '').strip()
    tags = content.get('tags', [])
    body += '\n\n' + ' '.join('#'+t for t in tags)
    if not title or len(title) > 20 or not body.strip() or len(body) > 1000:
        raise ValueError('小红书标题需1–20字，正文含话题不得超过1000字，请先调整文案')
    directory = Path(directory).resolve()
    files = []
    for index, item in enumerate(content.get('images', [])):
        name = Path(item['href']).name
        if name != f'card-{index+1:02d}.png':
            raise ValueError('发布图片必须使用本次生成的顺序卡片')
        path = (directory / name).resolve()
        if path.parent != directory or not path.is_file():
            raise ValueError('发布素材不存在')
        files.append(str(path))
    if not 1 <= len(files) <= 18:
        raise ValueError('发布图片数量无效')
    return {'title': title, 'body': body.strip(), 'files': files}


def receipt(value):
    """Do not equate HTTP 200, a click, or a success toast with a note receipt."""
    if not isinstance(value, dict) or value.get('success') is not True:
        return None
    data = value.get('data') or {}
    note = data.get('note') or data
    identifier = note.get('note_id') or note.get('id')
    if not isinstance(identifier, str) or not re.fullmatch('[0-9a-fA-F]{24}', identifier):
        return None
    return {'note_id': identifier, 'url': 'https://www.xiaohongshu.com/explore/'+identifier,
            'submitted_at': time.time(), 'verification': 'creator_publish_response', 'music_status': 'not_attached'}


def matching_notes(value, title):
    found = set()
    if isinstance(value, dict):
        caption = value.get('title') or value.get('display_title')
        identifier = value.get('note_id') or value.get('id')
        if caption == title and isinstance(identifier,str) and re.fullmatch('[0-9a-fA-F]{24}',identifier):
            found.add(identifier)
        for child in value.values():
            found.update(matching_notes(child,title))
    elif isinstance(value,list):
        for child in value:
            found.update(matching_notes(child,title))
    return found


def keep_login_window(page, identifier, seconds=300):
    """Allow account inspection without holding up a queued browser action."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if page.is_closed():
            return
        with connect() as db:
            waiting = db.execute("SELECT 1 FROM jobs WHERE status='queued' AND id<>? LIMIT 1", (identifier,)).fetchone()
        if waiting:
            return
        try:
            page.wait_for_timeout(1000)
        except Exception:
            if page.is_closed():
                return
            raise


def run(identifier):
    from playwright.sync_api import sync_playwright
    from .store import PublicationStore
    with connect() as db:
        job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (identifier,)).fetchone())
    payload = json.loads(job['input_json'])
    store = PublicationStore(Path(payload['db'])) if payload.get('db') else None
    if payload.get('platform') == 'douyin':
        from .douyin import run as run_douyin
        return run_douyin(identifier, job, payload, store)
    submitted = False
    context = None
    pw = None
    page = None
    stage = 'open_browser'
    folder = root() / 'jobs' / identifier
    folder.mkdir(parents=True, exist_ok=True)
    def update(state, **values):
        save(identifier, state, **values)
        if store:
            mapped = {'done':'published', 'not_published':'failed', 'preview':'ready', 'awaiting_login':'awaiting_login',
                      'submitting':'sending', 'unknown':'unknown', 'error':'failed'}.get(state, 'sending')
            if job['action']=='verify' and state=='error':
                mapped='unknown'
            store.set_publish(payload['batch'], 'xiaohongshu', mapped, {'job_id':identifier, **values})
    try:
        update('running', message='正在打开小红书创作中心')
        pw = sync_playwright().start()
        if pw:
            # A separate reusable profile, never copy an unrelated Chrome profile or cookies.
            context = pw.chromium.launch_persistent_context(str(root() / 'browser'), channel='chrome',
                        headless=False, viewport={'width':1280, 'height':900})
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(20000)
            page.goto(CREATOR+'/publish/publish?source=official', wait_until='domcontentloaded', timeout=60000)
            deadline = time.monotonic()+600
            while True:
                if page.is_closed():
                    raise ValueError('登录窗口已关闭')
                if '/login' not in page.url and page.get_by_text('发布笔记', exact=True).count():
                    break
                update('awaiting_login', message='请在弹出的Chrome窗口登录小红书；登录完成后将继续当前任务')
                if time.monotonic() > deadline:
                    raise ValueError('等待登录超时，请重新连接账号')
                page.wait_for_timeout(3000)
            if job['action']=='login':
                update('connected', message='小红书登录成功，登录态已保存。窗口保留最多5分钟，可手动关闭；提交发布任务后自动交接，无需再次登录')
                keep_login_window(page, identifier)
                return
            if job['action']=='verify':
                stage='verify_management'
                update('running',message='只读核对笔记管理，不重复提交发布')
                found=set()
                def managed(response):
                    parts=urlsplit(response.url)
                    if parts.hostname not in ('edith.xiaohongshu.com','creator.xiaohongshu.com') or 'note' not in parts.path:
                        return
                    try:
                        found.update(matching_notes(response.json(),payload['content']['title']))
                    except Exception:
                        pass
                page.on('response',managed)
                page.get_by_text('笔记管理',exact=True).click()
                page.wait_for_timeout(8000)
                page.screenshot(path=str(folder/'management.png'),full_page=True)
                (folder/'management.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
                if len(found)==1:
                    note=found.pop()
                    result={'note_id':note,'url':'https://www.xiaohongshu.com/explore/'+note,
                            'verification':'creator_note_management_exact_title','music_status':'not_attached'}
                    (folder/'receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                    update('done',message='已在创作中心笔记管理核实发布记录',receipt=result)
                else:
                    text=page.locator('body').inner_text()
                    total=re.search(r'全部\s+(\d+)',text)
                    if total and int(total[1])<=1 and payload['content']['title'] not in text:
                        update('not_published',message='已核对完整笔记列表，当前笔记未发布，可修正后重试',stage=stage)
                    else:
                        update('unknown',message='未找到唯一匹配的已发布笔记，未执行重复发送',stage=stage)
                return
            media = prepare(payload['content'], payload['directory'])
            stage = 'upload'
            update('running', message='登录成功，正在准备图文素材')
            image_tab = page.get_by_text('上传图文', exact=True)
            if image_tab.count():
                image_tab.last.click()
            uploader = page.locator('input[type=file][accept*="image"]')
            if not uploader.count():
                uploader = page.locator('input[type=file]')
            uploads = {'pending':set(),'last':time.monotonic(),'failed':False}
            def upload_request(request):
                parts=urlsplit(request.url)
                if request.method in ('POST','PUT') and parts.hostname and (
                        parts.hostname.endswith(('.xiaohongshu.com','.xhscdn.com','.aliyuncs.com'))) and (
                        request.method=='PUT' or 'upload' in parts.path.lower() or 'upload' in parts.hostname):
                    uploads['pending'].add(request)
                    uploads['last']=time.monotonic()
            def upload_finished(request):
                if request in uploads['pending']:
                    uploads['pending'].discard(request)
                    uploads['last']=time.monotonic()
            def upload_failed(request):
                if request in uploads['pending']:
                    uploads['failed']=True
                upload_finished(request)
            page.on('request',upload_request)
            page.on('requestfinished',upload_finished)
            page.on('requestfailed',upload_failed)
            uploaded_at=time.monotonic()
            uploader.first.set_input_files(media['files'])
            title = page.get_by_placeholder(re.compile('填写标题|输入标题'))
            title.wait_for(state='visible', timeout=120000)
            title.fill(media['title'])
            editor = page.locator('[contenteditable="true"]').first
            editor.fill(media['body'])
            guide = page.locator('.feature-guide__btn')
            if guide.count() and guide.first.is_visible():
                guide.first.click()
            editor.press('Escape')
            title.click()
            actual_body = editor.inner_text()
            if title.input_value() != media['title'] or re.sub(r'\s+', '', media['body']) != re.sub(r'\s+', '', actual_body):
                raise ValueError('发布表单内容校验失败，未提交')
            page.screenshot(path=str(folder/'preview.png'), full_page=True)
            if job['action']=='preview':
                update('preview', message='已上传并填好图文，未点击发布；窗口保留10分钟供检查')
                # Do not let an unobserved manual click be mislabeled as an automated success.
                page.wait_for_timeout(600000)
                return
            stage = 'find_publish_button'
            deadline=time.monotonic()+120
            while time.monotonic()<deadline:
                if uploads['failed']:
                    raise ValueError('图片上传网络失败，未提交发布')
                if not uploads['pending'] and time.monotonic()-uploads['last']>=3 and time.monotonic()-uploaded_at>=15:
                    break
                page.wait_for_timeout(500)
            else:
                raise ValueError('等待图片上传完成超时，未提交发布')
            # Creator center renders visual text "发布" with surrounding/inter-character spaces.
            button, widget = publish_control(page)
            button.wait_for(state='visible', timeout=120000)
            if not button.is_enabled():
                raise ValueError('发布按钮尚不可用，图片可能仍在上传或存在校验错误')
            update('submitting', message='正在提交发布，禁止重复发送')
            responses = []
            def received(response):
                parts = urlsplit(response.url)
                if response.request.method != 'POST' or parts.hostname not in ('edith.xiaohongshu.com','creator.xiaohongshu.com') or '/note' not in parts.path:
                    return
                try:
                    value = response.json()
                    responses.append({'path':parts.path, 'http_status':response.status,
                        'code':value.get('code'), 'success':value.get('success'), 'receipt':receipt(value)})
                except Exception:
                    pass
            page.on('response', received)
            stage = 'click_publish'
            submitted = True
            if widget:
                button.scroll_into_view_if_needed()
                box = button.bounding_box()
                if not box:
                    raise ValueError('发布控件没有可点击区域，请核对页面')
                button.click(position={'x':box['width']*.65,'y':box['height']*.5})
            else:
                button.click()
            page.wait_for_timeout(1500)
            page.screenshot(path=str(folder/'after-submit.png'),full_page=True)
            (folder/'after-submit.txt').write_text(page.locator('body').inner_text(),encoding='utf-8')
            stage = 'await_receipt'
            deadline = time.monotonic()+60
            result = None
            while time.monotonic() < deadline:
                result = next((r['receipt'] for r in responses if r['receipt']),None)
                if result:
                    break
                page.wait_for_timeout(500)
            (folder/'responses.json').write_text(json.dumps(responses,ensure_ascii=False,indent=2),encoding='utf-8')
            if not result:
                raise ValueError('平台未返回可验证的笔记ID，请在创作中心核实，禁止自动重发')
            (folder/'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            update('done', message='平台已返回笔记ID，内容已发布；审核和可见性以平台为准', receipt=result)
    except Exception as exc:
        # Browser errors can contain URLs/tokens; expose only fixed, actionable messages.
        message = str(exc) if isinstance(exc, ValueError) else '创作中心页面操作失败，请检查登录、上传或页面变化'
        diagnostic = {'stage':stage,'exception':type(exc).__name__}
        if page:
            try:
                page.screenshot(path=str(folder/'failure.png'), full_page=True)
                diagnostic['publish_buttons'] = page.locator('button').all_text_contents()
            except Exception:
                pass
        (folder/'diagnostic.json').write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
        update('unknown' if submitted else 'error', message=message[:300], stage=stage)
    finally:
        if context:
            try:
                context.close()
            except Exception:
                pass
        if pw:
            try:
                pw.stop()
            except Exception:
                pass


def worker(identifier):
    with connect() as db:
        db.execute("UPDATE jobs SET pid=? WHERE id=? AND status='queued'", (os.getpid(), identifier))
    while not acquire(identifier):
        if status(identifier)['status'] != 'queued':
            return
        recover_queue()
        time.sleep(2)
    try:
        run(identifier)
    except Exception:
        current = status(identifier)['status']
        save(identifier, 'unknown' if current == 'submitting' else 'error', message='发布任务异常结束，请核对任务结果')
    finally:
        # Release only after run() has closed the browser, even if already done.
        release(identifier)


if __name__=='__main__':
    worker(sys.argv[1])
