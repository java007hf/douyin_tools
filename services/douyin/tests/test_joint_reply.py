import asyncio
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from services.douyin.mention_mcp import create_server
from services.douyin.reply_style import COMMENT_REPLY_STYLE_VERSION


class JointReplyTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory(dir='cache')))
        self.provider = self.stack.enter_context(patch('services.douyin.video_understanding.UnderstandingProvider'))
        self.stack.enter_context(patch('services.douyin.video_understanding.validate_config', side_effect=lambda value: value))
        store = self.stack.enter_context(patch('services.video_creator.tools.ai.config_store.ProviderConfigStore'))
        store.return_value.get_by_provider.return_value = {}
        self.analysis = {'summary': '讲英语词汇', 'comment_reply': 'pretty可以表示挺……。',
                         'comment_reply_style_version': COMMENT_REPLY_STYLE_VERSION,
                         'transcript': [{'text': '完整音频证据'}]}

    def tearDown(self):
        self.stack.close()

    def call(self, tool='summarize_video', arguments=None):
        (self.root / 'summary.json').write_text(json.dumps(self.analysis), encoding='utf-8')
        server = create_server('reply', self.root, self.root / 'config.json', self.root / 'profile')
        return asyncio.run(server.call_tool(tool, arguments or {}))

    def test_joint_reply_requires_no_extra_model_call(self):
        result = self.call()
        self.provider.assert_not_called()
        self.assertIn(self.analysis['comment_reply'], json.dumps(result, ensure_ascii=False, default=str))

    def test_invalid_joint_reply_uses_bounded_repair(self):
        self.analysis['comment_reply'] = '字' * 301
        self.provider.return_value.complete.return_value = {'reply': '重新生成的简短正文。'}
        self.call()
        self.assertEqual(self.provider.return_value.complete.call_count, 1)

    def test_question_still_uses_question_specific_model_call(self):
        self.provider.return_value.complete.return_value = {'reply': '针对问题的答案。'}
        self.call('answer_video_question', {'question': '这个词是什么意思？'})
        self.provider.return_value.complete.assert_called_once()
        self.assertIn('完整音频证据', self.provider.return_value.complete.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
