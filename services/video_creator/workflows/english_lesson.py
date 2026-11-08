"""Produce an English micro-lesson with a reusable portrait and voice."""
from __future__ import annotations

import json
from math import ceil
import os
from pathlib import Path
import shutil
import subprocess
import sys
from threading import Lock
from time import monotonic
import uuid

from PIL import Image

from services.core.storage import store_root
from services.video_creator.tools.ai.doubao_web_video import DoubaoWebVideoProvider, validate_video
from services.video_creator.tools.ai.llm import create_agent_llm
from services.video_creator.tools.ai.providers import save_remote_asset
from services.video_creator.workflow.engine import WorkflowEngine
from services.video_creator.workflow.models import WorkflowNode


SCRIPT_PROMPT = (
    "你为中文母语学习者写一条极短的英语口播。只输出 JSON，字段 title 和 speech。"
    "speech 是能在约 6 到 10 秒内自然说完的单人口播。最多 28 个汉字、8 个英文单词。"
    "用一个具体场景引出一个准确用法，再给一个简短自然的英文例句。宽泛主题只选一个用法。"
    "用自然中文，保留英文拼写，不要音标、舞台说明、Markdown 或额外字段。"
)
DOUBAO_MODEL = "mock_doubao_seedance_2_0_mini"
VISUAL_PROMPT = (
    "写实竖屏英语口播。参考首帧的人脸、自然肩线、衣服和手持麦克风，画面下缘到腰带以下。"
    "固定平视机位，柔和窗光，保留自然皮肤纹理，眨眼和表情克制。只说以下台词一遍，"
    "准确读出中英文字，正常张嘴，无多余动作。无字幕、无背景音乐。"
)
PROFILE_FILES = ("portrait.png", "reference.wav", "reference.txt")
LESSON_SLOT = Lock()


def read_profile(store: Path) -> Path | None:
    root = store / "english_lesson_profiles"
    pointer = root / "current"
    if not pointer.is_file():
        return None
    profile = root / uuid.UUID(pointer.read_text(encoding="ascii")).hex
    return profile if all((profile / name).is_file() for name in PROFILE_FILES) else None


def save_profile(store: Path, portrait, audio, transcript: str) -> Path:
    transcript = transcript.strip()
    if not transcript or len(transcript) > 2000:
        raise ValueError("请填写声音样本对应的逐字稿（最多 2000 字）")
    root = store / "english_lesson_profiles"
    profile = root / uuid.uuid4().hex
    profile.mkdir(parents=True)
    pointer = root / (profile.name + ".tmp")
    try:
        with Image.open(portrait) as image:
            if image.width < 128 or image.height < 128:
                raise ValueError("参考人像至少需要 128 × 128 像素")
            image.convert("RGB").save(profile / "portrait.png")
        source = profile / "upload"
        source.write_bytes(audio.read(20 * 1024 * 1024 + 1))
        if source.stat().st_size > 20 * 1024 * 1024:
            raise ValueError("声音样本最多 20 MB")
        wav = profile / "reference.wav"
        ffmpeg("-i", str(source), "-t", "31", "-vn", "-ac", "1", "-ar", "24000", str(wav))
        duration = audio_duration(wav)
        if not 3 <= duration <= 30:
            raise ValueError("声音样本需为 3 至 30 秒")
        source.unlink()
        (profile / "reference.txt").write_text(transcript, encoding="utf-8")
        pointer.write_text(profile.name, encoding="ascii")
        pointer.replace(root / "current")
        return profile
    except Exception:
        pointer.unlink(missing_ok=True)
        shutil.rmtree(profile)
        raise


def ffmpeg(*args: str) -> None:
    result = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *args], capture_output=True, text=True, timeout=120,
    )
    if result.returncode:
        raise RuntimeError(f"FFmpeg 处理失败：{result.stderr.strip()[-500:]}")


def audio_duration(path: Path) -> float:
    import wave
    with wave.open(str(path), "rb") as wav:
        return wav.getnframes() / wav.getframerate()


def tts_python() -> str:
    repo = Path(__file__).resolve().parents[3]
    venv = repo / "cache" / "english-lesson-venv"
    bundled = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    return os.environ.get("DOUYIN_LESSON_TTS_PYTHON") or str(bundled if bundled.is_file() else sys.executable)


