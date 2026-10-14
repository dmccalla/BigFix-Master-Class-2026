# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Loop, top10, and UDP inputs consumed from raw BESAPI .xml captures.

The Agent Performance Counter collection task writes each answer row of the
loop, top10, and UDP queries into per-report .xml captures and converts them
to CSV text. The conversion is optional going forward, so the builder must
accept the captures directly and produce identical results.
"""

from __future__ import annotations

import csv
import os
import shutil
import subprocess
from pathlib import Path

import get_loop_health
import pytest
import run_diagnostics as builder

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<BESAPI xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
    'xsi:noNamespaceSchemaLocation="BESAPI.xsd">\n'
)


def _doc(answers: list[str]) -> str:
    body = "".join(f'\t\t\t<Answer type="string">{a}</Answer>\n' for a in answers)
    return (
        f"{_HEADER}\t<Query>\n\t\t<Result>\n{body}\t\t</Result>\n\t</Query>\n</BESAPI>\n"
    )


_LOOP_ROWS = [
    "Computer Name, Platform Health Check - Maximum Cycle Minutes, Platform Health Check - Average Cycle Minutes",
    "BFCLIENT1,42,17",
    "BFCLIENT2,180,95",
    "BFCLIENT3,Not Reported,Not Reported",
]

_UDP_ROWS = [
    "Computer Name,IP Address,Relay,Receiving UDP Pings",
    "BFCLIENT1,10.0.0.11,relay1.dmc.lab,Yes",
    "BFCLIENT2,10.0.1.12,relay1.dmc.lab,No",
]

_POWERSHELL = shutil.which("powershell.exe") or shutil.which("pwsh")


def _loop_capture(tmp_path: Path) -> Path:
    xml = tmp_path / "Client_Loop_07-31-2026_1255.xml"
    xml.write_text(_doc([_LOOP_ROWS[0]]) + _doc(_LOOP_ROWS[1:]), encoding="utf-8")
    return xml


def test_validate_loop_workbook_accepts_loop_capture(tmp_path: Path) -> None:
    xml = _loop_capture(tmp_path)
    assert builder.validate_loop_workbook(xml).ok


def test_validate_loop_workbook_rejects_top10_capture(tmp_path: Path) -> None:
    xml = tmp_path / "Client_Loop_07-31-2026_1255.xml"
    xml.write_text(_doc(["Result,Occurrences", "some result,5"]), encoding="utf-8")
    result = builder.validate_loop_workbook(xml)
    assert not result.ok


def test_load_loop_input_from_capture_matches_csv(tmp_path: Path) -> None:
    xml = _loop_capture(tmp_path)
    csv_file = tmp_path / "Client_Loop_07-31-2026_1255.csv"
    csv_file.write_text("\n".join(_LOOP_ROWS) + "\n", encoding="utf-8")

    from_xml = get_loop_health.load_loop_input(xml)
    from_csv = get_loop_health.load_loop_input(csv_file)
    assert list(from_xml.columns) == list(from_csv.columns)
    assert from_xml.values.tolist() == from_csv.values.tolist()


def _processed_loop_sample(path: Path):
    df = get_loop_health.load_loop_input(path)
    computer_column, max_column, avg_column = get_loop_health.auto_detect_columns(df)
    df = get_loop_health.normalize_loop_time_columns(df, max_column, avg_column)
    return get_loop_health.process_rows(
        df,
        computer_column,
        max_column,
        avg_column,
    )


def test_shipped_loop_samples_match_current_agent_performance_contract() -> None:
    # The lab capture ships in the release zip under Results, which is not
    # tracked (it is too large for the repository), so check it when present.
    sample_root = (
        Path(__file__).resolve().parents[1] / "SampleData" / "BigFix Master Class 2026"
    )
    xml_files = sorted(sample_root.rglob("Client_Loop_*.xml"))
    if not xml_files:
        pytest.skip(f"no Client_Loop_*.xml capture under {sample_root}")
    xml = xml_files[-1]
    csv_file = xml.with_suffix(".csv")
    assert csv_file.exists(), f"{xml.name} has no CSV twin"

    xml_df = get_loop_health.load_loop_input(xml)
    csv_df = get_loop_health.load_loop_input(csv_file)
    assert len(xml_df.columns) == 14
    assert len(csv_df.columns) == 14

    xml_rows, xml_not_reported, xml_errors = _processed_loop_sample(xml)
    csv_rows, csv_not_reported, csv_errors = _processed_loop_sample(csv_file)
    assert xml_rows == csv_rows
    assert (xml_not_reported, xml_errors) == (csv_not_reported, csv_errors)

    multicore = get_loop_health.analyze_agent_multicore(xml_rows)
    assert multicore is not None
    counts = [row[1].split("/") for row in multicore.settings_rows]
    totals = {int(total.replace(",", "")) for _, total in counts}
    assert len(totals) == 1
    assert sum(int(count.replace(",", "")) for count, _ in counts) == totals.pop()


def test_load_loop_input_from_capture_accepts_comma_in_computer_name(
    tmp_path: Path,
) -> None:
    xml = tmp_path / "Client_Loop_08-10-2026_1502.xml"
    xml.write_text(
        _doc(
            [
                _LOOP_ROWS[0],
                "NEIE10N248RC45B, RRC's Air M4,21,15.0",
            ]
        ),
        encoding="utf-8",
    )

    df = get_loop_health.load_loop_input(xml)

    assert df.iloc[0]["Computer Name"] == "NEIE10N248RC45B, RRC's Air M4"
    assert str(df.iloc[0]["Platform Health Check - Maximum Cycle Minutes"]) == "21"
    assert str(df.iloc[0]["Platform Health Check - Average Cycle Minutes"]) == "15.0"


@pytest.mark.skipif(_POWERSHELL is None, reason="PowerShell is not available")
def test_query_properties_reads_xml_answers_and_preserves_timings(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / "Utilities" / "query_properties.ps1"
    loop_xml = tmp_path / "Client_Loop_08-12-2026_1502.xml"
    udp_xml = tmp_path / "UDP_Notifications_08-12-2026_1502.xml"
    top10_xml = tmp_path / "Top10_08-12-2026_1502.xml"
    loop_csv = tmp_path / "Client_Loop_08-12-2026_1502.csv"
    top10_csv = tmp_path / "top10-query-results.csv"
    udp_csv = tmp_path / "udp-notification-results.csv"
    log_file = tmp_path / "query_properties.log"

    loop_xml.write_text(
        _doc(
            [
                "BFCLIENT1,42,17,Mon, 14 Sep 2026 10:00:00 -0400,True,1,60,"
                "1,10,490,1,15,85,8",
                "NEIE10N248RC45B, RRC's Air M4,21,15.0,Mon, "
                "14 Sep 2026 10:00:00 -0400,False,0,Not Enabled,"
                "Not Set,Not Set,Not Set,Not Applicable,Not Set,Not Set,Not Reported",
            ]
        ),
        encoding="utf-8",
    )
    udp_xml.write_text(
        _doc(
            [
                "BFCLIENT1,10.0.0.11,relay1.dmc.lab,True",
                "NEIE10N248RC45B, RRC's Air M4,10.0.0.12,relay2.dmc.lab,False",
            ]
        ),
        encoding="utf-8",
    )
    top10_xml.write_text(
        _doc(
            [
                "10.000: CustomSite_Resolve.1055:Background Evaluation",
                "20.000: CustomSite_Resolve.1055:Background Evaluation",
                "3.000: Patching Support.344:Background Evaluation",
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-LoopXml",
            str(loop_xml),
            "-UdpXml",
            str(udp_xml),
            "-Top10Input",
            str(top10_xml),
            "-OutputTop10Csv",
            str(top10_csv),
            "-OutputLoopCsv",
            str(loop_csv),
            "-OutputUdpCsv",
            str(udp_csv),
            "-LogFile",
            str(log_file),
            "-Quiet",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    with loop_csv.open(encoding="utf-8-sig", newline="") as handle:
        loop_rows = list(csv.DictReader(handle))
    assert loop_rows[0]["Computer Name"] == "BFCLIENT1"
    assert (
        loop_rows[0]["Platform Health Check - Last UDP Ping"]
        == "Mon, 14 Sep 2026 10:00:00 -0400"
    )
    assert loop_rows[0]["Platform Health Check - Command Polling Enabled"] == "1"
    assert loop_rows[0]["Platform Health Check - Command Polling Minutes"] == "60"
    assert loop_rows[1]["Computer Name"] == "NEIE10N248RC45B, RRC's Air M4"
    assert (
        loop_rows[1]["Platform Health Check - Last UDP Ping"]
        == "Mon, 14 Sep 2026 10:00:00 -0400"
    )
    assert loop_rows[1]["Platform Health Check - Command Polling Enabled"] == "0"
    assert (
        loop_rows[1]["Platform Health Check - Command Polling Minutes"] == "Not Enabled"
    )
    assert loop_rows[0]["Platform Health Check - FastHashVerify Enabled"] == "1"
    assert loop_rows[0]["Platform Health Check - FastHashVerify Work ms"] == "10"
    assert loop_rows[0]["Platform Health Check - FastHashVerify Sleep ms"] == "490"
    assert loop_rows[0]["Platform Health Check - Agent Multicore Scaling Enabled"] == "1"
    assert loop_rows[0]["Platform Health Check - Agent CPU Work Idle"] == "15"
    assert loop_rows[0]["Platform Health Check - Agent CPU Sleep Idle"] == "85"
    assert (
        loop_rows[0]["Platform Health Check - Agent Total Physical CPU Core Count"] == "8"
    )
    assert (
        loop_rows[1]["Platform Health Check - Agent Multicore Scaling Enabled"]
        == "Not Applicable"
    )
    assert (
        loop_rows[1]["Platform Health Check - Agent Total Physical CPU Core Count"]
        == "Not Reported"
    )

    with udp_csv.open(encoding="utf-8-sig", newline="") as handle:
        udp_rows = list(csv.DictReader(handle))
    assert udp_rows[0]["Computer Name"] == "BFCLIENT1"
    assert udp_rows[1]["Computer Name"] == "NEIE10N248RC45B, RRC's Air M4"
    assert udp_rows[1]["IPv4 Addresses"] == "10.0.0.12"
    assert udp_rows[1]["Relay"] == "relay2.dmc.lab"
    assert udp_rows[1]["Platform Health Check - Receiving UDP Pings"] == "False"

    with top10_csv.open(encoding="utf-8-sig", newline="") as handle:
        top10_rows = list(csv.DictReader(handle))
    assert top10_rows[0]["Result"] == "Background Evaluation of Custom Site: Resolve"
    assert top10_rows[0]["Occurrences"] == "2"
    assert top10_rows[0]["AvgClientProcessingSeconds"] == "15"
    assert top10_rows[0]["TotalClientProcessingSeconds"] == "30"
    assert top10_rows[0]["MaxClientProcessingSeconds"] == "20"


@pytest.mark.skipif(_POWERSHELL is None, reason="PowerShell is not available")
def test_query_properties_ignores_legacy_three_field_loop_warnings(
    tmp_path: Path,
) -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = project_root / "Utilities" / "query_properties.ps1"
    loop_xml = tmp_path / "Client_Loop_08-12-2026_1502.xml"
    top10_csv = tmp_path / "top10-query-results.csv"
    udp_csv = tmp_path / "udp-notification-results.csv"
    log_file = tmp_path / "query_properties.log"

    loop_xml.write_text(
        _doc(
            [
                (
                    "BFCLIENT1,Platform Health Check - Maximum Cycle Minutes "
                    "Duplicates: Platform Health Check - Maximum Cycle Minutes="
                    "2299764711, 6743, 3|Platform Health Check - Maximum Cycle "
                    "Minutes=2299764711, 7012, 3,Platform Health Check - Average "
                    "Cycle Minutes Duplicates: Platform Health Check - Average "
                    "Cycle Minutes=2299764711, 6743, 4"
                )
            ]
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            _POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-LoopXml",
            str(loop_xml),
            "-OutputTop10Csv",
            str(top10_csv),
            "-OutputUdpCsv",
            str(udp_csv),
            "-LogFile",
            str(log_file),
            "-Quiet",
        ],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr

    with udp_csv.open(encoding="utf-8-sig", newline="") as handle:
        assert list(csv.DictReader(handle)) == []


def test_loop_discovery_prefers_xml_capture(tmp_path: Path) -> None:
    xml = _loop_capture(tmp_path)
    csv_file = tmp_path / "Client_Loop_07-31-2026_1255.csv"
    csv_file.write_text("\n".join(_LOOP_ROWS) + "\n", encoding="utf-8")
    os.utime(xml, (1_000_000, 1_000_000))
    os.utime(csv_file, (2_000_000, 2_000_000))

    loop_mod = next(m for m in builder.MODULES if m.key == "loop")
    found = builder.discover_module_input(tmp_path, loop_mod)
    assert found == xml.resolve()


def test_udp_capture_detected_and_loaded(tmp_path: Path) -> None:
    xml = tmp_path / "UDP_Notification_07-31-2026_1255.xml"
    xml.write_text(_doc([_UDP_ROWS[0]]) + _doc(_UDP_ROWS[1:]), encoding="utf-8")

    assert get_loop_health._is_udp_notifications_file(xml)
    assert builder._looks_like_udp_notification_file(xml)
    summary = get_loop_health.load_udp_notification_summary(xml)
    assert summary is not None

    found = get_loop_health.discover_udp_notifications_file(tmp_path / "anchor.csv")
    assert found == xml.resolve()


def test_plural_udp_capture_name_detected_and_loaded(tmp_path: Path) -> None:
    xml = tmp_path / "UDP_Notifications_07-31-2026_1255.xml"
    xml.write_text(_doc([_UDP_ROWS[0]]) + _doc(_UDP_ROWS[1:]), encoding="utf-8")

    assert get_loop_health._is_udp_notifications_file(xml)
    assert builder._looks_like_udp_notification_file(xml)

    found = get_loop_health.discover_udp_notifications_file(tmp_path / "anchor.csv")
    assert found == xml.resolve()


def test_top10_capture_detected_as_evaluation_source(tmp_path: Path) -> None:
    xml = tmp_path / "Top10_07-31-2026_1255.xml"
    xml.write_text(
        _doc(
            [
                "3.53: Q: unique values of (it as string) of names of bes computers 2.10: Q: second expensive property",
            ]
        ),
        encoding="utf-8",
    )
    assert builder._looks_like_loop_evaluation_file(xml)
    assert get_loop_health._is_loop_evaluation_times_file(xml)


def test_loop_config_accepts_top10_xml_with_udp_omitted(tmp_path: Path) -> None:
    loop_xml = _loop_capture(tmp_path)
    top10_xml = tmp_path / "Top10_07-31-2026_1255.xml"
    top10_xml.write_text(
        _doc(
            [
                "3.53: Q: unique values of (it as string) of names of bes computers 2.10: Q: second expensive property",
            ]
        ),
        encoding="utf-8",
    )
    mod = next(m for m in builder.MODULES if m.key == "loop")

    inputs = builder.collect_inputs_from_config(
        mod,
        {
            "input_xlsx": str(loop_xml),
            "top_offenders_file": str(top10_xml),
            "udp_notifications_file": "",
            "start_date": "",
            "end_date": "",
        },
    )

    assert inputs["input_xlsx"] == loop_xml.resolve()
    assert inputs["top_offenders_file"] == top10_xml.resolve()
    assert inputs["udp_notifications_file"] is None


def test_standalone_udp_discovery_stops_at_results_root(tmp_path: Path) -> None:
    results = tmp_path / "Diagnostics" / "Platform" / "Results"
    client_loop = results / "Client_Loop"
    client_loop.mkdir(parents=True)
    loop_xml = client_loop / "Client_Loop_08-10-2026_1502.xml"
    loop_xml.write_text(_doc(_LOOP_ROWS), encoding="utf-8")
    stale_udp = tmp_path / "Diagnostics" / "udp-notification-results.csv"
    stale_udp.write_text(
        "Computer Name,IP Address,Relay,Receiving UDP Pings\n"
        "BFCLIENT1,10.0.0.11,relay1.dmc.lab,No\n",
        encoding="utf-8",
    )

    assert get_loop_health.discover_udp_notifications_file(loop_xml) is None


def test_loop_manual_deployment_info_folder_outside_scope_is_kept(
    tmp_path: Path,
) -> None:
    """A hand-picked Deployment_Information folder is never replaced.

    The loop capture lives in one folder and the deployment information in
    another, and neither sits under the data root. Without the manual marker
    the stale-path guard replaces the folder with whatever discovery finds
    (nothing here) and Contributing Factors goes missing.
    """
    loop_dir = tmp_path / "A" / "Client_Loop"
    loop_dir.mkdir(parents=True)
    loop_csv = loop_dir / "Client_Loop_08-10-2026_1502.csv"
    loop_csv.write_text(
        "Computer Name,Maximum Cycle Minutes,Average Cycle Minutes\nclient-1,16,4.3\n",
        encoding="utf-8",
    )
    deployment_dir = tmp_path / "B" / "Deployment_Information"
    deployment_dir.mkdir(parents=True)
    data_root = tmp_path / "C"
    data_root.mkdir()
    mod = next(m for m in builder.MODULES if m.key == "loop")
    raw = {
        "loop": {
            "input_xlsx": str(loop_csv),
            "deployment_info_folder": str(deployment_dir),
        }
    }

    unmarked = builder._parse_module_inputs_from_config([mod], raw, data_root)
    assert unmarked["loop"]["deployment_info_folder"] is None

    marked = builder._parse_module_inputs_from_config(
        [mod],
        raw,
        data_root,
        {"loop": {"deployment_info_folder": str(deployment_dir)}},
    )
    assert marked["loop"]["deployment_info_folder"] == deployment_dir.resolve()
