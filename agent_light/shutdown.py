"""Graceful shutdown helpers and PID file management."""

from __future__ import annotations

import logging
import os
import signal
import sys
from typing import Callable, Optional

from .constants import APP_DATA_DIR, PID_FILE

logger = logging.getLogger(__name__)

PID_DIR = APP_DATA_DIR
SHUTDOWN_FLAG = PID_DIR / "shutdown.request"

_delegate_getter: Optional[Callable[[], object]] = None


def write_pid() -> None:
    PID_DIR.mkdir(parents=True, exist_ok=True)
    SHUTDOWN_FLAG.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()))
    logger.info("PID file written: %s (pid=%d)", PID_FILE, os.getpid())


def remove_pid() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text().strip() == str(os.getpid()):
            PID_FILE.unlink()
            logger.info("PID file removed")
    except OSError as exc:
        logger.warning("Failed to remove PID file: %s", exc)


_shutdown_callback = None


def register_shutdown(callback) -> None:
    global _shutdown_callback
    _shutdown_callback = callback


def register_delegate_getter(getter: Callable[[], object]) -> None:
    global _delegate_getter
    _delegate_getter = getter


def install_signal_handlers() -> None:
    def _handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info("Received signal %s — scheduling shutdown on main thread", sig_name)
        try:
            from PyObjCTools.AppHelper import callAfter
            delegate = _delegate_getter() if _delegate_getter else None
            if delegate is not None:
                callAfter(delegate.performShutdown_, f"signal:{sig_name}")
            elif _shutdown_callback:
                callAfter(_shutdown_callback, f"signal:{sig_name}")
            else:
                callAfter(sys.exit, 0)
        except Exception as exc:
            logger.error("Signal handler failed: %s — forcing exit", exc)
            os._exit(0)

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


def consume_shutdown_flag() -> bool:
    """Return True if an external stop was requested."""
    try:
        if SHUTDOWN_FLAG.exists():
            SHUTDOWN_FLAG.unlink(missing_ok=True)
            logger.info("Shutdown flag consumed")
            return True
    except OSError as exc:
        logger.warning("Failed to read shutdown flag: %s", exc)
    return False
