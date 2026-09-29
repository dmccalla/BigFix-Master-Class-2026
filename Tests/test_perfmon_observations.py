# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import inspect
import json
from collections import OrderedDict
from pathlib import Path
from zipfile import ZipFile

import get_perfmon_charts
import inject_perfmon_charts
import pandas as pd
from docx import Document

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
    b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00"
    b"\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA"
    b"\xe2!\xbc\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _relative_luminance(hex_color: str) -> float:
    channels = [int(hex_color[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linearize(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = [linearize(channel) for channel in channels]
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(foreground: str, background: str) -> float:
    lighter, darker = sorted(
        [_relative_luminance(foreground), _relative_luminance(background)],
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def test_build_perfmon_observations_marks_standard_met() -> None:
    findings = [
        {
            "Counter": "PhysicalDisk_Total_Avg_Disk_Queue_Length",
            "Status": "OK",
            "Average": 0.2,
            "Maximum": 0.7,
            "Violations": 0,
            "ViolationPercent": 0,
            "Warnings": 0,
            "WarningPercent": 0,
            "Samples": 100,
            "Threshold": "<= 1 per disk",
            "Confidence": "High",
            "PeakViolationWindow": "No threshold breach detected",
        }
    ]
    env_rows = [
        {"Setting": "Sample Start", "Value": "05/01/2026 10:00"},
        {"Setting": "Sample End", "Value": "05/01/2026 11:00"},
        {"Setting": "Sample Count", "Value": 100},
    ]

    observations = get_perfmon_charts.build_perfmon_observations(findings, env_rows)

    section = observations["sections"]["Storage Queue Depth"]
    assert section["status"] == "OK"
    assert "standard was met" in section["observation"]
    assert observations["summary"]["status_counts"]["OK"] == 1


def test_build_perfmon_observations_uses_readable_summary_and_priority_items() -> None:
    findings = [
        {
            "Counter": "PhysicalDisk_Total_Avg_Disk_ms_Transfer",
            "Status": "Critical",
            "Average": 42.0,
            "Maximum": 75.2,
            "Violations": 80,
            "ViolationPercent": 80,
            "Warnings": 0,
            "WarningPercent": 0,
            "Samples": 100,
            "Threshold": "<= 20 ms",
            "Confidence": "High",
            "PeakViolationWindow": "05/01/2026 10:00 - 05/01/2026 11:00",
        },
        {
            "Counter": "Processor_Total_Processor_Time",
            "Status": "Warning",
            "Average": 72.0,
            "Maximum": 88.0,
            "Violations": 0,
            "ViolationPercent": 0,
            "Warnings": 25,
            "WarningPercent": 25,
            "Samples": 100,
            "Threshold": "<= 70%",
            "Confidence": "High",
            "PeakViolationWindow": "No threshold breach detected",
        },
        {
            "Counter": "System_Processor_Queue_Length",
            "Status": "OK",
            "Average": 1.0,
            "Maximum": 2.0,
            "Violations": 0,
            "ViolationPercent": 0,
            "Warnings": 0,
            "WarningPercent": 0,
            "Samples": 100,
            "Threshold": "<= 32",
            "Confidence": "High",
            "PeakViolationWindow": "No threshold breach detected",
        },
    ]
    env_rows = [
        {"Setting": "Sample Start", "Value": "05/01/2026 10:00"},
        {"Setting": "Sample End", "Value": "05/01/2026 11:00"},
        {"Setting": "Sample Count", "Value": 100},
    ]

    observations = get_perfmon_charts.build_perfmon_observations(findings, env_rows)
    summary = observations["summary"]

    assert "counter(s)" not in " ".join(summary["lines"])
    assert "1 counter did not meet the NFR standard" in summary["lines"][0]
    assert "1 counter should be monitored" in summary["lines"][0]
    assert "1 counter was within standard" in summary["lines"][0]
    assert summary["lines"][-1] == "Highest-priority review items:"
    assert summary["priority_items"] == [
        "PhysicalDisk_Total_Avg_Disk_ms_Transfer - Critical; peak 75.2",
        "Processor_Total_Processor_Time - Warning; peak 88.0",
    ]


def test_short_threshold_text_removes_context_sentence() -> None:
    assert (
        get_perfmon_charts.short_threshold_text(
            "Paging File % Usage Peak should be <= 5%. Physical memory of the analyzed system: 96 GB."
        )
        == "<= 5%"
    )


def test_observation_uses_short_threshold_text_for_memory() -> None:
    findings = [
        {
            "Counter": "Paging_File_Total_Usage_Peak",
            "Status": "Critical",
            "Average": 8.1,
            "Maximum": 12.2,
            "Violations": 10,
            "ViolationPercent": 10,
            "Warnings": 0,
            "WarningPercent": 0,
            "Samples": 100,
            "Threshold": (
                "Paging File % Usage Peak should be <= 5%. "
                "Physical memory of the analyzed system: 96 GB."
            ),
            "Confidence": "High",
            "PeakViolationWindow": "07/01/2026 10:00 - 07/01/2026 11:00",
        }
    ]

    observations = get_perfmon_charts.build_perfmon_observations(findings, [])
    text = observations["sections"]["Memory Health"]["observation"]

    assert "(<= 5%)" in text
    assert "Physical memory" not in text


def test_perfmon_status_colors_meet_wcag_aa_contrast() -> None:
    for status in ("OK", "Warning", "Critical", "Not Available"):
        assert (
            _contrast_ratio(inject_perfmon_charts.status_color(status), "FFFFFF") >= 4.5
        )
    assert _contrast_ratio("FFFFFF", "000032") >= 4.5
    assert _contrast_ratio("000032", "FFFFFF") >= 4.5
    # CHART_* are graphical chart marks (bars, dots, fills), not body text, so
    # WCAG 1.4.11 (non-text contrast) applies: the bar is the official brand
    # status color and must clear 3:1, not the 4.5:1 normal-text bar. Small
    # status TEXT keeps the 4.5:1 check above via status_color().
    for color in (
        inject_perfmon_charts.CHART_PASS,
        inject_perfmon_charts.CHART_ADVISORY,
        inject_perfmon_charts.CHART_FAIL,
        inject_perfmon_charts.CHART_CANNOT,
    ):
        assert _contrast_ratio(color.lstrip("#"), "FFFFFF") >= 3.0


def test_perfmon_nfr_thresholds_match_documented_perfmon_standards() -> None:
    assert (
        get_perfmon_charts.get_threshold(
            "System_Processor_Queue_Length", logical_processors=32
        )["critical"]
        == 4
    )
    assert (
        get_perfmon_charts.get_threshold("Processor_Total_Processor_Time", vm=False)[
            "critical"
        ]
        == 80
    )
    assert (
        get_perfmon_charts.get_threshold("Processor_Total_Processor_Time", vm=True)["min"]
        == 50
    )
    assert (
        get_perfmon_charts.get_threshold("Processor_Total_Privileged_Time")["critical"]
        == 10
    )
    assert (
        get_perfmon_charts.get_threshold("Paging_File_Total_Usage_Peak")["critical"] == 5
    )
    assert (
        get_perfmon_charts.get_threshold(
            "Network_Interface_1_Packets_Outbound_Discarded"
        )["critical"]
        == 0
    )
    assert (
        get_perfmon_charts.get_threshold("Network_Interface_1_Packets_Outbound_Errors")[
            "critical"
        ]
        == 0
    )
    assert (
        get_perfmon_charts.get_threshold(
            "Network_Interface_1_Packets_Received_Discarded"
        )["critical"]
        == 0
    )
    assert (
        get_perfmon_charts.get_threshold("Network_Interface_1_Packets_Received_Errors")[
            "critical"
        ]
        == 0
    )
    assert (
        get_perfmon_charts.get_threshold("PhysicalDisk_Total_Disk_Transfers_sec")["type"]
        == "informational"
    )


def test_packet_counter_analysis_uses_non_negative_sample_increases() -> None:
    counter = "Network_Interface_1_Packets_Received_Discarded"
    raw = pd.Series([100, 100, 103, 101, 108], dtype="float64")

    analyzed = get_perfmon_charts.counter_analysis_series(raw, counter)

    assert pd.isna(analyzed.iloc[0])
    assert analyzed.iloc[1] == 0
    assert analyzed.iloc[2] == 3
    assert pd.isna(analyzed.iloc[3])
    assert analyzed.iloc[4] == 7


def test_analyze_reports_packet_increases_not_cumulative_values() -> None:
    counter = "Network_Interface_1_Packets_Received_Discarded"
    df = pd.DataFrame(
        {
            "Time": pd.date_range("2026-08-18 07:52:00", periods=5, freq="min"),
            counter: [100, 100, 103, 101, 108],
        }
    )

    chart_df, findings = get_perfmon_charts.analyze(
        df,
        [counter],
        memory_gb=0,
        disk_count=0,
        vm=False,
        rolling_window=10,
        pct=0.98,
        pad=1.15,
        sample_start_str="08-18-2026 07:52",
        sample_end_str="08-18-2026 07:56",
        mem_src="Parameter Supplied",
        cpu_src="Parameter Supplied",
        disk_src="Parameter Supplied",
    )

    finding = findings[0]
    assert finding["Status"] == "Critical"
    assert finding["Average"] == 3.33
    assert finding["Maximum"] == 7.0
    assert finding["Samples"] == 3
    assert finding["Violations"] == 2
    values = chart_df[counter].tolist()
    assert pd.isna(values[0])
    assert values[1:3] == [0.0, 3.0]
    assert pd.isna(values[3])
    assert values[4] == 7.0


def test_blank_counter_is_cannot_verify_instead_of_disappearing() -> None:
    counter = "Paging_File_Total_Usage_Peak"
    df = pd.DataFrame(
        {
            "Time": pd.date_range("2026-08-18 07:52:00", periods=2, freq="min"),
            counter: [None, None],
        }
    )

    _chart_df, findings = get_perfmon_charts.analyze(
        df,
        [counter],
        memory_gb=384,
        disk_count=0,
        vm=False,
        rolling_window=10,
        pct=0.98,
        pad=1.15,
        sample_start_str="08-18-2026 07:52",
        sample_end_str="08-18-2026 07:53",
        mem_src="Parameter Supplied",
        cpu_src="Parameter Supplied",
        disk_src="Parameter Supplied",
    )

    assert findings[0]["Status"] == "Not Available"
    assert findings[0]["Samples"] == 0
    observations = get_perfmon_charts.build_perfmon_observations(
        findings,
        [
            {"Setting": "Analyzed System", "Value": "BFAPP01"},
            {"Setting": "Sample Count", "Value": 2},
        ],
    )
    assert observations["sections"]["Memory Health"]["status"] == "Not Available"
    assert (
        "No samples were recorded"
        in observations["sections"]["Memory Health"]["observation"]
    )
    assert observations["summary"]["status_counts"]["Not Available"] == 1


def test_zero_counter_text_distinguishes_valid_zero_from_missing_data() -> None:
    assert get_perfmon_charts.zero_counter_strip_text(
        "Paging_File_Total_Usage_Peak", True
    ) == ("0% page-file usage recorded", "PASS", "#1F8A5B")
    assert get_perfmon_charts.zero_counter_strip_text(
        "Paging_File_Total_Usage_Peak", False
    ) == ("No samples recorded", "CANNOT VERIFY", "#595959")


def test_export_and_load_perfmon_observations(tmp_path: Path) -> None:
    expected = {
        "schema_version": 1,
        "summary": {"lines": ["All reviewed counters met the standard."]},
        "sections": {},
    }

    path = get_perfmon_charts.export_perfmon_observations(expected, tmp_path)
    loaded = inject_perfmon_charts.load_perfmon_observations(tmp_path)

    assert path == tmp_path / "perfmon_observations.json"
    assert json.loads(path.read_text(encoding="utf-8")) == expected
    assert loaded == expected


def test_perfmon_png_axis_max_prioritizes_readability() -> None:
    low_standard = get_perfmon_charts.perfmon_chart_axis_max(32.9, {"critical": 10})
    high_standard = get_perfmon_charts.perfmon_chart_axis_max(32.9, {"critical": 80})

    assert round(low_standard, 3) == 41.125
    assert round(high_standard, 3) == 65.8


def test_perfmon_time_window_phrase_uses_compact_duration() -> None:
    times = pd.Series(pd.to_datetime(["2026-07-30 20:18:00", "2026-07-30 21:17:00"]))

    assert get_perfmon_charts.time_window_phrase(times) == "59 min"


def test_perfmon_hosts_are_detected_from_raw_counter_paths() -> None:
    hosts = get_perfmon_charts.perfmon_hosts_from_columns(
        [
            "(PDH-CSV 4.0) (Eastern Daylight Time)(240)",
            r"\\BFAPP01\Processor(_Total)\% Processor Time",
            r"\\BFSQL01\PhysicalDisk(_Total)\Avg. Disk sec/Transfer",
            r"\\bfapp01\System\Processor Queue Length",
        ]
    )

    assert hosts == ["BFAPP01", "BFSQL01"]
    assert get_perfmon_charts.perfmon_host_label(hosts) == (
        "Multiple hosts: BFAPP01, BFSQL01"
    )


def test_perfmon_loader_preserves_analyzed_system_label(tmp_path: Path) -> None:
    csv_path = tmp_path / "perfmon.csv"
    csv_path.write_text(
        "\n".join(
            [
                '"(PDH-CSV 4.0) (Eastern Daylight Time)(240)","\\\\BFAPP01\\Processor(_Total)\\% Processor Time"',
                '"07/30/2026 20:18:00.000","12.5"',
                '"07/30/2026 20:19:00.000","13.5"',
            ]
        ),
        encoding="utf-8",
    )

    df, counter_cols = get_perfmon_charts.load_and_normalize(str(csv_path))

    assert df.attrs["perfmon_hosts"] == ["BFAPP01"]
    assert df.attrs["perfmon_host_label"] == "BFAPP01"
    assert counter_cols == ["Processor_Total_Processor_Time"]


def test_perfmon_loader_keeps_multi_host_counter_names_unique(tmp_path: Path) -> None:
    csv_path = tmp_path / "multi_host_perfmon.csv"
    csv_path.write_text(
        "\n".join(
            [
                '"(PDH-CSV 4.0) (Eastern Daylight Time)(240)","\\\\BFAPP01\\Processor(_Total)\\% Processor Time","\\\\BFSQL01\\Processor(_Total)\\% Processor Time"',
                '"07/30/2026 20:18:00.000","12.5","92.0"',
                '"07/30/2026 20:19:00.000","13.5","93.0"',
            ]
        ),
        encoding="utf-8",
    )

    df, counter_cols = get_perfmon_charts.load_and_normalize(str(csv_path))

    assert df.attrs["perfmon_hosts"] == ["BFAPP01", "BFSQL01"]
    assert df.attrs["perfmon_host_label"] == "Multiple hosts: BFAPP01, BFSQL01"
    assert counter_cols == [
        "BFAPP01_Processor_Total_Processor_Time",
        "BFSQL01_Processor_Total_Processor_Time",
    ]
    assert df.columns.is_unique
    assert list(df[counter_cols[0]]) == [12.5, 13.5]
    assert list(df[counter_cols[1]]) == [92.0, 93.0]


def test_perfmon_chart_title_includes_analyzed_system() -> None:
    assert get_perfmon_charts.perfmon_chart_title(
        "Processor_Total_Processor_Time",
        "07/30/2026 20:18 - 07/30/2026 21:17",
        "BFAPP01",
    ) == (
        "Processor_Total_Processor_Time\n"
        "System: BFAPP01 | Capture window: 07/30/2026 20:18 - 07/30/2026 21:17"
    )
    assert (
        get_perfmon_charts.perfmon_context_line(
            "07/30/2026 20:18 - 07/30/2026 21:17",
            "BFSQL01",
        )
        == "System: BFSQL01  |  Capture window: 07/30/2026 20:18 - 07/30/2026 21:17"
    )


def test_perfmon_png_timeseries_layout_rules_are_in_source() -> None:
    source = inspect.getsource(get_perfmon_charts.export_png_charts)

    assert 'DateFormatter("%H:%M")' in source
    assert "rotation=0" in source
    assert 'set_xlabel("Time"' not in source
    assert 'set_ylabel("Value"' not in source
    assert 'label="_nolegend_"' in source
    assert "ncol=min(2, len(handles))" in source
    assert "render_zero_counter_strip" in source
    assert "perfmon_chart_title" in source
    assert "host_name" in source


def test_zero_perfmon_counter_exports_compact_strip(tmp_path: Path) -> None:
    counter = "Network_Interface_1_Packets_Received_Errors"
    df = pd.DataFrame(
        {
            "Time": pd.to_datetime(["2026-07-30 20:18:00", "2026-07-30 21:17:00"]),
            counter: [0, 0],
        }
    )
    findings = [{"Counter": counter, "Status": "OK"}]

    get_perfmon_charts.export_png_charts(
        df,
        [counter],
        findings,
        str(tmp_path),
        rolling_window=10,
        pct=0.98,
        pad=1.15,
        sample_start_str="07/30/2026 20:18",
        sample_end_str="07/30/2026 21:17",
    )

    data = (tmp_path / f"{counter}.png").read_bytes()
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")

    assert width > 2000
    assert height < 300


def test_long_network_interface_counter_exports_with_portable_filename(
    tmp_path: Path,
) -> None:
    counter = (
        "Network_Interface_Broadcom_NetXtreme_E-Series_Advanced_Dual-port_25Gb_"
        "SFP28_Ethernet_OCP_3_0_Adapter_2_Packets_Outbound_Discarded"
    )
    df = pd.DataFrame(
        {
            "Time": pd.to_datetime(["2026-08-18 07:52:00", "2026-08-18 07:53:00"]),
            counter: [0, 0],
        }
    )
    findings = [{"Counter": counter, "Status": "OK"}]

    chart_folder = tmp_path / ("chart-output-" + ("x" * 60))
    chart_folder.mkdir()

    get_perfmon_charts.export_png_charts(
        df,
        [counter],
        findings,
        str(chart_folder),
        rolling_window=10,
        pct=0.98,
        pad=1.15,
        sample_start_str="08/18/2026 07:52",
        sample_end_str="08/18/2026 07:53",
        host_name="USORDU102PWX1AP",
    )

    charts = list(chart_folder.glob("*.png"))
    assert len(charts) == 1
    assert len(str(charts[0])) <= 240
    assert "Packets_Outbound_Discarded" in charts[0].name
    assert charts[0].stat().st_size > 0


def test_export_perfmon_png_charts_clears_stale_images(tmp_path: Path) -> None:
    stale_chart = tmp_path / "PhysicalDisk_Total_Current_Disk_Queue_Length.png"
    stale_chart.write_bytes(_TINY_PNG)
    counter = "Processor_Total_Processor_Time"
    df = pd.DataFrame(
        {
            "Time": pd.to_datetime(["2026-07-30 20:18:00", "2026-07-30 21:17:00"]),
            counter: [12.5, 13.5],
        }
    )
    findings = [{"Counter": counter, "Status": "OK"}]

    get_perfmon_charts.export_png_charts(
        df,
        [counter],
        findings,
        str(tmp_path),
        rolling_window=10,
        pct=0.98,
        pad=1.15,
        sample_start_str="07/30/2026 20:18",
        sample_end_str="07/30/2026 21:17",
        host_name="BFAPP01",
    )

    assert not stale_chart.exists()
    assert (tmp_path / f"{counter}.png").exists()


def test_replace_observation_placeholders_updates_perfmon_section() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Observation: Your observations go here.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    observations = {
        "sections": {
            "Storage Queue Depth": {
                "status": "OK",
                "observation": "The standard was met throughout the sample window.",
            }
        }
    }

    updated = inject_perfmon_charts.replace_observation_placeholders(
        doc_xml, observations
    )

    assert "Your observations go here" not in updated
    assert "The standard was met throughout the sample window." in updated
    assert "Observation:" in updated
    assert "\u2713" in updated


def test_insert_perfmon_summary_adds_simple_status_table() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Appendix D: PerfMon Counters Data</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>General Observations</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    observations = {
        "summary": {
            "lines": ["PerfMon analysis found one counter area outside standard."]
        },
        "sections": {
            "Storage Queue Depth": {
                "status": "Critical",
                "threshold": "<= 1 per physical device",
                "average": 1.2,
                "maximum": 2.4,
                "violations": 3,
                "warnings": 0,
            }
        },
    }

    updated = inject_perfmon_charts.insert_perfmon_summary(doc_xml, observations)

    assert "<w:tbl>" in updated
    assert "Area" in updated
    assert "Storage Queue Depth" in updated
    assert "\u2717 Fail" in updated
    assert '<w:tblStyle w:val="BigFixContent"/>' in updated
    assert '<w:tblLook w:val="04A0"' in updated


def test_insert_perfmon_summary_adds_summary_after_perfmon_heading() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>General Observations</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Existing general note.</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    observations = {
        "summary": {"lines": ["PerfMon analysis found all counters within standard."]}
    }

    updated = inject_perfmon_charts.insert_perfmon_summary(doc_xml, observations)

    assert "PerfMon Infrastructure Summary" not in updated
    assert "PerfMon analysis found all counters within standard." in updated
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) > updated.index("General Observations")
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) > updated.index("Existing general note.")
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) < updated.index("Storage Queue Depth")


def test_insert_perfmon_summary_skips_toc_perfmon_entry() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:r><w:instrText>TOC \\o "1-3"</w:instrText></w:r></w:p>'
        "<w:p><w:r><w:instrText>PAGEREF _Toc123 \\h</w:instrText></w:r>"
        "<w:r><w:t>Perfmon Infrastructure Analysis</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>Appendix D: PerfMon Counters Data</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>General Observations</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    observations = {
        "summary": {"lines": ["PerfMon analysis found all counters within standard."]}
    }

    updated = inject_perfmon_charts.insert_perfmon_summary(doc_xml, observations)

    assert "PerfMon Infrastructure Summary" not in updated
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) > updated.index("General Observations")
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) < updated.index("Storage Queue Depth")


