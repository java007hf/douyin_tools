#!/usr/bin/env python3
"""Private model/provider administration tab."""
from __future__ import annotations
import argparse, http.server, json, os, sys
from pathlib import Path
from urllib import request
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.video_creator.tools.ai.config_store import ProviderConfigStore

HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>后台控制</title><style>body{margin:0;background:#f7f8fa;color:#182230;font:14px Segoe UI,Microsoft YaHei,Arial,sans-serif}main{max-width:1080px;margin:auto;padding:28px}.layout{display:grid;grid-template-columns:190px 1fr;gap:18px}.nav,.panel{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:16px}.nav button{display:block;width:100%;margin:0 0 8px;text-align:left;background:#fff;color:#344054;border:1px solid #e4e7ec}.nav button.active{background:#0f766e;color:#fff}.panel{display:none}.panel.active{display:block}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}label{display:block;color:#475467}input,select{width:100%;box-sizing:border-box;margin-top:5px;padding:10px;border:1px solid #cfd6e0;border-radius:6px;font:inherit}button{padding:10px 14px;border:0;border-radius:6px;background:#0f766e;color:#fff;font:inherit}.status{margin-top:12px;color:#667085;white-space:pre-wrap}@media(max-width:700px){main{padding:16px}.layout{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}</style></head><body><main><h1>后台控制</h1><p>分别配置 MiniMax、Seedance 和本地 ComfyUI。</p><div class="layout"><nav class="nav"><button class="active" data-panel="minimax">MiniMax</button><button data-panel="seedance">Seedance</button><button data-panel="comfy">ComfyUI 模型</button></nav><div><section id="minimax" class="panel active"></section><section id="seedance" class="panel"></section><section id="comfy" class="panel"><h2>本地 ComfyUI 模型</h2><div id="comfy-list" class="status">正在读取...</div></section></div></div></main><script>
document.head.insertAdjacentHTML('beforeend','<style>form button{margin-top:16px}</style>');const panels=document.querySelectorAll('.panel');document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-panel]').forEach(x=>x.classList.toggle('active',x===b));panels.forEach(x=>x.classList.toggle('active',x.id===b.dataset.panel))});
const fields=p=>`<h2>${p==='minimax'?'MiniMax':'Seedance'} 配置</h2><form data-provider="${p}"><input type="hidden" name="id"><div class="grid"><label>配置名称<input name="name" required></label><label>模型版本<select name="model"></select></label><label>API 地址<input name="base_url"></label><label>API Key<input name="api_key" type="password" placeholder="留空表示保持原值"></label><label>Token<input name="token" type="password" placeholder="留空表示保持原值"></label><label>默认比例<select name="ratio"><option>adaptive</option><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>3:4</option></select></label></div><button>保存配置</button><div class="status list"></div></form>`;
const cleanFields=p=>fields(p).replace(/<label>配置名称.*?<\\/label>/,'').replace(/<label>模型版本.*?<\\/label>/,'').replace(new RegExp('<label>[^<]*<input name="base_url"[^>]*></label>'),`<input name="base_url" type="hidden" value="${p==='minimax'?'https://api.minimaxi.com':'https://ark.cn-beijing.volces.com/api/v3'}">`).replace(/<label>默认比例.*?<\\/label>/,'');
function showDefaults(){document.querySelector('#minimax').innerHTML=cleanFields('minimax');document.querySelector('#seedance').innerHTML=cleanFields('seedance');document.querySelector('#minimax [name=base_url]').value='https://api.minimaxi.com';document.querySelector('#seedance [name=base_url]').value='https://ark.cn-beijing.volces.com/api/v3'}
showDefaults();
async function init(){const models=await (await fetch('/api/models')).json();document.querySelector('#minimax').innerHTML=cleanFields('minimax');document.querySelector('#seedance').innerHTML=cleanFields('seedance');document.querySelectorAll('form[data-provider]').forEach(f=>{const p=f.dataset.provider,s=f.querySelector('[name=model]');(models[p]||[]).forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;s.append(o)});f.onsubmit=async e=>{e.preventDefault();const v=Object.fromEntries(new FormData(f));v.provider=p;v.enabled=true;const r=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});f.querySelector('.list').textContent=r.ok?'已保存，凭据已脱敏':'保存失败';load()}});document.querySelector('#minimax [name=base_url]').value='https://api.minimaxi.com';document.querySelector('#seedance [name=base_url]').value='https://ark.cn-beijing.volces.com/api/v3';document.querySelector('#comfy-list').textContent=(models.comfy||[]).join(' | ')||'未发现模型';load()}
async function load(){const d=await (await fetch('/api/providers')).json();(d.providers||[]).forEach(v=>{const f=document.querySelector(`form[data-provider="${v.provider}"]`);if(!f)return;Object.keys(v).forEach(k=>{const e=f.elements[k];if(e&&v[k])e.value=v[k]})});document.querySelectorAll('.list').forEach(x=>x.textContent=(d.providers||[]).map(v=>`${v.name||v.provider} · ${v.model||'未设置'} · ${v.enabled===false?'已停用':'已启用'} · 凭据已脱敏`).join(' | ')||'暂无配置')}
init();</script></body></html>'''

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): return
    def send_body(self, status, content_type, body):
        body=body.encode() if isinstance(body,str) else body; self.send_response(status); self.send_header('content-type',content_type); self.send_header('content-length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path in ('/','/index.html'): self.send_body(200,'text/html; charset=utf-8',HTML); return
        if self.path=='/api/providers': self.send_body(200,'application/json; charset=utf-8',json.dumps({'providers':self.server.store.list_public()},ensure_ascii=False)); return
        if self.path=='/api/models':
            models={'minimax':['MiniMax-Hailuo-2.3','MiniMax-Hailuo-2.3-Fast','MiniMax-Hailuo-02'],'seedance':['doubao-seedance-1-0-pro-250528','doubao-seedance-1-5-pro-251215','doubao-seedance-2-0-pro','doubao-seedance-2-0-fast'],'comfy':[]}
            try:
                info=json.loads(request.urlopen(self.server.comfy_url+'/object_info',timeout=10).read())
                for node in ('UNETLoader','CheckpointLoaderSimple','CLIPLoader'):
                    required=info.get(node,{}).get('input',{}).get('required',{})
                    for field in ('unet_name','ckpt_name','clip_name'):
                        values=required.get(field,[[]])[0]
                        if isinstance(values,list): models['comfy'].extend(str(x) for x in values)
            except Exception: pass
            models['comfy']=list(dict.fromkeys(models['comfy'])); self.send_body(200,'application/json; charset=utf-8',json.dumps(models,ensure_ascii=False)); return
        self.send_body(404,'text/plain','Not found')
    def do_POST(self):
        if self.path!='/api/providers': self.send_body(404,'text/plain','Not found'); return
        try:
            values=json.loads(self.rfile.read(int(self.headers.get('content-length','0')))); self.send_body(200,'application/json; charset=utf-8',json.dumps({'provider':self.server.store.save(values)},ensure_ascii=False))
        except Exception as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)}))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8103); p.add_argument('--cache-dir',type=Path,default=Path('cache/video_creator')); a=p.parse_args(); a.cache_dir.mkdir(parents=True,exist_ok=True); s=http.server.ThreadingHTTPServer((a.host,a.port),Handler); s.store=ProviderConfigStore(a.cache_dir.resolve()/'provider_configs.json'); s.comfy_url=os.getenv('COMFYUI_URL','http://127.0.0.1:8188'); print(f'admin listening=http://{a.host}:{a.port}',flush=True); s.serve_forever()
if __name__=='__main__': main()
