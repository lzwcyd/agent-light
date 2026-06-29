"""Shared helpers for reading Cursor log directories."""

from __future__ import annotations

from pathlib import Path

from ..tool_paths import get_cursor_log_roots


def latest_session_dir() -> Path | None:
    best: Path | None = None
    best_mtime = 0.0
    for log_root in get_cursor_log_roots():
        try:
            sessions = [p for p in log_root.iterdir() if p.is_dir()]
        except OSError:
            continue
        for session in sessions:
            try:
                mtime = session.stat().st_mtime
            except OSError:
                continue
            if mtime > best_mtime:
                best_mtime = mtime
                best = session
    return best


def read_log_tail(path: Path, max_bytes: int = 8192) -> str:
    try:
        size = path.stat().st_size
        with open(path, "rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""
