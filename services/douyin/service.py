#!/usr/bin/env python3
"""
Fetch work URLs from a Douyin creator homepage.

Usage:
  python services/douyin/service.py "https://www.douyin.com/user/..." -o cache/urls.txt

First-time setup:
  pip install -r requirements.txt
  python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import http.server
import json
import mimetypes
import os
import re
import shutil
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit, urlunsplit
from urllib.request import Request, urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from playwright.sync_api import Page, Response, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright
from services.core.storage import service_store


NOTE_AWEME_TYPES = {68}
EXTENSION_MANIFEST = Path(__file__).with_name("chrome_extension") / "manifest.json"
EXPECTED_EXTENSION_VERSION = json.loads(EXTENSION_MANIFEST.read_text(encoding="utf-8"))["version"]


@dataclass(frozen=True)
class MediaItem:
    kind: str
    url: str
    extension: str
    label: str = ""
    width: int = 0
    height: int = 0
    bitrate: int = 0


WEB_HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Douyin 素材工作台</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #14171f;
      --muted: #667085;
      --line: #dde2ea;
      --accent: #0f766e;
      --accent-dark: #115e59;
      --danger: #b42318;
      --soft: #eef6f4;
      --shadow: 0 14px 40px rgba(20, 23, 31, .08);
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif;
      background: var(--bg);
      color: var(--ink);
    }
    header {
      padding: 22px 28px 14px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      position: sticky;
      top: 0;
      z-index: 3;
    }
    h1 {
      margin: 0;
      font-size: 22px;
      font-weight: 650;
      letter-spacing: 0;
    }
    main {
      display: grid;
      grid-template-columns: 190px minmax(0, 1fr);
      gap: 18px;
      padding: 18px;
      min-height: calc(100vh - 76px);
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      box-shadow: var(--shadow);
      min-width: 0;
    }
    .left { display: flex; flex-direction: column; gap: 18px; background: transparent; border: 0; box-shadow: none; }
    .box { padding: 18px; }
    h2 {
      margin: 0 0 14px;
      font-size: 16px;
      line-height: 1.3;
    }
    label {
      display: block;
      font-size: 13px;
      color: var(--muted);
      margin: 12px 0 6px;
    }
    input, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 10px 11px;
      font: inherit;
      min-height: 40px;
      outline: none;
      background: #fff;
    }
    input:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(15, 118, 110, .12);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
    }
    .checks {
      display: flex;
      align-items: center;
      gap: 14px;
      margin: 12px 0;
      color: var(--muted);
      font-size: 13px;
      flex-wrap: wrap;
    }
    .checks label {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      margin: 0;
    }
    .checks input { width: auto; min-height: auto; }
    button, .file-link {
      border: 0;
      border-radius: 6px;
      padding: 9px 12px;
      font: inherit;
      cursor: pointer;
      min-height: 38px;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      white-space: nowrap;
    }
    button.primary {
      background: var(--accent);
      color: #fff;
      width: 100%;
      margin-top: 14px;
    }
    button.primary:hover { background: var(--accent-dark); }
    button.secondary, .file-link {
      background: var(--soft);
      color: var(--accent-dark);
    }
    button.ghost {
      background: #f2f4f7;
      color: #344054;
    }
    button:disabled {
      opacity: .55;
      cursor: not-allowed;
    }
    .status {
      margin-top: 12px;
      color: var(--muted);
      font-size: 13px;
      min-height: 20px;
      word-break: break-word;
    }
    .status.error { color: var(--danger); }
    .result {
      padding: 0;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }
    .toolbar {
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .count { color: var(--muted); font-size: 13px; }
    .list { overflow: visible; }
    .row {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 12px;
      padding: 13px 16px;
      border-bottom: 1px solid var(--line);
      align-items: center;
    }
    .url {
      font-size: 13px;
      line-height: 1.45;
      word-break: break-all;
      color: var(--muted);
    }
    .item-main {
      display: grid;
      grid-template-columns: 92px 1fr;
      gap: 12px;
      align-items: center;
      min-width: 0;
    }
    .thumb {
      width: 92px;
      aspect-ratio: 4 / 5;
      border-radius: 6px;
      object-fit: cover;
      background: #eef1f5;
      border: 1px solid var(--line);
    }
    .thumb.empty {
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0;
      color: var(--muted);
      font-size: 12px;
    }
    .title {
      font-size: 14px;
      line-height: 1.45;
      margin-bottom: 5px;
      overflow: hidden;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
    }
    .meta { color: var(--muted); font-size: 12px; margin-bottom: 4px; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }
    .empty {
      padding: 36px 18px;
      color: var(--muted);
      text-align: center;
      font-size: 14px;
    }
    .downloads {
      margin-top: 10px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .item-main .downloads {
      grid-column: 1 / -1;
      margin-top: 0;
    }
    .modal {
      position: fixed;
      inset: 0;
      background: rgba(16, 24, 40, .72);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 22px;
      z-index: 10;
    }
    .modal.open { display: flex; }
    .modal-panel {
      width: min(980px, 96vw);
      max-height: 92vh;
      background: #fff;
      border-radius: 8px;
      overflow: hidden;
      display: grid;
      grid-template-rows: auto 1fr;
    }
    .modal-head {
      padding: 12px 14px;
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      border-bottom: 1px solid var(--line);
    }
    .modal-body {
      padding: 14px;
      overflow: auto;
      display: grid;
      gap: 12px;
      justify-items: center;
      background: #101828;
    }
    .modal-body img, .modal-body video {
      max-width: 100%;
      max-height: 78vh;
      border-radius: 6px;
      background: #000;
    }
    .understanding-result { padding: 24px; border-top: 2px solid #245d83; line-height: 1.75; }
    .understanding-result h2 { margin-bottom: 8px; }
    .understanding-result h3 { margin-top: 22px; }
    .understanding-result .summary-text { white-space: pre-wrap; max-width: 75ch; }
    .understanding-result .tag { display: inline-block; padding: 2px 10px; margin: 0 6px 6px 0; background: #e7f1f8; color: #245d83; border-radius: 4px; }
    .understanding-result video { width: 100%; max-height: 420px; background: #000; }
    .understanding-result .timeline-row { display: flex; gap: 12px; align-items: baseline; margin: 10px 0; }
    .understanding-result .timeline-row button { flex-shrink: 0; }
    .hint { color: #667085; font-size: 12px; line-height: 1.6; }
    [hidden] { display: none !important; }
    .tool-nav { display:flex; flex-direction:column; gap:8px; align-self:start; padding:12px; background:var(--panel); border:1px solid var(--line); border-radius:8px; }
    .tool-nav button { justify-content:flex-start; text-align:left; white-space:normal; background:transparent; color:var(--muted); }
    .tool-nav button[aria-selected="true"] { background:var(--accent); color:#fff; }
    .tool-nav button:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
    .tool-workspace { min-width:0; }
    .tool-page .box { max-width:920px; }
    .tool-page .understanding-result { border-top:1px solid var(--line); }
    @media (max-width: 700px) {
      main { grid-template-columns: 1fr; }
      .tool-nav { flex-direction:row; flex-wrap:wrap; }
      .tool-nav button { flex:1; justify-content:center; }
      .list { max-height: none; }
    }
  </style>
</head>
<body>
  <header><h1>Douyin 素材工作台</h1></header>
  <main>
    <nav class="tool-nav" role="tablist" aria-label="抖音工具功能">
      <button type="button" id="tabCollect" role="tab" data-tool="collect" aria-controls="pageCollect" aria-selected="true">拉取博主素材</button>
      <button type="button" id="tabDownload" role="tab" data-tool="download" aria-controls="pageDownload" aria-selected="false">单地址下载</button>
      <button type="button" id="tabUnderstand" role="tab" data-tool="understand" aria-controls="pageUnderstand" aria-selected="false">视频理解</button>
      <button type="button" id="tabMentions" role="tab" data-tool="mentions" aria-controls="pageMentions" aria-selected="false">@我自动回复</button>
    </nav>
    <div class="tool-workspace">
    <section id="pageMentions" class="tool-page" role="tabpanel" aria-labelledby="tabMentions" hidden>
      <div class="box">
        <h2>@我自动回复</h2>
        <p>服务默认监听并回复新 @通知。监听开关、检查间隔和回复模式在 Admin 控制台的“@我自动回复”中管理。Chrome 需已安装扩展且登录抖音，并配置“视频理解 LLM”。</p>
        <p><a href="https://www.douyin.com/user/self?from_tab_name=main&amp;showTab=favorite_collection" target="_blank" rel="noopener">打开抖音个人主页</a></p>
        <div id="mentionStatus" class="status" role="status" aria-live="polite"></div>
        <details><summary>通知请求状态</summary><pre id="mentionRequests" style="white-space:pre-wrap"></pre></details>
        <div id="mentionItems"></div>
      </div>
    </section>
    <section id="pageCollect" class="tool-page" role="tabpanel" aria-labelledby="tabCollect">
      <div class="box">
        <h2>拉取博主素材</h2>
        <label for="homepageUrl">博主主页地址</label>
        <textarea id="homepageUrl" rows="3" placeholder="https://www.douyin.com/user/..."></textarea>
        <div class="grid">
          <div>
            <label for="targetCount">目标数量</label>
            <input id="targetCount" type="number" min="1" placeholder="不限">
          </div>
        </div>
        <button id="collectBtn" class="primary">拉取列表</button>
        <div id="collectStatus" class="status"></div>
      </div>
      <div id="materialToolbar" class="toolbar">
        <strong>素材列表</strong>
        <span id="count" class="count">0 条</span>
      </div>
      <div id="list" class="list"><div class="empty">输入博主主页地址后开始拉取</div></div>
    </section>
    <section id="pageDownload" class="tool-page" role="tabpanel" aria-labelledby="tabDownload" hidden>
      <div class="box">
        <h2>单地址下载</h2>
        <label for="downloadUrl">作品链接或分享文案</label>
        <textarea id="downloadUrl" rows="3" placeholder="粘贴抖音作品链接或整段分享文案，支持 v.douyin.com 短链接"></textarea>
        <div class="checks">
          <label><input id="allMediaSingle" type="checkbox"> 下载全部候选媒体</label>
          <label><input id="headfulDownload" type="checkbox"> 显示浏览器</label>
        </div>
        <button id="downloadBtn" class="primary">开始下载</button>
        <div id="downloadStatus" class="status"></div>
        <div id="downloadFiles" class="downloads"></div>
      </div>
    </section>
    <section id="pageUnderstand" class="tool-page" role="tabpanel" aria-labelledby="tabUnderstand" hidden>
      <div class="box">
        <h2>视频理解</h2>
        <label for="understandUrl">作品链接或分享文案</label>
        <textarea id="understandUrl" rows="3" placeholder="粘贴抖音作品链接或分享文案"></textarea>
        <div class="checks"><label><input id="headfulUnderstand" type="checkbox"> 显示浏览器（登录或验证码时使用）</label></div>
        <button id="understandBtn" class="primary">理解并总结视频</button>
        <button id="understandHistoryBtn" class="ghost" type="button">理解历史</button>
        <div id="understandHistory" hidden></div>
        <div id="understandStatus" class="status" role="status" aria-live="polite"></div>
      </div>
      <article id="understandResult" class="understanding-result" hidden></article>
    </section>
    </div>
  </main>
  <div id="previewModal" class="modal" role="dialog" aria-modal="true">
    <div class="modal-panel">
      <div class="modal-head">
        <strong>本地预览</strong>
        <button id="closePreview" class="ghost">关闭</button>
      </div>
      <div id="previewBody" class="modal-body"></div>
    </div>
  </div>
  <script>
    const $ = (id) => document.getElementById(id);
    function selectTool(tool) {
      const tabs = [...document.querySelectorAll("[data-tool]")];
      if (!tabs.some(tab => tab.dataset.tool === tool)) tool = "collect";
      tabs.forEach(tab => {
        const active = tab.dataset.tool === tool;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        $(tab.getAttribute("aria-controls")).hidden = !active;
      });
      localStorage.setItem("douyinToolView", tool);
    }
    const toolTabs = [...document.querySelectorAll("[data-tool]")];
    toolTabs.forEach((tab, index) => {
      tab.onclick = () => selectTool(tab.dataset.tool);
      tab.onkeydown = event => {
        if (!["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
        event.preventDefault();
        const next = event.key === "Home" ? 0 : event.key === "End" ? toolTabs.length - 1 :
          (index + (["ArrowDown", "ArrowRight"].includes(event.key) ? 1 : -1) + toolTabs.length) % toolTabs.length;
        selectTool(toolTabs[next].dataset.tool);
        toolTabs[next].focus();
      };
    });
    selectTool(new URLSearchParams(location.search).get('view') || localStorage.getItem("douyinToolView") || "collect");
    let currentUrls = [];
    function mediaHref(href) {
      const prefix = window.location.pathname.match(/^\/tabs\/[^/]+/);
      if (prefix && (href === prefix[0] || href.startsWith(prefix[0] + '/'))) return href;
      return prefix ? prefix[0] + href : href;
    }
    async function refreshMentions() {
      try {
        const response = await fetch(mediaHref('/api/mentions'));
        const state = await response.json();
        if (!response.ok) throw new Error(state.error || '读取监听状态失败');
        $('mentionStatus').textContent = (state.enabled ? '监听中' : state.autostart_pending ? '自动监听等待配置' : '已停止') +
          (state.queue ? ` · 队列等待 ${state.queue.pending} 条 · 处理中 ${state.queue.active} 条 · 并发 ${state.queue.concurrency}` : '') +
          (state.last_seen ? ' · 扩展最后连接：' + new Date(state.last_seen * 1000).toLocaleTimeString() : ' · 等待扩展连接') +
          (state.error ? ' · ' + state.error : '');
        $('mentionRequests').textContent = JSON.stringify(state.request_state || {}, null, 2);
        const labels = {baseline:'已有通知（基线）',pending:'等待分析',running:'分析中',sending:'发送中',done:'已回复',draft:'回复草稿',error:'失败',cancelled:'已取消'};
        $('mentionItems').replaceChildren();
        for (const row of state.items) {
          const card = document.createElement('article');
          const link = document.createElement('a'); link.href = row.source_url; link.target = '_blank'; link.rel = 'noopener';
          link.textContent = (row.author || '@通知') + ' · ' + (labels[row.status] || row.status);
          if (row.queue_position) link.textContent += ` · 排队第 ${row.queue_position} 位`;
          const detail = document.createElement('p');
          detail.style.whiteSpace = 'pre-wrap';
          detail.textContent = [row.text, row.progress, row.reply && '回复：' + row.reply, row.error].filter(Boolean).join('\n');
          if (row.agent_plan) detail.textContent += '\n处理意图：' + (row.agent_plan.intent === 'question' ? '视频问答' : '视频摘要');
          card.append(link, detail);
          if (row.analysis && row.task_directory) {
            const report = document.createElement('a');
            report.href = mediaHref('/downloads/mentions/' + row.task_directory + '/report.md');
            report.target = '_blank'; report.rel = 'noopener'; report.textContent = '查看完整视频理解报告';
            card.append(report);
          }
          $('mentionItems').append(card);
        }
      } catch (error) { $('mentionStatus').textContent = error.message; }
    }
    refreshMentions();
    setInterval(() => { if (!$('pageMentions').hidden) refreshMentions(); }, 5000);
    function timeLabel(seconds) {
      const total = Math.floor(Number(seconds) || 0);
      return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
    }
    function renderUnderstanding(result) {
      const panel = $("understandResult");
      panel.replaceChildren();
      panel.dataset.historyId = result.history_id || "";
      panel.hidden = false;
      function add(tag, text, parent = panel, className = "") {
        const element = document.createElement(tag);
        element.textContent = text;
        if (className) element.className = className;
        parent.appendChild(element);
        return element;
      }
      add("h2", result.title);
      if (result.analysis_ready === false) {
        const labels = {pending:'排队中',running:'进行中',sending:'发送中',error:'失败',cancelled:'已取消'};
        const sourceLabel = result.record_source === 'mention' ? `@评论回复 · ${result.reply_username || '未知用户'}` : '手动解析';
        add('p', `${sourceLabel} · ${labels[result.reply_status] || result.reply_status}`);
        add('p', result.progress || '等待视频分析');
        if (result.reply_error) add('p', result.reply_error);
        const source = add('a', '打开原视频'); source.href = result.source_url; source.target = '_blank'; source.rel = 'noopener';
        return;
      }
      if (result.record_source === 'mention') {
        add('p', `@评论回复 · 回复对象：${result.reply_username || '未知用户'} · 状态：${result.reply_status}`, panel, 'reply-state');
        add('p', result.reply_text ? `回复正文：${result.reply_text}` : '', panel, 'reply-text');
        add('p', result.reply_error ? `回复错误：${result.reply_error}` : '', panel, 'reply-error');
      }
      const tags = add("div", "");
      [result.format, result.topic, ...(result.tags || [])].filter(Boolean).forEach(text => add("span", text, tags, "tag"));
      add("p", `视频 ${timeLabel(result.duration_seconds)} · ${result.frame_count} 张采样画面 · ${result.model}`, panel, "hint");
      add("h3", "内容摘要");
      add("div", result.summary, panel, "summary-text");
      add("h3", "核心要点");
      const points = add("ul", "");
      (result.key_points || []).forEach(text => add("li", text, points));
      const video = document.createElement("video");
      video.controls = true;
      video.preload = "metadata";
      video.src = mediaHref(result.video.href);
      add("h3", "时间线与原视频");
      panel.appendChild(video);
      const playbackStatus = add("p", "", panel, "hint");
      video.addEventListener("error", () => {
        playbackStatus.textContent = "视频加载失败，请刷新后重试，或下载缓存视频播放。";
      });
      (result.timeline || []).forEach(item => {
        const row = add("div", "", panel, "timeline-row");
        const button = add("button", timeLabel(item.seconds), row, "ghost");
        button.type = "button";
        button.setAttribute("aria-label", `跳转到 ${timeLabel(item.seconds)}`);
        button.onclick = async () => {
          try {
            if (video.readyState === 0) {
              playbackStatus.textContent = "正在加载视频…";
              await new Promise((resolve, reject) => {
                video.addEventListener("loadedmetadata", resolve, { once: true });
                video.addEventListener("error", reject, { once: true });
                video.load();
              });
            }
            video.currentTime = Math.max(0, Math.min(Number(item.seconds) || 0, video.duration || 0));
            await video.play();
            playbackStatus.textContent = "";
          } catch (error) {
            playbackStatus.textContent = "无法播放视频，请点击播放器播放按钮，或下载缓存视频。";
          }
        };
        add("span", item.content, row);
      });
      const details = add("details", "");
      const transcript = result.transcript || [];
      add("summary", `查看语音识别结果（${transcript.length} 段）`, details);
      const speechLength = transcript.map(item => item.text).join("").replace(/[\s\p{P}]/gu, "").length;
      if (!transcript.length) {
        add("p", "未识别到语音。视频可能只有音乐或环境音，也可能存在识别遗漏。", details, "hint");
      } else if (speechLength <= 4 && result.duration_seconds > 15) {
        add("p", "仅识别到少量文字，无法作为完整讲解。视频可能主要依靠画面字幕表达，也可能存在识别遗漏；请结合原视频核对。", details, "hint");
      }
      transcript.forEach(item => add("p", `${timeLabel(item.start)}–${timeLabel(item.end)} ${item.text}`, details));
      if (result.limitations && result.limitations.length) {
        add("h3", "理解范围");
        result.limitations.forEach(text => add("p", text, panel, "hint"));
      }
      const source = add("p", "");
      const sourceLink = add("a", "打开原作品", source);
      if (/^https?:\/\//i.test(result.source_url)) sourceLink.href = result.source_url;
      sourceLink.target = "_blank";
      sourceLink.rel = "noopener noreferrer";
      const videoLink = add("a", "下载缓存视频", add("p", ""));
      videoLink.href = mediaHref(result.video.href);
      videoLink.download = "";
      const link = add("a", result.history_id ? "下载完整报告 report.md" : "下载摘要 JSON", add("p", ""));
      link.href = mediaHref(result.report.href);
      link.download = result.history_id ? "report.md" : "summary.json";
      if (result.history_id) {
        const reportDetails = add("details", "");
        add("summary", "完整理解报告与中间过程", reportDetails);
        const report = document.createElement("iframe");
        report.title = "视频理解完整报告";
        report.src = mediaHref(`/api/understanding-history/${result.history_id}/report`);
        report.setAttribute("sandbox", "");
        report.style.cssText = "width:100%;height:720px;border:1px solid #d6e1eb;border-radius:6px";
        reportDetails.appendChild(report);
      }
    }
    let historyOffset = 0;
    let historyLoading = false;
    let historySnapshot = '';
    async function loadUnderstandingHistory(append = false) {
      const panel = $("understandHistory");
      panel.hidden = false;
      if (historyLoading) return;
      historyLoading = true;
      try {
        const targetCount = append ? historyOffset + 30 : Math.max(historyOffset, 30);
        const data = {items: [], total: 0};
        do {
          const response = await fetch(mediaHref(`/api/understanding-history?offset=${data.items.length}`));
          const page = await response.json();
          if (!response.ok) throw new Error(page.error || "加载历史失败");
          data.total = page.total;
          data.items.push(...page.items);
          if (!page.items.length) break;
        } while (data.items.length < Math.min(targetCount, data.total));
        const snapshot = JSON.stringify(data);
        if (snapshot === historySnapshot) return;
        const content = document.createDocumentFragment();
        if (!data.total) content.appendChild(document.createTextNode("暂无视频理解记录"));
        for (const item of data.items) {
          const row = document.createElement("p");
          row.style.cssText = "display:flex;gap:8px;align-items:stretch";
          const button = document.createElement("a");
          button.href = mediaHref(`/understanding/${encodeURIComponent(item.id)}`);
          button.target = '_blank';
          button.rel = 'noopener noreferrer';
          button.className = "ghost";
          button.style.cssText = "display:block;flex:1;min-width:0;white-space:normal;text-align:left;overflow-wrap:anywhere;padding:12px 16px;border:1px solid var(--line,#d6e1eb);border-radius:6px;color:inherit;text-decoration:none;background:white";
          const source = item.record_source === 'mention' ? `@评论回复 · ${item.reply_username || '未知用户'}` : '手动解析';
          button.textContent = `${new Date(item.created_at * 1000).toLocaleString()} · ${source} · ${item.title}`;
          if (item.reply_status) {
            const labels = {pending:'排队中',running:'进行中',sending:'发送中',done:'已回复',draft:'草稿',error:'失败',cancelled:'已取消'};
            if (item.record_source !== 'mention') labels.done = '已完成';
            button.textContent += ` · ${labels[item.reply_status] || item.reply_status}` + (item.progress ? ` · ${item.progress}` : '') + (item.reply_error ? ` · ${item.reply_error}` : '');
            if (item.queue_position) button.textContent += ` · 排队第 ${item.queue_position} 位`;
          }
          row.appendChild(button);
          const remove = document.createElement("button");
          remove.type = "button";
          remove.className = "ghost";
          remove.textContent = "×";
          remove.setAttribute("aria-label", `删除历史：${item.title}`);
          remove.title = "删除这条理解历史";
          remove.onclick = async () => {
            if (!window.confirm(`确定删除这条理解历史？\n${item.title}\n下载缓存文件将保留。`)) return;
            remove.disabled = true;
            try {
              const response = await fetch(mediaHref(`/api/understanding-history/${item.id}`), {method: "DELETE"});
              const data = await response.json();
              if (!response.ok) throw new Error(data.error || "删除失败");
              if ($("understandResult").dataset.historyId === item.id) {
                $("understandResult").replaceChildren();
                $("understandResult").hidden = true;
              }
              await loadUnderstandingHistory();
            } catch (error) {
              setStatus("understandStatus", error.message, true);
              remove.disabled = false;
            }
          };
          row.appendChild(remove);
          content.appendChild(row);
        }
        historyOffset = data.items.length;
        if (historyOffset < data.total) {
          const more = document.createElement("button");
          more.textContent = "加载更多";
          more.onclick = () => loadUnderstandingHistory(true);
          content.appendChild(more);
        }
        panel.replaceChildren(content);
        historySnapshot = snapshot;
      } catch (error) { setStatus("understandStatus", error.message, true); }
      finally { historyLoading = false; }
    }
    $("understandHistoryBtn").onclick = () => loadUnderstandingHistory();
    setInterval(() => { if (!$('pageUnderstand').hidden && !$('understandHistory').hidden) loadUnderstandingHistory(); }, 5000);
    async function waitUnderstanding(jobId) {
      for (;;) {
        let response, job;
        try {
          response = await fetch(mediaHref(`/api/jobs/${jobId}`));
          if (response.status >= 500) throw new Error("服务暂不可用");
          job = await response.json();
        } catch (error) {
          setStatus("understandStatus", "连接暂时中断，正在重新连接任务...");
          await new Promise(resolve => setTimeout(resolve, 5000));
          continue;
        }
        if (!response.ok) throw new Error(job.error || "任务不存在");
        setStatus("understandStatus", job.message || job.status);
        if (job.status === "done") return job.result;
        if (job.status === "error") throw new Error(job.error || "任务失败");
        await new Promise(resolve => setTimeout(resolve, 3000));
      }
    }
    async function followUnderstanding(jobId) {
      const button = $("understandBtn");
      button.disabled = true;
      try {
        const result = await waitUnderstanding(jobId);
        renderUnderstanding(result);
        if (!$("understandHistory").hidden) loadUnderstandingHistory();
        setStatus("understandStatus", "");
      } catch (error) {
        setStatus("understandStatus", error.message, true);
        localStorage.removeItem("douyinUnderstandingJob");
      } finally {
        button.disabled = false;
      }
    }
    $("understandBtn").addEventListener("click", async () => {
      const url = $("understandUrl").value.trim();
      if (!url) { setStatus("understandStatus", "请输入作品链接", true); return; }
      $("understandBtn").disabled = true;
      setStatus("understandStatus", "正在创建视频理解任务...");
      try {
        const started = await postJson("/api/understand", {url, headful: $("headfulUnderstand").checked});
        loadUnderstandingHistory();
        localStorage.setItem("douyinUnderstandingJob", started.jobId);
        await followUnderstanding(started.jobId);
      } catch (error) {
        setStatus("understandStatus", error.message, true);
        $("understandBtn").disabled = false;
      }
    });
    const pendingUnderstanding = localStorage.getItem("douyinUnderstandingJob");
    if (pendingUnderstanding) followUnderstanding(pendingUnderstanding);

    const downloadedByUrl = new Map();
    const downloadingByUrl = new Set();
    let singleDownloadedFiles = null;

    function setStatus(id, text, isError = false) {
      const el = $(id);
      el.textContent = text || "";
      el.classList.toggle("error", !!isError);
    }

    function numberValue(id) {
      const value = $(id).value.trim();
      return value ? Number(value) : null;
    }

    async function postJson(path, data) {
      const response = await fetch(path, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(data)
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "请求失败");
      return body;
    }

    async function waitJob(jobId, statusId, onUpdate, timeoutMs = 10 * 60 * 1000) {
      const startedAt = Date.now();
      for (;;) {
        if (Date.now() - startedAt > timeoutMs) {
          throw new Error("任务等待超时，请点击重试");
        }
        const response = await fetch(`/api/jobs/${jobId}`);
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || "任务不存在");
        if (statusId) setStatus(statusId, job.message || job.status);
        if (onUpdate && job.result) onUpdate(job.result, job);
        if (job.status === "done") return job.result;
        if (job.status === "error") throw new Error(job.error || "任务失败");
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }

    function preview(url) {
      window.open(url, "_blank", "noopener,noreferrer");
    }

    function openLocalPreview(files) {
      const body = $("previewBody");
      body.innerHTML = "";
      (files || []).forEach((file) => {
        const isVideo = (file.mime || "").startsWith("video/") || /\.(mp4|mov|webm)$/i.test(file.name || "");
        const media = document.createElement(isVideo ? "video" : "img");
        media.src = file.href;
        if (isVideo) {
          media.controls = true;
          media.autoplay = true;
        } else {
          media.alt = file.name || "downloaded image";
        }
        body.appendChild(media);
      });
      $("previewModal").classList.add("open");
    }

    function closePreview() {
      $("previewBody").querySelectorAll("video, audio").forEach((media) => {
        media.pause();
        media.removeAttribute("src");
        media.load();
      });
      $("previewBody").replaceChildren();
      $("previewModal").classList.remove("open");
    }

    $("closePreview").addEventListener("click", closePreview);
    $("previewModal").addEventListener("click", (event) => {
      if (event.target === $("previewModal")) closePreview();
    });

    function normalizeItem(item) {
      if (typeof item === "string") return { url: item, title: item, cover: "", type: "" };
      return {
        url: item.url || "",
        title: item.title || item.desc || item.url || "未命名作品",
        cover: item.cover || "",
        type: item.type || ""
      };
    }

    function renderList(items) {
      $("materialToolbar").style.display = "";
      $("list").style.display = "";
      currentUrls = (items || []).map(normalizeItem).filter((item) => item.url);
      $("count").textContent = `${currentUrls.length} 条`;
      if (!currentUrls.length) {
        $("list").innerHTML = '<div class="empty">暂无结果</div>';
        return;
      }
      $("list").innerHTML = "";
      currentUrls.forEach((item, index) => {
        const url = item.url;
        const row = document.createElement("div");
        row.className = "row";
        row.innerHTML = `
          <div class="item-main">
            <div class="thumb empty">无封面</div>
            <div>
              <div class="meta"></div>
              <div class="title"></div>
              <div class="url"></div>
            </div>
            <div class="downloads"></div>
          </div>
          <div class="actions">
            <button class="secondary" data-action="preview">打开链接</button>
            <button class="ghost" data-action="download">下载</button>
          </div>`;
        const thumbSlot = row.querySelector(".thumb");
        if (item.cover) {
          const img = document.createElement("img");
          img.className = "thumb";
          img.src = item.cover;
          img.alt = item.title;
          img.loading = "lazy";
          thumbSlot.replaceWith(img);
        }
        row.querySelector(".meta").textContent = `#${index + 1}${item.type ? " · " + item.type : ""}`;
        row.querySelector(".title").textContent = item.title;
        row.querySelector(".url").textContent = url;
        row.querySelector('[data-action="preview"]').addEventListener("click", () => preview(url));
        const downloadButton = row.querySelector('[data-action="download"]');
        if (downloadedByUrl.has(url)) {
          downloadButton.textContent = "本地预览";
        } else if (downloadingByUrl.has(url)) {
          downloadButton.disabled = true;
          downloadButton.textContent = "下载中";
        }
        row.querySelector('[data-action="download"]').addEventListener("click", async (event) => {
          const button = event.currentTarget;
          if (downloadedByUrl.has(url)) {
            openLocalPreview(downloadedByUrl.get(url));
            return;
          }
          const files = row.querySelector(".downloads");
          downloadingByUrl.add(url);
          button.disabled = true;
          button.textContent = "下载中";
          files.textContent = "";
          try {
            const started = await postJson("/api/download", {
              url,
              allMedia: $("allMediaSingle").checked,
              headful: $("headfulDownload").checked
            });
            const result = await waitJob(started.jobId, null, (_partial, job) => {
              files.textContent = job.message || "下载中";
            }, 180000);
            downloadedByUrl.set(url, result.files || []);
            files.innerHTML = "";
            result.files.forEach((file) => {
              const a = document.createElement("a");
              a.className = "file-link";
              a.href = file.href;
              a.textContent = file.name;
              a.setAttribute("download", file.name);
              files.appendChild(a);
            });
            button.textContent = "本地预览";
            button.disabled = false;
          } catch (error) {
            files.textContent = error.message;
            button.textContent = "重试下载";
            button.disabled = false;
          } finally {
            downloadingByUrl.delete(url);
          }
        });
        $("list").appendChild(row);
      });
    }

    $("collectBtn").addEventListener("click", async () => {
      const button = $("collectBtn");
      renderList([]);
      currentUrls = [];
      downloadedByUrl.clear();
      $("count").textContent = "0 条";
      $("list").innerHTML = '<div class="empty">正在等待新的作品...</div>';
      button.disabled = true;
      setStatus("collectStatus", "正在创建拉取任务...");
      try {
        const started = await postJson("/api/collect", {
          url: $("homepageUrl").value.trim(),
          targetCount: numberValue("targetCount")
        });
        const result = await waitJob(started.jobId, "collectStatus", (partial) => {
          if (partial.items || partial.urls) renderList(partial.items || partial.urls);
        });
        renderList(result.items || result.urls);
        setStatus("collectStatus", `拉取完成：${result.urls.length} 条`);
      } catch (error) {
        setStatus("collectStatus", error.message, true);
      } finally {
        button.disabled = false;
      }
    });

    $("downloadBtn").addEventListener("click", async () => {
      const button = $("downloadBtn");
      if (singleDownloadedFiles) {
        openLocalPreview(singleDownloadedFiles);
        return;
      }
      button.disabled = true;
      $("downloadFiles").innerHTML = "";
      setStatus("downloadStatus", "正在创建下载任务...");
      try {
        const started = await postJson("/api/download", {
          url: $("downloadUrl").value.trim(),
          allMedia: $("allMediaSingle").checked,
          headful: $("headfulDownload").checked
        });
        const result = await waitJob(started.jobId, "downloadStatus");
        singleDownloadedFiles = result.files || [];
        setStatus("downloadStatus", `下载完成：${result.files.length} 个文件`);
        result.files.forEach((file) => {
          const a = document.createElement("a");
          a.className = "file-link";
          a.href = file.href;
          a.textContent = file.name;
          a.setAttribute("download", file.name);
          $("downloadFiles").appendChild(a);
        });
      } catch (error) {
        setStatus("downloadStatus", error.message, true);
      } finally {
        button.disabled = false;
        if (singleDownloadedFiles) button.textContent = "本地预览";
      }
    });

    $("downloadUrl").addEventListener("input", () => {
      singleDownloadedFiles = null;
      $("downloadBtn").textContent = "开始下载";
    });
  </script>
</body>
</html>
"""


