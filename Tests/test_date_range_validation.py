# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import diagnostics_workbench_ui as ui
import pytest

UI_CLASS = ui.DiagnosticsWorkbenchUI
BUILD_METHOD = "_run_engine"


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


@pytest.fixture
def form():
    app = object.__new__(UI_CLASS)
    app.step = 2
    app._build_running = False
    app._modules_awaiting_review = lambda _keys: []
    app._module_row_status = lambda _key: ("Found", "")
    app._browsable_input_fields = lambda _mod: []
    app._selected_deployment_reference_dependents = lambda: []
    app.build_word_var = Var(False)
    app.template_var = Var()
    app.perfmon_additional_blg_var = Var()
    app._perfmon_capture2_path = lambda: None
    app._perfmon_input_path = lambda: None
    app.perfmon_processors_var = Var("6")
    app.perfmon_disks_var = Var("3")
    app.perfmon_memory_var = Var("12")
    app.date_field_vars = {
        (mod.key, field.key): Var()
        for mod in ui.MODULES
        for field in mod.inputs_schema
        if field.kind in {"date_optional", "datetime_optional"}
    }
    app.reported_errors = []
    app.highlighted_fields = set()
    app._show_errors = lambda _title, errors: app.reported_errors.extend(errors)
    app._apply_field_highlights = app.highlighted_fields.update
    app._reveal_step2_fields = lambda _fields: None
    app._show_step = lambda step: setattr(app, "step", step)
    app._validate_step1 = lambda: ([], set())
    return app


def set_range(form, module, start, end):
    form._selected_keys = lambda: [module]
    start_key, end_key = (
        ("start_date", "end_date")
        if module == "loop"
        else ("collection_start", "collection_end")
    )
    form.date_field_vars[(module, start_key)].set(start)
    form.date_field_vars[(module, end_key)].set(end)
    return {f"{module}:{start_key}", f"{module}:{end_key}"}


@pytest.mark.parametrize("module", ["loop", "perfmon", "filldb"])
def test_reversed_dates_block_next_and_highlight_both_fields(form, module):
    expected = set_range(form, module, "10-06-2026", "10-03-2026")
    form._next()
    assert form.step == 2
    assert form.highlighted_fields == expected
    assert any("cannot be earlier" in message for message in form.reported_errors)


@pytest.mark.parametrize("module", ["loop", "perfmon", "filldb"])
def test_reversed_dates_block_build_before_config_is_written(form, module):
    set_range(form, module, "10-06-2026", "10-03-2026")
    form.step = 3
    form._build_config = lambda: pytest.fail("Invalid dates reached the build")
    getattr(form, BUILD_METHOD)()
    assert any("cannot be earlier" in message for message in form.reported_errors)
    assert form._build_running is False


@pytest.mark.parametrize("module", ["loop", "perfmon", "filldb"])
@pytest.mark.parametrize(
    "start,end",
    [
        ("10-05-2026", "10-06-2026"),
        ("10-06-2026", "10-06-2026"),
        ("12-31-2025", "01-01-2026"),
        ("2026-10-05", "10/06/2026"),
        ("10-05-26", "10-06-26"),
    ],
)
def test_valid_date_ranges_are_accepted(form, module, start, end):
    set_range(form, module, start, end)
    bad_fields = set()
    assert form._validate_step2(bad_fields) == []
    assert bad_fields == set()


@pytest.mark.parametrize("module", ["perfmon", "filldb"])
@pytest.mark.parametrize(
    "start,end,valid",
    [
        ("10-06-2026 09:01", "10-06-2026 09:00", False),
        ("10-06-2026 09:00:01", "10-06-2026 09:00:00", False),
        ("10-06-2026 09:00", "10-06-2026 09:00", True),
        ("10-05-2026 23:59", "10-06-2026 00:00", True),
        ("", "", True),
        ("10-05-2026", "", True),
        ("", "10-06-2026", True),
    ],
)
def test_collection_ranges_compare_times_and_preserve_optional_dates(
    form, module, start, end, valid
):
    expected = set_range(form, module, start, end)
    bad_fields = set()
    errors = form._validate_step2(bad_fields)
    assert bool(errors) is not valid
    assert bad_fields == (set() if valid else expected)


@pytest.mark.parametrize("module", ["loop", "perfmon", "filldb"])
def test_invalid_date_keeps_its_format_error(form, module):
    expected = set_range(form, module, "02-30-2026", "03-01-2026")
    bad_fields = set()
    errors = form._validate_step2(bad_fields)
    assert len(errors) == 1
    assert "must use" in errors[0]
    assert bad_fields == {field for field in expected if "start" in field}


def test_unselected_modules_do_not_block_a_valid_range(form):
    set_range(form, "filldb", "10-06-2026", "10-03-2026")
    set_range(form, "loop", "10-05-2026", "10-06-2026")
    assert form._validate_step2() == []
