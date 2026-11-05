"""Cross-process FIFO admission for the shared video-understanding model.

Task execution stays in its owning service. SQLite only coordinates admission;
no credentials, model prompts, media paths or request bodies are stored here.
"""
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager

from services.core.storage import service_store

_local = threading.local()


def process_identity(pid):
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 5:
                raise PermissionError('Cannot inspect understanding queue owner')
            return None
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                return None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
                raise OSError('Cannot inspect understanding queue owner')
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        from pathlib import Path
        stat = Path(f'/proc/{pid}/stat')
        if stat.exists():
            fields = stat.read_text().rsplit(')', 1)[1].split()
            return None if fields[0] == 'Z' else fields[19]
        os.kill(pid, 0)
        return str(pid)
    except (ProcessLookupError, FileNotFoundError):
        return None


@contextmanager
def database():
    path = service_store('core') / 'understanding_queue.sqlite3'
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS admissions (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                task_id TEXT NOT NULL, platform TEXT NOT NULL, owner_pid INTEGER NOT NULL,
                owner_identity TEXT NOT NULL, status TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL)''')
            db.execute('BEGIN IMMEDIATE')
            owners = db.execute("SELECT DISTINCT owner_pid,owner_identity FROM admissions WHERE status IN ('pending','running')").fetchall()
            for owner in owners:
                try:
                    identity = process_identity(owner['owner_pid'])
                except PermissionError:
                    continue  # Fail closed: an uninspectable process may still own the model.
                if identity != owner['owner_identity']:
                    db.execute("UPDATE admissions SET status='interrupted',updated_at=? WHERE owner_pid=? AND owner_identity=? AND status IN ('pending','running')",
                               (time.time(), owner['owner_pid'], owner['owner_identity']))
            yield db
    finally:
        db.close()


def reserve(task_id, platform):
    if getattr(_local, 'ticket', None):
        return _local.ticket
    with database() as db:
        row = db.execute("SELECT id FROM admissions WHERE task_id=? AND status IN ('pending','running')", (task_id,)).fetchone()
        if row:
            return row['id']
        identifier = uuid.uuid4().hex
        now = time.time()
        identity = process_identity(os.getpid())
        if identity is None:
            raise RuntimeError('无法登记视频理解队列进程')
        db.execute('INSERT INTO admissions(id,task_id,platform,owner_pid,owner_identity,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',
                   (identifier, task_id, platform, os.getpid(), identity, 'pending', now, now))
        return identifier


def snapshot():
    with database() as db:
        rows = db.execute("SELECT id,task_id,platform,status,created_at FROM admissions WHERE status IN ('pending','running') ORDER BY sequence").fetchall()
        items, position = [], 0
        for row in rows:
            item = dict(row)
            if item['status'] == 'pending':
                position += 1
            item['queue_position'] = position if item['status'] == 'pending' else None
            items.append(item)
        return {'pending': position, 'active': sum(x['status'] == 'running' for x in items),
                'concurrency': 1, 'scope': 'shared_understanding', 'items': items}


def discard(task_id):
    with database() as db:
        db.execute("UPDATE admissions SET status='error',updated_at=? WHERE task_id=? AND owner_pid=? AND status='pending'",
                   (time.time(), task_id, os.getpid()))


def annotate(result, task_id, state=None):
    state = state or snapshot()
    item = next((row for row in state['items'] if row['task_id'] == task_id), None)
    if item and item['status'] == 'pending':
        result.update(queue_position=item['queue_position'], reply_status='pending',
                      progress=waiting_message(item, state))
    return result


def waiting_message(item, state):
    owner = next((row['platform'] for row in state['items'] if row['status'] == 'running'), '')
    return (f"等待共享视频理解队列 · 排队第 {item['queue_position']} 位"
            + (f' · 正在处理{owner}任务' if owner else ''))


@contextmanager
def shared_slot(task_id=None, platform='模型调用', progress=None):
    if getattr(_local, 'ticket', None):
        yield
        return
    ticket = reserve(task_id or uuid.uuid4().hex, platform)
    acquired = False
    status = 'error'
    last_message, last_report = None, 0
    try:
        while not acquired:
            with database() as db:
                first = db.execute("SELECT id,status FROM admissions WHERE status IN ('pending','running') ORDER BY sequence LIMIT 1").fetchone()
                if first and first['id'] == ticket and first['status'] == 'pending':
                    db.execute("UPDATE admissions SET status='running',updated_at=? WHERE id=?", (time.time(), ticket))
                    acquired = True
            if not acquired:
                if progress:
                    state = snapshot()
                    item = next((item for item in state['items'] if item['id'] == ticket), None)
                    if item is None:
                        raise RuntimeError('视频理解队列登记已失效')
                    message = waiting_message(item, state)
                    if message != last_message or time.monotonic() - last_report >= 5:
                        progress(message)
                        last_message, last_report = message, time.monotonic()
                time.sleep(.5)
        _local.ticket = ticket
        yield
        status = 'done'
    finally:
        _local.ticket = None
        with database() as db:
            db.execute('UPDATE admissions SET status=?,updated_at=? WHERE id=?', (status, time.time(), ticket))
