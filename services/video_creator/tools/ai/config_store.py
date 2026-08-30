"""Local provider configuration storage with redacted read access."""
from __future__ import annotations
import json
import threading
import uuid
from pathlib import Path


class ProviderConfigStore:
    def __init__(self, path: Path):
        self.path, self.lock = path, threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
    def _read(self):
        if not self.path.is_file(): return []
        try: return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError: return []
    def list_public(self):
        with self.lock:
            return [{k: ("********" if k in {"api_key", "token", "secret"} and v else v) for k, v in item.items() if k != "secret"} for item in self._read()]
    def get(self, provider_id: str):
        with self.lock:
            return next((x for x in self._read() if x.get("id") == provider_id), None)
    def save(self, values: dict):
        allowed = {"name", "provider", "base_url", "model", "api_key", "token", "secret", "enabled", "defaults"}
        with self.lock:
            items = self._read(); current = next((x for x in items if x.get("id") == values.get("id")), None)
            if current is None: current = {"id": uuid.uuid4().hex}; items.append(current)
            for key in allowed:
                if key in values and not (key in {"api_key", "token", "secret"} and values[key] == "********"): current[key] = values[key]
            current.setdefault("enabled", True)
            self.path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
            return {k: ("********" if k in {"api_key", "token", "secret"} and v else v) for k, v in current.items() if k != "secret"}
