"""FreeCleaner launcher.

`app.py` is safe for source runs, but on Windows it immediately hands off to
`pythonw app.pyw` unless debugging is requested.  This prevents the visible
PowerShell/console noise that made startup look like several broken launches.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


_INTERNAL_RELAUNCH_FLAGS = {"--elevated-relaunch", "--freecleaner-elevated-relaunch"}
_WAS_ELEVATED_RELAUNCH = any(arg in _INTERNAL_RELAUNCH_FLAGS for arg in sys.argv[1:])
if _WAS_ELEVATED_RELAUNCH:
    os.environ["FREECLEANER_ELEVATED_RELAUNCH"] = "1"
    sys.argv[:] = [sys.argv[0], *[arg for arg in sys.argv[1:] if arg not in _INTERNAL_RELAUNCH_FLAGS]]


def _hidden_creationflags() -> int:
    if os.name != "nt":
        return 0
    return int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)) | int(getattr(subprocess, "DETACHED_PROCESS", 0x00000008))


def _detach_from_console() -> None:
    """Detach this tiny launcher from an inherited console before pythonw handoff.

    When users start `python app.py` from PowerShell the parent terminal itself
    will remain, but this prevents FreeCleaner from writing startup noise to it
    while the real GUI process is spawned through pythonw.
    """
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.kernel32.FreeConsole()
    except Exception:
        pass


def _maybe_relaunch_pythonw() -> None:
    if os.name != "nt":
        return
    if os.environ.get("FREECLEANER_DEBUG_CONSOLE") == "1" or os.environ.get("FREECLEANER_BOOTSTRAPPED") == "1":
        return
    exe = Path(sys.executable)
    if exe.name.lower() not in {"python.exe", "python3.exe"}:
        return
    pythonw = exe.with_name("pythonw.exe")
    if not pythonw.is_file():
        return
    script = Path(__file__).with_name("app.pyw")
    env = os.environ.copy()
    env["FREECLEANER_BOOTSTRAPPED"] = "1"
    try:
        _detach_from_console()
        subprocess.Popen(
            [str(pythonw), str(script), *sys.argv[1:]],
            cwd=str(Path(__file__).resolve().parent),
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=_hidden_creationflags(),
        )
        raise SystemExit(0)
    except SystemExit:
        raise
    except Exception:
        # Fall back to in-process launch; logs will still capture stderr/stdout.
        return


_maybe_relaunch_pythonw()

from freecleaner.runtime_logging import setup_runtime_logging, log_startup, StreamToLog  # noqa: E402

_MUTEX_HANDLE = None

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
log_startup("launcher imported before Qt")
sys.stdout = StreamToLog(sys.__stdout__, level="INFO", target="app", echo=False)
sys.stderr = StreamToLog(sys.__stderr__, level="ERROR", target="startup", echo=False)

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from freecleaner.qt_bootstrap import main  # noqa: E402


if __name__ == "__main__":
    log_startup("entering qt bootstrap main")
    raise SystemExit(main())
