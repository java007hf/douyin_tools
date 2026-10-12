const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function harness() {
  const requests = [];
  const state = {notice:{status_code:0,at_list:[{comment:{cid:'101',aweme_id:'456'}}]},
    uid:'123',accountStatus:200,noticeStatus:200};
  function response(payload,status=200) {
    const raw = typeof payload === 'string' ? payload : JSON.stringify(payload);
    return {status,ok:status>=200&&status<300,text:async()=>raw,json:async()=>JSON.parse(raw),clone:()=>response(raw,status)};
  }
  function FakeXHR() {this.listeners={};this.status=200;}
  FakeXHR.prototype.open=function(method,url){this.method=method;this.url=url;this.headers={};};
  FakeXHR.prototype.setRequestHeader=function(name,value){this.headers[name.toLowerCase()]=value;};
  FakeXHR.prototype.addEventListener=function(name,fn){(this.listeners[name] ||= []).push(fn);};
  FakeXHR.prototype.send=function(body){
    requests.push({url:this.url,options:{method:this.method,headers:this.headers,body,transport:'xhr'}});
    this.responseText=JSON.stringify(state.notice);for(const fn of this.listeners.load||[])fn();
  };
  const window = {fetch:async(input,options={})=>{
    const url=typeof input==='string'?input:input.url;
    requests.push({url,options});
    const account=url.includes('/self/');
    return response(account?{status_code:0,user:{uid:state.uid}}:state.notice,
      account?state.accountStatus:state.noticeStatus);
  }};
  const context=vm.createContext({window,location:{href:'https://www.douyin.com/user/self'},
    URL,URLSearchParams,Headers,Request,AbortController,setTimeout,clearTimeout,XMLHttpRequest:FakeXHR});
  vm.runInContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/mention_requests.js'),'utf8'),context);
  const flush=()=>new Promise(resolve=>setImmediate(resolve));
  async function account(){await window.fetch('/aweme/v1/web/user/profile/self/');await flush();}
  async function notice(options){await window.fetch('/aweme/v1/web/notice/multi/?cursor=0&msToken=secret-token',options);await flush();}
  return {window,requests,state,context,flush,account,notice,collect:()=>window.__douyinMentionRequests.collect()};
}

