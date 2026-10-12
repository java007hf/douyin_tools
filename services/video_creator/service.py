#!/usr/bin/env python3
"""Video creator tab service: frame extraction and ComfyUI generation."""
from __future__ import annotations
import argparse, cgi, http.server, json, mimetypes, os, shutil, sqlite3, sys, threading, time, uuid, zipfile
from pathlib import Path
from urllib import parse, request
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.video_creator.tools.ai.comfyui_client import ComfyUIClient, ComfyUIError
from services.video_creator.tools.ai.config_store import ProviderConfigStore
from services.video_creator.tools.ai.providers import MiniMaxImageProvider, MiniMaxVideoProvider, ProviderError, SeedreamImageProvider, SeedanceProvider
from services.video_creator.tools.ai.llm import LLMError, OpenAICompatibleLLM
from services.video_creator.tools.video.extract_frames import extract_frames
from services.video_creator.tools.video.keyframes import extract_boundary_frames
from services.video_creator.tools.video.silence import ensure_non_dialogue_audio
from services.video_creator.workflow.generation import bind_media, flux_image, qwen_image, video_workflow
from services.video_creator.workflow.context import WorkflowContext
from services.video_creator.workflows.ai_video import AIVideoWorkflow
from services.video_creator.asset_library import ReferenceAssetStore
from services.core.storage import service_store
try: import oss2
except ImportError: oss2=None


def model_catalog(comfy_url: str) -> dict[str, list[str]]:
    models = {
        "minimax_image": ["image-01", "image-01-live"],
        "minimax_video": ["MiniMax-H3", "MiniMax-H3-Max"],
        "seedance_image": ["doubao-seedream-5-0-pro-260628", "doubao-seedream-5-0-260128", "doubao-seedream-5-0-lite-260128", "doubao-seedream-4-5-251128", "doubao-seedream-4-0-250828"],
        "seedance_video": ["doubao-seedance-2-0-pro", "doubao-seedance-2-0-fast", "doubao-seedance-2-0-mini", "doubao-seedance-1-5-pro-251215", "doubao-seedance-1-0-pro-250528"],
        "comfy": [],
        "comfy_video": [],
    }
    try:
        info = json.loads(request.urlopen(comfy_url + "/object_info", timeout=10).read())
        for node in ("UNETLoader", "CheckpointLoaderSimple", "CLIPLoader"):
            required = info.get(node, {}).get("input", {}).get("required", {})
            for field in ("unet_name", "ckpt_name", "clip_name"):
                values = required.get(field, [[]])[0]
                if isinstance(values, list):
                    for value in values:
                        target = models["comfy_video"] if field == "unet_name" and any(token in str(value).lower() for token in ("video", "minimax_h3")) else models["comfy"]
                        target.append(str(value))
    except Exception:
        pass
    models["comfy"] = list(dict.fromkeys(models["comfy"]))
    models["comfy_video"] = list(dict.fromkeys(models["comfy_video"]))
    models["comfy"] = [value for value in models["comfy"] if not any(token in value.lower() for token in ("minimax_h3", "qwen3vl", "qwen_2.5_vl", "video", "audio", "vae", "clip", "t5xxl"))]
    return models

def cloudinary_config() -> dict[str, str | bool]:
    values={"cloud_name":os.getenv("CLOUDINARY_CLOUD_NAME",""),"upload_preset":os.getenv("CLOUDINARY_UPLOAD_PRESET","")}
    path=service_store("video_creator") / "cloudinary.json"
    try:
        values.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError): pass
    try:
        storage=json.loads((service_store("video_creator") / "storage.json").read_text(encoding="utf-8"))
        if storage.get("provider")=="cloudinary": values.update({k:storage.get(k,"") for k in ("cloud_name","upload_preset")})
    except (OSError, json.JSONDecodeError): pass
    values["enabled"]=bool(values.get("cloud_name") and values.get("upload_preset")); return values

def storage_config() -> dict[str, str | bool]:
    path=(service_store("video_creator") / "storage.json"); values={}
    try: values=json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): pass
    values["provider"]=values.get("provider") or "oss"; values["enabled"]=bool((values.get("provider")=="oss" and values.get("endpoint") and values.get("bucket") and values.get("access_key_id") and values.get("access_key_secret") and values.get("public_base_url")) or (values.get("provider")=="cloudinary" and values.get("cloud_name") and values.get("upload_preset"))); return values

def cloudinary_upload(config: dict, filename: str, data: bytes) -> str:
    boundary="----DouyinCloudinary"+uuid.uuid4().hex
    mime=mimetypes.guess_type(filename)[0] or "application/octet-stream"
    parts=[f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{Path(filename).name}\"\r\nContent-Type: {mime}\r\n\r\n".encode()+data, f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload_preset\"\r\n\r\n{config['upload_preset']}\r\n".encode(), f"--{boundary}--\r\n".encode()]
    url=f"https://api.cloudinary.com/v1_1/{config['cloud_name']}/auto/upload"
    response=request.urlopen(request.Request(url,data=b"".join(parts),headers={"Content-Type":f"multipart/form-data; boundary={boundary}"}),timeout=120)
    result=json.loads(response.read()); secure_url=result.get("secure_url")
    if not secure_url: raise ValueError(result.get("error",{}).get("message","Cloudinary 上传失败"))
    return secure_url


def save_remote_asset(url: str, target: Path) -> None:
    """Copy short-lived cloud output URLs into the persistent local asset area."""
    req = request.Request(url, headers={"User-Agent": "DouyinWorkspace/1.0", "Accept": "*/*"})
    with request.urlopen(req, timeout=180) as response:
        data=response.read()
    if not data: raise ValueError("云端返回了空的图片内容")
    target.write_bytes(data)

def multipart_body(fields: dict[str, str], files: dict[str, Path]) -> tuple[bytes, str]:
    boundary = "----AIVideo" + uuid.uuid4().hex
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode("utf-8"))
    for name, path in files.items():
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        parts.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"; filename=\"{path.name}\"\r\nContent-Type: {mime}\r\n\r\n".encode("utf-8") + path.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"

def selected_library_assets(form, store: ReferenceAssetStore) -> list[dict]:
    raw=str(form.getvalue("library_asset_ids") or "").strip(); ids=[]
    if raw:
        try:
            value=json.loads(raw); ids=value if isinstance(value,list) else []
        except json.JSONDecodeError: ids=[item.strip() for item in raw.split(",") if item.strip()]
    legacy=str(form.getvalue("library_asset_id") or "").strip()
    if legacy and legacy not in ids: ids.insert(0,legacy)
    assets=[]
    for asset_id in ids[:50]:
        asset=store.get(str(asset_id))
        if asset: assets.append(asset)
    return assets

def asset_prompt_context(assets: list[dict]) -> str:
    if not assets: return ""
    values=[{"id":item["id"],"name":item.get("name"),"kind":item.get("kind"),"description":item.get("description",{})} for item in assets]
    return "\n\n已选择的参考资产（asset ID 必须保持绑定）：\n"+json.dumps(values,ensure_ascii=False)

