"""Small stdlib-only ComfyUI HTTP client."""
from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib import parse, request


class ComfyUIError(RuntimeError):
    pass


class ComfyUIClient:
    def __init__(self, base_url: str = "http://127.0.0.1:8188"):
        self.base_url = base_url.rstrip("/")

    def _request(self, path: str, data=None, method=None, headers=None):
        req = request.Request(self.base_url + path, data=data, method=method, headers=headers or {})
        try:
            with request.urlopen(req, timeout=30) as response:
                return response.status, response.headers, response.read()
        except Exception as exc:
            raise ComfyUIError(f"ComfyUI request failed: {path}: {exc}") from exc

    def object_info(self) -> dict:
        return json.loads(self._request("/object_info")[2])

    def validate_graph(self, graph: dict) -> None:
        info = self.object_info()
        missing = [node.get("class_type") for node in graph.values() if isinstance(node, dict) and node.get("class_type") not in info]
        if missing:
            raise ComfyUIError("ComfyUI 缺少节点: " + ", ".join(sorted(set(missing))))
        for node in graph.values():
            if not isinstance(node, dict): continue
            schema = info.get(node.get("class_type"), {}).get("input", {})
            for key, value in node.get("inputs", {}).items():
                if isinstance(value, str) and key.endswith("_name"):
                    choices = schema.get("required", {}).get(key, [[]])[0]
                    if choices and value not in choices: raise ComfyUIError(f"ComfyUI 缺少模型或资源: {value}")

    def upload(self, path: Path, subfolder: str = "douyin") -> str:
        boundary = uuid.uuid4().hex
        name = path.name
        content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
        parts = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
            path.read_bytes(),
            f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"subfolder\"\r\n\r\n{subfolder}\r\n--{boundary}--\r\n".encode(),
        ]
        _, _, body = self._request("/upload/image", b"".join(parts), "POST", {"Content-Type": f"multipart/form-data; boundary={boundary}"})
        result = json.loads(body)
        if result.get("name") is None:
            raise ComfyUIError(f"ComfyUI upload failed: {result}")
        return str(result["name"])

    def queue(self, prompt: dict, client_id: str | None = None) -> str:
        payload = json.dumps({"prompt": prompt, "client_id": client_id or uuid.uuid4().hex}).encode()
        _, _, body = self._request("/prompt", payload, "POST", {"Content-Type": "application/json"})
        result = json.loads(body)
        if result.get("node_errors"):
            raise ComfyUIError(json.dumps(result["node_errors"], ensure_ascii=False))
        if not result.get("prompt_id"):
            raise ComfyUIError(f"ComfyUI rejected prompt: {result}")
        return str(result["prompt_id"])

    def history(self, prompt_id: str) -> dict:
        return json.loads(self._request(f"/history/{parse.quote(prompt_id)}")[2])

    def wait(self, prompt_id: str, progress=None, timeout: int = 3600) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            result = self.history(prompt_id)
            item = result.get(prompt_id)
            if item and item.get("status", {}).get("status_str") == "error":
                raise ComfyUIError(str(item.get("status", {}).get("messages", "ComfyUI execution failed")))
            if item and item.get("outputs"):
                if progress: progress(100, "生成完成")
                return item
            if progress: progress(10, "ComfyUI 正在排队或执行工作流")
            time.sleep(2)
        raise ComfyUIError("ComfyUI task timed out")

    def view_url(self, output: dict) -> str:
        query = parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": output.get("type", "output")})
        return f"{self.base_url}/view?{query}"
