const BRIDGE_BASE = "http://127.0.0.1:18765";
const EXTENSION_VERSION = chrome.runtime.getManifest().version;
let busy = false;
let activeCommandId = null;

async function bridgeFetch(path, options = {}) {
  try {
    const response = await fetch(`${BRIDGE_BASE}${path}`, {
      ...options,
      headers: {
        "content-type": "application/json",
        ...(options.headers || {})
      }
    });
    return response.json();
  } catch (error) {
    return {
      ok: false,
      bridgeOffline: true,
      error: String(error && error.message || error)
    };
  }
}

async function reportResult(payload) {
  try {
    await bridgeFetch("/result", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  } catch (_) {
    // The local Python bridge may have already timed out or may not be running.
  }
}

async function reportProgress(data) {
  if (!activeCommandId) return;
  await bridgeFetch("/progress", {
    method: "POST",
    body: JSON.stringify({ id: activeCommandId, data })
  });
}

async function findDouyinTab() {
  const tabs = await chrome.tabs.query({ url: "https://www.douyin.com/*" });
  if (!tabs.length) throw new Error("No open douyin.com tab found");
  const active = tabs.find((tab) => tab.active) || tabs[0];
  return active;
}

async function waitForTabLoaded(tabId, timeoutMs = 30000) {
  const startedAt = Date.now();
  while (Date.now() - startedAt < timeoutMs) {
    const tab = await chrome.tabs.get(tabId);
    if (tab.status === "complete") return tab;
    await new Promise((resolve) => setTimeout(resolve, 300));
  }
  return chrome.tabs.get(tabId);
}

async function openCommandTab(command) {
  let lastError;
  for (let attempt = 0; attempt < 2; attempt += 1) {
    try {
      const tab = await chrome.tabs.create({ url: command.openUrl || command.url, active: true });
      await waitForTabLoaded(tab.id);
      await new Promise((resolve) => setTimeout(resolve, 8000));
      return tab;
    } catch (error) {
      lastError = error;
      if (!String(error && error.message || error).includes("No tab with id") || attempt === 1) {
        throw error;
      }
    }
  }
  throw lastError;
}

async function sendToContent(tabId, command) {
  const message = {
      source: "douyin-tools-background-v3",
      action: command.action || "interactV3",
      requestId: command.id,
      url: command.url,
      profileUrl: command.profileUrl,
      workId: command.workId,
      replyId: command.replyId,
      parentId: command.parentId,
      accountId: command.accountId,
      forceCapture: Boolean(command.forceCapture),
      comment: command.comment || "",
      like: Boolean(command.like),
      favorite: Boolean(command.favorite),
      maxScrolls: command.maxScrolls,
      targetCount: command.targetCount,
      waitMs: command.waitMs,
      timeoutMs: command.timeoutMs
  };

  let lastError;
  for (let attempt = 0; attempt < 5; attempt += 1) {
    try {
      await chrome.scripting.executeScript({
        target: { tabId },
        files: ["content.js"]
      });
      await new Promise((resolve) => setTimeout(resolve, 500 + attempt * 500));
      return await chrome.tabs.sendMessage(tabId, message);
    } catch (error) {
      lastError = error;
      if (!String(error && error.message || error).includes("Receiving end does not exist")) {
        throw error;
      }
    }
  }
  throw new Error(`Douyin page extension script was not ready after retries: ${lastError?.message || lastError}`);
}

async function pollOnce() {
  if (busy) return;

  let command;
  const response = await bridgeFetch("/command");
  if (!response.ok && response.bridgeOffline) {
    // Python bridge is usually offline until a command is running.
    return;
  }
  command = response.command;

  if (!command || !command.id) return;
  busy = true;
  activeCommandId = command.id;

  try {
    let tab = (command.openUrl || command.url)
      ? await openCommandTab(command)
      : await findDouyinTab();
    let result;
    try {
      result = await sendToContent(tab.id, command);
    } catch (error) {
      const message = String(error && error.message || error);
      if (!/(No tab with id|Receiving end does not exist)/.test(message) || !(command.openUrl || command.url)) {
        throw error;
      }
      console.warn(`Douyin Tools ${EXTENSION_VERSION}: tab disappeared, reopening once`);
      tab = await openCommandTab(command);
      result = await sendToContent(tab.id, command);
    }
    await reportResult({ id: command.id, ok: true, result });
  } catch (error) {
    console.error(`Douyin Tools ${EXTENSION_VERSION}: command failed`, error);
    await reportResult({
      id: command.id,
      ok: false,
      error: String(error && error.message || error)
    });
  } finally {
    activeCommandId = null;
    busy = false;
  }
}

chrome.runtime.onMessage.addListener((message) => {
  if (!message || message.source !== "douyin-tools-progress-v3") return;
  reportProgress(message.data || {}).catch(() => {});
});

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("douyin-tools-poll", { periodInMinutes: 1 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "douyin-tools-poll") pollOnce().catch(() => {});
});

