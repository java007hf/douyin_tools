(function () {
  const VERSION = "0.4.0";
  if (window.__douyinToolsVersion === VERSION) return;
  window.__douyinToolsInjected = true;
  window.__douyinToolsVersion = VERSION;

  const state = {
    captured: [],
    lastCommentListUrl: null,
    profileItems: new Map(),
    profileResponses: []
  };

  function isInteresting(url) {
    return /\/aweme\/v1\/web\/(comment|commit|aweme\/favorite|aweme\/collect)/.test(url);
  }

  function isProfilePostUrl(url) {
    return /\/aweme\/v1\/web\/aweme\/post\//.test(url);
  }

  function firstUrl(value) {
    if (typeof value === "string" && /^https?:\/\//.test(value)) return value;
    if (Array.isArray(value)) {
      for (const item of value) {
        const found = firstUrl(item);
        if (found) return found;
      }
    }
    if (value && typeof value === "object") {
      for (const key of ["url_list", "urlList", "urls"]) {
        const found = firstUrl(value[key]);
        if (found) return found;
      }
    }
    return "";
  }

  function workUrlFromAweme(item) {
    const awemeId = item?.aweme_id || item?.awemeId || item?.id;
    if (!awemeId) return "";
    const isNote = item.aweme_type === 68 || Array.isArray(item.images) || Array.isArray(item.image_infos);
    return `https://www.douyin.com/${isNote ? "note" : "video"}/${awemeId}`;
  }

  function titleFromAweme(item) {
    return item?.desc || item?.caption || item?.title ||
      item?.share_info?.share_title || item?.shareInfo?.shareTitle ||
      workUrlFromAweme(item) || "未命名作品";
  }

  function coverFromAweme(item) {
    const imagePostInfo = item?.image_post_info || item?.imagePostInfo || {};
    const imageGroups = [
      item?.images,
      item?.image_infos,
      item?.imageInfos,
      imagePostInfo.images,
      imagePostInfo.image_infos,
      imagePostInfo.imageInfos
    ];
    for (const images of imageGroups) {
      if (!Array.isArray(images)) continue;
      for (const image of images) {
        for (const key of [
          "url_list", "urlList", "display_image", "displayImage",
          "origin_cover", "originCover", "origin_image", "originImage",
          "thumbnail", "thumbnail_image", "thumbnailImage"
        ]) {
          const found = firstUrl(image?.[key]);
          if (found) return found;
        }
      }
    }

    const video = item?.video || {};
    for (const key of ["cover", "origin_cover", "originCover", "dynamic_cover", "dynamicCover"]) {
      const found = firstUrl(video[key]);
      if (found) return found;
    }
    return "";
  }

  function rememberProfilePayload(url, payload) {
    if (!payload || !Array.isArray(payload.aweme_list)) return;
    const response = {
      time: new Date().toISOString(),
      url,
      count: payload.aweme_list.length,
      hasMore: payload.has_more ?? payload.hasMore ?? null,
      maxCursor: payload.max_cursor ?? payload.maxCursor ?? null
    };
    state.profileResponses.unshift(response);
    state.profileResponses = state.profileResponses.slice(0, 30);

    for (const aweme of payload.aweme_list) {
      const url = workUrlFromAweme(aweme);
      if (!url) continue;
      state.profileItems.set(url, {
        url,
        title: titleFromAweme(aweme),
        cover: coverFromAweme(aweme),
        type: url.includes("/note/") ? "图文" : "视频"
      });
    }
  }

  function remember(url, method, body) {
    if (!isInteresting(url)) return;
    const item = {
      time: new Date().toISOString(),
      method,
      url,
      body: body || null
    };
    state.captured.unshift(item);
    state.captured = state.captured.slice(0, 50);
    if (url.includes("/comment/list/")) state.lastCommentListUrl = url;
  }

  const originalFetch = window.fetch;
  window.fetch = async function (...args) {
    const url = typeof args[0] === "string" ? args[0] : args[0]?.url;
    const method = args[1]?.method || "GET";
    const body = args[1]?.body || null;
    if (url) remember(url, method, body);
    const response = await originalFetch.apply(this, args);
    if (url && isProfilePostUrl(url)) {
      response.clone().json()
        .then((payload) => rememberProfilePayload(url, payload))
        .catch(() => {});
    }
    return response;
  };

  const originalOpen = XMLHttpRequest.prototype.open;
  const originalSend = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__douyinToolsMethod = method;
    this.__douyinToolsUrl = url;
    return originalOpen.call(this, method, url, ...rest);
  };
  XMLHttpRequest.prototype.send = function (body) {
    if (this.__douyinToolsUrl) {
      remember(this.__douyinToolsUrl, this.__douyinToolsMethod || "GET", body);
      this.addEventListener("load", () => {
        if (!isProfilePostUrl(this.__douyinToolsUrl)) return;
        try {
          rememberProfilePayload(this.__douyinToolsUrl, JSON.parse(this.responseText));
        } catch (_) {
          // Ignore non-JSON XHR payloads.
        }
      });
    }
    return originalSend.call(this, body);
  };

  function parseWorkId(inputUrl) {
    const url = new URL(inputUrl || location.href, location.href);
    const modalId = url.searchParams.get("modal_id");
    const vid = url.searchParams.get("vid");
    if (modalId) return modalId;
    if (vid) return vid;
    const match = url.pathname.match(/\/(?:video|note)\/([^/?#]+)/);
    return match ? match[1] : null;
  }

  function defaultParams(workId) {
    return {
      device_platform: "webapp",
      aid: "6383",
      channel: "channel_pc_web",
      aweme_id: workId,
      update_version_code: "170400",
      pc_client_type: "1",
      pc_libra_divert: "Windows",
      support_h265: "1",
      support_dash: "1",
      cpu_core_num: String(navigator.hardwareConcurrency || 8),
      version_code: "170400",
      version_name: "17.4.0",
      cookie_enabled: String(navigator.cookieEnabled),
      screen_width: String(window.screen.width),
      screen_height: String(window.screen.height),
      browser_language: navigator.language || "zh-CN",
      browser_platform: navigator.platform || "Win32",
      browser_name: "Chrome",
      browser_version: navigator.userAgentData?.brands?.[0]?.version || "151.0.0.0",
      browser_online: String(navigator.onLine),
      engine_name: "Blink",
      engine_version: navigator.userAgentData?.brands?.[0]?.version || "151.0.0.0",
      os_name: "Windows",
      os_version: "10",
      device_memory: String(navigator.deviceMemory || 8),
      platform: "PC",
      downlink: String(navigator.connection?.downlink || 10),
      effective_type: navigator.connection?.effectiveType || "4g",
      round_trip_time: String(navigator.connection?.rtt || 50)
    };
  }

  function paramsFromCaptured(workId) {
    const matched = state.captured.find((item) => {
      if (!item.url.includes("/comment/list/")) return false;
      try {
        return new URL(item.url).searchParams.get("aweme_id") === workId;
      } catch (_) {
        return false;
      }
    });
    const sourceUrl = matched?.url || state.lastCommentListUrl;
    if (!sourceUrl) return defaultParams(workId);

    const source = new URL(sourceUrl);
    const params = {};
    source.searchParams.forEach((value, key) => {
      if (!["cursor", "count", "item_type", "a_bogus", "msToken", "verifyFp", "fp"].includes(key)) {
        params[key] = value;
      }
    });
    params.aweme_id = workId;
    return { ...defaultParams(workId), ...params };
  }

  function endpoint(path) {
    return `https://www-hj.douyin.com${path}`;
  }

  async function signedFetch(path, params, method = "GET") {
    const url = new URL(endpoint(path));
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null) url.searchParams.set(key, String(value));
    });

    const options = {
      method,
      credentials: "include",
      headers: { accept: "application/json, text/plain, */*" }
    };
    if (method !== "GET") {
      options.headers["content-type"] = "application/x-www-form-urlencoded; charset=UTF-8";
      options.body = new URLSearchParams(params).toString();
    }

    const response = await fetch(url.toString(), {
      ...options
    });
    const text = await response.text();
    let payload = null;
    try {
      payload = JSON.parse(text);
    } catch (_) {
      payload = null;
    }
    return {
      ok: response.ok,
      status: response.status,
      method,
      url: url.toString(),
      payload,
      text: payload ? null : text.slice(0, 300)
    };
  }

  async function signedFetchAction(path, params, requireField) {
    const first = await signedFetch(path, params, "GET");
    if (success(first, requireField)) return first;

    const second = await signedFetch(path, params, "POST");
    if (success(second, requireField)) return second;

    return {
      ...second,
      attempts: [summarizeResponse(first), summarizeResponse(second)]
    };
  }

  function summarizeResponse(response) {
    const payload = response.payload || {};
    return {
      ok: response.ok,
      status: response.status,
      method: response.method,
      path: new URL(response.url).pathname,
      status_code: payload.status_code,
      status_msg: payload.status_msg,
      log_id: payload.log_pb?.impr_id || payload.log_id || null,
      has_comment: Boolean(payload.comment),
      comment_id: payload.comment?.cid || null,
      raw_text: response.text || null
    };
  }

  function success(result, requireField) {
    if (!result.ok || !result.payload) return false;
    if (![undefined, null, 0].includes(result.payload.status_code)) return false;
    if (result.payload.status_msg && !["success", "ok"].includes(result.payload.status_msg)) return false;
    if (Array.isArray(result.payload.aweme_list)) return false;
    if (requireField && !result.payload[requireField]) return false;
    return true;
  }

  function visible(el) {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.display !== "none" && style.visibility !== "hidden";
  }

  function elementText(el) {
    return [
      el.getAttribute("aria-label") || "",
      el.getAttribute("title") || "",
      el.textContent || ""
    ].join(" ").replace(/\s+/g, " ").trim();
  }

  function reasonableActionElement(el) {
    const rect = el.getBoundingClientRect();
    const text = elementText(el);
    const hasExplicitRole = el.matches("button,[role='button'],[aria-label],[title]");
    const hasIcon = Boolean(el.querySelector("svg,img"));
    const reasonableSize = rect.width >= 12 && rect.height >= 12 &&
      rect.width <= 240 && rect.height <= 240;
    return visible(el) && reasonableSize && text.length <= 120 && (hasExplicitRole || hasIcon);
  }

  function actionCandidates() {
    const primary = Array.from(document.querySelectorAll(
      "button,[role='button'],[aria-label],[title]"
    ));
    const secondary = Array.from(document.querySelectorAll("div,span"))
      .filter((el) => elementText(el).length <= 40 && el.querySelector("svg,img"));
    return primary.concat(secondary);
  }

  async function waitForCapturedPath(pathPart, since, timeoutMs = 3000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const found = state.captured.find((item) =>
        item.time >= since && item.url.includes(pathPart)
      );
      if (found) return found;
      await new Promise((resolve) => setTimeout(resolve, 150));
    }
    return null;
  }

  function clickLabeled(label, alreadyLabels) {
    const elements = actionCandidates();
    const matches = [];
    for (const el of elements) {
      if (!reasonableActionElement(el)) continue;
      const text = elementText(el);
      if (!text.includes(label)) continue;
      if (alreadyLabels.some((item) => text.includes(item))) {
        return { success: true, skipped: true, reason: `already ${label}` };
      }
      matches.push({ el, text, area: el.getBoundingClientRect().width * el.getBoundingClientRect().height });
    }

    matches.sort((a, b) => a.area - b.area);
    const match = matches[0];
    if (match) {
      const clickable = match.el.closest("button,[role='button']") || match.el;
      clickable.click();
      return { success: true, skipped: false, text: match.text.slice(0, 80), candidates: matches.length };
    }

    return { success: false, error: `Cannot find ${label} button` };
  }

  function domDiagnostics() {
    return actionCandidates()
      .filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          tag: el.tagName.toLowerCase(),
          role: el.getAttribute("role"),
          aria: el.getAttribute("aria-label"),
          title: el.getAttribute("title"),
          text: elementText(el).slice(0, 120),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          svg: Boolean(el.querySelector("svg")),
          img: Boolean(el.querySelector("img")),
          className: String(el.className || "").slice(0, 120)
        };
      })
      .filter((item) => item.width >= 8 && item.height >= 8 && item.width <= 320 && item.height <= 320)
      .slice(0, 80);
  }

  function iconDiagnostics() {
    return Array.from(document.querySelectorAll("div,span,button,[role='button']"))
      .filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return { el, rect, text: elementText(el) };
      })
      .filter(({ el, rect, text }) =>
        rect.width >= 20 && rect.height >= 20 &&
        rect.width <= 96 && rect.height <= 96 &&
        text.length <= 40 &&
        (el.querySelector("svg,img") || el.matches("button,[role='button']"))
      )
      .sort((a, b) => (b.rect.x - a.rect.x) || (a.rect.y - b.rect.y));
  }

  async function clickLikelyFavoriteButton() {
    const before = new Set(state.captured.map((item) => item.url));
    const startedAt = new Date().toISOString();

    const candidates = iconDiagnostics();
    const tried = [];
    for (const { el, rect, text } of candidates.slice(0, 30)) {
      const clickable = el.closest("button,[role='button']") || el;
      tried.push({
        text,
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        className: String(el.className || "").slice(0, 80)
      });

      clickable.click();
      const request = await waitForCapturedPath("/aweme/collect/", startedAt, 1000) ||
        await waitForCapturedPath("/aweme/favorite/", startedAt, 1000);
      if (request && !before.has(request.url)) {
        return {
          success: true,
          requestObserved: true,
          clicked: tried[tried.length - 1],
          requestPath: new URL(request.url).pathname
        };
      }
    }

    return {
      success: false,
      error: "Cannot identify favorite icon button",
      tried
    };
  }

  async function waitForWorkReady(workId, timeoutMs = 20000) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      const captured = state.captured.find((item) => {
        if (!item.url.includes("/comment/list/")) return false;
        try {
          return new URL(item.url).searchParams.get("aweme_id") === workId;
        } catch (_) {
          return false;
        }
      });
      if (captured) {
        return { ready: true, reason: "captured-comment-list", url: captured.url.split("?")[0] };
      }

      if (location.href.includes(workId) || document.body.innerText.includes(workId)) {
        return { ready: true, reason: "page-contains-work-id" };
      }

      window.dispatchEvent(new Event("scroll"));
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    return { ready: false, reason: "timeout", href: location.href, diagnostics: domDiagnostics() };
  }

  async function submitCommentViaDom(comment) {
    const startedAt = new Date().toISOString();
    const openComment = clickLabeled("评论", []);
    await new Promise((resolve) => setTimeout(resolve, 800));

    const candidates = [
      "textarea[placeholder*='评论']",
      "input[placeholder*='评论']",
      "[contenteditable='true'][placeholder*='评论']",
      "[contenteditable='true']",
      "textarea",
      "input"
    ];

    let editor = null;
    for (const selector of candidates) {
      editor = Array.from(document.querySelectorAll(selector)).find((el) => {
        const rect = el.getBoundingClientRect();
        return visible(el) && rect.width >= 120 && rect.height >= 20;
      });
      if (editor) break;
    }
    if (!editor) {
      return { success: false, openComment, error: "Cannot find comment editor" };
    }

    editor.focus();
    if (editor.isContentEditable) {
      editor.textContent = comment;
      editor.dispatchEvent(new InputEvent("input", {
        bubbles: true,
        inputType: "insertText",
        data: comment
      }));
    } else {
      editor.value = comment;
      editor.dispatchEvent(new Event("input", { bubbles: true }));
      editor.dispatchEvent(new Event("change", { bubbles: true }));
    }

    await new Promise((resolve) => setTimeout(resolve, 500));

    const sendLabels = ["发布", "发送"];
    for (const label of sendLabels) {
      const elements = actionCandidates();
      const matches = [];
      for (const el of elements) {
        if (!reasonableActionElement(el)) continue;
        const text = elementText(el);
        if (!text.includes(label)) continue;
        matches.push({ el, text, area: el.getBoundingClientRect().width * el.getBoundingClientRect().height });
      }
      matches.sort((a, b) => a.area - b.area);
      if (matches[0]) {
        (matches[0].el.closest("button,[role='button']") || matches[0].el).click();
        const request = await waitForCapturedPath("/comment/publish/", startedAt, 4000);
        return {
          success: Boolean(request),
          method: "dom",
          button: matches[0].text.slice(0, 80),
          requestObserved: Boolean(request)
        };
      }
    }

    return { success: false, method: "dom", error: "Cannot find publish button" };
  }

  async function interact(options) {
    const workId = options.workId || parseWorkId(options.url);
    if (!workId) throw new Error("Cannot parse work id from current URL");

    const readiness = await waitForWorkReady(workId);
    const base = paramsFromCaptured(workId);
    const result = {};

    if (options.like) {
      const response = await signedFetchAction("/aweme/v1/web/commit/item/digg/", {
        ...base,
        type: "1"
      });
      const apiSuccess = success(response);
      result.like = { success: apiSuccess, response: summarizeResponse(response), method: "api" };
      if (!apiSuccess) {
        const startedAt = new Date().toISOString();
        const fallback = clickLabeled("点赞", ["已点赞", "取消点赞"]);
        if (fallback.success && !fallback.skipped) {
          fallback.requestObserved = Boolean(
            await waitForCapturedPath("/commit/item/digg/", startedAt, 3000)
          );
          fallback.success = fallback.requestObserved;
        }
        if (!fallback.success) fallback.diagnostics = domDiagnostics();
        result.like.fallback = fallback;
        result.like.success = Boolean(fallback.success);
        result.like.method = "dom";
      }
    }

    if (options.favorite) {
      let response = await signedFetchAction("/aweme/v1/web/aweme/collect/", {
        ...base,
        action: "1"
      });
      if (!success(response)) {
        response = await signedFetchAction("/aweme/v1/web/aweme/favorite/", {
          ...base,
          action: "1"
        });
      }
      const apiSuccess = success(response);
      result.favorite = { success: apiSuccess, response: summarizeResponse(response), method: "api" };
      if (!apiSuccess) {
        const startedAt = new Date().toISOString();
        const fallback = clickLabeled("收藏", ["已收藏", "取消收藏"]);
        if (fallback.success && !fallback.skipped) {
          fallback.requestObserved = Boolean(
            await waitForCapturedPath("/aweme/favorite/", startedAt, 3000)
          );
          fallback.success = fallback.requestObserved;
        }
        if (!fallback.success) {
          const iconFallback = await clickLikelyFavoriteButton();
          fallback.iconFallback = iconFallback;
          fallback.success = Boolean(iconFallback.success);
        }
        if (!fallback.success) fallback.diagnostics = domDiagnostics();
        result.favorite.fallback = fallback;
        result.favorite.success = Boolean(fallback.success);
        result.favorite.method = "dom";
      }
    }

    if (options.comment) {
      const response = await signedFetchAction("/aweme/v1/web/comment/publish/", {
        ...base,
        text: options.comment,
        text_extra: "[]"
      }, "comment");
      const apiSuccess = success(response, "comment");
      result.comment = { success: apiSuccess, response: summarizeResponse(response), method: "api" };
      if (!apiSuccess) {
        const fallback = await submitCommentViaDom(options.comment);
        if (!fallback.success) fallback.diagnostics = domDiagnostics();
        result.comment.fallback = fallback;
        result.comment.success = Boolean(fallback.success);
        result.comment.method = "dom";
      }
    }

    return {
      version: VERSION,
      workId,
      readiness,
      result,
      capturedCount: state.captured.length,
      usedCapturedCommentList: Boolean(state.lastCommentListUrl)
    };
  }

  function profileItemsResult() {
    return Array.from(state.profileItems.values());
  }

  function scrollProfileContainers() {
    const scrollables = Array.from(document.querySelectorAll("*"))
      .filter((el) => el.scrollHeight > el.clientHeight + 50)
      .map((el) => ({
        el,
        overflowY: getComputedStyle(el).overflowY,
        range: el.scrollHeight - el.clientHeight
      }))
      .filter((item) => item.range > 200)
      .sort((a, b) => b.range - a.range)
      .slice(0, 8);

    window.dispatchEvent(new WheelEvent("wheel", { deltaY: 2200, bubbles: true, cancelable: true }));
    window.scrollTo(0, document.documentElement.scrollHeight);

    for (const { el } of scrollables) {
      el.dispatchEvent(new WheelEvent("wheel", { deltaY: 2200, bubbles: true, cancelable: true }));
      el.scrollTop = Math.min(el.scrollTop + 2200, el.scrollHeight);
      el.dispatchEvent(new Event("scroll", { bubbles: true }));
    }
  }

  async function collectProfile(options) {
    const maxScrolls = Math.max(1, Number(options.maxScrolls || 80));
    const targetCount = Number(options.targetCount || 0);
    const waitMs = Math.max(500, Number(options.waitMs || 1600));
    const startedAt = Date.now();
    let unchanged = 0;
    let lastCount = profileItemsResult().length;

    if (targetCount && lastCount >= targetCount) {
      return {
        version: VERSION,
        href: location.href,
        elapsedMs: Date.now() - startedAt,
        items: profileItemsResult(),
        responses: state.profileResponses,
        capturedPages: state.profileResponses.length
      };
    }

    for (let index = 0; index < maxScrolls; index += 1) {
      scrollProfileContainers();
      await new Promise((resolve) => setTimeout(resolve, waitMs));

      const count = profileItemsResult().length;
      if (targetCount && count >= targetCount) break;
      if (count === lastCount) {
        unchanged += 1;
      } else {
        unchanged = 0;
        lastCount = count;
      }
      if (unchanged >= 12) break;
    }

    return {
      version: VERSION,
      href: location.href,
      elapsedMs: Date.now() - startedAt,
      items: profileItemsResult(),
      responses: state.profileResponses,
      capturedPages: state.profileResponses.length
    };
  }

  window.addEventListener("message", async (event) => {
    if (event.source !== window) return;
    const message = event.data;
    if (!message || message.source !== "douyin-tools-content-v3") return;

    try {
      if (message.action === "getCaptured") {
        window.postMessage({
          id: message.id,
          source: "douyin-tools-page",
          ok: true,
          version: VERSION,
          captured: state.captured,
          workId: parseWorkId(location.href)
        }, "*");
        return;
      }

      if (message.action === "interactV3") {
        const data = await interact(message);
        window.postMessage({ id: message.id, source: "douyin-tools-page", ok: true, data }, "*");
        return;
      }

      if (message.action === "collectProfile") {
        const data = await collectProfile(message);
        window.postMessage({ id: message.id, source: "douyin-tools-page", ok: true, data }, "*");
      }
    } catch (error) {
      window.postMessage({
        id: message.id,
        source: "douyin-tools-page",
        ok: false,
        error: String(error && error.message || error)
      }, "*");
    }
  });
})();
