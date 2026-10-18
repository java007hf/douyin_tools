let pollTimer=null;
async function referenceTab(tabId){
  let tab=await chrome.tabs.get(tabId).catch(()=>null);
  if(!tab?.url||new URL(tab.url).pathname!=='/chat/create-image'){
    const candidates=await chrome.tabs.query({url:'https://www.doubao.com/chat/create-image*'});
    tab=candidates[0]||await chrome.tabs.create({url:'https://www.doubao.com/chat/create-image?channel=YRNUy',active:false});
  }
  const deadline=Date.now()+30000;
  while(Date.now()<deadline){
    const current=await chrome.tabs.get(tab.id);
    if(current.status==='complete'){
      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'MAIN',files:['page.js']});
      await chrome.scripting.executeScript({target:{tabId:tab.id},world:'ISOLATED',files:['content.js']});
      return tab.id;
    }
    await new Promise(resolve=>setTimeout(resolve,300));
  }
  throw Error('Doubao image creation tab did not load');
}
async function startCommands(tabId){
  clearInterval(pollTimer);

  let busy=false;
  pollTimer=setInterval(async()=>{

    if(busy)return;busy=true;
    try{
      const {enabled}=await chrome.storage.session.get('enabled');
      if(enabled===false){return}
      const response=await fetch('http://127.0.0.1:18767/command',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({protocol:8,version:chrome.runtime.getManifest().version})});
      if(!response.ok)throw Error('Bridge not ready');
      const value=await response.json();
      if(value.image){
        try{await chrome.tabs.sendMessage(await referenceTab(tabId),{action:'select_reference',image:value.image})}
        catch{await fetch('http://127.0.0.1:18767/event',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({stage:'bridge_error',reason:'Reference selection failed',ok:false})})}
      }
    }catch{}finally{busy=false}
  },2000);
}
chrome.runtime.onMessage.addListener((message,sender,reply)=>{
  if(message.action==='start_commands'&&sender.url?.startsWith(chrome.runtime.getURL(''))){
    startCommands(message.tabId);reply({ok:true});return;
  }
  if(sender.url && new URL(sender.url).origin!=='https://www.doubao.com')return;
  if(message.action==='page_ready'&&sender.tab?.id){startCommands(sender.tab.id);reply({ok:true});return;}
  if(!['upload','event'].includes(message.action))return;
  chrome.storage.session.get('enabled').then(async ({enabled})=>{
    if(enabled===false)throw Error('Bridge disabled');
    const response=await fetch('http://127.0.0.1:18767/'+message.action,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(message.payload)
    });
    const value=await response.json();if(!response.ok)throw Error('Local bridge rejected upload');
    reply({ok:true,value});
  }).catch(()=>reply({ok:false,error:'本地上传桥接不可用；未自动重试'}));
  return true;
});
