# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""The launcher, the docs and pyproject agree on the Python floor, and the
batch file keeps the line endings cmd.exe needs."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "Launchers" / "Run Diagnostics Workbench.cmd"


def _declared_floor() -> tuple[int, int]:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    spec = data["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec.strip())
    assert match, f"requires-python is not a plain floor: {spec!r}"
    return int(match.group(1)), int(match.group(2))


def test_launcher_uses_crlf_line_endings() -> None:
    raw = LAUNCHER.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "a BOM breaks cmd.exe"
    lf_only = raw.count(b"\n") - raw.count(b"\r\n")
    assert lf_only == 0, (
        f"{lf_only} lines end in bare LF. cmd.exe needs CRLF for goto labels."
    )


def test_launcher_checks_the_declared_python_floor() -> None:
    major, minor = _declared_floor()
    text = LAUNCHER.read_text(encoding="utf-8")
    assert f"sys.version_info >= ({major}, {minor})" in text
    assert f"Python {major}.{minor} or newer" in text
    stale = re.findall(r"3\.(\d+) or newer", text)
    assert set(stale) == {str(minor)}, (
        f"launcher names other floors: {sorted(set(stale))}"
    )


def test_docs_name_the_declared_python_floor() -> None:
    major, minor = _declared_floor()
    floor = f"{major}.{minor}"
    for rel in ("README.md", "Docs/Getting_Started.md", "Build/package_release.ps1"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        found = set(re.findall(r"Python (3\.\d+) or newer", text))
        assert found == {floor}, (
            f"{rel} says {sorted(found) or 'nothing'}, pyproject says {floor}"
        )
