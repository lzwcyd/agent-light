from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class LightState(str, Enum):
    RUNNING = "running"       # 红灯 - 模型正在工作
    WAITING = "waiting"       # 黄灯 - 需要人工确认
    IDLE = "idle"             # 绿灯 - 工作结束/空闲


@dataclass
class MonitoredInstance:
    """A single monitorable AI tool instance (one window or one process)."""

    instance_id: str
    tool_name: str          # cursor | claude | codex
    display_name: str       # e.g. "Cursor · agent-light"
    pid: int
    window_id: int | None = None
    bundle_id: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    state: LightState = LightState.IDLE
    state_reason: str = ""

    def focus_key(self) -> tuple[Any, ...]:
        return (self.tool_name, self.pid, self.window_id, self.instance_id)
