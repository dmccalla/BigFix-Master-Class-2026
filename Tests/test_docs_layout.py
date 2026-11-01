# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Docs layout guards.

Docs holds only README.md and folders. Every other file lives in the folder
that matches its kind: User Guide, Lab Guide, Presentation, Reference,
Records, Releases, Validation or Design. Relative Markdown links must resolve
so a move never leaves a README pointing at nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "Docs"
LINK = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)|^\[[^\]]+\]:\s*(\S+)", re.MULTILINE)
UNSHIPPED = ("Docs/Design", "Temp", "tmp", "output")


def test_docs_root_holds_only_readme_and_folders() -> None:
    loose = sorted(
        p.name
        for p in DOCS.iterdir()
        if p.is_file() and p.name != "README.md" and not p.name.startswith("~$")
    )
    assert not loose, (
        f"Loose files in Docs: {loose}. Move each into the folder that matches "
        "its kind (Reference, Records, Design, User Guide, Lab Guide, ...)."
    )


def test_relative_markdown_links_resolve() -> None:
    sources = [ROOT / "README.md", ROOT / "SECURITY.md", *DOCS.rglob("*.md")]
    broken = []
    for source in sources:
        rel_source = source.relative_to(ROOT).as_posix()
        if not source.is_file() or rel_source.startswith(UNSHIPPED):
            continue
        text = source.read_text(encoding="utf-8", errors="replace")
        for match in LINK.finditer(text):
            target = (match.group(1) or match.group(2)).strip("<>")
            if re.match(r"^(https?:|mailto:|#|tel:)", target):
                continue
            path = unquote(target.split("#")[0])
            if not path:
                continue
            resolved = (source.parent / path).resolve()
            try:
                rel_target = resolved.relative_to(ROOT).as_posix()
            except ValueError:
                rel_target = ""
            if rel_target.startswith(UNSHIPPED):
                continue
            if not resolved.exists():
                broken.append(f"{rel_source}: {target}")
    assert not broken, "Broken relative links:\n" + "\n".join(broken)
