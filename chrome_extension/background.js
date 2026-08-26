const BRIDGE_BASE = "http://127.0.0.1:18765";
const EXTENSION_VERSION = "0.4.0";
let busy = false;

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

async function sendToContent(tabId, command) {
  await chrome.scripting.executeScript({
    target: { tabId },
    files: ["content.js"]
  });

  try {
    return await chrome.tabs.sendMessage(tabId, {
      source: "douyin-tools-background-v3",
      action: command.action || "interactV3",
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
    });
  } catch (error) {
    return chrome.tabs.sendMessage(tabId, {
      source: "douyin-tools-background-v3",
      action: command.action || "interactV3",
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
    });
  }
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

  try {
    let tab;
    if (command.openUrl || command.url) {
      tab = await chrome.tabs.create({ url: command.openUrl || command.url, active: true });
      await waitForTabLoaded(tab.id);
      await new Promise((resolve) => setTimeout(resolve, 8000));
    } else {
      tab = await findDouyinTab();
    }

    const result = await sendToContent(tab.id, command);
    await reportResult({ id: command.id, ok: true, result });
  } catch (error) {
    console.error(`Douyin Tools ${EXTENSION_VERSION}: command failed`, error);
    await reportResult({
      id: command.id,
      ok: false,
      error: String(error && error.message || error)
    });
  } finally {
    busy = false;
  }
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.alarms.create("douyin-tools-poll", { periodInMinutes: 1 });
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === "douyin-tools-poll") pollOnce().catch(() => {});
});

setInterval(() => {
  pollOnce().catch(() => {});
}, 1000);
