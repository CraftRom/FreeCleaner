"""Qt application layer for FreeCleaner.

Full PySide6 frontend for the Windows cleanup, diagnostics and registry logic.
The interface uses a modern dark navigation rail, NVIDIA-App-like settings
structure, startup splash, animated toggles, availability states and explicit
administrator-mode entry points.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import json
import locale
import os
import re
import sys
import threading
import time
import webbrowser
import shutil
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover
    winreg = None  # type: ignore

from PySide6.QtCore import QObject, Qt, QThread, Signal, QSize, QTimer, Property, QEvent, QPropertyAnimation, QEasingCurve, QPoint
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QAbstractItemView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QProgressBar,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QTabWidget,
    QGraphicsDropShadowEffect,
    QGraphicsOpacityEffect,
    QToolButton,
    QStyle,
    QVBoxLayout,
    QWidget,
)

from .logic import (
    APP_VERSION,
    APP_VERSION_RAW,
    APP_UPDATE_LATEST_RELEASE_URL,
    APP_UPDATE_OWNER,
    APP_UPDATE_RELEASES_URL,
    APP_UPDATE_REPO,
    CONFIG_PATH,
    LEGACY_CONFIG_PATH,
    CLEAN_WORKERS,
    SCAN_WORKERS,
    IS_WINDOWS,
    LANG_PACKS,
    LANG_PACK_SOURCES,
    CleanerTask,
    PathFinder,
    RegistryValueSpec,
    SafeFS,
    WindowsOps,
    cleanup_old_update_files,
    compare_versions,
    download_url_to_file,
    fetch_latest_github_release,
    find_icon_path,
    get_adaptive_workers,
    get_update_download_path,
    get_updates_dir,
    get_user_data_dir,
    get_logs_dir,
    get_system_drive_info,
    guess_download_filename,
    language_display_name,
    launch_update_installer,
    schedule_update_cleanup_after_install,
)
from .runtime_logging import log_app, log_startup, log_error, log_action, log_security, log_qa_event, log_system_response, all_log_paths, app_log_path, startup_log_path

APP_QSS = r"""
* {
    font-family: "Segoe UI", "Inter", "Arial";
    font-size: 13px;
}
QMainWindow, QWidget#Root {
    background: #151615;
    color: #F4F4F4;
}
QFrame#TopBar {
    background: #242524;
    border-bottom: 1px solid #303130;
}
QFrame#NavRail {
    background: #101110;
    border-right: 1px solid #2A2B2A;
}
QToolButton#NavButton {
    color: #BEBEBE;
    background: transparent;
    border: 0;
    border-left: 3px solid transparent;
    padding: 6px 0px 6px 0px;
    margin: 0px;
    text-align: center;
    font-size: 11px;
    min-width: 78px;
    max-width: 78px;
}
QToolButton#NavButton:hover {
    background: #202120;
    color: #FFFFFF;
}
QToolButton#NavButton:checked {
    background: #1D2417;
    border-left: 3px solid #76B900;
    color: #FFFFFF;
}
QToolButton#WindowIconButton {
    background: transparent;
    border: 0;
    color: #CFCFCF;
    padding: 6px;
    font-size: 15px;
}
QToolButton#WindowIconButton:hover { background: #323332; color: #FFFFFF; }
QLabel#BrandTitle {
    color: #FFFFFF;
    font-size: 16px;
    font-weight: 800;
}
QLabel#VersionText, QLabel#Tiny {
    color: #A8A8A8;
    font-size: 11px;
}
QLabel#PageTitle {
    color: #FFFFFF;
    font-size: 21px;
    font-weight: 800;
}
QLabel#PageSubtitle, QLabel#Muted, QLabel#SectionSub {
    color: #BDBDBD;
}
QLabel#SectionTitle {
    color: #FFFFFF;
    font-size: 14px;
    font-weight: 800;
}
QFrame#Panel, QFrame#StatusCard, QFrame#TaskRow, QFrame#RegistryPanel, QFrame#SettingsSection {
    background: #1A1B1A;
    border: 1px solid #2C2D2C;
    border-radius: 0px;
}
QFrame#SettingsCard {
    background: #1A1B1A;
    border: 1px solid #2C2D2C;
    border-left: 3px solid transparent;
    border-radius: 0px;
}
QFrame#SettingsCard:hover {
    background: #202120;
    border-color: #3A3B3A;
    border-left-color: #76B900;
}
QFrame#SettingsCard[pressed="true"] {
    background: #202A17;
    border-color: #76B900;
}
QFrame#SettingsCard[changed="true"] {
    border-left-color: #F59E0B;
}
QLabel#SettingsKey {
    color: #8F928F;
    font-size: 10px;
}
QLabel#SettingsRestart {
    color: #FFD166;
    font-size: 10px;
    font-weight: 800;
}
QFrame#TaskRow:hover, QFrame#StatusCard:hover {
    background: #202120;
    border-color: #3A3B3A;
}
QFrame#TaskRow[availability="admin"] {
    border-left: 3px solid #F59E0B;
}
QFrame#TaskRow[availability="disabled"] {
    border-left: 3px solid #5D5D5D;
    background: #171817;
}
QFrame#TaskRow[availability="ready"] {
    border-left: 3px solid #76B900;
}
QFrame#TaskRow[availability="applied"] {
    border-left: 3px solid #76B900;
}
QFrame#TaskRow[availability="running"] {
    border-left: 3px solid #76B900;
    background: #202120;
}
QFrame#TaskRow[selected="true"] {
    border-color: #76B900;
}
QFrame#TaskRow[selected="true"] QLabel#SectionTitle {
    color: #FFFFFF;
}
QFrame#AccentGreen, QFrame#StatusAccentGreen { background: #76B900; }
QFrame#AccentBlue, QFrame#StatusAccentBlue { background: #4C8DFF; }
QFrame#AccentAmber, QFrame#StatusAccentAmber { background: #F59E0B; }
QFrame#AccentRed, QFrame#StatusAccentRed { background: #EF4444; }
QFrame#ThinSeparator { background: #2C2D2C; min-height: 1px; max-height: 1px; }
QLabel#PillGreen, QLabel#PillBlue, QLabel#PillAmber, QLabel#PillRed, QLabel#PillGrey {
    padding: 4px 10px;
    border-radius: 0px;
    font-size: 11px;
    font-weight: 800;
}
QLabel#PillGreen { color: #091100; background: #76B900; }
QLabel#PillBlue { color: #061226; background: #4C8DFF; }
QLabel#PillAmber { color: #1B1000; background: #F59E0B; }
QLabel#PillRed { color: #220707; background: #EF4444; }
QLabel#PillGrey { color: #D7D7D7; background: #333433; }
QPushButton, QToolButton#PlainButton {
    background: #2A2B2A;
    border: 1px solid #3A3B3A;
    border-radius: 0px;
    color: #F5F5F5;
    padding: 9px 14px;
    font-weight: 700;
}
QPushButton:hover, QToolButton#PlainButton:hover {
    background: #343534;
    border-color: #4B4C4B;
}
QPushButton:pressed, QToolButton#PlainButton:pressed { background: #232423; }
QPushButton#PrimaryButton {
    background: #76B900;
    color: #071100;
    border: 1px solid #76B900;
    font-weight: 900;
}
QPushButton#PrimaryButton:hover { background: #86D000; }
QPushButton#DangerButton {
    background: #401818;
    color: #FCA5A5;
    border: 1px solid #7F1D1D;
}
QPushButton#WarningButton {
    background: #3A2600;
    color: #FFD166;
    border: 1px solid #8A5B00;
}
QPushButton#GhostButton {
    background: transparent;
    border: 1px solid #3A3B3A;
    color: #E5E7EB;
}
QPushButton:disabled, QToolButton:disabled {
    color: #777777;
    background: #191A19;
    border-color: #252625;
}
QLineEdit, QComboBox, QTextEdit, QListWidget, QTreeWidget {
    background: #202120;
    color: #F7F7F7;
    border: 1px solid #343534;
    border-radius: 0px;
    selection-background-color: #76B900;
    selection-color: #101110;
}
QLineEdit { padding: 9px 10px; }
QTreeWidget { alternate-background-color: #1B1C1B; outline: 0; }
QTreeWidget::item { padding: 7px 6px; border-bottom: 1px solid #272827; }
QTreeWidget::item:selected { background: #263619; color: #FFFFFF; }
QHeaderView::section { background: #242524; color: #D8D8D8; border: 0; border-right: 1px solid #303130; padding: 8px 7px; font-weight: 800; }
QComboBox { padding: 8px 10px; }
QComboBox::drop-down { border: 0; width: 28px; }
QCheckBox { color: #F5F5F5; spacing: 10px; }
QCheckBox::indicator {
    width: 18px;
    height: 18px;
    border: 2px solid #A7A7A7;
    background: #151615;
}
QCheckBox::indicator:hover { border-color: #FFFFFF; background: #202120; }
QCheckBox::indicator:checked { background: #76B900; border: 2px solid #76B900; }
QCheckBox::indicator:checked:hover { background: #86D000; border-color: #86D000; }
QCheckBox::indicator:disabled { background: #262726; border-color: #555655; }
QCheckBox::indicator:checked:disabled { background: #76B900; border-color: #76B900; }
QCheckBox:disabled { color: #777777; }
QTabWidget::pane { border: 0; background: transparent; }
QTabBar::tab {
    background: transparent;
    color: #CFCFCF;
    padding: 11px 20px 9px 20px;
    border-bottom: 3px solid transparent;
    font-weight: 700;
}
QTabBar::tab:hover { color: #FFFFFF; }
QTabBar::tab:selected { color: #FFFFFF; border-bottom: 3px solid #76B900; }
QProgressBar {
    background: #303130;
    border: 0;
    border-radius: 0px;
    height: 8px;
    text-align: center;
    color: transparent;
}
QProgressBar::chunk { background: #76B900; }
QScrollArea { border: 0; background: transparent; }
QScrollBar:vertical { background: #151615; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #555655; min-height: 36px; }
QScrollBar::handle:vertical:hover { background: #6B6C6B; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QDialog#UpdateDialog {
    background: #151615;
    color: #F4F4F4;
}
QFrame#UpdateHero {
    background: #1D1E1D;
    border: 1px solid #2F302F;
    border-left: 4px solid #76B900;
}
QFrame#UpdateVersionCard {
    background: #1A1B1A;
    border: 1px solid #2C2D2C;
}
QFrame#UpdateStepCard {
    background: #191A19;
    border: 1px solid #2B2C2B;
}
QLabel#UpdateHeroTitle {
    color: #FFFFFF;
    font-size: 24px;
    font-weight: 900;
}
QLabel#UpdateVersionValue {
    color: #FFFFFF;
    font-size: 18px;
    font-weight: 900;
}
QLabel#UpdateStatusText {
    color: #F4F4F4;
    font-weight: 800;
}
QLabel#UpdateMetaText {
    color: #A8A8A8;
    font-size: 12px;
}

QWidget#SplashRoot { background: #151615; border: 1px solid #303130; }

QFrame#HomeHero {
    background: #1D1E1D;
    border: 1px solid #2F302F;
    border-left: 4px solid #76B900;
    border-radius: 0px;
}
QFrame#ActionTile {
    background: #1A1B1A;
    border: 1px solid #2C2D2C;
    border-radius: 0px;
}
QFrame#ActionTile:hover {
    background: #222322;
    border-color: #76B900;
}
QFrame#ActionTile[pressed="true"] {
    background: #202A17;
    border-color: #86D000;
}
QFrame#LegendStrip {
    background: #171817;
    border-top: 1px solid #2A2B2A;
    border-bottom: 1px solid #2A2B2A;
}
QLabel#HeroTitle {
    color: #FFFFFF;
    font-size: 25px;
    font-weight: 900;
}
QLabel#HeroMetric {
    color: #FFFFFF;
    font-size: 24px;
    font-weight: 900;
}
QLabel#NavHint {
    color: #9DA0A4;
    font-size: 10px;
}
QFrame#Toast {
    background: #242524;
    border: 1px solid #393A39;
    border-left: 4px solid #76B900;
}
QFrame#Toast[tone="warning"] { border-left-color: #F59E0B; }
QFrame#Toast[tone="error"] { border-left-color: #EF4444; }
QFrame#Toast[tone="info"] { border-left-color: #4C8DFF; }
QLabel#ToastText {
    color: #FFFFFF;
    font-weight: 700;
}
QFrame#DiagnosticCard {
    background: #1A1B1A;
    border: 1px solid #2D2E2D;
    border-left: 3px solid #76B900;
}
QFrame#DiagnosticCard:hover {
    background: #202120;
    border-color: #76B900;
}
QLabel#DiagnosticValue {
    color: #FFFFFF;
    font-size: 18px;
    font-weight: 900;
}
QFrame#InlineNotice {
    background: #191A19;
    border: 1px solid #303130;
    border-left: 3px solid #76B900;
}
QLabel#TextLinkLabel {
    color: #DCE6F7;
    padding: 7px 0px;
    font-weight: 800;
}
QFrame#ActionTile:hover QLabel#TextLinkLabel { color: #FFFFFF; }

"""


class UiFx:
    """Small, safe UI animation helpers.

    These animations intentionally use short opacity fades only. They avoid GPU-heavy
    blur/slide effects and keep the Qt event loop responsive even on low-end systems.
    """

    enabled = os.environ.get("FREECLEANER_DISABLE_UI_ANIMATIONS") != "1"
    duration_ms = 150

    @classmethod
    def fade_in(cls, widget: QWidget, duration: Optional[int] = None) -> None:
        if widget is None:
            return
        if not cls.enabled:
            widget.setVisible(True)
            return
        duration = int(duration or cls.duration_ms)
        token = int(getattr(widget, "_fc_fx_token", 0) or 0) + 1
        widget._fc_fx_token = token  # type: ignore[attr-defined]
        try:
            widget.setVisible(True)
            effect = widget.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(effect)
            effect.setOpacity(0.0)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(max(60, duration))
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            def finish() -> None:
                try:
                    if getattr(widget, "_fc_fx_token", None) != token:
                        return
                    effect.setOpacity(1.0)
                    # Remove the effect after show so text/icon rendering stays native.
                    if widget.graphicsEffect() is effect:
                        widget.setGraphicsEffect(None)
                except Exception:
                    pass
            anim.finished.connect(finish)
            widget._fc_fade_anim = anim  # type: ignore[attr-defined]
            anim.start()
        except Exception:
            widget.setVisible(True)

    @classmethod
    def fade_out(cls, widget: QWidget, duration: Optional[int] = None) -> None:
        if widget is None:
            return
        if not cls.enabled:
            widget.setVisible(False)
            return
        duration = int(duration or cls.duration_ms)
        token = int(getattr(widget, "_fc_fx_token", 0) or 0) + 1
        widget._fc_fx_token = token  # type: ignore[attr-defined]
        try:
            effect = widget.graphicsEffect()
            if not isinstance(effect, QGraphicsOpacityEffect):
                effect = QGraphicsOpacityEffect(widget)
                widget.setGraphicsEffect(effect)
            effect.setOpacity(1.0)
            anim = QPropertyAnimation(effect, b"opacity", widget)
            anim.setDuration(max(60, duration))
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            def finish() -> None:
                try:
                    if getattr(widget, "_fc_fx_token", None) != token:
                        return
                    widget.setVisible(False)
                    if widget.graphicsEffect() is effect:
                        widget.setGraphicsEffect(None)
                except Exception:
                    pass
            anim.finished.connect(finish)
            widget._fc_fade_anim = anim  # type: ignore[attr-defined]
            anim.start()
        except Exception:
            widget.setVisible(False)

    @classmethod
    def set_visible(cls, widget: QWidget, visible: bool, *, animated: bool = True, duration: Optional[int] = None) -> None:
        if visible:
            if not widget.isVisible() and animated:
                cls.fade_in(widget, duration)
            else:
                widget.setVisible(True)
        else:
            if widget.isVisible() and animated:
                cls.fade_out(widget, duration)
            else:
                widget.setVisible(False)


class ClickableTile(QFrame):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("pressed", "false")
        self.setAccessibleName("Home navigation tile")

    def _set_pressed(self, value: bool) -> None:
        prop = "true" if value else "false"
        if self.property("pressed") == prop:
            return
        self.setProperty("pressed", prop)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self._set_pressed(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            inside = self.rect().contains(event.position().toPoint()) if hasattr(event, "position") else self.rect().contains(event.pos())
            self._set_pressed(False)
            if inside:
                self.clicked.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_pressed(False)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ClickableSettingRow(QFrame):
    clicked = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("SettingsCard")
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setProperty("pressed", "false")
        self.setAccessibleName("Settings row")

    def _set_pressed(self, value: bool) -> None:
        prop = "true" if value else "false"
        if self.property("pressed") == prop:
            return
        self.setProperty("pressed", prop)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            self._set_pressed(True)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.button() == Qt.LeftButton:
            inside = self.rect().contains(event.position().toPoint()) if hasattr(event, "position") else self.rect().contains(event.pos())
            self._set_pressed(False)
            if inside:
                self.clicked.emit()
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802 - Qt override
        self._set_pressed(False)
        super().leaveEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.clicked.emit()
            event.accept()
            return
        super().keyPressEvent(event)


class ToggleSwitch(QCheckBox):
    """Animated Qt switch used for settings and registry tweaks.

    This widget does not rely on the platform checkbox indicator.  It toggles
    from the full switch rectangle on mouse release and from Space/Enter, then
    emits the normal Qt stateChanged/toggled signals.
    """

    def __init__(self, text: str = "", parent: Optional[QWidget] = None) -> None:
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCheckable(True)
        self.setMinimumSize(QSize(52, 28))
        self.setMaximumSize(QSize(52, 28))
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._position = 1.0 if self.isChecked() else 0.0
        self._pressed_inside = False

    def get_position(self) -> float:
        return float(self._position)

    def set_position(self, value: float) -> None:
        self._position = max(0.0, min(1.0, float(value)))
        self.update()

    position = Property(float, get_position, set_position)

    def _animate_to_state(self, *_: Any) -> None:
        self._position = 1.0 if self.isChecked() else 0.0
        self.update()

    def setChecked(self, value: bool) -> None:  # noqa: N802 - Qt API
        super().setChecked(bool(value))
        self._position = 1.0 if bool(value) else 0.0
        self.update()

    def nextCheckState(self) -> None:  # noqa: N802 - Qt override
        self.setChecked(not self.isChecked())

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.isEnabled() and event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self._pressed_inside = True
            event.accept()
            return
        self._pressed_inside = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self._pressed_inside:
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.isEnabled() and event.button() == Qt.LeftButton and self._pressed_inside:
            self._pressed_inside = False
            if self.rect().contains(event.pos()):
                self.nextCheckState()
            event.accept()
            return
        self._pressed_inside = False
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.isEnabled() and event.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.nextCheckState()
            event.accept()
            return
        super().keyPressEvent(event)

    def hitButton(self, pos) -> bool:  # noqa: N802 - Qt override
        return self.rect().contains(pos)

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        track = self.rect().adjusted(2, 5, -2, -5)
        radius = track.height() / 2
        if self.isChecked():
            bg = QColor("#76B900")
            knob = QColor("#0F120C" if self.isEnabled() else "#DDEBC9")
        elif not self.isEnabled():
            bg = QColor("#333433")
            knob = QColor("#797A79")
        else:
            bg = QColor("#3F403F")
            knob = QColor("#BFC0BF")
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(track, radius, radius)
        d = track.height() - 6
        x_off = (track.width() - d - 6) * self._position
        x = track.left() + 3 + x_off
        y = track.top() + 3
        painter.setBrush(knob)
        painter.drawEllipse(int(x), int(y), int(d), int(d))
        painter.end()


class Pill(QLabel):
    def __init__(self, text: str = "", tone: str = "Grey") -> None:
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumWidth(104)
        self.set_tone(tone)

    def set_tone(self, tone: str) -> None:
        tone = tone if tone in {"Green", "Blue", "Amber", "Red", "Grey"} else "Grey"
        self.setObjectName(f"Pill{tone}")
        self.style().unpolish(self)
        self.style().polish(self)

    def set_status(self, text: str, tone: str = "Grey") -> None:
        self.setText(text)
        self.set_tone(tone)


class SplashWindow(QWidget):
    def __init__(self, icon_path: Optional[str] = None) -> None:
        # Keep splash as a single native top-level without Tool/topmost owner
        # transitions.  Tool/topmost combinations can briefly flash helper
        # windows behind the splash on Windows while Qt modules are prepared.
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.setObjectName("SplashRoot")
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_NativeWindow, True)
        self.setFixedSize(460, 260)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 26, 30, 26)
        layout.setSpacing(14)
        brand = QHBoxLayout()
        if icon_path:
            icon = QLabel()
            icon.setPixmap(QIcon(icon_path).pixmap(42, 42))
            brand.addWidget(icon, 0, Qt.AlignLeft)
        text = QVBoxLayout()
        title = QLabel("FreeCleaner")
        title.setStyleSheet("font-size: 28px; font-weight: 900; color: #FFFFFF;")
        subtitle = QLabel(f"{APP_VERSION}")
        subtitle.setObjectName("VersionText")
        text.addWidget(title)
        text.addWidget(subtitle)
        brand.addLayout(text, 1)
        layout.addLayout(brand)
        line = QFrame()
        line.setObjectName("AccentGreen")
        line.setFixedHeight(3)
        layout.addWidget(line)
        self.message = QLabel("Підготовка FreeCleaner…")
        self.message.setObjectName("Muted")
        layout.addWidget(self.message)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(12)
        layout.addWidget(self.progress)
        layout.addStretch(1)
        footer = QLabel("Safe cleanup • Backups • Windows optimization")
        footer.setObjectName("Tiny")
        layout.addWidget(footer)
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

    def fade_out(self) -> None:
        self._fade_target = "hide"
        self.close()

    def _on_fade_finished(self) -> None:
        if getattr(self, "_fade_target", "show") == "hide":
            self.close()


class Worker(QObject):
    progress = Signal(int, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, fn: Callable[[Callable[[int, str], None]], Dict[str, Any]]) -> None:
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        started = datetime.now()
        try:
            log_qa_event("worker_run_start", worker=str(self), thread=threading.current_thread().name, started=str(started))
            def emit(percent: int, text: str = "") -> None:
                self.progress.emit(max(0, min(100, int(percent))), text)
            result = self.fn(emit) or {}
            log_qa_event("worker_run_finished", worker=str(self), thread=threading.current_thread().name, result=result)
            self.finished.emit(result)
        except Exception as exc:  # pragma: no cover - worker safety
            import traceback
            detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            log_error(detail)
            log_qa_event("worker_run_failed", worker=str(self), thread=threading.current_thread().name, error=detail)
            self.failed.emit(detail or str(exc))


class EstimateBridge(QObject):
    # Use object for byte totals: Qt int is 32-bit and overflows above ~2 GB,
    # which produced negative MB values in the UI.
    finished = Signal(int, object)


class StatusBridge(QObject):
    finished = Signal(int, dict)
    failed = Signal(int, str)


class WorkerBridge(QObject):
    """Main-thread bridge for signals emitted by workers.

    PySide can execute Python lambdas connected to worker-owned signals on the
    worker side depending on binding details. Emitting into this QObject first
    guarantees that all QWidget updates happen back on the GUI thread.
    """

    toggle_progress = Signal(str, int, str)
    toggle_finished = Signal(str, dict, object, object)
    toggle_failed = Signal(str, str, object, object)
    background_progress = Signal(int, str)
    background_finished = Signal(dict, object, object)
    background_failed = Signal(str, object, object)


class ProgramsBridge(QObject):
    scan_finished = Signal(object)
    scan_failed = Signal(str)
    cleanup_finished = Signal(object)
    cleanup_failed = Signal(str)


class DiagnosticCard(QFrame):
    def __init__(self, title: str, desc: str, button_text: str, callback: Callable[[], None], accent: str = "#76B900") -> None:
        super().__init__()
        self.setObjectName("DiagnosticCard")
        self.setMinimumHeight(128)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(8)
        header = QHBoxLayout()
        self.indicator = QLabel("●")
        self.indicator.setStyleSheet(f"color: {accent}; font-size: 16px; font-weight: 900;")
        header.addWidget(self.indicator)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        header.addWidget(title_label, 1)
        layout.addLayout(header)
        desc_label = QLabel(desc)
        desc_label.setObjectName("SectionSub")
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label, 1)
        bottom = QHBoxLayout()
        self.status = Pill("ready", "Green")
        bottom.addWidget(self.status)
        bottom.addStretch(1)
        btn = QPushButton(button_text)
        btn.clicked.connect(callback)
        bottom.addWidget(btn)
        layout.addLayout(bottom)

    def set_status(self, text: str, tone: str = "Green") -> None:
        self.status.set_status(text, tone)


class TaskRow(QFrame):
    changed = Signal()

    def __init__(self, task: CleanerTask, title: str, desc: str, *, switch: bool, status: str, enabled: bool) -> None:
        super().__init__()
        self.task = task
        self.switch_mode = bool(switch)
        self.setObjectName("TaskRow")
        self.setMinimumHeight(78 if switch else 84)
        self.setVisible(True)
        self.control = ToggleSwitch() if switch else QCheckBox()
        self.control.setEnabled(enabled)
        self.control.setChecked(bool(task.default))
        self.control.stateChanged.connect(lambda _=None: self._on_control_changed())

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(14)

        if not switch:
            root.addWidget(self.control, 0, Qt.AlignVCenter)

        text_box = QVBoxLayout()
        text_box.setSpacing(5)
        head = QHBoxLayout()
        self.title_label = QLabel(title)
        self.title_label.setObjectName("SectionTitle")
        self.title_label.setWordWrap(True)
        head.addWidget(self.title_label, 1)
        self.reboot_label = QLabel("restart")
        self.reboot_label.setObjectName("Tiny")
        self.reboot_label.setVisible(bool(task.reboot_required))
        head.addWidget(self.reboot_label, 0, Qt.AlignRight)
        text_box.addLayout(head)
        self.desc_label = QLabel(desc)
        self.desc_label.setObjectName("SectionSub")
        self.desc_label.setWordWrap(True)
        text_box.addWidget(self.desc_label)
        root.addLayout(text_box, 1)

        self.status_label = Pill(status, "Grey")
        root.addWidget(self.status_label, 0, Qt.AlignVCenter)
        if switch:
            root.addWidget(self.control, 0, Qt.AlignVCenter)
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        for widget in (self, self.title_label, self.desc_label, self.status_label, self.reboot_label):
            widget.installEventFilter(self)
        self.set_availability("ready" if enabled else ("admin" if task.requires_admin else "disabled"))
        self.set_selected_property(bool(task.default) and enabled)
        self.update_status(status)

    def _on_control_changed(self) -> None:
        self.set_selected_property(self.control.isChecked() and self.control.isEnabled())
        self.changed.emit()

    def set_selected_property(self, value: bool) -> None:
        new_value = "true" if value else "false"
        if self.property("selected") == new_value:
            return
        self.setProperty("selected", new_value)
        self.style().unpolish(self)
        self.style().polish(self)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802 - Qt override
        if event.type() == QEvent.MouseButtonRelease and self.control.isEnabled():
            try:
                if event.button() == Qt.LeftButton:
                    self.control.setChecked(not self.control.isChecked())
                    event.accept()
                    return True
            except Exception:
                pass
        return super().eventFilter(watched, event)

    def selected(self) -> bool:
        return bool(self.control.isChecked()) and self.control.isEnabled()

    def set_selected(self, value: bool) -> None:
        # Programmatic selection changes must never trigger cleaner/toggle actions.
        # Older builds emitted stateChanged while Reset/Clear Selection iterated rows,
        # which could start multiple optimizer workers and make the UI appear frozen.
        was_blocked = self.control.blockSignals(True)
        try:
            if self.control.isEnabled():
                self.control.setChecked(bool(value))
        finally:
            self.control.blockSignals(was_blocked)
        self.set_selected_property(bool(value) and self.control.isEnabled())

    def matches(self, query: str) -> bool:
        if not query:
            return True
        text = f"{self.title_label.text()} {self.desc_label.text()} {self.task.key}".casefold()
        return query.casefold() in text

    def set_availability(self, value: str) -> None:
        value = str(value or "ready")
        if self.property("availability") == value:
            return
        self.setProperty("availability", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_running(self, running: bool) -> None:
        self.set_availability("running" if running else "ready")
        if running:
            self.status_label.set_status("running", "Green")

    def update_status(self, status: str) -> None:
        text = status or ""
        low = text.casefold()
        if any(x in low for x in ("done", "застос", "applied", "готово", "вже змінено")):
            tone = "Green"
            self.set_availability("applied")
        elif any(x in low for x in ("admin", "адмін", "administrator")):
            tone = "Amber"
            self.set_availability("admin")
        elif any(x in low for x in ("unavailable", "недоступ", "disabled")):
            tone = "Grey"
            self.set_availability("disabled")
        elif any(x in low for x in ("change", "потріб", "needed")):
            tone = "Green"
            self.set_availability("ready")
        else:
            tone = "Grey"
            if self.task.state == "disabled":
                self.set_availability("disabled")
            elif self.task.requires_admin and not WindowsOps.is_admin():
                self.set_availability("admin")
            else:
                self.set_availability("ready")
        self.status_label.set_status(text, tone)



class StatusCard(QFrame):
    def __init__(self, title: str, value: str, accent_name: str = "Green") -> None:
        super().__init__()
        self.setObjectName("StatusCard")
        self.setMinimumHeight(74)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(3)
        accent = QFrame()
        accent.setObjectName(f"StatusAccent{accent_name}")
        accent.setFixedHeight(3)
        layout.addWidget(accent)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("Tiny")
        self.value_label = QLabel(value)
        self.value_label.setStyleSheet("font-size: 20px; font-weight: 700; color: #FFFFFF;")
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)

    def set_value(self, value: str) -> None:
        self.value_label.setText(value)


class Toast(QFrame):
    """Small animated in-app notification used instead of blocking dialogs for status."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setProperty("tone", "success")
        self.setVisible(False)
        self.setMinimumWidth(360)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        self.label = QLabel("")
        self.label.setObjectName("ToastText")
        self.label.setWordWrap(True)
        layout.addWidget(self.label, 1)
        self._fade_target = "show"
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 10)
        shadow.setColor(QColor(0, 0, 0, 130))
        # Keep the opacity effect because Qt allows only one graphics effect.
        # Shadow is intentionally not attached; simple flat NVIDIA-like UI is preferred.

    def show_message(self, text: str, tone: str = "success") -> None:
        self.label.setText(text)
        self.setProperty("tone", tone if tone in {"success", "warning", "error", "info"} else "success")
        self.style().unpolish(self)
        self.style().polish(self)
        self.adjustSize()
        parent = self.parentWidget()
        if parent:
            x = max(18, parent.width() - self.width() - 24)
            y = 72
            self.move(x, y)
        self.raise_()
        UiFx.fade_in(self, 130)
        QTimer.singleShot(2800, self.fade_out)

    def fade_out(self) -> None:
        if not self.isVisible():
            return
        UiFx.fade_out(self, 180)

    def _on_fade_finished(self) -> None:
        if getattr(self, "_fade_target", "show") == "hide":
            self.setVisible(False)


