# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import report_log as log


def test_title_prints_plain_line(capsys):
    log.title("FillDB Performance")
    out = capsys.readouterr()
    assert out.out == "FillDB Performance\n"
    assert out.err == ""


def test_step_prefixes_dash(capsys):
    log.step("Extracting counters from BLG")
    assert capsys.readouterr().out == "- Extracting counters from BLG\n"


def test_detail_aligns_label_and_value(capsys):
    log.detail("Rows", 24)
    expected = "  " + "Rows".ljust(log.LABEL_WIDTH) + ": 24\n"
    assert capsys.readouterr().out == expected


def test_detail_without_value_is_indented_note(capsys):
    log.detail("Workbook includes")
    assert capsys.readouterr().out == "  Workbook includes\n"


def test_result_matches_detail(capsys):
    log.result("Word document", r"C:\out\report.docx")
    expected = (
        "  " + "Word document".ljust(log.LABEL_WIDTH) + r": C:\out\report.docx" + "\n"
    )
    assert capsys.readouterr().out == expected


def test_status_markers_match_orchestrator_vocabulary(capsys):
    log.ok("Analysis complete")
    log.warn("Collection window not supplied")
    out = capsys.readouterr().out
    assert out == "[OK] Analysis complete\n[WARNING] Collection window not supplied\n"


def test_error_goes_to_stderr(capsys):
    log.error("Could not read input file")
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == "[ERROR] Could not read input file\n"


def test_blank_prints_empty_line(capsys):
    log.blank()
    assert capsys.readouterr().out == "\n"


def test_markers_are_ascii_only():
    # The whole point is portable, banner-free output: no decorative rules and
    # no non-ASCII glyphs that could render as "?" on legacy Windows consoles.
    import inspect

    source = inspect.getsource(log)
    # The emitted markers must stay ASCII.
    for marker in ("[OK]", "[WARNING]", "[ERROR]", "- ", ": "):
        assert marker.isascii()
    assert source.isascii()
