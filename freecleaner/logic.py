"""Core logic layer: paths, versioning, i18n, and safe cleanup operations.

This module must NOT contain UI widget creation code.
"""

from __future__ import annotations

import os
import sys
import ctypes
import threading
import subprocess
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
from typing import Callable, Optional, Dict, List, Tuple, Any

from .default_lang_packs import DEFAULT_LANG_PACKS


APP_NAME = "FreeCleaner"
VERSION_INFO_FILENAME = "version_info.txt"
LANG_DIRNAME = "lang"
ICONS_DIRNAME = os.path.join("assets", "icons")
REGISTRY_BACKUP_DIRNAME = "registry_backups"


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
CPU_COUNT = max(1, os.cpu_count() or 4)
SCAN_WORKERS = min(max(4, CPU_COUNT), 12)
CLEAN_WORKERS = min(max(4, CPU_COUNT * 2), 16)







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




@dataclass(slots=True)
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
    instant_action: bool = False
    registry_entries: Optional[List[Tuple[str, str]]] = None


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
        if IS_WINDOWS:
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)

    @staticmethod
    def run_command(cmd: str, timeout: int = 180, noisy: bool = False) -> bool:
        try:
            creationflags = 0x08000000 if IS_WINDOWS else 0
            completed = subprocess.run(
                cmd,
                shell=True,
                stdout=None if noisy else subprocess.DEVNULL,
                stderr=None if noisy else subprocess.DEVNULL,
                timeout=timeout,
                creationflags=creationflags,
            )
            return completed.returncode == 0
        except Exception:
            return False

    @staticmethod
    def reg_add(path: str, name: str, value: int, reg_type: str = "REG_DWORD") -> bool:
        cmd = f'reg add "{path}" /v "{name}" /t {reg_type} /d {value} /f'
        return WindowsOps.run_command(cmd, timeout=45)

    @staticmethod
    def registry_backup_dir() -> str:
        return os.path.join(get_runtime_base_dir(), REGISTRY_BACKUP_DIRNAME)

    @staticmethod
    def _split_reg_path(path: str) -> Tuple[Optional[Any], str, str]:
        clean = (path or "").strip().replace("/", "\\")
        if not clean:
            return None, "", ""
        root_name, _, subkey = clean.partition("\\")
        upper = root_name.upper()
        mapping: Dict[str, Tuple[str, Any]] = {}
        if winreg is not None:
            mapping = {
                "HKCU": ("HKEY_CURRENT_USER", winreg.HKEY_CURRENT_USER),
                "HKEY_CURRENT_USER": ("HKEY_CURRENT_USER", winreg.HKEY_CURRENT_USER),
                "HKLM": ("HKEY_LOCAL_MACHINE", winreg.HKEY_LOCAL_MACHINE),
                "HKEY_LOCAL_MACHINE": ("HKEY_LOCAL_MACHINE", winreg.HKEY_LOCAL_MACHINE),
            }
        if upper not in mapping:
            return None, subkey, ""
        full_name, root = mapping[upper]
        return root, subkey, full_name

    @staticmethod
    def _escape_reg_string(value: str) -> str:
        return str(value).replace("\\", r"\\").replace('"', r'\"')

    @staticmethod
    def _format_reg_value_line(name: str, value: Any, value_type: Any) -> Optional[str]:
        safe_name = WindowsOps._escape_reg_string(name)
        if value_type == "MISSING":
            return f'"{safe_name}"=-'
        if winreg is None:
            return None
        if value_type == winreg.REG_DWORD:
            try:
                return f'"{safe_name}"=dword:{int(value) & 0xFFFFFFFF:08x}'
            except Exception:
                return None
        if value_type == winreg.REG_QWORD:
            try:
                raw = int(value).to_bytes(8, byteorder="little", signed=False)
                return f'"{safe_name}"=hex(b):' + ",".join(f"{b:02x}" for b in raw)
            except Exception:
                return None
        if value_type == winreg.REG_SZ:
            return f'"{safe_name}"="{WindowsOps._escape_reg_string(str(value))}"'
        if value_type == winreg.REG_EXPAND_SZ:
            raw = (str(value) + "\0").encode("utf-16le")
            return f'"{safe_name}"=hex(2):' + ",".join(f"{b:02x}" for b in raw)
        return None

    @staticmethod
    def _read_registry_value(path: str, name: str) -> Tuple[Any, Any]:
        if not IS_WINDOWS or winreg is None:
            return None, None
        root, subkey, _ = WindowsOps._split_reg_path(path)
        if root is None:
            return None, None
        try:
            with winreg.OpenKey(root, subkey, 0, winreg.KEY_READ) as key:
                value, value_type = winreg.QueryValueEx(key, name)
                return value, value_type
        except OSError:
            return None, "MISSING"

    @staticmethod
    def create_registry_restore_snapshot(entries: List[Tuple[str, str]], label: str = "") -> Optional[str]:
        if not IS_WINDOWS or not entries:
            return None
        try:
            backup_dir = WindowsOps.registry_backup_dir()
            os.makedirs(backup_dir, exist_ok=True)
        except Exception:
            return None

        unique_entries: List[Tuple[str, str]] = []
        seen = set()
        for path, name in entries:
            key = (str(path).strip(), str(name).strip())
            if key[0] and key[1] and key not in seen:
                seen.add(key)
                unique_entries.append(key)
        if not unique_entries:
            return None

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        safe_label = re.sub(r"[^A-Za-z0-9_.-]+", "-", (label or "registry").strip("- ")) or "registry"
        out_path = os.path.join(backup_dir, f"{timestamp}-{safe_label}.reg")

        grouped: Dict[str, List[str]] = {}
        for reg_path, value_name in unique_entries:
            grouped.setdefault(reg_path, []).append(value_name)

        lines: List[str] = ["Windows Registry Editor Version 5.00", ""]
        for reg_path in sorted(grouped.keys()):
            _, _, full_root = WindowsOps._split_reg_path(reg_path)
            if not full_root:
                continue
            root_name, _, subkey = reg_path.replace("/", "\\").partition("\\")
            full_key_path = full_root if not subkey else f"{full_root}\\{subkey}"
            lines.append(f"[{full_key_path}]")
            for value_name in sorted(grouped[reg_path]):
                value, value_type = WindowsOps._read_registry_value(reg_path, value_name)
                line = WindowsOps._format_reg_value_line(value_name, value, value_type)
                if line:
                    lines.append(line)
            lines.append("")

        try:
            with open(out_path, "w", encoding="utf-16") as f:
                f.write("\r\n".join(lines).rstrip() + "\r\n")
            return out_path
        except Exception:
            return None

    @staticmethod
    def latest_registry_backup() -> Optional[str]:
        if not IS_WINDOWS:
            return None
        backup_dir = WindowsOps.registry_backup_dir()
        try:
            candidates = [
                os.path.join(backup_dir, name)
                for name in os.listdir(backup_dir)
                if name.lower().endswith(".reg")
            ]
        except Exception:
            return None
        if not candidates:
            return None
        candidates.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        return candidates[0]

    @staticmethod
    def import_registry_backup(path: str, timeout: int = 120) -> bool:
        if not IS_WINDOWS or not path or not os.path.isfile(path):
            return False
        return WindowsOps.run_command(f'reg import "{path}"', timeout=timeout)

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
    @staticmethod
    def fast_size(path: str) -> int:
        if not path or not os.path.exists(path):
            return 0
        total = 0
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    for entry in it:
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
                    total += os.path.getsize(current)
                except OSError:
                    pass
        return total

    @staticmethod
    def clean_directory(path: str, on_bytes_removed: Callable[[int], None], cancel_event: threading.Event) -> None:
        if not path or not os.path.exists(path):
            return
        for root, dirs, files in os.walk(path, topdown=False):
            if cancel_event.is_set():
                return
            for name in files:
                if cancel_event.is_set():
                    return
                file_path = os.path.join(root, name)
                try:
                    size = os.path.getsize(file_path)
                except OSError:
                    size = 0
                try:
                    os.chmod(file_path, 0o666)
                except OSError:
                    pass
                try:
                    os.remove(file_path)
                    if size > 0:
                        on_bytes_removed(size)
                except OSError:
                    continue
            for name in dirs:
                if cancel_event.is_set():
                    return
                dir_path = os.path.join(root, name)
                try:
                    os.rmdir(dir_path)
                except OSError:
                    continue


