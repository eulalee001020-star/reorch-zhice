"""Repository paths resolved once, so modules do not count parent directories."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
