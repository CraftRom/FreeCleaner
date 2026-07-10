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

def test_runtime_dependencies_do_not_reintroduce_unused_pillow():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    requirement_lines = [
        line.strip().lower()
        for line in requirements.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert not any(line.startswith("pillow") for line in requirement_lines)


def test_release_workflow_allows_unsigned_test_artifacts_but_not_unsigned_releases():
    workflow = (ROOT / ".github" / "workflows" / "build-release-notify.yml").read_text(encoding="utf-8")
    assert "throw 'WINDOWS_SIGNING_CERTIFICATE_BASE64 secret is required" not in workflow
    assert "signing_available: ${{ steps.signing.outputs.signing_available }}" in workflow
    assert "if: needs.version.outputs.signing_available == 'true'" in workflow
    assert "UNSIGNED TEST BUILD - DO NOT PUBLISH AS A RELEASE" in workflow
    assert "name: Create signed Release & Upload Assets" in workflow
    assert "name: Unsigned build notice" in workflow
    assert "-${{ needs.version.outputs.signing_label }}" in workflow
