# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

from __future__ import annotations

import json

import run_diagnostics as runner

from Lib.Core.performance_diagnostics import PerformanceRecorder


def test_child_script_timing_and_run_diagnostics_sidecar(tmp_path) -> None:
    child = tmp_path / "child.py"
    child.write_text("print('child completed')\n", encoding="utf-8")
    recorder = PerformanceRecorder("engine")
    log = runner.RunLog(recorder)

    assert runner.run_python(child, [], log) == 0
    runner._write_run_diagnostics(
        tmp_path,
        "Class_Test",
        recorder,
        log,
        result="completed",
    )

    path = tmp_path / "Class_Test_Run_Diagnostics.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    child_event = next(
        event for event in payload["events"] if event["name"] == "Child script"
    )
    assert child_event["detail"] == "child.py"
    assert child_event["return_code"] == 0
    assert payload["metadata"]["result"] == "completed"
