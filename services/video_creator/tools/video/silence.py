"""Deterministically replace a clip's generated audio with silence."""
from __future__ import annotations

import subprocess
import json
import re
import shutil
from pathlib import Path

from .merge import _ffmpeg


def replace_audio_with_silence(video: Path) -> Path:
    """Keep the video stream and replace all model-generated audio with silence."""
    temporary = video.with_name(video.stem + ".silent" + video.suffix)
    command = [
        _ffmpeg(), "-y", "-i", str(video),
        # H3 currently emits stereo AAC at 32 kHz. Matching that format keeps
        # concat timestamps correct when dialogue and silent shots are mixed.
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=32000",
        "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac",
        "-shortest", "-movflags", "+faststart", str(temporary),
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode or not temporary.is_file() or temporary.stat().st_size < 1024:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("无对白镜头静音处理失败：" + result.stderr[-1000:])
    temporary.replace(video)
    return video


def replace_audio_with_effects(video: Path, description: str = "") -> Path:
    """Replace unreliable model speech with deterministic ambience and Foley."""
    probe = shutil.which("ffprobe") or "ffprobe"
    result = subprocess.run(
        [probe, "-v", "error", "-show_entries", "format=duration", "-of", "json", str(video)],
        capture_output=True, text=True, timeout=30,
    )
    duration = max(0.1, float(json.loads(result.stdout)["format"]["duration"]))
    text = str(description or "")
    # A quiet room tone is always present. Extra layers are synthetic Foley,
    # never speech, so no-dialogue shots cannot invent words or vocalizations.
    sources = [f"anoisesrc=color=pink:amplitude=0.012:sample_rate=32000:d={duration}"]
    filters = ["[1:a]highpass=f=90,lowpass=f=1800[amb]"]
    labels = ["[amb]"]
    if any(word in text for word in ("蛛丝", "变成", "变形", "展开", "魔法", "能量", "金光", "火眼金睛")):
        sources += [f"sine=frequency=520:sample_rate=32000:duration={min(duration, 1.4)}", f"anoisesrc=color=white:amplitude=0.05:sample_rate=32000:d={min(duration, 1.8)}"]
        filters += ["[2:a]volume='0.10*(1-t/1.4)':eval=frame,adelay=350|350[shimmer]", "[3:a]highpass=f=1800,lowpass=f=7000,volume=0.18,afade=t=in:st=0:d=0.15,afade=t=out:st=1.2:d=0.6,adelay=500|500[web]"]
        labels += ["[shimmer]", "[web]"]
    if any(word in text for word in ("扫帚", "滑落", "碰撞", "脚步", "关节")):
        sources += ["sine=frequency=105:sample_rate=32000:duration=0.22"]
        index = len(sources)
        delay = max(0, int((duration * 0.55) * 1000))
        filters += [f"[{index}:a]volume=0.32,afade=t=out:st=0.03:d=0.19,adelay={delay}|{delay}[thud]"]
        labels += ["[thud]"]
    if any(word in text for word in ("衣料", "树叶", "风声", "沙沙")):
        sources += [f"anoisesrc=color=pink:amplitude=0.045:sample_rate=32000:d={duration}"]
        index = len(sources)
        filters += [f"[{index}:a]highpass=f=900,lowpass=f=4200,volume=0.22[rustle]"]
        labels += ["[rustle]"]
    # Non-dialogue Foley must be comfortably audible beside native dialogue.
    # Raise the designed mix before limiting instead of merely checking that an
    # almost-silent audio stream exists.
    filter_complex = ";".join(filters + ["".join(labels) + f"amix=inputs={len(labels)}:normalize=0,volume=6.4,alimiter=limit=0.8[outa]"])
    temporary = video.with_name(video.stem + ".effects" + video.suffix)
    command = [_ffmpeg(), "-y", "-i", str(video)]
    for source in sources:
        command += ["-f", "lavfi", "-i", source]
    command += ["-filter_complex", filter_complex, "-map", "0:v:0", "-map", "[outa]", "-c:v", "copy", "-c:a", "aac", "-ar", "32000", "-shortest", "-movflags", "+faststart", str(temporary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if result.returncode or not temporary.is_file() or temporary.stat().st_size < 1024:
        temporary.unlink(missing_ok=True)
        raise RuntimeError("无对白镜头音效处理失败：" + result.stderr[-1000:])
    temporary.replace(video)
    return video


def audio_mean_volume_db(video: Path) -> float:
    """Return ffmpeg's measured mean volume; missing/invalid audio is -inf."""
    result = subprocess.run(
        [_ffmpeg(), "-hide_banner", "-i", str(video), "-af", "volumedetect", "-f", "null", "NUL"],
        capture_output=True, text=True, timeout=300,
    )
    match = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", result.stderr)
    return float(match.group(1)) if match else float("-inf")


def ensure_non_dialogue_audio(video: Path, description: str = "", minimum_mean_db: float = -36.0) -> Path:
    """Create deterministic Foley and reject effectively inaudible results."""
    replace_audio_with_effects(video, description)
    measured = audio_mean_volume_db(video)
    if measured < minimum_mean_db:
        raise RuntimeError(f"无对白镜头音效不可听：平均响度 {measured:.1f} dB，要求不低于 {minimum_mean_db:.1f} dB")
    return video