class EnglishLessonWorkflow:
    def __init__(self, context, profile, agent_config, doubao_config, update, cancelled):
        self.context = context
        self.profile = profile
        self.agent_config = agent_config
        self.doubao_config = doubao_config
        self.update = update
        self.cancelled = cancelled

    def run(self):
        actions = [
            ("script", "生成英语讲稿", self.plan),
            ("voice", "复刻声音", self.speak),
            ("video", "豆包生成口播画面", self.render),
            ("export", "合成并校验视频", self.export),
        ]
        self.update(message="等待英语口播队列")
        with LESSON_SLOT:
            self.check_cancelled()
            WorkflowEngine([(WorkflowNode(key, title), action) for key, title, action in actions], self.on_change).run(self.context)
        return self.context.artifacts["output"]

    def on_change(self, nodes):
        root = self.context.task_dir
        (root / "trace.json").write_text(json.dumps({
            "nodes": nodes, "artifacts": self.context.artifacts,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        active = next((node for node in nodes if node["status"] == "running"), None)
        if active:
            self.update(message=active["title"], nodes=nodes, progress=5 + 20 * nodes.index(active))
        else:
            self.update(nodes=nodes)

    def check_cancelled(self):
        if self.cancelled():
            raise RuntimeError("任务已取消")

    def plan(self, ctx):
        self.check_cancelled()
        config = dict(self.agent_config, context_window=4096, thinking_enabled=False, output_token_limit=1024)
        result = create_agent_llm(config).complete_json(SCRIPT_PROMPT, ctx.brief, keep_alive=0)
        title, speech = (str(result.get(key) or "").strip() for key in ("title", "speech"))
        if not title or not speech or len(title) > 100 or len(speech) > 160:
            raise ValueError("讲稿为空或过长，请缩小本期讲解范围")
        (ctx.task_dir / "script.txt").write_text(speech, encoding="utf-8")
        ctx.artifacts.update(title=title, script="script.txt", speech=speech)
        self.update(title=title, speech=speech)
        return {"speech": speech}

    def speak(self, ctx):
        self.check_cancelled()
        root = ctx.task_dir
        wav = root / "speech.wav"
        environment = dict(os.environ, HF_HOME=str(store_root() / "models" / "qwen-tts"),
                           HF_HUB_DISABLE_SYMLINKS_WARNING="1", USE_TF="0")
        command = [tts_python(), "-B", "-m", "services.video_creator.tools.ai.lesson_voice",
                   str(self.profile / "reference.wav"), str(self.profile / "reference.txt"),
                   str(root / "script.txt"), str(wav)]
        with (root / "voice.log").open("wb") as log:
            deadline = monotonic() + 1200
            with subprocess.Popen(command, cwd=Path(__file__).resolve().parents[3], env=environment,
                                  stdout=log, stderr=subprocess.STDOUT) as process:
                try:
                    while process.poll() is None:
                        self.check_cancelled()
                        if monotonic() >= deadline:
                            raise RuntimeError("声音复刻超时")
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                except Exception:
                    process.kill()
                    raise
        if process.returncode or not wav.is_file():
            detail = (root / "voice.log").read_text(encoding="utf-8", errors="replace").strip().splitlines()
            reason = next((line for line in reversed(detail) if "Error:" in line), detail[-1] if detail else "请检查 Qwen3-TTS 环境")
            reason = reason[:400]
            raise RuntimeError(f"声音复刻失败（退出码 {process.returncode}）：{reason}")
        duration = audio_duration(wav)
        if not 2 <= duration <= 14:
            raise ValueError(f"口播音频为 {duration:.1f} 秒，请提交更短的讲解主题（视频支持 2 至 14 秒）")
        ctx.artifacts.update(audio=wav.name, audio_seconds=duration)
        return {"audio": wav.name, "duration_seconds": duration}

    def render(self, ctx):
        self.check_cancelled()
        root = ctx.task_dir
        seconds = ctx.artifacts["audio_seconds"]
        duration = max(4, ceil(seconds + 0.45))
        prompt = (
            VISUAL_PROMPT + f"从开头开始自然口播，约在第 {seconds:.1f} 秒说完，"
            f"说完自然停住。台词：{ctx.artifacts['speech']}"
        )
        (root / "video_prompt.txt").write_text(prompt, encoding="utf-8")
        ctx.artifacts.update(video_prompt="video_prompt.txt", video_model=DOUBAO_MODEL)
        trace = {}

        def progress(value):
            self.check_cancelled()
            upload = value.get("upload") or {}
            if not value.get("protocol"):
                message = f"豆包参考人像上传：{upload.get('committed', 0)}/{upload.get('expected', 1)}"
            elif value.get("awaiting_confirmation"):
                message = "正在确认豆包视频参数"
            else:
                message = f"豆包正在渲染，已查询 {value.get('polls', 0)} 次"
            self.update(message=message, provider_response=value)

        try:
            urls = DoubaoWebVideoProvider(self.doubao_config).generate(
                prompt, model=DOUBAO_MODEL, aspect="9:16", duration=duration,
                image=self.profile / "portrait.png", diagnostics=trace, progress=progress,
            )
        finally:
            self.update(provider_response=trace)
        self.check_cancelled()
        if not urls:
            raise RuntimeError("豆包没有返回口播 MP4")
        target = root / "render.mp4"
        save_remote_asset(urls[0], target)
        metadata = validate_video(target)
        ctx.artifacts.update(render=target.name, render_seconds=metadata["duration_seconds"])
        return {"model": DOUBAO_MODEL, "render": target.name, **metadata}

    def export(self, ctx):
        self.check_cancelled()
        root = ctx.task_dir
        target = root / "english_lesson.mp4"
        temporary = root / "english_lesson.tmp.mp4"
        if ctx.artifacts["render_seconds"] + 0.05 < ctx.artifacts["audio_seconds"]:
            raise ValueError("豆包画面短于完整口播，请缩短讲稿后重试")
        ffmpeg("-i", str(root / "render.mp4"), "-i", str(root / "speech.wav"),
               "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264", "-preset", "fast",
               "-crf", "18", "-pix_fmt", "yuv420p", "-c:a", "aac", "-af", "apad=pad_dur=0.25", "-shortest",
               "-movflags", "+faststart", str(temporary))
        metadata = validate_video(temporary)
        temporary.replace(target)
        ctx.artifacts["output"] = {"type": "video", "href": f"/artifacts/generation_jobs/{ctx.task_id}/{target.name}",
                                   **metadata}
        return {"video": target.name}
