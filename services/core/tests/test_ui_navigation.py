from __future__ import annotations

import contextlib
import http.server
import json
import socket
import threading
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
FRONTEND = ROOT / "frontend"


class DemoHandler(http.server.BaseHTTPRequestHandler):
    tabs = [
        {"id": "douyin", "title": "抖音工具", "description": "抖音内容", "url": "/tabs/douyin/"},
        {"id": "video-creator", "title": "AI创作工具", "description": "AI 内容", "url": "/tabs/video-creator/"},
        {"id": "admin", "title": "后台控制", "description": "系统配置", "url": "/tabs/admin/"},
    ]

    def log_message(self, *_args):
        return

    def do_GET(self):
        if self.path.startswith("/api/tabs"):
            return self.send_content("application/json", json.dumps({"tabs": self.tabs}).encode())
        if self.path == "/" or self.path.startswith("/index.html"):
            return self.send_content("text/html; charset=utf-8", (FRONTEND / "index.html").read_bytes())
        if self.path == "/assets/styles.css":
            return self.send_content("text/css; charset=utf-8", (FRONTEND / "assets" / "styles.css").read_bytes())
        if self.path == "/assets/app.js":
            return self.send_content("text/javascript; charset=utf-8", (FRONTEND / "assets" / "app.js").read_bytes())
        if self.path.startswith("/tabs/"):
            tab_id = self.path.strip("/").split("/")[-1]
            title = next(item["title"] for item in self.tabs if item["id"] == tab_id)
            body = f"<!doctype html><html><body><h1>{title}内容</h1><div style='height:1200px'>测试内容</div></body></html>"
            return self.send_content("text/html; charset=utf-8", body.encode("utf-8"))
        self.send_error(404)

    def send_content(self, content_type: str, body: bytes):
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def demo_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), DemoHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class NavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.page = self.browser.new_page(viewport={"width": 1280, "height": 720})

    def tearDown(self):
        self.page.close()

    def test_primary_tabs_show_exactly_one_matching_frame(self):
        with demo_server() as url:
            self.page.goto(url)
            cases = [
                ("抖音工具", "douyin"),
                ("AI创作工具", "video-creator"),
                ("后台控制", "admin"),
                ("抖音工具", "douyin"),
            ]
            for label, tab_id in cases:
                self.page.get_by_role("button", name=label).click()
                self.page.wait_for_selector(f'iframe[src="/tabs/{tab_id}/"]')
                visible = self.page.locator("iframe:not([hidden])")
                self.assertEqual(visible.count(), 1)
                self.assertEqual(visible.get_attribute("src"), f"/tabs/{tab_id}/")
                self.assertEqual(self.page.title(), f"{label} · Douyin Studio")
                self.assertEqual(self.page.locator(".tab.active").inner_text(), label)
                self.assertTrue(visible.content_frame.locator("h1").inner_text().startswith(label))

            hidden_frames = self.page.locator("iframe[hidden]")
            self.assertEqual(hidden_frames.count(), 2)
            for index in range(hidden_frames.count()):
                self.assertEqual(hidden_frames.nth(index).evaluate("el => getComputedStyle(el).display"), "none")

    def test_outer_shell_does_not_create_a_second_scrollbar(self):
        with demo_server() as url:
            self.page.goto(url)
            metrics = self.page.evaluate(
                """() => ({
                    viewport: innerHeight,
                    html: document.documentElement.scrollHeight,
                    body: document.body.scrollHeight,
                    workspace: document.querySelector('#workspace').clientHeight,
                    frame: document.querySelector('iframe:not([hidden])').clientHeight
                })"""
            )
            self.assertEqual(metrics["html"], metrics["viewport"])
            self.assertEqual(metrics["body"], metrics["viewport"])
            self.assertEqual(metrics["workspace"], metrics["frame"])
            self.assertEqual(metrics["workspace"], metrics["viewport"])
            self.assertEqual(self.page.locator(".commandbar").count(), 0)


if __name__ == "__main__":
    unittest.main()
