#!/usr/bin/env python3
"""Validate that release tag, build number and Windows metadata agree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Tuple

TAG_RE = re.compile(
    r"^v(?P<base>\d+(?:\.\d+){0,3})(?:-(?P<pre>alpha\d*|beta\d*|rc\d*))?-build-(?P<build>\d+)$",
    re.IGNORECASE,
)


def normalize_windows_version(base: str) -> str:
    parts = base.split(".")
    if not parts or any(not part.isdigit() for part in parts) or len(parts) > 4:
        raise ValueError(f"invalid base version: {base!r}")
    return ".".join(str(int(part)) for part in (parts + ["0"] * 4)[:4])


def parse_release_tag(tag: str) -> Tuple[str, int, str]:
    match = TAG_RE.fullmatch(tag.strip())
    if not match:
        raise ValueError(
            "tag must use v<1-4 numeric parts>[-alphaN|-betaN|-rcN]-build-<number>"
        )
    return match.group("base"), int(match.group("build")), match.group("pre") or ""


def expected_full_version(tag: str) -> str:
    base, build, _pre = parse_release_tag(tag)
    return f"{normalize_windows_version(base)}-build-{build}"


def version_info_product_version(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"StringStruct\('ProductVersion',\s*'([^']+)'\)", text)
    if not match:
        raise ValueError(f"ProductVersion not found in {path}")
    return match.group(1).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--full-version", required=True)
    parser.add_argument("--version-info", type=Path)
    args = parser.parse_args()

    expected = expected_full_version(args.tag)
    if args.full_version.strip() != expected:
        raise SystemExit(
            f"full version mismatch: tag requires {expected!r}, got {args.full_version!r}"
        )
    if args.version_info:
        actual = version_info_product_version(args.version_info)
        if actual != expected:
            raise SystemExit(
                f"version_info mismatch: expected {expected!r}, got {actual!r}"
            )
    print(f"release metadata OK: {args.tag} -> {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
