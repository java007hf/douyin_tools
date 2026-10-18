const {test}=require('node:test');
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
const path=require('node:path');

test('auto polling reinjects scripts into a reused image tab before selecting files',async()=>{
  const calls=[];let poll;
  const chrome={
    runtime:{getManifest:()=>({version:'fixture'}),getURL:()=> 'chrome-extension://fixture/',onMessage:{addListener(){}}},
    storage:{session:{get:async()=>({enabled:true})}},
    tabs:{get:async id=>({id,url:id===1?'https://www.doubao.com/chat/old':'https://www.doubao.com/chat/create-image',status:'complete'}),
      query:async()=>[{id:2,url:'https://www.doubao.com/chat/create-image',status:'complete'}],
      sendMessage:async(id,value)=>{calls.push(['select',id,value.action]);return {accepted:true}}},
    scripting:{executeScript:async options=>calls.push(['inject',options.target.tabId,options.world,options.files[0]])}
  };
  const context={chrome,setInterval:fn=>{poll=fn;return 1},clearInterval(){},setTimeout,Date,
    URL,fetch:async(url,options)=>{
      const body=JSON.parse(options.body);assert.equal(body.protocol,8);
      return {ok:true,json:async()=>({image:{name:'fixture.png',data:'AA=='}})};
    }};
  vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../chrome_extension/background.js'),'utf8'),context);
  await context.startCommands(1);await poll();
  assert.deepEqual(calls,[['inject',2,'MAIN','page.js'],['inject',2,'ISOLATED','content.js'],['select',2,'select_reference']]);
});
