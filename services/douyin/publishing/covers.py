"""Platform cover layouts, with generated visuals and deterministic CJK titles."""
from PIL import Image, ImageDraw, ImageOps
import math


def render_cover(content, platform, path, illustration, *, font, wrap):
    if platform == 'douyin':
        from .douyin_layout import render_cover as render_douyin_cover
        return render_douyin_cover(content, path, illustration, font=font, wrap=wrap)
    cover = content['cover']
    wide = platform == 'wechat'
    width, height = (1280, 720) if wide else (1080, 1440)
    style = cover['style']
    background = '#ffffff' if style == 'white_red' else '#171d27'
    image = Image.new('RGB', (width, height), background)
    if illustration is not None:
        with Image.open(illustration) as source:
            visual = source.convert('RGB')
    else:
        visual = Image.new('RGB', (width, height), '#b8c7bf')
    draw = ImageDraw.Draw(image)

    def title(box, color, maximum):
        x, y, w, h = box
        for size in range(maximum, 39, -4):
            face = font(size,bold=True)
            lines = wrap(draw, cover['headline'], face, w)
            if len(lines) > 1:
                count = math.ceil(len(cover['headline']) / len(lines))
                if len(lines) == 2 and cover['headline'][count:count+1] in '的了与和在':
                    count += 1
                lines = [line for offset in range(0, len(cover['headline']), count)
                         for line in wrap(draw, cover['headline'][offset:offset+count], face, w)]
            spacing = int(size * 1.24)
            if len(lines) * spacing <= h:
                for line in lines:
                    draw.text((x, y), line, font=face, fill=color, stroke_width=1)
                    y += spacing
                return y
        raise ValueError('封面标题超出可用版面')

    def subtitle(x, y, color, w):
        face = font(32 if wide else 38)
        for line in wrap(draw, cover['subtitle'], face, w):
            draw.text((x, y), line, font=face, fill=color)
            y += 48
        return y

    if style == 'white_red':
        bottom = title((64, 90, width-128, 420), '#df242d', 134)
        text_end=subtitle(70,bottom+32,'#333333',width-140)
        photo_y=max(500,text_end+72)
        art=ImageOps.fit(visual,(1080,1440-photo_y),Image.Resampling.LANCZOS,centering=(.5,.38))
        image.paste(art,(0,photo_y))
        footer = '#ffffff'
    elif style == 'editorial':
        image.paste(ImageOps.fit(visual, (width, height), Image.Resampling.LANCZOS), (0, 0))
        draw.rectangle((0, 0, 730, height), fill='#f4f3ed')
        draw.text((64, 58), '观点与观察', font=font(25), fill='#49615a')
        draw.rectangle((64, 108, 132, 116), fill='#346c5b')
        bottom = title((64, 170, 590, 360), '#183a32', 94)
        subtitle(68, min(570, bottom+30), '#49615a', 590)
        footer = '#49615a'
    elif style == 'bold':
        draw.text((68, 70), '看懂一个主题', font=font(28), fill='#f4cd6e')
        bottom = title((64, 210, width-128, 460), '#ffe29a', 138)
        subtitle(70, max(620, bottom+24), '#f7f4eb', width-140)
        art = ImageOps.fit(visual, (944, 530), Image.Resampling.LANCZOS)
        image.paste(art, (68, 800))
        footer = '#d8dfdf'
    else:
        image.paste(ImageOps.fit(visual, (width, height), Image.Resampling.LANCZOS, centering=(.5, .38)), (0, 0))
        shade = Image.new('RGBA', image.size, (0, 0, 0, 0))
        gradient = ImageDraw.Draw(shade)
        start = int(height*.38)
        for y in range(start, height):
            alpha = int(235 * ((y-start)/(height-start))**.7)
            gradient.line((0, y, width, y), fill=(10, 18, 22, alpha))
        image = Image.alpha_composite(image.convert('RGBA'), shade).convert('RGB')
        draw = ImageDraw.Draw(image)
        draw.text((64, 60), '生活与观察' if style == 'portrait' else '值得停下来看看', font=font(26), fill='white')
        bottom = title((64, int(height*(.43 if wide else .57)), width-128, int(height*.27)), '#ffffff', 92 if wide else 116)
        subtitle(68, bottom+24, '#f4e7c7', width-136)
        footer = '#e6e5dc'
    traces = content.get('image_traces', [])
    label = '图库配图' if traces and traces[0].get('ai_generated') is False else 'AI配图'
    if style!='white_red':
        draw.text((64, height-55), label + ' · 场景示意', font=font(20), fill=footer)
    image.save(path, 'PNG')
