"""Detect Codex / Claude Code states from session logs scoped to project cwd."""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from ..tool_paths import get_claude_projects_root, get_codex_sessions_root
from ..models import LightState
from .workspace_resolver import cwd_to_claude_slug

logger = logging.getLogger(__name__)

SESSION_MAX_AGE_SEC = 7200.0
RUNNING_SESSION_AGE_SEC = 45.0
WAITING_PENDING_AGE_SEC = 8.0


def _normalize_cwd(cwd: str) -> str:
    return os.path.normpath(cwd.strip())


def _find_codex_session(cwd: str) -> Path | None:
    target = _normalize_cwd(cwd)
    if not target:
        return None

    now = time.time()
    candidates: list[tuple[float, Path]] = []
    root = get_codex_sessions_root()
    if not root.is_dir():
        return None

    for path in root.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime > SESSION_MAX_AGE_SEC:
            continue

        try:
            first_line = path.read_text(encoding="utf-8", errors="replace").splitlines()[0]
            meta = json.loads(first_line)
        except (OSError, IndexError, json.JSONDecodeError):
            continue

        if meta.get("type") != "session_meta":
            continue

        session_cwd = _normalize_cwd(str(meta.get("payload", {}).get("cwd", "")))
        if session_cwd == target:
            candidates.append((mtime, path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _find_claude_session(cwd: str) -> Path | None:
    target = _normalize_cwd(cwd)
    if not target:
        return None

    base = get_claude_projects_root() / cwd_to_claude_slug(target)
    if not base.is_dir():
        return None

    now = time.time()
    candidates: list[tuple[float, Path]] = []
    for path in base.glob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if now - mtime > SESSION_MAX_AGE_SEC:
            continue
        candidates.append((mtime, path))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _analyze_codex_session(path: Path) -> tuple[LightState | None, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        age = time.time() - path.stat().st_mtime
    except OSError as exc:
        logger.debug("Failed to read codex session %s: %s", path, exc)
        return None, ""

    pending_calls: set[str] = set()
    last_event = ""

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        event_type = obj.get("type")
        payload = obj.get("payload") or {}
        if event_type == "response_item":
            item_type = payload.get("type")
            if item_type == "function_call":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    pending_calls.add(call_id)
            elif item_type == "function_call_output":
                call_id = payload.get("call_id")
                if isinstance(call_id, str):
                    pending_calls.discard(call_id)
        elif event_type == "event_msg":
            last_event = str(payload.get("type", ""))

    if pending_calls:
        if age >= WAITING_PENDING_AGE_SEC:
            return LightState.WAITING, f"session: approval pending ({len(pending_calls)})"
        return LightState.RUNNING, f"session: executing ({age:.0f}s ago)"

    if age < RUNNING_SESSION_AGE_SEC and last_event != "task_complete":
        return LightState.RUNNING, f"session: active ({age:.0f}s ago)"

    if last_event == "task_complete":
        return LightState.IDLE, "session: complete"

    return None, ""


def _claude_tool_blocks(message: dict) -> list[dict]:
    content = message.get("content")
    if not isinstance(content, list):
        return []
    return [block for block in content if isinstance(block, dict)]


def _analyze_claude_session(path: Path) -> tuple[LightState | None, str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        age = time.time() - path.stat().st_mtime
    except OSError as exc:
        logger.debug("Failed to read claude session %s: %s", path, exc)
        return None, ""

    pending_tools: set[str] = set()
    last_assistant_tools = False

    for line in lines:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue

        msg_type = obj.get("type")
        if msg_type == "assistant":
            message = obj.get("message") or {}
            tool_ids = [
                block.get("id")
                for block in _claude_tool_blocks(message)
                if block.get("type") == "tool_use" and isinstance(block.get("id"), str)
            ]
            if tool_ids:
                last_assistant_tools = True
                pending_tools.update(tool_ids)
            else:
                last_assistant_tools = False
        elif msg_type == "user":
            message = obj.get("message") or {}
            for block in _claude_tool_blocks(message):
                if block.get("type") == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    if isinstance(tool_use_id, str):
                        pending_tools.discard(tool_use_id)

    if pending_tools:
        if age >= WAITING_PENDING_AGE_SEC:
            return LightState.WAITING, f"session: approval pending ({len(pending_tools)})"
        return LightState.RUNNING, f"session: executing ({age:.0f}s ago)"

    if last_assistant_tools and age < RUNNING_SESSION_AGE_SEC:
        return LightState.RUNNING, f"session: active ({age:.0f}s ago)"

    return None, ""


def analyze_cli_session(tool_name: str, cwd: str) -> tuple[LightState | None, str]:
    """Return state for a CLI tool session in the given project directory."""
    if not cwd:
        return None, ""

    if tool_name == "codex":
        path = _find_codex_session(cwd)
        if path:
            return _analyze_codex_session(path)
    elif tool_name == "claude-code":
        path = _find_claude_session(cwd)
        if path:
            return _analyze_claude_session(path)

    return None, ""
