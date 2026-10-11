from __future__ import annotations

import contextlib
import http.server
import json
import socket
import threading
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
GENERATION_JS = ROOT / "services" / "video_creator" / "generation.js"


ASSETS = [
    {"id": "image-done", "kind": "image", "status": "done", "prompt": "图片资产", "params": {}},
    {"id": "video-running", "kind": "video", "status": "running", "progress": 42, "prompt": "视频任务", "params": {}},
    {"id": "ai-done", "kind": "ai_video", "status": "done", "prompt": "AI 视频资产", "params": {}, "nodes": []},
    {"id": "child", "kind": "video", "status": "done", "parent_job": "ai-done", "prompt": "子任务", "params": {}},
]
LIBRARY_ASSETS = [{"id": "pig", "name": "猪八戒", "kind": "character", "content_hash": "1234567890abcdef", "href": "/pig.png", "description": {"prompt": "旧 Prompt"}}]


FIXTURE = """<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<style>
body{margin:0;background:#f7f8fa;color:#182230;font:14px sans-serif}
main{max-width:980px;margin:auto;padding:28px}.tool{background:#fff;border:1px solid #ddd;padding:20px}
label{display:block;margin:10px 0}input,select{width:100%}button{padding:8px 12px}
</style></head><body><main><h1>视频创作</h1><p>测试工作台</p>
<section class="tool"><h2>视频抽帧</h2><form><input type="file"></form></section>
<section class="tool"><h2>抽帧结果</h2></section>
</main><script src="/generation.js"></script></body></html>"""


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/":
            return self.send_content("text/html; charset=utf-8", FIXTURE.encode())
        if path == "/generation.js":
            return self.send_content("text/javascript; charset=utf-8", GENERATION_JS.read_bytes())
        if path == "/api/assets":
            return self.send_json({"assets": ASSETS})
        if path == "/api/library-assets":
            return self.send_json({"assets": LIBRARY_ASSETS})
        if path == "/api/models":
            return self.send_json({})
        if path == "/api/providers":
            return self.send_json({"providers": []})
        self.send_error(404)

    def do_POST(self):
        if urlsplit(self.path).path == "/api/library-assets/pig/regenerate":
            return self.send_json({"ok": True, "jobId": "improved-pig"})
        self.send_error(404)

    def send_json(self, value):
        self.send_content("application/json", json.dumps(value).encode())

    def send_content(self, content_type: str, body: bytes):
        self.send_response(200)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@contextlib.contextmanager
