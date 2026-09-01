#!/usr/bin/env python3
"""Video creator tab service: frame extraction and ComfyUI generation."""
from __future__ import annotations
import argparse, cgi, http.server, json, mimetypes, os, sqlite3, sys, threading, uuid, zipfile
from pathlib import Path
from urllib import parse, request
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.video_creator.tools.ai.comfyui_client import ComfyUIClient, ComfyUIError
from services.video_creator.tools.ai.config_store import ProviderConfigStore
from services.video_creator.tools.ai.providers import MiniMaxImageProvider, MiniMaxVideoProvider, ProviderError, SeedreamImageProvider, SeedanceProvider
from services.video_creator.tools.video.extract_frames import extract_frames
from services.video_creator.workflow.generation import bind_media, flux_image, qwen_image, video_workflow
try: import oss2
except ImportError: oss2=None


def model_catalog(comfy_url: str) -> dict[str, list[str]]:
    models = {
        "minimax_image": ["image-01", "image-01-live"],
        "minimax_video": ["MiniMax-H3", "MiniMax-H3-Max"],
        "seedance_image": ["doubao-seedream-5-0-pro-260628", "doubao-seedream-5-0-260128", "doubao-seedream-5-0-lite-260128", "doubao-seedream-4-5-251128", "doubao-seedream-4-0-250828"],
        "seedance_video": ["doubao-seedance-2-0-pro", "doubao-seedance-2-0-fast", "doubao-seedance-2-0-mini", "doubao-seedance-1-5-pro-251215", "doubao-seedance-1-0-pro-250528"],
        "comfy": [],
    }
    try:
        info = json.loads(request.urlopen(comfy_url + "/object_info", timeout=10).read())
        for node in ("UNETLoader", "CheckpointLoaderSimple", "CLIPLoader"):
            required = info.get(node, {}).get("input", {}).get("required", {})
            for field in ("unet_name", "ckpt_name", "clip_name"):
                values = required.get(field, [[]])[0]
                if isinstance(values, list):
                    models["comfy"].extend(str(value) for value in values)
    except Exception:
        pass
    models["comfy"] = list(dict.fromkeys(models["comfy"]))
    models["comfy"] = [value for value in models["comfy"] if not any(token in value.lower() for token in ("minimax_h3", "qwen3vl", "qwen_2.5_vl", "video", "audio", "vae", "clip", "t5xxl"))]
    return models

def cloudinary_config() -> dict[str, str | bool]:
    values={"cloud_name":os.getenv("CLOUDINARY_CLOUD_NAME",""),"upload_preset":os.getenv("CLOUDINARY_UPLOAD_PRESET","")}
    path=Path("cache/video_creator/cloudinary.json")
    try:
        values.update(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError): pass
    try:
        storage=json.loads(Path("cache/video_creator/storage.json").read_text(encoding="utf-8"))
        if storage.get("provider")=="cloudinary": values.update({k:storage.get(k,"") for k in ("cloud_name","upload_preset")})
    except (OSError, json.JSONDecodeError): pass
    values["enabled"]=bool(values.get("cloud_name") and values.get("upload_preset")); return values

def storage_config() -> dict[str, str | bool]:
    path=Path("cache/video_creator/storage.json"); values={}
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
    def __init__(self, path: Path = Path("cache/video_creator/assets.db")):
        self.path, self.lock = path, threading.Lock(); self.path.parent.mkdir(parents=True, exist_ok=True)
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

