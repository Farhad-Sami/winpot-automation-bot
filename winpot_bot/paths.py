"""Frozen-executable safe path helpers."""

from __future__ import annotations

import sys
from pathlib import Path


def bundle_dir() -> Path:
    """Return directory containing bundled read-only assets (snapshot.js, .env)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def app_dir() -> Path:
    """Return writable directory next to the executable (for profiles/ and settings.json)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
