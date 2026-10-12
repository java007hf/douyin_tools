"""Persistent understanding records and deterministic process reports."""
import html
import json
import sqlite3
import time
from pathlib import Path
from urllib.parse import quote


def report_sections(root, result, trace):
    def read(name):
        path = root / name
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    stamp = lambda value: f"{int(value)//60}:{int(value)%60:02d}"
    sections = [
        ("内容摘要", result["summary"]),
        ("核心观点", "\n".join("- " + p for p in result.get("key_points", []))),
        ("时间线", "\n".join(f"- {stamp(p['seconds'])}：{p['content']}" for p in result.get("timeline", []))),
        ("理解范围", "\n".join("- " + p for p in result.get("limitations", []))),
        ("执行阶段", "\n".join(f"{p['name']} · {p['status']} · {p.get('ended_at', p['started_at'])-p['started_at']:.1f} 秒" for p in trace.get("nodes", []))),
        ("完整音频转写（ASR 识别结果，可能有错词或遗漏）", "\n".join(f"[{stamp(p['start'])}–{stamp(p['end'])}] {p['text']}" for p in result.get("transcript", [])) or "未识别到语音。"),
        ("画面识别中间结果", json.dumps(read("observations.json"), ensure_ascii=False, indent=2)),
        ("音频分段归纳中间结果", json.dumps(read("speech_notes.json"), ensure_ascii=False, indent=2)),
    ]
    if result.get('record_source') == 'mention':
        sections.insert(0, ('@评论回复', f"回复对象：{result.get('reply_username', '')}\n处理状态：{result.get('reply_status', '')}\n回复正文：{result.get('reply_text', '')}\n错误：{result.get('reply_error', '')}"))
    return sections


def write_report(root, result, trace):
    lines = ["# 视频理解报告", "", f"## {result['title']}", "",
             f"来源：{result['source_url']}", "", f"分类：{result['format']} / {result['topic']}", "",
             f"视频时长：{result['duration_seconds']} 秒；采样画面：{result['frame_count']} 张；模型：{result['model']}", "",
             f"语音模型：{result.get('transcription_model', '未记录')}；依据：{result.get('summary_basis', '未记录')}", "",
             f"[缓存视频]({trace['artifacts']['video']})", ""]
    for title, body in report_sections(root, result, trace):
        lines += ["## " + title, "", body if "中间结果" not in title else "```json\n" + body + "\n```", ""]
    lines += ["## 采样画面", ""]
    for index, frame in enumerate(trace["artifacts"].get("frames", [])):
        lines += [f"![采样画面 {index+1}]({frame})", ""]
    text = "\n".join(lines)
    temp = root / "report.md.tmp"
    temp.write_text(text, encoding="utf-8")
    temp.replace(root / "report.md")
    return text