class Handler(http.server.BaseHTTPRequestHandler):
    server_version="VideoCreator/0.3"
    def log_message(self,*_): return
    def send_json(self,status,payload):
        body=json.dumps(payload,ensure_ascii=False).encode(); self.send_response(status); self.send_header("content-type","application/json; charset=utf-8"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        path=parse.urlsplit(self.path).path
        if path in ("/","/index.html"):
            body=HTML.replace("</body>",'<script src="/assets/frame_preview.js"></script><script src="/assets/generation.js"></script></body>').encode(); self.send_response(200); self.send_header("content-type","text/html; charset=utf-8"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path in ("/assets/frame_preview.js","/assets/generation.js"):
            body=Path(__file__).with_name(path.rsplit("/",1)[-1]).read_bytes(); self.send_response(200); self.send_header("content-type","text/javascript; charset=utf-8"); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path=="/health": self.send_json(200,{"ok":True,"service":"video-creator"}); return
        if path=="/api/providers": self.send_json(200,{"providers":self.server.providers.list_public()}); return
        if path=="/api/cloudinary-config": self.send_json(200,cloudinary_config()); return
        if path=="/api/storage-config": self.send_json(200,storage_config()); return
        if path=="/api/models": self.send_json(200,model_catalog(self.server.comfy_url)); return
        if path=="/api/assets": self.send_json(200,{"assets":self.server.jobs.list()}); return
        if path.startswith("/api/jobs/") or path.startswith("/api/generation-jobs/"):
            job=self.server.jobs.get(path.rsplit("/",1)[-1]); self.send_json(200 if job else 404,job or {"error":"任务不存在"}); return
        if path=="/api/comfy-view":
            try:
                query=parse.urlsplit(self.path).query; response=request.urlopen(f"{self.server.comfy_url}/view?{query}",timeout=60); body=response.read(); self.send_response(200); self.send_header("content-type",response.headers.get("content-type","application/octet-stream")); self.send_header("content-length",str(len(body))); self.end_headers(); self.wfile.write(body)
            except Exception as exc: self.send_json(502,{"error":str(exc)})
            return
        if path.startswith("/artifacts/"):
            target=(self.server.cache_dir/parse.unquote(path[len("/artifacts/"):])).resolve()
            try: target.relative_to(self.server.cache_dir.resolve())
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
        if not path.startswith("/api/generation-jobs/"):
            self.send_json(404,{"error":"Not found"}); return
        job_id=path.rsplit("/",1)[-1]
        if not self.server.jobs.delete(job_id): self.send_json(404,{"error":"Generation asset not found"}); return
        self.send_json(200,{"ok":True})
    def do_POST(self):
        path=parse.urlsplit(self.path).path
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
        if path in ("/api/generate-image","/api/generate-video"): self.handle_generation(path.rsplit("/",1)[-1].replace("generate-","")); return
        if path!="/api/extract-frames": self.send_json(404,{"error":"Not found"}); return
        try:
            form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); upload=form["video"] if "video" in form else None
            if upload is None or not getattr(upload,"filename",""): raise ValueError("请上传视频文件")
            mode,value,fmt=str(form.getvalue("mode") or "interval"),float(form.getvalue("value") or 0),str(form.getvalue("format") or "jpg")
            if mode not in {"interval","count"} or value<=0: raise ValueError("抽帧参数无效")
            job=self.server.jobs.create(); task=self.server.cache_dir/"frame_jobs"/job; task.mkdir(parents=True,exist_ok=True); source=task/(Path(upload.filename).name or "input.mp4"); source.write_bytes(upload.file.read())
            def run():
                try:
                    self.server.jobs.update(job,status="running",message="正在读取视频"); result=extract_frames(source,task/"frames",interval_seconds=value if mode=="interval" else None,frame_count=int(value) if mode=="count" else None,image_format=fmt,progress_callback=lambda msg,cur,total:self.server.jobs.update(job,message=msg,progress=round(cur/total*100))); archive=task/"frames.zip"
                    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
                        for item in result["files"]: z.write(item["path"],item["name"])
                    files=[{"name":x["name"],"timestamp":x["timestamp"],"href":f"/artifacts/frame_jobs/{job}/frames/{x['name']}"} for x in result["files"]]; self.server.jobs.update(job,status="done",message="抽帧完成",result={"files":files,"duration":result["duration"],"fps":result["fps"],"zip":f"/artifacts/frame_jobs/{job}/frames.zip"})
                except Exception as exc: self.server.jobs.update(job,status="error",message="抽帧失败",error=str(exc))
            threading.Thread(target=run,daemon=True).start(); self.send_json(202,{"ok":True,"jobId":job})
        except Exception as exc: self.send_json(400,{"error":str(exc)})
    def handle_generation(self,kind):
        try:
            form=cgi.FieldStorage(fp=self.rfile,headers=self.headers,environ={"REQUEST_METHOD":"POST","CONTENT_TYPE":self.headers.get("content-type","")}); prompt=str(form.getvalue("prompt") or "").strip()
            if not prompt: raise ValueError("请输入提示词")
            job=self.server.jobs.create(); task=self.server.cache_dir/"generation_jobs"/job; task.mkdir(parents=True,exist_ok=True)
            def save(field,default):
                item=form[field] if field in form else None
                if item is None or not getattr(item,"filename",""): return None
                path=task/(Path(item.filename).name or default); path.write_bytes(item.file.read()); return path
            image,video=save("reference_image","reference.png"),save("reference_video","reference.mp4"); params={k:str(form.getvalue(k) or "") for k in ("model","width","height","aspect","resolution","count","frames","negative","provider_id","image_url","video_url")}; self.server.jobs.update(job,kind=kind,prompt=prompt,reference_image=image.name if image else "",reference_video=video.name if video else "",provider_id=params["provider_id"] or "local",params=params)
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
                                urls = MiniMaxImageProvider("https://api.minimaxi.com", api_key, 60).generate(prompt, image_url=params.get("image_url"), model=selected_model, aspect=params.get("aspect", "1:1"), count=params.get("count", "1"))
                            elif config.get("provider") == "seedance":
                                urls = SeedreamImageProvider("https://ark.cn-beijing.volces.com/api/v3", api_key, 60).generate(prompt, image=image, model=selected_model, aspect=params.get("aspect", "1:1"), resolution=params.get("resolution", "2K"))
                            else: raise ProviderError("当前 Provider 不支持生图")
                            self.server.jobs.update(job,status="done",message="生图完成",progress=100,outputs=[{"type":"image","href":url} for url in urls]); return
                        cloud = MiniMaxVideoProvider("https://api.minimaxi.com", api_key, 60) if config.get("provider") == "minimax" else SeedanceProvider("https://ark.cn-beijing.volces.com/api/v3", api_key, selected_model, 60)
                        task_id = cloud.submit(prompt, image=image, video=video, model=selected_model, image_url=params.get("image_url"), video_url=params.get("video_url"), resolution=params.get("resolution", "768P")); self.server.jobs.update(job,message="云端已接收任务",progress=15,provider_task_id=task_id); result=cloud.wait(task_id); remote=cloud.download_url(result)
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
                        if model == "qwen_image_fp8_e4m3fn.safetensors": graph=qwen_image(prompt,width,height,count,seed)
                        elif model == "flux1-krea-dev_fp8_scaled.safetensors":
                            uploaded=comfy.upload(image) if image else None; graph=flux_image(prompt,params["negative"],width,height,count,seed,uploaded,model=model)
                        else: raise ValueError(f"当前本地生图工作流不支持模型 {model}")
                    else:
                        uploaded_image = comfy.upload(image) if image else None
                        uploaded_video = comfy.upload(video) if video else None
                        workflow_params = dict(params, prompt=prompt, seed=0)
                        graph = bind_media(video_workflow("r2v" if video else "i2v" if image else "t2v", workflow_params), uploaded_image, uploaded_video)
                    comfy.validate_graph(graph); pid=comfy.queue(graph); self.server.jobs.update(job,message="ComfyUI 已接收任务",progress=10,prompt_id=pid); result=comfy.wait(pid,lambda p,m:self.server.jobs.update(job,progress=p,message=m)); outputs=[]
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
    p=argparse.ArgumentParser(); p.add_argument("--host",default="127.0.0.1"); p.add_argument("--port",type=int,default=8102); p.add_argument("--cache-dir",type=Path,default=Path("cache/video_creator")); a=p.parse_args(); a.cache_dir.mkdir(parents=True,exist_ok=True); server=http.server.ThreadingHTTPServer((a.host,a.port),Handler); server.jobs=Jobs(); server.cache_dir=a.cache_dir.resolve(); server.comfy_url=os.getenv("COMFYUI_URL","http://127.0.0.1:8188"); server.providers=ProviderConfigStore(server.cache_dir/"provider_configs.json"); print(f"video creator listening=http://{a.host}:{a.port} comfy={server.comfy_url}",flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
if __name__=="__main__": main()
