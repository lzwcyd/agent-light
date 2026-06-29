"""Scan running Cursor, Claude, Codex instances."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import psutil
from AppKit import NSRunningApplication, NSWorkspace

from ..models import MonitoredInstance
from .ax_api import get_app_windows, get_window_title
from .claude_desktop_sessions import match_session_for_window_title
from .workspace_resolver import resolve_workspace_path
from .cli_tool_scanner import scan_cli_instances

logger = logging.getLogger(__name__)

TOOL_CONFIGS = [
    {
        "tool_name": "cursor",
        "label": "Cursor",
        "bundle_ids": {"com.todesktop.230313mzl4w4u92"},
    },
    {
        "tool_name": "claude-desktop",
        "label": "Claude Desktop",
        "bundle_ids": {
            "com.anthropic.claudefordesktop",
            "com.anthropic.claude",
        },
    },
]

# extension-host (always-local|agent-exec|...) <workspace> [windowIndex-id]
CURSOR_HOST_RE = re.compile(
    r"extension-host\s+\([^)]+\)\s+(.+?)\s+\[(\d+)-",
    re.IGNORECASE,
)
CURSOR_RENDERER_RE = re.compile(r"--vscode-window-config=vscode:([a-f0-9-]+)")


def _short_title(title: str, max_len: int = 28) -> str:
    title = title.strip() or "Untitled"
    if len(title) <= max_len:
        return title
    return title[: max_len - 1] + "…"


def _parse_project_from_window_title(title: str) -> str:
    """Extract project folder name from Cursor window title."""
    title = title.strip()
    if not title:
        return "Untitled"
    title = re.sub(r"\s*[-–—]\s*Cursor\s*$", "", title, flags=re.IGNORECASE)
    for sep in (" — ", " - ", " – "):
        if sep in title:
            parts = [p.strip() for p in title.split(sep) if p.strip()]
            if len(parts) >= 2:
                return parts[-1]
    return title


def _cursor_display_name(project: str) -> str:
    return f"Cursor · {_short_title(project)}"


def _find_main_pid_for_bundle(bundle_id: str) -> int | None:
    apps = NSWorkspace.sharedWorkspace().runningApplications()
    for app in apps:
        if app.bundleIdentifier() == bundle_id and not app.isTerminated():
            return int(app.processIdentifier())
    return None


def _scan_cursor_via_extension_hosts(main_pid: int) -> list[MonitoredInstance]:
    """Detect Cursor windows via extension-host subprocess names."""
    windows: dict[str, dict[str, Any]] = {}

    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            cmdline = " ".join(proc.cmdline())
            if "Cursor Helper" not in cmdline or "extension-host" not in cmdline:
                continue

            match = CURSOR_HOST_RE.search(cmdline)
            if not match:
                continue

            workspace = match.group(1).strip()
            window_key = match.group(2)
            is_agent = "agent-exec" in cmdline.lower()

            entry = windows.setdefault(
                window_key,
                {"workspace": workspace, "pids": [], "agent_exec_pid": None},
            )
            entry["pids"].append(proc.info["pid"])
            if is_agent:
                entry["agent_exec_pid"] = proc.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    instances: list[MonitoredInstance] = []
    for window_key, info in sorted(windows.items()):
        label = info["workspace"]
        workspace = resolve_workspace_path(label, window_key)
        project = Path(workspace).name if workspace.startswith("/") else label
        instances.append(
            MonitoredInstance(
                instance_id=f"cursor-win-{window_key}",
                tool_name="cursor",
                display_name=_cursor_display_name(project),
                pid=main_pid,
                window_id=int(window_key) if window_key.isdigit() else None,
                bundle_id="com.todesktop.230313mzl4w4u92",
                extra={
                    "window_key": window_key,
                    "workspace": workspace,
                    "project": project,
                    "host_pids": info["pids"],
                    "agent_exec_pid": info["agent_exec_pid"],
                },
            )
        )
    return instances


def _scan_cursor_via_ax(main_pid: int) -> list[MonitoredInstance]:
    instances: list[MonitoredInstance] = []
    windows = get_app_windows(main_pid)
    for idx, window in enumerate(windows):
        raw_title = get_window_title(window) or f"Window {idx + 1}"
        label = _parse_project_from_window_title(raw_title)
        workspace = resolve_workspace_path(label)
        project = Path(workspace).name if workspace.startswith("/") else label
        instances.append(
            MonitoredInstance(
                instance_id=f"cursor-ax-{main_pid}-{idx}",
                tool_name="cursor",
                display_name=_cursor_display_name(project),
                pid=main_pid,
                window_id=idx,
                bundle_id="com.todesktop.230313mzl4w4u92",
                extra={
                    "window": window,
                    "window_title": raw_title,
                    "workspace": workspace,
                    "project": project,
                },
            )
        )
    return instances


def _scan_cursor() -> list[MonitoredInstance]:
    main_pid = _find_main_pid_for_bundle("com.todesktop.230313mzl4w4u92")
    if not main_pid:
        return []

    hosts = _scan_cursor_via_extension_hosts(main_pid)
    if hosts:
        ax_windows = get_app_windows(main_pid)
        for inst in hosts:
            project = str(inst.extra.get("project") or "")
            matched_window = None
            matched_title = ""
            if project and ax_windows:
                project_lower = project.lower()
                for window in ax_windows:
                    title = get_window_title(window) or ""
                    if project_lower in title.lower():
                        matched_window = window
                        matched_title = title
                        break
            if matched_window is not None:
                inst.extra["window"] = matched_window
                inst.extra["window_title"] = matched_title
                title_label = _parse_project_from_window_title(matched_title)
                resolved = resolve_workspace_path(
                    title_label,
                    str(inst.extra.get("window_key")),
                )
                if resolved.startswith("/"):
                    inst.extra["workspace"] = resolved
                    inst.extra["project"] = Path(resolved).name
                    inst.display_name = _cursor_display_name(inst.extra["project"])
        return hosts

    ax = _scan_cursor_via_ax(main_pid)
    if ax:
        return ax

    return [
        MonitoredInstance(
            instance_id=f"cursor-{main_pid}",
            tool_name="cursor",
            display_name="Cursor · Unknown",
            pid=main_pid,
            bundle_id="com.todesktop.230313mzl4w4u92",
            extra={"project": "Unknown"},
        )
    ]


def _claude_desktop_display_name(title: str, cwd: str) -> str:
    if cwd:
        folder = Path(cwd).name or title
        return f"Claude Desktop · {_short_title(folder)}"
    return f"Claude Desktop · {_short_title(title)}"


def _scan_gui_tool(config: dict[str, Any]) -> list[MonitoredInstance]:
    instances: list[MonitoredInstance] = []
    for bundle_id in config["bundle_ids"]:
        pid = _find_main_pid_for_bundle(bundle_id)
        if not pid:
            continue
        windows = get_app_windows(pid)
        if windows:
            for idx, window in enumerate(windows):
                title = get_window_title(window) or f"Window {idx + 1}"
                extra: dict[str, Any] = {
                    "window": window,
                    "window_title": title,
                }
                display_name = f"{config['label']} · {_short_title(title)}"

                if config["tool_name"] == "claude-desktop":
                    session = match_session_for_window_title(title)
                    cwd = session.cwd if session else ""
                    if cwd:
                        extra["cwd"] = cwd
                        extra["workspace"] = cwd
                        extra["project"] = Path(cwd).name
                        extra["coding_session"] = True
                    if session:
                        extra["session_id"] = session.session_id
                        extra["cli_session_id"] = session.cli_session_id
                        extra["session_title"] = session.title
                    display_name = _claude_desktop_display_name(title, cwd)

                instances.append(
                    MonitoredInstance(
                        instance_id=f"{config['tool_name']}-ax-{pid}-{idx}",
                        tool_name=config["tool_name"],
                        display_name=display_name,
                        pid=pid,
                        window_id=idx,
                        bundle_id=bundle_id,
                        extra=extra,
                    )
                )
        else:
            instances.append(
                MonitoredInstance(
                    instance_id=f"{config['tool_name']}-{pid}",
                    tool_name=config["tool_name"],
                    display_name=config["label"],
                    pid=pid,
                    bundle_id=bundle_id,
                )
            )
    return instances


def scan_instances() -> list[MonitoredInstance]:
    all_instances: list[MonitoredInstance] = []
    all_instances.extend(_scan_cursor())

    for config in TOOL_CONFIGS:
        if config["tool_name"] != "cursor":
            all_instances.extend(_scan_gui_tool(config))

    all_instances.extend(scan_cli_instances())

    seen: set[str] = set()
    unique: list[MonitoredInstance] = []
    for inst in all_instances:
        if inst.instance_id not in seen:
            seen.add(inst.instance_id)
            unique.append(inst)

    logger.debug("scan_instances → %d instance(s): %s", len(unique), [i.display_name for i in unique])
    return unique
