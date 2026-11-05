"""Admin-only stock-photo credentials and status; no keys in generated artifacts."""


def install(html):
    nav = '<button data-panel="stock-images">图库配图</button>'
    panel = '''<section id="stock-images" class="panel"><h2>图库配图</h2>
<p>发布配图顺序：图库照片 → 豆包 Mock → 本地生图。未配置或搜不到合适照片时使用 AI 补图。搜索结果缓存24小时，生成记录保留作者、来源与许可。</p>
<p>在图库官网申请或查看 API Key，开放情况以官网当前说明为准；已有 Key 可在此配置。</p>'''
    for provider, name in [('stock_pixabay','Pixabay'),('stock_pexels','Pexels')]:
        panel += f'''<form data-stock-provider="{provider}"><h3>{name}</h3><input type="hidden" name="id">
<label>API Key<input name="api_key" type="password" autocomplete="off" placeholder="留空保持已保存的 Key"></label>
<label>状态<select name="enabled"><option value="true">启用</option><option value="false">停用</option></select></label>
<button>保存 {name}</button><div class="status" role="status"></div></form>'''
    panel += '</section>'
    script = '''<script>
document.querySelectorAll('[data-stock-provider]').forEach(form=>{
  form.onsubmit=async event=>{event.preventDefault();const value=Object.fromEntries(new FormData(form));value.provider=form.dataset.stockProvider;value.enabled=value.enabled==='true';
    const status=form.querySelector('.status');status.textContent='正在保存…';
    try{const r=await fetch('/api/providers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});const d=await r.json();if(!r.ok)throw Error(d.error||'保存失败');form.elements.id.value=d.provider.id;form.elements.api_key.value=d.provider.api_key||'';status.textContent=value.enabled?'已启用，下一次生成时优先检索该图库':'已停用';}catch(e){status.textContent=e.message;}};
});
fetch('/api/providers').then(r=>r.json()).then(data=>{for(const form of document.querySelectorAll('[data-stock-provider]')){const saved=(data.providers||[]).filter(p=>p.provider===form.dataset.stockProvider).pop();if(saved){form.elements.id.value=saved.id;form.elements.api_key.value=saved.api_key||'';form.elements.enabled.value=String(saved.enabled!==false);}else form.querySelector('.status').textContent='待配置 API Key，目前会使用 AI 补图';}});
</script>'''
    return html.replace('<button data-panel="comfy">',nav+'<button data-panel="comfy">',1).replace('<section id="comfy"',panel+'<section id="comfy"',1).replace('</body>',script+'</body>')
