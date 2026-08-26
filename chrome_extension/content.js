function douyinToolsContentMain() {
  const CONTENT_VERSION = "0.4.0";

  function injectPageScript() {
    const parent = document.documentElement || document.head || document.body;
    if (!parent) {
      setTimeout(injectPageScript, 50);
      return;
    }

    const script = document.createElement("script");
    script.src = `${chrome.runtime.getURL("injected.js")}?v=${CONTENT_VERSION}&t=${Date.now()}`;
    script.onload = () => script.remove();
    script.onerror = () => {
      console.error(`Douyin Tools ${CONTENT_VERSION}: failed to inject page script`);
    };
    parent.appendChild(script);
  }

  injectPageScript();

  if (window.__douyinToolsContentVersion === CONTENT_VERSION) return;

  window.__douyinToolsContentVersion = CONTENT_VERSION;
  const pending = new Map();

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const message = event.data;
    if (!message || message.source !== "douyin-tools-page") return;

    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  });

  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (!message || message.source !== "douyin-tools-background-v3") return false;

    injectPageScript();
    const id = `${Date.now()}-${Math.random().toString(16).slice(2)}`;
    pending.set(id, sendResponse);
    window.postMessage({ ...message, id, source: "douyin-tools-content-v3" }, "*");

    setTimeout(() => {
      if (!pending.has(id)) return;
      pending.get(id)({
        id,
        source: "douyin-tools-page",
        ok: false,
        error: "Timed out waiting for page response"
      });
      pending.delete(id);
    }, Number(message.timeoutMs || 30000));

    return true;
  });
}

try {
  douyinToolsContentMain();
} catch (error) {
  console.error("Douyin Tools content failed", error);
}
