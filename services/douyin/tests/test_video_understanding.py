import json
import shutil
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from services.douyin.service import WEB_HTML, WebJobStore
from services.douyin.video_understanding import (
    UnderstandingProvider, validate_config, transcript_chunks, understand_work, validate_summary,
)


TEST_CONFIG = {"base_url": "http://127.0.0.1:11434/v1", "model": "test-vision", "api_format": "ollama", "transcription_model": "small", "context_window": 32768}


class UnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.root = Path("cache/understanding_tests") / uuid.uuid4().hex
        self.root.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.root)

    def summary(self):
        return {"title": "预算", "format": "口播", "topic": "经济", "tags": ["消费"],
                "summary": "作者讲述预算管理。", "key_points": ["比较价格"],
                "timeline": [{"seconds": 2, "content": "比较价格"}], "limitations": ["抽帧采样"]}

    def test_transcript_chunks_keep_every_segment(self):
        segments = [{"start": i, "end": i + 1, "text": str(i) + "x" * 40} for i in range(20)]
        chunks = transcript_chunks(segments, 120)
        self.assertGreater(len(chunks), 1)
        for item in segments:
            self.assertIn(item["text"], "\n".join(chunks))

    def test_missing_configuration_never_falls_back(self):
        for config in (None, {}, {"model": "test"}, {**TEST_CONFIG, "model": ""}, {**TEST_CONFIG, "api_format": ""}):
            with self.assertRaises(ValueError):
                validate_config(config)

    def test_context_window_validation(self):
        self.assertEqual(validate_config({**TEST_CONFIG, "context_window": "65536"})["context_window"], 65536)
        for value in (0, 300000, "bad", "32768.5"):
            with self.assertRaises(ValueError):
                validate_config({**TEST_CONFIG, "context_window": value})

    def test_turbo_asr_is_configurable_and_unknown_model_is_rejected(self):
        self.assertEqual(validate_config({**TEST_CONFIG, "transcription_model": "large-v3-turbo"})["transcription_model"], "large-v3-turbo")
        with self.assertRaises(ValueError):
            validate_config({**TEST_CONFIG, "transcription_model": "unregistered-model"})

    def test_invalid_timeline_is_rejected(self):
        summary = self.summary()
        summary["timeline"][0]["seconds"] = 20
        with self.assertRaises(ValueError):
            validate_summary(summary, 10)

    def test_workflow_preserves_transcript_and_named_artifacts(self):
        video = self.root / "media/input.mp4"
        video.parent.mkdir()
        video.touch()
        frame = self.root / "frame.jpg"
        frame.touch()
        transcript = [{"start": 0, "end": 3, "text": "今天讨论家庭预算"}]
        with patch("services.douyin.video_understanding.inspect_video", return_value=(4, [{"file": frame, "seconds": 0}])), \
             patch("services.douyin.video_understanding.transcribe", return_value=(transcript, "")), \
             patch.object(UnderstandingProvider, "complete", side_effect=[{"observations": []}, {"summary": "预算"}, self.summary()]) as complete:
            result = understand_work("https://www.douyin.com/video/123", self.root, lambda *args: [video], TEST_CONFIG, lambda *args: None)
        self.assertEqual(result["transcript"], transcript)
        self.assertEqual(result["summary_basis"], "audio_primary")
        self.assertIn("音频与画面或字幕冲突时以音频为准", complete.call_args.args[0])
        trace = json.loads((self.root / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "done")
        self.assertTrue(all(x["status"] == "success" for x in trace["nodes"]))
        self.assertEqual(trace["artifacts"]["summary"], "summary.json")
        self.assertEqual(trace["artifacts"]["report"], "report.md")
        self.assertIn("完整音频转写", (self.root / "report.md").read_text(encoding="utf-8"))
        self.assertNotIn("api_key", (self.root / "task.json").read_text())

    def test_history_survives_restart_and_report_escapes_model_html(self):
        from services.douyin.understanding_history import UnderstandingHistory, render_report
        download_root = self.root / "downloads"
        root = download_root / "understanding" / "test-id"
        root.mkdir(parents=True)
        (root / "video.mp4").touch()
        result = {**self.summary(), "title": "<script>alert(1)</script>", "source_url": "https://www.douyin.com/video/123",
                  "duration_seconds": 4, "frame_count": 0, "model": "test", "video_file": "video.mp4", "transcript": []}
        trace = {"status": "done", "nodes": [{"name": "download", "status": "success", "started_at": 1, "ended_at": 2}],
                 "artifacts": {"video": "video.mp4", "frames": []}}
        (root / "task.json").write_text(json.dumps(trace), encoding="utf-8")
        (root / "summary.json").write_text(json.dumps(result), encoding="utf-8")
        store = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        store.backfill()
        store.backfill()
        restored = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        self.assertEqual(restored.list()["total"], 1)
        self.assertEqual(restored.list(offset=1)["items"], [])
        saved = restored.get("test-id")
        self.assertEqual(saved["video"]["href"], "/downloads/understanding/test-id/video.mp4")
        self.assertTrue(saved["report"]["href"].endswith("report.md"))
        self.assertIsNone(restored.get("missing"))
        with restored.connect() as db:
            row = db.execute("SELECT source_url,report_markdown,video_cache_file FROM understanding_history").fetchone()
        self.assertEqual(row[0], result["source_url"])
        self.assertIn("视频理解报告", row[1])
        self.assertEqual(row[2], "understanding/test-id/video.mp4")
        rendered = render_report(root, saved, trace, "/downloads/")
        self.assertNotIn("<script>", rendered)
        self.assertIn("&lt;script&gt;", rendered)
        self.assertTrue(restored.delete("test-id"))
        self.assertFalse(restored.delete("test-id"))
        restored = UnderstandingHistory(self.root / "history.sqlite3", download_root)
        restored.backfill()
        self.assertEqual(restored.list()["total"], 0)
        self.assertIsNone(restored.get("test-id"))

    def test_download_failure_is_saved(self):
        def download(*args):
            raise RuntimeError("验证码未完成")
        with self.assertRaisesRegex(RuntimeError, "验证码"):
            understand_work("url", self.root, download, TEST_CONFIG, lambda *args: None)
        trace = json.loads((self.root / "task.json").read_text(encoding="utf-8"))
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["nodes"][0]["status"], "failed")

    def test_restart_marks_running_jobs_interrupted_and_keeps_results(self):
        store = WebJobStore(self.root)
        running = store.create("running")
        done = store.create("done")
        store.update(done, status="done", result={"summary": "saved"})
        restored = WebJobStore(self.root)
        self.assertEqual(restored.get(running)["status"], "error")
        self.assertEqual(restored.get(done)["result"], {"summary": "saved"})

    def test_multimodal_payload_uses_actual_image_bytes(self):
        image = self.root / "frame.jpg"
        image.write_bytes(b"jpeg-fixture")
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"choices":[{"message":{"content":"{\\"description\\":\\"frame\\"}"}}]}'
        with patch("services.douyin.video_understanding.request.urlopen", return_value=Response()) as call:
            result = UnderstandingProvider({**TEST_CONFIG, "base_url": "https://example.com/v1", "api_format": "openai"}).complete("describe", [image])
        payload = json.loads(call.call_args.args[0].data)
        self.assertEqual(result["description"], "frame")
        self.assertTrue(payload["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,"))

    def test_ollama_explicit_context_and_native_image_payload(self):
        image = self.root / "frame.jpg"
        image.write_bytes(b"jpeg-fixture")
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"message":{"content":"{\\"description\\":\\"frame\\"}"}}'
        with patch("services.douyin.video_understanding.request.urlopen", return_value=Response()) as call:
            UnderstandingProvider(TEST_CONFIG).complete("describe", [image])
        req = call.call_args.args[0]
        payload = json.loads(req.data)
        self.assertTrue(req.full_url.endswith("/api/chat"))
        self.assertEqual(payload["options"]["num_ctx"], 32768)
        self.assertFalse(payload["think"])
        self.assertEqual(len(payload["messages"][1]["images"]), 1)


if __name__ == "__main__":
    unittest.main()