def test_insert_perfmon_summary_handles_word_split_perfmon_heading_runs() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        '<w:r><w:t xml:space="preserve">Appendix </w:t></w:r>'
        "<w:r><w:t>D</w:t></w:r>"
        '<w:r><w:t xml:space="preserve">: </w:t></w:r>'
        "<w:r><w:t>Perf</w:t></w:r><w:r><w:t>M</w:t></w:r><w:r><w:t>on</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> Counters Data</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>General Observations</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    observations = {
        "summary": {"lines": ["PerfMon analysis found all counters within standard."]}
    }

    updated = inject_perfmon_charts.insert_perfmon_summary(doc_xml, observations)

    assert "PerfMon Infrastructure Summary" not in updated
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) > updated.index("General Observations")
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) < updated.index("Storage Queue Depth")


def test_insert_perfmon_summary_ignores_root_server_check_perfmon_text() -> None:
    doc_xml = (
        "<w:document><w:body>"
        "<w:tbl><w:tr>"
        "<w:tc><w:p><w:r><w:t>Run PerfMon using the BFPerf counter set and capture data for 24 hours. "
        "Review the results.</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>To view the full analysis please refer to Appendix E: Perfmon Counters Data</w:t></w:r></w:p></w:tc>"
        "</w:tr></w:tbl>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Appendix D: PerfMon Counters Data</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>General Observations</w:t></w:r></w:p>'
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr><w:r><w:t>Storage Queue Depth</w:t></w:r></w:p>'
        "</w:body></w:document>"
    )
    observations = {
        "summary": {"lines": ["PerfMon analysis found all counters within standard."]}
    }

    updated = inject_perfmon_charts.insert_perfmon_summary(doc_xml, observations)

    assert "PerfMon Infrastructure Summary" not in updated
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) > updated.index("General Observations")
    assert updated.index(
        "PerfMon analysis found all counters within standard."
    ) < updated.index("Storage Queue Depth")


