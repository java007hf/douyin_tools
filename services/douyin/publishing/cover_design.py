"""One cover composition contract shared by editorial planning, images and rendering."""
import re
from PIL import Image, ImageDraw, ImageOps

VERSION = 'subject-adaptive-cover-v3'
PALETTES = {
    'gold': {'title':'#ffeb58','highlight':'#ff923c','mood':'深灰、暖金、少量橙色，沉稳清楚'},
    'teal': {'title':'#ffffff','highlight':'#60e8d0','mood':'低饱和青绿、深灰、少量暖白，清晰克制'},
    'warm': {'title':'#fff2c8','highlight':'#ffc25b','mood':'自然米白、暖棕、少量金黄，亲近明亮'},
}
EDITORIAL_RULES = '''所有产品封面统一三段结构：上方主标题、中间醒目主视觉、下方补充文案。
headline只表达一个可被正文兑现的核心问题或结论，6至16字为宜、最多18字，排成1至2行；不要把主标题拆散放在多个位置。
subtitle补充主标题没有说出的原因、条件、对比或阅读收益，8至20字为宜、最多32字；不得重复标题，不承担整篇摘要，不堆多条口号。
中间只保留一个与选题相关的视觉焦点，人物面部、关键物体或动作清晰完整，不让文字横穿面部，不拼贴多个人像或无关装饰。
主标题用醒目粗体黄/白对比，补充文案较小；只强调原资料已有的关键数字或词，不创造收益、金额、身份或经历。字体、颜色、描边由排版器执行，不让生图模型画字。
cover.image_prompt和第一张card.image_prompt必须使用同一个封面构图方案。图库搜索词必须含与主题有关的职业、动作、道具或环境，不得仅用通用美女/人像词。
人物偏好必须服从选题；封面人物不冒充作者、当事人或真实收益获得者。其他内页按各页观点配图，不把封面人像复制到每页。
所有平台沿用此阅读层级；仅按9:16、3:4、16:9适配尺寸与平台遮挡区，不能改回左文右图、文字集中顶部加底部小照片或多处零碎标题。'''
EDITORIAL_RULES += '''\n先判断封面表达类型，再确定一个主题主视觉，而不是先选一张通用人像。
cover增加visual_type（overview/method/comparison/story/trend之一）、visual_focus（最多80字的具体可见主体/动作，不写抽象口号）、palette（gold/teal/warm之一）、emphasis_words（从headline原文中选1至2个精确连续词组，每个最多8字，不改写或创造词语）。
主题、主视觉、配色、标题重点必须形成一套方案：数据/趋势可用gold，科技/方法可用teal，生活/人文可用warm；单一主色、辅色和高亮色，不堆花色。关键词高亮而非整行全黄，非关键词以白/浅色衬托。保留平直、清楚的三段结构，不强制弧形字或科技纹理。'''
EDITORIAL_RULES += '''\n封面最终构图覆盖前述三段位置规则：人物封面必须style=portrait，人物在下半部，主标题与副标题集中在上方、紧密相邻，不把副标题放到人物下面；非人物封面style=scene/bold/editorial/white_red，允许标题组居中突出，副标题紧随主标题。不要要求上下两条深色蒙层，不要文字遮脸。'''

IMAGE_RULES = '''无字封面摄影构图：画面上方为低细节主标题留白，中间为唯一醒目的主题主体，下方为低细节补充文案留白。
画面中段主体占据主要视觉面积：脸、关键物体或动作集中在中间，完整清楚、自然真实，避免重要主体贴边；上、下文字带不出现另一张脸或抢眼物体。
只安排一个主要场景，人物/道具/环境服务本篇主题；不同选题改变具体场景，不复用通用棚拍人像。自然光、真实材质、清楚的视觉对比，不要复杂拼贴、海报边框、装饰标签。
不要在照片中生成任何汉字、英文、数字、字幕、Logo或水印；标题、补充文案和重点强调全部由后续排版程序添加。'''

ZONES = {
    'douyin': ((1080,1920), (72,280,820,250), (72,1120,820,210), (550,1080)),
    'xiaohongshu': ((1080,1440), (64,80,952,270), (64,1100,952,220), (380,1040)),
    'wechat': ((1280,720), (64,32,1152,160), (64,552,1152,120), (215,520)),
}


