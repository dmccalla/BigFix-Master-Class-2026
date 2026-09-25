# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Tests for Lib/Core/besapi_capture.py and .xml source guardrails."""

from __future__ import annotations

import os
from pathlib import Path

from Lib.Core.besapi_capture import (
    capture_to_log_text,
    merge_capture_text,
    newest_capture_source,
    read_capture_or_log_text,
    read_merged_capture_or_log_text,
)

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<BESAPI xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="BESAPI.xsd">\n'
)


def _doc(answers: list[str], tuples: list[tuple[str, str]] | None = None) -> str:
    body = "".join(f'\t\t\t<Answer type="string">{a}</Answer>\n' for a in answers)
    body += "".join(
        "\t\t\t<Tuple>\n"
        f'\t\t\t\t<Answer type="string">{v}</Answer>\n'
        f'\t\t\t\t<Answer type="string">{c}</Answer>\n'
        "\t\t\t</Tuple>\n"
        for v, c in (tuples or [])
    )
    return (
        f"{_HEADER}\t<Query>\n\t\t<Result>\n{body}\t\t</Result>\n\t</Query>\n</BESAPI>\n"
    )


def test_capture_to_log_text_matches_task_conversion() -> None:
    capture = "".join(
        [
            _doc(["DEPLOYMENT OVERVIEW DASHBOARD"]),
            _doc([" "]),
            _doc(["Total Managed Devices :: 14"]),
            _doc([], tuples=[("Undefined", "4"), ("21600", "1")]),
        ]
    )
    text = capture_to_log_text(capture)
    assert text.splitlines() == [
        "DEPLOYMENT OVERVIEW DASHBOARD",
        " ",
        "Total Managed Devices :: 14",
        "Undefined",
        "4",
        "21600",
        "1",
    ]


def test_capture_passes_through_failed_query_lines() -> None:
    capture = (
        _doc(["Total Managed Devices :: 14"])
        + "ERROR: Query line 7 failed: timeout\n"
        + _doc(["Relays Deployed :: 2"])
    )
    lines = capture_to_log_text(capture).splitlines()
    assert "ERROR: Query line 7 failed: timeout" in lines
    assert "Total Managed Devices :: 14" in lines
    assert "Relays Deployed :: 2" in lines


def test_capture_tolerates_malformed_fragment() -> None:
    capture = _doc(["good line"]) + "<?xml version..." + _doc(["second line"])
    lines = capture_to_log_text(capture).splitlines()
    assert lines == ["good line", "second line"]


def test_read_capture_or_log_text_dispatches_on_suffix(tmp_path: Path) -> None:
    xml = tmp_path / "General_Info_HOST_07-31-2026_1255.xml"
    xml.write_text(_doc(["Total Operators :: 3"]), encoding="utf-8")
    log = tmp_path / "General_Info_HOST_07-31-2026_1255.log"
    log.write_text("Total Operators :: 3\n", encoding="utf-8")
    assert read_capture_or_log_text(xml).splitlines() == ["Total Operators :: 3"]
    assert read_capture_or_log_text(log).splitlines() == ["Total Operators :: 3"]


def test_merged_capture_keeps_xml_fields_and_log_only_client_relevance(
    tmp_path: Path,
) -> None:
    xml = tmp_path / "General_Info_HOST_07-31-2026_1255.xml"
    xml.write_text(
        _doc(
            [
                "License Organization: XML Customer",
                "Number of Computers: 42",
            ]
        ),
        encoding="utf-8",
    )
    log = tmp_path / "General_Info_HOST_07-31-2026_1255.log"
    log.write_text(
        "\n".join(
            [
                "License Organization: Log Customer",
                "Actionsite Size: 6931 KB",
                "Cache Latency Metric: 00:00:54",
            ]
        ),
        encoding="utf-8",
    )

    merged = read_merged_capture_or_log_text(tmp_path, "General_Info").splitlines()

    assert "License Organization: XML Customer" in merged
    assert "License Organization: Log Customer" not in merged
    assert "Actionsite Size: 6931 KB" in merged
    assert "Cache Latency Metric: 00:00:54" in merged


def test_merged_capture_does_not_let_legacy_section_overwrite_xml_section() -> None:
    xml_text = "\n".join(
        [
            "Number of External Sites: 2",
            "//===== EXTERNAL SITES INFORMATION  ==================================",
            "Column Headers: Site, Count",
            "BES Support",
            "2",
        ]
    )
    log_text = "\n".join(
        [
            "Number of External Sites: 1",
            "//===== EXTERNAL SITES INFORMATION  ==================================",
            "Column Headers: Site, Count",
            "Legacy Site",
            "1",
            "Number of Custom Sites: 3",
        ]
    )

    merged = merge_capture_text(xml_text, log_text)

    assert "BES Support" in merged
    assert "Legacy Site" not in merged
    assert "Number of External Sites: 1" not in merged
    assert "Number of Custom Sites: 3" not in merged


def test_newest_capture_source_prefers_xml_and_tolerates_name_quirks(
    tmp_path: Path,
) -> None:
    # Historical task bug: Root_Server_Info XML names omitted the underscore.
    quirky_xml = tmp_path / "Root_Server_InfoBFROOT1_07-31-2026_1255.xml"
    log = tmp_path / "Root_Server_Info_BFROOT1_07-31-2026_1255.log"
    for path in (quirky_xml, log):
        path.write_text("x", encoding="utf-8")
    os.utime(quirky_xml, (1_000_000, 1_000_000))
    os.utime(log, (2_000_000, 2_000_000))
    assert newest_capture_source(tmp_path, "Root_Server_Info") == quirky_xml

    quirky_xml.unlink()
    assert newest_capture_source(tmp_path, "Root_Server_Info") == log


def test_newest_capture_source_log_pattern_override(tmp_path: Path) -> None:
    xml = tmp_path / "Deployment_Overview_Dashboard_HOST_07-31-2026_1255.xml"
    log = tmp_path / "Deployment_Overview_Dashboard_Data.log"
    log.write_text("x", encoding="utf-8")
    found = newest_capture_source(
        tmp_path,
        "Deployment_Overview_Dashboard",
        log_patterns=("Deployment_Overview_Dashboard_Data.log",),
    )
    assert found == log
    xml.write_text("x", encoding="utf-8")
    found = newest_capture_source(
        tmp_path,
        "Deployment_Overview_Dashboard",
        log_patterns=("Deployment_Overview_Dashboard_Data.log",),
    )
    assert found == xml
