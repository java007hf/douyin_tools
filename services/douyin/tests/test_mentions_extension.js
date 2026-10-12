const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

(async () => {
  const events = [];
  const requests = [];
  let handler;
  let notice = {at_list: [{comment: {cid:'101', aweme_id:'456', text:'讲了什么？'}}],
    likes: [{comment: {cid:'999', aweme_id:'456'}}]};
  let publication = {status_code:0, comment:{cid:'201', reply_id:'101'}};
  function response(payload) { return {ok:true, status:200, json:async()=>payload,
    text:async()=>typeof payload === 'string' ? payload : JSON.stringify(payload), clone(){return response(payload);}}; }
  const window = {__douyinToolsExtensionVersion:'test', screen:{width:1920,height:1080},
    fetch: async (url, options={}) => {
      requests.push({url, options});
      return response(url.includes('/self/') ? {user:{uid:'123'}} :
        url.includes('/notice/') ? notice : publication);
    }, addEventListener:(_, fn)=>{handler=fn;}, postMessage:data=>events.push(data)};
  const context = vm.createContext({window, location:{href:'https://www.douyin.com/user/self'},
    document:{querySelectorAll:()=>{throw new Error('DOM collection is forbidden');}},
    URL, URLSearchParams, Headers, Request, AbortController, setTimeout, clearTimeout, console,
    navigator:{}, XMLHttpRequest:function(){}, fetch:(...args)=>window.fetch(...args)});
  context.XMLHttpRequest.prototype.open = function(){};
  context.XMLHttpRequest.prototype.send = function(){};
  context.XMLHttpRequest.prototype.setRequestHeader = function(){};
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/mention_requests.js'),'utf8'),context);
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../chrome_extension/injected.js'),'utf8'),context);
  await window.fetch('https://www.douyin.com/aweme/v1/web/user/profile/self/');
  await window.fetch('https://www.douyin.com/aweme/v1/web/notice/multi/');
  await new Promise(resolve=>setImmediate(resolve));
  async function command(data) {
    await handler({source:window, data:{source:'douyin-tools-content-v3', id:'test', ...data}});
    return events.pop();
  }
  const collected = await command({action:'collectMentions'});
  assert.equal(collected.data.account_id,'123');
  assert.equal(collected.data.items.length,1);
  assert.equal(collected.data.items[0].comment_id,'101');
  let result = await command({action:'replyMention', accountId:'wrong', workId:'456', replyId:'101', comment:'摘要'});
  assert.equal(result.ok,false);
  result = await command({action:'replyMention', accountId:'123', workId:'456', replyId:'101', comment:'摘要'});
  assert.equal(result.ok,true);
  assert.equal(requests.at(-1).options.method,'POST');
  assert.equal(new URLSearchParams(requests.at(-1).options.body).get('reply_id'),'101');
  const before = requests.filter(r=>r.url.includes('/comment/publish/')).length;
  publication = {status_code:0, comment:{cid:'202',reply_id:'0'}};
  result = await command({action:'replyMention', accountId:'123', workId:'456', replyId:'101', comment:'摘要'});
  assert.equal(result.ok,false);
  assert.equal(requests.filter(r=>r.url.includes('/comment/publish/')).length,before+1); // No retry/fallback.
  publication = '{"status_code":0,"comment":{"cid":7654321098765432101,"reply_id":101}}';
  result = await command({action:'replyMention', accountId:'123', workId:'456', replyId:'101', comment:'摘要'});
  assert.equal(result.ok,true);
  assert.equal(result.data.comment_id,'7654321098765432101');
  console.log('Mention capture, account guard, original-comment binding and single-send checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
