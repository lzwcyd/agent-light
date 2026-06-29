"""macOS Accessibility API helpers."""

from __future__ import annotations

import logging
from typing import Any

from ApplicationServices import (
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementPerformAction,
    kAXChildrenAttribute,
    kAXRoleAttribute,
    kAXTitleAttribute,
    kAXValueAttribute,
    kAXWindowsAttribute,
    kAXDescriptionAttribute,
    kAXIdentifierAttribute,
)

logger = logging.getLogger(__name__)


def _ax_value(element: Any, attr: str) -> Any:
    err, value = AXUIElementCopyAttributeValue(element, attr, None)
    if err != 0 or value is None:
        return None
    return value


def get_app_windows(pid: int) -> list[Any]:
    app = AXUIElementCreateApplication(pid)
    windows = _ax_value(app, kAXWindowsAttribute)
    if not windows:
        return []
    return list(windows)


def get_window_title(window: Any) -> str:
    title = _ax_value(window, kAXTitleAttribute)
    return str(title) if title else ""


def collect_text_from_element(element: Any, depth: int = 0, max_depth: int = 12) -> list[str]:
    """Recursively collect visible text from an accessibility element tree."""
    if depth > max_depth:
        return []

    texts: list[str] = []
    for attr in (kAXTitleAttribute, kAXValueAttribute, kAXDescriptionAttribute, kAXIdentifierAttribute):
        val = _ax_value(element, attr)
        if val and isinstance(val, str) and val.strip():
            texts.append(val.strip().lower())

    role = _ax_value(element, kAXRoleAttribute)
    if role:
        texts.append(str(role).lower())

    children = _ax_value(element, kAXChildrenAttribute)
    if children:
        for child in children:
            texts.extend(collect_text_from_element(child, depth + 1, max_depth))

    return texts


def collect_window_text(pid: int, window: Any) -> str:
    texts = collect_text_from_element(window)
    title = get_window_title(window)
    if title:
        texts.append(title.lower())
    return " ".join(texts)


def focus_window(pid: int, window: Any) -> bool:
    """Bring a specific window to the front."""
    try:
        from AppKit import NSApplicationActivateIgnoringOtherApps, NSRunningApplication

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app:
            app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            try:
                AXUIElementPerformAction(window, "AXRaise")
            except Exception:
                pass
            return True
    except Exception as exc:
        logger.debug("focus_window failed pid=%s: %s", pid, exc)
    return False


def focus_process(pid: int) -> bool:
    try:
        from AppKit import NSRunningApplication, NSApplicationActivateIgnoringOtherApps

        app = NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
        if app:
            return bool(app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps))
    except Exception as exc:
        logger.debug("focus_process failed pid=%s: %s", pid, exc)
    return False
