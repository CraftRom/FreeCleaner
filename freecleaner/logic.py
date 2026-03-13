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


@dataclass(slots=True)
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
        preferred = None
        preferred_name = ""
        fallback = None
        fallback_name = ""
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            candidate = str(asset.get("browser_download_url") or "").strip()
            raw_asset_name = str(asset.get("name") or "").strip()
            asset_name = raw_asset_name.lower()
            if not candidate:
                continue
            if asset_name.endswith('.exe') and preferred is None:
                preferred = candidate
                preferred_name = raw_asset_name
            if fallback is None:
                fallback = candidate
                fallback_name = raw_asset_name
        download_url = preferred or fallback or html_url
        selected_asset_name = preferred_name or fallback_name

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
    def _clear_attributes(path: str, is_dir: bool = False) -> None:
        candidates = [path]
        extended = SafeFS._extended_path(path)
        if extended != path:
            candidates.append(extended)

        for candidate in candidates:
            try:
                os.chmod(candidate, stat.S_IWRITE | stat.S_IREAD)
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
    def _remove_file_native(path: str) -> bool:
        for candidate in (path, SafeFS._extended_path(path)):
            try:
                os.remove(candidate)
                return True
            except FileNotFoundError:
                return True
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
        quoted = os.path.abspath(path).replace('"', '""')
        commands = [
            f'cmd /c del /f /q /a "{quoted}"',
            'powershell -NoProfile -ExecutionPolicy Bypass -Command '
            f'"$p = [System.IO.Path]::GetFullPath(''{quoted}''); if (Test-Path -LiteralPath $p) {{ Remove-Item -LiteralPath $p -Force -ErrorAction Stop }}"',
        ]
        for cmd in commands:
            if WindowsOps.run_command(cmd, timeout=120):
                if not os.path.exists(path):
                    return True
        return not os.path.exists(path)

    @staticmethod
    def _remove_dir_shell(path: str) -> bool:
        quoted = os.path.abspath(path).replace('"', '""')
        commands = [
            f'cmd /c rd /s /q "{quoted}"',
            'powershell -NoProfile -ExecutionPolicy Bypass -Command '
            f'"$p = [System.IO.Path]::GetFullPath(''{quoted}''); if (Test-Path -LiteralPath $p) {{ Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop }}"',
        ]
        for cmd in commands:
            if WindowsOps.run_command(cmd, timeout=180):
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
        if os.path.isfile(path):
            return (1, 0)

        files = 0
        dirs = 0
        stack = [path]
        seen: Set[str] = set()
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_file(follow_symlinks=False):
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
            "scheduled_reboot": 0,
            "remaining_files": 0,
            "remaining_dirs": 0,
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
            removed = SafeFS._remove_file_native(path) or SafeFS._remove_file_shell(path)
            if removed:
                if size > 0:
                    on_bytes_removed(size)
                    result["removed_bytes"] += size
                result["files_removed"] += 1
                return result
            if SafeFS._schedule_for_delete(path):
                result["scheduled_reboot"] += 1
                return result
            result["errors"] += 1
            result["remaining_files"] = 1
            return result

        SafeFS._prepare_tree(path)

        all_dirs: List[str] = []
        all_files: List[str] = []
        try:
            for root, dirs, files in os.walk(path, topdown=False):
                if cancel_event.is_set():
                    return result
                for name in files:
                    all_files.append(os.path.join(root, name))
                for name in dirs:
                    all_dirs.append(os.path.join(root, name))
        except OSError:
            result["errors"] += 1

        for file_path in all_files:
            if cancel_event.is_set():
                return result
            try:
                size = os.path.getsize(file_path)
            except OSError:
                size = 0

            SafeFS._clear_attributes(file_path, is_dir=False)
            removed = SafeFS._remove_file_native(file_path)
            if not removed:
                time.sleep(0.02)
                SafeFS._clear_attributes(file_path, is_dir=False)
                removed = SafeFS._remove_file_native(file_path) or SafeFS._remove_file_shell(file_path)

            if removed:
                if size > 0:
                    on_bytes_removed(size)
                    result["removed_bytes"] += size
                result["files_removed"] += 1
                continue

            if SafeFS._schedule_for_delete(file_path):
                result["scheduled_reboot"] += 1
                continue

            result["errors"] += 1

        def _rmtree_onerror(func, failing_path, _exc_info):
            SafeFS._clear_attributes(failing_path, is_dir=os.path.isdir(failing_path))
            try:
                func(failing_path)
            except Exception:
                pass

        for dir_path in sorted(all_dirs, key=len, reverse=True):
            if cancel_event.is_set():
                return result
            if not os.path.exists(dir_path):
                continue

            SafeFS._clear_attributes(dir_path, is_dir=True)
            removed = SafeFS._remove_dir_native(dir_path)
            if not removed:
                try:
                    shutil.rmtree(dir_path, ignore_errors=False, onerror=_rmtree_onerror)
                    removed = not os.path.exists(dir_path)
                except Exception:
                    removed = False
            if not removed:
                removed = SafeFS._remove_dir_shell(dir_path)

            if removed:
                result["dirs_removed"] += 1
                continue

            if SafeFS._schedule_for_delete(dir_path):
                result["scheduled_reboot"] += 1
                continue

            result["errors"] += 1

        # Extra passes for stubborn empty folders under the target root.
        for _ in range(2):
            if cancel_event.is_set():
                return result
            for root, dirs, _files in os.walk(path, topdown=False):
                for name in dirs:
                    dir_path = os.path.join(root, name)
                    if not os.path.isdir(dir_path):
                        continue
                    SafeFS._clear_attributes(dir_path, is_dir=True)
                    if SafeFS._remove_dir_native(dir_path):
                        result["dirs_removed"] += 1

        remaining_files, remaining_dirs = SafeFS._count_remaining_entries(path)
        result["remaining_files"] = remaining_files
        result["remaining_dirs"] = remaining_dirs

        if remaining_files or remaining_dirs:
            result["errors"] += remaining_files + remaining_dirs

        return result

