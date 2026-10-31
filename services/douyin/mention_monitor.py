"""Persistent mention processing; browser transport is deliberately separate from analysis."""
from __future__ import annotations

import http.server
import json
import secrets
import math
import sqlite3
import threading
import time
import uuid


class MentionMonitor:
    def __init__(self, root, analyze, reply, on_processed=None, agent=None):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.analyze, self.reply = analyze, reply
        self.on_processed = on_processed
        self.agent = agent
        self.lock = threading.RLock()
        self.enabled = False
        self.auto_reply = False
        self.interval = 60
        self.command = None
        self.delivered = False
        self.last_poll = 0
        self.last_seen = 0
        self.error = ""
        self.baseline = True
        self.session = ""
        self.account_id = ''
        self.listen_started_at = 0
        self.request_state = {}
        self.transport = None
        self.worker = None
        self.preparer = None
        self.preparing_id = None
        self.startup_check = None
        self.startup_retry_at = 0
        self.token = secrets.token_urlsafe(32)
        self.health_path = self.root / 'inference_health.json'
        try:
            self.inference_health = json.loads(self.health_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            self.inference_health = {}
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS mentions (id TEXT PRIMARY KEY, data TEXT NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS mention_checkpoints (account_id TEXT PRIMARY KEY, observed_at REAL NOT NULL)")
            for key, raw in db.execute("SELECT id, data FROM mentions").fetchall():
                row = json.loads(raw)
                if row['status'] in {'running', 'sending'}:
                    row.update(status='error', error='服务重启，任务中断；发送中的结果需人工核对，禁止自动重发')
                    db.execute("UPDATE mentions SET data=? WHERE id=?", (json.dumps(row, ensure_ascii=False), key))
        threading.Thread(target=self._loop, daemon=True).start()

    def db(self):
        return sqlite3.connect(self.root / 'mentions.sqlite3', timeout=30)

    def save(self, row):
        if row['status'] != 'baseline' and not row.get('task_directory'):
            row['task_directory'] = uuid.uuid4().hex
        row['updated_at'] = time.time()
        with self.db() as db:
            db.execute('INSERT OR REPLACE INTO mentions VALUES (?, ?)', (row['id'], json.dumps(row, ensure_ascii=False)))
        if self.on_processed and row.get('task_directory'):
            try:
                self.on_processed(self.root / row['task_directory'], row)
            except Exception as exc:
                self.error = '更新 @评论历史失败：' + str(exc)

    def status(self):
        with self.lock, self.db() as db:
            rows = [json.loads(raw) for (raw,) in db.execute('SELECT data FROM mentions ORDER BY rowid DESC LIMIT 100')]
            queued = self._pending_rows(db)
            positions = {row['id']: index + 1 for index, row in enumerate(queued)}
            for row in rows:
                row['queue_position'] = positions.get(row['id'])
            active = sum(json.loads(raw)['status'] in {'running', 'sending'} for (raw,) in db.execute('SELECT data FROM mentions'))
            return dict(enabled=self.enabled, auto_reply=self.auto_reply, interval=self.interval,
                        queue=dict(pending=len(queued), active=active, concurrency=1),
                        autostart_pending=self.startup_check is not None and not self.enabled,
                        last_seen=self.last_seen, error=self.error, request_state=self.request_state,
                        inference_health=self.inference_health, items=rows)

    def save_inference_health(self, value):
        self.inference_health = value
        temporary = self.health_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.health_path)

    def defer_inference_failure(self, row, exc, *, probe=False):
        from services.douyin.inference_health import inference_failure_kind, memory_snapshot
        kind = inference_failure_kind(exc)
        if not kind and not probe:
            return False
        prior = self.inference_health
        failures = int(prior.get('failures', 0)) + 1
        delay = (30, 120, 300)[min(failures - 1, 2)]
        entry = dict(time=time.time(), kind=kind or prior.get('kind', 'probe'),
                     error=str(exc)[:2000], probe=probe, memory=memory_snapshot())
        row.setdefault('inference_recovery', []).append(entry)
        row['inference_recovery'] = row['inference_recovery'][-20:]
        attempts = int(row.get('inference_attempts', 0)) + (0 if probe else 1)
        row.update(inference_attempts=attempts, auto_reply=False)
        self.save_inference_health(dict(kind=entry['kind'], failures=failures,
            next_probe=time.time() + delay, error=entry['error'], task_directory=row['task_directory']))
        if attempts > 2:
            row.update(status='error', error=str(exc), progress='模型恢复后仍多次失败，已停止本任务自动重试')
        else:
            row.update(status='pending', error='', progress=f'等待模型恢复；{delay}秒后验证，恢复后仅保存草稿')
        self.save(row)
        root = self.root / row['task_directory']
        root.mkdir(parents=True, exist_ok=True)
        (root / 'inference_recovery.json').write_text(json.dumps(row['inference_recovery'], ensure_ascii=False, indent=2), encoding='utf-8')
        return True

    def configure_autostart(self, validate):
        with self.lock:
            self.startup_check = validate
            self.startup_retry_at = 0

    def try_autostart(self):
        with self.lock:
            if self.enabled or self.startup_check is None or time.time() < self.startup_retry_at:
                return
            self.startup_retry_at = time.time() + 30
            try:
                self.startup_check()
                self.start(auto_reply=True, interval=60)
            except Exception as exc:
                self.error = f'自动监听等待配置或启动条件：{exc}；30秒后重试'

    def start(self, auto_reply=False, interval=60):
        with self.lock:
            if self.enabled:
                raise ValueError('监听已启动，请先停止')
            if self.transport is None:
                self._start_transport()
            self.auto_reply = auto_reply
            self.interval = max(30, min(600, int(interval)))
            self.baseline = True
            self.account_id = ''
            self.listen_started_at = time.time()
            self.request_state = {}
            self.session = uuid.uuid4().hex
            self.last_poll = 0
            self.error = ''
            self.enabled = True

    def stop(self):
        with self.lock:
            self.enabled = False
            self.startup_check = None
            self.command = None
            self.session = ''
            with self.db() as db:
                rows = [json.loads(raw) for (raw,) in db.execute('SELECT data FROM mentions')]
            for row in rows:
                if row['status'] == 'pending':
                    row.update(status='cancelled', error='监听停止')
                    self.save(row)
        return self.status()

    def queue_existing(self, key):
        """Explicit single-record testing/backfill; never resend a previously attempted publish."""
        with self.lock, self.db() as db:
            if not self.enabled:
                raise ValueError('请先启动监听')
            found = db.execute('SELECT data FROM mentions WHERE id=?', (str(key),)).fetchone()
            if not found:
                raise ValueError('通知不存在')
            row = json.loads(found[0])
            if row['status'] != 'baseline' or row['account_id'] != self.account_id:
                raise ValueError('只允许处理当前账号中尚未发送过的基线通知')
            row.update(status='pending', session=self.session, auto_reply=self.auto_reply, error='', queued_at=time.time())
            self.save(row)
            return row

    def retry_failed(self, key):
        """Retry analysis as a draft only; never resend an earlier ambiguous comment."""
        with self.lock, self.db() as db:
            if not self.enabled:
                raise ValueError('请先启动监听')
            found = db.execute('SELECT data FROM mentions WHERE id=?', (str(key),)).fetchone()
            if not found:
                raise ValueError('通知不存在')
            row = json.loads(found[0])
            if row['status'] != 'error' or row['account_id'] != self.account_id:
                raise ValueError('只允许重试当前账号的失败任务')
            row.setdefault('retry_history', []).append(dict(
                error=row.get('error', ''), progress=row.get('progress', ''),
                task_directory=row.get('task_directory', ''), time=time.time()))
            row.update(status='pending', session=self.session, auto_reply=False, error='',
                       task_directory=uuid.uuid4().hex,
                       preparation_status='pending', preparation_error='',
                       progress='已排队重试分析；完成后仅保存草稿，不发送评论', queued_at=time.time(),
                       inference_attempts=0, retry_count=int(row.get('retry_count', 0)) + 1)
            self.save(row)
            return row

    def _start_transport(self):
        monitor = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def send(self, status, value):
                body = json.dumps(value, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_GET(self):
                if self.path != '/command':
                    return self.send(404, {})
                with monitor.lock:
                    monitor.last_seen = time.time()
                    command = monitor.command if not monitor.delivered else None
                    if command:
                        monitor.delivered = True
                    self.send(200, {'command': command, 'token': monitor.token})

            def do_POST(self):
                if self.path != '/result' or self.headers.get('X-Mention-Token') != monitor.token:
                    return self.send(403, {})
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if not 0 < size <= 1024 * 1024:
                        raise ValueError('无效的消息长度')
                    payload = json.loads(self.rfile.read(size))
                    monitor.accept(payload)
                    self.send(200, {'ok': True})
                except (ValueError, TypeError) as exc:
                    self.send(400, {'error': str(exc)})

        self.transport = http.server.ThreadingHTTPServer(('127.0.0.1', 18766), Handler)
        threading.Thread(target=self.transport.serve_forever, daemon=True).start()

    def accept(self, payload):
        with self.lock:
            if not self.enabled or not self.command or payload.get('id') != self.command['id']:
                raise ValueError('监听任务已停止或响应过期')
            if self.command['action'] == 'replyMention':
                self.reply_outcome = payload
                self.command = None
                return
            self.command = None
            if not payload.get('ok'):
                self.error = str(payload.get('error') or '扩展读取失败')
                return
            # Never advance a baseline or enqueue work from a failed refresh/old cache.
            self.request_state = dict(source='request', fresh=payload.get('fresh') is True,
                                      last_success=payload.get('last_success'),
                                      diagnostics=self._safe_diagnostics(payload.get('diagnostics')))
            if payload.get('fresh') is not True or payload.get('ready') is not True:
                self.error = str(payload.get('warning') or '本次通知请求未成功，未处理缓存通知')
                return
            items = payload.get('items')
            if not isinstance(items, list) or len(items) > 500:
                raise ValueError('无效的通知列表')
            account = str(payload.get('account_id') or '')
            if not account.isdigit():
                self.error = '未捕获当前登录账号 ID，请刷新个人主页并打开通知'
                return
            if account != self.account_id:
                self.account_id = account
                self.baseline = True
            with self.db() as db:
                checkpoint = db.execute('SELECT observed_at FROM mention_checkpoints WHERE account_id=?', (account,)).fetchone()
            cutoff = checkpoint[0] if self.baseline and checkpoint else self.listen_started_at
            # No guessing IDs: a notification must identify both the video and original comment.
            for item in items:
                if not isinstance(item, dict):
                    continue
                aweme, comment = str(item.get('work_id', '')), str(item.get('comment_id', ''))
                if not aweme.isdigit() or not comment.isdigit():
                    self.error = '有 @通知缺少作品或原评论 ID，已跳过'
                    continue
                key = f'{account}:{aweme}:{comment}'
                with self.db() as db:
                    if db.execute('SELECT 1 FROM mentions WHERE id=?', (key,)).fetchone():
                        continue
                try:
                    source_time = float(item.get('source_timestamp') or 0)
                except (ValueError, TypeError):
                    source_time = 0
                if not math.isfinite(source_time) or source_time < 0:
                    source_time = 0
                existing = ((self.baseline and not checkpoint) or
                            (source_time > 0 and source_time <= cutoff) or
                            (self.baseline and source_time <= 0))
                row = dict(id=key, work_id=aweme, comment_id=comment, account_id=account,
                           parent_id=str(item.get('parent_id') or ''),
                           text=str(item.get('text') or '')[:2000], author=str(item.get('author') or '')[:100],
                           source_url=f'https://www.douyin.com/video/{aweme}',
                           status='baseline' if existing else 'pending', session=self.session,
                           source='request', source_timestamp=source_time,
                           auto_reply=self.auto_reply, created_at=time.time(), reply='', error='')
                row['queued_at'] = row['created_at']
                self.save(row)
            # Persist only after a fresh, verified snapshot has been fully saved.
            with self.db() as db:
                db.execute('INSERT INTO mention_checkpoints VALUES (?,?) ON CONFLICT(account_id) DO UPDATE SET observed_at=max(observed_at,excluded.observed_at)',
                           (account, time.time()))
            if payload.get('ready') and str(payload.get('account_id') or '').isdigit():
                self.baseline = False
                self.error = str(payload.get('warning') or '')
            else:
                self.error = str(payload.get('warning') or '尚未捕获通知数据，请刷新个人主页并打开通知 → @我的')

    @staticmethod
    def _safe_diagnostics(value):
        if not isinstance(value, list):
            return []
        allowed = {'path', 'method', 'transport', 'time', 'ok', 'http_status', 'status_code',
                   'recognized', 'item_count', 'skipped_count', 'has_more', 'error',
                   'request_fields', 'response_fields', 'response_schema', 'mention_samples'}
        result = []
        for row in value[-8:]:
            if not isinstance(row, dict):
                continue
            clean = {key: val for key, val in row.items() if key in allowed}
            # Defense at the persistence boundary: never accept full URLs, headers or bodies.
            clean['path'] = str(clean.get('path') or '').split('?', 1)[0][:200]
            result.append(clean)
        return result

    @staticmethod
    def _pending_rows(db):
        rows = [json.loads(raw) for (raw,) in db.execute('SELECT data FROM mentions')]
        return sorted((r for r in rows if r['status'] == 'pending'),
                      key=lambda r: (r.get('queued_at', r.get('created_at', 0)), r['id']))

    def dispatch_next(self):
        """One durable FIFO consumer; notification capture remains independent."""
        with self.lock:
            if not self.enabled or self.baseline or not self.account_id:
                return
            if self.worker is not None and self.worker.is_alive():
                self.prepare_next()
                return
            with self.db() as db:
                row = next((r for r in self._pending_rows(db) if r['account_id'] == self.account_id), None)
            if row is None:
                return
            if self.inference_health.get('next_probe', 0) > time.time():
                message = '等待模型服务恢复，队列已暂停；恢复验证通过后自动继续'
                if row.get('progress') != message:
                    row['progress'] = message
                    self.save(row)
                return
            if row['id'] == self.preparing_id:
                return
            # Resume only never-started work after the logged-in account is verified.
            row.update(session=self.session, status='running', progress='已出队，开始视频分析')
            self.save(row)
            self.worker = threading.Thread(target=self.process, args=(row,), daemon=True)
            self.worker.start()

    def prepare_next(self):
        if self.inference_health:
            return
        if not self.agent or not hasattr(self.agent, 'prepare'):
            return
        if self.preparer is not None and self.preparer.is_alive():
            return
        with self.db() as db:
            row = next((r for r in self._pending_rows(db) if r['account_id'] == self.account_id
                        and r.get('preparation_status') not in {'done', 'error'}), None)
        if row is None:
            return
        row.update(preparation_status='running', progress='提前下载视频，LLM 等待排队')
        self.save(row)
        self.preparing_id = row['id']
        def prepare():
            try:
                def progress(message, *_):
                    with self.lock:
                        with self.db() as db:
                            current = json.loads(db.execute('SELECT data FROM mentions WHERE id=?', (row['id'],)).fetchone()[0])
                        if current['status'] != 'pending':
                            raise RuntimeError('任务已取消，停止下载准备')
                        row['progress'] = '下载准备：' + message
                        self.save(row)
                self.agent.prepare(row, self.root / row['task_directory'], progress)
                row.update(preparation_status='done', progress='视频已下载，等待 LLM 处理')
            except Exception as exc:
                row.update(preparation_status='error', preparation_error=str(exc), progress='提前下载失败，处理时重试')
            finally:
                with self.lock:
                    with self.db() as db:
                        current = json.loads(db.execute('SELECT data FROM mentions WHERE id=?', (row['id'],)).fetchone()[0])
                    if current['status'] == 'pending':
                        self.save(row)
                    self.preparing_id = None
        self.preparer = threading.Thread(target=prepare, daemon=True)
        self.preparer.start()

    def _loop(self):
        while True:
            time.sleep(1)
            try:
                self.try_autostart()
                with self.lock:
                    if not self.enabled:
                        continue
                    if self.command and time.time() - self.last_poll > 90:
                        self.error = '扩展读取通知超时，请重载扩展并保持已登录的个人主页打开'
                        self.command = None
                    if not self.command and time.time() - self.last_poll >= self.interval:
                        self.command = {'id': uuid.uuid4().hex, 'action': 'collectMentions', 'session': self.session}
                        self.delivered = False
                        self.last_poll = time.time()
                self.dispatch_next()
            except Exception as exc:
                with self.lock:
                    self.error = str(exc)

    def process(self, row):
        try:
            row.update(status='running')
            self.save(row)
            root = self.root / row['task_directory']
            row['task_directory'] = root.name
            def progress(message, *_):
                row['progress'] = message
                self.save(row)
            if self.agent:
                from services.douyin.video_understanding import _analysis_lock
                # The MCP subprocess has its own lock; arbitrate manual analysis here.
                with _analysis_lock:
                    if self.inference_health:
                        try:
                            self.agent.check_health(progress)
                        except Exception as exc:
                            self.defer_inference_failure(row, exc, probe=True)
                            return
                        self.save_inference_health({})
                    row['analysis'], row['reply'] = self.agent.run(row, root, progress)
            else:
                row['analysis'] = self.analyze(row['source_url'], root, progress)
                progress('视频分析完成，正在生成评论回复')
                row['reply'] = self.reply(row['analysis'])
            with self.lock:
                if not self.enabled or self.session != row['session']:
                    row.update(status='cancelled', error='监听停止，未发送回复')
                elif row['account_id'] != self.account_id:
                    row.update(status='cancelled', error='登录账号已切换，未发送回复')
                elif not row['auto_reply']:
                    row.update(status='draft')
                else:
                    # Dispatch once. Ambiguous transport errors must never trigger automatic resend.
                    row.update(status='sending')
                    self.save(row)
                    self.command = dict(id=uuid.uuid4().hex, action='replyMention', workId=row['work_id'],
                                        replyId=row['comment_id'], parentId=row.get('parent_id', ''),
                                        accountId=row['account_id'], comment=row['reply'])
                    self.delivered = False
                    self.last_poll = time.time()
                    command_id = self.command['id']
            if row['status'] == 'sending':
                deadline = time.time() + 90
                while time.time() < deadline:
                    time.sleep(1)
                    with self.lock:
                        if not self.command or self.command['id'] != command_id:
                            outcome = getattr(self, 'reply_outcome', {})
                            if outcome.get('id') != command_id or not outcome.get('ok'):
                                raise RuntimeError(outcome.get('error') or '发送结果未知，请人工核对原评论；不会自动重发')
                            row.update(status='done', response=outcome)
                            break
                else:
                    raise RuntimeError('回复超时，结果未知；请人工核对，不会自动重发')
            self.save(row)
        except Exception as exc:
            if row.get('status') != 'sending' and self.agent and self.defer_inference_failure(row, exc):
                return
            row.update(status='error', error=str(exc))
            self.save(row)
        finally:
            if self.on_processed and row.get('analysis'):
                try:
                    self.on_processed(self.root / row['task_directory'], row)
                except Exception as exc:
                    with self.lock:
                        self.error = '保存 @评论解析历史失败：' + str(exc)
