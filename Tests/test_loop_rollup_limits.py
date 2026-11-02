# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Relay and subnet rollups: every row in the data, top rows only in the Mini Report."""

import sys
from pathlib import Path

import get_loop_health as loop
import pytest
import run_diagnostics as runner
from docx import Document
from docx.text.paragraph import Paragraph
from openpyxl import load_workbook

LIMIT = loop.MINI_REPORT_ROLLUP_LIMIT


def _metrics() -> loop.ReportMetrics:
    return loop.ReportMetrics(
        total_devices=10,
        score_total_devices=10,
        overall_status="Healthy",
        environment_score=95,
        score_driver="test driver",
        score_breakdown="test breakdown",
        report_start_text="7/1/2026",
        report_end_text="7/2/2026",
        report_span_text="2 days",
        generated_at_text="7/2/2026 17:32",
        avg_mean_seconds=300,
        avg_median_seconds=240,
        avg_max_seconds=600,
        slowest_avg_seconds=900,
        peak_max_seconds=1200,
        avg_healthy=10,
        avg_warning=0,
        avg_critical=0,
        avg_healthy_pct=1.0,
        avg_warning_pct=0.0,
        avg_critical_pct=0.0,
        avg_over_120=0,
        avg_over_120_pct=0.0,
        not_reported_count=0,
        error_count=0,
        not_reported_pct=0.0,
        error_pct=0.0,
        total_issue_count=0,
        total_issue_pct=0.0,
        healthy_threshold_seconds=1800,
        critical_threshold_seconds=3600,
        fix_first_count=0,
    )


def _udp_summary(tmp_path: Path, groups: int) -> loop.UdpNotificationSummary:
    return loop.UdpNotificationSummary(
        source_file=tmp_path / "udp-notification-results.csv",
        total_devices=groups,
        receiving_count=0,
        not_receiving_count=groups,
        unknown_count=0,
        relay_rows=[[f"relay-{i:02d}", "1 / 1", "100.0%"] for i in range(groups)],
        subnet_rows=[
            [f"10.0.{i}.0/24", "1 / 1", f"relay-{i:02d}"] for i in range(groups)
        ],
    )


def _polling_summary(groups: int) -> loop.CommandPollingSummary:
    def row(name: str) -> list[str]:
        return [name, "1", "1", "0", "0", "0", "0", "0", "0"]

    return loop.CommandPollingSummary(
        total_devices=groups,
        enabled_count=groups,
        disabled_count=0,
        not_set_count=0,
        unknown_count=0,
        enabled_missing_interval_count=0,
        interval_below_loop_count=0,
        no_udp_polling_gap_count=0,
        relay_rows=[row(f"relay-{i:02d}") for i in range(groups)],
        subnet_rows=[row(f"10.0.{i}.0/24") for i in range(groups)],
    )


def _report(tmp_path: Path, groups: int) -> Document:
    output = tmp_path / "loop.docx"
    loop.generate_word(
        _metrics(),
        tmp_path / "missing.png",
        output,
        udp_summary=_udp_summary(tmp_path, groups),
        command_polling_summary=_polling_summary(groups),
    )
    return Document(str(output))


def _table_after(doc: Document, heading: str):
    """Return the first table that follows the named heading."""
    body = doc.element.body
    seen = False
    tables = iter(doc.tables)
    for el in body.iterchildren():
        if el.tag.endswith("}p") and Paragraph(el, doc).text.strip() == heading:
            seen = True
        elif el.tag.endswith("}tbl"):
            table = next(tables)
            if seen:
                return table
    raise AssertionError(f"no table after {heading!r}")


def test_udp_summary_keeps_every_relay_and_subnet(tmp_path: Path) -> None:
    lines = [
        "Computer Name,IPv4 Addresses,Relay,Platform Health Check - Receiving UDP Pings"
    ]
    lines += [f"client-{i},10.0.{i}.5,relay-{i:02d},False" for i in range(LIMIT + 5)]
    udp_file = tmp_path / "udp-notification-results.csv"
    udp_file.write_text("\n".join(lines), encoding="utf-8")

    summary = loop.load_udp_notification_summary(udp_file)

    assert summary is not None
    assert len(summary.relay_rows) == LIMIT + 5
    assert len(summary.subnet_rows) == LIMIT + 5


def test_report_caps_rollups_and_says_so(tmp_path: Path) -> None:
    doc = _report(tmp_path, LIMIT + 5)
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    notes = [p.text for p in doc.paragraphs if p.text.startswith("Showing")]

    capped = {
        f"UDP Notification Issues by Relay (Top {LIMIT})": "UDP Issues by Relay",
        f"Top {LIMIT} Subnets Not Receiving UDP Pings": "UDP Issues by Subnet",
        f"Command Polling by Relay (Top {LIMIT})": "Polling by Relay",
        f"Command Polling by Subnet (Top {LIMIT})": "Polling by Subnet",
    }
    for heading in capped:
        assert heading in headings
        assert len(_table_after(doc, heading).rows) == LIMIT + 1  # header + top rows
    for noun in ("relays", "subnets"):
        expected = f"Showing {LIMIT} of {LIMIT + 5:,} {noun}."
        assert sum(n.startswith(expected) for n in notes) == 2
    for sheet in capped.values():
        assert (
            sum(
                f"See the {sheet} worksheet in loop.xlsx for the complete list." in n
                for n in notes
            )
            == 1
        )


