"""Portrait Douyin posters with large imagery and readable phone-safe text."""
from math import ceil
import re
from PIL import Image, ImageDraw, ImageOps

WIDTH, HEIGHT = 1080, 1920
LAYOUT_VERSION = 'douyin-integrated-inner-v6'
BACKGROUND = '#202936'
INK = '#fffdf5'
ACCENT = '#ffeb58'
MUTED = '#bcc7d2'
# Conservative bounds from the supplied phone screenshots: search above,
# action rail on the right, expanded caption below. These are design bounds,
# not a claim that every device uses identical native UI geometry.
SAFE_BOX = (72, 280, 820, 1080)


def spec():
    return {'width': WIDTH, 'height': HEIGHT, 'aspect': '9:16', 'layout_version': LAYOUT_VERSION,
            'text_safe_box': list(SAFE_BOX)}


def readable_lines(draw, text, face, width):
    number=r'\d+(?:[.,]\d+)*(?:万美元|亿美元|亿元|万元|美元|人民币|%|万|亿|倍|年|岁|元)?'
    tokens=re.findall(number+r'(?:\s*(?:vs|VS|—|–|~|至|到|-)\s*'+number+r')?|[A-Za-z]+|\n|.',text)
    lines=[];current=[]
    for token in tokens:
        if token=='\n':
            lines.append(''.join(current));current=[];continue
        if current and draw.textlength(''.join(current)+token,font=face)>width:
            carry=[]
            if token in '，。！？：；、）》」』】”’…,.!?:;%)' or current[-1] in '（《「『【“‘(':
                carry=[current.pop()]
            lines.append(''.join(current));current=carry
        current.append(token)
    if current:lines.append(''.join(current))
    return lines


def heading(draw, text, box, *, font, wrap, maximum=90, centered=False, color=ACCENT, emphasis=False):
    x, y, width, height = box
    for size in range(maximum, 43, -2):
        face = font(size, bold=True)
        lines = readable_lines(draw, text, face, width)
        if len(lines)>1 and not re.search(r'[0-9A-Za-z]',text) and not any(c.isspace() for c in text) and len(lines[-1]) < len(lines[0])*.55:
            count=ceil(len(text)/len(lines))
            lines=[line for i in range(0,len(text),count) for line in wrap(draw,text[i:i+count],face,width)]
        step=round(size*1.30)
        if len(lines)*step<=height and all(draw.textlength(line,font=face)<=width for line in lines):
            for line in lines:
                xx=x+(width-draw.textlength(line,font=face))/2 if centered else x
                # Use the exact supplied title; numeric emphasis never adds a claim.
                parts=re.split(r'(\d+(?:[.,]\d+)*(?:%|万|亿|倍|年|岁|元)?)',line) if emphasis else [line]
                for part in parts:
                    fill='#ff742d' if emphasis and re.match(r'\d',part) else color
                    draw.text((round(xx),y),part,font=face,fill=fill,stroke_width=3,stroke_fill='#17202a')
                    xx+=draw.textlength(part,font=face)
                y+=step
            return y
    raise ValueError('抖音标题超出竖版可读区域，请简化标题')


def photo(image, source, box, *, centering=(.5,.45)):
    if source is None:
        raise ValueError('抖音图文缺少真实配图，请先生成或选择图片')
    with Image.open(source) as original:
        fitted=ImageOps.fit(original.convert('RGB'),(box[2],box[3]),Image.Resampling.LANCZOS,centering=centering)
    image.paste(fitted,(box[0],box[1]))


def render_cover(content, path, illustration, *, font, wrap):
    from .cover_design import render_cover as shared_cover
    return shared_cover(content, 'douyin', path, illustration, font=font, wrap=wrap)


def render_page(content,index,path,illustration,*,font,wrap):
    from .editorial_pages import render_page as integrated_page
    return integrated_page(content,index,path,illustration,'douyin',font=font,wrap=wrap)


def render_cards(content,directory,illustrations,*,font,wrap):
    if illustrations is None or len(illustrations)!=len(content['cards']):
        raise ValueError('抖音卡片与原始配图数量不一致')
    names=[]
    for index in range(len(content['cards'])):
        name=f'card-{index+1:02d}.png'
        if index==0:
            render_cover(content,directory/name,illustrations[index],font=font,wrap=wrap)
        else:
            render_page(content,index,directory/name,illustrations[index],font=font,wrap=wrap)
        names.append(name)
    return names
