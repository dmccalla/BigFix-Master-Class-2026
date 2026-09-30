# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zipfile import ZipFile

import filldb_perf_log as fpl
import get_filldb_performance as filldb_report

PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde"
    b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\xe2%\xb5"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _write_png(path: Path) -> Path:
    path.write_bytes(PNG_1X1)
    return path


def _log_line(
    ts: str, pid: int = 10880, msg: str = "GetReservedPropertyMap: 64 ms"
) -> str:
    return f"{ts} -- {pid} -- {msg}"


def _write_log(path: Path, first_ts: str, last_ts: str) -> Path:
    path.write_text(
        _log_line(first_ts)
        + "\n"
        + _log_line("Mon, 17 Nov 2025 11:40:00 -0500", msg="filler line")
        + "\n"
        + _log_line(last_ts, msg="UpdateMappings complete in: 177 ms")
        + "\n",
        encoding="utf-8",
    )
    return path


def test_filldb_chart_count_formatter_uses_full_comma_counts() -> None:
    assert filldb_report.format_count(143_428_334) == "143,428,334"
    assert filldb_report.format_count(124_502) == "124,502"


def test_filldb_chart_payload_colors_workload_bars_by_health(
    tmp_path: Path, monkeypatch
) -> None:
    captured = {}

    def fake_render_chart(chart, data, output_path):
        captured["chart"] = chart
        captured["data"] = data
        captured["output_path"] = output_path

    from Lib.Design import html_charts

    monkeypatch.setattr(html_charts, "render_chart", fake_render_chart)
    rows = [
        {
            "FillDB Object": "Fixlet Results:",
            "Count": "100",
            "Time (ms)": "600000",
            "Rate/s": "10",
            "Health Check": "100% Great",
        },
        {
            "FillDB Object": "Computer Administrators:",
            "Count": "1",
            "Time (ms)": "0",
            "Rate/s": "0",
            "Health Check": "0% Poor",
        },
        {
            "FillDB Object": "Long Property Results:",
            "Count": "50",
            "Time (ms)": "300000",
            "Rate/s": "10",
            "Health Check": "67% Good",
        },
    ]

    filldb_report.generate_filldb_chart(
        rows,
        tmp_path / "filldb.png",
        metadata={"duration": "1 hour"},
    )

    assert captured["chart"] == "filldb"
    bars = {item["label"]: item for item in captured["data"]["bars"]}
    assert bars["Fixlet Results"]["color"] == "#187A43"
    assert bars["Long Property Results"]["color"] == "#B45309"
    assert bars["Computer Administrators"]["color"] == "#C2410C"
    assert bars["Computer Administrators"]["width"] == "0.0%"
    assert all("dot" not in item for item in bars.values())


def test_filldb_word_places_score_method_note_below_chart(tmp_path: Path) -> None:
    output = tmp_path / "filldb.docx"
    chart = _write_png(tmp_path / "filldb.png")
    rows = [
        {
            "FillDB Object": "Fixlet results:",
            "Count": "143",
            "Time (ms)": "428",
            "Rate/s": "334",
            "Health Check": "100% Great",
        }
    ]

    filldb_report.write_word_output(
        rows,
        output,
        chart_path=chart,
        metadata={
            "generated": "07/31/2026 09:00",
            "start": "07/30/2026 09:00",
            "end": "07/30/2026 17:00",
            "duration": "8h 0m",
        },
    )

    with ZipFile(output) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")

    assert "How This Score Is Calculated" in xml
    assert '<w:pStyle w:val="Heading3"/>' in xml
    assert "Formula:" in xml
    assert "Great% x 100 + Good% x 67 + Poor% x 34" in xml
    assert "Health Check" in xml
    assert "100% Great" in xml
    assert "Analyzer Baseline" not in xml
    assert "analyzer baseline" not in xml
    assert "Capture Summary" in xml
    assert "Count" in xml
    assert "Time (ms)" in xml
    assert xml.index("How This Score Is Calculated") < xml.index("<w:tbl")


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def test_parse_log_timestamp_reads_leading_rfc2822_date():
    line = _log_line("Mon, 17 Nov 2025 11:36:12 -0500")
    parsed = fpl.parse_log_timestamp(line)
    assert parsed is not None
    assert (parsed.year, parsed.month, parsed.day) == (2025, 11, 17)
    assert (parsed.hour, parsed.minute, parsed.second) == (11, 36, 12)


def test_parse_log_timestamp_rejects_non_timestamp_lines():
    assert fpl.parse_log_timestamp("") is None
    assert fpl.parse_log_timestamp("not a timestamp -- 1 -- hi") is None
    assert fpl.parse_log_timestamp("FillDB Object,Count,Time (ms)") is None


