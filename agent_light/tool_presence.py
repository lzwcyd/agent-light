"""Detect whether Cursor / Claude Code / Codex are installed (no running process required)."""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TOOL_CURSOR = "cursor"
TOOL_CLAUDE = "claude"
TOOL_CODEX = "codex"
ALL_TOOLS = (TOOL_CURSOR, TOOL_CLAUDE, TOOL_CODEX)

TOOL_LABELS = {
    TOOL_CURSOR: "Cursor",
    TOOL_CLAUDE: "Claude Code",
    TOOL_CODEX: "Codex",
}

_CURSOR_APP_NAMES = ("Cursor.app",)
_CLAUDE_DESKTOP_MARKERS = (
    "claude.app",
    "claude helper",
    "claude helper (renderer)",
    "claude helper (gpu)",
)


@dataclass(frozen=True)
class ToolPresence:
    tool: str
    available: bool
    reason: str
    config_dir: Path | None = None


def _path_is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _path_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def _dir_has_entries(path: Path) -> bool:
    if not _path_is_dir(path):
        return False
    try:
        return any(path.iterdir())
    except OSError:
        return False


def _is_executable(path: Path) -> bool:
    return _path_is_file(path) and os.access(path, os.X_OK)


def _unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path.expanduser().resolve()) if path.exists() else str(path.expanduser())
        if key in seen:
            continue
        seen.add(key)
        out.append(path.expanduser())
    return out


def _which_cli(name: str) -> Path | None:
    found = shutil.which(name)
    return Path(found) if found else None


def _common_cli_bins(name: str) -> list[Path]:
    home = Path.home()
    candidates = [
        home / ".local" / "bin" / name,
        Path("/opt/homebrew/bin") / name,
        Path("/usr/local/bin") / name,
        home / ".npm-global" / "bin" / name,
        home / "node_modules" / ".bin" / name,
    ]
    return [p for p in candidates if _is_executable(p)]


def _glob_cask_bins(cask_name: str, binary_prefix: str) -> list[Path]:
    found: list[Path] = []
    for root in (Path("/opt/homebrew/Caskroom"), Path("/usr/local/Caskroom")):
        if not _path_is_dir(root):
            continue
        try:
            for path in root.glob(f"{cask_name}/*/{binary_prefix}*"):
                if _is_executable(path):
                    found.append(path)
        except OSError:
            continue
    return found


def _looks_like_claude_code_cli(path: Path, cmdline: str = "") -> bool:
    text = f"{path} {cmdline}".lower()
    if any(marker in text for marker in _CLAUDE_DESKTOP_MARKERS):
        return False
    if "claude-code" in text or "@anthropic-ai/claude-code" in text:
        return True
    if path.name == "claude" and "/.local/bin/" in str(path):
        return True
    if "/caskroom/claude" in text and "claude-code" in text:
        return True
    return path.name == "claude" and "claude.app" not in text


def find_codex_cli_binaries() -> list[Path]:
    found: list[Path] = []
    if p := _which_cli("codex"):
        found.append(p)
    found.extend(_common_cli_bins("codex"))
    found.extend(_glob_cask_bins("codex", "codex"))
    return _unique_paths(found)


def find_claude_code_cli_binaries() -> list[Path]:
    found: list[Path] = []
    if p := _which_cli("claude"):
        if _looks_like_claude_code_cli(p):
            found.append(p)
    for p in _common_cli_bins("claude"):
        if _looks_like_claude_code_cli(p):
            found.append(p)
    found.extend(_glob_cask_bins("claude-code", "claude"))
    found.extend(_glob_cask_bins("claude", "claude"))
    return _unique_paths([p for p in found if _looks_like_claude_code_cli(p)])


def find_cursor_app_bundles() -> list[Path]:
    found: list[Path] = []
    for apps_root in (Path("/Applications"), Path.home() / "Applications"):
        for app_name in _CURSOR_APP_NAMES:
            app = apps_root / app_name
            if _path_is_dir(app):
                found.append(app)
    return _unique_paths(found)


def _cursor_user_data_candidates() -> list[Path]:
    from .tool_paths import get_cursor_user_data_dirs

    dirs: list[Path] = []
    try:
        dirs = list(get_cursor_user_data_dirs())
    except (OSError, PermissionError):
        pass
    defaults = [
        Path.home() / "Library/Application Support/Cursor",
        Path.home() / "Library/Application Support/Cursor Nightly",
    ]
    return _unique_paths(dirs + defaults)


def _cursor_config_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = _settings_config_path("cursor_config_dir", ("AGENT_LIGHT_CURSOR_CONFIG_DIR", "CURSOR_CONFIG_DIR"))
    if configured:
        candidates.append(configured)
    for user_data in _cursor_user_data_candidates():
        home = _home_from_library_support(user_data)
        if home:
            candidates.append(home / ".cursor")
    candidates.append(Path.home() / ".cursor")
    return _unique_paths(candidates)


def _claude_config_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = _settings_config_path("claude_config_dir", ("AGENT_LIGHT_CLAUDE_CONFIG_DIR", "CLAUDE_CONFIG_DIR"))
    if configured:
        candidates.append(configured)
    candidates.append(Path.home() / ".claude")
    return _unique_paths(candidates)


def _codex_home_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = _settings_config_path("codex_home", ("AGENT_LIGHT_CODEX_HOME", "CODEX_HOME"))
    if configured:
        candidates.append(configured)
    candidates.append(Path.home() / ".codex")
    return _unique_paths(candidates)


