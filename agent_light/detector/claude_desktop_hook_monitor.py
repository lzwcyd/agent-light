"""Read Claude Desktop coding-mode state via shared Claude Code hooks."""

from __future__ import annotations

import logging

from ..models import LightState
from .cli_hook_monitor import analyze_cli_hooks
from .cli_session_monitor import analyze_cli_session

logger = logging.getLogger(__name__)


def analyze_claude_desktop_hooks(
    cwd: str,
    session_id: str | None = None,
) -> tuple[LightState | None, str]:
    if not cwd:
        return None, ""

    hook_state, hook_reason = analyze_cli_hooks("claude-code", cwd, session_id=session_id)
    if hook_state is not None:
        logger.debug(
            "Claude Desktop hook state for %s (session=%s) → %s (%s)",
            cwd,
            session_id or "-",
            hook_state.value,
            hook_reason,
        )
        return hook_state, hook_reason

    session_state, session_reason = analyze_cli_session("claude-code", cwd)
    if session_state is not None:
        logger.debug(
            "Claude Desktop session fallback for %s → %s (%s)",
            cwd,
            session_state.value,
            session_reason,
        )
        return session_state, session_reason

    return None, ""
