# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""The Deployment_Information folder is a required Client Performance input.

The schema keeps it folder_optional so discovery can fill it in. The UI treats
it as required, so a loop export with no folder reads Needs A File.
"""

from __future__ import annotations

from pathlib import Path

import diagnostics_workbench_ui as ui_module
from run_diagnostics import MODULE_BY_KEY


class _Var:
    def __init__(self, value: str = "") -> None:
        self._value = value

    def get(self) -> str:
        return self._value


def _make_ui(tmp_path: Path, deployment_folder: Path | None):
    ui = object.__new__(ui_module.DiagnosticsWorkbenchUI)
    loop_export = tmp_path / "Client_Loop_10-01-2026_1200.xml"
    loop_export.write_text("<BESAPI/>", encoding="utf-8")
    ui.data_root_var = _Var("")
    ui.module_input_override_vars = {
        ("loop", "input_xlsx"): _Var(str(loop_export)),
        ("loop", "deployment_info_folder"): _Var(
            str(deployment_folder) if deployment_folder else ""
        ),
    }
    ui._discovered = {}
    ui._validate_field_input = lambda _mod, _field, _path: (True, "")
    return ui


def test_loop_requires_deployment_information_folder(tmp_path: Path) -> None:
    ui = _make_ui(tmp_path, None)
    mod = MODULE_BY_KEY["loop"]
    field = next(f for f in mod.inputs_schema if f.key == "deployment_info_folder")

    assert ui._missing_required_input_labels("loop") == ["Deployment_Information folder"]
    assert ui._input_field_state(mod, field) == ("Needed", "Not selected")
    status, detail = ui._scan_status(mod)
    assert status == "Missing"
    assert "Deployment_Information folder" in detail


def test_loop_is_found_once_deployment_information_folder_is_picked(
    tmp_path: Path,
) -> None:
    folder = tmp_path / "Deployment_Information"
    folder.mkdir()
    ui = _make_ui(tmp_path, folder)
    mod = MODULE_BY_KEY["loop"]

    assert ui._missing_required_input_labels("loop") == []
    assert ui._scan_status(mod)[0] == "Found"


def test_other_modules_do_not_require_deployment_information(tmp_path: Path) -> None:
    ui = _make_ui(tmp_path, None)

    assert "Deployment_Information folder" not in ui._missing_required_input_labels(
        "filldb"
    )
