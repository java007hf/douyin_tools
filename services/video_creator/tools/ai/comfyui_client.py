"""Small stdlib-only ComfyUI HTTP client."""
from __future__ import annotations

import json
import mimetypes
import time
import uuid
from pathlib import Path
from urllib import error as urlerror, parse, request


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
        except urlerror.HTTPError as exc:
            try:
                detail=exc.read().decode("utf-8",errors="replace")
            except Exception:
                detail=""
            raise ComfyUIError(f"ComfyUI request failed: {path}: HTTP {exc.code}: {detail[:2000]}") from exc
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
                    if isinstance(choices, list) and choices and value not in choices: raise ComfyUIError(f"ComfyUI 缺少模型或资源: {value}")

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
        uploaded_name=str(result["name"])
        uploaded_subfolder=str(result.get("subfolder") or subfolder).strip("/")
        return f"{uploaded_subfolder}/{uploaded_name}" if uploaded_subfolder else uploaded_name

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

    def queue_state(self) -> dict:
        return json.loads(self._request("/queue")[2])

    def progress_state(self) -> dict:
        body = self._request("/progress")[2]
        return json.loads(body) if body else {}

    def cancel(self, prompt_id: str) -> bool:
        """Remove a queued prompt or interrupt it when it is the active prompt."""
        prompt_id = str(prompt_id or "")
        if not prompt_id:
            return False
        queue = self.queue_state()
        pending = [str(row[1]) for row in queue.get("queue_pending", []) if isinstance(row, list) and len(row) > 1]
        running = [str(row[1]) for row in queue.get("queue_running", []) if isinstance(row, list) and len(row) > 1]
        if prompt_id in pending:
            self._request("/queue", json.dumps({"delete": [prompt_id]}).encode(), "POST", {"Content-Type": "application/json"})
            return True
        if prompt_id in running:
            self._request("/interrupt", b"{}", "POST", {"Content-Type": "application/json"})
            return True
        return False

    def wait(self, prompt_id: str, progress=None, timeout: int = 14400) -> dict:
        started = time.monotonic()
        while time.monotonic() - started < timeout:
            result = self.history(prompt_id)
            item = result.get(prompt_id)
            if item and item.get("status", {}).get("status_str") == "error":
                raise ComfyUIError(str(item.get("status", {}).get("messages", "ComfyUI execution failed")))
            if item and item.get("outputs"):
                if progress: progress(100, "生成完成")
                return item
            if progress:
                try:
                    queue = self.queue_state()
                    pending = [str(row[1]) for row in queue.get("queue_pending", []) if isinstance(row, list) and len(row) > 1]
                    running = [str(row[1]) for row in queue.get("queue_running", []) if isinstance(row, list) and len(row) > 1]
                    if prompt_id in pending:
                        progress(5, f"ComfyUI 排队中，前面还有 {pending.index(prompt_id)} 个任务")
                    elif prompt_id in running:
                        state = self.progress_state()
                        current_id = str(state.get("prompt_id") or "")
                        value, maximum = float(state.get("value") or 0), float(state.get("max") or 0)
                        percent = 10 + round(value / maximum * 85) if current_id == prompt_id and maximum > 0 else 10
                        progress(min(95, percent), "ComfyUI 正在执行工作流")
                    else:
                        progress(8, "ComfyUI 正在准备工作流")
                except Exception:
                    progress(10, "ComfyUI 正在排队或执行工作流")
            time.sleep(2)
        raise ComfyUIError("ComfyUI task timed out")

    def view_url(self, output: dict) -> str:
        query = parse.urlencode({"filename": output["filename"], "subfolder": output.get("subfolder", ""), "type": output.get("type", "output")})
        return f"{self.base_url}/view?{query}"
