# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

from types import MethodType

import diagnostics_workbench_ui as ui
import pytest


class Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class ImmediateThread:
    def __init__(self, target, **kwargs):
        self.target = target

    def start(self):
        self.target()


class HeadlessUI:
    """Run real UI methods with scalar variables and no Tk window."""

    def __init__(self):
        self.step = 1
        self.data_root_var = Var()
        self.scan_confirmation_var = Var()
        self.scan_missing_var = Var()
        self.module_vars = {mod.key: Var(mod.key == "perfmon") for mod in ui.MODULES}
        self.module_input_override_vars = {
            ("perfmon", key): Var() for key in ("blg_path", "capture2_blg_path")
        }
        self.date_field_vars = {
            ("perfmon", "collection_start"): Var("09-01-2026"),
            ("perfmon", "collection_end"): Var("09-02-2026"),
        }
        for capture in ("perfmon", "perfmon2"):
            setattr(self, f"{capture}_processors_var", Var())
            setattr(self, f"{capture}_disks_var", Var())
            setattr(self, f"{capture}_memory_var", Var("32"))
            setattr(self, f"{capture}_vm_var", Var(True))
        self._discovered = {}
        self._optional_input_cache = {}
        self._last_scan_root = ""
        self._scan_token = 0
        self._scan_thread = None
        self._perfmon_detect_tokens = {"perfmon": 0, "perfmon2": 0}
        self._perfmon_detect_sources = {}

    def __getattr__(self, name):
        return MethodType(getattr(ui.DiagnosticsWorkbenchUI, name), self)

    def _post(self, callback):
        callback()

    def _clear_field_highlight(self, *args):
        pass

    def _sync_scan_confirmation_visibility(self):
        pass

    def _refresh_module_card_views(self, *args):
        pass

    def _rebuild_expansion(self, *args):
        pass

    def change_folder(self, root):
        self.data_root_var.set(str(root))
        self._on_data_root_changed()
        self._auto_scan_if_ready()

    def hardware(self, capture="perfmon"):
        return (
            getattr(self, f"{capture}_processors_var").get(),
            getattr(self, f"{capture}_disks_var").get(),
        )


@pytest.fixture
def detection(monkeypatch, tmp_path):
    captures = []
    for name in ("A", "B"):
        path = tmp_path / name / "Perfmon" / "server.blg"
        path.parent.mkdir(parents=True)
        path.touch()
        captures.append(path)
    queries = []
    hardware = dict(zip(captures, ((4, 1), (16, 3)), strict=True))

    def query(path):
        queries.append(path)
        cpus, disks = hardware[path]
        return [
            "Begin: 09/03/2026 08:00:00",
            "End: 09/04/2026 09:00:00",
            *(rf"\\HOST\Processor({n})\% Processor Time" for n in range(cpus)),
            *(rf"\\HOST\PhysicalDisk({n} C:)\Avg. Disk Queue Length" for n in range(disks)),
        ]

    monkeypatch.setattr(ui, "IS_WINDOWS", True)
    monkeypatch.setattr(ui.threading, "Thread", ImmediateThread)
    monkeypatch.setattr(ui, "relog_query_lines", query)
    app = HeadlessUI()
    yield app, captures, queries
    for capture in ("perfmon", "perfmon2"):
        assert getattr(app, f"{capture}_memory_var").get() == "32"
        assert getattr(app, f"{capture}_vm_var").get() is True
    assert app.date_field_vars[("perfmon", "collection_start")].get() == "09-01-2026"
    assert app.date_field_vars[("perfmon", "collection_end")].get() == "09-02-2026"


def test_initial_capture_and_different_data_folder(detection):
    app, (first, second), queries = detection
    app.change_folder(first.parents[1])
    assert app.hardware() == ("4", "1")
    app.change_folder(second.parents[1])
    assert app.hardware() == ("16", "3")
    assert app._perfmon_input_path() == second
    assert queries == [first, second]


@pytest.mark.parametrize("manual_override", [False, True])
def test_same_capture_rescan_preserves_hardware(detection, manual_override):
    app, (first, _), queries = detection
    app.change_folder(first.parents[1])
    if manual_override:
        app.perfmon_processors_var.set("8")
        app.perfmon_disks_var.set("2")
    expected = app.hardware()
    app._scan_inputs()
    assert app.hardware() == expected
    assert queries == [first]


