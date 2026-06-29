"""Install Agent Light hooks for Cursor, Claude Code, and Codex."""

from __future__ import annotations

import json
import logging
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from ..constants import APP_SLUG
from ..tool_paths import get_claude_config_dir, get_codex_home, get_cursor_config_dir
from ..tool_presence import (
    TOOL_CLAUDE,
    TOOL_CODEX,
    TOOL_CURSOR,
    get_available_tools,
    is_tool_available,
)
from .store import HOOKS_ROOT, PYTHON_PATH_FILE

logger = logging.getLogger(__name__)

CURSOR_SCRIPT = "agent-light-signal.sh"
CLAUDE_SCRIPT = "agent-light-claude-signal.sh"
CODEX_SCRIPT = "agent-light-codex-signal.sh"
OUR_SCRIPTS = frozenset({CURSOR_SCRIPT, CLAUDE_SCRIPT, CODEX_SCRIPT})

CURSOR_EVENTS = (
    "sessionStart",
    "sessionEnd",
    "beforeSubmitPrompt",
    "preToolUse",
    "postToolUse",
    "postToolUseFailure",
    "beforeShellExecution",
    "afterShellExecution",
    "beforeMCPExecution",
    "afterMCPExecution",
    "afterAgentThought",
    "afterAgentResponse",
    "subagentStart",
    "subagentStop",
    "stop",
)

CLAUDE_CODEX_EVENTS = (
    "SessionStart",
    "SessionEnd",
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "PermissionRequest",
    "PermissionDenied",
    "Notification",
    "SubagentStart",
    "SubagentStop",
    "Stop",
    "StopFailure",
)


@dataclass(frozen=True)
class HookToolPaths:
    tool: str
    config_dir: Path
    hooks_dir: Path
    config_file: Path
    script_path: Path
    hook_command: str


@dataclass
class HookToolResult:
    tool: str
    ok: bool
    message: str
    skipped: bool = False
    config_file: Path | None = None


def _wrapper_script(tool: str) -> str:
    data_home = f"$HOME/.{APP_SLUG}"
    return f"""#!/bin/bash
# Agent Light — relay {tool} hook events to traffic-light state signals.
set -euo pipefail

export AGENT_LIGHT_TOOL={tool}

PYTHON=""
if [[ -f "{data_home}/agent-hooks/python.txt" ]]; then
  PYTHON="$(tr -d '\\n' < "{data_home}/agent-hooks/python.txt")"
elif [[ -f "{data_home}/cursor-hooks/python.txt" ]]; then
  PYTHON="$(tr -d '\\n' < "{data_home}/cursor-hooks/python.txt")"
fi
if [[ -z "$PYTHON" || ! -x "$PYTHON" ]]; then
  for candidate in python3.12 python3.11 python3.10 python3.9 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      PYTHON="$(command -v "$candidate")"
      break
    fi
  done
fi
if [[ -z "$PYTHON" ]]; then
  echo '{{}}' >&1
  exit 0
fi
exec "$PYTHON" -m agent_light.agent_hooks.relay
"""


def _save_python_path(python_exe: str) -> None:
    HOOKS_ROOT.mkdir(parents=True, exist_ok=True)
    PYTHON_PATH_FILE.write_text(python_exe + "\n", encoding="utf-8")


def _write_script(path: Path, tool: str) -> None:
    path.write_text(_wrapper_script(tool), encoding="utf-8")
    path.chmod(0o755)


