# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Legacy XLS inputs need xlrd in both runtime installation paths."""

from __future__ import annotations

import tomllib
from pathlib import Path

import get_loop_health as loop
import pandas as pd
import pytest
import xlrd
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "fixtures" / "loop_basic_biff8.xls"


def test_project_declares_supported_xlrd_runtime() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = [Requirement(value) for value in project["project"]["dependencies"]]
    readers = [dependency for dependency in dependencies if dependency.name == "xlrd"]
    assert len(readers) == 1
    assert str(readers[0].specifier) == ">=2.0.2"


def test_launcher_pins_approved_xlrd() -> None:
    dependencies = [
        Requirement(line)
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    readers = [dependency for dependency in dependencies if dependency.name == "xlrd"]
    assert len(readers) == 1
    assert str(readers[0].specifier) == "==2.0.2"


def test_fixture_is_true_biff8_with_two_sheets() -> None:
    assert FIXTURE.read_bytes()[:8] == bytes.fromhex("D0CF11E0A1B11AE1")
    with xlrd.open_workbook(FIXTURE, on_demand=True) as book:
        assert book.biff_version == 80
        assert book.sheet_names() == [
            "Agent Performance Counters", "Not the selected sheet"
        ]


@pytest.mark.parametrize("suffix", [".xls", ".XLS"])
def test_loop_loads_legacy_xls_with_real_reader(tmp_path: Path, suffix: str) -> None:
    # Share the main workbench's synthetic BIFF8 fixture, not a renamed XLSX.
    path = tmp_path / f"loop{suffix}"
    path.write_bytes(FIXTURE.read_bytes())
    with pd.ExcelFile(path) as workbook:
        assert workbook.engine == "xlrd"

    frame = loop.load_loop_input(path)

    expected = pd.DataFrame(
        [
            ["TEST-CLIENT-1", 42, 17],
            ["TEST-CLIENT-2", 180, 95],
            ["TEST-CLIENT-3", "Not Reported", "Not Reported"],
        ],
        columns=[
            "Computer Name",
            "Platform Health Check - Maximum Cycle Minutes",
            "Platform Health Check - Average Cycle Minutes",
        ],
    )
    pd.testing.assert_frame_equal(frame, expected)
