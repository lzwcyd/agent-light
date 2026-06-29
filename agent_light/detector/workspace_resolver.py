"""Resolve Cursor workspace labels to full filesystem paths."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from urllib.parse import unquote

from ..tool_paths import get_cursor_workspace_storage
from .cursor_log_utils import latest_session_dir, read_log_tail

logger = logging.getLogger(__name__)

WORKSPACE_ROOTS_RE = re.compile(
    r'"workspace_roots"\s*:\s*\[\s*"([^"]+)"',
)


def path_to_slug(path: str) -> str:
    normalized = path.strip().rstrip("/")
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized.replace("/", "-")


def cwd_to_claude_slug(cwd: str) -> str:
    return "-" + path_to_slug(cwd)


def resolve_workspace_from_hooks(window_key: str | None) -> str:
    """Read the active workspace path for a Cursor window from hooks logs."""
    if not window_key:
        return ""

    session = latest_session_dir()
    if not session:
        return ""

    window_dir = session / f"window{window_key}"
    if not window_dir.is_dir():
        return ""

    hooks_logs = list(window_dir.glob("output_*/cursor.hooks.*.log"))
    if not hooks_logs:
        return ""

    hooks_log = max(hooks_logs, key=lambda p: p.stat().st_mtime)
    tail = read_log_tail(hooks_log, max_bytes=32768)
    matches = WORKSPACE_ROOTS_RE.findall(tail)
    if not matches:
        return ""

    return matches[-1]


def resolve_workspace_path(label: str, window_key: str | None = None) -> str:
    """
    Extension-host labels are often just the folder name (e.g. mockserver).
    Prefer hooks logs for the active window, then workspaceStorage.
    """
    if window_key:
        hooks_path = resolve_workspace_from_hooks(window_key)
        if hooks_path:
            return hooks_path

    label = label.strip()
    if not label or label == "Unknown":
        return label
    if label.startswith("/") or label.startswith("~"):
        return str(Path(label).expanduser())

    matches: list[tuple[float, str]] = []
    try:
        for ws_dir in get_cursor_workspace_storage().iterdir():
            ws_json = ws_dir / "workspace.json"
            if not ws_json.is_file():
                continue
            data = json.loads(ws_json.read_text(encoding="utf-8"))
            folder = data.get("folder", "")
            if not isinstance(folder, str) or not folder.startswith("file://"):
                continue
            path = unquote(folder[7:])
            if Path(path).name == label or path.rstrip("/").endswith(f"/{label}"):
                try:
                    mtime = ws_dir.stat().st_mtime
                except OSError:
                    mtime = 0.0
                matches.append((mtime, path))
    except OSError as exc:
        logger.debug("resolve_workspace_path failed for %s: %s", label, exc)

    if matches:
        matches.sort(key=lambda item: item[0], reverse=True)
        return matches[0][1]

    return label
