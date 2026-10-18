"""Private, atomically updated Doubao session configuration."""
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from .mock_doubao import MockDoubaoImageProvider, merge_request


class MockDoubaoConfigStore:
    lock = threading.Lock()

    def __init__(self, path: Path):
        self.path = path

    def _read(self):
        if not self.path.exists():
            return {}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except (OSError, ValueError):
            raise ValueError("豆包配置文件无法读取，请检查服务端文件") from None

    def public(self):
        with self.lock:
            value = self._read()
            headers = {k.lower(): v for k, v in value.get("headers", {}).items()}
            return {"configured": bool(value.get("body") or value.get("web_request") or value.get("web_video_request")),
                    "base_url": value.get("base_url", "https://api5-normal-lf.doubao.com"),
                    "endpoint": value.get("endpoint", "/im/sse/send/message"),
                    "timeout": value.get("timeout", 180),
                    "protocol": "web_chat_completion" if value.get("web_request") or value.get("web_video_request") else "legacy_android",
                    "token_configured": bool(headers.get("x-tt-token")),
                    "cookie_configured": bool(headers.get("cookie"))}

    def credentials(self):
        """Editable configuration for the dedicated Admin settings endpoint."""
        with self.lock:
            value = self._read()
            headers = {k.lower(): v for k, v in value.get("headers", {}).items()}
            return {"token": headers.get("x-tt-token", ""),
                    "cookie": headers.get("cookie", ""),
                    "headers": value.get("headers", {}), "model_routes": value.get("model_routes", {}), "web_request":value.get("web_request", {}),
                    "web_video_request":value.get("web_video_request", {}), "request_config": value}

    def save(self, values):
        if not isinstance(values, dict):
            raise ValueError("配置必须为 JSON 对象")
        with self.lock:
            config = self._read()
            template = values.get("request_config")
            if template:
                if not isinstance(template, dict):
                    raise ValueError("完整请求模板必须为 JSON 对象")
                for key in ("base_url", "endpoint", "headers", "query", "body", "timeout", "model_routes", "web_request", "web_video_request", "web_reference_request"):
                    if key in template:
                        config[key] = template[key]
            if "model_routes" in values:
                config["model_routes"] = values["model_routes"]
            if "web_request" in values:
                config["web_request"] = values["web_request"]
            if "web_video_request" in values: config["web_video_request"] = values["web_video_request"]
            for key in ("base_url", "endpoint", "timeout"):
                if values.get(key) not in (None, ""):
                    config[key] = values[key]
            headers = config.setdefault("headers", {})
            if not isinstance(headers, dict):
                raise ValueError("headers 必须为 JSON 对象")
            updates = values.get("headers", {})
            if not isinstance(updates, dict):
                raise ValueError("请求头必须为 JSON 对象")
            updates = {**updates}
            for field, header in (("token", "X-Tt-Token"), ("cookie", "Cookie")):
                if values.get(field) not in (None, "", "********"):
                    updates[header] = values[field]
            for key, value in updates.items():
                if value in ("", "********"):
                    continue
                if not isinstance(value, str) or "\r" in key or "\n" in key or "\r" in value or "\n" in value:
                    raise ValueError("请求头必须是无换行的字符串")
                for old in list(headers):
                    if old.lower() == key.lower():
                        del headers[old]
                headers[key] = value
            try:
                timeout = int(config.get("timeout", 180))
                if not 1 <= timeout <= 600 or not isinstance(config.get("query", {}), dict):
                    raise ValueError()
                config["timeout"] = timeout
                validator = MockDoubaoImageProvider.__new__(MockDoubaoImageProvider)
                validator.config = config
                if not config.get('web_request') and not config.get('web_video_request'):
                    validator.build_request("配置校验")
                if config.get('web_request'):
                    from .doubao_web import build_web_request
                    build_web_request(config, '配置校验')
                if config.get('web_video_request'):
                    from .doubao_web_video import build_video_request, captured_request, MODELS
                    build_video_request(config, '配置校验', model=next(iter(MODELS)))
                    captured_request(config, 'poll', '/im/chain/single')
                routes = config.get("model_routes", {})
                if not isinstance(routes, dict):
                    raise ValueError()
                for model, route in routes.items():
                    if not re.fullmatch(r"mock_doubao_[a-z0-9_]+", model) or model == "mock_doubao_seedream":
                        raise ValueError()
                    if not isinstance(route, dict) or not isinstance(route.get("request"), dict) or not route["request"]:
                        raise ValueError()
                    if set(route["request"]) - {"base_url", "endpoint", "headers", "query", "body"}:
                        raise ValueError()
                    if merge_request(config, route["request"]) == config:
                        raise ValueError()
                    if route.get("enabled") is not False:
                        _, route_headers, route_query, _ = validator.build_request("配置校验", model)
                        if not isinstance(route_query, dict) or not all(isinstance(v, str) and '\r' not in v and '\n' not in v for v in route_headers.values()):
                            raise ValueError()
            except Exception:
                raise ValueError("请求配置无效：请检查豆包地址、网页生图/视频模板，或旧协议 send_message_body/content 与 model_routes 参数") from None
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + "." + uuid.uuid4().hex + ".tmp")
            try:
                temporary.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
                for attempt in range(5):
                    try:
                        os.replace(temporary, self.path)
                        break
                    except PermissionError:
                        if attempt == 4:
                            raise
                        time.sleep(0.05 * (attempt + 1))
            finally:
                temporary.unlink(missing_ok=True)
        return self.public()
