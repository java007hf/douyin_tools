(() => {
  const form = document.querySelector('#mock-doubao-form');
  const status = form.querySelector('.status:last-child');
  const button = form.querySelector('button[type="submit"]');
  let original = {};
  const reveal = form.querySelector('#doubao-reveal');
  reveal.onclick = () => {
    const show = form.elements.token.type === 'password';
    ['token', 'cookie'].forEach(key => { form.elements[key].type = show ? 'text' : 'password'; });
    reveal.textContent = show ? '隐藏 Token / Cookie' : '显示 Token / Cookie';
  };
  async function fillCredentials() {
    const response = await fetch('/api/mock-doubao/credentials', {cache: 'no-store'});
    const value = await response.json();
    if (!response.ok) throw Error(value.error || '读取凭据失败');
    ['token', 'cookie', 'headers', 'request_config', 'model_routes', 'web_request', 'web_video_request'].forEach(key => {
      const text = typeof value[key] === 'string' ? value[key] : JSON.stringify(value[key], null, 2);
      form.elements[key].value = text;
      original[key] = text;
    });
  }
  const describe = value => `${value.configured ? '请求模板已配置' : '尚未配置请求模板'} · Token ${value.token_configured ? '已配置' : '未配置'} · Cookie ${value.cookie_configured ? '已配置' : '未配置'} · ${value.protocol==='web_chat_completion'?'网页生图/视频协议':'旧 Android 协议'}（配置状态不代表登录有效性）`;
  button.disabled = true;
  fetch('/api/mock-doubao', {cache: 'no-store'}).then(async response => {
    const value = await response.json();
    if (!response.ok) throw Error(value.error || '读取豆包配置失败');
    ['base_url', 'endpoint', 'timeout'].forEach(key => { form.elements[key].value = value[key]; });
    await fillCredentials();
    status.textContent = describe(value);
    button.disabled = false;
  }).catch(error => { status.textContent = error.message; });
  form.onsubmit = async event => {
    event.preventDefault();
    button.disabled = true;
    try {
      const values = Object.fromEntries(new FormData(form));
      ['token', 'cookie', 'headers', 'request_config', 'model_routes', 'web_request', 'web_video_request'].forEach(key => { if (values[key] === original[key]) delete values[key]; });
      for (const key of ['headers', 'request_config', 'model_routes', 'web_request', 'web_video_request']) {
        if (values[key] === undefined) continue;
        if (!values[key].trim()) { delete values[key]; continue; }
        try { values[key] = JSON.parse(values[key]); }
        catch (_) { throw Error(key === 'headers' ? '请求头 JSON 格式不正确' : key === 'model_routes' ? '模型路由 JSON 格式不正确' : '完整模板 JSON 格式不正确'); }
      }
      // A pasted complete template owns its endpoint and timeout unless omitted.
      for (const key of ['base_url', 'endpoint', 'timeout']) {
        if (values.request_config?.[key] !== undefined) delete values[key];
      }
      const response = await fetch('/api/mock-doubao', {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(values)
      });
      const value = await response.json();
      if (!response.ok) throw Error(value.error || '保存失败');
      await fillCredentials();
      ['base_url', 'endpoint', 'timeout'].forEach(key => { form.elements[key].value = value.config[key]; });
      status.textContent = '已保存，下次生成生效。' + describe(value.config);
    } catch (error) { status.textContent = error.message; }
    finally { button.disabled = false; }
  };
})();
