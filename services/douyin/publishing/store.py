"""SQLite publication versions, independently persisted from analysis updates."""
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager

from .content import PLATFORMS

ACTIVE = ('pending', 'running')


class PublicationStore:
    def __init__(self, path):
        self.path = path
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS publication_batches (
                id TEXT PRIMARY KEY, history_id TEXT NOT NULL, request_id TEXT NOT NULL,
                auto_publish INTEGER NOT NULL, status TEXT NOT NULL, created_at REAL NOT NULL,
                updated_at REAL NOT NULL, UNIQUE(history_id,request_id))''')
            db.execute('''CREATE TABLE IF NOT EXISTS publication_targets (
                batch_id TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL,
                progress TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                content_json TEXT NOT NULL DEFAULT '{}', publish_status TEXT NOT NULL DEFAULT 'not_connected',
                PRIMARY KEY(batch_id,platform))''')
            db.execute('CREATE INDEX IF NOT EXISTS publication_history ON publication_batches(history_id,created_at)')
            columns = {r['name'] for r in db.execute('PRAGMA table_info(publication_targets)')}
            if 'publish_json' not in columns:
                db.execute("ALTER TABLE publication_targets ADD COLUMN publish_json TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, history_id, platforms, auto_publish, request_id):
        if not isinstance(platforms, list) or not platforms or any(not isinstance(p, str) or p not in PLATFORMS for p in platforms):
            raise ValueError('请选择至少一个有效发布平台')
        if type(auto_publish) is not bool:
            raise ValueError('自动发布选项必须是布尔值')
        if not isinstance(request_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{16,80}', request_id):
            raise ValueError('缺少有效的请求标识')
        platforms = list(dict.fromkeys(platforms))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            record = db.execute('SELECT result_json FROM understanding_history WHERE id=?', (history_id,)).fetchone()
            if not record:
                raise ValueError('理解历史不存在')
            source = json.loads(record['result_json'])
            if source.get('analysis_ready') is False or not source.get('summary'):
                raise ValueError('请等待内容理解成功后再生成发布内容')
            old = db.execute('SELECT id,auto_publish FROM publication_batches WHERE history_id=? AND request_id=?', (history_id, request_id)).fetchone()
            if old:
                saved_platforms = [r['platform'] for r in db.execute('SELECT platform FROM publication_targets WHERE batch_id=? ORDER BY platform', (old['id'],))]
                if saved_platforms != sorted(platforms) or bool(old['auto_publish']) != auto_publish:
                    raise ValueError('请求标识已用于其他平台或自动发布选项，请重新提交')
                return old['id'], False
            if db.execute("SELECT 1 FROM publication_batches WHERE history_id=? AND status IN ('pending','running')", (history_id,)).fetchone():
                raise ValueError('这条记录的内容正在生成，请等待完成后再提交')
            identifier = uuid.uuid4().hex
            now = time.time()
            db.execute('INSERT INTO publication_batches VALUES (?,?,?,?,?,?,?)',
                       (identifier, history_id, request_id, int(auto_publish), 'pending', now, now))
            db.executemany('INSERT INTO publication_targets(batch_id,platform,status) VALUES (?,?,?)', [(identifier, p, 'pending') for p in platforms])
        return identifier, True

    def update(self, batch, platform, *, status, progress='', error='', content=None):
        with self.connect() as db:
            db.execute('UPDATE publication_targets SET status=?,progress=?,error=? WHERE batch_id=? AND platform=?', (status, progress, error, batch, platform))
            if content is not None:
                db.execute('UPDATE publication_targets SET content_json=? WHERE batch_id=? AND platform=?', (json.dumps(content, ensure_ascii=False), batch, platform))
            if status == 'running':
                db.execute("UPDATE publication_batches SET status='running' WHERE id=?", (batch,))
            db.execute('UPDATE publication_batches SET updated_at=? WHERE id=?', (time.time(), batch))

    def finish(self, batch):
        with self.connect() as db:
            rows = db.execute('SELECT status FROM publication_targets WHERE batch_id=?', (batch,)).fetchall()
            state = 'error' if any(r['status'] == 'error' for r in rows) else 'done'
            db.execute('UPDATE publication_batches SET status=?,updated_at=? WHERE id=?', (state, time.time(), batch))

    def set_publish(self, batch, platform, status, result):
        with self.connect() as db:
            db.execute('UPDATE publication_targets SET publish_status=?,publish_json=? WHERE batch_id=? AND platform=?',
                       (status, json.dumps(result, ensure_ascii=False), batch, platform))
            db.execute('UPDATE publication_batches SET updated_at=? WHERE id=?', (time.time(), batch))

    def claim_publish(self, history_id, batch, platform="xiaohongshu"):
        if platform not in ("xiaohongshu", "douyin"):
            raise ValueError("该平台尚未接入发布")
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('''SELECT t.* FROM publication_targets t JOIN publication_batches b ON b.id=t.batch_id
                WHERE b.history_id=? AND t.batch_id=? AND t.platform=? ''', (history_id,batch,platform)).fetchone()
            if not row or row['status']!='generated':
                raise ValueError('请先生成对应平台内容')
            if row['publish_status'] in ('published','queued','sending','awaiting_login','unknown'):
                raise ValueError('该版本已发布、正在发送或结果待核实，不允许重复发送')
            db.execute("UPDATE publication_targets SET publish_status='sending',publish_json='{}' WHERE batch_id=? AND platform=?", (batch,platform))
            return json.loads(row['content_json'])

    def interrupt(self):
        # Called once by the owning HTTP service at startup, never on history reads.
        with self.connect() as db:
            db.execute("UPDATE publication_targets SET status='error',progress='已中断',error='服务重启，内容生成已中断，可重新生成' WHERE status IN ('pending','running')")
            db.execute("UPDATE publication_batches SET status='error',updated_at=? WHERE status IN ('pending','running')", (time.time(),))

    def active_targets(self):
        with self.connect() as db:
            return [{'batch_id': row['batch_id'], 'history_id': row['history_id'], 'platform': row['platform'], 'content': json.loads(row['content_json'])}
                    for row in db.execute("SELECT t.batch_id,b.history_id,t.platform,t.content_json FROM publication_targets t JOIN publication_batches b ON b.id=t.batch_id WHERE b.status IN ('pending','running') AND t.status IN ('pending','running')")]

    def list(self, history_id):
        with self.connect() as db:
            batches = [dict(r) for r in db.execute('SELECT * FROM publication_batches WHERE history_id=? ORDER BY created_at DESC,id DESC', (history_id,))]
            for batch in batches:
                batch['auto_publish'] = bool(batch['auto_publish'])
                batch.pop('request_id')
                batch['targets'] = []
                for row in db.execute('SELECT * FROM publication_targets WHERE batch_id=? ORDER BY platform', (batch['id'],)):
                    target = dict(row)
                    target['content'] = json.loads(target.pop('content_json'))
                    target['publication'] = json.loads(target.pop('publish_json'))
                    if target['publish_status'] in ('queued','sending','awaiting_login') and target['publication'].get('job_id'):
                        from .xiaohongshu import status
                        job = status(target['publication']['job_id'])
                        mapping = {'queued':'queued','running':'sending','submitting':'sending','done':'published','error':'failed','unknown':'unknown','interrupted':'failed','preview':'ready','awaiting_login':'awaiting_login'}
                        target['publish_status'] = mapping.get(job['status'],target['publish_status'])
                        target['publication'] = {'job_id':job.get('id'), **job}
                        db.execute('UPDATE publication_targets SET publish_status=?,publish_json=? WHERE batch_id=? AND platform=?',
                            (target['publish_status'],json.dumps(target['publication'],ensure_ascii=False),batch['id'],target['platform']))
                    target.pop('batch_id')
                    batch['targets'].append(target)
        return batches

    def summaries(self, identifiers):
        if not identifiers:
            return {}
        marks = ','.join('?' for _ in identifiers)
        with self.connect() as db:
            rows = db.execute(f'''SELECT b.history_id,b.id,b.created_at,t.platform,t.status,t.publish_status
                FROM publication_batches b JOIN publication_targets t ON t.batch_id=b.id
                WHERE b.history_id IN ({marks}) ORDER BY b.created_at DESC,b.id DESC''', identifiers).fetchall()
        result = {}
        for row in rows:
            targets = result.setdefault(row['history_id'], {})
            targets.setdefault(row['platform'], {'platform': row['platform'], 'status': row['status'], 'publish_status': row['publish_status']})
        return {identifier: list(targets.values()) for identifier, targets in result.items()}

    def active(self, history_id):
        with self.connect() as db:
            return bool(db.execute("SELECT 1 FROM publication_batches WHERE history_id=? AND status IN ('pending','running')", (history_id,)).fetchone())
