#!/usr/bin/env python3
"""Validate that release tag, build number and Windows metadata agree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

TAG_RE = re.compile(
    r"^v(?P<base>\d+(?:\.\d+){0,3})"
    r"(?:-(?P<pre>alpha\d*|beta\d*|rc\d*))?"
    r"(?:-build-(?P<build>\d+))?$",
    re.IGNORECASE,
)
FULL_VERSION_RE = re.compile(r"^(?P<base>\d+(?:\.\d+){3})-build-(?P<build>\d+)$")


def normalize_windows_version(base: str) -> str:
    parts = base.split(".")
    if not parts or any(not part.isdigit() for part in parts) or len(parts) > 4:
        raise ValueError(f"invalid base version: {base!r}")
    return ".".join(str(int(part)) for part in (parts + ["0"] * 4)[:4])


def parse_release_tag(tag: str) -> tuple[str, int | None, str]:
    """Return base version, optional embedded build number, and prerelease label."""
    match = TAG_RE.fullmatch(tag.strip())
    if not match:
        raise ValueError(
            "tag must use v<1-4 numeric parts>[-alphaN|-betaN|-rcN]"
            "[-build-<number>]"
        )
    build_text = match.group("build")
    build = int(build_text) if build_text is not None else None
    return match.group("base"), build, match.group("pre") or ""


def resolve_build_number(tag: str, explicit_build: int | None, full_version: str) -> int:
    """Resolve one authoritative build number and reject contradictory metadata."""
    _base, tag_build, _pre = parse_release_tag(tag)
    full_match = FULL_VERSION_RE.fullmatch(full_version.strip())
    if not full_match:
        raise ValueError(
            "full version must use <four-part-version>-build-<number>, "
            f"got {full_version!r}"
        )
    full_build = int(full_match.group("build"))

    candidates = [value for value in (tag_build, explicit_build, full_build) if value is not None]
    if not candidates:
        raise ValueError("a build number is required")
    if len(set(candidates)) != 1:
        raise ValueError(
            "build number mismatch: "
            f"tag={tag_build!r}, argument={explicit_build!r}, full_version={full_build!r}"
        )
    return candidates[0]


def expected_full_version(tag: str, build_number: int | None = None) -> str:
    base, tag_build, _pre = parse_release_tag(tag)
    build = tag_build if tag_build is not None else build_number
    if build is None:
        raise ValueError(f"tag {tag!r} does not contain a build number")
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
    parser.add_argument("--build-number", type=int)
    parser.add_argument("--full-version", required=True)
    parser.add_argument("--version-info", type=Path)
    args = parser.parse_args()

    try:
        build_number = resolve_build_number(args.tag, args.build_number, args.full_version)
        expected = expected_full_version(args.tag, build_number)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

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
