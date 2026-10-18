"""Doubao video submit and conversation polling, derived from video.har."""
from __future__ import annotations
import re
import copy
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import requests
from .mock_doubao import response_error
from .providers import ProviderError

MODELS = {
    'mock_doubao_seedance_2_0_mini': 'seedance_v2.0_mini',
    'mock_doubao_seedance_2_0_fast': 'seedance_v2.0',
    'mock_doubao_seedance_2_0': 'seedance_v2.0_std',
    'mock_doubao_seedance_2_5': 'seedance_v2.5',
}
OPTIONS = json.loads(Path(__file__).with_name('doubao_web_video_options.json').read_text(encoding='utf-8'))

def objects(value):
    if isinstance(value, str) and value[:1] in '[{':
        try: yield from objects(json.loads(value))
        except ValueError: pass
    elif isinstance(value, dict):
        yield value
        for item in value.values(): yield from objects(item)
    elif isinstance(value, list):
        for item in value: yield from objects(item)

def extract_videos(value):
    urls = []
    for item in objects(value):
        if item.get('type') != 2 or not isinstance(item.get('video'), dict): continue
        video = item['video']
        url = video.get('download_url')
        if video.get('status') == 3 and isinstance(url,str) and url.startswith('https://') and url not in urls:
            urls.append(url)
    return urls

def captured_request(config, key, path):
    captured = config.get('web_video_request', {}).get(key, {})
    url = str(captured.get('url') or '')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.doubao.com' or parsed.path != path:
        raise ProviderError('缺少有效的豆包视频网页捕获模板：'+key)
    headers = {k:v for k,v in captured.get('headers', {}).items()
               if not k.startswith(':') and k.lower() not in {'cookie','content-length','accept-encoding'}}
    cookie = next((v for k,v in config.get('headers', {}).items() if k.lower()=='cookie' and v), None)
    if not cookie: raise ProviderError('尚未配置网页登录 Cookie；请在后台控制更新 Cookie')
    headers['Cookie'] = cookie
    return url, headers, copy.deepcopy(captured.get('body') or {})

def build_video_request(config, prompt, *, model, aspect=None, duration=None, reference=None):
    url, headers, body = captured_request(config, 'i2v_submit' if reference else 'submit', '/chat/completion')
    if model not in MODELS: raise ProviderError('视频模型未在实际网页配置中确认')
    options = OPTIONS[MODELS[model]]
    try:
        if body['chat_ability']['ability_type'] != 17: raise ValueError()
        ability = json.loads(body['chat_ability']['ability_param'])
        ability['model'] = MODELS[model]
        ratio = aspect or ability['ratio']
        if ratio not in {x['value'] for x in options['ratio']}: raise ProviderError('视频比例不在捕获配置中')
        seconds = int(duration or ability['duration'])
        if str(duration or seconds) != str(seconds) or not options['min_duration'] <= seconds <= options['max_duration']:
            raise ProviderError('该视频模型的时长范围为 '+str(options['min_duration'])+'–'+str(options['max_duration'])+' 秒（整数）')
        if not prompt.strip(): raise ProviderError('视频提示词不能为空')
        ability.update(ratio=ratio, duration=seconds)
        box = ability['input_box_content']
        box['user_input_content'] = prompt
        text = box['reply_message_format'] % prompt
        # HAR's visible text appends duration; ratio is a structured ability field.
        blocks=[block for message in body['messages'] for block in message['content_block']]
        texts=[block for block in blocks if 'text_block' in block.get('content',{})]
        if len(texts)!=1:raise ValueError()
        texts[0]['content']['text_block']['text']=text+'，'+str(seconds)+'s'
        if reference:
            attachments=[block for block in blocks if 'attachment_block' in block.get('content',{})]
            if len(attachments)!=1:raise ValueError()
            attachment=attachments[0]['content']['attachment_block']['attachments'][0]
            attachment['identifier']=str(uuid.uuid4())
            attachment['image']={'name':reference['name'],'uri':reference['uri'],'image_ori':{'url':'','width':reference['width'],'height':reference['height'],'format':reference['format'],'url_formats':{}}}
            attachments[0]['content']['attachment_block']['attachments']=[attachment]
        body['chat_ability']['ability_param'] = json.dumps(ability,ensure_ascii=False,separators=(',',':'))
        body['client_meta'].update(local_conversation_id='local_'+str(uuid.uuid4().int%10**16),conversation_id='',last_section_id='',last_message_index=None)
        for message in body['messages']:
            message['local_message_id']=str(uuid.uuid4())
            for block in message['content_block']:
                if block.get('block_id'):block['block_id']=str(uuid.uuid4())
        for key in ('unique_key','collect_id'):
            if body['option'].get(key): body['option'][key] = str(uuid.uuid4())
        body['option']['create_time_ms'] = int(time.time()*1000)
        body['option']['need_create_conversation'] = True
        body['option']['recovery_option']['req_create_time_sec'] = int(time.time())
        if body.get('ext',{}).get('collection_id'): body['ext']['collection_id'] = str(uuid.uuid4())
    except (KeyError,TypeError,ValueError):
        raise ProviderError('视频捕获模板的 chat_ability/messages/option 字段无效') from None
    return url, headers, body

