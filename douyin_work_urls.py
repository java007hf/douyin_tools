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
import json
import re
import sys
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
