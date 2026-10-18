"""Doubao /chat/completion adapter derived from verified HAR and cURL captures."""
from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .mock_doubao import extract_images, response_error
from .providers import ProviderError


OPTIONS = json.loads(Path(__file__).with_name('doubao_web_options.json').read_text(encoding='utf-8'))
MODELS = {
    'mock_doubao_seedream_5_0_flash':'Seedream 5.0 Flash',
    'mock_doubao_seedream_5_0_pro':'Seedream 5.0 Pro',
    'mock_doubao_seedream_5_0_lite':'Seedream 5.0 Lite',
    'mock_doubao_seedream_4_5':'Seedream 4.5',
    'mock_doubao_seedream_4_0':'Seedream 4.0',
}


def build_web_request(config, prompt, *, model=None, style=None, aspect=None, references=None):
    captured = config.get('web_reference_request' if references else 'web_request') or {}
    url = str(captured.get('url') or '')
    parsed = urlsplit(url)
    if parsed.scheme != 'https' or parsed.hostname != 'www.doubao.com' or parsed.path != '/chat/completion':
        raise ProviderError('网页请求必须使用捕获的 HTTPS www.doubao.com/chat/completion 地址')
    headers = {key:value for key,value in captured.get('headers', {}).items()
               if not key.startswith(':') and key.lower() not in {'content-length', 'accept-encoding'}}
    # The Admin Cookie field is the explicit session refresh entry point.
    cookie = next((v for k,v in config.get('headers', {}).items() if k.lower()=='cookie' and v), None)
    if cookie:
        headers = {k:v for k,v in headers.items() if k.lower()!='cookie'}
        headers['Cookie'] = cookie
    if not any(key.lower()=='cookie' and value for key,value in headers.items()):
        raise ProviderError('尚未配置网页登录 Cookie；请在后台控制更新 Cookie')
    body = copy.deepcopy(captured.get('body') or {})
    try:
        ability = json.loads(body['chat_ability']['ability_param'])
        if body['chat_ability']['ability_type'] != 3 or ability['ability_type'] != 1:
            raise ValueError()
        params = ability['ability_param']
        box = params['input_box_content']
        if not prompt.strip():
            raise ProviderError('生图提示词不能为空')
        if model and model != 'mock_doubao_seedream':
            if model not in MODELS:
                raise ProviderError('网页请求未确认该模型映射')
            params['model'] = MODELS[model]
        if style:
            labels = {item['value']:item['label'] for item in OPTIONS['style']}
            if style not in labels:
                raise ProviderError('风格不在捕获的豆包配置中')
            old_label = labels.get(params.get('style'))
            template = box.get('style_message_text', '')
            if references and not template:
                source=json.loads(config['web_request']['body']['chat_ability']['ability_param'])['ability_param']
                old_label=labels.get(source.get('style'))
                template=source['input_box_content'].get('style_message_text','')
            if not old_label or old_label not in template:
                raise ProviderError('捕获模板缺少可验证的风格文字格式')
            box['style_message_text'] = template.replace(old_label, labels[style])
            params['style'] = style
        if aspect:
            if aspect not in {item['value'] for item in OPTIONS['ratio']}:
                raise ProviderError('比例不在捕获的豆包配置中')
            params['ratio'] = aspect
        box['user_input_content'] = prompt
        text = box['reply_message_format'] % prompt
        if box.get('style_message_text'):
            text += '，' + box['style_message_text']
        if params.get('ratio') not in (None, '', 'auto'):
            text += '，' + params['ratio']
        text_blocks=[block for message in body['messages'] for block in message['content_block'] if 'text_block' in block.get('content',{})]
        if len(text_blocks)!=1:raise ValueError()
        text_blocks[0]['content']['text_block']['text'] = text
        if references:
            attachment_blocks=[block for message in body['messages'] for block in message['content_block'] if 'attachment_block' in block.get('content',{})]
            if len(attachment_blocks)!=1 or not 1<=len(references)<=2:raise ValueError()
            template=attachment_blocks[0]['content']['attachment_block']['attachments'][0]
            attachments=[]
            for reference in references:
                attachment=copy.deepcopy(template)
                attachment['identifier']=str(uuid.uuid4())
                attachment['image']={'name':reference['name'],'uri':reference['uri'],
                    'image_ori':{'url':'','width':reference['width'],'height':reference['height'],'format':reference['format'],'url_formats':{}}}
                attachments.append(attachment)
            attachment_blocks[0]['content']['attachment_block']['attachments']=attachments
        body['chat_ability']['ability_param'] = json.dumps(ability, ensure_ascii=False, separators=(',', ':'))
        body['client_meta'].update(local_conversation_id='local_'+str(uuid.uuid4().int % 10**16),
                                   conversation_id='', last_section_id='', last_message_index=None)
        for message in body['messages']:
            message['local_message_id'] = str(uuid.uuid4())
            for block in message['content_block']:
                if block.get('block_id'):block['block_id'] = str(uuid.uuid4())
        for key in ('unique_key', 'collect_id'):
            if body['option'].get(key):
                body['option'][key] = str(uuid.uuid4())
        body['option']['create_time_ms'] = int(time.time()*1000)
        body['option']['need_create_conversation'] = True
        body['option']['recovery_option']['req_create_time_sec'] = int(time.time())
        if body.get('ext', {}).get('collection_id'):
            body['ext']['collection_id'] = str(uuid.uuid4())
    except (KeyError, TypeError, ValueError):
        raise ProviderError('网页模板缺少已验证的 chat_ability/messages/option 字段') from None
    return url, headers, body


