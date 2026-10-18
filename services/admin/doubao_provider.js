(() => {
  const form=document.querySelector('form[data-provider="mock_doubao"]');
  async function load(){
    const [providers,models]=await Promise.all([fetch('/api/providers').then(r=>r.json()),fetch('/api/models').then(r=>r.json())]);
    const current=(providers.providers||[]).filter(p=>p.provider==='mock_doubao').pop();
    form.elements.model.replaceChildren(...(models.mock_doubao_image||[]).map(name=>new Option(name,name)));
    form.elements.default_video_model.replaceChildren(...(models.mock_doubao_video||[]).map(name=>new Option(name,name)));
    if(current){form.elements.default_video_model.value=current.default_video_model||(models.mock_doubao_video||[])[0];form.elements.id.value=current.id;form.elements.name.value=current.name||'豆包 Mock';form.elements.model.value=current.model;form.elements.enabled.checked=current.enabled!==false}
    const agent=document.querySelector('form[data-provider="ai_video_agent"]');if(!agent)return;
    const select=agent.elements.default_image_provider_id;
    const mockProviders=(providers.providers||[]).filter(p=>p.provider==='mock_doubao'&&p.enabled!==false);
    for(const provider of mockProviders)if(![...select.options].some(x=>x.value===provider.id))select.append(new Option(provider.name||'豆包 Mock',provider.id));
    for(const route of ['t2v','i2v']){
      const providerSelect=agent.elements['default_'+route+'_provider_id'];const videoSelect=agent.elements['default_'+route+'_model'];
      for(const provider of mockProviders)if(![...providerSelect.options].some(x=>x.value===provider.id))providerSelect.append(new Option(provider.name||'豆包 Mock',provider.id));
      for(const name of models.mock_doubao_video||[])if(![...videoSelect.options].some(x=>x.value===name))videoSelect.append(new Option(name,name));
      const agentSaved=(providers.providers||[]).filter(p=>p.provider==='ai_video_agent').pop();
      if(agentSaved&&mockProviders.some(p=>p.id===agentSaved['default_'+route+'_provider_id'])){providerSelect.value=agentSaved['default_'+route+'_provider_id'];videoSelect.value=agentSaved['default_'+route+'_model']}
      providerSelect.addEventListener('change',()=>{const provider=mockProviders.find(p=>p.id===providerSelect.value);if(provider&&!videoSelect.value.startsWith('mock_doubao_seedance_'))videoSelect.value=provider.default_video_model||(models.mock_doubao_video||[])[0]});
    }
    const modelSelect=agent.elements.default_image_model;
    for(const name of models.mock_doubao_image||[])if(![...modelSelect.options].some(x=>x.value===name))modelSelect.append(new Option(name,name));
    const saved=(providers.providers||[]).filter(p=>p.provider==='ai_video_agent').pop();
    if(saved&&mockProviders.some(p=>p.id===saved.default_image_provider_id)){select.value=saved.default_image_provider_id;modelSelect.value=saved.default_image_model}
    select.addEventListener('change',()=>{
      const provider=mockProviders.find(p=>p.id===select.value);
      if(provider&&!modelSelect.value.startsWith('mock_doubao_'))modelSelect.value=provider.model||models.mock_doubao_image[0];
    });
  }
  form.onsubmit=async event=>{
    event.preventDefault();const status=form.querySelector('.status');
    try{
      const values=Object.fromEntries(new FormData(form));values.provider='mock_doubao';values.enabled=form.elements.enabled.checked;
      const response=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(values)});
      const result=await response.json();if(!response.ok)throw Error(result.error||'保存失败');
      form.elements.id.value=result.provider.id;status.textContent='已保存。AI视频可将它选为默认生图 Provider；登录凭据在“豆包网页登录”中维护。';await load();
    }catch(error){status.textContent=error.message}
  };
  load().catch(error=>form.querySelector('.status').textContent=error.message);
})();
