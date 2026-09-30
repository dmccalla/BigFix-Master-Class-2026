# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

from types import MethodType

import diagnostics_workbench_ui as ui


class Widget:
    def __init__(self):
        self.options = {}

    def configure(self, **kwargs):
        self.options.update(kwargs)

    def winfo_exists(self):
        return True


class HeadlessUI:
    def __init__(self):
        self._log_chunks = []
        self._log_viewers = []
        self._open_output_buttons = []
        self._progress_order = []
        self._run_folder = None
        self._run_log_path = None
        self._footer_run_label = Widget()
        self.open_output_button = Widget()

    def __getattr__(self, name):
        return MethodType(getattr(ui.DiagnosticsWorkbenchUI, name), self)


def test_summary_run_folder_enables_open_output_for_existing_log_window(tmp_path):
    app = HeadlessUI()
    log_window_button = Widget()
    app._open_output_buttons.append(log_window_button)
    run_folder = tmp_path / "Class_Test_1_20260930_123438"
    run_folder.mkdir()

    app._append_log(f"   Run folder : {run_folder}\n")

    assert app._output_folder_to_open() == run_folder
    assert app._footer_run_label.options["text"] == str(run_folder)
    assert app.open_output_button.options["state"] == "normal"
    assert log_window_button.options["state"] == "normal"


def test_machine_run_folder_marker_remains_supported(tmp_path):
    app = HeadlessUI()
    run_folder = tmp_path / "Class_Test_1_20260930_123438"
    run_folder.mkdir()

    app._append_log(f"RUN_FOLDER: {run_folder}\n")

    assert app._output_folder_to_open() == run_folder
