#!/usr/bin/env python3
"""Reject generated files and duplicate methods in shipped source archives."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    required_files = (
        Path(".github/workflows/build-release-notify.yml"),
        Path(".github/workflows/quality.yml"),
        Path("requirements-dev.txt"),
        Path("freecleaner/build_trust.py"),
    )
    for relative_path in required_files:
        if not (ROOT / relative_path).is_file():
            errors.append(f"required source file is missing: {relative_path}")
    for path in ROOT.rglob("*"):
        if path.is_dir() and path.name in {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}:
            errors.append(f"generated directory: {path.relative_to(ROOT)}")
        elif path.is_file() and path.suffix in {".pyc", ".pyo"}:
            errors.append(f"compiled/cache file: {path.relative_to(ROOT)}")
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names: dict[str, list[int]] = defaultdict(list)
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names[item.name].append(item.lineno)
            for name, lines in names.items():
                if len(lines) > 1:
                    errors.append(
                        f"duplicate method: {path.relative_to(ROOT)}:{node.name}.{name} {lines}"
                    )
    if errors:
        raise SystemExit("\n".join(f"ERROR: {item}" for item in errors))
    print("source tree OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
