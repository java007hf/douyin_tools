"""Prepare real per-card illustration assets before deterministic typography."""
from .cards import render_cards
from .elegant_backgrounds import direction
from PIL import Image
import re


def contextual_terms(terms):
    generic=set('adult elegant tall asian woman women female portrait girl beautiful lifestyle person people man male young natural light photography photo'.split())
    return [term for term in terms if (set(re.findall(r'[a-z]+',term.lower()))-generic)
            or ('portrait' in term.lower() and 'adult' in term.lower() and 'elegant' in term.lower())]


def prepare_images(tool, content, platform, directory, progress):
    originals = []
    content['image_kind'] = 'ai_illustrated_card'
    content['image_traces'] = []
    content['illustration_files'] = []
    for index, card in enumerate(content['cards']):
        cover = content.get('cover') if index == 0 else None
        aspect = {'douyin':'9:16','xiaohongshu':'3:4','wechat':'16:9'}[platform]
        if platform=='xiaohongshu' and not cover:aspect='4:3'
        if platform=='wechat':aspect='16:9'
        target = directory / f'illustration-{index+1:02d}.png'
        content['image_traces'].append({'status': 'pending'})
        def changed(trace):
            content['image_traces'][index] = {**trace, 'card_index': index + 1}
            progress(f'配图 {index+1}/{len(content["cards"])} · {trace.get("message", "生成中")}')

        kind,description,terms=direction(card,index,cover,theme=content.get('theme'),title=content.get('title',''))
        # Match the subject before applying a restrained visual treatment.
        # Financial photographs illustrate the subject, never live quotations.
        prompt=(f'为完整图文海报创作高雅自然摄影背景，画幅{aspect}。'+description+
                '。低对比、柔和光线、低饱和、真实材质，整张画布连续，上中部留低细节文字空间；不生成可读文字、价格、日期、水印、标牌、边框或卡片，不做戏剧化拼贴；允许财经主题使用无具体数字的下跌趋势图。'+
                (('人物放在下半部，主副标题统一在上方留白。' if cover['style']=='portrait' else '非人物封面，中部留连续低细节区域供居中标题组。') if cover else '人物或物体偏侧边，避免与画面上中部的文字争抢。'))
        from .cover_design import PALETTES
        prompt+='配色气质：'+PALETTES.get(content['cover'].get('palette'),PALETTES['gold'])['mood']+'。不要改变自然肤色。'
        if platform=='xiaohongshu' and not cover:
            prompt=(f'为小红书内页上方的大图创作完整自然摄影，画幅{aspect}。'+description+
                    '。图片独立呈现具体主题，主体完整清楚，真实材质、自然光线；文字将在图片下方白底区域排版，照片里不要标题、文字、水印、边框、卡片或蒙层，也不必为叠字留白。')
        card.setdefault('source_visual_plan',{'image_prompt':card['image_prompt'],'search_terms':card['search_terms']})
        card['image_prompt']=description
        card['search_terms']=terms
        card['background_kind']=kind
        tool.required_subject=kind if kind in ('finance','semiconductor') else None
        trace = tool.generate(prompt, target, changed, aspect=aspect, search_terms=terms)
        content['image_traces'][index] = {**trace, 'card_index': index + 1}
        originals.append(target)
        content['illustration_files'].append(target.name)
        progress(f'配图 {index+1}/{len(content["cards"])} 已保存')
    progress('配图全部完成，正在排版图文卡片')
    from .cover_design import VERSION, ZONES
    content['cover']['composition']={'version':VERSION,'structure':['headline','subject','support'],
                                    'headline_box':list(ZONES[platform][1]),'support_box':list(ZONES[platform][2])}
    names=render_cards(content, platform, directory, illustrations=originals)
    expected=ZONES[platform][0]
    checked=[]
    for name in names:
        with Image.open(directory/name) as image:
            size=image.size;image.verify()
        if size!=expected:
            raise ValueError(f'最终图卡尺寸不符：{name} 实际{size}，要求{expected}')
        checked.append({'file':name,'width':size[0],'height':size[1]})
    content['render_validation']={'status':'passed','actual_files':checked}
    return names
