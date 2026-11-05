"""Durable FIFO understanding queue with one worker and no stored credentials."""
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path


class UnderstandingQueue:
    def __init__(self, path, execute):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.execute = execute
        self.wake = threading.Event()
        self.stopped = threading.Event()
        self.worker = None
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS tasks (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL,
                source_url TEXT NOT NULL, status TEXT NOT NULL, message TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL,
                result_json TEXT, error TEXT)''')
            db.execute("UPDATE tasks SET status='error', message=?, error=?, updated_at=? WHERE status='running'",
                       ('服务重启，任务已中断', '服务重启，任务已中断', time.time()))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self, identifier, url):
        now = time.time()
        with self.connect() as db:
            db.execute('INSERT INTO tasks(id,source_url,status,message,created_at,updated_at) VALUES (?,?,?,?,?,?)',
                       (identifier, url, 'pending', '等待视频理解队列', now, now))
        self.wake.set()
        return self.get(identifier)

    def _public(self, row, db):
        job = dict(row)
        raw = job.pop('result_json')
        if raw:
            job['result'] = json.loads(raw)
        job['queue_position'] = None
        if job['status'] == 'pending':
            job['queue_position'] = db.execute("SELECT count(*) FROM tasks WHERE status='pending' AND sequence<=?",
                                               (job['sequence'],)).fetchone()[0]
            job['message'] = f"排队第 {job['queue_position']} 位"
        return job

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute('SELECT * FROM tasks WHERE id=?', (identifier,)).fetchone()
            return self._public(row, db) if row else None

    def snapshot(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM tasks WHERE status IN ('pending','running') ORDER BY sequence").fetchall()
            items = [self._public(row, db) for row in rows]
        return {'pending': sum(x['status'] == 'pending' for x in items),
                'active': sum(x['status'] == 'running' for x in items), 'concurrency': 1, 'items': items}

    def update(self, identifier, status=None, message='', result=None, error=None):
        with self.connect() as db:
            db.execute('UPDATE tasks SET status=coalesce(?,status),message=?,result_json=coalesce(?,result_json),error=?,updated_at=? WHERE id=?',
                       (status, message, json.dumps(result, ensure_ascii=False) if result is not None else None,
                        error, time.time(), identifier))

    def start(self):
        if self.worker is not None:
            return
        self.worker = threading.Thread(target=self._run, name='youtube-understanding-queue', daemon=True)
        self.worker.start()

    def close(self, wait=False):
        self.stopped.set()
        self.wake.set()
        if wait and self.worker:
            self.worker.join(timeout=5)

    def _run(self):
        while not self.stopped.is_set():
            self.wake.clear()
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY sequence LIMIT 1").fetchone()
                if row:
                    db.execute("UPDATE tasks SET status='running',message=?,updated_at=? WHERE id=?",
                               ('正在开始视频理解', time.time(), row['id']))
            if not row:
                self.wake.wait(1)
                continue
            identifier = row['id']
            if self.stopped.is_set():
                self.update(identifier, status='pending', message='等待视频理解队列')
                return
            try:
                def progress(message, partial_result=None):
                    self.update(identifier, message=message, result=partial_result)
                result = self.execute(identifier, row['source_url'], progress)
                self.update(identifier, status='done', message='完成', result=result)
            except Exception as exc:
                self.update(identifier, status='error', message='失败', error=str(exc))