def test_perfmon_summary_renders_priority_items_as_bullets() -> None:
    observations = {
        "summary": {
            "lines": [
                "PerfMon analysis reviewed 3 counters across the captured sample window. "
                "1 counter did not meet the NFR standard; 0 counters should be monitored; "
                "2 counters were within standard.",
                "Sample window: 2026-06-01 to 2026-06-02 across 1440 samples.",
                "Highest-priority review items:",
            ],
            "priority_items": [
                "PhysicalDisk_Total_Avg_Disk_ms_Transfer - Critical; peak 75.2",
                "Paging_File_Total_Usage_Peak - Critical; peak 88.2",
            ],
        },
        "sections": {},
    }

    xml = inject_perfmon_charts.build_summary_xml(observations)

    assert "Highest-priority review items:" in xml
    assert "• " in xml
    assert "PhysicalDisk_Total_Avg_Disk_ms_Transfer - Critical; peak 75.2" in xml
    assert "Paging_File_Total_Usage_Peak - Critical; peak 88.2" in xml


def test_perfmon_summary_renders_supplied_hardware_context() -> None:
    observations = {
        "environment": {
            "Analyzed System": "BFTEST01",
            "Analyzed System Physical Memory (GB)": 64,
            "Physical Memory Source": "Parameter Supplied",
            "Logical Processor Count": 32,
            "Logical Processor Source": "Parameter Supplied",
            "Physical Disk Count": 4,
            "Physical Disk Source": "Parameter Supplied",
            "Virtual Machine": False,
            "Sample Start": "08-18-2026 07:52",
            "Sample End": "08-19-2026 07:01",
            "Sample Count": 1390,
        },
        "summary": {"lines": ["PerfMon analysis completed."]},
        "sections": {},
    }

    xml = inject_perfmon_charts.build_summary_xml(observations)

    assert "PerfMon Hardware Context" in xml
    assert "BFTEST01" not in xml
    assert "Capture Window" not in xml
    assert "1390" not in xml
    assert "64 GB (User supplied)" in xml
    assert "32 (User supplied)" in xml
    assert "4 (User supplied)" in xml
    assert "No" in xml


