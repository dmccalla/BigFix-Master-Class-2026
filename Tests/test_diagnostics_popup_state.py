# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from collections import deque
from types import MethodType

import diagnostics_workbench_ui as ui


class HeadlessDiagnosticsUI:
    """Use the popup's state methods without creating a desktop window."""

    def __init__(self) -> None:
        self.step = 2
        self._app_started_at = time.monotonic() - 12
        self._heartbeat_samples = deque([10.0, 12.0, 90.0, 18.0], maxlen=240)
        self._last_heartbeat_lag_ms = 18.0
        self._max_heartbeat_lag_ms = 90.0
        self._slow_heartbeat_count = 1
        self._resource_samples = deque(
            [
                {
                    "cpu_pct": 12.0,
                    "rss_mb": 100.0,
                    "widget_count": 240,
                    "ui_queue_depth": 0,
                    "gdi_objects": 20,
                    "user_objects": 18,
                },
                {
                    "cpu_pct": 14.0,
                    "rss_mb": 120.0,
                    "widget_count": 260,
                    "ui_queue_depth": 2,
                    "gdi_objects": 22,
                    "user_objects": 20,
                },
            ],
            maxlen=720,
        )
        self._resource_latest = dict(self._resource_samples[-1])
        self._resource_baseline = {"rss_mb": 100.0, "uptime_s": 5}
        self._scan_thread = None
        self._build_running = False
        self._process = None
        self._log_chunk_chars = 0
        self._log_truncated = False
        self._log_viewers = []
        self._perf_events = deque(maxlen=160)
        self._perf_counters = {}
        self._perf_last_ms = {}
        self._perf_max_ms = {}

    def _count_widgets_cached(self) -> int:
        return 260

    def __getattr__(self, name):
        if name in {
            "_diagnostic_worst_health",
            "_diagnostic_percentile",
            "_diagnostic_health",
            "_diagnostic_health_color",
            "_fmt_metric",
            "_diagnostic_metric_ratio",
            "_diagnostic_metric_health",
            "_diagnostic_numeric_series",
            "_diagnostic_trend_direction",
        }:
            return getattr(ui.DiagnosticsWorkbenchUI, name)
        return MethodType(getattr(ui.DiagnosticsWorkbenchUI, name), self)


def test_diagnostics_popup_snapshot_reports_metrics_trends_and_events() -> None:
    app = HeadlessDiagnosticsUI()
    app._record_perf_event("Input scan", elapsed_ms=82.5, detail="folders")

    snapshot = app._diagnostics_snapshot()
    visual_specs = app._diagnostic_visual_specs(snapshot)
    trend_specs = app._diagnostic_trend_specs(snapshot)
    report = app._format_diagnostics_report()

    assert snapshot["health"] == "Watch"
    assert snapshot["loop_health"] == "Watch"
    assert snapshot["resource_health"] == "Healthy"
    assert snapshot["perf_counters"] == {"Input scan": 1}
    assert {spec["key"] for spec in visual_specs} == {
        "ui_p95",
        "cpu",
        "memory",
        "widgets",
        "queue",
        "handles",
    }
    assert {spec["key"] for spec in trend_specs} == {
        "ui",
        "cpu",
        "memory",
        "queue",
    }
    assert "Master Class Diagnostics Workbench diagnostics." in report
    assert "Input scan: 1." in report
