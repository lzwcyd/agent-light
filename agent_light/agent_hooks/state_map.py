"""Shared agent hook state mapping for Cursor, Claude Code, and Codex."""

from __future__ import annotations

import re
from typing import Any

from ..models import LightState

_RUNNING_EVENTS = frozenset(
    {
        "sessionStart",
        "beforeSubmitPrompt",
        "userPromptSubmit",
        "preToolUse",
        "postToolUse",
        "afterShellExecution",
        "afterMCPExecution",
        "afterFileEdit",
        "afterAgentThought",
        "subagentStart",
        "subagentStop",
    }
)

_WAITING_EVENTS = frozenset(
    {
        "beforeShellExecution",
        "beforeMCPExecution",
        "permissionRequest",
        "permissionDenied",
        "notification",
        "stopFailure",
    }
)

_IDLE_EVENTS = frozenset(
    {
        "sessionEnd",
        "afterAgentResponse",
    }
)

_PASCAL_TO_CANONICAL = {
    "SessionStart": "sessionStart",
    "SessionEnd": "sessionEnd",
    "UserPromptSubmit": "userPromptSubmit",
    "BeforeSubmitPrompt": "beforeSubmitPrompt",
    "PreToolUse": "preToolUse",
    "PostToolUse": "postToolUse",
    "PostToolUseFailure": "postToolUseFailure",
    "BeforeShellExecution": "beforeShellExecution",
    "AfterShellExecution": "afterShellExecution",
    "BeforeMCPExecution": "beforeMCPExecution",
    "AfterMCPExecution": "afterMCPExecution",
    "PermissionRequest": "permissionRequest",
    "PermissionDenied": "permissionDenied",
    "Notification": "notification",
    "AfterAgentThought": "afterAgentThought",
    "AfterAgentResponse": "afterAgentResponse",
    "SubagentStart": "subagentStart",
    "SubagentStop": "subagentStop",
    "Stop": "stop",
    "StopFailure": "stopFailure",
}

_USER_INTERRUPT_STATUSES = frozenset({"aborted", "interrupted", "cancelled", "canceled"})
_USER_INTERRUPT_REASONS = frozenset({"aborted", "interrupted", "user_close", "window_close"})

_USER_INTERRUPT_TEXT_RE = re.compile(
    r"(?:conversation\s+interrupted|user\s+(?:cancel(?:led)?|abort(?:ed)?|interrupt(?:ed)?))",
    re.IGNORECASE,
)


def normalize_hook_event(event: str) -> str:
    event = (event or "").strip()
    if not event:
        return ""
    if event in _PASCAL_TO_CANONICAL:
        return _PASCAL_TO_CANONICAL[event]
    if event[0].islower():
        return event
    return _PASCAL_TO_CANONICAL.get(event, event[0].lower() + event[1:])


def _tool_name(payload: dict[str, Any]) -> str:
    name = payload.get("tool_name")
    return str(name) if name else ""


def _is_question_tool(tool: str) -> bool:
    return tool in ("AskQuestion", "AskUserQuestion", "ExitPlanMode")


def _text_blob(payload: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "last_assistant_message",
        "lastAssistantMessage",
        "error_message",
        "error",
        "reason",
        "stopReason",
        "systemMessage",
        "message",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value)
    error_details = payload.get("error_details") or payload.get("errorDetails")
    if isinstance(error_details, dict):
        for value in error_details.values():
            if isinstance(value, str) and value.strip():
                parts.append(value)
    return "\n".join(parts)


def _payload_indicates_user_interrupt(payload: dict[str, Any]) -> bool:
    """User cancelled / stopped the agent — treat as ended (green)."""
    if payload.get("is_interrupt") or payload.get("isInterrupt"):
        return True
    status = str(payload.get("status") or "").lower()
    if status in _USER_INTERRUPT_STATUSES:
        return True
    reason = str(payload.get("reason") or "").lower()
    if reason in _USER_INTERRUPT_REASONS:
        return True
    return bool(_USER_INTERRUPT_TEXT_RE.search(_text_blob(payload)))


def _map_stop_event(payload: dict[str, Any]) -> tuple[LightState, str]:
    if _payload_indicates_user_interrupt(payload):
        return LightState.IDLE, "hook: stop (user interrupted)"

    status = str(payload.get("status") or "").lower()
    if status in ("error",):
        return LightState.WAITING, f"hook: stop ({status})"

    return LightState.IDLE, f"hook: stop ({status or 'completed'})"


def map_hook_event(event: str, payload: dict[str, Any]) -> tuple[LightState | None, str]:
    event = normalize_hook_event(event or str(payload.get("hook_event_name") or ""))
    if not event:
        return None, ""

    tool = _tool_name(payload)

    if event == "preToolUse" and _is_question_tool(tool):
        return LightState.WAITING, f"hook: {tool}"

    if event in _WAITING_EVENTS:
        label = tool or event.replace("permission", "").replace("Request", "approval")
        return LightState.WAITING, f"hook: {event} ({label or 'approval'})"

    if event == "postToolUseFailure":
        if payload.get("is_interrupt") or payload.get("isInterrupt"):
            return LightState.IDLE, "hook: user interrupted"
        failure = str(payload.get("failure_type") or payload.get("failureType") or "")
        if failure in ("permission_denied", "permissionDenied"):
            return LightState.WAITING, "hook: permission denied"
        return LightState.RUNNING, f"hook: tool failure ({failure or 'error'})"

    if event in ("stop", "subagentStop"):
        return _map_stop_event(payload)

    if event == "sessionEnd":
        reason = str(payload.get("reason") or "ended")
        return LightState.IDLE, f"hook: sessionEnd ({reason})"

    if event == "afterAgentResponse":
        return LightState.IDLE, "hook: agent response done"

    if event in _RUNNING_EVENTS:
        detail = tool or str(payload.get("subagent_type") or payload.get("subagentType") or "").strip()
        suffix = f" ({detail})" if detail else ""
        return LightState.RUNNING, f"hook: {event}{suffix}"

    if event in _IDLE_EVENTS:
        return LightState.IDLE, f"hook: {event}"

    return None, ""