def test_perfmon_observation_calls_out_affected_counters() -> None:
    section = {
        "status": "Critical",
        "observation": "The standard was not met.",
        "counters_detail": [
            {
                "counter": "Network_Interface_X710_Packets_Received_Discarded",
                "status": "Critical",
                "average": 10.53,
                "maximum": 6102,
                "violations": 66,
                "violation_percent": 1.39,
            },
            {
                "counter": "Network_Interface_X710_Packets_Outbound_Discarded",
                "status": "OK",
                "average": 0,
                "maximum": 0,
            },
        ],
    }

    xml = inject_perfmon_charts.observation_paragraph_xml(section)

    assert "Affected Counters Requiring Review" in xml
    assert "Network_Interface_X710_Packets_Received_Discarded" in xml
    assert "peak 6102" in xml
    assert "66 readings (1.39%) above the standard" in xml
    assert "Network_Interface_X710_Packets_Outbound_Discarded" not in xml


def test_dedup_docpr_ids_preserves_valid_id_attribute() -> None:
    doc_xml = (
        '<w:p><wp:docPr id="1" name="Existing"/></w:p>'
        '<w:p><wp:docPr id="1" name="Duplicate"/></w:p>'
    )

    updated = inject_perfmon_charts._dedup_docpr_ids(doc_xml)

    assert 'id="id="' not in updated
    assert '<wp:docPr id="1" name="Existing"/>' in updated
    assert '<wp:docPr id="2" name="Duplicate"/>' in updated


