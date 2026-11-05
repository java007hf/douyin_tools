"""Readable Xiaohongshu photo essays: large photographs and content-led spacing."""
from PIL import Image, ImageDraw, ImageOps


def render_page(content, index, path, photo, *, font, wrap):
    card=content['cards'][index]
    image=Image.new('RGB',(1080,1440),'white')
    draw=ImageDraw.Draw(image)
    layout=card.get('layout','photo_top')
    with Image.open(photo) if photo is not None else Image.new('RGB',(1080,800),'#e9e5df') as source:
        visual=source.convert('RGB')

    def lines(text,size,bold=False):
        face=font(size,bold=bold)
        return face,wrap(draw,text,face,952)

    def measured_text(text,size):
        face=font(size)
        paragraphs=[p.strip() for p in text.split('\n') if p.strip()]
        wrapped=[wrap(draw,p,face,952) for p in paragraphs]
        return face,wrapped,sum(len(p) for p in wrapped)*int(size*1.48)+max(0,len(wrapped)-1)*20

    title_face,title_lines=lines(card['heading'],64,True)
    title_h=len(title_lines)*84
    if layout=='text_focus':
        # A dense reading page has a generous, edge-to-edge photo strip, not a floating thumbnail.
        photo_h=470
        text_y=64
        for size in range(43,32,-1):
            body_face,body_lines,body_h=measured_text(card['text'],size)
            if text_y+title_h+36+body_h <= 1440-photo_h-62:break
        else:raise ValueError('小红书内容页文字超出版面，请拆分信息点')
        photo_y=text_y+title_h+36+body_h+52
        photo_h=1440-photo_y
        image.paste(ImageOps.fit(visual,(1080,photo_h),Image.Resampling.LANCZOS,centering=(.5,.38)),(0,photo_y))
    else:
        # Prefer 55% photographic coverage; shrink only enough to fit genuine copy.
        for photo_h in range(800,619,-20):
            text_y=photo_h+42
            for size in range(40,32,-1):
                body_face,body_lines,body_h=measured_text(card['text'],size)
                if text_y+title_h+28+body_h <= 1365:break
            else:continue
            break
        else:raise ValueError('小红书大图页文字过多，请使用内容页或拆分')
        image.paste(ImageOps.fit(visual,(1080,photo_h),Image.Resampling.LANCZOS,centering=(.5,.38)),(0,0))
    yy=text_y
    for line in title_lines:
        draw.text((64,yy),line,font=title_face,fill='#181818');yy+=84
    yy+=36 if layout=='text_focus' else 28
    for paragraph in body_lines:
        for line in paragraph:
            draw.text((64,yy),line,font=body_face,fill='#363636');yy+=int(body_face.size*1.48)
        yy+=20
    label=f'{index+1} / {len(content["cards"])}'
    if layout=='text_focus':
        draw.rectangle((900,1362,1048,1412),fill='white')
        draw.text((918,1370),label,font=font(24),fill='#555555')
    else:
        draw.text((930,1390),label,font=font(22),fill='#777777')
    image.save(path,'PNG')
