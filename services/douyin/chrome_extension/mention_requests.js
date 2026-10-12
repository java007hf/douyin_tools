// Installed in MAIN at document_start, before the site's first account/notice requests.
// Credentials and complete request templates stay in this closure, never in the local task trace.
(function () {
  if (window.__douyinMentionRequests) return;
  const nativeFetch = window.fetch;
  const templates = new Map();
  const items = new Map();
  const history = [];
  let accountId = '';
  let accountTemplate = null;
  let ready = false;
  let lastSuccess = 0;
  let accountEpoch = 0;
  const pending = new Set();
  const REPLAY = Symbol('mention-read-replay');
  const stableId = value => typeof value === 'string' && /^\d+$/.test(value) ? value :
    Number.isSafeInteger(value) && value >= 0 ? String(value) : '';

  function classify(input) {
    let url;
    try { url = new URL(input, location.href); } catch (_) { return null; }
    if (url.protocol !== 'https:' || !['www.douyin.com', 'www-hj.douyin.com'].includes(url.hostname)) return null;
    if (/\/user\/(?:profile\/)?self\//.test(url.pathname)) return {kind: 'account', url};
    if (/\/(?:notice|notification)\//.test(url.pathname) &&
        !/\/(?:publish|delete|remove|read|mark|clear|ack|update|setting)\//.test(url.pathname)) {
      return {kind: 'notice', url};
    }
    return null;
  }

  function decode(text) {
    // Native JSON.parse rounds 64-bit numeric IDs. Preserve integer tokens before parsing.
    // Match complete JSON string tokens too, so digits inside quoted text remain untouched.
    return JSON.parse(text.replace(/"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, token => {
      if (/^-?\d{16,}$/.test(token) && !Number.isSafeInteger(Number(token))) return `"${token}"`;
      return token;
    }));
  }

  function parseNotices(payload, atEndpoint) {
    let recognized = atEndpoint;
    let skipped = 0;
    let count = 0;
    let budget = 10000;
    const seen = new WeakSet();
    const v2 = Array.isArray(payload.notice_list_v2) ? payload.notice_list_v2 : [];
    if (Array.isArray(payload.notice_list_v2)) recognized = true;
    for (const notice of v2) {
      const at = notice?.at;
      if (!at || typeof at !== 'object') continue;
      let schema;
      try { schema = new URL(at.schema_url || notice.general_notice?.schema_url || '', location.href); } catch (_) {}
      const params = schema?.searchParams;
      const root = at.level1_comment || {};
      const reply = at.reply_comment || {};
      const work = stableId(notice.aweme_id || at.aweme?.aweme_id || params?.get('aweme_id') || params?.get('item_id') ||
        schema?.pathname.match(/\/(?:detail|video|aweme)\/(\d+)/)?.[1]);
      const cid = stableId(reply.cid || reply.comment_id || params?.get('reply_comment_id') ||
        params?.get('comment_id') || params?.get('cid') || params?.get('commentId') || root.cid || root.comment_id);
      const rootId = stableId(root.cid || root.comment_id || params?.get('level1_comment_id'));
      if (!work || !cid) { skipped++; continue; }
      const stamp = Number(notice.create_time || reply.create_time || root.create_time || 0);
      items.set(`${work}:${cid}`, {work_id:work, comment_id:cid,
        parent_id:rootId && rootId !== cid && rootId !== '0' ? rootId : '',
        text:String(reply.text || root.text || at.content || ''), author:String(at.user_info?.nickname || ''),
        source_timestamp:Number.isFinite(stamp) ? (stamp > 1e12 ? stamp/1000 : stamp) : 0,
        source:'request', notice_id:stableId(notice.nid_str || notice.nid)});
      if (items.size > 500) items.delete(items.keys().next().value);
      count++;
    }
    function walk(value, mentionScope, depth) {
      if (!value || typeof value !== 'object' || depth > 12 || --budget < 0 || seen.has(value)) return;
      seen.add(value);
      if (Array.isArray(value)) {
        value.forEach(child => walk(child, mentionScope, depth + 1));
        return;
      }
      const label = [value.type, value.notice_type, value.content, value.title, value.description].join(' ');
      const marked = mentionScope || /^(?:at|mention|comment_at)$/.test(String(value.type || value.notice_type || '')) ||
        /在评论中(?:提到了你|@了你)/.test(label);
      const comment = value.comment || value.comment_info || value;
      const aweme = value.aweme || value.aweme_info || comment.aweme || {};
      const work = stableId(value.aweme_id || comment.aweme_id || aweme.aweme_id);
      const cid = stableId(comment.cid || comment.comment_id || value.comment_id);
      if (marked && (value.comment || value.comment_info || value.comment_id || value.cid)) {
        recognized = true;
        if (work && cid) {
          const parent = stableId(comment.reply_id);
          const stamp = Number(value.create_time || value.timestamp || comment.create_time || 0);
          items.set(`${work}:${cid}`, {work_id: work, comment_id: cid,
            parent_id: parent === '0' ? '' : parent,
            text: String(comment.text || ''), author: String(comment.user?.nickname || value.user?.nickname || ''),
            source_timestamp: Number.isFinite(stamp) ? (stamp > 1e12 ? stamp / 1000 : stamp) : 0,
            source: 'request'});
          if (items.size > 500) items.delete(items.keys().next().value);
          count++;
        } else skipped++;
      }
      for (const [key, child] of Object.entries(value)) {
        if (key === 'notice_list_v2') continue; // Explicit adapter owns v2 records and their parent binding.
        const atList = /^(?:at_list|mention_list|mentions|at_comment_list)$/.test(key);
        if (atList && Array.isArray(child)) recognized = true;
        // Scope is inherited only down a known mention list/record, never across sibling lists.
        walk(child, marked || atList, depth + 1);
      }
    }
    walk(payload, atEndpoint, 0);
    return {recognized, count, skipped};
  }

  function keyFor(template) {
    const url = new URL(template.url);
    for (const key of ['a_bogus', 'msToken', 'verifyFp', 'fp', '_', 'timestamp']) url.searchParams.delete(key);
    return `${template.method}:${url.href}:${template.body || ''}`;
  }

  function safeDiagnostic(template, fields) {
    // Only endpoint paths, methods, field names, counts and explicit result codes leave the page.
    const url = new URL(template.url);
    return {path: url.pathname, method: template.method, transport: template.transport,
      request_fields: [...url.searchParams.keys()].filter(key => !/token|bogus|verify|^fp$/i.test(key)),
      time: Date.now() / 1000, ...fields};
  }

  function responseSchema(value, depth = 0) {
    if (value === null) return 'null';
    if (depth >= 5) return Array.isArray(value) ? 'array' : typeof value;
    if (Array.isArray(value)) return value.slice(0, 2).map(child => responseSchema(child, depth + 1));
    if (typeof value !== 'object') return typeof value;
    return Object.fromEntries(Object.entries(value).slice(0, 20).map(([key, child]) => [key,
      ['type', 'notice_type'].includes(key) && (Number.isSafeInteger(child) ||
        ['at', 'mention', 'comment_at'].includes(child)) ? child : responseSchema(child, depth + 1)]));
  }

  function ingest(template, payload, httpStatus, epoch) {
    const match = classify(template.url);
    if (!match) return false;
    if (epoch !== accountEpoch && !(epoch === 0 && accountEpoch === 1)) return false;
    const statusCode = payload?.status_code;
    if (httpStatus < 200 || httpStatus >= 300 || !payload || typeof payload !== 'object' ||
        (statusCode !== undefined && statusCode !== null && statusCode !== 0)) {
      record(template, {ok: false, http_status: httpStatus, status_code: statusCode ?? null,
        error: '读取请求失败，需刷新页面重新捕获有效请求（登录态或签名可能过期）'});
      return false;
    }
    if (match.kind === 'account') {
      const uid = stableId(payload.user?.uid || payload.user_info?.uid);
      if (!uid) {
        record(template, {ok: false, http_status: httpStatus, error: '个人资料响应中缺少账号 UID'});
        return false;
      }
      if (uid !== accountId) {
        accountEpoch++;
        // Initial notice/account responses can arrive in either order in the same navigation.
        if (accountId) { items.clear(); templates.clear(); ready = false; lastSuccess = 0; }
        accountId = uid;
      }
      accountTemplate = template;
      return true;
    }
    const parsed = parseNotices(payload, /\/(?:at|mention)\//.test(match.url.pathname));
    const diagnostic = {ok: parsed.recognized, http_status: httpStatus, status_code: statusCode ?? null,
      recognized: parsed.recognized, item_count: parsed.count, skipped_count: parsed.skipped,
      response_fields: Object.keys(payload).slice(0, 30), has_more: Boolean(payload.has_more),
      response_schema: responseSchema(payload),
      mention_samples: v2Samples(payload),
      error: parsed.recognized ? '' : '已捕获通知响应，但尚未识别 @通知结构，需核实真实响应字段'};
    record(template, diagnostic);
    // A POST is replayable only after its response proves this is a list read.
    if (template.method === 'GET' || (template.method === 'POST' && parsed.recognized)) {
      const key = keyFor(template);
      templates.set(key, {...template, recognized: parsed.recognized, captured_at: Date.now() / 1000});
      if (templates.size > 8) templates.delete(templates.keys().next().value);
    }
    if (parsed.recognized) {
      ready = true;
      lastSuccess = Date.now() / 1000;
    }
    return parsed.recognized;
  }

  function record(template, fields) {
    history.push(safeDiagnostic(template, fields));
    if (history.length > 20) history.shift();
  }

  function v2Samples(payload) {
    return (Array.isArray(payload.notice_list_v2) ? payload.notice_list_v2 : []).filter(n => n?.at).slice(0,5).map(n => {
      let schema;
      try { schema = new URL(n.at.schema_url || '',location.href); } catch (_) {}
      return {author:String(n.at.user_info?.nickname || ''), notice_id:stableId(n.nid_str || n.nid),
        work_id:stableId(n.aweme_id || n.at.aweme?.aweme_id),
        schema_path:schema?.pathname || '',
        schema_ids: Object.fromEntries([...(schema?.searchParams || [])].filter(([key,value]) =>
          /^(?:comment_id|reply_comment_id|cid|commentId|level1_comment_id|aweme_id|item_id)$/.test(key) && stableId(value))),
        comment_fields:Object.keys(n.at.reply_comment || {}), root_fields:Object.keys(n.at.level1_comment || {})};
    });
  }

  function track(promise) {
    pending.add(promise);
    promise.finally(() => pending.delete(promise)).catch(() => {});
  }

  async function fetchTemplate(input, options = {}) {
    const requestInput = typeof Request !== 'undefined' && input instanceof Request;
    const url = typeof input === 'string' ? input : input?.url || String(input);
    if (!classify(url)) return null;
    const method = String(options.method || (requestInput ? input.method : 'GET')).toUpperCase();
    if (!['GET', 'POST'].includes(method)) return null;
    const headers = Object.fromEntries(new Headers(options.headers || (requestInput ? input.headers : undefined)));
    let body = options.body;
    if (body === undefined && requestInput && method === 'POST') body = await input.clone().text();
    if (body instanceof URLSearchParams) body = body.toString();
    if (body !== undefined && body !== null && typeof body !== 'string') return null;
    return {url: new URL(url, location.href).href, method, headers, body: method === 'POST' ? body || '' : null,
      transport: 'fetch', credentials: options.credentials || (requestInput ? input.credentials : 'same-origin'),
      referrer: options.referrer ?? (requestInput ? input.referrer : undefined),
      referrerPolicy: options.referrerPolicy ?? (requestInput ? input.referrerPolicy : undefined)};
  }

  window.fetch = async function (input, options) {
    const epoch = accountEpoch;
    const templatePromise = options?.[REPLAY] ? Promise.resolve(null) : fetchTemplate(input, options).catch(() => null);
    const response = await nativeFetch.apply(this, arguments);
    track(templatePromise.then(async template => {
      if (!template) return;
      try { ingest(template, decode(await response.clone().text()), response.status, epoch); }
      catch (_) { record(template, {ok: false, http_status: response.status, error: '响应不是可解析的 JSON'}); }
    }));
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  const originalHeader = XMLHttpRequest.prototype.setRequestHeader;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__mentionReadRequest = {url: new URL(url, location.href).href, method: String(method).toUpperCase(),
      headers: {}, transport: 'xhr', credentials: 'include'};
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.setRequestHeader = function (name, value) {
    if (this.__mentionReadRequest) {
      const key = String(name).toLowerCase();
      const headers = this.__mentionReadRequest.headers;
      headers[key] = headers[key] ? headers[key] + ', ' + value : String(value);
    }
    return originalHeader.call(this, name, value);
  };
  XMLHttpRequest.prototype.send = function (body) {
    const template = this.__mentionReadRequest;
    const epoch = accountEpoch;
    if (!this[REPLAY] && template && classify(template.url) && ['GET', 'POST'].includes(template.method) &&
        (body == null || typeof body === 'string' || body instanceof URLSearchParams)) {
      template.body = template.method === 'POST' ? String(body || '') : null;
      template.credentials = this.withCredentials ? 'include' : 'same-origin';
      this.addEventListener('load', () => {
        try {
          // Read responseText whenever possible to preserve integer precision.
          const payload = this.responseType === 'json' ? this.response : decode(this.responseText);
          ingest(template, payload, this.status, epoch);
        } catch (_) { record(template, {ok: false, http_status: this.status, error: 'XHR 响应无法解析'}); }
      });
    }
    return originalSend.call(this, body);
  };

  async function replay(template) {
    const epoch = accountEpoch;
    if (template.transport === 'xhr') {
      return new Promise(resolve => {
        const xhr = new XMLHttpRequest();
        xhr[REPLAY] = true;
        xhr.addEventListener('load', () => {
          try { resolve(ingest(template, decode(xhr.responseText), xhr.status, epoch)); }
          catch (_) { record(template, {ok: false, http_status: xhr.status, error: 'XHR 响应无法解析'}); resolve(false); }
        });
        for (const name of ['error', 'timeout', 'abort']) xhr.addEventListener(name, () => {
          record(template, {ok: false, error: 'XHR 请求超时或失败，请刷新页面重新捕获请求'});
          resolve(false);
        });
        try {
          xhr.open(template.method, template.url, true);
          xhr.timeout = 8000;
          xhr.withCredentials = template.credentials === 'include';
          for (const [name, value] of Object.entries(template.headers)) xhr.setRequestHeader(name, value);
          xhr.send(template.method === 'POST' ? template.body : null);
        } catch (_) {
          record(template, {ok: false, error: 'XHR 请求无法重放，请重新捕获读取请求'});
          resolve(false);
        }
      });
    }
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      // Enter the page's current fetch chain so its runtime middleware can run.
      // Preserve the observed request exactly; do not manufacture a_bogus or extend signatures.
      const response = await window.fetch(template.url, {method: template.method, headers: template.headers,
        credentials: template.credentials, ...(template.method === 'POST' ? {body: template.body} : {}),
        ...(template.referrer !== undefined ? {referrer: template.referrer} : {}),
        ...(template.referrerPolicy !== undefined ? {referrerPolicy: template.referrerPolicy} : {}),
        signal: controller.signal, [REPLAY]: true});
      return ingest(template, decode(await response.clone().text()), response.status, epoch);
    } catch (_) {
      record(template, {ok: false, error: '请求超时或网络失败，请刷新页面重新捕获请求'});
      return false;
    } finally { clearTimeout(timer); }
  }

  window.__douyinMentionRequests = Object.freeze({
    decodeJSON: decode,
    captureState() {
      return {account_ready: Boolean(accountTemplate), notice_ready: [...templates.values()].some(t => t.recognized)};
    },
    async collect() {
      await Promise.allSettled([...pending]);
      // Verify the live account before replaying cached notice templates or publishing a reply.
      const accountOk = accountTemplate ? await replay(accountTemplate) : false;
      const candidates = accountOk ? [...templates.values()].filter(t => t.recognized) : [];
      const result = await Promise.all(candidates.map(replay));
      await Promise.allSettled([...pending]);
      const fresh = accountOk && result.some(Boolean);
      const warning = !accountOk ? '未确认当前登录账号，请刷新个人主页重新捕获个人资料请求' :
        !candidates.length ? '请打开通知 → @我的以捕获读取请求；当前通知结构尚未识别' :
        !fresh ? '本次通知请求全部失败，缓存不作为有效轮询；请刷新页面重新捕获请求' : '';
      return {items: fresh ? Array.from(items.values()) : [], account_id: accountId,
        ready: ready && fresh, fresh, source: 'request', last_success: lastSuccess,
        diagnostics: history.slice(-8), warning};
    },
    async verifyAccount(expected) {
      await Promise.allSettled([...pending]);
      if (!accountTemplate || !await replay(accountTemplate) || accountId !== expected) {
        throw new Error('当前登录账号无法确认或已切换，已停止回复');
      }
    }
  });
})();
