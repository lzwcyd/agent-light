"""Dynamic path resolution for Cursor / Codex / Claude data directories."""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

USER_DATA_DIR_RE = re.compile(r"--user-data-dir(?:=|\s+)([^\s]+)")
CACHE_TTL_SEC = 30.0

_cache: dict[str, object] = {}
_cache_at = 0.0


def _now() -> float:
    return time.time()


def _invalidate_if_stale() -> None:
    global _cache_at
    if _now() - _cache_at > CACHE_TTL_SEC:
        _cache.clear()
        _cache_at = _now()


def invalidate_tool_paths_cache() -> None:
    """Force re-discovery on next access (e.g. after tool restart)."""
    global _cache_at
    _cache.clear()
    _cache_at = 0.0


def _expand_path(raw: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(raw.strip())))


def _settings_paths() -> dict[str, str]:
    try:
        from .settings import get_tool_paths

        return get_tool_paths()
    except Exception:
        return {}


def _path_from_config(*keys: str, env_keys: tuple[str, ...] = ()) -> Path | None:
    settings = _settings_paths()
    for key in keys:
        value = settings.get(key, "")
        if isinstance(value, str) and value.strip():
            return _expand_path(value)

    for env_key in env_keys:
        value = os.environ.get(env_key, "").strip()
        if value:
            return _expand_path(value)
    return None


def _home_from_user_data_dir(user_data_dir: Path) -> Path | None:
    parts = user_data_dir.parts
    if "Library" not in parts:
        return None
    idx = parts.index("Library")
    if idx <= 0:
        return None
    return Path(*parts[:idx])


def _discover_cursor_user_data_dirs() -> list[Path]:
    found: list[Path] = []
    seen: set[str] = set()
    try:
        processes = psutil.process_iter(["pid", "name", "cmdline"])
    except (psutil.Error, OSError, PermissionError):
        return found
    for proc in processes:
        try:
            name = (proc.info.get("name") or "").lower()
            cmdline = proc.info.get("cmdline") or []
            if not cmdline:
                continue
            text = " ".join(cmdline)
            if "cursor" not in name and "cursor" not in text.lower():
                continue
            for match in USER_DATA_DIR_RE.finditer(text):
                path = _expand_path(match.group(1))
                key = str(path)
                if key not in seen:
                    seen.add(key)
                    found.append(path)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _discover_cli_home(process_names: set[str], cmd_filter=None) -> Path | None:
    """Read HOME from a matching CLI process (optional cmdline filter)."""
    try:
        processes = psutil.process_iter(["pid", "name", "cmdline"])
    except (psutil.Error, OSError, PermissionError):
        return None
    for proc in processes:
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in process_names:
                continue
            cmdline = proc.info.get("cmdline") or []
            text = " ".join(cmdline)
            if cmd_filter is not None and not cmd_filter(name, text):
                continue
            env = psutil.Process(proc.info["pid"]).environ()
            home = env.get("HOME", "").strip()
            if home:
                return _expand_path(home)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            continue
    return None


def _codex_process_filter(name: str, cmdline: str) -> bool:
    text = f"{name} {cmdline}".lower()
    return (
        name == "codex"
        or "/codex" in text
        or "openai/codex" in text
        or "@openai/codex" in text
    )


def _claude_code_process_filter(name: str, cmdline: str) -> bool:
    text = f"{name} {cmdline}".lower()
    if "claude.app" in text or "claude helper" in text:
        return False
    return (
        "claude-code" in text
        or "@anthropic-ai/claude-code" in text
        or (name == "claude" and "claude-code" in text)
        or (name == "claude" and "/.local/bin/" in text)
    )


def _cached(key: str, factory):
    _invalidate_if_stale()
    if key not in _cache:
        _cache[key] = factory()
    return _cache[key]


def get_cursor_user_data_dirs() -> list[Path]:
    """All known Cursor user-data directories, most recently active first."""

    def _build() -> list[Path]:
        dirs: list[tuple[float, Path]] = []
        seen: set[str] = set()

        configured = _path_from_config(
            "cursor_user_data_dir",
            env_keys=("AGENT_LIGHT_CURSOR_USER_DATA_DIR", "CURSOR_USER_DATA_DIR"),
        )
        candidates: list[Path] = []
        if configured:
            candidates.append(configured)
        candidates.extend(_discover_cursor_user_data_dirs())
        candidates.append(
            Path.home() / "Library/Application Support/Cursor"
        )
        candidates.append(
            Path.home() / "Library/Application Support/Cursor Nightly"
        )

        for path in candidates:
            key = str(path)
            if key in seen:
                continue
            seen.add(key)
            logs = path / "logs"
            score = 0.0
            if logs.is_dir():
                try:
                    sessions = [p for p in logs.iterdir() if p.is_dir()]
                    if sessions:
                        score = max(p.stat().st_mtime for p in sessions)
                except OSError:
                    pass
            dirs.append((score, path))

        dirs.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in dirs]

    return _cached("cursor_user_data_dirs", _build)


