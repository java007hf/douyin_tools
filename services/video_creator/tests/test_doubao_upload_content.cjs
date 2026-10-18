const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');const path=require('node:path');const vm=require('node:vm');
const {webcrypto}=require('node:crypto');

test('image creation reference uploader is distinguished from single-image editor by multiple',async()=>{
  const listeners=[];const reports=[];let command;let complete;
  const done=new Promise(resolve=>complete=resolve);
  const window={addEventListener:(name,fn)=>listeners.push(fn),removeEventListener:(name,fn)=>{const i=listeners.indexOf(fn);if(i>=0)listeners.splice(i,1)}};
  window.postMessage=value=>{
    if(value.source==='doubao-bridge-config-v3')queueMicrotask(()=>listeners.slice().forEach(fn=>fn({source:window,origin:'https://www.doubao.com',data:{source:'doubao-bridge-configured',id:value.id}})));
  };
  const single={accept:'.jpg,.png,.jpeg,.webp,.apng,',multiple:false,disabled:false,getClientRects:()=>[],dispatchEvent:()=>assert.fail('single-image editor must not be selected')};
  const multi={...single,multiple:true,dispatchEvent:()=>reports.push('multi-selected')};
  class DataTransfer{constructor(){this.files=[];this.items={add:file=>this.files.push(file)}}}
  class File{constructor(parts,name,options){this.name=name}}
  const chrome={runtime:{onMessage:{addListener:fn=>command=fn,removeListener(){}},sendMessage:async value=>{
    if(value.action==='event'){reports.push(value.payload.stage);if(value.payload.stage==='reference_selected'||value.payload.stage==='bridge_error')complete()}
    return {ok:true};
  }}};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/content.js'),'utf8'),{
    window,document:{querySelectorAll:()=>[single,multi]},chrome,location:{origin:'https://www.doubao.com'},
    crypto:webcrypto,Uint8Array,DataTransfer,File,atob,Event,setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){}
  });
  command({action:'select_reference',image:{data:'aGVsbG8=',name:'reference.png',mime:'image/png'}},{},()=>{});
  await done;
  assert.equal(multi.files[0].name,'reference.png');
  assert.deepEqual(reports,['bridge_ready','multi-selected','reference_selected']);
});