def latest_assistant(value):
    messages=value.get('downlink_body',{}).get('pull_singe_chain_downlink_body',{}).get('messages',[])
    assistants=[message for message in messages if message.get('user_type')==2]
    return max(assistants,key=lambda message:int(message.get('index_in_conv') or 0)) if assistants else None

def build_confirmation_request(config, conversation, message, *, model, duration, aspect):
    labels={'mock_doubao_seedance_2_0_mini':'Seedance 2.0 Mini','mock_doubao_seedance_2_0_fast':'Seedance 2.0 Fast','mock_doubao_seedance_2_0':'Seedance 2.0','mock_doubao_seedance_2_5':'Seedance 2.5'}
    text='\n'.join(str(obj['text']) for obj in objects(message) if isinstance(obj.get('text'),str))
    if labels[model] not in text or not re.search(r'(?<!\d)'+str(int(duration))+r'\s*(秒|s)',text) or aspect not in (None,'','auto') and aspect not in text:
        raise ProviderError('豆包确认的模型、时长或比例与提交参数不匹配；未自动确认')
    try:url,headers,body=captured_request(config,'confirm','/chat/completion')
    except ProviderError:raise ProviderError('豆包要求确认，但尚未导入已验证的确认请求模板') from None
    body['client_meta'].update(conversation_id=conversation,last_section_id=message['section_id'],last_message_index=int(message['index_in_conv']))
    for item in body['messages']:
        item['local_message_id']=str(uuid.uuid4())
        for block in item['content_block']:
            if block.get('block_id'):block['block_id']=str(uuid.uuid4())
    body['option']['unique_key']=str(uuid.uuid4());body['option']['need_create_conversation']=False
    body['option']['create_time_ms']=int(time.time()*1000);body['option']['recovery_option']['req_create_time_sec']=int(time.time())
    return url,headers,body

def validate_video(path):
    import cv2
    capture = cv2.VideoCapture(str(path))
    try:
        ok, frame = capture.read()
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if not ok or fps <= 0 or frames <= 0:
            raise ProviderError('豆包返回的文件无法解码为有效视频')
        return {'width':int(frame.shape[1]),'height':int(frame.shape[0]),'duration_seconds':frames/fps,'fps':fps,'frames':frames}
    finally:
        capture.release()

