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
