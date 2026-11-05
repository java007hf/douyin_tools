"""Bounded model-only comedy development before costly media production."""
from __future__ import annotations

import json
from pathlib import Path

from .comedy_prompts import COMEDY_STORY_PROMPT


STORY_SCHEMA = """只输出JSON：{candidates:[{id,title,premise,character_goals:{},setup_fact,wrong_assumption,beats:[{action,speaker,dialogue}],payoff}]}。
恰好3个候选，id固定为c1/c2/c3，每个4个节拍。最后一拍实际呈现结局，payoff只是概括，不能额外发生事件。
台词简短，每拍最多一位说话者；只写剧情，不写摄影、模型或素材参数。候选的冲突机制应不同。"""

REVIEW_PROMPT = """你是严格的短喜剧剧本审稿人，只检查提交的原文，不替作者补充隐含事件，不改写剧本。
逐拍核对：开场规则与输赢结果是否一致；每个行动有明确动机；转折所需信息是否提前呈现；最后一拍是否真正兑现结局。
同时核对用户明确要求，不能漏掉排除的桥段、人物或画面文字。logic_ok只评估可指出的动机/因果矛盾，审美不喜欢归入humor_score，不要伪装成逻辑错误。
不要把普通嗅闻、肢体动作或神话设定本身判成身体羞辱；不是每一拍都必须独立构成笑点。一个角色假扮职业不意味着新增第三人，不能替原稿假设不存在的角色。只依据原文和用户要求，不臆造额外禁令。
区分动作带来的笑点与作者声称好笑。受伤、羞辱、表情夸张或漂亮外形本身不算完整喜剧机制。
例如规则是先笑才输，发怒不能算输。不要因人名熟悉或写了“反转”就放行。
只输出JSON {reviews:[{id,logic_ok,humor_score,approved,setup_evidence,payoff_evidence,issues:[{beat,quote,reason,repair_goal}]}]}。
每个候选一条，id与输入一致。humor_score为0到10整数，6表示至少有明确可理解的喜剧机制，不表示观众必然会笑。
evidence和quote必须引用原文；无可引用内容填空并列出缺失问题。issues只列必须修复的问题；有问题必须approved=false。
每个候选最多列三项关键问题，reason与repair_goal简短具体，repair_goal只描述要修复的关系或要求，不代写新桥段。
只凭当前文字判断，不输出润色后的故事，不自我表扬。"""


def _validate_candidates(value):
    rows = value.get('candidates')
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError('剧情开发必须返回三个候选')
    if {r.get('id') for r in rows if isinstance(r, dict)} != {'c1', 'c2', 'c3'}:
        raise ValueError('剧情候选ID必须为c1/c2/c3')
    for row in rows:
        if not all(row.get(key) for key in ('title', 'premise', 'setup_fact', 'wrong_assumption', 'payoff', 'character_goals')):
            raise ValueError('剧情候选缺少动机、铺垫或结局')
        beats = row.get('beats')
        if not isinstance(beats, list) or len(beats) != 4 or any(not isinstance(b, dict) or not b.get('action') for b in beats):
            raise ValueError('剧情候选必须有四个可见动作节拍')
    return rows


def _validate_reviews(value, candidates):
    rows = value.get('reviews')
    ids = {c['id'] for c in candidates}
    if not isinstance(rows, list) or len(rows) != len(ids) or {r.get('id') for r in rows if isinstance(r, dict)} != ids:
        raise ValueError('剧情评审必须覆盖所有候选且ID一致')
    for row in rows:
        score = row.get('humor_score')
        if type(score) is not int or not 0 <= score <= 10 or type(row.get('logic_ok')) is not bool or type(row.get('approved')) is not bool or not isinstance(row.get('issues'), list):
            raise ValueError('剧情评审缺少有效判定或评分')
        def text_values(value):
            if isinstance(value, str):
                return [value]
            if isinstance(value, dict):
                return [text for item in value.values() for text in text_values(item)]
            if isinstance(value, list):
                return [text for item in value for text in text_values(item)]
            return []
        source = text_values(next(c for c in candidates if c['id'] == row['id']))
        for key in ('setup_evidence', 'payoff_evidence'):
            quote = row.get(key)
            if not isinstance(quote, str) or (quote and not any(quote in text for text in source)):
                raise ValueError('剧情评审引用了原稿中不存在的证据')
        for issue in row['issues']:
            if not isinstance(issue, dict) or not isinstance(issue.get('reason'), str) or not issue['reason']:
                raise ValueError('剧情评审缺少具体问题原因')
            quote = issue.get('quote', '')
            if not isinstance(quote, str) or (quote and not any(quote in text for text in source)):
                raise ValueError('剧情评审的问题引用不在原稿中')
    return rows


def develop_comedy(llm, brief: str, duration: float, task_dir: Path, *, max_rewrites=1, on_progress=None):
    """All creative text comes from the configured LLM; selection is deterministic."""
    directory = task_dir / 'story_development'
    directory.mkdir(parents=True, exist_ok=True)
    def save(name, value):
        (directory / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    def status(**values):
        save('status.json', values)
        if on_progress:
            on_progress(values)
    request = {'brief': brief, 'total_duration_seconds': duration, 'requirements': STORY_SCHEMA}
    save('input.json', request)
    save('prompts.json', {'writer': COMEDY_STORY_PROMPT, 'reviewer': REVIEW_PROMPT})
    try:
        status(status='running', stage='generate', round=0)
        value = llm.complete_json(COMEDY_STORY_PROMPT, json.dumps(request, ensure_ascii=False))
        for round_index in range(max_rewrites + 1):
            save(f'round_{round_index}_candidates.json', value)
            candidates = _validate_candidates(value)
            status(status='running', stage='review', round=round_index)
            review = llm.complete_json(REVIEW_PROMPT, json.dumps({'brief': brief, 'candidates': candidates}, ensure_ascii=False))
            save(f'round_{round_index}_review.json', review)
            reviews = _validate_reviews(review, candidates)
            passed = [r for r in reviews if r['approved'] and r['logic_ok'] and r['humor_score'] >= 6 and not r['issues'] and r['setup_evidence'] and r['payoff_evidence']]
            if passed:
                winner = sorted(passed, key=lambda r: (-r['humor_score'], r['id']))[0]
                selected = next(c for c in candidates if c['id'] == winner['id'])
                result = {'selected': selected, 'review': winner, 'round': round_index, 'author': 'configured_llm', 'review_is_subjective': True}
                save('selected.json', result)
                status(status='done', stage='selected', round=round_index, selected_id=winner['id'])
                return result
            if round_index < max_rewrites:
                status(status='running', stage='rewrite', round=round_index + 1)
                value = llm.complete_json(COMEDY_STORY_PROMPT, json.dumps({**request, 'previous_candidates': candidates, 'review': reviews,
                    'revision_instruction': '针对逐条评审修复动机、规则和结局；可以重构失败剧情，但不得改变用户要求。不要只修改payoff说明，必须让四拍实际呈现结果。返回同样三个ID和完整JSON。'}, ensure_ascii=False))
        raise ValueError('喜剧剧情未通过模型评审，已停止素材生成；请查看 story_development 原稿和评审，调整配置或诉求后重试')
    except Exception as exc:
        status(status='error', error=str(exc))
        raise
