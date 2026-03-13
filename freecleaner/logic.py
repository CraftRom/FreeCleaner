"""Core logic layer: paths, versioning, i18n, and safe cleanup operations.

This module must NOT contain UI widget creation code.
"""

from __future__ import annotations

import os
import sys
import ctypes
import threading
import subprocess
import shutil
import stat
import time
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
from typing import Any, Callable, Optional, Dict, List, Tuple, Union

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
    def reg_add(path: str, name: str, value: Union[int, str], reg_type: str = "REG_DWORD") -> bool:
        safe_value = str(value).replace('"', '\"')
        cmd = f'reg add "{path}" /v "{name}" /t {reg_type} /d "{safe_value}" /f'
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
    def _clear_attributes(path: str, is_dir: bool = False) -> None:
        try:
            os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
        except OSError:
            pass
        if IS_WINDOWS:
            try:
                attrs = 0x10 if is_dir else 0x80
                ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
            except Exception:
                pass

    @staticmethod
    def _prepare_tree(path: str) -> None:
        if not IS_WINDOWS or not path or not os.path.isdir(path):
            return
        escaped = os.path.abspath(path).replace('\"', '')
        WindowsOps.run_command(f'attrib -r -s -h "{escaped}\\*" /s /d', timeout=180)

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
    def clean_directory(path: str, on_bytes_removed: Callable[[int], None], cancel_event: threading.Event) -> Dict[str, int]:
        result = {
            "removed_bytes": 0,
            "files_removed": 0,
            "dirs_removed": 0,
            "errors": 0,
        }
        if not path or not os.path.exists(path):
            return result

        if os.path.isfile(path):
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
            SafeFS._clear_attributes(path, is_dir=False)
            try:
                os.remove(path)
                if size > 0:
                    on_bytes_removed(size)
                    result["removed_bytes"] += size
                result["files_removed"] += 1
            except OSError:
                result["errors"] += 1
            return result

        SafeFS._prepare_tree(path)

        for root, dirs, files in os.walk(path, topdown=False):
            if cancel_event.is_set():
                return result
            for name in files:
                if cancel_event.is_set():
                    return result
                file_path = os.path.join(root, name)
                try:
                    size = os.path.getsize(file_path)
                except OSError:
                    size = 0
                SafeFS._clear_attributes(file_path, is_dir=False)
                try:
                    os.remove(file_path)
                except OSError:
                    time.sleep(0.02)
                    SafeFS._clear_attributes(file_path, is_dir=False)
                    try:
                        os.remove(file_path)
                    except OSError:
                        result["errors"] += 1
                        continue
                if size > 0:
                    on_bytes_removed(size)
                    result["removed_bytes"] += size
                result["files_removed"] += 1

            for name in dirs:
                if cancel_event.is_set():
                    return result
                dir_path = os.path.join(root, name)
                SafeFS._clear_attributes(dir_path, is_dir=True)
                try:
                    os.rmdir(dir_path)
                    result["dirs_removed"] += 1
                except OSError:
                    try:
                        if os.path.isdir(dir_path) and not os.listdir(dir_path):
                            shutil.rmtree(dir_path, ignore_errors=False)
                            result["dirs_removed"] += 1
                        else:
                            result["errors"] += 1
                    except OSError:
                        result["errors"] += 1

        # One more pass for stubborn empty folders inside the target
        for root, dirs, _files in os.walk(path, topdown=False):
            if cancel_event.is_set():
                return result
            for name in dirs:
                dir_path = os.path.join(root, name)
                SafeFS._clear_attributes(dir_path, is_dir=True)
                try:
                    os.rmdir(dir_path)
                    result["dirs_removed"] += 1
                except OSError:
                    pass

        return result


