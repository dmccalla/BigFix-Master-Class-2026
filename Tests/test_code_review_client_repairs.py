# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Regressions for the independently reproduced Revision 2 Client defects."""

import csv
from pathlib import Path

import pytest

from Get import get_loop_health as loop


@pytest.mark.parametrize("prefix", ["Number", "Total Number"])
def test_master_operator_analyses_accepts_both_capture_labels(tmp_path: Path, prefix):
    (tmp_path / "Content_Info_test.log").write_text(
        "Number of Master Operator Fixlets: 15\n"
        "Number of Master Operator Tasks: 30\n"
        f"{prefix} of Master Operator Analyses: 10\n",
        encoding="utf-8",
    )
    pressure = loop.parse_actionsite_pressure(tmp_path)
    assert pressure.master_operator_analyses == 10
    assert loop.master_operator_custom_content_total(pressure) == 55
    assert (
        "55 total (15 fixlets, 30 tasks, 10 analyses)"
        == loop._actionsite_custom_content_value(pressure)
    )


def test_relay_host_case_and_url_form_have_one_grouping_key():
    names = [
        "RELAYA.corp.local",
        "relaya.corp.local",
        "RelayA.corp.local",
        "http://RELAYA.corp.local:52311/bfmirror/downloads",
    ]
    assert len({loop.normalize_relay_name(name) for name in names}) == 1
    assert loop.normalize_relay_name("") == "Not reported"


def test_udp_rollup_combines_case_variants_before_ranking(tmp_path):
    path = tmp_path / "udp-notification-results.csv"
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow(["Computer Name", "IP Address", "Relay", "Receiving UDP Pings"])
        for index, (relay, receiving) in enumerate(
            [
                ("RELAYA.corp.local", False),
                ("relaya.corp.local", True),
                ("RelayA.corp.local", False),
                ("http://RELAYA.corp.local:52311", True),
            ]
        ):
            writer.writerow([f"device{index}", f"10.0.0.{index + 1}", relay, receiving])
    summary = loop.load_udp_notification_summary(path)
    assert len(summary.relay_rows) == 1
    assert summary.relay_rows[0][1] == "2 / 4"


@pytest.mark.parametrize(
    "minutes, expected",
    [(87, "1.5 hours"), (207, "3.5 hours"), (150, "2.5 hours"), (120, "2 hours")],
)
def test_hour_display_rounds_half_up(minutes, expected):
    assert loop.format_duration_for_report(minutes * 60) == expected
