# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Regression coverage for distinct loop, notification and display measures."""

from datetime import date, datetime
from pathlib import Path

import get_loop_health as loop
import pytest


def metrics():
    rows = [
        loop.ProcessedRow("peak-only", "02:40:00", "00:20:00", 9600, 1200),
        loop.ProcessedRow("slow-average", "02:40:00", "02:10:00", 9600, 7800),
    ]
    return loop.calculate_metrics(
        rows,
        3,
        1,
        0,
        900,
        3600,
        date(2026, 10, 1),
        date(2026, 10, 6),
        datetime(2026, 10, 21),
        good_threshold_seconds=1800,
    )[0]


@pytest.mark.parametrize(
    "fraction, expected",
    [
        (0, "0.0%"),
        (1 / 2477, "<0.1%"),
        (2 / 2477, "0.1%"),
        (1 / 300000, "<0.1%"),
        (0.25, "25.0%"),
        (1, "100.0%"),
    ],
)
def test_nonzero_percentages_do_not_display_as_zero(fraction, expected):
    assert loop.pct(fraction) == expected


def test_udp_overview_uses_udp_population_not_loop_population():
    summary = loop.UdpNotificationSummary(Path("udp.csv"), 2400, 2208, 192, 0, [], [])
    rows = {
        r["label"]: r for r in loop.context_strip_tiles(metrics(), udp_summary=summary)
    }
    assert rows["Devices reporting"]["value"] == "2 / 3"
    assert rows["No UDP pings received"]["value"] == "192 / 2,400"
    assert loop.udp_coverage_rows(summary)[1][1:] == ["192 / 2,400", "8.0%"]


def test_two_hour_count_remains_an_average_measure():
    report = metrics()
    assert report.avg_over_120 == 1
    assert report.peak_max_seconds == 9600
    assert report.score_total_devices == 3


def test_two_hour_tile_names_the_average_measure(monkeypatch, tmp_path):
    charts = []
    monkeypatch.setattr(
        "Lib.Design.html_charts.render_chart",
        lambda kind, data, path: charts.append(data),
    )
    loop.generate_png(metrics(), tmp_path / "loop.png")
    assert charts[0]["footer"][2]["label"] == "Devices averaging over 120 min"
    assert charts[0]["footer"][2]["value"] == "1"


def test_rare_udp_misses_can_be_sorted_without_parsing_display_percent(tmp_path):
    source = tmp_path / "udp.csv"
    source.write_text(
        "Computer Name,IPv4 Address,Relay,Receiving UDP Pings\n"
        + "\n".join(
            f"client-{i},10.0.0.1,relay-a,{'No' if i == 0 else 'Yes'}"
            for i in range(2500)
        ),
        encoding="utf-8",
    )
    summary = loop.load_udp_notification_summary(source)
    assert summary.relay_rows == [["relay-a", "1 / 2,500", "<0.1%"]]


def test_custom_flag_count_is_not_replaced_with_source_site_count():
    pressure = loop.ActionSitePressure(
        Path("Deployment_Information"),
        properties_count=100,
        active_properties_count=2,
        custom_properties_count=0,
    )
    properties = loop.PropertyIntervalSummary(
        Path("Property_Info.log"),
        [
            loop.PropertyInterval(
                "custom-analysis", "analysis", "custom-site", "operator", 360, "Custom"
            ),
            loop.PropertyInterval(
                "external-analysis", "analysis", "BES Support", "bigfix", 0, "External"
            ),
        ],
    )
    assert (
        loop.property_interval_band_counts(properties)["6 hours or longer"]["custom"]
        == 1
    )
    assert "0 custom-flagged" in loop._properties_value(pressure)