def test_perfmon_scorecard_aggregation_uses_report_sections() -> None:
    observations = {
        "sections": {
            "Storage Queue Depth": {"status": "Critical"},
            "Storage Latency": {"status": "Warning"},
            "Storage Operations": {"status": "OK"},
            "CPU Utilization": {"status": "OK"},
            "Memory Health": {"status": "Not Available"},
            "Unmapped Section": {"status": "Critical"},
        }
    }

    rows = inject_perfmon_charts.aggregate_perfmon_scorecard(observations)

    assert list(rows) == list(inject_perfmon_charts.SECTION_COUNTER_MAP.keys())
    assert rows["Storage Queue Depth"]["FAIL"] == 1
    assert rows["Storage Latency"]["ADVISORY"] == 1
    assert rows["Storage Operations"]["PASS"] == 1
    assert rows["CPU Utilization"]["PASS"] == 1
    assert rows["Memory Health"]["CANNOT VERIFY"] == 1
    assert sum(rows["CPU Latency"].values()) == 0


def _run_perfmon_charts_on_csv(csv_path: Path, out_xlsx: Path) -> Path:
    """Run the real chart pipeline on a relog-style CSV. Returns the charts
    folder. Uses a subprocess so the test exercises exactly what a build
    runs."""
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "Get" / "get_perfmon_charts.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--input",
            str(csv_path),
            "--output",
            str(out_xlsx),
            "--memory-gb",
            "16",
            "--processors",
            "4",
            "--disks",
            "2",
            "--virtual-machine",
            "--skip-docx",
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return out_xlsx.parent / (out_xlsx.stem + "_Charts")


