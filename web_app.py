#!/usr/bin/env python3
"""Unified frontend gateway for independently deployable tab services."""

from __future__ import annotations

import argparse
import http.server
import json
import signal
import subprocess
import sys
from urllib import error as urlerror
from urllib import request as urlrequest
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
        if self.proxy_tab_request():
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

    def do_POST(self) -> None:
        if self.proxy_tab_request():
            return
        self.send_error(404)

    def do_PATCH(self) -> None:
        if self.proxy_tab_request():
            return
        self.send_error(404)

    def do_DELETE(self) -> None:
        if self.proxy_tab_request():
            return
        self.send_error(404)

    def proxy_tab_request(self) -> bool:
        """Forward a same-origin /tabs/<id>/ request to its Tab service."""
        path = urlsplit(self.path).path
        prefix = "/tabs/"
        if not path.startswith(prefix):
            return False
        remainder = path[len(prefix):]
        tab_id, separator, service_path = remainder.partition("/")
        tabs = {tab.id: tab for tab in public_tabs_for_proxy()}
        tab = tabs.get(tab_id)
        if not tab:
            self.send_error(404)
            return True
        target_path = "/" + service_path if separator and service_path else "/"
        target = f"http://127.0.0.1:{tab.port}{target_path}"
        query = urlsplit(self.path).query
        if query:
            target += "?" + query
        body = None
        if self.command in {"POST", "PATCH", "PUT"}:
            length = int(self.headers.get("content-length", "0"))
            body = self.rfile.read(length)
        headers = {}
        for name in ("content-type", "accept", "range"):
            value = self.headers.get(name)
            if value:
                headers[name] = value
        try:
            response = urlrequest.urlopen(urlrequest.Request(target, data=body, headers=headers, method=self.command), timeout=300)
            response_body = response.read()
            response_body = self.rewrite_tab_asset_paths(response_body, response.headers.get("content-type", ""), tab_id)
            self.send_response(response.status)
            self.copy_response_headers(response.headers, len(response_body))
            self.end_headers()
            self.wfile.write(response_body)
        except urlerror.HTTPError as exc:
            response_body = exc.read()
            response_body = self.rewrite_tab_asset_paths(response_body, exc.headers.get("content-type", ""), tab_id)
            self.send_response(exc.code)
            self.copy_response_headers(exc.headers, len(response_body))
            self.end_headers()
            self.wfile.write(response_body)
        except (OSError, urlerror.URLError) as exc:
            payload = json.dumps({"error": f"Tab service unavailable: {exc}"}).encode("utf-8")
            self.send_response(502)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
        return True

    @staticmethod
    def rewrite_tab_asset_paths(body: bytes, content_type: str, tab_id: str) -> bytes:
        if "text/html" not in content_type and "javascript" not in content_type:
            return body
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            return body
        prefix = f"/tabs/{tab_id}"
        text = text.replace('src="/assets/', f'src="{prefix}/assets/')
        text = text.replace("src='/assets/", f"src='{prefix}/assets/")
        # Service pages use root-relative URLs, while they are embedded below
        # /tabs/<id>/ on the gateway. Rewrite all quoted API URLs, including
        # ternary expressions such as kind === 'image' ? '/api/...'.
        text = text.replace("'/api/", f"'{prefix}/api/")
        text = text.replace('"/api/', f'"{prefix}/api/')
        return text.encode("utf-8")

    def copy_response_headers(self, headers: object, content_length: int) -> None:
        content_type = headers.get("content-type") if headers else None
        if content_type:
            self.send_header("content-type", content_type)
        self.send_header("content-length", str(content_length))
        cache_control = headers.get("cache-control") if headers else None
        if cache_control:
            self.send_header("cache-control", cache_control)
        for name in ("content-range", "accept-ranges", "content-disposition"):
            value = headers.get(name) if headers else None
            if value:
                self.send_header(name, value)

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


def public_tabs_for_proxy():
    """Return all registered tabs, including private ones for internal proxying."""
    from services.core.registry import TABS
    return TABS


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
