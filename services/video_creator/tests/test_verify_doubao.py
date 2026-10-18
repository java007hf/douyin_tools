import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from services.video_creator.tools.ai.verify_doubao import business_errors, run_original


class StagedVerificationTests(unittest.TestCase):
    def test_http_success_does_not_hide_business_failure(self):
        raw = 'id: 1\nevent: json\ndata: ' + json.dumps({'status_code':710022002}) + '\n\n'
        self.assertEqual(business_errors(raw), [{'code':'710022002'}])

    def test_failed_baseline_never_downloads_or_duplicates_submission(self):
        root = Path(__file__).resolve().parents[3] / 'cache' / 'tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            handler = MagicMock()
            handler.process_message.return_value = {'status':'success','status_code':200,
                'raw_response':'data: {"status_code":710022002}\n\n'}
            module = types.SimpleNamespace(parseResponse=lambda _: {'status':'success','image_urls':[]})
            with patch('services.video_creator.tools.ai.verify_doubao.requests.get') as get:
                result = run_original(module, '小狗', Path(temp)/'baseline', handler)
            self.assertEqual(result['status'], 'error')
            self.assertEqual(result['image_count'], 0)
            handler.process_message.assert_called_once_with('小狗')
            get.assert_not_called()

    def test_no_image_is_not_success_even_without_business_error(self):
        root = Path(__file__).resolve().parents[3] / 'cache' / 'tests'
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root) as temp:
            handler = MagicMock()
            handler.process_message.return_value = {'status':'success','status_code':200,'raw_response':'data: {"status_code":0}\n\n'}
            module = types.SimpleNamespace(parseResponse=lambda _: {'status':'success','image_urls':[]})
            self.assertEqual(run_original(module, 'dog', Path(temp), handler)['status'], 'error')


if __name__ == '__main__':
    unittest.main()