def _write_relog_csv(csv_path: Path, counters: dict[str, list[float]]) -> None:
    header = ['"(PDH-CSV 4.0) (Eastern Daylight Time)(240)"'] + [
        f'"{name}"' for name in counters
    ]
    rows = [",".join(header)]
    length = len(next(iter(counters.values())))
    for index in range(length):
        stamp = f"06/14/2026 20:{17 + index // 60:02d}:{index % 60:02d}.000"
        values = [f'"{series[index]}"' for series in counters.values()]
        rows.append(",".join([f'"{stamp}"'] + values))
    csv_path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_distinct_drive_measurements_produce_distinct_graphs(tmp_path) -> None:
    """Regression: two measured drive series must yield two different PNG
    files, and the injector must select both for the queue-depth section.
    Guards against any change that reuses one visual for several drives."""
    import hashlib

    quiet = [0.0, 1.0] * 15
    busy = [float(2 + (index % 3)) for index in range(30)]
    csv_path = tmp_path / "two_drives.csv"
    _write_relog_csv(
        csv_path,
        {
            r"\\BFTEST\PhysicalDisk(0 C:)\Current Disk Queue Length": quiet,
            r"\\BFTEST\PhysicalDisk(1 E:)\Current Disk Queue Length": busy,
        },
    )
    charts = _run_perfmon_charts_on_csv(csv_path, tmp_path / "two_drives.xlsx")

    png_c = charts / "PhysicalDisk_0_C_Current_Disk_Queue_Length.png"
    png_e = charts / "PhysicalDisk_1_E_Current_Disk_Queue_Length.png"
    assert png_c.is_file(), sorted(p.name for p in charts.glob("*.png"))
    assert png_e.is_file(), sorted(p.name for p in charts.glob("*.png"))
    digest_c = hashlib.sha256(png_c.read_bytes()).hexdigest()
    digest_e = hashlib.sha256(png_e.read_bytes()).hexdigest()
    assert digest_c != digest_e, "two measured drives rendered identical graphs"

    png_files = inject_perfmon_charts.scan_chart_folder(charts)
    pattern_to_pngs = inject_perfmon_charts.map_patterns_to_pngs(png_files)
    by_section = inject_perfmon_charts.section_pngs_for_append(pattern_to_pngs)
    queue_pngs = [p.name for p in by_section.get("Storage Queue Depth", [])]
    assert png_c.name in queue_pngs
    assert png_e.name in queue_pngs


def test_physical_disk_instances_chart_separately(tmp_path) -> None:
    """Regression: distinct PhysicalDisk measurements must each produce their
    own graph, and the injector must select all physical disks for queue depth."""
    import hashlib

    series = {
        r"\\BFTEST\PhysicalDisk(0 C:)\Current Disk Queue Length": [0.0, 1.0] * 15,
        r"\\BFTEST\PhysicalDisk(6 E:)\Current Disk Queue Length": [
            float(2 + (index % 3)) for index in range(30)
        ],
        r"\\BFTEST\PhysicalDisk(2 F: S: S:)\Current Disk Queue Length": [
            float(index % 5) for index in range(30)
        ],
    }
    csv_path = tmp_path / "physical_disks.csv"
    _write_relog_csv(csv_path, series)
    charts = _run_perfmon_charts_on_csv(csv_path, tmp_path / "physical_disks.xlsx")

    names = [
        "PhysicalDisk_0_C_Current_Disk_Queue_Length.png",
        "PhysicalDisk_6_E_Current_Disk_Queue_Length.png",
        "PhysicalDisk_2_F_S_S_Current_Disk_Queue_Length.png",
    ]
    digests = set()
    for name in names:
        png = charts / name
        assert png.is_file(), sorted(p.name for p in charts.glob("*.png"))
        digests.add(hashlib.sha256(png.read_bytes()).hexdigest())
    assert len(digests) == 3, (
        "distinct physical disk measurements rendered identical graphs"
    )

    png_files = inject_perfmon_charts.scan_chart_folder(charts)
    by_section = inject_perfmon_charts.section_pngs_for_append(
        inject_perfmon_charts.map_patterns_to_pngs(png_files)
    )
    queue_pngs = [p.name for p in by_section.get("Storage Queue Depth", [])]
    for name in names:
        assert name in queue_pngs