HTML = """<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>视频创作</title><style>body{margin:0;background:#f7f8fa;color:#182230;font:14px Segoe UI,Microsoft YaHei,Arial,sans-serif}main{max-width:980px;margin:auto;padding:28px}.tool,.gen-panel{background:#fff;border:1px solid #dde2ea;border-radius:8px;padding:20px}h1{margin:0 0 6px}h2{margin-top:0}label{display:block;margin:14px 0 6px;color:#475467}input,select{width:100%;box-sizing:border-box;padding:10px;border:1px solid #cfd6e0;border-radius:6px;font:inherit}.mode{display:flex;gap:16px}.mode label{margin:8px 0}.mode input{width:auto}button{margin-top:18px;padding:10px 16px;border:0;border-radius:6px;background:#0f766e;color:#fff;font:inherit}.status{margin-top:14px;color:#667085;white-space:pre-wrap}.error{color:#b42318}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-top:16px}.frame{border:1px solid #dde2ea;border-radius:6px;overflow:hidden}.frame img{width:100%;aspect-ratio:16/9;object-fit:contain;background:#101828;display:block}.frame div{padding:7px;font-size:12px;color:#667085}@media(max-width:700px){main{padding:16px}}</style></head><body><main><h1>视频创作</h1><p>视频工具与 AI 生成工作台</p><section class='tool'><h2>视频抽帧</h2><form id='form'><label>输入视频<input id='video' type='file' accept='video/*' required></label><label>抽帧方式</label><div class='mode'><label><input type='radio' name='mode' value='interval' checked>按时间间隔</label><label><input type='radio' name='mode' value='count'>按总张数</label></div><label>参数<input id='value' type='number' min='0.1' step='0.1' value='1'></label><label>图片格式<select id='format'><option value='jpg'>JPG</option><option value='png'>PNG</option><option value='webp'>WebP</option></select></label><button id='submit'>开始抽帧</button><div id='status' class='status'></div></form></section><section class='tool' style='margin-top:16px'><h2>抽帧结果</h2><div id='meta' class='status'>暂无结果</div><div id='frames' class='grid'></div></section></main><script>const form=document.querySelector('#form'),submit=document.querySelector('#submit'),status=document.querySelector('#status'),meta=document.querySelector('#meta'),frames=document.querySelector('#frames');document.querySelectorAll('input[name=mode]').forEach(r=>r.onchange=()=>{const i=document.querySelector('#value'),c=r.value==='count';i.min=c?'1':'0.1';i.step=c?'1':'0.1';i.value=c?'10':'1'});async function poll(id){for(;;){const r=await fetch('/api/jobs/'+id),j=await r.json();if(!r.ok)throw Error(j.error||'任务不存在');status.textContent=(j.message||j.status)+(j.progress==null?'':' '+j.progress+'%');if(j.status==='done')return j.result;if(j.status==='error')throw Error(j.error||'任务失败');await new Promise(x=>setTimeout(x,500))}}form.onsubmit=async e=>{e.preventDefault();const file=document.querySelector('#video').files[0],mode=document.querySelector('input[name=mode]:checked').value;submit.disabled=true;frames.replaceChildren();meta.textContent='暂无结果';status.className='status';status.textContent='正在上传视频...';const b=new FormData;b.append('video',file);b.append('mode',mode);b.append('value',document.querySelector('#value').value);b.append('format',document.querySelector('#format').value);try{const r=await fetch('/api/extract-frames',{method:'POST',body:b}),j=await r.json();if(!r.ok)throw Error(j.error||'提交失败');const x=await poll(j.jobId);meta.textContent='共 '+x.files.length+' 张，视频时长 '+x.duration+' 秒';const a=document.createElement('a');a.href=x.zip;a.textContent='下载全部图片（ZIP）';a.style.display='inline-block';a.style.marginTop='15px';frames.before(a);x.files.forEach(f=>{const c=document.createElement('div'),img=document.createElement('img'),d=document.createElement('div');c.className='frame';img.src=f.href;img.loading='lazy';d.textContent=f.name+' · '+f.timestamp+'s';c.append(img,d);frames.append(c)})}catch(err){status.className='status error';status.textContent=err.message}finally{submit.disabled=false}};</script></body></html>"""

class Jobs:
    def __init__(self): self.data, self.lock = {}, threading.Lock()
    def create(self):
        job=uuid.uuid4().hex
        with self.lock: self.data[job]={"id":job,"status":"queued","message":"任务已创建"}
        return job
    def update(self, job, **fields):
        with self.lock:
            if job in self.data: self.data[job].update(fields)
    def get(self, job):
        with self.lock: return dict(self.data[job]) if job in self.data else None
    def delete(self, job):
        with self.lock: return self.data.pop(job, None) is not None

class PersistentJobs:
    def __init__(self, path: Path | None = None):
        self.path, self.lock = path or service_store("video_creator") / "assets.db", threading.Lock(); self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db: db.execute("CREATE TABLE IF NOT EXISTS assets (id TEXT PRIMARY KEY, data TEXT NOT NULL, created_at REAL NOT NULL)")
    def create(self):
        job=uuid.uuid4().hex; value={"id":job,"status":"queued","message":"任务已创建"}
        with self.lock, sqlite3.connect(self.path) as db: db.execute("INSERT INTO assets VALUES (?, ?, strftime('%s','now'))",(job,json.dumps(value,ensure_ascii=False)))
        return job
    def update(self, job, **fields):
        with self.lock, sqlite3.connect(self.path) as db:
            row=db.execute("SELECT data FROM assets WHERE id=?",(job,)).fetchone()
            if row: value=json.loads(row[0]); value.update(fields); db.execute("UPDATE assets SET data=? WHERE id=?",(json.dumps(value,ensure_ascii=False),job))
    def get(self, job):
        with self.lock, sqlite3.connect(self.path) as db:
            row=db.execute("SELECT data FROM assets WHERE id=?",(job,)).fetchone(); return json.loads(row[0]) if row else None
    def list(self):
        with self.lock, sqlite3.connect(self.path) as db: rows=db.execute("SELECT data FROM assets ORDER BY created_at DESC").fetchall()
        return [json.loads(row[0]) for row in rows]
    def delete(self, job):
        with self.lock, sqlite3.connect(self.path) as db: result=db.execute("DELETE FROM assets WHERE id=?",(job,)); return result.rowcount > 0

Jobs = PersistentJobs

def recover_comfy_jobs(server) -> None:
    """Finalize local jobs if the worker stopped after ComfyUI completed."""
    client=ComfyUIClient(server.comfy_url)
    try:
        queue=client.queue_state()
        active={str(row[1]) for key in ("queue_running", "queue_pending") for row in queue.get(key, []) if isinstance(row, list) and len(row)>1}
    except Exception:
        active=set()
    for job in server.jobs.list():
        if job.get("status") not in {"queued","running"} or job.get("provider_id") != "local" or not job.get("prompt_id"):
            continue
        try:
            prompt_id=str(job["prompt_id"])
            item=client.history(prompt_id).get(prompt_id,{})
            if not item and prompt_id not in active:
                server.jobs.update(job["id"],status="error",message="任务已中断",error="ComfyUI 中没有找到该任务，可能在服务重启或手动中断时停止")
                continue
            status=item.get("status",{})
            if status.get("status_str") == "error":
                server.jobs.update(job["id"],status="error",message="ComfyUI 任务失败",error=str(status.get("messages","ComfyUI execution failed")))
            elif item.get("outputs"):
                outputs=[]
                for node in item.get("outputs",{}).values():
                    for key in ("images","gifs","videos"):
                        for output in node.get(key,[]) or []:
                            filename=str(output.get("filename","")).lower()
                            is_video=key in ("gifs","videos") or filename.endswith((".mp4",".webm",".mov",".mkv"))
                            outputs.append({"type":"video" if is_video else "image","href":"/api/comfy-view?"+parse.urlencode(output)})
                if outputs:
                    server.jobs.update(job["id"],status="done",message="生成完成",progress=100,outputs=outputs)
        except Exception:
            continue