@pytest.mark.parametrize("groups", [2, 5, 10])
def test_report_keeps_short_rollups_whole(tmp_path: Path, groups: int) -> None:
    doc = _report(tmp_path, groups)
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]

    for heading in (
        "UDP Notification Issues by Relay",
        "Top Subnets Not Receiving UDP Pings",
        "Command Polling by Relay",
        "Command Polling by Subnet",
    ):
        assert heading in headings
        assert len(_table_after(doc, heading).rows) == groups + 1
    assert not [p.text for p in doc.paragraphs if p.text.startswith("Showing")]


@pytest.mark.parametrize(
    "groups,evaluation_count", [(2, 2), (10, 10), (11, 11), (376, 27)]
)
def test_pipeline_delivers_complete_workbook_named_by_preview(
    tmp_path: Path, monkeypatch, groups: int, evaluation_count: int
) -> None:
    """Exercise the real generator and UI filename changes with large captures."""
    capture = tmp_path / "client.csv"
    capture.write_text(
        "Computer Name,Maximum Cycle Minutes,Average Cycle Minutes,"
        "Platform Health Check - Command Polling Enabled,"
        "Platform Health Check - Command Polling Minutes\n"
        + "\n".join(f"client-{i},20,10,1,20" for i in range(groups)),
        encoding="utf-8",
    )
    udp = tmp_path / "udp-notification-results.csv"
    udp.write_text(
        "Computer Name,IPv4 Addresses,Relay,Platform Health Check - Receiving UDP Pings\n"
        + "\n".join(
            f"client-{i},10.{i // 254}.{i % 254}.5,relay-{i:03d},False"
            for i in range(groups)
        ),
        encoding="utf-8",
    )
    evaluations = tmp_path / "evaluation-times.txt"
    evaluations.write_text(
        "Count Percentage Result\n"
        + "\n".join(
            f"1 1.00% {40 + i}.0: CustomSite_Overflow{i}.1:Background Evaluation"
            for i in range(evaluation_count)
        ),
        encoding="utf-8",
    )
    deployment = tmp_path / "Deployment_Information"
    deployment.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    prefix = "Review_376_relays_20261102"

    # Keep chart rendering out of this data and filename test. The report uses
    # the same table/preview content when no chart image is present.
    monkeypatch.setattr(loop, "generate_png", lambda *args, **kwargs: None)

    def generate(script, args, log=None):
        assert script.name == "get_loop_health.py"
        with monkeypatch.context() as context:
            context.setattr(sys, "argv", [str(script), *args])
            assert loop.main() == 0
        workbook = next(output.glob("Client_Loop_Analysis_*.xlsx"))
        workbook.with_suffix(".png").write_bytes(b"chart placeholder")
        return 0

    monkeypatch.setattr(runner, "run_python", generate)
    runner.run_loop_pipeline(
        {
            "_file_prefix": prefix,
            "_out_folder": output,
            "input_xlsx": capture,
            "udp_notifications_file": udp,
            "top_offenders_file": evaluations,
            "deployment_info_folder": deployment,
            "start_date": "07-01-2026",
            "end_date": "07-02-2026",
        },
        None,
        "unused",
    )
    workbook_path = output / f"{prefix}_Client_Loop.xlsx"
    doc = Document(output / f"{prefix}_Client_Loop.docx")
    notes = [p.text for p in doc.paragraphs if p.text.startswith("Showing")]
    workbook = load_workbook(workbook_path, read_only=True)
    try:
        assert list(output.glob("*.xlsx")) == [workbook_path]
        for heading, sheet in loop.ROLLUP_WORKSHEETS.items():
            rows = list(workbook[sheet].iter_rows(min_row=2, values_only=True))
            assert len(rows) == groups
            heading = (
                f"Top {LIMIT} Subnets Not Receiving UDP Pings"
                if groups > LIMIT and sheet == "UDP Issues by Subnet"
                else f"{heading} (Top {LIMIT})"
                if groups > LIMIT
                else heading
            )
            preview = _table_after(doc, heading).rows[1:]
            assert [row.cells[0].text for row in preview] == [
                str(row[0]) for row in rows[:LIMIT]
            ]
            reference = f"See the {sheet} worksheet in {workbook_path.name} for the complete list."
            assert sum(reference in note for note in notes) == int(groups > LIMIT)
        evaluation_rows = list(
            workbook["Evaluation Offenders"].iter_rows(min_row=2, values_only=True)
        )
        assert len(evaluation_rows) == evaluation_count
        assert [row[0] for row in evaluation_rows] == list(range(1, evaluation_count + 1))
        assert (
            len(_table_after(doc, "Top 10 Most Expensive Evaluations").rows)
            == min(LIMIT, evaluation_count) + 1
        )
        evaluation_reference = (
            f"Showing 10 of {evaluation_count} captured evaluations. "
            f"See the Evaluation Offenders worksheet in {workbook_path.name} for the complete list."
        )
        assert notes.count(evaluation_reference) == int(evaluation_count > LIMIT)
        assert all("Client_Loop_Analysis_" not in note for note in notes)
        assert all(str(tmp_path) not in note for note in notes)
    finally:
        workbook.close()