@dataclass
class UiTaskSection:
    key: str
    title: str
    rows: List[TaskRow]
    container: QWidget
    layout: QVBoxLayout


_MAIN_WINDOW_REF: Optional["FreeCleanerQt"] = None
UPDATE_PROGRESS_PREFIX = "FC_UPDATE_PROGRESS|"


def _format_bytes(value: object) -> str:
    try:
        size = float(value or 0)
    except Exception:
        size = 0.0
    units = ("B", "KB", "MB", "GB")
    idx = 0
    while size >= 1024 and idx < len(units) - 1:
        size /= 1024.0
        idx += 1
    if idx == 0:
        return f"{int(size)} {units[idx]}"
    return f"{size:.1f} {units[idx]}"



def _program_norm(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^a-z0-9а-яіїєґё]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split())


_PROGRAM_TOKEN_STOP = {
    "app", "apps", "application", "setup", "installer", "update", "updater", "helper", "runtime",
    "microsoft", "windows", "system", "package", "packages", "common", "files", "program", "programs",
    "x64", "x86", "win64", "win32", "version", "freecleaner",
}
_APPDATA_SKIP_NAMES = {
    "microsoft", "packages", "temp", "temporary internet files", "programs", "windows", "crashdumps",
    "connecteddevicesplatform", "comms", "d3dscache", "nvidia", "amd", "intel", "freecleaner",
}


def _program_tokens(*values: str) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = _program_norm(value)
        if not normalized:
            continue
        compact = normalized.replace(" ", "")
        if len(compact) >= 4 and compact not in _PROGRAM_TOKEN_STOP:
            tokens.add(compact)
        for token in normalized.split():
            if len(token) >= 4 and token not in _PROGRAM_TOKEN_STOP:
                tokens.add(token)
    return tokens


def _path_drive(path: str) -> str:
    try:
        drive, _tail = os.path.splitdrive(os.path.abspath(path or ""))
        return drive.upper() or "—"
    except Exception:
        return "—"


def _expand_win_path(path: str) -> str:
    return os.path.expandvars(str(path or "").strip().strip('"'))


