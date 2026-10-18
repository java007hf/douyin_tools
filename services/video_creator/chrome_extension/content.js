(() => {
  // Reinjection after extension reload must replace stale listeners.
  if(window.__doubaoUploadContentListener){
    try{chrome.runtime.onMessage.removeListener(window.__doubaoUploadContentListener)}catch{}
  }
  // session storage is restricted to trusted contexts, so background owns config reads.
  function configure(){
    return new Promise((resolve,reject)=>{
      const id=crypto.randomUUID();
      const listener=event=>{
        if(event.source===window&&event.origin===location.origin&&event.data?.source==='doubao-bridge-configured'&&event.data.id===id){
          clearTimeout(timer);window.removeEventListener('message',listener);resolve();
        }
      };
      const timer=setTimeout(()=>{window.removeEventListener('message',listener);reject(Error('Page bridge not ready'))},3000);
      window.addEventListener('message',listener);
      window.postMessage({source:'doubao-bridge-config-v3',enabled:true,id},location.origin);
    });
  }
  const listener=(message,sender,reply)=>{
    if(message.action==='configure'){
      window.postMessage({source:'doubao-bridge-config-v3',enabled:message.enabled===true},location.origin);
      reply({ok:true});
    }
    if(message.action==='select_reference'){
      reply({accepted:true});
      (async()=>{
        let diagnostics={};
        try{
          await configure();
          await chrome.runtime.sendMessage({action:'event',payload:{stage:'bridge_ready',ok:true}});
          const candidates=()=>[...document.querySelectorAll('input[type="file"]')].filter(x=>!x.disabled&&/image|\.png|\.jpg|\.jpeg/i.test(x.accept));
          const deadline=Date.now()+20000;
          while(!candidates().length&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,200));
          diagnostics.inputs=[...document.querySelectorAll('input[type="file"]')].map(x=>({accept:x.accept,multiple:x.multiple,disabled:x.disabled,visible:!!x.getClientRects().length}));
          // Prefer image-only controls; for mixed attachment controls prefer the
          // narrower accepted type set over a generic code/document uploader.
          const specificity=input=>input.accept.split(',').filter(x=>!/^\s*(image\/|\.(png|jpe?g|webp|gif|bmp|avif|heic))/i.test(x)).length;
          const priority=input=>specificity(input)*2+(input.multiple?0:1);
          const inputs=candidates().sort((a,b)=>priority(a)-priority(b));
          if(!inputs.length||(inputs.length>1&&priority(inputs[0])===priority(inputs[1])))throw Error('Cannot uniquely identify image upload input');
          const image=message.image;const bytes=Uint8Array.from(atob(image.data),c=>c.charCodeAt(0));
          const transfer=new DataTransfer();transfer.items.add(new File([bytes],image.name,{type:image.mime}));
          inputs[0].files=transfer.files;
          inputs[0].dispatchEvent(new Event('change',{bubbles:true}));
          await chrome.runtime.sendMessage({action:'event',payload:{stage:'reference_selected',ok:true}});
        }catch(error){
          const reason=['Page bridge not ready','Cannot uniquely identify image upload input'].includes(error.message)?error.message:'Reference selection failed';
          await chrome.runtime.sendMessage({action:'event',payload:{stage:'bridge_error',ok:false,reason,...diagnostics}});
        }
      })();
    }
  };
  window.__doubaoUploadContentListener=listener;
  chrome.runtime.onMessage.addListener(listener);
  if(window.__doubaoUploadWindowListener)window.removeEventListener('message',window.__doubaoUploadWindowListener);
  const windowListener=async event=>{
    const message=event.data;
    if(event.source!==window || event.origin!==location.origin || message?.source!=='doubao-bridge-page')return;
    if(!['upload','event'].includes(message.action))return;
    const result=await chrome.runtime.sendMessage({action:message.action,payload:message.payload}).catch(()=>({ok:false}));
    window.postMessage({source:'doubao-bridge-response',id:message.id,...result},location.origin);
  };
  window.__doubaoUploadWindowListener=windowListener;
  window.addEventListener('message',windowListener);
  chrome.runtime.sendMessage({action:'page_ready'}).catch(()=>{});
  // An MV3 worker may sleep; page heartbeat resumes automatic polling.
  if(window.__doubaoUploadHeartbeat)clearInterval(window.__doubaoUploadHeartbeat);
  window.__doubaoUploadHeartbeat=setInterval(()=>chrome.runtime.sendMessage({action:'page_ready'}).catch(()=>{}),20000);
})();