(async()=>{
  // Capture initial traffic without a DOM bridge; credentials must not appear in diagnostics.
  let h=harness();await h.account();await h.notice();
  let snapshot=await h.collect();
  assert.equal(snapshot.fresh,true);assert.equal(snapshot.items[0].source,'request');
  assert.ok(!JSON.stringify(snapshot).includes('secret-token'));

  h=harness();await h.account();
  h.state.notice={status_code:0,notice_list:[],notice_list_v2:[{type:45,nid_str:'900',aweme_id:'456',create_time:100,
    at:{user_info:{nickname:'Jessica薛老师英语'},content:'@测试',
      schema_url:'snssdk1128://aweme/detail/456?comment_id=101',level1_comment:{},reply_comment:{}}}]};
  await h.notice();snapshot=await h.collect();
  assert.equal(snapshot.fresh,true);assert.equal(snapshot.items[0].author,'Jessica薛老师英语');
  assert.equal(snapshot.items[0].comment_id,'101');assert.equal(snapshot.items[0].parent_id,'');
  h.state.notice.notice_list_v2[0].at.reply_comment={cid:'102',text:'@测试'};
  h.state.notice.notice_list_v2[0].at.level1_comment={cid:'101'};
  await h.notice();snapshot=await h.collect();
  assert.equal(snapshot.items.find(i=>i.comment_id==='102').parent_id,'101');

  // The initial notice response can arrive before the account response.
  h=harness();await h.notice();await h.account();snapshot=await h.collect();
  assert.equal(snapshot.fresh,true);assert.equal(snapshot.items[0].comment_id,'101');

  // Preserve Request-object headers/body and read POSTs only after recognizing a list response.
  h=harness();await h.account();
  const input=new Request('https://www.douyin.com/aweme/v1/web/notice/multi/',{
    method:'POST',headers:{'Content-Type':'application/json','X-Read-Token':'private-secret'},
    body:JSON.stringify({notice_type:'at',cursor:0})});
  await h.window.fetch(input);await h.flush();snapshot=await h.collect();
  assert.equal(h.requests.at(-1).options.method,'POST');
  assert.equal(h.requests.at(-1).options.headers['x-read-token'],'private-secret');
  assert.equal(h.requests.at(-1).options.body,await input.clone().text());
  assert.ok(!JSON.stringify(snapshot).includes('private-secret'));

  // XHR headers/body and original transport survive replay (including page XHR middleware).
  h=harness();await h.account();
  const xhr=new h.context.XMLHttpRequest();xhr.open('POST','/aweme/v1/web/notice/multi/');
  xhr.setRequestHeader('Content-Type','application/x-www-form-urlencoded');xhr.send('notice_type=at&cursor=0');
  await h.collect();
  assert.equal(h.requests.at(-1).options.body,'notice_type=at&cursor=0');
  assert.equal(h.requests.at(-1).options.transport,'xhr');
  assert.equal(h.requests.at(-1).options.headers['content-type'],'application/x-www-form-urlencoded');

  // Numeric 64-bit IDs stay exact; quoted text remains unchanged.
  h=harness();await h.account();
  h.state.notice='{"status_code":0,"at_list":[{"comment":{"cid":7654321098765432101,"aweme_id":7654321098765432102,"text":"号码 7654321098765432103"}}]}';
  await h.notice();snapshot=await h.collect();
  assert.equal(snapshot.items[0].comment_id,'7654321098765432101');
  assert.equal(snapshot.items[0].work_id,'7654321098765432102');
  assert.equal(snapshot.items[0].text,'号码 7654321098765432103');

  // Failed refresh cannot return cached notices as fresh; business errors count as failures too.
  h.state.noticeStatus=403;snapshot=await h.collect();
  assert.equal(snapshot.fresh,false);assert.equal(snapshot.items.length,0);assert.equal(snapshot.ready,false);
  assert.ok(snapshot.diagnostics.some(d=>d.http_status===403));
  h.state.noticeStatus=200;h.state.notice={status_code:8,at_list:[]};snapshot=await h.collect();
  assert.equal(snapshot.fresh,false);

  // Same path with different notice filters produces separate templates.
  h=harness();await h.account();await h.notice();
  await h.window.fetch('/aweme/v1/web/notice/multi/?notice_type=mention');await h.flush();
  const before=h.requests.length;await h.collect();assert.equal(h.requests.length-before,3);

  // Unknown numeric types are diagnostic-only. Do not replay a mutating notice request.
  h=harness();await h.account();
  h.state.notice={status_code:0,notice_list:[{type:3,comment:{cid:'101',aweme_id:'456'}}]};
  await h.notice();snapshot=await h.collect();
  assert.equal(snapshot.ready,false);assert.equal(snapshot.items.length,0);
  assert.ok(snapshot.diagnostics.some(d=>d.recognized===false));
  await h.window.fetch('/aweme/v1/web/notice/mark/',{method:'POST',body:'notice_id=1'});await h.flush();
  const markCount=h.requests.filter(r=>r.url.includes('/notice/mark/')).length;await h.collect();
  assert.equal(h.requests.filter(r=>r.url.includes('/notice/mark/')).length,markCount);

  // Verify account through a real read every time; switching clears notice templates and cached items.
  h=harness();await h.account();await h.notice();h.state.uid='789';
  await assert.rejects(h.window.__douyinMentionRequests.verifyAccount('123'),/账号/);
  snapshot=await h.collect();assert.equal(snapshot.items.length,0);assert.equal(snapshot.account_id,'789');
  h.state.accountStatus=401;snapshot=await h.collect();assert.equal(snapshot.fresh,false);
  console.log('Request capture checks passed: fetch/Request/XHR, credentials, int64 IDs, freshness, filters and account changes');
})().catch(error=>{console.error(error);process.exitCode=1;});
