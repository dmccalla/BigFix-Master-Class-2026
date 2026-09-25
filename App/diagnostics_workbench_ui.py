#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
diagnostics_workbench_ui.py -- the Master Class Diagnostics Workbench desktop app.

Two panes:

  1. Inputs. Pick the run folder, choose the modules, point each one at its
     data. A data folder can be scanned to fill the inputs automatically, and
     any input can be browsed or typed by hand.
  2. Run. Watch the engine (App/run_diagnostics.py) work through the selected
     modules, then open the run folder and the files it produced.

The app never analyses anything itself. It writes a JSON config and runs the
engine as a child process, streaming its output into the log.
"""

from __future__ import annotations

import json
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from tkinter import TclError, filedialog, messagebox

import customtkinter as ctk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
for folder in (PROJECT_ROOT, APP_DIR):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from run_diagnostics import (
    APP_TITLE,
    MODULE_BY_KEY,
    MODULES,
    InputField,
    Module,
    _parse_optional_datetime,
    detect_hardware_from_blg,
    detect_perfmon_window,
    discover_loop_ancillary_inputs,
    relog_query_lines,
    scan_input_folder,
)

from Lib.Core.input_utils import DEFAULT_WORK_DIR, clean_user_path, open_path
from Lib.Core.subprocess_window import hidden_subprocess_kwargs
from Lib.Design.design_system import DESIGN_SYSTEM as DS

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

# ---------------------------------------------------------------------------
# Design tokens (light mode). Colors come from the shared design system.
# ---------------------------------------------------------------------------

CANVAS = DS.tech_grey.hex_value
PAPER = DS.white.hex_value
INK = DS.midnight.hex_value
MUTED = DS.text_muted.hex_value
PLUM = DS.accent_blue.hex_value
CLAY = DS.critical.hex_value
SUCCESS = DS.success.hex_value
HAIRLINE = "#E3E9F1"
FIELD_BORDER = "#CFD9E5"
PANEL = "#F4F7FB"
LOG_BG = DS.midnight.hex_value
LOG_TEXT = "#EAF1F8"
UI_FONT = "Segoe UI"
MONO_FONT = "Consolas"

PILL_STYLES = {
    "Found": (SUCCESS, "#E7F4EC"),
    "Chosen": (SUCCESS, "#E7F4EC"),
    "Missing": (CLAY, "#FDECEA"),
    "Not selected": (MUTED, "#F0F3F8"),
    "Windows only": (MUTED, "#F0F3F8"),
}

CONFIG_PATH = PROJECT_ROOT / "diagnostics_workbench.ui.config.json"
DETECTING = "Detecting..."

_RUN_FOLDER_RE = re.compile(r"^RUN_FOLDER:\s*(.+?)\s*$")
_MODULE_RE = re.compile(r"^\s*MODULE (\d+) OF (\d+)\s*$")
_STEP_RE = re.compile(r"^\s*Step:\s*(.+?)\s*$")
_RUN_LOG_RE = re.compile(r"^\s*Run log\s*:\s*(.+?)\s*$")

BROWSABLE_KINDS = {"file", "file_optional", "folder_optional"}
TEXT_KINDS = {"file", "file_optional", "folder_optional", "int", "int_detected", "datetime_optional"}
OUTPUT_SUFFIXES = {".docx", ".xlsx", ".png"}


def _display_path(value: object) -> str:
    text = clean_user_path(value)
    return str(Path(text)) if text else ""


def _field_id(key: str, field_key: str) -> str:
    return f"{key}:{field_key}"


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------


class DiagnosticsWorkbenchUI(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1200x840")
        self.minsize(980, 700)
        self.configure(fg_color=CANVAS)

        # ---- state ------------------------------------------------------
        self.run_name_var = ctk.StringVar(value="")
        self.output_folder_var = ctk.StringVar(value=_display_path(DEFAULT_WORK_DIR))
        self.data_root_var = ctk.StringVar(value="")
        self.scan_status_var = ctk.StringVar(value="")
        self.module_vars: dict[str, ctk.BooleanVar] = {
            mod.key: ctk.BooleanVar(value=self._module_available(mod)) for mod in MODULES
        }
        self.field_vars: dict[tuple[str, str], ctk.StringVar] = {}
        self.bool_vars: dict[tuple[str, str], ctk.BooleanVar] = {}
        for mod in MODULES:
            for field in mod.inputs_schema:
                if field.kind == "bool":
                    self.bool_vars[(mod.key, field.key)] = ctk.BooleanVar(value=False)
                else:
                    default = "" if field.default in (None, 0) else str(field.default)
                    self.field_vars[(mod.key, field.key)] = ctk.StringVar(value=default)
        # Inputs the user browsed or typed. The engine never replaces these.
        self._manual_fields: set[tuple[str, str]] = set()
        self._programmatic = 0
        self._discovered: dict[str, Path | None] = {}
        self._pill_labels: dict[str, ctk.CTkLabel] = {}
        # Validation highlighting: one registry for every pane, each entry
        # remembers the border it returns to when the highlight clears.
        self._field_widgets: dict[str, ctk.CTkEntry] = {}
        self._field_rest_borders: dict[str, str] = {}

        self._process: subprocess.Popen | None = None
        self._log_queue: queue.Queue[str | None] = queue.Queue()
        # Worker threads never touch Tk. They post callables here and the main
        # thread runs them from _drain_ui_queue.
        self._ui_queue: queue.Queue = queue.Queue()
        self._running = False
        self._cancel_requested = False
        self._run_folder: Path | None = None
        self._run_log_path: Path | None = None
        self._module_total = 0
        self._perfmon_detect_token = 0

        for (key, field_key), var in self.field_vars.items():
            var.trace_add(
                "write",
                lambda *_a, k=key, f=field_key: self._on_field_edited(k, f),
            )
        self.output_folder_var.trace_add(
            "write", lambda *_a: self._clear_field_highlight("output_folder")
        )
        self.data_root_var.trace_add(
            "write", lambda *_a: self._clear_field_highlight("data_root")
        )

        # ---- layout -----------------------------------------------------
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self._build_header()
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew", padx=24, pady=(0, 20))
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.pane_inputs = self._build_inputs_pane(self.content)
        self.pane_run = self._build_run_pane(self.content)
        self._show_pane("inputs")
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_ui_queue)

    # ------------------------------------------------------------------
    # Static helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _module_available(mod: Module) -> bool:
        return not (mod.windows_only and sys.platform != "win32")

    def _post(self, callback) -> None:
        """Hand a callable from a worker thread to the main thread."""
        self._ui_queue.put(callback)

    def _drain_ui_queue(self) -> None:
        while True:
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except TclError:
                pass
        try:
            self.after(100, self._drain_ui_queue)
        except TclError:
            pass

    def _set_var(self, var, value) -> None:
        """Programmatic write that does not count as a manual edit."""
        self._programmatic += 1
        try:
            var.set(value)
        finally:
            self._programmatic -= 1

    def _on_field_edited(self, key: str, field_key: str) -> None:
        self._clear_field_highlight(_field_id(key, field_key))
        if self._programmatic:
            return
        value = self.field_vars[(key, field_key)].get().strip()
        if value:
            self._manual_fields.add((key, field_key))
        else:
            self._manual_fields.discard((key, field_key))
        mod = MODULE_BY_KEY[key]
        if field_key == mod.file_key:
            self._refresh_pill(key)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=INK, corner_radius=0, height=76)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            bar,
            text=APP_TITLE,
            text_color=PAPER,
            font=(UI_FONT, 22, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=24, pady=(16, 0))
        ctk.CTkLabel(
            bar,
            text="Automated performance and configuration analysis for BigFix",
            text_color="#B8C4D6",
            font=(UI_FONT, 13),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=24, pady=(0, 14))
        self.pane_label = ctk.CTkLabel(
            bar, text="1  Inputs", text_color="#B8C4D6", font=(UI_FONT, 14, "bold")
        )
        self.pane_label.grid(row=0, column=1, rowspan=2, sticky="e", padx=24)

    def _show_pane(self, name: str) -> None:
        if name == "inputs":
            self.pane_run.grid_remove()
            self.pane_inputs.grid(row=0, column=0, sticky="nsew")
            self.pane_label.configure(text="1  Inputs")
        else:
            self.pane_inputs.grid_remove()
            self.pane_run.grid(row=0, column=0, sticky="nsew")
            self.pane_label.configure(text="2  Run")

    # ------------------------------------------------------------------
    # Pane 1: inputs
    # ------------------------------------------------------------------

    def _card(self, parent, title: str, subtitle: str = "") -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent, fg_color=PAPER, corner_radius=10, border_width=1, border_color=HAIRLINE
        )
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card, text=title, text_color=INK, font=(UI_FONT, 16, "bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        if subtitle:
            ctk.CTkLabel(
                card,
                text=subtitle,
                text_color=MUTED,
                font=(UI_FONT, 12),
                anchor="w",
                justify="left",
                wraplength=980,
            ).grid(row=1, column=0, sticky="w", padx=18, pady=(2, 0))
        return card

    def _entry(self, parent, var, field_id: str, placeholder: str = "") -> ctk.CTkEntry:
        entry = ctk.CTkEntry(
            parent,
            textvariable=var,
            placeholder_text=placeholder,
            height=36,
            corner_radius=8,
            border_width=1,
            border_color=FIELD_BORDER,
            fg_color=PAPER,
            text_color=INK,
            font=(UI_FONT, 13),
        )
        self._field_widgets[field_id] = entry
        self._field_rest_borders[field_id] = FIELD_BORDER
        return entry

    def _button(self, parent, text: str, command, primary: bool = False, **kw):
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=36,
            corner_radius=8,
            fg_color=PLUM if primary else PAPER,
            hover_color="#0B4FB8" if primary else PANEL,
            text_color=PAPER if primary else INK,
            border_width=0 if primary else 1,
            border_color=FIELD_BORDER,
            font=(UI_FONT, 13, "bold" if primary else "normal"),
            **kw,
        )

    def _build_inputs_pane(self, parent) -> ctk.CTkFrame:
        pane = ctk.CTkScrollableFrame(parent, fg_color="transparent")
        pane.grid_columnconfigure(0, weight=1)

        # Run card
        run = self._card(
            pane,
            "Run",
            "Name the run, choose where the outputs go, and optionally point at a "
            "data folder to fill the module inputs automatically.",
        )
        run.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        grid = ctk.CTkFrame(run, fg_color="transparent")
        grid.grid(row=2, column=0, sticky="ew", padx=18, pady=(10, 16))
        grid.grid_columnconfigure(1, weight=1)
        rows = [
            ("Run name (optional)", self.run_name_var, "run_name", None, "Lab 1"),
            ("Output folder", self.output_folder_var, "output_folder", "folder", ""),
            ("Data folder (optional)", self.data_root_var, "data_root", "folder", ""),
        ]
        for row, (label, var, fid, browse, placeholder) in enumerate(rows):
            ctk.CTkLabel(grid, text=label, text_color=INK, font=(UI_FONT, 13), anchor="w").grid(
                row=row, column=0, sticky="w", padx=(0, 12), pady=4
            )
            self._entry(grid, var, fid, placeholder).grid(
                row=row, column=1, sticky="ew", pady=4
            )
            if browse:
                self._button(
                    grid, "Browse", lambda v=var: self._browse_folder(v), width=90
                ).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=4)
        self._button(grid, "Scan data folder", self._scan_data_root, width=150).grid(
            row=2, column=3, sticky="e", padx=(8, 0), pady=4
        )
        ctk.CTkLabel(
            grid, textvariable=self.scan_status_var, text_color=MUTED, font=(UI_FONT, 12), anchor="w"
        ).grid(row=3, column=1, columnspan=3, sticky="w", pady=(2, 0))

        # Module cards
        for index, mod in enumerate(MODULES, start=1):
            self._build_module_card(pane, mod).grid(row=index, column=0, sticky="ew", pady=(0, 14))

        # Actions
        actions = ctk.CTkFrame(pane, fg_color="transparent")
        actions.grid(row=len(MODULES) + 1, column=0, sticky="ew", pady=(4, 12))
        actions.grid_columnconfigure(0, weight=1)
        self._button(actions, "Reset", self._reset, width=110).grid(row=0, column=0, sticky="w")
        self._button(actions, "Run analysis", self._start_run, primary=True, width=180).grid(
            row=0, column=1, sticky="e"
        )
        return pane

    def _build_module_card(self, parent, mod: Module) -> ctk.CTkFrame:
        card = ctk.CTkFrame(
            parent, fg_color=PAPER, corner_radius=10, border_width=1, border_color=HAIRLINE
        )
        card.grid_columnconfigure(1, weight=1)
        available = self._module_available(mod)
        check = ctk.CTkCheckBox(
            card,
            text=mod.label,
            variable=self.module_vars[mod.key],
            command=lambda k=mod.key: self._refresh_pill(k),
            text_color=INK,
            font=(UI_FONT, 16, "bold"),
            fg_color=PLUM,
            hover_color="#0B4FB8",
            state="normal" if available else "disabled",
        )
        check.grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        ctk.CTkLabel(
            card, text=f"Outputs: {mod.outputs}", text_color=MUTED, font=(UI_FONT, 12), anchor="w"
        ).grid(row=0, column=1, sticky="w", padx=(6, 0), pady=(14, 0))
        pill = ctk.CTkLabel(
            card,
            text="",
            font=(UI_FONT, 12, "bold"),
            corner_radius=12,
            width=110,
            height=26,
        )
        pill.grid(row=0, column=2, sticky="e", padx=18, pady=(14, 0))
        self._pill_labels[mod.key] = pill

        body = ctk.CTkFrame(card, fg_color="transparent")
        body.grid(row=1, column=0, columnspan=3, sticky="ew", padx=18, pady=(8, 6))
        body.grid_columnconfigure(1, weight=1)
        for row, field in enumerate(mod.inputs_schema):
            self._build_field_row(body, mod, field, row)

        if mod.note:
            ctk.CTkLabel(
                card,
                text=mod.note,
                text_color=MUTED,
                font=(UI_FONT, 12),
                anchor="w",
                justify="left",
                wraplength=1040,
            ).grid(row=2, column=0, columnspan=3, sticky="w", padx=18, pady=(0, 14))
        else:
            ctk.CTkFrame(card, fg_color="transparent", height=8).grid(row=2, column=0)
        self._refresh_pill(mod.key)
        return card

    def _build_field_row(self, body, mod: Module, field: InputField, row: int) -> None:
        required = field.kind in {"file", "int_detected"} or (
            mod.key == "perfmon" and field.key == "physical_memory_gb"
        )
        label = field.label + (" *" if required else "")
        ctk.CTkLabel(body, text=label, text_color=INK, font=(UI_FONT, 13), anchor="w").grid(
            row=row, column=0, sticky="w", padx=(0, 12), pady=3
        )
        if field.kind == "bool":
            ctk.CTkCheckBox(
                body,
                text="",
                variable=self.bool_vars[(mod.key, field.key)],
                fg_color=PLUM,
                hover_color="#0B4FB8",
                width=24,
            ).grid(row=row, column=1, sticky="w", pady=3)
            return
        placeholder = ""
        if field.kind == "datetime_optional":
            placeholder = "MM-DD-YYYY HH:MM (optional)"
        elif field.kind in {"int", "int_detected"}:
            placeholder = "whole number"
        elif field.kind in {"file_optional", "folder_optional"}:
            placeholder = "optional"
        entry = self._entry(
            body, self.field_vars[(mod.key, field.key)], _field_id(mod.key, field.key), placeholder
        )
        entry.grid(row=row, column=1, sticky="ew", pady=3)
        if field.kind in BROWSABLE_KINDS:
            self._button(
                body,
                "Browse",
                lambda m=mod, f=field: self._browse_field(m, f),
                width=90,
            ).grid(row=row, column=2, sticky="e", padx=(8, 0), pady=3)

    # ------------------------------------------------------------------
    # Pills and discovery
    # ------------------------------------------------------------------

    def _primary_path(self, key: str) -> Path | None:
        mod = MODULE_BY_KEY[key]
        if mod.file_key is None:
            return None
        text = self.field_vars[(key, mod.file_key)].get().strip()
        return Path(text) if text else None

    def _module_status(self, key: str) -> str:
        mod = MODULE_BY_KEY[key]
        if not self._module_available(mod):
            return "Windows only"
        if not self.module_vars[key].get():
            return "Not selected"
        path = self._primary_path(key)
        if path is None or not path.is_file():
            return "Missing"
        return "Chosen" if (key, mod.file_key) in self._manual_fields else "Found"

    def _refresh_pill(self, key: str) -> None:
        pill = self._pill_labels.get(key)
        if pill is None:
            return
        status = self._module_status(key)
        fg, bg = PILL_STYLES[status]
        try:
            pill.configure(text=status, text_color=fg, fg_color=bg)
        except TclError:
            pass

    def _browse_folder(self, var) -> None:
        current = var.get().strip()
        path = filedialog.askdirectory(
            title="Choose a folder", initialdir=current if Path(current).is_dir() else None
        )
        if path:
            var.set(_display_path(path))

    def _browse_field(self, mod: Module, field: InputField) -> None:
        var = self.field_vars[(mod.key, field.key)]
        current = var.get().strip()
        initial = str(Path(current).parent) if current else self.data_root_var.get().strip() or None
        if field.kind == "folder_optional":
            path = filedialog.askdirectory(title=f"Choose the {field.label}", initialdir=initial)
        else:
            patterns = " ".join(f"*{ext}" for ext in sorted(field.extensions or {"*"}))
            path = filedialog.askopenfilename(
                title=f"Choose the {field.label}",
                filetypes=[(field.label, patterns), ("All files", "*.*")],
                initialdir=initial,
            )
        if not path:
            return
        var.set(_display_path(path))  # counts as a manual edit through the trace
        self.module_vars[mod.key].set(True)
        self._after_primary_input_set(mod, field)

    def _after_primary_input_set(self, mod: Module, field: InputField) -> None:
        if field.key != mod.file_key:
            return
        self._refresh_pill(mod.key)
        if mod.key == "loop":
            self._fill_loop_ancillaries()
        if mod.key == "perfmon" and field.key == "blg_path":
            self._start_perfmon_detection(self._primary_path("perfmon"))
        if mod.key == "perfmon" and field.key == "capture2_blg_path":
            self._start_perfmon_detection(self._primary_path("perfmon"))

    def _scan_data_root(self) -> None:
        root_text = self.data_root_var.get().strip()
        root = Path(root_text) if root_text else None
        if root is None or not root.is_dir():
            self._apply_field_highlights({"data_root"})
            messagebox.showerror("Check folders", "- Data folder must be an existing folder.")
            return
        self.scan_status_var.set("Scanning...")

        def worker() -> None:
            found = scan_input_folder(root)
            self._post(lambda: self._apply_scan(root, found))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_scan(self, root: Path, found: dict[str, Path | None]) -> None:
        self._discovered = found
        filled = []
        for mod in MODULES:
            path = found.get(mod.key)
            if path is None or mod.file_key is None:
                continue
            if (mod.key, mod.file_key) in self._manual_fields:
                continue
            self._set_var(self.field_vars[(mod.key, mod.file_key)], _display_path(path))
            filled.append(mod.label)
            self._refresh_pill(mod.key)
        self._fill_loop_ancillaries(root)
        if self._primary_path("perfmon") is not None:
            self._start_perfmon_detection(self._primary_path("perfmon"))
        self.scan_status_var.set(
            "Scan found: " + ", ".join(filled) if filled else "Scan found no module inputs."
        )

    def _fill_loop_ancillaries(self, root: Path | None = None) -> None:
        if root is None:
            root_text = self.data_root_var.get().strip()
            root = Path(root_text) if root_text and Path(root_text).is_dir() else None
        loop_input = self._primary_path("loop")
        try:
            ancillary = discover_loop_ancillary_inputs(root, loop_input)
        except Exception:
            return
        for field_key, path in ancillary.items():
            if ("loop", field_key) in self._manual_fields:
                continue
            self._set_var(self.field_vars[("loop", field_key)], _display_path(path) if path else "")

    def _start_perfmon_detection(self, blg: Path | None) -> None:
        if blg is None or not blg.is_file() or sys.platform != "win32":
            return
        self._perfmon_detect_token += 1
        token = self._perfmon_detect_token
        for field_key in ("logical_processors", "physical_disks"):
            if ("perfmon", field_key) not in self._manual_fields:
                self._set_var(self.field_vars[("perfmon", field_key)], DETECTING)

        def worker() -> None:
            try:
                lines = relog_query_lines(blg)
                procs, disks, _volumes = detect_hardware_from_blg(blg, lines)
                begin, end = detect_perfmon_window(lines)
            except Exception:
                procs, disks, begin, end = 0, 0, "", ""
            self._post(lambda: self._apply_perfmon_detection(token, procs, disks, begin, end))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_perfmon_detection(self, token: int, procs: int, disks: int, begin: str, end: str) -> None:
        if token != self._perfmon_detect_token:
            return
        values = {
            "logical_processors": str(procs) if procs > 0 else "",
            "physical_disks": str(disks) if disks > 0 else "",
            "collection_start": begin,
            "collection_end": end,
        }
        for field_key, value in values.items():
            if ("perfmon", field_key) in self._manual_fields:
                continue
            var = self.field_vars[("perfmon", field_key)]
            if field_key.startswith("collection") and var.get().strip():
                continue
            self._set_var(var, value)

    # ------------------------------------------------------------------
    # Validation and highlighting
    # ------------------------------------------------------------------

    def _apply_field_highlights(self, field_ids) -> None:
        for fid in set(field_ids):
            widget = self._field_widgets.get(fid)
            if widget is None:
                continue
            try:
                widget.configure(border_width=2, border_color=CLAY)
            except TclError:
                self._field_widgets.pop(fid, None)

    def _clear_field_highlight(self, field_id: str) -> None:
        widget = self._field_widgets.get(field_id)
        if widget is None:
            return
        try:
            widget.configure(
                border_width=1, border_color=self._field_rest_borders.get(field_id, FIELD_BORDER)
            )
        except TclError:
            self._field_widgets.pop(field_id, None)

    def _selected_keys(self) -> list[str]:
        return [
            mod.key
            for mod in MODULES
            if self.module_vars[mod.key].get() and self._module_available(mod)
        ]

    def _validate(self) -> tuple[list[str], set[str]]:
        errors: list[str] = []
        bad: set[str] = set()
        output_text = self.output_folder_var.get().strip()
        if not output_text:
            errors.append("Output folder is required.")
            bad.add("output_folder")
        else:
            try:
                Path(output_text).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                errors.append(f"Output folder could not be created: {exc}")
                bad.add("output_folder")
        data_root = self.data_root_var.get().strip()
        if data_root and not Path(data_root).is_dir():
            errors.append("Data folder must be an existing folder when provided.")
            bad.add("data_root")
        selected = self._selected_keys()
        if not selected:
            errors.append("Select at least one module.")
        for key in selected:
            mod = MODULE_BY_KEY[key]
            for field in mod.inputs_schema:
                fid = _field_id(key, field.key)
                if field.kind == "bool":
                    continue
                value = self.field_vars[(key, field.key)].get().strip()
                if field.kind == "file":
                    if not value:
                        errors.append(f"{mod.label}: choose the {field.label}.")
                        bad.add(fid)
                    elif not Path(value).is_file():
                        errors.append(f"{mod.label}: {field.label} was not found.")
                        bad.add(fid)
                    elif field.extensions and Path(value).suffix.lower() not in field.extensions:
                        errors.append(f"{mod.label}: {field.label} has an unsupported extension.")
                        bad.add(fid)
                elif field.kind == "file_optional" and value and not Path(value).is_file():
                    errors.append(f"{mod.label}: {field.label} was not found.")
                    bad.add(fid)
                elif field.kind == "folder_optional" and value and not Path(value).is_dir():
                    errors.append(f"{mod.label}: {field.label} was not found.")
                    bad.add(fid)
                elif field.kind in {"int", "int_detected"}:
                    required = field.kind == "int_detected" or (
                        key == "perfmon" and field.key == "physical_memory_gb"
                    )
                    if value == DETECTING:
                        errors.append(
                            f"{mod.label}: wait for {field.label} detection to finish, or type the value."
                        )
                        bad.add(fid)
                    elif not value and required and self._int_field_applies(key, field):
                        errors.append(f"{mod.label}: enter {field.label}.")
                        bad.add(fid)
                    elif value and (not value.isdigit() or int(value) <= 0):
                        errors.append(f"{mod.label}: {field.label} must be a positive whole number.")
                        bad.add(fid)
                elif field.kind == "datetime_optional" and value:
                    try:
                        self._set_var(
                            self.field_vars[(key, field.key)],
                            _parse_optional_datetime(value, field.label),
                        )
                    except ValueError:
                        errors.append(
                            f"{mod.label}: {field.label} must use MM-DD-YYYY HH:MM or MM-DD-YYYY."
                        )
                        bad.add(fid)
        if "perfmon" in selected:
            capture1 = self.field_vars[("perfmon", "blg_path")].get().strip()
            capture2 = self.field_vars[("perfmon", "capture2_blg_path")].get().strip()
            if capture1 and capture2 and Path(capture1).resolve() == Path(capture2).resolve():
                errors.append("Perfmon Infrastructure Analysis: Capture 2 must differ from Capture 1.")
                bad.add(_field_id("perfmon", "capture2_blg_path"))
        return errors, bad

    def _int_field_applies(self, key: str, field: InputField) -> bool:
        """Capture 2 hardware values are only required once a Capture 2 file is set."""
        if key == "perfmon" and field.key.startswith("capture2_"):
            return bool(self.field_vars[("perfmon", "capture2_blg_path")].get().strip())
        return True

    # ------------------------------------------------------------------
    # Config
    # ------------------------------------------------------------------

    def _build_config(self) -> dict:
        selected = self._selected_keys()
        inputs: dict[str, dict] = {}
        manual: dict[str, dict[str, str]] = {}
        for key in selected:
            mod = MODULE_BY_KEY[key]
            values: dict[str, object] = {}
            for field in mod.inputs_schema:
                if field.kind == "bool":
                    values[field.key] = bool(self.bool_vars[(key, field.key)].get())
                    continue
                value = self.field_vars[(key, field.key)].get().strip()
                if value == DETECTING:
                    value = ""
                values[field.key] = value
                if (key, field.key) in self._manual_fields and value:
                    manual.setdefault(key, {})[field.key] = value
            inputs[key] = values
        return {
            "run_name": self.run_name_var.get().strip(),
            "output_folder": _display_path(self.output_folder_var.get()) or DEFAULT_WORK_DIR,
            "data_root": _display_path(self.data_root_var.get()),
            "modules": selected,
            "inputs": inputs,
            # Inputs the user chose by hand. The engine never replaces these
            # with a discovered path, wherever they live.
            "manual_inputs": manual,
        }

    # ------------------------------------------------------------------
    # Pane 2: run
    # ------------------------------------------------------------------

    def _build_run_pane(self, parent) -> ctk.CTkFrame:
        pane = ctk.CTkFrame(parent, fg_color="transparent")
        pane.grid_columnconfigure(0, weight=1)
        pane.grid_rowconfigure(2, weight=1)

        head = self._card(pane, "Run progress")
        head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        self.progress_label = ctk.CTkLabel(
            head, text="Ready.", text_color=INK, font=(UI_FONT, 13), anchor="w"
        )
        self.progress_label.grid(row=1, column=0, sticky="w", padx=18, pady=(6, 4))
        self.progress = ctk.CTkProgressBar(head, height=10, progress_color=PLUM, fg_color=HAIRLINE)
        self.progress.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 14))
        self.progress.set(0)

        self.log = ctk.CTkTextbox(
            pane,
            fg_color=LOG_BG,
            text_color=LOG_TEXT,
            font=(MONO_FONT, 12),
            corner_radius=10,
            wrap="none",
        )
        self.log.grid(row=2, column=0, sticky="nsew", pady=(0, 12))
        self.log.configure(state="disabled")

        self.outputs_card = self._card(pane, "Outputs")
        self.outputs_card.grid(row=3, column=0, sticky="ew", pady=(0, 12))
        self.outputs_frame = ctk.CTkFrame(self.outputs_card, fg_color="transparent")
        self.outputs_frame.grid(row=1, column=0, sticky="ew", padx=18, pady=(6, 12))
        self.outputs_frame.grid_columnconfigure(0, weight=1)
        self.outputs_card.grid_remove()

        actions = ctk.CTkFrame(pane, fg_color="transparent")
        actions.grid(row=4, column=0, sticky="ew")
        actions.grid_columnconfigure(1, weight=1)
        self.back_button = self._button(actions, "Back to inputs", lambda: self._show_pane("inputs"), width=140)
        self.back_button.grid(row=0, column=0, sticky="w")
        self.cancel_button = self._button(actions, "Cancel", self._cancel_run, width=110)
        self.cancel_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.open_folder_button = self._button(actions, "Open run folder", self._open_run_folder, width=150)
        self.open_folder_button.grid(row=0, column=3, sticky="e", padx=(8, 0))
        self.open_log_button = self._button(actions, "Open run log", self._open_run_log, width=130)
        self.open_log_button.grid(row=0, column=4, sticky="e", padx=(8, 0))
        return pane

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _reset_run_pane(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.progress.set(0)
        self.progress_label.configure(text="Starting...")
        for child in self.outputs_frame.winfo_children():
            child.destroy()
        self.outputs_card.grid_remove()
        self._run_folder = None
        self._run_log_path = None
        self._module_total = 0

    def _start_run(self) -> None:
        if self._running:
            return
        errors, bad = self._validate()
        if errors:
            self._apply_field_highlights(bad)
            messagebox.showerror("Check inputs", "\n".join(f"- {err}" for err in errors))
            return
        config = self._build_config()
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._reset_run_pane()
        self._show_pane("run")
        self._running = True
        self._cancel_requested = False
        self.back_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.open_folder_button.configure(state="disabled")
        self.open_log_button.configure(state="disabled")
        threading.Thread(target=self._run_worker, args=(CONFIG_PATH,), daemon=True).start()
        self.after(100, self._drain_log)

    def _run_worker(self, config_path: Path) -> None:
        python_exe = sys.executable
        if sys.platform == "win32":
            pythonw = Path(sys.executable).parent / "pythonw.exe"
            if pythonw.exists():
                python_exe = str(pythonw)
        cmd = [python_exe, str(APP_DIR / "run_diagnostics.py"), "--config", str(config_path), "--yes"]
        code = 1
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                **hidden_subprocess_kwargs(),
            )
            self._process = process
            if process.stdout:
                for line in process.stdout:
                    self._log_queue.put(line)
            code = process.wait()
        except Exception as exc:
            self._log_queue.put(f"\nERROR: could not run the engine: {exc}\n")
        finally:
            self._process = None
            self._log_queue.put(f"__EXIT__{code}")

    def _drain_log(self) -> None:
        finished: int | None = None
        while True:
            try:
                item = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                continue
            if item.startswith("__EXIT__"):
                finished = int(item[len("__EXIT__") :] or 1)
                continue
            self._append_log(item)
            self._track_progress(item.rstrip("\r\n"))
        if finished is not None:
            self._finish_run(finished)
            return
        if self._running:
            self.after(100, self._drain_log)

    def _track_progress(self, line: str) -> None:
        match = _RUN_FOLDER_RE.match(line)
        if match:
            self._run_folder = Path(match.group(1))
            return
        match = _MODULE_RE.match(line)
        if match:
            index, total = int(match.group(1)), int(match.group(2))
            self._module_total = total
            self.progress.set((index - 1) / total if total else 0)
            return
        match = _STEP_RE.match(line)
        if match and self._module_total:
            self.progress_label.configure(text=f"Running: {match.group(1)}")
            return
        match = _RUN_LOG_RE.match(line)
        if match:
            self._run_log_path = Path(match.group(1))

    def _finish_run(self, code: int) -> None:
        self._running = False
        self.back_button.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.open_folder_button.configure(state="normal" if self._run_folder else "disabled")
        self.open_log_button.configure(state="normal" if self._run_log_path else "disabled")
        if self._cancel_requested:
            self.progress_label.configure(text="Run canceled.")
            return
        if code == 0:
            self.progress.set(1)
            self.progress_label.configure(text="Run complete.")
            self._list_outputs()
        else:
            self.progress_label.configure(text=f"Run finished with errors (exit code {code}). See the log.")

    def _list_outputs(self) -> None:
        if self._run_folder is None:
            return
        manifests = sorted(self._run_folder.glob("*_Run_Manifest.json"))
        files: list[str] = []
        if manifests:
            try:
                data = json.loads(manifests[-1].read_text(encoding="utf-8"))
                files = list(data.get("files") or [])
            except (OSError, ValueError):
                files = []
        shown = [
            rel
            for rel in files
            if Path(rel).suffix.lower() in OUTPUT_SUFFIXES and len(Path(rel).parts) <= 2
        ]
        if not shown:
            return
        for row, rel in enumerate(sorted(shown)):
            path = self._run_folder / rel
            ctk.CTkLabel(
                self.outputs_frame, text=rel, text_color=INK, font=(UI_FONT, 13), anchor="w"
            ).grid(row=row, column=0, sticky="w", pady=2)
            self._button(
                self.outputs_frame, "Open", lambda p=path: self._open(p), width=80
            ).grid(row=row, column=1, sticky="e", padx=(8, 0), pady=2)
        self.outputs_card.grid()

    def _open(self, path: Path) -> None:
        try:
            open_path(path)
        except OSError as exc:
            messagebox.showerror("Could not open", f"{path}\n\n{exc}")

    def _open_run_folder(self) -> None:
        if self._run_folder is not None:
            self._open(self._run_folder)

    def _open_run_log(self) -> None:
        if self._run_log_path is not None:
            self._open(self._run_log_path)

    def _cancel_run(self) -> None:
        process = self._process
        if process is None:
            return
        self._cancel_requested = True
        try:
            process.terminate()
        except OSError:
            pass
        self._append_log("\nCancel requested.\n")

    # ------------------------------------------------------------------
    # Reset and close
    # ------------------------------------------------------------------

    def _reset(self) -> None:
        if not messagebox.askyesno("Reset?", "Clear every input and start again?"):
            return
        self._manual_fields.clear()
        self._discovered = {}
        self._set_var(self.run_name_var, "")
        self._set_var(self.output_folder_var, _display_path(DEFAULT_WORK_DIR))
        self._set_var(self.data_root_var, "")
        self.scan_status_var.set("")
        for (key, field_key), var in self.field_vars.items():
            field = next(f for f in MODULE_BY_KEY[key].inputs_schema if f.key == field_key)
            default = "" if field.default in (None, 0) else str(field.default)
            self._set_var(var, default)
        for var in self.bool_vars.values():
            var.set(False)
        for mod in MODULES:
            self.module_vars[mod.key].set(self._module_available(mod))
            self._refresh_pill(mod.key)
        for fid in list(self._field_widgets):
            self._clear_field_highlight(fid)

    def _on_close(self) -> None:
        if self._running and not messagebox.askyesno(
            "Quit?", "A run is in progress. Cancel it and quit?"
        ):
            return
        self._cancel_run()
        self.destroy()


def main() -> int:
    app = DiagnosticsWorkbenchUI()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
