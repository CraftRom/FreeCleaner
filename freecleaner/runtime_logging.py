"""Runtime logging helpers for FreeCleaner.

Qt-free and safe to import from the launcher before PySide6.  Logs are recreated
on every process start under the same user-data root as config, update cache and
registry backups.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import tempfile
import threading
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Optional

APP_NAME = "FreeCleaner"
LOGS_DIRNAME = "logs"
STARTUP_LOG_FILENAME = "startup.log"
APP_LOG_FILENAME = "app.log"
ERROR_LOG_FILENAME = "errors.log"
ACTIONS_LOG_FILENAME = "actions.log"
SECURITY_LOG_FILENAME = "security.log"
SYSTEM_LOG_FILENAME = "system.log"
QA_LOG_FILENAME = "qa.log"

_INITIALIZED = False
_LOG_PATHS: Dict[str, str] = {}
_LOCK = threading.RLock()
_STDIO_ECHO = os.environ.get("FREECLEANER_LOG_ECHO_STDIO") == "1"
_SYSTEM_RESPONSE_MAX_CHARS = int(os.environ.get("FREECLEANER_SYSTEM_LOG_MAX_CHARS", "262144") or "262144")
_SESSION_ID = os.environ.get("FREECLEANER_SESSION_ID") or uuid.uuid4().hex[:12]


def get_user_data_dir(create: bool = True) -> str:
    candidates = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if local:
            candidates.append(os.path.join(local, APP_NAME))
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            candidates.append(os.path.join(xdg, APP_NAME))
        home = os.path.expanduser("~")
        if home and home != "~":
            candidates.append(os.path.join(home, f".{APP_NAME.lower()}"))
    candidates.append(os.path.join(tempfile.gettempdir(), APP_NAME))
    for path in candidates:
        try:
            path = os.path.abspath(path)
            if create:
                os.makedirs(path, exist_ok=True)
            return path
        except Exception:
            continue
    return os.path.abspath(tempfile.gettempdir())


def get_logs_dir(create: bool = True) -> str:
    path = os.path.join(get_user_data_dir(create=create), LOGS_DIRNAME)
    if create:
        os.makedirs(path, exist_ok=True)
    return path


def _default_path(name: str) -> str:
    return os.path.join(get_logs_dir(True), name)


def startup_log_path() -> str:
    return _LOG_PATHS.get("startup") or _default_path(STARTUP_LOG_FILENAME)


def app_log_path() -> str:
    return _LOG_PATHS.get("app") or _default_path(APP_LOG_FILENAME)


def error_log_path() -> str:
    return _LOG_PATHS.get("errors") or _default_path(ERROR_LOG_FILENAME)


def actions_log_path() -> str:
    return _LOG_PATHS.get("actions") or _default_path(ACTIONS_LOG_FILENAME)


def security_log_path() -> str:
    return _LOG_PATHS.get("security") or _default_path(SECURITY_LOG_FILENAME)


def system_log_path() -> str:
    return _LOG_PATHS.get("system") or _default_path(SYSTEM_LOG_FILENAME)


def qa_log_path() -> str:
    return _LOG_PATHS.get("qa") or _default_path(QA_LOG_FILENAME)


def all_log_paths() -> Dict[str, str]:
    return {
        "startup": startup_log_path(),
        "app": app_log_path(),
        "errors": error_log_path(),
        "actions": actions_log_path(),
        "security": security_log_path(),
        "system": system_log_path(),
        "qa": qa_log_path(),
    }


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def _sanitize(message: Any, *, max_chars: Optional[int] = 12000) -> str:
    text = str(message if message is not None else "")
    # Keep logs useful but prevent multi-megabyte subprocess output from freezing UI.
    if max_chars is not None and max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars] + f"… [truncated at {max_chars} chars]"
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _write(path: str, line: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with _LOCK:
            with open(path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(line.rstrip("\n") + "\n")
    except Exception:
        pass


def _log(target: str, message: Any, *, level: str = "INFO") -> None:
    path = all_log_paths().get(target, app_log_path())
    max_chars = None if target == "system" else (60000 if target == "qa" else 12000)
    text = _sanitize(message, max_chars=max_chars)
    for line in text.split("\n") or [""]:
        if line.strip():
            _write(path, f"{_stamp()} [{level.upper()}] {line}")


def log_startup(message: Any, *, level: str = "INFO") -> None:
    _log("startup", message, level=level)


def log_app(message: Any, *, level: str = "INFO") -> None:
    _log("app", message, level=level)


def log_error(message: Any, *, level: str = "ERROR") -> None:
    _log("errors", message, level=level)
    _log("app", message, level=level)


def log_action(message: Any, *, level: str = "INFO") -> None:
    _log("actions", message, level=level)
    _log("app", f"action: {message}", level=level)


def log_security(message: Any, *, level: str = "INFO") -> None:
    _log("security", message, level=level)
    _log("app", f"security: {message}", level=level)


def log_system(message: Any, *, level: str = "INFO") -> None:
    _log("system", message, level=level)


def log_qa(message: Any, *, level: str = "INFO") -> None:
    _log("qa", message, level=level)


def _json_default(value: Any) -> str:
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def _safe_json(data: Dict[str, Any], *, max_chars: Optional[int] = None) -> str:
    try:
        text = json.dumps(data, ensure_ascii=False, default=_json_default, sort_keys=True)
    except Exception:
        text = str(data)
    return _sanitize(text, max_chars=max_chars)


def log_system_response(
    source: str,
    *,
    command: Any = None,
    returncode: Any = None,
    stdout: Any = "",
    stderr: Any = "",
    elapsed_ms: Any = None,
    timeout: Any = None,
    cwd: Any = None,
    context: Optional[Dict[str, Any]] = None,
    level: str = "INFO",
) -> None:
    """Write a QA-grade raw system response entry.

    This is intentionally separate from app.log/actions.log: app.log stays human
    readable, system.log captures raw command/registry/powercfg responses for
    later debugging. Output is capped by FREECLEANER_SYSTEM_LOG_MAX_CHARS to keep
    the UI responsive on very noisy systems.
    """
    payload = {
        "session_id": _SESSION_ID,
        "source": source,
        "command": command,
        "returncode": returncode,
        "elapsed_ms": elapsed_ms,
        "timeout": timeout,
        "cwd": cwd,
        "context": context or {},
        "stdout": _sanitize(stdout, max_chars=_SYSTEM_RESPONSE_MAX_CHARS),
        "stderr": _sanitize(stderr, max_chars=_SYSTEM_RESPONSE_MAX_CHARS),
    }
    log_system(_safe_json(payload, max_chars=None), level=level)


def log_qa_event(event: str, **fields: Any) -> None:
    payload = {"session_id": _SESSION_ID, "event": event, **fields}
    log_qa(_safe_json(payload, max_chars=60000))


def setup_runtime_logging(*, reset: bool = True) -> None:
    global _INITIALIZED, _LOG_PATHS
    logs = get_logs_dir(True)
    _LOG_PATHS = {
        "startup": os.path.join(logs, STARTUP_LOG_FILENAME),
        "app": os.path.join(logs, APP_LOG_FILENAME),
        "errors": os.path.join(logs, ERROR_LOG_FILENAME),
        "actions": os.path.join(logs, ACTIONS_LOG_FILENAME),
        "security": os.path.join(logs, SECURITY_LOG_FILENAME),
        "system": os.path.join(logs, SYSTEM_LOG_FILENAME),
        "qa": os.path.join(logs, QA_LOG_FILENAME),
    }
    if reset:
        for path in _LOG_PATHS.values():
            try:
                with open(path, "w", encoding="utf-8", errors="replace") as fh:
                    fh.write("")
            except Exception:
                pass
    logging.getLogger().handlers.clear()
    logging.getLogger().setLevel(logging.INFO)
    try:
        handler = logging.FileHandler(_LOG_PATHS["app"], encoding="utf-8", mode="a")
        handler.setFormatter(logging.Formatter("%(asctime)s.%(msecs)03d [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"))
        logging.getLogger().addHandler(handler)
    except Exception:
        pass
    _INITIALIZED = True
    install_exception_hooks()
    log_startup(f"Logging initialized: logs_dir={logs} session={_SESSION_ID}")
    log_startup(f"Python={sys.version.split()[0]} exe={sys.executable}")
    log_system_response(
        "runtime.startup",
        command="process_start",
        returncode="started",
        stdout={
            "session_id": _SESSION_ID,
            "pid": os.getpid(),
            "python": sys.version,
            "executable": sys.executable,
            "argv": sys.argv,
            "platform": platform.platform(),
            "cwd": os.getcwd(),
            "logs": _LOG_PATHS,
            "env_flags": {
                key: os.environ.get(key)
                for key in sorted(os.environ)
                if key.startswith("FREECLEANER_") or key.startswith("QT_")
            },
        },
        context={"phase": "startup"},
    )
    log_startup(f"Platform={platform.platform()} frozen={bool(getattr(sys, 'frozen', False))}")
    log_app(f"Application log initialized: {APP_NAME}")
    log_security("runtime logging ready; logs reset for this session")
    log_qa_event("runtime_logging_ready", logs=all_log_paths(), pid=os.getpid(), thread=threading.current_thread().name)


def install_exception_hooks() -> None:
    def excepthook(exc_type: type[BaseException], exc: BaseException, tb: Any) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log_startup(text, level="ERROR")
        log_error(text)
        try:
            if _STDIO_ECHO:
                sys.__excepthook__(exc_type, exc, tb)
        except Exception:
            pass

    sys.excepthook = excepthook

    if hasattr(threading, "excepthook"):
        def thread_hook(args: Any) -> None:
            text = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
            log_startup(f"Thread {getattr(args, 'thread', None)} failed:\n{text}", level="ERROR")
            log_error(f"Thread {getattr(args, 'thread', None)} failed:\n{text}")
        threading.excepthook = thread_hook  # type: ignore[assignment]


class StreamToLog:
    def __init__(self, stream: Any = None, level: str = "INFO", target: str = "app", *, echo: Optional[bool] = None) -> None:
        self.stream = stream
        self.level = level
        self.target = target
        self.echo = _STDIO_ECHO if echo is None else bool(echo)
        self._buffer = ""

    def _emit(self, line: str) -> None:
        if not line.strip():
            return
        if self.target == "startup":
            log_startup(line, level=self.level)
        elif self.target == "errors":
            log_error(line, level=self.level)
        elif self.target == "actions":
            log_action(line, level=self.level)
        elif self.target == "security":
            log_security(line, level=self.level)
        elif self.target == "system":
            log_system(line, level=self.level)
        elif self.target == "qa":
            log_qa(line, level=self.level)
        else:
            log_app(line, level=self.level)

    def write(self, data: str) -> int:
        if self.echo and self.stream:
            try:
                self.stream.write(data)
            except Exception:
                pass
        self._buffer += str(data)
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)
        return len(data)

    def flush(self) -> None:
        try:
            if self._buffer.strip():
                self._emit(self._buffer)
            self._buffer = ""
        except Exception:
            pass
        if self.echo and self.stream:
            try:
                self.stream.flush()
            except Exception:
                pass