setInterval(() => {
  pollOnce().catch(() => {});
}, 1000);

// Independent transport: existing manual collection/interaction bridge keeps port 18765.
let mentionBusy = false;
const mentionRecoveryAt = new Map();
const mentionNeedsCapture = new Set();
async function ensureMentionTab(command) {
  const tabs = await chrome.tabs.query({url: 'https://www.douyin.com/user/self*'});
  let tab = tabs.find(t => t.active) || tabs[0];
  if (!tab) {
    if (command.action === 'replyMention') throw new Error('原抖音标签页已关闭，未发送回复');
    tab = await chrome.tabs.create({url:'https://www.douyin.com/user/self?from_tab_name=main&showTab=favorite_collection',active:false});
    await waitForTabLoaded(tab.id);
  }
  if (command.action !== 'collectMentions') return tab;
  const prepare = {...command, action:'prepareMentionCapture', timeoutMs:12000,
    forceCapture:mentionNeedsCapture.has(tab.id)};
  let result;
  try { result = await sendToContent(tab.id, prepare); }
  catch (error) { result = {ok:false,error:String(error.message || error)}; }
  if ((!result?.ok || !result.data?.account_ready || mentionNeedsCapture.has(tab.id)) &&
      Date.now() - (mentionRecoveryAt.get(tab.id) || 0) > 300000) {
    // Refresh read-only page capture at most once per five minutes; never retry a publish.
    mentionRecoveryAt.set(tab.id,Date.now());
    await chrome.tabs.reload(tab.id);
    await waitForTabLoaded(tab.id);
    result = await sendToContent(tab.id,{...prepare,forceCapture:true});
  }
  if (!result?.ok) throw new Error(result?.error || '自动准备通知请求失败');
  return tab;
}
async function pollMentions() {
  if (mentionBusy || busy) return;
  mentionBusy = true;
  try {
    const response = await fetch('http://127.0.0.1:18766/command');
    const {command, token} = await response.json();
    if (!command) return;
    let outcome;
    try {
      const tab = await ensureMentionTab(command);
      const result = await sendToContent(tab.id, command);
      if (!result?.ok) throw new Error(result?.error || '页面扩展读取失败');
      if (command.action === 'collectMentions') {
        if (result.data?.fresh) mentionNeedsCapture.delete(tab.id);
        else mentionNeedsCapture.add(tab.id);
      }
      outcome = {id: command.id, ok: true, ...result.data};
    } catch (error) {
      outcome = {id: command.id, ok: false, error: String(error.message || error)};
    }
    await fetch('http://127.0.0.1:18766/result', {method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Mention-Token': token}, body: JSON.stringify(outcome)});
  } catch (_) {
    // Monitor only binds the loopback transport after the user starts it.
  } finally {
    mentionBusy = false;
  }
}
setInterval(() => pollMentions().catch(() => {}), 5000);
chrome.alarms.onAlarm.addListener(alarm => {
  if (alarm.name === 'douyin-tools-poll') pollMentions().catch(() => {});
});
chrome.runtime.onStartup.addListener(() => {
  chrome.alarms.create('douyin-tools-poll',{periodInMinutes:1});
  pollMentions().catch(() => {});
});
