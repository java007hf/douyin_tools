"""Tab registry shared by the unified frontend and deployment launcher."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class Tab:
    id: str
    title: str
    description: str
    service: str
    port: int
    enabled: bool = True


TABS = (
    Tab("douyin", "抖音工具", "拉取、下载和预览抖音素材", "douyin", 8101),
    Tab("video-creator", "视频创作", "参考视频复刻工作流", "video_creator", 8102),
)


def public_tabs(host: str) -> list[dict[str, object]]:
    return [
        {**asdict(tab), "url": f"http://{host}:{tab.port}/"}
        for tab in TABS
        if tab.enabled
    ]
