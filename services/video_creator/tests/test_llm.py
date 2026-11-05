import io
import json
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from services.video_creator.tools.ai.llm import LLMError, OpenAICompatibleLLM, create_agent_llm, validate_agent_config


class LLMTests(unittest.TestCase):
    def test_low_thinking_requires_model_advertised_support(self):
        config = {'base_url': 'http://localhost:11434/v1', 'model': 'local', 'api_format': 'ollama', 'thinking_enabled': 'low'}
        with patch('services.video_creator.tools.ai.llm.request.urlopen', side_effect=[
                io.BytesIO(b'{"thinking":{"values":[false,"low","medium"]}}'),
                io.BytesIO(b'{"message":{"content":"{}"},"done":true}')]) as post:
            client = create_agent_llm(config)
            self.assertEqual(client.complete_json('system', 'brief'), {})
        self.assertEqual(post.call_args_list[0].args[0].full_url, 'http://localhost:11434/api/show')
        self.assertEqual(json.loads(post.call_args_list[1].args[0].data)['think'], 'low')
        with patch('services.video_creator.tools.ai.llm.request.urlopen', return_value=io.BytesIO(b'{"thinking":{"values":[false,true]}}')):
            with self.assertRaisesRegex(LLMError, '未声明支持 low'):
                create_agent_llm(config)

    def test_ollama_output_budget_is_configurable(self):
        client=create_agent_llm({'base_url':'http://localhost:11434','model':'local','api_format':'ollama',
                                 'thinking_enabled':True,'output_token_limit':'12000'})
        with patch('services.video_creator.tools.ai.llm.request.urlopen',return_value=io.BytesIO(b'{"message":{"content":"{}"}}')) as post:
            client.complete_json('system','brief')
        self.assertEqual(json.loads(post.call_args.args[0].data)['options']['num_predict'],12000)
        for invalid in (0,32769,'1.5'):
            with self.subTest(invalid=invalid),self.assertRaises(LLMError):
                validate_agent_config({'base_url':'http://localhost:11434','model':'local','output_token_limit':invalid})

    def test_model_sampling_defaults_do_not_override_temperature(self):
        client=create_agent_llm({'base_url':'http://localhost:11434','model':'local','api_format':'ollama',
                                 'thinking_enabled':True,'use_model_sampling_defaults':'true'})
        with patch('services.video_creator.tools.ai.llm.request.urlopen',return_value=io.BytesIO(b'{"message":{"content":"{}"}}')) as post:
            client.complete_json('system','brief')
        options=json.loads(post.call_args.args[0].data)['options']
        self.assertNotIn('temperature',options)
        self.assertEqual(options['num_predict'],6000)

    def test_thinking_mode_counts_reasoning_but_only_parses_final_json(self):
        client = create_agent_llm({'base_url': 'http://localhost:11434', 'model': 'local',
                                   'api_format': 'ollama', 'thinking_enabled': 'true'})
        events = [{'message': {'thinking': 'private reasoning'}},
                  {'message': {'content': '{"approved":true}'}},
                  {'done': True, 'done_reason': 'stop', 'eval_count': 42}]
        body = '\n'.join(json.dumps(event) for event in events).encode()
        progress = []
        client.on_progress = progress.append
        with patch('services.video_creator.tools.ai.llm.request.urlopen', return_value=io.BytesIO(body)) as post:
            self.assertEqual(client.complete_json('system', 'brief'), {'approved': True})
        self.assertTrue(json.loads(post.call_args.args[0].data)['think'])
        self.assertEqual(json.loads(post.call_args.args[0].data)['options']['num_predict'], 6000)
        self.assertEqual(client.last_response_metrics['thinking_characters'], len('private reasoning'))
        self.assertNotIn('private reasoning', json.dumps(client.last_response_metrics))
        self.assertGreater(progress[0], 0)

    def test_output_token_limit_is_not_treated_as_valid_json_or_retried(self):
        client = create_agent_llm({'base_url': 'http://localhost:11434', 'model': 'local', 'api_format': 'ollama', 'thinking_enabled': True})
        event = {'message': {'thinking': 'reasoning', 'content': '{}'}, 'done': True, 'done_reason': 'length'}
        with patch('services.video_creator.tools.ai.llm.request.urlopen', return_value=io.BytesIO(json.dumps(event).encode())) as post:
            with self.assertRaisesRegex(LLMError, 'token 上限'):
                client.complete_json('system', 'brief')
        self.assertEqual(post.call_count, 1)

    def test_ollama_native_request_and_retry(self):
        client = create_agent_llm({'base_url': 'http://localhost:11434/v1/', 'model': 'local-model',
                                   'api_format': 'ollama', 'context_window': '32768'})
        responses = [io.BytesIO(json.dumps({'message': {'content': 'invalid'}}).encode()),
                     io.BytesIO(json.dumps({'message': {'content': '{"shots": []}'}}).encode())]
        with patch('services.video_creator.tools.ai.llm.request.urlopen', side_effect=responses) as post:
            self.assertEqual(client.complete_json('system', 'brief'), {'shots': []})
        self.assertEqual(post.call_count, 2)
        for call in post.call_args_list:
            req = call.args[0]
            self.assertEqual(req.full_url, 'http://localhost:11434/api/chat')
            self.assertIsNone(req.get_header('Authorization'))
            payload = json.loads(req.data)
            self.assertEqual(payload['options']['num_ctx'], 32768)
            self.assertEqual(payload['format'], 'json')
            self.assertFalse(payload['think'])
            self.assertTrue(payload['stream'])
            self.assertNotIn('response_format', payload)
            self.assertEqual(payload['model'], 'local-model')

    def test_ollama_direct_endpoint_and_auth(self):
        client = create_agent_llm({'base_url': 'https://example.test/proxy/api/chat', 'model': 'local-model',
                                   'api_format': 'ollama', 'api_key': 'Bearer secret'})
        with patch('services.video_creator.tools.ai.llm.request.urlopen', return_value=io.BytesIO(b'{"message":{"content":"{}"}}')) as post:
            self.assertEqual(client.complete_json('system', 'review'), {})
        self.assertEqual(post.call_args.args[0].full_url, 'https://example.test/proxy/api/chat')
        self.assertEqual(post.call_args.args[0].get_header('Authorization'), 'Bearer secret')

    def test_legacy_config_keeps_openai_protocol(self):
        client = create_agent_llm({'base_url': 'https://example.test/v1', 'model': 'existing', 'api_key': 'key'})
        with patch('services.video_creator.tools.ai.llm.request.urlopen', return_value=io.BytesIO(b'{"choices":[{"message":{"content":"{}"}}]}')) as post:
            client.complete_json('system', 'brief')
        self.assertEqual(post.call_args.args[0].full_url, 'https://example.test/v1/chat/completions')
        self.assertEqual(json.loads(post.call_args.args[0].data)['response_format'], {'type': 'json_object'})

    def test_ollama_stream_reports_progress_and_combines_chunks(self):
        client=create_agent_llm({'base_url':'http://localhost:11434','model':'local','api_format':'ollama'})
        progress=[]
        client.on_progress=progress.append
        events=[{'message':{'content':'{"approved":'}}, {'message':{'content':'true}'},'done':True}]
        body='\n'.join(json.dumps(event) for event in events).encode()
        with patch('services.video_creator.tools.ai.llm.request.urlopen',return_value=io.BytesIO(body)):
            self.assertEqual(client.complete_json('review','brief'),{'approved':True})
        self.assertGreater(progress[-1],progress[0])

    def test_invalid_agent_settings_are_rejected(self):
        base = {'base_url': 'http://localhost:11434', 'model': 'local', 'api_format': 'ollama'}
        for changes in ({'context_window': 1024}, {'context_window': '1.5'}, {'api_format': 'unknown'}, {'model': ''}, {'base_url': 'file:///tmp'}, {'thinking_enabled': 'maybe'}, {'thinking_enabled': 1}):
            with self.subTest(changes=changes), self.assertRaises(LLMError):
                validate_agent_config({**base, **changes})
        with self.assertRaises(LLMError):
            create_agent_llm({**base, 'enabled': False})

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
