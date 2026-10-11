"""Persistent, content-addressed reference assets for cross-project continuity."""
from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import sqlite3
import threading
import time
import uuid
from pathlib import Path


class ReferenceAssetStore:
    def __init__(self, root: Path):
        self.root = root
        self.files = root / "files"
        self.db_path = root / "library.db"
        self.lock = threading.Lock()
        self.files.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS reference_assets (
                id TEXT PRIMARY KEY, content_hash TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
                kind TEXT NOT NULL, description TEXT NOT NULL, filename TEXT NOT NULL,
                source_type TEXT NOT NULL, source_id TEXT, created_at REAL NOT NULL,
                use_count INTEGER NOT NULL DEFAULT 0)""")

    def add(self, source: Path, *, name: str, kind: str, description: dict | None = None,
            source_type: str = "upload", source_id: str = "") -> tuple[dict, bool]:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT * FROM reference_assets WHERE content_hash=?", (digest,)).fetchone()
            if row:
                return self._row(row), True
            asset_id = uuid.uuid4().hex
            suffix = source.suffix.lower() or mimetypes.guess_extension(mimetypes.guess_type(source.name)[0] or "") or ".bin"
            filename = f"{digest}{suffix}"
            target = self.files / filename
            if not target.exists():
                shutil.copy2(source, target)
            value = (asset_id, digest, name.strip() or source.stem, kind, json.dumps(description or {}, ensure_ascii=False),
                     filename, source_type, source_id, time.time(), 0)
            db.execute("INSERT INTO reference_assets VALUES (?,?,?,?,?,?,?,?,?,?)", value)
            row = db.execute("SELECT * FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
            asset = self._row(row)
            (self.root / f"{asset_id}.json").write_text(json.dumps(asset, ensure_ascii=False, indent=2), encoding="utf-8")
            return asset, False

    def get(self, asset_id: str) -> dict | None:
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT * FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
        return self._row(row) if row else None

    def list(self) -> list[dict]:
        with self.lock, sqlite3.connect(self.db_path) as db:
            rows = db.execute("SELECT * FROM reference_assets ORDER BY created_at DESC").fetchall()
        return [self._row(row) for row in rows]

    def use(self, asset_id: str) -> Path | None:
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT filename FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                return None
            db.execute("UPDATE reference_assets SET use_count=use_count+1 WHERE id=?", (asset_id,))
        path = self.files / row[0]
        return path if path.is_file() else None

    def update(self, asset_id: str, *, name: str, kind: str, description: dict) -> dict | None:
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT * FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE reference_assets SET name=?, kind=?, description=? WHERE id=?",
                (name.strip() or row[2], kind, json.dumps(description, ensure_ascii=False), asset_id),
            )
            row = db.execute("SELECT * FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
        asset = self._row(row)
        (self.root / f"{asset_id}.json").write_text(json.dumps(asset, ensure_ascii=False, indent=2), encoding="utf-8")
        return asset

    def delete(self, asset_id: str) -> bool:
        with self.lock, sqlite3.connect(self.db_path) as db:
            row = db.execute("SELECT filename FROM reference_assets WHERE id=?", (asset_id,)).fetchone()
            if not row:
                return False
            db.execute("DELETE FROM reference_assets WHERE id=?", (asset_id,))
            remaining = db.execute("SELECT 1 FROM reference_assets WHERE filename=?", (row[0],)).fetchone()
        if not remaining:
            (self.files / row[0]).unlink(missing_ok=True)
        (self.root / f"{asset_id}.json").unlink(missing_ok=True)
        return True

    @staticmethod
    def _row(row: tuple) -> dict:
        return {"id": row[0], "content_hash": row[1], "name": row[2], "kind": row[3],
                "description": json.loads(row[4]), "filename": row[5], "source_type": row[6],
                "source_id": row[7] or "", "created_at": row[8], "use_count": row[9],
                "href": f"/artifacts/reference_library/files/{row[5]}"}
