"""Serializable workflow task and node state models."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class WorkflowNode:
    id: str
    title: str
    status: str = "pending"
    message: str = ""
    attempts: int = 0
    started_at: str = ""
    ended_at: str = ""
    duration_ms: int = 0
    output: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