def image_rules(platform):
    if platform == 'douyin':
        return IMAGE_RULES+'抖音9:16：顶部15%至28%标题带、中间29%至56%视觉焦点、58%至69%补充带；面部不放在顶部搜索区，右侧18%及底部25%不放重要细节。'
    if platform == 'xiaohongshu':
        return IMAGE_RULES+'小红书3:4：顶部6%至24%标题带，中间27%至72%视觉焦点，底部76%至92%补充带。'
    return IMAGE_RULES+'公众号16:9：顶部5%至26%标题带，中间30%至72%视觉焦点，底部77%至93%补充带，兼顾缩略图可读性。'


def visual_plan(cover):
    palette=PALETTES.get(cover.get('palette'),PALETTES['gold'])
    return ('本篇主视觉焦点：'+str(cover.get('visual_focus') or cover['image_prompt'])+
            '。场景配色气质：'+palette['mood']+'。配色不改变人物真实肤色和物体正常颜色；不在照片中生成关键词或标题。')


def planned_lines(draw,text,face,width,words,wrap):
    if not words:return wrap(draw,text,face,width)
    pattern='|'.join(re.escape(word) for word in sorted(words,key=len,reverse=True))
    tokens=re.findall(pattern+r'|\d+(?:[.,]\d+)*(?:%|万|亿|倍|年|岁|元)?|\n|.',text)
    lines=[];line=''
    for token in tokens:
        if token=='\n':lines.append(line);line='';continue
        if line and draw.textlength(line+token,font=face)>width:
            lines.append(line);line=''
        line+=token
    if line:lines.append(line)
    return lines


def draw_copy(draw,text,box,*,font,wrap,maximum,color,words=(),highlight='#ff923c'):
    x,y,width,height=box
    for size in range(maximum,29,-2):
        face=font(size,bold=True);stroke=max(2,round(size*.035))
        lines=planned_lines(draw,text,face,width-2*stroke,words,wrap)
        step=round(size*1.3)
        if len(lines)>2 or len(lines)*step+stroke*2>height:continue
        if any(draw.textlength(line,font=face)>width-2*stroke for line in lines):continue
        boxes=[]
        for line in lines:
            xx=x+(width-draw.textlength(line,font=face))/2
            pattern='|'.join(re.escape(word) for word in sorted(words,key=len,reverse=True))
            pattern='('+pattern+')' if pattern else r'(\d+(?:[.,]\d+)*(?:%|万|亿|倍|年|岁|元)?)'
            for part in re.split(pattern,line):
                if not part:continue
                fill=highlight if (part in words if words else re.match(r'\d',part)) else color
                # Use an explicit top anchor so font ascenders cannot escape the box.
                draw.text((round(xx),y),part,font=face,fill=fill,stroke_width=stroke,stroke_fill='#17202a',anchor='lt')
                boxes.append(draw.textbbox((round(xx),y),part,font=face,stroke_width=stroke,anchor='lt'))
                xx+=draw.textlength(part,font=face)
            y+=step
        return boxes
    raise ValueError('封面文案超过两行可读区域，请由内容模型精简，不截断文字')


def render_cover(content,platform,path,illustration,*,font,wrap):
    if illustration is None:raise ValueError('封面缺少主视觉素材')
    size,top,bottom,focus=ZONES[platform]
    portrait=content['cover'].get('style')=='portrait'
    if platform=='douyin':
        top=(72,300 if portrait else 620,820,280)
        bottom=(72,610 if portrait else 930,820,160)
    elif platform=='xiaohongshu':
        top=(64,100 if portrait else 400,952,270)
        bottom=(64,400 if portrait else 700,952,160)
    else:
        top=(64,150,1152,200);bottom=(64,380,1152,120)
    with Image.open(illustration) as source:
        image=ImageOps.fit(source.convert('RGB'),size,Image.Resampling.LANCZOS,centering=(.5,.5))
    draw=ImageDraw.Draw(image)
    palette=PALETTES.get(content['cover'].get('palette'),PALETTES['gold'])
    words=content['cover'].get('emphasis_words',())
    draw_copy(draw,content['cover']['headline'],top,font=font,wrap=wrap,
              maximum=112 if platform!='wechat' else 82,color='#fffdf5' if words else palette['title'],
              words=words,highlight=palette['highlight'])
    draw_copy(draw,content['cover'].get('subtitle',''),bottom,font=font,wrap=wrap,
              maximum=76 if platform!='wechat' else 54,color='#fffdf5')
    image.save(path,'PNG')
    result={'version':VERSION,'platform':platform,'structure':['headline','subject','support'],
            'headline_box':list(top),'subject_y_range':list(focus),'support_box':list(bottom),
            'placement':'above_subject' if portrait else 'centered_group','dark_bands':False}
    content['cover']['composition']=result
    return result
