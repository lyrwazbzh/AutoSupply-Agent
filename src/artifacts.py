"""Temporary, user-scoped files exposed through the download API."""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import uuid
from pathlib import Path
from urllib.parse import quote


ARTIFACT_ROOT = Path(__file__).resolve().parent.parent / ".runtime" / "artifacts"
ARTIFACT_TTL_SECONDS = max(60, int(os.getenv("ARTIFACT_TTL_SECONDS", "86400")))


def _user_bucket(user_id: str) -> str:
    return hashlib.sha256((user_id or "default_user").encode("utf-8")).hexdigest()[:24]


def _safe_filename(filename: str) -> str:
    return Path(str(filename or "artifact")).name or "artifact"


def cleanup_expired_artifacts(*, now: float | None = None) -> int:
    """Remove artifact directories whose only file has exceeded the TTL."""
    if not ARTIFACT_ROOT.exists():
        return 0
    cutoff = (now or time.time()) - ARTIFACT_TTL_SECONDS
    removed = 0
    for user_dir in ARTIFACT_ROOT.iterdir():
        if not user_dir.is_dir():
            continue
        for artifact_dir in user_dir.iterdir():
            if not artifact_dir.is_dir():
                continue
            files = [path for path in artifact_dir.iterdir() if path.is_file()]
            stamp = max((path.stat().st_mtime for path in files), default=artifact_dir.stat().st_mtime)
            if stamp <= cutoff:
                shutil.rmtree(artifact_dir)
                removed += 1
        if not any(user_dir.iterdir()):
            user_dir.rmdir()
    return removed


def save_artifact_bytes(user_id: str, filename: str, content: bytes) -> tuple[str, Path]:
    cleanup_expired_artifacts()
    file_id = uuid.uuid4().hex
    artifact_dir = ARTIFACT_ROOT / _user_bucket(user_id) / file_id
    artifact_dir.mkdir(parents=True, exist_ok=False)
    path = artifact_dir / _safe_filename(filename)
    path.write_bytes(content)
    return file_id, path


def save_artifact_text(
    user_id: str, filename: str, content: str, *, encoding: str = "utf-8"
) -> tuple[str, Path]:
    return save_artifact_bytes(user_id, filename, content.encode(encoding))


def resolve_artifact(user_id: str, file_id: str, filename: str) -> Path | None:
    if len(file_id) != 32 or any(ch not in "0123456789abcdef" for ch in file_id.lower()):
        return None
    safe_name = _safe_filename(filename)
    if safe_name != filename:
        return None
    artifact_dir = ARTIFACT_ROOT / _user_bucket(user_id) / file_id.lower()
    path = (artifact_dir / safe_name).resolve()
    if not path.is_relative_to(artifact_dir.resolve()) or not path.is_file():
        return None
    if path.stat().st_mtime <= time.time() - ARTIFACT_TTL_SECONDS:
        shutil.rmtree(artifact_dir)
        return None
    return path


def artifact_url(public_base_url: str, file_id: str, filename: str) -> str:
    name = quote(_safe_filename(filename), safe="")
    return f"{public_base_url.rstrip('/')}/api/download/{file_id}/{name}"