class DoubaoWebImageProvider:
    def __init__(self, config_path: Path):
        self.config_path=config_path
        try:
            self.config = json.loads(config_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise ProviderError('无法读取豆包网页请求配置') from None

    def generate(self, prompt, *, image=None, reference_images=None, model=None, style=None, aspect=None, count=1, diagnostics=None, progress=None, **kwargs):
        if int(count or 1) != 1:
            raise ProviderError('当前网页请求仅验证了单次生图，请将数量设为 1')
        trace = diagnostics if diagnostics is not None else {}
        references=None
        paths=reference_images or ([image] if image else [])
        if paths:
            # Check the captured request before starting a browser upload.
            if not self.config.get('web_reference_request'):raise ProviderError('尚未导入已验证的豆包参考图请求模板')
            from .doubao_upload_bridge import upload_references
            references,trace['upload_verification_id']=upload_references(paths,store_dir=self.config_path.parent,progress=progress)
            trace['reference_count']=len(references)
        url, headers, body = build_web_request(self.config, prompt, model=model, style=style, aspect=aspect,references=references)
        trace.update(protocol='web_chat_completion', parsed_events=0, reply_end=False)
        timeout = min(600, max(1, int(self.config.get('timeout', 180))))
        started = time.monotonic()
        urls, data, event, total = [], [], '', 0

        def consume():
            nonlocal event
            if not data:
                return
            text = '\n'.join(data)
            data.clear()
            try:
                value = json.loads(text)
            except ValueError:
                raise ProviderError('豆包网页返回了无法解析的流式事件；未重新提交') from None
            trace['parsed_events'] += 1
            if isinstance(value, dict):
                failure = response_error(value, {'headers':headers})
                if failure:
                    raise ProviderError(failure)
            if event == 'SSE_REPLY_END':
                trace['reply_end'] = True
            for item in extract_images(value):
                if item not in urls:
                    urls.append(item)
            event = ''

        try:
            payload = json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
            # Never retry a generation POST or silently switch to Android on failure.
            with requests.post(url, headers=headers, data=payload, stream=True,
                               timeout=(15, timeout), allow_redirects=False) as response:
                trace['http_status'] = response.status_code
                if response.status_code != 200:
                    raise ProviderError(f'豆包网页请求失败 HTTP {response.status_code}')
                response.encoding = 'utf-8'
                for line in response.iter_lines(decode_unicode=True):
                    total += len(line)
                    if total > 16*1024*1024 or time.monotonic()-started > timeout:
                        raise ProviderError('豆包网页响应超时或超限，原请求可能已提交；未重新发送')
                    if not line:
                        consume()
                    elif line.startswith('event:'):
                        event = line[6:].strip()
                    elif line.startswith('data:'):
                        data.append(line[5:].lstrip())
                    elif line.startswith('{'):
                        data.append(line)
                consume()
        except requests.RequestException:
            raise ProviderError('豆包网页网络请求失败，原请求可能已提交；未重新发送') from None
        if not urls:
            raise ProviderError(f'豆包网页响应结束但没有生成图片（事件 {trace["parsed_events"]}）；未重新提交')
        if not trace['reply_end']:
            raise ProviderError('豆包网页流未完整结束，不能确认生成完成；未重新提交')
        return urls
