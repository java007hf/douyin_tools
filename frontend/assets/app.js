const tabs = document.querySelector('#tabs');
const workspace = document.querySelector('#workspace');
const status = document.querySelector('#status');
let tabData = [];
const frames = new Map();

function activate(tab) {
  document.querySelectorAll('.tab').forEach((button) => button.classList.toggle('active', button.dataset.id === tab.id));
  tabData.forEach((item) => {
    const frame = frames.get(item.id);
    if (frame) frame.hidden = item.id !== tab.id;
  });
  let frame = frames.get(tab.id);
  if (!frame) {
    frame = document.createElement('iframe');
    frame.className = 'frame';
    frame.title = tab.title;
    frame.src = tab.url;
    frames.set(tab.id, frame);
    workspace.appendChild(frame);
  }
  frame.hidden = false;
  document.title = `${tab.title} · Douyin Studio`;
}

async function boot() {
  try {
    const endpoint = new URL('/api/tabs', window.location.origin);
    endpoint.search = window.location.search.replace(/^\?/, '');
    const response = await fetch(endpoint);
    if (!response.ok) throw new Error('Tab 配置加载失败');
    tabData = (await response.json()).tabs || [];
    tabs.replaceChildren();
    tabData.forEach((tab, index) => {
      const button = document.createElement('button');
      button.className = 'tab';
      button.dataset.id = tab.id;
      button.dataset.short = tab.id === 'douyin' ? '抖' : tab.id === 'video-creator' ? 'AI' : '控';
      button.textContent = tab.title;
      button.title = tab.description;
      button.addEventListener('click', () => activate(tab));
      tabs.appendChild(button);
      if (index === 0) activate(tab);
    });
    status.textContent = `${tabData.length} 个功能模块已加载`;
  } catch (error) {
    status.textContent = error.message;
    workspace.innerHTML = '<div class="empty">暂时无法加载功能模块。</div>';
  }
}
boot();