def render_report(root, result, trace, download_prefix):
    esc = lambda value: html.escape(str(value), quote=True)
    body = [f"<h1>{esc(result['title'])}</h1>", f"<p>{esc(result['format'])} / {esc(result['topic'])} · {esc(result['duration_seconds'])} 秒 · {esc(result['model'])}</p>",
            f"<p>来源：{esc(result['source_url'])}</p>"]
    for title, text in report_sections(root, result, trace):
        body += [f"<h2>{esc(title)}</h2><pre>{esc(text)}</pre>"]
    body.append("<h2>采样画面</h2>")
    for frame in trace["artifacts"].get("frames", []):
        body.append(f'<img loading="lazy" alt="采样画面" src="{esc(download_prefix + quote(frame, safe="/"))}">')
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><style>body{font:16px/1.8 system-ui;margin:24px;color:#23384b;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}img{max-width:100%;display:block;margin:16px 0}h2{margin-top:32px}</style>' + "".join(body) + "</html>"


class UnderstandingHistory:
    def __init__(self, path, download_root):
        self.path = Path(path)
        self.download_root = Path(download_root).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS understanding_history (
                id TEXT PRIMARY KEY, created_at REAL NOT NULL, source_url TEXT NOT NULL,
                title TEXT NOT NULL, report_file TEXT NOT NULL, report_markdown TEXT NOT NULL,
                video_cache_file TEXT NOT NULL, result_json TEXT NOT NULL)""")
            db.execute("CREATE TABLE IF NOT EXISTS deleted_understanding_history (id TEXT PRIMARY KEY)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def update_manual(self, root, source_url, status, progress='', error=''):
        identifier = Path(root).name
        payload = {'history_id': identifier, 'source_url': source_url,
                   'title': '视频理解任务', 'record_source': 'manual',
                   'reply_status': status, 'progress': progress,
                   'reply_error': error, 'analysis_ready': False}
        with self.connect() as db:
            if db.execute('SELECT 1 FROM deleted_understanding_history WHERE id=?', (identifier,)).fetchone():
                return
            db.execute('INSERT INTO understanding_history VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET result_json=excluded.result_json',
                       (identifier, time.time(), source_url, payload['title'], '', '', '', json.dumps(payload, ensure_ascii=False)))

    def interrupt_manual_tasks(self):
        with self.connect() as db:
            for identifier, raw in db.execute('SELECT id,result_json FROM understanding_history').fetchall():
                payload = json.loads(raw)
                if payload.get('record_source') == 'manual' and payload.get('reply_status') in ('pending', 'running'):
                    payload.update(reply_status='error', reply_error='服务重启，任务已中断', progress='已中断')
                    db.execute('UPDATE understanding_history SET result_json=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), identifier))

    def save(self, root, result):
        root = Path(root).resolve()
        relative = root.relative_to(self.download_root).as_posix()
        video = str(result.get("video_file") or result.get("video", {}).get("href", "").removeprefix("/downloads/"))
        if result.get("video_file"):
            video = relative + "/" + video
        (self.download_root / video).resolve().relative_to(self.download_root)
        identifier = root.name
        trace = json.loads((root / "task.json").read_text(encoding="utf-8"))
        markdown = write_report(root, result, trace)
        payload = dict(result)
        payload.update(history_id=identifier, artifact_directory=relative, video={"href": "/downloads/" + quote(video, safe="/")},
                       report={"href": "/downloads/" + quote(relative + "/report.md", safe="/")},
                       summary_report={"href": "/downloads/" + quote(relative + "/summary.json", safe="/")})
        payload.pop("video_file", None)
        with self.connect() as db:
            if db.execute('SELECT 1 FROM deleted_understanding_history WHERE id=?', (identifier,)).fetchone():
                return payload
            db.execute("INSERT INTO understanding_history VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,report_file=excluded.report_file,video_cache_file=excluded.video_cache_file,report_markdown=excluded.report_markdown,result_json=excluded.result_json", (
                identifier, trace.get("nodes", [{}])[0].get("started_at", time.time()), result["source_url"],
                result["title"], relative + "/report.md", markdown, video, json.dumps(payload, ensure_ascii=False)))
        return payload

    def list(self, limit=30, offset=0):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT id,created_at,title,source_url,result_json FROM understanding_history ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            total = db.execute("SELECT count(*) FROM understanding_history").fetchone()[0]
            pending = []
            for entry in db.execute('SELECT id,created_at,result_json FROM understanding_history ORDER BY created_at,id'):
                if json.loads(entry['result_json']).get('reply_status') == 'pending':
                    pending.append(entry['id'])
            positions = {identifier: index + 1 for index, identifier in enumerate(pending)}
        items = []
        for row in rows:
            item = dict(row)
            result = json.loads(item.pop('result_json'))
            item.update(record_source=result.get('record_source', 'manual'), reply_username=result.get('reply_username', ''), reply_status=result.get('reply_status', ''), progress=result.get('progress', ''), reply_error=result.get('reply_error', ''))
            item['queue_position'] = positions.get(item['id'])
            items.append(item)
        return {"items": items, "total": total}

    def save_mention(self, root, row):
        result = row.get('analysis')
        metadata = {'record_source': 'mention', 'reply_username': row.get('author', ''),
                    'reply_status': row['status'], 'reply_text': row.get('reply', ''),
                    'reply_error': row.get('error', ''), 'mention_id': row['id'],
                    'agent_plan': row.get('agent_plan', {}), 'progress': row.get('progress', '')}
        if not result or not (root / 'task.json').exists():
            payload = {**metadata, 'history_id': root.name, 'title': '@视频处理', 'source_url': row['source_url'], 'analysis_ready': False}
            with self.connect() as db:
                if db.execute('SELECT 1 FROM deleted_understanding_history WHERE id=?', (root.name,)).fetchone():
                    return
                db.execute('INSERT INTO understanding_history VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET result_json=excluded.result_json',
                    (root.name, row.get('created_at', time.time()), row['source_url'], payload['title'], '', '', '', json.dumps(payload, ensure_ascii=False)))
            return
        self.save(root, {**result, **metadata, 'analysis_ready': True})

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM understanding_history WHERE id=?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def backfill(self):
        mentions = self.download_root / 'mentions'
        if (mentions / 'mentions.sqlite3').exists():
            with sqlite3.connect(mentions / 'mentions.sqlite3', timeout=30) as db:
                rows = db.execute('SELECT data FROM mentions').fetchall()
            for (raw,) in rows:
                row = json.loads(raw)
                if row.get('task_directory'):
                    try:
                        self.save_mention(mentions / row['task_directory'], row)
                    except (ValueError, OSError, KeyError):
                        continue
        for file in (self.download_root / "understanding").glob("*/summary.json"):
            with self.connect() as db:
                if db.execute("SELECT 1 FROM deleted_understanding_history WHERE id=?", (file.parent.name,)).fetchone():
                    continue
            if self.get(file.parent.name):
                continue
            try:
                trace = json.loads((file.parent / "task.json").read_text(encoding="utf-8"))
                if trace.get("status") == "done":
                    self.save(file.parent, json.loads(file.read_text(encoding="utf-8")))
            except (ValueError, OSError, KeyError):
                continue

    def delete(self, identifier):
        with self.connect() as db:
            deleted = db.execute("DELETE FROM understanding_history WHERE id=?", (identifier,)).rowcount
            if deleted:
                db.execute("INSERT OR IGNORE INTO deleted_understanding_history VALUES (?)", (identifier,))
        return bool(deleted)
