"""Continuous background photography with typography placed directly on the canvas."""
from PIL import Image,ImageDraw,ImageOps,ImageFilter
from math import ceil
import re

VERSION='full-image-unified-colors-v5'
WASH_ALPHA=32
COLOR_SCHEMES={
    'red_yellow':{'title':'#c90013','body':'#ffe600','title_stroke':'#fff9ed','body_stroke':'#080808'},
    'yellow':{'title':'#ffe600','body':'#ffe600','title_stroke':'#080808','body_stroke':'#080808'},
}
EDITORIAL_RULES="""内页是一张完整的背景图文海报：图片铺满画布，标题、短正文和重点直接排在整个背景上，不能分成照片区与文字区，不能放独立白色卡片、圆角文字框或上下拼接面板。封面按人物/非人物使用自适应标题组布局。
背景选题优先：经济、股票、财报、市场下跌必须使用证券交易、金融市场、下跌趋势或相关产业图片；不得用风景、美女、家居替代财经主题。高雅仅表示摄影、配色和排字质量，不是所有题材通用的素材分类。background_kind可选finance或semiconductor。背景审美统一要求：高雅、克制、自然摄影、真实材质、柔和光线、低饱和配色，可用风景、成年女性、生活场景或阅读环境；AI生图与图库查找同样遵守。每页另给background_kind，从landscape（风景）、portrait（高雅成年女性）、lifestyle（日常生活）、reading（阅读）中选择；这是背景氛围，不按文章比喻搜索裁判、马戏团、股票截图或杂乱图表。背景图服务阅读：使用贴合本页观点的自然环境、低对比场景、柔和光影或材质，画面上中部有连续低细节阅读空间，背景有细节但不抢文字。无文字、无标签、无水印。
心理/生活主题用暖白、浅绿等柔和日常氛围，财经科技用纸白、灰蓝；不强制暗黑、悲情剪影，可以选择高雅的成年女性人像、风景、日常生活与阅读等背景，作为氛围示意，不冒充案例人物；避免低俗、暴露、夸张摆拍和廉价网红滤镜。每页一个小观点，文字多就拆页，不缩成小字。标题与正文应是画面视觉主体，采用大字号和清楚行距；背景保留明显照片细节，不用强白蒙层洗成透明。同一作品全部内页固定一套配色，默认红色标题、黄色正文，也可整套黄色；不按页面、背景明暗或行切换颜色。文字使用实心粗体和统一描边保证可读性，不使用浅白细字或空心描边效果。
生图与图库按最终平台画幅选图：抖音9:16、小红书3:4、公众号16:9；主体偏边缘或成为环境一部分，文字不压面部或关键动作。图片只作氛围示意，不冒充真实案例人物。"""
PROFILES={
    'douyin':((1080,1920),(0,0,1080,1920),None,(80,300,800,1040),96,68),
    'xiaohongshu':((1080,1440),(0,0,1080,1440),None,(76,120,928,1200),92,64),
    'wechat':((1280,720),(0,0,1280,720),None,(76,60,1128,600),72,44),
}



