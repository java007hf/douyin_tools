"""Doubao captured-request image adapter; session material stays in store/."""
from __future__ import annotations

import copy
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import requests

from .providers import ProviderError
from .doubao_legacy_request import build_legacy_request


MODEL = "mock_doubao_seedream"
KNOWN_IMAGE_MODELS = {
    "mock_doubao_seedream_5_0_flash": "Seedream 5.0 Flash",
    "mock_doubao_seedream_5_0_pro": "Seedream 5.0 Pro",
    "mock_doubao_seedream_5_0_lite": "Seedream 5.0 Lite",
    "mock_doubao_seedream_4_5": "Seedream 4.5",
    "mock_doubao_seedream_4_0": "Seedream 4.0",
}


def response_error(value: dict, config: dict) -> str | None:
    error = value.get("error")
    code = value.get("status_code", value.get("code"))
    if not error and code in (None, 0, "0"):
        return None
    nested = error if isinstance(error, dict) else {}
    code = nested.get("code", code)
    label = str(code) if isinstance(code, (str, int)) and re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", str(code)) else "unknown"
    detail = str(nested.get("message") or value.get("status_desc") or value.get("message") or value.get("msg") or "")
    # A provider can echo request material. Never copy session values into task errors.
    for group in (config.get("headers", {}), config.get("query", {})):
        for secret in group.values():
            if isinstance(secret, str) and len(secret) >= 8:
                detail = detail.replace(secret, "[已隐藏]")
    detail = re.sub(r"https?://[^\s\"<>]+", "[URL]", detail)
    detail = re.sub(r"(?i)(bearer\s+)[^\s,;]+", r"\1[已隐藏]", detail)
    detail = re.sub(r"(?i)((?:token|cookie|authorization|api[_-]?key|signature|sessionid)\s*[=:]\s*)[^\s,;]+", r"\1[已隐藏]", detail)
    hint = "登录已失效，请在后台控制更新有效请求模板" if str(code) in {"710012001", "401", "403"} else "请检查请求模板、签名与账号状态"
    if str(code) == "710022002":
        hint = "豆包限制当前服务访问频率，已停止提交；请稍后手动重试"
    return f"豆包返回业务错误（code={label}）" + (f"：{detail[:500]}" if detail else "") + f"；{hint}"


