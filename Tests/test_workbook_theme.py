# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

from pathlib import Path

from workbook_theme import WORKBOOK_THEME, status_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]


WORKBOOK_EXPORTERS = [
    "Get/get_loop_health.py",
    "Get/get_perfmon_charts.py",
]


def test_workbook_exporters_use_shared_theme() -> None:
    for rel_path in WORKBOOK_EXPORTERS:
        text = (PROJECT_ROOT / rel_path).read_text(encoding="utf-8")
        assert "workbook_theme" in text, f"{rel_path} bypasses workbook_theme"


def test_status_key_uses_report_status_language() -> None:
    assert status_key("PASS") == "pass"
    assert status_key("ADVISORY") == "warning"
    assert status_key("BLOCKER") == "fail"
    assert status_key("CANNOT VERIFY") == "neutral"
    assert WORKBOOK_THEME.header_bg == "000032"
