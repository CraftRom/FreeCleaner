"""Core logic layer: paths, versioning, i18n, and safe cleanup operations.

This module must NOT contain UI widget creation code.
"""

from __future__ import annotations

import os
import sys
import ctypes
import ctypes.wintypes
import threading
import subprocess
import shutil
import stat
import time
import tempfile
import urllib.request
import urllib.parse
import urllib.error
import webbrowser
import shlex
try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore
import concurrent.futures
import queue
import json
import locale
import re
import configparser
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Dict, List, Tuple, Union, Set

from .default_lang_packs import DEFAULT_LANG_PACKS
from .runtime_logging import log_app, log_error, log_action, log_security, log_system_response, log_qa_event


APP_NAME = "FreeCleaner"
VERSION_INFO_FILENAME = "version_info.txt"
LANG_DIRNAME = "lang"
ICONS_DIRNAME = os.path.join("assets", "icons")
REGISTRY_BACKUP_DIRNAME = "registry_backups"
UPDATES_DIRNAME = "updates"
LOGS_DIRNAME = "logs"
GITHUB_API_BASE = "https://api.github.com"
APP_UPDATE_OWNER = os.environ.get("FREECLEANER_UPDATE_OWNER", "CraftRom").strip() or "CraftRom"
APP_UPDATE_REPO = os.environ.get("FREECLEANER_UPDATE_REPO", "FreeCleaner").strip() or "FreeCleaner"
APP_UPDATE_REPO_URL = f"https://github.com/{APP_UPDATE_OWNER}/{APP_UPDATE_REPO}"
APP_UPDATE_RELEASES_URL = f"{APP_UPDATE_REPO_URL}/releases"
APP_UPDATE_LATEST_RELEASE_URL = f"{APP_UPDATE_RELEASES_URL}/latest"


@dataclass
class UpdateInfo:
    owner: str
    repo: str
    tag_name: str
    name: str
    body: str
    html_url: str
    download_url: str
    asset_name: str
    published_at: str
    version_text: str
    version_tuple: Tuple[int, ...]
    changelog: str = ""
    changelog_count: int = 0




# -------------------------
# Assets (icons)
# -------------------------

def _iter_icon_candidates(filename: str) -> List[str]:
    """Return icon candidates *only* within assets/icons (runtime first, then bundle)."""
    filename = filename.replace("/", os.sep).replace("\\", os.sep)
    runtime = os.path.join(get_runtime_base_dir(), ICONS_DIRNAME, filename)
    bundle = os.path.join(get_bundle_base_dir(), ICONS_DIRNAME, filename)
    # Keep order deterministic
    return [runtime] if runtime == bundle else [runtime, bundle]


def find_icon_path(filename: str) -> Optional[str]:
    """Find an icon file in assets/icons (runtime first, then bundle)."""
    for path in _iter_icon_candidates(filename):
        try:
            if path and os.path.isfile(path):
                return path
        except Exception:
            continue
    return None

IS_WINDOWS = os.name == "nt"


def get_windows_version() -> Tuple[int, int, int]:
    """Return a reliable Windows version tuple: (major, minor, build)."""
    if not IS_WINDOWS:
        return (0, 0, 0)

    class _OSVERSIONINFOEXW(ctypes.Structure):
        _fields_ = [
            ("dwOSVersionInfoSize", ctypes.c_ulong),
            ("dwMajorVersion", ctypes.c_ulong),
            ("dwMinorVersion", ctypes.c_ulong),
            ("dwBuildNumber", ctypes.c_ulong),
            ("dwPlatformId", ctypes.c_ulong),
            ("szCSDVersion", ctypes.c_wchar * 128),
            ("wServicePackMajor", ctypes.c_ushort),
            ("wServicePackMinor", ctypes.c_ushort),
            ("wSuiteMask", ctypes.c_ushort),
            ("wProductType", ctypes.c_byte),
            ("wReserved", ctypes.c_byte),
        ]

    try:
        info = _OSVERSIONINFOEXW()
        info.dwOSVersionInfoSize = ctypes.sizeof(info)
        status = ctypes.windll.ntdll.RtlGetVersion(ctypes.byref(info))
        if status == 0:
            return (int(info.dwMajorVersion), int(info.dwMinorVersion), int(info.dwBuildNumber))
    except Exception:
        pass

    try:
        v = sys.getwindowsversion()  # type: ignore[attr-defined]
        return (int(v.major), int(v.minor), int(v.build))
    except Exception:
        return (0, 0, 0)


WINDOWS_VERSION = get_windows_version()


def _is_64bit_windows() -> bool:
    """Return True when the installed Windows OS is 64-bit.

    A 32-bit Python process can run on 64-bit Windows through WOW64, so
    pointer size alone is not enough here.
    """
    if not IS_WINDOWS:
        return sys.maxsize > 2**32
    if sys.maxsize > 2**32:
        return True
    try:
        is_wow64 = ctypes.c_bool(False)
        kernel32 = ctypes.windll.kernel32
        fn = getattr(kernel32, "IsWow64Process", None)
        if fn and fn(kernel32.GetCurrentProcess(), ctypes.byref(is_wow64)):
            return bool(is_wow64.value)
    except Exception:
        pass
    return False


def get_process_architecture() -> str:
    return "x64" if sys.maxsize > 2**32 else "x86"


def get_os_architecture() -> str:
    return "x64" if _is_64bit_windows() else "x86"


def is_32bit_process_on_64bit_windows() -> bool:
    return IS_WINDOWS and get_process_architecture() == "x86" and get_os_architecture() == "x64"


PROCESS_ARCHITECTURE = get_process_architecture()
OS_ARCHITECTURE = get_os_architecture()
IS_64BIT_WINDOWS = OS_ARCHITECTURE == "x64"
IS_WOW64_PROCESS = is_32bit_process_on_64bit_windows()


def get_update_asset_suffix() -> str:
    """Return the release asset suffix that matches the current Windows OS."""
    return "win64" if get_os_architecture() == "x64" else "win32"


def _asset_name_matches_update_arch(asset_name: str, suffix: Optional[str] = None) -> bool:
    name = (asset_name or "").strip().lower()
    wanted = (suffix or get_update_asset_suffix()).lower()
    return name.startswith(f"{APP_NAME.lower()}-") and name.endswith(f"-{wanted}-setup.exe")


def _asset_name_is_compatible_fallback(asset_name: str) -> bool:
    # The Qt/PySide6 build is x64-only.  Keep this helper for older update
    # metadata, but do not select win32 assets on modern releases.
    return False


def is_update_asset_compatible(asset_name: str) -> bool:
    """Return True if the release asset can be installed on this machine."""
    name = (asset_name or "").strip().lower()
    if not name.endswith("-setup.exe"):
        return False
    if get_os_architecture() == "x64":
        return name.endswith("-win64-setup.exe")
    return False


def is_windows_at_least(major: int, minor: int = 0, build: int = 0) -> bool:
    return IS_WINDOWS and WINDOWS_VERSION >= (major, minor, build)


