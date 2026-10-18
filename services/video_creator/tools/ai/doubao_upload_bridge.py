"""Loopback diagnostic bridge: native Doubao SDK signs; Python sends file bytes.

The service calls upload_references with persistent task files. The extension
selects supplied images in Doubao and keeps signing/commit in the browser.
This tool never submits any image/video generation request itself.
"""
from __future__ import annotations
import argparse
import base64
import http.server
import json
import threading
import time
import uuid
from urllib.parse import urlsplit
import requests
from services.core.storage import service_store

MAX_BYTES = 20 * 1024 * 1024
UPLOAD_HOSTS = {'tos-d-ct-lf.snssdk.com', 'tos-hl-x.snssdk.com'}

def upload_file(payload, session=requests, allowed_hosts=None):
    url = payload.get('url','')
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.hostname not in (allowed_hosts if allowed_hosts is not None else UPLOAD_HOSTS)
            or parsed.port not in (None,443) or parsed.username or parsed.password
            or not parsed.path.startswith('/upload/v1/tos-cn-i-a9rns2rl98/')
            or parsed.query or parsed.fragment):
        raise ValueError('Upload destination is not a captured Doubao storage endpoint')
    data = base64.b64decode(payload.get('data',''),validate=True)
    if not data or len(data)>MAX_BYTES: raise ValueError('Image size must be 1 byte to 20 MiB')
    # Forward only upload protocol headers; never send website cookies to storage.
    headers = {k:v for k,v in payload.get('headers',{}).items()
               if k.lower() in {'authorization','content-crc32','content-type','content-disposition','x-storage-u'}}
    if not all(isinstance(v,str) and '\r' not in v and '\n' not in v for v in headers.values()):
        raise ValueError('Invalid upload headers')
    # No retries: a connection failure may mean the bytes were already accepted.
    response = session.post(url,headers=headers,data=data,timeout=(15,90),allow_redirects=False)
    if 300<=response.status_code<400: raise ValueError('Upload redirect refused')
    if len(response.content)>1024*1024: raise ValueError('Upload response exceeds limit')
    return {'status':response.status_code,'text':response.text,
            'content_type':response.headers.get('Content-Type','application/json')}

