"""Original themed editorial illustrations and legible, downloadable PNG cards."""
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

PALETTES = {
    'xiaohongshu': ('#fffaf3', '#342b26', '#e95140', '#f4dfcc'),
    'wechat': ('#eef2ed', '#1e3b35', '#3e7766', '#d8e2d7'),
    'douyin': ('#151c29', '#f6f0e4', '#e4b97b', '#28374b'),
}


def font(size, bold=False):
    candidates = [os.environ.get('PUBLICATION_FONT', ''), 'C:/Windows/Fonts/msyhbd.ttc' if bold else 'C:/Windows/Fonts/msyh.ttc',
                  'C:/Windows/Fonts/simhei.ttf', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc']
    for path in candidates:
        if path and Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise RuntimeError('未找到中文字体，请设置 PUBLICATION_FONT 为中文字体文件路径')


def wrap(draw, text, face, width):
    lines, line = [], ''
    for char in text:
        if char == '\n':
            lines.append(line)
            line = ''
        elif line and draw.textlength(line + char, font=face) > width:
            if char in '，。！？：；、）》」』】”’…,.!?:;%)' and len(line)>1:
                carry=line[-1];lines.append(line[:-1]);line=carry+char
            elif line[-1:] in '（《「『【“‘(' and len(line)>1:
                carry=line[-1];lines.append(line[:-1]);line=carry+char
            else:
                lines.append(line)
                line = char
        else:
            line += char
    if line:
        lines.append(line)
    return lines


def illustration(draw, theme, box, ink, accent, muted):
    x, y, w, h = box
    def point(a, b):
        return (int(x + a * w), int(y + b * h))
    if theme == 'finance':
        # Symbolic market illustration: deliberately no invented prices or dates.
        for i, height in enumerate((.22, .43, .34, .62, .51, .77)):
            left, bottom = point(.08 + i * .14, .88)
            right, top = point(.16 + i * .14, .88 - height)
            draw.rounded_rectangle((left, top, right, bottom), radius=8, fill=muted if i % 2 else accent)
        draw.line([point(.04, .47), point(.25, .27), point(.43, .41), point(.63, .18), point(.85, .32), point(.96, .1)], fill=ink, width=7, joint='curve')
    elif theme == 'humanities':
        draw.ellipse((*point(.72, .02), *point(.94, .35)), fill=accent)
        draw.polygon([point(0, .85), point(.25, .18), point(.52, .85)], fill=muted)
        draw.polygon([point(.29, .85), point(.58, .3), point(.86, .85)], fill=accent)
        draw.polygon([point(.65, .85), point(.83, .42), point(1, .85)], fill=muted)
        for i in range(3):
            draw.arc((*point(.06, .79 + i * .055), *point(.94, 1.02 + i * .055)), 180, 355, fill=ink, width=3)
    elif theme == 'technology':
        draw.rounded_rectangle((*point(.32, .15), *point(.68, .78)), radius=22, fill=muted, outline=accent, width=6)
        for side in (0, 1):
            for i in range(4):
                draw.line([point(.32 if not side else .68, .25 + i * .13), point(.08 if not side else .92, .25 + i * .13)], fill=accent, width=5)
                cx, cy = point(.08 if not side else .92, .25 + i * .13)
                draw.ellipse((cx-7, cy-7, cx+7, cy+7), fill=ink)
        draw.line([point(.42, .4), point(.5, .3), point(.58, .4), point(.5, .6), point(.42, .4)], fill=ink, width=5)
    else:
        draw.ellipse((*point(.1, .12), *point(.58, .83)), fill=muted)
        draw.rounded_rectangle((*point(.42, .31), *point(.87, .88)), radius=22, outline=accent, width=9)
        draw.line([point(.25, .75), point(.72, .07)], fill=ink, width=6)


def render_cards(content, platform, directory, illustrations=None):
    if platform == 'douyin':
        from .douyin_layout import render_cards as render_douyin_cards
        return render_douyin_cards(content, directory, illustrations, font=font, wrap=wrap)
    wide = platform == 'wechat'
    width, height = (1280, 720) if wide else (1080, 1440)
    bg, ink, accent, muted = PALETTES[platform]
    files = []
    for index, card in enumerate(content['cards']):
        if index == 0 and content.get('cover'):
            from .covers import render_cover
            name = 'card-01.png'
            render_cover(content, platform, directory / name, illustrations[0] if illustrations is not None else None, font=font, wrap=wrap)
            files.append(name)
            continue
        if platform == 'xiaohongshu':
            from .xhs_layout import render_page
            name=f'card-{index+1:02d}.png'
            render_page(content,index,directory/name,illustrations[index] if illustrations is not None else None,font=font,wrap=wrap)
            files.append(name)
            continue
        image = Image.new('RGB', (width, height), bg)
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 56, 110, 62), fill=accent)
        draw.text((128, 43), {'xiaohongshu': '灵感笔记', 'wechat': '观点与观察', 'douyin': '滑动 · 看懂一个主题'}[platform], font=font(24), fill=ink)
        draw.text((width - 176, 43), f'{index + 1:02d} / {len(content["cards"]):02d}', font=font(24), fill=ink)
        heading_face, text_face = font(58 if wide else 68), font(30 if wide else 38)
        text_width = 650 if wide else width - 136
        heading = wrap(draw, card['heading'], heading_face, text_width)
        text = wrap(draw, card['text'], text_face, text_width)
        yy = 158 if wide else 164
        for line in heading:
            draw.text((68, yy), line, font=heading_face, fill=ink)
            yy += 80 if wide else 94
        yy += 26
        for line in text:
            draw.text((68, yy), line, font=text_face, fill=ink)
            yy += 48 if wide else 62
        box = (800, 210, 400, 340) if wide else (68, 830, 944, 470)
        if yy > (height - 120 if wide else 800):
            raise ValueError('卡片文字超出可用版面，请缩短标题或正文')
        if illustrations is not None:
            with Image.open(illustrations[index]) as source:
                visual = ImageOps.contain(source.convert('RGB'), (box[2], box[3]), Image.Resampling.LANCZOS)
            image.paste(visual, (box[0] + (box[2]-visual.width)//2, box[1] + (box[3]-visual.height)//2))
        else:
            illustration(draw, content['theme'], box, ink, accent, muted)
        draw.line((68, height - 100, width - 68, height - 100), fill=muted, width=2)
        traces = content.get('image_traces', [])
        label = '图库配图' if index < len(traces) and traces[index].get('ai_generated') is False else 'AI配图' if illustrations is not None else '概念插画'
        draw.text((68, height - 78), label + ' · 根据原内容整理' + (' · 非真实行情' if content['theme'] == 'finance' else ''), font=font(22), fill=ink)
        name = f'card-{index+1:02d}.png'
        image.save(directory / name)
        files.append(name)
    return files
