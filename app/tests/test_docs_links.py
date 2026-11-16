"""Relative links in the README and docs must point at files that exist."""

from __future__ import annotations

import re
from pathlib import Path

from app.core.paths import REPO_ROOT

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
SKIP_PREFIXES = ("http://", "https://", "mailto:", "#")


def _markdown_files() -> list[Path]:
    files = [REPO_ROOT / "README.md", REPO_ROOT / "app" / "services" / "README.md"]
    files += sorted((REPO_ROOT / "docs").rglob("*.md"))
    files += sorted((REPO_ROOT / "datasets").glob("*/README.md"))
    return files


def test_relative_links_resolve() -> None:
    broken: list[str] = []
    for source in _markdown_files():
        for target in LINK.findall(source.read_text(encoding="utf-8")):
            if target.startswith(SKIP_PREFIXES):
                continue
            path = target.split("#", 1)[0]
            if path and not (source.parent / path).exists():
                broken.append(f"{source.relative_to(REPO_ROOT)} -> {target}")
    assert not broken, "broken links:\n" + "\n".join(broken)
