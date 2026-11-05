const $ = id => document.getElementById(id);
const base = location.pathname.includes('/tabs/youtube') ? '/tabs/youtube' : '';
const href = p => p.startsWith(base + '/') ? p : base + p;
const labels = {done:'已完成', error:'失败', running:'进行中', pending:'排队中'};
let mode = 'download', submitting = false, downloadBusy = false;
let historyLoading = false, historyCount = 30, historySnapshot = '';
const jobs = new Map(), latest = {};
async function api(path, options) {
  const response = await fetch(href(path), {cache:'no-store', ...options});
  const data = await response.json();
  if (!response.ok) throw Error(data.error || '请求失败');
  return data;
}
function link(parent, text, path) {
  const a = document.createElement('a'); a.textContent = text; a.href = href(path);
  a.target = '_blank'; a.rel = 'noopener'; parent.append(a); return a;
}
function showResult(data){$('result').replaceChildren();const article=document.createElement('article');$('result').append(article);if(data.title){const h=document.createElement('h2');h.textContent=data.title;article.append(h)}const files=data.files||[data.video].filter(Boolean);for(const f of files){if(f.href){const v=document.createElement('video');v.controls=true;v.preload='metadata';v.src=href(f.href);article.append(v);const links=document.createElement('div');links.className='links';article.append(links);link(links,'下载视频',f.href).download=f.name||''}}
if(data.progress||data.reply_error){const status=document.createElement('p');status.textContent=(data.progress||'')+(data.reply_error?'：'+data.reply_error:'');article.append(status)}if(data.summary){const p=document.createElement('pre');p.textContent=data.summary;article.append(p)}if(data.key_points){const ul=document.createElement('ul');for(const text of data.key_points){const li=document.createElement('li');li.textContent=text;ul.append(li)}article.append(ul)}if(data.timeline){for(const item of data.timeline){const b=document.createElement('button');b.textContent=Math.floor(item.seconds/60)+':'+String(Math.floor(item.seconds%60)).padStart(2,'0')+' '+item.content;b.onclick=()=>{const v=article.querySelector('video');if(v){v.currentTime=item.seconds;v.play().catch(()=>{})}};article.append(b)}}if(data.history_id&&data.analysis_ready){const links=document.createElement('div');links.className='links';article.append(links);link(links,'完整报告', '/api/history/'+data.history_id+'/report');if(data.report)link(links,'下载 report.md',data.report.href).download='report.md';const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');summary.textContent='完整转写';pre.textContent=(data.transcript||[]).map(x=>'['+x.start.toFixed(1)+'s] '+x.text).join('\n');details.append(summary,pre);article.append(details)}}

function saveJobs() {
  localStorage.setItem('youtubeJobs', JSON.stringify([...jobs].map(([id, kind]) => ({id, kind}))));
}
function syncButton() {
  $('start').textContent = mode === 'understand' ? '理解并总结视频' : '开始下载';
  $('start').disabled = submitting || (mode === 'download' && downloadBusy);
}
async function poll(id, kind) {
  try {
    const job = await api('/api/jobs/' + id);
    if (kind === mode && latest[kind] === id) $('status').textContent = (job.message || labels[job.status]) + (job.error ? '：' + job.error : '');
    if (['done', 'error'].includes(job.status)) {
      jobs.delete(id); saveJobs();
      if (kind === 'download') downloadBusy = false;
      syncButton();
      if (job.result && kind === mode && latest[kind] === id) showResult(job.result);
      if (kind === 'understand') refreshUnderstanding();
      return;
    }
    setTimeout(() => poll(id, kind), 2500);
  } catch (error) {
    if (kind === mode && latest[kind] === id) $('status').textContent = '任务状态连接中断，正在重试：' + error.message;
    setTimeout(() => poll(id, kind), 5000);
  }
}
function queueSummary(queue) {
  $('queueStatus').textContent = `共享理解队列（抖音 / YouTube） · 队列等待 ${queue.pending} 条 · 处理中 ${queue.active} 条 · 并发 ${queue.concurrency}`;
}
async function loadHistory(more = false) {
  if (historyLoading) return;
  historyLoading = true;
  if (more) historyCount += 30;
  try {
    const data = {items:[], total:0};
    do {
      const page = await api('/api/history?offset=' + data.items.length + '&limit=30');
      data.items.push(...page.items); data.total = page.total; queueSummary(page.queue);
      if (!page.items.length) break;
    } while (data.items.length < Math.min(historyCount, data.total));
    const snapshot = JSON.stringify(data);
    if (snapshot === historySnapshot) return;
    const content = document.createDocumentFragment();
    if (!data.total) content.append(document.createTextNode('暂无视频理解记录'));
    for (const item of data.items) {
      const row = document.createElement('div'); row.className = 'history-row';
      const a = link(row, '', '/understanding/' + encodeURIComponent(item.id));
      a.textContent = `${new Date(item.created_at * 1000).toLocaleString()} · 手动解析 · ${item.title} · ${labels[item.reply_status || 'done'] || item.reply_status}`;
      if (item.progress) a.textContent += ' · ' + item.progress;
      if (item.queue_position && !item.progress?.includes('排队第')) a.textContent += ` · 排队第 ${item.queue_position} 位`;
      if (item.reply_error) a.textContent += ' · ' + item.reply_error;
      PublicationUI.decorate(row, item, () => loadHistory());
      const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = '×';
      remove.setAttribute('aria-label', '删除历史：' + item.title);
      remove.disabled = ['pending', 'running'].includes(item.reply_status);
      remove.title = remove.disabled ? '排队和处理中的任务暂不能删除历史' : '删除这条理解历史';
      remove.onclick = async () => {
        if (!confirm(`确定删除这条理解历史？\n${item.title}\n下载缓存文件将保留。`)) return;
        remove.disabled = true;
        try {await api('/api/history/' + item.id, {method:'DELETE'}); await loadHistory();}
        catch (error) {$('status').textContent = error.message; remove.disabled = false;}
      };
      row.append(remove); content.append(row);
    }
    if (data.items.length < data.total) {
      const more = document.createElement('button'); more.type = 'button'; more.textContent = '加载更多';
      more.onclick = () => loadHistory(true); content.append(more);
    }
    $('history').replaceChildren(content); historySnapshot = snapshot;
  } catch (error) {$('status').textContent = '加载历史失败：' + error.message;}
  finally {historyLoading = false;}
}
async function refreshUnderstanding() {
  if (mode !== 'understand') return;
  try {queueSummary(await api('/api/queue'));}
  catch (error) {$('queueStatus').textContent = '队列状态加载失败：' + error.message;}
  if (!$('history').hidden) await loadHistory();
}
function selectMode(next) {
  mode = next === 'understand' ? 'understand' : 'download';
  localStorage.setItem('youtubeToolView', mode);
  document.querySelectorAll('[data-mode]').forEach(b => b.setAttribute('aria-selected', String(b.dataset.mode === mode)));
  $('heading').textContent = mode === 'understand' ? '视频理解' : '单地址下载';
  $('hint').textContent = mode === 'understand' ? '下载视频并分析音频和画面，生成摘要、时间线、完整转写与报告。任务按提交顺序排队，可连续添加链接。' : '粘贴 YouTube 视频链接，下载后可预览并保存到本机。支持 watch、短链接、Shorts 和直播回放。';
  $('historyBtn').hidden = mode !== 'understand'; $('queueStatus').hidden = mode !== 'understand';
  $('history').hidden = mode !== 'understand' || localStorage.getItem('youtubeHistoryOpen') !== '1';
  $('result').replaceChildren(); $('status').textContent = ''; syncButton(); refreshUnderstanding();
}
document.querySelectorAll('[data-mode]').forEach(b => b.onclick = () => selectMode(b.dataset.mode));
$('historyBtn').onclick = () => { $('history').hidden = false; localStorage.setItem('youtubeHistoryOpen', '1'); loadHistory(); };
$('form').onsubmit = async event => {
  event.preventDefault(); if (submitting) return;
  const kind = mode; submitting = true; syncButton(); $('status').textContent = '正在创建任务…';
  try {
    const job = await api('/api/' + kind, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({url:$('url').value})});
    jobs.set(job.jobId, kind); latest[kind] = job.jobId; saveJobs();
    if (kind === 'download') downloadBusy = true;
    else {
      $('url').value = ''; $('history').hidden = false; localStorage.setItem('youtubeHistoryOpen', '1');
      $('status').textContent = '已加入视频理解队列，可继续添加链接。'; await refreshUnderstanding();
    }
    poll(job.jobId, kind);
  } catch (error) {$('status').textContent = error.message;}
  finally {submitting = false; syncButton();}
};
let saved = [];
try {saved = JSON.parse(localStorage.getItem('youtubeJobs') || '[]'); if (!Array.isArray(saved)) saved = [];}
catch (_) {}
const legacy = localStorage.getItem('youtubeJob');
if (legacy) {saved.push({id:legacy, kind:'understand'}); localStorage.removeItem('youtubeJob');}
selectMode(new URLSearchParams(location.search).get('view') || localStorage.getItem('youtubeToolView'));
for (const item of saved) {
  if (typeof item.id !== 'string' || !['download','understand'].includes(item.kind)) continue;
  jobs.set(item.id, item.kind); latest[item.kind] = item.id;
  if (item.kind === 'download') downloadBusy = true;
  poll(item.id, item.kind);
}
syncButton(); setInterval(refreshUnderstanding, 5000);