def understanding_detail_html() -> str:
    """Reuse the result renderer so standalone and submission views stay consistent."""
    style = WEB_HTML.split('<style>', 1)[1].split('</style>', 1)[0]
    renderer = WEB_HTML.split('    function timeLabel(seconds)', 1)[1].split('    let historyOffset', 1)[0]
    return r'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>视频理解详情</title>
<style>''' + style + r'''
body{margin:0;padding:24px;font-family:"Microsoft YaHei","Segoe UI",sans-serif}main.detail-page{max-width:1100px;margin:auto;display:block}
.detail-page h2{font-size:26px;line-height:1.45}.detail-page h3{font-size:20px}
.detail-toolbar{display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:20px}
.detail-toolbar a{color:#245d83}.detail-status{margin-left:auto;white-space:pre-wrap}
.understanding-result{border-top:1px solid #d6e1eb;background:white;padding:24px}
.summary-text{max-width:80ch!important}@media(max-width:600px){body{padding:12px}.understanding-result{padding:16px}.detail-status{margin-left:0;width:100%}}
</style></head><body><main class="detail-page">
<nav class="detail-toolbar" aria-label="详情导航"><a id="backLink">← 返回视频理解</a>
<span id="detailStatus" class="detail-status" role="status" aria-live="polite">正在加载记录…</span></nav>
<article id="understandResult" class="understanding-result" hidden></article>
</main><script>
const $ = id => document.getElementById(id);
const prefix = location.pathname.match(/^\/tabs\/[^/]+/);
function mediaHref(href){if(prefix && (href === prefix[0] || href.startsWith(prefix[0] + '/')))return href;return (prefix ? prefix[0] : '') + href;}
$('backLink').href = mediaHref('/?view=understand');
''' + 'function timeLabel(seconds)' + renderer + r'''
const id = location.pathname.split('/').filter(Boolean).pop();
let rendered = '';
async function refreshDetail(){
  let again = true;
  try{
    const response = await fetch(mediaHref('/api/understanding-history/' + encodeURIComponent(id)), {cache:'no-store'});
    const result = await response.json();
    if(!response.ok){again = response.status !== 404;throw new Error(result.error || '加载记录失败');}
    document.title = (result.title || '视频理解') + ' · 详情';
    const labels = {pending:'排队中',running:'进行中',sending:'发送中',done:'已完成',draft:'回复草稿',error:'失败',cancelled:'已取消'};
    if(result.record_source === 'mention') labels.done = '已回复';
    const status = result.reply_status || 'done';
    $('detailStatus').textContent = [labels[status] || status, result.progress, result.reply_error].filter(Boolean).join(' · ');
    // Keep video playback, expanded sections and reading position during reply-status updates.
    const content = {...result};
    if(result.analysis_ready !== false){delete content.progress;delete content.reply_status;delete content.reply_text;delete content.reply_error;}
    const snapshot = JSON.stringify(content);
    if(snapshot !== rendered){renderUnderstanding(result);rendered = snapshot;}
    if(result.record_source === 'mention' && result.analysis_ready !== false){
      document.querySelector('.reply-state').textContent = `@评论回复 · 回复对象：${result.reply_username || '未知用户'} · 状态：${labels[status] || status}`;
      document.querySelector('.reply-text').textContent = result.reply_text ? '回复正文：' + result.reply_text : '';
      document.querySelector('.reply-error').textContent = result.reply_error ? '回复错误：' + result.reply_error : '';
    }
    again = ['pending','running','sending'].includes(status);
  }catch(error){$('detailStatus').textContent = error.message;}
  if(again) setTimeout(refreshDetail,5000);
}
refreshDetail();
</script></body></html>'''


def print_json(data: Any) -> None:
    encoding = (sys.stdout.encoding or "").lower()
    ensure_ascii = "utf" not in encoding
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=2)
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


ProgressCallback = Callable[[str, dict[str, Any] | None], None]


def emit_progress(
    progress_callback: ProgressCallback | None,
    message: str,
    partial_result: dict[str, Any] | None = None,
) -> None:
    if progress_callback:
        progress_callback(message, partial_result)


class WebJobStore:
    def __init__(self, directory: Path | None = None) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self.directory = directory
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
            for path in directory.glob("*.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                    if job.get("status") == "running":
                        job.update(status="error", error="服务重启，任务已中断，请重新提交", message="任务中断")
                    self._jobs[job["id"]] = job
                    self._persist(job["id"])
                except (ValueError, KeyError, OSError):
                    continue

    def _persist(self, job_id: str) -> None:
        if self.directory:
            target = self.directory / (job_id + ".json")
            temp = target.with_suffix(".tmp")
            temp.write_text(json.dumps(self._jobs[job_id], ensure_ascii=False), encoding="utf-8")
            for attempt in range(8):
                try:
                    temp.replace(target)
                    break
                except PermissionError:
                    if attempt == 7:
                        raise
                    time.sleep(min(0.05 * (2 ** attempt), 0.5))

    def create(self, message: str) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "message": message,
                "created_at": time.time(),
            }
            self._persist(job_id)
        return job_id

    def update(self, job_id: str, **fields: Any) -> None:
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(fields)
                self._jobs[job_id]["updated_at"] = time.time()
                self._persist(job_id)

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None


def web_json_response(handler: http.server.BaseHTTPRequestHandler, status: int, data: Any) -> None:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json; charset=utf-8")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def web_text_response(
    handler: http.server.BaseHTTPRequestHandler,
    status: int,
    body: str,
    content_type: str = "text/html; charset=utf-8",
) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", content_type)
    handler.send_header("content-length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def read_json_request(handler: http.server.BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    return data


def json_bool(data: dict[str, Any], key: str, default: bool = False) -> bool:
    value = data.get(key, default)
    return bool(value)


def json_positive_int(data: dict[str, Any], key: str, default: int | None = None) -> int | None:
    value = data.get(key)
    if value in (None, ""):
        return default
    number = int(value)
    if number <= 0:
        raise ValueError(f"{key} must be greater than 0")
    return number


def json_positive_float(data: dict[str, Any], key: str, default: float) -> float:
    value = data.get(key)
    if value in (None, ""):
        return default
    number = float(value)
    if number <= 0:
        raise ValueError(f"{key} must be greater than 0")
    return number


def file_result(path: Path, download_root: Path) -> dict[str, str]:
    relative = path.resolve().relative_to(download_root.resolve()).as_posix()
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return {
        "name": path.name,
        "href": f"/downloads/{relative}",
        "mime": mime,
    }


def start_web_job(
    jobs: WebJobStore,
    message: str,
    target,
    *args: Any,
    **kwargs: Any,
) -> str:
    job_id = jobs.create(message)

    def runner() -> None:
        try:
            def progress(update: str, partial_result: dict[str, Any] | None = None) -> None:
                fields: dict[str, Any] = {"message": update}
                if partial_result is not None:
                    fields["result"] = partial_result
                jobs.update(job_id, **fields)

            result = target(progress, *args, **kwargs)
            jobs.update(job_id, status="done", message="完成", result=result)
        except Exception as exc:
            jobs.update(job_id, status="error", message="失败", error=str(exc))

    thread = threading.Thread(target=runner, name=f"douyin-web-job-{job_id[:8]}", daemon=True)
    thread.start()
    return job_id


def seed_browser_profile(source: Path, target: Path) -> None:
    if not source.is_dir() or any(target.iterdir()):
        return
    for child in source.iterdir():
        destination = target / child.name
        try:
            if child.is_dir():
                shutil.copytree(child, destination, ignore=shutil.ignore_patterns("Singleton*"))
            elif not child.name.startswith("Singleton"):
                shutil.copy2(child, destination)
        except OSError:
            continue


def run_web_server(host: str, port: int, cache_dir: Path, store_dir: Path | None = None) -> None:
    persistent_dir = (store_dir or service_store("douyin")).resolve()
    download_root = persistent_dir / "web_downloads"
    url_list_root = persistent_dir / "web_url_lists"
    legacy_user_data_dir = persistent_dir / ".douyin-browser"
    collect_user_data_dir = persistent_dir / ".douyin-browser-collect"
    download_user_data_dir = persistent_dir / ".douyin-browser-download"
    download_root.mkdir(parents=True, exist_ok=True)
    url_list_root.mkdir(parents=True, exist_ok=True)
    collect_user_data_dir.mkdir(parents=True, exist_ok=True)
    download_user_data_dir.mkdir(parents=True, exist_ok=True)
    seed_browser_profile(legacy_user_data_dir, collect_user_data_dir)
    seed_browser_profile(legacy_user_data_dir, download_user_data_dir)
    jobs = WebJobStore(persistent_dir / "web_jobs")
    from services.douyin.understanding_history import UnderstandingHistory, render_report
    history = UnderstandingHistory(persistent_dir / "understanding_history.sqlite3", download_root)
    history.backfill()
    history.interrupt_manual_tasks()
    from services.douyin.mention_monitor import MentionMonitor

    def mention_config():
        from services.douyin.video_understanding import validate_config
        from services.video_creator.tools.ai.config_store import ProviderConfigStore
        path = service_store('video_creator') / 'provider_configs.json'
        return validate_config(ProviderConfigStore(path).get_by_provider('douyin_understanding'))

    from services.douyin.mention_agent import MentionAgent
    agent = MentionAgent(mention_config, service_store('video_creator') / 'provider_configs.json', download_user_data_dir)
    mention_monitor = MentionMonitor(download_root / 'mentions', None, None, history.save_mention, agent=agent)
    if os.environ.get('DOUYIN_MENTION_AUTOSTART', '1').lower() in {'1', 'true', 'yes'}:
        mention_monitor.configure_autostart(mention_config)
    for trace_path in (download_root / "understanding").glob("*/task.json"):
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            if trace.get("status") == "running":
                trace.update(status="error", error="服务重启，任务已中断")
                for node in trace.get("nodes", []):
                    if node.get("status") == "running":
                        node.update(status="failed", error="服务重启，任务已中断")
                trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
        except (ValueError, OSError):
            continue

    class DouyinWebHandler(http.server.BaseHTTPRequestHandler):
        server_version = "DouyinWeb/0.1"

        def log_message(self, format: str, *args: Any) -> None:
            print(
                f"{self.address_string()} - {format % args}",
                file=sys.stderr,
                flush=True,
            )

        def do_GET(self) -> None:
            parsed = urlsplit(self.path)
            if parsed.path == '/api/mentions':
                web_json_response(self, 200, mention_monitor.status())
                return
            if parsed.path == "/api/understanding-history":
                try:
                    offset = max(0, int(dict(parse_qsl(parsed.query)).get("offset", "0")))
                except ValueError:
                    web_json_response(self, 400, {"error": "无效的分页参数"})
                    return
                web_json_response(self, 200, history.list(offset=offset))
                return
            if parsed.path.startswith("/api/understanding-history/"):
                parts = parsed.path.strip("/").split("/")
                result = history.get(parts[2]) if len(parts) in (3, 4) else None
                if not result or (len(parts) == 4 and parts[3] != "report"):
                    web_json_response(self, 404, {"error": "历史记录不存在"})
                    return
                if len(parts) == 3:
                    web_json_response(self, 200, result)
                else:
                    if result.get('analysis_ready') is False:
                        web_json_response(self, 409, {'error': '视频分析尚未完成，报告暂不可用'})
                        return
                    relative = result.get('artifact_directory') or 'understanding/' + result['history_id']
                    root = (download_root / relative).resolve()
                    root.relative_to(download_root.resolve())
                    trace = json.loads((root / "task.json").read_text(encoding="utf-8"))
                    web_text_response(self, 200, render_report(root, result, trace, "../../../downloads/" + relative + "/"))
                return
            if re.fullmatch(r"/understanding/[0-9a-f]{32}", parsed.path):
                web_text_response(self, 200, understanding_detail_html())
                return
            if parsed.path in ("/", "/index.html"):
                web_text_response(self, 200, WEB_HTML)
                return

            if self.path.startswith("/api/jobs/"):
                job_id = self.path.rsplit("/", 1)[-1]
                job = jobs.get(job_id)
                if not job:
                    web_json_response(self, 404, {"error": "任务不存在"})
                    return
                web_json_response(self, 200, job)
                return

            if self.path.startswith("/downloads/"):
                relative = unquote(self.path[len("/downloads/") :].split("?", 1)[0])
                try:
                    target = (download_root / relative).resolve()
                    target.relative_to(download_root.resolve())
                except ValueError:
                    web_json_response(self, 403, {"error": "禁止访问该文件"})
                    return
                if not target.is_file():
                    web_json_response(self, 404, {"error": "文件不存在"})
                    return
                content_type = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
                file_size = target.stat().st_size
                range_header = self.headers.get("range")
                start = 0
                end = file_size - 1
                status = 200
                if range_header:
                    match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
                    if not match:
                        self.send_response(416)
                        self.send_header("content-range", f"bytes */{file_size}")
                        self.end_headers()
                        return
                    if match.group(1):
                        start = int(match.group(1))
                    if match.group(2):
                        end = int(match.group(2))
                    if match.group(1) == "" and match.group(2):
                        suffix_length = int(match.group(2))
                        start = max(file_size - suffix_length, 0)
                        end = file_size - 1
                    if start > end or start >= file_size:
                        self.send_response(416)
                        self.send_header("content-range", f"bytes */{file_size}")
                        self.end_headers()
                        return
                    end = min(end, file_size - 1)
                    status = 206

                content_length = end - start + 1
                self.send_response(status)
                self.send_header("content-type", content_type)
                self.send_header("accept-ranges", "bytes")
                self.send_header("content-length", str(content_length))
                if status == 206:
                    self.send_header("content-range", f"bytes {start}-{end}/{file_size}")
                self.send_header(
                    "content-disposition",
                    f'inline; filename="{target.name.replace(chr(34), "_")}"',
                )
                self.end_headers()
                with target.open("rb") as file:
                    file.seek(start)
                    remaining = content_length
                    while remaining > 0:
                        chunk = file.read(min(1024 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                return

            web_json_response(self, 404, {"error": "Not found"})

        def do_DELETE(self) -> None:
            parts = urlsplit(self.path).path.strip("/").split("/")
            if len(parts) == 3 and parts[:2] == ["api", "understanding-history"]:
                if history.delete(parts[2]):
                    web_json_response(self, 200, {"deleted": True})
                else:
                    web_json_response(self, 404, {"error": "历史记录不存在"})
                return
            web_json_response(self, 404, {"error": "Not found"})

        def do_POST(self) -> None:
            try:
                data = read_json_request(self)

                if self.path == '/api/mentions/start':
                    mention_config()
                    mention_monitor.start(auto_reply=json_bool(data, 'autoReply'), interval=data.get('interval', 60))
                    web_json_response(self, 200, mention_monitor.status())
                    return
                if self.path == '/api/mentions/stop':
                    web_json_response(self, 200, mention_monitor.stop())
                    return
                if self.path == '/api/mentions/process-existing':
                    web_json_response(self, 202, mention_monitor.queue_existing(data.get('id')))
                    return

                if self.path == "/api/collect":
                    homepage_url = str(data.get("url") or "").strip()
                    if not homepage_url:
                        raise ValueError("请输入博主主页地址")
                    target_count = json_positive_int(data, "targetCount")
                    # The web UI is target-driven. Keep these as server-side
                    # defaults so old API callers remain compatible.
                    max_scrolls = 80
                    wait_seconds = 1.5
                    if target_count:
                        max_scrolls = max(1, min(max_scrolls, (target_count + 17) // 18 + 2))

                    def collect_task(progress) -> dict[str, Any]:
                        progress(f"等待 Chrome 扩展接收任务，请确认扩展已重载到 {EXPECTED_EXTENSION_VERSION}")
                        result = run_extension_profile_collect(
                            homepage_url,
                            max_scrolls=max_scrolls,
                            target_count=target_count,
                            wait_seconds=wait_seconds,
                            progress_callback=progress,
                        )
                        if not result.get("ok"):
                            raise RuntimeError(result.get("error") or "Chrome 扩展拉取失败")

                        urls = result.get("urls") or []
                        items = result.get("items") or []
                        progress(
                            f"扩展拉取完成：{len(urls)} 条，捕获分页 {result.get('captured_pages') or 0} 页",
                            {"urls": urls, "items": items, "partial": True},
                        )
                        output = url_list_root / f"urls_{int(time.time())}_{uuid.uuid4().hex[:8]}.json"
                        output.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
                        return {
                            "urls": urls,
                            "items": items,
                            "responses": result.get("responses") or [],
                            "version_warning": result.get("version_warning"),
                            "output": str(output),
                        }

                    job_id = start_web_job(jobs, "正在拉取博主素材列表", collect_task)
                    web_json_response(self, 202, {"jobId": job_id})
                    return

                if self.path == "/api/understand":
                    from services.douyin.video_understanding import validate_config, understand_work
                    from services.video_creator.tools.ai.config_store import ProviderConfigStore
                    work_url = extract_douyin_work_url(str(data.get("url") or ""))
                    config_path = service_store("video_creator") / "provider_configs.json"
                    saved = ProviderConfigStore(config_path).get_by_provider("douyin_understanding")
                    config = validate_config(saved)
                    headful = json_bool(data, "headful")
                    task_root = download_root / "understanding" / uuid.uuid4().hex
                    history.update_manual(task_root, work_url, 'pending', '等待视频理解队列')

                    def understanding_task(progress):
                        def tracked_progress(message, partial_result=None):
                            status = 'pending' if message == '等待视频理解队列' else 'running'
                            history.update_manual(task_root, work_url, status, message)
                            progress(message, partial_result)
                        def download(url, output_dir, callback):
                            return download_work_media(url, output_dir=output_dir, headless=not headful,
                                user_data_dir=download_user_data_dir, all_media=False,
                                wait_seconds=1.5, progress_callback=callback)
                        try:
                            result = understand_work(work_url, task_root, download, config, tracked_progress)
                            tracked_progress("正在保存完整报告和历史记录")
                            return history.save(task_root, {**result, 'record_source': 'manual', 'reply_status': 'done', 'analysis_ready': True})
                        except Exception as exc:
                            history.update_manual(task_root, work_url, 'error', '失败', str(exc))
                            raise

                    job_id = start_web_job(jobs, "正在创建视频理解任务", understanding_task)
                    web_json_response(self, 202, {"jobId": job_id})
                    return

                if self.path == "/api/download":
                    work_url = extract_douyin_work_url(str(data.get("url") or ""))
                    all_media = json_bool(data, "allMedia")
                    headful = json_bool(data, "headful")

                    def download_task(progress) -> dict[str, Any]:
                        paths = download_work_media(
                            work_url,
                            output_dir=download_root,
                            headless=not headful,
                            user_data_dir=download_user_data_dir,
                            all_media=all_media,
                            wait_seconds=1.5,
                            progress_callback=progress,
                        )
                        return {"files": [file_result(path, download_root) for path in paths]}

                    job_id = start_web_job(jobs, "正在下载作品素材", download_task)
                    web_json_response(self, 202, {"jobId": job_id})
                    return

                web_json_response(self, 404, {"error": "Not found"})
            except Exception as exc:
                web_json_response(self, 400, {"error": str(exc)})

    server = http.server.ThreadingHTTPServer((host, port), DouyinWebHandler)
    print(f"web listening=http://{host}:{port}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def extract_douyin_work_url(text: str) -> str:
    for candidate in re.findall(r"https?://[^\s<>\[\]【】\"'“”]+", text, re.IGNORECASE):
        candidate = candidate.rstrip("。，,！!；;：:）)")
        hostname = urlsplit(candidate).hostname or ""
        if hostname == "douyin.com" or hostname.endswith(".douyin.com"):
            return candidate
    raise ValueError("请输入抖音作品链接或包含链接的分享文案")


def resolve_douyin_work_url(text: str) -> str:
    url = extract_douyin_work_url(text)
    if urlsplit(url).hostname == "v.douyin.com":
        request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urlopen(request, timeout=30) as response:
                url = response.geturl()
        except Exception as exc:
            raise ValueError("抖音短链接解析失败，请重试或复制完整作品链接") from exc
        url = extract_douyin_work_url(url)
    return standard_open_url(url)


def parse_sec_uid(homepage_url: str) -> str:
    path = unquote(urlsplit(homepage_url).path).rstrip("/")
    match = re.search(r"/user/([^/?#]+)$", path)
    if not match:
        raise ValueError("Homepage URL must look like https://www.douyin.com/user/<sec_uid>")
    return match.group(1)


def parse_work_id(work_url: str) -> str:
    parts = urlsplit(work_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key in ("modal_id", "vid"):
        value = query.get(key)
        if value and re.fullmatch(r"[0-9A-Za-z_-]+", value):
            return value

    path = unquote(parts.path).rstrip("/")
    match = re.search(r"/(?:video|note)/([^/?#]+)$", path)
    if not match:
        raise ValueError(
            "Work URL must look like /video/<id>, /note/<id>, "
            "or a user page URL with modal_id/vid."
        )
    return match.group(1)


def standard_video_url(work_id: str) -> str:
    return f"https://www.douyin.com/video/{work_id}"


def standard_open_url(raw_url: str) -> str:
    work_id = parse_work_id(raw_url)
    path = unquote(urlsplit(raw_url).path).rstrip("/")
    if re.search(r"/note/[^/?#]+$", path):
        return f"https://www.douyin.com/note/{work_id}"
    return standard_video_url(work_id)


def is_note_work_url(raw_url: str) -> bool:
    path = unquote(urlsplit(raw_url).path).rstrip("/")
    return bool(re.search(r"/note/[^/?#]+$", path))


def close_popups(page: Page) -> None:
    selectors = [
        "button:has-text('Agree')",
        "button:has-text('OK')",
        "button:has-text('Cancel')",
        "button:has-text('Not now')",
        "button:has-text('同意')",
        "button:has-text('我知道了')",
        "button:has-text('稍后再说')",
        "button:has-text('暂不登录')",
        "button:has-text('取消')",
        "[aria-label='Close']",
        "[aria-label='关闭']",
    ]

    for selector in selectors:
        try:
            locator = page.locator(selector).first
            if locator.is_visible(timeout=700):
                locator.click(timeout=1000)
        except PlaywrightTimeoutError:
            continue
        except Exception:
            continue


def looks_like_douyin_aweme_response(response: Response) -> bool:
    if "douyin.com" not in response.url:
        return False

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type and "javascript" not in content_type:
        return False

    markers = (
        "/aweme/post/",
        "/aweme/v1/web/aweme/post/",
        "/aweme/v1/web/aweme/listcollection/",
        "/web/api/v2/aweme/post/",
    )
    return any(marker in response.url for marker in markers)


def looks_like_douyin_json_response(response: Response) -> bool:
    if "douyin.com" not in response.url:
        return False

    content_type = response.headers.get("content-type", "")
    return "json" in content_type or "javascript" in content_type


def response_json(response: Response) -> Any | None:
    try:
        return response.json()
    except Exception:
        return None


def parse_json_text(text: str) -> Any | None:
    try:
        return json.loads(text)
    except Exception:
        pass

    stripped = text.strip()
    for start_char, end_char in (("{", "}"), ("[", "]")):
        start = stripped.find(start_char)
        end = stripped.rfind(end_char)
        if start >= 0 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except Exception:
                return None
    return None


def iter_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_dicts(child)


def author_matches(item: dict[str, Any], sec_uid: str) -> bool:
    author = item.get("author")
    if not isinstance(author, dict):
        return False

    return author.get("sec_uid") == sec_uid or author.get("sec_user_id") == sec_uid


def work_url_from_aweme(item: dict[str, Any]) -> str | None:
    aweme_id = item.get("aweme_id") or item.get("awemeId") or item.get("id")
    if aweme_id is None:
        return None

    aweme_id = str(aweme_id)
    if not re.fullmatch(r"[0-9A-Za-z_-]+", aweme_id):
        return None

    aweme_type = item.get("aweme_type")
    is_note = aweme_type in NOTE_AWEME_TYPES or bool(item.get("images"))
    path_type = "note" if is_note else "video"
    return f"https://www.douyin.com/{path_type}/{aweme_id}"


def aweme_title(item: dict[str, Any]) -> str:
    for key in ("desc", "caption", "title", "share_title", "shareTitle"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    share_info = item.get("share_info") or item.get("shareInfo")
    if isinstance(share_info, dict):
        for key in ("share_title", "shareTitle", "title", "desc"):
            value = share_info.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

    return "未命名作品"


def aweme_cover_url(item: dict[str, Any]) -> str:
    image_post_info = item.get("image_post_info") or item.get("imagePostInfo")
    image_groups = [
        item.get("images"),
        item.get("image_infos"),
        item.get("imageInfos"),
    ]
    if isinstance(image_post_info, dict):
        image_groups.extend(
            [
                image_post_info.get("images"),
                image_post_info.get("image_infos"),
                image_post_info.get("imageInfos"),
            ]
        )

    for images in image_groups:
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in (
                "url_list",
                "urlList",
                "display_image",
                "displayImage",
                "origin_cover",
                "originCover",
                "origin_image",
                "originImage",
                "thumbnail",
                "thumbnail_image",
                "thumbnailImage",
            ):
                if url := first_url(image.get(key)):
                    return url

    video = item.get("video")
    if isinstance(video, dict):
        for key in (
            "cover",
            "origin_cover",
            "originCover",
            "dynamic_cover",
            "dynamicCover",
            "animated_cover",
            "animatedCover",
        ):
            if url := first_url(video.get(key)):
                return url

    return ""


def work_item_from_aweme(item: dict[str, Any]) -> dict[str, str] | None:
    url = work_url_from_aweme(item)
    if not url:
        return None
    return {
        "url": url,
        "title": aweme_title(item),
        "cover": aweme_cover_url(item),
        "type": "图文" if is_note_work_url(url) else "视频",
    }


def aweme_id_matches(item: dict[str, Any], work_id: str) -> bool:
    aweme_id = item.get("aweme_id") or item.get("awemeId") or item.get("id")
    return str(aweme_id) == work_id


def first_url(value: Any) -> str | None:
    if isinstance(value, str) and value.startswith(("http://", "https://")):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.startswith(("http://", "https://")):
                return item
    if isinstance(value, dict):
        for key in ("url_list", "urlList", "urls"):
            if url := first_url(value.get(key)):
                return url
    return None


def int_value(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def add_media(
    items: list[MediaItem],
    seen: set[str],
    kind: str,
    url: str | None,
    *,
    label: str = "",
    width: int = 0,
    height: int = 0,
    bitrate: int = 0,
) -> None:
    if not url or url in seen:
        return
    seen.add(url)
    extension = "mp4" if kind == "video" else image_extension_from_url(url)
    items.append(
        MediaItem(
            kind=kind,
            url=url,
            extension=extension,
            label=label,
            width=width,
            height=height,
            bitrate=bitrate,
        )
    )


def image_extension_from_url(url: str) -> str:
    path = urlsplit(url).path.lower()
    for extension in ("jpg", "jpeg", "png", "webp"):
        if path.endswith(f".{extension}"):
            return extension
    return "jpg"


def extract_media_from_aweme(item: dict[str, Any]) -> list[MediaItem]:
    media: list[MediaItem] = []
    seen: set[str] = set()

    video = item.get("video")
    if isinstance(video, dict):
        for key in ("play_addr", "download_addr", "playAddr", "downloadAddr"):
            add_media(
                media,
                seen,
                "video",
                first_url(video.get(key)),
                label=key,
                width=int_value(video.get("width")),
                height=int_value(video.get("height")),
                bitrate=int_value(video.get("bit_rate") or video.get("bitRate")),
            )

        bit_rates = video.get("bit_rate") or video.get("bitRate") or []
        if isinstance(bit_rates, list):
            for bit_rate in bit_rates:
                if isinstance(bit_rate, dict):
                    label = str(
                        bit_rate.get("gear_name")
                        or bit_rate.get("gearName")
                        or bit_rate.get("format")
                        or "bit_rate"
                    )
                    add_media(
                        media,
                        seen,
                        "video",
                        first_url(bit_rate.get("play_addr")),
                        label=label,
                        width=int_value(bit_rate.get("width") or video.get("width")),
                        height=int_value(bit_rate.get("height") or video.get("height")),
                        bitrate=int_value(
                            bit_rate.get("bit_rate")
                            or bit_rate.get("bitRate")
                            or bit_rate.get("quality_type")
                            or bit_rate.get("qualityType")
                        ),
                    )
                    add_media(
                        media,
                        seen,
                        "video",
                        first_url(bit_rate.get("playAddr")),
                        label=label,
                        width=int_value(bit_rate.get("width") or video.get("width")),
                        height=int_value(bit_rate.get("height") or video.get("height")),
                        bitrate=int_value(
                            bit_rate.get("bit_rate")
                            or bit_rate.get("bitRate")
                            or bit_rate.get("quality_type")
                            or bit_rate.get("qualityType")
                        ),
                    )

    image_groups = [
        item.get("images"),
        item.get("image_infos"),
        item.get("imageInfos"),
    ]
    image_post_info = item.get("image_post_info") or item.get("imagePostInfo")
    if isinstance(image_post_info, dict):
        image_groups.extend(
            [
                image_post_info.get("images"),
                image_post_info.get("image_infos"),
                image_post_info.get("imageInfos"),
            ]
        )

    for images in image_groups:
        if not isinstance(images, list):
            continue
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in (
                "url_list",
                "urlList",
                "download_url_list",
                "downloadUrlList",
                "display_image",
                "displayImage",
                "origin_cover",
                "originCover",
                "origin_image",
                "originImage",
                "thumbnail",
                "thumbnail_image",
                "thumbnailImage",
            ):
                add_media(media, seen, "image", first_url(image.get(key)))

    return media


def extract_media_from_payload(payload: Any, work_id: str) -> list[MediaItem]:
    for item in iter_dicts(payload):
        if aweme_id_matches(item, work_id):
            media = extract_media_from_aweme(item)
            if media:
                return media
    return []


def extract_first_media_from_payload(payload: Any) -> list[MediaItem]:
    """Fallback for detail responses that omit aweme_id after modal navigation."""
    for item in iter_dicts(payload):
        if not isinstance(item, dict) or not (item.get("video") or item.get("images") or item.get("image_post_info") or item.get("imagePostInfo")):
            continue
        media = extract_media_from_aweme(item)
        if media:
            return media
    return []


def extract_media_from_page_dom(page: Page, *, prefer_images: bool) -> list[MediaItem]:
    image_urls = page.evaluate(
        """() => {
            const seen = new Set();
            return Array.from(document.images)
                .map(img => ({
                    src: img.currentSrc || img.src,
                    width: img.naturalWidth || 0,
                    height: img.naturalHeight || 0,
                }))
                .filter(item => item.src && !item.src.startsWith('data:'))
                .filter(item => item.width >= 600 && item.height >= 600)
                .filter(item => item.src.includes('aweme_images') || item.src.includes('PackSourceEnum_AWEME_DETAIL'))
                .sort((a, b) => (b.width * b.height) - (a.width * a.height))
                .filter(item => {
                    const key = item.src.split('?')[0];
                    if (seen.has(key)) return false;
                    seen.add(key);
                    return true;
                })
                .map(item => item.src);
        }"""
    )
    media: list[MediaItem] = []
    seen: set[str] = set()
    if prefer_images and isinstance(image_urls, list):
        for image_url in image_urls:
            if isinstance(image_url, str):
                add_media(media, seen, "image", image_url, label="dom_aweme_image")
    if not prefer_images:
        video_urls = page.evaluate(
            """() => Array.from(document.querySelectorAll('video, video source'))
                .map(item => item.currentSrc || item.src || '')
                .filter(url => /^https?:/i.test(url))"""
        )
        if isinstance(video_urls, list):
            for video_url in video_urls:
                if isinstance(video_url, str):
                    add_media(media, seen, "video", video_url, label="dom_video")
    return media


def extract_work_urls_from_payload(payload: Any, sec_uid: str) -> set[str]:
    urls: set[str] = set()
    for item in iter_dicts(payload):
        if not author_matches(item, sec_uid):
            continue
        if url := work_url_from_aweme(item):
            urls.add(url)
    return urls


def extract_work_items_from_payload(payload: Any, sec_uid: str) -> dict[str, dict[str, str]]:
    items: dict[str, dict[str, str]] = {}
    for item in iter_dicts(payload):
        if not author_matches(item, sec_uid):
            continue
        work_item = work_item_from_aweme(item)
        if work_item:
            items[work_item["url"]] = work_item
    return items


def payload_page_info(payload: Any) -> tuple[Any, Any]:
    if not isinstance(payload, dict):
        return None, None

    has_more = payload.get("has_more")
    max_cursor = payload.get("max_cursor")
    if has_more is None:
        has_more = payload.get("hasMore")
    if max_cursor is None:
        max_cursor = payload.get("maxCursor")

    return has_more, max_cursor


def replace_query_param(raw_url: str, name: str, value: Any) -> str:
    parts = urlsplit(raw_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query[name] = str(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def display_api_path(raw_url: str | None) -> str | None:
    if not raw_url:
        return None
    parts = urlsplit(raw_url)
    return parts.path


def truthy_has_more(value: Any) -> bool:
    return value is True or value == 1 or value == "1" or value == "true"


def trigger_next_page(page: Page, scroll_pixels: int) -> None:
    page.mouse.wheel(0, scroll_pixels)
    page.keyboard.press("PageDown")
    page.evaluate(
        """scrollPixels => {
            const candidates = [document.scrollingElement, document.documentElement, document.body]
                .concat(Array.from(document.querySelectorAll('*')))
                .filter(Boolean)
                .filter(el => el.scrollHeight > el.clientHeight + 20);

            candidates
                .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))
                .slice(0, 6)
                .forEach(el => {
                    el.scrollTop = Math.min(el.scrollTop + scrollPixels, el.scrollHeight);
                    el.dispatchEvent(new Event('scroll', { bubbles: true }));
                });

            window.dispatchEvent(new Event('scroll'));
        }""",
        scroll_pixels,
    )


def safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value).strip("_") or "douyin_work"


def download_url(context, url: str, destination: Path, referer: str) -> None:
    response = context.request.get(
        url,
        headers={
            "referer": referer,
            "user-agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        },
        timeout=90_000,
    )
    if not response.ok:
        raise RuntimeError(f"Download failed: HTTP {response.status} {url}")
    destination.write_bytes(response.body())


def media_content_length(context, item: MediaItem, referer: str) -> int:
    try:
        response = context.request.head(
            item.url,
            headers={
                "referer": referer,
                "user-agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
            },
            timeout=30_000,
        )
        if not response.ok:
            return 0
        return int(response.headers.get("content-length", "0") or "0")
    except Exception:
        return 0


def mp4_handler_types(data: bytes) -> set[str]:
    handlers: set[str] = set()

    def walk(start: int, end: int) -> None:
        offset = start
        while offset + 8 <= end:
            size = int.from_bytes(data[offset : offset + 4], "big", signed=False)
            box_type = data[offset + 4 : offset + 8]
            header_size = 8
            if size == 1 and offset + 16 <= end:
                size = int.from_bytes(data[offset + 8 : offset + 16], "big", signed=False)
                header_size = 16
            elif size == 0:
                size = end - offset
            if size < header_size or offset + size > len(data):
                break

            payload_start = offset + header_size
            payload_end = offset + size
            if box_type == b"hdlr" and payload_start + 12 <= payload_end:
                handler = data[payload_start + 8 : payload_start + 12].decode("latin1", errors="ignore")
                if handler:
                    handlers.add(handler)
            elif box_type in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
                walk(payload_start, payload_end)
            offset += size

    walk(0, len(data))
    return handlers


def downloaded_file_has_video(path: Path) -> bool:
    try:
        data = path.read_bytes()
    except OSError:
        return False
    handlers = mp4_handler_types(data)
    return "vide" in handlers


def media_rank(context, item: MediaItem, referer: str) -> tuple[int, int, int, int]:
    lowered = f"{item.url} {item.label}".lower()
    penalty = 0
    if "audio" in lowered or "music" in lowered or "soun" in lowered:
        penalty -= 5_000_000_000
    if "dash" in lowered or "adaptation" in lowered:
        penalty -= 500_000_000
    if "watermark" in lowered or "download" in lowered:
        penalty += 100_000_000

    area = item.width * item.height
    length = media_content_length(context, item, referer)
    return (penalty + area, item.bitrate, length, -len(item.url))


def choose_default_media(
    context,
    media: list[MediaItem],
    referer: str,
    *,
    prefer_images: bool = False,
) -> list[MediaItem]:
    images = [item for item in media if item.kind == "image"]
    if prefer_images and images:
        return images[:1]

    videos = [item for item in media if item.kind == "video"]
    if videos:
        ranked = sorted(
            videos,
            key=lambda item: media_rank(context, item, referer),
            reverse=True,
        )
        return ranked

    return images or media


_download_lock = threading.Lock()


def download_work_media(work_url, **kwargs):
    # The reusable download profile has one browser writer; model work has its own queue.
    with _download_lock:
        return _download_work_media(work_url, **kwargs)


def _download_work_media(
    work_url: str,
    *,
    output_dir: Path,
    headless: bool,
    user_data_dir: Path,
    all_media: bool = False,
    wait_seconds: float = 6.0,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    emit_progress(progress_callback, "正在解析作品链接")
    work_url = resolve_douyin_work_url(work_url)
    work_id = parse_work_id(work_url)
    prefer_images = is_note_work_url(work_url)
    output_dir.mkdir(parents=True, exist_ok=True)
    emit_progress(progress_callback, "正在打开作品页面")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        media: list[MediaItem] = []

        def handle_response(response: Response) -> None:
            nonlocal media
            if media or not looks_like_douyin_json_response(response):
                return
            payload = response_json(response)
            if payload is None:
                return
            media = extract_media_from_payload(payload, work_id)
            if not media and (f"/video/{work_id}" in page.url or f"/note/{work_id}" in page.url):
                media = extract_first_media_from_payload(payload)

        page.on("response", handle_response)
        page.goto(work_url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(int(wait_seconds * 1000))
        close_popups(page)

        if not media:
            page.mouse.click(640, 450)
            page.keyboard.press("Space")
            emit_progress(progress_callback, "正在触发页面播放以捕获媒体接口")
            page.wait_for_timeout(2500)

        fallback_url = standard_open_url(work_url)
        if not media and fallback_url not in page.url:
            message = f"retry_with_standard_url: {fallback_url}"
            emit_progress(progress_callback, "正在改用标准作品地址重试")
            print(message, file=sys.stderr, flush=True)
            page.goto(fallback_url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(int(wait_seconds * 1000))
            close_popups(page)

        if not media:
            emit_progress(progress_callback, "接口未返回媒体，正在从页面图片提取")
            media = extract_media_from_page_dom(page, prefer_images=prefer_images)
            if media:
                print(f"dom_media_found media={len(media)}", file=sys.stderr, flush=True)

        if not media:
            context.close()
            raise RuntimeError(
                "No downloadable media URL was found. Try --headful and finish login/captcha first."
            )

        if not all_media:
            media = choose_default_media(context, media, work_url, prefer_images=prefer_images)
            if prefer_images and not any(item.kind == "image" for item in media):
                context.close()
                raise RuntimeError(
                    "No downloadable image URL was found for this note. Try --headful and finish login/captcha first."
                )
        emit_progress(progress_callback, f"已找到 {len(media)} 个候选媒体，开始下载")

        downloaded: list[Path] = []
        base_name = safe_name(work_id)
        for index, item in enumerate(media, start=1):
            path = output_dir / f"{base_name}_{item.kind}_{index:02d}.{item.extension}"
            emit_progress(progress_callback, f"正在下载候选 {index}/{len(media)}")
            if all_media or item.kind != "video":
                download_url(context, item.url, path, work_url)
                downloaded.append(path)
                message = f"downloaded {item.kind}: {path}"
                emit_progress(progress_callback, message)
                print(message, file=sys.stderr, flush=True)
                continue

            temp_path = output_dir / f"{base_name}_{item.kind}_{index:02d}.partial.{item.extension}"
            download_url(context, item.url, temp_path, work_url)
            if downloaded_file_has_video(temp_path):
                os.replace(temp_path, path)
                downloaded.append(path)
                message = f"downloaded {item.kind}: {path}"
                emit_progress(progress_callback, message)
                print(message, file=sys.stderr, flush=True)
                break

            temp_path.unlink(missing_ok=True)
            message = f"skipped_audio_only_candidate: {index}/{len(media)}"
            emit_progress(progress_callback, "当前候选只有音频，正在尝试下一个视频源")
            print(message, file=sys.stderr, flush=True)

        if not downloaded:
            context.close()
            raise RuntimeError("No downloaded candidate contained a video track.")

        context.close()

    return downloaded


def click_labeled_action(page: Page, label: str, already_labels: tuple[str, ...]) -> bool:
    clicked = page.evaluate(
        """({ label, alreadyLabels }) => {
            const elements = Array.from(document.querySelectorAll(
                'button, [role="button"], [aria-label], [title], div, span'
            ));

            function visible(el) {
                const rect = el.getBoundingClientRect();
                const style = window.getComputedStyle(el);
                return rect.width > 0 && rect.height > 0 &&
                    style.visibility !== 'hidden' && style.display !== 'none';
            }

            for (const el of elements) {
                if (!visible(el)) continue;
                const text = [
                    el.getAttribute('aria-label') || '',
                    el.getAttribute('title') || '',
                    el.textContent || '',
                ].join(' ');
                if (!text.includes(label)) continue;
                if (alreadyLabels.some(item => text.includes(item))) return false;

                const clickable = el.closest('button, [role="button"]') || el;
                clickable.click();
                return true;
            }
            return false;
        }""",
        {"label": label, "alreadyLabels": list(already_labels)},
    )
    if clicked:
        page.wait_for_timeout(1200)
    return bool(clicked)


def submit_comment(page: Page, comment_text: str) -> bool:
    selectors = [
        "textarea[placeholder*='评论']",
        "input[placeholder*='评论']",
        "[contenteditable='true'][placeholder*='评论']",
        "[contenteditable='true']",
    ]

    for selector in selectors:
        locator = page.locator(selector).first
        try:
            if not locator.is_visible(timeout=1200):
                continue
            locator.click(timeout=2000)
            locator.fill(comment_text, timeout=3000)
            break
        except Exception:
            continue
    else:
        page.locator("[aria-label*='评论'], button:has-text('评论')").first.click(timeout=3000)
        page.wait_for_timeout(1000)
        for selector in selectors:
            locator = page.locator(selector).first
            try:
                if not locator.is_visible(timeout=1200):
                    continue
                locator.click(timeout=2000)
                locator.fill(comment_text, timeout=3000)
                break
            except Exception:
                continue
        else:
            return False

    send_selectors = [
        "button:has-text('发布')",
        "button:has-text('发送')",
        "[role='button']:has-text('发布')",
        "[role='button']:has-text('发送')",
    ]
    for selector in send_selectors:
        locator = page.locator(selector).first
        try:
            if locator.is_visible(timeout=1200):
                locator.click(timeout=3000)
                page.wait_for_timeout(1800)
                return True
        except Exception:
            continue

    page.keyboard.press("Control+Enter")
    page.wait_for_timeout(1800)
    return True


def interact_with_work(
    work_url: str,
    *,
    comment_text: str | None,
    like: bool,
    favorite: bool,
    headless: bool,
    user_data_dir: Path,
    wait_seconds: float = 6.0,
) -> dict[str, bool]:
    work_id = parse_work_id(work_url)

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=headless,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto(work_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(int(wait_seconds * 1000))
        close_popups(page)

        if f"/video/{work_id}" not in page.url and f"/note/{work_id}" not in page.url:
            page.goto(standard_video_url(work_id), wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(int(wait_seconds * 1000))
            close_popups(page)

        result = {"liked": False, "favorited": False, "commented": False}
        if like:
            result["liked"] = click_labeled_action(page, "点赞", ("已点赞", "取消点赞"))
        if favorite:
            result["favorited"] = click_labeled_action(page, "收藏", ("已收藏", "取消收藏"))
        if comment_text:
            result["commented"] = submit_comment(page, comment_text)

        context.close()

    return result


def douyin_api_headers(referer: str) -> dict[str, str]:
    return {
        "accept": "application/json, text/plain, */*",
        "referer": referer,
        "user-agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "x-requested-with": "XMLHttpRequest",
    }


def api_fetch_from_page(
    page: Page,
    endpoint: str,
    params: dict[str, Any],
    *,
    method: str = "POST",
) -> dict[str, Any]:
    result = page.evaluate(
        """async ({ endpoint, params, method }) => {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), 15000);
            const cleanParams = {};
            for (const [key, value] of Object.entries(params)) {
                if (value !== null && value !== undefined) cleanParams[key] = String(value);
            }

            const body = new URLSearchParams(cleanParams);
            const options = {
                method,
                credentials: 'include',
                signal: controller.signal,
                headers: {
                    accept: 'application/json, text/plain, */*',
                    'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
                    'x-requested-with': 'XMLHttpRequest',
                },
            };

            let url = endpoint;
            if (method === 'GET') {
                url = `${endpoint}?${body.toString()}`;
            } else {
                options.body = body.toString();
            }

            try {
                const response = await fetch(url, options);
                const text = await response.text();
                return { ok: response.ok, status: response.status, url, text };
            } catch (error) {
                return { ok: false, status: 0, url, text: String(error && error.message || error) };
            } finally {
                clearTimeout(timer);
            }
        }""",
        {"endpoint": endpoint, "params": params, "method": method},
    )
    text = result["text"]
    payload = parse_json_text(text)
    return {
        "ok": result["ok"],
        "status": result["status"],
        "url": endpoint,
        "payload": payload,
        "text": text[:300] if payload is None else None,
    }


def douyin_common_params(work_id: str) -> dict[str, Any]:
    return {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "aweme_id": work_id,
        "pc_client_type": "1",
        "version_code": "190500",
        "version_name": "19.5.0",
        "cookie_enabled": "true",
        "screen_width": "1280",
        "screen_height": "900",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "124.0.0.0",
    }


def api_success(result: dict[str, Any], *, require_field: str | None = None) -> bool:
    payload = result.get("payload")
    if not result.get("ok") or not isinstance(payload, dict):
        return False

    status_code = payload.get("status_code")
    if status_code is None:
        status_code = payload.get("statusCode")
    if status_code not in (None, 0):
        return False

    status_msg = payload.get("status_msg")
    if status_msg and status_msg not in ("success", "ok"):
        return False

    if require_field and not payload.get(require_field):
        return False

    return True


def interact_with_work_api(
    work_url: str,
    *,
    comment_text: str | None,
    like: bool,
    favorite: bool,
    user_data_dir: Path,
) -> dict[str, Any]:
    work_id = parse_work_id(work_url)
    referer = standard_video_url(work_id)
    results: dict[str, Any] = {}

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=True,
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            page.goto(referer, wait_until="domcontentloaded", timeout=20_000)
            page.wait_for_timeout(3000)
            close_popups(page)
        except Exception as exc:
            results["page_init"] = {"success": False, "error": str(exc)}

        base_params = douyin_common_params(work_id)
        if like:
            result = api_fetch_from_page(
                page,
                "https://www.douyin.com/aweme/v1/web/commit/item/digg/",
                {**base_params, "type": "1"},
            )
            results["like"] = {"success": api_success(result), "status": result["status"], "payload": result["payload"]}

        if favorite:
            result = api_fetch_from_page(
                page,
                "https://www.douyin.com/aweme/v1/web/aweme/collect/",
                {**base_params, "action": "1"},
            )
            results["favorite"] = {
                "success": api_success(result),
                "status": result["status"],
                "payload": result["payload"],
            }

        if comment_text:
            result = api_fetch_from_page(
                page,
                "https://www.douyin.com/aweme/v1/web/comment/publish/",
                {**base_params, "text": comment_text, "text_extra": "[]"},
            )
            results["comment"] = {
                "success": api_success(result, require_field="comment"),
                "status": result["status"],
                "payload": result["payload"],
                "text": result["text"],
            }

        context.close()

    return results


def run_extension_bridge(
    work_url: str,
    *,
    comment_text: str | None,
    like: bool,
    favorite: bool,
    port: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    command_id = uuid.uuid4().hex
    work_id = parse_work_id(work_url)
    command = {
        "id": command_id,
        "url": work_url,
        "openUrl": standard_open_url(work_url),
        "workId": work_id,
        "comment": comment_text or "",
        "like": like,
        "favorite": favorite,
    }
    state: dict[str, Any] = {
        "delivered": False,
        "result": None,
        "progress": None,
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return

            if self.path == "/command":
                if state["delivered"]:
                    self._send_json(200, {"ok": True, "command": None})
                    return
                state["delivered"] = True
                self._send_json(200, {"ok": True, "command": command})
                return

            self._send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            if self.path == "/progress":
                length = int(self.headers.get("content-length", "0") or "0")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8", errors="replace"))
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if payload.get("id") != command_id:
                    self._send_json(409, {"ok": False, "error": "command id mismatch"})
                    return
                state["progress"] = payload.get("data") or {}
                self._send_json(200, {"ok": True})
                return

            if self.path != "/result":
                self._send_json(404, {"ok": False, "error": "not found"})
                return

            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

            if payload.get("id") != command_id:
                self._send_json(409, {"ok": False, "error": "command id mismatch"})
                return

            state["result"] = payload
            self._send_json(200, {"ok": True})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(
        f"extension_bridge listening=http://127.0.0.1:{port} command_id={command_id}",
        file=sys.stderr,
        flush=True,
    )
    print(
        "Open a logged-in douyin.com tab with the Chrome extension enabled.",
        file=sys.stderr,
        flush=True,
    )

    deadline = time.time() + timeout_seconds
    try:
        while time.time() < deadline:
            if state["result"] is not None:
                result = state["result"]
                data = ((result.get("result") or {}).get("data") or {})
                version = data.get("version")
                if version and version != EXPECTED_EXTENSION_VERSION:
                    result["version_warning"] = (
                        f"Chrome extension page script version is {version}, expected {EXPECTED_EXTENSION_VERSION}. "
                        "Reload the extension and refresh the douyin.com tab."
                    )
                elif not version:
                    result["version_warning"] = (
                        "Chrome extension returned an old result format. "
                        "Reload the extension and refresh the douyin.com tab."
                    )
                return result
            time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()

    return {
        "ok": False,
        "error": (
            "Timed out waiting for Chrome extension. "
            "Reload the extension, keep a logged-in douyin.com tab open, and retry."
        ),
        "delivered": state["delivered"],
    }


def run_extension_profile_collect(
    homepage_url: str,
    *,
    max_scrolls: int,
    target_count: int | None,
    wait_seconds: float,
    port: int = 18765,
    timeout_seconds: float | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    command_id = uuid.uuid4().hex
    if timeout_seconds is None:
        timeout_seconds = max(90.0, max_scrolls * max(wait_seconds, 0.5) + 45.0)

    command = {
        "id": command_id,
        "action": "collectProfile",
        "url": homepage_url,
        "openUrl": homepage_url,
        "profileUrl": homepage_url,
        "maxScrolls": max_scrolls,
        "targetCount": target_count,
        "waitMs": int(wait_seconds * 1000),
        "timeoutMs": int(timeout_seconds * 1000),
    }
    state: dict[str, Any] = {
        "delivered": False,
        "result": None,
        "progress": None,
    }

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("access-control-allow-origin", "*")
            self.send_header("access-control-allow-methods", "GET, POST, OPTIONS")
            self.send_header("access-control-allow-headers", "content-type")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_OPTIONS(self) -> None:
            self._send_json(200, {"ok": True})

        def do_GET(self) -> None:
            if self.path == "/health":
                self._send_json(200, {"ok": True})
                return

            if self.path == "/command":
                if state["delivered"]:
                    self._send_json(200, {"ok": True, "command": None})
                    return
                state["delivered"] = True
                self._send_json(200, {"ok": True, "command": command})
                return

            self._send_json(404, {"ok": False, "error": "not found"})

        def do_POST(self) -> None:
            if self.path == "/progress":
                length = int(self.headers.get("content-length", "0") or "0")
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8", errors="replace"))
                except Exception as exc:
                    self._send_json(400, {"ok": False, "error": str(exc)})
                    return
                if payload.get("id") != command_id:
                    self._send_json(409, {"ok": False, "error": "command id mismatch"})
                    return
                state["progress"] = payload.get("data") or {}
                self._send_json(200, {"ok": True})
                return

            if self.path != "/result":
                self._send_json(404, {"ok": False, "error": "not found"})
                return

            length = int(self.headers.get("content-length", "0") or "0")
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            try:
                payload = json.loads(raw)
            except Exception as exc:
                self._send_json(400, {"ok": False, "error": str(exc)})
                return

            if payload.get("id") != command_id:
                self._send_json(409, {"ok": False, "error": "command id mismatch"})
                return

            state["result"] = payload
            self._send_json(200, {"ok": True})

    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print(
        f"extension_profile_collect listening=http://127.0.0.1:{port} command_id={command_id}",
        file=sys.stderr,
        flush=True,
    )
    print(
        "Keep Chrome open with the Douyin Tools extension enabled. The extension will open the profile page.",
        file=sys.stderr,
        flush=True,
    )

    deadline = time.time() + timeout_seconds
    last_progress_signature = ""
    try:
        while time.time() < deadline:
            progress_data = state.get("progress") or {}
            progress_signature = json.dumps(progress_data, ensure_ascii=False, sort_keys=True)
            if progress_data and progress_signature != last_progress_signature:
                last_progress_signature = progress_signature
                progress_items = progress_data.get("items") or []
                if target_count:
                    progress_items = progress_items[:target_count]
                if progress_callback:
                    progress_callback(
                        f"正在拉取：第 {progress_data.get('scroll', 0)} 轮，已发现 {len(progress_items)} 条，捕获分页 {progress_data.get('capturedPages', 0)} 页",
                        {"urls": [item.get("url") for item in progress_items if isinstance(item, dict) and item.get("url")], "items": progress_items, "partial": True},
                    )
            if state["result"] is not None:
                result = state["result"]
                if not result.get("ok"):
                    return {
                        "ok": False,
                        "error": result.get("error") or "Chrome extension command failed",
                        "raw": result,
                    }

                content_result = result.get("result") or {}
                if not content_result.get("ok"):
                    return {
                        "ok": False,
                        "error": content_result.get("error") or "Chrome extension page command failed",
                        "raw": result,
                    }

                data = content_result.get("data") or {}
                version = data.get("version")
                if version and version != EXPECTED_EXTENSION_VERSION:
                    data["version_warning"] = (
                        f"Chrome extension page script version is {version}, expected {EXPECTED_EXTENSION_VERSION}. "
                        "Reload the extension and refresh the douyin.com tab."
                    )
                elif not version:
                    data["version_warning"] = (
                        "Chrome extension returned an old result format. "
                        "Reload the extension and refresh the douyin.com tab."
                    )

                items = data.get("items") or []
                if target_count:
                    items = items[:target_count]
                urls = [item.get("url") for item in items if isinstance(item, dict) and item.get("url")]
                return {
                    "ok": True,
                    "urls": urls,
                    "items": items,
                    "responses": data.get("responses") or [],
                    "captured_pages": data.get("capturedPages"),
                    "elapsed_ms": data.get("elapsedMs"),
                    "version_warning": data.get("version_warning"),
                }
            time.sleep(0.25)
    finally:
        server.shutdown()
        server.server_close()

    return {
        "ok": False,
        "error": (
            "Timed out waiting for Chrome extension. "
            f"Reload extension version {EXPECTED_EXTENSION_VERSION}, keep Chrome open, and retry."
        ),
        "delivered": state["delivered"],
    }


def collect_urls(
    homepage_url: str,
    *,
    headless: bool,
    max_scrolls: int,
    idle_rounds: int,
    target_count: int | None,
    scroll_pixels: int,
    user_data_dir: Path,
    wait_seconds: float,
    progress_callback: ProgressCallback | None = None,
) -> list[str]:
    sec_uid = parse_sec_uid(homepage_url)

    def progress(message: str, urls: set[str]) -> None:
        items = [work_items.get(url) or {"url": url, "title": url, "cover": "", "type": ""} for url in sorted(urls)]
        emit_progress(progress_callback, message, {"urls": sorted(urls), "items": items, "partial": True})

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(user_data_dir),
            headless=headless,
            viewport={"width": 1440, "height": 1100},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        seen: set[str] = set()
        work_items: dict[str, dict[str, str]] = {}
        api_hits = 0
        last_has_more: Any = None
        last_cursor: Any = None
        last_api_url: str | None = None
        fetched_cursors: set[str] = set()
        pagination_blocked = False

        def handle_response(response: Response) -> None:
            nonlocal api_hits, last_has_more, last_cursor, last_api_url
            if not looks_like_douyin_aweme_response(response):
                return
            payload = response_json(response)
            if payload is None:
                return
            has_more, max_cursor = payload_page_info(payload)
            if has_more is not None:
                last_has_more = has_more
            if max_cursor is not None:
                last_cursor = max_cursor
            items = extract_work_items_from_payload(payload, sec_uid)
            urls = set(items) or extract_work_urls_from_payload(payload, sec_uid)
            if urls:
                api_hits += 1
                last_api_url = response.url
                seen.update(urls)
                work_items.update(items)

        def fetch_next_cursor() -> int:
            nonlocal api_hits, last_has_more, last_cursor, last_api_url, pagination_blocked

            if not last_api_url or last_cursor is None:
                return 0

            cursor_key = str(last_cursor)
            if cursor_key in fetched_cursors:
                return 0
            fetched_cursors.add(cursor_key)

            next_url = replace_query_param(last_api_url, "max_cursor", last_cursor)
            result = page.evaluate(
                """async url => {
                    const response = await fetch(url, {
                        credentials: 'include',
                        headers: { accept: 'application/json, text/plain, */*' },
                    });
                    return { ok: response.ok, status: response.status, text: await response.text() };
                }""",
                next_url,
            )

            if not result.get("ok"):
                message = f"direct_page_fetch status={result.get('status')} cursor={last_cursor}"
                progress(message, seen)
                print(message, file=sys.stderr, flush=True)
                return 0

            payload = parse_json_text(result["text"])
            if payload is None:
                snippet = result["text"][:120].replace("\n", "\\n").replace("\r", "\\r")
                pagination_blocked = True
                message = (
                    f"direct_page_fetch non_json status={result.get('status')} "
                    f"cursor={last_cursor} body={snippet!r}; "
                    "pagination_blocked=Douyin returned HTML instead of JSON, likely due to signed pagination parameters"
                )
                progress(message, seen)
                print(message, file=sys.stderr, flush=True)
                return 0

            has_more, max_cursor = payload_page_info(payload)
            if has_more is not None:
                last_has_more = has_more
            if max_cursor is not None:
                last_cursor = max_cursor

            items = extract_work_items_from_payload(payload, sec_uid)
            urls = set(items) or extract_work_urls_from_payload(payload, sec_uid)
            before = len(seen)
            seen.update(urls)
            work_items.update(items)
            if urls:
                api_hits += 1
                last_api_url = next_url
            added = len(seen) - before
            message = (
                f"direct_page_fetch status={result.get('status')} extracted={len(urls)} "
                f"added={added} has_more={last_has_more} cursor={last_cursor}"
            )
            progress(message, seen)
            print(message, file=sys.stderr, flush=True)
            return added

        page.on("response", handle_response)
        page.goto(homepage_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        close_popups(page)

        unchanged_rounds = 0
        message = (
            f"scroll=000 found={len(seen)} added={len(seen)} "
            f"api_pages={api_hits} has_more={last_has_more} cursor={last_cursor} "
            f"api={display_api_path(last_api_url)}"
        )
        progress(message, seen)
        print(message, file=sys.stderr, flush=True)

        for index in range(1, max_scrolls + 1):
            before = len(seen)
            trigger_next_page(page, scroll_pixels)
            page.wait_for_timeout(int(wait_seconds * 1000))
            close_popups(page)

            added = len(seen) - before
            if added == 0 and truthy_has_more(last_has_more):
                added = fetch_next_cursor()

            message = (
                f"scroll={index:03d} found={len(seen)} added={added} "
                f"api_pages={api_hits} has_more={last_has_more} cursor={last_cursor} "
                f"api={display_api_path(last_api_url)}"
            )
            progress(message, seen)
            print(message, file=sys.stderr, flush=True)

            if target_count is not None and len(seen) >= target_count:
                break

            if added == 0:
                unchanged_rounds += 1
            else:
                unchanged_rounds = 0

            if unchanged_rounds >= idle_rounds:
                break

            if pagination_blocked and unchanged_rounds >= 3:
                message = (
                    f"pagination_stopped found={len(seen)} reason=signed_next_page_blocked; "
                    "try visible browser login/verification or a Douyin page context that can generate fresh pagination signatures"
                )
                progress(message, seen)
                print(message, file=sys.stderr, flush=True)
                break

        context.close()

    return sorted(seen)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect Douyin work URLs or download one work's media."
    )
    parser.add_argument("homepage_url", nargs="?", help="Douyin creator homepage URL")
    parser.add_argument(
        "-o",
        "--output",
        help="Optional output file. Use .json for JSON, otherwise one URL per line.",
    )
    parser.add_argument("--download", help="Download media from one Douyin video/note URL")
    parser.add_argument(
        "--download-dir",
        type=Path,
        default=service_store("douyin") / "downloads",
        help="Directory for --download output files",
    )
    parser.add_argument(
        "--all-media",
        action="store_true",
        help="Download all candidate media URLs instead of only the first video source",
    )
    parser.add_argument("--interact", help="Interact with one Douyin video/note URL")
    parser.add_argument(
        "--api-interact",
        help="Interact through Douyin web API using cookies from --user-data-dir",
    )
    parser.add_argument(
        "--extension-interact",
        help="Send an interact command to the installed Chrome extension bridge",
    )
    parser.add_argument(
        "--extension-collect",
        help="Collect a Douyin creator homepage through the installed Chrome extension bridge",
    )
    parser.add_argument("--comment", help="Comment text for --interact")
    parser.add_argument("--like", action="store_true", help="Like the work for --interact")
    parser.add_argument("--favorite", action="store_true", help="Favorite the work for --interact")
    parser.add_argument("--bridge-port", type=int, default=18765, help="Local extension bridge port")
    parser.add_argument(
        "--bridge-timeout",
        type=float,
        default=60,
        help="Seconds to wait for the Chrome extension bridge result",
    )
    parser.add_argument("--headful", action="store_true", help="Show the browser window")
    parser.add_argument("--max-scrolls", type=int, default=500, help="Maximum scroll attempts")
    parser.add_argument(
        "--idle-rounds",
        type=int,
        default=20,
        help="Stop after this many scrolls without discovering new URLs",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        help="Stop after collecting at least this many work URLs",
    )
    parser.add_argument(
        "--scroll-pixels",
        type=int,
        default=3500,
        help="Mouse wheel distance for each pagination scroll",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=1.5,
        help="Seconds to wait after each scroll",
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=service_store("douyin") / ".douyin-browser",
        help="Browser profile directory. Reused so manual login can persist.",
    )
    parser.add_argument("--web", action="store_true", help="Start the web interface")
    parser.add_argument("--web-host", default="127.0.0.1", help="Host for --web")
    parser.add_argument("--web-port", type=int, default=8003, help="Port for --web")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path("cache"),
        help="Directory for disposable temporary files",
    )
    parser.add_argument("--store-dir", type=Path, default=service_store("douyin"), help="Persistent state, history, media, and browser profiles")
    args = parser.parse_args()

    if args.web:
        os.environ["DOUYIN_STORE_DIR"] = str(args.store_dir.resolve().parent)
        run_web_server(args.web_host, args.web_port, args.cache_dir, args.store_dir)
        return 0

    if args.download:
        downloaded = download_work_media(
            args.download,
            output_dir=args.download_dir,
            headless=not args.headful,
            user_data_dir=args.user_data_dir,
            all_media=args.all_media,
            wait_seconds=args.wait,
        )
        for path in downloaded:
            print(path)
        print(f"\nDownloaded: {len(downloaded)}", file=sys.stderr)
        return 0

    if args.interact:
        if not args.comment and not args.like and not args.favorite:
            parser.error("--interact requires at least one of --comment, --like, or --favorite")

        result = interact_with_work(
            args.interact,
            comment_text=args.comment,
            like=args.like,
            favorite=args.favorite,
            headless=not args.headful,
            user_data_dir=args.user_data_dir,
            wait_seconds=args.wait,
        )
        print_json(result)
        return 0

    if args.api_interact:
        if not args.comment and not args.like and not args.favorite:
            parser.error("--api-interact requires at least one of --comment, --like, or --favorite")

        result = interact_with_work_api(
            args.api_interact,
            comment_text=args.comment,
            like=args.like,
            favorite=args.favorite,
            user_data_dir=args.user_data_dir,
        )
        print_json(result)
        return 0

    if args.extension_interact:
        if not args.comment and not args.like and not args.favorite:
            parser.error("--extension-interact requires at least one of --comment, --like, or --favorite")

        result = run_extension_bridge(
            args.extension_interact,
            comment_text=args.comment,
            like=args.like,
            favorite=args.favorite,
            port=args.bridge_port,
            timeout_seconds=args.bridge_timeout,
        )
        print_json(result)
        return 0

    if args.extension_collect:
        result = run_extension_profile_collect(
            args.extension_collect,
            max_scrolls=args.max_scrolls,
            target_count=args.target_count,
            wait_seconds=args.wait,
            port=args.bridge_port,
            timeout_seconds=max(args.bridge_timeout, args.max_scrolls * max(args.wait, 0.5) + 45),
        )
        if not result.get("ok"):
            print_json(result)
            return 1

        urls = result.get("urls") or []
        if args.output:
            output = Path(args.output)
            if output.suffix.lower() == ".json":
                payload = {
                    "urls": urls,
                    "items": result.get("items") or [],
                    "responses": result.get("responses") or [],
                }
                output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

        for url in urls:
            print(url)
        print(f"\nTotal: {len(urls)}", file=sys.stderr)
        if result.get("version_warning"):
            print(result["version_warning"], file=sys.stderr)
        return 0

    if not args.homepage_url:
        parser.error("homepage_url is required unless --download is used")

    urls = collect_urls(
        args.homepage_url,
        headless=not args.headful,
        max_scrolls=args.max_scrolls,
        idle_rounds=args.idle_rounds,
        target_count=args.target_count,
        scroll_pixels=args.scroll_pixels,
        user_data_dir=args.user_data_dir,
        wait_seconds=args.wait,
    )

    if args.output:
        output = Path(args.output)
        if output.suffix.lower() == ".json":
            output.write_text(json.dumps(urls, ensure_ascii=False, indent=2), encoding="utf-8")
        else:
            output.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")

    for url in urls:
        print(url)

    print(f"\nTotal: {len(urls)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
