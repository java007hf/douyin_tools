"""Cloud video provider adapters.

The adapters intentionally keep credentials and provider-specific response
formats outside the workflow and asset-feed layers.
"""
from __future__ import annotations

import json
import mimetypes
import time
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib import parse, request


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


class JsonProvider(VideoProvider):
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
    """MiniMax video generation API, including text and first-frame image modes."""
    def submit(self, prompt: str, *, image: Path | None = None, video: Path | None = None, **params) -> str:
        if video: raise ProviderError("MiniMax public video API adapter currently supports text and reference image modes; video reference needs a provider-specific API")
        payload = {"prompt": prompt, "model": params.get("model", "MiniMax-Hailuo-2.3"), "duration": int(params.get("duration", 6)), "resolution": params.get("resolution", "768P")}
        if image: payload["first_frame_image"] = params.get("image_url") or self._require_url(image)
        result = self.call("/v1/video_generation", payload)
        task_id = result.get("task_id")
        if not task_id: raise ProviderError(f"MiniMax did not return task_id: {result}")
        return str(task_id)
    def _require_url(self, path: Path) -> str:
        raise ProviderError(f"MiniMax requires a public image URL for this request: {path.name}")
    def status(self, task_id: str) -> dict: return self.call("/v1/query/video_generation?" + parse.urlencode({"task_id": task_id}), method="GET")
    def download_url(self, task: dict) -> str | None:
        file_id = task.get("file_id")
        if not file_id: return task.get("video_url")
        result = self.call("/v1/files/retrieve?" + parse.urlencode({"file_id": file_id}), method="GET")
        return result.get("file", {}).get("download_url") or result.get("file", {}).get("download_url")
    def cancel(self, task_id: str) -> None: self.call("/v1/delete_video_generation", {"task_id": task_id})


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
        payload = {"model": params.get("model", self.model), "content": content, "resolution": params.get("resolution", "720p"), "ratio": params.get("ratio", "16:9")}
        result = self.call("/contents/generations/tasks", payload)
        task_id = result.get("id") or result.get("task_id")
        if not task_id: raise ProviderError(f"Seedance did not return task id: {result}")
        return str(task_id)
    def status(self, task_id: str) -> dict: return self.call("/contents/generations/tasks/" + parse.quote(task_id), method="GET")
    def download_url(self, task: dict) -> str | None: return task.get("content", {}).get("video_url") or task.get("video_url")
    def cancel(self, task_id: str) -> None: self.call("/contents/generations/tasks/" + parse.quote(task_id), method="DELETE")