def _settings_config_path(key: str, env_keys: tuple[str, ...]) -> Path | None:
    try:
        from .settings import get_tool_paths

        value = get_tool_paths().get(key, "").strip()
        if value:
            return Path(value).expanduser()
    except Exception:
        pass
    for env_key in env_keys:
        value = os.environ.get(env_key, "").strip()
        if value:
            return Path(value).expanduser()
    return None


def _home_from_library_support(user_data_dir: Path) -> Path | None:
    parts = user_data_dir.parts
    if "Library" not in parts:
        return None
    idx = parts.index("Library")
    if idx <= 0:
        return None
    return Path(*parts[:idx])


def _best_existing_dir(candidates: list[Path], markers: tuple[str, ...]) -> Path | None:
    scored: list[tuple[int, Path]] = []
    for path in candidates:
        if not _path_is_dir(path):
            continue
        score = 1
        for marker in markers:
            marker_path = path / marker
            if _path_is_file(marker_path) or _dir_has_entries(marker_path):
                score += 2
        scored.append((score, path))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]


def resolve_cursor_config_dir() -> Path:
    markers = ("hooks.json", "projects", "hooks")
    best = _best_existing_dir(_cursor_config_dir_candidates(), markers)
    return best or Path.home() / ".cursor"


def resolve_claude_config_dir() -> Path:
    markers = ("settings.json", "projects", "hooks")
    best = _best_existing_dir(_claude_config_dir_candidates(), markers)
    return best or Path.home() / ".claude"


def resolve_codex_home() -> Path:
    markers = ("hooks.json", "config.toml", "sessions", "hooks")
    best = _best_existing_dir(_codex_home_candidates(), markers)
    return best or Path.home() / ".codex"


def _detect_cursor() -> ToolPresence:
    config_dir = resolve_cursor_config_dir()
    if _path_is_file(config_dir / "hooks" / "agent-light-signal.sh"):
        return ToolPresence(TOOL_CURSOR, True, "已安装 Agent Light Hook", config_dir)

    for user_data in _cursor_user_data_candidates():
        if _path_is_dir(user_data):
            return ToolPresence(TOOL_CURSOR, True, f"检测到数据目录 {user_data}", config_dir)

    if _path_is_dir(config_dir) and _dir_has_entries(config_dir):
        return ToolPresence(TOOL_CURSOR, True, f"检测到配置目录 {config_dir}", config_dir)

    for marker in ("hooks.json", "projects", "hooks"):
        if _path_is_file(config_dir / marker) or _dir_has_entries(config_dir / marker):
            return ToolPresence(TOOL_CURSOR, True, f"检测到 {config_dir / marker}", config_dir)

    if find_cursor_app_bundles():
        return ToolPresence(TOOL_CURSOR, True, "检测到 Cursor.app", config_dir)

    return ToolPresence(TOOL_CURSOR, False, "未检测到 Cursor", config_dir)


def _detect_claude() -> ToolPresence:
    config_dir = resolve_claude_config_dir()
    if _path_is_file(config_dir / "hooks" / "agent-light-claude-signal.sh"):
        return ToolPresence(TOOL_CLAUDE, True, "已安装 Agent Light Hook", config_dir)

    for marker in ("settings.json", "projects", "hooks"):
        target = config_dir / marker
        if _path_is_file(target) or _dir_has_entries(target):
            return ToolPresence(TOOL_CLAUDE, True, f"检测到 {target}", config_dir)

    bins = find_claude_code_cli_binaries()
    if bins:
        return ToolPresence(TOOL_CLAUDE, True, f"检测到 CLI {bins[0]}", config_dir)

    return ToolPresence(TOOL_CLAUDE, False, "未检测到 Claude Code", config_dir)


def _detect_codex() -> ToolPresence:
    config_dir = resolve_codex_home()
    if _path_is_file(config_dir / "hooks" / "agent-light-codex-signal.sh"):
        return ToolPresence(TOOL_CODEX, True, "已安装 Agent Light Hook", config_dir)

    for marker in ("hooks.json", "config.toml", "sessions", "hooks"):
        target = config_dir / marker
        if _path_is_file(target) or _dir_has_entries(target):
            return ToolPresence(TOOL_CODEX, True, f"检测到 {target}", config_dir)

    bins = find_codex_cli_binaries()
    if bins:
        return ToolPresence(TOOL_CODEX, True, f"检测到 CLI {bins[0]}", config_dir)

    return ToolPresence(TOOL_CODEX, False, "未检测到 Codex", config_dir)


def get_tool_presence(tool: str) -> ToolPresence:
    if tool == TOOL_CURSOR:
        return _detect_cursor()
    if tool == TOOL_CLAUDE:
        return _detect_claude()
    if tool == TOOL_CODEX:
        return _detect_codex()
    return ToolPresence(tool, False, "未知工具", None)


def get_all_tool_presence() -> dict[str, ToolPresence]:
    return {tool: get_tool_presence(tool) for tool in ALL_TOOLS}


def is_tool_available(tool: str) -> bool:
    return get_tool_presence(tool).available


def get_available_tools() -> list[str]:
    return [tool for tool in ALL_TOOLS if is_tool_available(tool)]


def format_available_tools_summary() -> str:
    available = get_available_tools()
    if not available:
        return "未检测到 Cursor / Claude Code / Codex"
    return "检测到：" + "、".join(TOOL_LABELS[t] for t in available)


def format_missing_tools_summary() -> str:
    missing = [tool for tool in ALL_TOOLS if not is_tool_available(tool)]
    if not missing:
        return ""
    return "未检测到：" + "、".join(TOOL_LABELS[t] for t in missing)
