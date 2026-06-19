# -*- mode: python ; coding: utf-8 -*-

"""PyInstaller build profile for FreeCleaner.

FreeCleaner is a Qt application.  The release build intentionally uses a
one-directory PyInstaller layout and the Inno Setup installer copies that whole
folder into Program Files.  This avoids the fragile one-file `_MEI...` temporary
extraction path where Python 3.13 can fail to load python313.dll or one of its
runtime dependencies on some Windows setups.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

block_cipher = None


def _unique_pairs(pairs):
    seen = set()
    result = []
    for src, dst in pairs:
        try:
            src = os.path.abspath(str(src))
        except Exception:
            src = str(src)
        key = (src.lower(), str(dst).replace('\\\\', '/').lower())
        if key in seen or not os.path.exists(src):
            continue
        seen.add(key)
        result.append((src, dst))
    return result


def _python_runtime_binaries():
    """Collect Python/VC runtime DLLs explicitly for Windows builds.

    PyInstaller usually discovers these files automatically, but Python 3.13
    and GitHub-hosted runners can leave the bootloader with a `python313.dll`
    LoadLibrary dependency failure if a VC runtime DLL is not staged next to the
    executable.  Keeping them explicit makes both CI and local builds stable.
    """
    roots = {
        Path(sys.executable).resolve().parent,
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
    }
    patterns = (
        'python*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
        'concrt*.dll',
    )
    pairs = []
    for root in roots:
        for pattern in patterns:
            for path in glob.glob(str(root / pattern)):
                pairs.append((path, '.'))
    return _unique_pairs(pairs)


a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=_python_runtime_binaries(),
    datas=[
        ('PRIVACY_POLICY.txt', '.'),
        ('LICENSE', '.'),
        ('assets/icons', 'assets/icons'),
        ('lang', 'lang'),
        ('app.ico', '.'),
        ('version_info.txt', '.'),
    ],
    hiddenimports=[
        'PySide6.QtCore',
        'PySide6.QtGui',
        'PySide6.QtWidgets',
        'PySide6.QtSvg',
        'freecleaner.qt_bootstrap',
        'freecleaner.qt_app',
        'freecleaner.logic',
        'freecleaner.runtime_logging',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['customtkinter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='FreeCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icons/app.ico',
    version='version_info.txt',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[
        'python*.dll',
        'vcruntime*.dll',
        'msvcp*.dll',
        'concrt*.dll',
        'PySide6*.dll',
        'Qt6*.dll',
    ],
    name='FreeCleaner',
)
