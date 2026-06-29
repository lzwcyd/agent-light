"""Resolve Claude Desktop coding sessions from app session metadata."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..tool_paths import get_claude_desktop_sessions_dir

logger = logging.getLogger(__name__)

SESSION_FILE_RE = re.compile(r"^local_.+\.json$", re.IGNORECASE)
CLAUDE_TITLE_SUFFIX_RE = re.compile(r"\s*[-–—]\s*Claude\s*$", re.IGNORECASE)

_cache_at = 0.0
_cache: list[ClaudeDesktopSession] = []
CACHE_TTL_SEC = 2.0


@dataclass(frozen=True)
class ClaudeDesktopSession:
    session_id: str
    cli_session_id: str
    title: str
    cwd: str
    last_activity_at: float
    is_archived: bool


def invalidate_claude_desktop_session_cache() -> None:
    global _cache_at
    _cache.clear()
    _cache_at = 0.0


def _normalize_title(title: str) -> str:
    text = title.strip()
    text = CLAUDE_TITLE_SUFFIX_RE.sub("", text)
    return text.strip().lower()


def _normalize_cwd(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return text


def _load_sessions_from_disk() -> list[ClaudeDesktopSession]:
    root = get_claude_desktop_sessions_dir()
    if not root.is_dir():
        return []

    sessions: list[ClaudeDesktopSession] = []
    try:
        paths = sorted(root.rglob("local_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError as exc:
        logger.debug("Failed to scan Claude Desktop sessions at %s: %s", root, exc)
        return []

    for path in paths:
        if not SESSION_FILE_RE.match(path.name):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue

        cli_session_id = str(data.get("cliSessionId") or data.get("cli_session_id") or "").strip()
        session_id = str(data.get("sessionId") or data.get("session_id") or cli_session_id).strip()
        title = str(data.get("title") or "").strip()
        cwd = _normalize_cwd(str(data.get("cwd") or ""))
        if not cli_session_id or not cwd:
            continue

        last_activity_raw = data.get("lastActivityAt") or data.get("last_activity_at") or 0
        try:
            last_activity_at = float(last_activity_raw) / 1000.0 if float(last_activity_raw) > 1e12 else float(last_activity_raw)
        except (TypeError, ValueError):
            last_activity_at = 0.0
        if last_activity_at <= 0:
            try:
                last_activity_at = path.stat().st_mtime
            except OSError:
                last_activity_at = 0.0

        sessions.append(
            ClaudeDesktopSession(
                session_id=session_id,
                cli_session_id=cli_session_id,
                title=title,
                cwd=cwd,
                last_activity_at=last_activity_at,
                is_archived=bool(data.get("isArchived") or data.get("is_archived")),
            )
        )

    sessions.sort(key=lambda item: item.last_activity_at, reverse=True)
    return sessions


def load_claude_desktop_sessions() -> list[ClaudeDesktopSession]:
    global _cache_at
    now = time.time()
    if _cache and now - _cache_at <= CACHE_TTL_SEC:
        return list(_cache)

    _cache[:] = _load_sessions_from_disk()
    _cache_at = now
    return list(_cache)


def _title_score(window_title: str, session: ClaudeDesktopSession) -> int:
    window_norm = _normalize_title(window_title)
    session_norm = _normalize_title(session.title)
    if not window_norm or not session_norm:
        return 0

    if window_norm == session_norm:
        return 100

    if window_norm in session_norm or session_norm in window_norm:
        return 80

    folder = Path(session.cwd).name.lower()
    if folder and (folder in window_norm or window_norm in folder):
        return 60

    window_tokens = {token for token in re.split(r"[\s/·\-–—]+", window_norm) if len(token) >= 3}
    session_tokens = {token for token in re.split(r"[\s/·\-–—]+", session_norm) if len(token) >= 3}
    overlap = window_tokens & session_tokens
    if overlap:
        return 40 + min(len(overlap) * 5, 20)

    return 0


def match_session_for_window_title(window_title: str) -> ClaudeDesktopSession | None:
    """Match a Claude Desktop window title to the most likely coding session."""
    title = window_title.strip()
    if not title:
        return None

    best: ClaudeDesktopSession | None = None
    best_score = 0
    for session in load_claude_desktop_sessions():
        if session.is_archived:
            continue
        score = _title_score(title, session)
        if score <= 0:
            continue
        if score > best_score or (score == best_score and best and session.last_activity_at > best.last_activity_at):
            best = session
            best_score = score

    return best if best_score >= 40 else None
