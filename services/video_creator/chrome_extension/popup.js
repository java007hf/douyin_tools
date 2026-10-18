for(const enabled of [true,false])document.getElementById(enabled?'enable':'disable').onclick=async()=>{
  try{
    const tabs=await chrome.tabs.query({active:true,currentWindow:true});
    if(!tabs[0]?.url?.startsWith('https://www.doubao.com/'))throw Error('请先打开豆包网页');
    if(enabled){
      document.getElementById('status').textContent='正在连接豆包页面…';
      await chrome.scripting.executeScript({target:{tabId:tabs[0].id},world:'MAIN',files:['page.js']});
      await chrome.scripting.executeScript({target:{tabId:tabs[0].id},world:'ISOLATED',files:['content.js']});
    }
    await chrome.storage.session.set({enabled});
    const configured=await chrome.tabs.sendMessage(tabs[0].id,{action:'configure',enabled});
    if(!configured?.ok)throw Error('豆包页面脚本未就绪，请刷新页面后再启用');
    if(enabled)await chrome.runtime.sendMessage({action:'start_commands',tabId:tabs[0].id});
    document.getElementById('status').textContent=enabled?'已启用，等待本地图片自动传入':'已停用';
  }catch(error){document.getElementById('status').textContent=error.message}
};
