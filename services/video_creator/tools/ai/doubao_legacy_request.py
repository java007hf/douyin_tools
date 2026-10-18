"""Text request compatibility with the user's original SimpleDoubaoHandler.

Opaque header fragments are read from the private template, never embedded here.
This reproduces timestamp/trace updates; it does not renew authentication tokens.
"""
import copy
import json
import random
import time
import uuid


def dynamic_fields(headers):
    now = int(time.time())
    millis = int(time.time() * 1000)
    trace = lambda: ''.join(random.choice('0123456789abcdef') for _ in range(32))
    source = {key.lower(): value for key, value in headers.items()}
    auth = str(source.get('x-bd-auth', '')).split('|')
    if len(auth) == 4:
        auth[2] = str(now)
    layer = str(source.get('x-bd-layer-auth', '')).rsplit('-', 1)[0]
    dsa = str(source.get('x-dsa-trace-id', ''))[10:]
    flow = str(source.get('x-flow-trace', '')).split('-')
    updates = {
        'x-khronos': str(now),
        'x-bd-auth': '|'.join(auth),
        'x-bd-layer-auth': f'{layer}-{now}',
        'x-ss-birth': f'{now}.072',
        'x-ss-req-ticket': str(millis + random.randint(100, 999)),
        'x-dsa-trace-id': f'{now}{dsa}',
        'x-flow-trace': f'{"-".join(flow[:2])}-{trace()}',
        'x-request-id': trace(),
        'x-tt-trace-id': f'00-{trace()}-{trace()[:16]}-00',
    }
    dynamic = {key: updates[key.lower()] for key in headers if key.lower() in updates}
    query = {'_rticket': str(int(time.time() * 1000)) + str(random.randint(1000, 9999)),
             'iid': str(random.randint(100000000000000, 999999999999999))}
    return dynamic, query


def build_legacy_request(config, prompt):
    headers = dict(config.get('headers', {}))
    dynamic, _ = dynamic_fields(headers)
    body = copy.deepcopy(config['body'])
    message = body['uplink_body']['send_message_body']
    identity = str(uuid.uuid4())
    body['sequence_id'] = message['local_message_id'] = identity
    message['unique_key'] = str(uuid.uuid4())
    # Keep additional model-specific content fields while updating legacy text.
    content = json.loads(message['content'])
    content.update(im_cmd=-1, text=prompt)
    message['content'] = json.dumps(content, ensure_ascii=False)
    message['create_time'] = int(time.time())
    message.setdefault('ext', {})['create_time_ms'] = str(message['create_time'] * 1000)
    # The original build_url calls update_dynamic_fields a second time.
    _, query_updates = dynamic_fields(headers)
    query = {**config.get('query', {}), **query_updates}
    url = config['base_url'].rstrip('/') + config.get('endpoint', '/im/sse/send/message')
    url += '?' + '&'.join(f'{key}={value}' for key, value in query.items())
    headers.update(dynamic)
    if not any(key.lower() == 'content-type' for key in headers):
        headers['Content-Type'] = 'application/json; encoding=utf-8'
    return url, headers, {}, body
