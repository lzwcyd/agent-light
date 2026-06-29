"""Read Claude Code / Codex state from hook signals."""

from __future__ import annotations

import logging

from ..agent_hooks.store import lookup_state
from ..models import LightState

logger = logging.getLogger(__name__)


def analyze_cli_hooks(
    tool_name: str,
    cwd: str,
    session_id: str | None = None,
) -> tuple[LightState | None, str]:
    if tool_name not in ("codex", "claude-code") or not cwd:
        return None, ""

    state, reason = lookup_state(tool_name, cwd, session_id=session_id)
    if state is not None:
        logger.debug("Hook state for %s %s → %s (%s)", tool_name, cwd, state.value, reason)
    return state, reason
