"""Regression coverage for report voice leaking from evidence into publishable copy."""
import copy
import unittest
from unittest.mock import Mock, patch

from services.douyin.understanding_prompts import AUTHOR_VOICE_RULES, validate_author_voice
from services.douyin.video_understanding import validate_summary
from services.douyin.publishing.content import generate_content, validate_content
from services.douyin.tests.test_publishing import content


class AuthorVoiceTests(unittest.TestCase):
    def test_rejects_report_frames_but_keeps_cases_and_named_attribution(self):
        for text in ('视频还对比了合同工与正式工。', '作者对无礼貌消息采取冷处理。',
                     '作者观点：面试比工作更难。', '主讲人分析了风险。', '原文指出入职有风险。'):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, '成稿口吻不符'):
                validate_author_voice([('summary', text)])
        for text in ('一位工程师入职七周后被裁，这是一个他人的案例。',
                     '据某公司的公告，该团队正在调整。', '张某表示，合同工与正式工的要求不同。',
                     '我更看重沟通是否及时。', '视频剪辑需要注意节奏。', '这本书讨论作者身份。'):
            validate_author_voice([('summary', text)])

    def test_understanding_checks_all_public_fields_but_not_limitations(self):
        base = {'title': '职场沟通', 'format': '口播', 'topic': '职场', 'tags': [],
                'summary': '沟通需要礼貌。', 'key_points': ['尊重回复边界。'],
                'timeline': [{'seconds': 0, 'content': '沟通与回复边界'}],
                'limitations': ['作者观点未经独立核实。']}
        validate_summary(copy.deepcopy(base), 10)
        for field in ('title', 'summary', 'key_points', 'timeline'):
            value = copy.deepcopy(base)
            if field == 'key_points': value[field] = ['作者对无礼貌消息采取冷处理。']
            elif field == 'timeline': value[field][0]['content'] = '视频还对比了两种面试。'
            else: value[field] = '作者观点：沟通很重要。'
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, '成稿口吻不符'):
                validate_summary(value, 10)

    def test_publication_checks_body_cards_and_cover_for_both_platforms(self):
        for platform in ('xiaohongshu', 'douyin'):
            for field in ('summary', 'body', 'card', 'cover'):
                value = content(platform)
                if field == 'card': value['cards'][0]['text'] = '作者对无礼貌消息采取冷处理。'
                elif field == 'cover': value['cover']['subtitle'] = '视频还对比了面试难度'
                else: value[field] = '视频还对比了两种面试。'
                with self.subTest(platform=platform, field=field), self.assertRaisesRegex(ValueError, '成稿口吻不符'):
                    validate_content(value, platform, {})

    def test_report_voice_in_old_source_is_rewritten_once_not_string_replaced(self):
        source = {'summary': '视频还对比了两种面试。作者对无礼貌消息采取冷处理。'}
        original = copy.deepcopy(source)
        for platform in ('xiaohongshu', 'douyin'):
            bad, good = content(platform), content(platform)
            bad['body'] = source['summary']
            provider = Mock()
            provider.complete.side_effect = [bad, good]
            result = generate_content(provider, source, platform)
            self.assertEqual(result['body'], good['body'])
            self.assertEqual(provider.complete.call_count, 2)
            self.assertIn('成稿口吻不符', provider.complete.call_args.args[0])
            self.assertIn('上次输出', provider.complete.call_args.args[0])
            for call in provider.complete.call_args_list:
                self.assertIn(AUTHOR_VOICE_RULES, call.kwargs['system_prompt'])
            provider.complete.side_effect = [bad, bad]
            with self.assertRaisesRegex(ValueError, '成稿口吻不符'):
                generate_content(provider, source, platform)
            self.assertEqual(provider.complete.call_count, 4)
        self.assertEqual(source, original)

    def test_length_repair_and_card_supplement_receive_same_voice_rules(self):
        from services.douyin.publishing.content import expand_short_cards, shorten_long_cards, supplement_cards, split_dense_cards
        provider = Mock()
        value = content('xiaohongshu')
        value['cards'][1]['text'] = ''
        provider.complete.return_value = {'pages': [{'index': 1, 'text': content('xiaohongshu')['cards'][1]['text']}]}
        expand_short_cards(provider, value, 'xiaohongshu', {})
        self.assertIn(AUTHOR_VOICE_RULES, provider.complete.call_args.kwargs['system_prompt'])
        value=content('xiaohongshu');value['cards'][1]['text']='长内容。'*40
        provider.complete.return_value={'groups':[{'index':1,'cards':[content('xiaohongshu')['cards'][1]]*2}]}
        split_dense_cards(provider,value,'xiaohongshu',{})
        self.assertIn(AUTHOR_VOICE_RULES,provider.complete.call_args.kwargs['system_prompt'])
        value = content('douyin'); value['cards'][1]['text'] = '沟通。' * 40
        provider.complete.return_value = {'pages': [{'index': 1, 'text': '及时沟通，尊重回复边界。'}]}
        shorten_long_cards(provider, value, 'douyin', {})
        self.assertIn(AUTHOR_VOICE_RULES, provider.complete.call_args.kwargs['system_prompt'])
        value = content('douyin'); value['cards'].pop()
        provider.complete.return_value = {'cards': [content('douyin')['cards'][0]]}
        supplement_cards(provider, value, 'douyin', {})
        self.assertIn(AUTHOR_VOICE_RULES, provider.complete.call_args.kwargs['system_prompt'])

    def test_saved_report_draft_is_blocked_before_browser_or_files(self):
        from services.douyin.publishing import douyin, xiaohongshu
        for adapter in (douyin, xiaohongshu):
            with self.subTest(adapter=adapter.__name__), self.assertRaisesRegex(ValueError, '成稿口吻不符'):
                adapter.prepare({'title': '沟通', 'body': '作者对无礼貌消息采取冷处理。'}, None)


if __name__ == '__main__':
    unittest.main()
