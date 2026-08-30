"""Extract still frames from a video using OpenCV."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Callable

import cv2


ProgressCallback = Callable[[str, int, int], None]


def extract_frames(
    video_path: Path,
    output_dir: Path,
    *,
    interval_seconds: float | None = None,
    frame_count: int | None = None,
    image_format: str = "jpg",
    quality: int = 92,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    if (interval_seconds is None) == (frame_count is None):
        raise ValueError("请在抽帧间隔和抽帧张数中选择一个")
    if interval_seconds is not None and interval_seconds <= 0:
        raise ValueError("抽帧间隔必须大于 0")
    if frame_count is not None and not 1 <= frame_count <= 10_000:
        raise ValueError("抽帧张数必须在 1 到 10000 之间")
    if image_format not in {"jpg", "png", "webp"}:
        raise ValueError("不支持的图片格式")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise RuntimeError("无法打开视频文件，请检查格式或文件是否损坏")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
        total_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        duration = total_frames / fps if fps > 0 and total_frames > 0 else 0.0
        if total_frames <= 0:
            raise RuntimeError("无法读取视频帧信息")

        if frame_count is not None:
            indexes = sorted({int(round(index)) for index in _linspace(0, total_frames - 1, frame_count)})
        else:
            step = max(1, int(round((interval_seconds or 1) * fps)))
            indexes = list(range(0, total_frames, step))
        if not indexes:
            indexes = [0]

        output_dir.mkdir(parents=True, exist_ok=True)
        extension = image_format
        params = []
        if image_format == "jpg":
            params = [cv2.IMWRITE_JPEG_QUALITY, max(1, min(100, quality))]
        elif image_format == "webp":
            params = [cv2.IMWRITE_WEBP_QUALITY, max(1, min(100, quality))]

        files: list[dict[str, object]] = []
        for position, frame_index in enumerate(indexes, start=1):
            capture.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
            ok, frame = capture.read()
            if not ok:
                continue
            output = output_dir / f"frame_{position:05d}.{extension}"
            if not cv2.imwrite(str(output), frame, params):
                raise RuntimeError(f"写入图片失败: {output.name}")
            timestamp = frame_index / fps if fps > 0 else 0.0
            files.append({"name": output.name, "path": output, "timestamp": round(timestamp, 3)})
            if progress_callback:
                progress_callback(f"正在抽帧：{position}/{len(indexes)}", position, len(indexes))

        if not files:
            raise RuntimeError("没有成功读取到视频帧")
        return {
            "files": files,
            "fps": round(fps, 3),
            "duration": round(duration, 3),
            "total_frames": total_frames,
        }
    finally:
        capture.release()


def _linspace(start: int, end: int, count: int) -> list[float]:
    if count == 1:
        return [float(start)]
    step = (end - start) / (count - 1)
    return [start + index * step for index in range(count)]