class Handler(http.server.BaseHTTPRequestHandler):
    server_version="VideoCreator/0.3"
    def log_message(self,*_): return
    def send_json(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header("content-type","application/json; charset=utf-8"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=parse.urlsplit(self.path).path
        if path in ("/","/index.html"):
            body=HTML.replace("</body>",'<script src="/assets/frame_preview.js?v=2"></script><script src="/assets/generation.js?v=3"></script></body>').encode(); self.send_response(200); self.send_header("content-type","text/html; charset=utf-8"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path in ("/assets/frame_preview.js","/assets/generation.js"):
            body=Path(__file__).with_name(path.rsplit("/",1)[-1]).read_bytes(); self.send_response(200); self.send_header("content-type","text/javascript; charset=utf-8"); self.send_header("cache-control","no-store"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path=="/health": self.send_json(200,{"ok":True,"service":"video-creator"}); return
        if path=="/api/providers": self.send_json(200,{"providers":self.server.providers.list_public()}); return
        if path=="/api/llm-config":
            config=self.server.providers.get_by_provider("llm") or {}
            self.send_json(200,{k:("********" if k=="api_key" and v else v) for k,v in config.items() if k not in {"secret","token"}}); return
        if path=="/api/cloudinary-config": self.send_json(200,cloudinary_config()); return
        if path=="/api/storage-config": self.send_json(200,storage_config()); return
        if path=="/api/models": self.send_json(200,model_catalog(self.server.comfy_url)); return
        if path=="/api/assets":
            # AI Video child jobs are internal production steps (asset renders and
            # shot renders). They remain queryable by id and visible in the parent
            # Trace, but must not pollute the user-facing draft inbox.
            assets=[item for item in self.server.jobs.list() if not item.get("parent_job")]
            self.send_json(200,{"assets":assets}); return
        if path=="/api/library-assets": self.send_json(200,{"assets":self.server.asset_library.list()}); return
        if path.startswith("/api/generation-jobs/") and path.endswith("/trace"):
            job_id=path.split("/")[-2];job=self.server.jobs.get(job_id)
            if not job: self.send_json(404,{"error":"任务不存在"}); return
            task_dir=self.server.store_dir/("ai_video_jobs" if job.get("kind")=="ai_video" else "generation_jobs")/job_id
            files=[str(item.relative_to(task_dir)).replace("\\","/") for item in task_dir.rglob("*") if item.is_file()] if task_dir.is_dir() else []
            children=[item for item in self.server.jobs.list() if item.get("parent_job")==job_id]
            self.send_json(200,{"task":job,"child_tasks":children,"artifact_files":files}); return
        if path.startswith("/api/jobs/") or path.startswith("/api/generation-jobs/"):
            job=self.server.jobs.get(path.rsplit("/",1)[-1]); self.send_json(200 if job else 404,job or {"error":"任务不存在"}); return
        if path=="/api/comfy-view":
            try:
                query=parse.urlsplit(self.path).query; response=request.urlopen(f"{self.server.comfy_url}/view?{query}",timeout=60); body=response.read(); self.send_response(200); self.send_header("content-type",response.headers.get("content-type","application/octet-stream")); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body)
            except Exception as exc: self.send_json(502,{"error":str(exc)})
            return
        if path.startswith("/artifacts/"):
            target=(self.server.store_dir/parse.unquote(path[len("/artifacts/"):])).resolve()
            try: target.relative_to(self.server.store_dir.resolve())
            except ValueError: self.send_error(403); return
            if target.is_file():
                body=target.read_bytes(); self.send_response(200); self.send_header("content-type",mimetypes.guess_type(target.name)[0] or "application/octet-stream"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        self.send_error(404)
    def do_PATCH(self):
        path=parse.urlsplit(self.path).path
        if not path.startswith("/api/generation-jobs/"):
            self.send_json(404,{"error":"Not found"}); return
        job_id=path.rsplit("/",1)[-1]; job=self.server.jobs.get(job_id)
        if not job: self.send_json(404,{"error":"Generation asset not found"}); return
        try:
            length=int(self.headers.get("content-length","0")); values=json.loads(self.rfile.read(length)); fields={}
            if "prompt" in values: fields["prompt"]=str(values["prompt"]).strip()
            if "params" in values and isinstance(values["params"],dict): fields["params"]=values["params"]
            self.server.jobs.update(job_id,**fields); self.send_json(200,self.server.jobs.get(job_id))
        except Exception as exc: self.send_json(400,{"error":str(exc)})
    def do_DELETE(self):
        path=parse.urlsplit(self.path).path
        if path.startswith("/api/library-assets/"):
            asset_id=path.rsplit("/",1)[-1]
            self.send_json(200,{"ok":True}) if self.server.asset_library.delete(asset_id) else self.send_json(404,{"error":"资产不存在"})
            return
        if not path.startswith("/api/generation-jobs/"):
            self.send_json(404,{"error":"Not found"}); return
        job_id=path.rsplit("/",1)[-1]; job=self.server.jobs.get(job_id)
        if not job: self.send_json(404,{"error":"Generation asset not found"}); return
        self.server.cancelled_jobs.add(job_id)
        children=[item for item in self.server.jobs.list() if item.get("parent_job")==job_id]
        comfy=ComfyUIClient(self.server.comfy_url); cancelled_prompts=[]
        for item in [job,*children]:
            prompt_id=str(item.get("prompt_id") or "")
            if prompt_id:
                try:
                    if comfy.cancel(prompt_id): cancelled_prompts.append(prompt_id)
                except Exception: pass
        for item in children: self.server.cancelled_jobs.add(item["id"]); self.server.jobs.delete(item["id"])
        self.server.jobs.delete(job_id)
        self.send_json(200,{"ok":True,"cancelled":job.get("status") not in {"done","error"},"cancelled_prompt_ids":cancelled_prompts})
    def do_PUT(self):
        path=parse.urlsplit(self.path).path
        if not path.startswith("/api/library-assets/"):
            self.send_json(404,{"error":"Not found"}); return
        try:
            asset_id=path.rsplit("/",1)[-1]
            length=int(self.headers.get("content-length","0")); values=json.loads(self.rfile.read(length))
            name=str(values.get("name") or "").strip(); kind=str(values.get("kind") or "").strip()
            description=values.get("description")
            if not name: raise ValueError("资产名称不能为空")
            if kind not in {"character","location","prop","style"}: raise ValueError("资产类型无效")
            if not isinstance(description,dict): raise ValueError("资产描述必须是 JSON 对象")
            asset=self.server.asset_library.update(asset_id,name=name,kind=kind,description=description)
            if not asset: self.send_json(404,{"error":"资产不存在"}); return
            self.send_json(200,{"asset":asset})
        except Exception as exc:
            self.send_json(400,{"error":str(exc)})
    def do_POST(self):
        path=parse.urlsplit(self.path).path
        if path.startswith("/api/library-assets/") and path.endswith("/regenerate"):
            asset_id=path.split("/")[-2]; asset=self.server.asset_library.get(asset_id)
            if not asset: self.send_json(404,{"error":"资产不存在"}); return
            try:
                form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")})
                prompt=str(form.getvalue("prompt") or "").strip()
                if not prompt: raise ValueError("请输入重新生成 Prompt")
                reference=self.server.asset_library.use(asset_id); upload=form["reference_image"] if "reference_image" in form else None; temp=None
                uploaded=upload is not None and bool(getattr(upload,"filename",""))
                if uploaded:
                    suffix=Path(upload.filename).suffix.lower() or ".png"; temp=self.server.store_dir/"reference_library"/("regenerate-"+uuid.uuid4().hex+suffix);temp.write_bytes(upload.file.read());reference=temp
                if not reference or not reference.is_file(): raise ValueError("原资产参考图已丢失，请上传新的参考图")
                host=self.server.server_address[0];base=f"http://{'127.0.0.1' if host in ('0.0.0.0','::') else host}:{self.server.server_address[1]}"
                fields={"provider_id":"local","model":"qwen_image_fp8_e4m3fn.safetensors","prompt":prompt,"count":"1","aspect":"16:9","resolution":"2K","reference_type":"style" if asset.get("kind")=="style" else "identity"}
                body,content_type=multipart_body(fields,{"reference_image":reference})
                result=json.loads(request.urlopen(request.Request(base+"/api/generate-image",data=body,headers={"Content-Type":content_type}),timeout=120).read())
                job_id=str(result["jobId"]);self.server.jobs.update(job_id,asset_regeneration_source_id=asset_id,asset_regeneration_name=asset.get("name"),asset_regeneration_kind=asset.get("kind"))
                if temp: temp.unlink(missing_ok=True)
                def persist_regenerated():
                    deadline=time.monotonic()+14400
                    while time.monotonic()<deadline:
                        state=self.server.jobs.get(job_id)
                        if not state or state.get("status") in {"error","cancelled"}: return
                        if state.get("status")=="done":
                            outputs=state.get("outputs") or [];href=str(outputs[0].get("href") or "") if outputs else ""
                            if href:
                                if href.startswith("/artifacts/"):
                                    source=(self.server.store_dir/parse.unquote(href[len("/artifacts/"):])).resolve();source.relative_to(self.server.store_dir)
                                else:
                                    query=parse.parse_qs(parse.urlsplit(href).query);suffix=Path(str((query.get("filename") or ["asset.png"])[0])).suffix or ".png"
                                    source=self.server.store_dir/"generation_jobs"/job_id/("regenerated_asset"+suffix);source.parent.mkdir(parents=True,exist_ok=True)
                                    with request.urlopen(href if href.startswith("http") else base+href,timeout=300) as remote: source.write_bytes(remote.read())
                                description=dict(asset.get("description") or {});description.update({"prompt":prompt,"derived_from":asset_id,"generation_model":"qwen_image_fp8_e4m3fn.safetensors","reference_source":"uploaded" if uploaded else "current_asset"})
                                generated,duplicate=self.server.asset_library.add(source,name=str(asset.get("name") or "未命名资产")[:80],kind=str(asset.get("kind") or "character"),description=description,source_type="asset_regeneration",source_id=job_id)
                                self.server.jobs.update(job_id,persisted_asset_id=generated.get("id"),persisted_asset_duplicate=duplicate)
                            return
                        time.sleep(2)
                threading.Thread(target=persist_regenerated,daemon=True).start()
                self.send_json(202,{"ok":True,"jobId":job_id,"message":"改良版资产已开始生成"})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path.startswith("/api/generation-jobs/") and path.endswith("/asset-decisions"):
            job_id=path.split("/")[-2];job=self.server.jobs.get(job_id)
            if not job: self.send_json(404,{"error":"任务不存在"}); return
            if job.get("status")!="awaiting_asset_confirmation": self.send_json(409,{"error":"任务当前不在资产确认阶段"}); return
            try:
                length=int(self.headers.get("content-length","0"));values=json.loads(self.rfile.read(length));decisions=values.get("decisions")
                if not isinstance(decisions,dict): raise ValueError("缺少资产选择")
                requirements={str(item.get("entity_id")):item for item in job.get("asset_requirements",[]) if isinstance(item,dict) and item.get("entity_id")}
                if set(decisions)!=set(requirements): raise ValueError("请为每个角色、场景和道具完成选择")
                normalized={}
                for entity_id,choice in decisions.items():
                    if not isinstance(choice,dict) or choice.get("action") not in {"keep","reuse","regenerate"}: raise ValueError(f"{entity_id} 的选择无效")
                    if choice["action"]=="reuse":
                        asset_id=str(choice.get("asset_id") or "");asset=self.server.asset_library.get(asset_id)
                        if not asset or asset.get("kind")!=requirements[entity_id].get("kind"): raise ValueError(f"{entity_id} 选择的资产不存在或类型不匹配")
                        normalized[entity_id]={"action":"reuse","asset_id":asset_id,"name":asset.get("name")}
                    elif choice["action"]=="regenerate": normalized[entity_id]={"action":"regenerate"}
                    else: normalized[entity_id]={"action":"keep"}
                self.server.jobs.update(job_id,asset_decisions=normalized,message="资产选择已确认，正在继续生成")
                self.send_json(200,{"ok":True,"jobId":job_id})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/library-assets":
            try:
                content_type=self.headers.get("content-type","")
                if content_type.startswith("multipart/form-data"):
                    form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":content_type})
                    item=form["file"] if "file" in form else None
                    if item is None or not getattr(item,"filename",""): raise ValueError("请选择参考图")
                    suffix=Path(item.filename).suffix.lower() or ".bin"; temp=self.server.store_dir/"reference_library"/("upload-"+uuid.uuid4().hex+suffix); temp.parent.mkdir(parents=True,exist_ok=True); temp.write_bytes(item.file.read())
                    try: asset,duplicate=self.server.asset_library.add(temp,name=str(form.getvalue("name") or Path(item.filename).stem),kind=str(form.getvalue("kind") or "character"),description=json.loads(str(form.getvalue("description") or "{}")))
                    finally: temp.unlink(missing_ok=True)
                else:
                    length=int(self.headers.get("content-length","0")); values=json.loads(self.rfile.read(length)); job=self.server.jobs.get(str(values.get("job_id") or ""))
                    if not job or job.get("status")!="done": raise ValueError("只能从已完成的草稿沉淀资产")
                    index=int(values.get("output_index") or 0); outputs=job.get("outputs") or []
                    if index<0 or index>=len(outputs) or outputs[index].get("type")!="image": raise ValueError("请选择草稿中的图片产物")
                    href=str(outputs[index].get("href") or ""); prefix="/artifacts/"
                    if not href.startswith(prefix): raise ValueError("远程临时图片请先下载后上传到资产库")
                    source=(self.server.store_dir/parse.unquote(href[len(prefix):])).resolve(); source.relative_to(self.server.store_dir)
                    description=values.get("description") if isinstance(values.get("description"),dict) else {"prompt":job.get("prompt","")}
                    asset,duplicate=self.server.asset_library.add(source,name=str(values.get("name") or job.get("prompt") or "未命名资产")[:80],kind=str(values.get("kind") or "character"),description=description,source_type="generation",source_id=job["id"])
                self.send_json(200,{"asset":asset,"duplicate":duplicate})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/upload-cloud-reference":
            try:
                cloud=cloudinary_config()
                if not cloud.get("enabled"): raise ValueError("请先在后台控制台配置阿里云 OSS，或配置 Cloudinary")
                form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); item=form["file"] if "file" in form else None
                if item is None or not getattr(item,"filename",""): raise ValueError("未上传参考素材")
                self.send_json(200,{"url":cloudinary_upload(cloud,item.filename,item.file.read())})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/upload-reference":
            try:
                config=storage_config()
                if config.get("provider")!="oss" or not config.get("enabled"): raise ValueError("请先在后台控制台配置完整的阿里云 OSS 和公网访问地址")
                if oss2 is None: raise ValueError("缺少 oss2 依赖，请执行 pip install -r requirements.txt")
                form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); item=form["file"] if "file" in form else None
                if item is None or not getattr(item,"filename",""): raise ValueError("未上传参考素材")
                suffix=Path(item.filename).suffix.lower() or ".bin"; key=f"references/{uuid.uuid4().hex}{suffix}"; data=item.file.read(); auth=oss2.Auth(config["access_key_id"],config["access_key_secret"]); bucket=oss2.Bucket(auth,config["endpoint"],config["bucket"]); bucket.put_object(key,data); url=config["public_base_url"].rstrip("/")+"/"+key; self.send_json(200,{"url":url})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/providers":
            try:
                length=int(self.headers.get("content-length","0")); values=json.loads(self.rfile.read(length)); self.send_json(200,{"provider":self.server.providers.save(values)})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/improve-prompt":
            try:
                length=int(self.headers.get("content-length","0")); values=json.loads(self.rfile.read(length)); config=self.server.providers.get_by_provider("llm")
                if not config or config.get("enabled") is False: raise LLMError("请先在后台控制中配置并启用 LLM")
                api_key=config.get("api_key") or config.get("token")
                if not api_key: raise LLMError("LLM 尚未配置 API Key")
                prompt=str(values.get("prompt") or "").strip(); kind=str(values.get("kind") or "image"); instruction=str(values.get("instruction") or "")
                if not prompt: raise LLMError("请输入原始提示词")
                model=str(config.get("model") or "gpt-4o-mini"); base_url=str(config.get("base_url") or "https://api.openai.com/v1")
                improved=OpenAICompatibleLLM(base_url,api_key,model).improve(prompt,instruction,kind); self.send_json(200,{"prompt":improved})
            except Exception as exc: self.send_json(400,{"error":str(exc)})
            return
        if path=="/api/generate-ai-video": self.handle_ai_video(); return
        if path in ("/api/generate-image","/api/generate-video"): self.handle_generation(path.rsplit("/",1)[-1].replace("generate-","")); return
        if path!="/api/extract-frames": self.send_json(404,{"error":"Not found"}); return
        try:
            form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); upload=form["video"] if "video" in form else None
            if upload is None or not getattr(upload,"filename",""): raise ValueError("请上传视频文件")
            mode,value,fmt=str(form.getvalue("mode") or "interval"),float(form.getvalue("value") or 0),str(form.getvalue("format") or "jpg")
            if mode not in {"interval","count"} or value<=0: raise ValueError("抽帧参数无效")
            job=self.server.jobs.create(); task=self.server.store_dir/"frame_jobs"/job; task.mkdir(parents=True,exist_ok=True); source=task/(Path(upload.filename).name or "input.mp4"); source.write_bytes(upload.file.read())
            def run():
                try:
                    self.server.jobs.update(job,status="running",message="正在读取视频"); result=extract_frames(source,task/"frames",interval_seconds=value if mode=="interval" else None,frame_count=int(value) if mode=="count" else None,image_format=fmt,progress_callback=lambda msg,cur,total:self.server.jobs.update(job,message=msg,progress=round(cur/total*100))); archive=task/"frames.zip"
                    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
                        for item in result["files"]: z.write(item["path"],item["name"])
                    files=[{"name":x["name"],"timestamp":x["timestamp"],"href":f"/artifacts/frame_jobs/{job}/frames/{x['name']}"} for x in result["files"]]; self.server.jobs.update(job,status="done",message="抽帧完成",result={"files":files,"duration":result["duration"],"fps":result["fps"],"zip":f"/artifacts/frame_jobs/{job}/frames.zip"})
                except Exception as exc: self.server.jobs.update(job,status="error",message="抽帧失败",error=str(exc))
            threading.Thread(target=run,daemon=True).start(); self.send_json(202,{"ok":True,"jobId":job})
        except Exception as exc: self.send_json(400,{"error":str(exc)})
    def handle_ai_video(self):
        try:
            form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")})
            brief=str(form.getvalue("prompt") or "").strip()
            if not brief: raise ValueError("请输入视频创作要求")
            agent_config=self.server.providers.get_by_provider("ai_video_agent") or {}
            if not agent_config or agent_config.get("enabled") is False or not (agent_config.get("api_key") or agent_config.get("token")): raise LLMError("请先在后台控制的 AI视频 中配置并启用 Agent 模型")
            job=self.server.jobs.create(); task=self.server.store_dir/"ai_video_jobs"/job; task.mkdir(parents=True,exist_ok=True)
            def save(field, default):
                item=form[field] if field in form else None
                if item is None or not getattr(item,"filename",""): return None
                target=task/default; target.write_bytes(item.file.read()); return target
            image=save("reference_image","reference_image"+(Path(getattr(form["reference_image"],"filename","")).suffix if "reference_image" in form else ".png"))
            video=save("reference_video","reference_video"+(Path(getattr(form["reference_video"],"filename","")).suffix if "reference_video" in form else ".mp4"))
            selected_assets=selected_library_assets(form,self.server.asset_library);library_asset_ids=[item["id"] for item in selected_assets];library_asset_id=library_asset_ids[0] if library_asset_ids else ""
            if library_asset_id and not image:
                source=self.server.asset_library.use(library_asset_id)
                if not source: raise ValueError("选择的资产不存在或文件已丢失")
                image=task/("library_reference"+source.suffix); shutil.copy2(source,image)
            params={key:str(form.getvalue(key) or "") for key in ("image_url","video_url","library_asset_id")}
            params["library_asset_ids"]=library_asset_ids
            params["confirm_assets"]=str(form.getvalue("confirm_assets") or "").lower() in {"1","true","on","yes"}
            params.update({"model":str(agent_config.get("default_video_model") or ""),"provider_id":str(agent_config.get("default_video_provider_id") or "local"),"total_duration":max(1,min(300,int(form.getvalue("total_duration") or 15)))})
            self.server.jobs.update(job,kind="ai_video",prompt=brief,reference_image=image.name if image else "",reference_video=video.name if video else "",provider_id=params["provider_id"] or "local",params=params,nodes=[])
            if image and not library_asset_id:
                try: self.server.asset_library.add(image,name=str(getattr(form["reference_image"],"filename","") or "AI视频用户参考图")[:80],kind="reference",description={"prompt":brief,"role":"user_reference"},source_type="upload",source_id=job)
                except Exception: pass
            host=self.server.server_address[0]
            base=f"http://{'127.0.0.1' if host in ('0.0.0.0','::') else host}:{self.server.server_address[1]}"
            def run():
                try:
                    # A full storyboard contains a structured plan for every shot and can take several minutes on reasoning models.
                    llm=OpenAICompatibleLLM(str(agent_config.get("base_url") or "https://api.openai.com/v1"),str(agent_config.get("api_key") or agent_config.get("token")),str(agent_config.get("model") or "gpt-4o-mini"),600)
                    workflow_params=dict(params)
                    workflow_params["_enforce_story_arc"]=True
                    workflow_params["_available_library_assets"]=[{"id":item.get("id"),"name":item.get("name"),"kind":item.get("kind"),"description":item.get("description",{}),"href":item.get("href","")} for item in self.server.asset_library.list()[:100]]
                    context=WorkflowContext(job,task,brief+asset_prompt_context(selected_assets),image,video,workflow_params)
                    def changed(nodes):
                        if job in self.server.cancelled_jobs: raise RuntimeError("任务已取消")
                        completed=sum(node["status"]=="success" for node in nodes); running=next((node for node in nodes if node["status"]=="running"),None)
                        self.server.jobs.update(job,status="running",message=running["title"] if running else "AI 视频工作流执行中",progress=min(95,completed*20),nodes=nodes)
                    def public_url(path):
                        storage=storage_config()
                        if not storage.get("enabled"): raise ValueError("云端生成需要在后台配置素材存储，才能上传 Agent 生成的参考图")
                        if storage.get("provider")=="cloudinary": return cloudinary_upload(storage,path.name,path.read_bytes())
                        if oss2 is None: raise ValueError("缺少 oss2 依赖")
                        key=f"ai-video/{job}/{uuid.uuid4().hex}{path.suffix.lower()}";bucket=oss2.Bucket(oss2.Auth(storage["access_key_id"],storage["access_key_secret"]),storage["endpoint"],storage["bucket"]);bucket.put_object(key,path.read_bytes());return storage["public_base_url"].rstrip("/")+"/"+key
                    def invoke(kind,fields,files,target):
                        provider_id=fields.get("provider_id","local")
                        if provider_id!="local":
                            if files.get("reference_image") and not fields.get("image_url"): fields["image_url"]=public_url(files["reference_image"])
                            if files.get("reference_video") and not fields.get("video_url"): fields["video_url"]=public_url(files["reference_video"])
                        body,content_type=multipart_body(fields,files)
                        response=json.loads(request.urlopen(request.Request(base+f"/api/generate-{kind}",data=body,headers={"Content-Type":content_type}),timeout=120).read())
                        child=response["jobId"]; self.server.jobs.update(child,parent_job=job)
                        # Quality-first 768p H3 jobs on a 12 GB GPU can take well over an hour
                        # for a single five-second shot. Keep the HTTP workflow alive long
                        # enough for production renders instead of misclassifying them as hung.
                        deadline=time.monotonic()+14400
                        while True:
                            if job in self.server.cancelled_jobs: raise RuntimeError("任务已取消")
                            state=self.server.jobs.get(child)
                            if state and state.get("status")=="done": break
                            if state and state.get("status")=="error": raise RuntimeError(state.get("error") or "镜头生成失败")
                            if time.monotonic()>deadline: raise TimeoutError("镜头生成等待超过 4 小时")
                            time.sleep(1)
                        output=(state.get("outputs") or [None])[0]
                        if not output: raise RuntimeError("生成任务完成但没有输出")
                        href=str(output["href"]); source=href if href.startswith("http") else base+href
                        with request.urlopen(source,timeout=300) as remote: target.write_bytes(remote.read())
                        return target
                    def generate(shot, ctx):
                        target=task/f"shot_{int(shot['sequence']):02d}.mp4"
                        # A corrected retry may seed already completed shots into the new task.
                        # Reuse only material video files; downstream keyframe extraction still
                        # validates that the clip is readable before dependent shots run.
                        if target.is_file() and target.stat().st_size > 1024:
                            return target
                        files={};active_image=ctx.artifacts.get("active_reference_image");active_images=(ctx.artifacts.get("active_reference_images") or ([active_image] if active_image else []))[:9];active_asset_ids=(ctx.artifacts.get("active_reference_asset_ids") or [])[:len(active_images)];active_video=ctx.artifacts.get("active_reference_video")
                        if active_video: files["reference_video"]=active_video
                        elif active_images:
                            files["reference_image"]=active_images[0]
                            for index,path in enumerate(active_images[1:],start=2): files[f"reference_image_{index}"]=path
                        mode=str(shot.get("generation_plan",{}).get("mode") or "t2v");route="r2v" if mode=="r2v" else "i2v" if mode in {"i2v","image_then_i2v","previous_frame_i2v","reference_pack_i2v"} else "t2v"
                        shot_prompt=str(shot.get("generation_plan",{}).get("video_prompt") or shot.get("prompt") or ctx.brief)
                        if mode=="reference_pack_i2v":
                            mapping=[{"picture":f"Picture {index+1}","asset_id":active_asset_ids[index] if index<len(active_asset_ids) else "runtime_reference"} for index in range(len(active_images))]
                            plan=shot.setdefault("generation_plan",{});plan["reference_mapping"]=mapping
                            tags=" ".join(f"<Picture {index+1}> = <asset:{item['asset_id']}>." for index,item in enumerate(mapping))
                            shot_prompt=tags+" Generate a new shot from the written plan, do not treat either reference as a static poster. Absolutely no subtitles, captions, dialogue text, signs, logos, watermarks or any readable text in the image. "+shot_prompt
                        fields={"provider_id":str(agent_config.get(f"default_{route}_provider_id") or agent_config.get("default_video_provider_id") or "local"),"model":str(agent_config.get(f"default_{route}_model") or agent_config.get("default_video_model") or ""),"prompt":shot_prompt,"duration":str(shot.get("duration_seconds") or 5),"resolution":str(agent_config.get("default_video_resolution") or "768p"),"aspect":str(agent_config.get("default_video_aspect") or "16:9"),"steps":str(agent_config.get("default_video_steps") or "24"),"reference_count":str(len(active_images)),"reference_asset_ids":json.dumps(active_asset_ids,ensure_ascii=False),**({"workflow_mode":"reference_pack_i2v"} if mode=="reference_pack_i2v" else {})}
                        if active_image==ctx.reference_image and params.get("image_url"): fields["image_url"]=params["image_url"]
                        if active_video==ctx.reference_video and params.get("video_url"): fields["video_url"]=params["video_url"]
                        clip=invoke("video",fields,files,target)
                        audio=shot.get("audio") if isinstance(shot.get("audio"),dict) else {}
                        if str(audio.get("mode") or "").lower()=="no_dialogue":
                            effect_text=" ".join(str(audio.get(key) or "") for key in ("sound_effects","ambience"))
                            ensure_non_dialogue_audio(clip,effect_text)
                        return clip
                    def generate_image(spec,ctx):
                        fields={"provider_id":str(agent_config.get("default_image_provider_id") or "local"),"model":str(agent_config.get("default_image_model") or "flux"),"prompt":str(spec.get("prompt") or ctx.brief),"count":"1","aspect":"16:9","resolution":"2K"}
                        asset_id="".join(char for char in str(spec.get("id") or uuid.uuid4().hex) if char.isalnum() or char in "-_") or uuid.uuid4().hex
                        return invoke("image",fields,{},task/f"asset_{asset_id}.png")
                    def keyframes(clip,shot,ctx): return extract_boundary_frames(clip,task/"keyframes"/str(shot["id"]))
                    def persist_assets(assets,bible,ctx):
                        specs={str(item.get("id")):item for item in bible.get("assets",[]) if isinstance(item,dict) and item.get("id")}
                        for asset_id,asset_path in assets.items():
                            if not isinstance(asset_path,Path) or not asset_path.is_file(): continue
                            spec=specs.get(str(asset_id),{})
                            self.server.asset_library.add(asset_path,name=str(spec.get("name") or spec.get("identity") or spec.get("prompt") or asset_id)[:80],kind=str(spec.get("kind") or "reference"),description=spec,source_type="ai_video",source_id=job)
                    def confirm_assets(bible,ctx):
                        available=self.server.asset_library.list()
                        requirements=AIVideoWorkflow.asset_requirements(bible,available)
                        def normalized_name(value): return "".join(char.lower() for char in str(value or "") if char.isalnum())
                        selected_by_id={item["id"]:item for item in selected_assets};preselected={};unresolved=[]
                        for requirement in requirements:
                            matches=[item for item in selected_by_id.values() if item.get("kind")==requirement.get("kind") and normalized_name(item.get("name"))==normalized_name(requirement.get("name"))]
                            if matches:
                                asset=matches[0];preselected[str(requirement["entity_id"])]={"action":"reuse","asset_id":asset["id"],"name":asset.get("name")}
                            else: unresolved.append(requirement)
                        if not unresolved: return preselected
                        self.server.jobs.update(job,status="awaiting_asset_confirmation",message=f"故事板发现 {len(unresolved)} 个缺失资产，请确认后继续",progress=20,asset_requirements=unresolved,asset_preselected_decisions=preselected)
                        deadline=time.monotonic()+604800
                        while time.monotonic()<deadline:
                            if job in self.server.cancelled_jobs: raise RuntimeError("资产确认已取消")
                            state=self.server.jobs.get(job) or {}
                            decisions=state.get("asset_decisions")
                            if isinstance(decisions,dict):
                                self.server.jobs.update(job,status="running",message="正在按选择准备资产",asset_requirements=[])
                                return {**preselected,**decisions}
                            if state.get("status") in {"error","cancelled"}: raise RuntimeError("资产确认已取消")
                            time.sleep(1)
                        raise TimeoutError("等待资产确认超过 7 天")
                    prompts={"storyboard":agent_config.get("storyboard_system_prompt"),"review":agent_config.get("review_system_prompt")}
                    result=AIVideoWorkflow(llm,generate,changed,prompts,generate_image,keyframes,on_assets_prepared=persist_assets,resolve_library_asset=self.server.asset_library.use,confirm_assets=confirm_assets).run(context)
                    href=f"/artifacts/ai_video_jobs/{job}/{result['output'].name}"
                    self.server.jobs.update(job,status="done",message="AI 视频创作完成",progress=100,creative_intent=result["creative_intent"],continuity_bible=result["continuity_bible"],storyboard=result["storyboard"],review=result["review"],outputs=[{"type":"video","href":href}])
                except Exception as exc: self.server.jobs.update(job,status="error",message="AI 视频工作流失败",error=str(exc))
            threading.Thread(target=run,daemon=True).start(); self.send_json(202,{"ok":True,"jobId":job})
        except Exception as exc: self.send_json(400,{"error":str(exc)})
    def handle_generation(self,kind):
        try:
            form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); prompt=str(form.getvalue("prompt") or "").strip()
            if not prompt: raise ValueError("请输入提示词")
            job=self.server.jobs.create(); task=self.server.store_dir/"generation_jobs"/job; task.mkdir(parents=True,exist_ok=True)
            parent_job=str(form.getvalue("parent_job") or "").strip();repair_shot_id=str(form.getvalue("repair_shot_id") or "").strip()
            if parent_job:
                parent=self.server.jobs.get(parent_job)
                if not parent or parent.get("kind")!="ai_video": raise ValueError("局部修复的父 AI 视频任务不存在")
                self.server.jobs.update(job,parent_job=parent_job,repair_shot_id=repair_shot_id,kind="ai_video_repair")
            def save(field,default):
                item=form[field] if field in form else None
                if item is None or not getattr(item,"filename",""): return None
                path=task/(Path(item.filename).name or default); path.write_bytes(item.file.read()); return path
            image,image2,video=save("reference_image","reference.png"),save("reference_image_2","reference_2.png"),save("reference_video","reference.mp4")
            reference_images=[item for item in (image,image2) if item]
            for index in range(3,10):
                extra=save(f"reference_image_{index}",f"reference_{index}.png")
                if extra: reference_images.append(extra)
            selected_assets=selected_library_assets(form,self.server.asset_library);library_asset_ids=[item["id"] for item in selected_assets];library_asset_id=library_asset_ids[0] if library_asset_ids else "";uploaded_reference_count=len(reference_images)
            if len(reference_images)<9:
                for index,asset in enumerate(selected_assets[:9-len(reference_images)]):
                    source=self.server.asset_library.use(asset["id"])
                    if not source: continue
                    target=task/(f"library_reference_{len(reference_images)+1}"+source.suffix);shutil.copy2(source,target);reference_images.append(target)
            image=reference_images[0] if reference_images else None;image2=reference_images[1] if len(reference_images)>1 else None
            source_job=str(form.getvalue("retry_source_job") or "").strip()
            if source_job and not image and not video:
                source=self.server.jobs.get(source_job)
                source_dir=(self.server.store_dir/"generation_jobs"/source_job).resolve()
                try: source_dir.relative_to(self.server.store_dir.resolve())
                except ValueError: source=None
                if source:
                    for field,default in (("reference_image","reference.png"),("reference_video","reference.mp4")):
                        name=Path(str(source.get(field) or "")).name
                        source_path=source_dir/name if name else source_dir/default
                        if source_path.is_file():
                            target=task/default; shutil.copyfile(source_path,target)
                            if field=="reference_image": image=target
                            else: video=target
            params={k:str(form.getvalue(k) or "") for k in ("model","width","height","aspect","resolution","count","duration","frames","steps","negative","provider_id","image_url","video_url","reference_type","lora","lora_strength","seed","workflow_mode","library_asset_id")};params["library_asset_ids"]=library_asset_ids
            params["reference_image_2"]=image2.name if image2 else "";params["reference_count"]=len(reference_images);params["reference_asset_ids"]=library_asset_ids
            if kind == "video":
                # A fixed seed lets ComfyUI return a cached result for an otherwise identical task.
                params["seed"] = str(int(params.get("seed") or 0) or (uuid.uuid4().int % (2**63)))
            reference_mapping=[{"picture":f"Picture {uploaded_reference_count+index+1}","asset_id":asset["id"]} for index,asset in enumerate(selected_assets[:max(0,9-uploaded_reference_count)])]
            params["reference_mapping"]=reference_mapping
            provider_mapping="\n"+" ".join(f"<{item['picture']}> = <asset:{item['asset_id']}>." for item in reference_mapping) if reference_mapping else ""
            effective_prompt=prompt+provider_mapping+asset_prompt_context(selected_assets)
            self.server.jobs.update(job,kind=kind,prompt=prompt,reference_image=image.name if image else "",reference_video=video.name if video else "",provider_id=params["provider_id"] or "local",params=params)
            if image and not library_asset_id:
                try: self.server.asset_library.add(image,name=str(getattr(form["reference_image"],"filename","") or prompt or "用户参考图")[:80],kind=str(params.get("reference_type") or "reference"),description={"prompt":prompt,"role":"user_reference"},source_type="upload",source_id=job)
                except Exception: pass
            def run():
                try:
                    self.server.jobs.update(job,status="running",message="正在连接生成服务",progress=5)
                    provider_id = params["provider_id"] or "local"
                    model_name=params.get("model","").lower()
                    if provider_id == "local" and (model_name.startswith("image-") or model_name.startswith("doubao-seedream") or model_name.startswith("doubao-seedance")):
                        provider_name="minimax" if model_name.startswith("image-") else "seedance"; configured=self.server.providers.get_by_provider(provider_name)
                        if configured: provider_id=configured["id"]; params["provider_id"]=provider_id; self.server.jobs.update(job,provider_id=provider_id,params=params)
                    if provider_id != "local":
                        config = self.server.providers.get(provider_id)
                        if not config or config.get("enabled") is False: raise ValueError("云端 Provider 不存在或已停用")
                        api_key = config.get("api_key") or config.get("token")
                        if not api_key: raise ValueError("云端 Provider 尚未配置 API Key 或 Token")
                        if image and not params.get("image_url"): raise ValueError("云端参考图需要先配置可访问的 image_url")
                        if video and not params.get("video_url"): raise ValueError("云端参考视频需要先配置可访问的 video_url")
                        selected_model = params.get("model") or config.get("model", "")
                        if kind == "image":
                            if config.get("provider") == "minimax":
                                urls = MiniMaxImageProvider("https://api.minimaxi.com", api_key, 60).generate(effective_prompt, image_url=params.get("image_url"), model=selected_model, aspect=params.get("aspect", "1:1"), count=params.get("count", "1"))
                            elif config.get("provider") == "seedance":
                                urls = SeedreamImageProvider("https://ark.cn-beijing.volces.com/api/v3", api_key, 60).generate(effective_prompt, image=image, model=selected_model, aspect=params.get("aspect", "1:1"), resolution=params.get("resolution", "2K"))
                            else: raise ProviderError("当前 Provider 不支持生图")
                            outputs=[]
                            for index,url in enumerate(urls):
                                local=task/f"cloud_image_{index+1}."+((parse.urlsplit(url).path.rsplit('.',1)[-1].lower()) if '.' in parse.urlsplit(url).path.rsplit('/',1)[-1] else 'png')
                                if local.suffix not in {".jpg",".jpeg",".png",".webp"}: local=local.with_suffix(".png")
                                save_remote_asset(url,local); outputs.append({"type":"image","href":f"/artifacts/generation_jobs/{job}/{local.name}"})
                            self.server.jobs.update(job,status="done",message="生图完成",progress=100,outputs=outputs); return
                        cloud = MiniMaxVideoProvider("https://api.minimaxi.com", api_key, 60) if config.get("provider") == "minimax" else SeedanceProvider("https://ark.cn-beijing.volces.com/api/v3", api_key, selected_model, 60)
                        task_id = cloud.submit(effective_prompt, image=image, video=video, model=selected_model, image_url=params.get("image_url"), video_url=params.get("video_url"), resolution=params.get("resolution", "768P"), duration=params.get("duration", "5"), aspect=params.get("aspect", "16:9"), ratio=params.get("aspect", "16:9")); self.server.jobs.update(job,message="云端已接收任务",progress=15,provider_task_id=task_id); result=cloud.wait(task_id); remote=cloud.download_url(result)
                        if not remote: raise ValueError("云端任务完成但没有返回视频地址")
                        self.server.jobs.update(job,status="done",message="生成完成",progress=100,outputs=[{"type":"video","href":remote}]); return
                    comfy=ComfyUIClient(self.server.comfy_url)
                    if kind=="image":
                        model=params["model"] or "flux"
                        if model=="sd": raise ValueError("当前 ComfyUI 未安装 Stable Diffusion checkpoint，暂不能使用 sd")
                        if model=="qwen": raise ValueError("Qwen Image 请在模型列表中选择 qwen_image_fp8_e4m3fn.safetensors")
                        if model == "qwen_image_fp8_e4m3fn.safetensors" and not params["width"] and not params["height"]:
                            qwen_sizes={"1:1":(1328,1328),"16:9":(1664,928),"9:16":(928,1664),"4:3":(1472,1104),"3:4":(1104,1472),"3:2":(1584,1056),"2:3":(1056,1584)}
                            width,height=qwen_sizes.get(params["aspect"],(1328,1328))
                        else:
                            width=max(16,int(params["width"] or 1024)); height=max(16,int(params["height"] or 1024))
                        count=max(1,min(8,int(params["count"] or 1))); seed=uuid.uuid4().int % (2**31)
                        uploaded=comfy.upload(image) if image else None
                        if model == "qwen_image_fp8_e4m3fn.safetensors": graph=qwen_image(effective_prompt,width,height,count,seed,params.get("lora") or None,float(params.get("lora_strength") or 1),uploaded,params.get("reference_type") or "identity")
                        elif model == "flux1-krea-dev_fp8_scaled.safetensors":
                            uploaded=comfy.upload(image) if image else None; graph=flux_image(effective_prompt,params["negative"],width,height,count,seed,uploaded,model=model)
                        else: raise ValueError(f"当前本地生图工作流不支持模型 {model}")
                    else:
                        uploaded_images = [comfy.upload(path) for path in reference_images]
                        uploaded_image = uploaded_images[0] if uploaded_images else None
                        uploaded_image_2 = uploaded_images[1] if len(uploaded_images)>1 else None
                        uploaded_video = comfy.upload(video) if video else None
                        workflow_params = dict(params, prompt=effective_prompt, seed=int(params["seed"]))
                        workflow_kind = params.get("workflow_mode") or ("r2v" if video else "i2v" if image else "t2v")
                        graph = bind_media(video_workflow(workflow_kind, workflow_params), uploaded_image, uploaded_video, uploaded_image_2,uploaded_images)
                    graphs=[graph]
                    if kind=="image" and count>1:
                        graphs=[]
                        for index in range(count):
                            image_seed=(seed+index) % (2**31)
                            if model == "qwen_image_fp8_e4m3fn.safetensors":
                                graphs.append(qwen_image(effective_prompt,width,height,1,image_seed,params.get("lora") or None,float(params.get("lora_strength") or 1),uploaded,params.get("reference_type") or "identity"))
                            else:
                                graphs.append(flux_image(effective_prompt,params["negative"],width,height,1,image_seed,uploaded,model=model))
                    outputs=[]
                    for index,current_graph in enumerate(graphs):
                        comfy.validate_graph(current_graph); pid=comfy.queue(current_graph); self.server.jobs.update(job,message=f"ComfyUI 已接收第 {index+1}/{len(graphs)} 个任务",progress=10+round(index/len(graphs)*80),prompt_id=pid)
                        result=comfy.wait(pid,lambda p,m:self.server.jobs.update(job,progress=10+round((index+p/100)/len(graphs)*85),message=m))
                        for node in result.get("outputs",{}).values():
                            for key in ("images","gifs","videos"):
                                for item in node.get(key,[]) or []:
                                    filename = str(item.get("filename", "")).lower()
                                    is_video = key in ("gifs", "videos") or filename.endswith((".mp4", ".webm", ".mov", ".mkv"))
                                    outputs.append({"type":"video" if is_video else "image","href":"/api/comfy-view?"+parse.urlencode(item)})
                    if not outputs: raise ComfyUIError("ComfyUI 完成但没有返回可展示的输出")
                    self.server.jobs.update(job,status="done",message="生成完成",progress=100,outputs=outputs)
                except Exception as exc: self.server.jobs.update(job,status="error",message="生成失败",error=str(exc))
            threading.Thread(target=run,daemon=True).start(); self.send_json(202,{"ok":True,"jobId":job})
        except Exception as exc: self.send_json(400,{"error":str(exc)})

def main():
    p=argparse.ArgumentParser(); p.add_argument("--host",default="127.0.0.1"); p.add_argument("--port",type=int,default=8102); p.add_argument("--cache-dir",type=Path,default=Path("cache/video_creator")); p.add_argument("--store-dir",type=Path,default=service_store("video_creator")); a=p.parse_args(); a.cache_dir.mkdir(parents=True,exist_ok=True); server=http.server.ThreadingHTTPServer((a.host,a.port),Handler); a.store_dir.mkdir(parents=True,exist_ok=True); server.store_dir=a.store_dir.resolve(); os.environ["DOUYIN_STORE_DIR"]=str(server.store_dir.parent); server.jobs=Jobs(server.store_dir/"assets.db"); server.cancelled_jobs=set(); server.asset_library=ReferenceAssetStore(server.store_dir/"reference_library"); server.comfy_url=os.getenv("COMFYUI_URL","http://127.0.0.1:8188"); server.providers=ProviderConfigStore(server.store_dir/"provider_configs.json"); print(f"video creator listening=http://{a.host}:{a.port} comfy={server.comfy_url}",flush=True)
    recover_comfy_jobs(server)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=="__main__": main()