def test_combined_disk_instance_is_not_cloned_per_drive(tmp_path) -> None:
    """Regression: one measured series for a combined instance (one physical
    disk hosting several volumes) must produce exactly one graph, never
    per-drive copies of the same visual."""
    values = [float(index % 4) for index in range(30)]
    csv_path = tmp_path / "combined.csv"
    _write_relog_csv(
        csv_path,
        {r"\\BFTEST\PhysicalDisk(0 C: E: F:)\Current Disk Queue Length": values},
    )
    charts = _run_perfmon_charts_on_csv(csv_path, tmp_path / "combined.xlsx")

    queue_pngs = sorted(p.name for p in charts.glob("*Current_Disk_Queue_Length*.png"))
    assert queue_pngs == ["PhysicalDisk_0_C_E_F_Current_Disk_Queue_Length.png"], (
        queue_pngs
    )


def test_perfmon_section_alias_finds_storage_operations_heading() -> None:
    assert (
        inject_perfmon_charts.perfmon_section_key_for_text(
            "Disk Transfers/sec (By Drive / Physical)"
        )
        == "Storage Operations"
    )


def test_perfmon_duplicate_placeholder_rids_are_tracked_by_occurrence() -> None:
    doc_xml = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>'
        "<w:r><w:t>Storage Latency</w:t></w:r></w:p>"
        '<w:p><w:r><w:drawing><a:blip r:embed="rId24"/>'
        "</w:drawing></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>'
        "<w:r><w:t>Storage Operations</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading4"/></w:pPr>'
        "<w:r><w:t>Disk Transfers/sec (By Drive / Physical)</w:t></w:r></w:p>"
        '<w:p><w:r><w:drawing><a:blip r:embed="rId24"/>'
        "</w:drawing></w:r></w:p>"
    )
    rels_xml = (
        "<Relationships>"
        '<Relationship Id="rId24" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/image24.tiff"/>'
        "</Relationships>"
    )

    section_rids, _insert_points, _media = (
        inject_perfmon_charts.discover_perfmon_sections(doc_xml, rels_xml)
    )

    latency_token = section_rids["Storage Latency"][0]
    operations_token = section_rids["Storage Operations"][0]
    assert latency_token != operations_token
    assert inject_perfmon_charts.split_placeholder_token(latency_token)[0] == "rId24"
    assert inject_perfmon_charts.split_placeholder_token(operations_token)[0] == "rId24"

    pattern_to_pngs = OrderedDict(
        (pattern, [])
        for patterns in inject_perfmon_charts.SECTION_COUNTER_MAP.values()
        for pattern in patterns
    )
    pattern_to_pngs["*PhysicalDisk_*_Avg_Disk_ms_Transfer*"] = [Path("latency.png")]
    pattern_to_pngs["*PhysicalDisk_*_Disk_Transfers_sec*"] = [Path("operations.png")]

    mapped, extras = inject_perfmon_charts.build_rid_to_png_map(
        section_rids, pattern_to_pngs
    )

    assert mapped[latency_token] == Path("latency.png")
    assert mapped[operations_token] == Path("operations.png")
    assert not extras


def test_perfmon_discovery_stops_before_about_bigfix_images() -> None:
    doc_xml = (
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading3"/></w:pPr>'
        "<w:r><w:t>Network Health</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'
        "<w:r><w:t>About BigFix</w:t></w:r></w:p>"
        '<w:p><w:r><w:drawing><a:blip r:embed="rId24"/>'
        "</w:drawing></w:r></w:p>"
    )
    rels_xml = (
        "<Relationships>"
        '<Relationship Id="rId24" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" '
        'Target="media/about-bigfix.png"/>'
        "</Relationships>"
    )

    section_rids, _insert_points, _media = (
        inject_perfmon_charts.discover_perfmon_sections(doc_xml, rels_xml)
    )

    assert section_rids["Network Health"] == []


def test_relationship_id_to_media_accepts_word_target_variants() -> None:
    rels_xml = """
    <Relationships>
      <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/image1.png"/>
      <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image2.tiff"/>
      <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="word/media/image3.jpeg"/>
    </Relationships>
    """

    assert inject_perfmon_charts.relationship_id_to_media(rels_xml) == {
        "rId1": "image1.png",
        "rId2": "image2.tiff",
        "rId3": "image3.jpeg",
    }


def test_perfmon_scorecard_score_and_rating() -> None:
    counts = {"PASS": 2, "ADVISORY": 1, "FAIL": 1, "CANNOT VERIFY": 0}

    score = inject_perfmon_charts.perfmon_section_score(counts)

    assert score == 64
    assert inject_perfmon_charts.perfmon_rating(score)[0] == "Needs Attention"
    assert (
        inject_perfmon_charts.perfmon_section_score(
            {"PASS": 0, "ADVISORY": 0, "FAIL": 0, "CANNOT VERIFY": 0}
        )
        is None
    )
    assert inject_perfmon_charts.perfmon_rating(None)[0] == "Not Scored"


