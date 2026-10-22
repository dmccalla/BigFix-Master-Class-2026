#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""build_provenance.py -- which code and which template built a document.

Design's build rule (10-20): the build log names the commit and the full
template path. The document's Comments property names the commit and the
template file name only, because a local path never goes into a delivered
document.
"""

from __future__ import annotations

import re
import subprocess
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from Lib.Core.subprocess_window import hidden_subprocess_kwargs

# U+00B7 with a space on each side, the same separator as the document stamp.
_SEPARATOR = " · "
_CORE_PART = "docProps/core.xml"
_DC_NAMESPACE = "http://purl.org/dc/elements/1.1/"


def _git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
        stdin=subprocess.DEVNULL,
        **hidden_subprocess_kwargs(),
    )
    return result.stdout.strip()


def build_commit(repo_root: Path) -> str:
    """The short commit hash of the code under repo_root.

    "-dirty" is added when tracked files under repo_root differ from that
    commit, so a build from uncommitted code never claims a clean commit.
    "unknown" when the code is not a git checkout, as in a release package.
    """
    try:
        head = _git(repo_root, "rev-parse", "--short", "HEAD")
        changed = _git(
            repo_root, "status", "--porcelain", "--untracked-files=no", "--", "."
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if not head:
        return "unknown"
    return f"{head}-dirty" if changed else head


def provenance_comment(commit: str, template: Path | str | None) -> str:
    """The Comments property text: the commit and the template file name."""
    name = Path(str(template)).name if template else "none"
    return f"Commit {commit}{_SEPARATOR}Template {name}"


def _with_description(core_xml: str, text: str) -> str:
    element = f"<dc:description>{escape(text)}</dc:description>"
    existing = re.compile(
        r"<dc:description\s*/>|<dc:description>.*?</dc:description>", re.DOTALL
    )
    if existing.search(core_xml):
        return existing.sub(lambda _: element, core_xml, count=1)
    root = re.search(r"<cp:coreProperties\b[^>]*>", core_xml)
    if root is None:
        raise ValueError("docProps/core.xml has no cp:coreProperties element")
    opening = root.group(0)
    if "xmlns:dc=" not in opening:
        opening = opening[:-1] + f' xmlns:dc="{_DC_NAMESPACE}">'
    closing = "</cp:coreProperties>"
    body = core_xml[: root.start()] + opening + core_xml[root.end() :]
    return body.replace(closing, element + closing, 1)


def set_document_comments(docx_path: Path | str, text: str) -> bool:
    """Write text to the Comments property (dc:description) of a .docx.

    Returns False when the file has no core properties part to write to, and
    raises ValueError when the file is not a Word package.
    """
    path = Path(docx_path)
    try:
        with zipfile.ZipFile(path) as source:
            items = [(info, source.read(info.filename)) for info in source.infolist()]
    except zipfile.BadZipFile as exc:
        raise ValueError(f"{path.name} is not a Word document") from exc
    if _CORE_PART not in {info.filename for info, _ in items}:
        return False
    temporary = path.with_name(path.name + ".provenance.tmp")
    with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as target:
        for info, data in items:
            if info.filename == _CORE_PART:
                data = _with_description(data.decode("utf-8"), text).encode("utf-8")
            target.writestr(info, data)
    temporary.replace(path)
    return True
