# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Every first-party source file carries the MIT notice, and the license
files exist at the root."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SUFFIXES = {".py", ".ps1", ".sh", ".bat", ".cmd", ".command"}
REQUIRED_NOTICE = "SPDX-License-Identifier: MIT"


def _tracked_files() -> list[Path]:
    completed = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    return [ROOT / line for line in completed.stdout.splitlines() if line.strip()]


def test_first_party_source_files_have_spdx_license_notice() -> None:
    missing: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() not in SOURCE_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if REQUIRED_NOTICE not in text:
            missing.append(path.relative_to(ROOT).as_posix())
    assert not missing, (
        "First-party source files must keep the MIT SPDX notice:\n  "
        + "\n  ".join(missing)
    )


def test_root_license_and_notice_files_exist() -> None:
    assert (ROOT / "LICENSE").is_file()
    assert (ROOT / "NOTICE").is_file()
    assert "MIT License" in (ROOT / "LICENSE").read_text(encoding="utf-8")
