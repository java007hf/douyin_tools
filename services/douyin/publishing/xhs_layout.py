"""Xiaohongshu inner pages: large top photograph, black copy on white below."""
from PIL import Image,ImageDraw,ImageOps

VERSION='xhs-photo-top-white-copy-v1'
RULES="""小红书内页使用上方大图、下方纯白文字区：图片约占一半至六成，黑色粗体标题、深灰正文、自然段落与清楚行距。文字不叠在照片上，不使用抖音的红黄字、整版背景或整体蒙层。每页一个小观点，目标40至70字，上限100字；内容过多拆成更多片段，每页独立配图，不缩小字体。配图按选题选择真实自然摄影场景，照片内不生成文字，不必专门为标题留白。封面继续单独策划。"""


def render_page(content,index,path,photo,*,font,wrap):
    if photo is None:raise ValueError('小红书内页缺少主题图片')
    card=content['cards'][index]
    if len(card['text'].strip())>100:raise ValueError('小红书单页文字过密，请拆成多个片段')
    image=Image.new('RGB',(1080,1440),'white');draw=ImageDraw.Draw(image)
    title_face=font(68,bold=True);body_face=font(48)
    from .douyin_layout import readable_lines
    titles=readable_lines(draw,card['heading'],title_face,936)
    lines=readable_lines(draw,card['text'].strip(),body_face,936)
    if len(titles)>2:raise ValueError('小红书内页标题过长，请简化')
    text_height=len(titles)*88+24+len(lines)*70
    for photo_height in range(820,679,-20):
        text_y=photo_height+48
        if text_y+text_height<=1370:break
    else:raise ValueError('小红书内页文字过密，请拆页，不缩小字体')
    with Image.open(photo) as source:
        visual=ImageOps.fit(source.convert('RGB'),(1080,photo_height),Image.Resampling.LANCZOS,centering=(.5,.4))
    image.paste(visual,(0,0));yy=text_y
    for line in titles:
        draw.text((72,yy),line,font=title_face,fill='#111111',anchor='lt');yy+=88
    yy+=24
    for line in lines:
        draw.text((72,yy),line,font=body_face,fill='#333333',anchor='lt');yy+=70
    draw.text((980,1390),f'{index+1}/{len(content["cards"])}',font=font(22),fill='#888888',anchor='rt')
    content['inner_color_scheme']='xhs_black_on_white'
    content.setdefault('page_rendering',{})[str(index+1)]={'version':VERSION,'platform':'xiaohongshu',
        'photo_box':[0,0,1080,photo_height],'text_box':[72,text_y,936,1370-text_y],
        'title_colors':['#111111'],'body_colors':['#333333'],'body_font_size':48,
        'background_mode':'photo_top_white_copy','separate_text_panel':True}
    image.save(path,'PNG')