# ---------------------------------------------------------------------------
# Analysis-CSV detection
# ---------------------------------------------------------------------------


def test_looks_like_analysis_csv_true_for_analyzer_output(tmp_path):
    csv = tmp_path / "perf.csv"
    csv.write_text(
        "FillDB Object,Count,Time (ms),Rate/s,Health Check\n"
        "Fixlet results:,143,428,334,----: Not enough data.\n",
        encoding="utf-8",
    )
    assert fpl.looks_like_analysis_csv(csv) is True


def test_looks_like_analysis_csv_false_for_raw_log(tmp_path):
    log = _write_log(
        tmp_path / "FillDBPerf.log",
        "Mon, 17 Nov 2025 11:36:12 -0500",
        "Mon, 17 Nov 2025 15:57:08 -0500",
    )
    assert fpl.looks_like_analysis_csv(log) is False


# ---------------------------------------------------------------------------
# Chronological ordering (the core correctness guarantee)
# ---------------------------------------------------------------------------


def test_order_log_files_uses_first_timestamp_not_filename(tmp_path):
    # Mirrors the real rollover set: the active suffixless file is NEWEST, the
    # numbered segments are older. A plain filename sort would put the active
    # file first (the legacy bug); timestamp ordering must not.
    active = _write_log(
        tmp_path / "FillDBPerf.log",
        "Mon, 17 Nov 2025 11:36:12 -0500",
        "Mon, 17 Nov 2025 15:57:08 -0500",
    )
    seg0 = _write_log(
        tmp_path / "FillDBPerf.log_0",
        "Sun, 16 Nov 2025 02:56:10 -0500",
        "Sun, 16 Nov 2025 08:27:06 -0500",
    )
    seg1 = _write_log(
        tmp_path / "FillDBPerf.log_1",
        "Sun, 16 Nov 2025 08:27:06 -0500",
        "Sun, 16 Nov 2025 13:50:13 -0500",
    )
    seg2 = _write_log(
        tmp_path / "FillDBPerf.log_2",
        "Sun, 16 Nov 2025 13:50:13 -0500",
        "Sun, 16 Nov 2025 19:14:47 -0500",
    )

    ordered = fpl.order_log_files([active, seg0, seg1, seg2])
    assert [p.name for p in ordered] == [
        "FillDBPerf.log_0",
        "FillDBPerf.log_1",
        "FillDBPerf.log_2",
        "FillDBPerf.log",
    ]


def test_order_log_files_falls_back_to_numeric_suffix(tmp_path):
    # No parseable timestamps -> numeric suffix order, active (base) last, and
    # 10 must sort after 2 (numeric, not lexical).
    names = ["X.log", "X.log_0", "X.log_2", "X.log_10"]
    for name in names:
        (tmp_path / name).write_text("no timestamps here\n", encoding="utf-8")
    ordered = fpl.order_log_files([tmp_path / n for n in names])
    assert [p.name for p in ordered] == ["X.log_0", "X.log_2", "X.log_10", "X.log"]


# ---------------------------------------------------------------------------
# Log-set discovery
# ---------------------------------------------------------------------------


def test_discover_log_set_from_file_gathers_rollover_siblings(tmp_path):
    for name in ("FillDBPerf.log", "FillDBPerf.log_0", "FillDBPerf.log_1"):
        (tmp_path / name).write_text(
            _log_line("Mon, 17 Nov 2025 11:36:12 -0500"), encoding="utf-8"
        )
    (tmp_path / "HEALTHCHECK_FILLDB_PERF_README.txt").write_text(
        "readme", encoding="utf-8"
    )

    found = fpl.discover_log_set(tmp_path / "FillDBPerf.log_0")
    assert {p.name for p in found} == {
        "FillDBPerf.log",
        "FillDBPerf.log_0",
        "FillDBPerf.log_1",
    }


def test_discover_log_set_from_folder_excludes_readme_and_csv(tmp_path):
    (tmp_path / "FillDBperf.log").write_text(
        _log_line("Mon, 17 Nov 2025 11:36:12 -0500"), encoding="utf-8"
    )
    (tmp_path / "HEALTHCHECK_FILLDB_PERF_README.txt").write_text(
        "readme", encoding="utf-8"
    )
    (tmp_path / "old_analysis.csv").write_text("FillDB Object,Count\n", encoding="utf-8")

    found = fpl.discover_log_set(tmp_path)
    assert [p.name for p in found] == ["FillDBperf.log"]


def test_discover_log_set_prefers_filldbperf_over_other_names(tmp_path):
    (tmp_path / "FillDBPerf.log").write_text("x", encoding="utf-8")
    (tmp_path / "FillDBPerf.log_0").write_text("x", encoding="utf-8")
    (tmp_path / "something_else.log").write_text("x" * 10_000, encoding="utf-8")

    found = fpl.discover_log_set(tmp_path)
    assert {p.name for p in found} == {"FillDBPerf.log", "FillDBPerf.log_0"}


