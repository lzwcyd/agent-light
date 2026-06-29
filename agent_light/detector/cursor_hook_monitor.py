"""Read Cursor agent state from hook signals."""

from __future__ import annotations

import logging

from ..agent_hooks.store import lookup_state
from ..models import LightState

logger = logging.getLogger(__name__)


def analyze_cursor_hooks(workspace: str, window_key: str | None = None) -> tuple[LightState | None, str]:
    state, reason = lookup_state("cursor", workspace, window_key=window_key)
    if state is not None:
        logger.debug(
            "Hook state for cursor %s (window=%s) → %s (%s)",
            workspace,
            window_key or "-",
            state.value,
            reason,
        )
    return state, reason
