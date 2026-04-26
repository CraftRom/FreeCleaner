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
import urllib.request
import urllib.parse
import urllib.error
import webbrowser
try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore
import concurrent.futures
import queue
import json
import locale
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Dict, List, Tuple, Union, Set

from .default_lang_packs import DEFAULT_LANG_PACKS


APP_NAME = "FreeCleaner"
VERSION_INFO_FILENAME = "version_info.txt"
LANG_DIRNAME = "lang"
ICONS_DIRNAME = os.path.join("assets", "icons")
REGISTRY_BACKUP_DIRNAME = "registry_backups"
GITHUB_API_BASE = "https://api.github.com"


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
    name = (asset_name or "").strip().lower()
    return name.startswith(f"{APP_NAME.lower()}-") and name.endswith("-win32-setup.exe")


def is_update_asset_compatible(asset_name: str) -> bool:
    """Return True if the release asset can be installed on this machine."""
    name = (asset_name or "").strip().lower()
    if not name.endswith("-setup.exe"):
        return False
    if get_os_architecture() == "x64":
        return name.endswith("-win64-setup.exe") or name.endswith("-win32-setup.exe")
    return name.endswith("-win32-setup.exe")


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
    """Base directory for runtime files.

    - For .exe (PyInstaller frozen): directory next to the executable
    - For source runs (.py): directory of the *entry script* (e.g. app.py)
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



def get_bundle_base_dir() -> str:
    """Base directory for bundled resources.

    - For PyInstaller: sys._MEIPASS
    - For source runs: same as runtime base dir (keeps lookups consistent)
    """
    if hasattr(sys, "_MEIPASS"):
        return sys._MEIPASS
    return get_runtime_base_dir()



CONFIG_PATH = os.path.join(get_runtime_base_dir(), "config.json")

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


def normalize_version_tuple(raw: str) -> Tuple[int, ...]:
    text = (raw or "").strip()
    if not text:
        return (0,)

    if text.lower().startswith("v"):
        text = text[1:]

    text = text.split("+", 1)[0].strip()
    text = text.split("-", 1)[0].strip()

    parts: List[int] = []
    for segment in text.split('.'):
        piece = segment.strip()
        if not piece:
            continue
        m = re.match(r"(\d+)", piece)
        if not m:
            break
        parts.append(int(m.group(1)))

    if not parts:
        return (0,)

    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


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


def fetch_latest_github_release(owner: str, repo: str, timeout: int = 12) -> Optional[UpdateInfo]:
    owner = (owner or '').strip()
    repo = (repo or '').strip()
    if not owner or not repo:
        return None

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases/latest"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}-UpdateChecker",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
    except Exception:
        return None

    if not isinstance(payload, dict):
        return None

    tag_name = str(payload.get("tag_name") or "").strip()
    name = str(payload.get("name") or tag_name or f"{owner}/{repo}").strip()
    body = str(payload.get("body") or "").strip()
    html_url = str(payload.get("html_url") or "").strip()
    published_at = str(payload.get("published_at") or payload.get("created_at") or "").strip()

    download_url = html_url
    selected_asset_name = ""
    assets = payload.get("assets")
    if isinstance(assets, list):
        arch_suffix = get_update_asset_suffix()
        exact_setup = None
        exact_setup_name = ""
        win32_fallback = None
        win32_fallback_name = ""
        compatible_setup = None
        compatible_setup_name = ""
        generic_exe = None
        generic_exe_name = ""
        first_asset = None
        first_asset_name = ""

        for asset in assets:
            if not isinstance(asset, dict):
                continue
            candidate = str(asset.get("browser_download_url") or "").strip()
            raw_asset_name = str(asset.get("name") or "").strip()
            asset_name = raw_asset_name.lower()
            if not candidate:
                continue

            if first_asset is None:
                first_asset = candidate
                first_asset_name = raw_asset_name

            if _asset_name_matches_update_arch(raw_asset_name, arch_suffix):
                exact_setup = candidate
                exact_setup_name = raw_asset_name
                break

            if _asset_name_is_compatible_fallback(raw_asset_name) and win32_fallback is None:
                win32_fallback = candidate
                win32_fallback_name = raw_asset_name

            if is_update_asset_compatible(raw_asset_name) and compatible_setup is None:
                compatible_setup = candidate
                compatible_setup_name = raw_asset_name

            if asset_name.endswith('.exe') and generic_exe is None and (not asset_name.endswith('-setup.exe') or is_update_asset_compatible(raw_asset_name)):
                generic_exe = candidate
                generic_exe_name = raw_asset_name

        download_url = exact_setup or win32_fallback or compatible_setup or generic_exe or html_url
        selected_asset_name = exact_setup_name or win32_fallback_name or compatible_setup_name or generic_exe_name

    version_text = tag_name or name
    return UpdateInfo(
        owner=owner,
        repo=repo,
        tag_name=tag_name or name,
        name=name,
        body=body,
        html_url=html_url,
        download_url=download_url,
        asset_name=selected_asset_name,
        published_at=published_at,
        version_text=version_text,
        version_tuple=normalize_version_tuple(version_text),
    )


def get_default_download_dir() -> str:
    home = os.path.expanduser("~")
    downloads = os.path.join(home, "Downloads")
    if os.path.isdir(downloads):
        return downloads
    return get_runtime_base_dir()


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
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response, open(temp_path, "wb") as fh:
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
        return True, dest
    except Exception as exc:
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
    candidates = [
        os.path.join(get_runtime_base_dir(), VERSION_INFO_FILENAME),
        os.path.join(get_bundle_base_dir(), VERSION_INFO_FILENAME),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), VERSION_INFO_FILENAME),
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
    reboot_required: bool = False


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
        """Return existing paths without duplicates, normalized case-insensitively on Windows."""
        result: List[str] = []
        seen: Set[str] = set()
        for path in paths:
            if not path:
                continue
            expanded = PathFinder.expand(path)
            try:
                abs_path = os.path.abspath(expanded)
            except Exception:
                abs_path = expanded
            key = os.path.normcase(abs_path)
            if key in seen or not os.path.exists(abs_path):
                continue
            seen.add(key)
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
    def get_windows_junk_targets() -> List[Tuple[str, str, str, str, bool]]:
        """Return real Windows cleanup targets as (key, title_key, desc_key, path, requires_admin).

        Targets are intentionally scoped to caches/logs/download caches.  It never returns
        dangerous system roots such as System32, WinSxS or Program Files.
        """
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        windir = os.environ.get("WINDIR", r"C:\Windows")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates: List[Tuple[str, str, str, str, bool]] = [
            ("recent_docs", "task.recent_docs.title", "task.recent_docs.desc", PathFinder._safe_join(appdata, r"Microsoft\Windows\Recent"), False),
            ("thumb_cache", "task.thumb_cache.title", "task.thumb_cache.desc", PathFinder._safe_join(local, r"Microsoft\Windows\Explorer"), False),
            ("wer_user", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(local, r"Microsoft\Windows\WER"), False),
            ("wer_system", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(programdata, r"Microsoft\Windows\WER"), True),
            ("windows_logs_cbs", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(windir, r"Logs\CBS"), True),
            ("windows_logs_dism", "task.error_logs.title", "task.error_logs.desc", PathFinder._safe_join(windir, r"Logs\DISM"), True),
            ("update_cache_files", "task.update_cache_files.title", "task.update_cache_files.desc", PathFinder._safe_join(windir, r"SoftwareDistribution\Download"), True),
            ("delivery_opt", "task.delivery_opt.title", "task.delivery_opt.desc", PathFinder._safe_join(local, r"Microsoft\Windows\DeliveryOptimization\Cache"), False),
            ("prefetch", "task.prefetch.title", "task.prefetch.desc", PathFinder._safe_join(windir, "Prefetch"), True),
        ]
        return [(k,t,d,p,a) for k,t,d,p,a in candidates if p and os.path.exists(p)]

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
            ("opera", "Opera", PathFinder._safe_join(roaming, r"Opera Software\Opera Stable")),
            ("opera_gx", "Opera GX", PathFinder._safe_join(roaming, r"Opera Software\Opera GX Stable")),
        ]
        subdirs = [
            r"Cache", r"Cache\Cache_Data", r"Code Cache", r"GPUCache",
            r"Service Worker\CacheStorage", r"Service Worker\ScriptCache",
            r"Media Cache", r"ShaderCache", r"GrShaderCache",
        ]
        result: List[Tuple[str, str, str, str, Dict[str, str]]] = []
        seen: Set[str] = set()
        for slug, name, root in browsers:
            if not root or not os.path.isdir(root):
                continue
            profiles: List[str] = [""]
            try:
                for entry in os.listdir(root):
                    full = os.path.join(root, entry)
                    if os.path.isdir(full) and (entry == "Default" or entry.startswith("Profile") or entry in ("Guest Profile", "System Profile")):
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
            ("telegram_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Telegram Desktop\tdata\user_data"), {"app": "Telegram"}),
            ("teams_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Microsoft\Teams\Cache"), {"app": "Microsoft Teams"}),
            ("slack_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(appdata, r"Slack\Cache"), {"app": "Slack"}),
            ("spotify_cache", "task.app_cache.title", "task.app_cache.desc", PathFinder._safe_join(local, r"Spotify\Storage"), {"app": "Spotify"}),
        ]
        return [(k,t,d,p,fmt) for k,t,d,p,fmt in candidates if p and os.path.exists(p)]

    @staticmethod
    def get_gaming_cache_targets() -> List[Tuple[str, str, str, str, bool]]:
        local = os.environ.get("LOCALAPPDATA", "")
        appdata = os.environ.get("APPDATA", "")
        programdata = os.environ.get("PROGRAMDATA", r"C:\ProgramData")
        candidates = [
            ("dx_shader_cache", "task.dx_shader_cache.title", "task.dx_shader_cache.desc", PathFinder._safe_join(local, "D3DSCache"), False),
            ("nvidia_dx", "task.nvidia_dx.title", "task.nvidia_dx.desc", PathFinder._safe_join(local, r"NVIDIA\DXCache"), False),
            ("nvidia_gl", "task.nvidia_gl.title", "task.nvidia_gl.desc", PathFinder._safe_join(local, r"NVIDIA\GLCache"), False),
            ("nvidia_nv_cache", "task.nvidia_nv_cache.title", "task.nvidia_nv_cache.desc", PathFinder._safe_join(programdata, r"NVIDIA Corporation\NV_Cache"), True),
            ("amd_dx", "task.amd_dx.title", "task.amd_dx.desc", PathFinder._safe_join(local, r"AMD\DxCache"), False),
            ("amd_gl", "task.amd_gl.title", "task.amd_gl.desc", PathFinder._safe_join(local, r"AMD\GLCache"), False),
            ("steam_htmlcache", "task.steam_htmlcache.title", "task.steam_htmlcache.desc", PathFinder._safe_join(local, r"Steam\htmlcache"), False),
            ("battle_net_cache", "task.battle_net_cache.title", "task.battle_net_cache.desc", PathFinder._safe_join(programdata, r"Battle.net\Agent\data\cache"), True),
            ("battle_net_agent_logs", "task.battle_net_cache.title", "task.battle_net_cache.desc", PathFinder._safe_join(programdata, r"Battle.net\Agent\Logs"), True),
            ("epic_webcache", "task.epic_webcache.title", "task.epic_webcache.desc", PathFinder._safe_join(local, r"EpicGamesLauncher\Saved\webcache"), False),
            ("epic_webcache_4147", "task.epic_webcache.title", "task.epic_webcache.desc", PathFinder._safe_join(local, r"EpicGamesLauncher\Saved\webcache_4147"), False),
            ("obs_browser_cache", "task.temp_capture_cache.title", "task.temp_capture_cache.desc", PathFinder._safe_join(appdata, r"obs-studio\plugin_config\obs-browser\Cache"), False),
        ]
        return [(k,t,d,p,a) for k,t,d,p,a in candidates if p and os.path.exists(p)]


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
    def run_as_admin() -> None:
        if not IS_WINDOWS:
            return
        try:
            args = subprocess.list2cmdline(sys.argv)
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
        except Exception:
            pass

    @staticmethod
    def run_command(cmd: str, timeout: int = 180, noisy: bool = False) -> bool:
        try:
            creationflags = 0x08000000 if IS_WINDOWS else 0
            startupinfo = None
            if IS_WINDOWS and not noisy:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            completed = subprocess.run(
                cmd,
                shell=True,
                stdout=None if noisy else subprocess.DEVNULL,
                stderr=None if noisy else subprocess.DEVNULL,
                timeout=timeout,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            return completed.returncode == 0
        except Exception:
            return False

    @staticmethod
    def run_command_args(args: List[str], timeout: int = 180, noisy: bool = False) -> bool:
        """Run a command without shell interpolation.

        Used for filesystem cleanup fallbacks where paths can contain spaces,
        quotes, ampersands or non-Latin characters.  Keeping shell=False avoids
        accidental command parsing bugs and makes cleanup errors much rarer.
        """
        if not args:
            return False
        try:
            creationflags = 0x08000000 if IS_WINDOWS else 0
            startupinfo = None
            if IS_WINDOWS and not noisy:
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            completed = subprocess.run(
                args,
                shell=False,
                stdout=None if noisy else subprocess.DEVNULL,
                stderr=None if noisy else subprocess.DEVNULL,
                timeout=timeout,
                creationflags=creationflags,
                startupinfo=startupinfo,
            )
            return completed.returncode == 0
        except Exception:
            return False

    @staticmethod
    def schedule_delete_on_reboot(path: str) -> bool:
        if not IS_WINDOWS or not path:
            return False
        try:
            MOVEFILE_DELAY_UNTIL_REBOOT = 0x4
            normalized = os.path.abspath(path)
            return bool(ctypes.windll.kernel32.MoveFileExW(str(normalized), None, MOVEFILE_DELAY_UNTIL_REBOOT))
        except Exception:
            return False

    @staticmethod
    def reg_add(path: str, name: str, value: Union[int, str], reg_type: str = "REG_DWORD") -> bool:
        safe_value = str(value).replace('"', '\"')
        value_type = (reg_type or "REG_DWORD").upper()
        if isinstance(value, str) and value_type == "REG_DWORD" and value.lower().startswith("0x"):
            cmd = f'reg add "{path}" /v "{name}" /t {value_type} /d {safe_value} /f'
        else:
            cmd = f'reg add "{path}" /v "{name}" /t {value_type} /d "{safe_value}" /f'
        return WindowsOps.run_command(cmd, timeout=45)

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
    def registry_backup_root() -> str:
        root = os.path.join(get_runtime_base_dir(), REGISTRY_BACKUP_DIRNAME)
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
        exported = 0
        for index, key in enumerate(unique_keys, start=1):
            safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', key).strip('_')[:90] or f'key_{index}'
            target = os.path.join(folder, f'{index:02d}_{safe_name}.reg')
            ok = WindowsOps.run_command(f'reg export "{key}" "{target}" /y', timeout=45)
            manifest_lines.append(f'{key}={"ok" if ok else "missing"}')
            if ok and os.path.isfile(target):
                exported += 1

        with open(os.path.join(folder, 'manifest.txt'), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(manifest_lines))

        return folder if exported else None

    @staticmethod
    def latest_registry_backup_dir() -> Optional[str]:
        backups = WindowsOps.list_registry_backups()
        return backups[0]["path"] if backups else None

    @staticmethod
    def list_registry_backups() -> List[Dict[str, Any]]:
        root = os.path.join(get_runtime_base_dir(), REGISTRY_BACKUP_DIRNAME)
        if not os.path.isdir(root):
            return []
        items: List[Dict[str, Any]] = []
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if not os.path.isdir(path):
                continue
            reg_files = sorted(
                os.path.join(path, entry)
                for entry in os.listdir(path)
                if entry.lower().endswith('.reg')
            )
            if not reg_files:
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
    def _read_registry_manifest(folder: str) -> List[str]:
        manifest = os.path.join(folder, 'manifest.txt')
        keys: List[str] = []
        if not os.path.isfile(manifest):
            return keys
        try:
            with open(manifest, 'r', encoding='utf-8') as fh:
                for raw in fh:
                    line = raw.strip()
                    if not line or '=' not in line:
                        continue
                    key = line.split('=', 1)[0].strip()
                    if key:
                        keys.append(key)
        except Exception:
            return []
        return keys

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
        if not reg_files:
            return False

        keys = WindowsOps._read_registry_manifest(folder)
        if keys:
            root = WindowsOps.registry_backup_root()
            stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            snapshot = os.path.join(root, f'pre_restore_{stamp}')
            os.makedirs(snapshot, exist_ok=True)
            exported = 0
            manifest_lines = []
            for index, key in enumerate(keys, start=1):
                safe_name = re.sub(r'[^A-Za-z0-9._-]+', '_', key).strip('_')[:90] or f'key_{index}'
                target = os.path.join(snapshot, f'{index:02d}_{safe_name}.reg')
                ok = WindowsOps.run_command(f'reg export "{key}" "{target}" /y', timeout=45)
                manifest_lines.append(f'{key}={"ok" if ok else "missing"}')
                if ok and os.path.isfile(target):
                    exported += 1
            try:
                with open(os.path.join(snapshot, 'manifest.txt'), 'w', encoding='utf-8') as fh:
                    fh.write('\n'.join(manifest_lines))
            except Exception:
                pass
            if exported == 0:
                try:
                    shutil.rmtree(snapshot, ignore_errors=True)
                except Exception:
                    pass

        results = [WindowsOps.run_command(f'reg import "{path}"', timeout=60) for path in reg_files]
        return all(results)

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
    def clear_recycle_bin() -> bool:
        if not IS_WINDOWS:
            return False

        # Never delete C:\$Recycle.Bin directly. It is a protected system
        # folder and direct removal can leave stale SID folders, broken ACLs, or
        # false failures. The Shell API is the correct Windows 7-11 path.
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
        duplicated = WindowsOps.run_command(
            "powercfg -duplicatescheme e9a42b02-d5df-448d-aa00-03f14749eb61",
            timeout=60,
        )
        switched = WindowsOps.run_command(
            "powercfg /S e9a42b02-d5df-448d-aa00-03f14749eb61",
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
    def is_safe_clean_target(path: str) -> bool:
        """Reject dangerous roots even if a bad task/path is registered later."""
        if not path:
            return False
        try:
            abs_path = os.path.abspath(path)
        except Exception:
            return False

        if SafeFS._is_drive_root(abs_path):
            return False

        norm = SafeFS._norm_abs(abs_path)
        blocked: Set[str] = set()

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
                blocked.add(SafeFS._norm_abs(value))

        windir = os.environ.get("WINDIR") or os.environ.get("SYSTEMROOT")
        if windir:
            blocked.add(SafeFS._norm_abs(os.path.join(windir, "System32")))
            blocked.add(SafeFS._norm_abs(os.path.join(windir, "SysWOW64")))
            blocked.add(SafeFS._norm_abs(os.path.join(windir, "WinSxS")))

        users_root = os.path.dirname(os.path.expanduser("~"))
        if users_root:
            blocked.add(SafeFS._norm_abs(users_root))

        return norm not in blocked

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
        if not IS_WINDOWS or not path or not os.path.isdir(path):
            return
        escaped = os.path.abspath(path).replace('"', '')
        WindowsOps.run_command(f'attrib -r -s -h "{escaped}\\*" /s /d', timeout=180)

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
        if not IS_WINDOWS:
            return False
        if not os.path.exists(path):
            return True

        commands = [
            ["cmd.exe", "/c", "del", "/f", "/q", "/a", os.path.abspath(path)],
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$ErrorActionPreference='Stop'; if (Test-Path -LiteralPath $args[0]) { Remove-Item -LiteralPath $args[0] -Force -ErrorAction Stop }",
                os.path.abspath(path),
            ],
        ]
        for args in commands:
            if WindowsOps.run_command_args(args, timeout=120):
                if not os.path.exists(path):
                    return True
        return not os.path.exists(path)

    @staticmethod
    def _remove_dir_shell(path: str) -> bool:
        if not IS_WINDOWS:
            return False
        if not os.path.exists(path):
            return True

        commands = [
            ["cmd.exe", "/c", "rd", "/s", "/q", os.path.abspath(path)],
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                "$ErrorActionPreference='Stop'; if (Test-Path -LiteralPath $args[0]) { Remove-Item -LiteralPath $args[0] -Recurse -Force -ErrorAction Stop }",
                os.path.abspath(path),
            ],
        ]
        for args in commands:
            if WindowsOps.run_command_args(args, timeout=180):
                if not os.path.exists(path):
                    return True
        return not os.path.exists(path)

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
        if os.path.isfile(path) or os.path.islink(path):
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
                            if entry.is_symlink():
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
                if os.path.islink(current):
                    continue
                with os.scandir(current) as it:
                    for entry in it:
                        if cancel_event is not None and cancel_event.is_set():
                            break
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
                                total += entry.stat(follow_symlinks=False).st_size
                            elif entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                        except (PermissionError, FileNotFoundError, OSError):
                            continue
            except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
                try:
                    if not os.path.islink(current):
                        total += os.path.getsize(current)
                except OSError:
                    pass
        return total

    @staticmethod
    def fast_size_many(paths: List[str], cancel_event: Optional[threading.Event] = None) -> int:
        total = 0
        for path in PathFinder.unique_existing(paths):
            if cancel_event is not None and cancel_event.is_set():
                break
            total += SafeFS.fast_size(path, cancel_event)
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
            "errors": 0,
        }
        if not path or not os.path.exists(path):
            return result

        if not SafeFS.is_safe_clean_target(path):
            result["errors"] = 1
            return result

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
                    removed = SafeFS._remove_file_native(file_path) or SafeFS._remove_file_shell(file_path)
                if removed:
                    mark_file_removed(size)
                    return True
                if SafeFS._schedule_for_delete(file_path):
                    result["scheduled_reboot"] += 1
                    return True
                result["errors"] += 1
                return False
            except Exception:
                result["errors"] += 1
                return False

        try:
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

            # Stream the tree instead of building all_files/all_dirs first.
            # This is much faster and uses constant memory on huge cache folders.
            for root, dirs, files in os.walk(path, topdown=False, onerror=on_walk_error, followlinks=False):
                if cancel_event.is_set():
                    flush_progress(True)
                    return result

                for name in files:
                    if cancel_event.is_set():
                        flush_progress(True)
                        return result
                    file_path = os.path.join(root, name)
                    remove_single_file(file_path)

                for name in dirs:
                    if cancel_event.is_set():
                        flush_progress(True)
                        return result
                    dir_path = os.path.join(root, name)
                    if not os.path.exists(dir_path):
                        continue

                    # Do not recurse through symlink targets.  Remove the link
                    # itself only if Windows/native rmdir handles it.
                    SafeFS._clear_attributes(dir_path, is_dir=True)
                    removed = SafeFS._remove_dir_native(dir_path)
                    if not removed:
                        removed = SafeFS._remove_dir_shell(dir_path)

                    if removed:
                        result["dirs_removed"] += 1
                        continue

                    if SafeFS._schedule_for_delete(dir_path):
                        result["scheduled_reboot"] += 1
                        continue

                    result["errors"] += 1

            # One light second pass: catches folders that became empty after
            # locked files were skipped/scheduled without doing expensive loops.
            if not cancel_event.is_set():
                try:
                    for root, dirs, _files in os.walk(path, topdown=False, followlinks=False):
                        for name in dirs:
                            dir_path = os.path.join(root, name)
                            if not os.path.isdir(dir_path):
                                continue
                            SafeFS._clear_attributes(dir_path, is_dir=True)
                            if SafeFS._remove_dir_native(dir_path):
                                result["dirs_removed"] += 1
                except OSError:
                    result["errors"] += 1

            remaining_files, remaining_dirs = SafeFS._count_remaining_entries(path)
            result["remaining_files"] = remaining_files
            result["remaining_dirs"] = remaining_dirs

            # Keep scheduled-on-reboot items visible in the separate counter but
            # do not double-count every remaining child as a new failure.
            if remaining_files or remaining_dirs:
                result["errors"] += max(0, (remaining_files + remaining_dirs) - result["scheduled_reboot"])

            flush_progress(True)
            return result
        finally:
            flush_progress(True)

