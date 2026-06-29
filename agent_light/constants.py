"""Application-wide names and paths (no user-specific values)."""

from __future__ import annotations

from pathlib import Path

APP_DISPLAY_NAME = "Agent Light"
APP_SLUG = "agent-light"
APP_LOGGER_NAME = "agent-light"

APP_DATA_DIR = Path.home() / f".{APP_SLUG}"
LOG_DIR = APP_DATA_DIR / "logs"
LOG_FILE = LOG_DIR / f"{APP_SLUG}.log"
PID_FILE = APP_DATA_DIR / f"{APP_SLUG}.pid"
HOOKS_ROOT = APP_DATA_DIR / "agent-hooks"