def merge_request(base: dict, overrides: dict) -> dict:
    result = copy.deepcopy(base)
    for key, value in overrides.items():
        result[key] = merge_request(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


def image_models(config_path: Path) -> list[str]:
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        if config.get('web_request'):
            from .doubao_web import MODELS
            return [MODEL] + list(MODELS)
        return [MODEL] + [key for key, route in config.get("model_routes", {}).items()
                          if key != MODEL and route.get("enabled", True)]
    except (OSError, ValueError, AttributeError, TypeError):
        return [MODEL]


def image_model_status(config_path: Path) -> dict:
    configured = image_models(config_path)
    return {key: {"label": label, "configured": key in configured}
            for key, label in KNOWN_IMAGE_MODELS.items()}


def extract_images(value) -> list[str]:
    """Read generated creations, including JSON encoded inside SSE messages."""
    urls = []

    def visit(node):
        if isinstance(node, str):
            try:
                visit(json.loads(node))
            except (ValueError, RecursionError):
                pass
        elif isinstance(node, list):
            for child in node:
                visit(child)
        elif isinstance(node, dict):
            for creation in node.get("creations", []) or []:
                if not isinstance(creation, dict) or creation.get("type") != 1:
                    continue
                image = creation.get("image") or {}
                if image.get('status') not in (None,2):
                    continue
                for key in ("image_ori_raw", "image_ori", "image_preview", "image_thumb"):
                    url = (image.get(key) or {}).get("url")
                    if isinstance(url, str) and urlsplit(url).scheme == "https":
                        if url not in urls:
                            urls.append(url)
                        break
            for child in node.values():
                visit(child)

    visit(value)
    return urls


class MockDoubaoImageProvider:
    media_kind = 'image'
    default_model = MODEL

    def __init__(self, config_path: Path):
        try:
            self.config = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ProviderError("请配置 store/video_creator/mock_doubao.json 中的豆包请求模板和登录凭据") from exc
        self.timeout = max(1, min(600, int(self.config.get("timeout", 180))))

    def resolve_config(self, model):
        config = self.config
        if model != MODEL:
            route = config.get("model_routes", {}).get(model)
            if not isinstance(route, dict) or route.get("enabled") is False:
                raise ProviderError("未配置或已停用该豆包模型路由")
            config = merge_request(config, route["request"])
        return config

    def build_request(self, prompt: str, model: str = MODEL, **params):
        config = self.resolve_config(model)
        base = str(config.get("base_url", ""))
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not (parsed.hostname == "doubao.com" or (parsed.hostname or "").endswith(".doubao.com")):
            raise ProviderError("豆包请求地址必须是 HTTPS doubao.com 域名")
        endpoint = str(config.get("endpoint", "/im/sse/send/message"))
        if not endpoint.startswith("/") or endpoint.startswith("//") or "?" in endpoint or "#" in endpoint:
            raise ProviderError("豆包 endpoint 必须为不含查询参数的绝对路径")
        body = copy.deepcopy(config.get("body", {}))
        try:
            message = body["uplink_body"]["send_message_body"]
            content = json.loads(message["content"])
            content["text"] = prompt
            message["content"] = json.dumps(content, ensure_ascii=False)
        except (KeyError, TypeError, ValueError) as exc:
            raise ProviderError("豆包 body 缺少有效的 send_message_body/content 模板") from exc
        return build_legacy_request(config, prompt)

    def extract_outputs(self, value):
        return extract_images(value)

    def generate(self, prompt: str, *, image: Path | None = None, **params) -> list[str]:
        if not prompt.strip():
            raise ProviderError("生图提示词不能为空")
        if image:
            raise ProviderError("mock_doubao_seedream 暂不支持本地参考图上传，请使用文生图")
        if int(params.get("count") or 1) != 1:
            raise ProviderError("豆包网页请求的出图数量由网页端控制，请将数量设为 1")
        url, headers, query, body = self.build_request(prompt, params.get("model") or self.default_model, **{k:v for k,v in params.items() if k != 'model'})
        diagnostics = params.get("diagnostics")
        if diagnostics is None:
            diagnostics = {}
        diagnostics.update(parsed_events=0, malformed_events=0, event_keys=[])
        started = time.monotonic()
        urls, event, total = [], [], 0

        def consume():
            if not event:
                return
            text = "\n".join(event)
            event.clear()
            if text == "[DONE]":
                return
            try:
                value = json.loads(text)
            except ValueError:
                # Some legacy gateways emit one JSON data line per chunk without
                # the SSE blank separator. Parse those as independent events.
                if "\n" in text:
                    for part in text.splitlines():
                        event.append(part)
                        consume()
                else:
                    diagnostics["malformed_events"] += 1
                return
            diagnostics["parsed_events"] += 1
            if isinstance(value, dict):
                diagnostics["event_keys"] = list(dict.fromkeys(diagnostics["event_keys"] + list(value)))[:40]
                failure = response_error(value, self.config)
                if failure:
                    raise ProviderError(failure)
            def collect_ids(node):
                if isinstance(node, dict):
                    for key in ('message_id', 'conversation_id'):
                        if isinstance(node.get(key), (str, int)) and node[key]:
                            diagnostics[key] = str(node[key])
                    for child in node.values():
                        collect_ids(child)
                elif isinstance(node, list):
                    for child in node:
                        collect_ids(child)
            collect_ids(value)
            for item in self.extract_outputs(value):
                if item not in urls:
                    urls.append(item)

        try:
            # A generation POST must never be retried automatically: it can create duplicates.
            with requests.post(url, headers=headers, params=query, json=body, stream=True,
                               timeout=(15, self.timeout), allow_redirects=False) as response:
                diagnostics["http_status"] = response.status_code
                if response.status_code != 200:
                    raise ProviderError(f"豆包请求失败 HTTP {response.status_code}，请检查登录凭据是否过期")
                response.encoding = "utf-8"
                for line in response.iter_lines(decode_unicode=True):
                    total += len(line)
                    if time.monotonic() - started > self.timeout or total > 16 * 1024 * 1024:
                        raise ProviderError("豆包响应超时或超过大小限制；请求可能已提交，请勿立即重复生成")
                    if not line:
                        consume()
                    elif line.startswith("data:"):
                        event.append(line[5:].lstrip())
                    elif line.startswith(("{", "[")):
                        event.append(line)
                consume()
        except requests.RequestException:
            raise ProviderError("豆包网络请求失败；请求可能已提交，请检查账号后重试") from None
        if not urls:
            label = '视频' if self.media_kind == 'video' else '图片'
            raise ProviderError(f"豆包响应结束但未返回生成{label}（解析事件 {diagnostics['parsed_events']}，异常事件 {diagnostics['malformed_events']}）；请检查登录状态、额度或请求模板。请求可能已提交，请勿自动重发")
        return urls


def main():
    """Single-submission diagnostic entry point; never print session material."""
    import argparse
    from services.core.storage import service_store

    parser = argparse.ArgumentParser(description="豆包网页请求生图（单次提交）")
    parser.add_argument("prompt")
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    root = service_store("video_creator")
    try:
        provider = MockDoubaoImageProvider(root / 'mock_doubao.json')
        urls = provider.generate(args.prompt, model=args.model)
        target = root / "generation_jobs" / ("mock_" + uuid.uuid4().hex)
        target.mkdir(parents=True)
        for index, url in enumerate(urls, 1):
            with requests.get(url, timeout=(15, 120)) as response:
                response.raise_for_status()
                (target / f"image_{index}.png").write_bytes(response.content)
        print(json.dumps({"status": "done", "directory": str(target), "count": len(urls)}, ensure_ascii=False))
    except (ProviderError, requests.RequestException, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc) if isinstance(exc, RuntimeError) else "媒体下载失败"}, ensure_ascii=False))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
