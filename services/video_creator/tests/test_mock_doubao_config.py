import http.server
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib import request, error

from services.admin.service import Handler, FIXED_HTML
from services.video_creator.tools.ai.mock_doubao_config import MockDoubaoConfigStore


class ConfigTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[3] / "cache" / "tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "mock_doubao.json"
        self.initial = {"base_url": "https://api.doubao.com", "headers": {"x-tt-token": "old-secret", "Cookie": "old-cookie"},
                        "query": {"device_id": "private-device"},
                        "body": {"uplink_body": {"send_message_body": {"content": '{"text":"old"}'}}}}
        self.path.write_text(json.dumps(self.initial), encoding="utf-8")
        self.store = MockDoubaoConfigStore(self.path)

    def test_update_preserves_empty_credentials_and_body(self):
        public = self.store.save({"token": "", "cookie": "********", "headers": {"x-tt-token": "", "X-Argus": "new-signature"}})
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["headers"]["x-tt-token"], "old-secret")
        self.assertEqual(saved["body"], self.initial["body"])
        self.assertTrue(public["token_configured"])
        for secret in ("old-secret", "old-cookie", "new-signature", "private-device"):
            self.assertNotIn(secret, json.dumps(public))

    def test_case_insensitive_token_replacement(self):
        self.store.save({"token": "new-secret"})
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["headers"]["X-Tt-Token"], "new-secret")
        self.assertNotIn("x-tt-token", saved["headers"])

    def test_invalid_template_does_not_overwrite_existing(self):
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            self.store.save({"request_config": {"body": {"private": "secret"}}})
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(list(self.root.glob("*.tmp")), [])

    def test_initialize_with_full_template(self):
        self.path.unlink()
        self.assertFalse(self.store.public()["configured"])
        self.assertTrue(self.store.save({"request_config": self.initial})["configured"])

    def test_model_routes_roundtrip_and_invalid_alias_rejected(self):
        routes = {'mock_doubao_seedream_4_5': {'request': {'query': {'captured_model_field': 'fixture-only'}}}}
        self.store.save({'model_routes': routes})
        self.assertEqual(self.store.credentials()['model_routes'], routes)
        self.assertNotIn('model_routes', self.store.public())
        before = self.path.read_bytes()
        for invalid in ({'arbitrary': {'request': {'query': {'model': 'x'}}}},
                        {'mock_doubao_fake': {'request': {'body': {}}}}):
            with self.assertRaises(ValueError):
                self.store.save({'model_routes': invalid})
            self.assertEqual(self.path.read_bytes(), before)

    def test_admin_http_save_and_read_never_return_credentials(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.store_dir = self.root
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            req = request.Request(base + "/api/mock-doubao", data=json.dumps({"token": "new-secret"}).encode(), headers={"Content-Type": "application/json"})
            with request.urlopen(req) as response:
                result = response.read().decode()
                self.assertTrue(json.loads(result)["config"]["token_configured"])
                self.assertNotIn("secret", result)
            with request.urlopen(base + "/api/mock-doubao") as response:
                self.assertNotIn("secret", response.read().decode())
            with request.urlopen(base + "/api/mock-doubao/credentials") as response:
                credentials = json.load(response)
                self.assertEqual(credentials["token"], "new-secret")
                self.assertEqual(credentials["cookie"], "old-cookie")
                self.assertEqual(credentials["request_config"]["body"], self.initial["body"])
                self.assertEqual(response.headers["Cache-Control"], "no-store")
            bad = request.Request(base + "/api/mock-doubao", data=b'{"token":"private-secret",}', headers={"Content-Type": "application/json"})
            with self.assertRaises(error.HTTPError) as caught:
                request.urlopen(bad)
            self.assertNotIn("private-secret", caught.exception.read().decode())
            with request.urlopen(base + "/assets/mock_doubao.js") as response:
                self.assertIn(b"/api/mock-doubao", response.read())
        finally:
            server.shutdown()
            server.server_close()
            worker.join()
        self.assertIn('data-panel="mock-doubao"', FIXED_HTML)
        self.assertIn('id="mock-doubao-form"', FIXED_HTML)


if __name__ == "__main__":
    unittest.main()
