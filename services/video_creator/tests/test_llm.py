import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from services.video_creator.tools.ai.llm import LLMError, OpenAICompatibleLLM


class LLMTests(unittest.TestCase):
    def test_structured_request_preserves_provider_error_body(self):
        error=HTTPError(
            "https://example.test/chat/completions",404,"Not Found",{},
            io.BytesIO(b'{"error":{"code":"ModelNotOpen","message":"activate model service"}}'),
        )
        client=OpenAICompatibleLLM("https://example.test","secret","model")
        with patch("services.video_creator.tools.ai.llm.request.urlopen",side_effect=error):
            with self.assertRaisesRegex(LLMError,"ModelNotOpen"):
                client.complete_json("system","prompt")


if __name__ == "__main__":
    unittest.main()