@pytest.mark.parametrize(
    "capture,field", [("perfmon", "blg_path"), ("perfmon2", "capture2_blg_path")]
)
def test_browse_same_capture_preserves_override_and_replacement_refreshes(
    detection, monkeypatch, capture, field
):
    app, (first, second), queries = detection
    choices = iter((first, first, second))
    monkeypatch.setattr(ui.filedialog, "askopenfilename", lambda **kwargs: str(next(choices)))
    app._browse_module_input_field("perfmon", field)
    assert app.hardware(capture) == ("4", "1")
    getattr(app, f"{capture}_processors_var").set("8")
    getattr(app, f"{capture}_disks_var").set("2")
    app._browse_module_input_field("perfmon", field)
    assert app.hardware(capture) == ("8", "2")
    app._browse_module_input_field("perfmon", field)
    assert app.hardware(capture) == ("16", "3")
    assert queries == [first, second]
    other = "perfmon2" if capture == "perfmon" else "perfmon"
    assert app.hardware(other) == ("", "")


def test_folder_change_keeps_manual_capture_source_and_overrides(detection):
    app, (first, second), queries = detection
    app.module_input_override_vars[("perfmon", "blg_path")].set(str(first))
    app.change_folder(first.parents[1])
    app.perfmon_processors_var.set("8")
    app.perfmon_disks_var.set("2")
    app.change_folder(second.parents[1])
    assert app._perfmon_input_path() == first
    assert app.hardware() == ("8", "2")
    assert queries == [first]


@pytest.mark.parametrize("capture", ["perfmon", "perfmon2"])
def test_explicit_redetect_refreshes_same_capture(detection, capture):
    app, (first, _), queries = detection
    field = "blg_path" if capture == "perfmon" else "capture2_blg_path"
    app.module_input_override_vars[("perfmon", field)].set(str(first))
    app._start_perfmon_detection(capture=capture, auto=True)
    getattr(app, f"{capture}_processors_var").set("8")
    app._start_perfmon_detection(capture=capture)
    assert app.hardware(capture) == ("4", "1")
    assert queries == [first, first]


@pytest.mark.parametrize("capture", ["perfmon", "perfmon2"])
def test_late_detection_cannot_restore_previous_capture(detection, monkeypatch, capture):
    app, (first, second), _ = detection
    field = "blg_path" if capture == "perfmon" else "capture2_blg_path"
    callbacks = []
    monkeypatch.setattr(app, "_post", callbacks.append)
    app.module_input_override_vars[("perfmon", field)].set(str(first))
    app._start_perfmon_detection(capture=capture, auto=True)
    app.module_input_override_vars[("perfmon", field)].set(str(second))
    callbacks[0]()  # Source changed before replacement detection starts.
    assert app.hardware(capture) == (ui.DETECTING, ui.DETECTING)
    app._start_perfmon_detection(capture=capture, auto=True)
    callbacks[1]()
    callbacks[0]()  # Old token must not overwrite the new result either.
    assert app.hardware(capture) == ("16", "3")


def test_replacement_detection_failure_does_not_reuse_old_counts(detection, monkeypatch):
    app, (first, second), _ = detection
    app.change_folder(first.parents[1])

    def fail(path):
        raise OSError("Unreadable capture")

    monkeypatch.setattr(ui, "relog_query_lines", fail)
    app.change_folder(second.parents[1])
    assert app.hardware() == ("", "")


def test_return_to_capture_retries_discarded_detection(detection, monkeypatch):
    app, (first, _), queries = detection
    callbacks = []
    monkeypatch.setattr(app, "_post", callbacks.append)
    app.module_input_override_vars[("perfmon", "blg_path")].set(str(first))
    app._start_perfmon_detection(auto=True)
    app.module_input_override_vars[("perfmon", "blg_path")].set("")
    callbacks[0]()
    app.module_input_override_vars[("perfmon", "blg_path")].set(str(first))
    app._start_perfmon_detection(auto=True)
    assert len(callbacks) == 2
    callbacks[1]()
    assert app.hardware() == ("4", "1")
    assert queries == [first, first]
