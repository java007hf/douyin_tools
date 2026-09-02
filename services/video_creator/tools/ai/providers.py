"""Cloud video provider adapters.

The adapters intentionally keep credentials and provider-specific response
formats outside the workflow and asset-feed layers.
"""
from __future__ import annotations

import json
import mimetypes
import base64
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib import error as urlerror, parse, request


class ProviderError(RuntimeError):
    pass


class VideoProvider(ABC):
    @abstractmethod
    def submit(self, prompt: str, *, image: Path | None = None, video: Path | None = None, **params) -> str: ...
    @abstractmethod
    def status(self, task_id: str) -> dict: ...
    @abstractmethod
    def download_url(self, task: dict) -> str | None: ...
    def cancel(self, task_id: str) -> None: raise ProviderError("Provider does not support cancellation")


class JsonProvider:
    def __init__(self, base_url: str, api_key: str, timeout: int = 60):
        self.base_url, self.api_key, self.timeout = base_url.rstrip("/"), api_key, timeout
    def call(self, path: str, payload=None, *, method="POST", headers=None, retries=2) -> dict:
        body = json.dumps(payload).encode() if payload is not None else None
        merged = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", **(headers or {})}
        last_error = None
        for attempt in range(retries + 1):
            try:
                with request.urlopen(request.Request(self.base_url + path, data=body, method=method, headers=merged), timeout=self.timeout) as response:
                    result = json.loads(response.read()); break
            except urlerror.HTTPError as exc:
                try:
                    detail = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    detail = ""
                last_error = RuntimeError(f"HTTP {exc.code}: {detail[:1200]}")
                if attempt == retries: raise ProviderError(f"Cloud provider request failed: {path}: {last_error}") from exc
                time.sleep(2 ** attempt)
            except Exception as exc:
                last_error = exc
                if attempt == retries: raise ProviderError(f"Cloud provider request failed: {path}: {exc}") from exc
                time.sleep(2 ** attempt)
        if isinstance(result, dict) and result.get("base_resp", {}).get("status_code", 0) not in (0, None): raise ProviderError(str(result["base_resp"]))
        return result
    def wait(self, task_id: str, *, timeout: int = 1800) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            result = self.status(task_id)
            state = str(result.get("status", result.get("state", ""))).lower()
            if state in {"success", "succeeded", "completed", "done"}: return result
            if state in {"fail", "failed", "error"}: raise ProviderError(str(result))
            time.sleep(5)
        raise ProviderError("Cloud provider task timed out")


class MiniMaxVideoProvider(JsonProvider):
    """MiniMax H3 V2 multimodal video generation API."""
    def submit(self, prompt: str, *, image: Path | None = None, video: Path | None = None, **params) -> str:
        content = [{"type": "text", "text": prompt}]
        if image: content.append({"type": "image_url", "image_url": {"url": params.get("image_url") or self._require_url(image), "role": "reference_image"}})
        if video: content.append({"type": "video_url", "video_url": {"url": params.get("video_url") or self._require_url(video), "role": "reference_video"}})
        resolution = {"360p": "768P", "720p": "768P", "1080p": "2K"}.get(str(params.get("resolution", "768P")), params.get("resolution", "768P"))
        payload = {"model": params.get("model") or "MiniMax-H3", "content": content, "resolution": resolution, "duration": int(params.get("duration", 6)), "ratio": params.get("aspect", "16:9")}
        result = self.call("/v2/video_generation", payload)
        task_id = result.get("task_id")
        if not task_id: raise ProviderError(f"MiniMax did not return task_id: {result}")
        return str(task_id)
    def _require_url(self, path: Path) -> str:
        raise ProviderError(f"MiniMax requires a public image URL for this request: {path.name}")
    def status(self, task_id: str) -> dict: return self.call("/v1/query/video_generation?" + parse.urlencode({"task_id": task_id}), method="GET")
    def download_url(self, task: dict) -> str | None:
        task = task.get("task", task)
        if task.get("content", {}).get("url"): return task["content"]["url"]
        file_id = task.get("file_id")
        if not file_id: return task.get("video_url")
        result = self.call("/v1/files/retrieve?" + parse.urlencode({"file_id": file_id}), method="GET")
        return result.get("file", {}).get("download_url") or result.get("file", {}).get("download_url")
    def cancel(self, task_id: str) -> None: self.call("/v1/delete_video_generation", {"task_id": task_id})


