# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Validate the active demo against its originals and declared assessment period."""

import csv
import hashlib
import io
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

import get_loop_health as loop
import pytest

from Lib.Core.besapi_capture import read_capture_or_log_text

SAMPLE_ROOT = Path(__file__).parents[1] / "SampleData"
SAMPLE = next(p.parent for p in SAMPLE_ROOT.glob("*/DEMO_SNAPSHOT.json"))
META = json.loads((SAMPLE / "DEMO_SNAPSHOT.json").read_text())
RFC = re.compile(
    r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun), \d{2} [A-Z][a-z]{2} "
    r"\d{4} \d{2}:\d{2}:\d{2} [+-]\d{4}\b"
)


def _period():
    return tuple(
        datetime.fromisoformat(META[k]).date()
        for k in ("assessment_start", "assessment_end")
    )


def test_active_captures_have_one_assessment_period():
    _, end = _period()
    sources = list((SAMPLE / "Deployment_Information").rglob("*.log"))
    assert sources
    for source in sources:
        text = read_capture_or_log_text(source)
        generated = re.search(r"Report Generated: (.+)", text)
        if generated:
            captured = datetime.strptime(
                generated[1].strip(), "%a, %d %b %Y %H:%M:%S %z"
            )
            assert _period()[0] <= captured.date() <= end, source
        if source.name.startswith("Content_Info"):
            assert all(
                datetime.strptime(value, "%a, %d %b %Y %H:%M:%S %z").date() <= end
                for value in RFC.findall(text)
            ), source


def test_loop_csv_xml_and_dates_agree():
    folder = next(p for p in SAMPLE.iterdir() if p.name.lower() == "client_loop")
    xml = loop.load_loop_input(next(folder.glob("Client_Loop*.xml")))
    csv_data = loop.load_loop_input(next(folder.glob("Client_Loop*.csv")))
    assert xml.astype(str).values.tolist() == csv_data.astype(str).values.tolist()
    assert len(xml) == META["expected_loop_rows"]
    _, end = _period()
    dates = RFC.findall(xml.to_string())
    assert dates
    assert all(
        datetime.strptime(d, "%a, %d %b %Y %H:%M:%S %z").date() <= end for d in dates
    )


def test_xml_and_log_companions_preserve_shared_fields_and_supplements():
    from html import unescape

    for source in (SAMPLE / "Deployment_Information").rglob("*.xml"):
        log = source.with_suffix(".log")
        if log.is_file():

            def normalized(p):
                return [
                    unescape(line.strip())
                    for line in read_capture_or_log_text(p).splitlines()
                    if line.strip()
                ]

            primary, converted = normalized(source), normalized(log)
            hardware = []
            if source.name.startswith("Root_Server_Info_"):
                hardware = [
                    line
                    for line in primary
                    if line.startswith("BES Server Hardware Information:")
                ]
                assert len(hardware) == 1
                primary = [line for line in primary if line not in hardware]
            assert primary == converted[: len(primary)], source
            supplements = converted[len(primary) :]
            if supplements:
                # Client relevance and Admin Tool values are log supplements,
                # not answers from the primary REST query. Keep them intact.
                if hardware:
                    assert len(supplements) == 12
                    assert supplements[0].startswith("C: - Total Space:")
                    assert supplements[-1].startswith(
                        "FillDB Parallelism (Parallelism Enabled For Query):"
                    )
                else:
                    assert source.name.startswith("General_Info_"), source
                    assert len(supplements) == 3
                    assert supplements[0].startswith("Actionsite Size:")
                    assert supplements[1].startswith("passwordComplexityDescription,")
                    assert supplements[2].startswith("MinimumRefreshSeconds,")


def test_original_inputs_are_preserved_and_hash_verified():
    archive = SAMPLE / META["originals_archive"]
    assert (
        hashlib.sha256(archive.read_bytes()).hexdigest()
        == META["originals_archive_sha256"]
    )
    with ZipFile(archive) as original:
        assert original.testzip() is None
        names = original.namelist()
        assert any(name.startswith("Deployment_Information/") for name in names)
        assert any(name.endswith(".csv") for name in names)


