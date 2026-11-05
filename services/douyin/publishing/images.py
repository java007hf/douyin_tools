"""Prepare real per-card illustration assets before deterministic typography."""
from .cards import render_cards


def prepare_images(tool, content, platform, directory, progress):
    originals = []
    content['image_kind'] = 'ai_illustrated_card'
    content['image_traces'] = []
    content['illustration_files'] = []
    for index, card in enumerate(content['cards']):
        cover = content.get('cover') if index == 0 else None
        aspect = '9:16' if platform == 'douyin' and cover else '3:4' if cover and cover['style'] in {'portrait', 'scene'} and platform != 'wechat' else '16:9'
        target = directory / f'illustration-{index+1:02d}.png'
        content['image_traces'].append({'status': 'pending'})
        prompt = ('为图文内容创作相关场景配图，画面与主题一致，优先自然生活摄影风格。不要文字、标题、数字、价格、日期、坐标、水印或标志。'
                  f'配图不冒充真实新闻事件或实时行情。画幅{aspect}，主体清楚，构图自然，不做商务广告海报。\n'
                  f'主题：{content["title"]}\n本页观点：{card["heading"]}。{card["text"]}\n视觉要求：{card["image_prompt"]}'
                  + (f'\n这是封面主视觉：{cover["image_prompt"]}。' +
                     ('人物应为成年女性或与主题相关的成年人，穿着得体，面部自然清晰，头部完整，居中构图；背景简洁，底部留出标题空间。' if cover['style']=='portrait' else
                      '主体偏右、左侧留出清爽标题空间。' if cover['style']=='editorial' else '主体明确，构图醒目，保留标题留白。') if cover else '')
                  +
                  '\n最终约束：不要任何文字、标签、数字、价格、日期、坐标、水印或标志；所有文字由后续排版添加。')
        if platform == 'xiaohongshu':
            prompt += '\n小红书视觉：温暖日光，奶油白、浅杏或柔和暖色；自然随手拍和日常生活摄影感，真实材质，允许轻微自然不完美。避免冷青色商务插画、3D玻璃、悬浮图表、金属科技风和过度光滑的AI海报。'

        def changed(trace):
            content['image_traces'][index] = {**trace, 'card_index': index + 1}
            progress(f'配图 {index+1}/{len(content["cards"])} · {trace.get("message", "生成中")}')

        trace = tool.generate(prompt, target, changed, aspect=aspect, search_terms=card['search_terms'])
        content['image_traces'][index] = {**trace, 'card_index': index + 1}
        originals.append(target)
        content['illustration_files'].append(target.name)
        progress(f'配图 {index+1}/{len(content["cards"])} 已保存')
    progress('配图全部完成，正在排版图文卡片')
    return render_cards(content, platform, directory, illustrations=originals)
