"""Small local plot-pattern library used to ground storyboard planning."""
from __future__ import annotations

PLOT_PATTERNS = [
    {"id": "误会升级反转", "tags": ["搞笑", "误会", "反转", "短剧"], "pattern": "建立误会 -> 对方提出小要求 -> 主角认真执行并自我陶醉 -> 最后一镜揭示真相并留下反应笑点。", "beats": ["误会建立", "要求升级", "自信执行", "真相反转和定格反应"]},
    {"id": "道具失控喜剧", "tags": ["搞笑", "道具", "变化", "喜剧"], "pattern": "普通道具被错误使用，连续产生越来越离谱但可视化的结果，最后道具反过来解决或困住主角。", "beats": ["展示道具", "第一次错误使用", "失控升级", "道具反制主角"]},
    {"id": "相亲错位喜剧", "tags": ["相亲", "人物关系", "搞笑", "神话"], "pattern": "角色带着错误期待进入相亲场景，把对方或场景信号理解错，主动表现后才发现真正对象与想象完全不同。", "beats": ["期待进入", "错误示好", "对方提出考验", "对象揭示和逃跑反应"]},
    {"id": "双人问答节奏", "tags": ["对白", "双人", "喜剧", "对话"], "pattern": "两个角色围绕同一件事进行短句问答，每轮信息更具体，最后一句台词重新解释前面所有信息。", "beats": ["问题", "误答", "追问", "一句话反转"]},
]


def retrieve_plot_references(brief: str, limit: int = 3) -> list[dict]:
    text = str(brief or "").lower()
    scored = [(sum(1 for tag in item["tags"] if tag.lower() in text), item) for item in PLOT_PATTERNS]
    scored.sort(key=lambda row: row[0], reverse=True)
    return [item for score, item in scored[:limit] if score > 0] or PLOT_PATTERNS[:limit]
