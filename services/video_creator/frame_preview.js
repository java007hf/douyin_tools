(() => {
  const modal = document.createElement("div");
  modal.innerHTML = '<div data-frame-overlay style="position:fixed;inset:0;z-index:20;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(16,24,40,.82)"><div style="max-width:92vw;max-height:92vh;background:#fff;border-radius:8px;padding:14px;position:relative"><button data-frame-close type="button" style="position:absolute;right:10px;top:10px;margin:0;padding:7px 11px;border:0;border-radius:5px;background:#182230;color:#fff;cursor:pointer">关闭</button><img data-frame-image alt="抽帧预览" style="display:block;max-width:88vw;max-height:78vh;object-fit:contain;background:#101828"><a data-frame-download download style="display:inline-block;margin-top:12px;padding:9px 14px;border-radius:5px;background:#0f766e;color:#fff;text-decoration:none">下载图片</a></div></div>';
  document.body.appendChild(modal);
  const overlay = modal.querySelector("[data-frame-overlay]");
  const image = modal.querySelector("[data-frame-image]");
  const download = modal.querySelector("[data-frame-download]");
  function close() { image.removeAttribute("src"); download.removeAttribute("href"); overlay.style.display = "none"; }
  document.addEventListener("click", (event) => {
    const frame = event.target.closest("#frames img");
    if (frame) { image.src = frame.src; download.href = frame.src; download.download = (frame.nextElementSibling?.textContent || "frame.jpg").split(" · ")[0]; overlay.style.display = "flex"; return; }
    if (event.target === overlay || event.target.closest("[data-frame-close]")) close();
  });
})();
