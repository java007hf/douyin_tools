import unittest
from unittest.mock import patch

from services.video_creator.tools.ai.providers import MiniMaxVideoProvider, ProviderError, SeedanceProvider


class ProviderTests(unittest.TestCase):
    def test_minimax_submit_and_status(self):
        provider = MiniMaxVideoProvider("https://example.test", "key")
        with patch.object(provider, "call", side_effect=[{"task_id": "m1"}, {"status": "Success", "file_id": "f1"}, {"file": {"download_url": "https://cdn.test/a.mp4"}}]):
            task_id = provider.submit("hello")
            result = provider.wait(task_id)
            self.assertEqual(task_id, "m1")
            self.assertEqual(provider.download_url(result), "https://cdn.test/a.mp4")

    def test_seedance_requires_task_id(self):
        provider = SeedanceProvider("https://example.test", "key", "model")
        with patch.object(provider, "call", return_value={}):
            with self.assertRaises(ProviderError): provider.submit("hello")


if __name__ == "__main__": unittest.main()
