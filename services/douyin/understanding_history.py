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
        payload.update(history_id=identifier, video={"href": "/downloads/" + quote(video, safe="/")},
                       report={"href": "/downloads/" + quote(relative + "/report.md", safe="/")},
                       summary_report={"href": "/downloads/" + quote(relative + "/summary.json", safe="/")})
        payload.pop("video_file", None)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO understanding_history VALUES (?,?,?,?,?,?,?,?)", (
                identifier, trace.get("nodes", [{}])[0].get("started_at", time.time()), result["source_url"],
                result["title"], relative + "/report.md", markdown, video, json.dumps(payload, ensure_ascii=False)))
        return payload

    def list(self, limit=30, offset=0):
        with self.connect() as db:
            db.row_factory = sqlite3.Row
            rows = db.execute("SELECT id,created_at,title,source_url FROM understanding_history ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
            total = db.execute("SELECT count(*) FROM understanding_history").fetchone()[0]
        return {"items": [dict(row) for row in rows], "total": total}

    def get(self, identifier):
        with self.connect() as db:
            row = db.execute("SELECT result_json FROM understanding_history WHERE id=?", (identifier,)).fetchone()
        return json.loads(row[0]) if row else None

    def backfill(self):
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
