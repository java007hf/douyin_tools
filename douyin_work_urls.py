#!/usr/bin/env python3
"""
Fetch work URLs from a Douyin creator homepage.

Usage:
  python douyin_work_urls.py "https://www.douyin.com/user/..." -o urls.txt

First-time setup:
  pip install -r requirements.txt
  python -m playwright install chromium
"""

from __future__ import annotations

import argparse
import http.server
import json
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, unquote, urlsplit, urlunsplit

from playwright.sync_api import Page, Response, TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright


NOTE_AWEME_TYPES = {68}


@dataclass(frozen=True)
class MediaItem:
    kind: str
    url: str
    extension: str


def print_json(data: Any) -> None:
    encoding = (sys.stdout.encoding or "").lower()
    ensure_ascii = "utf" not in encoding
    text = json.dumps(data, ensure_ascii=ensure_ascii, indent=2)
    sys.stdout.write(text)
    sys.stdout.write("\n")
    sys.stdout.flush()


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


def add_media(items: list[MediaItem], seen: set[str], kind: str, url: str | None) -> None:
    if not url or url in seen:
        return
    seen.add(url)
    extension = "mp4" if kind == "video" else image_extension_from_url(url)
    items.append(MediaItem(kind=kind, url=url, extension=extension))


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
            add_media(media, seen, "video", first_url(video.get(key)))

        bit_rates = video.get("bit_rate") or video.get("bitRate") or []
        if isinstance(bit_rates, list):
            for bit_rate in bit_rates:
                if isinstance(bit_rate, dict):
                    add_media(media, seen, "video", first_url(bit_rate.get("play_addr")))
                    add_media(media, seen, "video", first_url(bit_rate.get("playAddr")))

    images = item.get("images") or item.get("image_infos") or item.get("imageInfos") or []
    if isinstance(images, list):
        for image in images:
            if not isinstance(image, dict):
                continue
            for key in (
                "url_list",
                "urlList",
                "download_url_list",
                "downloadUrlList",
                "display_image",
                "origin_cover",
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


def extract_work_urls_from_payload(payload: Any, sec_uid: str) -> set[str]:
    urls: set[str] = set()
    for item in iter_dicts(payload):
        if not author_matches(item, sec_uid):
            continue
        if url := work_url_from_aweme(item):
            urls.add(url)
    return urls


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
        timeout=120_000,
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


def choose_default_media(context, media: list[MediaItem], referer: str) -> list[MediaItem]:
    videos = [item for item in media if item.kind == "video"]
    if videos:
        ranked = sorted(
            videos,
            key=lambda item: media_content_length(context, item, referer),
            reverse=True,
        )
        return ranked[:1]

    return media


def download_work_media(
    work_url: str,
    *,
    output_dir: Path,
    headless: bool,
    user_data_dir: Path,
    all_media: bool = False,
    wait_seconds: float = 6.0,
) -> list[Path]:
    work_id = parse_work_id(work_url)
    output_dir.mkdir(parents=True, exist_ok=True)

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

        page.on("response", handle_response)
        page.goto(work_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(int(wait_seconds * 1000))
        close_popups(page)

        if not media:
            page.mouse.click(640, 450)
            page.keyboard.press("Space")
            page.wait_for_timeout(2500)

        if not media and f"/video/{work_id}" not in page.url:
            fallback_url = standard_video_url(work_id)
            print(f"retry_with_standard_url: {fallback_url}", file=sys.stderr, flush=True)
            page.goto(fallback_url, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(int(wait_seconds * 1000))
            close_popups(page)

        if not media:
            context.close()
            raise RuntimeError(
                "No downloadable media URL was found. Try --headful and finish login/captcha first."
            )

        if not all_media:
            media = choose_default_media(context, media, work_url)

        downloaded: list[Path] = []
        base_name = safe_name(work_id)
        for index, item in enumerate(media, start=1):
            path = output_dir / f"{base_name}_{item.kind}_{index:02d}.{item.extension}"
            download_url(context, item.url, path, work_url)
            downloaded.append(path)
            print(f"downloaded {item.kind}: {path}", file=sys.stderr, flush=True)

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
                if version and version != "0.3.9":
                    result["version_warning"] = (
                        f"Chrome extension page script version is {version}, expected 0.3.9. "
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
) -> list[str]:
    sec_uid = parse_sec_uid(homepage_url)

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
        api_hits = 0
        last_has_more: Any = None
        last_cursor: Any = None
        last_api_url: str | None = None
        fetched_cursors: set[str] = set()

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
            urls = extract_work_urls_from_payload(payload, sec_uid)
            if urls:
                api_hits += 1
                last_api_url = response.url
                seen.update(urls)

        def fetch_next_cursor() -> int:
            nonlocal api_hits, last_has_more, last_cursor, last_api_url

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
                print(
                    f"direct_page_fetch status={result.get('status')} cursor={last_cursor}",
                    file=sys.stderr,
                    flush=True,
                )
                return 0

            payload = parse_json_text(result["text"])
            if payload is None:
                snippet = result["text"][:120].replace("\n", "\\n").replace("\r", "\\r")
                print(
                    (
                        f"direct_page_fetch non_json status={result.get('status')} "
                        f"cursor={last_cursor} body={snippet!r}"
                    ),
                    file=sys.stderr,
                    flush=True,
                )
                return 0

            has_more, max_cursor = payload_page_info(payload)
            if has_more is not None:
                last_has_more = has_more
            if max_cursor is not None:
                last_cursor = max_cursor

            urls = extract_work_urls_from_payload(payload, sec_uid)
            before = len(seen)
            seen.update(urls)
            if urls:
                api_hits += 1
                last_api_url = next_url
            added = len(seen) - before
            print(
                (
                    f"direct_page_fetch status={result.get('status')} extracted={len(urls)} "
                    f"added={added} has_more={last_has_more} cursor={last_cursor}"
                ),
                file=sys.stderr,
                flush=True,
            )
            return added

        page.on("response", handle_response)
        page.goto(homepage_url, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(3000)
        close_popups(page)

        unchanged_rounds = 0
        print(
            (
                f"scroll=000 found={len(seen)} added={len(seen)} "
                f"api_pages={api_hits} has_more={last_has_more} cursor={last_cursor} "
                f"api={display_api_path(last_api_url)}"
            ),
            file=sys.stderr,
            flush=True,
        )

        for index in range(1, max_scrolls + 1):
            before = len(seen)
            trigger_next_page(page, scroll_pixels)
            page.wait_for_timeout(int(wait_seconds * 1000))
            close_popups(page)

            added = len(seen) - before
            if added == 0 and truthy_has_more(last_has_more):
                added = fetch_next_cursor()

            print(
                (
                    f"scroll={index:03d} found={len(seen)} added={added} "
                    f"api_pages={api_hits} has_more={last_has_more} cursor={last_cursor} "
                    f"api={display_api_path(last_api_url)}"
                ),
                file=sys.stderr,
                flush=True,
            )

            if target_count is not None and len(seen) >= target_count:
                break

            if added == 0:
                unchanged_rounds += 1
            else:
                unchanged_rounds = 0

            if unchanged_rounds >= idle_rounds:
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
        default=Path("downloads"),
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
        default=Path(".douyin-browser"),
        help="Browser profile directory. Reused so manual login can persist.",
    )
    args = parser.parse_args()

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
