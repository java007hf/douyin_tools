const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

(async () => {
  let tabs = [];
  const created = [], reloaded = [], commands = [];
  const listener = {addListener() {}};
  const context = vm.createContext({console, setInterval(){}, setTimeout,
    chrome:{runtime:{getManifest:()=>({version:'test'}),onInstalled:listener,onStartup:listener,onMessage:listener},
      alarms:{create(){},onAlarm:listener}, tabs:{query:async()=>tabs,
        create:async options=>{created.push(options);const tab={id:1,status:'complete'};tabs=[tab];return tab;},
        get:async()=>({id:1,status:'complete'}),reload:async id=>reloaded.push(id)}},
    prepare:async(_tab,command)=>{commands.push(command);return {ok:true,data:{account_ready:true,notice_ready:true}};}});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/background.js'),'utf8'),context);
  vm.runInContext('sendToContent = prepare;',context);
  await vm.runInContext("ensureMentionTab({id:'1',action:'collectMentions'})",context);
  assert.equal(created.length,1);assert.equal(created[0].active,false);
  assert.ok(created[0].url.includes('/user/self'));
  assert.equal(commands[0].action,'prepareMentionCapture');
  await vm.runInContext("ensureMentionTab({id:'2',action:'collectMentions'})",context);
  assert.equal(created.length,1); // Reuse the tab.
  vm.runInContext('mentionNeedsCapture.add(1);',context);
  await vm.runInContext("ensureMentionTab({id:'3',action:'collectMentions'})",context);
  await vm.runInContext("ensureMentionTab({id:'4',action:'collectMentions'})",context);
  assert.equal(reloaded.length,1); // Bounded refresh rather than reloading every poll.
  tabs=[];
  await assert.rejects(vm.runInContext("ensureMentionTab({id:'5',action:'replyMention'})",context),/关闭/);
  assert.equal(created.length,1); // Never reopen a page to retry a reply.
  assert.ok(commands.every(c=>c.action==='prepareMentionCapture'));
  // UI is used only to trigger the real list request, not to read notification IDs/text.
  let opened=false, dropdown=false, captured=false, pageHandler, pageResult;
  function element(text,onClick) {return {textContent:text,getAttribute:()=>null,
    getBoundingClientRect:()=>({width:80,height:30}),querySelectorAll:()=>[],closest:()=>null,
    dispatchEvent(){},click:onClick};}
  const notify=element('通知',()=>{opened=true;});
  const title=element('互动消息',()=>{});
  const all=element('全部消息',()=>{dropdown=true;});
  const at=element('@我的',()=>{captured=true;});
  const pageWindow={__douyinToolsExtensionVersion:'test',fetch:async()=>{},
    __douyinMentionRequests:{captureState:()=>({account_ready:true,notice_ready:captured})},
    addEventListener:(_name,fn)=>{pageHandler=fn;},postMessage:value=>{pageResult=value;}};
  function XHR(){}
  XHR.prototype.open=function(){};XHR.prototype.send=function(){};
  const page=vm.createContext({window:pageWindow,document:{querySelectorAll:()=>[
    notify,...opened?[title,all]:[],...dropdown?[at]:[]]},XMLHttpRequest:XHR,
    MouseEvent:function(){},getComputedStyle:()=>({display:'block',visibility:'visible'}),
    setTimeout:fn=>fn(),console});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/injected.js'),'utf8'),page);
  await pageHandler({source:pageWindow,data:{source:'douyin-tools-content-v3',id:'prepare',action:'prepareMentionCapture'}});
  assert.equal(pageResult.ok,true);assert.equal(pageResult.data.notice_ready,true);
  assert.equal(opened,true);assert.equal(dropdown,true);
  console.log('Automatic startup checks passed: create/reuse tab, prepare capture, bounded recovery, no publish retry');
})().catch(error=>{console.error(error);process.exitCode=1;});
