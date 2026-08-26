async function activeTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs[0]?.id) throw new Error("No active tab");
  return tabs[0];
}

async function send(action, payload = {}) {
  const tab = await activeTab();
  return chrome.tabs.sendMessage(tab.id, {
    source: "douyin-tools-background-v3",
    action: action === "interact" ? "interactV3" : action,
    url: tab.url,
    ...payload
  });
}

function show(value) {
  document.getElementById("output").textContent =
    typeof value === "string" ? value : JSON.stringify(value, null, 2);
}

document.getElementById("run").addEventListener("click", async () => {
  try {
    const comment = document.getElementById("comment").value.trim();
    const like = document.getElementById("like").checked;
    const favorite = document.getElementById("favorite").checked;
    if (!comment && !like && !favorite) {
      show("Choose like, favorite, or enter a comment.");
      return;
    }
    const result = await send("interact", { comment, like, favorite });
    show(result);
  } catch (error) {
    show(String(error && error.message || error));
  }
});

document.getElementById("copy").addEventListener("click", async () => {
  try {
    const result = await send("getCaptured");
    const text = JSON.stringify(result, null, 2);
    await navigator.clipboard.writeText(text);
    show("Captured request data copied.");
  } catch (error) {
    show(String(error && error.message || error));
  }
});
