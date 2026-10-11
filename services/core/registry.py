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
    admin_only: bool = False


TABS = (
    Tab("douyin", "抖音工具", "拉取、下载和预览抖音素材", "douyin", 8101),
    Tab("video-creator", "AI创作工具", "参考视频复刻工作流", "video_creator", 8102),
    Tab("admin", "后台控制", "模型与云端 Provider 配置", "admin", 8103, admin_only=True),
)


def public_tabs(host: str, include_admin: bool = False) -> list[dict[str, object]]:
    return [
        # Keep Tab documents on the gateway origin. The gateway proxies their
        # APIs, which avoids requiring browsers to reach separate service ports.
        {**asdict(tab), "url": f"/tabs/{tab.id}/"}
        for tab in TABS
        if tab.enabled and (include_admin or not tab.admin_only)
    ]