def get_cursor_user_data_dir() -> Path:
    dirs = get_cursor_user_data_dirs()
    return dirs[0] if dirs else Path.home() / "Library/Application Support/Cursor"


def get_cursor_log_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    for user_data in get_cursor_user_data_dirs():
        log_root = user_data / "logs"
        key = str(log_root)
        if key not in seen and log_root.is_dir():
            seen.add(key)
            roots.append(log_root)
    return roots


def get_cursor_log_root() -> Path:
    roots = get_cursor_log_roots()
    return roots[0] if roots else get_cursor_user_data_dir() / "logs"


def get_cursor_workspace_storage() -> Path:
    return get_cursor_user_data_dir() / "User" / "workspaceStorage"


def get_cursor_projects_root() -> Path:
    def _build() -> Path:
        configured = _path_from_config(
            "cursor_projects_dir",
            env_keys=("AGENT_LIGHT_CURSOR_PROJECTS_DIR", "CURSOR_PROJECTS_DIR"),
        )
        if configured:
            return configured

        home = _home_from_user_data_dir(get_cursor_user_data_dir())
        if home:
            return home / ".cursor" / "projects"
        return Path.home() / ".cursor" / "projects"

    return _cached("cursor_projects_root", _build)


def get_cursor_config_dir() -> Path:
    """Cursor hooks config root (~/.cursor or discovered equivalent)."""

    def _build() -> Path:
        configured = _path_from_config(
            "cursor_config_dir",
            env_keys=("AGENT_LIGHT_CURSOR_CONFIG_DIR", "CURSOR_CONFIG_DIR"),
        )
        if configured:
            return configured

        projects = get_cursor_projects_root()
        if projects.is_dir() and projects.name == "projects" and projects.parent.name == ".cursor":
            return projects.parent

        home = _home_from_user_data_dir(get_cursor_user_data_dir())
        candidates: list[Path] = []
        if home:
            candidates.append(home / ".cursor")
        candidates.append(Path.home() / ".cursor")
        for path in candidates:
            if path.is_dir():
                return path
        return candidates[-1]

    return _cached("cursor_config_dir", _build)


def get_codex_home() -> Path:
    def _build() -> Path:
        configured = _path_from_config(
            "codex_home",
            env_keys=("AGENT_LIGHT_CODEX_HOME", "CODEX_HOME"),
        )
        if configured:
            return configured

        candidates: list[Path] = []
        proc_home = _discover_cli_home({"codex"}, _codex_process_filter)
        if proc_home:
            candidates.append(proc_home / ".codex")
        candidates.append(Path.home() / ".codex")
        for path in candidates:
            if path.is_dir():
                return path
        return candidates[-1]

    return _cached("codex_home", _build)


def get_codex_sessions_root() -> Path:
    configured = _path_from_config(
        "codex_sessions_dir",
        env_keys=("AGENT_LIGHT_CODEX_SESSIONS_DIR",),
    )
    if configured:
        return configured
    return get_codex_home() / "sessions"


def get_claude_config_dir() -> Path:
    def _build() -> Path:
        configured = _path_from_config(
            "claude_config_dir",
            env_keys=("AGENT_LIGHT_CLAUDE_CONFIG_DIR", "CLAUDE_CONFIG_DIR"),
        )
        if configured:
            return configured

        candidates: list[Path] = []
        proc_home = _discover_cli_home({"claude", "node"}, _claude_code_process_filter)
        if proc_home:
            candidates.append(proc_home / ".claude")
        candidates.append(Path.home() / ".claude")
        for path in candidates:
            if path.is_dir():
                return path
        return candidates[-1]

    return _cached("claude_config_dir", _build)


def get_claude_projects_root() -> Path:
    configured = _path_from_config(
        "claude_projects_dir",
        env_keys=("AGENT_LIGHT_CLAUDE_PROJECTS_DIR",),
    )
    if configured:
        return configured
    return get_claude_config_dir() / "projects"


def get_claude_desktop_sessions_dir() -> Path:
    configured = _path_from_config(
        "claude_desktop_sessions_dir",
        env_keys=("AGENT_LIGHT_CLAUDE_DESKTOP_SESSIONS_DIR",),
    )
    if configured:
        return configured
    return Path.home() / "Library/Application Support/Claude/claude-code-sessions"


def get_resolved_tool_paths() -> dict[str, str]:
    """Snapshot of currently resolved paths (for logging / debugging)."""
    return {
        "cursor_user_data_dir": str(get_cursor_user_data_dir()),
        "cursor_log_root": str(get_cursor_log_root()),
        "cursor_workspace_storage": str(get_cursor_workspace_storage()),
        "cursor_projects_root": str(get_cursor_projects_root()),
        "cursor_config_dir": str(get_cursor_config_dir()),
        "codex_home": str(get_codex_home()),
        "codex_sessions_root": str(get_codex_sessions_root()),
        "claude_config_dir": str(get_claude_config_dir()),
        "claude_projects_root": str(get_claude_projects_root()),
        "claude_desktop_sessions_dir": str(get_claude_desktop_sessions_dir()),
    }
