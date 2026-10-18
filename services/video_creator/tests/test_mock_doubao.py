import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from services.video_creator.tools.ai.mock_doubao import MODEL, MockDoubaoImageProvider, extract_images, image_models, image_model_status, response_error
from services.video_creator.tools.ai.providers import ProviderError


class MockDoubaoTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(__file__).resolve().parents[3] / "cache" / "tests"
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "session.json"
        self.config = {"base_url": "https://api.doubao.com", "headers": {"X-Tt-Token": "private-token"},
                       "body": {"uplink_body": {"send_message_body": {"content": '{"im_cmd":-1,"text":"old"}'}}}}
        self.path.write_text(json.dumps(self.config), encoding="utf-8")
        self.provider = MockDoubaoImageProvider(self.path)

    def creation(self):
        return {"creations": [{"type": 1, "image": {"image_ori_raw": {"url": "https://cdn.test/original.png"},
                                                   "image_preview": {"url": "https://cdn.test/preview.png"}}}]}

    def test_nested_content_prefers_original_and_deduplicates(self):
        payload = {"content": json.dumps([self.creation(), self.creation()]), "image_ori": {"url": "https://cdn.test/input.png"}}
        self.assertEqual(extract_images(payload), ["https://cdn.test/original.png"])

    def test_fresh_ids_and_template_preserved(self):
        first = self.provider.build_request("new")[3]
        second = self.provider.build_request("new")[3]
        self.assertNotEqual(first["sequence_id"], second["sequence_id"])
        self.assertEqual(first["sequence_id"], first["uplink_body"]["send_message_body"]["local_message_id"])
        self.assertEqual(self.provider.config, self.config)

    def test_model_routes_change_payload_not_just_display_name(self):
        self.provider.config['model_routes'] = {
            'mock_doubao_seedream_4_5': {'request': {'body': {'uplink_body': {'send_message_body': {'ext': {'input_skill': '{"model":"captured-example"}'}}}}}},
            'mock_doubao_disabled': {'enabled': False, 'request': {'query': {'model': 'off'}}},
        }
        self.path.write_text(json.dumps(self.provider.config), encoding='utf-8')
        alternate = self.provider.build_request('new', 'mock_doubao_seedream_4_5')[3]
        default = self.provider.build_request('new')[3]
        self.assertIn('captured-example', alternate['uplink_body']['send_message_body']['ext']['input_skill'])
        self.assertNotIn('input_skill', default['uplink_body']['send_message_body']['ext'])
        self.assertNotIn('mock_doubao_disabled', image_models(self.path))
        self.assertTrue(image_model_status(self.path)['mock_doubao_seedream_4_5']['configured'])
        self.assertFalse(image_model_status(self.path)['mock_doubao_seedream_5_0_pro']['configured'])
        with self.assertRaises(ProviderError):
            self.provider.build_request('new', 'mock_doubao_disabled')

    def test_stream_and_final_unterminated_event(self):
        response = MagicMock(status_code=200)
        response.iter_lines.return_value = [": ping", "data: " + json.dumps({"content": json.dumps(self.creation())}), "", "data: [DONE]"]
        response.__enter__.return_value = response
        with patch("services.video_creator.tools.ai.mock_doubao.requests.post", return_value=response) as post:
            self.assertEqual(self.provider.generate("a cat", model=MODEL), ["https://cdn.test/original.png"])
        self.assertEqual(post.call_count, 1)
        self.assertFalse(post.call_args.kwargs["allow_redirects"])

    def test_network_error_redacted_without_retry(self):
        with patch("services.video_creator.tools.ai.mock_doubao.requests.post", side_effect=requests.ConnectionError("private-token")) as post:
            with self.assertRaises(ProviderError) as raised:
                self.provider.generate("cat")
        self.assertNotIn("private-token", str(raised.exception))
        self.assertEqual(post.call_count, 1)

    def test_empty_response_is_failure(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_lines.return_value = ["data: [DONE]", ""]
        with patch("services.video_creator.tools.ai.mock_doubao.requests.post", return_value=response):
            with self.assertRaises(ProviderError):
                self.provider.generate("cat")

    def test_unsupported_reference_rejected_before_submission(self):
        with patch("services.video_creator.tools.ai.mock_doubao.requests.post") as post:
            with self.assertRaises(ProviderError):
                self.provider.generate("cat", image=Path("reference.png"))
        post.assert_not_called()

    def test_business_error_code_without_private_details(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_lines.return_value = ['data: {"code":401,"error":"private-token"}', ""]
        with patch("services.video_creator.tools.ai.mock_doubao.requests.post", return_value=response):
            with self.assertRaises(ProviderError) as raised:
                self.provider.generate("cat")
        self.assertIn("401", str(raised.exception))
        self.assertNotIn("private-token", str(raised.exception))

    def test_preserves_captured_content_type(self):
        self.provider.config['headers']['content-type'] = 'application/json; encoding=utf-8'
        headers = self.provider.build_request('cat')[1]
        self.assertEqual(headers['content-type'], 'application/json; encoding=utf-8')
        self.assertNotIn('Content-Type', headers)

    def test_internal_and_nested_errors_keep_code_and_redact_detail(self):
        message = response_error({'code': 'Internal', 'message': 'code=712012002 prompts=不支持编码类型 private-token'}, self.config)
        self.assertIn('Internal', message)
        self.assertIn('712012002', message)
        self.assertNotIn('private-token', message)
        self.assertIn('710012001', response_error({'error': {'code': 710012001, 'message': 'login invalid'}}, self.config))

    def test_legacy_data_lines_without_blank_separators(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_lines.return_value = ['data: {"code":0}', 'data: ' + json.dumps(self.creation())]
        diagnostics = {}
        with patch('services.video_creator.tools.ai.mock_doubao.requests.post', return_value=response):
            self.assertEqual(self.provider.generate('dog', diagnostics=diagnostics), ['https://cdn.test/original.png'])
        self.assertEqual(diagnostics['parsed_events'], 2)

    def test_legacy_request_updates_fields_and_preserves_captured_headers(self):
        self.provider.config['headers'].update({'Host': 'api.doubao.com', 'Accept-Encoding': 'gzip, deflate',
            'X-Khronos': 'old', 'X-Bd-Auth': '5|example-ip|old|opaque-signature',
            'X-Bd-Layer-Auth': 'opaque-prefix-old', 'X-Request-Id': 'old'})
        self.provider.config['query'] = {'iid': 'old', 'resolution': '1224*2580'}
        with patch('time.time', return_value=1800000000.125):
            url, headers, query, body = self.provider.build_request('dog')
        self.assertEqual(headers['X-Khronos'], '1800000000')
        self.assertEqual(headers['X-Bd-Auth'], '5|example-ip|1800000000|opaque-signature')
        self.assertEqual(headers['Host'], 'api.doubao.com')
        self.assertEqual(headers['Accept-Encoding'], 'gzip, deflate')
        self.assertIn('resolution=1224*2580', url)
        self.assertRegex(url, r'_rticket=1800000000125\d{4}')
        self.assertRegex(url, r'iid=\d{15}')
        self.assertEqual(body['uplink_body']['send_message_body']['ext']['create_time_ms'], '1800000000000')
        self.assertEqual(query, {})

    def test_http_200_ack_rate_limit_is_failure_without_retry(self):
        response = MagicMock(status_code=200)
        response.__enter__.return_value = response
        response.iter_lines.return_value = ['id: 1', 'event: json', 'data: ' + json.dumps({
            'cmd': 100, 'downlink_body': {'send_message_ack_downlink_body': {}},
            'status_code': 710022002, 'status_desc': '当前服务访问频繁，请稍后重试'}), '']
        with patch('services.video_creator.tools.ai.mock_doubao.requests.post', return_value=response) as post:
            with self.assertRaises(ProviderError) as caught:
                self.provider.generate('dog')
        self.assertIn('710022002', str(caught.exception))
        self.assertIn('当前服务访问频繁', str(caught.exception))
        self.assertEqual(post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