CPU_COUNT = max(1, os.cpu_count() or 4)
# Conservative fallbacks used when adaptive probing is unavailable.
SCAN_WORKERS = max(1, min(CPU_COUNT, max(1, CPU_COUNT // 2)))
CLEAN_WORKERS = max(1, CPU_COUNT - 2) if CPU_COUNT > 2 else 1


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def _filetime_to_int(filetime: Any) -> int:
    return (int(filetime.dwHighDateTime) << 32) + int(filetime.dwLowDateTime)


def _get_windows_cpu_times() -> Optional[Tuple[int, int]]:
    """Return (idle, total) CPU ticks using WinAPI, compatible with Win7+."""
    if not IS_WINDOWS:
        return None
    try:
        idle = ctypes.wintypes.FILETIME()
        kernel = ctypes.wintypes.FILETIME()
        user = ctypes.wintypes.FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None
        idle_i = _filetime_to_int(idle)
        kernel_i = _filetime_to_int(kernel)
        user_i = _filetime_to_int(user)
        return idle_i, kernel_i + user_i
    except Exception:
        return None


def get_memory_load_percent() -> Optional[float]:
    """Return current RAM load percent without external dependencies."""
    if not IS_WINDOWS:
        return None
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return float(stat.dwMemoryLoad)
    except Exception:
        pass
    return None


class AdaptiveThreadManager:
    """Adaptive worker selector for scan/clean operations.

    - scan starts around half of logical CPUs because it is mostly disk-bound;
    - clean starts at all logical CPUs minus two to keep the UI/system responsive;
    - both modes back off when CPU/RAM load is high.
    """

    def __init__(self, cpu_count: Optional[int] = None):
        self.cpu_count = max(1, int(cpu_count or CPU_COUNT or 1))
        self._last_cpu_sample = _get_windows_cpu_times()
        self._last_sample_at = time.time()
        self._last_cpu_load = None  # type: Optional[float]
        self._last_memory_load = get_memory_load_percent()
        self._last_workers = {"scan": SCAN_WORKERS, "clean": CLEAN_WORKERS}

    def sample_cpu_load(self) -> Optional[float]:
        current = _get_windows_cpu_times()
        if not current:
            return self._last_cpu_load
        previous = self._last_cpu_sample
        self._last_cpu_sample = current
        self._last_sample_at = time.time()
        if not previous:
            return self._last_cpu_load

        idle_delta = current[0] - previous[0]
        total_delta = current[1] - previous[1]
        if total_delta <= 0:
            return self._last_cpu_load
        load = 100.0 * (1.0 - (float(idle_delta) / float(total_delta)))
        load = max(0.0, min(100.0, load))
        self._last_cpu_load = load
        return load

    def sample_memory_load(self) -> Optional[float]:
        load = get_memory_load_percent()
        if load is not None:
            self._last_memory_load = load
        return self._last_memory_load

    def base_workers(self, mode: str) -> int:
        if mode == "clean":
            return max(1, self.cpu_count - 2) if self.cpu_count > 2 else 1
        return max(1, self.cpu_count // 2)

    def choose_workers(self, mode: str, pending_items: int = 0) -> int:
        mode = "clean" if mode == "clean" else "scan"
        base = self.base_workers(mode)
        cpu = self.sample_cpu_load()
        mem = self.sample_memory_load()
        workers = base

        if cpu is not None:
            if cpu >= 92.0:
                workers = max(1, workers // 3)
            elif cpu >= 80.0:
                workers = max(1, workers // 2)
            elif cpu >= 65.0:
                workers = max(1, workers - 1)
            elif cpu <= 35.0 and (mem is None or mem < 75.0):
                limit = self.cpu_count if mode == "clean" else max(1, (self.cpu_count + 1) // 2)
                workers = min(limit, workers + 1)

        if mem is not None:
            if mem >= 92.0:
                workers = 1
            elif mem >= 85.0:
                workers = max(1, workers // 2)
            elif mem >= 75.0:
                workers = max(1, workers - 1)

        if mode == "clean" and self.cpu_count > 2:
            workers = min(workers, self.cpu_count - 2)
        if mode == "scan":
            workers = min(workers, max(1, (self.cpu_count + 1) // 2))

        if pending_items:
            workers = min(workers, max(1, pending_items))
        workers = max(1, int(workers))
        self._last_workers[mode] = workers
        return workers

    def status_text(self, mode: str) -> str:
        cpu = self._last_cpu_load
        mem = self._last_memory_load
        parts = ["adaptive", "mode=%s" % ("clean" if mode == "clean" else "scan")]
        if cpu is not None:
            parts.append("cpu=%.0f%%" % cpu)
        if mem is not None:
            parts.append("ram=%.0f%%" % mem)
        return ", ".join(parts)


ADAPTIVE_THREADS = AdaptiveThreadManager()


def get_adaptive_workers(mode: str, pending_items: int = 0) -> int:
    return ADAPTIVE_THREADS.choose_workers(mode, pending_items)


def get_adaptive_thread_status(mode: str) -> str:
    return ADAPTIVE_THREADS.status_text(mode)


# -------------------------
# Runtime paths / config
# -------------------------

def get_runtime_base_dir() -> str:
    """Base directory for application files.

    This is the install/source directory. It can be read-only when FreeCleaner
    is installed under Program Files, so mutable runtime data must not be
    written here. Use get_user_data_dir() for config, backups and updates.
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)

    # When running from sources, __file__ points to freecleaner/logic.py.
    # We want config/lang/assets next to the entry script.
    try:
        entry = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ""
        if entry and os.path.isfile(entry):
            return os.path.dirname(entry)
    except Exception:
        pass

    return os.getcwd()


def get_user_data_dir(create: bool = True) -> str:
    """Return a per-user writable directory for mutable FreeCleaner data.

    Windows blocks normal users from writing to Program Files. Update downloads,
    config files and registry backups therefore live in %LOCALAPPDATA%\\FreeCleaner
    instead of the installation directory. If that path is unavailable, fall
    back to the system temp directory rather than failing the action.
    """
    candidates: List[str] = []

    if IS_WINDOWS:
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


def get_bundle_base_dir() -> str:
    """Base directory for bundled resources.

    - For PyInstaller: sys._MEIPASS
    - For source runs: same as runtime base dir (keeps lookups consistent)
    """
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_runtime_base_dir()



LEGACY_CONFIG_PATH = os.path.join(get_runtime_base_dir(), "config.json")
CONFIG_PATH = os.path.join(get_user_data_dir(create=True), "config.json")

# -------------------------
# Version info (single source of truth)
# -------------------------

def _format_version_display(raw: str) -> str:
    """Make a friendly display string for title/UI.

    Examples:
      - "6.3.1.0" -> "v6.3.1"
      - "1.0.0.0" -> "v1.0.0"
      - "v6.3.1 Pro" -> "v6.3.1 Pro" (kept as-is)
    """
    raw = (raw or "").strip()
    if not raw:
        return "v0.0.0"
    if raw.lower().startswith("v"):
        return raw
    m = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:\.(\d+))?", raw)
    if not m:
        return raw
    a, b, c, d = m.group(1), m.group(2), m.group(3), m.group(4)
    if d is None or d == "0":
        return f"v{a}.{b}.{c}"
    return f"v{a}.{b}.{c}.{d}"


_VERSION_RE = re.compile(
    r"(?ix)"
    r"(?:^|[^0-9])"
    r"v?"
    r"(?P<base>\d+(?:\.\d+){0,3})"
    r"(?:\s*(?:-|_|\+|\.)?\s*build\s*(?:-|_|\.)?\s*(?P<build>\d+))?"
)


def extract_version_text(raw: str) -> str:
    """Return the best version token found in a release tag/name/asset string."""
    text = (raw or "").strip()
    if not text:
        return "0.0.0.0"
    best = None
    for match in _VERSION_RE.finditer(text):
        candidate = match.group(0).strip(" -_+.")
        if not candidate:
            continue
        has_build = bool(match.group("build"))
        parts_count = len((match.group("base") or "").split("."))
        score = (100 if has_build else 0) + parts_count
        if best is None or score > best[0]:
            best = (score, candidate)
    return best[1] if best else text


def normalize_version_tuple(raw: str) -> Tuple[int, ...]:
    """Normalize app/release versions into a comparable tuple.

    Supports all formats used by FreeCleaner releases and CI artifacts:
      - v1.2
      - 1.2.0.0
      - FreeCleaner 1.2.0.0-build-23
      - FreeCleaner-1.2.0.0-build-23-win64-setup.exe
    The returned tuple is always (major, minor, patch, revision, build).
    """
    text = extract_version_text(raw)
    match = _VERSION_RE.search(text)
    if not match:
        return (0, 0, 0, 0, 0)

    base_parts: List[int] = []
    for segment in (match.group("base") or "0").split("."):
        try:
            base_parts.append(max(0, int(segment)))
        except Exception:
            base_parts.append(0)
    while len(base_parts) < 4:
        base_parts.append(0)
    base_parts = base_parts[:4]
    try:
        build = max(0, int(match.group("build") or 0))
    except Exception:
        build = 0
    return tuple(base_parts + [build])


def compare_versions(left: str, right: str) -> int:
    a = list(normalize_version_tuple(left))
    b = list(normalize_version_tuple(right))
    size = max(len(a), len(b))
    a.extend([0] * (size - len(a)))
    b.extend([0] * (size - len(b)))
    if tuple(a) < tuple(b):
        return -1
    if tuple(a) > tuple(b):
        return 1
    return 0


def _release_version_text(tag_name: str, name: str) -> str:
    """Prefer full release title version over short tag when it contains build metadata."""
    tag = (tag_name or "").strip()
    title = (name or "").strip()
    candidates = [title, tag]
    best_text = tag or title or "0.0.0.0"
    best_tuple = normalize_version_tuple(best_text)
    best_score = -1
    for candidate in candidates:
        if not candidate:
            continue
        version = extract_version_text(candidate)
        vt = normalize_version_tuple(version)
        has_build = vt[-1] > 0 or bool(re.search(r"(?i)build", candidate))
        score = (100 if has_build else 0) + sum(1 for part in vt[:4] if part != 0)
        if score > best_score:
            best_score = score
            best_text = version
            best_tuple = vt
    return best_text or ".".join(str(x) for x in best_tuple[:4])


def _github_api_request(url: str, timeout: int = 12) -> Optional[Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}-UpdateChecker/{APP_VERSION_RAW if 'APP_VERSION_RAW' in globals() else '0'}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )
    try:
        started = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
            status_code = getattr(response, "status", None) or getattr(response, "code", None)
            log_system_response(
                "http.response",
                command={"method": "GET", "url": url},
                returncode=status_code,
                elapsed_ms=int((time.perf_counter() - started) * 1000),
                timeout=timeout,
                context={"update_check": True},
            )
            return payload if isinstance(payload, (dict, list)) else None
    except Exception as exc:
        log_system_response(
            "http.update_check_failed",
            command={"method": "GET", "url": url},
            returncode="exception",
            stderr=str(exc),
            timeout=timeout,
            context={"update_check": True},
            level="WARNING",
        )
        return None


def _short_release_body(body: str, *, max_lines: int = 10, max_chars: int = 1400) -> str:
    """Return a readable user-facing release note excerpt."""
    text = str(body or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    text = re.sub(r"(?s)```.*?```", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    lines: List[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        line = re.sub(r"^[-*+]\s+", "• ", line).strip()
        line = re.sub(r"^\d+[.)]\s+", "• ", line).strip()
        line = re.sub(r"\s+", " ", line).strip()
        if line:
            lines.append(line)
        if len(lines) >= max_lines:
            break
    result = "\n".join(lines).strip()
    if len(result) > max_chars:
        result = result[: max_chars - 1].rstrip() + "…"
    return result


def _build_recent_release_changelog(releases: Any, *, limit: int = 5) -> Tuple[str, int]:
    """Build a changelog from the latest release tags returned by GitHub."""
    if not isinstance(releases, list):
        return "", 0
    entries: List[str] = []
    for release in releases:
        if not isinstance(release, dict):
            continue
        if release.get("draft"):
            continue
        tag = str(release.get("tag_name") or "").strip()
        name = str(release.get("name") or tag or "FreeCleaner").strip()
        published = str(release.get("published_at") or release.get("created_at") or "").strip()[:10]
        version = _release_version_text(tag, name)
        title = name if name else version
        if version and version not in title:
            title = f"{title} ({version})"
        if published:
            title = f"{title} • {published}"
        body = _short_release_body(str(release.get("body") or "").strip())
        if body:
            entries.append(f"{title}\n{body}")
        else:
            entries.append(f"{title}\n• Покращення стабільності та зручності FreeCleaner.")
        if len(entries) >= limit:
            break
    return "\n\n".join(entries).strip(), len(entries)


def fetch_recent_github_releases(owner: str = APP_UPDATE_OWNER, repo: str = APP_UPDATE_REPO, limit: int = 5, timeout: int = 12) -> List[Dict[str, Any]]:
    owner = (owner or APP_UPDATE_OWNER).strip()
    repo = (repo or APP_UPDATE_REPO).strip()
    if not owner or not repo:
        return []
    safe_limit = max(1, min(10, int(limit or 5)))
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases?per_page={safe_limit}"
    payload = _github_api_request(url, timeout=timeout)
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _select_release_asset(assets: Any) -> Tuple[str, str]:
    """Return (download_url, asset_name) for the best installer asset."""
    if not isinstance(assets, list):
        return "", ""

    best: Tuple[int, str, str] = (-1, "", "")
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        candidate = str(asset.get("browser_download_url") or "").strip()
        raw_name = str(asset.get("name") or "").strip()
        if not candidate or not raw_name:
            continue
        name = raw_name.lower()
        if not name.endswith((".exe", ".msi")):
            continue
        if not is_update_asset_compatible(raw_name):
            continue
        score = 10
        if name.endswith("-setup.exe"):
            score += 80
        if name.endswith(f"-{get_update_asset_suffix()}-setup.exe"):
            score += 60
        if APP_NAME.lower() in name:
            score += 20
        if score > best[0]:
            best = (score, candidate, raw_name)
    return best[1], best[2]


def fetch_latest_github_release(owner: str = APP_UPDATE_OWNER, repo: str = APP_UPDATE_REPO, timeout: int = 12) -> Optional[UpdateInfo]:
    owner = (owner or APP_UPDATE_OWNER).strip()
    repo = (repo or APP_UPDATE_REPO).strip()
    if not owner or not repo:
        return None

    latest_url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases/latest"
    payload = _github_api_request(latest_url, timeout=timeout)
    if not isinstance(payload, dict):
        return None

    recent_releases = fetch_recent_github_releases(owner, repo, limit=5, timeout=timeout)
    changelog, changelog_count = _build_recent_release_changelog(recent_releases, limit=5)

    tag_name = str(payload.get("tag_name") or "").strip()
    name = str(payload.get("name") or tag_name or f"{owner}/{repo}").strip()
    body = str(payload.get("body") or "").strip()
    html_url = str(payload.get("html_url") or f"https://github.com/{owner}/{repo}/releases/latest").strip()
    published_at = str(payload.get("published_at") or payload.get("created_at") or "").strip()

    download_url, selected_asset_name = _select_release_asset(payload.get("assets"))
    if not download_url:
        download_url = html_url
        selected_asset_name = ""

    version_text = _release_version_text(tag_name, name)
    info = UpdateInfo(
        owner=owner,
        repo=repo,
        tag_name=tag_name or name,
        name=name,
        body=changelog or body,
        html_url=html_url,
        download_url=download_url,
        asset_name=selected_asset_name,
        published_at=published_at,
        version_text=version_text,
        version_tuple=normalize_version_tuple(version_text),
        changelog=changelog,
        changelog_count=changelog_count,
    )
    log_action({
        "update_release": f"{owner}/{repo}",
        "tag": info.tag_name,
        "name": info.name,
        "version": info.version_text,
        "asset": info.asset_name,
        "url": info.html_url,
        "changelog_releases": info.changelog_count,
    })
    return info


def get_default_download_dir() -> str:
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        return downloads
    return get_runtime_base_dir()


def get_updates_dir(create: bool = True) -> str:
    """Return a per-user writable update cache directory.

    Do not write update installers next to the executable. Installed copies often
    live in Program Files, where non-admin users cannot create .part downloads.
    """
    candidates = [
        os.path.join(get_user_data_dir(create=create), UPDATES_DIRNAME),
        os.path.join(tempfile.gettempdir(), APP_NAME, UPDATES_DIRNAME),
    ]

    for path in candidates:
        try:
            updates_dir = os.path.abspath(path)
            if create:
                os.makedirs(updates_dir, exist_ok=True)
            return updates_dir
        except Exception:
            continue

    fallback = os.path.abspath(os.path.join(tempfile.gettempdir(), APP_NAME, UPDATES_DIRNAME))
    if create:
        os.makedirs(fallback, exist_ok=True)
    return fallback


def get_logs_dir(create: bool = True) -> str:
    """Return the per-user logs directory next to config, updates and backups."""
    path = os.path.join(get_user_data_dir(create=create), LOGS_DIRNAME)
    if create:
        try:
            os.makedirs(path, exist_ok=True)
        except Exception:
            pass
    return path


def _bytes_to_gb_text(value: int) -> str:
    gb = float(value or 0) / (1024 ** 3)
    text = f"{gb:.2f}" if gb < 10 else f"{gb:.0f}"
    return text.replace(".", ",")


def get_system_drive_info() -> Dict[str, Any]:
    """Return label/size/free information for the Windows system drive.

    Kept UI-safe: any WinAPI failure falls back to plain disk_usage data.
    """
    if IS_WINDOWS:
        drive = os.environ.get("SystemDrive") or os.path.splitdrive(os.path.abspath(os.getcwd()))[0] or "C:"
        root = drive + os.sep if len(drive) == 2 and drive[1] == ":" else drive
    else:
        root = os.path.abspath(os.sep)
        drive = root
    label = ""
    fs = ""
    if IS_WINDOWS:
        try:
            volume_name = ctypes.create_unicode_buffer(261)
            file_system = ctypes.create_unicode_buffer(261)
            serial = ctypes.c_ulong()
            max_component = ctypes.c_ulong()
            flags = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetVolumeInformationW(
                ctypes.c_wchar_p(root),
                volume_name,
                len(volume_name),
                ctypes.byref(serial),
                ctypes.byref(max_component),
                ctypes.byref(flags),
                file_system,
                len(file_system),
            )
            if ok:
                label = str(volume_name.value or "").strip()
                fs = str(file_system.value or "").strip()
        except Exception as exc:
            log_app(f"system drive label lookup failed: {exc}", level="WARNING")
    try:
        usage = shutil.disk_usage(root)
        total = int(usage.total)
        free = int(usage.free)
        used = int(usage.used)
        percent_used = round((used / total) * 100, 1) if total else 0.0
    except Exception as exc:
        log_app(f"system drive usage lookup failed: {exc}", level="ERROR")
        total = free = used = 0
        percent_used = 0.0
    display_label = label or ("Windows" if IS_WINDOWS else "System")
    short = f"{display_label} ({drive.upper()})" if drive else display_label
    size_text = f"{_bytes_to_gb_text(free)} ГБ вільно з {_bytes_to_gb_text(total)} ГБ" if total else "невідомий розмір"
    return {
        "drive": drive.upper(),
        "root": root,
        "label": display_label,
        "fs": fs,
        "total": total,
        "used": used,
        "free": free,
        "percent_used": percent_used,
        "short": short,
        "size_text": size_text,
        "display": f"{short} • {size_text}",
    }


def _safe_update_filename(filename: str, fallback: str = "FreeCleaner-update.exe") -> str:
    name = os.path.basename((filename or "").strip()) or fallback
    name = urllib.parse.unquote(name)
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if not name:
        name = fallback
    return name[:180]


def get_update_download_path(filename: str, fallback: str = "FreeCleaner-update.exe") -> str:
    """Build a safe update destination path inside the per-user updates dir."""
    name = _safe_update_filename(filename, fallback=fallback)
    return os.path.join(get_updates_dir(create=True), name)


def cleanup_old_update_files(keep_paths: Optional[Set[str]] = None) -> int:
    """Delete stale files from the per-user updates dir and return a count.

    The function is intentionally limited to the FreeCleaner user-data updates
    directory. It never follows symlinks and never touches parent directories.
    """
    updates_dir = get_updates_dir(create=True)
    root = os.path.abspath(updates_dir)
    keep = {os.path.abspath(p) for p in (keep_paths or set()) if p}
    removed = 0

    if not os.path.isdir(root):
        return 0

    for name in list(os.listdir(root)):
        path = os.path.abspath(os.path.join(root, name))
        try:
            if os.path.commonpath([root, path]) != root:
                continue
        except Exception:
            continue
        if path in keep:
            continue
        try:
            if os.path.isdir(path) and not os.path.islink(path):
                shutil.rmtree(path, ignore_errors=True)
            else:
                os.remove(path)
            removed += 1
        except FileNotFoundError:
            continue
        except Exception:
            continue
    return removed


def is_installable_update_file(path: str) -> bool:
    ext = os.path.splitext(path or "")[1].lower()
    return IS_WINDOWS and ext in {".exe", ".msi"}


def _powershell_literal(value: str) -> str:
    return "'" + (value or "").replace("'", "''") + "'"


def _shell_execute_with_process(file_path: str, parameters: str = "", verb: str = "open", working_dir: Optional[str] = None) -> Tuple[bool, str, Optional[int]]:
    if not IS_WINDOWS:
        return False, "ShellExecute is available only on Windows.", None

    try:
        SEE_MASK_NOCLOSEPROCESS = 0x00000040
        SW_SHOWNORMAL = 1

        class SHELLEXECUTEINFOW(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.wintypes.DWORD),
                ("fMask", ctypes.c_ulong),
                ("hwnd", ctypes.wintypes.HWND),
                ("lpVerb", ctypes.wintypes.LPCWSTR),
                ("lpFile", ctypes.wintypes.LPCWSTR),
                ("lpParameters", ctypes.wintypes.LPCWSTR),
                ("lpDirectory", ctypes.wintypes.LPCWSTR),
                ("nShow", ctypes.c_int),
                ("hInstApp", ctypes.wintypes.HINSTANCE),
                ("lpIDList", ctypes.c_void_p),
                ("lpClass", ctypes.wintypes.LPCWSTR),
                ("hkeyClass", ctypes.wintypes.HKEY),
                ("dwHotKey", ctypes.wintypes.DWORD),
                ("hIcon", ctypes.wintypes.HANDLE),
                ("hProcess", ctypes.wintypes.HANDLE),
            ]

        sei = SHELLEXECUTEINFOW()
        sei.cbSize = ctypes.sizeof(SHELLEXECUTEINFOW)
        sei.fMask = SEE_MASK_NOCLOSEPROCESS
        sei.hwnd = None
        sei.lpVerb = verb
        sei.lpFile = file_path
        sei.lpParameters = parameters or None
        sei.lpDirectory = working_dir or os.path.dirname(file_path) or None
        sei.nShow = SW_SHOWNORMAL

        if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(sei)):
            err = ctypes.get_last_error()
            log_system_response("shell_execute", command={"file": file_path, "parameters": parameters, "verb": verb, "cwd": working_dir}, returncode=f"failed:{err}", stderr=f"ShellExecuteEx failed ({err})", context={"visible": True}, level="WARNING")
            return False, f"ShellExecuteEx failed ({err}).", None

        pid: Optional[int] = None
        handle = sei.hProcess
        if handle:
            try:
                pid_value = ctypes.windll.kernel32.GetProcessId(handle)
                pid = int(pid_value) if pid_value else None
            except Exception:
                pid = None
            try:
                ctypes.windll.kernel32.CloseHandle(handle)
            except Exception:
                pass
        log_system_response("shell_execute", command={"file": file_path, "parameters": parameters, "verb": verb, "cwd": working_dir}, returncode="started", stdout={"pid": pid}, context={"visible": True})
        return True, "Process started.", pid
    except Exception as exc:
        log_system_response("shell_execute", command={"file": file_path, "parameters": parameters, "verb": verb, "cwd": working_dir}, returncode="exception", stderr=str(exc), context={"visible": True}, level="ERROR")
        return False, str(exc) or "Failed to start installer.", None


def launch_update_installer(installer_path: str) -> Tuple[bool, str, Optional[int]]:
    """Launch a downloaded update installer and return (ok, message, pid)."""
    path = os.path.abspath(installer_path or "")
    if not path or not os.path.isfile(path):
        return False, "Update file was not found.", None
    try:
        updates_root = os.path.abspath(get_updates_dir(create=True))
        if os.path.commonpath([updates_root, path]) != updates_root:
            log_security(f"blocked update launch outside updates dir: {path}", level="WARNING")
            return False, "Update file is outside the trusted updates folder.", None
    except Exception:
        return False, "Could not verify update file location.", None

    ext = os.path.splitext(path)[1].lower()
    if ext not in {".exe", ".msi"}:
        log_security(f"blocked non-installer update launch: {path}", level="WARNING")
        return False, "Unsupported update installer type.", None
    if not IS_WINDOWS:
        try:
            webbrowser.open(path)
            return True, "Update file opened.", None
        except Exception as exc:
            return False, str(exc) or "Could not open update file.", None

    try:
        if ext == ".msi":
            proc = subprocess.Popen(["msiexec.exe", "/i", path], cwd=os.path.dirname(path) or None)
            log_system_response("process.start", command=["msiexec.exe", "/i", path], returncode="started", stdout={"pid": int(proc.pid)}, context={"installer": True, "visible": True})
            return True, "MSI installer started.", int(proc.pid)
        if ext == ".exe":
            ok, message, pid = _shell_execute_with_process(path)
            if ok:
                return ok, message, pid
            ok, message, pid = _shell_execute_with_process(path, verb="runas")
            if ok:
                return ok, message, pid
            proc = subprocess.Popen([path], cwd=os.path.dirname(path) or None)
            log_system_response("process.start", command=[path], returncode="started", stdout={"pid": int(proc.pid)}, context={"installer": True, "visible": True})
            return True, "Installer started.", int(proc.pid)
        os.startfile(path)  # type: ignore[attr-defined]
        return True, "Update file opened.", None
    except Exception as exc:
        return False, str(exc) or "Could not start update installer.", None


def schedule_update_cleanup_after_install(installer_pid: Optional[int], updates_dir: Optional[str] = None) -> bool:
    """Start a detached cleanup task for the per-user updates directory."""
    if not IS_WINDOWS:
        return False

    root = os.path.abspath(updates_dir or get_updates_dir(create=True))
    if not os.path.isdir(root):
        return False

    pid = int(installer_pid or 0)
    if pid > 0:
        wait_block = f"try {{ Wait-Process -Id {pid} -Timeout 7200 -ErrorAction SilentlyContinue }} catch {{ }};"
    else:
        wait_block = "Start-Sleep -Seconds 120;"

    script = (
        "$ErrorActionPreference='SilentlyContinue';"
        + wait_block
        + "Start-Sleep -Seconds 5;"
        + "$dir=" + _powershell_literal(root) + ";"
        + "if (Test-Path -LiteralPath $dir) {"
        + "Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | ForEach-Object {"
        + "$p=$_.FullName;"
        + "$isLink=($_.Attributes -band [IO.FileAttributes]::ReparsePoint);"
        + "for ($i=0; $i -lt 20; $i++) {"
        + "try { if ($isLink) { Remove-Item -LiteralPath $p -Force -ErrorAction Stop } else { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop }; break }"
        + "catch { Start-Sleep -Seconds 3 }"
        + "}"
        + "}"
        + "}"
    )

    try:
        creationflags = 0x08000000  # CREATE_NO_WINDOW
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-Command", script],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return True
    except Exception:
        return False


def guess_download_filename(url: str, fallback: str = "download.bin") -> str:
    text = (url or "").strip()
    if not text:
        return fallback
    try:
        parsed = urllib.parse.urlparse(text)
        name = os.path.basename(urllib.parse.unquote(parsed.path))
        return name or fallback
    except Exception:
        return fallback


def download_url_to_file(
    url: str,
    dest_path: str,
    *,
    progress_cb: Optional[Callable[[int, Optional[int]], None]] = None,
    timeout: int = 30,
    cancel_event: Optional[threading.Event] = None,
) -> Tuple[bool, str]:
    target_url = (url or "").strip()
    dest = (dest_path or "").strip()
    if not target_url:
        return False, "Empty download URL."
    parsed_url = urllib.parse.urlparse(target_url)
    if parsed_url.scheme.lower() != "https":
        log_security(f"blocked non-HTTPS update download URL: {target_url}", level="WARNING")
        return False, "Only HTTPS update downloads are allowed."
    if not dest:
        return False, "Empty destination path."

    parent_dir = os.path.dirname(dest) or "."
    os.makedirs(parent_dir, exist_ok=True)
    temp_path = dest + ".part"

    request = urllib.request.Request(
        target_url,
        headers={
            "Accept": "application/octet-stream,application/vnd.github+json;q=0.9,*/*;q=0.8",
            "User-Agent": f"{APP_NAME}-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )

    downloaded = 0
    total: Optional[int] = None
    log_action({"download_start": target_url, "dest": dest})
    try:
        started_http = time.perf_counter()
        with urllib.request.urlopen(request, timeout=timeout) as response, open(temp_path, "wb") as fh:
            status_code = getattr(response, "status", None) or getattr(response, "code", None)
            headers_snapshot = {str(k): str(v) for k, v in getattr(response, "headers", {}).items()}
            log_system_response(
                "http.response",
                command={"method": "GET", "url": target_url},
                returncode=status_code,
                stdout={"headers": headers_snapshot},
                elapsed_ms=int((time.perf_counter() - started_http) * 1000),
                timeout=timeout,
                context={"dest": dest},
            )
            length_header = response.headers.get("Content-Length")
            if length_header and str(length_header).isdigit():
                total = int(length_header)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    raise RuntimeError("Download cancelled.")
                chunk = response.read(1024 * 128)
                if not chunk:
                    break
                fh.write(chunk)
                downloaded += len(chunk)
                if progress_cb is not None:
                    try:
                        progress_cb(downloaded, total)
                    except Exception:
                        pass
        os.replace(temp_path, dest)
        log_action({"download_complete": dest, "bytes": downloaded})
        log_system_response("http.download_complete", command={"url": target_url}, returncode="ok", stdout={"dest": dest, "bytes": downloaded, "expected_total": total}, context={"dest": dest})
        return True, dest
    except Exception as exc:
        log_error(f"download failed: {target_url}: {exc}")
        log_system_response("http.download_failed", command={"url": target_url}, returncode="exception", stderr=str(exc), timeout=timeout, context={"dest": dest}, level="ERROR")
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except Exception:
            pass
        return False, str(exc) or "Download failed."


def _parse_version_info_text(text: str) -> Dict[str, str]:
    meta: Dict[str, str] = {}

    # StringStruct('ProductVersion', '1.0.0.0')
    for m in re.finditer(r"StringStruct\('(?P<k>[^']+)'\s*,\s*'(?P<v>[^']*)'\)", text or ""):
        k = m.group("k").strip()
        v = m.group("v").strip()
        if k and v:
            meta[k] = v

    # filevers=(1, 0, 0, 0)
    m = re.search(r"filevers=\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)", text or "")
    if m:
        meta.setdefault("FileVersion", ".".join(m.groups()))

    # prodvers=(1, 0, 0, 0)
    m = re.search(r"prodvers=\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)", text or "")
    if m:
        meta.setdefault("ProductVersion", ".".join(m.groups()))

    return meta


def _load_version_info_from_file() -> Dict[str, str]:
    """Reads version_info.txt (external first, then bundled)."""
    package_dir = os.path.dirname(os.path.abspath(__file__))
    source_root = os.path.dirname(package_dir)
    candidates = [
        os.path.join(get_runtime_base_dir(), VERSION_INFO_FILENAME),
        os.path.join(get_bundle_base_dir(), VERSION_INFO_FILENAME),
        os.path.join(source_root, VERSION_INFO_FILENAME),
        os.path.join(package_dir, VERSION_INFO_FILENAME),
    ]
    for path in candidates:
        try:
            if path and os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    return _parse_version_info_text(f.read())
        except Exception:
            continue
    return {}


class _LANGANDCODEPAGE(ctypes.Structure):
    _fields_ = [("wLanguage", ctypes.c_ushort), ("wCodePage", ctypes.c_ushort)]


def _load_version_info_from_exe(exe_path: str) -> Dict[str, str]:
    """Reads embedded Windows version resources from an .exe (built from version_info.txt)."""
    if not IS_WINDOWS:
        return {}
    try:
        exe_path = os.path.abspath(exe_path)
        size = ctypes.windll.version.GetFileVersionInfoSizeW(exe_path, None)
        if not size:
            return {}
        buf = ctypes.create_string_buffer(size)
        if not ctypes.windll.version.GetFileVersionInfoW(exe_path, 0, size, buf):
            return {}

        # read translations
        trans_ptr = ctypes.c_void_p()
        trans_len = ctypes.c_uint()
        translations: List[Tuple[int, int]] = []
        if ctypes.windll.version.VerQueryValueW(buf, "\\VarFileInfo\\Translation", ctypes.byref(trans_ptr), ctypes.byref(trans_len)):
            if trans_ptr.value and trans_len.value >= ctypes.sizeof(_LANGANDCODEPAGE):
                count = trans_len.value // ctypes.sizeof(_LANGANDCODEPAGE)
                arr = ctypes.cast(trans_ptr, ctypes.POINTER(_LANGANDCODEPAGE))
                for i in range(count):
                    translations.append((arr[i].wLanguage, arr[i].wCodePage))

        if not translations:
            translations = [(0x0409, 0x04B0)]  # en-US, Unicode

        def query(name: str) -> Optional[str]:
            for lang, cp in translations:
                sub = f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{name}"
                value_ptr = ctypes.c_void_p()
                value_len = ctypes.c_uint()
                if ctypes.windll.version.VerQueryValueW(buf, sub, ctypes.byref(value_ptr), ctypes.byref(value_len)):
                    if value_ptr.value:
                        try:
                            return ctypes.wstring_at(value_ptr.value)
                        except Exception:
                            pass
            return None

        meta: Dict[str, str] = {}
        for k in ("ProductName", "ProductVersion", "FileVersion", "CompanyName", "FileDescription", "InternalName", "OriginalFilename"):
            v = query(k)
            if v:
                meta[k] = v
        return meta
    except Exception:
        return {}


def load_app_meta() -> Dict[str, str]:
    """Single source of truth:
      - For .exe: read embedded version resources (origin: version_info.txt)
      - For .py: read version_info.txt next to the script
    """
    if getattr(sys, "frozen", False) and IS_WINDOWS:
        meta = _load_version_info_from_exe(sys.executable)
        if meta:
            return meta
    return _load_version_info_from_file()


APP_META = load_app_meta()
APP_VERSION_RAW = APP_META.get("ProductVersion") or APP_META.get("FileVersion") or "0.0.0.0"
APP_VERSION = _format_version_display(APP_VERSION_RAW)



def load_language_packs() -> Tuple[Dict[str, Dict[str, str]], Dict[str, str]]:
    """Load language packs.

    Priority:
      1) External ./lang next to .exe (marked as custom only in frozen build)
      2) Bundle lang inside PyInstaller (datas)
      3) Built-in defaults from default_lang_packs.py (English only)

    Only English has an in-code fallback. All other languages are loaded strictly from JSON.
    """
    packs = {k: dict(v) for k, v in DEFAULT_LANG_PACKS.items()}
    sources = {k: "builtin" for k in packs}

    runtime_lang_dir = os.path.abspath(os.path.join(get_runtime_base_dir(), LANG_DIRNAME))
    bundle_lang_dir = os.path.abspath(os.path.join(get_bundle_base_dir(), LANG_DIRNAME))

    checked: List[str] = []
    for lang_dir in (runtime_lang_dir, bundle_lang_dir):
        if lang_dir in checked:
            continue
        checked.append(lang_dir)

        if not os.path.isdir(lang_dir):
            continue

        is_runtime_external = (
            getattr(sys, "frozen", False)
            and lang_dir == runtime_lang_dir
            and runtime_lang_dir != bundle_lang_dir
        )
        source_kind = "runtime_external" if is_runtime_external else "bundle"

        for fname in os.listdir(lang_dir):
            if not fname.lower().endswith(".json"):
                continue

            code = os.path.splitext(fname)[0].lower()
            fpath = os.path.join(lang_dir, fname)

            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    data = json.load(f)

                if not isinstance(data, dict):
                    continue

                normalized = {str(k): str(v) for k, v in data.items()}
                base = dict(DEFAULT_LANG_PACKS["en"]) if code == "en" else {}
                base.update(normalized)
                base["NAME"] = (
                    str(base.get("NAME", "")).strip()
                    or str(base.get(f"lang_{code}", "")).strip()
                    or code.upper()
                )
                packs[code] = base
                sources[code] = source_kind
            except Exception:
                continue

    for code, pack in packs.items():
        pack["NAME"] = (
            str(pack.get("NAME", "")).strip()
            or str(pack.get(f"lang_{code}", "")).strip()
            or code.upper()
        )

    return packs, sources


LANG_PACKS, LANG_PACK_SOURCES = load_language_packs()

# -------------------------
# Language display helpers (UI)
# -------------------------

def language_display_name(code: str) -> str:
    """Human-friendly language name for UI.

    - Uses NAME from JSON/builtin.
    - In frozen builds, packs loaded from external ./lang next to the .exe
      are labeled as 'Користувацька <NAME>'.
    """
    code = (code or "").strip().lower()
    pack = LANG_PACKS.get(code, {})
    name = str(pack.get("NAME") or pack.get(f"lang_{code}") or code.upper()).strip() or code.upper()

    source = LANG_PACK_SOURCES.get(code, "")
    is_custom_external = bool(getattr(sys, "frozen", False)) and source == "runtime_external"
    return f"Користувацька {name}" if is_custom_external else name




@dataclass
class RegistryValueSpec:
    key_path: str
    name: str
    desired: Union[int, str]
    reg_type: str = "REG_DWORD"
    label: str = ""
    requires_admin: bool = False


@dataclass
class CleanerTask:
    key: str
    title_key: str
    desc_key: str
    path: Optional[str] = None
    kind: str = "directory"
    category: str = "system"
    state: str = "normal"
    default: bool = False
    requires_admin: bool = False
    command: Optional[Callable[[], None]] = None
    danger: str = "safe"
    fmt: Optional[Dict[str, str]] = None
    paths: Optional[List[str]] = None
    instant_action: bool = False
    registry_keys: Optional[List[str]] = None
    registry_values: Optional[List[RegistryValueSpec]] = None
    reboot_required: bool = False
    # UI hint: cleanup actions should stay checkboxes, optimizer tweaks should be switches.
    control: str = "auto"


class PathFinder:
    @staticmethod
    def expand(path: str) -> str:
        return os.path.normpath(os.path.expandvars(path))

    @staticmethod
    def _read_env_from_registry(root, reg_path: str) -> List[str]:
        paths = set()
        if not IS_WINDOWS:
            return []
        try:
            with winreg.OpenKey(root, reg_path) as key:
                for name in ("TEMP", "TMP"):
                    try:
                        value = winreg.QueryValueEx(key, name)[0]
                        if value:
                            paths.add(PathFinder.expand(value))
                    except OSError:
                        pass
        except OSError:
            pass
        return list(paths)

    @staticmethod
    def get_user_temp_paths() -> List[str]:
        paths = set(PathFinder._read_env_from_registry(winreg.HKEY_CURRENT_USER, r"Environment")) if IS_WINDOWS else set()
        for name in ("TEMP", "TMP"):
            value = os.environ.get(name)
            if value:
                paths.add(PathFinder.expand(value))
        return sorted(paths)

    @staticmethod
    def get_system_temp_paths() -> List[str]:
        if not IS_WINDOWS:
            return []
        reg = r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"
        paths = set(PathFinder._read_env_from_registry(winreg.HKEY_LOCAL_MACHINE, reg))
        if not paths:
            paths.add(r"C:\Windows\Temp")
        return sorted(paths)

    @staticmethod
    def existing(paths: List[str]) -> List[str]:
        seen = []
        known = set()
        for path in paths:
            path = PathFinder.expand(path)
            if path not in known and os.path.exists(path):
                known.add(path)
                seen.append(path)
        return seen


    @staticmethod
    def unique_existing(paths: List[str]) -> List[str]:
        """Return existing paths without duplicates or nested double-counts.

        Browser/app caches often expose both a parent cache directory and one of
        its children, for example ``Cache`` and ``Cache\\Cache_Data``.  Scanning
        both inflates the estimate, and cleaning both wastes work.  Keeping the
        shortest parent path is enough because FreeCleaner removes the contents
        of that target recursively while preserving the target root itself.
        """
        normalized: List[Tuple[str, str]] = []
        seen: Set[str] = set()
        for path in paths:
            if not path:
                continue
            expanded = PathFinder.expand(path)
            try:
                abs_path = os.path.abspath(expanded)
            except Exception:
                abs_path = expanded
            try:
                if not os.path.exists(abs_path):
                    continue
            except Exception:
                continue
            key = os.path.normcase(os.path.normpath(abs_path))
            if key in seen:
                continue
            seen.add(key)
            normalized.append((abs_path, key))

        normalized.sort(key=lambda item: (len(item[1]), item[1]))
        result: List[str] = []
        kept_keys: List[str] = []
        for abs_path, key in normalized:
            nested = False
            for parent_key in kept_keys:
                try:
                    if os.path.commonpath([parent_key, key]) == parent_key:
                        nested = True
                        break
                except Exception:
                    continue
            if nested:
                continue
            kept_keys.append(key)
            result.append(abs_path)
        return result

    @staticmethod
    def _existing_unique(paths: List[str]) -> List[str]:
        return PathFinder.unique_existing(paths)

    @staticmethod
    def _safe_join(*parts: str) -> str:
        return os.path.normpath(os.path.join(*[p for p in parts if p]))

    @staticmethod
    def get_program_files_paths() -> List[str]:
        """Return all Program Files roots visible to the current process."""
        names = ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)")
        paths: List[str] = []
        seen: Set[str] = set()
        for name in names:
            value = os.environ.get(name, "")
            if not value:
                continue
            expanded = PathFinder.expand(value)
            norm = os.path.normcase(os.path.abspath(expanded))
            if norm in seen:
                continue
            seen.add(norm)
            paths.append(expanded)
        return paths

    @staticmethod
    def get_local_low_dir() -> str:
        """Return the per-user LocalLow folder used by CryptnetUrlCache and WebView2 apps."""
        userprofile = os.environ.get("USERPROFILE", "")
        return PathFinder._safe_join(userprofile, r"AppData\LocalLow") if userprofile else ""

    @staticmethod
    def get_uwp_temp_cache_targets() -> List[str]:
        """Return conservative Microsoft Store / packaged-app temp cache folders.

        We only target TempState/AC\\Temp/LocalCache\\Temp-like folders, not
        broad LocalState or LocalCache roots where apps can keep real data.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        packages_root = PathFinder._safe_join(local, "Packages")
        if not packages_root or not os.path.isdir(packages_root):
            return []
        rels = (
            "TempState",
            r"AC\Temp",
            r"LocalCache\Temp",
            r"LocalCache\Microsoft\Windows\Caches",
        )
        targets: List[str] = []
        try:
            package_names = os.listdir(packages_root)
        except OSError:
            return []
        for package_name in package_names:
            package_root = os.path.join(packages_root, package_name)
            if not os.path.isdir(package_root):
                continue
            for rel in rels:
                target = os.path.join(package_root, rel)
                if os.path.exists(target):
                    targets.append(target)
        return PathFinder.unique_existing(targets)

    @staticmethod
    def get_windows_junk_targets() -> List[Tuple[str, str, str, str, bool]]:
        """Return real Windows cleanup targets as (key, title_key, desc_key, path, requires_admin).

        Targets are intentionally scoped to caches, logs, dumps and update download
        leftovers. It never returns dangerous system roots such as System32, WinSxS
        or Program Files.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        locallow = PathFinder.get_local_low_dir()
        windir = os.environ.get("WINDIR", r"C:\Windows")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        system_drive = os.environ.get("SystemDrive", "C:")
        network_service_local = PathFinder._safe_join(windir, r"ServiceProfiles\NetworkService\AppData\Local")
        candidates: List[Tuple[str, str, str, str, bool]] = [
            ("recent_docs", "task.recent_docs.title", "task.recent_docs.desc", PathFinder._safe_join(appdata, r"Microsoft\Windows\Recent"), False),
            ("jump_lists_auto", "task.jump_lists.title", "task.jump_lists.desc", PathFinder._safe_join(appdata, r"Microsoft\Windows\Recent\AutomaticDestinations"), False),
            ("jump_lists_custom", "task.jump_lists.title", "task.jump_lists.desc", PathFinder._safe_join(appdata, r"Microsoft\Windows\Recent\CustomDestinations"), False),
            ("thumb_cache", "task.thumb_cache.title", "task.thumb_cache.desc", PathFinder._safe_join(local, r"Microsoft\Windows\Explorer"), False),
            ("icon_cache_db", "task.icon_cache_db.title", "task.icon_cache_db.desc", PathFinder._safe_join(local, "IconCache.db"), False),
            ("inet_cache", "task.inet_cache.title", "task.inet_cache.desc", PathFinder._safe_join(local, r"Microsoft\Windows\INetCache"), False),
            ("windows_caches_user", "task.windows_caches_user.title", "task.windows_caches_user.desc", PathFinder._safe_join(local, r"Microsoft\Windows\Caches"), False),
            ("web_cache", "task.web_cache.title", "task.web_cache.desc", PathFinder._safe_join(local, r"Microsoft\Windows\WebCache"), False),
            ("cryptnet_content", "task.cryptnet_cache.title", "task.cryptnet_cache.desc", PathFinder._safe_join(locallow, r"Microsoft\CryptnetUrlCache\Content"), False),
            ("cryptnet_metadata", "task.cryptnet_cache.title", "task.cryptnet_cache.desc", PathFinder._safe_join(locallow, r"Microsoft\CryptnetUrlCache\MetaData"), False),
            ("crash_dumps_user", "task.crash_dumps.title", "task.crash_dumps.desc", PathFinder._safe_join(local, "CrashDumps"), False),
            ("wer_user", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(local, r"Microsoft\Windows\WER"), False),
            ("wer_system", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(programdata, r"Microsoft\Windows\WER"), True),
            ("windows_logs_cbs", "task.windows_component_logs.title", "task.windows_component_logs.desc", PathFinder._safe_join(windir, r"Logs\CBS"), True),
            ("windows_logs_dism", "task.windows_component_logs.title", "task.windows_component_logs.desc", PathFinder._safe_join(windir, r"Logs\DISM"), True),
            ("windows_logs_mosetup", "task.windows_setup_logs.title", "task.windows_setup_logs.desc", PathFinder._safe_join(windir, r"Logs\MoSetup"), True),
            ("windows_logs_waasmedic", "task.windows_update_etl_logs.title", "task.windows_update_etl_logs.desc", PathFinder._safe_join(windir, r"Logs\waasmedic"), True),
            ("windows_setupcln_logs", "task.windows_setup_logs.title", "task.windows_setup_logs.desc", PathFinder._safe_join(windir, r"System32\LogFiles\setupcln"), True),
            ("windows_wmi_diagtrack_logs", "task.windows_wmi_etl_logs.title", "task.windows_wmi_etl_logs.desc", PathFinder._safe_join(windir, r"System32\LogFiles\WMI"), True),
            ("windows_panther_logs", "task.windows_setup_logs.title", "task.windows_setup_logs.desc", PathFinder._safe_join(windir, "Panther"), True),
            ("windows_minidump", "task.memory_dumps.title", "task.memory_dumps.desc", PathFinder._safe_join(windir, "Minidump"), True),
            ("windows_memory_dump", "task.memory_dumps.title", "task.memory_dumps.desc", PathFinder._safe_join(windir, "MEMORY.DMP"), True),
            ("windows_old", "task.windows_old.title", "task.windows_old.desc", PathFinder._safe_join(system_drive + os.sep, "Windows.old"), True),
            ("update_cache_files", "task.update_cache_files.title", "task.update_cache_files.desc", PathFinder._safe_join(windir, r"SoftwareDistribution\Download"), True),
            ("delivery_opt_user", "task.delivery_opt.title", "task.delivery_opt.desc", PathFinder._safe_join(local, r"Microsoft\Windows\DeliveryOptimization\Cache"), False),
            ("delivery_opt_programdata", "task.delivery_opt.title", "task.delivery_opt.desc", PathFinder._safe_join(programdata, r"Microsoft\Windows\DeliveryOptimization\Cache"), True),
            ("delivery_opt_networkservice", "task.delivery_opt.title", "task.delivery_opt.desc", PathFinder._safe_join(network_service_local, r"Microsoft\Windows\DeliveryOptimization\Cache"), True),
            ("font_cache_user", "task.font_cache.title", "task.font_cache.desc", PathFinder._safe_join(local, "FontCache"), False),
            ("programdata_temp", "task.programdata_temp.title", "task.programdata_temp.desc", PathFinder._safe_join(programdata, "Temp"), True),
            ("windows_system_temp", "task.windows_system_temp.title", "task.windows_system_temp.desc", PathFinder._safe_join(windir, "SystemTemp"), True),
            ("windows_programdata_caches", "task.windows_programdata_caches.title", "task.windows_programdata_caches.desc", PathFinder._safe_join(programdata, r"Microsoft\Windows\Caches"), True),
            ("windows_device_metadata_cache", "task.windows_device_metadata_cache.title", "task.windows_device_metadata_cache.desc", PathFinder._safe_join(programdata, r"Microsoft\Windows\DeviceMetadataCache\dmrccache"), True),
            ("prefetch", "task.prefetch.title", "task.prefetch.desc", PathFinder._safe_join(windir, "Prefetch"), True),
        ]
        return [(k, t, d, p, a) for k, t, d, p, a in candidates if p and os.path.exists(p)]

    @staticmethod
    def get_chromium_cache_targets() -> List[Tuple[str, str, str, str, Dict[str, str]]]:
        """Discover Chromium based browser caches across all profiles.

        Modern Chromium browsers moved cache folders several times.  We check the
        old Default\\Cache layout and the newer Profile\\Cache\\Cache_Data and
        Code Cache folders, so analysis reflects real removable data instead of a
        single hard-coded folder.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        browsers = [
            ("chrome", "Google Chrome", PathFinder._safe_join(local, r"Google\Chrome\User Data")),
            ("edge", "Microsoft Edge", PathFinder._safe_join(local, r"Microsoft\Edge\User Data")),
            ("brave", "Brave", PathFinder._safe_join(local, r"BraveSoftware\Brave-Browser\User Data")),
            ("vivaldi", "Vivaldi", PathFinder._safe_join(local, r"Vivaldi\User Data")),
            ("yandex", "Yandex Browser", PathFinder._safe_join(local, r"Yandex\YandexBrowser\User Data")),
            ("opera", "Opera", PathFinder._safe_join(roaming, r"Opera Software\Opera Stable")),
            ("opera_gx", "Opera GX", PathFinder._safe_join(roaming, r"Opera Software\Opera GX Stable")),
        ]
        subdirs = [
            r"Cache", r"Cache\Cache_Data", r"Code Cache", r"GPUCache",
            r"Service Worker\CacheStorage", r"Service Worker\ScriptCache",
            r"Media Cache", r"ShaderCache", r"GrShaderCache", r"DawnCache",
            r"GraphiteDawnCache", r"Crashpad\reports", r"BrowserMetrics",
            r"optimization_guide_prediction_model_downloads",
        ]
        result: List[Tuple[str, str, str, str, Dict[str, str]]] = []
        seen: Set[str] = set()
        for slug, name, root in browsers:
            if not root or not os.path.isdir(root):
                continue
            # Opera keeps its profile directly in the root. Chromium-family
            # browsers usually use Default/Profile N. Avoid Guest/System Profile
            # because they add clutter and are not useful quick-clean choices.
            profiles: List[str] = [""] if slug in {"opera", "opera_gx"} else []
            try:
                for entry in os.listdir(root):
                    full = os.path.join(root, entry)
                    if os.path.isdir(full) and (entry == "Default" or re.fullmatch(r"Profile \d+", entry)):
                        profiles.append(entry)
            except OSError:
                pass
            for profile in profiles:
                base = os.path.join(root, profile) if profile else root
                profile_label = profile or "Default"
                for sub in subdirs:
                    path = os.path.join(base, sub)
                    norm = os.path.normcase(os.path.abspath(path))
                    if norm in seen or not os.path.exists(path):
                        continue
                    seen.add(norm)
                    key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"browser_{slug}_{profile_label}_{sub}").strip("_").lower()
                    result.append((key, "task.browser_generic.title", "task.browser_generic.desc", path, {"browser": name, "profile": profile_label, "path": path}))
        return result

    @staticmethod
    def get_firefox_cache_targets() -> List[Tuple[str, str, str, str, Dict[str, str]]]:
        targets: List[Tuple[str, str, str, str, Dict[str, str]]] = []
        roots = [
            PathFinder._safe_join(os.environ.get("LOCALAPPDATA", ""), r"Mozilla\Firefox\Profiles"),
            PathFinder._safe_join(os.environ.get("APPDATA", ""), r"Mozilla\Firefox\Profiles"),
        ]
        seen: Set[str] = set()
        for root in roots:
            if not root or not os.path.isdir(root):
                continue
            try:
                profiles = os.listdir(root)
            except OSError:
                continue
            for profile in profiles:
                profile_path = os.path.join(root, profile)
                if not os.path.isdir(profile_path):
                    continue
                for suffix, title_key in (("cache2", "task.firefox_cache2.title"), ("startupCache", "task.firefox_startupCache.title")):
                    target = os.path.join(profile_path, suffix)
                    norm = os.path.normcase(os.path.abspath(target))
                    if norm in seen or not os.path.exists(target):
                        continue
                    seen.add(norm)
                    key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"firefox_{profile}_{suffix}").strip("_").lower()
                    targets.append((key, title_key, f"task.firefox_{suffix}.desc", target, {"profile": profile, "path": target}))
        return targets

    @staticmethod
    def get_app_cache_targets() -> List[Tuple[str, str, str, str, Dict[str, str]]]:
        appdata = os.environ.get("APPDATA", "")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            ("discord_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discord\Cache"), {"app": "Discord"}),
            ("discord_gpu_cache", "task.discord_gpu_cache.title", "task.discord_gpu_cache.desc", PathFinder._safe_join(appdata, r"discord\GPUCache"), {"app": "Discord"}),
            ("discord_code_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discord\Code Cache"), {"app": "Discord"}),
            ("discord_canary_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discordcanary\Cache"), {"app": "Discord Canary"}),
            ("discord_canary_code_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discordcanary\Code Cache"), {"app": "Discord Canary"}),
            ("discord_ptb_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discordptb\Cache"), {"app": "Discord PTB"}),
            ("discord_ptb_code_cache", "task.discord_cache.title", "task.discord_cache.desc", PathFinder._safe_join(appdata, r"discordptb\Code Cache"), {"app": "Discord PTB"}),
            ("telegram_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Telegram Desktop\tdata\user_data"), {"app": "Telegram"}),
            ("teams_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Microsoft\Teams\Cache"), {"app": "Microsoft Teams"}),
            ("teams_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Microsoft\Teams\Code Cache"), {"app": "Microsoft Teams"}),
            ("teams_gpu_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Microsoft\Teams\GPUCache"), {"app": "Microsoft Teams"}),
            ("new_teams_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Packages\MSTeams_8wekyb3d8bbwe\LocalCache\Microsoft\MSTeams\Cache"), {"app": "Microsoft Teams"}),
            ("slack_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Slack\Cache"), {"app": "Slack"}),
            ("slack_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Slack\Code Cache"), {"app": "Slack"}),
            ("slack_gpu_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Slack\GPUCache"), {"app": "Slack"}),
            ("spotify_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Spotify\Storage"), {"app": "Spotify"}),
            ("zoom_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Zoom\data\WebviewCache"), {"app": "Zoom"}),
            ("vscode_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Code\Cache"), {"app": "Visual Studio Code"}),
            ("vscode_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Code\Code Cache"), {"app": "Visual Studio Code"}),
            ("vscode_gpu_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Code\GPUCache"), {"app": "Visual Studio Code"}),
            ("cursor_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Cursor\Cache"), {"app": "Cursor"}),
            ("cursor_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Cursor\Code Cache"), {"app": "Cursor"}),
            ("cursor_gpu_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Cursor\GPUCache"), {"app": "Cursor"}),
            ("postman_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Postman\Cache"), {"app": "Postman"}),
            ("postman_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Postman\Code Cache"), {"app": "Postman"}),
            ("obs_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\cache"), {"app": "OBS Studio"}),
            ("minecraft_launcher_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r".minecraft\webcache2"), {"app": "Minecraft Launcher"}),
            ("curseforge_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"CurseForge\Cache"), {"app": "CurseForge"}),
            ("overwolf_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Overwolf\BrowserCache"), {"app": "Overwolf"}),
            ("whatsapp_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"WhatsApp\Cache"), {"app": "WhatsApp"}),
            ("whatsapp_code_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"WhatsApp\Code Cache"), {"app": "WhatsApp"}),
            ("github_desktop_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"GitHub Desktop\Cache"), {"app": "GitHub Desktop"}),
            ("notion_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Notion\Cache"), {"app": "Notion"}),
            ("figma_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Figma\Cache"), {"app": "Figma"}),
            ("microsoft_store_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Packages\Microsoft.WindowsStore_8wekyb3d8bbwe\LocalCache"), {"app": "Microsoft Store"}),
            ("widgets_webview_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Packages\MicrosoftWindows.Client.WebExperience_cw5n1h2txyewy\AC\#!001\INetCache"), {"app": "Windows Widgets"}),
        ]
        return [(k, t, d, p, fmt) for k, t, d, p, fmt in candidates if p and os.path.exists(p)]

    @staticmethod
    def get_onedrive_cleanup_targets() -> List[Tuple[str, str, str, str, Dict[str, str]]]:
        """Return conservative OneDrive cleanup targets.

        Never touches the user's OneDrive sync folders or account/settings DBs.
        Targets are limited to logs, crash dumps, setup logs and WebView/cache
        folders that OneDrive can rebuild.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        base = PathFinder._safe_join(local, r"Microsoft\OneDrive")
        candidates: List[Tuple[str, str, str, str, Dict[str, str]]] = []
        def add(key: str, title_key: str, desc_key: str, rel_or_path: str) -> None:
            path = rel_or_path if os.path.isabs(rel_or_path) else PathFinder._safe_join(base, rel_or_path)
            candidates.append((key, title_key, desc_key, path, {"app": "OneDrive", "path": path}))

        if base:
            # Logs and crash reports are safe to remove and often grow after sync issues.
            add("onedrive_logs", "task.onedrive_logs.title", "task.onedrive_logs.desc", "logs")
            add("onedrive_setup_logs", "task.onedrive_setup_logs.title", "task.onedrive_setup_logs.desc", r"setup\logs")
            add("onedrive_crash_reports", "task.onedrive_crash_reports.title", "task.onedrive_crash_reports.desc", "CrashReports")
            add("onedrive_standalone_updater_logs", "task.onedrive_setup_logs.title", "task.onedrive_setup_logs.desc", r"StandaloneUpdater\logs")

            # OneDrive uses embedded web UI components on modern builds. Cache only.
            for rel in (
                r"EBWebView\Default\Cache",
                r"EBWebView\Default\Code Cache",
                r"EBWebView\Default\GPUCache",
                r"EBWebView\Default\Service Worker\CacheStorage",
                r"EBWebView\Default\DawnCache",
                r"EBWebView\Default\GrShaderCache",
                r"EBWebView\Default\ShaderCache",
            ):
                safe_key = "onedrive_webview_" + re.sub(r"[^a-zA-Z0-9_]+", "_", rel).strip("_").lower()
                add(safe_key, "task.onedrive_webview_cache.title", "task.onedrive_webview_cache.desc", rel)

        # Machine-wide updater/setup logs only; no program files or sync data.
        if programdata:
            candidates.append((
                "onedrive_programdata_setup_logs",
                "task.onedrive_setup_logs.title",
                "task.onedrive_setup_logs.desc",
                PathFinder._safe_join(programdata, r"Microsoft OneDrive\Setup\logs"),
                {"app": "OneDrive"},
            ))

        return [item for item in candidates if item[3] and os.path.exists(item[3])]

    @staticmethod
    def get_streaming_cache_targets() -> List[Tuple[str, str, str, str, Dict[str, str]]]:
        """Return conservative streaming/recording app cleanup targets.

        These are limited to caches, logs, crash reports and temporary browser
        data.  Profile/configuration folders are intentionally not targeted so
        OBS scenes, sources, plugins and Streamlabs layouts are not removed.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        candidates = [
            ("obs_logs", "task.streaming_obs_logs.title", "task.streaming_obs_logs.desc", PathFinder._safe_join(appdata, r"obs-studio\logs"), {"app": "OBS Studio"}),
            ("obs_crashes", "task.streaming_obs_logs.title", "task.streaming_obs_logs.desc", PathFinder._safe_join(appdata, r"obs-studio\crashes"), {"app": "OBS Studio"}),
            ("obs_browser_cache_streaming", "task.streaming_obs_cache.title", "task.streaming_obs_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\plugin_config\obs-browser\Cache"), {"app": "OBS Studio"}),
            ("obs_browser_code_cache", "task.streaming_obs_cache.title", "task.streaming_obs_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\plugin_config\obs-browser\Code Cache"), {"app": "OBS Studio"}),
            ("obs_browser_gpu_cache", "task.streaming_obs_cache.title", "task.streaming_obs_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\plugin_config\obs-browser\GPUCache"), {"app": "OBS Studio"}),
            ("streamlabs_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(appdata, r"slobs-client\Cache"), {"app": "Streamlabs Desktop"}),
            ("streamlabs_code_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(appdata, r"slobs-client\Code Cache"), {"app": "Streamlabs Desktop"}),
            ("streamlabs_gpu_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(appdata, r"slobs-client\GPUCache"), {"app": "Streamlabs Desktop"}),
            ("streamlabs_logs", "task.streaming_app_logs.title", "task.streaming_app_logs.desc", PathFinder._safe_join(appdata, r"slobs-client\logs"), {"app": "Streamlabs Desktop"}),
            ("twitch_studio_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(appdata, r"Twitch Studio\Cache"), {"app": "Twitch Studio"}),
            ("twitch_studio_logs", "task.streaming_app_logs.title", "task.streaming_app_logs.desc", PathFinder._safe_join(appdata, r"Twitch Studio\Logs"), {"app": "Twitch Studio"}),
            ("xsplit_logs", "task.streaming_app_logs.title", "task.streaming_app_logs.desc", PathFinder._safe_join(appdata, r"SplitMediaLabs\XSplit Broadcaster\logs"), {"app": "XSplit Broadcaster"}),
            ("nvidia_broadcast_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(local, r"NVIDIA Corporation\NVIDIA Broadcast\Cache"), {"app": "NVIDIA Broadcast"}),
            ("vdo_ninja_cache", "task.streaming_app_cache.title", "task.streaming_app_cache.desc", PathFinder._safe_join(local, r"VDO.Ninja\Cache"), {"app": "VDO.Ninja"}),
        ]
        return [(k, t, d, p, fmt) for k, t, d, p, fmt in candidates if p and os.path.exists(p)]

    @staticmethod
    def get_gaming_cache_targets() -> List[Tuple[str, str, str, str, bool]]:
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates = [
            ("dx_shader_cache", "task.dx_shader_cache.title", "task.dx_shader_cache.desc", PathFinder._safe_join(local, "D3DSCache"), False),
            ("nvidia_dx", "task.nvidia_dx.title", "task.nvidia_dx.desc", PathFinder._safe_join(local, r"NVIDIA\DXCache"), False),
            ("nvidia_gl", "task.nvidia_gl.title", "task.nvidia_gl.desc", PathFinder._safe_join(local, r"NVIDIA\GLCache"), False),
            ("nvidia_compute_cache", "task.nvidia_compute_cache.title", "task.nvidia_compute_cache.desc", PathFinder._safe_join(local, r"NVIDIA\ComputeCache"), False),
            ("nvidia_ngx_cache", "task.nvidia_ngx_cache.title", "task.nvidia_ngx_cache.desc", PathFinder._safe_join(local, r"NVIDIA\NGXCache"), False),
            ("nvidia_legacy_nv_cache_user", "task.nvidia_nv_cache.title", "task.nvidia_nv_cache.desc", PathFinder._safe_join(local, r"NVIDIA Corporation\NV_Cache"), False),
            ("nvidia_nv_cache", "task.nvidia_nv_cache.title", "task.nvidia_nv_cache.desc", PathFinder._safe_join(programdata, r"NVIDIA Corporation\NV_Cache"), True),
            ("amd_dx", "task.amd_dx.title", "task.amd_dx.desc", PathFinder._safe_join(local, r"AMD\DxCache"), False),
            ("amd_gl", "task.amd_gl.title", "task.amd_gl.desc", PathFinder._safe_join(local, r"AMD\GLCache"), False),
            ("amd_vk", "task.amd_vk.title", "task.amd_vk.desc", PathFinder._safe_join(local, r"AMD\VkCache"), False),
            ("intel_shader_cache", "task.intel_shader_cache.title", "task.intel_shader_cache.desc", PathFinder._safe_join(local, r"Intel\ShaderCache"), False),
            ("microsoft_dx_shader_cache", "task.dx_shader_cache.title", "task.dx_shader_cache.desc", PathFinder._safe_join(local, r"Microsoft\DirectX Shader Cache"), False),
            ("steam_htmlcache", "task.steam_htmlcache.title", "task.steam_htmlcache.desc", PathFinder._safe_join(local, r"Steam\htmlcache"), False),
            ("steam_appcache", "task.steam_appcache.title", "task.steam_appcache.desc", PathFinder._safe_join(os.environ.get("ProgramFiles(x86)", ""), r"Steam\appcache\httpcache"), False),
            ("steam_shadercache", "task.steam_shadercache.title", "task.steam_shadercache.desc", PathFinder._safe_join(os.environ.get("ProgramFiles(x86)", ""), r"Steam\steamapps\shadercache"), False),
            ("battle_net_cache", "task.battle_net_cache.title", "task.battle_net_cache.desc", PathFinder._safe_join(programdata, r"Battle.net\Agent\data\cache"), True),
            ("battle_net_agent_logs", "task.battle_net_cache.title", "task.battle_net_cache.desc", PathFinder._safe_join(programdata, r"Battle.net\Agent\Logs"), True),
            ("blizzard_browser_cache", "task.battle_net_cache.title", "task.battle_net_cache.desc", PathFinder._safe_join(local, r"Battle.net\BrowserCache"), False),
            ("epic_webcache", "task.epic_webcache.title", "task.epic_webcache.desc", PathFinder._safe_join(local, r"EpicGamesLauncher\Saved\webcache"), False),
            ("epic_webcache_4147", "task.epic_webcache.title", "task.epic_webcache.desc", PathFinder._safe_join(local, r"EpicGamesLauncher\Saved\webcache_4147"), False),
            ("ea_desktop_cache", "task.launcher_cache.title", "task.launcher_cache.desc", PathFinder._safe_join(local, r"Electronic Arts\EA Desktop\Cache"), False),
            ("ubisoft_cache", "task.launcher_cache.title", "task.launcher_cache.desc", PathFinder._safe_join(local, r"Ubisoft Game Launcher\cache"), False),
            ("gog_cache", "task.launcher_cache.title", "task.launcher_cache.desc", PathFinder._safe_join(programdata, r"GOG.com\Galaxy\webcache"), True),
            ("riot_cache", "task.launcher_cache.title", "task.launcher_cache.desc", PathFinder._safe_join(local, r"Riot Games\Riot Client\Cache"), False),
            ("obs_browser_cache", "task.temp_capture_cache.title", "task.temp_capture_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\plugin_config\obs-browser\Cache"), False),
        ]
        epic_saved = PathFinder._safe_join(local, r"EpicGamesLauncher\Saved")
        try:
            if epic_saved and os.path.isdir(epic_saved):
                for entry in os.listdir(epic_saved):
                    if entry.lower().startswith("webcache"):
                        candidates.append((
                            f"epic_{entry.lower()}",
                            "task.epic_webcache.title",
                            "task.epic_webcache.desc",
                            os.path.join(epic_saved, entry),
                            False,
                        ))
        except OSError:
            pass
        return [(k, t, d, p, a) for k, t, d, p, a in candidates if p and os.path.exists(p)]


class WindowsOps:
    @staticmethod
    def is_admin() -> bool:
        if not IS_WINDOWS:
            return False
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    @staticmethod
    def hidden_subprocess_kwargs(*, capture: bool = False, noisy: bool = False) -> Dict[str, Any]:
        kwargs: Dict[str, Any] = {}
        if IS_WINDOWS:
            # CREATE_NO_WINDOW keeps cmd/powershell/powercfg/bcdedit/reg helpers
            # completely hidden.  Keep the numeric fallback for Python builds
            # where subprocess.CREATE_NO_WINDOW is unavailable.
            kwargs["creationflags"] = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            try:
                startupinfo.wShowWindow = 0
            except Exception:
                pass
            kwargs["startupinfo"] = startupinfo
        if capture:
            kwargs.update({"stdout": subprocess.PIPE, "stderr": subprocess.STDOUT})
        elif not noisy:
            kwargs.update({"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL})
        kwargs.setdefault("stdin", subprocess.DEVNULL)
        return kwargs

    @staticmethod
    def _admin_relaunch_target() -> Tuple[str, str, str]:
        """Return executable, parameters and working directory for UAC relaunch.

        Build 31 could close the current window while the elevated copy exited
        immediately because the single-instance mutex was still held by the old
        process.  The internal --elevated-relaunch flag lets the new copy skip
        only that startup mutex check while the old copy is shutting down.
        """
        cwd = os.path.abspath(get_runtime_base_dir())
        internal_flag = "--elevated-relaunch"
        args = [arg for arg in sys.argv[1:] if arg not in {internal_flag, "--freecleaner-elevated-relaunch"}]
        if getattr(sys, "frozen", False):
            file_path = os.path.abspath(sys.executable)
            params = subprocess.list2cmdline([internal_flag, *args])
            return file_path, params, os.path.dirname(file_path) or cwd

        current_script = os.path.abspath(sys.argv[0]) if sys.argv else ""
        if not current_script or not os.path.exists(current_script):
            current_script = os.path.join(cwd, "app.pyw")
        # Prefer the windowed launcher for source runs so the elevated copy does
        # not open a console.  If the current script is app.py, hand off to app.pyw.
        if os.path.basename(current_script).lower() == "app.py":
            pyw_script = os.path.join(os.path.dirname(current_script), "app.pyw")
            if os.path.exists(pyw_script):
                current_script = pyw_script

        exe = os.path.abspath(sys.executable)
        if os.path.basename(exe).lower() in {"python.exe", "python3.exe"}:
            pythonw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            if os.path.exists(pythonw):
                exe = pythonw
        params = subprocess.list2cmdline([current_script, internal_flag, *args])
        return exe, params, os.path.dirname(current_script) or cwd

    @staticmethod
    def run_as_admin() -> Tuple[bool, str, Optional[int]]:
        if not IS_WINDOWS:
            return False, "Administrator relaunch is available only on Windows.", None
        try:
            file_path, parameters, working_dir = WindowsOps._admin_relaunch_target()
            log_action({"admin_relaunch_start": {"file": file_path, "parameters": parameters, "cwd": working_dir}})
            ok, message, pid = _shell_execute_with_process(file_path, parameters=parameters, verb="runas", working_dir=working_dir)
            log_system_response(
                "admin_relaunch",
                command={"file": file_path, "parameters": parameters, "cwd": working_dir},
                returncode="started" if ok else "failed",
                stdout=message,
                context={"pid": pid, "frozen": bool(getattr(sys, "frozen", False))},
                level="INFO" if ok else "WARNING",
            )
            return ok, message, pid
        except Exception as exc:
            log_error(f"admin relaunch failed: {exc}")
            log_system_response("admin_relaunch", command="runas", returncode="exception", stderr=str(exc), level="ERROR")
            return False, str(exc), None

    @staticmethod
    def run_command(cmd: str, timeout: int = 180, noisy: bool = False) -> bool:
        """Run a legacy string command without shell interpolation.

        Older FreeCleaner builds used shell=True here.  The method is retained
        for compatibility but now tokenizes the string and delegates to
        run_command_args so paths cannot be interpreted as shell operators.
        """
        text = (cmd or "").strip()
        if not text:
            return False
        try:
            args = shlex.split(text, posix=False if IS_WINDOWS else True)
        except Exception as exc:
            log_error(f"command parse failed: {text}: {exc}")
            return False
        if not args:
            return False
        log_security(f"legacy string command routed through shell-free runner: {args}")
        return WindowsOps.run_command_args(args, timeout=timeout, noisy=noisy)

    @staticmethod
    def run_command_args(
        args: List[str],
        timeout: int = 180,
        noisy: bool = False,
        *,
        log_failure: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Run a command without shell interpolation and log the full OS response.

        Even commands that normally do not need stdout are captured so QA can
        inspect the exact Windows answer later in system.log. CREATE_NO_WINDOW is
        still used on Windows, so capture does not reintroduce console flashes.
        """
        if not args:
            return False
        safe_args = [str(arg) for arg in args]
        started = time.perf_counter()
        try:
            log_action({"run_args": safe_args, "timeout": timeout})
            completed = subprocess.run(
                safe_args,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **WindowsOps.hidden_subprocess_kwargs(capture=True),
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            output = completed.stdout or ""
            log_system_response(
                "subprocess.run",
                command=safe_args,
                returncode=int(completed.returncode),
                stdout=output,
                stderr="",
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_args", "noisy": bool(noisy), **(context or {})},
                level="INFO" if int(completed.returncode) == 0 or not log_failure or bool((context or {}).get("optional")) else "WARNING",
            )
            log_qa_event("subprocess_completed", command=safe_args, rc=int(completed.returncode), elapsed_ms=elapsed, output_chars=len(output))
            ok = completed.returncode == 0
            if ok and safe_args and str(safe_args[0]).lower().endswith("powercfg.exe"):
                command_tokens = {str(part).casefold() for part in safe_args[1:]}
                if command_tokens.intersection({"/s", "-s", "/setactive", "-setactive", "/setacvalueindex", "-setacvalueindex", "/setdcvalueindex", "-setdcvalueindex", "-duplicatescheme"}):
                    WindowsOps.invalidate_powercfg_cache(" ".join(safe_args[:3]))
            if not ok and log_failure:
                log_error(f"args failed rc={completed.returncode}: {safe_args}: {str(output)[:1000]}")
            return ok
        except subprocess.TimeoutExpired as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or ""
            log_system_response(
                "subprocess.timeout",
                command=safe_args,
                returncode="timeout",
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_args", **(context or {})},
                level="ERROR",
            )
            log_error(f"args timeout after {timeout}s: {safe_args}")
            return False
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            log_system_response(
                "subprocess.exception",
                command=safe_args,
                returncode="exception",
                stdout="",
                stderr=str(exc),
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_args", **(context or {})},
                level="ERROR",
            )
            log_error(f"args exception: {safe_args}: {exc}")
            return False

    @staticmethod
    def run_command_capture(
        args: List[str],
        timeout: int = 180,
        *,
        log_failure: bool = True,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[int, str]:
        """Run a command and return (returncode, combined_output) without shell parsing."""
        if not args:
            return (1, "")
        safe_args = [str(arg) for arg in args]
        started = time.perf_counter()
        try:
            log_action({"capture_args": safe_args, "timeout": timeout})
            completed = subprocess.run(
                safe_args,
                shell=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **WindowsOps.hidden_subprocess_kwargs(capture=True),
            )
            elapsed = int((time.perf_counter() - started) * 1000)
            output = completed.stdout or ""
            log_system_response(
                "subprocess.capture",
                command=safe_args,
                returncode=int(completed.returncode),
                stdout=output,
                stderr="",
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_capture", **(context or {})},
                level="INFO" if int(completed.returncode) == 0 or not log_failure or bool((context or {}).get("optional")) else "WARNING",
            )
            log_qa_event("subprocess_capture_completed", command=safe_args, rc=int(completed.returncode), elapsed_ms=elapsed, output_chars=len(output))
            if int(completed.returncode) != 0 and log_failure:
                log_error(f"capture failed rc={completed.returncode}: {safe_args}: {str(output)[:1000]}")
            return (int(completed.returncode), output)
        except subprocess.TimeoutExpired as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            stdout = getattr(exc, "stdout", "") or ""
            stderr = getattr(exc, "stderr", "") or ""
            combined = (str(stdout) + ("\n" + str(stderr) if stderr else "")).strip()
            log_system_response(
                "subprocess.capture_timeout",
                command=safe_args,
                returncode="timeout",
                stdout=stdout,
                stderr=stderr,
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_capture", **(context or {})},
                level="ERROR",
            )
            log_error(f"capture timeout after {timeout}s: {safe_args}")
            return (1, combined or f"timeout after {timeout}s")
        except Exception as exc:
            elapsed = int((time.perf_counter() - started) * 1000)
            log_system_response(
                "subprocess.capture_exception",
                command=safe_args,
                returncode="exception",
                stdout="",
                stderr=str(exc),
                elapsed_ms=elapsed,
                timeout=timeout,
                cwd=os.getcwd(),
                context={"mode": "run_command_capture", **(context or {})},
                level="ERROR",
            )
            log_error(f"capture exception: {safe_args}: {exc}")
            return (1, str(exc))

    @staticmethod
    def schedule_delete_on_reboot(path: str) -> bool:
        if not IS_WINDOWS or not path:
            return False
        try:
            MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
            normalized = os.path.abspath(path)
            candidates = [normalized]
            # MoveFileExW handles long paths better with the extended prefix.
            # Keep the normal path first so logs and Windows tools stay readable.
            extended_prefix = "\\\\?\\"
            unc_prefix = "\\\\?\\UNC\\"
            if len(normalized) >= 248 and not normalized.startswith(extended_prefix):
                if normalized.startswith("\\\\"):
                    candidates.append(unc_prefix + normalized.lstrip("\\"))
                else:
                    candidates.append(extended_prefix + normalized)
            for candidate in candidates:
                try:
                    ok = bool(ctypes.windll.kernel32.MoveFileExW(str(candidate), None, MOVEFILE_DELAY_UNTIL_REBOOT))
                    log_system_response(
                        "filesystem.schedule_delete_on_reboot",
                        command={"path": normalized, "candidate": candidate},
                        returncode="ok" if ok else "failed",
                        stdout={"scheduled": ok},
                        context={"api": "MoveFileExW"},
                        level="INFO" if ok else "WARNING",
                    )
                    if ok:
                        return True
                except Exception as exc:
                    log_system_response(
                        "filesystem.schedule_delete_on_reboot",
                        command={"path": normalized, "candidate": candidate},
                        returncode="exception",
                        stderr=str(exc),
                        context={"api": "MoveFileExW"},
                        level="WARNING",
                    )
            return False
        except Exception:
            return False

    @staticmethod
    def _split_registry_path(path: str) -> Optional[Tuple[Any, str, str]]:
        if not IS_WINDOWS or winreg is None:
            return None
        clean = (path or "").strip().replace("/", "\\")
        if not clean or "\\" not in clean:
            return None
        hive_name, subkey = clean.split("\\", 1)
        hive_name = hive_name.upper()
        hives = {
            "HKCU": winreg.HKEY_CURRENT_USER,
            "HKEY_CURRENT_USER": winreg.HKEY_CURRENT_USER,
            "HKLM": winreg.HKEY_LOCAL_MACHINE,
            "HKEY_LOCAL_MACHINE": winreg.HKEY_LOCAL_MACHINE,
        }
        hive = hives.get(hive_name)
        if hive is None:
            return None
        short = "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"
        return hive, subkey, short

    @staticmethod
    def _registry_access_flags(access: int, key_path: str) -> int:
        flags = access
        # Most optimizer keys live in the native 64-bit registry view.  A 32-bit
        # frozen build on 64-bit Windows would otherwise read/write WOW6432Node
        # for HKLM\SOFTWARE values and report misleading statuses.
        try:
            if IS_64BIT_WINDOWS and key_path.upper().startswith("HKLM\\SOFTWARE\\"):
                flags |= winreg.KEY_WOW64_64KEY  # type: ignore[union-attr]
        except Exception:
            pass
        return flags

    @staticmethod
    def _normalize_registry_value(value: Any, reg_type: str) -> Any:
        value_type = (reg_type or "REG_DWORD").upper()
        if value_type == "REG_DWORD":
            if isinstance(value, int):
                return int(value) & 0xFFFFFFFF
            text = str(value).strip()
            if not text:
                return None
            try:
                return int(text, 16) & 0xFFFFFFFF if text.lower().startswith("0x") else int(text) & 0xFFFFFFFF
            except Exception:
                return text.lower()
        if value_type == "REG_SZ":
            return str(value).strip().lower()
        return str(value).strip().lower()

    @staticmethod
    def format_registry_value(value: Any, reg_type: str) -> str:
        value_type = (reg_type or "REG_DWORD").upper()
        if value is None:
            return "missing"
        if value_type == "REG_DWORD":
            normalized = WindowsOps._normalize_registry_value(value, reg_type)
            if isinstance(normalized, int):
                return f"0x{normalized:08x} ({normalized})" if normalized > 9 else str(normalized)
        return str(value)

    @staticmethod
    def registry_value_status(spec: RegistryValueSpec) -> Dict[str, Any]:
        desired_display = WindowsOps.format_registry_value(spec.desired, spec.reg_type)
        result: Dict[str, Any] = {
            "label": spec.label or f"{spec.key_path}\\{spec.name}",
            "path": spec.key_path,
            "name": spec.name,
            "reg_type": spec.reg_type,
            "desired": spec.desired,
            "desired_display": desired_display,
            "current": None,
            "current_display": "missing",
            "matches": False,
            "status": "unavailable",
            "requires_admin": bool(spec.requires_admin),
        }
        parsed = WindowsOps._split_registry_path(spec.key_path)
        if not parsed:
            log_system_response("registry.status", command=f"query {spec.key_path} {spec.name}", returncode="invalid_path", stdout=result, context={"registry_path": spec.key_path, "value": spec.name}, level="WARNING")
            return result
        hive, subkey, _short = parsed
        try:
            flags = WindowsOps._registry_access_flags(winreg.KEY_READ, spec.key_path)  # type: ignore[union-attr]
            with winreg.OpenKey(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                value, _actual_type = winreg.QueryValueEx(key, spec.name)  # type: ignore[union-attr]
            current_norm = WindowsOps._normalize_registry_value(value, spec.reg_type)
            desired_norm = WindowsOps._normalize_registry_value(spec.desired, spec.reg_type)
            result.update({
                "current": value,
                "current_display": WindowsOps.format_registry_value(value, spec.reg_type),
                "matches": current_norm == desired_norm,
                "status": "ok" if current_norm == desired_norm else "different",
            })
        except FileNotFoundError:
            result["status"] = "missing"
        except PermissionError:
            result["status"] = "access_denied"
        except OSError:
            result["status"] = "missing"
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
        log_system_response(
            "registry.status",
            command=f"query {spec.key_path} {spec.name}",
            returncode=result.get("status"),
            stdout=result,
            stderr=result.get("error", ""),
            context={"matches": result.get("matches"), "requires_admin": result.get("requires_admin")},
            level="INFO" if result.get("status") in {"ok", "different", "missing"} else "WARNING",
        )
        return result

    @staticmethod
    def registry_statuses(specs: List[RegistryValueSpec]) -> List[Dict[str, Any]]:
        return [WindowsOps.registry_value_status(spec) for spec in specs or []]

    @staticmethod
    def apply_registry_values(specs: List[RegistryValueSpec]) -> List[bool]:
        results: List[bool] = []
        for spec in specs or []:
            if spec.requires_admin and not WindowsOps.is_admin():
                continue
            results.append(WindowsOps.reg_add(spec.key_path, spec.name, spec.desired, spec.reg_type))
        return results

    @staticmethod
    def reg_add(path: str, name: str, value: Union[int, str], reg_type: str = "REG_DWORD") -> bool:
        """Set a registry value safely.

        Prefer winreg over `reg add` shell strings.  This avoids quoting bugs and
        command parsing problems with localized values while still falling back
        to reg.exe when winreg is unavailable.
        """
        value_type = (reg_type or "REG_DWORD").upper()
        parsed = WindowsOps._split_registry_path(path)
        if parsed and winreg is not None:
            hive, subkey, _short = parsed
            try:
                flags = WindowsOps._registry_access_flags(winreg.KEY_SET_VALUE | winreg.KEY_CREATE_SUB_KEY, path)  # type: ignore[union-attr]
                with winreg.CreateKeyEx(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                    if value_type == "REG_DWORD":
                        normalized = WindowsOps._normalize_registry_value(value, value_type)
                        if not isinstance(normalized, int):
                            return False
                        winreg.SetValueEx(key, name, 0, winreg.REG_DWORD, normalized)  # type: ignore[union-attr]
                    elif value_type == "REG_EXPAND_SZ":
                        winreg.SetValueEx(key, name, 0, winreg.REG_EXPAND_SZ, str(value))  # type: ignore[union-attr]
                    else:
                        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, str(value))  # type: ignore[union-attr]
                log_system_response(
                    "registry.write",
                    command=f"set {path} {name}",
                    returncode="ok",
                    stdout={"path": path, "name": name, "value": value, "type": value_type, "api": "winreg"},
                    context={"api": "winreg"},
                )
                return True
            except Exception as exc:
                log_system_response(
                    "registry.write",
                    command=f"set {path} {name}",
                    returncode="winreg_exception",
                    stderr=str(exc),
                    context={"api": "winreg", "fallback": "reg.exe"},
                    level="WARNING",
                )
                # Fall through to reg.exe. Some locked-down systems allow the
                # command-line tool when direct API calls are restricted.
                pass

        safe_value = str(value)
        return WindowsOps.run_command_args(
            ["reg.exe", "add", path, "/v", name, "/t", value_type, "/d", safe_value, "/f"],
            timeout=45,
        )

    @staticmethod
    def _query_registry_value(key_path: str, value_name: str = "") -> Optional[Any]:
        parsed = WindowsOps._split_registry_path(key_path)
        if not parsed or winreg is None:
            return None
        hive, subkey, _short = parsed
        try:
            flags = WindowsOps._registry_access_flags(winreg.KEY_READ, key_path)  # type: ignore[union-attr]
            with winreg.OpenKey(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                value, _kind = winreg.QueryValueEx(key, value_name or "")  # type: ignore[union-attr]
                return value
        except Exception:
            return None

    @staticmethod
    def _enum_registry_subkeys(key_path: str, limit: int = 10000) -> List[str]:
        parsed = WindowsOps._split_registry_path(key_path)
        if not parsed or winreg is None:
            return []
        hive, subkey, _short = parsed
        result: List[str] = []
        try:
            flags = WindowsOps._registry_access_flags(winreg.KEY_READ, key_path)  # type: ignore[union-attr]
            with winreg.OpenKey(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                index = 0
                while index < limit:
                    try:
                        result.append(str(winreg.EnumKey(key, index)))  # type: ignore[union-attr]
                        index += 1
                    except OSError:
                        break
        except Exception:
            return []
        return result

    @staticmethod
    def _enum_registry_values(key_path: str, limit: int = 1000) -> List[Tuple[str, Any]]:
        parsed = WindowsOps._split_registry_path(key_path)
        if not parsed or winreg is None:
            return []
        hive, subkey, _short = parsed
        values: List[Tuple[str, Any]] = []
        try:
            flags = WindowsOps._registry_access_flags(winreg.KEY_READ, key_path)  # type: ignore[union-attr]
            with winreg.OpenKey(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                index = 0
                while index < limit:
                    try:
                        name, value, _kind = winreg.EnumValue(key, index)  # type: ignore[union-attr]
                        values.append((str(name), value))
                        index += 1
                    except OSError:
                        break
        except Exception:
            return []
        return values

    @staticmethod
    def _delete_registry_value(key_path: str, value_name: str) -> bool:
        parsed = WindowsOps._split_registry_path(key_path)
        if not parsed or winreg is None:
            return False
        hive, subkey, _short = parsed
        try:
            flags = WindowsOps._registry_access_flags(winreg.KEY_SET_VALUE, key_path)  # type: ignore[union-attr]
            with winreg.OpenKey(hive, subkey, 0, flags) as key:  # type: ignore[union-attr]
                winreg.DeleteValue(key, value_name)  # type: ignore[union-attr]
            return True
        except FileNotFoundError:
            return True
        except Exception:
            return False

    @staticmethod
    def _delete_registry_tree(key_path: str) -> bool:
        parsed = WindowsOps._split_registry_path(key_path)
        if not parsed or winreg is None:
            return False
        hive, subkey, _short = parsed

        def delete_subtree(relative_subkey: str) -> bool:
            full = key_path.split("\\", 1)[0] + "\\" + relative_subkey
            try:
                flags = WindowsOps._registry_access_flags(winreg.KEY_READ | winreg.KEY_WRITE, full)  # type: ignore[union-attr]
                with winreg.OpenKey(hive, relative_subkey, 0, flags) as key:  # type: ignore[union-attr]
                    children: List[str] = []
                    index = 0
                    while True:
                        try:
                            children.append(str(winreg.EnumKey(key, index)))  # type: ignore[union-attr]
                            index += 1
                        except OSError:
                            break
                ok = True
                for child in children:
                    ok = delete_subtree(relative_subkey + "\\" + child) and ok
                try:
                    try:
                        winreg.DeleteKeyEx(hive, relative_subkey, WindowsOps._registry_access_flags(0, full), 0)  # type: ignore[attr-defined, union-attr]
                    except AttributeError:
                        winreg.DeleteKey(hive, relative_subkey)  # type: ignore[union-attr]
                    return ok
                except FileNotFoundError:
                    return ok
                except Exception:
                    return False
            except FileNotFoundError:
                return True
            except Exception:
                return False

        return delete_subtree(subkey)

    @staticmethod
    def _extract_executable_from_command(command: Any) -> Optional[str]:
        text = str(command or "").strip()
        if not text:
            return None
        text = os.path.expandvars(text).strip()
        if text.startswith("@"):
            text = text[1:].strip()
        # Registry command strings often contain icon suffixes or arguments.
        if text.startswith('"'):
            end = text.find('"', 1)
            candidate = text[1:end] if end > 1 else text.strip('"')
        else:
            match = re.search(r"(?i)([a-z]:\\[^\"<>|]+?\.(?:exe|com|bat|cmd|msi))", text)
            if match:
                candidate = match.group(1)
            else:
                token = text.split()[0] if text.split() else ""
                candidate = token.strip('"')
        candidate = candidate.strip().strip('"').strip()
        if not candidate:
            return None
        # Icon strings can look like C:\app\app.exe,0
        candidate = re.sub(r"(?i)(\.(?:exe|com|bat|cmd|msi)),.*$", r"\1", candidate)
        return candidate or None

    @staticmethod
    def _registry_command_is_dynamic_or_system(command: Any) -> bool:
        text = str(command or "").strip().lower()
        if not text:
            return False
        dynamic_tokens = ("rundll32", "regsvr32", "msiexec", "explorer.exe", "cmd.exe", "powershell", "pwsh.exe", "wscript", "cscript")
        if any(token in text for token in dynamic_tokens):
            return True
        if text.startswith(("ms-settings:", "shell:", "windowsdefender:", "http:", "https:")):
            return True
        return False

    @staticmethod
    def _executable_exists_for_registry(candidate: Optional[str]) -> bool:
        if not candidate:
            return False
        expanded = os.path.expandvars(str(candidate).strip().strip('"'))
        if not expanded:
            return False
        try:
            if os.path.isabs(expanded):
                return os.path.exists(expanded)
        except Exception:
            pass
        try:
            if shutil.which(expanded):
                return True
        except Exception:
            pass
        name = os.path.basename(expanded)
        if not name:
            return False
        roots = [
            os.environ.get("WINDIR", r"C:\Windows"),
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "System32"),
            os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "SysWOW64"),
        ] + PathFinder.get_program_files_paths()
        for root in roots:
            if not root:
                continue
            try:
                if os.path.exists(os.path.join(root, name)):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def find_registry_leftover_candidates(include_machine: bool = False, limit: int = 8000) -> Dict[str, List[Dict[str, str]]]:
        """Find conservative registry leftovers without touching COM/driver/service keys.

        Scope is intentionally narrow:
        - stale Open With app registrations under Software\\Classes\\Applications;
        - stale App Paths entries;
        - broken Run/RunOnce startup values.
        """
        delete_keys: List[Dict[str, str]] = []
        delete_values: List[Dict[str, str]] = []
        scanned = 0

        def add_key(path: str, reason: str) -> None:
            nonlocal scanned
            if scanned >= limit:
                return
            scanned += 1
            delete_keys.append({"path": path, "reason": reason})

        def add_value(path: str, name: str, reason: str) -> None:
            nonlocal scanned
            if scanned >= limit:
                return
            scanned += 1
            delete_values.append({"path": path, "name": name, "reason": reason})

        scopes = ["HKCU"]
        if include_machine:
            scopes.append("HKLM")

        for hive in scopes:
            apps_base = hive + r"\Software\Classes\Applications"
            for app_name in WindowsOps._enum_registry_subkeys(apps_base, limit=limit):
                if scanned >= limit:
                    break
                if not app_name.lower().endswith((".exe", ".com", ".bat", ".cmd")):
                    continue
                app_key = apps_base + "\\" + app_name
                command = WindowsOps._query_registry_value(app_key + r"\shell\open\command", "")
                if command and WindowsOps._registry_command_is_dynamic_or_system(command):
                    continue
                exe = WindowsOps._extract_executable_from_command(command) if command else app_name
                if exe and not WindowsOps._executable_exists_for_registry(exe):
                    add_key(app_key, "missing application executable")

            app_paths_base = hive + r"\SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
            for app_name in WindowsOps._enum_registry_subkeys(app_paths_base, limit=limit):
                if scanned >= limit:
                    break
                app_key = app_paths_base + "\\" + app_name
                default_path = WindowsOps._query_registry_value(app_key, "")
                exe = WindowsOps._extract_executable_from_command(default_path) if default_path else app_name
                if exe and not WindowsOps._executable_exists_for_registry(exe):
                    add_key(app_key, "missing App Paths executable")

            for run_subkey in (
                r"\Software\Microsoft\Windows\CurrentVersion\Run",
                r"\Software\Microsoft\Windows\CurrentVersion\RunOnce",
            ):
                run_key = hive + run_subkey
                for name, command in WindowsOps._enum_registry_values(run_key, limit=1000):
                    if scanned >= limit:
                        break
                    if not name or WindowsOps._registry_command_is_dynamic_or_system(command):
                        continue
                    exe = WindowsOps._extract_executable_from_command(command)
                    if exe and not WindowsOps._executable_exists_for_registry(exe):
                        add_value(run_key, name, "missing startup executable")

        return {"delete_keys": delete_keys, "delete_values": delete_values}

    @staticmethod
    def cleanup_registry_leftovers(include_machine: bool = False) -> Dict[str, Any]:
        candidates = WindowsOps.find_registry_leftover_candidates(include_machine=include_machine)
        key_items = list(candidates.get("delete_keys") or [])
        value_items = list(candidates.get("delete_values") or [])
        backup_keys: List[str] = []
        for item in key_items:
            path = item.get("path") or ""
            if path and path not in backup_keys:
                backup_keys.append(path)
        for item in value_items:
            path = item.get("path") or ""
            if path and path not in backup_keys:
                backup_keys.append(path)

        backup_dir = ""
        if backup_keys:
            backup_dir = WindowsOps.backup_registry_keys(backup_keys) or ""
            if not backup_dir:
                return {
                    "found": len(key_items) + len(value_items),
                    "removed": 0,
                    "failed": len(key_items) + len(value_items),
                    "backup": "",
                    "keys_removed": 0,
                    "values_removed": 0,
                }

        keys_removed = 0
        values_removed = 0
        failed = 0
        # Values first, then whole orphan keys.
        for item in value_items:
            if WindowsOps._delete_registry_value(item.get("path", ""), item.get("name", "")):
                values_removed += 1
            else:
                failed += 1
        for item in key_items:
            if WindowsOps._delete_registry_tree(item.get("path", "")):
                keys_removed += 1
            else:
                failed += 1
        return {
            "found": len(key_items) + len(value_items),
            "removed": keys_removed + values_removed,
            "failed": failed,
            "backup": backup_dir,
            "keys_removed": keys_removed,
            "values_removed": values_removed,
        }

    @staticmethod
    def open_in_file_manager(path: str) -> bool:
        try:
            if not path:
                return False
            if IS_WINDOWS:
                os.startfile(os.path.abspath(path))  # type: ignore[attr-defined]
                return True
            return False
        except Exception:
            return False

    @staticmethod
    def open_url(url: str) -> bool:
        try:
            target = (url or '').strip()
            if not target:
                return False
            if IS_WINDOWS:
                os.startfile(target)  # type: ignore[attr-defined]
                return True
            return bool(webbrowser.open(target))
        except Exception:
            try:
                return bool(webbrowser.open(url))
            except Exception:
                return False


    @staticmethod
    def _obs_root() -> str:
        return os.path.join(os.environ.get("APPDATA", ""), "obs-studio") if os.environ.get("APPDATA", "") else ""

    @staticmethod
    def _read_ini_file(path: str) -> configparser.ConfigParser:
        parser = configparser.ConfigParser(strict=False, interpolation=None)
        parser.optionxform = str  # preserve OBS key case for cleaner display/fallbacks
        for encoding in ("utf-8-sig", "utf-8", "mbcs"):
            try:
                with open(path, "r", encoding=encoding, errors="replace") as fh:
                    parser.read_file(fh)
                return parser
            except Exception:
                continue
        return parser

    @staticmethod
    def _cfg_get(parser: configparser.ConfigParser, candidates: List[Tuple[str, str]], default: str = "") -> str:
        for section, key in candidates:
            try:
                if parser.has_option(section, key):
                    return str(parser.get(section, key)).strip()
            except Exception:
                continue
        return default

    @staticmethod
    def _cfg_bool(parser: configparser.ConfigParser, candidates: List[Tuple[str, str]]) -> bool:
        raw = WindowsOps._cfg_get(parser, candidates, "")
        return str(raw).strip().casefold() in {"1", "true", "yes", "on", "enabled"}

    @staticmethod
    def discover_obs_profiles() -> List[Dict[str, Any]]:
        """Read OBS profile metadata without modifying profiles, scenes or sources."""
        root = os.path.join(WindowsOps._obs_root(), "basic", "profiles")
        profiles: List[Dict[str, Any]] = []
        if not root or not os.path.isdir(root):
            return profiles
        try:
            names = sorted(os.listdir(root))
        except OSError:
            return profiles
        for name in names:
            folder = os.path.join(root, name)
            ini_path = os.path.join(folder, "basic.ini")
            if not os.path.isdir(folder) or not os.path.isfile(ini_path):
                continue
            parser = WindowsOps._read_ini_file(ini_path)
            output_mode = WindowsOps._cfg_get(parser, [("Output", "Mode")], "")
            stream_encoder = WindowsOps._cfg_get(parser, [
                ("AdvOut", "Encoder"),
                ("AdvOut", "StreamEncoder"),
                ("SimpleOutput", "StreamEncoder"),
                ("SimpleOutput", "Encoder"),
            ], "")
            record_encoder = WindowsOps._cfg_get(parser, [
                ("AdvOut", "RecEncoder"),
                ("AdvOut", "RecEncoder2"),
                ("SimpleOutput", "RecEncoder"),
                ("SimpleOutput", "RecEncoder2"),
            ], "")
            record_format = WindowsOps._cfg_get(parser, [
                ("AdvOut", "RecFormat2"),
                ("AdvOut", "RecFormat"),
                ("SimpleOutput", "RecFormat2"),
                ("SimpleOutput", "RecFormat"),
            ], "")
            record_path = WindowsOps._cfg_get(parser, [
                ("AdvOut", "RecFilePath"),
                ("SimpleOutput", "FilePath"),
                ("SimpleOutput", "RecFilePath"),
            ], "")
            replay_buffer = WindowsOps._cfg_bool(parser, [
                ("AdvOut", "RecRB"),
                ("AdvOut", "ReplayBuffer"),
                ("SimpleOutput", "RecRB"),
                ("SimpleOutput", "ReplayBuffer"),
                ("ReplayBuffer", "Enable"),
                ("ReplayBuffer", "Enabled"),
            ])
            profiles.append({
                "name": name,
                "path": folder,
                "ini": ini_path,
                "output_mode": output_mode or "unknown",
                "stream_encoder": stream_encoder or "unknown",
                "record_encoder": record_encoder or "unknown",
                "record_format": (record_format or "unknown").lower(),
                "record_path": os.path.expandvars(record_path) if record_path else "",
                "replay_buffer": replay_buffer,
            })
        return profiles

    @staticmethod
    def _encoder_kind(encoder: str) -> str:
        name = (encoder or "").casefold()
        if not name or name == "unknown":
            return "unknown"
        if any(token in name for token in ("nvenc", "qsv", "amf", "vce", "vaapi", "videotoolbox", "av1", "hevc", "h264_texture")):
            return "hardware"
        if "x264" in name or "x265" in name:
            return "cpu"
        return "unknown"

    @staticmethod
    def latest_obs_log_issues(max_logs: int = 3) -> List[Dict[str, Any]]:
        logs_dir = PathFinder._safe_join(WindowsOps._obs_root(), "logs")
        if not logs_dir or not os.path.isdir(logs_dir):
            return []
        try:
            files = [
                os.path.join(logs_dir, name)
                for name in os.listdir(logs_dir)
                if name.lower().endswith((".txt", ".log"))
            ]
        except OSError:
            return []
        files.sort(key=lambda item: os.path.getmtime(item), reverse=True)
        patterns: List[Tuple[str, re.Pattern[str]]] = [
            ("encoding_overload", re.compile(r"encoding overloaded|encoder overloaded|skipped frames due to encoding lag", re.I)),
            ("rendering_lag", re.compile(r"lagged frames due to rendering lag|rendering lag|rendering stalls", re.I)),
            ("dropped_frames", re.compile(r"dropped frames.*(?:insufficient bandwidth|connection stalls|network)|network.*dropped frames", re.I)),
            ("nvenc_error", re.compile(r"nvenc error|failed to open nvenc|no nvenc capable devices|nvenc.*failed", re.I)),
            ("recording_failure", re.compile(r"recording.*(?:failed|stopped unexpectedly)|failed to start recording", re.I)),
        ]
        issues: List[Dict[str, Any]] = []
        for path in files[:max_logs]:
            try:
                size = os.path.getsize(path)
                with open(path, "rb") as fh:
                    if size > 384 * 1024:
                        fh.seek(max(0, size - 384 * 1024))
                    text = fh.read().decode("utf-8", errors="replace")
            except Exception:
                continue
            for kind, pattern in patterns:
                matches = pattern.findall(text)
                if matches:
                    issues.append({"kind": kind, "count": len(matches), "log": os.path.basename(path)})
        return issues

    @staticmethod
    def latest_obs_log_activity(max_logs: int = 2) -> Dict[str, bool]:
        logs_dir = PathFinder._safe_join(WindowsOps._obs_root(), "logs")
        activity = {"stream": False, "record": False, "replay": False}
        if not logs_dir or not os.path.isdir(logs_dir):
            return activity
        try:
            files = [os.path.join(logs_dir, name) for name in os.listdir(logs_dir) if name.lower().endswith((".txt", ".log"))]
            files.sort(key=lambda item: os.path.getmtime(item), reverse=True)
        except OSError:
            return activity
        checks = {
            "stream": re.compile(r"streaming.*(?:start|started)|output '.*stream.*'", re.I),
            "record": re.compile(r"recording.*(?:start|started)|output '.*(?:record|file).*'", re.I),
            "replay": re.compile(r"replay buffer.*(?:start|started)|output '.*replay.*'", re.I),
        }
        for path in files[:max_logs]:
            try:
                with open(path, "rb") as fh:
                    text = fh.read(512 * 1024).decode("utf-8", errors="replace")
            except Exception:
                continue
            for key, pattern in checks.items():
                if pattern.search(text):
                    activity[key] = True
        return activity

    @staticmethod
    def _sample_cpu_load(delay: float = 0.35) -> Optional[float]:
        first = _get_windows_cpu_times()
        if not first:
            return None
        time.sleep(max(0.05, min(1.0, delay)))
        second = _get_windows_cpu_times()
        if not second:
            return None
        idle_delta = second[0] - first[0]
        total_delta = second[1] - first[1]
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (1.0 - (float(idle_delta) / float(total_delta)))))

    @staticmethod
    def _sample_gpu_load() -> Optional[float]:
        if not IS_WINDOWS:
            return None
        ps = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
        if not ps:
            return None
        command = (
            "$samples=(Get-Counter '\\GPU Engine(*)\\Utilization Percentage' -ErrorAction Stop).CounterSamples;"
            "$sum=($samples | Measure-Object -Property CookedValue -Sum).Sum;"
            "[math]::Round([double]$sum,1)"
        )
        rc, output = WindowsOps.run_command_capture([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command], timeout=10)
        if rc != 0:
            return None
        match = re.search(r"[-+]?\d+(?:[\.,]\d+)?", output or "")
        if not match:
            return None
        try:
            value = float(match.group(0).replace(",", "."))
            return max(0.0, min(100.0, value))
        except Exception:
            return None

    @staticmethod
    def quick_disk_write_test(preferred_folder: str = "", size_mb: int = 64) -> Dict[str, Any]:
        folder = preferred_folder or tempfile.gettempdir()
        folder = os.path.expandvars(folder)
        if folder and not os.path.isdir(folder):
            folder = os.path.dirname(folder)
        if not folder or not os.path.isdir(folder):
            folder = tempfile.gettempdir()
        size_mb = max(8, min(256, int(size_mb or 64)))
        path = ""
        started = time.perf_counter()
        try:
            fd, path = tempfile.mkstemp(prefix="freecleaner_disk_test_", suffix=".tmp", dir=folder)
            chunk = b"0" * (4 * 1024 * 1024)
            remaining = size_mb * 1024 * 1024
            with os.fdopen(fd, "wb", buffering=0) as fh:
                while remaining > 0:
                    part = chunk if remaining >= len(chunk) else chunk[:remaining]
                    fh.write(part)
                    remaining -= len(part)
                try:
                    os.fsync(fh.fileno())
                except Exception:
                    pass
            elapsed = max(0.001, time.perf_counter() - started)
            mbps = float(size_mb) / elapsed
            return {"ok": True, "folder": folder, "size_mb": size_mb, "mbps": mbps}
        except Exception as exc:
            return {"ok": False, "folder": folder, "error": str(exc)}
        finally:
            if path:
                try:
                    os.remove(path)
                except Exception:
                    pass

    @staticmethod
    def find_onedrive_executables() -> List[str]:
        candidates: List[str] = []
        local = os.environ.get("LOCALAPPDATA", "")
        if local:
            candidates.append(PathFinder._safe_join(local, r"Microsoft\OneDrive\OneDrive.exe"))
        for root in PathFinder.get_program_files_paths():
            candidates.append(PathFinder._safe_join(root, r"Microsoft OneDrive\OneDrive.exe"))
        seen: Set[str] = set()
        result: List[str] = []
        for path in candidates:
            if not path:
                continue
            expanded = PathFinder.expand(path)
            key = os.path.normcase(os.path.abspath(expanded))
            if key in seen:
                continue
            seen.add(key)
            if os.path.isfile(expanded):
                result.append(expanded)
        return result

    @staticmethod
    def is_process_running(image_name: str) -> bool:
        if not IS_WINDOWS or not image_name:
            return False
        rc, output = WindowsOps.run_command_capture(["tasklist.exe", "/FI", f"IMAGENAME eq {image_name}"], timeout=15)
        return rc == 0 and image_name.casefold() in (output or "").casefold()

    @staticmethod
    def collect_onedrive_report() -> Dict[str, Any]:
        """Collect read-only OneDrive state without touching sync folders."""
        local = os.environ.get("LOCALAPPDATA", "")
        one_root = PathFinder._safe_join(local, r"Microsoft\OneDrive") if local else ""
        run_value = WindowsOps._query_registry_value(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "OneDrive")
        policy_value = WindowsOps._query_registry_value(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\OneDrive", "DisableFileSyncNGSC")
        files_on_demand = WindowsOps._query_registry_value(r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer", "SyncRootManager")
        targets = [path for _key, _tkey, _dkey, path, _fmt in PathFinder.get_onedrive_cleanup_targets()]
        cache_bytes = 0
        try:
            cache_bytes = SafeFS.fast_size_many(targets, threading.Event()) if targets else 0
        except Exception:
            cache_bytes = 0
        return {
            "installed": bool(WindowsOps.find_onedrive_executables() or os.path.isdir(one_root)),
            "running": WindowsOps.is_process_running("OneDrive.exe"),
            "executables": WindowsOps.find_onedrive_executables(),
            "user_autostart": "enabled" if run_value else "disabled",
            "policy_sync": "disabled" if WindowsOps._normalize_registry_value(policy_value, "REG_DWORD") == 1 else ("enabled" if WindowsOps._normalize_registry_value(policy_value, "REG_DWORD") == 0 else "unknown"),
            "files_on_demand_hint": "available" if files_on_demand is not None else "unknown",
            "cleanup_targets": len(targets),
            "cleanup_bytes": cache_bytes,
        }

    @staticmethod
    def quit_onedrive() -> bool:
        if not IS_WINDOWS:
            return False
        ok = False
        for exe in WindowsOps.find_onedrive_executables():
            # /shutdown is supported by the sync client on current builds; if it
            # is ignored, taskkill below is the fallback.
            try:
                subprocess.run([exe, "/shutdown"], shell=False, timeout=12, **WindowsOps.hidden_subprocess_kwargs())
                ok = True
            except Exception:
                pass
        time.sleep(0.6)
        if WindowsOps.is_process_running("OneDrive.exe"):
            ok = WindowsOps.run_command_args(["taskkill.exe", "/IM", "OneDrive.exe", "/F"], timeout=20) or ok
        return ok or not WindowsOps.is_process_running("OneDrive.exe")

    @staticmethod
    def disable_onedrive_background() -> Dict[str, Any]:
        """Stop OneDrive and disable its startup/sync policy when allowed.

        User data and sync folders are intentionally untouched.  HKLM policy is
        only written with admin rights; user autostart is removed for the current
        user without requiring admin rights.
        """
        result = {"quit": False, "autostart_removed": False, "policy_disabled": False, "admin_policy_skipped": False}
        result["quit"] = WindowsOps.quit_onedrive()
        result["autostart_removed"] = WindowsOps._delete_registry_value(r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run", "OneDrive")
        if WindowsOps.is_admin():
            result["policy_disabled"] = WindowsOps.reg_add(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\OneDrive", "DisableFileSyncNGSC", 1, "REG_DWORD")
        else:
            result["admin_policy_skipped"] = True
        return result

    @staticmethod
    def restore_onedrive_background() -> Dict[str, Any]:
        result = {"policy_removed": False, "started": False}
        if WindowsOps.is_admin():
            result["policy_removed"] = WindowsOps._delete_registry_value(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\OneDrive", "DisableFileSyncNGSC")
        for exe in WindowsOps.find_onedrive_executables():
            try:
                subprocess.Popen([exe, "/background"], **WindowsOps.hidden_subprocess_kwargs())
                result["started"] = True
                break
            except Exception:
                continue
        return result

    @staticmethod
    def collect_streaming_diagnostics() -> Dict[str, Any]:
        """Collect a read-only streaming/OBS diagnostic report."""
        profiles = WindowsOps.discover_obs_profiles()
        primary_record_folder = ""
        for profile in profiles:
            record_path = str(profile.get("record_path") or "")
            if record_path and os.path.isdir(record_path):
                primary_record_folder = record_path
                break
        result: Dict[str, Any] = {
            "obs_profiles": profiles,
            "obs_log_issues": WindowsOps.latest_obs_log_issues(),
            "obs_log_activity": WindowsOps.latest_obs_log_activity(),
            "cpu_load": WindowsOps._sample_cpu_load(),
            "ram_load": get_memory_load_percent(),
            "gpu_load": WindowsOps._sample_gpu_load(),
            "disk_write": WindowsOps.quick_disk_write_test(primary_record_folder or tempfile.gettempdir(), 64),
        }
        return result

    @staticmethod
    def _registry_bool_state(key_path: str, value_name: str, enabled_value: Any = 1, disabled_value: Any = 0) -> str:
        value = WindowsOps._query_registry_value(key_path, value_name)
        if value is None:
            return "unknown"
        normalized = WindowsOps._normalize_registry_value(value, "REG_DWORD")
        enabled_norm = WindowsOps._normalize_registry_value(enabled_value, "REG_DWORD")
        disabled_norm = WindowsOps._normalize_registry_value(disabled_value, "REG_DWORD")
        if normalized == enabled_norm:
            return "enabled"
        if normalized == disabled_norm:
            return "disabled"
        return "custom"

    @staticmethod
    def read_gpu_preferences(limit: int = 80) -> List[Dict[str, str]]:
        """Read Windows per-app GPU preferences without changing them."""
        result: List[Dict[str, str]] = []
        key_path = r"HKCU\Software\Microsoft\DirectX\UserGpuPreferences"
        for app_path, raw_value in WindowsOps._enum_registry_values(key_path, limit=limit):
            raw = str(raw_value or "")
            match = re.search(r"GpuPreference\s*=\s*(\d+)", raw, re.I)
            pref = match.group(1) if match else "unknown"
            label = {
                "0": "system_default",
                "1": "power_saving",
                "2": "high_performance",
            }.get(pref, "unknown")
            result.append({
                "path": str(app_path),
                "name": os.path.basename(str(app_path).strip('"')) or str(app_path),
                "preference": label,
                "raw": raw,
            })
        return result

    @staticmethod
    def summarize_gpu_preferences(entries: List[Dict[str, str]]) -> Dict[str, Any]:
        relevant_tokens = ("obs", "wow", "warcraft", "battle.net", "streamlabs", "twitch", "xsplit", "minecraft", "javaw", "steam", "discord")
        relevant: List[Dict[str, str]] = []
        for item in entries or []:
            hay = f"{item.get('path','')} {item.get('name','')}".casefold()
            if any(token in hay for token in relevant_tokens):
                relevant.append(item)
        high = sum(1 for item in relevant if item.get("preference") == "high_performance")
        low = sum(1 for item in relevant if item.get("preference") == "power_saving")
        default = sum(1 for item in relevant if item.get("preference") == "system_default")
        return {"relevant": relevant[:12], "high": high, "power_saving": low, "system_default": default, "total_relevant": len(relevant)}

    @staticmethod
    def collect_gaming_compat_report() -> Dict[str, Any]:
        """Collect read-only gaming/streaming compatibility hints.

        The report is intentionally diagnostic.  It does not apply registry,
        powercfg or BCDEdit changes, so it is safe to run before choosing tweaks.
        """
        report: Dict[str, Any] = {
            "windows_version": ".".join(str(part) for part in get_windows_version()) if IS_WINDOWS else sys.platform,
            "process_arch": get_process_architecture(),
            "os_arch": get_os_architecture(),
            "active_power_scheme": "unknown",
            "game_mode": "unknown",
            "game_dvr": "unknown",
            "hags": "unsupported",
            "power_throttling": "unknown",
            "dynamic_tick": "unknown",
            "gpu_preferences": [],
            "gpu_preference_summary": {"relevant": [], "high": 0, "power_saving": 0, "system_default": 0, "total_relevant": 0},
            "notes": [],
        }
        notes: List[str] = report["notes"]
        if not IS_WINDOWS:
            notes.append("gaming_report_note_windows_only")
            return report

        gpu_preferences = WindowsOps.read_gpu_preferences()
        report["gpu_preferences"] = gpu_preferences
        report["gpu_preference_summary"] = WindowsOps.summarize_gpu_preferences(gpu_preferences)

        active_scheme = WindowsOps.active_power_scheme_guid(timeout=30)
        if active_scheme:
            report["active_power_scheme"] = active_scheme

        # Game Mode is controlled per user by GameBar keys.  Missing keys mean
        # Windows will use defaults, so we avoid claiming a hard enabled state.
        mode_values = [
            WindowsOps._registry_bool_state(r"HKCU\Software\Microsoft\GameBar", "AllowAutoGameMode", 1, 0),
            WindowsOps._registry_bool_state(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, 0),
        ]
        if "disabled" in mode_values:
            report["game_mode"] = "disabled"
        elif all(value == "enabled" for value in mode_values):
            report["game_mode"] = "enabled"
        else:
            report["game_mode"] = "unknown"

        # Windows capture/background recording can conflict with OBS recording.
        capture_values = [
            WindowsOps._registry_bool_state(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 1, 0),
            WindowsOps._registry_bool_state(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "HistoricalCaptureEnabled", 1, 0),
            WindowsOps._registry_bool_state(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 1, 0),
        ]
        policy_state = WindowsOps._registry_bool_state(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 1, 0)
        if policy_state == "disabled" or all(value == "disabled" for value in capture_values if value != "unknown"):
            report["game_dvr"] = "disabled"
        elif "enabled" in capture_values or policy_state == "enabled":
            report["game_dvr"] = "enabled"
            notes.append("gaming_report_note_capture_enabled")
        else:
            report["game_dvr"] = "unknown"

        if WindowsOps.supports_hags():
            hags_value = WindowsOps._query_registry_value(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
            normalized = WindowsOps._normalize_registry_value(hags_value, "REG_DWORD") if hags_value is not None else None
            if normalized == 2:
                report["hags"] = "enabled"
            elif normalized == 1:
                report["hags"] = "disabled"
            elif normalized is None:
                report["hags"] = "unknown"
            else:
                report["hags"] = "custom"
        else:
            notes.append("gaming_report_note_hags_unsupported")

        power_value = WindowsOps._query_registry_value(r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff")
        normalized_power = WindowsOps._normalize_registry_value(power_value, "REG_DWORD") if power_value is not None else None
        if normalized_power == 1:
            report["power_throttling"] = "disabled"
        elif normalized_power == 0:
            report["power_throttling"] = "enabled"
        else:
            report["power_throttling"] = "unknown"

        rc, output = WindowsOps.bcdedit_current_output(timeout=30)
        lowered = (output or "").casefold()
        if rc == 0 and "disabledynamictick" in lowered:
            if re.search(r"disabledynamictick\s+yes", lowered):
                report["dynamic_tick"] = "disabled"
                notes.append("gaming_report_note_dynamic_tick_custom")
            elif re.search(r"disabledynamictick\s+no", lowered):
                report["dynamic_tick"] = "enabled"
            else:
                report["dynamic_tick"] = "custom"
        elif rc == 0:
            report["dynamic_tick"] = "default"

        if is_32bit_process_on_64bit_windows():
            notes.append("gaming_report_note_wow64")
        if not WindowsOps.is_admin():
            notes.append("gaming_report_note_admin_limited")
        return report

    @staticmethod
    def registry_backup_root() -> str:
        root = os.path.join(get_user_data_dir(create=True), REGISTRY_BACKUP_DIRNAME)
        os.makedirs(root, exist_ok=True)
        return root

    @staticmethod
    def backup_registry_keys(keys: List[str]) -> Optional[str]:
        if not IS_WINDOWS or not keys:
            return None
        unique_keys: List[str] = []
        seen = set()
        for key in keys:
            clean = (key or '').strip()
            if clean and clean not in seen:
                seen.add(clean)
                unique_keys.append(clean)
        if not unique_keys:
            return None

        root = WindowsOps.registry_backup_root()
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        folder = os.path.join(root, f'backup_{stamp}')
        os.makedirs(folder, exist_ok=True)

        manifest_lines = []
        for index, key in enumerate(unique_keys, start=1):
            safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', key).strip('_')[:90] or f'key_{index}'
            target = os.path.join(folder, f'{index:02d}_{safe_name}.reg')
            ok = WindowsOps.run_command_args(["reg.exe", "export", key, target, "/y"], timeout=45)
            status = "ok" if ok and os.path.isfile(target) else "missing"
            manifest_lines.append(f'{key}={status}')

        try:
            with open(os.path.join(folder, 'manifest.txt'), 'w', encoding='utf-8') as fh:
                fh.write('\n'.join(manifest_lines))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            return None

        # A backup where every key was missing is still useful: restore can
        # delete keys created by an optimizer action and return to the original
        # "not configured" state.
        return folder if manifest_lines else None

    @staticmethod
    def latest_registry_backup_dir() -> Optional[str]:
        backups = WindowsOps.list_registry_backups()
        return backups[0]["path"] if backups else None

    @staticmethod
    def list_registry_backups() -> List[Dict[str, Any]]:
        root = os.path.join(get_user_data_dir(create=True), REGISTRY_BACKUP_DIRNAME)
        if not os.path.isdir(root):
            return []
        items: List[Dict[str, Any]] = []
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isdir(path):
                continue
            try:
                entries = os.listdir(path)
            except OSError:
                continue
            reg_files = sorted(
                os.path.join(path, entry)
                for entry in entries
                if entry.lower().endswith('.reg')
            )
            manifest = os.path.join(path, 'manifest.txt')
            if not reg_files and not os.path.isfile(manifest):
                continue
            created = datetime.fromtimestamp(os.path.getmtime(path)).strftime('%Y-%m-%d %H:%M:%S')
            kind = 'pre_restore' if name.lower().startswith('pre_restore_') else 'backup'
            items.append({
                'path': path,
                'name': name,
                'created': created,
                'kind': kind,
                'count': len(reg_files),
            })
        items.sort(key=lambda item: os.path.getmtime(item['path']), reverse=True)
        return items

    @staticmethod
    def has_registry_backup() -> bool:
        return bool(WindowsOps.list_registry_backups())

    @staticmethod
    def _read_registry_manifest_entries(folder: str) -> List[Tuple[str, str]]:
        manifest = os.path.join(folder, 'manifest.txt')
        entries: List[Tuple[str, str]] = []
        if not os.path.isfile(manifest):
            return entries
        try:
            with open(manifest, 'r', encoding='utf-8') as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or '=' not in line:
                        continue
                    key, status = line.split('=', 1)
                    key = key.strip()
                    status = status.strip().lower() or 'unknown'
                    if key:
                        entries.append((key, status))
        except Exception:
            return []
        return entries

    @staticmethod
    def _read_registry_manifest(folder: str) -> List[str]:
        return [key for key, _status in WindowsOps._read_registry_manifest_entries(folder)]

    @staticmethod
    def describe_registry_backup(folder: str) -> Dict[str, Any]:
        folder = os.path.abspath(folder)
        name = os.path.basename(folder)
        reg_files = sorted(
            os.path.join(folder, entry)
            for entry in os.listdir(folder)
            if entry.lower().endswith('.reg')
        ) if os.path.isdir(folder) else []
        created = datetime.fromtimestamp(os.path.getmtime(folder)).strftime('%Y-%m-%d %H:%M:%S') if os.path.isdir(folder) else ''
        kind = 'pre_restore' if name.lower().startswith('pre_restore_') else 'backup'
        manifest_path = os.path.join(folder, 'manifest.txt')
        manifest_text = ''
        if os.path.isfile(manifest_path):
            try:
                with open(manifest_path, 'r', encoding='utf-8') as fh:
                    manifest_text = fh.read().strip()
            except Exception:
                manifest_text = ''
        return {
            'path': folder,
            'name': name,
            'created': created,
            'count': len(reg_files),
            'kind': kind,
            'kind_label': 'Pre-restore snapshot' if kind == 'pre_restore' else 'Registry backup',
            'manifest_text': manifest_text,
        }

    @staticmethod
    def restore_registry_backup_dir(folder: str) -> bool:
        folder = os.path.abspath(folder)
        if not os.path.isdir(folder):
            return False
        reg_files = [os.path.join(folder, name) for name in os.listdir(folder) if name.lower().endswith('.reg')]
        reg_files.sort()
        manifest_entries = WindowsOps._read_registry_manifest_entries(folder)
        if not reg_files and not manifest_entries:
            return False

        keys = [key for key, _status in manifest_entries]
        if keys:
            root = WindowsOps.registry_backup_root()
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            snapshot = os.path.join(root, f'pre_restore_{stamp}')
            os.makedirs(snapshot, exist_ok=True)
            manifest_lines = []
            for index, key in enumerate(keys, start=1):
                safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', key).strip('_')[:90] or f'key_{index}'
                target = os.path.join(snapshot, f'{index:02d}_{safe_name}.reg')
                ok = WindowsOps.run_command_args(["reg.exe", "export", key, target, "/y"], timeout=45)
                manifest_lines.append(f'{key}={"ok" if ok and os.path.isfile(target) else "missing"}')
            try:
                with open(os.path.join(snapshot, 'manifest.txt'), 'w', encoding='utf-8') as fh:
                    fh.write('\n'.join(manifest_lines))
            except Exception:
                pass
            if not any(os.path.isfile(os.path.join(snapshot, name)) and name.lower().endswith('.reg') for name in os.listdir(snapshot)) and not manifest_lines:
                try:
                    shutil.rmtree(snapshot, ignore_errors=True)
                except Exception:
                    pass

        import_results = [WindowsOps.run_command_args(["reg.exe", "import", path], timeout=60) for path in reg_files]

        # Restore keys that did not exist before the backup by deleting them.
        # This makes first-run optimizer changes reversible even when the key was
        # created from scratch.
        missing_keys = [key for key, status in manifest_entries if status == 'missing']
        delete_results: List[bool] = []
        for key in missing_keys:
            deleted = WindowsOps.run_command_args(["reg.exe", "delete", key, "/f"], timeout=45)
            if not deleted:
                # `reg delete` returns an error when the key is already absent.
                # That is still a successful restore of the previous missing
                # state, so verify with `reg query` before reporting failure.
                deleted = not WindowsOps.run_command_args(["reg.exe", "query", key], timeout=30)
            delete_results.append(deleted)

        return all(import_results or [True]) and all(delete_results or [True])

    @staticmethod
    def restore_latest_registry_backup() -> bool:
        latest = WindowsOps.latest_registry_backup_dir()
        if not latest:
            return False
        return WindowsOps.restore_registry_backup_dir(latest)

    @staticmethod
    def supports_ms_settings() -> bool:
        return is_windows_at_least(10, 0, 10240)

    @staticmethod
    def supports_hags() -> bool:
        return is_windows_at_least(10, 0, 19041)

    @staticmethod
    def supports_power_throttling() -> bool:
        return is_windows_at_least(10, 0, 16299)

    @staticmethod
    def supports_ultimate_performance() -> bool:
        return is_windows_at_least(10, 0, 17134)

    @staticmethod
    def supports_windows_10_or_11() -> bool:
        return is_windows_at_least(10, 0, 10240)

    @staticmethod
    def supports_windows_11_features() -> bool:
        return is_windows_at_least(10, 0, 22000)

    @staticmethod
    def supports_dynamic_tick_toggle() -> bool:
        # FreeCleaner targets Windows 10/11.  BCDEdit supports the flag on older
        # systems too, but keeping the gate to the supported OS family avoids
        # offering low-level boot tweaks on unsupported setups.
        return WindowsOps.supports_windows_10_or_11()

    @staticmethod
    def parse_powercfg_numeric_value(output: str) -> Optional[int]:
        """Extract only an explicit AC setting value from powercfg output.

        Older builds used the last number found in the text as a fallback.  That
        is unsafe: on localized/OEM output without a real setting block it can
        pick numbers from the scheme GUID, for example the ``9685`` segment in a
        Balanced plan GUID, and then mark hidden CPU power settings as applied.
        """
        text = str(output or "")
        if not text.strip():
            return None
        patterns = (
            r"Current\s+AC\s+Power\s+Setting\s+Index\s*:\s*(0x[0-9a-fA-F]+|\d+)",
            r"Power\s+Setting\s+AC\s+Value\s+Index\s*:\s*(0x[0-9a-fA-F]+|\d+)",
            r"AC\s+Power\s+Setting\s+Index\s*:\s*(0x[0-9a-fA-F]+|\d+)",
        )
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                raw = match.group(1)
                try:
                    return int(raw, 16) if raw.lower().startswith("0x") else int(raw)
                except Exception:
                    return None
        return None

    @staticmethod
    def bcdedit_current_output(*, timeout: int = 45) -> Tuple[int, str]:
        """Return BCDEdit output for the current/default boot entry.

        Some Windows 11/localized builds reject `/enum {current}` with
        "specified entry type is invalid" even though plain `/enum` works.  For
        status detection this is optional, so failures are fully captured in
        system.log but do not pollute errors.log.
        """
        attempts = (
            ["bcdedit.exe", "/enum", "{current}"],
            ["bcdedit.exe", "/enum"],
            ["bcdedit.exe", "/enum", "all"],
        )
        last_rc, last_output = 1, ""
        for index, args in enumerate(attempts, 1):
            rc, output = WindowsOps.run_command_capture(
                args,
                timeout=timeout,
                log_failure=False,
                context={"feature": "bcdedit_status", "attempt": index, "optional": True},
            )
            last_rc, last_output = rc, output
            if rc == 0 and output:
                log_action({"bcdedit_status_probe_ok": {"attempt": index, "args": args}})
                return rc, output
            log_action({"bcdedit_status_probe_failed": {"attempt": index, "args": args, "rc": rc}})
        return last_rc, last_output

    @staticmethod
    def dynamic_tick_disabled_status() -> Optional[bool]:
        if not IS_WINDOWS or not WindowsOps.supports_dynamic_tick_toggle():
            return None
        rc, output = WindowsOps.bcdedit_current_output(timeout=45)
        if rc != 0 or not output:
            return None
        low = output.casefold()
        if "disabledynamictick" not in low:
            return False
        return any(marker in low for marker in (
            "disabledynamictick yes",
            "disabledynamictick    yes",
            "disabledynamictick true",
            "disabledynamictick так",
        ))

    @staticmethod
    def set_dynamic_tick_disabled(disabled: bool) -> bool:
        """Toggle the dynamic tick boot option for latency experiments.

        This is intentionally an advanced manual action.  Microsoft documents
        disabledynamictick as a BCDEdit boot option and notes that it is mainly
        intended for debugging, so it is not part of the default gaming profile.
        """
        if not IS_WINDOWS or not WindowsOps.supports_dynamic_tick_toggle():
            return False
        current = WindowsOps.dynamic_tick_disabled_status()
        if current is not None and bool(current) == bool(disabled):
            log_action({"dynamic_tick_set_skipped_already_desired": {"disabled": bool(disabled)}})
            log_system_response(
                "bcdedit.dynamic_tick_noop",
                command=["bcdedit.exe", "/set", "disabledynamictick", "yes" if disabled else "no"],
                returncode="already_applied",
                stdout={"current": current, "desired": bool(disabled)},
                context={"feature": "dynamic_tick_set", "noop": True},
            )
            return True
        value = "yes" if disabled else "no"
        return WindowsOps.run_command_args(["bcdedit.exe", "/set", "disabledynamictick", value], timeout=90, noisy=False, context={"feature": "dynamic_tick_set", "disabled": bool(disabled)})

    @staticmethod
    def restore_dynamic_tick_default() -> bool:
        """Remove the custom dynamic tick boot option and return to Windows default."""
        if not IS_WINDOWS or not WindowsOps.supports_dynamic_tick_toggle():
            return False
        rc, output = WindowsOps.run_command_capture(["bcdedit.exe", "/deletevalue", "disabledynamictick"], timeout=90, log_failure=False, context={"feature": "dynamic_tick_restore", "optional_absent_ok": True})
        if rc == 0:
            return True
        lowered = (output or "").casefold()
        # When the value is not present, deleting it fails, but the system is
        # already on the default timer policy.  Do not mask access-denied or BCD
        # corruption errors as success.
        absent_markers = (
            "element not found",
            "could not find",
            "cannot find",
            "не найден",
            "не знайден",
        )
        absent = any(marker in lowered for marker in absent_markers)
        if not absent:
            log_error(f"dynamic tick restore failed rc={rc}: {str(output)[:1000]}")
        return absent


    POWERCFG_ALIAS_MAP: Dict[str, str] = {
        # Microsoft powercfg aliases are not guaranteed to be accepted on every
        # localized/OEM Windows image. Use official GUIDs internally, while still
        # allowing old call sites to pass friendly aliases.
        "SCHEME_CURRENT": "SCHEME_CURRENT",
        "SCHEME_BALANCED": "SCHEME_BALANCED",
        "SCHEME_MIN": "SCHEME_MIN",
        "SCHEME_MAX": "SCHEME_MAX",
        "SUB_PROCESSOR": "54533251-82be-4824-96c1-47b60b740d00",
        "SUB_PCIEXPRESS": "501a4d13-42af-4429-9fd1-a8218c268e20",
        "PERFEPP": "36687f9e-e3a5-4dbf-b1dc-15eb381c6863",
        "PERFBOOSTMODE": "be337238-0d82-4146-a960-4f3749d470c7",
        "CPMINCORES": "0cc5b647-c1df-4637-891a-dec35c318583",
        "ASPM": "ee12f906-d277-404b-b6da-e5fa1a576df5",
        "PERFINCPOL": "465e1f50-b610-473a-ab58-00d1077dc418",
        "PERFDECPOL": "40fbefc7-2e9d-4d25-a185-0cf891d08c1e",
        "PERFINCTHRESHOLD": "06cadf0e-64ed-448a-8927-ce7bf90eb35d",
        "PERFDECTHRESHOLD": "12a0ab44-fe28-4fa9-b3bd-4b64f44960a6",
        "DISTRIBUTEUTIL": "e0007330-f589-42ed-a401-5ddb10e785d3",
    }

    @staticmethod
    def powercfg_token(name_or_guid: str) -> str:
        text = str(name_or_guid or "").strip()
        return WindowsOps.POWERCFG_ALIAS_MAP.get(text.upper(), text)

    @staticmethod
    def powercfg_args(*parts: str) -> List[str]:
        return ["powercfg.exe", *[WindowsOps.powercfg_token(part) for part in parts]]

    POWERCFG_UNSUPPORTED_CACHE: Dict[Tuple[str, str, str], float] = {}
    POWERCFG_ACTIVE_SCHEME_CACHE: Tuple[Optional[str], float] = (None, 0.0)
    POWERCFG_ACTIVE_SCHEME_TTL_SECONDS = 8.0

    @staticmethod
    def invalidate_powercfg_cache(reason: str = "") -> None:
        """Drop short-lived powercfg caches after a power policy write."""
        try:
            WindowsOps.POWERCFG_ACTIVE_SCHEME_CACHE = (None, 0.0)
            WindowsOps.POWERCFG_UNSUPPORTED_CACHE.clear()
            log_action({"powercfg_cache_invalidated": {"reason": reason or "manual"}})
        except Exception:
            pass

    @staticmethod
    def parse_active_power_scheme_guid(output: str) -> Optional[str]:
        match = re.search(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})", str(output or ""))
        return match.group(1).lower() if match else None

    @staticmethod
    def active_power_scheme_guid(*, timeout: int = 30, force_refresh: bool = False) -> Optional[str]:
        if not IS_WINDOWS:
            return None
        now = time.monotonic()
        cached_guid, cached_at = WindowsOps.POWERCFG_ACTIVE_SCHEME_CACHE
        if cached_guid and not force_refresh and now - cached_at < WindowsOps.POWERCFG_ACTIVE_SCHEME_TTL_SECONDS:
            log_action({"powercfg_active_scheme_cache_hit": {"scheme": cached_guid, "age_ms": int((now - cached_at) * 1000)}})
            return cached_guid
        rc, output = WindowsOps.run_command_capture(
            WindowsOps.powercfg_args("/getactivescheme"),
            timeout=timeout,
            log_failure=False,
            context={"feature": "powercfg_active_scheme", "optional": True, "cache": "refresh"},
        )
        if rc != 0:
            return cached_guid
        guid = WindowsOps.parse_active_power_scheme_guid(output)
        if guid:
            WindowsOps.POWERCFG_ACTIVE_SCHEME_CACHE = (guid, now)
        return guid

    @staticmethod
    def powercfg_current_scheme_token() -> str:
        # Some Windows 11/OEM builds reject SCHEME_CURRENT for query/value-index
        # calls.  The active scheme GUID is more stable and still points at the
        # same policy FreeCleaner is about to inspect or edit.
        return WindowsOps.active_power_scheme_guid() or "SCHEME_CURRENT"

    @staticmethod
    def powercfg_set_ac_value(subgroup: str, setting: str, value: Any, *, timeout: int = 90) -> bool:
        if not IS_WINDOWS:
            return False
        scheme = WindowsOps.powercfg_current_scheme_token()
        args = WindowsOps.powercfg_args("/setacvalueindex", scheme, subgroup, setting, str(value))
        return WindowsOps.run_command_args(args, timeout=timeout, noisy=False, log_failure=False, context={"feature": "powercfg_set_ac_value", "scheme": scheme, "subgroup": subgroup, "setting": setting, "value": value, "optional": True})

    @staticmethod
    def _translate_powercfg_command(args: List[str], scheme: Optional[str] = None) -> List[str]:
        translated = list(args)
        if translated and translated[0].lower() == "powercfg.exe":
            out = ["powercfg.exe"]
            for part in translated[1:]:
                token = WindowsOps.powercfg_token(part)
                if scheme and token.upper() == "SCHEME_CURRENT":
                    token = scheme
                out.append(token)
            translated = out
        return translated

    @staticmethod
    def _run_powercfg_commands(commands: List[List[str]], timeout: int = 90) -> int:
        """Run powercfg commands and return how many completed successfully.

        Power aliases are not guaranteed to exist on every Windows 10/11 build,
        OEM image, CPU generation, or power plan.  Treat unsupported aliases as a
        soft failure so one missing setting does not break the whole optimizer.
        """
        ok_count = 0
        scheme = WindowsOps.powercfg_current_scheme_token()
        for args in commands:
            translated = WindowsOps._translate_powercfg_command(args, scheme=scheme)
            if WindowsOps.run_command_args(translated, timeout=timeout, log_failure=False, context={"feature": "powercfg_profile_apply", "scheme": scheme, "optional": True}):
                ok_count += 1
        return ok_count

    @staticmethod
    def powercfg_get_ac_value(subgroup: str, setting: str, scheme: Optional[str] = None) -> Optional[int]:
        """Read a Windows power AC setting without console flashes.

        Uses `/QUERY` first and only falls back when the query contains a real
        setting block but no parseable value.  If Windows/OEM returns only the
        scheme header, the setting is treated as unsupported immediately to avoid
        noisy `/GETACVALUEINDEX` calls. Unsupported settings are optional: full
        stdout/stderr stays in system.log, while errors.log is reserved for real
        application failures.
        """
        if not IS_WINDOWS:
            return None
        subgroup_token = WindowsOps.powercfg_token(subgroup)
        setting_token = WindowsOps.powercfg_token(setting)
        scheme = scheme or WindowsOps.powercfg_current_scheme_token()
        cache_key = (str(scheme).lower(), str(subgroup_token).lower(), str(setting_token).lower())
        now = time.monotonic()
        cached_at = WindowsOps.POWERCFG_UNSUPPORTED_CACHE.get(cache_key)
        if cached_at and now - cached_at < 90:
            log_action({"powercfg_optional_cached_unavailable": {"scheme": scheme, "subgroup": subgroup, "setting": setting}})
            return None

        # Query first. On Windows 11/OEM images a hidden setting can return only
        # the scheme header.  That is not a valid value source, and falling back to
        # `/GETACVALUEINDEX` only adds "Invalid Parameters" noise and latency.
        query_args = WindowsOps.powercfg_args("/QUERY", scheme, subgroup_token, setting_token)
        rc, output = WindowsOps.run_command_capture(
            query_args,
            timeout=45,
            log_failure=False,
            context={
                "feature": "powercfg_ac_value",
                "scheme": scheme,
                "subgroup": subgroup,
                "setting": setting,
                "attempt": 1,
                "optional": True,
            },
        )
        last_rc = rc
        if rc == 0 and output:
            value = WindowsOps.parse_powercfg_numeric_value(output)
            log_action({"powercfg_value_probe": {"scheme": scheme, "subgroup": subgroup, "setting": setting, "attempt": 1, "value": value}})
            if value is not None:
                return value
            if "power setting guid" not in str(output).casefold():
                WindowsOps.POWERCFG_UNSUPPORTED_CACHE[cache_key] = now
                log_action({"powercfg_query_missing_setting_block": {"scheme": scheme, "subgroup": subgroup, "setting": setting, "fallback": "skipped_getacvalueindex"}})
                return None

        # Fallback only when QUERY clearly saw a setting record but the localized
        # output did not contain a parseable AC index.
        get_args = WindowsOps.powercfg_args("/GETACVALUEINDEX", scheme, subgroup_token, setting_token)
        rc, output = WindowsOps.run_command_capture(
            get_args,
            timeout=45,
            log_failure=False,
            context={
                "feature": "powercfg_ac_value",
                "scheme": scheme,
                "subgroup": subgroup,
                "setting": setting,
                "attempt": 2,
                "optional": True,
                "fallback_reason": "query_record_without_parseable_value",
            },
        )
        last_rc = rc
        if rc == 0 and output:
            value = WindowsOps.parse_powercfg_numeric_value(output)
            log_action({"powercfg_value_probe": {"scheme": scheme, "subgroup": subgroup, "setting": setting, "attempt": 2, "value": value}})
            if value is not None:
                return value
        WindowsOps.POWERCFG_UNSUPPORTED_CACHE[cache_key] = now
        log_action({"powercfg_optional_unavailable": {"scheme": scheme, "subgroup": subgroup, "setting": setting, "rc": last_rc}})
        return None

    @staticmethod
    def apply_safe_gaming_power_profile() -> bool:
        """Apply conservative Windows power settings for gaming.

        This intentionally stays at the Windows power-policy layer.  It does not
        touch CPU/GPU voltage, clocks, firmware, fan curves, thermal limits or
        vendor-specific driver overclocking APIs.
        """
        if not IS_WINDOWS:
            return False

        # Switch to the built-in High Performance plan, then tune only AC values
        # that reduce power-saving latency while the machine is plugged in.  Do
        # not force CPU min/max state here; OEM Balanced/High Performance values
        # can be restored safely by switching back to Balanced.
        switched = WindowsOps.run_command_args(WindowsOps.powercfg_args("/S", "SCHEME_MIN"), timeout=90)
        optional_commands = [
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFEPP", "0"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFBOOSTMODE", "1"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PCIEXPRESS", "ASPM", "0"],
            ["powercfg.exe", "/setactive", "SCHEME_CURRENT"],
        ]
        optional_ok = WindowsOps._run_powercfg_commands(optional_commands)

        # Some Windows editions or OEM power plans do not expose every alias.
        # The profile is still useful when the plan switch succeeded.
        return switched or optional_ok >= 2

    @staticmethod
    def apply_cpu_latency_performance_profile() -> bool:
        """Apply an advanced AC-only CPU latency profile for games.

        This profile is for desktops or plugged-in laptops where frametime
        consistency matters more than heat, battery life, and idle power.  It is
        still safer than overclocking: it only asks Windows to favor performance
        through official power-policy aliases, and unsupported aliases are skipped.
        """
        if not IS_WINDOWS:
            return False

        switched = WindowsOps.run_command_args(WindowsOps.powercfg_args("/S", "SCHEME_MIN"), timeout=90)
        commands = [
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFEPP", "0"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFBOOSTMODE", "2"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFINCPOL", "2"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFDECPOL", "1"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFINCTHRESHOLD", "10"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "PERFDECTHRESHOLD", "8"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "CPMINCORES", "100"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PROCESSOR", "DISTRIBUTEUTIL", "0"],
            ["powercfg.exe", "/setacvalueindex", "SCHEME_CURRENT", "SUB_PCIEXPRESS", "ASPM", "0"],
            ["powercfg.exe", "/setactive", "SCHEME_CURRENT"],
        ]
        ok_count = WindowsOps._run_powercfg_commands(commands)
        return switched or ok_count >= 4

    @staticmethod
    def restore_balanced_power_profile() -> bool:
        """Return Windows to the built-in Balanced power plan.

        Avoid `powercfg -restoredefaultschemes` here because it removes custom OEM
        and user-created plans.  Switching back to Balanced is a safer rollback.
        """
        if not IS_WINDOWS:
            return False
        return WindowsOps.run_command_args(WindowsOps.powercfg_args("/S", "SCHEME_BALANCED"), timeout=90)

    @staticmethod
    def purge_standby_memory() -> bool:
        """Purge low-priority standby RAM cache through the Windows memory manager.

        This does not terminate processes and does not modify RAM timings.  It is
        meant as a one-shot action before launching a heavy game, not as a looped
        background cleaner.
        """
        if not IS_WINDOWS:
            return False
        try:
            ntdll = ctypes.WinDLL("ntdll")
            nt_set_system_information = ntdll.NtSetSystemInformation
            nt_set_system_information.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_ulong]
            nt_set_system_information.restype = ctypes.c_long

            SystemMemoryListInformation = 80
            MemoryPurgeLowPriorityStandbyList = 5
            MemoryPurgeStandbyList = 4

            # Prefer the less aggressive low-priority standby purge.  Fall back
            # to the broader standby list only on older systems where mode 5 is
            # unavailable.
            for mode in (MemoryPurgeLowPriorityStandbyList, MemoryPurgeStandbyList):
                command = ctypes.c_int(mode)
                status = int(nt_set_system_information(
                    SystemMemoryListInformation,
                    ctypes.byref(command),
                    ctypes.sizeof(command),
                ))
                if status >= 0:
                    return True
        except Exception:
            pass
        return False

    @staticmethod
    def clear_recycle_bin() -> bool:
        if not IS_WINDOWS:
            return False

        # Never delete C:\$Recycle.Bin directly. It is a protected system
        # folder and direct removal can leave stale SID folders, broken ACLs, or
        # false failures. The Shell API is the correct Windows 10/11 path.
        try:
            class _SHQUERYRBINFO(ctypes.Structure):
                _pack_ = 4
                _fields_ = [
                    ("cbSize", ctypes.wintypes.DWORD),
                    ("i64Size", ctypes.c_longlong),
                    ("i64NumItems", ctypes.c_longlong),
                ]

            shell32 = ctypes.windll.shell32

            query = getattr(shell32, "SHQueryRecycleBinW", None)
            if query:
                query.argtypes = [ctypes.wintypes.LPCWSTR, ctypes.POINTER(_SHQUERYRBINFO)]
                query.restype = ctypes.c_long
                info = _SHQUERYRBINFO()
                info.cbSize = ctypes.sizeof(_SHQUERYRBINFO)
                query_result = int(query(None, ctypes.byref(info)))
                # Empty recycle bin is not a failure; the UI should not report an
                # error just because there was nothing to remove.
                if query_result == 0 and int(info.i64NumItems) <= 0:
                    return True

            empty = shell32.SHEmptyRecycleBinW
            empty.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPCWSTR, ctypes.wintypes.DWORD]
            empty.restype = ctypes.c_long

            SHERB_NOCONFIRMATION = 0x00000001
            SHERB_NOPROGRESSUI = 0x00000002
            SHERB_NOSOUND = 0x00000004
            flags = SHERB_NOCONFIRMATION | SHERB_NOPROGRESSUI | SHERB_NOSOUND
            result = int(empty(None, None, flags))
            if result == 0:
                return True
        except Exception:
            pass

        # Fallback 1: call the same Shell API from PowerShell. This helps when
        # the frozen Python process has a ctypes/Shell32 loading issue.
        shell_api_script = r'''
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class FreeCleanerRecycleBin
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct SHQUERYRBINFO
    {
        public UInt32 cbSize;
        public Int64 i64Size;
        public Int64 i64NumItems;
    }

    [DllImport("Shell32.dll", CharSet = CharSet.Unicode)]
    public static extern Int32 SHQueryRecycleBin(String pszRootPath, ref SHQUERYRBINFO pSHQueryRBInfo);

    [DllImport("Shell32.dll", CharSet = CharSet.Unicode)]
    public static extern Int32 SHEmptyRecycleBin(IntPtr hwnd, String pszRootPath, UInt32 dwFlags);
}
"@
$info = New-Object FreeCleanerRecycleBin+SHQUERYRBINFO
$info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($info)
$queryResult = [FreeCleanerRecycleBin]::SHQueryRecycleBin($null, [ref]$info)
if ($queryResult -eq 0 -and $info.i64NumItems -le 0) { exit 0 }
$result = [FreeCleanerRecycleBin]::SHEmptyRecycleBin([IntPtr]::Zero, $null, 0x00000007)
if ($result -eq 0) { exit 0 }
exit 1
'''
        if WindowsOps.run_command_args(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                shell_api_script,
            ],
            timeout=120,
        ):
            return True

        # Fallback 2: Windows PowerShell 5+ exposes Clear-RecycleBin. Keep it
        # as a last resort because it is absent on some older systems.
        clear_cmdlet_script = r'''
$ErrorActionPreference = 'Stop'
if (-not (Get-Command Clear-RecycleBin -ErrorAction SilentlyContinue)) { exit 1 }
try {
    Clear-RecycleBin -Force -ErrorAction Stop
    exit 0
} catch {
    # If it fails only because there is nothing to clear, treat it as success.
    try {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FreeCleanerRecycleBinQueryOnly
{
    [StructLayout(LayoutKind.Sequential, Pack = 4)]
    public struct SHQUERYRBINFO
    {
        public UInt32 cbSize;
        public Int64 i64Size;
        public Int64 i64NumItems;
    }
    [DllImport("Shell32.dll", CharSet = CharSet.Unicode)]
    public static extern Int32 SHQueryRecycleBin(String pszRootPath, ref SHQUERYRBINFO pSHQueryRBInfo);
}
"@
        $info = New-Object FreeCleanerRecycleBinQueryOnly+SHQUERYRBINFO
        $info.cbSize = [Runtime.InteropServices.Marshal]::SizeOf($info)
        $queryResult = [FreeCleanerRecycleBinQueryOnly]::SHQueryRecycleBin($null, [ref]$info)
        if ($queryResult -eq 0 -and $info.i64NumItems -le 0) { exit 0 }
    } catch {}
    exit 1
}
'''
        return WindowsOps.run_command_args(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                clear_cmdlet_script,
            ],
            timeout=120,
        )

    @staticmethod
    def try_enable_ultimate_performance() -> bool:
        ultimate_guid = "e9a42b02-d5df-448d-aa00-03f14749eb61"
        duplicated = WindowsOps.run_command_args(
            ["powercfg.exe", "-duplicatescheme", ultimate_guid],
            timeout=60,
        )
        switched = WindowsOps.run_command_args(
            ["powercfg.exe", "/S", ultimate_guid],
            timeout=60,
        )
        return duplicated or switched


class SafeFS:
    """Filesystem helpers optimized for safe cache cleanup.

    The cleaner intentionally removes the *contents* of a selected cache/log
    folder and keeps the target root folder itself.  That avoids breaking apps
    that expect their cache directory to keep existing after cleanup.
    """

    PROGRESS_FLUSH_BYTES = 4 * 1024 * 1024
    PROGRESS_FLUSH_SECONDS = 0.12

    @staticmethod
    def _extended_path(path: str) -> str:
        if not IS_WINDOWS:
            return path
        try:
            normalized = os.path.abspath(path)
            if normalized.startswith("\\\\?\\"):
                return normalized
            if normalized.startswith("\\\\"):
                return "\\\\?\\UNC\\" + normalized.lstrip("\\")
            return "\\\\?\\" + normalized
        except Exception:
            return path

    @staticmethod
    def _norm_abs(path: str) -> str:
        try:
            return os.path.normcase(os.path.normpath(os.path.abspath(path)))
        except Exception:
            return os.path.normcase(os.path.normpath(path or ""))

    @staticmethod
    def _is_drive_root(path: str) -> bool:
        try:
            abs_path = os.path.abspath(path)
            drive, tail = os.path.splitdrive(abs_path)
            if drive:
                return tail in ("\\", "/", "")
            return os.path.dirname(abs_path) == abs_path
        except Exception:
            return False

    @staticmethod
    def _is_reparse_point(path: str) -> bool:
        """Return True for symlinks/junctions/reparse points that must not be traversed."""
        try:
            if os.path.islink(path):
                return True
            isjunction = getattr(os.path, "isjunction", None)
            if isjunction and isjunction(path):
                return True
        except Exception:
            pass

        if IS_WINDOWS:
            try:
                FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
                attrs = ctypes.windll.kernel32.GetFileAttributesW(str(SafeFS._extended_path(path)))
                if attrs != -1 and (int(attrs) & FILE_ATTRIBUTE_REPARSE_POINT):
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _entry_is_reparse_point(entry: os.DirEntry) -> bool:
        """Fast reparse-point check for os.scandir/os.walk entries.

        Calling GetFileAttributesW for every file is expensive on large cache
        folders.  DirEntry can answer symlink status cheaply and, on Windows,
        exposes file attributes through stat(follow_symlinks=False).
        """
        try:
            if entry.is_symlink():
                return True
        except OSError:
            return True
        if IS_WINDOWS:
            try:
                attrs = int(getattr(entry.stat(follow_symlinks=False), "st_file_attributes", 0) or 0)
                return bool(attrs & 0x00000400)
            except OSError:
                return True
            except Exception:
                pass
        return False

    @staticmethod
    def is_safe_clean_target(path: str) -> bool:
        """Reject dangerous roots and protected Windows trees.

        This is the last line of defence for cleanup tasks.  It intentionally
        allows known cache folders under Program Files/ProgramData, but rejects
        drive roots, user/profile roots, Windows roots, and critical Windows
        subtrees even if a bad path is accidentally registered later.
        """
        if not path:
            return False
        try:
            abs_path = os.path.abspath(path)
            real_path = os.path.realpath(abs_path)
        except Exception:
            return False

        if SafeFS._is_reparse_point(abs_path):
            return False

        if SafeFS._is_drive_root(abs_path) or SafeFS._is_drive_root(real_path):
            return False

        norm = SafeFS._norm_abs(abs_path)
        real_norm = SafeFS._norm_abs(real_path)
        blocked_exact: Set[str] = set()
        blocked_trees: Set[str] = set()
        allowed_protected_trees: Set[str] = set()

        for env_name in (
            "WINDIR",
            "SYSTEMROOT",
            "PROGRAMFILES",
            "PROGRAMW6432",
            "PROGRAMFILES(X86)",
            "PROGRAMDATA",
            "USERPROFILE",
            "HOMEDRIVE",
            "APPDATA",
            "LOCALAPPDATA",
        ):
            value = os.environ.get(env_name)
            if value:
                if env_name == "HOMEDRIVE":
                    value = value + os.sep
                blocked_exact.add(SafeFS._norm_abs(value))
                blocked_exact.add(SafeFS._norm_abs(os.path.realpath(value)))

        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        if windir:
            # These protected folders are registered as cleanup targets on
            # purpose.  Keep the allow-list narrow so a task under System32 can
            # work without making the whole System32 tree cleanable.
            for child in (r"System32\LogFiles\setupcln", r"System32\LogFiles\WMI"):
                allowed = os.path.join(windir, child)
                allowed_protected_trees.add(SafeFS._norm_abs(allowed))
                allowed_protected_trees.add(SafeFS._norm_abs(os.path.realpath(allowed)))

            # These are never valid cleanup targets, neither directly nor via
            # symlink/reparse-point resolution.
            for child in ("System32", "SysWOW64", "WinSxS", "servicing"):
                critical = os.path.join(windir, child)
                blocked_trees.add(SafeFS._norm_abs(critical))
                blocked_trees.add(SafeFS._norm_abs(os.path.realpath(critical)))

        users_root = os.path.dirname(os.path.expanduser("~"))
        if users_root:
            blocked_exact.add(SafeFS._norm_abs(users_root))
            blocked_exact.add(SafeFS._norm_abs(os.path.realpath(users_root)))

        if norm in blocked_exact or real_norm in blocked_exact:
            return False

        for allowed in allowed_protected_trees:
            try:
                if os.path.commonpath([allowed, norm]) == allowed and os.path.commonpath([allowed, real_norm]) == allowed:
                    return True
            except Exception:
                continue

        for blocked in blocked_trees:
            try:
                if os.path.commonpath([blocked, norm]) == blocked:
                    return False
                if os.path.commonpath([blocked, real_norm]) == blocked:
                    return False
            except Exception:
                continue

        return True

    @staticmethod
    def _clear_attributes(path: str, is_dir: bool = False) -> None:
        candidates = [path]
        extended = SafeFS._extended_path(path)
        if extended != path:
            candidates.append(extended)

        for candidate in candidates:
            try:
                os.chmod(candidate, stat.S_IWRITE | stat.S_IREAD | (stat.S_IEXEC if is_dir else 0))
            except OSError:
                pass

        if IS_WINDOWS:
            for candidate in candidates:
                try:
                    attrs = 0x10 if is_dir else 0x80
                    ctypes.windll.kernel32.SetFileAttributesW(str(candidate), attrs)
                except Exception:
                    pass

    @staticmethod
    def _prepare_tree(path: str) -> None:
        # Do not run recursive attrib over the whole tree: on Windows it can walk
        # into junctions/reparse points.  Attributes are cleared per file/folder
        # right before removal, which is slower only on locked trees and much safer.
        try:
            SafeFS._clear_attributes(path, is_dir=os.path.isdir(path))
        except Exception:
            pass

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return int(os.lstat(path).st_size)
        except OSError:
            try:
                return int(os.path.getsize(path))
            except OSError:
                return 0

    @staticmethod
    def _remove_file_native(path: str) -> bool:
        for candidate in (path, SafeFS._extended_path(path)):
            try:
                os.remove(candidate)
                return True
            except FileNotFoundError:
                return True
            except IsADirectoryError:
                return False
            except OSError:
                continue
        return False

    @staticmethod
    def _is_obviously_locked(path: str) -> bool:
        if not IS_WINDOWS:
            return False
        try:
            GENERIC_READ = 0x80000000
            FILE_SHARE_READ = 0x00000001
            FILE_SHARE_WRITE = 0x00000002
            OPEN_EXISTING = 3
            FILE_ATTRIBUTE_NORMAL = 0x80
            handle = ctypes.windll.kernel32.CreateFileW(
                str(path),
                GENERIC_READ,
                FILE_SHARE_READ | FILE_SHARE_WRITE,
                None,
                OPEN_EXISTING,
                FILE_ATTRIBUTE_NORMAL,
                None,
            )
            if int(handle) in (-1, 0xFFFFFFFF):
                err = int(ctypes.get_last_error() or 0)
                return err in (32, 33)
            ctypes.windll.kernel32.CloseHandle(handle)
        except Exception:
            return False
        return False

    @staticmethod
    def _remove_file_powershell_literal(path: str) -> bool:
        """Last-resort literal-path fallback without `$args[0]`.

        Previous builds passed the target path through `$args[0]`; on some
        PowerShell hosts this became null and generated hundreds of false errors.
        Keep this fallback available for rare quoting/attribute edge-cases, but
        do not call it for obviously locked temp files.
        """
        if not IS_WINDOWS or not path or not os.path.exists(path):
            return not os.path.exists(path)
        literal = _powershell_literal(path)
        script = "$ErrorActionPreference='Stop'; $p=" + literal + "; if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -ErrorAction Stop }"
        ok = WindowsOps.run_command_args(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
            timeout=60,
            noisy=False,
            log_failure=False,
            context={"feature": "filesystem_file_literal_fallback", "optional": True},
        )
        return ok and not os.path.exists(path)

    @staticmethod
    def _remove_dir_native(path: str) -> bool:
        for candidate in (path, SafeFS._extended_path(path)):
            try:
                os.rmdir(candidate)
                return True
            except FileNotFoundError:
                return True
            except OSError:
                continue
        return False

    @staticmethod
    def _remove_file_shell(path: str) -> bool:
        """No per-file external fallback during bulk cleanup.

        Starting powershell.exe for hundreds of temp files made cleanup look
        frozen and spammed logs.  Native deletion plus delete-on-reboot is the
        safe path for locked/system files.
        """
        return False

    @staticmethod
    def _remove_dir_shell(path: str) -> bool:
        """Deprecated external directory-removal fallback.

        Directory cleanup is now handled by os.rmdir/extended paths and optional
        delete-on-reboot scheduling.  No cmd.exe/PowerShell recursion is used, so
        junction filtering cannot be bypassed.
        """
        return False

    @staticmethod
    def _dir_is_empty(path: str) -> bool:
        try:
            with os.scandir(path) as it:
                return next(it, None) is None
        except FileNotFoundError:
            return True
        except OSError:
            return False

    @staticmethod
    def _schedule_for_delete(path: str) -> bool:
        if not os.path.exists(path):
            return True
        try:
            SafeFS._clear_attributes(path, is_dir=os.path.isdir(path))
        except Exception:
            pass
        return WindowsOps.schedule_delete_on_reboot(path)

    @staticmethod
    def _count_remaining_entries(path: str) -> Tuple[int, int]:
        if not path or not os.path.exists(path):
            return 0, 0
        if SafeFS._is_reparse_point(path):
            return (0, 1) if os.path.isdir(path) else (1, 0)
        if os.path.isfile(path):
            return (1, 0)

        files = 0
        dirs = 0
        stack = [path]
        seen: Set[str] = set()
        while stack:
            current = stack.pop()
            norm = SafeFS._norm_abs(current)
            if norm in seen:
                continue
            seen.add(norm)
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if SafeFS._entry_is_reparse_point(entry):
                                if entry.is_dir(follow_symlinks=False):
                                    dirs += 1
                                else:
                                    files += 1
                            elif entry.is_file(follow_symlinks=False):
                                files += 1
                            elif entry.is_dir(follow_symlinks=False):
                                dirs += 1
                                stack.append(entry.path)
                        except OSError:
                            continue
            except OSError:
                continue
        return files, dirs

    @staticmethod
    def fast_size(path: str, cancel_event: Optional[threading.Event] = None) -> int:
        if not path or not os.path.exists(path):
            return 0
        total = 0
        stack = [path]
        seen: Set[str] = set()
        while stack:
            if cancel_event is not None and cancel_event.is_set():
                break
            current = stack.pop()
            norm = SafeFS._norm_abs(current)
            if norm in seen:
                continue
            seen.add(norm)
            try:
                if SafeFS._is_reparse_point(current):
                    continue
                with os.scandir(current) as it:
                    for entry in it:
                        if cancel_event is not None and cancel_event.is_set():
                            break
                        try:
                            if SafeFS._entry_is_reparse_point(entry):
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += max(0, int(entry.stat(follow_symlinks=False).st_size or 0))
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                try:
                    if not SafeFS._is_reparse_point(current):
                        total += max(0, int(os.path.getsize(current) or 0))
                except OSError:
                    pass
        return total

    @staticmethod
    def fast_size_many(paths: List[str], cancel_event: Optional[threading.Event] = None) -> int:
        total = 0
        for path in PathFinder.unique_existing(paths):
            if cancel_event is not None and cancel_event.is_set():
                break
            total += max(0, SafeFS.fast_size(path, cancel_event))
        return total

    @staticmethod
    def fast_size_limited(
        path: str,
        cancel_event: Optional[threading.Event] = None,
        max_seconds: float = 2.5,
        max_entries: int = 12000,
    ) -> int:
        """Bounded estimator for live UI selection previews.

        Exact analysis/cleanup still uses fast_size_many().  This capped variant
        prevents a click on a huge cache tree from spawning long disk scans that
        make the whole system feel frozen, especially when the system drive is
        almost full.
        """
        if not path or not os.path.exists(path):
            return 0
        deadline = time.monotonic() + max(0.15, float(max_seconds or 0.0))
        entries_seen = 0
        total = 0
        stack = [path]
        seen: Set[str] = set()
        while stack:
            if cancel_event is not None and cancel_event.is_set():
                break
            if entries_seen >= max_entries or time.monotonic() >= deadline:
                break
            current = stack.pop()
            norm = SafeFS._norm_abs(current)
            if norm in seen:
                continue
            seen.add(norm)
            try:
                if SafeFS._is_reparse_point(current):
                    continue
                with os.scandir(current) as it:
                    for entry in it:
                        if cancel_event is not None and cancel_event.is_set():
                            break
                        entries_seen += 1
                        if entries_seen >= max_entries or time.monotonic() >= deadline:
                            break
                        try:
                            if SafeFS._entry_is_reparse_point(entry):
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += max(0, int(entry.stat(follow_symlinks=False).st_size or 0))
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                try:
                    if not SafeFS._is_reparse_point(current):
                        total += max(0, int(os.path.getsize(current) or 0))
                except OSError:
                    pass
        return total

    @staticmethod
    def fast_size_many_limited(
        paths: List[str],
        cancel_event: Optional[threading.Event] = None,
        max_seconds: float = 2.5,
        max_entries: int = 12000,
    ) -> int:
        total = 0
        started = time.monotonic()
        for path in PathFinder.unique_existing(paths):
            if cancel_event is not None and cancel_event.is_set():
                break
            remaining = max(0.1, float(max_seconds or 0.0) - (time.monotonic() - started))
            if remaining <= 0.1:
                break
            total += max(0, SafeFS.fast_size_limited(path, cancel_event, remaining, max_entries))
        return total

    @staticmethod
    def clean_many(paths: List[str], on_bytes_removed: Callable[[int], None], cancel_event: threading.Event) -> Dict[str, int]:
        total_result = {
            "removed_bytes": 0,
            "files_removed": 0,
            "dirs_removed": 0,
            "scheduled_reboot": 0,
            "remaining_files": 0,
            "remaining_dirs": 0,
            "skipped_links": 0,
            "skipped_busy": 0,
            "errors": 0,
        }
        for path in PathFinder.unique_existing(paths):
            if cancel_event.is_set():
                break
            result = SafeFS.clean_directory(path, on_bytes_removed, cancel_event)
            for key, value in result.items():
                total_result[key] = total_result.get(key, 0) + int(value or 0)
        return total_result

    @staticmethod
    def clean_directory(path: str, on_bytes_removed: Callable[[int], None], cancel_event: threading.Event) -> Dict[str, int]:
        result = {
            "removed_bytes": 0,
            "files_removed": 0,
            "dirs_removed": 0,
            "scheduled_reboot": 0,
            "remaining_files": 0,
            "remaining_dirs": 0,
            "skipped_links": 0,
            "skipped_busy": 0,
            "errors": 0,
        }
        if not path or not os.path.exists(path):
            return result

        if not SafeFS.is_safe_clean_target(path):
            log_security(f"blocked unsafe cleanup target: {path}", level="WARNING")
            log_system_response("filesystem.clean_blocked", command={"path": path}, returncode="unsafe_target", stdout=result, context={"safe_guard": True}, level="WARNING")
            result["errors"] = 1
            return result

        clean_started = time.perf_counter()
        log_system_response("filesystem.clean_start", command={"path": path}, returncode="start", stdout={"path": path}, context={"safe_target": True})
        pending_progress_bytes = 0
        last_flush = time.monotonic()

        def flush_progress(force: bool = False) -> None:
            nonlocal pending_progress_bytes, last_flush
            if pending_progress_bytes <= 0:
                return
            now = time.monotonic()
            if not force and pending_progress_bytes < SafeFS.PROGRESS_FLUSH_BYTES and (now - last_flush) < SafeFS.PROGRESS_FLUSH_SECONDS:
                return
            chunk = pending_progress_bytes
            pending_progress_bytes = 0
            last_flush = now
            try:
                on_bytes_removed(chunk)
            except Exception:
                pass

        def mark_file_removed(size: int) -> None:
            nonlocal pending_progress_bytes
            result["files_removed"] += 1
            if size > 0:
                result["removed_bytes"] += size
                pending_progress_bytes += size
                flush_progress(False)

        def remove_single_file(file_path: str) -> bool:
            try:
                size = SafeFS._file_size(file_path)
                SafeFS._clear_attributes(file_path, is_dir=False)
                removed = SafeFS._remove_file_native(file_path)
                if not removed:
                    SafeFS._clear_attributes(file_path, is_dir=False)
                    removed = SafeFS._remove_file_native(file_path)
                if removed:
                    mark_file_removed(size)
                    return True
                if not SafeFS._is_obviously_locked(file_path):
                    removed = SafeFS._remove_file_shell(file_path)
                    if removed:
                        mark_file_removed(size)
                        return True
                if SafeFS._schedule_for_delete(file_path):
                    result["scheduled_reboot"] += 1
                    return True
                # Locked/in-use temp files are normal on Windows.  Keep them out of
                # errors.log and report them as skipped so QA can still see the
                # remaining count without treating it as an app failure.
                result["skipped_busy"] += 1
                return False
            except Exception as exc:
                result["skipped_busy"] += 1
                log_system_response(
                    "filesystem.file_skip_exception",
                    command={"path": file_path},
                    returncode="skipped",
                    stderr=str(exc),
                    context={"phase": "file_delete"},
                    level="INFO",
                )
                return False

        try:
            if SafeFS._is_reparse_point(path):
                result["errors"] = 1
                return result
            if os.path.isfile(path) or os.path.islink(path):
                if not remove_single_file(path):
                    result["remaining_files"] = 1 if os.path.exists(path) else 0
                flush_progress(True)
                return result

            if not os.path.isdir(path):
                return result

            SafeFS._prepare_tree(path)

            def on_walk_error(_error: OSError) -> None:
                result["errors"] += 1

            # Walk top-down so reparse points can be filtered before Python
            # descends into them. This protects against junction/symlink cache
            # entries that point outside the selected target. Directories are
            # removed afterwards in reverse order to keep the target root intact.
            dirs_to_remove: List[str] = []
            for root, dirs, files in os.walk(path, topdown=True, onerror=on_walk_error, followlinks=False):
                if cancel_event.is_set():
                    flush_progress(True)
                    return result

                if root != path and SafeFS._is_reparse_point(root):
                    dirs[:] = []
                    continue

                safe_dirs: List[str] = []
                for name in list(dirs):
                    dir_path = os.path.join(root, name)
                    try:
                        is_link = SafeFS._is_reparse_point(dir_path)
                    except Exception:
                        is_link = True
                    if is_link:
                        # Leave links/junctions in place rather than risk cleaning
                        # a target outside the selected cache folder.
                        result["skipped_links"] += 1
                        continue
                    safe_dirs.append(name)
                    dirs_to_remove.append(dir_path)
                dirs[:] = safe_dirs

                for name in files:
                    if cancel_event.is_set():
                        flush_progress(True)
                        return result
                    file_path = os.path.join(root, name)
                    if SafeFS._is_reparse_point(file_path):
                        result["skipped_links"] += 1
                        continue
                    remove_single_file(file_path)

            for dir_path in reversed(dirs_to_remove):
                if cancel_event.is_set():
                    flush_progress(True)
                    return result
                if not os.path.exists(dir_path):
                    continue
                if SafeFS._is_reparse_point(dir_path):
                    continue

                SafeFS._clear_attributes(dir_path, is_dir=True)
                removed = SafeFS._remove_dir_native(dir_path)

                if removed:
                    result["dirs_removed"] += 1
                    continue

                # If the folder still contains skipped links/junctions or locked
                # children, keep it in place. Scheduling a non-empty folder for
                # reboot deletion is too ambiguous and can make the UI claim a
                # safer cleanup than what Windows will actually do later.
                if SafeFS._dir_is_empty(dir_path) and SafeFS._schedule_for_delete(dir_path):
                    result["scheduled_reboot"] += 1
                    continue

                result["skipped_busy"] += 1

            remaining_files, remaining_dirs = SafeFS._count_remaining_entries(path)
            result["remaining_files"] = remaining_files
            result["remaining_dirs"] = remaining_dirs

            # Keep scheduled-on-reboot items visible in the separate counter but
            # do not double-count every remaining child as a new failure.
            if remaining_files or remaining_dirs:
                expected_remaining = result["scheduled_reboot"] + result.get("skipped_links", 0) + result.get("skipped_busy", 0)
                result["errors"] += max(0, (remaining_files + remaining_dirs) - expected_remaining)

            flush_progress(True)
            return result
        finally:
            flush_progress(True)
            try:
                log_system_response(
                    "filesystem.clean_complete",
                    command={"path": path},
                    returncode="ok" if int(result.get("errors", 0) or 0) == 0 else "partial",
                    stdout=result,
                    elapsed_ms=int((time.perf_counter() - clean_started) * 1000),
                    context={"path": path, "skipped_busy_is_normal": True},
                    level="INFO" if int(result.get("errors", 0) or 0) == 0 else "WARNING",
                )
            except Exception:
                pass

