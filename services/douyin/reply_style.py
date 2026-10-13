"""Shared style and validation for joint analysis and standalone reply repair."""
import re

COMMENT_REPLY_STYLE_VERSION = 'conversational-v1'
SUMMARY_REPLY_PROMPT = (
    '在评论区用自然口语说清视频的主题和关键点，根据内容复杂度决定篇幅，不限制句数、不凑长度。'
    '直接讲内容，不逐段复述、不写观察报告，不遗漏必要的例子或结论。'
    '过滤证据中的无关细节：发布者介绍、账号、人物衣着动作、麦克风、字幕展示、平台标识、'
    '引导关注、结尾互动、“你学会了吗”等套话，以及不确定的转写碎片和对它们的猜测。'
    '仅当这些细节本身是主题时保留。整段默认概述视频，不重复归因；'
    '不要使用“作者认为/分析/批评”“主讲人指出”“视频指出”“观点认为”“创作者旨在”等模板。'
    '保留原有推测、条件和不确定程度，不添加证据之外的事实或建议。'
    '正文最多300个字符，不含链接、广告或客套问候，没有最低字数。'
)


def comment_reply_error(text):
    if not isinstance(text, str) or not text.strip():
        return '回复为空或不是文字'
    if len(text.strip()) > 300:
        return f'回复长度{len(text.strip())}超过300字符'
    if re.search(r'https?://', text):
        return '回复含链接'
    return ''
