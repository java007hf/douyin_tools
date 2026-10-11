"""Small observable, retry-aware sequential workflow engine."""
from __future__ import annotations
from collections.abc import Callable
from datetime import datetime, timezone
from time import monotonic
from .context import WorkflowContext
from .models import WorkflowNode


class WorkflowEngine:
    def __init__(self, nodes: list[tuple[WorkflowNode, Callable[[WorkflowContext], dict]]], on_change: Callable[[list[dict]], None]):
        self.nodes, self.on_change = nodes, on_change

    def run(self, context: WorkflowContext) -> None:
        self._emit()
        for node, action in self.nodes:
            node.status, node.attempts = "running", node.attempts + 1
            node.started_at=datetime.now(timezone.utc).isoformat();started=monotonic()
            self._emit()
            try:
                node.output = action(context) or {}
                node.status, node.message = "success", node.output.get("message", "完成")
            except Exception as exc:
                node.status, node.message = "failed", str(exc)
                node.ended_at=datetime.now(timezone.utc).isoformat();node.duration_ms=round((monotonic()-started)*1000)
                self._emit()
                raise
            node.ended_at=datetime.now(timezone.utc).isoformat();node.duration_ms=round((monotonic()-started)*1000)
            self._emit()

    def _emit(self) -> None:
        self.on_change([node.as_dict() for node, _ in self.nodes])
