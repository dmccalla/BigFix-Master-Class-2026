# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

from Lib.Core.performance_diagnostics import PerformanceRecorder


def test_recorder_writes_compact_json_evidence(tmp_path) -> None:
    recorder = PerformanceRecorder("engine", event_limit=2)
    recorder.update_metadata(selected_modules=["loop", "perfmon"])
    recorder.record("Build run context", elapsed_ms=12.3456)
    recorder.record("Child script", elapsed_ms=98.7654, detail="get_loop_health.py")

    path = recorder.write_json(tmp_path / "run-diagnostics.json", result="completed")
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["component"] == "engine"
    assert payload["metadata"] == {
        "selected_modules": ["loop", "perfmon"],
        "result": "completed",
    }
    assert payload["events"][-1] == {
        "time": payload["events"][-1]["time"],
        "name": "Child script",
        "elapsed_ms": 98.77,
        "detail": "get_loop_health.py",
    }


def test_recorder_bounds_events_and_reset_starts_a_new_window() -> None:
    recorder = PerformanceRecorder("desktop_ui", event_limit=2)
    recorder.record("first")
    recorder.record("second")
    recorder.record("third")

    assert [event["name"] for event in recorder.snapshot()["events"]] == [
        "second",
        "third",
    ]

    recorder.reset(run="next")
    assert recorder.snapshot()["metadata"] == {"run": "next"}
    assert recorder.snapshot()["events"] == []
