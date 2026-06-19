"""Compatibility wrapper for the FreeCleaner Qt frontend."""

from __future__ import annotations

from .qt_app import FreeCleanerQt, main


class Cleaner(FreeCleanerQt):
    """Backward-compatible class name for older launchers."""


__all__ = ["Cleaner", "FreeCleanerQt", "main"]


if __name__ == "__main__":
    raise SystemExit(main())