class DoubaoWebVideoProvider:
    def __init__(self, config_path):
        self.config_path=Path(config_path)
        try: self.config = json.loads(self.config_path.read_text(encoding='utf-8'))
        except (OSError,ValueError): raise ProviderError('无法读取豆包视频配置') from None

    def generate(self, prompt, *, model, aspect=None, duration=None, image=None, video=None, diagnostics=None, progress=None, **kwargs):
        if video:raise ProviderError('豆包 mock 暂不支持参考视频，请使用文生视频或单图生视频')
        trace=diagnostics if diagnostics is not None else {}
        reference=None
        if image:
            from .doubao_upload_bridge import upload_references
            captured_request(self.config,'i2v_submit','/chat/completion')
            def upload_progress(value):
                trace.update(mode='i2v',upload=value)
                if progress:progress(dict(trace))
            references,trace['upload_verification_id']=upload_references([image],store_dir=self.config_path.parent,progress=upload_progress)
            reference=references[0]
            trace['reference_count']=1
        url, headers, body = build_video_request(self.config,prompt,model=model,aspect=aspect,duration=duration,reference=reference)
        poll_url, poll_headers, poll_body = captured_request(self.config,'poll','/im/chain/single')
        trace = diagnostics if diagnostics is not None else {}
        trace.update(protocol='web_video_chat_completion',mode='i2v' if image else 't2v',polls=0,reply_end=False)
        conversation = None
        try:
            def submit(url,headers,body):
                nonlocal conversation
                with requests.post(url,headers=headers,data=json.dumps(body,ensure_ascii=False,separators=(',',':')).encode(),stream=True,timeout=(15,180),allow_redirects=False) as response:
                    trace['http_status'] = response.status_code
                    if response.status_code != 200: raise ProviderError('豆包视频提交失败 HTTP '+str(response.status_code))
                    response.encoding='utf-8'
                    event=''
                    for line in response.iter_lines(decode_unicode=True):
                        if line.startswith('event:'): event=line[6:].strip()
                        if not line.startswith('data:'): continue
                        value=json.loads(line[5:])
                        failure=response_error(value,{'headers':headers})
                        if failure: raise ProviderError(failure)
                        if event=='SSE_REPLY_END': trace['reply_end']=True
                        if 'ack_client_meta' in value:
                            conversation=value['ack_client_meta']['conversation_id']
                            trace['conversation_id']=conversation
                            if progress: progress(dict(trace))
            submit(url,headers,body)
            if not conversation: raise ProviderError('视频提交未返回会话 ID；未重新提交')
            deadline=time.monotonic()+1800
            while time.monotonic()<deadline:
                poll_body['sequence_id']=str(uuid.uuid4())
                poll_body['uplink_body']['pull_singe_chain_uplink_body']['conversation_id']=conversation
                try:
                    response=requests.post(poll_url,headers=poll_headers,data=json.dumps(poll_body,ensure_ascii=False,separators=(',',':')).encode(),timeout=(15,45),allow_redirects=False)
                    trace['polls']+=1
                    if response.status_code != 200: raise ProviderError('视频查询失败 HTTP '+str(response.status_code))
                    value=response.json()
                    failure=response_error(value,{'headers':poll_headers})
                    if failure: raise ProviderError(failure)
                    urls=extract_videos(value)
                    if urls: return urls
                    latest=latest_assistant(value)
                    texts=[o.get('text','') for o in objects(latest or value) if isinstance(o.get('text'),str)]
                    if any('确认后' in text or '请先确认' in text for text in texts):
                        trace['awaiting_confirmation']=True
                        if not latest:raise ProviderError('豆包要求确认，但未取得可验证的消息游标；未自动确认')
                        if not trace.get('confirmation_sent'):
                            ability=json.loads(body['chat_ability']['ability_param'])
                            confirm_url,confirm_headers,confirm_body=build_confirmation_request(self.config,conversation,latest,model=model,duration=ability['duration'],aspect=ability['ratio'])
                            trace['confirmation_sent']=True
                            if progress:progress(dict(trace))
                            submit(confirm_url,confirm_headers,confirm_body)
                            trace['awaiting_confirmation']=False
                    trace.pop('poll_network_error',None)
                except requests.RequestException:
                    trace['poll_network_error']=True
                if progress: progress(dict(trace))
                time.sleep(10)
            raise ProviderError('豆包视频等待超时，请凭会话 ID 在豆包查看；未重复提交')
        except requests.RequestException:
            raise ProviderError('豆包视频提交网络中断，原请求可能已提交；未重新发送') from None
        except (ValueError,KeyError,TypeError):
            raise ProviderError('豆包视频响应结构无法解析；未重新提交') from None
