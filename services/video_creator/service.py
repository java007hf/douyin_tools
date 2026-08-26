#!/usr/bin/env python3
"""Independent placeholder service for the future video creation tab."""

from __future__ import annotations

import argparse
import http.server
import json
import uuid
from urllib.parse import urlsplit


HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>视频创作</title><style>
body{margin:0;background:#f7f8fa;color:#182230;font:14px Segoe UI,Microsoft YaHei,Arial,sans-serif}
main{max-width:900px;margin:0 auto;padding:28px}h1{margin:0 0 8px;font-size:24px}p{color:#667085}
form{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:22px;margin-top:22px}
label{display:block;margin:16px 0 7px;color:#475467}input,textarea{width:100%;box-sizing:border-box;border:1px solid #cfd6e0;border-radius:6px;padding:10px;font:inherit}
textarea{min-height:150px;resize:vertical}button{margin-top:20px;border:0;border-radius:6px;padding:11px 18px;background:#0f766e;color:#fff;font:inherit;cursor:pointer}
#status{margin-top:16px;white-space:pre-wrap;color:#475467}
</style></head><body><main><h1>视频创作</h1>
<p>上传参考视频并描述需要复刻的内容。生成引擎将在后续版本接入。</p>
<form id="form"><label for="reference">参考视频</label><input id="reference" type="file" accept="video/*" required>
<label for="brief">需要复刻的内容</label><textarea id="brief" placeholder="描述画面、节奏、文案、动作或其他要求" required></textarea>
<button type="submit">提交创作任务</button><div id="status"></div></form></main>
<script>
const form=document.querySelector('#form'), status=document.querySelector('#status');
form.addEventListener('submit', async (event)=>{event.preventDefault(); const file=document.querySelector('#reference').files[0];
status.textContent='正在提交...'; const body=new FormData(); body.append('reference',file); body.append('brief',document.querySelector('#brief').value);
try { const response=await fetch('/api/generate',{method:'POST',body}); const data=await response.json(); if(!response.ok) throw new Error(data.error||'提交失败'); status.textContent=data.message+'\\n任务 ID：'+data.jobId; }
catch(error){status.textContent=error.message;}});
</script></body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "VideoCreator/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def send_json(self, status: int, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("content-type", "application/json; charset=utf-8")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path in ("/", "/index.html"):
            body = HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/health":
            self.send_json(200, {"ok": True, "service": "video-creator"})
            return
        self.send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        if urlsplit(self.path).path != "/api/generate":
            self.send_json(404, {"error": "Not found"})
            return
        # Keep the contract ready for a real generation backend without
        # pretending that a video has been generated yet.
        length = int(self.headers.get("content-length", "0") or "0")
        if length <= 0:
            self.send_json(400, {"error": "请上传参考视频并填写复刻内容"})
            return
        self.rfile.read(length)
        job_id = uuid.uuid4().hex
        self.send_json(202, {
            "ok": True,
            "jobId": job_id,
            "status": "queued",
            "message": "创作任务已建立，视频生成引擎尚未接入。",
        })


def main() -> int:
    parser = argparse.ArgumentParser(description="Video creator tab service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8102)
    args = parser.parse_args()
    server = http.server.ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"video creator listening=http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