def fixture_server():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), FixtureHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class GenerationAssetUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def test_assets_have_a_separate_entry_filters_and_status_badges(self):
        with fixture_server() as url:
            page = self.browser.new_page(viewport={"width": 1280, "height": 720})
            try:
                page.goto(url)
                page.locator(".asset-card").first.wait_for(state="attached")

                self.assertFalse(page.locator('[data-view="assets"]').is_visible())
                self.assertEqual(page.locator("[data-asset-running]").inner_text(), "1")
                self.assertEqual(page.locator("[data-asset-done]").inner_text(), "2")

                page.locator(".asset-button").click()
                self.assertTrue(page.locator('[data-view="assets"]').is_visible())
                self.assertEqual(page.locator('[data-view="assets"] h2').inner_text(), "草稿箱")
                self.assertFalse(page.locator('[data-view="image"]').is_visible())

                cases = [("生图", "image"), ("生视频", "video"), ("AI 视频", "ai_video")]
                for label, kind in cases:
                    page.locator("[data-asset-filter]", has_text=label).click()
                    visible = page.locator(".asset-card:visible")
                    self.assertEqual(visible.count(), 1)
                    self.assertEqual(visible.get_attribute("data-kind"), kind)

                page.locator('[data-tool="library"]').click()
                self.assertTrue(page.locator('[data-view="library"]').is_visible())
                self.assertEqual(page.locator('[data-view="library"] h2').inner_text(), "资产")
            finally:
                page.close()

    def test_restored_running_draft_refreshes_without_page_reload(self):
        running = next(item for item in ASSETS if item["id"] == "video-running")
        original = dict(running)
        with fixture_server() as url:
            page = self.browser.new_page(viewport={"width": 1280, "height": 720})
            try:
                page.goto(url)
                card = page.locator('[data-job-id="video-running"]')
                card.wait_for(state="attached")
                running.update(status="done", progress=100, message="生成完成", outputs=[])
                page.wait_for_function("document.querySelector('[data-job-id=video-running] h3').textContent.includes('完成')", timeout=7000)
            finally:
                running.clear()
                running.update(original)
                page.close()

    def test_asset_editor_exposes_prompt_and_reference_regeneration(self):
        with fixture_server() as url:
            page = self.browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                page.goto(url)
                page.locator('[data-tool="library"]').click()
                page.get_by_role("button", name="编辑").click()
                self.assertEqual(page.locator('[data-regenerate] textarea[name="prompt"]').input_value(), "旧 Prompt")
                self.assertEqual(page.locator('[data-regenerate] input[name="reference_image"]').get_attribute("accept"), "image/*")
                self.assertTrue(page.get_by_role("button", name="开始生成改良版").is_visible())
            finally:
                page.close()

    def test_creation_forms_support_multiple_asset_ids_and_prompt_tokens(self):
        with fixture_server() as url:
            page = self.browser.new_page(viewport={"width": 1280, "height": 800})
            try:
                page.goto(url)
                page.locator('[data-tool="video"]').click()
                picker = page.locator('[data-form="video"] .asset-picker')
                picker.locator('.asset-picker-toggle').click()
                picker.locator('input[value="pig"]').check()
                self.assertEqual(page.locator('[data-form="video"] [name="library_asset_ids"]').input_value(), '["pig"]')
                self.assertIn("<asset:pig>", page.locator('[data-form="video"] [name="prompt"]').input_value())
                self.assertEqual(picker.locator('.asset-picker-toggle').inner_text(), "已选 1 个素材")
                page.locator('[data-tool="ai_video"]').click()
                ai_picker=page.locator('[data-form="ai_video"] .asset-picker')
                ai_picker.locator('.asset-picker-toggle').click()
                page.locator('[data-form="ai_video"] [name="confirm_assets"]').check()
                ai_picker.locator('input[value="pig"]').check()
                self.assertTrue(page.locator('[data-form="ai_video"] [name="confirm_assets"]').is_checked())
                self.assertFalse(page.locator('[data-form="ai_video"] [name="confirm_assets"]').is_disabled())
            finally:
                page.close()

    def test_asset_confirmation_requires_every_item_and_fits_card(self):
        awaiting = {
            "id": "ai-awaiting", "kind": "ai_video",
            "status": "awaiting_asset_confirmation", "prompt": "资产确认测试",
            "params": {}, "nodes": [],
            "asset_requirements": [
                {"entity_id": "hero", "kind": "character", "name": "主角", "current_action": "regenerate", "candidates": [{"id": "pig", "name": "猪八戒", "kind": "character", "href": "/pig.png"}]},
                {"entity_id": "room", "kind": "location", "name": "房间", "current_action": "regenerate", "candidates": []},
                {"entity_id": "key", "kind": "prop", "name": "钥匙", "current_action": "regenerate", "candidates": []},
            ],
        }
        ASSETS.append(awaiting)
        try:
            with fixture_server() as url:
                page = self.browser.new_page(viewport={"width": 720, "height": 900})
                try:
                    page.goto(url)
                    card = page.locator('[data-job-id="ai-awaiting"]')
                    card.wait_for(state="attached")
                    page.locator(".asset-button").click()
                    card.wait_for(state="visible")
                    card.locator("[data-asset-confirm]").wait_for(state="attached")
                    submit = card.locator('[data-asset-confirm] button[type="submit"]')
                    groups = card.locator("fieldset[data-entity-id]")
                    self.assertEqual(groups.count(), 3)
                    self.assertFalse(submit.is_enabled())
                    self.assertEqual(card.locator(".asset-confirm-progress").inner_text(), "已选择 0 / 3")
                    self.assertEqual(groups.nth(0).locator(".asset-confirm-option").count(), 3)
                    self.assertEqual(groups.nth(0).locator('img[alt="猪八戒参考图"]').count(), 1)
                    fits = groups.evaluate_all("els => els.every(el => el.getBoundingClientRect().right <= el.closest('.asset-card').getBoundingClientRect().right)")
                    self.assertTrue(fits)

                    groups.nth(0).locator('input[value="reuse:pig"]').check()
                    self.assertFalse(submit.is_enabled())
                    self.assertEqual(card.locator(".asset-confirm-progress").inner_text(), "已选择 1 / 3")
                    page.wait_for_timeout(3500)
                    self.assertTrue(groups.nth(0).locator('input[value="reuse:pig"]').is_checked())

                    for index in (1, 2):
                        groups.nth(index).locator('input[value="regenerate"]').check()
                    self.assertTrue(submit.is_enabled())
                    self.assertEqual(card.locator(".asset-confirm-progress").inner_text(), "已选择 3 / 3")

                    panel_box = card.locator(".asset-confirm-panel").bounding_box()
                    group_box = groups.nth(0).bounding_box()
                    self.assertLessEqual(group_box["x"] + group_box["width"], panel_box["x"] + panel_box["width"] + 1)
                finally:
                    page.close()
        finally:
            ASSETS.remove(awaiting)


if __name__ == "__main__":
    unittest.main()