def _extract_exe_from_command(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    raw = raw.replace("/I{", "{").replace("/X{", "{")
    if raw.startswith('"'):
        end = raw.find('"', 1)
        candidate = raw[1:end] if end > 1 else raw.strip('"')
    else:
        match = re.search(r"[A-Za-z]:\\[^\n\r\t]*?\.exe", raw, flags=re.IGNORECASE)
        candidate = match.group(0) if match else raw.split()[0]
    candidate = _expand_win_path(candidate.split(",")[0])
    if candidate.lower().endswith(".exe") and os.path.isfile(candidate):
        return candidate
    return ""


def _find_exe_in_install_dir(path: str, display_name: str = "") -> str:
    folder = _expand_win_path(path)
    if not folder or not os.path.isdir(folder):
        return ""
    preferred_tokens = _program_tokens(display_name, os.path.basename(folder))
    try:
        candidates: list[str] = []
        with os.scandir(folder) as it:
            for entry in it:
                try:
                    if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(".exe"):
                        candidates.append(entry.path)
                except OSError:
                    continue
        if not candidates:
            return ""
        def score(p: str) -> tuple[int, int, str]:
            name = os.path.splitext(os.path.basename(p))[0]
            tokens = _program_tokens(name)
            hit = len(preferred_tokens & tokens)
            low = name.lower()
            bad = 1 if any(x in low for x in ("unins", "setup", "update", "helper", "crash", "report")) else 0
            return (-hit, bad, name.lower())
        candidates.sort(key=score)
        return candidates[0]
    except Exception:
        return ""


def _appdata_roots() -> list[str]:
    roots: list[str] = []
    for env_name in ("APPDATA", "LOCALAPPDATA"):
        value = os.environ.get(env_name)
        if value and os.path.isdir(value):
            roots.append(value)
    user_profile = os.environ.get("USERPROFILE") or os.path.expanduser("~")
    locallow = os.path.join(user_profile, "AppData", "LocalLow") if user_profile else ""
    if locallow and os.path.isdir(locallow):
        roots.append(locallow)
    unique: list[str] = []
    seen: set[str] = set()
    for path in roots:
        norm = os.path.normcase(os.path.abspath(path))
        if norm not in seen:
            seen.add(norm)
            unique.append(path)
    return unique


def _safe_appdata_child(path: str) -> bool:
    if not path:
        return False
    try:
        abs_path = os.path.abspath(path)
        if SafeFS._is_reparse_point(abs_path):
            return False
        for root in _appdata_roots():
            root_abs = os.path.abspath(root)
            try:
                if os.path.commonpath([root_abs, abs_path]) == root_abs and os.path.normcase(root_abs) != os.path.normcase(abs_path):
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def _read_reg_value(key: Any, name: str, default: Any = "") -> Any:
    try:
        return winreg.QueryValueEx(key, name)[0]
    except Exception:
        return default


def _iter_installed_programs_from_registry() -> list[dict[str, Any]]:
    if not IS_WINDOWS or winreg is None:
        return []
    roots = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    by_key: dict[str, dict[str, Any]] = {}
    for hive, path in roots:
        try:
            base = winreg.OpenKey(hive, path)
        except Exception:
            continue
        try:
            count = winreg.QueryInfoKey(base)[0]
            for idx in range(count):
                try:
                    sub_name = winreg.EnumKey(base, idx)
                    sub = winreg.OpenKey(base, sub_name)
                except Exception:
                    continue
                try:
                    name = str(_read_reg_value(sub, "DisplayName", "") or "").strip()
                    if not name:
                        continue
                    if int(_read_reg_value(sub, "SystemComponent", 0) or 0) == 1:
                        continue
                    release_type = str(_read_reg_value(sub, "ReleaseType", "") or "").lower()
                    if release_type in {"security update", "update rollup", "hotfix"}:
                        continue
                    publisher = str(_read_reg_value(sub, "Publisher", "") or "").strip()
                    install_location = _expand_win_path(str(_read_reg_value(sub, "InstallLocation", "") or ""))
                    display_icon = str(_read_reg_value(sub, "DisplayIcon", "") or "")
                    uninstall = str(_read_reg_value(sub, "UninstallString", "") or "")
                    estimated = _read_reg_value(sub, "EstimatedSize", 0) or 0
                    try:
                        estimated_bytes = max(0, int(estimated)) * 1024
                    except Exception:
                        estimated_bytes = 0
                    exe_path = _extract_exe_from_command(display_icon) or _extract_exe_from_command(uninstall)
                    if not exe_path and install_location:
                        exe_path = _find_exe_in_install_dir(install_location, name)
                    if install_location and not os.path.isdir(install_location):
                        install_location = os.path.dirname(exe_path) if exe_path else install_location
                    key = _program_norm(name + " " + (publisher or ""))
                    if not key:
                        continue
                    existing = by_key.get(key)
                    record = {
                        "name": name,
                        "publisher": publisher,
                        "install_path": install_location if install_location and os.path.exists(install_location) else "",
                        "exe_path": exe_path if exe_path and os.path.isfile(exe_path) else "",
                        "estimated_size": estimated_bytes,
                        "tokens": _program_tokens(name, publisher, os.path.basename(install_location or "")),
                    }
                    if existing:
                        if not existing.get("install_path") and record.get("install_path"):
                            existing.update(record)
                        elif int(record.get("estimated_size") or 0) > int(existing.get("estimated_size") or 0):
                            existing.update(record)
                    else:
                        by_key[key] = record
                finally:
                    try:
                        sub.Close()
                    except Exception:
                        pass
        finally:
            try:
                base.Close()
            except Exception:
                pass
    return list(by_key.values())


def _scan_appdata_children(cancel_event: Optional[threading.Event] = None) -> list[dict[str, Any]]:
    children: list[dict[str, Any]] = []
    for root in _appdata_roots():
        if cancel_event is not None and cancel_event.is_set():
            break
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if cancel_event is not None and cancel_event.is_set():
                        break
                    try:
                        if not entry.is_dir(follow_symlinks=False):
                            continue
                        name = entry.name.strip()
                        if not name or name.lower() in _APPDATA_SKIP_NAMES:
                            continue
                        if SafeFS._entry_is_reparse_point(entry):
                            continue
                        tokens = _program_tokens(name)
                        if not tokens:
                            continue
                        children.append({
                            "name": name,
                            "path": entry.path,
                            "root": root,
                            "tokens": tokens,
                        })
                    except OSError:
                        continue
        except OSError:
            continue
    return children


def _program_match_score(program: dict[str, Any], child: dict[str, Any]) -> int:
    ptokens = set(program.get("tokens") or set())
    ctokens = set(child.get("tokens") or set())
    if not ptokens or not ctokens:
        return 0
    score = len(ptokens & ctokens) * 10
    pname = _program_norm(str(program.get("name") or "")).replace(" ", "")
    cname = _program_norm(str(child.get("name") or "")).replace(" ", "")
    if pname and cname and (pname in cname or cname in pname):
        score += 18
    return score


def scan_program_inventory(cancel_event: Optional[threading.Event] = None) -> list[dict[str, Any]]:
    installed = _iter_installed_programs_from_registry()
    app_children = _scan_appdata_children(cancel_event)
    matched_child_indexes: set[int] = set()
    program_leftovers: dict[int, list[dict[str, Any]]] = {idx: [] for idx in range(len(installed))}

    for cidx, child in enumerate(app_children):
        best_idx = -1
        best_score = 0
        for pidx, program in enumerate(installed):
            score = _program_match_score(program, child)
            if score > best_score:
                best_idx = pidx
                best_score = score
        if best_idx >= 0 and best_score >= 10:
            program_leftovers.setdefault(best_idx, []).append(child)
            matched_child_indexes.add(cidx)

    entries: list[dict[str, Any]] = []
    for pidx, program in enumerate(installed):
        if cancel_event is not None and cancel_event.is_set():
            break
        leftovers = program_leftovers.get(pidx, [])
        leftover_paths = [str(x.get("path") or "") for x in leftovers if x.get("path")]
        install_path = str(program.get("install_path") or "")
        install_size = int(program.get("estimated_size") or 0)
        if not install_size and install_path and os.path.isdir(install_path):
            install_size = SafeFS.fast_size_limited(install_path, cancel_event, max_seconds=0.35, max_entries=1800)
        leftover_size = SafeFS.fast_size_many_limited(leftover_paths, cancel_event, max_seconds=0.55, max_entries=3200) if leftover_paths else 0
        leftover_drives = sorted({_path_drive(p) for p in leftover_paths if p})
        entries.append({
            "status": "installed",
            "name": str(program.get("name") or ""),
            "publisher": str(program.get("publisher") or ""),
            "install_path": install_path,
            "exe_path": str(program.get("exe_path") or ""),
            "install_drive": _path_drive(install_path) if install_path else "—",
            "install_size": install_size,
            "leftover_paths": leftover_paths,
            "leftover_drive": ", ".join(leftover_drives) if leftover_drives else "—",
            "leftover_size": leftover_size,
        })

    for cidx, child in enumerate(app_children):
        if cidx in matched_child_indexes:
            continue
        if cancel_event is not None and cancel_event.is_set():
            break
        path = str(child.get("path") or "")
        size = SafeFS.fast_size_limited(path, cancel_event, max_seconds=0.45, max_entries=2600) if path else 0
        entries.append({
            "status": "removed",
            "name": str(child.get("name") or ""),
            "publisher": "",
            "install_path": "",
            "exe_path": "",
            "install_drive": "removed",
            "install_size": 0,
            "leftover_paths": [path] if path else [],
            "leftover_drive": _path_drive(path),
            "leftover_size": size,
        })

    entries.sort(key=lambda item: (0 if item.get("status") == "removed" else 1, str(item.get("name") or "").lower()))
    return entries


def delete_program_leftover_paths(paths: list[str], cancel_event: Optional[threading.Event] = None) -> dict[str, int]:
    result = {"removed_bytes": 0, "removed_items": 0, "errors": 0}
    unique: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if not path:
            continue
        try:
            abs_path = os.path.abspath(path)
        except Exception:
            continue
        norm = os.path.normcase(abs_path)
        if norm in seen:
            continue
        seen.add(norm)
        unique.append(abs_path)
    for path in unique:
        if cancel_event is not None and cancel_event.is_set():
            break
        if not os.path.exists(path):
            continue
        if not _safe_appdata_child(path):
            log_security(f"blocked unsafe program leftover delete: {path}", level="WARNING")
            result["errors"] += 1
            continue
        try:
            size = SafeFS.fast_size(path, cancel_event)
            if os.path.isdir(path):
                def onerror(func, p, _exc):
                    try:
                        SafeFS._clear_attributes(p, is_dir=os.path.isdir(p))
                        func(p)
                    except Exception:
                        pass
                shutil.rmtree(path, onerror=onerror)
            else:
                SafeFS._clear_attributes(path, is_dir=False)
                os.remove(path)
            result["removed_bytes"] += max(0, int(size or 0))
            result["removed_items"] += 1
            log_action(f"program leftover removed: {path}")
        except Exception as exc:
            result["errors"] += 1
            log_error(f"program leftover delete failed: {path}: {exc}")
    return result


def _format_eta(seconds: object) -> str:
    try:
        sec = max(0, int(float(seconds or 0)))
    except Exception:
        sec = 0
    if sec <= 0:
        return "—"
    mins, rem = divmod(sec, 60)
    if mins <= 0:
        return f"{rem}s"
    return f"{mins}m {rem:02d}s"


class UpdateDialog(QDialog):
    """Modern in-app update window with live download/install progress."""

    download_requested = Signal()
    release_requested = Signal(str)
    cancel_requested = Signal()

    def __init__(self, parent: QWidget, result: Dict[str, Any]) -> None:
        super().__init__(parent)
        self.result = dict(result or {})
        self._tr = getattr(parent, "tr", lambda key: key)
        self._trf = getattr(parent, "trf", lambda key, **kwargs: str(key).format(**kwargs))
        self._downloading = False
        self.setObjectName("UpdateDialog")
        self.setWindowTitle(self._tr("update_window_title"))
        self.setModal(False)
        self.setMinimumSize(680, 520)
        self.resize(760, 580)

        latest = str(self.result.get("latest") or self.result.get("latest_name") or self._tr("update_latest_fallback"))
        current = str(self.result.get("current_display") or APP_VERSION)
        asset_name = str(self.result.get("asset_name") or "")
        published = str(self.result.get("published_at") or "")
        body = str(self.result.get("body") or "").strip()
        changelog_count = int(self.result.get("changelog_count") or 0)
        release_url = str(self.result.get("release_url") or APP_UPDATE_LATEST_RELEASE_URL)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 18)
        root.setSpacing(14)

        hero = QFrame()
        hero.setObjectName("UpdateHero")
        hero_l = QVBoxLayout(hero)
        hero_l.setContentsMargins(16, 14, 16, 14)
        hero_l.setSpacing(8)
        title = QLabel(self._tr("update_hero_title"))
        title.setObjectName("UpdateHeroTitle")
        hero_l.addWidget(title)
        subtitle = QLabel(self._tr("update_hero_subtitle"))
        subtitle.setObjectName("SectionSub")
        subtitle.setWordWrap(True)
        hero_l.addWidget(subtitle)
        root.addWidget(hero)

        versions = QHBoxLayout()
        versions.setSpacing(12)
        versions.addWidget(self._version_card(self._tr("update_current_version"), current), 1)
        versions.addWidget(self._version_card(self._tr("update_new_version"), latest), 1)
        root.addLayout(versions)

        meta_card = QFrame()
        meta_card.setObjectName("UpdateStepCard")
        meta_l = QVBoxLayout(meta_card)
        meta_l.setContentsMargins(14, 12, 14, 12)
        meta_l.setSpacing(6)
        self.asset_label = QLabel(self._trf("update_file_label", file=asset_name or self._tr("update_installer_missing")))
        self.asset_label.setObjectName("UpdateMetaText")
        self.asset_label.setWordWrap(True)
        meta_l.addWidget(self.asset_label)
        self.folder_label = QLabel(self._trf("update_folder_label", path=get_updates_dir(create=True)))
        self.folder_label.setObjectName("UpdateMetaText")
        self.folder_label.setWordWrap(True)
        meta_l.addWidget(self.folder_label)
        if published:
            published_label = QLabel(self._trf("update_published_at", date=published))
            published_label.setObjectName("UpdateMetaText")
            meta_l.addWidget(published_label)
        root.addWidget(meta_card)

        progress_card = QFrame()
        progress_card.setObjectName("UpdateStepCard")
        progress_l = QVBoxLayout(progress_card)
        progress_l.setContentsMargins(14, 12, 14, 12)
        progress_l.setSpacing(8)
        self.status_label = QLabel(self._tr("update_ready_to_download"))
        self.status_label.setObjectName("UpdateStatusText")
        self.status_label.setWordWrap(True)
        progress_l.addWidget(self.status_label)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        progress_l.addWidget(self.progress)
        self.progress_meta = QLabel(self._tr("update_waiting_download"))
        self.progress_meta.setObjectName("UpdateMetaText")
        progress_l.addWidget(self.progress_meta)
        root.addWidget(progress_card)

        notes_title = QLabel(self._trf("update_changelog_recent", count=changelog_count or 5))
        notes_title.setObjectName("SectionTitle")
        root.addWidget(notes_title)
        self.notes = QTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMinimumHeight(130)
        self.notes.setPlainText(body or self._tr("update_no_changelog"))
        root.addWidget(self.notes, 1)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        self.release_btn = QPushButton(self._tr("update_open_release"))
        self.release_btn.setObjectName("GhostButton")
        self.release_btn.setIcon(self.style().standardIcon(QStyle.SP_DirLinkIcon))
        self.release_btn.clicked.connect(lambda: self.release_requested.emit(release_url))
        buttons.addWidget(self.release_btn)
        buttons.addStretch(1)
        self.cancel_btn = QPushButton(self._tr("update_later"))
        self.cancel_btn.setObjectName("GhostButton")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        buttons.addWidget(self.cancel_btn)
        self.download_btn = QPushButton(self._tr("update_download"))
        self.download_btn.setObjectName("PrimaryButton")
        self.download_btn.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        self.download_btn.clicked.connect(self._on_download_clicked)
        buttons.addWidget(self.download_btn)
        root.addLayout(buttons)

    def _version_card(self, title: str, value: str) -> QWidget:
        card = QFrame()
        card.setObjectName("UpdateVersionCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        small = QLabel(title)
        small.setObjectName("Tiny")
        layout.addWidget(small)
        val = QLabel(value or "—")
        val.setObjectName("UpdateVersionValue")
        val.setWordWrap(True)
        layout.addWidget(val)
        return card

    def _on_download_clicked(self) -> None:
        if self._downloading:
            return
        self.download_requested.emit()

    def _on_cancel_clicked(self) -> None:
        if self._downloading:
            self.cancel_btn.setEnabled(False)
            self.status_label.setText(self._tr("update_cancel_requested"))
            self.cancel_requested.emit()
            return
        self.close()

    def set_downloading(self, version: str, filename: str, dest_path: str) -> None:
        self._downloading = True
        self.download_btn.setEnabled(False)
        self.download_btn.setText(self._tr("update_downloading_button"))
        self.cancel_btn.setText(self._tr("cancel"))
        self.cancel_btn.setEnabled(True)
        if filename:
            self.asset_label.setText(self._trf("update_file_label", file=filename))
        if dest_path:
            self.folder_label.setText(self._trf("update_saving_to", path=dest_path))
        self.status_label.setText(self._trf("update_downloading_version", version=version))
        self.progress.setValue(1)
        self.progress_meta.setText(self._tr("update_download_starting"))
        self.raise_()
        self.show()

    def update_progress_payload(self, payload: Dict[str, Any]) -> None:
        stage = str(payload.get("stage") or "downloading")
        percent = int(payload.get("percent") or 0)
        self.progress.setValue(max(0, min(100, percent)))
        if stage == "downloading":
            downloaded = payload.get("downloaded") or 0
            total = payload.get("total") or 0
            speed = payload.get("speed") or 0
            eta = payload.get("eta") or 0
            if total:
                self.status_label.setText(self._trf("update_download_percent", percent=percent))
                self.progress_meta.setText(self._trf("update_download_meta", downloaded=_format_bytes(downloaded), total=_format_bytes(total), speed=_format_bytes(speed), eta=_format_eta(eta)))
            else:
                self.status_label.setText(self._tr("update_downloading_file"))
                self.progress_meta.setText(self._trf("update_download_meta_unknown", downloaded=_format_bytes(downloaded), speed=_format_bytes(speed)))
        elif stage == "verifying":
            self.status_label.setText(self._tr("update_verifying_file"))
            self.progress_meta.setText(str(payload.get("path") or ""))
        elif stage == "installing":
            self.status_label.setText(self._tr("update_starting_installer"))
            self.progress_meta.setText(str(payload.get("path") or ""))
        elif stage == "cancelled":
            self.set_failed(self._tr("update_download_cancelled"))
        elif stage == "failed":
            self.set_failed(str(payload.get("message") or self._tr("update_download_failed")))

    def set_failed(self, message: str) -> None:
        self._downloading = False
        self.progress.setValue(0)
        self.status_label.setText(message or self._tr("update_download_failed"))
        self.progress_meta.setText(self._tr("update_retry_or_release"))
        self.download_btn.setEnabled(True)
        self.download_btn.setText(self._tr("retry"))
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText(self._tr("close"))

    def set_done(self, path: str) -> None:
        self._downloading = False
        self.progress.setValue(100)
        self.status_label.setText(self._tr("update_install_launched_status"))
        self.progress_meta.setText(path or "")
        self.download_btn.setEnabled(False)
        self.download_btn.setText(self._tr("update_install_started_button"))
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText(self._tr("close"))


class FreeCleanerQt(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        log_startup("FreeCleanerQt.__init__ start")
        log_app("FreeCleanerQt window initialization started")
        log_qa_event("qt_window_init_start", thread=threading.current_thread().name, pid=os.getpid())
        self.config = self.load_config()
        self.lang_preference = self.normalize_language_preference(str(self.config.get("language", "auto")))
        self.lang_code = self.detect_initial_language()
        self.lang = LANG_PACKS.get(self.lang_code, LANG_PACKS.get("en", {}))
        self.is_admin = WindowsOps.is_admin()
        self.tasks: Dict[str, CleanerTask] = {}
        self.rows: Dict[str, TaskRow] = {}
        self.sections: Dict[str, UiTaskSection] = {}
        self.cancel_event = threading.Event()
        self.thread: Optional[QThread] = None
        self.worker: Optional[Worker] = None
        self.background_jobs: List[Tuple[QThread, Worker]] = []
        self.toggle_jobs: Dict[str, Tuple[QThread, Worker]] = {}
        self._toggle_group_cooldown_until: Dict[str, float] = {}
        self._toggle_group_cooldown_ms = 1200
        self.analysis_total = 0
        self.freed_bytes = 0
        self.revert_registry_specs: Dict[str, List[RegistryValueSpec]] = {}
        self.revert_commands: Dict[str, Callable[[], Any]] = {}
        self._programmatic_change = False
        self._estimate_token = 0
        self._estimate_cancel_event = threading.Event()
        self._estimate_active = False
        self.estimate_bridge = EstimateBridge(self)
        self.estimate_bridge.finished.connect(self.on_selection_estimate_ready, Qt.QueuedConnection)
        self.estimate_timer = QTimer(self)
        self.estimate_timer.setSingleShot(True)
        self.estimate_timer.timeout.connect(self.start_selection_estimate)
        self.status_bridge = StatusBridge(self)
        self.status_bridge.finished.connect(self.on_status_sync_ready, Qt.QueuedConnection)
        self.status_bridge.failed.connect(self.on_status_sync_failed, Qt.QueuedConnection)
        self._status_sync_token = 0
        self._status_sync_worker_active = False
        self._status_applied_cache: Dict[str, Optional[bool]] = {}
        self._active_power_scheme_cache: Optional[str] = None
        self._active_power_scheme_guid_cache: Optional[str] = None
        self._dynamic_tick_cache: Optional[bool] = None
        self._cleaning_keys: List[str] = []
        self._status_sync_pending = False
        self._last_status_sync_started_at = 0.0
        self._powercfg_value_cache: Dict[Tuple[str, str], Optional[int]] = {}
        self._last_ui_heartbeat_monotonic = time.monotonic()
        self._last_ui_heartbeat_logged = 0.0
        self._ui_watchdog_stop = threading.Event()
        self._auto_status_sync_enabled = False
        self._auto_update_check_enabled = False
        self._update_check_running = False
        self._update_download_running = False
        self._update_dialog: Optional[UpdateDialog] = None
        self._update_progress_dialog: Optional[UpdateDialog] = None
        self._update_download_cancel_event: Optional[threading.Event] = None
        self._max_background_jobs = 2
        self.program_entries: List[Dict[str, Any]] = []
        self._program_scan_running = False
        self._program_scan_started = False
        self._program_cleanup_running = False
        self.apply_runtime_config_flags()
        self.programs_bridge = ProgramsBridge(self)
        self.programs_bridge.scan_finished.connect(self.on_program_scan_ready, Qt.QueuedConnection)
        self.programs_bridge.scan_failed.connect(self.on_program_scan_failed, Qt.QueuedConnection)
        self.programs_bridge.cleanup_finished.connect(self.on_program_cleanup_finished, Qt.QueuedConnection)
        self.programs_bridge.cleanup_failed.connect(self.on_program_cleanup_failed, Qt.QueuedConnection)
        self.worker_bridge = WorkerBridge(self)
        self.worker_bridge.toggle_progress.connect(self.on_toggle_progress, Qt.QueuedConnection)
        self.worker_bridge.toggle_finished.connect(self.on_toggle_finished, Qt.QueuedConnection)
        self.worker_bridge.toggle_failed.connect(self.on_toggle_failed, Qt.QueuedConnection)
        self.worker_bridge.background_progress.connect(self.on_background_progress, Qt.QueuedConnection)
        self.worker_bridge.background_finished.connect(self.on_background_worker_finished, Qt.QueuedConnection)
        self.worker_bridge.background_failed.connect(self.on_background_worker_failed, Qt.QueuedConnection)
        self.ui_watchdog = QTimer(self)
        self.ui_watchdog.setInterval(1000)
        self.ui_watchdog.timeout.connect(self.on_ui_heartbeat)
        self.ui_watchdog.start()
        threading.Thread(target=self._ui_freeze_watchdog_loop, name="FreeCleanerUiFreezeWatchdog", daemon=True).start()

        self.setWindowTitle(f"FreeCleaner {APP_VERSION_RAW}")
        icon = find_icon_path("app.ico") or find_icon_path("app.png")
        if icon:
            self.setWindowIcon(QIcon(icon))
        self.resize(1360, 820)
        self.setMinimumSize(1060, 680)

        root = QWidget()
        root.setObjectName("Root")
        self.setCentralWidget(root)
        main = QVBoxLayout(root)
        main.setContentsMargins(0, 0, 0, 0)
        main.setSpacing(0)

        self.build_top_bar(main)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        main.addLayout(body, 1)
        self.build_nav(body)
        self.stack = QStackedWidget()
        body.addWidget(self.stack, 1)
        self.toast = Toast(root)

        self.build_pages()
        self.register_tasks()
        self.refresh_task_counts()
        self.refresh_backup_state()
        self.nav_buttons[0].setChecked(True)
        self.stack.setCurrentIndex(0)
        self.log(self.trf("app_started", title="FreeCleaner") if self.tr("app_started") != "app_started" else "FreeCleaner started.")
        self.refresh_system_drive_status()
        # Heavy registry/powercfg status checks are deferred until after the
        # window is visible.  This keeps splash startup clean and avoids bursts
        # of hidden helper processes during UI construction.
        if self._auto_status_sync_enabled:
            QTimer.singleShot(1500, lambda: self.defer_status_sync(0))
        else:
            log_qa_event("startup_auto_status_sync_disabled")
        log_startup("FreeCleanerQt.__init__ complete")
        log_qa_event("qt_window_init_complete", tasks=len(self.tasks), rows=len(self.rows), thread=threading.current_thread().name)
        if self._auto_update_check_enabled and self.setting_bool("auto_check_updates", False):
            QTimer.singleShot(8000, self.check_updates)
        else:
            log_qa_event("startup_auto_update_check_disabled")

    # ------------------------- config / i18n -------------------------
    def load_config(self) -> Dict[str, Any]:
        for path in (CONFIG_PATH, LEGACY_CONFIG_PATH):
            try:
                if path and os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        return data
            except Exception as exc:
                log_app(f"config load failed for {path}: {exc}", level="ERROR")
                try:
                    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    os.replace(path, f"{path}.corrupt_{stamp}")
                    log_app(f"corrupt config moved to {path}.corrupt_{stamp}", level="WARNING")
                except Exception as move_exc:
                    log_app(f"could not move corrupt config {path}: {move_exc}", level="ERROR")
        return {}

    def save_config(self) -> None:
        try:
            data = dict(self.config or {})
            data["language"] = self.lang_preference
            folder = os.path.dirname(CONFIG_PATH)
            if folder:
                os.makedirs(folder, exist_ok=True)
            tmp = f"{CONFIG_PATH}.tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
                fh.write("\n")
            os.replace(tmp, CONFIG_PATH)
        except Exception as exc:
            log_app(f"config save failed: {exc}", level="ERROR")

    def setting_bool_from_config(self, key: str, default: bool = False) -> bool:
        value = (self.config or {}).get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on", "enabled"}

    def setting_int_from_config(self, key: str, default: int = 0, *, minimum: int = 0, maximum: int = 999999) -> int:
        try:
            value = int((self.config or {}).get(key, default))
        except Exception:
            value = int(default)
        return max(int(minimum), min(int(maximum), value))

    def apply_runtime_config_flags(self) -> None:
        """Apply config-backed runtime switches that used to be env-only."""
        env_animations_default = os.environ.get("FREECLEANER_DISABLE_UI_ANIMATIONS") != "1"
        UiFx.enabled = self.setting_bool_from_config("ui_animations_enabled", env_animations_default)
        UiFx.duration_ms = self.setting_int_from_config("ui_animation_duration_ms", 150, minimum=60, maximum=420)
        self._auto_status_sync_enabled = self.setting_bool_from_config(
            "startup_status_sync_enabled", os.environ.get("FREECLEANER_AUTO_STATUS_SYNC") == "1"
        )
        self._auto_update_check_enabled = self.setting_bool_from_config(
            "startup_update_check_enabled", os.environ.get("FREECLEANER_AUTO_UPDATE_CHECK") == "1"
        )
        self._max_background_jobs = self.setting_int_from_config("background_worker_limit", 2, minimum=1, maximum=4)

    @staticmethod
    def normalize_language_preference(value: str) -> str:
        code = (value or "auto").strip().lower()
        return code if code == "auto" or code in LANG_PACKS else "auto"

    def detect_initial_language(self) -> str:
        if self.lang_preference != "auto":
            return self.lang_preference
        try:
            loc = (locale.getdefaultlocale()[0] or "").lower()
        except Exception:
            loc = ""
        if loc.startswith("uk"):
            return "uk" if "uk" in LANG_PACKS else "en"
        if loc.startswith("pl") and "pl" in LANG_PACKS:
            return "pl"
        if loc.startswith("de") and "de" in LANG_PACKS:
            return "de"
        if loc.startswith("es") and "es" in LANG_PACKS:
            return "es"
        return "en"

    def tr(self, key: str) -> str:
        value = str(self.lang.get(key) or LANG_PACKS.get("en", {}).get(key) or key)
        return value.replace("\\n", "\n")

    def trf(self, key: str, **kwargs: Any) -> str:
        try:
            return self.tr(key).format(**kwargs)
        except Exception:
            return self.tr(key)

    def task_text(self, task: CleanerTask) -> Tuple[str, str]:
        fmt = task.fmt or {}
        try:
            title = self.tr(task.title_key).format(**fmt)
        except Exception:
            title = self.tr(task.title_key)
        try:
            desc = self.tr(task.desc_key).format(**fmt)
        except Exception:
            desc = self.tr(task.desc_key)
        return title, desc

    # ------------------------- layout -------------------------
    def build_top_bar(self, parent: QVBoxLayout) -> None:
        top = QFrame()
        top.setObjectName("TopBar")
        top.setFixedHeight(56)
        layout = QHBoxLayout(top)
        layout.setContentsMargins(16, 0, 16, 0)
        layout.setSpacing(10)

        title = QLabel("FreeCleaner")
        title.setObjectName("BrandTitle")
        layout.addWidget(title)
        subtitle = QLabel(self.trf("topbar_version", version=APP_VERSION))
        subtitle.setObjectName("VersionText")
        layout.addWidget(subtitle)
        layout.addStretch(1)

        mode_text = self.tr("admin_access") if self.is_admin else self.tr("limited_mode")
        self.top_admin_label = Pill(mode_text, "Green" if self.is_admin else "Amber")
        layout.addWidget(self.top_admin_label)

        self.elevate_btn = None
        self.about_top_btn = None
        parent.addWidget(top)

    def build_nav(self, parent: QHBoxLayout) -> None:
        rail = QFrame()
        rail.setObjectName("NavRail")
        rail.setFixedWidth(78)
        nav = QVBoxLayout(rail)
        nav.setContentsMargins(0, 8, 0, 8)
        nav.setSpacing(2)
        self.nav_buttons: List[QToolButton] = []
        self._nav_icon_specs: List[Tuple[QToolButton, str, str, str]] = []
        self._nav_icon_cache: Dict[str, QIcon] = {}
        items = [
            ("home", self.tr("nav_home")),
            ("cleaner", self.tr("nav_cleaner")),
            ("programs", self.tr("nav_programs")),
            ("optimizer", self.tr("nav_optimizer")),
            ("registry", self.tr("nav_registry")),
            ("diagnostics", self.tr("nav_diagnostics")),
            ("settings", self.tr("nav_settings")),
        ]
        group = QButtonGroup(self)
        group.setExclusive(True)
        for idx, (icon_name, text) in enumerate(items):
            label = text if len(text) <= 10 else text[:9] + "…"
            btn = QToolButton()
            btn.setObjectName("NavButton")
            btn.setFixedSize(78, 66)
            btn.setAutoRaise(True)
            icon_path = find_icon_path(os.path.join("nav", f"{icon_name}.svg")) or find_icon_path(os.path.join("nav", f"{icon_name}.png"))
            if icon_path:
                btn.setIcon(QIcon(icon_path))
                btn.setIconSize(QSize(22, 22))
                btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                btn.setText(label)
            else:
                fallback = {"home": "⌂", "cleaner": "◫", "programs": "▦", "optimizer": "☑", "registry": "▣", "diagnostics": "◈", "settings": "⚙"}.get(icon_name, "•")
                btn.setText(f"{fallback}\n{label}")
                btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
            btn.setToolTip(text)
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, i=idx: self.set_page(i))
            group.addButton(btn, idx)
            nav.addWidget(btn, 0, Qt.AlignHCenter)
            self.nav_buttons.append(btn)
            self._nav_icon_specs.append((btn, icon_name, label, text))
        nav.addStretch(1)
        parent.addWidget(rail)
        self.repair_nav_icons()

    def set_page(self, index: int) -> None:
        if not hasattr(self, "stack"):
            return
        if hasattr(self, "nav_buttons") and 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        previous = self.stack.currentIndex()
        if previous == index:
            return
        self.stack.setCurrentIndex(index)
        if index == getattr(self, "programs_page_index", -1) and not getattr(self, "_program_scan_started", False):
            QTimer.singleShot(150, self.start_program_scan)
        page = self.stack.currentWidget()
        if page is not None:
            UiFx.fade_in(page, 140)
        self.repair_nav_icons()

    def repair_nav_icons(self) -> None:
        """Re-apply side-nav icons after minimize/restore/theme/paint changes.

        Some Windows/Qt/SVG combinations can lose QToolButton icon pixmaps after
        the window is minimized, restored, or repolished. Re-applying the icon
        from the stored asset path is cheap and keeps the rail stable.
        """
        specs = getattr(self, "_nav_icon_specs", [])
        fallback_map = {"home": "⌂", "cleaner": "◫", "programs": "▦", "optimizer": "☑", "registry": "▣", "diagnostics": "◈", "settings": "⚙"}
        for btn, icon_name, label, text in specs:
            try:
                icon_path = find_icon_path(os.path.join("nav", f"{icon_name}.svg")) or find_icon_path(os.path.join("nav", f"{icon_name}.png"))
                if icon_path:
                    icon = QIcon(icon_path)
                    if not icon.isNull():
                        self._nav_icon_cache[icon_name] = icon
                        btn.setIcon(icon)
                        btn.setIconSize(QSize(22, 22))
                        btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                        btn.setText(label)
                        btn.setToolTip(text)
                        continue
                fallback = fallback_map.get(icon_name, "•")
                btn.setIcon(QIcon())
                btn.setText(f"{fallback}\n{label}")
                btn.setToolButtonStyle(Qt.ToolButtonTextOnly)
                btn.setToolTip(text)
            except Exception as exc:
                log_qa_event("nav_icon_repair_failed", icon=icon_name, error=str(exc))

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            if event.type() in (QEvent.WindowStateChange, QEvent.ApplicationStateChange):
                QTimer.singleShot(50, self.repair_nav_icons)
        except Exception:
            pass
        super().changeEvent(event)

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            QTimer.singleShot(50, self.repair_nav_icons)
            UiFx.fade_in(self.centralWidget(), 180)
        except Exception:
            pass
        super().showEvent(event)

    def content_page(self, title: str, subtitle: str = "") -> Tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(16)
        head = QVBoxLayout()
        label = QLabel(title)
        label.setObjectName("PageTitle")
        head.addWidget(label)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("Muted")
            sub.setWordWrap(True)
            head.addWidget(sub)
        outer.addLayout(head)
        return page, outer

    def build_pages(self) -> None:
        self.home_page, home_layout = self.content_page(
            self.tr("home_title"),
            self.tr("home_subtitle"),
        )
        self.build_home_page(home_layout)
        self.stack.addWidget(self.home_page)

        self.cleaner_page, cleaner_layout = self.content_page(
            self.tr("tab_cleaner"),
            self.tr("tab_cleaner_sub"),
        )
        self.build_cleaner_page(cleaner_layout)
        self.stack.addWidget(self.cleaner_page)

        self.programs_page, programs_layout = self.content_page(
            self.tr("programs_title"),
            self.tr("programs_subtitle"),
        )
        self.build_programs_page(programs_layout)
        self.programs_page_index = self.stack.addWidget(self.programs_page)

        self.optimizer_page, opt_layout = self.content_page(
            self.tr("optimizer_modules").strip(),
            self.tr("optimizer_subtitle"),
        )
        self.build_optimizer_page(opt_layout)
        self.stack.addWidget(self.optimizer_page)

        self.registry_page, registry_layout = self.content_page(
            self.tr("registry_tools_title"),
            self.tr("registry_tools_sub"),
        )
        self.build_registry_page(registry_layout)
        self.stack.addWidget(self.registry_page)

        self.diagnostics_page, diag_layout = self.content_page(
            self.tr("diagnostics_modules"),
            self.tr("diagnostics_subtitle"),
        )
        self.build_diagnostics_page(diag_layout)
        self.stack.addWidget(self.diagnostics_page)

        self.settings_page, settings_layout = self.content_page(
            self.tr("settings_title"),
            self.tr("settings_subtitle"),
        )
        self.build_settings_page(settings_layout)
        self.stack.addWidget(self.settings_page)


    def build_home_page(self, parent: QVBoxLayout) -> None:
        hero = QFrame()
        hero.setObjectName("HomeHero")
        h = QHBoxLayout(hero)
        h.setContentsMargins(18, 16, 18, 16)
        h.setSpacing(18)
        text = QVBoxLayout()
        title = QLabel("FreeCleaner")
        title.setObjectName("HeroTitle")
        subtitle = QLabel(self.tr("home_hero_subtitle"))
        subtitle.setObjectName("SectionSub")
        subtitle.setWordWrap(True)
        text.addWidget(title)
        text.addWidget(subtitle)
        h.addLayout(text, 1)
        # Keep the hero header clean: the administrator state is represented by
        # the action button only.  A separate status pill here duplicated the
        # same information and made the header visually noisy.
        admin = QPushButton(self.tr("settings_admin_mode_title") if not self.is_admin else self.tr("admin_active"))
        admin.setObjectName("PrimaryButton" if not self.is_admin else "GhostButton")
        admin.setEnabled(not self.is_admin)
        admin.clicked.connect(self.restart_as_admin)
        h.addWidget(admin)
        parent.addWidget(hero)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        self.home_selected_metric = self.home_tile(self.tr("home_tile_cleaner_title"), "0", self.tr("home_tile_cleaner_action"), lambda: self.set_page(1))
        self.home_optimizer_metric = self.home_tile(self.tr("home_tile_optimizer_title"), self.tr("home_tile_optimizer_value"), self.tr("home_tile_optimizer_action"), lambda: self.set_page(2))
        self.home_backup_metric = self.home_tile(self.tr("home_tile_registry_title"), "—", self.tr("home_tile_registry_action"), lambda: self.set_page(3))
        self.home_diag_metric = self.home_tile(self.tr("home_tile_diagnostics_title"), self.tr("home_tile_diagnostics_value"), self.tr("home_tile_diagnostics_action"), lambda: self.set_page(4))
        for idx, tile in enumerate((self.home_selected_metric, self.home_optimizer_metric, self.home_backup_metric, self.home_diag_metric)):
            grid.addWidget(tile, idx // 2, idx % 2)
            QTimer.singleShot(80 + idx * 45, lambda w=tile: UiFx.fade_in(w, 160))
        parent.addLayout(grid)

        notice = QFrame()
        notice.setObjectName("InlineNotice")
        nl = QHBoxLayout(notice)
        nl.setContentsMargins(14, 12, 14, 12)
        msg = QLabel(self.tr("home_hint_controls"))
        msg.setObjectName("SectionSub")
        msg.setWordWrap(True)
        nl.addWidget(msg, 1)
        parent.addWidget(notice)
        parent.addStretch(1)

    def home_tile(self, title: str, value: str, action_text: str, callback: Callable[[], None]) -> QFrame:
        tile = ClickableTile()
        tile.setObjectName("ActionTile")
        tile.setToolTip(action_text)
        tile.clicked.connect(callback)
        layout = QVBoxLayout(tile)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(7)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        v = QLabel(value)
        v.setObjectName("HeroMetric")
        hint = QLabel(f"{action_text}  →")
        hint.setObjectName("TextLinkLabel")
        hint.setWordWrap(True)
        for child in (t, v, hint):
            child.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(t)
        layout.addWidget(v)
        layout.addStretch(1)
        layout.addWidget(hint)
        tile.metric_label = v  # type: ignore[attr-defined]
        tile.action_label = hint  # type: ignore[attr-defined]
        return tile

    def refresh_system_drive_status(self) -> None:
        """Refresh visible system-drive card without blocking the UI."""
        try:
            info = get_system_drive_info()
            value = info.get("display") or "—"
            if hasattr(self, "card_disk"):
                self.card_disk.set_value(str(value))
            if hasattr(self, "home_diag_metric"):
                # Keep Home compact but useful; full drive line stays on Cleaner.
                self.home_diag_metric.metric_label.setText(str(info.get("size_text") or "—"))  # type: ignore[attr-defined]
            log_app(f"system drive status: {value}")
        except Exception as exc:
            log_app(f"refresh_system_drive_status failed: {exc}", level="ERROR")
            if hasattr(self, "card_disk"):
                self.card_disk.set_value("—")

    def build_status_row(self, parent: QVBoxLayout) -> None:
        row = QGridLayout()
        row.setHorizontalSpacing(12)
        self.card_selected = StatusCard(self.tr("selected_modules"), "0", "Green")
        self.card_junk = StatusCard(self.tr("junk_found"), "—", "Blue")
        self.card_disk = StatusCard(self.tr("system_drive"), "—", "Green")
        self.card_admin = StatusCard(self.tr("admin_access"), self.tr("yes") if self.is_admin else self.tr("no"), "Green" if self.is_admin else "Amber")
        row.addWidget(self.card_selected, 0, 0)
        row.addWidget(self.card_junk, 0, 1)
        row.addWidget(self.card_disk, 0, 2)
        row.addWidget(self.card_admin, 0, 3)
        for column in range(4):
            row.setColumnStretch(column, 1)
        parent.addLayout(row)

    def build_cleaner_page(self, parent: QVBoxLayout) -> None:
        self.build_status_row(parent)
        toolbar = QFrame()
        toolbar.setObjectName("Panel")
        tlay = QHBoxLayout(toolbar)
        tlay.setContentsMargins(12, 10, 12, 10)
        tlay.addWidget(QLabel(self.tr("search_modules") if self.tr("search_modules") != "search_modules" else "Пошук"))
        self.search = QLineEdit()
        self.search.setPlaceholderText(self.tr("search_placeholder") if self.tr("search_placeholder") != "search_placeholder" else "Фільтр модулів")
        self.search.textChanged.connect(self.apply_search)
        tlay.addWidget(self.search, 1)
        reset_search = QPushButton(self.tr("clear_search") if self.tr("clear_search") != "clear_search" else "Очистити")
        reset_search.clicked.connect(lambda: self.search.setText(""))
        tlay.addWidget(reset_search)
        parent.addWidget(toolbar)

        self.cleaner_scroll, self.cleaner_inner, self.cleaner_inner_layout = self.scroll_container()
        parent.addWidget(self.cleaner_scroll, 1)
        self.build_footer(parent)

    def build_optimizer_page(self, parent: QVBoxLayout) -> None:
        legend = QFrame()
        legend.setObjectName("LegendStrip")
        l = QHBoxLayout(legend)
        l.setContentsMargins(12, 8, 12, 8)
        l.setSpacing(8)
        l.addWidget(QLabel(self.tr("statuses_label")))
        for text, tone in ((self.tr("registry_status_change_needed"), "Green"), (self.tr("registry_status_done"), "Blue"), (self.tr("registry_status_admin_only"), "Amber"), (self.tr("registry_status_unavailable"), "Grey")):
            l.addWidget(Pill(text, tone))
        l.addStretch(1)
        parent.addWidget(legend)

        toolbar = QFrame()
        toolbar.setObjectName("Panel")
        tl = QHBoxLayout(toolbar)
        tl.setContentsMargins(12, 10, 12, 10)
        tl.addWidget(QLabel(self.tr("search_tweaks")))
        self.optimizer_search = QLineEdit()
        self.optimizer_search.setPlaceholderText(self.tr("optimizer_search_placeholder"))
        self.optimizer_search.textChanged.connect(self.apply_optimizer_search)
        tl.addWidget(self.optimizer_search, 1)
        clear = QPushButton(self.tr("clear_search"))
        clear.clicked.connect(lambda: self.optimizer_search.setText(""))
        tl.addWidget(clear)
        parent.addWidget(toolbar)

        self.optimizer_scroll, self.optimizer_inner, self.optimizer_inner_layout = self.scroll_container()
        parent.addWidget(self.optimizer_scroll, 1)
        actions = QHBoxLayout()
        self.refresh_registry_btn = QPushButton(self.tr("task.refresh_registry_statuses.title"))
        self.refresh_registry_btn.clicked.connect(self.sync_registry_toggle_states)
        actions.addWidget(self.refresh_registry_btn)
        hint = QLabel(self.tr("optimizer_toggle_hint"))
        hint.setObjectName("SectionSub")
        actions.addWidget(hint, 1)
        parent.addLayout(actions)

    def build_registry_page(self, parent: QVBoxLayout) -> None:
        panel = QFrame()
        panel.setObjectName("RegistryPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(18, 16, 18, 16)
        title = QLabel(self.tr("registry_tools_title"))
        title.setObjectName("SectionTitle")
        layout.addWidget(title)
        sub = QLabel(self.tr("manual_registry_backup_desc") if self.tr("manual_registry_backup_desc") != "manual_registry_backup_desc" else self.tr("registry_tools_sub"))
        sub.setObjectName("Muted")
        sub.setWordWrap(True)
        layout.addWidget(sub)
        actions = QHBoxLayout()
        b1 = QPushButton(self.tr("manual_registry_backup"))
        b1.setObjectName("PrimaryButton")
        b1.clicked.connect(self.manual_registry_backup)
        b2 = QPushButton(self.tr("restore_registry_backup"))
        b2.setToolTip(self.tr("restore_registry_latest_tip"))
        b2.clicked.connect(self.restore_latest_registry_backup)
        b3 = QPushButton(self.tr("open_backup_folder"))
        b3.clicked.connect(lambda: WindowsOps.open_in_file_manager(WindowsOps.registry_backup_root()))
        actions.addWidget(b1)
        actions.addWidget(b2)
        actions.addWidget(b3)
        actions.addStretch(1)
        layout.addLayout(actions)
        parent.addWidget(panel)

        self.backup_list = QListWidget()
        self.backup_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.backup_list.itemDoubleClicked.connect(self.restore_registry_backup_item)
        self.backup_list.customContextMenuRequested.connect(self.show_registry_backup_context_menu)
        parent.addWidget(self.backup_list, 1)

    def build_diagnostics_page(self, parent: QVBoxLayout) -> None:
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        cards = [
            DiagnosticCard(self.tr("task.system_health_report.title"), self.tr("diagnostics_system_card_desc"), self.tr("diagnostics_run_check"), self.run_system_report, "#76B900"),
            DiagnosticCard(self.tr("task.gaming_compat_report.title"), self.tr("diagnostics_gaming_card_desc"), self.tr("diagnostics_collect"), self.run_gaming_report, "#4C8DFF"),
            DiagnosticCard(self.tr("task.streaming_diagnostics.title"), self.tr("diagnostics_streaming_card_desc"), self.tr("diagnostics_collect"), self.run_streaming_report, "#F59E0B"),
            DiagnosticCard(self.tr("task.onedrive_report.title"), self.tr("diagnostics_onedrive_card_desc"), self.tr("diagnostics_collect"), self.run_onedrive_report, "#22C55E"),
        ]
        self.diagnostic_cards = cards
        for idx, card in enumerate(cards):
            grid.addWidget(card, idx // 2, idx % 2)
        parent.addLayout(grid)
        log_head = QFrame()
        log_head.setObjectName("Panel")
        lh = QHBoxLayout(log_head)
        lh.setContentsMargins(12, 8, 12, 8)
        title = QLabel(self.tr("diagnostics_log_title"))
        title.setObjectName("SectionTitle")
        lh.addWidget(title)
        lh.addStretch(1)
        clear = QPushButton(self.tr("clear_log"))
        clear.clicked.connect(lambda: self.log_box.clear())
        lh.addWidget(clear)
        parent.addWidget(log_head)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        try:
            self.log_box.document().setMaximumBlockCount(450)
        except Exception:
            pass
        parent.addWidget(self.log_box, 1)

    def build_programs_page(self, parent: QVBoxLayout) -> None:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(12)

        top = QHBoxLayout()
        self.program_scan_btn = QPushButton(self.tr("programs_scan"))
        self.program_scan_btn.setObjectName("PrimaryButton")
        self.program_scan_btn.clicked.connect(self.start_program_scan)
        top.addWidget(self.program_scan_btn)
        self.program_clean_removed_btn = QPushButton(self.tr("programs_clean_removed"))
        self.program_clean_removed_btn.setObjectName("DangerButton")
        self.program_clean_removed_btn.setEnabled(False)
        self.program_clean_removed_btn.clicked.connect(self.clean_removed_program_leftovers)
        top.addWidget(self.program_clean_removed_btn)
        top.addStretch(1)
        self.program_summary = QLabel(self.tr("programs_summary_empty"))
        self.program_summary.setObjectName("Muted")
        top.addWidget(self.program_summary)
        layout.addLayout(top)

        self.program_search = QLineEdit()
        self.program_search.setPlaceholderText(self.tr("programs_search_placeholder"))
        self.program_search.textChanged.connect(self.filter_program_rows)
        layout.addWidget(self.program_search)

        self.program_tree = QTreeWidget()
        self.program_tree.setColumnCount(7)
        self.program_tree.setHeaderLabels([
            self.tr("programs_col_name"),
            self.tr("programs_col_status"),
            self.tr("programs_col_install_disk"),
            self.tr("programs_col_install_size"),
            self.tr("programs_col_leftover_disk"),
            self.tr("programs_col_leftover_size"),
            self.tr("programs_col_location"),
        ])
        self.program_tree.setAlternatingRowColors(True)
        self.program_tree.setRootIsDecorated(False)
        self.program_tree.setSortingEnabled(True)
        self.program_tree.setSelectionMode(QAbstractItemView.SingleSelection)
        self.program_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.program_tree.customContextMenuRequested.connect(self.show_program_context_menu)
        self.program_tree.itemDoubleClicked.connect(lambda item, _col: self.open_program_location(item.data(0, Qt.UserRole) or {}))
        self.program_tree.setMinimumHeight(430)
        layout.addWidget(self.program_tree, 1)
        parent.addWidget(panel, 1)

    def _program_icon(self, removed: bool = False) -> QIcon:
        pix = QPixmap(20, 20)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        if removed:
            painter.setBrush(QColor("#3A1717"))
            painter.setPen(QPen(QColor("#C65B5B"), 2))
            painter.drawEllipse(3, 3, 14, 14)
            painter.setPen(QPen(QColor("#E07A7A"), 2))
            painter.drawLine(7, 7, 13, 13)
            painter.drawLine(13, 7, 7, 13)
        else:
            painter.setBrush(QColor("#1D2A12"))
            painter.setPen(QPen(QColor("#76B900"), 2))
            painter.drawRoundedRect(3, 4, 14, 12, 2, 2)
            painter.drawLine(6, 8, 14, 8)
        painter.end()
        return QIcon(pix)

    def _context_icon(self, kind: str) -> QIcon:
        pix = QPixmap(18, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        painter.setRenderHint(QPainter.Antialiasing)
        if kind == "run":
            painter.setPen(QPen(QColor("#76B900"), 2))
            painter.setBrush(QColor("#76B900"))
            painter.drawPolygon([pix.rect().center() + QPoint(-3, -6), pix.rect().center() + QPoint(-3, 6), pix.rect().center() + QPoint(6, 0)])
        elif kind == "folder":
            painter.setPen(QPen(QColor("#D8B45A"), 2))
            painter.setBrush(QColor("#4A3715"))
            painter.drawRoundedRect(2, 5, 14, 10, 2, 2)
            painter.drawLine(3, 5, 7, 3)
        elif kind == "delete":
            painter.setPen(QPen(QColor("#B95A5A"), 2))
            painter.drawLine(5, 5, 13, 13)
            painter.drawLine(13, 5, 5, 13)
        painter.end()
        return QIcon(pix)

    def start_program_scan(self) -> None:
        if getattr(self, "_program_scan_running", False):
            return
        self._program_scan_started = True
        self._program_scan_running = True
        self.program_scan_btn.setEnabled(False)
        self.program_clean_removed_btn.setEnabled(False)
        self.program_summary.setText(self.tr("programs_summary_scanning"))
        self.program_tree.clear()
        def worker() -> None:
            try:
                entries = scan_program_inventory(threading.Event())
                self.programs_bridge.scan_finished.emit(entries)
            except Exception as exc:
                import traceback
                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                log_error(detail)
                self.programs_bridge.scan_failed.emit(str(exc))
        threading.Thread(target=worker, name="FreeCleanerProgramInventory", daemon=True).start()

    def on_program_scan_ready(self, entries: object) -> None:
        self._program_scan_running = False
        self.program_scan_btn.setEnabled(True)
        try:
            self.program_entries = list(entries or [])  # type: ignore[arg-type]
        except Exception:
            self.program_entries = []
        self.render_program_entries()
        removed_count = sum(1 for e in self.program_entries if e.get("status") == "removed")
        leftover_total = sum(int(e.get("leftover_size") or 0) for e in self.program_entries)
        self.program_summary.setText(self.trf("programs_summary_fmt", count=len(self.program_entries), removed=removed_count, size=_format_bytes(leftover_total)))
        self.program_clean_removed_btn.setEnabled(removed_count > 0)
        self.show_toast(self.tr("programs_scan_done"), "success")

    def on_program_scan_failed(self, error: str) -> None:
        self._program_scan_running = False
        self.program_scan_btn.setEnabled(True)
        self.program_summary.setText(self.tr("programs_scan_failed"))
        QMessageBox.warning(self, "FreeCleaner", self.trf("programs_scan_failed_detail", error=error))

    def render_program_entries(self) -> None:
        self.program_tree.setSortingEnabled(False)
        self.program_tree.clear()
        for entry in self.program_entries:
            removed = entry.get("status") == "removed"
            status = self.tr("programs_status_removed") if removed else self.tr("programs_status_installed")
            location = self.tr("programs_install_location_removed") if removed else (entry.get("install_path") or self.tr("programs_unknown"))
            if removed and entry.get("leftover_paths"):
                location = str((entry.get("leftover_paths") or [""])[0])
            item = QTreeWidgetItem([
                str(entry.get("name") or self.tr("programs_unknown")),
                status,
                self.tr("programs_install_location_removed") if removed else str(entry.get("install_drive") or "—"),
                _format_bytes(entry.get("install_size") or 0) if not removed else "—",
                str(entry.get("leftover_drive") or "—"),
                _format_bytes(entry.get("leftover_size") or 0),
                location,
            ])
            item.setIcon(0, self._program_icon(removed))
            item.setData(0, Qt.UserRole, entry)
            if removed:
                item.setForeground(1, QColor("#FCA5A5"))
            self.program_tree.addTopLevelItem(item)
        for col in range(self.program_tree.columnCount()):
            self.program_tree.resizeColumnToContents(col)
        self.program_tree.setSortingEnabled(True)
        self.program_tree.sortItems(1, Qt.DescendingOrder)
        self.filter_program_rows()

    def filter_program_rows(self) -> None:
        if not hasattr(self, "program_tree"):
            return
        query = _program_norm(self.program_search.text() if hasattr(self, "program_search") else "")
        for idx in range(self.program_tree.topLevelItemCount()):
            item = self.program_tree.topLevelItem(idx)
            hay = _program_norm(" ".join(item.text(col) for col in range(item.columnCount())))
            item.setHidden(bool(query and query not in hay))

    def current_program_entry(self) -> Dict[str, Any]:
        item = self.program_tree.currentItem() if hasattr(self, "program_tree") else None
        if not item:
            return {}
        data = item.data(0, Qt.UserRole)
        return data if isinstance(data, dict) else {}

    def show_program_context_menu(self, pos) -> None:
        item = self.program_tree.itemAt(pos)
        if not item:
            return
        self.program_tree.setCurrentItem(item)
        entry = item.data(0, Qt.UserRole) or {}
        if not isinstance(entry, dict):
            return
        menu = QMenu(self)
        run_action = QAction(self._context_icon("run"), self.tr("programs_open_run"), menu)
        run_action.setEnabled(bool(entry.get("exe_path")) and entry.get("status") != "removed")
        run_action.triggered.connect(lambda: self.open_or_run_program(entry))
        menu.addAction(run_action)
        loc_action = QAction(self._context_icon("folder"), self.tr("programs_open_location"), menu)
        loc_action.triggered.connect(lambda: self.open_program_location(entry))
        menu.addAction(loc_action)
        menu.addSeparator()
        del_action = QAction(self._context_icon("delete"), self.tr("programs_delete_leftovers"), menu)
        del_action.setEnabled(bool(entry.get("leftover_paths")))
        del_action.triggered.connect(lambda: self.delete_selected_program_leftovers(entry))
        menu.addAction(del_action)
        menu.exec(self.program_tree.viewport().mapToGlobal(pos))

    def open_or_run_program(self, entry: Dict[str, Any]) -> None:
        path = str(entry.get("exe_path") or "")
        if not path or not os.path.isfile(path):
            self.open_program_location(entry)
            return
        try:
            if IS_WINDOWS:
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path)
            log_action(f"program launched: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "FreeCleaner", self.trf("programs_open_failed", error=str(exc)))

    def open_program_location(self, entry: Dict[str, Any]) -> None:
        paths = list(entry.get("leftover_paths") or [])
        path = ""
        if entry.get("status") == "removed" and paths:
            path = str(paths[0])
        else:
            path = str(entry.get("install_path") or "") or (str(paths[0]) if paths else "")
        if path and os.path.isfile(path):
            path = os.path.dirname(path)
        if not path or not os.path.exists(path):
            QMessageBox.information(self, "FreeCleaner", self.tr("programs_no_location"))
            return
        try:
            if IS_WINDOWS:
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                webbrowser.open(path)
            log_action(f"program location opened: {path}")
        except Exception as exc:
            QMessageBox.warning(self, "FreeCleaner", self.trf("programs_open_failed", error=str(exc)))

    def delete_selected_program_leftovers(self, entry: Optional[Dict[str, Any]] = None) -> None:
        entry = entry or self.current_program_entry()
        paths = [str(p) for p in (entry.get("leftover_paths") or []) if p]
        if not paths:
            QMessageBox.information(self, "FreeCleaner", self.tr("programs_no_leftovers"))
            return
        name = str(entry.get("name") or self.tr("programs_unknown"))
        text = self.trf("programs_delete_selected_confirm", name=name, count=len(paths), size=_format_bytes(entry.get("leftover_size") or 0))
        if QMessageBox.question(self, self.tr("programs_confirm_title"), text) != QMessageBox.Yes:
            return
        self._run_program_cleanup(paths)

    def clean_removed_program_leftovers(self) -> None:
        removed = [e for e in self.program_entries if e.get("status") == "removed" and e.get("leftover_paths")]
        if not removed:
            QMessageBox.information(self, "FreeCleaner", self.tr("programs_no_leftovers"))
            return
        paths: list[str] = []
        total = 0
        for entry in removed:
            paths.extend([str(p) for p in (entry.get("leftover_paths") or []) if p])
            total += int(entry.get("leftover_size") or 0)
        text = self.trf("programs_delete_removed_all_confirm", count=len(removed), size=_format_bytes(total))
        if QMessageBox.question(self, self.tr("programs_confirm_title"), text) != QMessageBox.Yes:
            return
        self._run_program_cleanup(paths)

    def _run_program_cleanup(self, paths: List[str]) -> None:
        if getattr(self, "_program_cleanup_running", False):
            return
        self._program_cleanup_running = True
        self.program_clean_removed_btn.setEnabled(False)
        self.program_scan_btn.setEnabled(False)
        self.program_summary.setText(self.tr("programs_cleanup_running"))
        def worker() -> None:
            try:
                result = delete_program_leftover_paths(paths, threading.Event())
                self.programs_bridge.cleanup_finished.emit(result)
            except Exception as exc:
                import traceback
                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                log_error(detail)
                self.programs_bridge.cleanup_failed.emit(str(exc))
        threading.Thread(target=worker, name="FreeCleanerProgramLeftoverCleanup", daemon=True).start()

    def on_program_cleanup_finished(self, result: object) -> None:
        self._program_cleanup_running = False
        self.program_scan_btn.setEnabled(True)
        data = result if isinstance(result, dict) else {}
        self.show_toast(self.trf("programs_deleted_fmt", count=int(data.get("removed_items") or 0), size=_format_bytes(data.get("removed_bytes") or 0)), "success" if not data.get("errors") else "warning")
        self.start_program_scan()

    def on_program_cleanup_failed(self, error: str) -> None:
        self._program_cleanup_running = False
        self.program_scan_btn.setEnabled(True)
        self.program_clean_removed_btn.setEnabled(True)
        QMessageBox.warning(self, "FreeCleaner", self.trf("programs_delete_failed", error=error))

    def build_settings_page(self, parent: QVBoxLayout) -> None:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)

        interface, interface_layout = self.settings_tab_page()
        interface_layout.addWidget(self.settings_section_header(
            self.tr("settings_tab_interface"),
            self.tr("settings_interface_desc")
        ))
        self.ui_animations_switch = self.settings_toggle_card(
            interface_layout,
            self.tr("settings_animations_title"),
            self.tr("settings_animations_desc"),
            "ui_animations_enabled",
            os.environ.get("FREECLEANER_DISABLE_UI_ANIMATIONS") != "1",
            restart_hint=False,
            on_changed=lambda value: self.apply_runtime_config_flags(),
        )
        self.animation_speed_combo = self.settings_combo_card(
            interface_layout,
            self.tr("settings_animation_speed_title"),
            self.tr("settings_animation_speed_desc"),
            "ui_animation_duration_ms",
            [(90, self.tr("speed_fast")), (150, self.tr("speed_balanced")), (220, self.tr("speed_smooth")), (320, self.tr("speed_very_smooth"))],
            150,
            on_changed=lambda _value: self.apply_runtime_config_flags(),
        )
        self.compact_logs_switch = self.settings_toggle_card(
            interface_layout,
            self.tr("settings_compact_log_title"),
            self.tr("settings_compact_log_desc"),
            "compact_event_log",
            True,
        )
        interface_layout.addStretch(1)
        tabs.addTab(interface, self.tr("settings_tab_interface"))

        startup, startup_layout = self.settings_tab_page()
        startup_layout.addWidget(self.settings_section_header(
            self.tr("settings_startup_section_title"),
            self.tr("settings_startup_section_desc")
        ))
        self.startup_status_sync_switch = self.settings_toggle_card(
            startup_layout,
            self.tr("settings_auto_status_title"),
            self.tr("settings_auto_status_desc"),
            "startup_status_sync_enabled",
            os.environ.get("FREECLEANER_AUTO_STATUS_SYNC") == "1",
            on_changed=lambda value: self.apply_runtime_config_flags(),
        )
        self.startup_update_gate_switch = self.settings_toggle_card(
            startup_layout,
            self.tr("settings_startup_update_gate_title"),
            self.tr("settings_startup_update_gate_desc"),
            "startup_update_check_enabled",
            os.environ.get("FREECLEANER_AUTO_UPDATE_CHECK") == "1",
            on_changed=lambda value: self.apply_runtime_config_flags(),
        )
        self.auto_update_switch = self.settings_toggle_card(
            startup_layout,
            self.tr("settings_auto_update_title"),
            self.tr("settings_auto_update_desc"),
            "auto_check_updates",
            True,
        )
        self.background_limit_combo = self.settings_combo_card(
            startup_layout,
            self.tr("settings_background_limit_title"),
            self.tr("settings_background_limit_desc"),
            "background_worker_limit",
            [(1, self.tr("background_limit_1")), (2, self.tr("background_limit_2")), (3, self.tr("background_limit_3")), (4, self.tr("background_limit_4"))],
            2,
            on_changed=lambda _value: self.apply_runtime_config_flags(),
        )
        startup_layout.addStretch(1)
        tabs.addTab(startup, self.tr("settings_tab_startup"))

        safety, safety_layout = self.settings_tab_page()
        safety_layout.addWidget(self.settings_section_header(
            self.tr("settings_safety_section_title"),
            self.tr("settings_safety_section_desc")
        ))
        self.confirm_heavy_switch = self.settings_toggle_card(
            safety_layout,
            self.tr("settings_confirm_heavy_title"),
            self.tr("settings_confirm_heavy_desc"),
            "confirm_heavy_actions",
            True,
        )
        admin_panel = QFrame()
        admin_panel.setObjectName("SettingsSection")
        al = QHBoxLayout(admin_panel)
        al.setContentsMargins(14, 12, 14, 12)
        al.setSpacing(12)
        admin_text = QVBoxLayout()
        admin_title = QLabel(self.tr("settings_admin_mode_title"))
        admin_title.setObjectName("SectionTitle")
        admin_desc = QLabel(self.tr("settings_admin_mode_desc"))
        admin_desc.setObjectName("SectionSub")
        admin_desc.setWordWrap(True)
        admin_text.addWidget(admin_title)
        admin_text.addWidget(admin_desc)
        al.addLayout(admin_text, 1)
        self.admin_mode_switch = ToggleSwitch()
        self.admin_mode_switch.setChecked(self.is_admin)
        self.admin_mode_switch.setEnabled(not self.is_admin)
        self.admin_mode_switch.stateChanged.connect(self.on_admin_switch_changed)
        al.addWidget(self.admin_mode_switch)
        admin_btn = QPushButton(self.tr("admin_already_running") if self.is_admin else self.tr("restart_as_admin"))
        admin_btn.setEnabled(not self.is_admin)
        admin_btn.setObjectName("PrimaryButton" if not self.is_admin else "GhostButton")
        admin_btn.clicked.connect(self.restart_as_admin)
        al.addWidget(admin_btn)
        safety_layout.addWidget(admin_panel)
        safety_layout.addStretch(1)
        tabs.addTab(safety, self.tr("settings_tab_safety"))

        notify, notify_layout = self.settings_tab_page()
        notify_layout.addWidget(self.settings_section_header(self.tr("settings_tab_notifications"), self.tr("settings_notifications_desc")))
        self.notify_done_switch = self.settings_toggle_card(
            notify_layout,
            self.tr("settings_notify_done_title"),
            self.tr("settings_notify_done_desc"),
            "notify_on_finish",
            True,
        )
        self.notify_admin_switch = self.settings_toggle_card(
            notify_layout,
            self.tr("settings_notify_unavailable_title"),
            self.tr("settings_notify_unavailable_desc"),
            "notify_admin_required",
            True,
        )
        notify_layout.addStretch(1)
        tabs.addTab(notify, self.tr("settings_tab_notifications"))

        info, info_layout = self.settings_tab_page()
        info_layout.addWidget(self.settings_section_header(self.tr("settings_tab_info"), self.tr("settings_info_section_desc")))

        lang_panel = QFrame()
        lang_panel.setObjectName("SettingsSection")
        lang_row = QHBoxLayout(lang_panel)
        lang_row.setContentsMargins(14, 12, 14, 12)
        lang_text = QVBoxLayout()
        lang_title = QLabel(self.tr("language") if self.tr("language") != "language" else "Мова")
        lang_title.setObjectName("SectionTitle")
        lang_desc = QLabel(self.tr("language_restart_desc"))
        lang_desc.setObjectName("SectionSub")
        lang_text.addWidget(lang_title)
        lang_text.addWidget(lang_desc)
        lang_row.addLayout(lang_text, 1)
        self.lang_combo = QComboBox()
        self.lang_combo.setMinimumWidth(240)
        self.lang_options: List[Tuple[str, str]] = [("auto", f"auto — {language_display_name(self.lang_code)}")]
        for code in sorted(LANG_PACKS.keys()):
            self.lang_options.append((code, language_display_name(code)))
        for _code, label in self.lang_options:
            self.lang_combo.addItem(label)
        selected = next((i for i, (code, _label) in enumerate(self.lang_options) if code == self.lang_preference), 0)
        self.lang_combo.setCurrentIndex(selected)
        self.lang_combo.currentIndexChanged.connect(self.on_language_changed)
        lang_row.addWidget(self.lang_combo)
        info_layout.addWidget(lang_panel)

        about_panel = QFrame()
        about_panel.setObjectName("SettingsSection")
        ap = QVBoxLayout(about_panel)
        ap.setContentsMargins(14, 12, 14, 12)
        about_title = QLabel(f"FreeCleaner {APP_VERSION}")
        about_title.setObjectName("SectionTitle")
        about_text = QLabel(self.tr("about_short_desc"))
        about_text.setObjectName("SectionSub")
        about_text.setWordWrap(True)
        ap.addWidget(about_title)
        ap.addWidget(about_text)
        actions = QHBoxLayout()
        open_cfg = QPushButton(self.tr("open_config_folder") if self.tr("open_config_folder") != "open_config_folder" else "Відкрити папку конфігурації")
        open_cfg.clicked.connect(self.open_config_folder)
        open_logs = QPushButton(self.tr("open_logs_folder"))
        open_logs.clicked.connect(self.open_logs_folder)
        about = QPushButton(self.tr("about_title"))
        about.clicked.connect(self.open_about)
        update = QPushButton(self.tr("check_updates"))
        update.clicked.connect(self.check_updates)
        for b in (open_cfg, open_logs, about, update):
            actions.addWidget(b)
        actions.addStretch(1)
        ap.addLayout(actions)
        info_layout.addWidget(about_panel)
        info_layout.addStretch(1)
        tabs.addTab(info, self.tr("settings_tab_info"))

        license_page, license_layout = self.settings_tab_page()
        license_layout.addWidget(self.settings_section_header(self.tr("about_license") if self.tr("about_license") != "about_license" else "Ліцензія", self.tr("about_license_sub") if self.tr("about_license_sub") != "about_license_sub" else "Умови використання FreeCleaner."))
        self.license_text = QTextEdit()
        self.license_text.setReadOnly(True)
        self.license_text.setPlainText(self.read_project_text("LICENSE") or self.trf("about_doc_missing", name="LICENSE"))
        license_layout.addWidget(self.license_text, 1)
        privacy_btn = QPushButton(self.tr("about_privacy"))
        privacy_btn.clicked.connect(self.show_privacy_policy)
        license_layout.addWidget(privacy_btn, 0, Qt.AlignLeft)
        tabs.addTab(license_page, self.tr("about_license") if self.tr("about_license") != "about_license" else "Ліцензія")

        parent.addWidget(tabs, 1)

    def settings_tab_page(self) -> Tuple[QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(12)
        scroll.setWidget(inner)
        return scroll, layout

    def settings_toggle_card(
        self,
        parent: QVBoxLayout,
        title: str,
        subtitle: str,
        key: str,
        default: bool,
        *,
        restart_hint: bool = False,
        on_changed: Optional[Callable[[bool], None]] = None,
    ) -> ToggleSwitch:
        row = ClickableSettingRow()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("SectionSub")
        subtitle_label.setWordWrap(True)
        key_label = QLabel(f"config: {key}")
        key_label.setObjectName("SettingsKey")
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        text_box.addWidget(key_label)
        if restart_hint:
            restart_label = QLabel("застосовується після перезапуску")
            restart_label.setObjectName("SettingsRestart")
            text_box.addWidget(restart_label)
        layout.addLayout(text_box, 1)
        switch = ToggleSwitch()
        switch.setChecked(self.setting_bool(key, default))
        switch.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        layout.addWidget(switch, 0, Qt.AlignVCenter)

        def toggle_row() -> None:
            if switch.isEnabled():
                switch.setChecked(not switch.isChecked())

        def apply_state(_state: int) -> None:
            self.set_setting_bool(key, switch.isChecked())
            if on_changed:
                on_changed(switch.isChecked())
            row.setProperty("changed", "true")
            row.style().unpolish(row)
            row.style().polish(row)
            UiFx.fade_in(row, 100)
            log_qa_event("settings_bool_changed", key=key, value=bool(switch.isChecked()))

        row.clicked.connect(toggle_row)
        switch.stateChanged.connect(apply_state)
        parent.addWidget(row)
        UiFx.fade_in(row, 130)
        return switch

    def settings_combo_card(
        self,
        parent: QVBoxLayout,
        title: str,
        subtitle: str,
        key: str,
        options: Sequence[Tuple[int, str]],
        default: int,
        *,
        on_changed: Optional[Callable[[int], None]] = None,
    ) -> QComboBox:
        row = QFrame()
        row.setObjectName("SettingsCard")
        layout = QHBoxLayout(row)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(14)
        text_box = QVBoxLayout()
        text_box.setSpacing(4)
        title_label = QLabel(title)
        title_label.setObjectName("SectionTitle")
        subtitle_label = QLabel(subtitle)
        subtitle_label.setObjectName("SectionSub")
        subtitle_label.setWordWrap(True)
        key_label = QLabel(f"config: {key}")
        key_label.setObjectName("SettingsKey")
        text_box.addWidget(title_label)
        text_box.addWidget(subtitle_label)
        text_box.addWidget(key_label)
        layout.addLayout(text_box, 1)
        combo = QComboBox()
        combo.setMinimumWidth(220)
        current_value = self.setting_int(key, default, minimum=min(v for v, _ in options), maximum=max(v for v, _ in options))
        selected_index = 0
        for idx, (value, label) in enumerate(options):
            combo.addItem(label, int(value))
            if int(value) == int(current_value):
                selected_index = idx
        combo.setCurrentIndex(selected_index)

        def changed(index: int) -> None:
            value = int(combo.itemData(index) or default)
            self.set_setting_int(key, value)
            if on_changed:
                on_changed(value)
            row.setProperty("changed", "true")
            row.style().unpolish(row)
            row.style().polish(row)
            UiFx.fade_in(row, 100)
            log_qa_event("settings_int_changed", key=key, value=value)

        combo.currentIndexChanged.connect(changed)
        layout.addWidget(combo, 0, Qt.AlignVCenter)
        parent.addWidget(row)
        UiFx.fade_in(row, 130)
        return combo

    def settings_section_header(self, title: str, subtitle: str = "") -> QFrame:
        panel = QFrame()
        panel.setObjectName("SettingsSection")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("SectionTitle")
        layout.addWidget(t)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("SectionSub")
            sub.setWordWrap(True)
            layout.addWidget(sub)
        return panel

    def setting_row(self, text: str, switch: ToggleSwitch, subtitle: str = "") -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(14, 8, 14, 8)
        label_box = QVBoxLayout()
        title = QLabel(text)
        title.setObjectName("SectionTitle")
        label_box.addWidget(title)
        if subtitle:
            sub = QLabel(subtitle)
            sub.setObjectName("SectionSub")
            sub.setWordWrap(True)
            label_box.addWidget(sub)
        row.addLayout(label_box, 1)
        row.addWidget(switch, 0, Qt.AlignVCenter)
        return row

    def read_project_text(self, filename: str) -> str:
        candidates = []
        try:
            base = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            candidates.append(os.path.join(base, filename))
        except Exception:
            pass
        try:
            if getattr(sys, "frozen", False):
                candidates.append(os.path.join(os.path.dirname(sys.executable), filename))
        except Exception:
            pass
        for path in candidates:
            try:
                if path and os.path.isfile(path):
                    with open(path, "r", encoding="utf-8", errors="replace") as fh:
                        return fh.read()
            except Exception:
                continue
        return ""

    def scroll_container(self) -> Tuple[QScrollArea, QWidget, QVBoxLayout]:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addStretch(1)
        scroll.setWidget(inner)
        return scroll, inner, layout

    def build_footer(self, parent: QVBoxLayout) -> None:
        foot = QFrame()
        foot.setObjectName("Panel")
        layout = QVBoxLayout(foot)
        layout.setContentsMargins(14, 12, 14, 12)
        self.result_label = QLabel(self.tr("freed_zero") if self.tr("freed_zero") != "freed_zero" else "Звільнено: 0.00 MB")
        self.result_label.setStyleSheet("font-size: 18px; font-weight: 800;")
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress_anim = None
        self._progress_target_value = 0
        self._progress_anim_timer = QTimer(self)
        self._progress_anim_timer.setInterval(24)
        self._progress_anim_timer.timeout.connect(self._tick_progress_animation)
        layout.addWidget(self.result_label)
        layout.addWidget(self.progress)
        actions = QHBoxLayout()
        self.run_btn = QPushButton(self.tr("analyze_clean"))
        self.run_btn.setObjectName("PrimaryButton")
        self.run_btn.clicked.connect(self.start_clean)
        self.scan_btn = QPushButton(self.tr("analyze_only") if self.tr("analyze_only") != "analyze_only" else "Лише аналіз")
        self.scan_btn.clicked.connect(self.start_analysis)
        self.reset_btn = QPushButton(self.tr("reset_all"))
        self.reset_btn.clicked.connect(self.clear_selection)
        actions.addWidget(self.run_btn, 2)
        actions.addWidget(self.scan_btn, 1)
        actions.addWidget(self.reset_btn, 1)
        layout.addLayout(actions)
        parent.addWidget(foot)

    def section(self, parent_layout: QVBoxLayout, key: str, title: str) -> UiTaskSection:
        panel = QFrame()
        panel.setObjectName("Panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        head = QLabel(title)
        head.setObjectName("SectionTitle")
        layout.addWidget(head)
        parent_layout.insertWidget(max(0, parent_layout.count() - 1), panel)
        section = UiTaskSection(key, title, [], panel, layout)
        self.sections[key] = section
        return section

    # ------------------------- task registration -------------------------
    def add_task(self, section_key: str, task: CleanerTask, *, switch: bool = False) -> None:
        self.tasks[task.key] = task
        if section_key not in self.sections:
            raise KeyError(section_key)
        title, desc = self.task_text(task)
        enabled = task.state != "disabled" and (not task.requires_admin or self.is_admin or (switch and task.category == "optimizer"))
        status = "checking" if switch and task.category == "optimizer" else self.status_for_task(task)
        row = TaskRow(task, title, desc, switch=switch, status=status, enabled=enabled)
        row.changed.connect(lambda key=task.key: self.on_task_row_changed(key))
        self.rows[task.key] = row
        sec = self.sections[section_key]
        sec.rows.append(row)
        sec.layout.addWidget(row)

    @staticmethod
    def registry_keys_for_specs(specs: Sequence[RegistryValueSpec]) -> List[str]:
        keys: List[str] = []
        seen = set()
        for spec in specs or []:
            key = spec.key_path
            if key and key not in seen:
                seen.add(key)
                keys.append(key)
        return keys

    def on_ui_heartbeat(self) -> None:
        # Tiny GUI-thread heartbeat. A daemon watchdog thread checks this value;
        # if it stops changing, the Qt event loop is blocked. Log only every few
        # seconds to avoid making logging itself part of the problem.
        try:
            now = time.monotonic()
            self._last_ui_heartbeat_monotonic = now
            if now - float(getattr(self, "_last_ui_heartbeat_logged", 0.0)) >= 5.0:
                self._last_ui_heartbeat_logged = now
                log_qa_event(
                    "ui_heartbeat",
                    thread=threading.current_thread().name,
                    status_worker=bool(getattr(self, "_status_sync_worker_active", False)),
                    toggle_jobs=list(getattr(self, "toggle_jobs", {}).keys()),
                    main_worker=bool(getattr(self, "thread", None) is not None),
                    estimate_active=bool(getattr(self, "_estimate_active", False)),
                )
        except Exception:
            pass

    def _ui_freeze_watchdog_loop(self) -> None:
        # Runs outside Qt. It does not touch widgets; it only reports a frozen
        # event loop for QA logs when heartbeat stops.
        last_report = 0.0
        while not getattr(self, "_ui_watchdog_stop", threading.Event()).is_set():
            try:
                time.sleep(2.0)
                last = float(getattr(self, "_last_ui_heartbeat_monotonic", 0.0) or 0.0)
                delta = time.monotonic() - last
                if last > 0 and delta >= 6.0 and (time.monotonic() - last_report) >= 6.0:
                    last_report = time.monotonic()
                    log_qa_event(
                        "ui_event_loop_stalled",
                        seconds=round(delta, 2),
                        status_worker=bool(getattr(self, "_status_sync_worker_active", False)),
                        toggle_jobs=list(getattr(self, "toggle_jobs", {}).keys()),
                        main_worker=bool(getattr(self, "thread", None) is not None),
                        estimate_active=bool(getattr(self, "_estimate_active", False)),
                    )
            except Exception:
                pass

    def register_tasks(self) -> None:
        self.section(self.cleaner_inner_layout, "clean_basic", "Системне очищення")
        self.section(self.cleaner_inner_layout, "clean_browser", "Браузери та застосунки")
        self.section(self.cleaner_inner_layout, "clean_game", "Ігри та стрімінг")
        self.section(self.cleaner_inner_layout, "clean_deep", "Глибоке очищення")
        self.section(self.optimizer_inner_layout, "opt_core", "Windows gaming tweaks")
        self.section(self.optimizer_inner_layout, "opt_registry", "Registry tweaks")
        self.register_cleaner_tasks()
        self.register_optimizer_tasks()

    def register_cleaner_tasks(self) -> None:
        for index, path in enumerate(PathFinder.existing(PathFinder.get_user_temp_paths())):
            self.add_task("clean_basic", CleanerTask(
                key=f"user_temp_{index}", title_key="task.user_temp.title", desc_key="task.user_temp.desc",
                path=path, paths=[path], category="system", default=True, fmt={"path": path}, control="checkbox",
            ))
        sys_state = "normal" if self.is_admin else "disabled"
        for index, path in enumerate(PathFinder.existing(PathFinder.get_system_temp_paths())):
            self.add_task("clean_basic", CleanerTask(
                key=f"sys_temp_{index}", title_key="task.system_temp.title", desc_key="task.system_temp.desc",
                path=path, paths=[path], category="system", default=self.is_admin, state=sys_state, requires_admin=True, fmt={"path": path}, control="checkbox",
            ))

        deep_keys = {
            "prefetch", "update_cache_files", "delivery_opt_programdata", "delivery_opt_networkservice", "wer_system",
            "windows_logs_cbs", "windows_logs_dism", "windows_logs_mosetup", "windows_logs_waasmedic",
            "windows_setupcln_logs", "windows_wmi_diagtrack_logs", "windows_panther_logs",
            "windows_minidump", "windows_memory_dump", "windows_old",
        }
        for key, tkey, dkey, path, requires_admin in PathFinder.get_windows_junk_targets():
            section = "clean_deep" if key in deep_keys else "clean_basic"
            state = sys_state if requires_admin else "normal"
            self.add_task(section, CleanerTask(key=key, title_key=tkey, desc_key=dkey, path=path, paths=[path], category="deep" if section == "clean_deep" else "system", default=False, state=state, requires_admin=requires_admin, fmt={"path": path}))

        uwp_paths = PathFinder.get_uwp_temp_cache_targets()
        if uwp_paths:
            self.add_task("clean_basic", CleanerTask(key="uwp_temp_caches", title_key="task.uwp_temp_caches.title", desc_key="task.uwp_temp_caches.desc", path=uwp_paths[0], paths=uwp_paths, category="system", default=False, fmt={"count": str(len(uwp_paths)), "path": uwp_paths[0]}))

        chromium_groups: Dict[Tuple[str, str], List[str]] = {}
        for _key, _tkey, _dkey, path, fmt in PathFinder.get_chromium_cache_targets():
            chromium_groups.setdefault((fmt.get("browser", "Chromium"), fmt.get("profile", "Default")), []).append(path)
        for (browser, profile), paths_raw in sorted(chromium_groups.items()):
            paths = PathFinder.unique_existing(paths_raw)
            if not paths:
                continue
            safe_key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"browser_{browser}_{profile}_cache").strip("_").lower()
            self.add_task("clean_browser", CleanerTask(key=safe_key, title_key="task.browser_generic.title", desc_key="task.browser_generic.desc", path=paths[0], paths=paths, category="browsers", default=False, fmt={"browser": browser, "profile": profile, "path": paths[0]}))

        firefox_groups: Dict[str, List[str]] = {}
        for _key, _tkey, _dkey, path, fmt in PathFinder.get_firefox_cache_targets():
            firefox_groups.setdefault(fmt.get("profile", "Default"), []).append(path)
        for profile, paths_raw in sorted(firefox_groups.items()):
            paths = PathFinder.unique_existing(paths_raw)
            if paths:
                safe_key = re.sub(r"[^a-zA-Z0-9_]+", "_", f"firefox_{profile}_cache").strip("_").lower()
                self.add_task("clean_browser", CleanerTask(key=safe_key, title_key="task.firefox_cache2.title", desc_key="task.firefox_cache2.desc", path=paths[0], paths=paths, category="browsers", default=False, fmt={"profile": profile, "path": paths[0]}))

        app_groups: Dict[str, Dict[str, Any]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_app_cache_targets():
            app_name = fmt.get("app") or key.split("_")[0].title()
            base = "discord" if key.startswith("discord_") else re.sub(r"[^a-zA-Z0-9_]+", "_", app_name).strip("_").lower()
            group = app_groups.setdefault(base, {"title_key": tkey, "desc_key": dkey, "paths": [], "app": app_name})
            group["paths"].append(path)
        for base, group in sorted(app_groups.items()):
            paths = PathFinder.unique_existing(group["paths"])
            if paths:
                self.add_task("clean_browser", CleanerTask(key=f"{base}_cache_group", title_key=group["title_key"], desc_key=group["desc_key"], path=paths[0], paths=paths, category="browsers", default=False, fmt={"app": group["app"], "path": paths[0]}))

        for key, tkey, dkey, path, requires_admin in PathFinder.get_gaming_cache_targets():
            self.add_task("clean_game", CleanerTask(key=key, title_key=tkey, desc_key=dkey, path=path, paths=[path], category="gamer", default=False, state=sys_state if requires_admin else "normal", requires_admin=requires_admin, fmt={"path": path}))
        streaming_groups: Dict[str, Dict[str, Any]] = {}
        for key, tkey, dkey, path, fmt in PathFinder.get_streaming_cache_targets():
            app_name = fmt.get("app") or "Streaming app"
            base = re.sub(r"[^a-zA-Z0-9_]+", "_", f"streaming_{app_name}_{'logs' if 'log' in key or 'crash' in key else 'cache'}").strip("_").lower()
            group = streaming_groups.setdefault(base, {"title_key": tkey, "desc_key": dkey, "paths": [], "app": app_name})
            group["paths"].append(path)
        for base, group in sorted(streaming_groups.items()):
            paths = PathFinder.unique_existing(group["paths"])
            if paths:
                self.add_task("clean_game", CleanerTask(key=f"{base}_group", title_key=group["title_key"], desc_key=group["desc_key"], path=paths[0], paths=paths, category="gamer", default=False, fmt={"app": group["app"], "path": paths[0]}))

        # command-style cleanup actions
        self.add_task("clean_browser", CleanerTask(key="dns_flush", title_key="task.dns_flush.title", desc_key="task.dns_flush.desc", kind="command", category="browsers", default=True, command=lambda: WindowsOps.run_command_args(["ipconfig.exe", "/flushdns"], timeout=60)))
        self.add_task("clean_deep", CleanerTask(key="recycle", title_key="task.recycle.title", desc_key="task.recycle.desc", kind="command", category="deep", default=False, command=WindowsOps.clear_recycle_bin))
        self.add_task("clean_deep", CleanerTask(key="registry_leftovers_conservative", title_key="task.registry_leftovers.title", desc_key="task.registry_leftovers.desc", kind="command", category="deep", default=False, command=lambda: WindowsOps.cleanup_registry_leftovers(include_machine=self.is_admin)))
        self.add_task("clean_deep", CleanerTask(key="dism_clean", title_key="task.dism_clean.title", desc_key="task.dism_clean.desc", kind="command", category="ultimate", default=False, state=sys_state, requires_admin=True, command=lambda: WindowsOps.run_command_args(["dism.exe", "/Online", "/Cleanup-Image", "/StartComponentCleanup"], timeout=3600), danger="heavy"))

    def register_optimizer_tasks(self) -> None:
        # Do not mark admin-only toggles as globally disabled when the app is not
        # elevated.  They must stay clickable so the UI can explain the admin
        # requirement instead of looking broken/inactive.  Actual execution is
        # still blocked in start_toggle_task().
        state = "normal"
        self.revert_registry_specs.clear()
        self.revert_commands.clear()

        def add_registry_task(key: str, title_key: str, desc_key: str, specs: List[RegistryValueSpec], *, supports: bool = True, reboot: bool = False, off_specs: Optional[List[RegistryValueSpec]] = None) -> None:
            if off_specs:
                self.revert_registry_specs[key] = off_specs
            self.add_task(
                "opt_registry",
                CleanerTask(
                    key=key,
                    title_key=title_key,
                    desc_key=desc_key,
                    kind="command",
                    category="optimizer",
                    default=False,
                    state=state if supports else "disabled",
                    requires_admin=any(s.requires_admin for s in specs),
                    registry_values=specs,
                    registry_keys=self.registry_keys_for_specs(specs),
                    reboot_required=reboot,
                    command=lambda specs=specs: WindowsOps.apply_registry_values(specs),
                    control="switch",
                ),
                switch=True,
            )

        add_registry_task("enable_game_mode", "task.enable_game_mode.title", "task.enable_game_mode.desc", [
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AllowAutoGameMode", 1, label="GameBar/AllowAutoGameMode"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 1, label="GameBar/AutoGameModeEnabled"),
        ], off_specs=[
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AllowAutoGameMode", 0, label="GameBar/AllowAutoGameMode"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "AutoGameModeEnabled", 0, label="GameBar/AutoGameModeEnabled"),
        ])
        add_registry_task("disable_gamedvr", "task.disable_gamedvr.title", "task.disable_gamedvr.desc", [
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 0, label="GameConfigStore/GameDVR_Enabled"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehaviorMode", 2, label="GameConfigStore/FSEBehaviorMode"),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 0, label="GameConfigStore/HonorFSE"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 0, label="GameDVR/AppCaptureEnabled"),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "ShowStartupPanel", 0, label="GameBar/ShowStartupPanel"),
            RegistryValueSpec(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 0, label="Policy GameDVR/AllowGameDVR", requires_admin=True),
        ], reboot=True, off_specs=[
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_Enabled", 1),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_FSEBehaviorMode", 0),
            RegistryValueSpec(r"HKCU\System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", 1),
            RegistryValueSpec(r"HKCU\Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", 1),
            RegistryValueSpec(r"HKCU\Software\Microsoft\GameBar", "ShowStartupPanel", 1),
            RegistryValueSpec(r"HKLM\SOFTWARE\Policies\Microsoft\Windows\GameDVR", "AllowGameDVR", 1, requires_admin=True),
        ])
        add_registry_task("disable_mouse_acceleration", "task.disable_mouse_acceleration.title", "task.disable_mouse_acceleration.desc", [
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseSpeed", "0", "REG_SZ", label="Mouse/MouseSpeed"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold1", "0", "REG_SZ", label="Mouse/MouseThreshold1"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold2", "0", "REG_SZ", label="Mouse/MouseThreshold2"),
        ], off_specs=[
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseSpeed", "1", "REG_SZ"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold1", "6", "REG_SZ"),
            RegistryValueSpec(r"HKCU\Control Panel\Mouse", "MouseThreshold2", "10", "REG_SZ"),
        ])
        add_registry_task("enable_hags", "task.enable_hags.title", "task.enable_hags.desc", [
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2, label="GraphicsDrivers/HwSchMode", requires_admin=True),
        ], supports=WindowsOps.supports_hags(), reboot=True, off_specs=[
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 1, requires_admin=True),
        ])
        add_registry_task("disable_power_throttling", "task.disable_power_throttling.title", "task.disable_power_throttling.desc", [
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", 1, label="PowerThrottling/PowerThrottlingOff", requires_admin=True),
        ], supports=WindowsOps.supports_power_throttling(), reboot=True, off_specs=[
            RegistryValueSpec(r"HKLM\SYSTEM\CurrentControlSet\Control\Power\PowerThrottling", "PowerThrottlingOff", 0, requires_admin=True),
        ])
        add_registry_task("network_throttling_off", "task.network_throttling_off.title", "task.network_throttling_off.desc", [
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", "0xffffffff", label="SystemProfile/NetworkThrottlingIndex", requires_admin=True),
        ], reboot=True, off_specs=[
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "NetworkThrottlingIndex", 10, requires_admin=True),
        ])
        add_registry_task("mmcss_gaming_profile", "task.mmcss_gaming_profile.title", "task.mmcss_gaming_profile.desc", [
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 10, label="SystemProfile/SystemResponsiveness", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority", 8, label="Games/GPU Priority", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority", 6, label="Games/Priority", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category", "High", "REG_SZ", label="Games/Scheduling Category", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "SFIO Priority", "High", "REG_SZ", label="Games/SFIO Priority", requires_admin=True),
        ], reboot=True, off_specs=[
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile", "SystemResponsiveness", 20, requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "GPU Priority", 8, requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Priority", 2, requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "Scheduling Category", "Medium", "REG_SZ", requires_admin=True),
            RegistryValueSpec(r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile\Tasks\Games", "SFIO Priority", "Normal", "REG_SZ", requires_admin=True),
        ])

        self.revert_commands.update({
            "high_perf_plan": WindowsOps.restore_balanced_power_profile,
            "safe_gaming_power_profile": WindowsOps.restore_balanced_power_profile,
            "cpu_latency_power_profile": WindowsOps.restore_balanced_power_profile,
            "ultimate_perf_plan": WindowsOps.restore_balanced_power_profile,
            "disable_dynamic_tick_latency": WindowsOps.restore_dynamic_tick_default,
        })
        self.add_task("opt_core", CleanerTask(key="high_perf_plan", title_key="task.high_perf_plan.title", desc_key="task.high_perf_plan.desc", kind="command", category="optimizer", state=state, requires_admin=True, command=lambda: WindowsOps.run_command_args(["powercfg.exe", "/S", "SCHEME_MIN"], timeout=90), control="switch"), switch=True)
        self.add_task("opt_core", CleanerTask(key="safe_gaming_power_profile", title_key="task.safe_gaming_power_profile.title", desc_key="task.safe_gaming_power_profile.desc", kind="command", category="optimizer", state=state, requires_admin=True, command=WindowsOps.apply_safe_gaming_power_profile, control="switch"), switch=True)
        self.add_task("opt_core", CleanerTask(key="cpu_latency_power_profile", title_key="task.cpu_latency_power_profile.title", desc_key="task.cpu_latency_power_profile.desc", kind="command", category="optimizer", state=state, requires_admin=True, command=WindowsOps.apply_cpu_latency_performance_profile, control="switch"), switch=True)
        self.add_task("opt_core", CleanerTask(key="ultimate_perf_plan", title_key="task.ultimate_perf_plan.title", desc_key="task.ultimate_perf_plan.desc", kind="command", category="optimizer", state=state if WindowsOps.supports_ultimate_performance() else "disabled", requires_admin=True, command=WindowsOps.try_enable_ultimate_performance, control="switch"), switch=True)
        self.add_task("opt_core", CleanerTask(key="purge_standby_ram", title_key="task.purge_standby_ram.title", desc_key="task.purge_standby_ram.desc", kind="command", category="optimizer", state=state, requires_admin=True, command=WindowsOps.purge_standby_memory, control="switch", instant_action=True), switch=True)
        self.add_task("opt_core", CleanerTask(key="disable_dynamic_tick_latency", title_key="task.disable_dynamic_tick_latency.title", desc_key="task.disable_dynamic_tick_latency.desc", kind="command", category="optimizer", state=state if WindowsOps.supports_dynamic_tick_toggle() else "disabled", requires_admin=True, command=lambda: WindowsOps.set_dynamic_tick_disabled(True), reboot_required=True, control="switch"), switch=True)

    # ------------------------- statuses and operations -------------------------
    def defer_status_sync(self, delay_ms: int = 0) -> None:
        """Synchronize Windows/toggle statuses without spawning command storms.

        Multiple row updates can request a refresh at almost the same time.  The
        first request wins; later ones are coalesced.  A small rate limit keeps
        powercfg/BCDEdit probes from running dozens of times when a user toggles
        several switches quickly, while still leaving the UI responsive.
        """
        if self._status_sync_pending:
            log_qa_event("status_sync_coalesced", delay_ms=delay_ms)
            return
        self._status_sync_pending = True

        def run() -> None:
            now = time.monotonic()
            min_gap = 0.9
            remaining_ms = int(max(0.0, min_gap - (now - float(getattr(self, "_last_status_sync_started_at", 0.0)))) * 1000)
            if remaining_ms > 0:
                QTimer.singleShot(remaining_ms, run)
                return
            if getattr(self, "thread", None) is not None:
                QTimer.singleShot(120, run)
                return
            if getattr(self, "toggle_jobs", {}):
                # Do not rescan while a toggle worker is still active. That was
                # the main source of stale/overwritten visual switch states.
                QTimer.singleShot(180, run)
                return
            if getattr(self, "_status_sync_worker_active", False):
                QTimer.singleShot(180, run)
                return
            self._status_sync_pending = False
            self._last_status_sync_started_at = time.monotonic()
            self.start_status_sync_worker()

        QTimer.singleShot(max(0, int(delay_ms)), run)

    def invalidate_system_status_cache(self) -> None:
        self._active_power_scheme_cache = None
        self._active_power_scheme_guid_cache = None
        self._dynamic_tick_cache = None
        self._powercfg_value_cache = {}

    @staticmethod
    def _is_high_power_text(text: str) -> bool:
        folded = str(text or "").casefold()
        return ("scheme_min" in folded) or ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" in folded) or ("high performance" in folded)

    @staticmethod
    def _is_ultimate_power_text(text: str) -> bool:
        folded = str(text or "").casefold()
        return ("e9a42b02-d5df-448d-aa00-03f14749eb61" in folded) or ("ultimate performance" in folded)

    @staticmethod
    def _command_status_from_values(key: str, active_text: str, values: Dict[Tuple[str, str], Optional[int]], dynamic_tick: Optional[bool]) -> Optional[bool]:
        if key == "high_perf_plan":
            return FreeCleanerQt._is_high_power_text(active_text) if active_text else None
        if key == "safe_gaming_power_profile":
            if not active_text:
                return None
            high = FreeCleanerQt._is_high_power_text(active_text)
            epp = values.get(("SUB_PROCESSOR", "PERFEPP"))
            aspm = values.get(("SUB_PCIEXPRESS", "ASPM"))
            boost = values.get(("SUB_PROCESSOR", "PERFBOOSTMODE"))
            # ASPM alone is not enough to prove the CPU profile is applied.
            processor_known = [value for value in (epp, boost) if value is not None]
            if not processor_known:
                return None if high else False
            return high and (epp in (0, None)) and (aspm in (0, None)) and (boost in (1, 2, None))
        if key == "cpu_latency_power_profile":
            if not active_text:
                return None
            high = FreeCleanerQt._is_high_power_text(active_text)
            epp = values.get(("SUB_PROCESSOR", "PERFEPP"))
            aspm = values.get(("SUB_PCIEXPRESS", "ASPM"))
            boost = values.get(("SUB_PROCESSOR", "PERFBOOSTMODE"))
            min_cores = values.get(("SUB_PROCESSOR", "CPMINCORES"))
            processor_known = [value for value in (epp, boost, min_cores) if value is not None]
            if not processor_known:
                return None if high else False
            return high and (epp in (0, None)) and (aspm in (0, None)) and (boost in (2, None)) and (min_cores in (100, None))
        if key == "ultimate_perf_plan":
            return FreeCleanerQt._is_ultimate_power_text(active_text) if active_text else None
        if key == "disable_dynamic_tick_latency":
            return dynamic_tick
        if key == "purge_standby_ram":
            return False
        return None

    def active_power_scheme_guid_cached(self, *, refresh: bool = False) -> Optional[str]:
        # Non-blocking cache accessor.  The async status worker refreshes this.
        return self._active_power_scheme_guid_cache

    def powercfg_ac_value_cached(self, subgroup: str, setting: str) -> Optional[int]:
        # Non-blocking cache accessor.  The async status worker refreshes this.
        scheme = (self._active_power_scheme_guid_cache or "").lower()
        return self._powercfg_value_cache.get((scheme, str(subgroup), str(setting)))

    def active_power_scheme_text(self, *, refresh: bool = False) -> str:
        # Non-blocking cache accessor.  Status worker refreshes the value.
        return self._active_power_scheme_cache or ""

    def dynamic_tick_disabled_state(self, *, refresh: bool = False) -> Optional[bool]:
        # Non-blocking cache accessor.  Status worker refreshes the value.
        return self._dynamic_tick_cache

    def command_task_applied(self, task: CleanerTask) -> Optional[bool]:
        # GUI code must not synchronously run powercfg/BCDEdit.  The async
        # status worker fills _status_applied_cache and this method only reads
        # that cached result.  This prevents short UI freezes when the user
        # clicks or navigates while Windows command probes are running.
        if task.instant_action:
            return False
        if task.requires_admin and not self.is_admin and task.key == "disable_dynamic_tick_latency":
            return None
        if task.key in getattr(self, "_status_applied_cache", {}):
            return self._status_applied_cache.get(task.key)
        return None

    def status_for_task(self, task: CleanerTask) -> str:
        # This method is called from paint/update paths.  Never run registry,
        # powercfg or BCDEdit probes here; the async status worker owns them.
        if task.requires_admin and not self.is_admin:
            return self.tr("registry_status_admin_only")
        if task.state == "disabled":
            return self.tr("registry_status_unavailable") if task.registry_values else "disabled"
        if task.category == "optimizer" and task.control == "switch":
            applied = self.command_task_applied(task)
            if applied is True:
                return self.tr("registry_status_done")
            if applied is False:
                return self.tr("registry_status_change_needed")
            return "checking"
        if task.registry_values:
            return self.tr("registry_status_change_needed")
        if task.category == "optimizer" and task.kind != "directory":
            applied = self.command_task_applied(task)
            if applied is True:
                return self.tr("registry_status_done")
            if applied is False:
                return self.tr("registry_status_change_needed")
            return "action"
        if task.paths or task.path:
            return "clean"
        return "action"

    def _snapshot_status_tasks(self) -> List[Dict[str, Any]]:
        snapshot: List[Dict[str, Any]] = []
        busy = set(getattr(self, "toggle_jobs", {}).keys())
        for task in self.tasks.values():
            if task.category != "optimizer" or task.control != "switch":
                continue
            if task.key in busy:
                log_qa_event("status_sync_skip_busy_toggle", key=task.key)
                continue
            snapshot.append({
                "key": task.key,
                "state": task.state,
                "requires_admin": bool(task.requires_admin),
                "instant_action": bool(task.instant_action),
                "registry_values": list(task.registry_values or []),
            })
        return snapshot

    def start_status_sync_worker(self) -> None:
        if getattr(self, "_status_sync_worker_active", False):
            self._status_sync_pending = True
            log_qa_event("status_sync_worker_coalesced")
            return
        token = int(getattr(self, "_status_sync_token", 0)) + 1
        self._status_sync_token = token
        self._status_sync_worker_active = True
        snapshot = self._snapshot_status_tasks()
        is_admin = bool(self.is_admin)
        log_action("status_sync_start")
        log_qa_event("status_sync_start", token=token, active_toggles=list(getattr(self, "toggle_jobs", {}).keys()), tasks=len(snapshot), async_worker=True)

        def worker() -> None:
            started = time.monotonic()
            result: Dict[str, Any] = {"token": token, "items": {}, "elapsed_ms": 0}
            try:
                active_text = ""
                active_guid: Optional[str] = None
                power_values: Dict[Tuple[str, str], Optional[int]] = {}

                needs_power = any(item["key"] in {"high_perf_plan", "safe_gaming_power_profile", "cpu_latency_power_profile", "ultimate_perf_plan"} for item in snapshot)
                if IS_WINDOWS and needs_power:
                    rc, output = WindowsOps.run_command_capture(
                        WindowsOps.powercfg_args("/getactivescheme"),
                        timeout=30,
                        log_failure=False,
                        context={"feature": "qt_status_active_power_scheme", "optional": True},
                    )
                    if rc == 0 and output:
                        active_text = " ".join(output.strip().split()).casefold()
                        active_guid = WindowsOps.parse_active_power_scheme_guid(output)

                def get_power_value(subgroup: str, setting: str) -> Optional[int]:
                    key_tuple = (str(subgroup), str(setting))
                    if key_tuple not in power_values:
                        power_values[key_tuple] = WindowsOps.powercfg_get_ac_value(subgroup, setting, scheme=active_guid or "SCHEME_CURRENT") if IS_WINDOWS else None
                    return power_values.get(key_tuple)

                dynamic_tick: Optional[bool] = None
                for item in snapshot:
                    key = str(item.get("key") or "")
                    registry_values = item.get("registry_values") or []
                    try:
                        if registry_values:
                            statuses = WindowsOps.registry_statuses(registry_values)
                            applied = bool(statuses) and all(s.get("matches") for s in statuses)
                            result["items"][key] = {"kind": "registry", "applied": applied, "statuses": statuses}
                            log_qa_event("status_sync_registry", key=key, applied=applied, statuses=statuses)
                            continue

                        if item.get("instant_action"):
                            result["items"][key] = {"kind": "command", "applied": False}
                            log_qa_event("status_sync_command", key=key, applied=False)
                            continue

                        if key == "disable_dynamic_tick_latency":
                            # BCDEdit can return Access denied or stall depending on BCD store
                            # policy. Do not probe it during passive status sync; only the
                            # explicit toggle worker may run BCDEdit. This keeps UI clicks safe.
                            result["items"][key] = {"kind": "command", "applied": None, "boot_status_probe_skipped": True}
                            log_qa_event("status_sync_command_skipped_boot_probe", key=key, admin=is_admin)
                            continue

                        if key in {"safe_gaming_power_profile", "cpu_latency_power_profile"}:
                            get_power_value("SUB_PROCESSOR", "PERFEPP")
                            get_power_value("SUB_PCIEXPRESS", "ASPM")
                            get_power_value("SUB_PROCESSOR", "PERFBOOSTMODE")
                            if key == "cpu_latency_power_profile":
                                get_power_value("SUB_PROCESSOR", "CPMINCORES")

                        applied = FreeCleanerQt._command_status_from_values(key, active_text, power_values, dynamic_tick)
                        result["items"][key] = {"kind": "command", "applied": applied}
                        log_qa_event("status_sync_command", key=key, applied=applied)
                    except Exception as exc:
                        result["items"][key] = {"kind": "error", "applied": None, "error": str(exc)}
                        log_error(f"status sync failed for {key}: {exc}")
                result["active_text"] = active_text
                result["active_guid"] = active_guid
                result["elapsed_ms"] = int((time.monotonic() - started) * 1000)
                self.status_bridge.finished.emit(token, result)
            except Exception as exc:
                import traceback
                detail = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
                log_error(detail)
                self.status_bridge.failed.emit(token, detail or str(exc))

        threading.Thread(target=worker, name="FreeCleanerStatusSync", daemon=True).start()

    def sync_registry_toggle_states(self) -> None:
        """Public refresh entry point: run status probes off the GUI thread."""
        self.defer_status_sync(0)

    def on_status_sync_failed(self, token: int, error: str) -> None:
        if token != getattr(self, "_status_sync_token", token):
            return
        self._status_sync_worker_active = False
        log_error(f"status sync worker failed: {error}")
        log_action("status_sync_complete")
        log_qa_event("status_sync_complete", token=token, failed=True)
        if getattr(self, "_status_sync_pending", False):
            self._status_sync_pending = False
            self.defer_status_sync(350)

    def on_status_sync_ready(self, token: int, result: Dict[str, Any]) -> None:
        if token != getattr(self, "_status_sync_token", token):
            log_qa_event("status_sync_stale_result_ignored", token=token, current=getattr(self, "_status_sync_token", None))
            return
        self._status_sync_worker_active = False
        self._active_power_scheme_cache = str(result.get("active_text") or "")
        self._active_power_scheme_guid_cache = result.get("active_guid") or self._active_power_scheme_guid_cache
        items = result.get("items") or {}
        try:
            for task in self.tasks.values():
                if task.category != "optimizer" or task.control != "switch":
                    continue
                row = self.rows.get(task.key)
                if not row or task.key in getattr(self, "toggle_jobs", {}) or self.toggle_group_busy(task.key):
                    continue
                row.control.setEnabled(self.row_base_enabled(row))
                item = items.get(task.key) or {}
                applied = item.get("applied") if isinstance(item, dict) else None
                self._status_applied_cache[task.key] = applied if applied is None else bool(applied)
                if applied is not None:
                    was_blocked = row.control.blockSignals(True)
                    try:
                        row.control.setChecked(bool(applied))
                    finally:
                        row.control.blockSignals(was_blocked)
                    row.set_selected_property(bool(applied) and row.control.isEnabled())
                    row.update_status(self.tr("registry_status_done") if applied else self.tr("registry_status_change_needed"))
                else:
                    if task.requires_admin and not self.is_admin:
                        status = self.tr("registry_status_admin_only")
                    elif task.state == "disabled":
                        status = self.tr("registry_status_unavailable") if task.registry_values else "disabled"
                    elif isinstance(item, dict) and any((s.get("status") == "access_denied") for s in (item.get("statuses") or [])):
                        status = self.tr("registry_status_access_denied")
                    else:
                        status = "action" if not task.registry_values else self.tr("registry_status_change_needed")
                    row.update_status(status)
                    row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
                row.control.update()
        finally:
            pass
        self.refresh_task_counts()
        self.log(self.tr("registry_status_refresh_ok"))
        log_action("status_sync_complete")
        log_qa_event("status_sync_complete", token=token, elapsed_ms=result.get("elapsed_ms"), async_worker=True)
        if getattr(self, "_status_sync_pending", False):
            self._status_sync_pending = False
            self.defer_status_sync(350)

    def selected_tasks(self, *, include_optimizer: bool = True) -> List[CleanerTask]:
        selected = []
        for key, row in self.rows.items():
            task = self.tasks[key]
            if row.selected() and (include_optimizer or task.category != "optimizer"):
                selected.append(task)
        return selected

    def clear_selection(self) -> None:
        self._programmatic_change = True
        self.setUpdatesEnabled(False)
        try:
            for row in self.rows.values():
                row.set_selected(False)
        finally:
            self.setUpdatesEnabled(True)
            self._programmatic_change = False
        try:
            self._estimate_cancel_event.set()
        except Exception:
            pass
        self.refresh_task_counts()
        self.log(self.tr("selected_reset_hint") if self.tr("selected_reset_hint") != "selected_reset_hint" else "Selection cleared.")

    def refresh_task_counts(self) -> None:
        selected_clean = len(self.selected_tasks(include_optimizer=False))
        selected_tweaks = len([t for t in self.selected_tasks(include_optimizer=True) if t.category == "optimizer"])
        if hasattr(self, "card_selected"):
            self.card_selected.set_value(str(selected_clean))
        if hasattr(self, "home_selected_metric"):
            self.home_selected_metric.metric_label.setText(str(selected_clean))  # type: ignore[attr-defined]
        if hasattr(self, "home_optimizer_metric"):
            self.home_optimizer_metric.metric_label.setText(f"{selected_tweaks} selected")  # type: ignore[attr-defined]

    def on_task_row_changed(self, key: str) -> None:
        if getattr(self, "_programmatic_change", False):
            return
        self.refresh_task_counts()
        task = self.tasks.get(key)
        row = self.rows.get(key)
        if not task or not row:
            return
        if task.category == "optimizer" and row.switch_mode:
            self.start_toggle_task(key, bool(row.control.isChecked()))
        else:
            self.schedule_selection_estimate()

    def schedule_selection_estimate(self) -> None:
        if getattr(self, "thread", None) is not None:
            return
        try:
            self._estimate_cancel_event.set()
        except Exception:
            pass
        self._estimate_cancel_event = threading.Event()
        self._estimate_token += 1
        self.estimate_timer.start(600)

    def start_selection_estimate(self) -> None:
        token = int(self._estimate_token)
        cancel_event = self._estimate_cancel_event
        tasks = [t for t in self.selected_tasks(include_optimizer=False) if t.kind == "directory" and self._task_paths(t)]
        if not tasks:
            self.estimate_bridge.finished.emit(token, 0)
            return
        def worker() -> None:
            total = 0
            self._estimate_active = True
            try:
                workers = min(2, get_adaptive_workers("scan", len(tasks)))
                log_qa_event("estimate_worker_start", token=token, tasks=len(tasks), workers=workers)
                with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = [executor.submit(SafeFS.fast_size_many_limited, self._task_paths(task), cancel_event, 2.5, 12000) for task in tasks]
                    for fut in concurrent.futures.as_completed(futures):
                        if cancel_event.is_set():
                            break
                        try:
                            total += int(fut.result() or 0)
                        except Exception:
                            pass
            finally:
                self._estimate_active = False
                if not cancel_event.is_set():
                    self.estimate_bridge.finished.emit(token, int(total))
                log_qa_event("estimate_worker_finish", token=token, cancelled=cancel_event.is_set(), total=int(total))
        threading.Thread(target=worker, name="FreeCleanerSelectionEstimate", daemon=True).start()

    def on_selection_estimate_ready(self, token: int, total: object) -> None:
        if token != self._estimate_token:
            return
        safe_total = self.safe_byte_count(total)
        self.analysis_total = safe_total
        if hasattr(self, "card_junk"):
            self.card_junk.set_value(self.human_mb(safe_total) if safe_total else "—")
        if hasattr(self, "result_label"):
            self.result_label.setText(f"Обрано до очищення: {self.human_mb(safe_total)}" if safe_total else (self.tr("freed_zero") if self.tr("freed_zero") != "freed_zero" else "Звільнено: 0.00 MB"))

    def row_base_enabled(self, row: TaskRow) -> bool:
        task = row.task
        admin_prompt_allowed = row.switch_mode and task.category == "optimizer"
        return bool(task.state != "disabled" and (not task.requires_admin or self.is_admin or admin_prompt_allowed))

    def rollback_toggle_control(self, row: TaskRow, value: bool) -> None:
        row.control.blockSignals(True)
        row.control.setChecked(bool(value))
        row.control.blockSignals(False)
        row.control.setEnabled(self.row_base_enabled(row) and row.task.key not in getattr(self, "toggle_jobs", {}) and not self.toggle_group_busy(row.task.key))
        row.set_selected_property(bool(value) and row.control.isEnabled())
        row.control.update()

    def toggle_action_group(self, key: str) -> str:
        # Power-plan actions target the same Windows power policy and must not
        # run on top of each other.  Independent registry/command toggles can run
        # in parallel; each still has its own row lock.
        if key in {"high_perf_plan", "safe_gaming_power_profile", "cpu_latency_power_profile", "ultimate_perf_plan"}:
            return "power-policy"
        if key == "disable_dynamic_tick_latency":
            return "boot-policy"
        task = self.tasks.get(key)
        if task and task.registry_values:
            first = task.registry_values[0]
            return f"registry:{first.key_path.casefold()}:{first.name.casefold()}"
        return f"toggle:{key}"

    def toggle_group_keys(self, group: str) -> List[str]:
        return [k for k, task in self.tasks.items() if task.category == "optimizer" and self.toggle_action_group(k) == group]

    def toggle_group_cooling(self, group: str) -> bool:
        until = float(getattr(self, "_toggle_group_cooldown_until", {}).get(group, 0.0) or 0.0)
        return time.monotonic() < until

    def toggle_group_busy(self, key: str) -> bool:
        group = self.toggle_action_group(key)
        if self.toggle_group_cooling(group):
            return True
        return any(other != key and self.toggle_action_group(other) == group for other in getattr(self, "toggle_jobs", {}))

    def refresh_optimizer_interactivity(self) -> None:
        for row in getattr(self, "rows", {}).values():
            if row.task.category != "optimizer":
                continue
            group_busy = self.toggle_group_busy(row.task.key)
            own_busy = row.task.key in getattr(self, "toggle_jobs", {})
            enabled = self.row_base_enabled(row) and not group_busy and not own_busy
            row.control.setEnabled(enabled)
            row.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
            row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
            row.control.update()

    def mark_toggle_group_cooldown(self, key: str, ms: Optional[int] = None) -> None:
        group = self.toggle_action_group(key)
        cooldown_ms = int(ms if ms is not None else getattr(self, "_toggle_group_cooldown_ms", 1200))
        until = time.monotonic() + max(0.0, cooldown_ms / 1000.0)
        self._toggle_group_cooldown_until[group] = max(float(self._toggle_group_cooldown_until.get(group, 0.0) or 0.0), until)
        log_qa_event("toggle_group_cooldown", key=key, group=group, cooldown_ms=cooldown_ms)
        self.refresh_optimizer_interactivity()
        QTimer.singleShot(cooldown_ms + 50, self.refresh_optimizer_interactivity)

    def run_toggle_worker(self, key: str, fn: Callable[[Callable[[int, str], None]], Dict[str, Any]]) -> None:
        if key in self.toggle_jobs:
            log_qa_event("toggle_worker_duplicate_blocked", key=key, active=list(self.toggle_jobs.keys()))
            self.show_toast(self.tr("toggle_busy"), "warning")
            return
        log_qa_event("toggle_worker_create", key=key, group=self.toggle_action_group(key), active=list(self.toggle_jobs.keys()))
        thread = QThread()
        worker = Worker(fn)
        worker.moveToThread(thread)
        self.toggle_jobs[key] = (thread, worker)
        self.mark_toggle_group_cooldown(key, 600)
        thread.started.connect(worker.run)
        worker._fc_kind = "toggle"
        worker._fc_key = key
        worker._fc_thread = thread
        worker.progress.connect(self.on_toggle_worker_progress_router, Qt.QueuedConnection)
        worker.finished.connect(self.on_toggle_worker_finished_router, Qt.QueuedConnection)
        worker.failed.connect(self.on_toggle_worker_failed_router, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()
        log_qa_event("toggle_worker_started", key=key, thread_object=str(thread))


    def on_toggle_worker_progress_router(self, percent: int, text: str) -> None:
        worker = self.sender()
        key = str(getattr(worker, "_fc_key", "") or "")
        self.worker_bridge.toggle_progress.emit(key, int(percent), str(text or ""))

    def on_toggle_worker_finished_router(self, result: Dict[str, Any]) -> None:
        worker = self.sender()
        key = str(getattr(worker, "_fc_key", "") or "")
        thread = getattr(worker, "_fc_thread", None)
        self.worker_bridge.toggle_finished.emit(key, result or {}, thread, worker)

    def on_toggle_worker_failed_router(self, error: str) -> None:
        worker = self.sender()
        key = str(getattr(worker, "_fc_key", "") or "")
        thread = getattr(worker, "_fc_thread", None)
        self.worker_bridge.toggle_failed.emit(key, str(error or ""), thread, worker)

    def on_background_worker_progress_router(self, percent: int, text: str) -> None:
        self.worker_bridge.background_progress.emit(int(percent), str(text or ""))

    def on_background_worker_finished_router(self, result: Dict[str, Any]) -> None:
        worker = self.sender()
        thread = getattr(worker, "_fc_thread", None)
        self.worker_bridge.background_finished.emit(result or {}, thread, worker)

    def on_background_worker_failed_router(self, error: str) -> None:
        worker = self.sender()
        thread = getattr(worker, "_fc_thread", None)
        self.worker_bridge.background_failed.emit(str(error or ""), thread, worker)

    def on_toggle_progress(self, key: str, percent: int, text: str) -> None:
        row = self.rows.get(key)
        if row:
            row.set_running(True)
        self.set_progress_value(percent, animated=True)
        if text:
            self.log(text)
        log_qa_event("toggle_progress", key=key, percent=percent, text=text)

    def on_toggle_finished(self, key: str, result: Dict[str, Any], thread: QThread, worker: Worker) -> None:
        self.toggle_jobs.pop(key, None)
        self.mark_toggle_group_cooldown(key)
        log_qa_event("toggle_finished", key=key, result=result, remaining=list(self.toggle_jobs.keys()))
        row = self.rows.get(key)
        task = self.tasks.get(key)
        ok = bool(result.get("ok"))
        requested_enabled = bool(result.get("enabled"))
        previous = bool(result.get("previous_state"))
        verified_state: Optional[bool] = None
        final_status = "ready"
        if row and task:
            row.set_running(False)
            row.control.setEnabled(self.row_base_enabled(row) and not self.toggle_group_busy(key))
            if ok and not task.instant_action:
                # Do not run any registry/powercfg/BCDEdit verification on the GUI
                # thread.  The async status worker will verify and repaint shortly
                # after.  This keeps the click handler constant-time.
                self.invalidate_system_status_cache()
                verified_state = None
            row.control.blockSignals(True)
            if task.instant_action:
                row.control.setChecked(False)
                final_status = "ready" if ok else self.status_for_task(task)
            elif verified_state is not None:
                row.control.setChecked(bool(verified_state))
                final_status = self.tr("registry_status_done") if verified_state else self.tr("registry_status_change_needed")
            elif ok:
                row.control.setChecked(requested_enabled)
                final_status = self.tr("registry_status_done") if requested_enabled else self.tr("registry_status_change_needed")
            else:
                row.control.setChecked(previous)
                final_status = self.status_for_task(task)
            row.control.blockSignals(False)
            row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
            row.update_status(final_status)
            row.control.update()
        self.invalidate_system_status_cache()
        self.refresh_task_counts()
        self.refresh_backup_state()
        log_action({"toggle": key, "ok": ok, "requested_enabled": requested_enabled, "verified": verified_state})
        self.show_toast("Тумблер застосовано" if ok else "Не вдалося застосувати тумблер", "success" if ok else "error")
        self.refresh_optimizer_interactivity()
        # Let QThread.quit()/deleteLater and power policy broadcasts settle before a full status probe.
        self.defer_status_sync(1400)

    def on_toggle_failed(self, key: str, error: str, thread: QThread, worker: Worker) -> None:
        self.toggle_jobs.pop(key, None)
        self.mark_toggle_group_cooldown(key)
        log_qa_event("toggle_failed", key=key, error=error, remaining=list(self.toggle_jobs.keys()))
        row = self.rows.get(key)
        if row:
            row.set_running(False)
            row.control.setEnabled(self.row_base_enabled(row) and not self.toggle_group_busy(key))
            row.update_status(self.status_for_task(row.task))
            row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
            row.control.update()
        self.log(error)
        log_error(f"toggle failed: {key}\n{error}")
        self.show_toast(self.tr("toggle_error_details"), "error")
        self.refresh_optimizer_interactivity()
        self.defer_status_sync(1400)

    def start_toggle_task(self, key: str, enable: bool) -> None:
        task = self.tasks.get(key)
        row = self.rows.get(key)
        if not task or not row:
            log_qa_event("toggle_start_missing_row_or_task", key=key, enable=enable)
            return
        previous_state = not bool(enable)
        log_qa_event("toggle_requested", key=key, enable=bool(enable), previous_state=previous_state, admin=self.is_admin, state=task.state)
        if key in getattr(self, "toggle_jobs", {}):
            self.rollback_toggle_control(row, previous_state)
            self.show_toast(self.tr("toggle_busy"), "warning")
            return
        if self.toggle_group_busy(key):
            self.rollback_toggle_control(row, previous_state)
            self.refresh_optimizer_interactivity()
            self.show_toast(self.tr("toggle_group_busy"), "warning")
            return
        if task.requires_admin and not self.is_admin:
            self.rollback_toggle_control(row, previous_state)
            row.update_status(self.tr("registry_status_admin_only"))
            log_action({"toggle_blocked_admin_required": key})
            self.show_toast(self.tr("admin_required_short"), "warning")
            return
        if task.state == "disabled":
            self.rollback_toggle_control(row, previous_state)
            self.show_toast(self.tr("tweak_unavailable_system"), "warning")
            return
        specs = task.registry_values if enable else self.revert_registry_specs.get(key)
        command = task.command if enable else self.revert_commands.get(key)
        if not enable and not specs and not command:
            self.rollback_toggle_control(row, previous_state)
            self.show_toast(self.tr("toggle_no_safe_off"), "warning")
            self.defer_status_sync(0)
            return
        title, _ = self.task_text(task)
        log_action({"toggle_start": key, "enable": bool(enable), "group": self.toggle_action_group(key)})
        row.set_running(True)
        row.control.setEnabled(False)
        row.control.update()

        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(5, f"{title}: {'ON' if enable else 'OFF'}")
            reg_keys = self.registry_keys_for_specs(specs or [])
            if reg_keys:
                backup = WindowsOps.backup_registry_keys(reg_keys)
                emit(18, self.trf("registry_backup_created", path=backup) if backup else self.tr("registry_backup_failed"))
                if not backup:
                    return {"op": "toggle", "toggle_key": key, "ok": False, "enabled": enable, "previous_state": previous_state}
            ok = True
            if specs:
                ok = all(WindowsOps.apply_registry_values(specs) or [False])
            elif command:
                result = command()
                ok = bool(result) if isinstance(result, bool) else True
            emit(100, f"{title}: {'OK' if ok else 'FAIL'}")
            return {
                "op": "toggle",
                "toggle_key": key,
                "ok": bool(ok),
                "enabled": enable,
                "previous_state": previous_state,
                "momentary": bool(task.instant_action),
            }

        self.run_toggle_worker(key, job)

    def apply_search(self) -> None:
        query = self.search.text().strip() if hasattr(self, "search") else ""
        self.apply_task_search(query, lambda key: key.startswith("clean_"))

    def apply_optimizer_search(self) -> None:
        query = self.optimizer_search.text().strip() if hasattr(self, "optimizer_search") else ""
        self.apply_task_search(query, lambda key: key.startswith("opt_"))

    def apply_task_search(self, query: str, section_filter: Callable[[str], bool]) -> None:
        for section in self.sections.values():
            if not section_filter(section.key):
                continue
            visible = False
            for row in section.rows:
                match = row.matches(query)
                UiFx.set_visible(row, match, animated=True, duration=120)
                visible = visible or match
            UiFx.set_visible(section.container, visible or not query, animated=True, duration=130)

    def _task_paths(self, task: CleanerTask) -> List[str]:
        paths: List[str] = []
        if task.paths:
            paths.extend(task.paths)
        elif task.path:
            paths.append(task.path)
        return PathFinder.unique_existing(paths)

    @staticmethod
    def safe_byte_count(value: object) -> int:
        try:
            parsed = int(value or 0)
        except Exception:
            return 0
        return max(0, parsed)

    @classmethod
    def human_mb(cls, value: object) -> str:
        safe_value = cls.safe_byte_count(value)
        return f"{safe_value / (1024 * 1024):.2f} MB"

    def _tick_progress_animation(self) -> None:
        if not hasattr(self, "progress"):
            return
        target = max(0, min(100, int(getattr(self, "_progress_target_value", self.progress.value()))))
        current = int(self.progress.value())
        if current == target:
            try:
                self._progress_anim_timer.stop()
            except Exception:
                pass
            return
        diff = target - current
        step = max(1, abs(diff) // 4)
        self.progress.setValue(current + (step if diff > 0 else -step))

    def set_progress_value(self, value: int, *, animated: bool = True) -> None:
        if not hasattr(self, "progress"):
            return
        target = max(0, min(100, int(value)))
        if not animated or not hasattr(self, "_progress_anim_timer"):
            self._progress_target_value = target
            self.progress.setValue(target)
            return
        self._progress_target_value = target
        if not self._progress_anim_timer.isActive():
            self._progress_anim_timer.start()

    def log(self, text: str) -> None:
        line = str(text or "").strip()
        if not line:
            return
        log_app(line)
        if self.setting_bool("compact_event_log", True) and ("'run_args':" in line or '"command": [' in line):
            return
        if hasattr(self, "log_box"):
            self.log_box.append(line)
        else:
            # Avoid printing during normal GUI/source startup; logs are written
            # to %LOCALAPPDATA%/FreeCleaner/logs/app.log instead.
            pass

    def set_busy(self, busy: bool) -> None:
        for btn in (
            getattr(self, "run_btn", None), getattr(self, "scan_btn", None), getattr(self, "reset_btn", None),
            getattr(self, "refresh_registry_btn", None),
        ):
            if btn:
                btn.setEnabled(not busy)
        for row in getattr(self, "rows", {}).values():
            admin_prompt_allowed = row.switch_mode and row.task.category == "optimizer"
            base_enabled = row.task.state != "disabled" and (not row.task.requires_admin or self.is_admin or admin_prompt_allowed)
            group_busy = row.task.category == "optimizer" and self.toggle_group_busy(row.task.key)
            row_busy = bool(busy and row.task.category != "optimizer") or row.task.key in getattr(self, "toggle_jobs", {}) or group_busy
            row.control.setEnabled(base_enabled and not row_busy)
            row.setCursor(Qt.PointingHandCursor if base_enabled and not row_busy else Qt.ArrowCursor)
        if not busy:
            # Repaint rows after transient busy-disable so they do not stay grey.
            for row in getattr(self, "rows", {}).values():
                if row.task.category == "optimizer" and row.task.key not in getattr(self, "toggle_jobs", {}) and not self.toggle_group_busy(row.task.key):
                    row.update_status(self.status_for_task(row.task))

    def on_background_progress(self, _percent: int, text: str) -> None:
        payload_text = str(text or "")
        if payload_text.startswith(UPDATE_PROGRESS_PREFIX):
            self.handle_update_progress_payload(payload_text[len(UPDATE_PROGRESS_PREFIX):])
            return
        if text:
            self.log(payload_text)

    def handle_update_progress_payload(self, payload_text: str) -> None:
        try:
            payload = json.loads(payload_text or "{}")
        except Exception:
            return
        dlg = getattr(self, "_update_progress_dialog", None) or getattr(self, "_update_dialog", None)
        if dlg is not None:
            try:
                dlg.update_progress_payload(payload)
            except Exception as exc:
                log_qa_event("update_dialog_progress_failed", error=str(exc))
        try:
            stage = str(payload.get("stage") or "")
            if stage and stage not in {"downloading"}:
                self.log(str(payload.get("message") or stage))
        except Exception:
            pass

    def cancel_update_download(self) -> None:
        event = getattr(self, "_update_download_cancel_event", None)
        if event is not None:
            event.set()
            self.log("Скасування завантаження оновлення…")

    def run_background_worker(self, fn: Callable[[Callable[[int, str], None]], Dict[str, Any]]) -> None:
        """Run lightweight background jobs without locking the cleaner UI."""
        limit = max(1, int(getattr(self, "_max_background_jobs", 2) or 2))
        if len(getattr(self, "background_jobs", [])) >= limit:
            self.show_toast(self.tr("background_diagnostics_busy"), "warning")
            log_qa_event("background_worker_limit_blocked", active=len(getattr(self, "background_jobs", [])), limit=limit)
            return
        thread = QThread()
        worker = Worker(fn)
        worker.moveToThread(thread)
        self.background_jobs.append((thread, worker))
        thread.started.connect(worker.run)
        worker._fc_kind = "background"
        worker._fc_thread = thread
        worker.progress.connect(self.on_background_worker_progress_router, Qt.QueuedConnection)
        worker.finished.connect(self.on_background_worker_finished_router, Qt.QueuedConnection)
        worker.failed.connect(self.on_background_worker_failed_router, Qt.QueuedConnection)
        worker.finished.connect(thread.quit)
        worker.failed.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def on_background_worker_finished(self, result: Dict[str, Any], thread: QThread, worker: Worker) -> None:
        try:
            if (thread, worker) in self.background_jobs:
                self.background_jobs.remove((thread, worker))
        except Exception:
            pass
        op = str(result.get("op") or "")
        if op == "update":
            self._update_check_running = False
            if result.get("failed"):
                self.log(self.tr("update_check_failed"))
                if self.setting_bool("notify_on_finish", True):
                    self.show_toast(self.tr("update_check_failed"), "warning")
            elif result.get("available"):
                latest = str(result.get("latest") or "")
                self.log(self.trf("update_available_log", current=APP_VERSION, latest=latest))
                if self.setting_bool("notify_on_finish", True):
                    self.show_toast(f"Доступне оновлення: {latest}", "info")
                self.show_update_dialog(result)
            else:
                text = "FreeCleaner актуальний"
                if result.get("newer_local"):
                    text = "Локальна збірка новіша за останній GitHub release"
                self.log(text)
                if self.setting_bool("notify_on_finish", True):
                    self.show_toast(text, "info")
        elif op == "update_download":
            self._update_download_running = False
            self._update_download_cancel_event = None
            ok = bool(result.get("ok"))
            path = str(result.get("path") or "")
            message = str(result.get("message") or "")
            dlg = getattr(self, "_update_progress_dialog", None)
            if ok:
                if dlg is not None:
                    dlg.set_done(path)
                self.log(self.trf("update_install_started", path=path))
                self.show_toast(self.tr("update_install_started_button"), "success")
                if IS_WINDOWS:
                    QTimer.singleShot(1800, QApplication.quit)
            else:
                if dlg is not None:
                    if result.get("cancelled"):
                        dlg.set_failed("Завантаження оновлення скасовано.")
                    else:
                        dlg.set_failed(self.trf("update_download_failed_reason", reason=message))
                self.log(self.trf("update_download_failed_reason", reason=message))
                self.show_toast(self.tr("update_download_cancelled") if result.get("cancelled") else self.tr("update_download_failed"), "warning" if result.get("cancelled") else "error")
        elif op == "registry_backup":
            path = str(result.get("path") or "")
            if path:
                self.log(self.trf("manual_registry_backup_ok", path=path))
                self.refresh_backup_state()
                self.show_toast("Registry backup створено", "success")
            else:
                self.show_toast(self.tr("manual_registry_backup_fail"), "error")
        elif op == "registry_restore":
            ok = bool(result.get("ok"))
            name = str(result.get("name") or "backup")
            self.log(self.trf("registry_restore_ok" if ok else "registry_restore_fail", name=name))
            self.refresh_backup_state()
            self.sync_registry_toggle_states()
            self.show_toast("Registry restore завершено" if ok else "Registry restore не вдався", "success" if ok else "error")
        elif op == "diagnostic_report":
            title = str(result.get("title") or "Diagnostic report")
            report = result.get("report") or {}
            self.log(f"{title}:")
            if isinstance(report, dict):
                for key, value in report.items():
                    self.log(f"  {key}: {value}")
            else:
                self.log(str(report))
            card = result.get("card")
            try:
                if hasattr(self, "diagnostic_cards") and card is not None:
                    self.diagnostic_cards[int(card)].set_status("done", "Blue")
            except Exception:
                pass
            toast = str(result.get("toast") or "Діагностику завершено")
            self.show_toast(toast, "info")

    def on_background_worker_failed(self, error: str, thread: QThread, worker: Worker) -> None:
        try:
            if (thread, worker) in self.background_jobs:
                self.background_jobs.remove((thread, worker))
        except Exception:
            pass
        self._update_check_running = False
        self._update_download_running = False
        self._update_dialog: Optional[UpdateDialog] = None
        self._update_progress_dialog: Optional[UpdateDialog] = None
        self._update_download_cancel_event: Optional[threading.Event] = None
        self.log(f"Background job failed: {error}")
        if hasattr(self, "toast"):
            self.show_toast(self.tr("background_action_failed"), "error")

    def run_worker(self, fn: Callable[[Callable[[int, str], None]], Dict[str, Any]]) -> None:
        if self.thread is not None:
            self.show_toast(self.tr("wait_current_action"), "warning")
            return
        self.cancel_event.clear()
        self.set_progress_value(0, animated=False)
        self.set_busy(True)
        self.thread = QThread()
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.on_worker_progress, Qt.QueuedConnection)
        self.worker.finished.connect(self.on_worker_finished, Qt.QueuedConnection)
        self.worker.failed.connect(self.on_worker_failed, Qt.QueuedConnection)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.thread.finished.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.thread.finished.connect(self.on_main_worker_thread_finished, Qt.QueuedConnection)
        self.thread.start()

    def on_main_worker_thread_finished(self) -> None:
        # This slot belongs to the QMainWindow, so Qt queues it to the GUI thread.
        # Avoid Python lambdas connected to QThread.finished because PySide can run
        # them on the wrong side in edge cases.
        self.thread = None
        self.worker = None
        self.set_busy(False)
        self.defer_status_sync(0)

    def on_worker_progress(self, percent: int, text: str) -> None:
        self.set_progress_value(percent, animated=True)
        if text:
            self.log(text)

    def on_worker_finished(self, result: Dict[str, Any]) -> None:
        op = str(result.get("op") or "")
        total = self.safe_byte_count(result.get("total", self.analysis_total))
        if op == "toggle":
            key = str(result.get("toggle_key") or "")
            row = self.rows.get(key)
            task = self.tasks.get(key)
            if row and result.get("momentary"):
                row.control.blockSignals(True)
                row.control.setChecked(False)
                row.control.blockSignals(False)
            if row and task and not task.registry_values:
                row.update_status("applied" if result.get("enabled") and result.get("ok") else "ready")
        elif op != "update":
            self.analysis_total = total
            if hasattr(self, "card_junk"):
                self.card_junk.set_value(self.human_mb(total) if total else "—")
            if "freed" in result:
                self.freed_bytes = self.safe_byte_count(result.get("freed"))
                selected_before = self.safe_byte_count(result.get("selected_before", total))
                self.result_label.setText(f"Звільнено: {self.human_mb(self.freed_bytes)} • Було обрано: {self.human_mb(selected_before)}")
            else:
                self.result_label.setText(f"Знайдено: {self.human_mb(total)}")
        self.set_progress_value(100, animated=True)
        for key in getattr(self, "_cleaning_keys", []):
            row = self.rows.get(key)
            if row:
                row.update_status(self.status_for_task(row.task))
        self.restore_cleaning_selection()
        self._cleaning_keys = []
        if hasattr(self, "toast") and self.setting_bool("notify_on_finish", True):
            if op == "update":
                self.show_toast("Перевірка оновлень завершена", "info")
            elif op == "toggle":
                self.show_toast("Тумблер застосовано" if result.get("ok") else "Не вдалося застосувати тумблер", "success" if result.get("ok") else "error")
            elif "tweaks" in result:
                self.show_toast(f"Застосовано твікiв: {int(result.get('tweaks') or 0)}", "success")
            elif "freed" in result:
                self.show_toast(f"Очищення завершено: {self.human_mb(self.freed_bytes)}", "success")
            else:
                self.show_toast(f"Аналіз завершено: {self.human_mb(total)}", "info")
        self.refresh_backup_state()
        self.refresh_system_drive_status()

    def on_worker_failed(self, error: str) -> None:
        QMessageBox.critical(self, "FreeCleaner", error)
        self.log(error)
        for key in getattr(self, "_cleaning_keys", []):
            row = self.rows.get(key)
            if row:
                row.update_status(self.status_for_task(row.task))
        self.restore_cleaning_selection()
        self._cleaning_keys = []
        self.set_progress_value(0, animated=True)
        if hasattr(self, "toast"):
            self.show_toast(self.tr("action_failed_details"), "error")
        self.defer_status_sync(0)


    def restore_cleaning_selection(self) -> None:
        keys = set(getattr(self, "_pre_clean_selected_keys", set()) or set())
        if not keys:
            return
        self._programmatic_change = True
        self.setUpdatesEnabled(False)
        try:
            for key in keys:
                row = self.rows.get(key)
                if not row:
                    continue
                row.set_running(False)
                if row.control.isEnabled():
                    row.control.blockSignals(True)
                    row.control.setChecked(True)
                    row.control.blockSignals(False)
                row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
        finally:
            self.setUpdatesEnabled(True)
            self._programmatic_change = False
        self.refresh_task_counts()

    def start_analysis(self) -> None:
        tasks = [t for t in self.selected_tasks(include_optimizer=False) if t.kind == "directory" and self._task_paths(t)]
        if not tasks:
            QMessageBox.information(self, "FreeCleaner", self.tr("nothing_selected"))
            return
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            total = 0
            count = len(tasks)
            workers = get_adaptive_workers("scan", SCAN_WORKERS)
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {executor.submit(SafeFS.fast_size_many, self._task_paths(task), self.cancel_event): task for task in tasks}
                for idx, fut in enumerate(concurrent.futures.as_completed(future_map), start=1):
                    task = future_map[fut]
                    try:
                        size = int(fut.result() or 0)
                    except Exception:
                        size = 0
                    total += size
                    title, _ = self.task_text(task)
                    emit(int(idx / count * 100), f"{title}: {self.human_mb(size)}")
            return {"total": total, "op": "analysis"}
        self.run_worker(job)

    def start_clean(self) -> None:
        tasks = self.selected_tasks(include_optimizer=False)
        if not tasks:
            QMessageBox.information(self, "FreeCleaner", self.tr("nothing_selected"))
            return
        if self.setting_bool("confirm_heavy_actions", True) and any(t.danger == "heavy" for t in tasks):
            if QMessageBox.question(self, self.tr("confirm_heavy_title"), self.tr("confirm_heavy_message")) != QMessageBox.Yes:
                return
        self._cleaning_keys = [t.key for t in tasks]
        self._pre_clean_selected_keys = set(self._cleaning_keys)
        self._pre_clean_selected_bytes = self.safe_byte_count(getattr(self, "analysis_total", 0))
        for task in tasks:
            row = self.rows.get(task.key)
            if row:
                # Keep the user's selected checkboxes as-is.  Running state is a
                # visual overlay only; selection must survive the cleanup pass.
                row.set_selected_property(row.control.isChecked() and row.control.isEnabled())
                row.set_running(True)
        if hasattr(self, "result_label"):
            self.result_label.setText(f"Очищення... Обрано: {self.human_mb(self._pre_clean_selected_bytes)}")
        self.refresh_task_counts()
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            total_before = 0
            freed = 0
            dir_tasks = [t for t in tasks if t.kind == "directory" and self._task_paths(t)]
            cmd_tasks = [t for t in tasks if t.kind != "directory"]
            workers = get_adaptive_workers("scan", SCAN_WORKERS)
            emit(1, f"Аналіз: {len(dir_tasks)} modules")
            task_sizes: Dict[str, int] = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                future_map = {executor.submit(SafeFS.fast_size_many, self._task_paths(task), self.cancel_event): task for task in dir_tasks}
                for fut in concurrent.futures.as_completed(future_map):
                    task = future_map[fut]
                    try:
                        size = self.safe_byte_count(fut.result())
                    except Exception:
                        size = 0
                    task_sizes[task.key] = size
                    total_before += size
            if total_before:
                emit(12, f"Знайдено: {self.human_mb(total_before)}")
            # backup registry before optimizer registry tweaks
            reg_keys: List[str] = []
            for task in cmd_tasks:
                for key in task.registry_keys or []:
                    if key not in reg_keys:
                        reg_keys.append(key)
            if reg_keys:
                backup = WindowsOps.backup_registry_keys(reg_keys)
                emit(15, self.trf("registry_backup_created", path=backup) if backup else self.tr("registry_backup_failed"))
                if not backup:
                    return {"total": total_before, "freed": 0, "selected_before": getattr(self, "_pre_clean_selected_bytes", total_before), "op": "clean"}
            clean_workers = get_adaptive_workers("clean", CLEAN_WORKERS)
            step_base = 20
            count = max(1, len(dir_tasks))
            for idx, task in enumerate(dir_tasks, start=1):
                paths = self._task_paths(task)
                title, _ = self.task_text(task)
                task_before = self.safe_byte_count(task_sizes.get(task.key, 0))
                task_removed_live = 0
                last_emit = 0.0
                start_percent = step_base + int((idx - 1) / count * 58)
                end_percent = step_base + int(idx / count * 58)

                def on_removed(chunk: int, *, _title: str = title, _before: int = task_before, _start: int = start_percent, _end: int = end_percent) -> None:
                    nonlocal task_removed_live, last_emit
                    task_removed_live += self.safe_byte_count(chunk)
                    now = time.monotonic()
                    if now - last_emit < 0.16 and task_removed_live < _before:
                        return
                    last_emit = now
                    if _before > 0:
                        ratio = min(1.0, task_removed_live / max(1, _before))
                        percent = _start + int((_end - _start) * ratio)
                        emit(percent, f"{_title}: {self.human_mb(task_removed_live)} / {self.human_mb(_before)}")

                result = SafeFS.clean_many(paths, on_removed, self.cancel_event)
                removed = self.safe_byte_count(result.get("removed_bytes", 0))
                freed += removed
                skipped = int(result.get("skipped_busy", 0) or 0)
                scheduled = int(result.get("scheduled_reboot", 0) or 0)
                suffix = ""
                if skipped or scheduled:
                    suffix = f" • skipped busy: {skipped}" + (f" • reboot: {scheduled}" if scheduled else "")
                emit(end_percent, f"{title}: {self.human_mb(removed)}{suffix}")
            for idx, task in enumerate(cmd_tasks, start=1):
                title, _ = self.task_text(task)
                ok = True
                if task.registry_values:
                    statuses = WindowsOps.registry_statuses(task.registry_values)
                    if statuses and all(s.get("matches") for s in statuses):
                        ok = True
                        emit(80 + int(idx / max(1, len(cmd_tasks)) * 18), f"{title}: already applied")
                        continue
                    ok = all(WindowsOps.apply_registry_values(task.registry_values) or [False])
                elif task.command:
                    res = task.command()
                    ok = bool(res) if isinstance(res, bool) else True
                emit(80 + int(idx / max(1, len(cmd_tasks)) * 18), f"{title}: {'OK' if ok else 'FAIL'}")
            return {"total": total_before, "freed": max(0, int(freed or 0)), "selected_before": getattr(self, "_pre_clean_selected_bytes", total_before), "op": "clean"}
        self.run_worker(job)

    def start_apply_tweaks(self) -> None:
        tasks = [t for t in self.selected_tasks(include_optimizer=True) if t.category == "optimizer" and t.kind != "directory"]
        if not tasks:
            QMessageBox.information(self, "FreeCleaner", self.tr("nothing_selected"))
            return
        if self.setting_bool("confirm_heavy_actions", True) and any(t.danger == "heavy" for t in tasks):
            if QMessageBox.question(self, self.tr("confirm_heavy_title"), self.tr("confirm_heavy_message")) != QMessageBox.Yes:
                return

        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            reg_keys: List[str] = []
            for task in tasks:
                for key in task.registry_keys or []:
                    if key not in reg_keys:
                        reg_keys.append(key)
            if reg_keys:
                backup = WindowsOps.backup_registry_keys(reg_keys)
                emit(10, self.trf("registry_backup_created", path=backup) if backup else self.tr("registry_backup_failed"))
                if not backup:
                    return {"total": self.analysis_total, "freed": 0, "op": "tweaks"}
            count = max(1, len(tasks))
            for idx, task in enumerate(tasks, start=1):
                title, _ = self.task_text(task)
                ok = True
                if task.registry_values:
                    statuses = WindowsOps.registry_statuses(task.registry_values)
                    if statuses and all(s.get("matches") for s in statuses):
                        emit(10 + int(idx / count * 88), f"{title}: already applied")
                        continue
                    ok = all(WindowsOps.apply_registry_values(task.registry_values) or [False])
                elif task.command:
                    res = task.command()
                    ok = bool(res) if isinstance(res, bool) else True
                emit(10 + int(idx / count * 88), f"{title}: {'OK' if ok else 'FAIL'}")
            return {"total": self.analysis_total, "freed": 0, "tweaks": len(tasks), "op": "tweaks"}

        self.run_worker(job)

    # ------------------------- registry/settings/actions -------------------------
    def collect_registry_keys(self) -> List[str]:
        keys: List[str] = []
        for task in self.tasks.values():
            for key in task.registry_keys or []:
                if key not in keys:
                    keys.append(key)
        return keys

    def manual_registry_backup(self) -> None:
        keys = self.collect_registry_keys()
        if not keys:
            QMessageBox.information(self, "FreeCleaner", self.tr("manual_registry_backup_empty"))
            return
        self.log("Registry backup: creating...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, "Registry backup: creating...")
            path = WindowsOps.backup_registry_keys(keys)
            emit(100, "Registry backup: done" if path else "Registry backup: failed")
            return {"op": "registry_backup", "path": path or ""}
        self.run_background_worker(job)

    def refresh_backup_state(self) -> None:
        if not hasattr(self, "backup_list"):
            return
        self.backup_list.clear()
        backups = WindowsOps.list_registry_backups()
        for backup in backups:
            row = QListWidgetItem(f"{backup.get('created')} • {backup.get('name')} • {backup.get('count')} .reg")
            row.setData(Qt.UserRole, dict(backup))
            row.setToolTip(str(backup.get("path") or ""))
            self.backup_list.addItem(row)
        if hasattr(self, "home_backup_metric"):
            self.home_backup_metric.metric_label.setText(str(len(backups)))  # type: ignore[attr-defined]

    def _selected_registry_backup(self, item: Optional[QListWidgetItem] = None) -> Optional[Dict[str, Any]]:
        if item is None and hasattr(self, "backup_list"):
            item = self.backup_list.currentItem()
        if item is not None:
            data = item.data(Qt.UserRole)
            if isinstance(data, dict):
                return dict(data)
        backups = WindowsOps.list_registry_backups()
        if not backups:
            return None
        row = self.backup_list.currentRow() if hasattr(self, "backup_list") else 0
        row = row if 0 <= row < len(backups) else 0
        return dict(backups[row])

    def _confirm_registry_restore(self, backup: Dict[str, Any], *, latest: bool = False) -> bool:
        title = "Відновити найновішу резервну копію?" if latest else "Відновити цю резервну копію?"
        details = (
            f"{title}\n\n"
            f"Дата: {backup.get('created')}\n"
            f"Папка: {backup.get('name')}\n"
            f"Файлів: {backup.get('count')} .reg\n\n"
            "Перед імпортом FreeCleaner створить pre-restore snapshot, щоб можна було відкотити відновлення."
        )
        return QMessageBox.question(self, "FreeCleaner", details) == QMessageBox.Yes

    def _start_registry_restore(self, backup: Dict[str, Any], *, latest: bool = False) -> None:
        if not backup:
            QMessageBox.information(self, "FreeCleaner", self.tr("registry_restore_missing"))
            return
        if not self.is_admin:
            QMessageBox.warning(self, "FreeCleaner", self.tr("restore_registry_admin_required"))
            return
        if not self._confirm_registry_restore(backup, latest=latest):
            return
        backup_path = str(backup.get("path") or "")
        backup_name = str(backup.get("name") or "backup")
        if not backup_path:
            QMessageBox.warning(self, "FreeCleaner", self.tr("registry_restore_missing"))
            return
        self.log(f"Registry restore: {backup_name}...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, f"Registry restore: {backup_name}...")
            ok = WindowsOps.restore_registry_backup_dir(backup_path)
            emit(100, "Registry restore: done" if ok else "Registry restore: failed")
            return {"op": "registry_restore", "ok": bool(ok), "name": backup_name}
        self.run_background_worker(job)

    def restore_latest_registry_backup(self) -> None:
        backups = WindowsOps.list_registry_backups()
        if not backups:
            QMessageBox.information(self, "FreeCleaner", self.tr("registry_restore_missing"))
            return
        self._start_registry_restore(dict(backups[0]), latest=True)

    def restore_registry_backup_item(self, item: QListWidgetItem) -> None:
        backup = self._selected_registry_backup(item)
        if backup:
            self._start_registry_restore(backup)

    def open_restore_dialog(self) -> None:
        backup = self._selected_registry_backup()
        if not backup:
            QMessageBox.information(self, "FreeCleaner", self.tr("registry_restore_missing"))
            return
        self._start_registry_restore(backup)

    def _trash_menu_icon(self) -> QIcon:
        pix = QPixmap(18, 18)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        try:
            color = QColor(178, 75, 75)
            painter.setPen(QPen(color, 1.7))
            painter.drawLine(5, 6, 13, 6)
            painter.drawLine(7, 4, 11, 4)
            painter.drawRect(6, 7, 6, 8)
            painter.drawLine(8, 9, 8, 14)
            painter.drawLine(10, 9, 10, 14)
        finally:
            painter.end()
        return QIcon(pix)

    def _open_registry_backup_location(self, backup: Dict[str, Any]) -> None:
        path = os.path.abspath(str(backup.get("path") or ""))
        if path and os.path.isdir(path):
            WindowsOps.open_in_file_manager(path)
            self.log(f"Registry backup location opened: {path}")
        else:
            QMessageBox.warning(self, "FreeCleaner", self.tr("registry_restore_missing"))

    def _delete_registry_backup(self, backup: Dict[str, Any]) -> None:
        path = os.path.abspath(str(backup.get("path") or ""))
        root = os.path.abspath(WindowsOps.registry_backup_root())
        name = str(backup.get("name") or os.path.basename(path) or "backup")
        try:
            if not path or not os.path.isdir(path) or os.path.commonpath([root, path]) != root or path == root:
                raise ValueError("unsafe backup path")
        except Exception:
            QMessageBox.warning(self, "FreeCleaner", "Неможливо безпечно видалити цю резервну копію.")
            return
        text = (
            "Видалити цю резервну копію?\n\n"
            f"{backup.get('created')} • {name}\n"
            f"Файлів: {backup.get('count')} .reg\n\n"
            "Буде видалено тільки цю конкретну папку backup з її файлами."
        )
        if QMessageBox.question(self, "FreeCleaner", text) != QMessageBox.Yes:
            return
        try:
            shutil.rmtree(path, ignore_errors=False)
            self.log(f"Registry backup deleted: {name}")
            self.refresh_backup_state()
            self.show_toast("Резервну копію видалено", "success")
        except Exception as exc:
            self.log(f"Registry backup delete failed: {name}: {exc}")
            self.show_toast("Не вдалося видалити резервну копію", "error")

    def show_registry_backup_context_menu(self, pos) -> None:
        if not hasattr(self, "backup_list"):
            return
        item = self.backup_list.itemAt(pos)
        if item is None:
            return
        self.backup_list.setCurrentItem(item)
        backup = self._selected_registry_backup(item)
        if not backup:
            return
        menu = QMenu(self.backup_list)
        menu.setStyleSheet("QMenu { background: #242524; color: #F4F4F4; border: 1px solid #3A3B3A; padding: 4px; } QMenu::item { padding: 7px 28px 7px 24px; } QMenu::item:selected { background: #303130; }")
        restore_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
        restore_action = QAction(restore_icon, self.tr("restore"), self)
        open_action = QAction(folder_icon, self.tr("open_location"), self)
        delete_action = QAction(self._trash_menu_icon(), self.tr("delete"), self)
        delete_action.setToolTip("Видаляє тільки вибрану папку backup з її файлами")
        menu.addAction(restore_action)
        menu.addAction(open_action)
        menu.addSeparator()
        menu.addAction(delete_action)
        chosen = menu.exec(self.backup_list.viewport().mapToGlobal(pos))
        if chosen == restore_action:
            self._start_registry_restore(backup)
        elif chosen == open_action:
            self._open_registry_backup_location(backup)
        elif chosen == delete_action:
            self._delete_registry_backup(backup)

    def setting_bool(self, key: str, default: bool = False) -> bool:
        value = self.config.get(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().casefold() in {"1", "true", "yes", "on", "enabled"}

    def set_setting_bool(self, key: str, value: bool) -> None:
        self.config[key] = bool(value)
        self.save_config()

    def setting_int(self, key: str, default: int = 0, *, minimum: int = 0, maximum: int = 999999) -> int:
        return self.setting_int_from_config(key, default, minimum=minimum, maximum=maximum)

    def set_setting_int(self, key: str, value: int) -> None:
        self.config[key] = int(value)
        self.save_config()

    def on_language_changed(self, index: int) -> None:
        if 0 <= index < len(self.lang_options):
            self.lang_preference = self.lang_options[index][0]
            self.config["language"] = self.lang_preference
            self.save_config()
            QMessageBox.information(self, "FreeCleaner", "Мова буде повністю оновлена після перезапуску програми.")

    def on_admin_switch_changed(self, state: int) -> None:
        if self.is_admin:
            return
        if state:
            self.admin_mode_switch.blockSignals(True)
            self.admin_mode_switch.setChecked(False)
            self.admin_mode_switch.blockSignals(False)
            self.restart_as_admin()

    def show_toast(self, text: str, tone: str = "success") -> None:
        log_app(f"toast[{tone}]: {text}")
        if hasattr(self, "toast"):
            self.toast.show_message(text, tone)

    def open_config_folder(self) -> None:
        folder = os.path.dirname(CONFIG_PATH) or get_user_data_dir(create=True)
        os.makedirs(folder, exist_ok=True)
        WindowsOps.open_in_file_manager(folder)

    def open_logs_folder(self) -> None:
        folder = get_logs_dir(create=True)
        WindowsOps.open_in_file_manager(folder)
        self.log(f"Logs folder: {folder}")

    def open_about(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle(self.tr("about_title"))
        dlg.resize(620, 430)
        layout = QVBoxLayout(dlg)
        title = QLabel(f"FreeCleaner {APP_VERSION}")
        title.setObjectName("PageTitle")
        layout.addWidget(title)
        desc = QLabel(self.tr("about_short_desc"))
        desc.setObjectName("SectionSub")
        desc.setWordWrap(True)
        layout.addWidget(desc)
        meta = QTextEdit()
        meta.setReadOnly(True)
        meta.setPlainText(
            f"Version: {APP_VERSION_RAW}\n"
            
            f"Mode: {'Administrator' if self.is_admin else 'Restricted'}\n"
            f"Config: {CONFIG_PATH}\n"
            f"Data folder: {get_user_data_dir(create=True)}\n"
            f"Logs: {get_logs_dir(create=True)}\n"
            + "\n".join(f"{name.title()} log: {path}" for name, path in all_log_paths().items())
        )
        layout.addWidget(meta, 1)
        actions = QHBoxLayout()
        license_btn = QPushButton(self.tr("about_license") if self.tr("about_license") != "about_license" else "License")
        license_btn.clicked.connect(lambda: QMessageBox.information(self, "License", self.read_project_text("LICENSE")[:5000] or "LICENSE file not found."))
        privacy_btn = QPushButton("Privacy")
        privacy_btn.clicked.connect(self.show_privacy_policy)
        close_btn = QPushButton("OK")
        close_btn.setObjectName("PrimaryButton")
        close_btn.clicked.connect(dlg.accept)
        actions.addWidget(license_btn)
        actions.addWidget(privacy_btn)
        actions.addStretch(1)
        actions.addWidget(close_btn)
        layout.addLayout(actions)
        dlg.exec()

    def show_privacy_policy(self) -> None:
        text = self.read_project_text("PRIVACY_POLICY.txt") or "PRIVACY_POLICY.txt file not found."
        dlg = QDialog(self)
        dlg.setWindowTitle("Privacy Policy")
        dlg.resize(720, 520)
        layout = QVBoxLayout(dlg)
        box = QTextEdit()
        box.setReadOnly(True)
        box.setPlainText(text)
        layout.addWidget(box, 1)
        close = QPushButton("OK")
        close.setObjectName("PrimaryButton")
        close.clicked.connect(dlg.accept)
        layout.addWidget(close, 0, Qt.AlignRight)
        dlg.exec()

    def restart_as_admin(self) -> None:
        if self.is_admin:
            QMessageBox.information(self, "FreeCleaner", "Програма вже запущена від адміністратора.")
            return
        if QMessageBox.question(self, "FreeCleaner", "Перезапустити FreeCleaner від адміністратора?") != QMessageBox.Yes:
            return
        ok, message, pid = WindowsOps.run_as_admin()
        if not ok:
            self.log(f"Не вдалося перезапустити від адміністратора: {message}", "error")
            QMessageBox.warning(self, "FreeCleaner", f"Не вдалося запустити FreeCleaner від адміністратора.\n\n{message}")
            return
        self.log(self.tr("relaunching_admin"))
        try:
            self.show_toast("FreeCleaner", "Запущено запит UAC. Поточне вікно закриється після старту нового процесу.", "info")
        except Exception:
            pass
        # Do not quit immediately: the elevated copy needs a moment to pass UAC
        # and skip the single-instance mutex through --elevated-relaunch.
        QTimer.singleShot(1200, QApplication.quit)


    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        try:
            self._ui_watchdog_stop.set()
            self._estimate_cancel_event.set()
            self.cancel_event.set()
        except Exception:
            pass
        super().closeEvent(event)

    def check_updates(self) -> None:
        if getattr(self, "_update_check_running", False):
            self.log(self.tr("update_check_running"))
            self.show_toast(self.tr("update_check_running"), "warning")
            return
        limit = max(1, int(getattr(self, "_max_background_jobs", 2) or 2))
        if len(getattr(self, "background_jobs", [])) >= limit:
            self.show_toast(self.tr("background_busy_retry_check"), "warning")
            return
        self._update_check_running = True
        self.log(f"{self.tr('checking_updates')} ({APP_UPDATE_OWNER}/{APP_UPDATE_REPO})")

        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(8, self.tr("update_contacting_server"))
            info = fetch_latest_github_release(APP_UPDATE_OWNER, APP_UPDATE_REPO)
            if not info:
                emit(100, self.tr("update_check_failed"))
                return {
                    "total": self.analysis_total,
                    "op": "update",
                    "failed": True,
                    "repo": f"{APP_UPDATE_OWNER}/{APP_UPDATE_REPO}",
                    "release_url": APP_UPDATE_LATEST_RELEASE_URL,
                }

            cmp_result = compare_versions(APP_VERSION_RAW, info.version_text)
            base = {
                "total": self.analysis_total,
                "op": "update",
                "repo": f"{info.owner}/{info.repo}",
                "current": APP_VERSION_RAW,
                "current_display": APP_VERSION,
                "latest": info.version_text,
                "latest_name": info.name,
                "tag": info.tag_name,
                "release_url": info.html_url,
                "download_url": info.download_url,
                "asset_name": info.asset_name,
                "published_at": info.published_at,
                "body": info.changelog or info.body,
                "changelog_count": info.changelog_count,
            }
            if cmp_result < 0:
                emit(100, self.trf("update_available_log", current=APP_VERSION, latest=info.version_text))
                base["available"] = True
                return base
            emit(100, self.trf("update_up_to_date_log", version=APP_VERSION))
            base["available"] = False
            base["newer_local"] = cmp_result > 0
            return base

        self.run_background_worker(job)

    def show_update_dialog(self, result: Dict[str, Any]) -> None:
        try:
            old = getattr(self, "_update_dialog", None)
            if old is not None and old.isVisible():
                old.raise_()
                old.activateWindow()
                return
        except Exception:
            pass
        dlg = UpdateDialog(self, result)
        self._update_dialog = dlg
        dlg.download_requested.connect(lambda: self.download_update_and_install(result, dlg), Qt.QueuedConnection)
        dlg.release_requested.connect(lambda url: webbrowser.open(str(url or APP_UPDATE_LATEST_RELEASE_URL)), Qt.QueuedConnection)
        dlg.cancel_requested.connect(self.cancel_update_download, Qt.QueuedConnection)
        dlg.destroyed.connect(lambda _=None, ref=dlg: self._clear_update_dialog_ref(ref), Qt.QueuedConnection)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _clear_update_dialog_ref(self, ref: QWidget) -> None:
        if getattr(self, "_update_dialog", None) is ref:
            self._update_dialog = None
        if getattr(self, "_update_progress_dialog", None) is ref:
            self._update_progress_dialog = None

    def download_update_and_install(self, update: Dict[str, Any], dialog: Optional[UpdateDialog] = None) -> None:
        if getattr(self, "_update_download_running", False):
            self.show_toast(self.tr("update_download_busy"), "warning")
            if dialog is not None:
                dialog.set_failed(self.tr("update_download_busy"))
            return
        download_url = str(update.get("download_url") or "").strip()
        release_url = str(update.get("release_url") or APP_UPDATE_LATEST_RELEASE_URL).strip()
        asset_name = str(update.get("asset_name") or "").strip()
        latest = str(update.get("latest") or update.get("latest_name") or "update")

        if not download_url or not download_url.lower().startswith("https://"):
            self.show_toast(self.tr("update_download_failed"), "error")
            if dialog is not None:
                dialog.set_failed(self.tr("update_no_secure_installer_link"))
            return
        if not asset_name or not download_url.lower().endswith((".exe", ".msi")):
            self.log(self.tr("update_installer_missing_open_release_log"))
            if dialog is not None:
                dialog.set_failed(self.tr("update_installer_missing_open_release"))
            try:
                webbrowser.open(release_url or download_url)
                self.show_toast(self.tr("update_release_page_opened"), "info")
            except Exception as exc:
                self.show_toast(str(exc), "error")
            return

        limit = max(1, int(getattr(self, "_max_background_jobs", 2) or 2))
        if len(getattr(self, "background_jobs", [])) >= limit:
            self.show_toast(self.tr("background_busy_retry_download"), "warning")
            if dialog is not None:
                dialog.set_failed(self.tr("background_busy_retry_download"))
            return
        self._update_download_running = True
        filename = asset_name or guess_download_filename(download_url, fallback="FreeCleaner-update.exe")
        dest_path = get_update_download_path(filename, fallback="FreeCleaner-update.exe")
        self._update_download_cancel_event = threading.Event()
        if dialog is not None:
            self._update_progress_dialog = dialog
            dialog.set_downloading(latest, filename, dest_path)
        keep = {dest_path}
        try:
            removed = cleanup_old_update_files(keep)
            if removed:
                self.log(self.trf("update_cleanup_removed", count=removed))
        except Exception:
            pass
        self.log(self.trf("update_download_started", version=latest))
        self.log(self.trf("update_download_location", path=get_updates_dir(create=True)))

        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            started = time.perf_counter()
            cancel_event = getattr(self, "_update_download_cancel_event", None)

            def emit_payload(percent: int, **payload: Any) -> None:
                payload["percent"] = max(0, min(100, int(percent)))
                try:
                    emit(payload["percent"], UPDATE_PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False))
                except Exception:
                    emit(payload["percent"], str(payload.get("message") or ""))

            def on_progress(downloaded: int, total: Optional[int]) -> None:
                elapsed = max(0.001, time.perf_counter() - started)
                speed = max(0.0, float(downloaded) / elapsed)
                if total and total > 0:
                    percent = max(1, min(94, int(downloaded * 94 / total)))
                    eta = max(0.0, float(total - downloaded) / speed) if speed > 0 else 0.0
                else:
                    percent = min(90, max(5, int((downloaded / max(downloaded + 1024 * 1024, 1)) * 90)))
                    eta = 0.0
                emit_payload(percent, stage="downloading", downloaded=downloaded, total=total or 0, speed=int(speed), eta=int(eta), message=self.trf("update_download_percent", percent=percent))

            emit_payload(2, stage="downloading", downloaded=0, total=0, speed=0, eta=0, message=self.trf("update_download_started", version=latest))
            ok, message = download_url_to_file(download_url, dest_path, progress_cb=on_progress, cancel_event=cancel_event)
            if not ok:
                stage = "cancelled" if "cancel" in str(message).casefold() else "failed"
                emit_payload(100, stage=stage, message=message)
                return {"op": "update_download", "ok": False, "message": message, "path": dest_path, "cancelled": stage == "cancelled"}

            emit_payload(96, stage="verifying", path=dest_path, message=self.trf("update_download_saved", path=dest_path))
            emit_payload(98, stage="installing", path=dest_path, message=self.trf("update_install_starting", path=dest_path))
            install_ok, install_message, pid = launch_update_installer(dest_path)
            result = {
                "op": "update_download",
                "ok": bool(install_ok),
                "path": dest_path,
                "message": install_message,
                "pid": pid,
            }
            if install_ok:
                schedule_update_cleanup_after_install(pid)
                emit_payload(100, stage="installing", path=dest_path, message=self.tr("update_install_started_button"))
            else:
                emit_payload(100, stage="failed", message=self.trf("update_install_failed_reason", reason=install_message))
            return result

        self.run_background_worker(job)

    def run_system_report(self) -> None:
        self.log("System check: collecting...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, "System check: collecting...")
            report = {
                "mode": "administrator" if self.is_admin else "restricted",
                "registered_tasks": len(self.tasks),
                "cleaner_tasks": len([t for t in self.tasks.values() if t.category != "optimizer"]),
                "optimizer_toggles": len([t for t in self.tasks.values() if t.category == "optimizer"]),
                "registry_backups": len(WindowsOps.list_registry_backups()),
                "scan_workers": get_adaptive_workers("scan", SCAN_WORKERS),
                "clean_workers": get_adaptive_workers("clean", CLEAN_WORKERS),
                "system_drive": get_system_drive_info(),
                "config_path": CONFIG_PATH,
                "logs_dir": get_logs_dir(create=True),
                "log_files": all_log_paths(),
            }
            emit(100, "System check: done")
            return {"op": "diagnostic_report", "title": "System check", "report": report, "card": 0, "toast": "Системну перевірку завершено"}
        self.run_background_worker(job)

    def run_streaming_report(self) -> None:
        self.log("OBS/Streaming report: collecting...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, "OBS/Streaming report: collecting...")
            report = WindowsOps.collect_streaming_diagnostics()
            emit(100, "OBS/Streaming report: done")
            return {"op": "diagnostic_report", "title": "OBS/Streaming report", "report": report, "card": 2, "toast": "Streaming diagnostics зібрано"}
        self.run_background_worker(job)

    def run_gaming_report(self) -> None:
        self.log("Gaming compatibility report: collecting...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, "Gaming compatibility report: collecting...")
            report = WindowsOps.collect_gaming_compat_report()
            emit(100, "Gaming compatibility report: done")
            return {"op": "diagnostic_report", "title": "Gaming compatibility report", "report": report, "card": 1, "toast": "Gaming report зібрано"}
        self.run_background_worker(job)

    def run_onedrive_report(self) -> None:
        self.log("OneDrive report: collecting...")
        def job(emit: Callable[[int, str], None]) -> Dict[str, Any]:
            emit(10, "OneDrive report: collecting...")
            report = WindowsOps.collect_onedrive_report()
            emit(100, "OneDrive report: done")
            return {"op": "diagnostic_report", "title": "OneDrive report", "report": report, "card": 3, "toast": "OneDrive report зібрано"}
        self.run_background_worker(job)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        self.cancel_event.set()
        try:
            self._estimate_cancel_event.set()
        except Exception:
            pass
        self._status_sync_pending = False
        super().closeEvent(event)


def configure_high_dpi() -> None:
    # Warning-free Qt 6 startup: use QT_SCALE_FACTOR_ROUNDING_POLICY from the
    # launcher/bootstrap instead of calling the Qt API at runtime.  Some Windows
    # builds print a warning even when the call is guarded, so this is a no-op.
    return


def _prepare_qapplication(app: QApplication, apply_stylesheet: bool = True) -> Optional[str]:
    app.setApplicationName("FreeCleaner")
    app.setApplicationDisplayName("FreeCleaner")
    app.setOrganizationName("FreeCleaner")
    if apply_stylesheet:
        app.setStyleSheet(APP_QSS)
    app.setQuitOnLastWindowClosed(True)
    icon = find_icon_path("app.ico") or find_icon_path("app.png")
    if icon:
        app.setWindowIcon(QIcon(icon))
    return icon


def launch_existing_app(app: QApplication, splash: Optional[QWidget] = None) -> int:
    global _MAIN_WINDOW_REF
    if IS_WINDOWS:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("FreeCleaner.Qt")
        except Exception:
            pass
    # Do not apply the global QSS while the splash is visible.  Re-polishing the
    # already shown splash during full Qt UI import can create a short native
    # background-window flash on Windows.  Apply QSS after the splash closes and
    # before the main window becomes visible.
    icon = _prepare_qapplication(app, apply_stylesheet=False)
    owned_splash = splash is None
    if splash is None:
        splash = SplashWindow(icon)
        splash.show_centered()
    if hasattr(splash, "set_progress"):
        splash.set_progress(72, "Завантаження Qt інтерфейсу…")  # type: ignore[attr-defined]
    window = FreeCleanerQt()
    _MAIN_WINDOW_REF = window
    try:
        app._freecleaner_main_window = window  # keep PySide wrapper alive
    except Exception:
        pass
    if hasattr(splash, "set_progress"):
        splash.set_progress(100, "Запуск інтерфейсу…")  # type: ignore[attr-defined]
    native_splash = bool(getattr(splash, "_fc_native_splash", False)) if splash is not None else False

    def show_main_window() -> None:
        # Native bootstrap splash stays visible while the Qt stylesheet is
        # applied and the main window is mapped.  Closing it first creates the
        # exact black/background gap and helper-window blink reported during
        # "Preparing Qt modules".  Qt fallback splash keeps the previous close
        # first behavior.
        if native_splash:
            try:
                app.setStyleSheet(APP_QSS)
            except Exception:
                pass
            # Quiet handoff: map and polish the Qt main window while it is fully
            # transparent, then close the Win32 splash and reveal the already
            # painted window.  Showing the main window at normal opacity before
            # the first paint produced the gray native frame behind the splash.
            try:
                window.setWindowOpacity(0.0)
            except Exception:
                pass
            window.show()
            try:
                QApplication.processEvents()
                window.repaint()
                QApplication.processEvents()
            except Exception:
                pass
            if splash is not None:
                try:
                    splash.close()
                except Exception:
                    pass
            try:
                window.setWindowOpacity(1.0)
            except Exception:
                pass
            window.raise_()
            window.activateWindow()
        else:
            if splash is not None:
                try:
                    splash.close()
                except Exception:
                    pass
            try:
                app.setStyleSheet(APP_QSS)
            except Exception:
                pass
            window.show()
            window.raise_()
            window.activateWindow()
        log_startup("main window shown")

    if splash is not None:
        if hasattr(splash, "fade_out"):
            splash.fade_out()  # type: ignore[attr-defined]
            # Keep the native splash visible through this short handoff delay.
            # For Qt fallback splash, fade_out closes it just like previous builds.
            QTimer.singleShot(120 if native_splash else (360 if owned_splash else 320), show_main_window)
        else:
            if not native_splash:
                splash.close()
            QTimer.singleShot(0, show_main_window)
    else:
        QTimer.singleShot(0, show_main_window)
    return app.exec()


def main() -> int:
    configure_high_dpi()
    # High-DPI rounding is controlled by environment variables set before Qt.
    # A direct Qt setter here is too late on some Windows/PySide6 builds and
    # creates the startup warning the user sees in logs.
    app = QApplication(sys.argv)
    return launch_existing_app(app)


if __name__ == "__main__":
    raise SystemExit(main())
