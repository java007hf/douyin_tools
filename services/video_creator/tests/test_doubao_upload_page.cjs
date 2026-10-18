const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

test('fresh host from ApplyImageUpload is bridged instead of silently uploaded natively',async()=>{
  const listeners=[];const events=[];const nativeUploads=[];const pythonUploads=[];
  class XHR{}
  XHR.prototype.open=function(){};XHR.prototype.send=function(){};XHR.prototype.setRequestHeader=function(){};
  const window={XMLHttpRequest:XHR,addEventListener:(name,fn)=>listeners.push(fn)};
  const dispatch=data=>listeners.forEach(fn=>fn({source:window,origin:'https://www.doubao.com',data}));
  window.postMessage=data=>queueMicrotask(()=>{
    if(data.source==='doubao-bridge-page'){
      if(data.action==='event')events.push(data.payload);
      if(data.action==='upload')pythonUploads.push(data.payload);
      dispatch({source:'doubao-bridge-response',id:data.id,ok:true,value:{status:200,text:'{"code":2000}',content_type:'application/json'}});
    }
  });
  window.fetch=async input=>{
    const url=typeof input==='string'?input:input.url;
    if(url.includes('Action=ApplyImageUpload'))return new Response(JSON.stringify({Result:{UploadAddress:{UploadHosts:['tos-lq-x.bytedancevod.com']}}}));
    nativeUploads.push(url);return new Response('{}');
  };
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../chrome_extension/page.js'),'utf8'),{
    window,location:{href:'https://www.doubao.com/chat/create-image',origin:'https://www.doubao.com'},
    URL,Request,Response,Blob,ArrayBuffer,Uint8Array,crypto:webcrypto,btoa,setTimeout,clearTimeout
  });
  dispatch({source:'doubao-bridge-config-v3',enabled:true});
  const url='https://tos-lq-x.bytedancevod.com/upload/v1/tos-cn-i-a9rns2rl98/fixture.png';
  const earlyUpload=window.fetch(url,{method:'POST',body:new Blob(['early'])});
  await new Promise(resolve=>setTimeout(resolve,5));
  assert.equal(nativeUploads.length,0,'unknown node must pause instead of falling back');
  await window.fetch('https://www.doubao.com/top/v1?Action=ApplyImageUpload');
  await earlyUpload;
  await window.fetch(url,{method:'POST',body:new Blob(['after'])});
  assert.equal(nativeUploads.length,0,'new captured host must not bypass Python');
  assert.equal(pythonUploads.length,2);
  assert.equal(Buffer.from(pythonUploads[1].data,'base64').toString(),'after');
  assert.deepEqual(events.filter(x=>x.stage==='upload_route').map(x=>x.bridged),[true,true]);
});

test('XHR SDK upload inside ready-state callback waits for fresh host registration',async()=>{
  const listeners=[];const events=[];let registered=false;let nativeUploads=0;let pythonUploads=0;
  let resolveUpload,rejectUpload;
  const done=new Promise((resolve,reject)=>{resolveUpload=resolve;rejectUpload=reject});
  class ProgressEvent extends Event {constructor(type,options={}){super(type);Object.assign(this,options)}}
  class XHR {
    constructor(){this.handlers=[];this.readyState=0;this.responseType='';this.upload=new EventTarget()}
    addEventListener(name,fn,options={}){this.handlers.push({name,fn,capture:options.capture===true})}
    dispatchEvent(event){
      const handlers=this.handlers.filter(x=>x.name===event.type);
      // Adversarial SDK order: upload starts before ANY observer callback.
      this['on'+event.type]?.();
      handlers.filter(x=>x.capture).forEach(x=>x.fn());
      handlers.filter(x=>!x.capture).forEach(x=>x.fn());
      return true;
    }
    open(method,url){this.url=url;this.readyState=1}
    setRequestHeader(){}
    abort(){}
    send(){
      if(!this.url.includes('ApplyImageUpload')){nativeUploads++;return}
      this.responseText=JSON.stringify({Result:{UploadAddress:{UploadHosts:['tos-fresh-fixture.snssdk.com']}}});
      this.readyState=4;this.dispatchEvent(new Event('readystatechange'));this.dispatchEvent(new Event('load'));
    }
  }
  const window={XMLHttpRequest:XHR,addEventListener:(name,fn)=>listeners.push(fn),fetch:async()=>new Response('{}')};
  const dispatch=data=>listeners.forEach(fn=>fn({source:window,origin:'https://www.doubao.com',data}));
  window.postMessage=data=>{
    if(data.source!=='doubao-bridge-page')return;
    if(data.action==='event')events.push(data.payload);
    const reply=()=>dispatch({source:'doubao-bridge-response',id:data.id,ok:true,value:{status:200,text:'{"code":2000}',content_type:'application/json'}});
    if(data.payload.stage==='apply')setTimeout(()=>{registered=true;reply()},20);
    else if(data.action==='upload'){
      try{assert.equal(registered,true,'Python must register the new host before upload');pythonUploads++;queueMicrotask(reply)}catch(error){rejectUpload(error)}
    }else queueMicrotask(reply);
  };
  vm.runInNewContext(fs.readFileSync(require('node:path').join(__dirname,'../chrome_extension/page.js'),'utf8'),{
    window,location:{href:'https://www.doubao.com/chat/create-image',origin:'https://www.doubao.com'},
    URL,Request,Response,Blob,ArrayBuffer,Uint8Array,crypto:webcrypto,btoa,setTimeout,clearTimeout,Event,ProgressEvent,TextEncoder
  });
  dispatch({source:'doubao-bridge-config-v3',enabled:true});
  const apply=new XHR();apply.open('GET','https://www.doubao.com/top/v1?Action=ApplyImageUpload');
  apply.onreadystatechange=()=>{
    const upload=new XHR();upload.open('POST','https://tos-fresh-fixture.snssdk.com/upload/v1/tos-cn-i-a9rns2rl98/fresh.png');
    upload.addEventListener('load',resolveUpload);upload.addEventListener('error',()=>rejectUpload(Error('Unexpected upload error')));
    upload.send(new Blob(['new image']));
  };
  apply.send();
  await done;
  assert.equal(nativeUploads,0);
  assert.equal(pythonUploads,1);
  assert.equal(events.filter(x=>x.stage==='apply').length,1,'ready-state and load must not double-register');
});
