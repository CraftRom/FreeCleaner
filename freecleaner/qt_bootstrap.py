"""Quiet Qt bootstrap used to keep one visible splash while modules load.

The launcher must not let PySide/Qt create visible helper windows before the
main window is ready.  On Windows we therefore show a tiny native Win32 splash
*before* importing PySide6.  It stays visible through QApplication creation,
heavy Qt module imports and FreeCleaner UI construction, then hands off to the
real main window.  Non-Windows/source fallback keeps the old Qt splash path.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Optional

from .runtime_logging import log_startup, log_app, log_qa_event

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.*=false")
# Keep Windows/Qt startup silent: no console, no activation jumps, no native
# tooltip/helper windows stealing focus while the splash is the only UI.
os.environ.setdefault("QT_USE_NATIVE_WINDOWS", "0")
os.environ.setdefault("QT_ENABLE_REGEXP_JIT", "0")


def _meta_from_file() -> dict[str, str]:
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "version_info.txt"),
        os.path.join(os.getcwd(), "version_info.txt"),
    ]
    meta: dict[str, str] = {}
    for path in candidates:
        try:
            if os.path.isfile(path):
                text = open(path, "r", encoding="utf-8", errors="ignore").read()
                for key in ("ProductName", "ProductVersion", "FileVersion"):
                    match = re.search(rf"{key}',\s*'([^']+)'", text)
                    if match:
                        meta[key] = match.group(1)
                if meta:
                    return meta
        except Exception:
            pass
    return meta


def _app_name_from_file() -> str:
    return _meta_from_file().get("ProductName") or "FreeCleaner"


def _version_from_file() -> str:
    meta = _meta_from_file()
    return meta.get("ProductVersion") or meta.get("FileVersion") or "Qt"


def _icon_path() -> Optional[str]:
    base = os.path.dirname(os.path.dirname(__file__))
    for rel in ("assets/icons/app.ico", "assets/icons/app.png", "app.ico"):
        path = os.path.join(base, rel)
        if os.path.isfile(path):
            return path
    return None


class NativeWinSplash:
    """One quiet Win32 splash window shown before PySide6 is imported.

    This avoids the Qt-splash failure mode where the Qt window can disappear or
    momentarily lose z-order exactly when PySide6/QtWidgets are importing.  The
    native splash is intentionally no-activate/toolwindow/no-taskbar and is kept
    alive until the main Qt window is already constructed.
    """

    _fc_native_splash = True

    def __init__(self) -> None:
        self.hwnd = None
        self._user32 = None
        self._gdi32 = None
        self._wndproc_ref = None
        self._class_name = "FreeCleanerQuietStartupSplash"
        self._progress = 6
        self._message = "Підготовка запуску…"
        self._app_name = _app_name_from_file()
        self._version = _version_from_file()
        self._width = 460
        self._height = 250
        self._created = False
        self._paint_failed_logged = False
        if os.name == "nt":
            try:
                self._create()
            except Exception as exc:
                log_startup(f"native splash create failed: {exc}", level="WARNING")
                self.hwnd = None
                self._created = False

    @property
    def is_available(self) -> bool:
        return bool(self._created and self.hwnd)

    def _create(self) -> None:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32
        kernel32 = ctypes.windll.kernel32
        self._user32 = user32
        self._gdi32 = gdi32

        HANDLE = ctypes.c_void_p
        HWND = getattr(wintypes, "HWND", HANDLE)
        HINSTANCE = getattr(wintypes, "HINSTANCE", HANDLE)
        HICON = getattr(wintypes, "HICON", HANDLE)
        HCURSOR = getattr(wintypes, "HCURSOR", HANDLE)
        HBRUSH = getattr(wintypes, "HBRUSH", HANDLE)
        LRESULT = ctypes.c_longlong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_long
        WNDPROC = ctypes.WINFUNCTYPE(LRESULT, HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        class WNDCLASS(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", HINSTANCE),
                ("hIcon", HICON),
                ("hCursor", HCURSOR),
                ("hbrBackground", HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        self._RECT = wintypes.RECT

        class PAINTSTRUCT(ctypes.Structure):
            _fields_ = [
                ("hdc", wintypes.HDC),
                ("fErase", wintypes.BOOL),
                ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL),
                ("fIncUpdate", wintypes.BOOL),
                ("rgbReserved", ctypes.c_byte * 32),
            ]

        self._PAINTSTRUCT = PAINTSTRUCT
        self._WNDPROC = WNDPROC
        # Python 3.13 on Windows does not expose every Win32 handle alias in
        # ctypes.wintypes (for example HCURSOR/HICON can be missing).  Also,
        # raw ctypes Win32 calls return 32-bit ints by default, which can
        # truncate HWND/HBRUSH values on 64-bit Windows and make the native
        # splash fail before Qt is imported.  Define the needed handle aliases
        # above and pin prototypes here so the silent native splash is reliable
        # and never falls back to the flickery Qt splash just because of type
        # metadata differences between Python builds.
        self._DefWindowProcW = user32.DefWindowProcW
        self._DefWindowProcW.restype = LRESULT
        self._DefWindowProcW.argtypes = [HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
        kernel32.GetModuleHandleW.restype = HINSTANCE
        kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        user32.LoadCursorW.restype = HCURSOR
        # lpCursorName also accepts MAKEINTRESOURCEW(IDC_ARROW).  Model it as
        # a raw handle-sized pointer so Python does not try to convert 32512 to
        # a Unicode string and abort native splash creation.
        user32.LoadCursorW.argtypes = [HINSTANCE, HANDLE]
        kernel32.GetLastError.restype = wintypes.DWORD
        user32.RegisterClassW.restype = wintypes.ATOM
        user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
        user32.CreateWindowExW.restype = HWND
        user32.CreateWindowExW.argtypes = [
            wintypes.DWORD,
            wintypes.LPCWSTR,
            wintypes.LPCWSTR,
            wintypes.DWORD,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            HWND,
            HANDLE,
            HINSTANCE,
            HANDLE,
        ]
        user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
        user32.SetWindowPos.argtypes = [HWND, HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user32.UpdateWindow.argtypes = [HWND]
        user32.InvalidateRect.argtypes = [HWND, HANDLE, wintypes.BOOL]
        user32.DestroyWindow.argtypes = [HWND]
        user32.SetLayeredWindowAttributes.argtypes = [HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD]
        HDC = getattr(wintypes, "HDC", HANDLE)
        HFONT = HANDLE
        HGDIOBJ = HANDLE
        gdi32.CreateSolidBrush.restype = HBRUSH
        gdi32.CreateSolidBrush.argtypes = [wintypes.DWORD]
        # Pin GDI/User painting APIs too. Without these prototypes Python can try
        # to squeeze 64-bit HBRUSH/HFONT handles into 32-bit C ints during
        # WM_PAINT, producing callback OverflowError and leaving the splash blank
        # or flickery exactly while Qt modules are loading.
        user32.BeginPaint.restype = HDC
        user32.BeginPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)]
        user32.EndPaint.restype = wintypes.BOOL
        user32.EndPaint.argtypes = [HWND, ctypes.POINTER(PAINTSTRUCT)]
        user32.FillRect.restype = ctypes.c_int
        user32.FillRect.argtypes = [HDC, ctypes.POINTER(wintypes.RECT), HBRUSH]
        user32.DrawTextW.restype = ctypes.c_int
        user32.DrawTextW.argtypes = [HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
        gdi32.CreateFontW.restype = HFONT
        gdi32.SelectObject.restype = HGDIOBJ
        gdi32.SelectObject.argtypes = [HDC, HGDIOBJ]
        gdi32.DeleteObject.restype = wintypes.BOOL
        gdi32.DeleteObject.argtypes = [HGDIOBJ]
        gdi32.SetTextColor.restype = wintypes.DWORD
        gdi32.SetTextColor.argtypes = [HDC, wintypes.DWORD]
        gdi32.SetBkMode.restype = ctypes.c_int
        gdi32.SetBkMode.argtypes = [HDC, ctypes.c_int]

        self._WM_PAINT = 0x000F
        self._WM_DESTROY = 0x0002
        self._SW_SHOWNOACTIVATE = 4
        self._SWP_NOMOVE = 0x0002
        self._SWP_NOSIZE = 0x0001
        self._HWND_TOPMOST = HWND(-1)
        self._WS_POPUP = 0x80000000
        self._WS_EX_TOOLWINDOW = 0x00000080
        self._WS_EX_NOACTIVATE = 0x08000000
        self._WS_EX_TOPMOST = 0x00000008
        self._WS_EX_LAYERED = 0x00080000
        self._LWA_ALPHA = 0x00000002

        hinstance = kernel32.GetModuleHandleW(None)
        self._wndproc_ref = WNDPROC(self._wndproc)
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc_ref
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = hinstance
        wc.hIcon = HICON(0)
        cursor = user32.LoadCursorW(HINSTANCE(0), HANDLE(32512))  # IDC_ARROW
        wc.hCursor = cursor or HCURSOR(0)
        wc.hbrBackground = gdi32.CreateSolidBrush(0x151615)
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name
        atom = user32.RegisterClassW(ctypes.byref(wc))
        if not atom:
            # ERROR_CLASS_ALREADY_EXISTS is OK during rapid relaunch while the
            # previous process is still closing.  Any other registration failure
            # should fall back only with a precise diagnostic.
            last_error = int(kernel32.GetLastError() or 0)
            if last_error != 1410:
                raise ctypes.WinError(last_error)

        screen_w = user32.GetSystemMetrics(0)
        screen_h = user32.GetSystemMetrics(1)
        x = max(0, int((screen_w - self._width) / 2))
        y = max(0, int((screen_h - self._height) / 2))
        exstyle = self._WS_EX_TOOLWINDOW | self._WS_EX_NOACTIVATE | self._WS_EX_TOPMOST | self._WS_EX_LAYERED
        hwnd = user32.CreateWindowExW(
            exstyle,
            self._class_name,
            "FreeCleaner startup",
            self._WS_POPUP,
            x,
            y,
            self._width,
            self._height,
            HWND(0),
            HANDLE(0),
            hinstance,
            HANDLE(0),
        )
        if not hwnd:
            raise RuntimeError("CreateWindowExW returned null")
        self.hwnd = hwnd
        try:
            user32.SetLayeredWindowAttributes(hwnd, 0, 248, self._LWA_ALPHA)
        except Exception:
            pass
        user32.ShowWindow(hwnd, self._SW_SHOWNOACTIVATE)
        user32.SetWindowPos(hwnd, self._HWND_TOPMOST, 0, 0, 0, 0, self._SWP_NOMOVE | self._SWP_NOSIZE)
        user32.UpdateWindow(hwnd)
        self._created = True
        self._pump()
        log_startup("native quiet splash shown before PySide import")
        log_qa_event("native_quiet_splash_shown")

    def _wndproc(self, hwnd: Any, msg: int, wparam: Any, lparam: Any) -> int:
        if msg == getattr(self, "_WM_PAINT", 0x000F):
            try:
                self._paint(hwnd)
            except Exception as exc:
                # Never let a ctypes callback exception escape: Windows will keep
                # sending WM_PAINT and Python will log noisy "Exception ignored"
                # tracebacks during startup. One precise warning is enough; the
                # app can continue and the Qt UI will still load.
                if not getattr(self, "_paint_failed_logged", False):
                    self._paint_failed_logged = True
                    log_startup(f"native splash paint failed: {exc}", level="WARNING")
            return 0
        return self._DefWindowProcW(hwnd, msg, wparam, lparam)

    def _rgb(self, r: int, g: int, b: int) -> int:
        return int(r) | (int(g) << 8) | (int(b) << 16)

    def _draw_text(self, hdc: Any, text: str, rect_tuple: tuple[int, int, int, int], size: int, weight: int, color: tuple[int, int, int], *, center: bool = True) -> None:
        import ctypes
        from ctypes import wintypes

        gdi32 = self._gdi32
        user32 = self._user32
        if not gdi32 or not user32:
            return
        font = gdi32.CreateFontW(
            -size,
            0,
            0,
            0,
            weight,
            0,
            0,
            0,
            1,  # DEFAULT_CHARSET
            0,
            0,
            5,  # CLEARTYPE_QUALITY
            0,
            "Segoe UI",
        )
        old_font = gdi32.SelectObject(hdc, font)
        gdi32.SetTextColor(hdc, self._rgb(*color))
        gdi32.SetBkMode(hdc, 1)  # TRANSPARENT
        left, top, right, bottom = rect_tuple
        rect = wintypes.RECT(left, top, right, bottom)
        flags = 0x00000020 | 0x00000004 | 0x00000400  # SINGLELINE|VCENTER|END_ELLIPSIS
        if center:
            flags |= 0x00000001  # CENTER
        user32.DrawTextW(hdc, text, -1, ctypes.byref(rect), flags)
        gdi32.SelectObject(hdc, old_font)
        gdi32.DeleteObject(font)

    def _fill_rect(self, hdc: Any, rect_tuple: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
        import ctypes
        from ctypes import wintypes

        gdi32 = self._gdi32
        user32 = self._user32
        if not gdi32 or not user32:
            return
        rect = wintypes.RECT(*rect_tuple)
        brush = gdi32.CreateSolidBrush(self._rgb(*color))
        user32.FillRect(hdc, ctypes.byref(rect), brush)
        gdi32.DeleteObject(brush)

    def _paint(self, hwnd: Any) -> None:
        import ctypes
        user32 = self._user32
        gdi32 = self._gdi32
        if not user32 or not gdi32:
            return
        ps = self._PAINTSTRUCT()
        hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
        try:
            self._fill_rect(hdc, (0, 0, self._width, self._height), (21, 22, 21))
            self._fill_rect(hdc, (0, 0, self._width, 1), (48, 49, 48))
            self._fill_rect(hdc, (0, self._height - 1, self._width, self._height), (48, 49, 48))
            self._fill_rect(hdc, (0, 0, 1, self._height), (48, 49, 48))
            self._fill_rect(hdc, (self._width - 1, 0, self._width, self._height), (48, 49, 48))
            self._draw_text(hdc, self._app_name, (30, 92, 430, 126), 26, 900, (255, 255, 255), center=True)
            self._fill_rect(hdc, (30, 132, 430, 135), (118, 185, 0))
            self._draw_text(hdc, self._message, (30, 142, 430, 166), 14, 500, (219, 219, 219), center=True)
            self._fill_rect(hdc, (30, 180, 430, 188), (48, 49, 48))
            progress_w = max(0, min(400, int(400 * self._progress / 100)))
            if progress_w:
                self._fill_rect(hdc, (30, 180, 30 + progress_w, 188), (118, 185, 0))
            self._draw_text(hdc, f"Версія {self._version}", (30, 206, 430, 228), 12, 500, (168, 168, 168), center=True)
        finally:
            user32.EndPaint(hwnd, ctypes.byref(ps))

    def _pump(self) -> None:
        if os.name != "nt" or not self._user32:
            return
        try:
            import ctypes
            from ctypes import wintypes

            class MSG(ctypes.Structure):
                _fields_ = [
                    ("hwnd", wintypes.HWND),
                    ("message", wintypes.UINT),
                    ("wParam", wintypes.WPARAM),
                    ("lParam", wintypes.LPARAM),
                    ("time", wintypes.DWORD),
                    ("pt", wintypes.POINT),
                ]

            msg = MSG()
            PM_REMOVE = 0x0001
            while self._user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))
        except Exception:
            pass

    def show_centered(self) -> None:
        # Already centered and shown by _create().  Kept for splash API parity.
        self._pump()

    def set_progress(self, value: int, message: str = "") -> None:
        self._progress = max(0, min(100, int(value)))
        if message:
            self._message = str(message)
        if self.hwnd and self._user32:
            try:
                self._user32.InvalidateRect(self.hwnd, None, True)
                self._user32.UpdateWindow(self.hwnd)
                self._pump()
            except Exception:
                pass

    def fade_out(self) -> None:
        # Keep visible until qt_app.show_main_window closes it.  Closing here is
        # what produced the black/background gap during Qt handoff.
        self._pump()

    def close(self) -> None:
        if self.hwnd and self._user32:
            try:
                self._user32.DestroyWindow(self.hwnd)
                self._pump()
            except Exception:
                pass
        self.hwnd = None
        self._created = False


def _qt_message_handler(mode, context, message):
    try:
        text = str(message)
        if "setHighDpi" in text or "ScaleFactorRoundingPolicy" in text:
            return
        if "QFont::setPointSize" in text and "Point size <= 0" in text:
            # Qt can emit this harmless warning while resolving theme/default
            # fonts on Windows.  It does not affect rendering and only makes
            # startup/app logs look broken to users.
            log_qa_event("qt_font_warning_suppressed", message=text)
            return
        log_startup(f"Qt: {text}", level="WARNING")
        log_app(f"Qt: {text}", level="WARNING")
    except Exception:
        pass


def configure_high_dpi() -> None:
    log_startup("configure_high_dpi via environment variables only")
    return


def _make_qt_splash_class(Qt, QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget, QIcon, QFont):
    class EarlySplash(QWidget):
        def __init__(self, icon_path: Optional[str] = None) -> None:
            super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            self.setAttribute(Qt.WA_ShowWithoutActivating, True)
            self.setAttribute(Qt.WA_NativeWindow, True)
            self.setAttribute(Qt.WA_NoSystemBackground, False)
            self.setAttribute(Qt.WA_OpaquePaintEvent, True)
            self.setFixedSize(460, 250)
            self.setStyleSheet("""
                QWidget { background: #151615; color: #F4F4F4; font-family: Segoe UI, Arial; }
                QWidget#SplashRoot { border: 1px solid #303130; }
                QLabel#Title { font-size: 28px; font-weight: 900; color: #FFFFFF; }
                QLabel#Muted { color: #BDBDBD; }
                QLabel#Tiny { color: #A8A8A8; font-size: 11px; }
                QFrame#Accent { background: #76B900; min-height: 3px; max-height: 3px; }
                QProgressBar { background: #303130; border: 0; height: 8px; color: transparent; }
                QProgressBar::chunk { background: #76B900; }
            """)
            self.setObjectName("SplashRoot")
            layout = QVBoxLayout(self)
            layout.setContentsMargins(30, 26, 30, 18)
            layout.setSpacing(0)
            layout.addSpacing(64)
            title = QLabel(_app_name_from_file())
            title.setObjectName("Title")
            title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            title.setFixedHeight(34)
            title.setFont(QFont("Segoe UI", 18, 800))
            title.setStyleSheet("color: #FFFFFF;")
            layout.addWidget(title)
            layout.addSpacing(10)
            accent = QFrame()
            accent.setObjectName("Accent")
            accent.setFixedHeight(3)
            layout.addWidget(accent)
            layout.addSpacing(10)
            self.message = QLabel("Підготовка запуску…")
            self.message.setObjectName("Muted")
            self.message.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.message.setFixedHeight(22)
            self.message.setFont(QFont("Segoe UI", 10, 500))
            self.message.setStyleSheet("color: #DBDBDB;")
            layout.addWidget(self.message)
            layout.addSpacing(14)
            self.progress = QProgressBar()
            self.progress.setRange(0, 100)
            self.progress.setValue(8)
            self.progress.setFixedHeight(8)
            layout.addWidget(self.progress)
            layout.addSpacing(16)
            version = QLabel(f"Версія {_version_from_file()}")
            version.setObjectName("Tiny")
            version.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            version.setFixedHeight(18)
            version.setFont(QFont("Segoe UI", 9, 500))
            version.setStyleSheet("color: #A8A8A8;")
            layout.addWidget(version)
            layout.addStretch(1)
            self._fade_target = "show"

        def show_centered(self) -> None:
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(geo.center() - self.rect().center())
            self.show()
            self.raise_()
            self._fade_target = "show"
            try:
                QApplication.processEvents()
            except Exception:
                pass

        def set_progress(self, value: int, message: str = "") -> None:
            self.progress.setValue(max(0, min(100, int(value))))
            if message:
                self.message.setText(message)
            try:
                QApplication.processEvents()
            except Exception:
                pass

        def fade_out(self) -> None:
            self._fade_target = "hide"
            # Keep parity with build-39 fallback behavior.
            self.close()

    return EarlySplash


def main() -> int:
    log_startup("qt_bootstrap.main start")
    log_qa_event("qt_bootstrap_start", argv=sys.argv, pid=os.getpid())
    configure_high_dpi()

    # Windows path: create a native splash before PySide6 is imported.  This is
    # the important part: while Qt modules are prepared, the only visible window
    # is this quiet Win32 splash, not a Qt top-level that can lose z-order.
    native_splash: Optional[NativeWinSplash] = None
    if os.name == "nt" and os.environ.get("FREECLEANER_DISABLE_NATIVE_SPLASH") != "1":
        native_splash = NativeWinSplash()
        if native_splash.is_available:
            native_splash.set_progress(20, "Підготовка модулів Qt…")
        else:
            native_splash = None

    log_startup("importing PySide6 for QApplication")
    from PySide6.QtCore import Qt, qInstallMessageHandler
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

    try:
        qInstallMessageHandler(_qt_message_handler)
        log_startup("Qt message handler installed")
    except Exception as exc:
        log_startup(f"Qt message handler failed: {exc}", level="ERROR")

    log_startup("creating QApplication")
    app = QApplication(sys.argv)
    log_qa_event("qapplication_created", screens=len(QApplication.screens()))
    app.setApplicationName("FreeCleaner")
    app.setApplicationDisplayName("FreeCleaner")
    app.setOrganizationName("FreeCleaner")
    app.setQuitOnLastWindowClosed(False)
    icon = _icon_path()
    if icon:
        app.setWindowIcon(QIcon(icon))

    splash: Any = native_splash
    if splash is None:
        EarlySplash = _make_qt_splash_class(Qt, QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget, QIcon, QFont)
        splash = EarlySplash(icon)
        log_startup("showing fallback Qt splash")
        splash.show_centered()
        log_qa_event("early_splash_shown")
        splash.set_progress(28, "Підготовка модулів Qt…")
    else:
        log_qa_event("early_splash_shown", kind="native_win32")

    log_startup("importing full qt_app")
    splash.set_progress(48, "Тихе завантаження Qt інтерфейсу…")
    from . import qt_app
    splash.set_progress(70, "Завантаження інтерфейсу FreeCleaner…")
    log_startup("handoff to full qt_app")
    return qt_app.launch_existing_app(app, splash)


if __name__ == "__main__":
    raise SystemExit(main())
