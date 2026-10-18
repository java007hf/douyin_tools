#!/usr/bin/env python3
"""Private model/provider administration tab."""
from __future__ import annotations
import argparse, html, http.server, json, os, sys
from pathlib import Path
from urllib import request, error
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.video_creator.tools.ai.config_store import ProviderConfigStore
from services.core.storage import service_store
from services.video_creator.tools.ai.mock_doubao_config import MockDoubaoConfigStore
from services.video_creator.workflow.prompts import DEFAULT_REVIEW_PROMPT, DEFAULT_STORYBOARD_PROMPT

class CloudinaryConfigStore:
    def __init__(self, path: Path): self.path, self.lock = path, __import__('threading').Lock(); self.path.parent.mkdir(parents=True, exist_ok=True)
    def get(self):
        if not self.path.is_file(): return {}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('access_key_secret'): data['access_key_secret']='********'
            return data
        except (OSError, json.JSONDecodeError): return {}
    def save(self, values):
        data={"cloud_name":str(values.get("cloud_name","")).strip(),"upload_preset":str(values.get("upload_preset","")).strip()}
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'); return data

class StorageConfigStore:
    def __init__(self, path: Path): self.path, self.lock = path, __import__('threading').Lock(); self.path.parent.mkdir(parents=True, exist_ok=True)
    def get(self):
        if not self.path.is_file(): return {}
        try:
            data=json.loads(self.path.read_text(encoding='utf-8'))
            if data.get('access_key_secret'): data['access_key_secret']='********'
            return data
        except (OSError, json.JSONDecodeError): return {}
    def save(self, values):
        data={k:str(values.get(k,'' )).strip() for k in ('provider','endpoint','bucket','access_key_id','access_key_secret','public_base_url','cloud_name','upload_preset')}
        if data['provider'] not in {'oss','cloudinary'}: data['provider']='oss'
        try: old=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError): old={}
        if data['access_key_secret']=='********': data['access_key_secret']=old.get('access_key_secret','')
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8'); return {**data,'access_key_secret':'********' if data['access_key_secret'] else ''}

HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>后台控制</title><style>body{margin:0;background:#f7f8fa;color:#182230;font:14px Segoe UI,Microsoft YaHei,Arial,sans-serif}main{max-width:1080px;margin:auto;padding:28px}.layout{display:grid;grid-template-columns:190px 1fr;gap:18px}.nav,.panel{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:16px}.nav button{display:block;width:100%;margin:0 0 8px;text-align:left;background:#fff;color:#344054;border:1px solid #e4e7ec}.nav button.active{background:#0f766e;color:#fff}.panel{display:none}.panel.active{display:block}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}label{display:block;color:#475467}input,select{width:100%;box-sizing:border-box;margin-top:5px;padding:10px;border:1px solid #cfd6e0;border-radius:6px;font:inherit}button{padding:10px 14px;border:0;border-radius:6px;background:#0f766e;color:#fff;font:inherit}.status{margin-top:12px;color:#667085;white-space:pre-wrap}@media(max-width:700px){main{padding:16px}.layout{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}</style></head><body><main><h1>后台控制</h1><p>分别配置 MiniMax、Seedance 和本地 ComfyUI。</p><div class="layout"><nav class="nav"><button class="active" data-panel="minimax">MiniMax</button><button data-panel="seedance">Seedance</button><button data-panel="comfy">ComfyUI 模型</button></nav><div><section id="minimax" class="panel active"></section><section id="seedance" class="panel"></section><section id="comfy" class="panel"><h2>本地 ComfyUI 模型</h2><div id="comfy-list" class="status">正在读取...</div></section></div></div></main><script>
document.head.insertAdjacentHTML('beforeend','<style>form button{margin-top:16px}</style>');const panels=document.querySelectorAll('.panel');document.querySelectorAll('[data-panel]').forEach(b=>b.onclick=()=>{document.querySelectorAll('[data-panel]').forEach(x=>x.classList.toggle('active',x===b));panels.forEach(x=>x.classList.toggle('active',x.id===b.dataset.panel))});
const fields=p=>`<h2>${p==='minimax'?'MiniMax':'Seedance'} 配置</h2><form data-provider="${p}"><input type="hidden" name="id"><div class="grid"><label>配置名称<input name="name" required></label><label>模型版本<select name="model"></select></label><label>API 地址<input name="base_url"></label><label>API Key<input name="api_key" type="password" placeholder="留空表示保持原值"></label><label>Token<input name="token" type="password" placeholder="留空表示保持原值"></label><label>默认比例<select name="ratio"><option>adaptive</option><option>16:9</option><option>9:16</option><option>1:1</option><option>4:3</option><option>3:4</option></select></label></div><button>保存配置</button><div class="status list"></div></form>`;
const cleanFields=p=>fields(p).replace(/<label>配置名称.*?<\\/label>/,'').replace(/<label>模型版本.*?<\\/label>/,'').replace(new RegExp('<label>[^<]*<input name="base_url"[^>]*></label>'),`<input name="base_url" type="hidden" value="${p==='minimax'?'https://api.minimaxi.com':'https://ark.cn-beijing.volces.com/api/v3'}">`).replace(/<label>Token.*?<\\/label>/,'').replace(/<label>默认比例.*?<\\/label>/,'');
function showDefaults(){document.querySelector('#minimax').innerHTML=cleanFields('minimax');document.querySelector('#seedance').innerHTML=cleanFields('seedance');document.querySelector('#minimax [name=base_url]').value='https://api.minimaxi.com';document.querySelector('#seedance [name=base_url]').value='https://ark.cn-beijing.volces.com/api/v3'}
async function saveProvider(e,f){e.preventDefault();const p=f.dataset.provider;const v=Object.fromEntries(new FormData(f));v.provider=p;v.enabled=true;try{const r=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});f.querySelector('.list').textContent=r.ok?'已保存，凭据已脱敏':'保存失败';if(r.ok)load()}catch(_){f.querySelector('.list').textContent='保存失败'}return false}
document.addEventListener('submit',e=>saveProvider(e,e.target),true);
async function refreshStatus(){try{const d=await (await fetch('/api/providers')).json();const text=(d.providers||[]).map(v=>`${v.provider} · ${v.api_key==='********'?'API Key 已配置':'API Key 未配置'} · ${v.enabled===false?'已停用':'已启用'}`).join(' | ')||'暂无配置';document.querySelectorAll('.list').forEach(x=>x.textContent=text)}catch(_){}}
setInterval(refreshStatus,1000);
showDefaults();
setTimeout(()=>{const form=document.querySelector('#storage-form');if(!form)return;const grid=form.querySelector('.grid');[['cloud_name','Cloud Name','例如 demo'],['upload_preset','Upload Preset','Unsigned Upload Preset']].forEach(([name,label,placeholder])=>{const wrap=document.createElement('label');wrap.dataset.cloudinaryField='true';wrap.textContent=label;const input=document.createElement('input');input.name=name;input.placeholder=placeholder;wrap.append(input);grid.append(wrap)});const toggle=()=>form.querySelectorAll('[data-cloudinary-field]').forEach(x=>x.style.display=form.elements.provider.value==='cloudinary'?'block':'none');form.elements.provider.onchange=toggle;toggle();fetch('/api/storage').then(r=>r.json()).then(v=>Object.keys(v).forEach(k=>{if(form.elements[k])form.elements[k].value=k==='access_key_secret'&&v[k]?'********':v[k]}))},0);
setTimeout(()=>{document.querySelectorAll('.nav button').forEach(x=>{if(x.textContent==='Cloudinary')x.remove()});document.querySelectorAll('.panel').forEach(x=>{if(x.textContent.includes('Cloudinary 参考素材'))x.remove()})},0);
document.addEventListener('click',e=>{if(e.target.matches('.nav button')&&e.target.dataset.panel!=='storage'){setTimeout(()=>{const panel=document.querySelector('#storage');if(panel){panel.classList.remove('active');panel.style.display='none'}},0)}},true);
document.addEventListener('click',e=>{if(e.target.matches('.nav button')&&e.target.dataset.panel!=='storage'&&e.target.dataset.panel!=='cloudinary'){setTimeout(()=>{const panel=document.querySelector('#'+e.target.dataset.panel);if(panel)panel.style.display='block'},0)}},true);
const storageButton=document.createElement('button');storageButton.textContent='素材存储';storageButton.dataset.panel='storage';document.querySelector('.nav').append(storageButton);storageButton.onclick=()=>{document.querySelectorAll('.panel').forEach(x=>{x.classList.remove('active');x.style.display='none'});document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));storageButton.classList.add('active');const panel=document.querySelector('#storage');panel.classList.add('active');panel.style.display='block'};
const storagePanel=document.createElement('section');storagePanel.className='panel';storagePanel.id='storage';storagePanel.style.display='none';storagePanel.innerHTML='<h2>素材存储</h2><form id="storage-form"><div class="grid"><label>默认存储<select name="provider"><option value="oss">阿里云 OSS</option><option value="cloudinary">Cloudinary</option></select></label><label>公网访问地址<input name="public_base_url" placeholder="https://cdn.example.com"></label><label>OSS Endpoint<input name="endpoint" placeholder="https://oss-cn-hangzhou.aliyuncs.com"></label><label>Bucket<input name="bucket"></label><label>AccessKey ID<input name="access_key_id"></label><label>AccessKey Secret<input name="access_key_secret" type="password" placeholder="留空保持原值"></label></div><button>保存素材存储配置</button><div class="status storage-status"></div></form>';document.querySelector('.layout>div').append(storagePanel);const storageForm=storagePanel.querySelector('form');storageForm.onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(storageForm)))});storagePanel.querySelector('.storage-status').textContent=r.ok?'已保存':'保存失败'};fetch('/api/storage').then(r=>r.json()).then(v=>Object.keys(v).forEach(k=>{if(storageForm.elements[k])storageForm.elements[k].value=k==='access_key_secret'&&v[k]?'********':v[k]}));
const cloudButton=document.createElement('button');cloudButton.textContent='Cloudinary';cloudButton.dataset.panel='cloudinary';document.querySelector('.nav').append(cloudButton);cloudButton.onclick=()=>{document.querySelectorAll('.panel').forEach(x=>{x.classList.remove('active');x.style.display='none'});document.querySelectorAll('.nav button').forEach(x=>x.classList.remove('active'));cloudButton.classList.add('active');const panel=document.querySelector('#cloudinary');panel.classList.add('active');panel.style.display='block'};document.querySelectorAll('.nav button').forEach(button=>{if(button!==cloudButton)button.addEventListener('click',()=>{const panel=document.querySelector('#cloudinary');if(panel){panel.classList.remove('active');panel.style.display='none'}})});setTimeout(()=>{const panel=document.querySelector('.layout>div>section:last-child');if(panel){panel.id='cloudinary';panel.className='panel';panel.style.display='none'}},0);
const cloudPanel=document.createElement('section');cloudPanel.className='panel active';cloudPanel.style.display='block';cloudPanel.innerHTML='<h2>Cloudinary 参考素材</h2><form id="cloudinary-form"><div class="grid"><label>Cloud Name<input name="cloud_name" placeholder="例如 demo"></label><label>Upload Preset<input name="upload_preset" placeholder="Unsigned Upload Preset"></label></div><button>保存 Cloudinary 配置</button><div class="status cloud-status"></div></form>';document.querySelector('.layout>div').append(cloudPanel);const cloudForm=cloudPanel.querySelector('form');cloudForm.onsubmit=async e=>{e.preventDefault();const r=await fetch('/api/cloudinary',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(cloudForm)))});cloudPanel.querySelector('.cloud-status').textContent=r.ok?'已保存':'保存失败'};fetch('/api/cloudinary').then(r=>r.json()).then(v=>Object.keys(v).forEach(k=>{if(cloudForm.elements[k])cloudForm.elements[k].value=v[k] }));
async function init(){const models=await (await fetch('/api/models')).json();document.querySelector('#minimax').innerHTML=cleanFields('minimax');document.querySelector('#seedance').innerHTML=cleanFields('seedance');document.querySelectorAll('form[data-provider]').forEach(f=>{const p=f.dataset.provider,s=f.querySelector('[name=model]');(models[p]||[]).forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;s.append(o)});f.onsubmit=async e=>{e.preventDefault();const v=Object.fromEntries(new FormData(f));v.provider=p;v.enabled=true;const r=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(v)});f.querySelector('.list').textContent=r.ok?'已保存，凭据已脱敏':'保存失败';load()}});document.querySelector('#minimax [name=base_url]').value='https://api.minimaxi.com';document.querySelector('#seedance [name=base_url]').value='https://ark.cn-beijing.volces.com/api/v3';document.querySelector('#comfy-list').textContent=(models.comfy||[]).join(' | ')||'未发现模型';load()}
async function load(){const d=await (await fetch('/api/providers')).json();(d.providers||[]).forEach(v=>{const f=document.querySelector(`form[data-provider="${v.provider}"]`);if(!f)return;const values={...v,api_key:v.api_key||v.token};Object.keys(values).forEach(k=>{const e=f.elements[k];if(e&&values[k])e.value=values[k]})});document.querySelectorAll('.list').forEach(x=>x.textContent=(d.providers||[]).map(v=>`${v.name||v.provider} · ${v.model||'未设置'} · ${v.enabled===false?'已停用':'已启用'} · 凭据已脱敏`).join(' | ')||'暂无配置')}
init();</script></body></html>'''

FIXED_HTML = '''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>后台控制</title><style>body{margin:0;background:#f7f8fa;color:#182230;font:14px Segoe UI,Microsoft YaHei,Arial,sans-serif}main{max-width:1080px;margin:auto;padding:28px}.layout{display:grid;grid-template-columns:190px 1fr;gap:18px}.nav,.panel{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:16px}.nav button{display:block;width:100%;margin:0 0 8px;text-align:left;background:#fff;color:#344054;border:1px solid #e4e7ec}.nav button.active{background:#0f766e;color:#fff}.panel{display:none}.panel.active{display:block}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}label{display:block;color:#475467}input,select{width:100%;box-sizing:border-box;margin-top:5px;padding:10px;border:1px solid #cfd6e0;border-radius:6px;font:inherit}button{padding:10px 14px;border:0;border-radius:6px;background:#0f766e;color:#fff;font:inherit}.status{margin-top:12px;color:#667085;white-space:pre-wrap}@media(max-width:700px){main{padding:16px}.layout{grid-template-columns:1fr}.grid{grid-template-columns:1fr}}</style></head><body><main><h1>后台控制</h1><div class="layout"><nav class="nav"><button class="active" data-panel="minimax">MiniMax</button><button data-panel="seedance">Seedance</button><button data-panel="storage">素材存储</button><button data-panel="comfy">ComfyUI 模型</button></nav><div><section id="minimax" class="panel active"><h2>MiniMax 配置</h2><form data-provider="minimax"><label>API Key<input name="api_key" type="password" placeholder="留空表示保持原值"></label><button>保存配置</button><div class="status"></div></form></section><section id="seedance" class="panel"><h2>Seedance 配置</h2><form data-provider="seedance"><label>API Key<input name="api_key" type="password" placeholder="留空表示保持原值"></label><button>保存配置</button><div class="status"></div></form></section><section id="storage" class="panel"><h2>素材存储</h2><form id="storage-form"><div class="grid"><label>默认存储<select name="provider"><option value="oss">阿里云 OSS</option><option value="cloudinary">Cloudinary</option></select></label><label>公网访问地址<input name="public_base_url" placeholder="https://cdn.example.com"></label><label data-oss>OSS Endpoint<input name="endpoint" placeholder="https://oss-cn-hangzhou.aliyuncs.com"></label><label data-oss>Bucket<input name="bucket"></label><label data-oss>AccessKey ID<input name="access_key_id"></label><label data-oss>AccessKey Secret<input name="access_key_secret" type="password" placeholder="留空保持原值"></label><label data-cloud>Cloud Name<input name="cloud_name" placeholder="例如 demo"></label><label data-cloud>Upload Preset<input name="upload_preset" placeholder="Unsigned Upload Preset"></label></div><button>保存素材存储配置</button><div class="status"></div></form></section><section id="comfy" class="panel"><h2>本地 ComfyUI 模型</h2><div id="comfy-list" class="status">正在读取...</div></section></div></div></main><script>const panels=[...document.querySelectorAll('.panel')];document.querySelectorAll('[data-panel]').forEach(button=>button.onclick=()=>{document.querySelectorAll('[data-panel]').forEach(x=>x.classList.toggle('active',x===button));panels.forEach(x=>x.classList.toggle('active',x.id===button.dataset.panel))});async function saveProvider(event,form){event.preventDefault();const value=Object.fromEntries(new FormData(form));value.provider=form.dataset.provider;value.enabled=true;const response=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});form.querySelector('.status').textContent=response.ok?'已保存，凭据已脱敏':'保存失败';return false}document.querySelectorAll('[data-provider]').forEach(form=>form.onsubmit=e=>saveProvider(e,form));const storageForm=document.querySelector('#storage-form');const toggleStorage=()=>{const cloud=storageForm.elements.provider.value==='cloudinary';storageForm.querySelectorAll('[data-oss]').forEach(x=>x.style.display=cloud?'none':'block');storageForm.querySelectorAll('[data-cloud]').forEach(x=>x.style.display=cloud?'block':'none')};storageForm.elements.provider.onchange=toggleStorage;storageForm.onsubmit=async e=>{e.preventDefault();const response=await fetch('/api/storage',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(Object.fromEntries(new FormData(storageForm)))});storageForm.querySelector('.status').textContent=response.ok?'已保存':'保存失败'};fetch('/api/storage').then(r=>r.json()).then(value=>{Object.keys(value).forEach(key=>{if(storageForm.elements[key])storageForm.elements[key].value=key==='access_key_secret'&&value[key]?'********':value[key]});toggleStorage()});fetch('/api/models').then(r=>r.json()).then(value=>{document.querySelector('#comfy-list').textContent=(value.comfy||[]).join(' | ')||'未发现模型'});</script></body></html>'''
FIXED_HTML = FIXED_HTML.replace('button{padding:', '.panel form button{margin-top:16px}button{padding:').replace('保存素材存储配置', '保存配置')
FIXED_HTML = FIXED_HTML.replace('<button data-panel="comfy">ComfyUI 模型</button>', '<button data-panel="llm">LLM</button><button data-panel="comfy">ComfyUI 模型</button>')
FIXED_HTML = FIXED_HTML.replace('<section id="comfy" class="panel">', '<section id="llm" class="panel"><h2>LLM 配置</h2><form data-provider="llm"><label>API 地址<input name="base_url" value="https://api.openai.com/v1" placeholder="https://api.openai.com/v1"></label><label>模型<input name="model" value="gpt-4o-mini" placeholder="gpt-4o-mini"></label><label>API Key<input name="api_key" type="password" placeholder="只填写 Key，不要填写 Bearer 或 API 地址"></label><p class="status">火山方舟示例：API 地址填写 https://ark.cn-beijing.volces.com/api/v3，API Key 填 ARK_API_KEY 的实际值。</p><button>保存配置</button><div class="status"></div></form></section><section id="comfy" class="panel">')
FIXED_HTML = FIXED_HTML.replace('</script></body></html>', "fetch('/api/providers').then(r=>r.json()).then(data=>{const latest=new Map((data.providers||[]).map(v=>[v.provider,v]));latest.forEach(v=>{const form=[...document.querySelectorAll('form[data-provider]')].find(f=>f.dataset.provider===v.provider);if(!form)return;Object.entries(v).forEach(([key,value])=>{if(value!=null&&form.elements[key])form.elements[key].value=value})})});</script></body></html>")
FIXED_HTML = FIXED_HTML.replace('<form data-provider="minimax">', '<form data-provider="minimax"><input type="hidden" name="id">').replace('<form data-provider="seedance">', '<form data-provider="seedance"><input type="hidden" name="id">').replace('<form data-provider="llm">', '<form data-provider="llm"><input type="hidden" name="id">')
FIXED_HTML = FIXED_HTML.replace('<h2>LLM 配置</h2>', '<h2>生图&amp;视频 LLM</h2><p class="status">仅供普通生图和生视频页面的“AI辅助”提示词改善使用；AI视频不读取此配置。</p>')
FIXED_HTML = FIXED_HTML.replace('input,select{', 'input,select,textarea{').replace('font:inherit}button{', 'font:inherit}textarea{min-height:130px;resize:vertical}button{')
FIXED_HTML = FIXED_HTML.replace('</style></head>', '[name="storyboard_system_prompt"],[name="review_system_prompt"]{min-height:440px;line-height:1.6;font-family:Consolas,"Microsoft YaHei",monospace}</style></head>')
FIXED_HTML = FIXED_HTML.replace('<button data-panel="llm">LLM</button>', '<button data-panel="llm">生图&amp;视频 LLM</button><button data-panel="ai-video-agent">AI视频</button>')
FIXED_HTML = FIXED_HTML.replace('<section id="comfy" class="panel">', '''<section id="ai-video-agent" class="panel"><h2>AI视频配置</h2><p class="status">此处配置只供 AI 视频 Workflow 使用，不会影响普通生图、生视频及其提示词辅助。</p><form data-provider="ai_video_agent"><input type="hidden" name="id"><div class="grid"><label>Agent API 地址<input name="base_url" value="https://api.openai.com/v1" placeholder="OpenAI-compatible API 地址"></label><label>Agent 模型<input name="model" value="gpt-4o-mini" placeholder="用于故事板规划和审片"></label><label style="grid-column:1/-1">Agent API Key<input name="api_key" type="password" placeholder="留空表示保持原值"></label><label>默认生图 Provider<select name="default_image_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>默认生图模型<select name="default_image_model"><option value="">自动选择</option></select></label><label>默认视频 Provider<select name="default_video_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>默认视频模型<select name="default_video_model"><option value="">自动选择</option></select></label><label style="grid-column:1/-1">故事板规划 System Prompt<textarea name="storyboard_system_prompt" placeholder="负责理解意图并输出 continuity_bible、creative_intent 和 shots JSON"></textarea></label><label style="grid-column:1/-1">审片 System Prompt<textarea name="review_system_prompt" placeholder="要求输出 approved、summary、issues JSON"></textarea></label></div><h3>Agent 工具</h3><div class="status">plan_storyboard（Agent 模型） · generate_image · generate_video_t2v · generate_video_i2v · generate_video_r2v · extract_keyframes · review_video（待多模态 MCP 化） · merge_video</div><button>保存 AI视频配置</button><div class="status"></div></form></section><section id="comfy" class="panel">''')
FIXED_HTML = FIXED_HTML.replace('</script></body></html>', '''Promise.all([fetch('/api/providers').then(r=>r.json()),fetch('/api/models').then(r=>r.json())]).then(([providers,models])=>{const form=document.querySelector('form[data-provider="ai_video_agent"]');if(!form)return;(providers.providers||[]).filter(x=>['minimax','seedance'].includes(x.provider)&&x.enabled!==false).forEach(x=>{form.elements.default_video_provider_id.append(new Option(x.name||x.provider,x.id));form.elements.default_image_provider_id.append(new Option(x.name||x.provider,x.id))});[...(models.minimax||[]),...(models.seedance||[]),...(models.comfy||[]).filter(x=>x.toLowerCase().includes('minimax_h3'))].forEach(x=>form.elements.default_video_model.append(new Option(x,x)));[...(models.comfy||[]).filter(x=>!x.toLowerCase().includes('minimax_h3'))].forEach(x=>form.elements.default_image_model.append(new Option(x,x)));const saved=(providers.providers||[]).filter(x=>x.provider==='ai_video_agent').pop();if(saved)Object.entries(saved).forEach(([key,value])=>{if(value&&form.elements[key])form.elements[key].value=value})});</script></body></html>''')
FIXED_HTML = FIXED_HTML.replace('<textarea name="storyboard_system_prompt" placeholder="负责理解意图并输出 continuity_bible、creative_intent 和 shots JSON"></textarea>', '<textarea name="storyboard_system_prompt">'+html.escape(DEFAULT_STORYBOARD_PROMPT)+'</textarea>')
FIXED_HTML = FIXED_HTML.replace('<textarea name="review_system_prompt" placeholder="要求输出 approved、summary、issues JSON"></textarea>', '<textarea name="review_system_prompt">'+html.escape(DEFAULT_REVIEW_PROMPT)+'</textarea>')
FIXED_HTML = FIXED_HTML.replace('<label>默认视频 Provider<select name="default_video_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>默认视频模型<select name="default_video_model"><option value="">自动选择</option></select></label>', '<label>T2V Provider<select name="default_t2v_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>T2V 模型<select name="default_t2v_model"><option value="">自动选择</option></select></label><label>I2V Provider<select name="default_i2v_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>I2V 模型<select name="default_i2v_model"><option value="">自动选择</option></select></label><label>R2V Provider<select name="default_r2v_provider_id"><option value="local">本地 ComfyUI</option></select></label><label>R2V 模型<select name="default_r2v_model"><option value="">自动选择</option></select></label>')
FIXED_HTML = FIXED_HTML.replace('<label>R2V 模型<select name="default_r2v_model"><option value="">自动选择</option></select></label>', '<label>R2V 模型<select name="default_r2v_model"><option value="">自动选择</option></select></label><label>默认视频清晰度<select name="default_video_resolution"><option value="768p">768p 质量优先</option><option value="360p">360p 快速预览</option><option value="1080p">1080p（最多3秒/镜头）</option></select></label><label>默认画幅<select name="default_video_aspect"><option value="16:9">16:9</option><option value="9:16">9:16</option><option value="1:1">1:1</option></select></label><label>采样步数<input name="default_video_steps" type="number" min="8" max="40" value="24"></label>')
FIXED_HTML = FIXED_HTML.replace('form.elements.default_video_provider_id.append(new Option(x.name||x.provider,x.id));form.elements.default_image_provider_id.append(new Option(x.name||x.provider,x.id))', "['default_t2v_provider_id','default_i2v_provider_id','default_r2v_provider_id'].forEach(name=>form.elements[name].append(new Option(x.name||x.provider,x.id)));form.elements.default_image_provider_id.append(new Option(x.name||x.provider,x.id))")
FIXED_HTML = FIXED_HTML.replace("].forEach(x=>form.elements.default_video_model.append(new Option(x,x)));", "].forEach(x=>['default_t2v_model','default_i2v_model','default_r2v_model'].forEach(name=>form.elements[name].append(new Option(x,x))));")


FIXED_HTML = FIXED_HTML.replace('<button data-panel="comfy">ComfyUI 模型</button>', '<button data-panel="douyin-understanding">视频理解 LLM</button><button data-panel="comfy">ComfyUI 模型</button>')
FIXED_HTML = FIXED_HTML.replace('<section id="comfy" class="panel">', '<section id="douyin-understanding" class="panel"><h2>视频理解 LLM</h2><p class="status">独立用于下载作品后的画面识别、内容分类和摘要。必须保存配置后才能使用，不会读取其他 LLM 配置或使用代码默认模型。请选择支持图片输入的模型；音频由本地 Whisper 转写。</p><form data-provider="douyin_understanding"><input type="hidden" name="id"><label>接口类型<select name="api_format" required><option value="">请选择接口类型</option><option value="ollama">Ollama 原生接口</option><option value="openai">OpenAI 兼容接口</option></select></label><label>API 地址<input name="base_url" required placeholder="填写模型服务 API 地址"></label><label>视觉模型<input name="model" required placeholder="填写已安装或已开通的视觉模型名称"></label><label>上下文窗口（tokens）<input name="context_window" type="number" min="4096" max="262144" step="1" value="16384" required></label><p class="status">Ollama 按此数值设置上下文窗口。OpenAI 兼容服务的窗口由服务端决定，此项不会改变其模型上限。窗口越大，占用内存/显存越多；更大窗口不保证处理更快。</p><label>API Key<input name="api_key" type="password" placeholder="留空保持原值；本地 Ollama 可不填"></label><label>本地语音转写模型<select name="transcription_model"><option value="tiny">tiny（最快）</option><option value="base">base</option><option value="small" selected>small（默认）</option><option value="medium">medium</option><option value="large-v3">large-v3（精度优先）</option></select></label><p class="status">转写使用 CPU，不占用视觉模型的显存。首次使用需下载转写模型到 store/models/whisper。</p><button>保存视频理解配置</button><div class="status"></div></form></section><section id="comfy" class="panel">')

FIXED_HTML = FIXED_HTML.replace('<option value="large-v3">large-v3（精度优先）</option>', '<option value="large-v3">large-v3（精度优先）</option><option value="large-v3-turbo">large-v3-turbo（速度与精度兼顾）</option>')

MENTION_PANEL = '''<section id="mention-control" class="panel"><h2>@我自动回复</h2>
<p>服务默认启动监听。需要 Chrome 插件已启用、抖音已登录，并配置视频理解 LLM。</p>
<label>检查间隔（秒，30–600）<input id="mention-interval" type="number" min="30" max="600" value="60"></label>
<label style="margin:16px 0"><input id="mention-auto" type="checkbox" checked style="width:auto"> 分析完成后自动回复原评论；关闭时仅生成草稿</label>
<p>修改间隔或回复模式时，请先暂停监听，再重新启动。暂停会取消等待中的任务。</p>
<button id="mention-toggle" type="button" disabled>读取状态中…</button>
<div id="mention-control-status" class="status" role="status" aria-live="polite">正在读取监听状态…</div>
</section>'''
MENTION_SCRIPT = '''
let mentionInitialized=false,mentionActive=false,mentionBusy=false;
async function refreshMentionControl(){
  try{
    const r=await fetch('/api/mentions');const s=await r.json();if(!r.ok)throw new Error(s.error||'读取监听状态失败');
    mentionActive=s.enabled||s.autostart_pending;
    document.querySelector('#mention-toggle').disabled=mentionBusy;
    document.querySelector('#mention-toggle').textContent=mentionBusy?'处理中…':mentionActive?'暂停监听':'启动监听';
    document.querySelector('#mention-interval').disabled=s.enabled;
    document.querySelector('#mention-auto').disabled=s.enabled;
    if(!mentionInitialized){document.querySelector('#mention-interval').value=s.interval;document.querySelector('#mention-auto').checked=s.enabled?s.auto_reply:true;mentionInitialized=true;}
    document.querySelector('#mention-control-status').textContent=(s.enabled?'监听中':s.autostart_pending?'自动监听等待配置':'已暂停')+' · '+(s.auto_reply?'自动回复':'仅草稿')+' · 等待 '+s.queue.pending+' 条 · 处理中 '+s.queue.active+' 条'+(s.last_seen?' · 扩展最后连接：'+new Date(s.last_seen*1000).toLocaleTimeString():' · 等待扩展连接')+(s.error?' · '+s.error:'');
  }catch(e){document.querySelector('#mention-control-status').textContent=e.message;}
}
async function changeMentionControl(action){
  if(mentionBusy)return;
  mentionBusy=true;document.querySelector('#mention-toggle').disabled=true;document.querySelector('#mention-toggle').textContent='处理中…';
  try{const r=await fetch('/api/mentions/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({autoReply:document.querySelector('#mention-auto').checked,interval:Number(document.querySelector('#mention-interval').value)})});const s=await r.json();if(!r.ok)throw new Error(s.error||'操作失败');await refreshMentionControl();}catch(e){document.querySelector('#mention-control-status').textContent=e.message;}finally{mentionBusy=false;document.querySelector('#mention-toggle').disabled=false;document.querySelector('#mention-toggle').textContent=mentionActive?'暂停监听':'启动监听';}
}
document.querySelector('#mention-toggle').onclick=()=>changeMentionControl(mentionActive?'stop':'start');
refreshMentionControl();setInterval(()=>{if(document.querySelector('#mention-control').classList.contains('active'))refreshMentionControl();},5000);
'''
FIXED_HTML = FIXED_HTML.replace('<button data-panel="comfy">', '<button data-panel="mention-control">@我自动回复</button><button data-panel="comfy">')
FIXED_HTML = FIXED_HTML.replace('<section id="comfy" class="panel">', MENTION_PANEL + '<section id="comfy" class="panel">')
FIXED_HTML = FIXED_HTML.replace('</script></body></html>', MENTION_SCRIPT + '</script></body></html>')


DOUBAO_PANEL = '''<section id="mock-doubao" class="panel"><h2>豆包网页登录凭据</h2>
<p class="status">供 mock_doubao_seedream 生图使用。凭据过期后，在此更新自己的有效请求配置。保存后下次生成立即生效。</p>
<form id="mock-doubao-form" autocomplete="off"><div class="grid">
<label>请求地址<input name="base_url" type="url" required></label>
<label>请求路径<input name="endpoint" required></label>
<label>X-Tt-Token<input name="token" type="password" autocomplete="new-password" placeholder="留空保持原值"></label>
<label>Cookie<input name="cookie" type="password" autocomplete="new-password" placeholder="留空保持原值"></label>
<label>请求超时（秒）<input name="timeout" type="number" min="1" max="600" value="180" required></label>
</div><button type="button" id="doubao-reveal">显示 Token / Cookie</button><p class="status">Token 或 Cookie 未必足够；如请求签名、设备参数也已过期，请同时更新请求头或完整模板。已保存凭据会回填，可切换显示或隐藏；空白字段保持原值。</p>
<label>更新请求头（JSON，可选）<textarea name="headers" spellcheck="false" placeholder='{"X-Tt-Token":"新的登录 Token"}'></textarea></label>
<label>生图模型路由（JSON）<textarea name="model_routes" spellcheck="false" placeholder='{"mock_doubao_自定义英文标识":{"request":{"body":{}}}}'></textarea></label><p>每个模型需填写从真实请求确认的差异参数。名称仅支持 mock_doubao_ 加小写英文、数字、下划线；request 支持 body、query、headers、base_url、endpoint，按字段递归覆盖默认模板。不要只改名称；保存后重新打开生图页加载模型列表。</p><details><summary>已验证的网页生图请求</summary><p>由实际 cURL 导入的 /chat/completion 报文。Cookie 字段用于更新网页登录会话；此处保留 URL、其余请求头和 body。启用网页模板后不回退到旧 Android 请求。</p><label>网页请求 web_request（JSON）<textarea name="web_request" spellcheck="false" placeholder="{}"></textarea></label></details><details><summary>已验证的网页视频请求</summary><p>submit 是提交模板，poll 是会话查询模板。视频复用上方 Cookie。</p><label>web_video_request（JSON）<textarea name="web_video_request" spellcheck="false"></textarea></label></details><details><summary>完整请求模板（JSON）</summary><p>支持网页 web_request、web_video_request 及旧协议 headers、query、body；不会刷新签名。</p><label>请求配置<textarea name="request_config" spellcheck="false" placeholder='{"base_url":"https://api5-normal-lf.doubao.com","endpoint":"/im/sse/send/message","headers":{},"query":{},"body":{}}'></textarea></label></details>
<button type="submit">保存豆包登录配置</button><div class="status" role="status" aria-live="polite"></div></form></section>'''
FIXED_HTML = FIXED_HTML.replace('<button data-panel="comfy">', '<button data-panel="mock-doubao">豆包网页登录</button><button data-panel="comfy">')
FIXED_HTML = FIXED_HTML.replace('<section id="comfy" class="panel">', DOUBAO_PANEL + '<section id="comfy" class="panel">')
FIXED_HTML = FIXED_HTML.replace('</body>', '<script src="/assets/mock_doubao.js"></script></body>')


# Mock Provider references the shared private Doubao session; no duplicate credentials.
FIXED_HTML=FIXED_HTML.replace('<button data-panel="comfy">ComfyUI 模型</button>', '<button data-panel="doubao-provider">豆包 Mock Provider</button><button data-panel="comfy">ComfyUI 模型</button>')
FIXED_HTML=FIXED_HTML.replace('<section id="comfy" class="panel">', '''<section id="doubao-provider" class="panel"><h2>豆包 Mock Provider</h2><p>供直接生图及 AI视频生成资产使用。登录凭据复用“豆包网页登录”；参考图上传需要已登录 Chrome 豆包页和上传插件。当前参考图支持 1–2 张。</p><form data-provider="mock_doubao"><input name="id" type="hidden"><label>配置名称<input name="name" value="豆包 Mock" required></label><label>默认生图模型<select name="model"></select></label><label>默认视频模型<select name="default_video_model"></select></label><label><input name="enabled" type="checkbox" checked style="width:auto">启用</label><button>保存 Provider</button><div class="status"></div></form></section><section id="comfy" class="panel">''')
FIXED_HTML=FIXED_HTML.replace('</body>', '<script src="/assets/doubao_provider.js"></script></body>')

class Handler(http.server.BaseHTTPRequestHandler):
    def proxy_mentions(self):
        try:
            body = self.rfile.read(int(self.headers.get('content-length', '0'))) if self.command == 'POST' else None
            base = os.getenv('DOUYIN_SERVICE_URL', 'http://127.0.0.1:8101').rstrip('/')
            req = request.Request(base + self.path, data=body, headers={'Content-Type':'application/json'}, method=self.command)
            with request.urlopen(req, timeout=15) as response:
                self.send_body(response.status, 'application/json; charset=utf-8', response.read())
        except error.HTTPError as exc:
            self.send_body(exc.code, 'application/json; charset=utf-8', exc.read())
        except Exception:
            self.send_body(502, 'application/json; charset=utf-8', json.dumps({'error':'抖音服务连接失败，请检查服务是否运行'}, ensure_ascii=False))
    def log_message(self, *_): return
    def send_body(self, status, content_type, body):
        body=body.encode() if isinstance(body,str) else body; self.send_response(status); self.send_header('content-type',content_type); self.send_header('content-length',str(len(body))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.path == '/assets/doubao_provider.js': self.send_body(200,'application/javascript; charset=utf-8',Path(__file__).with_name('doubao_provider.js').read_text(encoding='utf-8')); return
        if self.path == '/assets/mock_doubao.js': self.send_body(200,'application/javascript; charset=utf-8',Path(__file__).with_name('mock_doubao.js').read_text(encoding='utf-8')); return
        if self.path == '/api/mock-doubao/credentials':
            try: self.send_body(200,'application/json; charset=utf-8',json.dumps(MockDoubaoConfigStore(self.server.store_dir/'mock_doubao.json').credentials(),ensure_ascii=False))
            except ValueError as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)},ensure_ascii=False))
            return
        if self.path == '/api/mock-doubao':
            try: self.send_body(200,'application/json; charset=utf-8',json.dumps(MockDoubaoConfigStore(self.server.store_dir/'mock_doubao.json').public(),ensure_ascii=False))
            except ValueError as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)},ensure_ascii=False))
            return
        if self.path == '/api/mentions': self.proxy_mentions(); return
        if self.path=='/api/storage': self.send_body(200,'application/json; charset=utf-8',json.dumps(StorageConfigStore(self.server.store_dir / 'storage.json').get(),ensure_ascii=False)); return
        if self.path=='/api/cloudinary': self.send_body(200,'application/json; charset=utf-8',json.dumps(CloudinaryConfigStore(self.server.store_dir / 'cloudinary.json').get(),ensure_ascii=False)); return
        if self.path in ('/','/index.html'): self.send_body(200,'text/html; charset=utf-8',FIXED_HTML); return
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
            from services.video_creator.tools.ai.doubao_web import MODELS
            models['mock_doubao_image']=list(MODELS)
            from services.video_creator.tools.ai.doubao_web_video import MODELS as VIDEO_MODELS
            models['mock_doubao_video']=list(VIDEO_MODELS)
            models['comfy']=list(dict.fromkeys(models['comfy'])); self.send_body(200,'application/json; charset=utf-8',json.dumps(models,ensure_ascii=False)); return
        self.send_body(404,'text/plain','Not found')
    def do_POST(self):
        if self.path == '/api/mock-doubao':
            try:
                length=int(self.headers.get('content-length','0'))
                if not 0 < length <= 1024*1024: raise ValueError('配置大小必须在 1 MB 以内')
                try: values=json.loads(self.rfile.read(length))
                except (ValueError, UnicodeError): raise ValueError('配置不是有效的 JSON') from None
                config=MockDoubaoConfigStore(self.server.store_dir/'mock_doubao.json').save(values)
                self.send_body(200,'application/json; charset=utf-8',json.dumps({'config':config},ensure_ascii=False))
            except ValueError as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)},ensure_ascii=False))
            except Exception: self.send_body(500,'application/json; charset=utf-8',json.dumps({'error':'保存豆包配置失败，请检查服务端存储'},ensure_ascii=False))
            return
        if self.path in ('/api/mentions/start', '/api/mentions/stop'): self.proxy_mentions(); return
        if self.path=='/api/storage':
            try:
                values=json.loads(self.rfile.read(int(self.headers.get('content-length','0')))); self.send_body(200,'application/json; charset=utf-8',json.dumps({'config':StorageConfigStore(self.server.store_dir / 'storage.json').save(values)},ensure_ascii=False))
            except Exception as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)}))
            return
        if self.path=='/api/cloudinary':
            try:
                values=json.loads(self.rfile.read(int(self.headers.get('content-length','0')))); self.send_body(200,'application/json; charset=utf-8',json.dumps({'config':CloudinaryConfigStore(self.server.store_dir / 'cloudinary.json').save(values)},ensure_ascii=False))
            except Exception as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)}))
            return
        if self.path!='/api/providers': self.send_body(404,'text/plain','Not found'); return
        try:
            values=json.loads(self.rfile.read(int(self.headers.get('content-length','0'))))
            if values.get('provider') == 'mock_doubao':
                from services.video_creator.tools.ai.doubao_web import MODELS
                if values.get('model') not in MODELS:raise ValueError('请选择已验证映射的豆包生图模型')
                from services.video_creator.tools.ai.doubao_web_video import MODELS as VIDEO_MODELS
                if values.get('default_video_model') and values['default_video_model'] not in VIDEO_MODELS:raise ValueError('请选择已确认映射的豆包视频模型')
                values={k:v for k,v in values.items() if k in {'id','provider','name','model','default_video_model','enabled'}}
            if values.get('provider') == 'douyin_understanding':
                from services.douyin.video_understanding import validate_config
                values = validate_config(values)
            self.send_body(200,'application/json; charset=utf-8',json.dumps({'provider':self.server.store.save(values)},ensure_ascii=False))
        except Exception as exc: self.send_body(400,'application/json; charset=utf-8',json.dumps({'error':str(exc)}))

def main():
    p=argparse.ArgumentParser(); p.add_argument('--host',default='127.0.0.1'); p.add_argument('--port',type=int,default=8103); p.add_argument('--cache-dir',type=Path,default=Path('cache/video_creator')); p.add_argument('--store-dir',type=Path,default=service_store('video_creator')); a=p.parse_args(); a.cache_dir.mkdir(parents=True,exist_ok=True); s=http.server.ThreadingHTTPServer((a.host,a.port),Handler); s.store_dir=a.store_dir.resolve(); s.store_dir.mkdir(parents=True,exist_ok=True); s.store=ProviderConfigStore(s.store_dir/'provider_configs.json'); s.comfy_url=os.getenv('COMFYUI_URL','http://127.0.0.1:8188'); print(f'admin listening=http://{a.host}:{a.port}',flush=True); s.serve_forever()
if __name__=='__main__': main()