def _load_json(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except json.JSONDecodeError:
        backup = path.with_suffix(path.suffix + ".bak")
        shutil.copy2(path, backup)
        logger.warning("Backed up invalid %s to %s", path, backup)
        return {}


def _write_json(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _is_our_hook_command(command: object) -> bool:
    if not isinstance(command, str) or not command.strip():
        return False
    return any(name in command for name in OUR_SCRIPTS)


def _cursor_paths() -> HookToolPaths:
    config_dir = get_cursor_config_dir()
    hooks_dir = config_dir / "hooks"
    script_path = hooks_dir / CURSOR_SCRIPT
    return HookToolPaths(
        tool="cursor",
        config_dir=config_dir,
        hooks_dir=hooks_dir,
        config_file=config_dir / "hooks.json",
        script_path=script_path,
        hook_command=f"./hooks/{CURSOR_SCRIPT}",
    )


def _claude_paths() -> HookToolPaths:
    config_dir = get_claude_config_dir()
    hooks_dir = config_dir / "hooks"
    script_path = hooks_dir / CLAUDE_SCRIPT
    return HookToolPaths(
        tool="claude",
        config_dir=config_dir,
        hooks_dir=hooks_dir,
        config_file=config_dir / "settings.json",
        script_path=script_path,
        hook_command=str(script_path),
    )


def _codex_paths() -> HookToolPaths:
    config_dir = get_codex_home()
    hooks_dir = config_dir / "hooks"
    script_path = hooks_dir / CODEX_SCRIPT
    return HookToolPaths(
        tool="codex",
        config_dir=config_dir,
        hooks_dir=hooks_dir,
        config_file=config_dir / "hooks.json",
        script_path=script_path,
        hook_command=str(script_path),
    )


def _merge_cursor_hooks(config: dict, command: str) -> dict:
    hooks = config.setdefault("hooks", {})
    entry = {"command": command, "timeout": 5}
    for event in CURSOR_EVENTS:
        items = hooks.setdefault(event, [])
        if not any(isinstance(item, dict) and item.get("command") == command for item in items):
            items.append(dict(entry))
    config["version"] = 1
    return config


def _merge_claude_codex_hooks(config: dict, command: str, events: tuple[str, ...]) -> dict:
    hooks = config.setdefault("hooks", {})
    for event in events:
        groups = hooks.setdefault(event, [])
        if not any(
            isinstance(group, dict)
            and any(
                isinstance(h, dict) and h.get("command") == command
                for h in (group.get("hooks") or [])
            )
            for group in groups
        ):
            groups.append(
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": command, "timeout": 5}],
                }
            )
    return config


def _remove_cursor_hooks(config: dict) -> tuple[dict, bool]:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return config, False

    changed = False
    for event in list(hooks.keys()):
        items = hooks.get(event)
        if not isinstance(items, list):
            continue
        kept = [
            item
            for item in items
            if not (isinstance(item, dict) and _is_our_hook_command(item.get("command")))
        ]
        if len(kept) != len(items):
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    return config, changed


def _remove_claude_codex_hooks(config: dict) -> tuple[dict, bool]:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return config, False

    changed = False
    for event in list(hooks.keys()):
        groups = hooks.get(event)
        if not isinstance(groups, list):
            continue
        kept_groups: list[object] = []
        event_changed = False
        for group in groups:
            if not isinstance(group, dict):
                kept_groups.append(group)
                continue
            hook_list = group.get("hooks") or []
            if not isinstance(hook_list, list):
                kept_groups.append(group)
                continue
            kept_hooks = [
                hook
                for hook in hook_list
                if not (isinstance(hook, dict) and _is_our_hook_command(hook.get("command")))
            ]
            if len(kept_hooks) != len(hook_list):
                event_changed = True
            if kept_hooks:
                new_group = dict(group)
                new_group["hooks"] = kept_hooks
                kept_groups.append(new_group)
            elif hook_list:
                event_changed = True
        if event_changed or len(kept_groups) != len(groups):
            changed = True
            if kept_groups:
                hooks[event] = kept_groups
            else:
                del hooks[event]
    return config, changed


def _ensure_codex_hooks_feature(config_path: Path) -> None:
    if not config_path.is_file():
        config_path.write_text("[features]\nhooks = true\n", encoding="utf-8")
        return
    text = config_path.read_text(encoding="utf-8")
    if "[features]" not in text:
        text = text.rstrip() + "\n\n[features]\nhooks = true\n"
    elif "hooks" not in text:
        text = text.replace("[features]", "[features]\nhooks = true\n", 1)
    elif "hooks = false" in text:
        text = text.replace("hooks = false", "hooks = true")
    config_path.write_text(text, encoding="utf-8")


def _config_has_our_hooks(config: dict, layout: str) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False
    if layout == "cursor":
        for items in hooks.values():
            if isinstance(items, list) and any(
                isinstance(item, dict) and _is_our_hook_command(item.get("command")) for item in items
            ):
                return True
        return False
    for groups in hooks.values():
        if not isinstance(groups, list):
            continue
        for group in groups:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks") or []:
                if isinstance(hook, dict) and _is_our_hook_command(hook.get("command")):
                    return True
    return False


def _script_is_valid(path: Path) -> bool:
    if not path.is_file() or not path.stat().st_mode & 0o111:
        return False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return "agent_light.agent_hooks.relay" in text and "AGENT_LIGHT_TOOL" in text


def _cursor_hook_command_registered(config: dict, command: str) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event in CURSOR_EVENTS:
        items = hooks.get(event)
        if not isinstance(items, list):
            return False
        if not any(
            isinstance(item, dict) and item.get("command") == command for item in items
        ):
            return False
    return True


def _claude_codex_hook_command_registered(config: dict, command: str, events: tuple[str, ...]) -> bool:
    hooks = config.get("hooks")
    if not isinstance(hooks, dict):
        return False
    for event in events:
        groups = hooks.get(event)
        if not isinstance(groups, list):
            return False
        if not any(
            isinstance(group, dict)
            and any(
                isinstance(hook, dict) and hook.get("command") == command
                for hook in (group.get("hooks") or [])
            )
            for group in groups
        ):
            return False
    return True


def _audit_tool_hooks(paths: HookToolPaths, tool_key: str) -> tuple[bool, list[str]]:
    """Return (complete, issue_descriptions)."""
    issues: list[str] = []
    if not _script_is_valid(paths.script_path):
        if paths.script_path.is_file():
            issues.append("脚本不可执行或内容异常")
        else:
            issues.append("缺少 Hook 脚本")

    config = _load_json(paths.config_file)
    if tool_key == TOOL_CURSOR:
        if not _config_has_our_hooks(config, "cursor"):
            issues.append("hooks.json 未注册 Agent Light Hook")
        elif not _cursor_hook_command_registered(config, paths.hook_command):
            issues.append("hooks.json 事件注册不完整")
    else:
        if not _config_has_our_hooks(config, "claude"):
            issues.append("配置未注册 Agent Light Hook")
        elif not _claude_codex_hook_command_registered(config, paths.hook_command, CLAUDE_CODEX_EVENTS):
            issues.append("配置事件注册不完整")

    if tool_key == TOOL_CODEX:
        config_toml = paths.config_dir / "config.toml"
        if config_toml.is_file():
            text = config_toml.read_text(encoding="utf-8")
            if "hooks = false" in text:
                issues.append("Codex config.toml 中 hooks 未启用")
        # missing config.toml is fine; install will create/enable

    return not issues, issues


def _has_our_hooks_installed(paths: HookToolPaths, tool_key: str) -> bool:
    if paths.script_path.is_file():
        return True
    layout = "cursor" if tool_key == TOOL_CURSOR else "claude"
    config = _load_json(paths.config_file)
    return _config_has_our_hooks(config, layout)


def is_cursor_hooks_installed() -> bool:
    paths = _cursor_paths()
    complete, _ = _audit_tool_hooks(paths, TOOL_CURSOR)
    return complete


def is_claude_hooks_installed() -> bool:
    paths = _claude_paths()
    complete, _ = _audit_tool_hooks(paths, TOOL_CLAUDE)
    return complete


def is_codex_hooks_installed() -> bool:
    paths = _codex_paths()
    complete, _ = _audit_tool_hooks(paths, TOOL_CODEX)
    return complete


def is_cli_hooks_installed(tool_name: str) -> bool:
    if tool_name == "codex":
        return is_codex_hooks_installed()
    if tool_name == "claude-code":
        return is_claude_hooks_installed()
    return False


def is_all_hooks_installed() -> bool:
    available = get_available_tools()
    if not available:
        return True
    status = hooks_install_status()
    return all(status[tool] for tool in available)


def hooks_need_install() -> bool:
    available = get_available_tools()
    if not available:
        return False
    status = hooks_install_status()
    return any(not status[tool] for tool in available)


def hooks_install_status() -> dict[str, bool]:
    return {
        TOOL_CURSOR: is_cursor_hooks_installed(),
        TOOL_CLAUDE: is_claude_hooks_installed(),
        TOOL_CODEX: is_codex_hooks_installed(),
    }


def get_installed_hook_tools() -> list[str]:
    """Tools that currently have any Agent Light hook artifacts (for uninstall)."""
    installed: list[str] = []
    for tool_key, paths_fn in (
        (TOOL_CURSOR, _cursor_paths),
        (TOOL_CLAUDE, _claude_paths),
        (TOOL_CODEX, _codex_paths),
    ):
        if _has_our_hooks_installed(paths_fn(), tool_key):
            installed.append(tool_key)
    return installed


def install_cursor_hooks(python_exe: str | None = None) -> Path:
    python = python_exe or sys.executable
    _save_python_path(python)

    paths = _cursor_paths()
    paths.hooks_dir.mkdir(parents=True, exist_ok=True)
    _write_script(paths.script_path, "cursor")

    config = _load_json(paths.config_file) or {"version": 1, "hooks": {}}
    config = _merge_cursor_hooks(config, paths.hook_command)
    _write_json(paths.config_file, config)
    return paths.config_file


def install_claude_hooks(python_exe: str | None = None) -> Path:
    python = python_exe or sys.executable
    _save_python_path(python)

    paths = _claude_paths()
    paths.hooks_dir.mkdir(parents=True, exist_ok=True)
    _write_script(paths.script_path, "claude-code")

    config = _load_json(paths.config_file)
    config = _merge_claude_codex_hooks(config, paths.hook_command, CLAUDE_CODEX_EVENTS)
    _write_json(paths.config_file, config)
    return paths.config_file


def install_codex_hooks(python_exe: str | None = None) -> Path:
    python = python_exe or sys.executable
    _save_python_path(python)

    paths = _codex_paths()
    paths.hooks_dir.mkdir(parents=True, exist_ok=True)
    _write_script(paths.script_path, "codex")

    config = _load_json(paths.config_file)
    config = _merge_claude_codex_hooks(config, paths.hook_command, CLAUDE_CODEX_EVENTS)
    _write_json(paths.config_file, config)
    _ensure_codex_hooks_feature(paths.config_dir / "config.toml")
    return paths.config_file


def install_all_hooks(python_exe: str | None = None) -> dict[str, Path]:
    paths: dict[str, Path] = {}
    for result in install_all_hooks_detailed(python_exe):
        if result.config_file:
            paths[result.tool] = result.config_file
    return paths


def _install_tool(paths: HookToolPaths, python_exe: str, tool_key: str) -> HookToolResult:
    if not is_tool_available(tool_key):
        return HookToolResult(
            tool_key,
            True,
            f"未检测到该工具，已跳过（{paths.config_dir}）",
            skipped=True,
        )

    complete, issues = _audit_tool_hooks(paths, tool_key)
    if complete:
        return HookToolResult(
            tool_key,
            True,
            f"已安装且配置完整（{paths.config_dir}）",
            skipped=True,
            config_file=paths.config_file if paths.config_file.is_file() else None,
        )

    try:
        had_partial = _has_our_hooks_installed(paths, tool_key)
        if tool_key == TOOL_CURSOR:
            config_file = install_cursor_hooks(python_exe)
        elif tool_key == TOOL_CLAUDE:
            config_file = install_claude_hooks(python_exe)
        elif tool_key == TOOL_CODEX:
            config_file = install_codex_hooks(python_exe)
        else:
            return HookToolResult(tool_key, False, "未知工具")

        after_complete, remaining = _audit_tool_hooks(paths, tool_key)
        if not after_complete:
            detail = "、".join(remaining) if remaining else "配置不完整"
            return HookToolResult(tool_key, False, f"安装后校验失败：{detail}")

        if had_partial:
            issue_hint = f"（修复：{'、'.join(issues)}）" if issues else ""
            message = f"已修复并校验 → {config_file}{issue_hint}"
        else:
            message = f"已安装 → {config_file}"
        return HookToolResult(
            tool_key,
            True,
            message,
            config_file=config_file,
        )
    except OSError as exc:
        logger.exception("Failed to install %s hooks", tool_key)
        return HookToolResult(tool_key, False, f"安装失败: {exc}")


def _should_uninstall_tool(tool_key: str, paths: HookToolPaths) -> bool:
    return _has_our_hooks_installed(paths, tool_key)


def _uninstall_tool(paths: HookToolPaths, layout: str, tool_key: str) -> HookToolResult:
    if not _should_uninstall_tool(tool_key, paths):
        return HookToolResult(
            tool_key,
            True,
            "未检测到该工具，已跳过",
            skipped=True,
        )
    changed = False
    try:
        if paths.config_file.is_file():
            config = _load_json(paths.config_file)
            if layout == "cursor":
                config, config_changed = _remove_cursor_hooks(config)
            else:
                config, config_changed = _remove_claude_codex_hooks(config)
            if config_changed:
                _write_json(paths.config_file, config)
                changed = True

        if paths.script_path.is_file() and paths.script_path.name in OUR_SCRIPTS:
            paths.script_path.unlink()
            changed = True

        if changed:
            return HookToolResult(
                paths.tool,
                True,
                f"已移除 ({paths.config_dir})",
                config_file=paths.config_file if paths.config_file.is_file() else None,
            )
        return HookToolResult(paths.tool, True, f"未安装 ({paths.config_dir})")
    except OSError as exc:
        logger.exception("Failed to uninstall %s hooks", paths.tool)
        return HookToolResult(paths.tool, False, f"删除失败: {exc}")


def install_all_hooks_detailed(python_exe: str | None = None) -> list[HookToolResult]:
    from ..tool_paths import invalidate_tool_paths_cache

    invalidate_tool_paths_cache()
    python = python_exe or sys.executable
    return [
        _install_tool(_cursor_paths(), python, TOOL_CURSOR),
        _install_tool(_claude_paths(), python, TOOL_CLAUDE),
        _install_tool(_codex_paths(), python, TOOL_CODEX),
    ]


def uninstall_cursor_hooks() -> HookToolResult:
    return _uninstall_tool(_cursor_paths(), "cursor", TOOL_CURSOR)


def uninstall_claude_hooks() -> HookToolResult:
    return _uninstall_tool(_claude_paths(), "claude", TOOL_CLAUDE)


def uninstall_codex_hooks() -> HookToolResult:
    return _uninstall_tool(_codex_paths(), "codex", TOOL_CODEX)


def uninstall_all_hooks() -> list[HookToolResult]:
    from ..tool_paths import invalidate_tool_paths_cache

    invalidate_tool_paths_cache()
    return [
        uninstall_cursor_hooks(),
        uninstall_claude_hooks(),
        uninstall_codex_hooks(),
    ]


def format_hook_results(results: list[HookToolResult]) -> str:
    labels = {TOOL_CURSOR: "Cursor", TOOL_CLAUDE: "Claude Code", TOOL_CODEX: "Codex"}
    lines: list[str] = []
    for result in results:
        label = labels.get(result.tool, result.tool)
        if result.skipped:
            mark = "—"
        else:
            mark = "✓" if result.ok else "✗"
        lines.append(f"{mark} {label}: {result.message}")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Install or remove Agent Light agent hooks")
    parser.add_argument("--uninstall", action="store_true", help="Remove Agent Light hooks only")
    args = parser.parse_args()

    if args.uninstall:
        results = uninstall_all_hooks()
        print("Agent Light hooks removed:")
    else:
        results = install_all_hooks_detailed()
        print("✓ Agent Light hooks installed:")
    for line in format_hook_results(results).splitlines():
        print(f"  {line}")
    if not args.uninstall:
        available = get_available_tools()
        if available:
            print("  Restart installed tools, then run an agent task.")
        else:
            print("  No supported AI tools detected on this machine.")


if __name__ == "__main__":
    main()
