import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from services.douyin.mention_agent import classify_intent


class AgentTests(unittest.TestCase):
    def test_intent_allowlist_and_empty_question(self):
        provider = Mock()
        provider.complete.return_value = {'intent': 'summary', 'question': 'test'}
        self.assertEqual(classify_intent(provider, '@Benyl test'), {'intent': 'summary', 'question': ''})
        provider.complete.return_value = {'intent': 'question', 'question': '为什么去沙漠？'}
        self.assertEqual(classify_intent(provider, '为什么去沙漠？')['intent'], 'question')
        for value in ({'intent': 'publish'}, {'intent': 'question', 'question': ''}):
            provider.complete.return_value = value
            with self.assertRaises(ValueError):
                classify_intent(provider, 'test')

    def test_real_stdio_discovery_and_invalid_calls(self):
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        async def probe(root, kind):
            params = StdioServerParameters(command=sys.executable, args=[
                '-m', 'services.douyin.mention_mcp', '--kind', kind, '--task-dir', str(root),
                '--config-path', str(root / 'config.json'), '--profile', str(root / 'profile')])
            with (root / 'stderr.log').open('a') as log:
                async with stdio_client(params, errlog=log) as streams:
                    async with ClientSession(*streams) as session:
                        await session.initialize()
                        names = {t.name for t in (await session.list_tools()).tools}
                        expected = {'understand_video'} if kind == 'understanding' else {'summarize_video', 'answer_video_question'}
                        self.assertEqual(names, expected)
                        tool, args = ('understand_video', {'url': 'https://example.com'}) if kind == 'understanding' else ('answer_video_question', {'question': ''})
                        self.assertTrue((await session.call_tool(tool, args)).isError)
        cache = Path(__file__).resolve().parents[3] / 'cache'
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            for kind in ('understanding', 'reply'):
                asyncio.run(probe(Path(tmp), kind))

    def test_summary_and_question_use_different_evidence(self):
        from services.douyin.mention_mcp import create_server
        cache = Path(__file__).resolve().parents[3] / 'cache'
        with tempfile.TemporaryDirectory(dir=cache) as tmp:
            root = Path(tmp)
            (root / 'summary.json').write_text(json.dumps({'summary': '沙漠旅行', 'transcript': []}), encoding='utf-8')
            with patch('services.douyin.video_understanding.validate_config', return_value={}), patch('services.video_creator.tools.ai.config_store.ProviderConfigStore'), patch('services.douyin.video_understanding.UnderstandingProvider') as provider:
                provider.return_value.complete.return_value = {'reply': '视频摘要'}
                server = create_server('reply', root, root / 'config.json', root / 'profile')
                asyncio.run(server.call_tool('summarize_video', {}))
                self.assertIn('"question": ""', provider.return_value.complete.call_args.args[0])
                asyncio.run(server.call_tool('answer_video_question', {'question': '为何去沙漠？'}))
                self.assertIn('为何去沙漠？', provider.return_value.complete.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
