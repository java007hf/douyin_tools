(() => {
  if(window.__doubaoUploadPageRevision==='registered-upload-v3')return;
  // Upgrade a reused tab without re-enabling its older transport hooks.
  if(window.__doubaoUploadPageInstalled)window.postMessage({source:'doubao-bridge-config',enabled:false},location.origin);
  window.postMessage({source:'doubao-bridge-config-v2',enabled:false},location.origin);
  window.__doubaoUploadPageInstalled=true;
  window.__doubaoUploadPageRevision='registered-upload-v3';
  let enabled=false;
  const uploadHosts=new Set(['tos-d-ct-lf.snssdk.com','tos-hl-x.snssdk.com']);
  const registrations=new Set();
  const pending=new Map();const originalFetch=window.fetch;const XHR=window.XMLHttpRequest;
  const candidate=url=>{try{const u=new URL(url,location.href);return u.protocol==='https:'&&u.pathname.startsWith('/upload/v1/tos-cn-i-a9rns2rl98/')}catch{return false}};
  const allowed=url=>candidate(url)&&uploadHosts.has(new URL(url,location.href).hostname);
  async function authorize(url){
    const deadline=Date.now()+15000;
    while(!allowed(url)){
      if(Date.now()>deadline)throw Error('Upload destination was not registered; native fallback refused');
      await new Promise(resolve=>setTimeout(resolve,20));
    }
    await Promise.all([...registrations]);
  }
  async function route(url,transport,bridged){
    if(candidate(url))await call('event',{stage:'upload_route',host:new URL(url).hostname,transport,bridged});
  }
  function call(action,payload){
    const id=crypto.randomUUID();
    return new Promise((resolve,reject)=>{
      const timeout=setTimeout(()=>{pending.delete(id);reject(Error('Python upload bridge timeout; not retried'))},110000);
      pending.set(id,{resolve,reject,timeout});
      window.postMessage({source:'doubao-bridge-page',id,action,payload},location.origin);
    });
  }
  window.addEventListener('message',event=>{
    if(event.source!==window||event.origin!==location.origin)return;
    const value=event.data;
    if(value?.source==='doubao-bridge-config-v3'){
      enabled=value.enabled===true;
      window.postMessage({source:'doubao-bridge-configured',id:value.id},location.origin);
      return;
    }
    if(value?.source!=='doubao-bridge-response')return;
    const item=pending.get(value.id);if(!item)return;
    clearTimeout(item.timeout);pending.delete(value.id);
    if(value.ok)item.resolve(value.value);else item.reject(Error('Python upload bridge unavailable; not retried'));
  });
  async function observe(url,text){
    const parsed=new URL(url,location.href);
    if(parsed.origin!==location.origin||parsed.pathname!=='/top/v1')return;
    const action=parsed.searchParams.get('Action');if(!['ApplyImageUpload','CommitImageUpload'].includes(action))return;
    const value=JSON.parse(text);const result=value.Result;
    if(action==='ApplyImageUpload'){
      const observed_hosts=[...(result?.UploadAddress?.UploadHosts||[]),...(result?.InnerUploadAddress?.UploadNodes||[]).map(x=>x.UploadHost)]
        .map(host=>{try{return new URL(host.includes('://')?host:'https://'+host).hostname}catch{return ''}});
      const hosts=observed_hosts.filter(host=>['snssdk.com','doubao.com','byteimg.com','bytedance.com','bytedancevod.com'].some(domain=>host.endsWith('.'+domain)));
      hosts.forEach(host=>uploadHosts.add(host));
      const registration=call('event',{stage:'apply',ok:!!result?.UploadAddress,hosts,observed_hosts});
      registrations.add(registration);
      try{await registration}finally{registrations.delete(registration)}
    }
    else await call('event',{stage:'commit',ok:!!result?.Results?.length,
      uris:(result?.Results||[]).filter(x=>x.UriStatus===2000||x.UriStatus===0).map(x=>x.Uri)});
  }
  async function transfer(url,headers,body){
    // The SDK can start the storage XHR inside its Apply ready-state callback.
    // Do not send bytes until Python has received the new destination registration.
    await Promise.all([...registrations]);
    let bytes;
    if(body instanceof Blob)bytes=new Uint8Array(await body.arrayBuffer());
    else if(body instanceof ArrayBuffer)bytes=new Uint8Array(body);
    else if(ArrayBuffer.isView(body))bytes=new Uint8Array(body.buffer,body.byteOffset,body.byteLength);
    else throw Error('Unverified upload body format; not retried');
    if(!bytes.length||bytes.length>20*1024*1024)throw Error('Upload image exceeds bridge limit');
    let binary='';for(let offset=0;offset<bytes.length;offset+=32768)binary+=String.fromCharCode(...bytes.subarray(offset,offset+32768));
    return call('upload',{url,headers,data:btoa(binary)});
  }
  window.fetch=async function(input,init){
    if(!enabled)return originalFetch.apply(this,arguments);
    const request=new Request(input,init);
    if(request.method==='POST'&&candidate(request.url)){
      await authorize(request.url);
      await route(request.url,'fetch',true);
      const result=await transfer(request.url,Object.fromEntries(request.headers),await request.arrayBuffer());
      return new Response(result.status===204?null:result.text,{status:result.status,headers:{'Content-Type':result.content_type}});
    }
    if(request.method==='POST')await route(request.url,'fetch',false);
    const response=await originalFetch.apply(this,arguments);
    const parsed=new URL(request.url);
    if(parsed.origin===location.origin&&parsed.pathname==='/top/v1'){
      try{await observe(request.url,await response.clone().text())}catch{}
    }
    return response;
  };
  // The browser upload SDK can use XHR instead of fetch. Keep its API object and
  // listeners, replace only a verified storage POST's transport.
  const open=XHR.prototype.open,send=XHR.prototype.send,setHeader=XHR.prototype.setRequestHeader;
  const states=new WeakMap();
  XHR.prototype.open=function(method,url,...rest){states.set(this,{method:String(method).toUpperCase(),url:new URL(url,location.href).href,headers:{}});return open.call(this,method,url,...rest)};
  XHR.prototype.setRequestHeader=function(key,value){const state=states.get(this);if(state)state.headers[key]=value;return setHeader.call(this,key,value)};
  XHR.prototype.send=function(body){
    const state=states.get(this);
    if(!enabled||!state)return send.call(this,body);
    if(state.method!=='POST'||!candidate(state.url)){
      if(state.method==='POST')route(state.url,'xhr',false).catch(()=>{});
      let observed=false;
      const completed=()=>{
        if(this.readyState!==4||observed)return;
        observed=true;
        if(!this.responseType||this.responseType==='text')observe(state.url,this.responseText).catch(()=>{});
        else if(this.responseType==='json')observe(state.url,JSON.stringify(this.response)).catch(()=>{});
      };
      // Capture runs before the SDK's ordinary ready-state callback. Updating the
      // in-page host set is synchronous; Python registration is awaited in transfer.
      this.addEventListener('readystatechange',completed,{capture:true});
      this.addEventListener('load',completed,{once:true,capture:true});
      return send.call(this,body);
    }
    let cancelled=false;
    const abort=this.abort.bind(this);
    this.abort=()=>{cancelled=true;abort()};
    authorize(state.url).then(()=>route(state.url,'xhr',true)).then(()=>transfer(state.url,state.headers,body)).then(result=>{
      if(cancelled)return;
      const type=this.responseType;
      const response=type==='json'?JSON.parse(result.text):type==='arraybuffer'?new TextEncoder().encode(result.text).buffer:type==='blob'?new Blob([result.text],{type:result.content_type}):result.text;
      for(const [key,value] of Object.entries({status:result.status,statusText:result.status===200?'OK':'',readyState:4,responseURL:state.url,response,...(!type||type==='text'?{responseText:result.text}:{})}))Object.defineProperty(this,key,{configurable:true,get:()=>value});
      this.getResponseHeader=name=>name.toLowerCase()==='content-type'?result.content_type:null;
      this.getAllResponseHeaders=()=>`content-type: ${result.content_type}\r\n`;
      this.upload.dispatchEvent(new ProgressEvent('progress',{lengthComputable:true,loaded:body.size||body.byteLength,total:body.size||body.byteLength}));
      this.upload.dispatchEvent(new ProgressEvent('load'));this.upload.dispatchEvent(new ProgressEvent('loadend'));
      this.dispatchEvent(new Event('readystatechange'));this.dispatchEvent(new ProgressEvent('load'));this.dispatchEvent(new ProgressEvent('loadend'));
    }).catch(()=>{
      if(cancelled)return;
      call('event',{stage:'bridge_error',ok:false}).catch(()=>{});
      this.dispatchEvent(new ProgressEvent('error'));this.dispatchEvent(new ProgressEvent('loadend'));
    });
  };
})();