def serve(port=18767,timeout=180,expected=1,image=None,progress=None,store_dir=None):
    report={'id':uuid.uuid4().hex,'state':'waiting','events':[],'uploaded':0,'committed':0}
    finished=threading.Event();lock=threading.Lock()
    allowed_hosts=set(UPLOAD_HOSTS)
    committed_uris=set()
    commands=[];delivered=0
    if image:
        import mimetypes
        from pathlib import Path
        for item in image if isinstance(image,list) else [image]:
            source=Path(item)
            data=source.read_bytes()
            if not data or len(data)>MAX_BYTES:raise ValueError('Invalid reference image size')
            commands.append({'name':source.name,'mime':mimetypes.guess_type(source.name)[0] or 'image/png',
                             'data':base64.b64encode(data).decode()})
    root=(store_dir or service_store('video_creator'))/'doubao_web'/'upload_verification'/report['id']
    root.mkdir(parents=True)
    def save():
        (root/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    save()
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args): pass  # Requests can contain ephemeral credentials.
        def send(self,status,value):
            data=json.dumps(value).encode();self.send_response(status)
            self.send_header('Content-Type','application/json');self.send_header('Cache-Control','no-store')
            self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
        def do_POST(self):
            nonlocal delivered
            origin=self.headers.get('Origin','')
            if not origin.startswith('chrome-extension://'):
                self.send(403,{'error':'Extension origin required'});return
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<MAX_BYTES*2:raise ValueError('Invalid request size')
                value=json.loads(self.rfile.read(length))
                if self.path=='/command':
                    with lock:
                        report['extension_polls']=report.get('extension_polls',0)+1
                        report['extension_version']=str(value.get('version',''))[:30]
                        report['extension_protocol']=value.get('protocol')
                        save()
                    if value.get('protocol')!=8:
                        self.send(200,{'image':None,'required_protocol':8});return
                    with lock:
                        value=None
                        if commands and report['committed']>=delivered:
                            value=commands.pop(0);delivered+=1
                            report['events'].append({'stage':'reference_dispatched','index':delivered});save()
                    self.send(200,{'image':value})
                elif self.path=='/upload':
                    result=upload_file(value,allowed_hosts=allowed_hosts)
                    with lock:
                        report['uploaded']+=1
                        report['events'].append({'stage':'python_upload','host':urlsplit(value['url']).hostname,'http_status':result['status']});save()
                    self.send(200,result)
                elif self.path=='/event':
                    stage=value.get('stage')
                    if stage not in {'apply','commit','bridge_error','reference_selected','bridge_ready','upload_route'}:raise ValueError('Unknown stage')
                    # Persist only status and confirmed reusable image URIs, never signed URLs/headers.
                    uris=[u for u in value.get('uris',[]) if isinstance(u,str) and u.startswith('tos-cn-i-a9rns2rl98/') and '?' not in u][:10]
                    with lock:
                        event={'stage':stage,'ok':value.get('ok') is True,'uris':uris}
                        if stage=='apply':
                            hosts=[host for host in value.get('hosts',[]) if isinstance(host,str) and any(host.endswith('.'+domain) for domain in ('snssdk.com','doubao.com','byteimg.com','bytedance.com','bytedancevod.com')) and urlsplit('https://'+host).hostname==host]
                            allowed_hosts.update(hosts);event['hosts']=hosts
                            event['observed_hosts']=[host for host in value.get('observed_hosts',[]) if isinstance(host,str) and urlsplit('https://'+host).hostname==host][:10]
                        if stage=='upload_route':
                            event.update(host=str(value.get('host',''))[:200],transport=value.get('transport'),bridged=value.get('bridged') is True)
                        if stage=='bridge_error':
                            event['reason']=value.get('reason') if value.get('reason') in {'Page bridge not ready','Cannot uniquely identify image upload input','Reference selection failed'} else 'Upload transport failed'
                            event['inputs']=[{k:x.get(k) for k in ('accept','multiple','disabled','visible')} for x in value.get('inputs',[]) if isinstance(x,dict)][:20]
                        report['events'].append(event)
                        if stage=='commit' and value.get('ok') is True:
                            committed_uris.update(uris)
                            report['committed']=len(committed_uris)
                            if report['committed']>=expected:
                                report['state']='done' if report['uploaded']>=expected else 'transport_bypassed'
                                finished.set()
                        if stage=='bridge_error':report['state']='error';finished.set()
                        save()
                    if progress:progress({'uploaded':report['uploaded'],'committed':report['committed'],'expected':expected})
                    self.send(200,{'ok':True})
                else:self.send(404,{'error':'Unknown endpoint'})
            except Exception:
                with lock:report['state']='error';save();finished.set()
                self.send(400,{'error':'Upload bridge failed; request was not retried'})
    server=http.server.ThreadingHTTPServer(('127.0.0.1',port),Handler)
    worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
    print('Ready: enable Doubao Upload Bridge; the supplied image will be selected automatically.' if image else 'Ready: enable Doubao Upload Bridge, then choose a reference image on Doubao.',flush=True)
    try:
        finished.wait(timeout)
        with lock:
            if report['state']=='waiting':report['state']='timeout'
            save()
    finally:server.shutdown();server.server_close()
    print(json.dumps({'state':report['state'],'uploaded':report['uploaded'],'committed':report['committed'],'report':str(root/'verification.json')}),flush=True)
    return report

_upload_lock=threading.Lock()

def upload_references(paths, *, store_dir=None, progress=None, timeout=180):
    """Stable tool interface shared by direct forms and Workflow generation."""
    from PIL import Image
    from .providers import ProviderError
    if not 1<=len(paths)<=2:raise ProviderError('豆包参考图目前支持 1–2 张，请减少参考素材')
    # Validate files before opening the bridge or touching the logged-in page.
    sizes=[]
    for path in paths:
        with Image.open(path) as image:
            image.load();sizes.append((image.width,image.height,image.format.lower()))
    with _upload_lock:
        try:report=serve(timeout=timeout,expected=len(paths),image=list(paths),progress=progress,store_dir=store_dir)
        except OSError:raise ProviderError('豆包上传桥接端口被占用，请先停止独立测试脚本') from None
    if report['state']!='done':
        reason=next((e.get('reason') for e in reversed(report['events']) if e['stage']=='bridge_error'),None)
        detail={'Cannot uniquely identify image upload input':'豆包页面未找到唯一可用的图片上传入口',
                'Page bridge not ready':'豆包页面脚本未就绪',
                'Reference selection failed':'无法连接豆包图像创作页的上传组件'}.get(reason,'请确认 Chrome 豆包页已登录且上传插件已连接')
        raise ProviderError('豆包参考图上传未完成（'+report['state']+'）：'+detail+'。未提交生成请求')
    uris=list(dict.fromkeys(uri for event in report['events'] if event['stage']=='commit' and event.get('ok') for uri in event['uris']))
    if len(uris)!=len(paths):raise ProviderError('豆包上传图片数量不匹配，未提交生成请求')
    return [{'uri':uri,'name':path.name,'width':size[0],'height':size[1],'format':size[2]}
            for path,uri,size in zip(paths,uris,sizes)],report['id']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=18767)
    parser.add_argument('--timeout',type=int,default=180);parser.add_argument('--expected',type=int,default=1)
    parser.add_argument('--image',action='append',help='Local reference image; repeat for sequential uploads')
    args=parser.parse_args();serve(args.port,args.timeout,args.expected,args.image)
