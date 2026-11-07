"""Topic first, restrained art direction second; backgrounds are illustrative."""
import re
SCENES={
 'finance':('金融市场下跌主题：交易终端、证券交易屏幕或下行趋势的金融图表，克制清晰的财经摄影，非真实即时行情，不展示可识别具体价格或日期，不使用风景、人像或家居替代', ['stock market crash','stock trading screen','forex candlestick chart']),
 'semiconductor':('半导体产业与资本市场背景：存储芯片、半导体晶圆或数据中心，专业财经科技摄影，不展示虚构行情或价格', ['semiconductor manufacturing','electronic circuit board','computer memory module']),
 'landscape':('宁静湖泊、远山或自然林地，柔和晨光，低饱和，简洁连续的空间，无游客或醒目标牌', ['misty mountain lake','quiet forest landscape']),
 'portrait':('气质高雅的成年女性自然生活肖像，穿着得体、表情自然，窗边柔光，主体偏侧，非新闻当事人，不做夸张时装摆拍', ['adult woman reading window','elegant adult woman portrait']),
 'lifestyle':('自然日光下简洁舒适的客厅沙发、咖啡或阅读生活场景，真实材质、克制陈设，没有杂乱人群、卫生间或洁具', ['sunlit living room sofa','cozy living room window']),
 'reading':('窗边阅读、书本、木质桌面与柔和日光，安静生活感，构图简洁，书上不可出现清晰可读文字', ['book window soft light','reading coffee sunlight']),
}


def direction(card,index,cover=None,*,theme=None,title=''):
    kind=card.get('background_kind')
    if theme=='finance' or re.search(r'股市|股价|财报|证券|股指|美光',title):
        kind='semiconductor' if index>0 and re.search(r'供给|产能|存储|HBM',card.get('heading','')) else 'finance'
        description,terms=SCENES[kind]
        return kind,description,list(terms)
    if cover:
        kind='portrait' if cover.get('style')=='portrait' else 'landscape'
    if kind not in SCENES:kind=('landscape','reading','lifestyle','portrait')[(index-1)%4]
    description,terms=SCENES[kind]
    return kind,description,list(terms)
