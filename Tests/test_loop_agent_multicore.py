# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""11.0.7 agent multicore configuration coverage in the client performance path."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import get_loop_health as loop
import pandas as pd
from docx import Document
from openpyxl import load_workbook


def _sample_rows() -> list[loop.ProcessedRow]:
    df = pd.DataFrame(
        {
            "Computer Name": ["scaled-client", "default-client", "scaled-client-2"],
            "Maximum Cycle Minutes": [20, 40, 80],
            "Average Cycle Minutes": [10, 30, 60],
            "Platform Health Check - Agent Multicore Scaling Enabled": [
                "1",
                "Not Set",
                "1",
            ],
            "Platform Health Check - Agent Multicore Max Core Utilization": [
                "80",
                "Not Set",
                "80",
            ],
            "Platform Health Check - Agent Multicore Work Type Scalar": [
                "4",
                "Not Set",
                "4",
            ],
        }
    )
    df = loop.normalize_loop_time_columns(
        df, "Maximum Cycle Minutes", "Average Cycle Minutes"
    )
    processed, not_reported, errors = loop.process_rows(
        df,
        "Computer Name",
        "Maximum Cycle Minutes",
        "Average Cycle Minutes",
    )
    assert not_reported == 0
    assert errors == 0
    return processed


def _sample_metrics(
    processed: list[loop.ProcessedRow],
) -> tuple[loop.ReportMetrics, list[loop.ProcessedRow]]:
    return loop.calculate_metrics(
        processed=processed,
        total_source_rows=len(processed),
        not_reported_count=0,
        error_count=0,
        healthy_threshold_seconds=1800,
        critical_threshold_seconds=3600,
        report_start=date(2026, 9, 1),
        report_end=date(2026, 9, 2),
        generated_at=datetime(2026, 9, 30, 10, 30, 0),
    )


def test_agent_multicore_settings_are_reported_without_assessment() -> None:
    processed = _sample_rows()
    summary = loop.analyze_agent_multicore(processed)

    assert summary is not None
    assert summary.total_devices == 3
    assert summary.settings_rows == [
        ["Enabled", "80", "4", "2"],
        ["Not Set", "Not Set", "Not Set", "1"],
    ]

    source = loop.processed_to_dataframe(processed)
    assert list(
        source[
            [
                "Agent Multicore Scaling",
                "Agent Multicore Max Core Utilization",
                "Agent Multicore Work Type Scalar",
            ]
        ].iloc[0]
    ) == ["Enabled", "80", "4"]


def test_agent_multicore_workbook_and_word_sections_are_written(tmp_path: Path) -> None:
    processed = _sample_rows()
    summary = loop.analyze_agent_multicore(processed)
    assert summary is not None
    metrics, fix_first = _sample_metrics(processed)

    workbook = tmp_path / "loop.xlsx"
    loop.generate_excel(
        metrics,
        processed,
        fix_first,
        workbook,
        agent_multicore_summary=summary,
    )
    wb = load_workbook(workbook)
    assert "Agent Multicore Settings" in wb.sheetnames
    settings = list(wb["Agent Multicore Settings"].values)
    assert settings[0] == (
        "Scale Work Time With CPU Cores",
        "Max Core Utilization",
        "Work Type Scalar",
        "Devices",
    )
    assert settings[1] == ("Enabled", "80", "4", "2")

    word_output = tmp_path / "loop.docx"
    loop.generate_word(
        metrics,
        tmp_path / "missing.png",
        word_output,
        agent_multicore_summary=summary,
    )
    doc = Document(str(word_output))
    headings = [p.text for p in doc.paragraphs if p.style.name.startswith("Heading")]
    assert "Agent Multicore Settings" in headings
    assert any("configuration context only" in p.text for p in doc.paragraphs)
    assert any("earlier than BigFix 11.0.7" in p.text for p in doc.paragraphs)
    assert any(
        table.rows[0].cells[0].text == "Scale Work Time With CPU Cores"
        for table in doc.tables
    )