class MiniMaxImageProvider(JsonProvider):
    """MiniMax image generation API for text-to-image and subject reference."""
    def generate(self, prompt: str, *, image_url: str | None = None, **params) -> list[str]:
        payload = {
            "model": params.get("model") or "image-01",
            "prompt": prompt,
            "aspect_ratio": params.get("aspect", "1:1"),
            "response_format": "url",
            "n": max(1, min(9, int(params.get("count", 1) or 1))),
        }
        if image_url:
            payload["subject_reference"] = [{"type": "character", "image_file": image_url}]
        result = self.call("/v1/image_generation", payload)
        urls = result.get("data", {}).get("image_urls", [])
        if not urls: raise ProviderError(f"MiniMax did not return image URLs: {result}")
        return [str(url) for url in urls]


class SeedreamImageProvider(JsonProvider):
    """Volcengine Ark Seedream image generation API."""
    def generate(self, prompt: str, *, image: Path | None = None, **params) -> list[str]:
        size = str(params.get("resolution", "2K"))
        if size not in {"1K", "2K", "4K"}:
            size = "2K"
        payload = {
            "model": params.get("model") or "doubao-seedream-5-0-pro-260628",
            "prompt": prompt,
            "size": size,
            "stream": False,
            "response_format": "url",
            "watermark": False,
        }
        model = str(payload["model"]).lower()
        if any(name in model for name in ("seedream-5-0-lite", "seedream-4-5", "seedream-4-0")):
            payload["sequential_image_generation"] = "disabled"
        if image:
            encoded = base64.b64encode(image.read_bytes()).decode("ascii")
            payload["image"] = [f"data:{mimetypes.guess_type(image.name)[0] or 'image/png'};base64,{encoded}"]
        result = self.call("/images/generations", payload)
        urls = [item.get("url") for item in result.get("data", []) if item.get("url")]
        if not urls: raise ProviderError(f"Seedream did not return image URLs: {result}")
        return [str(url) for url in urls]


class SeedanceProvider(JsonProvider):
    """Volcengine Ark adapter using configurable endpoint/model IDs.

    Ark accounts expose different regional endpoints and model endpoint IDs, so
    those values remain configuration rather than being hard-coded here.
    """
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 60):
        super().__init__(base_url, api_key, timeout); self.model = model
    def submit(self, prompt: str, *, image: Path | None = None, video: Path | None = None, **params) -> str:
        content = [{"type": "text", "text": prompt}]
        if params.get("image_url"): content.append({"type": "image_url", "image_url": {"url": params["image_url"]}})
        if params.get("video_url"): content.append({"type": "video_url", "video_url": {"url": params["video_url"]}})
        model = str(params.get("model", self.model))
        duration = int(params.get("duration", 5))
        model_name = model.lower()
        if "2-0" in model_name:
            if duration < 4 or duration > 15: raise ProviderError("Seedance 2.0 视频时长必须是 4-15 秒")
        elif "1-5" in model_name:
            if duration < 4 or duration > 12: raise ProviderError("Seedance 1.5 视频时长必须是 4-12 秒")
        elif duration < 2 or duration > 12:
            raise ProviderError("Seedance 1.0 视频时长必须是 2-12 秒")
        payload = {"model": model, "content": content, "resolution": params.get("resolution", "720p"), "ratio": params.get("ratio", "16:9"), "duration": duration}
        result = self.call("/contents/generations/tasks", payload)
        task_id = result.get("id") or result.get("task_id")
        if not task_id: raise ProviderError(f"Seedance did not return task id: {result}")
        return str(task_id)
    def status(self, task_id: str) -> dict: return self.call("/contents/generations/tasks/" + parse.quote(task_id), method="GET")
    def download_url(self, task: dict) -> str | None: return task.get("content", {}).get("video_url") or task.get("video_url")
    def cancel(self, task_id: str) -> None: self.call("/contents/generations/tasks/" + parse.quote(task_id), method="DELETE")