def test_discover_log_set_uses_largest_set_for_nonstandard_name(tmp_path):
    # No "filldbperf" base present: the real capture is the largest group.
    (tmp_path / "stray.log").write_text("x", encoding="utf-8")
    (tmp_path / "capture.log").write_text("x" * 5000, encoding="utf-8")
    (tmp_path / "capture.log_0").write_text("x" * 5000, encoding="utf-8")

    found = fpl.discover_log_set(tmp_path)
    assert {p.name for p in found} == {"capture.log", "capture.log_0"}


# ---------------------------------------------------------------------------
# Window detection
# ---------------------------------------------------------------------------


def test_detect_window_from_logs_spans_full_capture(tmp_path):
    _write_log(
        tmp_path / "FillDBPerf.log",
        "Mon, 17 Nov 2025 11:36:12 -0500",
        "Mon, 17 Nov 2025 15:57:08 -0500",
    )
    _write_log(
        tmp_path / "FillDBPerf.log_0",
        "Sun, 16 Nov 2025 02:56:10 -0500",
        "Sun, 16 Nov 2025 08:27:06 -0500",
    )

    start, end = fpl.detect_window_from_logs(tmp_path)
    assert start == datetime(2025, 11, 16, 2, 56, 10)
    assert end == datetime(2025, 11, 17, 15, 57, 8)
    # Naive (tz stripped) to match the rest of the report's metadata handling.
    assert start.tzinfo is None and end.tzinfo is None


# ---------------------------------------------------------------------------
# ensure_analysis_csv (exe stubbed)
# ---------------------------------------------------------------------------


def test_ensure_analysis_csv_passes_through_existing_csv(tmp_path):
    csv = tmp_path / "perf.csv"
    csv.write_text("FillDB Object,Count\nFixlet results:,1\n", encoding="utf-8")
    result = fpl.ensure_analysis_csv(csv, exe=tmp_path / "fake.exe")
    assert result == csv


def test_ensure_analysis_csv_combines_in_order_and_writes_csv(tmp_path, monkeypatch):
    _write_log(
        tmp_path / "FillDBPerf.log",
        "Mon, 17 Nov 2025 11:36:12 -0500",
        "Mon, 17 Nov 2025 15:57:08 -0500",
    )
    _write_log(
        tmp_path / "FillDBPerf.log_0",
        "Sun, 16 Nov 2025 02:56:10 -0500",
        "Sun, 16 Nov 2025 08:27:06 -0500",
    )

    captured: dict[str, object] = {}

    def fake_run_analyzer(log_path, **_kwargs):
        text = Path(log_path).read_text(encoding="utf-8")
        captured["combined_text"] = text
        captured["combined_existed"] = Path(log_path).exists()
        return "FillDB Object,Count\nFixlet results:,1\n"

    monkeypatch.setattr(fpl, "run_analyzer", fake_run_analyzer)

    dest = tmp_path / "out" / "result.csv"
    dest.parent.mkdir()
    result = fpl.ensure_analysis_csv(tmp_path, dest_csv=dest, exe=tmp_path / "fake.exe")

    assert result == dest
    assert dest.read_text(encoding="utf-8").startswith("FillDB Object,Count")
    # The combined log must order the older segment before the active file.
    text = captured["combined_text"]
    assert text.index("02:56:10") < text.index("11:36:12")
    # Temp combined log is cleaned up; only the CSV remains.
    assert not list(dest.parent.glob("*_combined.tmp.log"))


def test_ensure_analysis_csv_single_file_does_not_combine(tmp_path, monkeypatch):
    log = _write_log(
        tmp_path / "FillDBperf.log",
        "Mon, 17 Nov 2025 11:36:12 -0500",
        "Mon, 17 Nov 2025 15:57:08 -0500",
    )

    seen: dict[str, Path] = {}

    def fake_run_analyzer(log_path, **_kwargs):
        seen["path"] = Path(log_path)
        return "FillDB Object,Count\nFixlet results:,1\n"

    monkeypatch.setattr(fpl, "run_analyzer", fake_run_analyzer)

    dest = tmp_path / "single.csv"
    fpl.ensure_analysis_csv(log, dest_csv=dest, exe=tmp_path / "fake.exe")
    # Single file is analyzed in place, not via a combined temp.
    assert seen["path"] == log


def test_ensure_analysis_csv_raises_when_no_logs(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    try:
        fpl.ensure_analysis_csv(empty, exe=tmp_path / "fake.exe")
    except ValueError as exc:
        assert "No FillDB performance logs" in str(exc)
    else:
        raise AssertionError("expected ValueError for empty folder")
