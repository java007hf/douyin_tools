/* Shared publication controls for Douyin and YouTube history. */
(() => {
  'use strict';
  const prefix = location.pathname.match(/^\/tabs\/[^/]+/)?.[0] || '';
  const href = path => prefix && (path === prefix || path.startsWith(prefix + '/')) ? path : prefix + path;
  const names = {xiaohongshu:'小红书', wechat:'微信公众号', douyin:'抖音图文'};
  const publishLabels = {not_connected:'未发送',queued:'排队发布',sending:'正在发送',awaiting_login:'等待账号登录',ready:'已准备预览',published:'内容已发布',failed:'发送失败',unknown:'发送结果待核实'};
  const labels = {pending:'等待生成', running:'正在生成', generated:'内容已生成', error:'生成失败'};
  const active = batches => (batches || []).some(b => ['pending','running'].includes(b.status) || b.targets?.some(t => ['queued','sending','awaiting_login'].includes(t.publish_status)));
  const el = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  };
  const css = el('style');
  css.textContent = `
    .publication-history-row{display:grid!important;grid-template-columns:minmax(0,1fr) auto auto;align-items:start!important;gap:8px!important}
    .publication-history-row>a{grid-column:1;grid-row:1}.publication-history-row>.publication-action{grid-column:2;grid-row:1;align-self:start!important}
    .publication-history-row>button:not(.publication-action){grid-column:3;grid-row:1;align-self:start!important}
    .publication-history-row>.publication-badges{grid-column:1/-1;grid-row:2;display:flex;flex-wrap:wrap;gap:4px;min-width:0}
    .publication-dialog{width:min(980px,90vw);max-height:88vh;box-sizing:border-box;border:1px solid #cfd8d8;border-radius:14px;padding:28px;color:#1c3236;background:#f9faf8;box-shadow:0 24px 90px #102c3540;font:15px 'Microsoft YaHei',sans-serif}
    .publication-dialog::backdrop{background:#152c3d70}.publication-dialog h2{margin:0;font-size:25px}.publication-head{display:flex;justify-content:space-between;gap:20px;align-items:center}
    .publication-dialog button,.publication-action{cursor:pointer;border:1px solid #bacbc8;border-radius:6px;padding:9px 14px;background:white;color:#1c5552;font:inherit}.publication-dialog button:disabled,.publication-action:disabled{opacity:.5;cursor:default}
    .publication-dialog .publication-primary,.publication-target .publication-primary{background:#225f58;color:white;border-color:#225f58}.publication-note{color:#536b6d;font-size:13px;line-height:1.7}
    .publication-platforms{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:18px 0}.publication-platforms label{display:flex;align-items:center;gap:10px;border:1px solid #cedbd6;background:white;border-radius:8px;padding:16px;margin:0;cursor:pointer}
    .publication-dialog input[type=checkbox]{width:18px;height:18px;margin:0;accent-color:#225f58}.publication-auto{display:flex;gap:9px;align-items:center;margin:16px 0}
    .publication-feedback{white-space:pre-wrap;margin:14px 0;line-height:1.6}.publication-content{border-top:1px solid #cedbd6;margin-top:24px;padding-top:20px}.publication-batch{margin:18px 0}.publication-target{border:1px solid #d4ddda;background:white;border-radius:8px;padding:16px;margin:12px 0}
    .publication-target summary{cursor:pointer;line-height:1.7}.publication-body{white-space:pre-wrap;overflow-wrap:anywhere;line-height:1.9;font:inherit;background:transparent;padding:0;max-height:none}
    .publication-images{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:18px 0}.publication-images img{width:100%;height:auto;border-radius:5px;display:block}.publication-images figure{margin:0}.publication-images figcaption{font-size:12px;color:#536b6d;margin-top:6px}
    .publication-links{display:flex;gap:16px;flex-wrap:wrap;margin:16px 0}.publication-links a{color:#225f58}.publication-badge{display:inline-block;border-radius:4px;background:#e8efe9;color:#2a6453;padding:2px 6px;font-size:12px;margin:3px}.publication-images .publication-cover{grid-column:span 2;max-width:420px}
    .publication-columns{display:grid;grid-template-columns:minmax(230px,.8fr) minmax(0,1.5fr);gap:28px;margin-top:20px;align-items:start}.publication-column{min-width:0;padding:20px;border:1px solid #d4ddda;border-radius:10px;background:#fff;box-sizing:border-box}.publication-cover-panel{background:#f5f7f3}.publication-body-panel{border-top:3px solid #225f58}.publication-field-label{display:block;margin:18px 0 8px;color:#536b6d;font-size:13px}.publication-cover-headline{margin:0 0 12px;font-size:22px;line-height:1.5;overflow-wrap:anywhere}.publication-cover-subtitle{margin:0 0 16px;line-height:1.7;color:#536b6d}.publication-note-title{margin:0 0 18px;font-size:21px;line-height:1.5;overflow-wrap:anywhere}.publication-column>h4{margin:0 0 16px;color:#536b6d;font-size:13px;letter-spacing:.08em}.publication-column>h3{margin-top:0}.publication-column .publication-cover{max-width:100%;margin:18px 0}.publication-column img{max-width:100%;display:block;border-radius:6px}.publication-image-button{display:block;width:100%;padding:0!important;border:0!important;background:transparent!important;cursor:zoom-in!important}.publication-original{border:0;background:none;color:#225f58;padding:6px 0;cursor:pointer;font:inherit}.publication-column .publication-images{grid-template-columns:repeat(2,minmax(0,1fr))}
    .publication-publish-actions{position:sticky;top:0;z-index:2;display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:14px 0;padding:12px;background:#f5f8f5;border:1px solid #cedbd6;border-radius:8px;box-shadow:0 3px 10px #102c3510}.publication-publish-actions .publication-primary{font-weight:700;padding:11px 20px}.publication-publish-actions .publication-note{flex:1;min-width:180px;margin:0}
    .publication-viewer{width:min(1100px,96vw);height:94vh;max-width:96vw;max-height:94vh;box-sizing:border-box;padding:16px;border:0;border-radius:12px;background:#172124;color:white;overflow:hidden}.publication-viewer::backdrop{background:#081114dd}.publication-viewer-head{display:flex;align-items:center;justify-content:space-between;gap:16px;height:44px}.publication-viewer button{border:1px solid #ffffff50;border-radius:6px;padding:8px 14px;background:#263438;color:white;cursor:pointer;font:inherit}.publication-viewer-stage{height:calc(100% - 88px);display:grid;grid-template-columns:48px minmax(0,1fr) 48px;gap:12px;align-items:center}.publication-viewer-stage img{width:100%;height:100%;min-height:0;object-fit:contain}.publication-viewer-caption{margin:8px 0 0;text-align:center;font-size:14px}.publication-viewer button:disabled{opacity:.35;cursor:default}
    @media(max-width:760px){.publication-columns{grid-template-columns:minmax(0,1fr)}.publication-column .publication-cover{max-width:420px}.publication-viewer-stage{grid-template-columns:36px minmax(0,1fr) 36px;gap:4px}.publication-viewer-stage button{padding:8px}}
    @media(max-width:650px){.publication-dialog{padding:18px}.publication-platforms{grid-template-columns:1fr}.publication-images{grid-template-columns:repeat(2,minmax(0,1fr))}}
  `;
  document.head.append(css);

  // Keep the same action available where readers finish the understanding report.
  const detailPublish = document.getElementById('publicationButton');
  const detailContents = document.getElementById('publicationContents');
  if (detailPublish && detailContents) {
    detailPublish.classList.add('publication-action');
    detailPublish.style.cssText = 'background:#225f58;color:white;border-color:#225f58';
    const heading = detailContents.parentElement.querySelector('h2');
    if (heading) {
      const bar = el('div', undefined, 'publication-head');
      const button = el('button', '发布内容', 'publication-action');
      button.type = 'button';
      const sync = () => {
        button.disabled = detailPublish.disabled;
        button.title = button.disabled ? '理解完成后可生成发布内容' : '选择平台、生成并发布内容';
      };
      button.onclick = () => detailPublish.click();
      heading.before(bar);bar.append(heading, button);
      sync();
      new MutationObserver(sync).observe(detailPublish, {attributes:true, attributeFilter:['disabled']});
    }
  }

  async function api(path, options) {
    const response = await fetch(href(path), {cache:'no-store', ...options});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '内容任务请求失败');
    return data;
  }
  let publicationCapabilities;
  async function requireDouyinPublisher() {
    try {
      publicationCapabilities ||= api('/api/publications/capabilities');
      const value=await publicationCapabilities;
      if (!(value.version >= 2 && value.douyin?.music_required && value.douyin?.text_validation && value.douyin?.relayout)) throw new Error();
    } catch {
      publicationCapabilities=null;
      throw new Error('当前服务尚未加载新版抖音发布模块，请在理解任务空闲后重启服务并刷新页面。');
    }
  }

  function bodyPreview(text) {
    const article = el('div', undefined, 'publication-body');
    let paragraph = [];
    const flush = () => {if (paragraph.length) {article.append(el('p', paragraph.join('\n')));paragraph = [];}};
    for (const line of text.split('\n')) {
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      if (heading) {flush();article.append(el('h' + Math.min(heading[1].length + 1, 4), heading[2]));}
      else if (!line.trim()) flush();
      else paragraph.push(line);
    }
    flush();return article;
  }
  function previewImages(images, start, originals = false) {
    if (!images.length) return;
    const previous = document.activeElement;
    document.querySelector('.publication-viewer')?.close();
    const dialog = el('dialog', undefined, 'publication-viewer');
    dialog.setAttribute('aria-label', originals ? '配图原图预览' : '图文预览');
    const head = el('div', undefined, 'publication-viewer-head');
    const count = el('span'), close = el('button', '关闭'); close.type = 'button';
    head.append(count, close);
    const stage = el('div', undefined, 'publication-viewer-stage');
    const back = el('button', '‹'), next = el('button', '›'), image = el('img');
    back.type = next.type = 'button';
    back.setAttribute('aria-label', '上一张'); next.setAttribute('aria-label', '下一张');
    const caption = el('p', undefined, 'publication-viewer-caption');
    let index = Math.max(0, Math.min(start, images.length - 1));
    function update() {
      const item = images[index];
      image.src = href(originals ? item.original_href || item.href : item.href);
      image.alt = item.heading || '图文图片';
      count.textContent = `${originals ? '配图原图' : '图文预览'} · ${index + 1} / ${images.length}`;
      caption.textContent = item.heading || '';
      back.disabled = index === 0; next.disabled = index === images.length - 1;
    }
    const move = offset => {index = Math.max(0, Math.min(index + offset, images.length - 1));update();};
    back.onclick = () => move(-1); next.onclick = () => move(1); close.onclick = () => dialog.close();
    dialog.addEventListener('keydown', event => {
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {event.preventDefault();move(event.key === 'ArrowLeft' ? -1 : 1);}
    });
    dialog.addEventListener('click', event => {if (event.target === dialog) dialog.close();});
    dialog.addEventListener('close', () => {dialog.remove();if (previous?.isConnected) previous.focus();}, {once:true});
    stage.append(back, image, next); dialog.append(head, stage, caption); document.body.append(dialog);
    update();dialog.showModal();close.focus();
  }
  function render(container, batches) {
    container.replaceChildren();
    if (!batches?.length) {container.append(el('p','尚未生成平台内容。','publication-note'));return;}
    for (const [index, batch] of batches.entries()) {
      const version = el('details', undefined, 'publication-batch'); version.open = index === 0;
      version.append(el('summary', `${new Date(batch.created_at * 1000).toLocaleString()} · ${batch.auto_publish ? '已请求自动发布' : '手动发布'}`));
      for (const target of batch.targets) {
        const card = el('details', undefined, 'publication-target'); card.open = index === 0;
        card.append(el('summary', `${names[target.platform]} · ${labels[target.status] || target.status} · ${['xiaohongshu','douyin'].includes(target.platform) ? publishLabels[target.publish_status] || '未发送' : '发布待接入'}`));
        if (target.error) card.append(el('p', target.error, 'publication-feedback'));
        if (target.progress && target.status !== 'generated') card.append(el('p', target.progress, 'publication-note'));
        if (['xiaohongshu','douyin'].includes(target.platform)) {
          const controls = el('div', undefined, 'publication-publish-actions');
          const login = el('button', '登录' + names[target.platform]);login.type='button';
          const message=el('p',target.publication?.message || '', 'publication-note');message.setAttribute('role','status');
          async function action(path, button) {
            button.disabled=true;
            try {
              if (target.platform === 'douyin') await requireDouyinPublisher();
              const result=await api(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:target.platform})});
              message.textContent=result.message || '已加入队列，正在等待前面的任务完成…';
              const timer=setInterval(async()=>{
                if (!container.isConnected) {clearInterval(timer);return;}
                try {
                  const job=await api('/api/publications/'+target.platform+'/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:result.id})});
                  message.textContent=job.message || job.status;
                  if (!['queued','running','awaiting_login','submitting'].includes(job.status)) {
                    clearInterval(timer);button.disabled=false;
                    const latest=await api('/api/understanding-history/'+encodeURIComponent(batch.history_id));
                    render(container,latest.publications);
                  }
                } catch(error) {clearInterval(timer);message.textContent=error.message;button.disabled=false;}
              },3000);
            } catch(error) {message.textContent=error.message;button.disabled=false;}
          }
          login.onclick=()=>action('/api/publications/'+target.platform+'/login',login);controls.append(login);
          if (target.status==='generated') {
            const send=el('button',({queued:'已加入发布队列',published:'已发布',sending:'正在发布…',awaiting_login:'等待登录后发布',unknown:'发布结果待核实'})[target.publish_status] || '一键发布到'+names[target.platform],'publication-primary');send.type='button';
            send.title='将本版本的封面、内页图片、标题和正文发布到'+names[target.platform];
            send.disabled=['published','queued','sending','awaiting_login','unknown'].includes(target.publish_status);
            send.onclick=()=>action('/api/understanding-history/'+encodeURIComponent(batch.history_id)+'/publications/'+batch.id+'/send',send);
            controls.prepend(send);
            if (target.platform === 'douyin') {
              const layout=el('button','更新竖版排版');layout.type='button';
              layout.title='复用本地LLM原文与原图，保存新的9:16版本，不发布、不覆盖原作';
              layout.onclick=async()=>{
                layout.disabled=true;
                try {
                  await requireDouyinPublisher();
                  const requestId=Date.now().toString(36)+'_'+Math.random().toString(36).slice(2).padEnd(16,'0');
                  await api('/api/understanding-history/'+encodeURIComponent(batch.history_id)+'/publications/'+batch.id+'/relayout',
                    {method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({platform:'douyin',request_id:requestId})});
                  const latest=await api('/api/understanding-history/'+encodeURIComponent(batch.history_id));
                  render(container,latest.publications);
                } catch(error) {message.textContent=error.message;layout.disabled=false;}
              };
              controls.append(layout);
            }
            const preview=el('button','预填检查');preview.type='button';preview.disabled=send.disabled;
            preview.onclick=()=>action('/api/understanding-history/'+encodeURIComponent(batch.history_id)+'/publications/'+batch.id+'/preview',preview);
            controls.append(preview);
            if (target.publish_status==='unknown') {
              const verify=el('button','核对发布结果');verify.type='button';
              verify.onclick=()=>action('/api/understanding-history/'+encodeURIComponent(batch.history_id)+'/publications/'+batch.id+'/verify',verify);
              controls.append(verify);
            }
          }
          if (target.publication?.receipt?.title) controls.append(el('p','发布标题：'+target.publication.receipt.title,'publication-note'));
          if (target.publication?.receipt?.url) {const note=el('a','查看已发布笔记');note.href=target.publication.receipt.url;note.target='_blank';note.rel='noopener';controls.append(note);}
          if (!message.textContent) message.textContent = target.status === 'generated'
            ? '发布本版本的封面、内页、标题和正文；首次使用请登录；登录态会保存，之后可直接发布。'
            : '内容生成完成后可一键发布。';
          controls.append(message);card.append(controls);
        }
        const content = target.content;
        if (content?.title) {
          if (content.rendering?.width) card.append(el('p',`图片规格：${content.rendering.width}×${content.rendering.height} · ${content.rendering.aspect}`,'publication-note'));
          if (content.editorial_trace?.model) {
            card.append(el('p', `改写模型：${content.editorial_trace.model} · ${names[target.platform]}风格规则 · 复用视频理解 LLM`, 'publication-note'));
          }
          const columns = el('div', undefined, 'publication-columns');
          const coverColumn = el('section', undefined, 'publication-column publication-cover-panel');
          const bodyColumn = el('section', undefined, 'publication-column publication-body-panel');
          coverColumn.setAttribute('aria-label', '封面');
          bodyColumn.setAttribute('aria-label', '笔记内容');
          coverColumn.append(el('h4', '封面'), el('span', '封面标题', 'publication-field-label'),
            el('h3', content.cover?.headline || content.images?.find(image => image.is_cover)?.heading || content.title, 'publication-cover-headline'));
          if (content.cover?.subtitle) coverColumn.append(el('p', content.cover.subtitle, 'publication-cover-subtitle'));
          bodyColumn.append(el('h4', '笔记内容'), el('span', '笔记标题', 'publication-field-label'),
            el('h3', content.title, 'publication-note-title'), el('span', '正文', 'publication-field-label'), bodyPreview(content.body || ''));
          bodyColumn.append(el('p', (content.tags || []).map(t => '#' + t).join(' '), 'publication-note'));
          columns.append(coverColumn, bodyColumn);card.append(columns);
          if (content.cover) {
            const info = el('details');info.append(el('summary','封面方案与标题候选'));
            const styles = {white_red:'白底红字',portrait:'人物主视觉',scene:'场景主视觉',bold:'高对比大字',editorial:'杂志图文'};
            info.append(el('p',`${styles[content.cover.style] || content.cover.style} · ${content.cover.headline}`),el('p',content.cover.reason,'publication-note'));
            for (const title of content.cover.title_candidates || []) info.append(el('p',(title===content.cover.headline?'✓ ':'')+title));
            if (content.cover.href) {const download = el('a','下载封面');download.href=href(content.cover.href);download.download='cover.png';info.append(download);}
            coverColumn.append(info);
          }
          const images = el('div', undefined, 'publication-images');
          for (const [i, image] of (content.images || []).entries()) {
            const figure = el('figure'), link = el('button', undefined, 'publication-image-button'), img = el('img');
            if (image.is_cover) figure.className = 'publication-cover';
            link.type = 'button';link.setAttribute('aria-label', '预览：' + image.heading);
            link.onclick = () => previewImages(content.images, i);
            img.src = href(image.href); img.alt = image.heading; img.loading = 'lazy';
            const origin = {mock_doubao:'豆包 Mock',local:'本地生图',stock_pixabay:'Pixabay 照片',stock_pexels:'Pexels 照片'}[image.provider] || '';
            link.append(img); figure.append(link, el('figcaption', `${image.is_cover?'封面':i+1}. ${image.is_cover ? content.cover?.headline || image.heading : image.heading}${origin ? ' · '+origin : ''}`));
            if (image.attribution && /^https:\/\//.test(image.source_url || '')) {const credit=el('a',image.attribution);credit.href=image.source_url;credit.target='_blank';credit.rel='noopener';figure.append(credit);}
            if (image.license && /^https:\/\//.test(image.license_url || '')) {const license=el('a',image.license);license.href=image.license_url;license.target='_blank';license.rel='noopener';figure.append(el('br'),license);}
            if (image.fallback_reason) figure.append(el('p', image.fallback_reason, 'publication-note'));
            if (image.original_href) {const original = el('button','查看配图原图','publication-original');original.type='button';original.onclick=()=>previewImages(content.images,i,true);figure.append(original);}
            if (image.is_cover) coverColumn.append(figure);else images.append(figure);
          }
          bodyColumn.append(images);
          card.append(el('p', '优先图库照片，找不到合适素材时用AI补图（豆包 → 本地）。来源和许可见各图片；示意配图不代表真实事件或实时行情。', 'publication-note'));
          if (content.image_traces?.length) {
            const tasks = el('details');tasks.append(el('summary','配图任务与切换记录'));
            for (const [i, trace] of content.image_traces.entries()) {
              tasks.append(el('p', [`配图 ${i+1}`,{local:'本地生图',mock_doubao:'豆包 Mock',stock_pixabay:'Pixabay',stock_pexels:'Pexels'}[trace.provider],trace.model,trace.status,trace.message,
                trace.prompt_id && `ComfyUI 任务：${trace.prompt_id}`,trace.stock_fallback_reason,trace.fallback_reason,trace.error,trace.release_error].filter(Boolean).join(' · '),'publication-note'));
            }
            card.append(tasks);
          }
          const boundMusic = target.publication?.receipt?.music || target.publication?.music || content.preflight?.music;
          if (boundMusic?.title) {
            card.append(el('h4',boundMusic.status === 'confirmed' ? '配乐已随发布提交' : '已选择待发布配乐'),
              el('p',[boundMusic.title,boundMusic.author,boundMusic.duration_seconds && `${boundMusic.duration_seconds}秒`,`音乐ID：${boundMusic.music_id}`].filter(Boolean).join(' · '),'publication-note'));
          } else if (content.music?.status === 'suggested') {
            card.append(el('h4','配乐建议 · 尚未匹配曲库音乐'), el('p', `${content.music.mood} · ${(content.music.keywords || []).join(' / ')}\n${content.music.reason}`, 'publication-feedback'));
          }
          const links = el('div', undefined, 'publication-links');
          for (const [key, label] of [['package','下载完整素材包'],['markdown','下载文案 Markdown'],['json','查看内容 JSON'],['comparison','查看排版对比']]) {
            if (!content.exports?.[key]) continue;
            const link = el('a', label); link.href = href(content.exports[key]); link.target = '_blank'; link.rel = 'noopener';
            if (key !== 'json') link.download = '';
            links.append(link);
          }
          card.append(links);
          const scope = el('details'); scope.append(el('summary','来源、理解范围与配图提示词'));
          scope.append(el('p', content.source_url || '', 'publication-note'));
          for (const text of content.limitations || []) scope.append(el('p', text, 'publication-note'));
          for (const image of content.cards || []) scope.append(el('p', `${image.heading}：${image.image_prompt}`, 'publication-note'));
          card.append(scope);
        }
        version.append(card);
      }
      container.append(version);
    }
  }

  async function open(item, onRefresh) {
    document.querySelector('.publication-dialog')?.close();
    const dialog = el('dialog', undefined, 'publication-dialog');
    const head = el('div', undefined, 'publication-head'), close = el('button', '关闭'); close.type = 'button';
    const title = el('h2','发布内容'); title.id = 'publication-dialog-title';
    dialog.setAttribute('aria-labelledby', title.id); head.append(title, close);
    dialog.append(head, el('p', item.title, 'publication-note'));
    const form = el('form'), platforms = el('div', undefined, 'publication-platforms');
    for (const [id, name] of Object.entries(names)) {
      const label = el('label'), checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.name = 'platform'; checkbox.value = id;
      const text = el('span', name); text.append(el('small', ' · '+(['xiaohongshu','douyin'].includes(id)?'网页发布':'待接入'), 'publication-note'));
      label.append(checkbox, text); platforms.append(label);
    }
    const autoLabel = el('label', undefined, 'publication-auto'), auto = el('input'); auto.type = 'checkbox';
    autoLabel.append(auto, el('span', '生成后自动发布'));
    const submit = el('button','生成所选平台内容','publication-primary'); submit.type = 'submit';
    const feedback = el('p', '', 'publication-feedback'); feedback.setAttribute('role','status'); feedback.setAttribute('aria-live','polite');
    const results = el('section', undefined, 'publication-content'); results.append(el('p','正在加载已有内容…'));
    form.append(platforms, autoLabel, el('p','小红书、抖音已接入创作中心网页发布，首次需在Chrome分别登录；公众号待接入。勾选后会发布本次新生成的已接入平台内容，历史版本不会自动补发。抖音会按配乐方案搜索真实曲库并校验绑定，缺少配乐时不提交；小红书配乐仍为建议。','publication-note'), submit, feedback);
    dialog.append(form, results); document.body.append(dialog); dialog.showModal();
    let timer, snapshot = '', submitting = false, requestId = null, submissionError = '';
    close.onclick = () => dialog.close();
    dialog.addEventListener('close', () => {clearTimeout(timer);dialog.remove();});
    async function refresh() {
      clearTimeout(timer);
      try {
        const result = await api('/api/understanding-history/' + encodeURIComponent(item.id));
        if (!dialog.open) return;
        const next = JSON.stringify(result.publications);
        if (next !== snapshot) {render(results, result.publications);snapshot = next;}
        const busy = active(result.publications);
        submit.disabled = busy || submitting;
        platforms.querySelectorAll('input').forEach(input => input.disabled = busy || submitting);
        auto.disabled = busy || submitting;
        if (busy) feedback.textContent = '正在后台生成；关闭对话框后仍可在这条历史记录中查看。';
        else if (submissionError) feedback.textContent = submissionError;
        else if (snapshot !== '[]') feedback.textContent = '内容任务已结束。各平台结果见下方，失败的平台可重新选择生成。';
        onRefresh?.();
        if (busy) timer = setTimeout(refresh, 3000);
      } catch (error) {
        if (!dialog.open) return;
        feedback.textContent = error.message;
        timer = setTimeout(refresh, 5000);
      }
    }
    // Retain the same idempotency key after an ambiguous network failure.
    form.onchange = () => {requestId = null;submissionError = '';feedback.textContent = '';};
    form.onsubmit = async event => {
      event.preventDefault(); if (submitting) return;
      const selected = [...platforms.querySelectorAll('input:checked')].map(input => input.value);
      if (!selected.length) {feedback.textContent = '请至少勾选一个平台。';return;}
      requestId ||= (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2).padEnd(16,'0'));
      submitting = true; submissionError = '';submit.disabled = true; feedback.textContent = '正在创建内容任务…';
      try {
        if (selected.includes('douyin')) await requireDouyinPublisher();
        await api('/api/understanding-history/' + encodeURIComponent(item.id) + '/publications', {
          method:'POST', headers:{'Content-Type':'application/json'},
          body:JSON.stringify({platforms:selected, auto_publish:auto.checked, request_id:requestId})
        });
        requestId = null;
      } catch (error) {submissionError = error.message;feedback.textContent = error.message;}
      finally {submitting = false;submit.disabled = false;}
      await refresh();
    };
    await refresh();
  }

  function decorate(row, item, onRefresh) {
    row.classList.add('publication-history-row');
    const button = el('button','发布','publication-action'); button.type = 'button';
    button.disabled = item.analysis_ready === false;
    button.title = button.disabled ? '理解完成后可生成发布内容' : '选择平台、生成并查看内容';
    button.onclick = () => open(item, onRefresh);
    row.append(button);
    if (item.publications?.length) {
      const badges = el('span',undefined,'publication-badges');
      for (const target of item.publications) badges.append(el('span', `${names[target.platform]} · ${labels[target.status] || target.status} · ${['xiaohongshu','douyin'].includes(target.platform) ? publishLabels[target.publish_status] || '未发送' : '待接入'}`, 'publication-badge'));
      row.append(badges);
    }
  }
  window.PublicationUI = {open, decorate, render, active};
})();
