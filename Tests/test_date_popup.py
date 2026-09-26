# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""The date picker is a plain tkinter month grid with no calendar package."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from tkinter import TclError

import pytest

ROOT = Path(__file__).resolve().parents[1]
for folder in (ROOT, ROOT / "App"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import diagnostics_workbench_ui as ui  # noqa: E402


@pytest.fixture(scope="module")
def root():
    # One Tk interpreter for the module. Creating and destroying a root per
    # test makes Tcl lose its init.tcl after a few rounds on Windows.
    try:
        app = ui.ctk.CTk()
    except TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"Tk is not available here: {exc}")
    app.withdraw()
    yield app
    app.destroy()


@pytest.fixture
def anchor(root):
    label = ui.ctk.CTkLabel(root, text="anchor")
    label.pack()
    yield label
    label.destroy()


def _pump(widget, times: int = 5) -> None:
    for _ in range(times):
        widget.update_idletasks()
        widget.update()


def _cell_for(popup: ui.DatePopup, day: date):
    return next(cell for cell, cell_date in popup._cell_dates.items() if cell_date == day)


def test_no_calendar_package_is_imported() -> None:
    assert "tkcalendar" not in sys.modules
    assert "tkcalendar" not in Path(ui.__file__).read_text(encoding="utf-8")


def test_grid_shows_the_month_and_blanks_the_other_days(root, anchor) -> None:
    picked: list[date] = []
    popup = ui.DatePopup(root, anchor, date(2026, 2, 10), picked.append, lambda: None)
    _pump(root)
    assert popup._month_label is not None
    assert popup._month_label.cget("text") == "February 2026"
    shown = [cell.cget("text") for cell in popup._cells]
    # February 2026 starts on a Sunday, so six blanks lead the Monday-first grid.
    assert shown[:7] == ["", "", "", "", "", "", "1"]
    assert shown.count("") == 42 - 28
    assert _cell_for(popup, date(2026, 2, 10)).cget("bg") == ui.PLUM
    popup._close()


def test_month_navigation_crosses_the_year(root, anchor) -> None:
    popup = ui.DatePopup(root, anchor, date(2026, 1, 15), lambda _d: None, lambda: None)
    _pump(root)
    popup._shift_month(-1)
    assert popup._shown == date(2025, 12, 1)
    assert popup._month_label.cget("text") == "December 2025"
    popup._shift_month(2)
    assert popup._shown == date(2026, 2, 1)
    popup._close()


def test_clicking_a_day_picks_it_and_closes(root, anchor) -> None:
    picked: list[date] = []
    popup = ui.DatePopup(root, anchor, date(2026, 6, 14), picked.append, lambda: None)
    _pump(root)
    popup._pick_cell(_cell_for(popup, date(2026, 6, 20)))
    _pump(root)
    assert picked == [date(2026, 6, 20)]
    assert not popup.winfo_exists()


def test_clear_calls_back_and_closes(root, anchor) -> None:
    cleared: list[bool] = []
    popup = ui.DatePopup(
        root, anchor, None, lambda _d: None, lambda: cleared.append(True)
    )
    _pump(root)
    popup._do_clear()
    _pump(root)
    assert cleared == [True]
    assert not popup.winfo_exists()
