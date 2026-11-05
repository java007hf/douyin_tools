import copy
import json
import tempfile
import unittest
from pathlib import Path

from services.video_creator.workflow.story_development import develop_comedy


def candidates():
    return {'candidates': [dict(id=f'c{i}', title=f'候选{i}', premise='目标', character_goals={'甲': '取胜'},
        setup_fact='开场规则', wrong_assumption='误判', payoff='结果',
        beats=[{'action': text, 'speaker': '无', 'dialogue': ''} for text in ['开场规则', '行动', '转折', '结果']]) for i in range(1, 4)]}


def reviews(approved):
    return {'reviews': [dict(id=f'c{i}', logic_ok=approved, humor_score=7 if approved else 3,
        approved=approved, setup_evidence='开场规则', payoff_evidence='结果',
        issues=[] if approved else [{'beat': 4, 'quote': '结果', 'reason': '结果不符合规则', 'repair_goal': '修复因果'}]) for i in range(1, 4)]}


class SequenceLLM:
    def __init__(self, *values):
        self.values = iter(values)
        self.calls = []

    def complete_json(self, system, prompt):
        self.calls.append((system, json.loads(prompt)))
        return copy.deepcopy(next(self.values))


class StoryDevelopmentTests(unittest.TestCase):
    def test_literal_quotes_in_model_evidence_are_not_json_escapes(self):
        draft = candidates()
        verdict = reviews(True)
        for row in draft['candidates']:
            row['setup_fact'] = '他说"开始"'
        for row in verdict['reviews']:
            row['setup_evidence'] = '他说"开始"'
        with tempfile.TemporaryDirectory() as directory:
            result = develop_comedy(SequenceLLM(draft, verdict), '搞笑故事', 24, Path(directory))
            self.assertEqual(result['selected']['id'], 'c1')

    def test_rewrite_uses_review_and_persists_model_text(self):
        original = candidates()
        rewritten = candidates()
        rewritten['candidates'][0]['title'] = '模型修订'
        llm = SequenceLLM(original, reviews(False), rewritten, reviews(True))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = develop_comedy(llm, '搞笑故事', 24, root)
            self.assertEqual(result['selected']['title'], '模型修订')
            self.assertEqual(result['round'], 1)
            self.assertEqual(llm.calls[2][1]['previous_candidates'], original['candidates'])
            self.assertEqual(llm.calls[2][1]['review'], reviews(False)['reviews'])
            self.assertEqual(json.loads((root/'story_development/round_0_candidates.json').read_text(encoding='utf-8')), original)
            self.assertEqual(json.loads((root/'story_development/status.json').read_text(encoding='utf-8'))['status'], 'done')

    def test_failure_stops_at_bounded_rewrite_limit(self):
        llm = SequenceLLM(candidates(), reviews(False), candidates(), reviews(False))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(ValueError, '已停止素材生成'):
                develop_comedy(llm, '搞笑故事', 24, root)
            self.assertEqual(len(llm.calls), 4)
            self.assertFalse((root/'story_development/selected.json').exists())
            self.assertEqual(json.loads((root/'story_development/status.json').read_text(encoding='utf-8'))['status'], 'error')

    def test_approval_cannot_override_issues_or_hallucinated_evidence(self):
        for invalid in ('issues', 'quote', 'missing_id'):
            verdict = reviews(True)
            if invalid == 'issues':
                for row in verdict['reviews']:
                    row['issues'] = [{'reason': '因果不成立'}]
            elif invalid == 'quote':
                verdict['reviews'][0]['payoff_evidence'] = '原稿没有的事件'
            else:
                verdict['reviews'][0]['id'] = 'c9'
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as directory:
                with self.assertRaises(ValueError):
                    develop_comedy(SequenceLLM(candidates(), verdict), '搞笑故事', 24, Path(directory), max_rewrites=0)


if __name__ == '__main__':
    unittest.main()
