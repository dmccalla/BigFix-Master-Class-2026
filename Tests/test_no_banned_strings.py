# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
Keep this tree free of references to the project it was derived from.

The Workbench is handed to Master Class attendees as a standalone tool. It
must not carry the name, branding, fonts, or hosting details of any other
project. This guard fails on the first occurrence of any banned string in a
text file, with the file and line, so the rule stays enforced rather than
remembered.

Data-contract strings are not banned: MXFillDBPerf.exe writes a column named
"Health Check" and that name is read back as data, so the bare phrase is
allowed. The compound forms below are not.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Case-sensitive unless noted. Keep this list short and specific.
BANNED = (
    "BigFix Health Check",
    "BigFix Platform Health Check",
    "Health Check Report",
    "Health Check report",
    "health check report",
    "health check template",
    "Health_Check",
    "HealthCheck",
    "Report Builder",
    "report builder",
    "AVP/PS",
    "AVP-PS",
    "Diagnostic Workbench",
    "HCL",
    "github.com",
)
BANNED_CASEFOLD = ("roobert", "hcltech", "hclsoftware")

_EXCL_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    "SampleData",
    "Fonts",
    "Temp",
}
_TEXT_EXT = {
    ".py",
    ".md",
    ".json",
    ".html",
    ".css",
    ".js",
    ".txt",
    ".toml",
    ".cfg",
    ".ini",
    ".cmd",
    ".ps1",
    ".bes",
    ".sql",
    ".xml",
}
# This guard names the strings it bans, so it cannot scan itself.
_EXCL_FILES = {Path(__file__).resolve()}


def _iter_text_files():
    for path in ROOT.rglob("*"):
        if path.suffix.lower() not in _TEXT_EXT:
            continue
        if any(part in _EXCL_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.resolve() in _EXCL_FILES:
            continue
        yield path


def _hits(path: Path) -> list[str]:
    hits: list[str] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return hits
    for number, line in enumerate(lines, 1):
        folded = line.casefold()
        for needle in BANNED:
            if needle in line:
                hits.append(f"{path.relative_to(ROOT)}:{number}: {needle!r}")
        for needle in BANNED_CASEFOLD:
            if needle in folded:
                hits.append(f"{path.relative_to(ROOT)}:{number}: {needle!r}")
    return hits


def test_tree_has_no_banned_strings() -> None:
    hits: list[str] = []
    for path in _iter_text_files():
        hits.extend(_hits(path))
    assert not hits, "Banned strings found:\n  " + "\n  ".join(hits)
