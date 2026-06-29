"""Persist hook-derived agent states under ~/.agent-light/agent-hooks/."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from ..models import LightState

from ..constants import HOOKS_ROOT as APP_HOOKS_ROOT

logger = logging.getLogger(__name__)

HOOKS_ROOT = APP_HOOKS_ROOT
LEGACY_CURSOR_ROOT = HOOKS_ROOT.parent / "cursor-hooks"
STATES_DIR = HOOKS_ROOT / "states"
PYTHON_PATH_FILE = HOOKS_ROOT / "python.txt"
LEGACY_PYTHON_PATH_FILE = LEGACY_CURSOR_ROOT / "python.txt"

RUNNING_TTL_SEC = 35.0
WAITING_TTL_SEC = 600.0
IDLE_TTL_SEC = 86400.0

VALID_TOOLS = frozenset({"cursor", "codex", "claude-code"})


def _path_to_slug(path: str) -> str:
    normalized = path.strip().rstrip("/")
    if normalized.startswith("/"):
        normalized = normalized[1:]
    return normalized.replace("/", "-")


def _normalize_workspace(path: str) -> str:
    text = path.strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return text


def workspace_keys(payload: dict[str, Any]) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        normalized = _normalize_workspace(raw)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        keys.append(normalized)

    for root in payload.get("workspace_roots") or []:
        if isinstance(root, str):
            add(root)

    cwd = payload.get("cwd")
    if isinstance(cwd, str):
        add(cwd)

    project_dir = payload.get("project_dir") or payload.get("projectDir")
    if isinstance(project_dir, str):
        add(project_dir)

    return keys


def _conversation_id_from_payload(payload: dict[str, Any]) -> str | None:
    raw = payload.get("conversation_id") or payload.get("conversationId")
    if not raw:
        return None
    text = str(raw).strip()
    return text or None


def _state_path(tool_name: str, workspace: str, conversation_id: str | None = None) -> Path:
    STATES_DIR.mkdir(parents=True, exist_ok=True)
    slug = _path_to_slug(workspace) or "unknown"
    if tool_name == "cursor" and conversation_id:
        safe_id = conversation_id.replace("/", "-")
        return STATES_DIR / f"{tool_name}-{slug}--{safe_id}.json"
    return STATES_DIR / f"{tool_name}-{slug}.json"


def write_signal(
    tool_name: str,
    payload: dict[str, Any],
    state: LightState,
    reason: str,
) -> None:
    if tool_name not in VALID_TOOLS:
        logger.debug("Unknown hook tool %s", tool_name)
        return

    keys = workspace_keys(payload)
    if not keys:
        logger.debug(
            "Hook signal ignored for %s: no workspace (%s)",
            tool_name,
            payload.get("hook_event_name"),
        )
        return

    record = {
        "tool_name": tool_name,
        "workspace": keys[0],
        "workspace_roots": keys,
        "conversation_id": _conversation_id_from_payload(payload),
        "session_id": payload.get("session_id") or payload.get("sessionId"),
        "hook_event": payload.get("hook_event_name") or payload.get("hookEventName"),
        "tool_event": payload.get("tool_name"),
        "state": state.value,
        "reason": reason,
        "updated_at": time.time(),
    }

    conversation_id = record["conversation_id"] if tool_name == "cursor" else None

    for workspace in keys:
        path = _state_path(tool_name, workspace, conversation_id)
        try:
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed to write hook state %s: %s", path, exc)


def _read_record(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _record_is_fresh(record: dict[str, Any]) -> bool:
    try:
        updated = float(record.get("updated_at", 0))
    except (TypeError, ValueError):
        return False

    age = time.time() - updated
    state = str(record.get("state") or "")

    if state == LightState.WAITING.value:
        return age <= WAITING_TTL_SEC
    if state == LightState.RUNNING.value:
        return age <= RUNNING_TTL_SEC
    if state == LightState.IDLE.value:
        return age <= IDLE_TTL_SEC
    return False


def _workspace_matches(instance_workspace: str, record: dict[str, Any]) -> bool:
    target = _normalize_workspace(instance_workspace)
    if not target:
        return False

    candidates = record.get("workspace_roots") or [record.get("workspace")]
    target_name = Path(target).name
    for item in candidates:
        if not isinstance(item, str):
            continue
        normalized = _normalize_workspace(item)
        if normalized == target:
            return True
        if Path(normalized).name == target_name:
            return True
    return False


def _iter_state_files(tool_name: str) -> list[Path]:
    files: list[Path] = []
    if STATES_DIR.is_dir():
        files.extend(STATES_DIR.glob(f"{tool_name}-*.json"))
    legacy = LEGACY_CURSOR_ROOT / "states"
    if tool_name == "cursor" and legacy.is_dir():
        files.extend(legacy.glob("*.json"))
    return files


def _state_priority(state: LightState) -> int:
    if state == LightState.WAITING:
        return 3
    if state == LightState.RUNNING:
        return 2
    return 1


def _record_to_state(record: dict[str, Any]) -> tuple[LightState, str, float] | None:
    if not _record_is_fresh(record):
        return None
    try:
        state = LightState(str(record.get("state")))
    except ValueError:
        return None
    reason = str(record.get("reason") or "hook")
    updated = float(record.get("updated_at", 0))
    return state, reason, updated


def _pick_best(
    candidates: list[tuple[LightState, str, float]],
) -> tuple[LightState | None, str]:
    if not candidates:
        return None, ""
    candidates.sort(key=lambda item: (_state_priority(item[0]), item[2]), reverse=True)
    state, reason, _ = candidates[0]
    return state, reason


def _lookup_conversation_state(
    tool_name: str,
    workspace: str,
    conversation_id: str,
) -> tuple[LightState | None, str]:
    path = _state_path(tool_name, workspace, conversation_id)
    record = _read_record(path)
    if not record:
        return None, ""
    parsed = _record_to_state(record)
    if parsed is None:
        return None, ""
    if not _workspace_matches(workspace, record):
        return None, ""
    state, reason, _ = parsed
    return state, reason


def _lookup_workspace_states(
    tool_name: str,
    workspace: str,
) -> tuple[LightState | None, str]:
    candidates: list[tuple[LightState, str, float]] = []

    for path in _iter_state_files(tool_name):
        record = _read_record(path)
        if not record:
            continue
        record_tool = str(record.get("tool_name") or ("cursor" if tool_name == "cursor" else ""))
        if record_tool and record_tool != tool_name:
            continue
        if not _workspace_matches(workspace, record):
            continue
        parsed = _record_to_state(record)
        if parsed is None:
            continue
        candidates.append(parsed)

    return _pick_best(candidates)


def _lookup_session_states(
    tool_name: str,
    workspace: str,
    session_id: str,
) -> tuple[LightState | None, str]:
    candidates: list[tuple[LightState, str, float]] = []
    target_session = session_id.strip()

    for path in _iter_state_files(tool_name):
        record = _read_record(path)
        if not record:
            continue
        record_tool = str(record.get("tool_name") or "")
        if record_tool and record_tool != tool_name:
            continue
        record_session = record.get("session_id") or record.get("sessionId")
        if not isinstance(record_session, str) or record_session.strip() != target_session:
            continue
        if not _workspace_matches(workspace, record):
            continue
        parsed = _record_to_state(record)
        if parsed is not None:
            candidates.append(parsed)

    return _pick_best(candidates)


def lookup_state(
    tool_name: str,
    workspace: str,
    window_key: str | None = None,
    session_id: str | None = None,
) -> tuple[LightState | None, str]:
    if tool_name not in VALID_TOOLS or not workspace or workspace == "Unknown":
        return None, ""

    if session_id and tool_name == "claude-code":
        state, reason = _lookup_session_states(tool_name, workspace, session_id)
        if state is not None:
            return state, reason

    if tool_name == "cursor" and window_key:
        from ..detector.cursor_window_conversations import recent_conversation_ids_for_window

        conversation_ids = recent_conversation_ids_for_window(str(window_key))
        if not conversation_ids:
            return None, ""

        allowed = set(conversation_ids)

        for conversation_id in conversation_ids:
            state, reason = _lookup_conversation_state(tool_name, workspace, conversation_id)
            if state is not None:
                return state, reason

        # Legacy files: workspace-level filename but conversation_id inside JSON.
        legacy_candidates: list[tuple[LightState, str, float]] = []
        for path in _iter_state_files(tool_name):
            record = _read_record(path)
            if not record:
                continue
            record_conv = record.get("conversation_id")
            if not isinstance(record_conv, str) or record_conv not in allowed:
                continue
            if not _workspace_matches(workspace, record):
                continue
            parsed = _record_to_state(record)
            if parsed is not None:
                legacy_candidates.append(parsed)

        return _pick_best(legacy_candidates)

    return _lookup_workspace_states(tool_name, workspace)
