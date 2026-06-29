"""Bring monitored AI tool instances to the foreground."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .detector.ax_api import focus_process, focus_window, get_app_windows, get_window_title
from .models import MonitoredInstance

logger = logging.getLogger(__name__)

CURSOR_BUNDLE_ID = "com.todesktop.230313mzl4w4u92"


def _escape_applescript(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _match_terms(instance: MonitoredInstance) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        terms.append(text)

    # Window title is more specific than folder name — try it first.
    window_title = instance.extra.get("window_title")
    if isinstance(window_title, str):
        add(window_title)

    for key in ("project",):
        value = instance.extra.get(key)
        if isinstance(value, str):
            add(value)

    workspace = instance.extra.get("workspace")
    if isinstance(workspace, str):
        if workspace.startswith("/"):
            add(Path(workspace).name)
        else:
            add(workspace)

    if " · " in instance.display_name:
        add(instance.display_name.split(" · ")[-1])

    cwd = instance.extra.get("cwd")
    if isinstance(cwd, str) and cwd:
        add(Path(cwd).name)

    terms.sort(key=len, reverse=True)
    return terms


def _find_cursor_window(pid: int, terms: list[str]):
    if not terms:
        return None
    lowered = [term.lower() for term in terms]
    for window in get_app_windows(pid):
        title = (get_window_title(window) or "").lower()
        if any(term in title for term in lowered):
            return window
    return None


def _activate_bundle(bundle_id: str) -> bool:
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        app = NSRunningApplication.runningApplicationWithBundleIdentifier_(bundle_id)
        if app and not app.isTerminated():
            return bool(
                app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            )
    except Exception as exc:
        logger.debug("activate bundle failed %s: %s", bundle_id, exc)
    return False


def _run_applescript(script: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=8,
        )
        output = (result.stdout or "").strip()
        ok = result.returncode == 0 and output != "NOT FOUND"
        if not ok and result.stderr.strip():
            logger.debug("AppleScript stderr: %s", result.stderr.strip())
        return ok, output
    except Exception as exc:
        logger.debug("AppleScript failed: %s", exc)
        return False, ""


def _focus_cursor_via_applescript(terms: list[str]) -> bool:
    for term in terms:
        escaped = _escape_applescript(term)
        script = f'''
        tell application "Cursor" to activate
        delay 0.05
        tell application "System Events"
            tell process "Cursor"
                set frontmost to true
                repeat with w in windows
                    if name of w contains "{escaped}" then
                        perform action "AXRaise" of w
                        try
                            click w
                        end try
                        return name of w
                    end if
                end repeat
            end tell
        end tell
        return "NOT FOUND"
        '''
        ok, matched = _run_applescript(script)
        if ok and matched:
            logger.info("Focused Cursor window via AppleScript: %s", matched)
            return True
    return False


def focus_cursor_instance(instance: MonitoredInstance) -> bool:
    terms = _match_terms(instance)
    pid = instance.pid or _find_cursor_pid()

    # AppleScript via osascript works from menu-bar/accessory apps; in-process AX often does not.
    if _focus_cursor_via_applescript(terms):
        return True

    window = instance.extra.get("window")
    if window is not None and pid:
        if focus_window(pid, window):
            logger.info("Focused Cursor AX window for %s", instance.display_name)
            return True

    if pid:
        matched = _find_cursor_window(pid, terms)
        if matched is not None and focus_window(pid, matched):
            logger.info("Focused Cursor window for %s", instance.display_name)
            return True

    if pid and focus_process(pid):
        logger.info("Focused Cursor app for %s", instance.display_name)
        return True

    return _activate_bundle(CURSOR_BUNDLE_ID)


def _focus_iterm_session(folder_name: str, tty: str) -> bool:
    escaped_folder = _escape_applescript(folder_name)
    script = f'''
    tell application "iTerm" to activate
    delay 0.05
    tell application "iTerm"
        repeat with w in windows
            repeat with t in tabs of w
                repeat with s in sessions of t
                    try
                        set sName to name of s
                        if sName contains "{escaped_folder}" then
                            select s
                            return "ok"
                        end if
                    end try
                end repeat
            end repeat
        end repeat
    end tell
    return "NOT FOUND"
    '''
    ok, _ = _run_applescript(script)
    return ok


def _focus_terminal_app(app_name: str) -> bool:
    ok, _ = _run_applescript(
        f'tell application "{app_name}" to activate\ndelay 0.05\nreturn "ok"'
    )
    return ok


def focus_cli_instance(instance: MonitoredInstance) -> bool:
    terminal_name = str(instance.extra.get("terminal_name") or "Terminal")
    app_name = "iTerm" if "iterm" in terminal_name.lower() else "Terminal"
    folder = ""
    cwd = instance.extra.get("cwd")
    if isinstance(cwd, str) and cwd:
        folder = Path(cwd).name

    tty = str(instance.extra.get("tty") or "")

    if app_name == "iTerm" and folder and _focus_iterm_session(folder, tty):
        logger.info("Focused iTerm session for %s", instance.display_name)
        return True

    if _focus_terminal_app(app_name):
        logger.info("Focused %s for %s", app_name, instance.display_name)
        return True

    terminal_pid = instance.extra.get("terminal_pid")
    if terminal_pid and focus_process(int(terminal_pid)):
        logger.info("Focused terminal pid %s for %s", terminal_pid, instance.display_name)
        return True

    shell_pid = instance.extra.get("shell_pid")
    if shell_pid and focus_process(int(shell_pid)):
        return True

    return focus_process(instance.pid)


def focus_gui_instance(instance: MonitoredInstance) -> bool:
    if instance.bundle_id and _activate_bundle(instance.bundle_id):
        return True

    window = instance.extra.get("window")
    if window is not None and focus_window(instance.pid, window):
        return True

    windows = get_app_windows(instance.pid)
    idx = instance.window_id
    if windows and idx is not None and 0 <= idx < len(windows):
        return focus_window(instance.pid, windows[idx])

    return focus_process(instance.pid)


def _resolve_instance(instance: MonitoredInstance) -> MonitoredInstance:
    try:
        from .detector.process_scanner import scan_instances

        for fresh in scan_instances():
            if fresh.instance_id == instance.instance_id:
                return fresh
    except Exception as exc:
        logger.debug("Failed to refresh instance before focus: %s", exc)
    return instance


def focus_instance(instance: MonitoredInstance) -> None:
    target = _resolve_instance(instance)
    logger.info("Focus requested: %s", target.display_name)
    try:
        if target.tool_name == "cursor":
            ok = focus_cursor_instance(target)
        elif target.tool_name in ("codex", "claude-code"):
            ok = focus_cli_instance(target)
        else:
            ok = focus_gui_instance(target)
        logger.info("Focus result for %s: %s", target.display_name, ok)
    except Exception:
        logger.exception("Failed to focus %s", target.display_name)


def _find_cursor_pid() -> int:
    from AppKit import NSWorkspace

    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == CURSOR_BUNDLE_ID:
            return int(app.processIdentifier())
    return 0