def render_page(content,index,path,source,platform,*,font,wrap):
    if source is None:raise ValueError('图文内页缺少主题配图')
    size,photo_box,paper,copy,title_size,body_size=PROFILES[platform]
    warm=content.get('theme') in ('humanities','general')
    background,ink,accent=('#f5f1e8','#253b35','#417660') if warm else ('#f2f5f7','#233746','#3a617a')
    image=Image.new('RGB',size,background)
    with Image.open(source) as original:
        image=ImageOps.fit(original.convert('RGB'),size,Image.Resampling.LANCZOS,centering=(.5,.4)).filter(ImageFilter.GaussianBlur(.5))
    # A uniform translucent wash keeps the photograph continuous behind all
    # text. No opaque panel, lower blank canvas, or independent photo rectangle.
    wash=Image.new('RGBA',size,(*Image.new('RGB',(1,1),background).getpixel((0,0)),WASH_ALPHA))
    image=Image.alpha_composite(image.convert('RGBA'),wash).convert('RGB');draw=ImageDraw.Draw(image)
    card=content['cards'][index];tx,ty,tw,th=copy
    scheme=content.get('inner_color_scheme','red_yellow')
    if not isinstance(scheme,str) or scheme not in COLOR_SCHEMES:raise ValueError('未知内页配色方案')
    content['inner_color_scheme']=scheme
    colors=COLOR_SCHEMES[scheme]
    from .douyin_layout import readable_lines
    for selected_title in range(title_size,title_size-13,-2):
        title_face=font(selected_title,bold=True);title_lines=readable_lines(draw,card['heading'],title_face,tw-4)
        if len(title_lines)<=2:break
    if len(title_lines)>1 and not re.search(r'[A-Za-z0-9]',card['heading']) and len(title_lines[-1])<len(title_lines[0])*.55:
        breaks=[i+1 for i,char in enumerate(card['heading'][:-1]) if char in '，：、；']
        options=[[card['heading'][:i],card['heading'][i:]] for i in breaks]
        options=[pair for pair in options if all(draw.textlength(line,font=title_face)<=tw for line in pair)]
        if options:title_lines=min(options,key=lambda pair:abs(len(pair[0])-len(pair[1])))
        else:
            count=ceil(len(card['heading'])/len(title_lines))
            title_lines=[line for i in range(0,len(card['heading']),count) for line in wrap(draw,card['heading'][i:i+count],title_face,tw)]
    title_step=round(selected_title*1.3)
    if len(title_lines)>2:raise ValueError('内页标题过长，请拆分或简化，不缩小字号')
    yy=ty
    title_colors=[]
    for line in title_lines:
        fill,stroke=colors['title'],colors['title_stroke'];title_colors.append(fill)
        draw.text((tx,yy),line,font=title_face,fill=fill,anchor='lt',stroke_width=2,stroke_fill=stroke);yy+=title_step
    yy=max(yy+48,ty+(280 if platform!='wechat' else 200))
    body_top=yy
    for selected_body in range(body_size,body_size-5,-2):
        body_face=font(selected_body,bold=True);body_lines=readable_lines(draw,card['text'].strip(),body_face,tw-4)
        if len(body_lines)>2 and draw.textlength(body_lines[-1],font=body_face)<tw*.25:
            for factor in (.95,.9,.85):
                balanced=readable_lines(draw,card['text'].strip(),body_face,(tw-4)*factor)
                if len(balanced)<=len(body_lines)+1 and draw.textlength(balanced[-1],font=body_face)>=tw*.3:
                    body_lines=balanced;break
        body_step=round(selected_body*1.38)
        if yy+len(body_lines)*body_step<=ty+th and all(draw.textlength(line,font=body_face)<=tw-4 for line in body_lines):break
    if yy+len(body_lines)*body_step>ty+th or any(draw.textlength(line,font=body_face)>tw-4 for line in body_lines):raise ValueError('内页内容过密，请拆成更多片段，不缩小字号挤字')
    body_colors=[]
    for line in body_lines:
        fill,stroke=colors['body'],colors['body_stroke'];body_colors.append(fill)
        draw.text((tx,yy),line,font=body_face,fill=fill,anchor='lt',stroke_width=2,stroke_fill=stroke);yy+=body_step
    content.setdefault('page_rendering',{})[str(index+1)]={'version':VERSION,'platform':platform,
        'text_box':list(copy),'photo_box':list(photo_box),'body_font_size':selected_body,'title_font_size':selected_title,
        'wash_opacity':WASH_ALPHA/255,'contrast_mode':'fixed_palette','color_scheme':scheme,
        'title_colors':title_colors,'body_colors':body_colors,'text_style':'solid_bold_high_contrast',
        'body_top':body_top,'background_mode':'full_bleed_uniform_wash','separate_text_panel':False}
    image.save(path,'PNG')


def rules(platform):
    if platform=="xiaohongshu":
        from .xhs_layout import RULES
        return RULES
    return EDITORIAL_RULES
