"""Runtime context shared by the AI-video workflow nodes."""
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class WorkflowContext:
    task_id: str
    task_dir: Path
    brief: str
    reference_image: Path | None = None
    reference_video: Path | None = None
    params: dict[str, Any] = field(default_factory=dict)
    artifacts: dict[str, Any] = field(default_factory=dict)
