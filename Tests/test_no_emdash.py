# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Project-wide em-dash ban (user directive 2026-07-19).

Em-dashes (U+2014) are not allowed anywhere in the project: not in code, docs,
config, chart templates, or the Word report templates. The em-dash "aside"
writing style is unwanted; use a colon, comma, parentheses, or a full stop
instead. Number ranges use a hyphen ("0-2 weeks"), which is fine.

This guard fails if any em-dash reappears so the ban stays enforced.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

EM_DASH = "\u2014"  # kept as an escape so this guard file stays em-dash-free
ROOT = Path(__file__).resolve().parents[1]
# The collection tasks are covered by the same project-wide ban.
TASKS_ROOT = ROOT / "Tasks and Analyses"

_EXCL_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "Temp",
    ".claude",
    "SampleData",
    "Dist",
}
_TEXT_EXT = {
    ".py",
    ".md",
    ".json",
    ".html",
    ".css",
    ".js",
    ".txt",
    ".yml",
    ".yaml",
    ".toml",
    ".cfg",
    ".ini",
    ".bes",
    ".rst",
}
_TEMPLATE_EXT = {".dotx", ".docx"}


def _iter_files(exts: set[str]):
    roots = [ROOT]
    if TASKS_ROOT.is_dir():
        roots.append(TASKS_ROOT)
    for root in roots:
        for path in root.rglob("*"):
            if path.suffix.lower() not in exts:
                continue
            if any(part in _EXCL_DIRS for part in path.relative_to(root).parts):
                continue
            if path.name.startswith("~$"):
                continue
            yield path


def _text_files():
    return sorted(_iter_files(_TEXT_EXT))


def test_no_emdash_in_source_text() -> None:
    offenders = []
    for path in _text_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        if EM_DASH in text:
            n = text.count(EM_DASH)
            offenders.append(f"{path.relative_to(ROOT.parent)} ({n})")
    assert not offenders, (
        "Em-dash (U+2014) is banned project-wide; use a colon/comma/parentheses "
        "instead. Found in:\n  " + "\n  ".join(offenders)
    )


def test_no_emdash_in_word_templates() -> None:
    offenders = []
    for path in sorted(_iter_files(_TEMPLATE_EXT)):
        try:
            zf = zipfile.ZipFile(path)
        except (OSError, zipfile.BadZipFile):
            continue
        with zf:
            for name in zf.namelist():
                if not (name.startswith("word/") and name.endswith(".xml")):
                    continue
                try:
                    chunk = zf.read(name).decode("utf-8")
                except (KeyError, UnicodeDecodeError):
                    continue
                if EM_DASH in chunk:
                    offenders.append(f"{path.relative_to(ROOT.parent)}::{name}")
    assert not offenders, (
        "Em-dash (U+2014) found in a Word template's static content; remove it "
        "in Word. Offenders:\n  " + "\n  ".join(offenders)
    )
