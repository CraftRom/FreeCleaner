import ast
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_single_close_event_and_real_toggle_animation():
    source = (ROOT / "freecleaner" / "qt_app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    app_class = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "FreeCleanerQt")
    close_events = [node for node in app_class.body if isinstance(node, ast.FunctionDef) and node.name == "closeEvent"]
    assert len(close_events) == 1
    assert "QPropertyAnimation(self, b\"position\"" in source
    assert "QThread.terminate" not in source


def test_installer_no_longer_edits_main_config_with_string_surgery():
    source = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "ReplaceOrAddJsonLanguage" not in source
    assert "installer-language.json" in source
    assert "MinVersion=10.0" in source
