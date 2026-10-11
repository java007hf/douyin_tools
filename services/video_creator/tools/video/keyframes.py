"""Extract stable first/last frame artifacts from a generated clip."""
from __future__ import annotations
from pathlib import Path
import cv2


def extract_boundary_frames(video: Path, output_dir: Path) -> dict[str, Path]:
    capture=cv2.VideoCapture(str(video))
    if not capture.isOpened(): raise RuntimeError(f"无法读取生成视频：{video.name}")
    try:
        total=int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        if total<=0: raise RuntimeError(f"生成视频没有可读取帧：{video.name}")
        output_dir.mkdir(parents=True,exist_ok=True)
        frames={}
        for name,index in (("first",0),("last",max(0,total-1))):
            capture.set(cv2.CAP_PROP_POS_FRAMES,index); ok,frame=capture.read()
            if not ok: raise RuntimeError(f"无法提取{name}关键帧：{video.name}")
            target=output_dir/f"{name}.jpg"
            if not cv2.imwrite(str(target),frame,[cv2.IMWRITE_JPEG_QUALITY,92]): raise RuntimeError(f"无法保存关键帧：{target.name}")
            frames[name]=target
        return frames
    finally: capture.release()
