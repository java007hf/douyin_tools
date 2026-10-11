"""Lossless-first video concatenation tool used by workflows."""
from __future__ import annotations
import subprocess
import shutil
from pathlib import Path


def _ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable:
        return executable
    fallback = Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe")
    if fallback.is_file():
        return str(fallback)
    raise FileNotFoundError("ffmpeg is required to merge video clips; install it and add it to PATH")


def merge_videos(inputs: list[Path], output: Path) -> Path:
    if not inputs:
        raise ValueError("没有可合成的视频片段")
    if len(inputs) == 1:
        output.write_bytes(inputs[0].read_bytes())
        return output
    manifest = output.with_suffix(".concat.txt")
    manifest.write_text("".join("file '" + str(path.resolve()).replace("'", "'\\''") + "'\n" for path in inputs), encoding="utf-8")
    ffmpeg = _ffmpeg()
    command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c", "copy", str(output)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode:
        command = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(manifest), "-c:v", "libx264", "-c:a", "aac", str(output)]
        result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode or not output.is_file():
        raise RuntimeError("视频合成失败：" + result.stderr[-1000:])
    return output