def test_loop_measurements_are_preserved_except_corrected_root_core_example():
    folder = next(p for p in SAMPLE.iterdir() if p.name.lower() == "client_loop")
    current = list(
        csv.reader(
            next(folder.glob("Client_Loop*.csv")).open(newline="", encoding="utf-8-sig")
        )
    )
    with ZipFile(SAMPLE / META["originals_archive"]) as archive:
        name = next(
            n
            for n in archive.namelist()
            if Path(n).name.startswith("Client_Loop") and n.endswith(".csv")
        )
        original = list(csv.reader(io.StringIO(archive.read(name).decode("utf-8-sig"))))
    assert len(current) == len(original)
    udp = current[0].index("Platform Health Check - Last UDP Ping")
    assert current[0] == original[0]
    for old, new in zip(original[1:], current[1:], strict=True):
        for column, (before, after) in enumerate(zip(old, new, strict=True)):
            if column == udp:
                continue
            if (
                META["expected_loop_rows"] == 13
                and old[0] == "BFROOT1"
                and column == len(old) - 1
            ):
                assert (before, after) == ("16", "4")
            else:
                assert before == after


def test_filldb_duration_and_dates_fit_the_assessment():
    source = next(SAMPLE.rglob("FillDBPerf_analysis.csv")).read_text()
    start = datetime.fromisoformat(
        re.search(r"FillDB start time:,([^\n]+)", source)[1].strip()
    )
    end = datetime.fromisoformat(
        re.search(r"FillDB end time:,([^\n]+)", source)[1].strip()
    )
    first, last = _period()
    assert first <= start.date() <= end.date() <= last
    assert end - start == timedelta(hours=37, seconds=56)


def test_validation_fingerprints_resolve_to_current_inputs():
    manifest = json.loads((SAMPLE / "SAMPLE_DATA_VALIDATION.json").read_text())
    for item in manifest["input_files"]:
        data = (SAMPLE / item["path"]).read_bytes()
        if item["hash_mode"] == "utf8_lf":
            data = data.decode("utf-8-sig").replace("\r\n", "\n").encode("utf-8")
        assert len(data) == item["bytes_for_hash"], item["path"]
        assert hashlib.sha256(data).hexdigest() == item["sha256"], item["path"]
    assert (
        hashlib.sha256((SAMPLE / "Perfmon/server.blg").read_bytes()).hexdigest()
        == "50f786d60cda1ca0a5f0295dd68dd53436db637d5f90dff20f8e87dd11f29e22"
    )


@pytest.mark.skipif(META["expected_loop_rows"] != 13, reason="Full-report demo only")
def test_dashboard_actions_and_remaining_ids_match_the_frozen_sources(tmp_path):
    import get_deployment_health_dashboard as dashboard
    from Lib.Analysis.dashboard_source_ids import dashboard_source_id_by_name

    source = next((SAMPLE / "Deployment_Healthcheck_Dashboard").glob("*.log"))
    text = source.read_text()
    assert "Total Open Actions: 28 || Open Top Level Actions: 25" in text
    assert (
        "Total Stopped\\Expired Actions: 480 || Top Level Stopped\\Expired Actions: 469"
        in text
    )
    parsed = dashboard.parse_log(str(source))
    with ZipFile(SAMPLE / META["originals_archive"]) as archive:
        name = next(
            n
            for n in archive.namelist()
            if n.startswith("Deployment_Healthcheck_Dashboard/") and n.endswith(".log")
        )
        old = tmp_path / "original.log"
        old.write_bytes(archive.read(name))
    previous = dashboard.parse_log(str(old))

    def ids(p):
        return dashboard_source_id_by_name(
            {
                section: [row["name"] for row in rows]
                for section, rows in p["sections"].items()
            }
        )

    assert ids(previous) == ids(parsed)
    assert text.count("FillDB :: Enabled") == 1
    assert sum(len(rows) for rows in parsed["sections"].values()) == 44


@pytest.mark.skipif(META["expected_loop_rows"] != 13, reason="Full-report demo only")
def test_root_capacity_and_backup_timestamps_match_the_demo():
    source = next((SAMPLE / "Server_Capacity").glob("*RootServer*.log")).read_text()
    assert "Host name: BFROOT1" in source
    assert "Logical processors: 4" in source
    assert "Cores per socket: 4" in source
    assert "Physical memory (MB): 12288" in source
    sql = next(
        (SAMPLE / "SQL/SQL_Information").glob("*maintenance_plan_history.csv")
    ).read_text()
    dates = [
        datetime.strptime(d, "%Y-%m-%d").date()
        for d in re.findall(r"\b2026-\d{2}-\d{2}\b", sql)
    ]
    assert dates and max(dates) == _period()[1]
    assert "BFI-ROOT01" not in sql
