# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

from __future__ import annotations

from types import MethodType

import diagnostics_workbench_ui as ui


class _Var:
    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


class _HeadlessThemeUI:
    def __init__(self, dark_mode: bool) -> None:
        self.dark_mode_var = _Var(dark_mode)
        self.step = 2
        self.closed_diagnostics = 0
        self.shown_steps: list[int] = []

    def _close_diagnostics_window(self) -> None:
        self.closed_diagnostics += 1

    def _show_step(self, step: int) -> None:
        self.shown_steps.append(step)

    def __getattr__(self, name):
        return MethodType(getattr(ui.DiagnosticsWorkbenchUI, name), self)


def test_theme_toggle_applies_mode_and_redraws_active_step(monkeypatch) -> None:
    selected_modes: list[str] = []
    monkeypatch.setattr(ui.ctk, "set_appearance_mode", selected_modes.append)

    app = _HeadlessThemeUI(dark_mode=True)
    app._toggle_theme()

    assert selected_modes == ["dark"]
    assert app.closed_diagnostics == 1
    assert app.shown_steps == [2]


def test_mode_color_resolves_the_active_appearance(monkeypatch) -> None:
    monkeypatch.setattr(ui.ctk, "get_appearance_mode", lambda: "Dark")
    assert ui._mode_color(("#FFFFFF", "#111111")) == "#111111"
    assert ui._mode_color("#123456") == "#123456"
