#!/usr/bin/env python3
"""Unified frontend gateway for independently deployable tab services."""

from __future__ import annotations

import argparse
import http.server
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from services.core.registry import public_tabs


ROOT = Path(__file__).resolve().parent
FRONTEND = ROOT / "frontend"


class FrontendHandler(http.server.BaseHTTPRequestHandler):
    server_version = "DouyinWorkspace/0.1"

    def log_message(self, format: str, *args: object) -> None:
        return

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path == "/api/tabs":
            host = self.headers.get("host", "127.0.0.1:8003").split(":", 1)[0]
            body = __import__("json").dumps({"tabs": public_tabs(host, getattr(self.server, "include_admin", True))}, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path in ("/", "/index.html"):
            self.serve_file(FRONTEND / "index.html", "text/html; charset=utf-8")
            return
        if path.startswith("/assets/"):
            target = (FRONTEND / "assets" / path.removeprefix("/assets/")).resolve()
            try:
                target.relative_to((FRONTEND / "assets").resolve())
            except ValueError:
                self.send_error(403)
                return
            if target.is_file():
                content_type = "text/javascript; charset=utf-8" if target.suffix == ".js" else "text/css; charset=utf-8"
                self.serve_file(target, content_type)
                return
        self.send_error(404)

    def serve_file(self, target: Path, content_type: str) -> None:
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_services(args: argparse.Namespace) -> list[subprocess.Popen[bytes]]:
    cache_dir = Path(args.cache_dir).resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    service_host = args.service_host
    commands = [
        [sys.executable, str(ROOT / "services" / "douyin" / "service.py"), "--web", "--web-host", service_host, "--web-port", str(args.douyin_port), "--cache-dir", str(cache_dir / "douyin")],
        [sys.executable, str(ROOT / "services" / "video_creator" / "service.py"), "--host", service_host, "--port", str(args.video_port)],
        [sys.executable, str(ROOT / "services" / "admin" / "service.py"), "--host", service_host, "--port", "8103", "--cache-dir", str(cache_dir / "video_creator")],
    ]
    return [subprocess.Popen(command, cwd=ROOT) for command in commands]


def main() -> int:
    parser = argparse.ArgumentParser(description="Unified tab frontend")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--service-host", default="0.0.0.0")
    parser.add_argument("--douyin-port", type=int, default=8101)
    parser.add_argument("--video-port", type=int, default=8102)
    parser.add_argument("--cache-dir", type=Path, default=Path("cache"))
    parser.add_argument("--no-admin", action="store_true", help="Hide the private admin tab")
    parser.add_argument("--no-start-services", action="store_true", help="Use separately started tab services")
    args = parser.parse_args()
    children = [] if args.no_start_services else start_services(args)
    server = http.server.ThreadingHTTPServer((args.host, args.port), FrontendHandler)
    server.include_admin = not args.no_admin
    print(f"frontend listening=http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for child in children:
            child.terminate()
        for child in children:
            child.wait(timeout=5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
