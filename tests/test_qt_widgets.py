from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt

from freecleaner.qt_app import ToggleSwitch, UiFx


def test_toggle_switch_animates_to_checked(qtbot):
    previous = UiFx.enabled
    UiFx.enabled = True
    try:
        switch = ToggleSwitch()
        qtbot.addWidget(switch)
        switch.show()
        switch.setChecked(True)
        qtbot.waitUntil(lambda: switch.get_position() >= 0.99, timeout=1000)
        assert switch.isChecked()
    finally:
        UiFx.enabled = previous


def test_toggle_switch_reduced_motion_and_keyboard(qtbot):
    previous = UiFx.enabled
    UiFx.enabled = False
    try:
        switch = ToggleSwitch()
        qtbot.addWidget(switch)
        switch.show()
        switch.setFocus()
        qtbot.keyClick(switch, Qt.Key_Space)
        assert switch.isChecked()
        assert switch.get_position() == 1.0
        qtbot.keyClick(switch, Qt.Key_Return)
        assert not switch.isChecked()
        assert switch.get_position() == 0.0
    finally:
        UiFx.enabled = previous
