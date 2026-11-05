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
  assert.match(multi.files[0].name,/^doubao-bridge-.*-reference\.png$/);
  assert.deepEqual(reports,['bridge_ready','multi-selected','reference_selected']);
});

test('new batch clears only bridge-owned draft attachments before choosing the image',async()=>{
  const listeners=[];let command;let finish;let selected;
  const done=new Promise(resolve=>finish=resolve);
  const cards=['doubao-bridge-one.png','doubao-bridge-two.png','asset_user-photo.png'].map(name=>({
    name,isConnected:true,getAttribute:()=>name,
    querySelector(){return {dispatchEvent:()=>{this.isConnected=false}}}
  }));
  const input={accept:'image/png',multiple:true,disabled:false,getClientRects:()=>[],dispatchEvent(){}};
  const window={addEventListener:(n,fn)=>listeners.push(fn),removeEventListener:(n,fn)=>{const i=listeners.indexOf(fn);if(i>=0)listeners.splice(i,1)}};
  window.postMessage=value=>{if(value.source==='doubao-bridge-config-v3')queueMicrotask(()=>listeners.slice().forEach(fn=>fn({source:window,origin:'https://www.doubao.com',data:{source:'doubao-bridge-configured',id:value.id}})))};
  const chrome={runtime:{onMessage:{addListener:fn=>command=fn,removeListener(){}},sendMessage:async value=>{
    if(value.payload?.stage==='reference_selected'){selected=value.payload;finish()}
    if(value.payload?.stage==='bridge_error')throw Error(value.payload.reason);
    return {ok:true};
  }}};
  class DataTransfer{constructor(){this.files=[];this.items={add:file=>this.files.push(file)}}}
  class File{constructor(parts,name){this.name=name}}
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/content.js'),'utf8'),{
    window,document:{querySelectorAll:selector=>selector.startsWith('.guidance-input')?cards.filter(x=>x.isConnected):[input]},
    chrome,location:{origin:'https://www.doubao.com'},crypto:webcrypto,Uint8Array,DataTransfer,File,atob,Event,MouseEvent:Event,
    setTimeout,clearTimeout,setInterval:()=>1,clearInterval(){}
  });
  command({action:'select_reference',image:{data:'aGVsbG8=',name:'new.png',mime:'image/png',reset_before_upload:true}},{},()=>{});
  await done;
  assert.equal(selected.ui.cleared,2);
  assert.equal(cards[2].isConnected,true,'user photo must remain in the draft');
  assert.match(input.files[0].name,/^doubao-bridge-.*-new\.png$/);
});
