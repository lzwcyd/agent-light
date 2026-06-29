"""Logging setup with 1 MB rotating file handler."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .constants import APP_LOGGER_NAME, LOG_DIR, LOG_FILE
MAX_BYTES = 1 * 1024 * 1024  # 1 MB
BACKUP_COUNT = 2

_configured = False
_quiet_mode = False


def is_quiet_mode() -> bool:
    return _quiet_mode


def setup_logging(level: int = logging.INFO, *, quiet: bool = False) -> Path | None:
    global _configured, _quiet_mode
    _quiet_mode = quiet

    root = logging.getLogger()
    if _configured:
        return None if quiet else LOG_FILE

    if quiet:
        root.handlers.clear()
        root.addHandler(logging.NullHandler())
        root.setLevel(logging.CRITICAL + 1)
        logging.disable(logging.CRITICAL)
        _configured = True
        return None

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root.handlers.clear()
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(fmt)
    file_handler.setLevel(level)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(fmt)
    console_handler.setLevel(level)

    root.addHandler(file_handler)
    root.addHandler(console_handler)

    _configured = True
    logging.getLogger(APP_LOGGER_NAME).info(
        "Logging initialized → %s (max %d MB)", LOG_FILE, MAX_BYTES // (1024 * 1024)
    )
    return LOG_FILE
