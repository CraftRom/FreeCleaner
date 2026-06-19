"""Windowed FreeCleaner launcher for Windows source runs and packaged builds."""

from __future__ import annotations

import os
import sys

from freecleaner.runtime_logging import setup_runtime_logging, log_startup, StreamToLog

_MUTEX_HANDLE = None

_INTERNAL_RELAUNCH_FLAGS = {"--elevated-relaunch", "--freecleaner-elevated-relaunch"}
_WAS_ELEVATED_RELAUNCH = any(arg in _INTERNAL_RELAUNCH_FLAGS for arg in sys.argv[1:])
if _WAS_ELEVATED_RELAUNCH:
    os.environ["FREECLEANER_ELEVATED_RELAUNCH"] = "1"
    sys.argv[:] = [sys.argv[0], *[arg for arg in sys.argv[1:] if arg not in _INTERNAL_RELAUNCH_FLAGS]]

def _acquire_single_instance() -> bool:
    """Return False when another FreeCleaner GUI process is already running."""
    global _MUTEX_HANDLE
    if (
        os.name != "nt"
        or os.environ.get("FREECLEANER_ALLOW_MULTI_INSTANCE") == "1"
        or os.environ.get("FREECLEANER_ELEVATED_RELAUNCH") == "1"
        or _WAS_ELEVATED_RELAUNCH
    ):
        return True
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.CreateMutexW(None, False, "Local\\FreeCleaner.Qt.SingleInstance")
        if handle and kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            return False
        _MUTEX_HANDLE = handle
    except Exception:
        return True
    return True


setup_runtime_logging(reset=True)
if not _acquire_single_instance():
    log_startup("another FreeCleaner instance is already running; startup cancelled")
    raise SystemExit(0)
log_startup("windowed launcher imported before Qt")
sys.stdout = StreamToLog(sys.__stdout__, level="INFO", target="app", echo=False)
sys.stderr = StreamToLog(sys.__stderr__, level="ERROR", target="startup", echo=False)

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("FREECLEANER_BOOTSTRAPPED", "1")

from freecleaner.qt_bootstrap import main


if __name__ == "__main__":
    log_startup("entering qt bootstrap main")
    raise SystemExit(main())