def test_perfmon_section_source_id_maps_counter_areas() -> None:
    assert (
        inject_perfmon_charts.perfmon_section_source_id("Storage Latency") == "PRF-INF-02"
    )
    assert (
        inject_perfmon_charts.perfmon_section_source_id("CPU Privileged Time")
        == "PRF-INF-06"
    )
    assert (
        inject_perfmon_charts.perfmon_section_source_id("Memory Health") == "PRF-INF-09"
    )


def test_perfmon_scorecard_payload_carries_finding_summary(
    monkeypatch, tmp_path: Path
) -> None:
    from Lib.Design import html_charts

    captured: dict[str, object] = {}

    def fake_render_chart(chart, data, output_path):
        captured["chart"] = chart
        captured["data"] = data
        Path(output_path).write_bytes(_TINY_PNG)

    monkeypatch.setattr(html_charts, "render_chart", fake_render_chart)

    output = tmp_path / "perfmon.png"
    result = inject_perfmon_charts.render_perfmon_scorecard(
        {
            "sections": {
                "CPU Utilization": {
                    "section": "CPU Utilization",
                    "status": "OK",
                    "average": 22,
                    "threshold": "<= 80%",
                },
                "Disk Latency": {
                    "section": "Disk Latency",
                    "status": "Critical",
                    "average": 24,
                    "threshold": "<= 20 ms",
                },
                "Memory Health": {
                    "section": "Memory Health",
                    "status": "Warning",
                    "average": 8,
                    "threshold": "<= 5%",
                },
            }
        },
        output,
    )

    assert result == output
    assert captured["chart"] == "perfmon"
    data = captured["data"]
    assert data["findingsSummary"] == {"total": 2, "critical": 1, "warning": 1}
    assert data["findingIds"] == ["PRF-INF-02", "PRF-INF-09"]


def test_insert_perfmon_scorecard_skips_toc_entry() -> None:
    doc_xml = (
        "<w:document><w:body>"
        '<w:p><w:r><w:instrText>TOC \\o "1-3"</w:instrText></w:r></w:p>'
        "<w:p><w:r><w:instrText>PAGEREF _Toc456 \\h</w:instrText></w:r>"
        "<w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>PerfMon Counters Analysis</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Intro paragraph.</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )

    updated = inject_perfmon_charts.insert_perfmon_scorecard_xml(
        doc_xml,
        "rId99",
        Path("PerfMon_Counters_Analysis_Scorecard.png"),
        9100,
    )

    assert inject_perfmon_charts.PERFMON_SCORECARD_TITLE in updated
    assert updated.index(inject_perfmon_charts.PERFMON_SCORECARD_TITLE) > updated.index(
        '<w:p><w:pPr><w:pStyle w:val="Heading1"'
    )
    assert updated.index(inject_perfmon_charts.PERFMON_SCORECARD_TITLE) < updated.index(
        "Intro paragraph."
    )
    assert "How This Score Is Calculated" in updated
    score_heading = updated[: updated.index("How This Score Is Calculated")]
    assert score_heading.rfind('<w:pStyle w:val="Heading3"/>') > score_heading.rfind(
        "<w:p>"
    )
    assert "Advisory% x 55" in updated
    assert updated.index(inject_perfmon_charts.PERFMON_SCORECARD_TITLE) < updated.index(
        "How This Score Is Calculated"
    )
    assert updated.index("How This Score Is Calculated") < updated.index(
        "Intro paragraph."
    )


def test_append_perfmon_capture_section_adds_supplemental_content(
    monkeypatch, tmp_path: Path
) -> None:
    chart_folder = tmp_path / "charts"
    chart_folder.mkdir()
    (chart_folder / "Processor_Total_Processor_Time.png").write_bytes(_TINY_PNG)
    (chart_folder / "perfmon_observations.json").write_text(
        json.dumps(
            {
                "environment": {"Analyzed System": "BFSQL01"},
                "summary": {
                    "lines": ["Additional capture reviewed SQL server counters."],
                    "status_counts": {"OK": 1},
                },
                "sections": {
                    "CPU Utilization": {
                        "status": "OK",
                        "observation": "CPU utilization remained within standard.",
                        "evidence": "Peak processor time was 22%.",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    template = tmp_path / "template.docx"
    output = tmp_path / "output.docx"
    doc = Document()
    doc.add_heading("PerfMon Counters Analysis", level=1)
    doc.add_paragraph("Primary PerfMon content.")
    doc.add_heading("Next Section", level=1)
    doc.save(str(template))

    monkeypatch.setattr(
        inject_perfmon_charts,
        "render_perfmon_scorecard",
        lambda _observations, _output_path: None,
    )

    inject_perfmon_charts.append_perfmon_capture_section(
        chart_folder,
        template,
        output,
        section_title="Additional PerfMon Capture",
    )

    with ZipFile(output) as zf:
        doc_xml = zf.read("word/document.xml").decode("utf-8")
        media_files = [name for name in zf.namelist() if name.startswith("word/media/")]

    assert doc_xml.index("Additional PerfMon Capture") < doc_xml.index("Next Section")
    assert "Analyzed system: BFSQL01" in doc_xml
    assert "CPU Utilization" in doc_xml
    assert any("perfmon_supplemental_" in name for name in media_files)


def test_perfmon_scorecard_no_data_behavior() -> None:
    rows = inject_perfmon_charts.aggregate_perfmon_scorecard({"sections": {}})

    assert all(sum(counts.values()) == 0 for counts in rows.values())
    assert inject_perfmon_charts.perfmon_overall_score(rows) is None
