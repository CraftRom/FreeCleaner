#!/usr/bin/env python3
"""Validate external JSON language packs and format placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

PLACEHOLDER_RE = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)[^}]*\}(?!\})")


def placeholders(value: str) -> set[str]:
    return set(PLACEHOLDER_RE.findall(value or ""))


def main() -> int:
    lang_dir = Path(__file__).resolve().parents[1] / "lang"
    packs = {}
    for path in sorted(lang_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise SystemExit(f"{path}: root must be an object")
        packs[path.stem] = data
    if "en" not in packs:
        raise SystemExit("lang/en.json is required")
    reference = packs["en"]
    errors: list[str] = []
    for code, pack in packs.items():
        missing = sorted(set(reference) - set(pack))
        extra = sorted(set(pack) - set(reference))
        if missing:
            errors.append(f"{code}: missing keys: {', '.join(missing[:20])}")
        if extra:
            errors.append(f"{code}: extra keys: {', '.join(extra[:20])}")
        for key in sorted(set(reference) & set(pack)):
            value = pack[key]
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{code}:{key}: value must be a non-empty string")
                continue
            if placeholders(value) != placeholders(str(reference[key])):
                errors.append(
                    f"{code}:{key}: placeholders {sorted(placeholders(value))} "
                    f"!= {sorted(placeholders(str(reference[key])))}"
                )
    if errors:
        raise SystemExit("\n".join(errors))
    print(f"translations OK: {len(packs)} packs, {len(reference)} keys")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
