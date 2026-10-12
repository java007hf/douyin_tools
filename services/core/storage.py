"""Separate durable application state from disposable cache files."""
from __future__ import annotations

import os
from contextlib import closing
import json
import sqlite3
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def store_root() -> Path:
    return Path(os.environ.get("DOUYIN_STORE_DIR") or ROOT / "store").resolve()


def service_store(name: str) -> Path:
    return store_root() / name


def migrate_legacy_store(cache_root: Path = ROOT / "cache") -> list[str]:
    """Move known durable data only; never overwrite an existing destination.

    Run with all application writers stopped. Diagnostics and validation data
    are intentionally excluded. Moving task directories retains portable URLs.
    """
    cache_root = Path(cache_root).resolve()
    destination = store_root()
    names = {
        "models": ["whisper"],
        "douyin": ["understanding_history.sqlite3", "understanding_history.sqlite3-wal",
                   "understanding_history.sqlite3-shm", "web_jobs", "web_downloads", "web_url_lists",
                   ".douyin-browser", ".douyin-browser-collect", ".douyin-browser-download"],
        "video_creator": ["provider_configs.json", "storage.json", "cloudinary.json", "assets.db",
                          "assets.db-wal", "assets.db-shm", "reference_library", "ai_video_jobs",
                          "generation_jobs", "frame_jobs"],
    }
    moves = []
    for service, entries in names.items():
        for entry in entries:
            source = cache_root / service / entry
            target = destination / service / entry
            if source.exists():
                if target.exists():
                    raise FileExistsError(f"Persistent migration destination already exists: {target}")
                moves.append((source, target))
    # Older standalone runs used the top-level cache instead of cache/douyin.
    for entry in (".douyin-browser", ".douyin-browser-collect", ".douyin-browser-download", "web_downloads", "web_url_lists", "downloads"):
        source = cache_root / entry
        target = destination / "douyin" / "legacy" / entry
        if entry == ".douyin-browser" and not (cache_root / "douyin" / entry).exists():
            target = destination / "douyin" / entry
        if source.exists():
            if target.exists():
                raise FileExistsError(f"Persistent migration destination already exists: {target}")
            moves.append((source, target))
    # Check every path before moving any data; all targets are within store/.
    for source, target in moves:
        source.resolve().relative_to(cache_root)
        target.resolve().relative_to(destination)
    completed = []
    try:
        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            for attempt in range(20):
                try:
                    source.rename(target)
                    break
                except PermissionError:
                    if attempt == 19:
                        raise
                    time.sleep(min(0.05 * (2 ** attempt), 0.5))
            completed.append((source, target))
    except OSError:
        # Keep a failed migration recoverable without partially changing roots.
        for source, target in reversed(completed):
            target.rename(source)
        raise
    _rewrite_migrated_paths(cache_root, destination)
    return [target.relative_to(destination).as_posix() for _, target in moves]


def _rewrite_migrated_paths(old: Path, new: Path) -> None:
    def rewrite(value):
        if isinstance(value, dict):
            return {key: rewrite(item) for key, item in value.items()}
        if isinstance(value, list):
            return [rewrite(item) for item in value]
        if isinstance(value, str):
            for service in ("douyin", "video_creator"):
                for source in (str(old / service), (old / service).as_posix(), "cache/" + service, "cache\\" + service):
                    if value.lower().startswith(source.lower() + "\\") or value.lower().startswith(source.lower() + "/"):
                        return str(new / service) + value[len(source):]
        return value

    for service in ("douyin", "video_creator"):
        for path in (new / service).rglob("*.json"):
            if any(part.startswith(".douyin-browser") for part in path.parts):
                continue
            try:
                original = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            updated = rewrite(original)
            if updated != original:
                path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    for file, table, key, column in (
        (new / "video_creator/assets.db", "assets", "id", "data"),
        (new / "douyin/understanding_history.sqlite3", "understanding_history", "id", "result_json"),
        (new / "douyin/web_downloads/mentions/mentions.sqlite3", "mentions", "id", "data"),
    ):
        if not file.exists():
            continue
        with closing(sqlite3.connect(file)) as db, db:
            for identifier, raw in db.execute(f"SELECT {key},{column} FROM {table}").fetchall():
                original = json.loads(raw)
                updated = rewrite(original)
                if updated != original:
                    db.execute(f"UPDATE {table} SET {column}=? WHERE {key}=?", (json.dumps(updated, ensure_ascii=False), identifier))
