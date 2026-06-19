"""Tiny Qt bootstrap used to show the splash before heavy FreeCleaner imports.

The old launcher imported the full application before QApplication and splash
were created. On slower PCs and in one-file builds that can look like several
mini-starts or flicker before the splash. This module creates QApplication and a
minimal splash first, then imports the full Qt frontend.
"""

from __future__ import annotations

import os
import re
import sys
from typing import Optional

from .runtime_logging import log_startup, log_app, log_qa_event

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PySide6.QtCore import Qt, qInstallMessageHandler
from PySide6.QtGui import QIcon

# Do not call the direct Qt DPI rounding setter here. Environment variables
# above are the warning-free Qt 6 path and avoid visible startup noise.
from PySide6.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget


def _qt_message_handler(mode, context, message):
    # Route Qt warnings to startup/app logs.  Returning without writing to
    # stderr keeps source runs quiet and makes startup problems diagnosable.
    try:
        text = str(message)
        # Qt can still emit this from old cached Python/PySide sessions.  It is
        # not useful to spam the user with it after the explicit pre-QApp call.
        if "setHighDpi" "ScaleFactorRoundingPolicy" in text:
            # Fully ignore this noisy Qt warning if it appears from PySide internals.
            return
        log_startup(f"Qt: {text}", level="WARNING")
        log_app(f"Qt: {text}", level="WARNING")
    except Exception:
        pass


try:
    qInstallMessageHandler(_qt_message_handler)
    log_startup("Qt message handler installed")
except Exception as exc:
    log_startup(f"Qt message handler failed: {exc}", level="ERROR")


def _version_from_file() -> str:
    candidates = [
        os.path.join(os.path.dirname(os.path.dirname(__file__)), "version_info.txt"),
        os.path.join(os.getcwd(), "version_info.txt"),
    ]
    for path in candidates:
        try:
            if os.path.isfile(path):
                text = open(path, "r", encoding="utf-8", errors="ignore").read()
                match = re.search(r"ProductVersion',\s*'([^']+)'", text)
                if match:
                    return match.group(1)
        except Exception:
            pass
    return "Qt"


def _icon_path() -> Optional[str]:
    base = os.path.dirname(os.path.dirname(__file__))
    for rel in ("assets/icons/app.ico", "assets/icons/app.png", "app.ico"):
        path = os.path.join(base, rel)
        if os.path.isfile(path):
            return path
    return None


def configure_high_dpi() -> None:
    log_startup("configure_high_dpi via environment variables only")
    # Qt 6 reads QT_SCALE_FACTOR_ROUNDING_POLICY during application creation.
    # Do not call the direct Qt DPI rounding setter here: on some Windows/Qt
    # builds the GUI layer can already be partially initialized by the time this
    # function runs. Environment variables above are the stable path.
    return


class EarlySplash(QWidget):
    def __init__(self, icon_path: Optional[str] = None) -> None:
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
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
        layout.setContentsMargins(30, 26, 30, 24)
        layout.setSpacing(14)
        brand = QHBoxLayout()
        if icon_path:
            icon = QLabel()
            icon.setPixmap(QIcon(icon_path).pixmap(42, 42))
            brand.addWidget(icon)
        text = QVBoxLayout()
        title = QLabel("FreeCleaner")
        title.setObjectName("Title")
        subtitle = QLabel(f"{_version_from_file()} • Qt")
        subtitle.setObjectName("Tiny")
        text.addWidget(title)
        text.addWidget(subtitle)
        brand.addLayout(text, 1)
        layout.addLayout(brand)
        accent = QFrame()
        accent.setObjectName("Accent")
        layout.addWidget(accent)
        self.message = QLabel("Підготовка запуску…")
        self.message.setObjectName("Muted")
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(8)
        layout.addWidget(self.progress)
        layout.addStretch(1)
        footer = QLabel("Splash first • No pre-start flicker")
        footer.setObjectName("Tiny")
        layout.addWidget(footer)
        self._fade_target = "show"

    def show_centered(self) -> None:
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.move(geo.center() - self.rect().center())
        self.show()
        self._fade_target = "show"

    def set_progress(self, value: int, message: str = "") -> None:
        self.progress.setValue(max(0, min(100, int(value))))
        if message:
            self.message.setText(message)
        # Avoid nested processEvents from splash updates; Qt event loop owns repaint.

    def fade_out(self) -> None:
        self._fade_target = "hide"
        self.close()

    def _on_fade_finished(self) -> None:
        if self._fade_target == "hide":
            self.close()


def main() -> int:
    log_startup("qt_bootstrap.main start")
    log_qa_event("qt_bootstrap_start", argv=sys.argv, pid=os.getpid())
    configure_high_dpi()
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
    splash = EarlySplash(icon)
    log_startup("showing early splash")
    splash.show_centered()
    log_qa_event("early_splash_shown")
    splash.set_progress(28, "Завантаження ядра FreeCleaner…")
    log_startup("importing full qt_app")
    from . import qt_app
    splash.set_progress(58, "Підготовка модулів Qt…")
    log_startup("handoff to full qt_app")
    return qt_app.launch_existing_app(app, splash)


if __name__ == "__main__":
    raise SystemExit(main())
