"""Portrait Douyin posters with large imagery and readable phone-safe text."""
from math import ceil
import re
from PIL import Image, ImageDraw, ImageOps

WIDTH, HEIGHT = 1080, 1920
LAYOUT_VERSION = 'douyin-portrait-v2'
BACKGROUND = '#202936'
INK = '#fffdf5'
ACCENT = '#ffe4a0'
MUTED = '#bcc7d2'


def spec():
    return {'width': WIDTH, 'height': HEIGHT, 'aspect': '9:16', 'layout_version': LAYOUT_VERSION}


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


def heading(draw, text, box, *, font, wrap, maximum=90, centered=False):
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
                draw.text((round(xx),y),line,font=face,fill=ACCENT)
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
    image=Image.new('RGB',(WIDTH,HEIGHT),BACKGROUND)
    full=content['cover'].get('style') in ('portrait','scene')
    photo(image,illustration,(0,0,WIDTH,HEIGHT) if full else (0,700,WIDTH,HEIGHT-700),centering=(.5,.32))
    shade=Image.new('RGBA',image.size,(0,0,0,0))
    overlay=ImageDraw.Draw(shade)
    if full:
        for y in range(1000):
            overlay.line((0,y,WIDTH,y),fill=(20,28,38,round(235*(1-y/1000)**.6)))
    else:
        for y in range(700,860):
            overlay.line((0,y,WIDTH,y),fill=(32,41,54,round(255*(1-(y-700)/160))))
    image=Image.alpha_composite(image.convert('RGBA'),shade).convert('RGB')
    draw=ImageDraw.Draw(image)
    end=heading(draw,content['cover']['headline'],(72,145,WIDTH-144,390),font=font,wrap=wrap,maximum=130,centered=True)
    face=font(48)
    subtitle=content['cover'].get('subtitle','')
    lines=wrap(draw,subtitle,face,WIDTH-144)
    yy=max(440,end+24)
    for line in lines:
        if yy+65>680:raise ValueError('抖音封面副标题超出竖版可读区域')
        draw.text((round((WIDTH-draw.textlength(line,font=face))/2),yy),line,font=face,fill=INK)
        yy+=65
    traces=content.get('image_traces',[])
    label='图库配图' if traces and traces[0].get('ai_generated') is False else '场景配图'
    draw.text((72,1640),label+' · 场景示意',font=font(24),fill=INK,stroke_width=1,stroke_fill=BACKGROUND)
    image.save(path,'PNG')


def render_page(content,index,path,illustration,*,font,wrap):
    image=Image.new('RGB',(WIDTH,HEIGHT),BACKGROUND)
    draw=ImageDraw.Draw(image)
    card=content['cards'][index]
    y=heading(draw,card['heading'],(72,112,WIDTH-144,270),font=font,wrap=wrap,maximum=86)+38
    text='\n'.join(line for line in card['text'].splitlines() if line.strip())
    for size in range(52,41,-2):
        face=font(size)
        lines=readable_lines(draw,text,face,WIDTH-144)
        step=round(size*1.36)
        if y+len(lines)*step<=805 and all(draw.textlength(line,font=face)<=WIDTH-144 for line in lines):break
    else:raise ValueError('抖音正文超出竖版可读区域，请压缩本页正文')
    for line in lines:
        draw.text((72,y),line,font=face,fill=INK)
        y+=step
    photo_y=y+56
    photo_height=1590-photo_y
    if photo_height<520:raise ValueError('抖音卡片文字过密，配图区不足')
    photo(image,illustration,(0,photo_y,WIDTH,photo_height))
    draw=ImageDraw.Draw(image)
    traces=content.get('image_traces',[])
    label='图库配图' if index<len(traces) and traces[index].get('ai_generated') is False else '场景配图'
    draw.text((72,1640),label+' · 根据来源内容整理',font=font(24),fill=MUTED)
    image.save(path,'PNG')


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
