#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
diagnostics_workbench_ui.py -- the Master Class Diagnostics Workbench desktop app.

Three steps, laid out like the full Workbench:

  1. Folders.  Pick the data folder (scanned for module inputs) and the
     output folder, and name the run.
  2. Modules.  One row per analysis module: checkbox, description, status
     pill, and a Details expansion with what the module does, the inputs it
     found or needs, and the values to confirm.
  3. Run.      The run details, one status row per module, and the action
     strip that runs the engine and shows progress.

The app never analyses anything itself. It writes a JSON config and runs
App/run_diagnostics.py as a child process, streaming its output into the log.
"""

from __future__ import annotations

import calendar
import contextlib
import ctypes
import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from collections import deque
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from tkinter import TclError, filedialog, messagebox
from tkinter import font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw, ImageTk

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
for folder in (PROJECT_ROOT, APP_DIR):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from run_diagnostics import (  # noqa: E402
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
    validate_loop_workbook,
)

from Lib.Core import app_version  # noqa: E402
from Lib.Core.input_utils import (  # noqa: E402
    DEFAULT_WORK_DIR,
    clean_user_path,
    open_path,
)
from Lib.Core.performance_diagnostics import (  # noqa: E402
    PerformanceRecorder,
    process_resource_metrics,
)
from Lib.Core.subprocess_window import hidden_subprocess_kwargs  # noqa: E402
from Lib.Design.design_system import DESIGN_SYSTEM as DS  # noqa: E402

ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

IS_WINDOWS = sys.platform == "win32"

# ---------------------------------------------------------------------------
# Design tokens. The same values the full Workbench draws with, light mode.
# ---------------------------------------------------------------------------

CANVAS = DS.tech_grey.hex_value
PAPER = DS.white.hex_value
INK = DS.midnight.hex_value
MUTED = DS.text_muted.hex_value
MOSS = "#1a7f4e"
PLUM = DS.accent_blue.hex_value
CLAY = DS.critical.hex_value
OCHRE = "#946200"
FOG = "#DCE6F0"
RAIL = "#FFFFFF"
BRAND_NAVY = "#000032"
BRAND_EYEBROW = "#6FA3F0"
LINK_BLUE = "#0F5FDC"
FOOTER_RAIL = "#EEF1F8"
CARD_HEADER = "#EEF1F8"
PLUM_SOFT = "#E6EFFD"
PANEL = "#F4F7FB"
HAIRLINE = "#E3E9F1"
FIELD_BORDER = "#CFD9E5"
LOG_BG = DS.midnight.hex_value
LOG_TEXT = "#EAF1F8"
ROW_RULE = "#F0F3F8"
RUN_DETAIL_RULE = "#EDF1F7"
EXPANSION_TINT = "#F7FAFD"
UI_FONT = "Segoe UI"

NEEDS_REVIEW_PILL = "Needs Review"
S2_PILL_STYLES = {
    "Found": ("#1a7f4e", "#e7f4ec"),
    NEEDS_REVIEW_PILL: ("#946200", "#FDF6E7"),
    "Missing": ("#b3372c", "#fdecea"),
}
S2_PILL_NEUTRAL = ("#000032", "#F0F3F8")
STATUS_PILL_TEXT = {
    "Found": "Found",
    "Missing": "Needs A File",
    "Scanning": "Scanning",
    "Not scanned": "Not Scanned",
}
S3_STATUS_PILL_STYLES = {
    "not_started": ("#F0F3F8", "#E3E9F1", "#000032"),
    "running": ("#E6EFFD", "#c9dcf8", "#0a48a8"),
    "done": ("#e7f4ec", "#cfe6da", "#14663f"),
    "failed": ("#fdecea", "#f2c9c4", "#b3372c"),
}

OUTPUT_TERM_ORDER = ["Infographic", "Excel", "Mini Report"]
OUTPUT_TERM_COLORS = {
    "Infographic": "#6B2FA0",
    "Excel": "#16704A",
    "Mini Report": "#8A4A0F",
}
OUTPUT_TILE_FILLS = {
    "Infographic": "#F1E9F7",
    "Excel": "#E4F1EA",
    "Mini Report": "#F7EDE2",
}

# What each module does, for the row description and the Details expansion.
MODULE_DETAILS = {
    "loop": {
        "summary": (
            "Reviews client evaluation performance, notification coverage, and client "
            "CPU and hashing settings."
        ),
        "does": (
            "Creates an Infographic, Excel file, and Mini Report. Optional data adds "
            "expensive evaluations, UDP notification coverage, Command Polling Review, "
            "relay details, subnet details, FastHashVerify settings, and client multicore settings."
        ),
        "use": (
            "Use this with a Client Loop XML or CSV capture. The Client Performance "
            "Counters Basic export is also supported."
        ),
        "consultant": (
            "Confirm the collection period, slow client counts, UDP results, command "
            "polling settings, expensive evaluations, FastHashVerify settings, and client multicore settings."
        ),
    },
    "perfmon": {
        "summary": "Reviews Windows performance counters against BigFix requirements.",
        "does": (
            "Creates an Infographic, Excel file, and Mini Report from one or two "
            "PerfMon captures. Each counter is scored against its threshold."
        ),
        "use": "Use this when a BigFix platform server has a PerfMon BLG capture.",
        "consultant": (
            "Confirm the capture host and hardware values. Review every counter "
            "outside its limit."
        ),
    },
    "filldb": {
        "summary": "Reviews FillDB processing performance.",
        "does": (
            "Reads raw FillDB performance logs or an existing analyzer CSV. It "
            "creates an Infographic and Mini Report."
        ),
        "use": (
            "Use this when FillDB performance logging was enabled and the logs "
            "were collected."
        ),
        "consultant": "Confirm the collection period. Review any processing delays.",
    },
}
MISSING_INPUT_CLUES = {
    "loop": "Client Loop XML or CSV export",
    "perfmon": "PerfMon BLG from a platform server",
    "filldb": "FillDB performance log (FillDBperf.log) or CSV",
}
STEP_TITLES = {
    1: "Folders and Run Details",
    2: "Choose the Modules to Run",
    3: "Build the Outputs",
}
RAIL_LABELS = ["Folders", "Modules", "Build"]
# The engine prints "Step: <label>" when a module starts. The labels here are
# the ones App/run_diagnostics.py prints, so progress can follow the log.
STEP_HEADERS = {
    "loop": "Client Performance Analysis",
    "perfmon": "Perfmon Infrastructure Analysis",
    "filldb": "FillDB Performance Analysis",
}
BROWSABLE_INPUT_KINDS = {"file", "file_optional", "folder", "folder_optional"}
LOGO_ASSET_PATH = PROJECT_ROOT / "Assets" / "workbench_icon.png"
CONDENSED_FONT_FILE = PROJECT_ROOT / "Fonts" / "Roboto" / "RobotoCondensed-Bold.ttf"


def _app_data_dir() -> Path:
    """Per-user folder for files the app writes for itself.

    The build config goes here rather than next to the code, so an extracted
    copy of the Workbench stays exactly what it was shipped as.
    """
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "Master Class Diagnostics Workbench"
    return PROJECT_ROOT


CONFIG_PATH = _app_data_dir() / "last_build.config.json"
DETECTING = "Detecting..."
_LAYOUT_DEBOUNCE_MS = 40
_MAX_CAPTURED_LOG_CHARS = 2_000_000
_MAX_LOG_VIEWER_LINES = 8_000
_UI_QUEUE_MAX_CALLBACKS = 48
_UI_QUEUE_BUDGET_MS = 8.0
_LOG_DRAIN_MAX_ITEMS = 160
_LOG_DRAIN_BUDGET_MS = 10.0
_DIAGNOSTIC_HEARTBEAT_MS = 250
_DIAGNOSTIC_SLOW_TICK_MS = 250.0
_DIAGNOSTIC_RESOURCE_SAMPLE_MS = 5_000
_DIAGNOSTIC_EVENT_LIMIT = 160
_DIAGNOSTIC_RESOURCE_SAMPLE_LIMIT = 720
_DIAGNOSTIC_BASELINE_SAMPLE_COUNT = 6
_DIAGNOSTIC_TREND_POINT_LIMIT = 120
_DIAGNOSTIC_LOG_TAIL_CHARS = 100_000
DIAGNOSTIC_CARD_BG = "#F8FAFD"
DIAGNOSTIC_GAUGE_TRACK = "#DDE5EE"

_RUN_FOLDER_RE = re.compile(
    r"^(?:RUN_FOLDER:|\s*Run folder\s*:)\s*(.+?)\s*$", re.IGNORECASE
)
_RUN_LOG_RE = re.compile(r"^\s*Run log\s*:\s*(.+?)\s*$")


def _display_path(value: object) -> str:
    text = clean_user_path(value)
    return os.path.normpath(text) if text else ""


def _field_id(key: str, field_key: str) -> str:
    return f"{key}:{field_key}"


# ---------------------------------------------------------------------------
# Drawn icons and pills. Supersampled with PIL, scaled down for crisp strokes.
# ---------------------------------------------------------------------------

_ICON_CACHE: dict[tuple[str, int], ctk.CTkImage] = {}
_CANVAS_ICON_CACHE: dict[tuple[str, int], ImageTk.PhotoImage] = {}
_PILL_BG_CACHE: dict[tuple[str, str, int, int], ImageTk.PhotoImage] = {}


def _table_icon(kind: str, display: int) -> ctk.CTkImage:
    cached = _ICON_CACHE.get((kind, display))
    if cached is not None:
        return cached
    S = 4
    size = 24 * S
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    w = int(1.6 * S)

    def doc(x0, y0, x1, y1, color, lines):
        fold = 4 * S
        d.line(
            [(x1 - fold, y0), (x0, y0), (x0, y1), (x1, y1), (x1, y0 + fold)],
            fill=color,
            width=w,
            joint="curve",
        )
        d.line(
            [(x1 - fold, y0), (x1 - fold, y0 + fold), (x1, y0 + fold)],
            fill=color,
            width=max(S, w - S),
            joint="curve",
        )
        for line_y in lines:
            d.line([(x0 + 3 * S, line_y), (x1 - 3 * S, line_y)], fill=color, width=w)

    if kind in OUTPUT_TERM_COLORS:
        stroke = OUTPUT_TERM_COLORS[kind]
        d.rounded_rectangle(
            [0, 0, size - 1, size - 1], radius=7 * S, fill=OUTPUT_TILE_FILLS[kind]
        )
        if kind == "Mini Report":
            doc(int(7.5 * S), 8 * S, int(16.5 * S), 19 * S, stroke, [int(14.5 * S)])
        elif kind == "Infographic":
            d.line(
                [(6 * S, int(18.5 * S)), (18 * S, int(18.5 * S))], fill=stroke, width=w
            )
            for bar_x, top in ((8 * S, 13 * S), (12 * S, 9 * S), (16 * S, 11 * S)):
                d.line(
                    [(bar_x, top), (bar_x, int(17.5 * S))],
                    fill=stroke,
                    width=int(2.2 * S),
                )
        elif kind == "Excel":
            d.rounded_rectangle(
                [6 * S, 6 * S, 18 * S, 18 * S],
                radius=int(1.5 * S),
                outline=stroke,
                width=w,
            )
            for rule_x in (10 * S, 14 * S):
                d.line([(rule_x, 6 * S), (rule_x, 18 * S)], fill=stroke, width=w)
            for rule_y in (10 * S, 14 * S):
                d.line([(6 * S, rule_y), (18 * S, rule_y)], fill=stroke, width=w)
    elif kind == "check_tile":
        d.ellipse([0, 0, size - 1, size - 1], fill="#e7f4ec")
        d.line(
            [(int(6.5 * S), int(12.5 * S)), (11 * S, 17 * S), (18 * S, 7 * S)],
            fill="#1a7f4e",
            width=int(2.4 * S),
            joint="curve",
        )
    image = ctk.CTkImage(light_image=img, dark_image=img, size=(display, display))
    _ICON_CACHE[(kind, display)] = image
    return image


def _canvas_icon(kind: str, display: int) -> ImageTk.PhotoImage:
    key = (kind, display)
    cached = _CANVAS_ICON_CACHE.get(key)
    if cached is None:
        source = _table_icon(kind, display)._light_image
        cached = ImageTk.PhotoImage(source.resize((display, display), Image.LANCZOS))
        _CANVAS_ICON_CACHE[key] = cached
    return cached


def _pill_bg_photo(bg: str, border: str, width: int, height: int) -> ImageTk.PhotoImage:
    key = (bg, border, width, height)
    cached = _PILL_BG_CACHE.get(key)
    if cached is None:
        S = 4
        img = Image.new("RGBA", (width * S, height * S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle(
            [0, 0, width * S - 1, height * S - 1],
            radius=(height // 2) * S,
            fill=bg,
            outline=border,
            width=S,
        )
        cached = ImageTk.PhotoImage(img.resize((width, height), Image.LANCZOS))
        _PILL_BG_CACHE[key] = cached
    return cached


@lru_cache(maxsize=4)
def _caret_icon(expanded: bool, size: int = 12) -> ctk.CTkImage:
    scale = 4
    canvas = size * scale
    image = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if expanded:
        points = [
            (0.2 * canvas, 0.32 * canvas),
            (0.8 * canvas, 0.32 * canvas),
            (0.5 * canvas, 0.75 * canvas),
        ]
    else:
        points = [
            (0.32 * canvas, 0.2 * canvas),
            (0.32 * canvas, 0.8 * canvas),
            (0.75 * canvas, 0.5 * canvas),
        ]
    draw.polygon(points, fill="#000032")
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


@lru_cache(maxsize=2)
def _calendar_icon(size: int = 14) -> ctk.CTkImage:
    scale = 4
    c = size * scale
    image = Image.new("RGBA", (c, c), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    width = int(1.2 * scale)
    draw.rounded_rectangle(
        [0.08 * c, 0.18 * c, 0.92 * c, 0.92 * c],
        radius=int(0.08 * c),
        outline="#FFFFFF",
        width=width,
    )
    draw.line([0.08 * c, 0.4 * c, 0.92 * c, 0.4 * c], fill="#FFFFFF", width=width)
    draw.line([0.32 * c, 0.06 * c, 0.32 * c, 0.24 * c], fill="#FFFFFF", width=width)
    draw.line([0.68 * c, 0.06 * c, 0.68 * c, 0.24 * c], fill="#FFFFFF", width=width)
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def _make_logo(size: int = 38) -> ctk.CTkImage | None:
    if not LOGO_ASSET_PATH.exists():
        return None
    image = Image.open(LOGO_ASSET_PATH).convert("RGBA")
    image = image.resize((size, size), Image.Resampling.LANCZOS)
    return ctk.CTkImage(light_image=image, dark_image=image, size=(size, size))


def _truncate_for_width(text: str, font: tkfont.Font, max_width: int) -> str:
    if max_width <= 0 or font.measure(text) <= max_width:
        return text
    ellipsis = "..."
    while text and font.measure(text + ellipsis) > max_width:
        text = text[:-1]
    return text + ellipsis if text else ellipsis


class HoverTip:
    """Small tooltip used on the step rail."""

    _active_window: ctk.CTkToplevel | None = None
    _active_after_id: str | None = None
    _active_widget = None

    def __init__(
        self, widget, text: str, *, wraplength: int = 340, delay_ms: int = 350
    ) -> None:
        self.widget = widget
        self.text = text
        self.wraplength = wraplength
        self.delay_ms = delay_ms
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<Destroy>", self.hide, add="+")

    def show(self, _event=None) -> None:
        self.hide()
        if not self.text:
            return
        try:
            HoverTip._active_after_id = self.widget.after(self.delay_ms, self._show_now)
            HoverTip._active_widget = self.widget
        except TclError:
            HoverTip._active_after_id = None

    def _show_now(self) -> None:
        HoverTip._active_after_id = None
        try:
            if not self.widget.winfo_exists():
                return
        except TclError:
            return
        x = self.widget.winfo_rootx() + 24
        y = self.widget.winfo_rooty() + 24
        window = ctk.CTkToplevel(self.widget)
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        HoverTip._active_window = window
        frame = ctk.CTkFrame(window, fg_color=INK, corner_radius=10)
        frame.pack()
        ctk.CTkLabel(
            frame,
            text=self.text,
            text_color=PAPER,
            font=(UI_FONT, 12),
            wraplength=self.wraplength,
            justify="left",
        ).pack(padx=14, pady=10)

    def hide(self, _event=None) -> None:
        HoverTip.dismiss_active()

    @classmethod
    def dismiss_active(cls) -> None:
        if cls._active_after_id is not None and cls._active_widget is not None:
            try:
                cls._active_widget.after_cancel(cls._active_after_id)
            except TclError:
                pass
        cls._active_after_id = None
        cls._active_widget = None
        window = cls._active_window
        cls._active_window = None
        if window is not None:
            try:
                if window.winfo_exists():
                    window.destroy()
            except TclError:
                pass


class DatePopup(ctk.CTkToplevel):
    """Floating calendar. Calls on_pick(date) on a pick, on_clear() on Clear.

    The month grid is plain tkinter, so the runtime carries no calendar
    package. Weeks start on Monday and days outside the month are blank.
    """

    WEEKDAYS = ("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su")

    def __init__(
        self, master, anchor_widget, initial: date | None, on_pick, on_clear
    ) -> None:
        super().__init__(master)
        self._on_pick = on_pick
        self._on_clear = on_clear
        self._selected = initial or date.today()
        self._shown = self._selected.replace(day=1)
        self._cells: list[tk.Label] = []
        self._cell_dates: dict[tk.Label, date | None] = {}
        self._month_label: tk.Label | None = None
        self.title("Pick a date")
        self.configure(fg_color=CANVAS)
        self.resizable(False, False)
        self.transient(master.winfo_toplevel())
        self._build_widgets()
        self.update_idletasks()
        self._place_near(anchor_widget)
        self.after(50, self._lift_and_grab)
        self.bind("<Escape>", lambda _e: self._close())
        self.bind("<Left>", lambda _e: self._shift_month(-1))
        self.bind("<Right>", lambda _e: self._shift_month(1))
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build_widgets(self) -> None:
        outer = ctk.CTkFrame(self, fg_color=PAPER, corner_radius=14)
        outer.pack(padx=12, pady=12, fill="both", expand=True)
        header = tk.Frame(outer, bg=PLUM)
        header.pack(fill="x", padx=12, pady=(12, 0))
        nav_style = {
            "bg": PLUM,
            "fg": PAPER,
            "activebackground": PLUM_SOFT,
            "activeforeground": PLUM,
            "relief": "flat",
            "bd": 0,
            "font": (UI_FONT, 11, "bold"),
            "width": 3,
            "cursor": "hand2",
        }
        tk.Button(
            header, text="<", command=lambda: self._shift_month(-1), **nav_style
        ).pack(side="left", padx=(6, 0), pady=4)
        tk.Button(
            header, text=">", command=lambda: self._shift_month(1), **nav_style
        ).pack(side="right", padx=(0, 6), pady=4)
        self._month_label = tk.Label(
            header, bg=PLUM, fg=PAPER, font=(UI_FONT, 11, "bold")
        )
        self._month_label.pack(side="left", expand=True, fill="x", pady=4)

        grid = tk.Frame(
            outer, bg=PAPER, highlightthickness=1, highlightbackground=PLUM_SOFT
        )
        grid.pack(padx=12, pady=(0, 8))
        for col, name in enumerate(self.WEEKDAYS):
            tk.Label(
                grid, text=name, bg=PAPER, fg=MUTED, font=(UI_FONT, 10), width=4, pady=4
            ).grid(row=0, column=col)
        for index in range(42):
            cell = tk.Label(
                grid, text="", bg=PAPER, fg=INK, font=(UI_FONT, 11), width=4, pady=5
            )
            cell.grid(row=1 + index // 7, column=index % 7, padx=1, pady=1)
            cell.bind("<Button-1>", lambda _e, c=cell: self._pick_cell(c))
            cell.bind("<Enter>", lambda _e, c=cell: self._style_cell(c, hovered=True))
            cell.bind("<Leave>", lambda _e, c=cell: self._style_cell(c))
            self._cells.append(cell)
        self._paint_month()

        footer = ctk.CTkFrame(outer, fg_color="transparent")
        footer.pack(fill="x", padx=12, pady=(4, 12))
        footer.grid_columnconfigure(1, weight=1)
        ctk.CTkButton(
            footer,
            text="Today",
            width=82,
            height=30,
            corner_radius=15,
            fg_color=MOSS,
            text_color=PAPER,
            hover_color=PLUM,
            command=lambda: self._do_pick(date.today()),
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(
            footer,
            text="Clear",
            width=82,
            height=30,
            corner_radius=15,
            fg_color=PLUM_SOFT,
            text_color=PLUM,
            hover_color=PLUM,
            command=self._do_clear,
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _shift_month(self, step: int) -> None:
        index = self._shown.month - 1 + step
        self._shown = date(self._shown.year + index // 12, index % 12 + 1, 1)
        self._paint_month()

    def _paint_month(self) -> None:
        if self._month_label is not None:
            self._month_label.configure(text=self._shown.strftime("%B %Y"))
        weeks = calendar.Calendar(firstweekday=calendar.MONDAY).monthdayscalendar(
            self._shown.year, self._shown.month
        )
        days = [day for week in weeks for day in week]
        days += [0] * (len(self._cells) - len(days))
        for cell, day in zip(self._cells, days):
            self._cell_dates[cell] = self._shown.replace(day=day) if day else None
            cell.configure(
                text=str(day) if day else "", cursor="hand2" if day else "arrow"
            )
            self._style_cell(cell)

    def _style_cell(self, cell: tk.Label, hovered: bool = False) -> None:
        cell_date = self._cell_dates.get(cell)
        if cell_date is None:
            cell.configure(bg=PAPER, fg=INK, font=(UI_FONT, 11))
        elif cell_date == self._selected:
            cell.configure(bg=PLUM, fg=PAPER, font=(UI_FONT, 11, "bold"))
        elif hovered:
            cell.configure(bg=PLUM_SOFT, fg=PLUM, font=(UI_FONT, 11))
        elif cell_date == date.today():
            cell.configure(bg=PAPER, fg=MOSS, font=(UI_FONT, 11, "bold"))
        else:
            cell.configure(bg=PAPER, fg=INK, font=(UI_FONT, 11))

    def _pick_cell(self, cell: tk.Label) -> None:
        picked = self._cell_dates.get(cell)
        if picked is not None:
            self._do_pick(picked)

    def _do_pick(self, picked: date) -> None:
        try:
            self._on_pick(picked)
        finally:
            self._close()

    def _do_clear(self) -> None:
        try:
            self._on_clear()
        finally:
            self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except TclError:
            pass
        self.destroy()

    def _place_near(self, anchor_widget) -> None:
        try:
            ax = anchor_widget.winfo_rootx()
            ay = anchor_widget.winfo_rooty()
            ah = anchor_widget.winfo_height()
        except TclError:
            return
        self.update_idletasks()
        win_w, win_h = self.winfo_reqwidth(), self.winfo_reqheight()
        screen_w, screen_h = self.winfo_screenwidth(), self.winfo_screenheight()
        x, y = ax, ay + ah + 4
        if x + win_w > screen_w - 8:
            x = max(8, screen_w - win_w - 8)
        if y + win_h > screen_h - 8:
            y = max(8, ay - win_h - 4)
        self.geometry(f"+{x}+{y}")

    def _lift_and_grab(self) -> None:
        try:
            self.lift()
            self.focus_force()
            self.grab_set()
        except TclError:
            pass


# ---------------------------------------------------------------------------
# The app
# ---------------------------------------------------------------------------


class DiagnosticsWorkbenchUI(ctk.CTk):
    _S2_ACCENT_MIN = 3
    _S2_CHECK_MIN = 26
    _S2_NAME_MIN = 330
    _S2_STATUS_MIN = 140
    _S2_LINK_MIN = 58
    _S2_GAP = 14
    _S2_ROW_HEIGHT = 52
    _S2_MISSING_EXTRA = 36
    _S3_MODULE_MIN = 350
    _S3_OUTPUTS_MIN = 116
    _S3_STATUS_MIN = 118
    _S3_GAP = 14
    _S3_ROW_HEIGHT = 54
    _DATE_PARSE_FORMATS = (
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%Y %H:%M",
        "%m-%d-%Y",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%Y %H:%M",
        "%m/%d/%Y",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    )

    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        default_height = min(1080, max(900, self.winfo_screenheight() - 40))
        self.geometry(f"1400x{default_height}")
        self.minsize(1180, 780)
        self.configure(fg_color=CANVAS)

        self.step = 1
        self.data_root_var = ctk.StringVar(value="")
        self.output_folder_var = ctk.StringVar(value=_display_path(DEFAULT_WORK_DIR))
        self.run_name_var = ctk.StringVar(value="")
        self.scan_confirmation_var = ctk.StringVar(value="")
        self.scan_missing_var = ctk.StringVar(value="")

        self.module_vars = {mod.key: ctk.BooleanVar(value=False) for mod in MODULES}
        # A browsed or typed path per browsable field. Present means manual.
        self.module_input_override_vars = {
            (mod.key, field.key): ctk.StringVar()
            for mod in MODULES
            for field in mod.inputs_schema
            if field.kind in BROWSABLE_INPUT_KINDS
        }
        self.date_field_vars = {
            (mod.key, field.key): ctk.StringVar()
            for mod in MODULES
            for field in mod.inputs_schema
            if field.kind == "datetime_optional"
        }
        self.perfmon_processors_var = ctk.StringVar(value="")
        self.perfmon_disks_var = ctk.StringVar(value="")
        self.perfmon_memory_var = ctk.StringVar(value="")
        self.perfmon_vm_var = ctk.BooleanVar(value=False)
        self.perfmon2_processors_var = ctk.StringVar(value="")
        self.perfmon2_disks_var = ctk.StringVar(value="")
        self.perfmon2_memory_var = ctk.StringVar(value="")
        self.perfmon2_vm_var = ctk.BooleanVar(value=False)

        self._discovered: dict[str, Path | None] = {}
        self._optional_input_cache: dict[tuple[str, str], Path | None] = {}
        self._scan_thread: threading.Thread | None = None
        self._scan_token = 0
        self._last_scan_root = ""
        self._expanded_module_key: str | None = None
        self._module_card_controls: dict[str, dict[str, object]] = {}
        self._group_count_label: ctk.CTkLabel | None = None
        self._perfmon_detect_tokens = {"perfmon": 0, "perfmon2": 0}
        self._perfmon_detect_sources: dict[str, Path] = {}
        self._field_widgets: dict[str, ctk.CTkEntry] = {}
        self._field_rest_borders: dict[str, str] = {}
        self._ui_queue: queue.Queue = queue.Queue()
        self._diagnostics = PerformanceRecorder("desktop_ui")
        self._app_started_at = time.monotonic()
        self._heartbeat_expected_at = time.perf_counter()
        self._heartbeat_samples: deque[float] = deque(maxlen=240)
        self._last_heartbeat_lag_ms = 0.0
        self._max_heartbeat_lag_ms = 0.0
        self._slow_heartbeat_count = 0
        self._resource_after_id: str | None = None
        self._resource_last_cpu_sample = (time.perf_counter(), time.process_time())
        self._resource_samples: deque[dict[str, object]] = deque(
            maxlen=_DIAGNOSTIC_RESOURCE_SAMPLE_LIMIT
        )
        self._resource_latest: dict[str, object] = {}
        self._resource_baseline: dict[str, object] | None = None
        self._last_resource_warning_at = 0.0
        self._perf_events: deque[dict[str, object]] = deque(
            maxlen=_DIAGNOSTIC_EVENT_LIMIT
        )
        self._perf_counters: dict[str, int] = {}
        self._perf_last_ms: dict[str, float] = {}
        self._perf_max_ms: dict[str, float] = {}
        self._widget_count_cache: tuple[int, float] | None = None
        self._diagnostics_window: ctk.CTkToplevel | None = None
        self._diagnostics_textbox: ctk.CTkTextbox | None = None
        self._diagnostics_refresh_after_id: str | None = None
        self._diagnostics_visual_widgets: dict[str, dict[str, object]] = {}
        self._diagnostics_trend_widgets: dict[str, dict[str, object]] = {}
        self._diagnostics_summary_labels: dict[str, ctk.CTkLabel] = {}

        self._process: subprocess.Popen | None = None
        self._log_queue: queue.Queue[str] = queue.Queue()
        self._log_chunks: deque[str] = deque()
        self._log_chunk_chars = 0
        self._log_truncated = False
        self._log_viewers: list[ctk.CTkTextbox] = []
        self._open_output_buttons: list[ctk.CTkButton] = []
        self._build_running = False
        self._cancel_requested = False
        self._run_folder: Path | None = None
        self._run_log_path: Path | None = None
        self._progress_order: list[str] = []
        self._progress_completed: set[str] = set()
        self._progress_current: str | None = None
        self._module_run_started: dict[str, float] = {}
        self._canvas_status_pills: dict[str, dict] = {}
        self._build_started_at: float | None = None
        self._elapsed_timer_id: str | None = None
        self._nav_row_states: dict[int, str] = {}

        for (key, _field_key), var in self.module_input_override_vars.items():
            var.trace_add("write", lambda *_a, k=key: self._on_manual_input_changed(k))
        self.output_folder_var.trace_add(
            "write", lambda *_a: self._clear_field_highlight("output_folder")
        )
        self.data_root_var.trace_add("write", lambda *_a: self._on_data_root_changed())
        self.run_name_var.trace_add("write", lambda *_a: self._update_rail_context())
        for var, fid in (
            (self.perfmon_processors_var, "perfmon:logical_processors"),
            (self.perfmon_disks_var, "perfmon:physical_disks"),
            (self.perfmon_memory_var, "perfmon:physical_memory_gb"),
            (self.perfmon2_processors_var, "perfmon:capture2_logical_processors"),
            (self.perfmon2_disks_var, "perfmon:capture2_physical_disks"),
            (self.perfmon2_memory_var, "perfmon:capture2_physical_memory_gb"),
        ):
            var.trace_add("write", lambda *_a, f=fid: self._on_perfmon_value_changed(f))
        for (key, field_key), var in self.date_field_vars.items():
            var.trace_add(
                "write",
                lambda *_a, k=key, f=_field_id(key, field_key): (
                    self._on_date_value_changed(k, f)
                ),
            )

        self._build_shell()
        self._install_diagnostics_shortcuts()
        self._show_step(1)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_ui_queue)
        self._start_performance_diagnostics()

    # ------------------------------------------------------------------
    # Threads hand work back through a queue the main thread drains.
    # ------------------------------------------------------------------

    def _post(self, callback) -> None:
        self._ui_queue.put(callback)

    def _record_diagnostic(self, name: str, **kwargs) -> None:
        """Record evidence when the full desktop UI is present.

        Focused tests exercise these methods with lightweight headless doubles;
        diagnostics must never become a required part of their behavior.
        """
        recorder = self.__dict__.get("_diagnostics")
        if recorder is not None:
            recorder.record(name, **kwargs)
        self._record_perf_event(
            name,
            elapsed_ms=kwargs.get("elapsed_ms"),
            detail=str(kwargs.get("detail", "")),
        )

    def _drain_ui_queue(self) -> None:
        started = time.perf_counter()
        processed = 0
        while processed < _UI_QUEUE_MAX_CALLBACKS:
            if (time.perf_counter() - started) * 1000 >= _UI_QUEUE_BUDGET_MS:
                break
            try:
                callback = self._ui_queue.get_nowait()
            except queue.Empty:
                break
            try:
                callback()
            except TclError:
                pass
            processed += 1
        elapsed_ms = (time.perf_counter() - started) * 1000
        if processed or elapsed_ms >= _UI_QUEUE_BUDGET_MS:
            self._record_diagnostic(
                "UI callback drain",
                elapsed_ms=elapsed_ms,
                callbacks=processed,
                queue_depth=self._ui_queue.qsize(),
            )
        try:
            delay = 5 if not self._ui_queue.empty() else 100
            self.after(delay, self._drain_ui_queue)
        except TclError:
            pass

    def _start_performance_diagnostics(self) -> None:
        now = time.perf_counter()
        self._heartbeat_expected_at = now + (_DIAGNOSTIC_HEARTBEAT_MS / 1000)
        self.after(_DIAGNOSTIC_HEARTBEAT_MS, self._diagnostic_heartbeat)
        self._resource_after_id = self.after(1_000, self._sample_process_resources)

    def _diagnostic_heartbeat(self) -> None:
        now = time.perf_counter()
        lag_ms = max(0.0, (now - self._heartbeat_expected_at) * 1000)
        self._heartbeat_samples.append(lag_ms)
        self._last_heartbeat_lag_ms = lag_ms
        self._max_heartbeat_lag_ms = max(self._max_heartbeat_lag_ms, lag_ms)
        if lag_ms >= _DIAGNOSTIC_SLOW_TICK_MS:
            self._slow_heartbeat_count += 1
            self._record_diagnostic("UI heartbeat lag", elapsed_ms=lag_ms)
        self._heartbeat_expected_at = now + (_DIAGNOSTIC_HEARTBEAT_MS / 1000)
        try:
            self.after(_DIAGNOSTIC_HEARTBEAT_MS, self._diagnostic_heartbeat)
        except TclError:
            pass

    def _sample_process_resources(self) -> None:
        now_wall = time.perf_counter()
        now_cpu = time.process_time()
        previous_wall, previous_cpu = self._resource_last_cpu_sample
        elapsed_wall = max(now_wall - previous_wall, 0.001)
        cpu_pct = max(0.0, ((now_cpu - previous_cpu) / elapsed_wall) * 100)
        self._resource_last_cpu_sample = (now_wall, now_cpu)
        sample: dict[str, object] = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "uptime_s": int(time.monotonic() - self._app_started_at),
            "cpu_pct": cpu_pct,
            "python_threads": threading.active_count(),
            "widget_count": self._count_widgets_cached(),
            "ui_queue_depth": self._ui_queue.qsize(),
        }
        sample.update(process_resource_metrics())
        self._resource_samples.append(sample)
        self._resource_latest = sample
        self._set_resource_baseline_if_ready()
        resource_health, resource_notes = self._resource_health(
            sample, self._resource_baseline
        )
        now_monotonic = time.monotonic()
        if (
            resource_health != "Healthy"
            and now_monotonic - self._last_resource_warning_at >= 60
        ):
            self._last_resource_warning_at = now_monotonic
            self._record_diagnostic(
                "Resource pressure",
                detail=resource_notes[0] if resource_notes else resource_health,
            )
        self._record_diagnostic(
            "UI process resources",
            captured_log_chars=self.__dict__.get("_log_chunk_chars", 0),
            **sample,
        )
        try:
            self._resource_after_id = self.after(
                _DIAGNOSTIC_RESOURCE_SAMPLE_MS,
                self._sample_process_resources,
            )
        except TclError:
            self._resource_after_id = None

    # ------------------------------------------------------------------
    # Hidden application diagnostics
    # ------------------------------------------------------------------

    def _install_diagnostics_shortcuts(self) -> None:
        for sequence in ("<Control-Shift-D>", "<Control-Shift-d>"):
            self.bind_all(
                sequence,
                lambda _event: self._toggle_diagnostics_window(),
                add="+",
            )

    def _record_perf_event(
        self,
        name: str,
        *,
        elapsed_ms: object = None,
        detail: str = "",
    ) -> None:
        """Maintain the compact, human-readable event view in the popup."""
        state = self.__dict__
        counters = state.setdefault("_perf_counters", {})
        counters[name] = counters.get(name, 0) + 1
        if isinstance(elapsed_ms, int | float):
            last = state.setdefault("_perf_last_ms", {})
            maximum = state.setdefault("_perf_max_ms", {})
            last[name] = float(elapsed_ms)
            maximum[name] = max(maximum.get(name, 0.0), float(elapsed_ms))
        events = state.setdefault("_perf_events", deque(maxlen=_DIAGNOSTIC_EVENT_LIMIT))
        events.append(
            {
                "time": datetime.now().strftime("%H:%M:%S"),
                "step": state.get("step", 0),
                "name": name,
                "elapsed_ms": elapsed_ms if isinstance(elapsed_ms, int | float) else None,
                "detail": detail,
            }
        )

    def _count_widgets(self, widget) -> int:
        try:
            children = widget.winfo_children()
        except TclError:
            return 0
        return 1 + sum(self._count_widgets(child) for child in children)

    def _count_widgets_cached(self) -> int:
        now = time.perf_counter()
        cached = self.__dict__.get("_widget_count_cache")
        if cached is not None and now - cached[1] < 5.0:
            return cached[0]
        count = self._count_widgets(self)
        self.__dict__["_widget_count_cache"] = (count, now)
        return count

    @staticmethod
    def _resource_average(samples: list[dict[str, object]], key: str) -> float | None:
        values = [
            float(sample[key])
            for sample in samples
            if isinstance(sample.get(key), int | float)
        ]
        return (sum(values) / len(values)) if values else None

    def _set_resource_baseline_if_ready(self) -> None:
        if self._resource_baseline is not None:
            return
        samples = list(self._resource_samples)
        if len(samples) < _DIAGNOSTIC_BASELINE_SAMPLE_COUNT:
            return
        baseline: dict[str, object] = {
            "samples": _DIAGNOSTIC_BASELINE_SAMPLE_COUNT,
            "uptime_s": int(time.monotonic() - self._app_started_at),
        }
        for key in (
            "cpu_pct",
            "rss_mb",
            "private_mb",
            "python_threads",
            "widget_count",
            "ui_queue_depth",
            "gdi_objects",
            "user_objects",
        ):
            value = self._resource_average(
                samples[:_DIAGNOSTIC_BASELINE_SAMPLE_COUNT], key
            )
            if value is not None:
                baseline[key] = value
        self._resource_baseline = baseline
        self._record_perf_event(
            "Resource baseline established",
            detail=f"{_DIAGNOSTIC_BASELINE_SAMPLE_COUNT} samples",
        )

    @staticmethod
    def _diagnostic_worst_health(*healths: str) -> str:
        order = {"Healthy": 0, "Watch": 1, "Lagging": 2, "Blocked": 3}
        return max(healths, key=lambda health: order.get(health, 0))

    @staticmethod
    def _diagnostic_percentile(samples: list[float], percentile: float) -> float:
        if not samples:
            return 0.0
        ordered = sorted(samples)
        index = int(round((len(ordered) - 1) * percentile))
        return ordered[max(0, min(index, len(ordered) - 1))]

    @staticmethod
    def _diagnostic_health(last_ms: float, p95_ms: float, max_ms: float) -> str:
        if last_ms >= 1000 or p95_ms >= 500 or max_ms >= 2000:
            return "Blocked"
        if last_ms >= 250 or p95_ms >= 150 or max_ms >= 750:
            return "Lagging"
        if last_ms >= 80 or p95_ms >= 80 or max_ms >= 250:
            return "Watch"
        return "Healthy"

    @staticmethod
    def _diagnostic_health_color(health: str) -> str:
        return {
            "Healthy": MOSS,
            "Watch": OCHRE,
            "Lagging": CLAY,
            "Blocked": CLAY,
        }.get(health, OCHRE)

    @staticmethod
    def _fmt_metric(value: object, suffix: str = "") -> str:
        if isinstance(value, float):
            return f"{value:.1f}{suffix}"
        if isinstance(value, int):
            return f"{value}{suffix}"
        return "Not available"

    def _resource_health(
        self,
        latest: dict[str, object] | None,
        baseline: dict[str, object] | None,
    ) -> tuple[str, list[str]]:
        if not latest:
            return "Healthy", ["Resource monitor is collecting its first sample."]
        health = "Healthy"
        notes: list[str] = []

        def mark(level: str, note: str) -> None:
            nonlocal health
            health = self._diagnostic_worst_health(health, level)
            notes.append(note)

        cpu_pct = latest.get("cpu_pct")
        if isinstance(cpu_pct, int | float):
            if cpu_pct >= 90:
                mark("Lagging", f"CPU is very high at {cpu_pct:.0f}% of one core.")
            elif cpu_pct >= 50:
                mark("Watch", f"CPU is elevated at {cpu_pct:.0f}% of one core.")

        queue_depth = latest.get("ui_queue_depth")
        if isinstance(queue_depth, int | float):
            if queue_depth >= 500:
                mark("Lagging", f"{int(queue_depth)} UI callbacks are waiting.")
            elif queue_depth >= 100:
                mark("Watch", f"{int(queue_depth)} UI callbacks are waiting.")

        widgets = latest.get("widget_count")
        if isinstance(widgets, int | float):
            if widgets >= 6000:
                mark("Lagging", f"Widget count is very high at {int(widgets)}.")
            elif widgets >= 3000:
                mark("Watch", f"Widget count is high at {int(widgets)}.")

        for key, label in (
            ("gdi_objects", "GDI objects"),
            ("user_objects", "USER objects"),
        ):
            count = latest.get(key)
            if isinstance(count, int | float):
                if count >= 8000:
                    mark(
                        "Lagging", f"{label} are near the Windows limit at {int(count)}."
                    )
                elif count >= 5000:
                    mark("Watch", f"{label} are elevated at {int(count)}.")

        rss_mb = latest.get("rss_mb")
        baseline_rss = baseline.get("rss_mb") if baseline else None
        if isinstance(rss_mb, int | float) and isinstance(baseline_rss, int | float):
            delta = float(rss_mb) - float(baseline_rss)
            ratio = delta / max(float(baseline_rss), 1.0)
            if delta >= 500 or ratio >= 0.75:
                mark("Lagging", f"Memory is {delta:.0f} MB above baseline.")
            elif delta >= 200 or ratio >= 0.35:
                mark("Watch", f"Memory is {delta:.0f} MB above baseline.")
        if not notes:
            notes.append("Resources are inside the current thresholds.")
        return health, notes

    def _background_activity(self) -> list[str]:
        active = []
        if self._scan_thread is not None and self._scan_thread.is_alive():
            active.append("Input scan")
        if self._build_running:
            active.append("Report build")
        if self._process is not None:
            active.append("Build engine process")
        return active

    def _diagnostics_snapshot(self) -> dict[str, object]:
        samples = list(self._heartbeat_samples)
        p95_lag = self._diagnostic_percentile(samples, 0.95)
        resource_latest = dict(self._resource_latest)
        resource_health, resource_notes = self._resource_health(
            resource_latest, self._resource_baseline
        )
        loop_health = self._diagnostic_health(
            self._last_heartbeat_lag_ms, p95_lag, self._max_heartbeat_lag_ms
        )
        return {
            "health": self._diagnostic_worst_health(loop_health, resource_health),
            "loop_health": loop_health,
            "resource_health": resource_health,
            "resource_notes": resource_notes,
            "uptime_s": int(time.monotonic() - self._app_started_at),
            "step": self.step,
            "last_lag_ms": self._last_heartbeat_lag_ms,
            "avg_lag_ms": sum(samples) / len(samples) if samples else 0.0,
            "p95_lag_ms": p95_lag,
            "max_lag_ms": self._max_heartbeat_lag_ms,
            "slow_tick_count": self._slow_heartbeat_count,
            "widget_count": self._count_widgets_cached(),
            "background_activity": self._background_activity(),
            "captured_log_chars": self._log_chunk_chars,
            "captured_log_truncated": self._log_truncated,
            "open_log_viewers": len(self._log_viewers),
            "perf_counters": dict(self._perf_counters),
            "perf_last_ms": dict(self._perf_last_ms),
            "perf_max_ms": dict(self._perf_max_ms),
            "recent_events": list(self._perf_events)[-24:],
            "resource_latest": resource_latest,
            "resource_baseline": self._resource_baseline,
            "resource_sample_count": len(self._resource_samples),
        }

    def _format_diagnostics_report(self) -> str:
        snapshot = self._diagnostics_snapshot()
        resources = snapshot["resource_latest"]
        baseline = snapshot["resource_baseline"]
        active = snapshot["background_activity"] or ["None"]
        baseline_status = (
            f"ready at {baseline.get('uptime_s')} seconds"
            if isinstance(baseline, dict)
            else (
                f"collecting {snapshot['resource_sample_count']}/"
                f"{_DIAGNOSTIC_BASELINE_SAMPLE_COUNT} samples"
            )
        )
        lines = [
            "Master Class Diagnostics Workbench diagnostics.",
            "",
            f"Health: {snapshot['health']}.",
            f"UI responsiveness: {snapshot['loop_health']}.",
            f"Resource pressure: {snapshot['resource_health']}.",
            f"Current step: {snapshot['step']}.",
            f"Uptime: {snapshot['uptime_s']} seconds.",
            "",
            "Performance summary.",
            *[f"- {note}" for note in snapshot["resource_notes"]],
            "",
            "UI event loop.",
            f"Last lag: {snapshot['last_lag_ms']:.1f} ms.",
            f"Average lag: {snapshot['avg_lag_ms']:.1f} ms.",
            f"P95 lag: {snapshot['p95_lag_ms']:.1f} ms.",
            f"Maximum lag: {snapshot['max_lag_ms']:.1f} ms.",
            f"Slow ticks: {snapshot['slow_tick_count']}.",
            "",
            "Process resources.",
            f"Resource baseline: {baseline_status}.",
            f"CPU: {self._fmt_metric(resources.get('cpu_pct'), '% of one core')}.",
            f"Memory working set: {self._fmt_metric(resources.get('rss_mb'), ' MB')}.",
            f"Memory private bytes: {self._fmt_metric(resources.get('private_mb'), ' MB')}.",
            f"Python threads: {self._fmt_metric(resources.get('python_threads'))}.",
            f"GDI objects: {self._fmt_metric(resources.get('gdi_objects'))}.",
            f"USER objects: {self._fmt_metric(resources.get('user_objects'))}.",
            "",
            "Live state.",
            f"Widget count: {snapshot['widget_count']}.",
            f"Background activity: {', '.join(active)}.",
            f"UI callback queue: {self._fmt_metric(resources.get('ui_queue_depth'))}.",
            f"Captured UI log chars: {snapshot['captured_log_chars']}.",
            f"Captured UI log truncated: {snapshot['captured_log_truncated']}.",
            f"Open log viewers: {snapshot['open_log_viewers']}.",
            "",
            "Render and action counters.",
        ]
        counters = snapshot["perf_counters"]
        if counters:
            for name in sorted(counters):
                last = snapshot["perf_last_ms"].get(name)
                maximum = snapshot["perf_max_ms"].get(name)
                timing = (
                    f" Last {last:.1f} ms. Maximum {maximum:.1f} ms."
                    if last is not None and maximum is not None
                    else ""
                )
                lines.append(f"{name}: {counters[name]}.{timing}")
        else:
            lines.append("No recorded UI actions yet.")
        lines.extend(["", "Recent events."])
        events = snapshot["recent_events"]
        if events:
            for event in events:
                elapsed = event.get("elapsed_ms")
                timing = f" {elapsed:.1f} ms." if elapsed is not None else ""
                detail = f" {event.get('detail')}." if event.get("detail") else ""
                lines.append(
                    f"{event.get('time')} step {event.get('step')}: "
                    f"{event.get('name')}.{timing}{detail}"
                )
        else:
            lines.append("No recent events.")
        return "\n".join(lines)

    @staticmethod
    def _diagnostic_metric_ratio(value: object, limit: float) -> float:
        if not isinstance(value, int | float) or limit <= 0:
            return 0.0
        return max(0.0, min(1.0, float(value) / limit))

    @staticmethod
    def _diagnostic_metric_health(value: object, watch_at: float, lag_at: float) -> str:
        if not isinstance(value, int | float):
            return "Healthy"
        if float(value) >= lag_at:
            return "Lagging"
        if float(value) >= watch_at:
            return "Watch"
        return "Healthy"

    def _diagnostic_visual_specs(
        self, snapshot: dict[str, object]
    ) -> list[dict[str, object]]:
        resources = snapshot["resource_latest"]
        baseline = snapshot["resource_baseline"]

        def number(value: object) -> float | None:
            return float(value) if isinstance(value, int | float) else None

        def spec(
            key: str,
            title: str,
            value: object,
            value_text: str,
            detail: str,
            *,
            watch_at: float,
            lag_at: float,
        ) -> dict[str, object]:
            health = self._diagnostic_metric_health(value, watch_at, lag_at)
            return {
                "key": key,
                "title": title,
                "value": value_text,
                "detail": detail,
                "ratio": self._diagnostic_metric_ratio(value, lag_at),
                "health": health,
                "color": self._diagnostic_health_color(health),
            }

        p95_lag = number(snapshot.get("p95_lag_ms"))
        cpu_pct = number(resources.get("cpu_pct"))
        widget_count = number(snapshot.get("widget_count"))
        queue_depth = number(resources.get("ui_queue_depth"))
        gdi_objects = number(resources.get("gdi_objects"))
        user_objects = number(resources.get("user_objects"))
        handle_pressure = max(gdi_objects or 0.0, user_objects or 0.0)

        memory_value = 0.0
        memory_text = "Baseline pending"
        memory_detail = "Waiting for enough resource samples."
        memory_watch_at, memory_lag_at = 200.0, 500.0
        rss_mb = number(resources.get("rss_mb"))
        baseline_rss = (
            number(baseline.get("rss_mb")) if isinstance(baseline, dict) else None
        )
        if rss_mb is not None and baseline_rss is not None:
            memory_value = max(0.0, rss_mb - baseline_rss)
            memory_watch_at = min(200.0, baseline_rss * 0.35)
            memory_lag_at = min(500.0, baseline_rss * 0.75)
            memory_text = f"{memory_value:.0f} MB over"
            memory_detail = (
                f"{rss_mb:.0f} MB working set, {baseline_rss:.0f} MB baseline."
            )
        elif rss_mb is not None:
            memory_text = f"{rss_mb:.0f} MB"
            memory_detail = "Working set measured; baseline still collecting."

        return [
            spec(
                "ui_p95",
                "UI Lag P95",
                p95_lag,
                f"{p95_lag:.1f} ms" if p95_lag is not None else "Not available",
                "95% of recent UI heartbeat samples were at or below this.",
                watch_at=80.0,
                lag_at=150.0,
            ),
            spec(
                "cpu",
                "CPU",
                cpu_pct,
                f"{cpu_pct:.1f}%" if cpu_pct is not None else "Not available",
                "Measured as percent of one CPU core.",
                watch_at=50.0,
                lag_at=90.0,
            ),
            spec(
                "memory",
                "Memory Drift",
                memory_value,
                memory_text,
                memory_detail,
                watch_at=memory_watch_at,
                lag_at=memory_lag_at,
            ),
            spec(
                "widgets",
                "Widget Count",
                widget_count,
                f"{int(widget_count)}" if widget_count is not None else "Not available",
                "Large widget trees make screen changes more expensive.",
                watch_at=3000.0,
                lag_at=6000.0,
            ),
            spec(
                "queue",
                "UI Queue",
                queue_depth,
                f"{int(queue_depth)}" if queue_depth is not None else "Not available",
                "Callbacks waiting for the UI thread.",
                watch_at=100.0,
                lag_at=500.0,
            ),
            spec(
                "handles",
                "Windows UI Handles",
                handle_pressure,
                (
                    f"GDI {int(gdi_objects or 0)}, USER {int(user_objects or 0)}"
                    if gdi_objects is not None or user_objects is not None
                    else "Not available"
                ),
                "Windows object counters for the Workbench process.",
                watch_at=5000.0,
                lag_at=8000.0,
            ),
        ]

    @staticmethod
    def _diagnostic_numeric_series(
        samples: list[dict[str, object]], key: str, *, offset: float = 0.0
    ) -> list[float]:
        return [
            max(0.0, float(sample[key]) - offset)
            for sample in samples[-_DIAGNOSTIC_TREND_POINT_LIMIT:]
            if isinstance(sample.get(key), int | float)
        ]

    @staticmethod
    def _diagnostic_trend_direction(values: list[float], scale: float) -> str:
        if len(values) < 4:
            return "Collecting"
        window = max(2, min(8, len(values) // 3))
        delta = sum(values[-window:]) / window - sum(values[:window]) / window
        tolerance = max(scale * 0.05, 1.0)
        if delta > tolerance:
            return "Rising"
        if delta < -tolerance:
            return "Falling"
        return "Stable"

    def _diagnostic_trend_specs(
        self, snapshot: dict[str, object]
    ) -> list[dict[str, object]]:
        samples = list(self._resource_samples)
        baseline = snapshot["resource_baseline"]

        def build_spec(
            key: str,
            title: str,
            values: list[float],
            suffix: str,
            detail: str,
            *,
            watch_at: float,
            lag_at: float,
        ) -> dict[str, object]:
            current = values[-1] if values else None
            health = self._diagnostic_metric_health(current, watch_at, lag_at)
            return {
                "key": key,
                "title": title,
                "values": values,
                "value": f"{current:.1f}{suffix}"
                if current is not None
                else "Collecting",
                "direction": self._diagnostic_trend_direction(values, lag_at),
                "detail": detail,
                "watch_at": watch_at,
                "lag_at": lag_at,
                "health": health,
                "color": self._diagnostic_health_color(health),
            }

        ui_values = [
            float(value)
            for value in list(self._heartbeat_samples)[-_DIAGNOSTIC_TREND_POINT_LIMIT:]
        ]
        memory_offset = (
            float(baseline.get("rss_mb", 0.0)) if isinstance(baseline, dict) else 0.0
        )
        return [
            build_spec(
                "ui",
                "UI heartbeat lag",
                ui_values,
                " ms",
                "Timer delay in the desktop UI.",
                watch_at=80.0,
                lag_at=150.0,
            ),
            build_spec(
                "cpu",
                "Process CPU",
                self._diagnostic_numeric_series(samples, "cpu_pct"),
                "%",
                "Percent of one CPU core.",
                watch_at=50.0,
                lag_at=90.0,
            ),
            build_spec(
                "memory",
                "Memory drift",
                self._diagnostic_numeric_series(samples, "rss_mb", offset=memory_offset),
                " MB",
                "Working-set growth above the startup baseline.",
                watch_at=200.0,
                lag_at=500.0,
            ),
            build_spec(
                "queue",
                "UI callback queue",
                self._diagnostic_numeric_series(samples, "ui_queue_depth"),
                "",
                "Callbacks waiting for the UI thread.",
                watch_at=100.0,
                lag_at=500.0,
            ),
        ]

    def _reset_diagnostics_metrics(self) -> None:
        self._heartbeat_samples.clear()
        self._last_heartbeat_lag_ms = 0.0
        self._max_heartbeat_lag_ms = 0.0
        self._slow_heartbeat_count = 0
        self._resource_samples.clear()
        self._resource_latest = {}
        self._resource_baseline = None
        self._last_resource_warning_at = 0.0
        self._resource_last_cpu_sample = (time.perf_counter(), time.process_time())
        self._perf_events.clear()
        self._perf_counters.clear()
        self._perf_last_ms.clear()
        self._perf_max_ms.clear()
        self._diagnostics.reset()
        self._record_perf_event("Diagnostics reset")
        self._set_diagnostics_snapshot_text()
        self._refresh_diagnostics_window()

    def _diagnostics_log_text(self) -> str:
        captured_log = self._captured_log_text()
        if len(captured_log) > _DIAGNOSTIC_LOG_TAIL_CHARS:
            captured_log = (
                "Earlier captured UI log text was omitted from this diagnostic log.\n"
                + captured_log[-_DIAGNOSTIC_LOG_TAIL_CHARS:]
            )
        selected = ", ".join(self._selected_keys()) or "None"
        lines = [
            "Master Class Diagnostics Workbench diagnostic log.",
            f"Created: {datetime.now().strftime('%m-%d-%Y %H:%M:%S')}.",
            f"App version: {app_version.version()}.",
            f"Python: {sys.version.split()[0]}.",
            f"Project root: {PROJECT_ROOT}.",
            "",
            self._format_diagnostics_report(),
            "",
            "Build state.",
            f"Build running: {self._build_running}.",
            f"Cancel requested: {self._cancel_requested}.",
            f"Run folder: {self._run_folder or 'Not created'}.",
            f"Selected modules: {selected}.",
            "",
            "Captured UI log tail.",
            captured_log.strip() or "No captured UI log text.",
        ]
        return "\n".join(lines) + "\n"

    def _diagnostics_log_folder(self) -> Path:
        candidates = [self._run_folder]
        output_folder = _display_path(self.output_folder_var.get())
        if output_folder:
            candidates.append(Path(output_folder))
        candidates.append(_app_data_dir())
        for folder in candidates:
            if folder is None:
                continue
            try:
                folder.mkdir(parents=True, exist_ok=True)
                return folder
            except OSError:
                continue
        return PROJECT_ROOT

    def _save_diagnostics_log(self) -> None:
        folder = self._diagnostics_log_folder()
        initial_name = (
            f"MasterClass_DiagnosticLog_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        selected = filedialog.asksaveasfilename(
            title="Save Diagnostic Log",
            initialdir=str(folder),
            initialfile=initial_name,
            defaultextension=".txt",
            filetypes=[
                ("Text files", "*.txt"),
                ("Log files", "*.log"),
                ("All files", "*.*"),
            ],
        )
        if not selected:
            return
        path = Path(selected).with_suffix(Path(selected).suffix or ".txt")
        try:
            path.write_text(self._diagnostics_log_text(), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Could not save diagnostic log", str(exc))
            return
        self._record_perf_event("Diagnostics log saved", detail=str(path))
        self._refresh_diagnostics_window()
        messagebox.showinfo("Diagnostic log saved", f"Saved diagnostic log.\n\n{path}")

    def _toggle_diagnostics_window(self) -> None:
        window = self._diagnostics_window
        try:
            if window is not None and window.winfo_exists():
                self._close_diagnostics_window()
                return
        except TclError:
            pass
        self._show_diagnostics_window()

    def _set_diagnostics_snapshot_text(self) -> None:
        text = self._diagnostics_textbox
        if text is None:
            return
        try:
            text.configure(state="normal")
            text.delete("1.0", "end")
            text.insert("1.0", self._format_diagnostics_report())
            text.configure(state="disabled")
        except TclError:
            pass

    def _create_diagnostics_visual_panel(self, parent) -> None:
        panel = ctk.CTkFrame(
            parent,
            fg_color=PAPER,
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
        )
        panel.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        panel.grid_columnconfigure((0, 1, 2), weight=1, uniform="diagnostic_metric")
        summary = ctk.CTkFrame(panel, fg_color="transparent")
        summary.grid(row=0, column=0, columnspan=3, sticky="ew", padx=16, pady=(14, 8))
        summary.grid_columnconfigure((0, 1, 2), weight=1, uniform="diagnostic_summary")
        for column, key, title in (
            (0, "health", "Health"),
            (1, "loop", "UI responsiveness"),
            (2, "resources", "Resource pressure"),
        ):
            label = ctk.CTkLabel(
                summary,
                text=f"{title}: collecting",
                text_color=INK,
                font=(UI_FONT, 13, "bold"),
                anchor="w",
            )
            label.grid(
                row=0, column=column, sticky="ew", padx=(0 if column == 0 else 10, 0)
            )
            self._diagnostics_summary_labels[key] = label
        for index, spec in enumerate(
            self._diagnostic_visual_specs(self._diagnostics_snapshot())
        ):
            card = self._create_diagnostic_metric_card(panel, spec)
            card.grid(
                row=1 + index // 3,
                column=index % 3,
                sticky="ew",
                padx=(16 if index % 3 == 0 else 8, 16 if index % 3 == 2 else 8),
                pady=(4, 14 if index >= 3 else 8),
            )
        self._create_diagnostics_guidance_panel(panel, 3)
        self._create_diagnostics_trend_panel(panel, 4)

    def _create_diagnostic_metric_card(self, parent, spec: dict[str, object]):
        card = ctk.CTkFrame(
            parent,
            fg_color=DIAGNOSTIC_CARD_BG,
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            card,
            text=str(spec["title"]),
            text_color=INK,
            font=(UI_FONT, 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        value = ctk.CTkLabel(
            card,
            text=str(spec["value"]),
            text_color=str(spec["color"]),
            font=(UI_FONT, 18, "bold"),
            anchor="w",
        )
        value.grid(row=1, column=0, sticky="ew", padx=12, pady=(2, 0))
        bar = ctk.CTkProgressBar(
            card,
            height=8,
            corner_radius=4,
            fg_color=DIAGNOSTIC_GAUGE_TRACK,
            progress_color=str(spec["color"]),
        )
        bar.grid(row=2, column=0, sticky="ew", padx=12, pady=(8, 0))
        bar.set(float(spec["ratio"]))
        detail = ctk.CTkLabel(
            card,
            text=str(spec["detail"]),
            text_color=MUTED,
            font=(UI_FONT, 10),
            anchor="w",
            justify="left",
            wraplength=270,
        )
        detail.grid(row=3, column=0, sticky="ew", padx=12, pady=(6, 10))
        self._diagnostics_visual_widgets[str(spec["key"])] = {
            "value": value,
            "bar": bar,
            "detail": detail,
        }
        return card

    def _create_diagnostics_guidance_panel(self, parent, row: int) -> None:
        guide = ctk.CTkFrame(
            parent,
            fg_color="#F8FBFE",
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
        )
        guide.grid(row=row, column=0, columnspan=3, sticky="ew", padx=16, pady=(0, 12))
        guide.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            guide,
            text="When to report an issue",
            text_color=INK,
            font=(UI_FONT, 13, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        ctk.CTkLabel(
            guide,
            text=(
                "Brief spikes are expected while scanning folders and building outputs. "
                "Capture the snapshot when red persists, memory rises steadily, or "
                "the same action repeatedly delays or freezes the Workbench."
            ),
            text_color=MUTED,
            font=(UI_FONT, 11),
            anchor="w",
            justify="left",
            wraplength=940,
        ).grid(row=1, column=0, sticky="ew", padx=12, pady=(4, 10))

    def _create_diagnostics_trend_panel(self, parent, row: int) -> None:
        ctk.CTkLabel(
            parent,
            text="Performance trends",
            text_color=INK,
            font=(UI_FONT, 14, "bold"),
            anchor="w",
        ).grid(row=row, column=0, columnspan=3, sticky="ew", padx=16, pady=(4, 6))
        ctk.CTkLabel(
            parent,
            text="Amber marks the Watch threshold. Red marks the sustained issue threshold.",
            text_color=MUTED,
            font=(UI_FONT, 11),
            anchor="w",
        ).grid(row=row + 1, column=0, columnspan=3, sticky="ew", padx=16)
        trend_frame = ctk.CTkFrame(parent, fg_color="transparent")
        trend_frame.grid(
            row=row + 2, column=0, columnspan=3, sticky="ew", padx=16, pady=(6, 14)
        )
        trend_frame.grid_columnconfigure((0, 1), weight=1, uniform="diagnostic_trend")
        for index, spec in enumerate(
            self._diagnostic_trend_specs(self._diagnostics_snapshot())
        ):
            card = self._create_diagnostic_trend_card(trend_frame, spec)
            card.grid(
                row=index // 2,
                column=index % 2,
                sticky="ew",
                padx=(0 if index % 2 == 0 else 8, 8 if index % 2 == 0 else 0),
                pady=(0, 8 if index < 2 else 0),
            )

    def _create_diagnostic_trend_card(self, parent, spec: dict[str, object]):
        card = ctk.CTkFrame(
            parent,
            fg_color=DIAGNOSTIC_CARD_BG,
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text=str(spec["title"]),
            text_color=INK,
            font=(UI_FONT, 12, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="ew")
        value = ctk.CTkLabel(
            head,
            text=f"{spec['value']} - {spec['direction']}",
            text_color=str(spec["color"]),
            font=(UI_FONT, 12, "bold"),
            anchor="e",
        )
        value.grid(row=0, column=1, sticky="e", padx=(8, 0))
        canvas = tk.Canvas(
            card, height=78, bg=DIAGNOSTIC_CARD_BG, highlightthickness=0, bd=0
        )
        canvas.grid(row=1, column=0, sticky="ew", padx=12, pady=(8, 0))
        detail = ctk.CTkLabel(
            card,
            text=str(spec["detail"]),
            text_color=MUTED,
            font=(UI_FONT, 10),
            anchor="w",
            justify="left",
            wraplength=430,
        )
        detail.grid(row=2, column=0, sticky="ew", padx=12, pady=(6, 10))
        self._diagnostics_trend_widgets[str(spec["key"])] = {
            "value": value,
            "canvas": canvas,
            "detail": detail,
        }
        self._draw_diagnostic_trend(canvas, spec)
        return card

    def _draw_diagnostic_trend(self, canvas: tk.Canvas, spec: dict[str, object]) -> None:
        try:
            if not canvas.winfo_exists():
                return
        except TclError:
            return
        canvas.configure(bg=DIAGNOSTIC_CARD_BG)
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 260), max(canvas.winfo_height(), 72)
        top, right, bottom, left = 8, 4, 10, 4
        plot_width, plot_height = (
            max(width - left - right, 1),
            max(height - top - bottom, 1),
        )
        values = [
            float(value)
            for value in spec.get("values", [])
            if isinstance(value, int | float)
        ]
        watch_at = float(spec.get("watch_at") or 0.0)
        lag_at = max(float(spec.get("lag_at") or 1.0), 1.0)
        canvas.create_rectangle(
            left,
            top,
            left + plot_width,
            top + plot_height,
            outline=DIAGNOSTIC_GAUGE_TRACK,
        )
        watch_y = top + plot_height * (1 - max(0.0, min(1.0, watch_at / lag_at)))
        canvas.create_line(
            left, watch_y, left + plot_width, watch_y, fill=OCHRE, dash=(3, 4)
        )
        canvas.create_text(
            left + 5,
            watch_y - 6,
            text="Watch",
            fill=OCHRE,
            font=(UI_FONT, 8, "bold"),
            anchor="w",
        )
        canvas.create_line(left, top, left + plot_width, top, fill=CLAY, dash=(3, 4))
        canvas.create_text(
            left + 5,
            top + 8,
            text="Sustained issue",
            fill=CLAY,
            font=(UI_FONT, 8, "bold"),
            anchor="w",
        )
        if not values:
            canvas.create_text(
                left + plot_width / 2,
                top + plot_height / 2,
                text="Collecting",
                fill=MUTED,
                font=(UI_FONT, 10),
            )
            return
        if len(values) == 1:
            x, y = (
                left + plot_width,
                top + plot_height * (1 - min(1.0, values[0] / lag_at)),
            )
            canvas.create_oval(
                x - 3, y - 3, x + 3, y + 3, fill=str(spec["color"]), outline=""
            )
            return
        step = plot_width / (len(values) - 1)
        points: list[float] = []
        for index, value in enumerate(values):
            ratio = max(0.0, min(1.0, value / lag_at))
            points.extend([left + index * step, top + plot_height * (1 - ratio)])
        canvas.create_line(points, fill=str(spec["color"]), width=2, smooth=True)

    def _update_diagnostics_visuals(self, snapshot: dict[str, object]) -> None:
        for key, text in (
            ("health", f"Health: {snapshot['health']}"),
            ("loop", f"UI responsiveness: {snapshot['loop_health']}"),
            ("resources", f"Resource pressure: {snapshot['resource_health']}"),
        ):
            label = self._diagnostics_summary_labels.get(key)
            if label is not None:
                try:
                    if label.winfo_exists():
                        label.configure(text=text)
                except TclError:
                    pass
        for spec in self._diagnostic_visual_specs(snapshot):
            widgets = self._diagnostics_visual_widgets.get(str(spec["key"]))
            if not widgets:
                continue
            value, bar, detail = widgets["value"], widgets["bar"], widgets["detail"]
            try:
                value.configure(text=str(spec["value"]), text_color=str(spec["color"]))
                bar.configure(progress_color=str(spec["color"]))
                bar.set(float(spec["ratio"]))
                detail.configure(text=str(spec["detail"]))
            except TclError:
                pass
        for spec in self._diagnostic_trend_specs(snapshot):
            widgets = self._diagnostics_trend_widgets.get(str(spec["key"]))
            if not widgets:
                continue
            value, canvas, detail = widgets["value"], widgets["canvas"], widgets["detail"]
            try:
                value.configure(
                    text=f"{spec['value']} - {spec['direction']}",
                    text_color=str(spec["color"]),
                )
                detail.configure(text=str(spec["detail"]))
            except TclError:
                continue
            self._draw_diagnostic_trend(canvas, spec)

    def _show_diagnostics_window(self) -> None:
        screen_width = max(760, self.winfo_screenwidth())
        screen_height = max(640, self.winfo_screenheight())
        window = ctk.CTkToplevel(self)
        window.title("Workbench Diagnostics")
        window.geometry(
            f"{min(1120, max(760, screen_width - 80))}x"
            f"{min(980, max(760, screen_height - 100))}"
        )
        window.minsize(760, 680)
        window.configure(fg_color=CANVAS)
        self._diagnostics_window = window
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(window, fg_color=PAPER, corner_radius=8)
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text="Workbench diagnostics",
            text_color=INK,
            font=(UI_FONT, 24, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 0))
        ctk.CTkLabel(
            header,
            text="Press Ctrl+Shift+D to close this panel.",
            text_color=MUTED,
            font=(UI_FONT, 13),
            anchor="w",
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(2, 14))
        actions = ctk.CTkFrame(header, fg_color="transparent")
        actions.grid(row=0, column=1, rowspan=2, sticky="e", padx=16)
        for text, command in (
            ("Copy Snapshot", self._copy_diagnostics_snapshot),
            ("Save Log", self._save_diagnostics_log),
            ("Refresh", self._set_diagnostics_snapshot_text),
            ("Reset", self._reset_diagnostics_metrics),
        ):
            self._secondary_toolbar_button(actions, text, command).pack(
                side="left", padx=(0, 8)
            )

        self._diagnostics_visual_widgets = {}
        self._diagnostics_trend_widgets = {}
        self._diagnostics_summary_labels = {}
        body = ctk.CTkScrollableFrame(
            window,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=PLUM,
            scrollbar_button_hover_color="#0B4FC0",
        )
        body.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
        body.grid_columnconfigure(0, weight=1)
        self._wire_scrollable_inner_width(body)
        self._create_diagnostics_visual_panel(body)
        text = ctk.CTkTextbox(
            body,
            fg_color=DIAGNOSTIC_CARD_BG,
            text_color=INK,
            border_width=1,
            border_color=HAIRLINE,
            corner_radius=8,
            font=("Consolas", 12),
            height=260,
            wrap="none",
        )
        text.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        self._diagnostics_textbox = text
        footer = ctk.CTkFrame(window, fg_color=PAPER, corner_radius=8)
        footer.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 18))
        footer.grid_columnconfigure(0, weight=1)
        self._pill_button(footer, "Close", self._close_diagnostics_window, FOG, INK).grid(
            row=0, column=1, padx=(8, 14), pady=12
        )
        window.protocol("WM_DELETE_WINDOW", self._close_diagnostics_window)
        self._record_perf_event("Diagnostics opened")
        self._set_diagnostics_snapshot_text()
        self._refresh_diagnostics_window()
        window.lift()
        window.focus_force()

    def _refresh_diagnostics_window(self) -> None:
        window = self._diagnostics_window
        try:
            if window is None or not window.winfo_exists():
                return
            if self._diagnostics_refresh_after_id is not None:
                try:
                    window.after_cancel(self._diagnostics_refresh_after_id)
                except TclError:
                    pass
                self._diagnostics_refresh_after_id = None
            self._update_diagnostics_visuals(self._diagnostics_snapshot())
            self._diagnostics_refresh_after_id = window.after(
                1000, self._refresh_diagnostics_window
            )
        except TclError:
            self._diagnostics_window = None
            self._diagnostics_textbox = None
            self._diagnostics_refresh_after_id = None

    def _copy_diagnostics_snapshot(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self._format_diagnostics_report())
        self.update_idletasks()
        self._record_perf_event("Diagnostics copied")
        self._refresh_diagnostics_window()

    def _close_diagnostics_window(self) -> None:
        window = self._diagnostics_window
        if window is not None and self._diagnostics_refresh_after_id is not None:
            try:
                window.after_cancel(self._diagnostics_refresh_after_id)
            except TclError:
                pass
        self._diagnostics_window = None
        self._diagnostics_textbox = None
        self._diagnostics_refresh_after_id = None
        self._diagnostics_visual_widgets = {}
        self._diagnostics_trend_widgets = {}
        self._diagnostics_summary_labels = {}
        try:
            if window is not None and window.winfo_exists():
                window.destroy()
        except TclError:
            pass

    # ------------------------------------------------------------------
    # Shell: brand bar, step rail, hero, content, action bar, footer
    # ------------------------------------------------------------------

    def _build_shell(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self._build_brand_bar()
        self._build_step_rail()

        self.main = ctk.CTkFrame(self, fg_color="transparent")
        self.main.grid(row=2, column=0, sticky="nsew", padx=30, pady=(28, 0))
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)
        self.hero = ctk.CTkFrame(self.main, fg_color="transparent")
        self.hero.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.hero.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(
            self.hero, text="", text_color=INK, font=(UI_FONT, 32, "bold")
        )
        self.title_label.grid(row=0, column=0, sticky="w")
        self.content = ctk.CTkFrame(self.main, fg_color="transparent")
        self.content.grid(row=1, column=0, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)

        self.nav = ctk.CTkFrame(self, fg_color=PAPER, corner_radius=0)
        self.nav.grid(row=3, column=0, sticky="ew")
        ctk.CTkFrame(self.nav, height=1, fg_color=HAIRLINE, corner_radius=0).place(
            relx=0.0, rely=0.0, relwidth=1.0, anchor="nw"
        )
        self.nav.grid_columnconfigure(2, weight=1)
        self.reset_button = self._action_secondary_button(
            self.nav, "Start over", self._confirm_start_over
        )
        self.reset_button.grid(row=0, column=0, padx=(30, 0), pady=16)
        self.back_button = self._action_secondary_button(self.nav, "Back", self._back)
        self.back_button.grid(row=0, column=1, padx=(16, 0), pady=16)
        self.next_button = self._action_primary_button(self.nav, "Next", self._next)
        self.next_button.grid(row=0, column=3, padx=(16, 30), pady=16)
        self.close_button = self._action_primary_button(self.nav, "Close", self._on_close)
        self.close_button.grid(row=0, column=4, padx=(0, 30), pady=16)
        self._build_footer_rail()

    def _condensed_font_family(self) -> str:
        try:
            if CONDENSED_FONT_FILE.is_file() and IS_WINDOWS:
                ctypes.windll.gdi32.AddFontResourceExW(str(CONDENSED_FONT_FILE), 0x10, 0)
            if "Roboto Condensed" in tkfont.families(self):
                return "Roboto Condensed"
        except (OSError, AttributeError, TclError, ValueError):
            return UI_FONT
        return UI_FONT

    def _build_brand_bar(self) -> None:
        bar = ctk.CTkFrame(self, fg_color=BRAND_NAVY, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(2, weight=1)
        self.logo_image = _make_logo(38)
        if self.logo_image is not None:
            ctk.CTkLabel(
                bar,
                text="",
                image=self.logo_image,
                width=38,
                height=38,
                fg_color="transparent",
            ).grid(row=0, column=0, padx=(30, 18), pady=16)
        self._condensed_family = self._condensed_font_family()
        stack = ctk.CTkFrame(bar, fg_color="transparent")
        stack.grid(
            row=0, column=1, sticky="w", pady=16, padx=(0 if self.logo_image else 30, 0)
        )
        ctk.CTkLabel(
            stack,
            text="BIGFIX PLATFORM",
            text_color=BRAND_EYEBROW,
            font=(UI_FONT, 11, "bold"),
            anchor="w",
            height=13,
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            stack,
            text="MASTER CLASS DIAGNOSTICS WORKBENCH",
            text_color="#FFFFFF",
            font=(self._condensed_family, 24, "bold"),
            anchor="w",
            height=27,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))
        ctk.CTkLabel(
            stack,
            text="Automated performance and configuration analysis.",
            text_color=BRAND_EYEBROW,
            font=(UI_FONT, 13),
            anchor="w",
            height=15,
        ).grid(row=2, column=0, sticky="w", pady=(8, 0))
        right = ctk.CTkFrame(bar, fg_color="transparent")
        right.grid(row=0, column=3, sticky="e", padx=(0, 30))
        ctk.CTkLabel(
            right,
            text="2.0",
            text_color="#FFFFFF",
            font=(UI_FONT, 13),
        ).grid(row=0, column=0)

    def _build_step_rail(self) -> None:
        holder = ctk.CTkFrame(self, fg_color=RAIL, corner_radius=0)
        holder.grid(row=1, column=0, sticky="ew")
        holder.grid_columnconfigure(0, weight=1)
        rail = ctk.CTkFrame(holder, fg_color="transparent")
        rail.grid(row=0, column=0, sticky="ew", padx=30)
        rail.grid_columnconfigure(1, weight=1)
        items = ctk.CTkFrame(rail, fg_color="transparent")
        items.grid(row=0, column=0, sticky="w")
        self.step_badges: list[ctk.CTkButton] = []
        self.step_labels: list[ctk.CTkLabel] = []
        self._step_indicators: list[ctk.CTkFrame] = []
        for idx, label_text in enumerate(RAIL_LABELS, start=1):
            item = ctk.CTkFrame(items, fg_color="transparent")
            item.grid(row=0, column=idx - 1, sticky="ns")
            item.grid_columnconfigure(0, weight=1)
            inner = ctk.CTkFrame(item, fg_color="transparent")
            inner.grid(row=0, column=0, padx=(0 if idx == 1 else 28, 28), pady=(18, 14))
            badge = ctk.CTkButton(
                inner,
                text=str(idx),
                width=30,
                height=30,
                corner_radius=15,
                border_width=2,
                border_color=FIELD_BORDER,
                fg_color="transparent",
                hover=False,
                text_color=INK,
                font=(UI_FONT, 13, "bold"),
                command=lambda n=idx: self._on_nav_click(n),
            )
            badge.grid(row=0, column=0)
            label = ctk.CTkLabel(
                inner, text=label_text, text_color=INK, font=(UI_FONT, 15), anchor="w"
            )
            label.grid(row=0, column=1, padx=(12, 0))
            indicator = ctk.CTkFrame(
                item, fg_color="transparent", height=4, corner_radius=0
            )
            indicator.grid(row=1, column=0, sticky="ew")
            for widget in (item, inner, label):
                widget.bind("<Button-1>", lambda _e, n=idx: self._on_nav_click(n))
                with contextlib.suppress(TclError):
                    widget.configure(cursor="hand2")
            self.step_badges.append(badge)
            self.step_labels.append(label)
            self._step_indicators.append(indicator)
        # width/height 1: an empty CTkFrame otherwise requests its default
        # 200 px and inflates the rail on step 1, where the run label is hidden.
        right = ctk.CTkFrame(rail, fg_color="transparent", width=1, height=1)
        right.grid(row=0, column=2, sticky="e")
        self._rail_run_divider = ctk.CTkFrame(
            right, width=1, height=18, fg_color=FIELD_BORDER, corner_radius=0
        )
        self._rail_run_divider.grid(row=0, column=0, padx=10)
        self._rail_run_label = ctk.CTkLabel(
            right, text="", text_color=INK, font=(UI_FONT, 14, "bold")
        )
        self._rail_run_label.grid(row=0, column=1)
        ctk.CTkFrame(holder, height=1, fg_color=FIELD_BORDER, corner_radius=0).grid(
            row=1, column=0, sticky="ew"
        )
        self._update_rail_context()

    def _update_rail_context(self) -> None:
        run_name = self.run_name_var.get().strip()
        if run_name and self.step != 1:
            self._rail_run_divider.grid()
            self._rail_run_label.configure(text=run_name)
            self._rail_run_label.grid()
        else:
            self._rail_run_divider.grid_remove()
            self._rail_run_label.grid_remove()

    def _build_footer_rail(self) -> None:
        rail = ctk.CTkFrame(self, fg_color=FOOTER_RAIL, corner_radius=0)
        rail.grid(row=4, column=0, sticky="ew")
        ctk.CTkFrame(rail, height=1, fg_color=HAIRLINE, corner_radius=0).place(
            relx=0.0, rely=0.0, relwidth=1.0, anchor="nw"
        )
        rail.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(
            rail,
            text=f"{APP_TITLE}. Provided as-is for BigFix Master Class attendees.",
            text_color=INK,
            font=(UI_FONT, 12),
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(30, 0), pady=8)
        ctk.CTkLabel(
            rail,
            text="Press Ctrl+Shift+D to show diagnostics.",
            text_color=MUTED,
            font=(UI_FONT, 11),
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=16, pady=8)
        self._footer_run_label = ctk.CTkLabel(
            rail, text="", text_color=LINK_BLUE, font=(UI_FONT, 12), cursor="hand2"
        )
        self._footer_run_label.grid(row=0, column=2, sticky="e", padx=(16, 30), pady=8)
        self._footer_run_label.bind("<Button-1>", lambda _e: self._open_output_folder())

    def _action_secondary_button(self, parent, text: str, command):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=44,
            corner_radius=8,
            fg_color=PAPER,
            hover_color="#F4F7FB",
            border_width=1,
            border_color=FIELD_BORDER,
            text_color=INK,
            font=(UI_FONT, 15, "bold"),
        )
        button.configure(width=self._action_button_width(text, 24))
        return button

    def _action_primary_button(self, parent, text: str, command):
        button = ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=44,
            corner_radius=8,
            fg_color=PLUM,
            hover_color="#0a48a8",
            text_color="#FFFFFF",
            font=(UI_FONT, 15, "bold"),
        )
        button.configure(width=self._action_button_width(text, 36))
        return button

    @staticmethod
    def _action_button_width(text: str, side_padding: int) -> int:
        font = tkfont.Font(family=UI_FONT, size=15, weight="bold")
        return font.measure(text) + 2 * side_padding

    def _pill_button(self, parent, text: str, command, fg: str, text_color: str = PAPER):
        hover = {PLUM: "#0B4FC0", PAPER: "#EEF3F8", FOG: "#CAD8E8", CLAY: "#9A330A"}.get(
            fg, fg
        )
        return ctk.CTkButton(
            parent,
            text=text,
            command=command,
            height=42,
            corner_radius=8,
            fg_color=fg,
            hover_color=hover,
            text_color=text_color,
            font=(UI_FONT, 13, "bold"),
        )

    def _step2_pill_button(
        self, parent, text: str, command, fg: str, text_color: str = PAPER
    ):
        button = self._pill_button(parent, text, command, fg, text_color)
        button.configure(height=44, corner_radius=8, font=(UI_FONT, 15, "bold"))
        return button

    def _secondary_toolbar_button(self, parent, text: str, command):
        button = self._pill_button(parent, text, command, fg=PAPER, text_color=INK)
        button.configure(
            height=34,
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
            hover_color="#F4F7FB",
            font=(UI_FONT, 13, "bold"),
        )
        return button

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _show_step(self, step: int) -> None:
        HoverTip.dismiss_active()
        self.step = step
        self.title_label.configure(text=STEP_TITLES[step])
        self._update_rail_context()
        self._clear_content()
        if step == 1:
            self._build_step1()
        elif step == 2:
            self._build_step2()
        else:
            self._build_step3()
        self._set_nav_state(step)
        self._sync_nav()

    def _clear_content(self) -> None:
        started = time.perf_counter()
        child_count = len(self.content.winfo_children())
        self._field_widgets.clear()
        self._field_rest_borders.clear()
        self._module_card_controls.clear()
        self._canvas_status_pills.clear()
        self._group_count_label = None
        HoverTip.dismiss_active()
        for child in self.content.winfo_children():
            child.destroy()
        elapsed_ms = (time.perf_counter() - started) * 1000
        if child_count or elapsed_ms >= _UI_QUEUE_BUDGET_MS:
            self._record_diagnostic(
                "Clear step content",
                elapsed_ms=elapsed_ms,
                widgets=child_count,
            )

    def _set_nav_state(self, step: int) -> None:
        rows = zip(self.step_badges, self.step_labels, self._step_indicators)
        for idx, (badge, label, indicator) in enumerate(rows, start=1):
            state = "active" if idx == step else "idle"
            if self._nav_row_states.get(idx) == state:
                continue
            self._nav_row_states[idx] = state
            if state == "active":
                badge.configure(fg_color=PLUM, border_width=0, text_color="#FFFFFF")
                label.configure(text_color=INK, font=(UI_FONT, 15, "bold"))
                indicator.configure(fg_color=PLUM)
            else:
                badge.configure(fg_color="transparent", border_width=2, text_color=INK)
                label.configure(text_color=INK, font=(UI_FONT, 15))
                indicator.configure(fg_color="transparent")

    def _sync_nav(self) -> None:
        locked = self._build_running
        self.reset_button.configure(state="disabled" if locked else "normal")
        self.back_button.configure(
            state="disabled" if locked or self.step == 1 else "normal"
        )
        if self.step == 1:
            self.back_button.grid_remove()
        else:
            self.back_button.grid()
        if self.step == 3:
            self.next_button.grid_remove()
            self.close_button.grid()
            self.close_button.configure(state="disabled" if locked else "normal")
        else:
            self.close_button.grid_remove()
            self.next_button.grid()
            self.next_button.configure(state="normal")

    def _on_nav_click(self, n: int) -> None:
        if not self._build_running:
            self._go_step(n)

    def _go_step(self, step: int) -> None:
        if step == self.step:
            return
        if step > self.step:
            errors: list[str] = []
            bad_fields: set[str] = set()
            if step >= 2 and self.step <= 1:
                step1_errors, step1_bad = self._validate_step1()
                errors.extend(step1_errors)
                bad_fields |= step1_bad
                if (
                    not errors
                    and not self._discovered
                    and self.data_root_var.get().strip()
                ):
                    self._scan_inputs()
            if step == 3 and self.step <= 2:
                errors.extend(self._validate_step2(bad_fields))
            if errors:
                self._reveal_step2_fields(bad_fields)
                self._apply_field_highlights(bad_fields)
                self._show_errors("Check Inputs", errors)
                return
        self._show_step(step)

    def _next(self) -> None:
        self._go_step(self.step + 1)

    def _back(self) -> None:
        if self.step > 1:
            self._show_step(self.step - 1)

    def _show_errors(self, title: str, errors: list[str]) -> None:
        messagebox.showerror(title, "\n".join(f"- {err}" for err in errors))

    def _confirm_start_over(self) -> None:
        if messagebox.askyesno(
            "Start over?", "Clear every step and begin a new run? This cannot be undone."
        ):
            self._reset_form()

    def _reset_form(self) -> None:
        self._scan_token += 1
        self.data_root_var.set("")
        self.output_folder_var.set(_display_path(DEFAULT_WORK_DIR))
        self.run_name_var.set("")
        self.scan_confirmation_var.set("")
        self.scan_missing_var.set("")
        for var in self.module_vars.values():
            var.set(False)
        for var in self.module_input_override_vars.values():
            var.set("")
        for var in self.date_field_vars.values():
            var.set("")
        for var in (
            self.perfmon_processors_var,
            self.perfmon_disks_var,
            self.perfmon_memory_var,
            self.perfmon2_processors_var,
            self.perfmon2_disks_var,
            self.perfmon2_memory_var,
        ):
            var.set("")
        self.perfmon_vm_var.set(False)
        self.perfmon2_vm_var.set(False)
        self._discovered = {}
        self._optional_input_cache = {}
        self._expanded_module_key = None
        self._run_folder = None
        self._run_log_path = None
        self._clear_captured_log()
        self._footer_run_label.configure(text="")
        self._show_step(1)

    # ------------------------------------------------------------------
    # Field highlighting (one registry for every step)
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
                border_width=1,
                border_color=self._field_rest_borders.get(field_id, FIELD_BORDER),
            )
        except TclError:
            self._field_widgets.pop(field_id, None)

    def _register_field(
        self, field_id: str, entry, rest_border: str = FIELD_BORDER
    ) -> None:
        self._field_widgets[field_id] = entry
        self._field_rest_borders[field_id] = rest_border

    def _reveal_step2_fields(self, field_ids) -> None:
        if self.step != 2:
            return
        for field_id in sorted(field_ids):
            key = field_id.split(":", 1)[0]
            if key not in MODULE_BY_KEY:
                continue
            if self._expanded_module_key != key:
                self._expand_module_row(key)
            self._scroll_to_module_row(key)
            return

    def _scroll_to_module_row(self, key: str) -> None:
        """Bring a module row (and its open expansion) to the top of the list."""
        controls = self._module_card_controls.get(key)
        scroll = getattr(self, "module_scroll", None)
        if not controls or scroll is None:
            return
        canvas = controls.get("canvas")
        outer = getattr(scroll, "_parent_canvas", None)
        try:
            if canvas is None or outer is None or not canvas.winfo_exists():
                return
            self.update_idletasks()
            inner_height = max(1, scroll.winfo_height())
            row_top = canvas.winfo_rooty() - scroll.winfo_rooty() + outer.canvasy(0)
            outer.yview_moveto(max(0.0, (row_top - 8) / inner_height))
        except TclError:
            pass

    # ------------------------------------------------------------------
    # Shared form pieces
    # ------------------------------------------------------------------

    def _add_form_section(self, parent, title: str):
        card = ctk.CTkFrame(
            parent,
            fg_color=PAPER,
            corner_radius=12,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.pack(fill="x", padx=(0, 4), pady=(0, 14))
        header = ctk.CTkFrame(card, fg_color=CARD_HEADER, corner_radius=10)
        header.pack(fill="x", padx=2, pady=(2, 0))
        ctk.CTkLabel(
            header, text=title, text_color=INK, font=(self._condensed_family, 14, "bold")
        ).pack(side="left", padx=18, pady=11)
        ctk.CTkFrame(card, fg_color=HAIRLINE, height=1).pack(fill="x", padx=2)
        return card

    def _add_form_row(self, card, label: str, hint: str, *, first: bool = False):
        if not first:
            ctk.CTkFrame(card, fg_color=HAIRLINE, height=1).pack(fill="x", padx=14)
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure(0, minsize=210)
        row.grid_columnconfigure(1, weight=1)
        left = ctk.CTkFrame(row, fg_color="transparent")
        left.grid(row=0, column=0, rowspan=2, sticky="nw", padx=(14, 4), pady=12)
        ctk.CTkLabel(
            left, text=label, text_color=INK, font=(UI_FONT, 15, "bold"), anchor="w"
        ).pack(anchor="w")
        if hint:
            ctk.CTkLabel(
                left,
                text=hint,
                text_color=INK,
                font=(UI_FONT, 14),
                wraplength=192,
                justify="left",
                anchor="w",
            ).pack(anchor="w", pady=(2, 0))
        return row

    def _form_entry(self, parent, var, field_id: str | None = None):
        entry = ctk.CTkEntry(
            parent,
            textvariable=var,
            height=40,
            corner_radius=8,
            border_width=1,
            border_color=FIELD_BORDER,
            fg_color=PAPER,
            text_color=INK,
            font=(UI_FONT, 14),
        )
        if field_id is not None:
            self._register_field(field_id, entry)
        return entry

    def _form_browse_button(self, parent, text: str, command):
        button = self._pill_button(parent, text, command, fg=PAPER, text_color=INK)
        button.configure(
            height=40,
            width=96,
            corner_radius=8,
            border_width=1,
            border_color=FIELD_BORDER,
            hover_color="#F4F7FB",
            font=(UI_FONT, 15, "bold"),
        )
        return button

    def _keep_tail_view(self, entry, var) -> None:
        def move_tail(*_a) -> None:
            try:
                if entry.winfo_exists() and entry.focus_get() is not entry:
                    entry.after(_LAYOUT_DEBOUNCE_MS, lambda: entry.xview_moveto(1.0))
            except TclError:
                pass

        var.trace_add("write", move_tail)
        move_tail()

    def _path_entry(self, parent, text: str, placeholder: str = "No input selected yet."):
        entry = ctk.CTkEntry(
            parent,
            height=34,
            corner_radius=8,
            border_width=1,
            border_color=FIELD_BORDER,
            fg_color=PAPER,
            text_color=INK,
            placeholder_text=placeholder,
            font=(UI_FONT, 14),
        )
        if text:
            entry.insert(0, _display_path(text))
            entry.after(
                _LAYOUT_DEBOUNCE_MS,
                lambda: entry.xview_moveto(1.0) if entry.winfo_exists() else None,
            )
        entry.configure(state="readonly")
        return entry

    def _wire_scrollable_inner_width(self, scrollable) -> None:
        canvas = getattr(scrollable, "_parent_canvas", None)
        frame_id = getattr(scrollable, "_create_window_id", None) or getattr(
            scrollable, "_scrollable_frame_id", None
        )
        if canvas is None or frame_id is None:
            return

        def _sync(event):
            try:
                canvas.itemconfigure(frame_id, anchor="nw", width=event.width)
                canvas.coords(frame_id, 0, 0)
            except TclError:
                pass

        canvas.bind("<Configure>", _sync, add="+")

    def _scrollable(self, parent):
        scroll = ctk.CTkScrollableFrame(
            parent,
            fg_color="transparent",
            corner_radius=0,
            scrollbar_button_color=PLUM,
            scrollbar_button_hover_color="#0B4FC0",
        )
        scroll.grid_columnconfigure(0, weight=1)
        self._wire_scrollable_inner_width(scroll)
        return scroll

    # ------------------------------------------------------------------
    # Step 1: folders and run details
    # ------------------------------------------------------------------

    def _build_step1(self) -> None:
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(0, weight=1)
        form = self._scrollable(frame)
        form.grid(row=0, column=0, sticky="nsew")

        folders = self._add_form_section(form, "Folders")
        data_row = self._add_form_row(
            folders,
            "Data Folder",
            "The folder with the collected data. Optional: leave it blank to pick "
            "each module's input on step 2.",
            first=True,
        )
        data_entry = self._form_entry(data_row, self.data_root_var, "data_root")
        data_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(14, 6))
        self._keep_tail_view(data_entry, self.data_root_var)
        self._form_browse_button(data_row, "Browse", self._browse_data_root).grid(
            row=0, column=2, sticky="e", padx=(0, 14), pady=(14, 6)
        )
        self._scan_confirmation_label = ctk.CTkLabel(
            data_row,
            textvariable=self.scan_confirmation_var,
            text_color=MOSS,
            font=(UI_FONT, 14, "bold"),
            anchor="w",
        )
        self._scan_confirmation_label.grid(row=1, column=1, sticky="w", pady=0)
        missing_holder = ctk.CTkFrame(data_row, fg_color="transparent")
        missing_holder.grid(row=2, column=1, sticky="ew", pady=(2, 14))
        ctk.CTkLabel(
            missing_holder,
            text="Not Found:",
            text_color=OCHRE,
            font=(UI_FONT, 14, "bold"),
            height=20,
        ).pack(side="left", anchor="n")
        ctk.CTkLabel(
            missing_holder,
            textvariable=self.scan_missing_var,
            text_color=INK,
            font=(UI_FONT, 14),
            wraplength=640,
            justify="left",
            height=20,
        ).pack(side="left", anchor="n", padx=(5, 0))
        self._scan_missing_label = missing_holder
        self._sync_scan_confirmation_visibility()

        output_row = self._add_form_row(
            folders, "Output Folder", "A timestamped run folder is created here."
        )
        output_entry = self._form_entry(
            output_row, self.output_folder_var, "output_folder"
        )
        output_entry.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=14)
        self._keep_tail_view(output_entry, self.output_folder_var)
        self._form_browse_button(output_row, "Browse", self._browse_output_folder).grid(
            row=0, column=2, sticky="e", padx=(0, 14), pady=14
        )

        run_details = self._add_form_section(form, "Run Details")
        name_row = self._add_form_row(
            run_details,
            "Run Name",
            "Required. Names the run folder and the output files.",
            first=True,
        )
        name_entry = self._form_entry(name_row, self.run_name_var, "run_name")
        name_entry.configure(width=320)
        name_entry.grid(row=0, column=1, sticky="w", pady=14)

        self._auto_scan_if_ready()

    def _sync_scan_confirmation_visibility(self) -> None:
        pairs = (
            (getattr(self, "_scan_confirmation_label", None), self.scan_confirmation_var),
            (getattr(self, "_scan_missing_label", None), self.scan_missing_var),
        )
        for label, var in pairs:
            if label is None:
                continue
            try:
                if not label.winfo_exists():
                    continue
                if var.get():
                    label.grid()
                else:
                    label.grid_remove()
            except TclError:
                pass

    def _browse_data_root(self) -> None:
        current = self.data_root_var.get().strip()
        path = filedialog.askdirectory(
            title="Choose the data folder",
            initialdir=current if current and Path(current).is_dir() else None,
        )
        if path:
            self.data_root_var.set(_display_path(path))
            self._scan_inputs()

    def _browse_output_folder(self) -> None:
        current = self.output_folder_var.get().strip()
        path = filedialog.askdirectory(
            title="Choose the output folder",
            initialdir=current if current and Path(current).is_dir() else None,
        )
        if path:
            self.output_folder_var.set(_display_path(path))

    def _on_data_root_changed(self) -> None:
        self._clear_field_highlight("data_root")
        if _display_path(self.data_root_var.get()) != self._last_scan_root:
            self._discovered = {}
            self._optional_input_cache = {}
            self.scan_confirmation_var.set("")
            self.scan_missing_var.set("")
            self._sync_scan_confirmation_visibility()

    def _auto_scan_if_ready(self) -> None:
        raw = self.data_root_var.get().strip()
        if raw and Path(raw).is_dir() and _display_path(raw) != self._last_scan_root:
            self._scan_inputs()

    # ------------------------------------------------------------------
    # Scanning and status
    # ------------------------------------------------------------------

    def _scan_inputs(self) -> None:
        raw = self.data_root_var.get().strip()
        root = Path(raw) if raw else None
        if root is None or not root.is_dir():
            return
        self._scan_token += 1
        token = self._scan_token
        self.scan_confirmation_var.set("Scanning...")
        self.scan_missing_var.set("")
        self._sync_scan_confirmation_visibility()

        def worker() -> None:
            started = time.perf_counter()
            try:
                found = scan_input_folder(root)
                ancillary = discover_loop_ancillary_inputs(root, found.get("loop"))
                self._record_diagnostic(
                    "Input scan",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    found_modules=sum(value is not None for value in found.values()),
                )
                self._post(
                    lambda: self._scan_inputs_complete(root, found, ancillary, token)
                )
            except Exception as exc:
                self._post(lambda e=exc: self._scan_inputs_failed(e, token))

        self._scan_thread = threading.Thread(target=worker, daemon=True)
        self._scan_thread.start()
        if self.step == 2:
            self._refresh_module_card_views(tuple(self.module_vars))

    def _scan_inputs_complete(
        self, root: Path, found: dict, ancillary: dict, token: int
    ) -> None:
        if token != self._scan_token:
            return
        self._scan_thread = None
        self._discovered = dict(found)
        self._optional_input_cache = {
            ("loop", key): path for key, path in ancillary.items()
        }
        self._last_scan_root = _display_path(root)
        self._update_scan_confirmation()
        if not any(var.get() for var in self.module_vars.values()):
            self._select_all_available()
        if self.step == 2:
            self._refresh_module_card_views(tuple(self.module_vars))
        self._start_perfmon_detection(auto=True)

    def _scan_inputs_failed(self, exc: Exception, token: int) -> None:
        if token != self._scan_token:
            return
        self._scan_thread = None
        self.scan_confirmation_var.set("")
        self.scan_missing_var.set(f"Scan failed: {exc}")
        self._sync_scan_confirmation_visibility()

    def _update_scan_confirmation(self) -> None:
        statuses = {mod.key: self._data_folder_scan_status(mod)[0] for mod in MODULES}
        found = sum(1 for status in statuses.values() if status == "Found")
        missing = sorted(
            (self._module_display_name(k) for k, s in statuses.items() if s == "Missing"),
            key=str.casefold,
        )
        self.scan_confirmation_var.set(
            f"Data found for {found} of {len(MODULES)} modules."
        )
        self.scan_missing_var.set(
            f"{', '.join(missing)}. Choose files for these on step 2." if missing else ""
        )
        self._sync_scan_confirmation_visibility()

    def _data_folder_scan_status(self, mod: Module) -> tuple[str, str]:
        raw = self.data_root_var.get().strip()
        if not raw or not Path(raw).is_dir():
            return "Not scanned", "Select a data folder."
        path = self._discovered.get(mod.key)
        if path is not None:
            return "Found", f"Found: {_display_path(path)}"
        clue = MISSING_INPUT_CLUES.get(mod.key, "input")
        return "Missing", f"No {clue} found under {_display_path(raw)}."

    def _module_display_name(self, key: str) -> str:
        return MODULE_BY_KEY[key].label

    def _module_available(self, key: str) -> bool:
        mod = MODULE_BY_KEY.get(key)
        return mod is not None and not (mod.windows_only and not IS_WINDOWS)

    def _primary_field(self, mod: Module) -> InputField | None:
        return next((f for f in mod.inputs_schema if f.key == mod.file_key), None)

    def _browsable_input_fields(self, mod: Module) -> list[InputField]:
        if mod.key == "perfmon":
            return []
        return [f for f in mod.inputs_schema if f.kind in BROWSABLE_INPUT_KINDS]

    def _manual_field_input_path(self, key: str, field_key: str | None) -> Path | None:
        if field_key is None:
            return None
        var = self.module_input_override_vars.get((key, field_key))
        raw = var.get().strip() if var is not None else ""
        return Path(raw) if raw else None

    def _manual_input_path(self, key: str) -> Path | None:
        return self._manual_field_input_path(key, MODULE_BY_KEY[key].file_key)

    def _resolved_input_for_field(self, mod: Module, field: InputField) -> Path | None:
        manual = self._manual_field_input_path(mod.key, field.key)
        if manual is not None:
            return manual
        if field.key == mod.file_key:
            discovered = self._discovered.get(mod.key)
            return Path(discovered) if discovered else None
        if mod.key == "loop":
            root_text = self.data_root_var.get().strip()
            root = Path(root_text) if root_text and Path(root_text).is_dir() else None
            primary = self._resolved_input_for_field(mod, self._primary_field(mod))
            try:
                detected = discover_loop_ancillary_inputs(root, primary).get(field.key)
            except Exception:
                detected = None
            return Path(detected) if detected else None
        return None

    def _validate_field_input(
        self, mod: Module, field: InputField, path: Path
    ) -> tuple[bool, str]:
        if field.kind in {"folder", "folder_optional"}:
            if not path.exists():
                return False, "folder does not exist"
            if not path.is_dir():
                return False, "path is not a folder"
            return True, ""
        if not path.exists():
            return False, "file does not exist"
        if not path.is_file():
            return False, "path is not a file"
        if field.extensions and path.suffix.lower() not in {
            ext.lower() for ext in field.extensions
        }:
            return False, f"expected one of: {', '.join(sorted(field.extensions))}"
        if mod.key == "loop" and field.key == mod.file_key:
            validation = validate_loop_workbook(path)
            if not validation.ok:
                return False, validation.reason
        return True, ""

    def _input_field_state(self, mod: Module, field: InputField) -> tuple[str, str]:
        path = self._resolved_input_for_field(mod, field)
        required = field.kind in {"file", "folder"}
        if path is None:
            return ("Needed" if required else "Optional", "Not selected")
        valid, reason = self._validate_field_input(mod, field, path)
        if not valid:
            return "Needed", f"Invalid: {reason}"
        return "Found", _display_path(path)

    def _input_state_color(self, state: str) -> str:
        return {"Found": MOSS, "Optional": MUTED}.get(state, CLAY)

    def _missing_required_input_labels(self, key: str) -> list[str]:
        mod = MODULE_BY_KEY[key]
        primary = self._primary_field(mod)
        missing: list[str] = []
        for field in [primary] if primary is not None else []:
            path = self._resolved_input_for_field(mod, field)
            if path is None:
                missing.append(field.label)
                continue
            valid, reason = self._validate_field_input(mod, field, path)
            if not valid:
                missing.append(f"{field.label} ({reason})")
        return missing

    def _missing_input_message(self, key: str) -> str:
        labels = self._missing_required_input_labels(key)
        if not labels:
            return f"Needs the {MISSING_INPUT_CLUES.get(key, 'module input')}."
        if len(labels) == 1:
            return f"Needs the {labels[0]}."
        return f"Needs the {', '.join(labels[:-1])}, and {labels[-1]}."

    def _scan_status(self, mod: Module) -> tuple[str, str]:
        manual = self._manual_input_path(mod.key)
        if manual is not None:
            primary = self._primary_field(mod)
            if primary is None:
                return "Missing", "This module has no primary input."
            valid, reason = self._validate_field_input(mod, primary, manual)
            if valid:
                return "Found", f"Found: {_display_path(manual)}"
            return "Missing", f"Manual selection problem: {reason}"
        thread = self._scan_thread
        if thread is not None and thread.is_alive():
            return "Scanning", "Input scan is running; status will update shortly."
        raw = self.data_root_var.get().strip()
        if not raw or not Path(raw).is_dir():
            return (
                "Not scanned",
                "Select a data folder or choose this module's input manually.",
            )
        path = self._discovered.get(mod.key)
        if path is not None:
            return "Found", f"Found: {_display_path(path)}"
        return "Missing", self._missing_input_message(mod.key)

    def _module_selection_status(self, key: str) -> tuple[str, str]:
        return self._scan_status(MODULE_BY_KEY[key])

    def _module_selected_for_step2(self, key: str) -> bool:
        return bool(self.module_vars[key].get() and self._module_available(key))

    def _module_row_status(self, key: str) -> tuple[str, str]:
        status, detail = self._module_selection_status(key)
        if not self._module_selected_for_step2(key):
            return status, detail
        if status != "Not scanned":
            return status, detail
        if self._missing_required_input_labels(key):
            return "Missing", self._missing_input_message(key)
        return "Found", "Needs review."

    def _module_has_reviewable_inputs(self, key: str) -> bool:
        return self._module_available(key)

    def _module_review_inputs_complete(self, key: str) -> bool:
        """Whether the values the module needs beyond its input are present.

        There is no review button. A row reads Needs Review while something
        is missing and Found the moment it is filled in.
        """
        if self._module_row_status(key)[0] in {"Missing", "Not scanned", "Scanning"}:
            return False
        if key == "perfmon":
            return not self._perfmon_missing_field_ids()
        if key == "loop":
            return not self._loop_missing_date_ids()
        return True

    def _loop_missing_date_ids(self) -> set[str]:
        """The loop report needs both dates. Ids of the ones still blank."""
        return {
            _field_id("loop", field_key)
            for field_key in ("start_date", "end_date")
            if not self.date_field_vars[("loop", field_key)].get().strip()
        }

    def _module_reviewed(self, key: str) -> bool:
        return self._module_review_inputs_complete(key)

    def _module_pill(self, key: str, status: str) -> tuple[str, str, str]:
        label = STATUS_PILL_TEXT.get(status, status)
        fg, bg = S2_PILL_STYLES.get(status, S2_PILL_NEUTRAL)
        if status in {"Missing", "Scanning", "Not scanned"}:
            return label, fg, bg
        if not self._module_selected_for_step2(key):
            return label, fg, bg
        if status == "Found" and self._module_has_reviewable_inputs(key):
            if self._module_reviewed(key):
                return label, fg, bg
            return NEEDS_REVIEW_PILL, *S2_PILL_STYLES[NEEDS_REVIEW_PILL]
        return label, fg, bg

    def _modules_awaiting_review(self, keys) -> list[str]:
        pending = []
        for key in keys:
            status = self._module_row_status(key)[0]
            if self._module_pill(key, status)[0] == NEEDS_REVIEW_PILL:
                pending.append(key)
        return pending

    def _module_review_gate_message(self, key: str) -> str:
        name = self._module_display_name(key)
        if key == "perfmon":
            return f"{name}: complete the required hardware values in the step 2 details."
        if key == "loop":
            return (
                f"{name}: enter the Report Start Date and Report End Date in the "
                "step 2 details."
            )
        return f"{name}: complete the step 2 details."

    def _module_review_field_ids(self, key: str) -> set[str]:
        """Registry ids of the fields behind a module's Needs Review pill."""
        if key == "perfmon":
            return self._perfmon_missing_field_ids()
        if key == "loop":
            return self._loop_missing_date_ids()
        return set()

    def _on_module_review_value_changed(self, key: str) -> None:
        if self.step == 2:
            self._refresh_module_card_views([key])

    def _positive_int_or_blank(self, value: str) -> str:
        clean = str(value or "").strip()
        return clean if clean.isdigit() and int(clean) > 0 else ""

    def _selected_keys(self) -> list[str]:
        return [
            mod.key
            for mod in MODULES
            if self.module_vars[mod.key].get() and self._module_available(mod.key)
        ]

    def _on_manual_input_changed(self, key: str) -> None:
        for field in MODULE_BY_KEY[key].inputs_schema:
            self._clear_field_highlight(_field_id(key, field.key))
        if self.step == 2:
            self._refresh_module_card_views([key])

    # ------------------------------------------------------------------
    # Step 2: modules
    # ------------------------------------------------------------------

    def _build_step2(self) -> None:
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        presets = ctk.CTkFrame(frame, fg_color="transparent")
        presets.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        presets.grid_columnconfigure(3, weight=1)
        ctk.CTkLabel(
            presets, text="Presets", text_color=INK, font=(UI_FONT, 13, "bold")
        ).grid(row=0, column=0, sticky="w", padx=(4, 14))
        self._step2_pill_button(
            presets,
            "All Available",
            self._select_all_available,
            fg=PLUM,
            text_color=PAPER,
        ).grid(row=0, column=1, sticky="w", padx=(0, 8))
        clear_link = ctk.CTkLabel(
            presets,
            text="Clear",
            text_color=INK,
            font=(UI_FONT, 15, "bold"),
            cursor="hand2",
        )
        clear_link.grid(row=0, column=2, sticky="w", padx=(6, 0))
        clear_link.bind("<Button-1>", lambda _e: self._clear_modules())
        ctk.CTkLabel(
            presets,
            text="Tip: Click Details for more information about a module.",
            text_color=MUTED,
            font=(UI_FONT, 13),
            anchor="e",
        ).grid(row=0, column=3, sticky="e", padx=(18, 4))

        self.module_scroll = self._scrollable(frame)
        self.module_scroll.grid(row=1, column=0, sticky="nsew")
        self._render_module_cards()
        self._start_perfmon_detection(auto=True)

    def _select_all_available(self) -> None:
        for key in self.module_vars:
            self.module_vars[key].set(
                self._module_available(key)
                and self._module_selection_status(key)[0] == "Found"
            )
        if self.step == 2:
            self._refresh_module_card_views(tuple(self.module_vars))

    def _clear_modules(self) -> None:
        for var in self.module_vars.values():
            var.set(False)
        if self.step == 2:
            self._refresh_module_card_views(tuple(self.module_vars))

    def _render_module_cards(self) -> None:
        target = self.module_scroll
        self._module_card_controls.clear()
        for child in target.winfo_children():
            child.destroy()
        self._add_module_section(target, "Analysis Modules", [mod.key for mod in MODULES])
        expanded = self._expanded_module_key
        if expanded is not None:
            self._expanded_module_key = None
            self._expand_module_row(expanded)
        self._update_group_count()

    def _add_module_section(self, parent, title: str, keys: list[str]):
        card = ctk.CTkFrame(
            parent,
            fg_color=PAPER,
            corner_radius=12,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.pack(fill="x", padx=(0, 4), pady=(0, 14))
        header = ctk.CTkFrame(card, fg_color=CARD_HEADER, corner_radius=10)
        header.pack(fill="x", padx=2, pady=(2, 0))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header,
            text=title.upper(),
            text_color=INK,
            font=(self._condensed_family, 14, "bold"),
        ).grid(row=0, column=0, sticky="w", padx=18, pady=11)
        self._group_count_label = ctk.CTkLabel(
            header, text="", text_color=INK, font=(UI_FONT, 14)
        )
        self._group_count_label.grid(row=0, column=1, sticky="e", padx=(0, 18))
        ctk.CTkFrame(card, fg_color=HAIRLINE, height=1).pack(fill="x", padx=2)
        gap = self._S2_GAP
        head = self._step2_row_grid(card)
        for col, columnspan, text, anchor, padx in [
            (1, 1, "", "w", (15, 0)),
            (2, 1, "MODULE", "w", (0, 0)),
            (3, 1, "DESCRIPTION", "w", (0, gap)),
            (4, 2, "STATUS", "center", (0, gap)),
        ]:
            ctk.CTkLabel(
                head, text=text, text_color=INK, font=(UI_FONT, 13, "bold"), anchor=anchor
            ).grid(
                row=0, column=col, columnspan=columnspan, sticky="ew", padx=padx, pady=9
            )
        for key in keys:
            self._add_module_row(card, key)
        ctk.CTkFrame(card, fg_color="transparent", height=4).pack(fill="x")
        return card

    def _update_group_count(self) -> None:
        label = self._group_count_label
        if label is None:
            return
        selected = sum(1 for key in self.module_vars if self.module_vars[key].get())
        total = len(MODULES)
        text = (
            f"All {total} modules selected"
            if selected == total
            else f"{selected} of {total} modules selected"
        )
        try:
            if label.winfo_exists():
                label.configure(text=text)
        except TclError:
            pass

    def _step2_row_grid(self, parent):
        gap = self._S2_GAP
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=(0, 18))
        row.grid_columnconfigure(0, minsize=self._S2_ACCENT_MIN)
        row.grid_columnconfigure(1, minsize=self._S2_CHECK_MIN + gap)
        row.grid_columnconfigure(2, minsize=self._S2_NAME_MIN + gap)
        row.grid_columnconfigure(3, weight=1)
        row.grid_columnconfigure(4, minsize=self._S2_STATUS_MIN + gap)
        row.grid_columnconfigure(5, minsize=self._S2_LINK_MIN + gap)
        return row

    def _step2_fonts(self) -> dict[str, tkfont.Font]:
        fonts = self.__dict__.get("_s2_row_fonts")
        if fonts is None:
            fonts = {
                "name": tkfont.Font(family=UI_FONT, size=-15, weight="bold"),
                "desc": tkfont.Font(family=UI_FONT, size=-14),
                "pill": tkfont.Font(family=UI_FONT, size=-13, weight="bold"),
                "link": tkfont.Font(family=UI_FONT, size=-14, weight="bold"),
            }
            self.__dict__["_s2_row_fonts"] = fonts
        return fonts

    def _add_module_row(self, parent, key: str) -> None:
        status, _detail = self._module_row_status(key)
        available = self._module_available(key)
        if not available:
            self.module_vars[key].set(False)
        fonts = self._step2_fonts()
        gap = self._S2_GAP
        row_h = self._S2_ROW_HEIGHT
        mid = row_h // 2
        missing = status == "Missing" and available
        canvas = tk.Canvas(
            parent,
            height=row_h + (self._S2_MISSING_EXTRA if missing else 0),
            bd=0,
            highlightthickness=0,
            bg=PAPER,
        )
        canvas.pack(fill="x")
        controls: dict[str, object] = {"canvas": canvas, "status": status}
        controls["rule"] = canvas.create_line(2, 0, 2000, 0, fill=ROW_RULE)
        controls["accent"] = canvas.create_rectangle(
            0, 0, self._S2_ACCENT_MIN, row_h, fill="", outline=""
        )
        check_x = self._S2_ACCENT_MIN + 15
        check_y = mid - 9
        controls["checkbox_box"] = canvas.create_rectangle(
            check_x,
            check_y,
            check_x + 18,
            check_y + 18,
            width=1.5,
            tags=("checkbox_hit",),
        )
        controls["checkbox_check"] = canvas.create_line(
            check_x + 4,
            mid,
            check_x + 8,
            mid + 5,
            check_x + 15,
            mid - 6,
            width=2.2,
            capstyle="round",
            joinstyle="round",
            state="hidden",
            tags=("checkbox_hit",),
        )
        self._paint_module_checkbox(controls, key)
        name_x = self._S2_ACCENT_MIN + self._S2_CHECK_MIN + gap
        display_name = self._module_display_name(key)
        name_text = display_name if available else f"{display_name}  (Windows only)"
        canvas.create_text(
            name_x,
            mid,
            text=_truncate_for_width(name_text, fonts["name"], self._S2_NAME_MIN - 14),
            font=fonts["name"],
            fill=INK,
            anchor="w",
        )
        desc_x = name_x + self._S2_NAME_MIN + gap
        summary = MODULE_DETAILS.get(key, {}).get("summary", "")
        controls["desc"] = canvas.create_text(
            desc_x, mid, text=summary, font=fonts["desc"], fill=INK, anchor="w"
        )
        controls["desc_text"] = summary
        pill_label, pill_fg, pill_bg = self._module_pill(key, status)
        pill_w = fonts["pill"].measure(f"  {pill_label}  ")
        controls["pill_w"] = pill_w
        tags = ("review_pill_hit",) if pill_label == NEEDS_REVIEW_PILL else ()
        controls["pill_bg"] = canvas.create_image(
            0,
            mid,
            image=_pill_bg_photo(pill_bg, pill_bg, pill_w, 24),
            anchor="e",
            tags=tags,
        )
        controls["pill_text"] = canvas.create_text(
            0,
            mid,
            text=pill_label,
            font=fonts["pill"],
            fill=pill_fg,
            anchor="center",
            tags=tags,
        )
        controls["link"] = canvas.create_text(
            0,
            mid,
            text="Details",
            font=fonts["link"],
            fill=PLUM,
            anchor="e",
            tags=("link",),
        )
        controls["missing_item"] = canvas.create_text(
            desc_x,
            row_h + 14,
            text=self._missing_input_message(key),
            font=fonts["desc"],
            fill=CLAY,
            anchor="w",
            state="normal" if missing else "hidden",
        )
        controls["expansion_wrapper"] = None
        controls["expansion"] = None
        controls["expansion_built"] = False

        def _relayout(_event=None, c=canvas, controls=controls) -> None:
            try:
                width = c.winfo_width()
                if width <= 1:
                    return
                right = width - 18
                c.coords(controls["rule"], 2, 0, width - 2, 0)
                c.coords(controls["accent"], 0, 0, self._S2_ACCENT_MIN, c.winfo_height())
                c.coords(controls["link"], right, mid)
                pill_right = right - self._S2_LINK_MIN - gap
                c.coords(controls["pill_bg"], pill_right, mid)
                c.coords(controls["pill_text"], pill_right - controls["pill_w"] / 2, mid)
                status_start = pill_right - max(self._S2_STATUS_MIN, controls["pill_w"])
                desc_max = status_start - gap - desc_x
                c.itemconfigure(
                    controls["desc"],
                    text=_truncate_for_width(
                        controls["desc_text"], fonts["desc"], max(40, desc_max)
                    ),
                )
            except TclError:
                pass

        controls["relayout"] = _relayout
        canvas.bind("<Configure>", lambda _e: _relayout(), add="+")

        def _click(_event, k=key, c=canvas) -> None:
            hit = c.find_withtag("current")
            tags = c.gettags(hit[0]) if hit else ()
            if "checkbox_hit" in tags:
                if self._module_available(k):
                    self.module_vars[k].set(not self.module_vars[k].get())
                    self._on_module_selection_toggle(k)
            elif "link" in tags or "review_pill_hit" in tags:
                self._module_row_link_action(k)
            else:
                self._on_module_row_click(k)

        canvas.bind("<Button-1>", _click)
        for tag in ("checkbox_hit", "link", "review_pill_hit"):
            canvas.tag_bind(
                tag, "<Enter>", lambda _e, c=canvas: c.configure(cursor="hand2")
            )
            canvas.tag_bind(tag, "<Leave>", lambda _e, c=canvas: c.configure(cursor=""))
        self._module_card_controls[key] = controls

    def _paint_module_checkbox(self, controls: dict[str, object], key: str) -> None:
        canvas = controls.get("canvas")
        box = controls.get("checkbox_box")
        check = controls.get("checkbox_check")
        if canvas is None or box is None or check is None:
            return
        available = self._module_available(key)
        selected = bool(self.module_vars[key].get()) and available
        fill = PLUM if selected else PAPER
        outline = PLUM if selected else FIELD_BORDER
        if not available:
            fill, outline = FOG, FIELD_BORDER
        try:
            if canvas.winfo_exists():
                canvas.itemconfigure(box, fill=fill, outline=outline)
                canvas.itemconfigure(
                    check, fill=PAPER, state="normal" if selected else "hidden"
                )
        except TclError:
            pass

    def _on_module_selection_toggle(self, key: str) -> None:
        self._refresh_module_card_views([key])
        if (
            self.module_vars[key].get()
            and self._module_needs_step2_attention(key)
            and self._expanded_module_key != key
        ):
            self._expand_module_row(key)

    def _module_needs_step2_attention(self, key: str) -> bool:
        if not self._module_selected_for_step2(key):
            return False
        status, _detail = self._module_row_status(key)
        return (
            status == "Missing" or self._module_pill(key, status)[0] == NEEDS_REVIEW_PILL
        )

    def _on_module_row_click(self, key: str) -> None:
        if self._expanded_module_key == key:
            self._collapse_module_row()
        else:
            self._expand_module_row(key)

    def _module_row_link_action(self, key: str) -> None:
        self._on_module_row_click(key)

    def _set_module_row_link_text(self, key: str) -> None:
        controls = self._module_card_controls.get(key)
        if not controls:
            return
        try:
            text = "Close" if self._expanded_module_key == key else "Details"
            controls["canvas"].itemconfigure(controls["link"], text=text)
        except TclError:
            pass

    def _collapse_module_row(self) -> None:
        key = self._expanded_module_key
        self._expanded_module_key = None
        if key is None:
            return
        controls = self._module_card_controls.get(key)
        if controls:
            try:
                wrapper = controls.get("expansion_wrapper")
                if wrapper is not None and wrapper.winfo_exists():
                    wrapper.pack_forget()
                canvas = controls.get("canvas")
                if canvas is not None and canvas.winfo_exists():
                    canvas.configure(bg=PAPER)
                    canvas.itemconfigure(controls["accent"], fill="", outline="")
            except TclError:
                pass
        self._set_module_row_link_text(key)

    def _expand_module_row(self, key: str) -> None:
        previous = self._expanded_module_key
        if previous is not None and previous != key:
            self._collapse_module_row()
        controls = self._module_card_controls.get(key)
        if not controls:
            return
        canvas = controls.get("canvas")
        try:
            if canvas is None or not canvas.winfo_exists():
                return
            wrapper = controls.get("expansion_wrapper")
            if wrapper is None or not wrapper.winfo_exists():
                wrapper = ctk.CTkFrame(
                    canvas.master, fg_color=EXPANSION_TINT, corner_radius=0
                )
                wrapper.grid_columnconfigure(1, weight=1)
                ctk.CTkFrame(
                    wrapper,
                    fg_color=PLUM,
                    width=self._S2_ACCENT_MIN,
                    height=1,
                    corner_radius=0,
                ).grid(row=0, column=0, sticky="ns")
                expansion = ctk.CTkFrame(wrapper, fg_color="transparent", height=1)
                expansion.grid(
                    row=0,
                    column=1,
                    sticky="ew",
                    padx=(40 - self._S2_ACCENT_MIN, 18),
                    pady=(0, 14),
                )
                controls["expansion_wrapper"] = wrapper
                controls["expansion"] = expansion
                controls["expansion_built"] = False
            if not controls.get("expansion_built"):
                self._build_module_expansion(controls["expansion"], key)
                controls["expansion_built"] = True
            wrapper.pack(fill="x", after=canvas)
            canvas.configure(bg=EXPANSION_TINT)
            canvas.itemconfigure(controls["accent"], fill=PLUM, outline=PLUM)
        except TclError:
            return
        self._expanded_module_key = key
        self._refresh_module_card_state(key)

    def _rebuild_expansion(self, key: str) -> None:
        controls = self._module_card_controls.get(key)
        if not controls:
            return
        expansion = controls.get("expansion")
        try:
            if expansion is not None and expansion.winfo_exists():
                for child in expansion.winfo_children():
                    child.destroy()
                controls["expansion_built"] = False
                if self._expanded_module_key == key:
                    self._build_module_expansion(expansion, key)
                    controls["expansion_built"] = True
        except TclError:
            pass

    def _refresh_module_card_views(self, keys) -> None:
        for key in keys:
            self._refresh_module_card_state(key)
        self._update_group_count()

    def _refresh_module_card_state(self, key: str) -> None:
        controls = self._module_card_controls.get(key)
        if not controls:
            return
        status, _detail = self._module_row_status(key)
        controls["status"] = status
        canvas = controls.get("canvas")
        try:
            if canvas is None or not canvas.winfo_exists():
                return
            pill_label, pill_fg, pill_bg = self._module_pill(key, status)
            pill_w = self._step2_fonts()["pill"].measure(f"  {pill_label}  ")
            controls["pill_w"] = pill_w
            tags = ("review_pill_hit",) if pill_label == NEEDS_REVIEW_PILL else ()
            canvas.itemconfigure(
                controls["pill_bg"],
                image=_pill_bg_photo(pill_bg, pill_bg, pill_w, 24),
                tags=tags,
            )
            canvas.itemconfigure(
                controls["pill_text"], text=pill_label, fill=pill_fg, tags=tags
            )
            missing = status == "Missing" and self._module_available(key)
            canvas.itemconfigure(
                controls["missing_item"],
                text=self._missing_input_message(key),
                state="normal" if missing else "hidden",
            )
            wanted_h = self._S2_ROW_HEIGHT + (self._S2_MISSING_EXTRA if missing else 0)
            if int(canvas.cget("height")) != wanted_h:
                canvas.configure(height=wanted_h)
            relayout = controls.get("relayout")
            if relayout is not None:
                relayout()
        except TclError:
            return
        self._paint_module_checkbox(controls, key)
        self._set_module_row_link_text(key)

    # ------------------------------------------------------------------
    # Step 2 expansion content
    # ------------------------------------------------------------------

    def _build_module_expansion(self, frame, key: str) -> None:
        if not self._module_available(key):
            ctk.CTkLabel(
                frame,
                text="Not available on this OS. Needs a Windows-only tool (relog.exe).",
                text_color=INK,
                font=(UI_FONT, 15),
                wraplength=640,
                justify="left",
                anchor="w",
            ).pack(fill="x", pady=(2, 0))
            return
        self._add_expansion_details(frame, key)
        if key == "perfmon":
            self._add_perfmon_capture_panels(frame)
            self._add_perfmon_compact_dates(frame)
        else:
            self._add_module_input_rows(frame, key)
            self._add_date_tools(frame, key)

    def _add_expansion_details(self, frame, key: str) -> None:
        detail = MODULE_DETAILS.get(key, {})
        block = ctk.CTkFrame(
            frame, fg_color=PAPER, corner_radius=10, border_width=1, border_color=HAIRLINE
        )
        block.pack(fill="x", pady=(0, 12))
        inner = ctk.CTkFrame(block, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=14)
        inner.grid_columnconfigure((0, 2, 4), weight=1, uniform="exp_details")
        columns = [
            ("What it does", detail.get("does", "")),
            ("When to use it", detail.get("use", "")),
            ("Consultant action", detail.get("consultant", "")),
        ]
        body_labels = []
        for col, (title, body) in enumerate(columns):
            grid_col = col * 2
            cell = ctk.CTkFrame(inner, fg_color="transparent")
            cell.grid(row=0, column=grid_col, sticky="nsew")
            ctk.CTkLabel(
                cell, text=title, text_color=INK, font=(UI_FONT, 15, "bold"), anchor="w"
            ).pack(anchor="w")
            body_label = ctk.CTkLabel(
                cell,
                text=body,
                text_color=INK,
                font=(UI_FONT, 14),
                wraplength=250,
                justify="left",
                anchor="w",
            )
            body_label.pack(anchor="w", fill="x", pady=(2, 0))
            body_labels.append(body_label)
            if col < 2:
                tk.Frame(inner, bg=RUN_DETAIL_RULE, width=1).grid(
                    row=0, column=grid_col + 1, sticky="ns", padx=20
                )

        def fit_columns(_event=None) -> None:
            try:
                for label in body_labels:
                    if not label.winfo_exists():
                        return
                    width = label.master.winfo_width()
                    if width > 40 and int(label.cget("wraplength")) != width - 4:
                        label.configure(wraplength=width - 4)
            except TclError:
                pass

        inner.bind("<Configure>", fit_columns, add="+")

    def _add_module_input_rows(self, frame, key: str) -> None:
        mod = MODULE_BY_KEY[key]
        fields = self._browsable_input_fields(mod)
        if not fields:
            return
        block = ctk.CTkFrame(
            frame, fg_color=PAPER, corner_radius=10, border_width=1, border_color=HAIRLINE
        )
        block.pack(fill="x", pady=(0, 12))
        block.grid_columnconfigure(0, minsize=190)
        block.grid_columnconfigure(1, minsize=330)
        block.grid_columnconfigure(2, weight=1)
        block.grid_columnconfigure(3, minsize=84)
        block.grid_columnconfigure(4, minsize=100)
        for col, text in enumerate(("INPUT", "LOOKS FOR", "SELECTED", "STATE", "")):
            ctk.CTkLabel(
                block,
                text=text,
                text_color=INK,
                font=(UI_FONT, 12, "bold"),
                anchor="w" if col < 3 else "e",
            ).grid(
                row=0,
                column=col,
                sticky="ew",
                padx=(14 if col == 0 else 8, 14 if col == 4 else 8),
                pady=(12, 4),
            )
        for row_index, field in enumerate(fields, start=1):
            state, value = self._input_field_state(mod, field)
            pattern_items = self._field_pattern_items(mod, field)
            pattern = ", ".join(pattern_items) or "-"
            if len(pattern_items) > 4:
                pattern = f"{pattern_items[0]} and {len(pattern_items) - 1} more"
            cells = (
                (field.label, "bold", INK),
                (pattern, "normal", INK),
                (value, "normal", INK),
                (state, "bold", self._input_state_color(state)),
            )
            for col, (text, weight, color) in enumerate(cells):
                label = ctk.CTkLabel(
                    block,
                    text=text,
                    text_color=color,
                    font=(UI_FONT, 13, weight),
                    anchor="w" if col < 3 else "e",
                    justify="left",
                    wraplength=0,
                    width=1,
                )
                label.grid(
                    row=row_index,
                    column=col,
                    sticky="ew",
                    padx=(14 if col == 0 else 8, 8),
                    pady=5,
                )
                if col == 2:
                    self._left_ellipsize_label(label, text)
            button_text = "Change" if state == "Found" else "Choose"
            if field.kind in {"folder", "folder_optional"}:
                button_text = "Change folder" if state == "Found" else "Choose folder"
            button = self._step2_pill_button(
                block,
                button_text,
                lambda k=key, fk=field.key: self._browse_module_input_field(k, fk),
                fg=PAPER,
                text_color=PLUM,
            )
            button.configure(
                height=30,
                border_width=1,
                border_color=HAIRLINE,
                hover_color="#F4F7FB",
                font=(UI_FONT, 12, "bold"),
            )
            if not self.module_vars[key].get():
                button.configure(state="disabled")
            button.grid(row=row_index, column=4, sticky="e", padx=(8, 14), pady=5)

    def _field_pattern_items(self, mod: Module, field: InputField) -> list[str]:
        if field.key == mod.file_key:
            source = mod.file_patterns or ([mod.file_pattern] if mod.file_pattern else [])
            patterns = [str(p) for p in source]
        elif field.patterns:
            patterns = [str(p) for p in field.patterns]
        else:
            patterns = []
        if patterns:
            return patterns
        if field.extensions:
            return sorted(field.extensions)
        return []

    def _left_ellipsize_label(
        self, label, full_text: str, *, font_size: int = 13
    ) -> None:
        font = tkfont.Font(family=UI_FONT, size=-font_size)

        def fitted(width: int) -> str:
            if font.measure(full_text) <= width:
                return full_text
            low, high = 0, len(full_text)
            while low < high:
                mid = (low + high + 1) // 2
                if font.measure("..." + full_text[-mid:]) <= width:
                    low = mid
                else:
                    high = mid - 1
            return "..." + full_text[-low:] if low else "..."

        def apply(_event=None) -> None:
            try:
                if not label.winfo_exists():
                    return
                width = label.winfo_width()
                if width > 1:
                    text = fitted(width)
                    if label.cget("text") != text:
                        label.configure(text=text)
            except TclError:
                pass

        label.bind("<Configure>", apply, add="+")

    def _browse_module_input_field(self, key: str, field_key: str) -> None:
        mod = MODULE_BY_KEY[key]
        field = next((f for f in mod.inputs_schema if f.key == field_key), None)
        if field is None:
            return
        current = self._resolved_input_for_field(mod, field)
        initial = ""
        if current is not None:
            initial = str(current if current.is_dir() else current.parent)
        elif self.data_root_var.get().strip():
            initial = self.data_root_var.get().strip()
        if field.kind in {"folder", "folder_optional"}:
            path = filedialog.askdirectory(
                title=f"Choose the {field.label}", initialdir=initial or None
            )
        else:
            patterns = " ".join(f"*{ext}" for ext in sorted(field.extensions or {".*"}))
            path = filedialog.askopenfilename(
                title=f"Choose the {field.label}",
                filetypes=[(field.label, patterns), ("All Files", "*.*")],
                initialdir=initial or None,
            )
        if not path:
            return
        self.module_input_override_vars[(key, field_key)].set(_display_path(path))
        self.module_vars[key].set(True)
        if key == "perfmon" and field_key == mod.file_key:
            self._start_perfmon_detection(auto=True)
        elif key == "perfmon" and field_key == "capture2_blg_path":
            self._start_perfmon_detection(capture="perfmon2", auto=True)
        self._refresh_module_card_views([key])
        self._rebuild_expansion(key)

    def _add_date_tools(self, card, key: str) -> None:
        fields = [
            f for f in MODULE_BY_KEY[key].inputs_schema if f.kind == "datetime_optional"
        ]
        if not fields:
            return
        panel = ctk.CTkFrame(
            card, fg_color=PANEL, corner_radius=12, border_width=1, border_color=HAIRLINE
        )
        panel.pack(fill="x", pady=(0, 12))
        panel.grid_columnconfigure(tuple(range(len(fields))), weight=1)
        if key == "loop":
            title = "Client Loop report date range"
            help_text = (
                "Required. The export does not record collection start and end. Enter "
                "when the counters were started and stopped. The report shows this "
                "range."
            )
        else:
            title = "Collection date metadata"
            help_text = (
                "Optional. Use MM-DD-YYYY HH:MM for date and time values, or "
                "MM-DD-YYYY when only the date is known."
            )
        ctk.CTkLabel(panel, text=title, text_color=INK, font=(UI_FONT, 16, "bold")).grid(
            row=0, column=0, columnspan=len(fields), sticky="w", padx=14, pady=(12, 0)
        )
        help_label = ctk.CTkLabel(
            panel,
            text=help_text,
            text_color=INK,
            font=(UI_FONT, 14),
            wraplength=960,
            justify="left",
            anchor="w",
        )
        help_label.grid(
            row=1, column=0, columnspan=len(fields), sticky="ew", padx=14, pady=(2, 8)
        )
        panel.bind(
            "<Configure>",
            lambda e: help_label.configure(wraplength=max(280, e.width - 28)),
            add="+",
        )
        for col, field in enumerate(fields):
            field_card = ctk.CTkFrame(
                panel,
                fg_color=PAPER,
                corner_radius=8,
                border_width=1,
                border_color=HAIRLINE,
            )
            field_card.grid(row=2, column=col, sticky="ew", padx=8, pady=(0, 12))
            field_card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                field_card,
                text=field.label,
                text_color=INK,
                font=(UI_FONT, 14, "bold"),
                wraplength=240,
                justify="left",
                anchor="w",
            ).grid(row=0, column=0, columnspan=2, sticky="ew", padx=12, pady=(10, 0))
            var = self.date_field_vars[(key, field.key)]
            entry = ctk.CTkEntry(
                field_card,
                textvariable=var,
                placeholder_text="MM-DD-YYYY",
                height=36,
                corner_radius=8,
                border_width=1,
                border_color=HAIRLINE,
                fg_color=PAPER,
                text_color=INK,
                font=(UI_FONT, 14),
            )
            entry.grid(row=1, column=0, sticky="ew", padx=(10, 4), pady=(6, 2))
            self._register_field(_field_id(key, field.key), entry, HAIRLINE)
            ctk.CTkButton(
                field_card,
                text="",
                image=_calendar_icon(),
                width=42,
                height=36,
                corner_radius=8,
                fg_color=PLUM,
                hover_color="#0B4FC0",
                command=lambda k=key, fk=field.key, e=entry: self._open_date_picker(
                    k, fk, e
                ),
            ).grid(row=1, column=1, sticky="e", padx=(0, 10), pady=(6, 2))
            ctk.CTkLabel(
                field_card,
                text="Required" if key == "loop" else "Optional",
                text_color=MUTED,
                font=(UI_FONT, 12),
                anchor="w",
            ).grid(row=2, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))

    def _open_date_picker(self, module_key: str, field_key: str, anchor_widget) -> None:
        var = self.date_field_vars.get((module_key, field_key))
        if var is None:
            return
        current = self._parse_date_field_value(var.get())

        def commit(picked: date) -> None:
            if current is None or not (current.hour or current.minute or current.second):
                var.set(picked.strftime("%m-%d-%Y"))
                return
            combined = datetime(
                picked.year,
                picked.month,
                picked.day,
                current.hour,
                current.minute,
                current.second,
            )
            var.set(
                combined.strftime(
                    "%m-%d-%Y %H:%M:%S" if combined.second else "%m-%d-%Y %H:%M"
                )
            )

        DatePopup(
            self,
            anchor_widget,
            current.date() if current else None,
            on_pick=commit,
            on_clear=lambda: var.set(""),
        )

    def _parse_date_field_value(self, raw: str) -> datetime | None:
        raw = (raw or "").strip()
        if not raw:
            return None
        for fmt in self._DATE_PARSE_FORMATS:
            try:
                return datetime.strptime(raw, fmt)
            except ValueError:
                continue
        return None

    # ------------------------------------------------------------------
    # PerfMon panels
    # ------------------------------------------------------------------

    def _perfmon_input_path(self) -> Path | None:
        mod = MODULE_BY_KEY["perfmon"]
        return self._resolved_input_for_field(mod, self._primary_field(mod))

    def _perfmon_capture2_path(self) -> Path | None:
        return self._manual_field_input_path("perfmon", "capture2_blg_path")

    def _add_perfmon_capture_panels(self, parent) -> None:
        wrap = ctk.CTkFrame(parent, fg_color="transparent")
        wrap.pack(fill="x", pady=(0, 12))
        wrap.grid_columnconfigure((0, 1), weight=1, uniform="perfmon_capture")

        primary = ctk.CTkFrame(
            wrap, fg_color=PAPER, corner_radius=12, border_width=1, border_color=HAIRLINE
        )
        primary.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        head = ctk.CTkFrame(primary, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(12, 0))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head,
            text="Capture 1 - BigFix Root Server",
            text_color=INK,
            font=(UI_FONT, 15, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        status, _detail = self._module_selection_status("perfmon")
        ctk.CTkLabel(
            head,
            text=STATUS_PILL_TEXT.get(status, status),
            text_color={"Found": MOSS, "Scanning": PLUM}.get(status, CLAY),
            font=(UI_FONT, 13, "bold"),
        ).grid(row=0, column=1, sticky="e")
        blg = self._perfmon_input_path()
        self._path_entry(
            primary, str(blg) if blg else "", placeholder="No BLG selected yet."
        ).pack(fill="x", padx=14, pady=(8, 0))
        self._add_perfmon_hardware_controls(
            primary,
            "perfmon",
            self.perfmon_processors_var,
            self.perfmon_disks_var,
            self.perfmon_memory_var,
            self.perfmon_vm_var,
        )
        ctk.CTkLabel(
            primary,
            text="CPUs and disks are detected from the BLG. RAM is entered manually.",
            text_color=INK,
            font=(UI_FONT, 15),
            wraplength=320,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(8, 0))
        self._add_perfmon_links(
            primary,
            [
                ("Re-detect", lambda: self._start_perfmon_detection()),
                (
                    "Browse",
                    lambda: self._browse_module_input_field("perfmon", "blg_path"),
                ),
            ],
        )

        capture2 = self._perfmon_capture2_path()
        secondary = ctk.CTkFrame(
            wrap,
            fg_color=PAPER,
            corner_radius=12,
            border_width=1,
            border_color=HAIRLINE if capture2 else FIELD_BORDER,
        )
        secondary.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        head2 = ctk.CTkFrame(secondary, fg_color="transparent")
        head2.pack(fill="x", padx=14, pady=(12, 0))
        head2.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            head2,
            text="Capture 2 - SQL Server host",
            text_color=INK,
            font=(UI_FONT, 15, "bold"),
            anchor="w",
        ).grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(
            head2,
            text="selected" if capture2 else "optional",
            text_color=INK,
            font=(UI_FONT, 13),
        ).grid(row=0, column=1, sticky="e")
        entry = ctk.CTkEntry(
            secondary,
            textvariable=self.module_input_override_vars[
                ("perfmon", "capture2_blg_path")
            ],
            placeholder_text="Add the SQL host's BLG file.",
            height=34,
            corner_radius=8,
            border_width=1,
            border_color=FIELD_BORDER,
            fg_color=PAPER,
            text_color=INK,
            font=(UI_FONT, 14),
        )
        entry.pack(fill="x", padx=14, pady=(8, 0))
        self._register_field(_field_id("perfmon", "capture2_blg_path"), entry)
        self._add_perfmon_hardware_controls(
            secondary,
            "perfmon2",
            self.perfmon2_processors_var,
            self.perfmon2_disks_var,
            self.perfmon2_memory_var,
            self.perfmon2_vm_var,
        )
        ctk.CTkLabel(
            secondary,
            text="CPUs and disks are detected once a file is chosen. RAM is entered manually.",
            text_color=INK,
            font=(UI_FONT, 15),
            wraplength=320,
            justify="left",
            anchor="w",
        ).pack(fill="x", padx=14, pady=(8, 0))
        links: list[tuple[str, object]] = [
            ("Re-detect", lambda: self._start_perfmon_detection(capture="perfmon2")),
            (
                "Browse",
                lambda: self._browse_module_input_field("perfmon", "capture2_blg_path"),
            ),
        ]
        if capture2:
            links.append(("Remove", self._remove_capture2))
        self._add_perfmon_links(secondary, links)

    def _add_perfmon_hardware_controls(
        self, parent, capture: str, processors_var, disks_var, memory_var, vm_var
    ) -> None:
        prefix = "" if capture == "perfmon" else "capture2_"
        hw1 = ctk.CTkFrame(parent, fg_color="transparent")
        hw1.pack(fill="x", padx=14, pady=(10, 0))
        for label_text, var, field_key in (
            ("CPUs", processors_var, "logical_processors"),
            ("Disks", disks_var, "physical_disks"),
        ):
            ctk.CTkLabel(hw1, text=label_text, text_color=INK, font=(UI_FONT, 15)).pack(
                side="left", padx=(0, 6)
            )
            entry = ctk.CTkEntry(
                hw1,
                textvariable=var,
                width=56,
                height=32,
                corner_radius=8,
                border_width=1,
                border_color=HAIRLINE,
                fg_color=PAPER,
                text_color=INK,
                font=(UI_FONT, 15),
            )
            entry.pack(side="left", padx=(0, 14))
            self._register_field(
                _field_id("perfmon", prefix + field_key), entry, HAIRLINE
            )
        hw2 = ctk.CTkFrame(parent, fg_color="transparent")
        hw2.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(hw2, text="RAM", text_color=INK, font=(UI_FONT, 15)).pack(
            side="left", padx=(0, 6)
        )
        entry = ctk.CTkEntry(
            hw2,
            textvariable=memory_var,
            width=56,
            height=32,
            corner_radius=8,
            border_width=1,
            border_color=HAIRLINE,
            fg_color=PAPER,
            text_color=INK,
            font=(UI_FONT, 15),
        )
        entry.pack(side="left")
        self._register_field(
            _field_id("perfmon", prefix + "physical_memory_gb"), entry, HAIRLINE
        )
        ctk.CTkLabel(hw2, text="GB", text_color=INK, font=(UI_FONT, 15)).pack(
            side="left", padx=(6, 14)
        )
        ctk.CTkCheckBox(
            hw2,
            text="Virtual machine",
            variable=vm_var,
            font=(UI_FONT, 15),
            text_color=INK,
            fg_color=PLUM,
            hover_color="#0B4FC0",
            checkbox_width=18,
            checkbox_height=18,
            corner_radius=4,
            border_width=1.5,
            border_color=FIELD_BORDER,
        ).pack(side="left")

    def _add_perfmon_links(self, parent, specs: list[tuple[str, object]]) -> None:
        links = ctk.CTkFrame(parent, fg_color="transparent")
        links.pack(fill="x", padx=8, pady=(4, 10))
        for link_text, link_cmd in specs:
            ctk.CTkButton(
                links,
                text=link_text,
                command=link_cmd,
                fg_color="transparent",
                hover_color=PANEL,
                text_color=LINK_BLUE,
                width=80,
                height=28,
                corner_radius=8,
                font=(UI_FONT, 15, "bold"),
            ).pack(side="left", padx=(0, 6))

    def _add_perfmon_compact_dates(self, parent) -> None:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(8, 12))
        for label_text, field_key in (
            ("Start", "collection_start"),
            ("End", "collection_end"),
        ):
            var = self.date_field_vars[("perfmon", field_key)]
            ctk.CTkLabel(row, text=label_text, text_color=INK, font=(UI_FONT, 15)).pack(
                side="left", padx=(0, 6)
            )
            entry = ctk.CTkEntry(
                row,
                textvariable=var,
                width=150,
                height=32,
                corner_radius=8,
                border_width=1,
                border_color=FIELD_BORDER,
                fg_color=PAPER,
                text_color=INK,
                font=(UI_FONT, 14),
            )
            entry.pack(side="left")
            self._register_field(_field_id("perfmon", field_key), entry)
            ctk.CTkButton(
                row,
                text="",
                image=_calendar_icon(),
                width=36,
                height=32,
                corner_radius=8,
                fg_color=PLUM,
                hover_color="#0B4FC0",
                command=lambda fk=field_key, e=entry: self._open_date_picker(
                    "perfmon", fk, e
                ),
            ).pack(side="left", padx=(4, 18))

    def _remove_capture2(self) -> None:
        self.module_input_override_vars[("perfmon", "capture2_blg_path")].set("")
        for var in (
            self.perfmon2_processors_var,
            self.perfmon2_disks_var,
            self.perfmon2_memory_var,
        ):
            var.set("")
        self.perfmon2_vm_var.set(False)
        self._rebuild_expansion("perfmon")

    def _on_date_value_changed(self, key: str, field_id: str) -> None:
        self._clear_field_highlight(field_id)
        self._on_module_review_value_changed(key)

    def _on_perfmon_value_changed(self, field_id: str) -> None:
        self._clear_field_highlight(field_id)
        self._on_module_review_value_changed("perfmon")

    def _perfmon_missing_field_ids(self) -> set[str]:
        ids: set[str] = set()
        primary = (
            (self.perfmon_processors_var, "perfmon:logical_processors"),
            (self.perfmon_disks_var, "perfmon:physical_disks"),
            (self.perfmon_memory_var, "perfmon:physical_memory_gb"),
        )
        for var, fid in primary:
            if not self._positive_int_or_blank(var.get()):
                ids.add(fid)
        if self._perfmon_capture2_path() is not None:
            secondary = (
                (self.perfmon2_processors_var, "perfmon:capture2_logical_processors"),
                (self.perfmon2_disks_var, "perfmon:capture2_physical_disks"),
                (self.perfmon2_memory_var, "perfmon:capture2_physical_memory_gb"),
            )
            for var, fid in secondary:
                if not self._positive_int_or_blank(var.get()):
                    ids.add(fid)
        return ids

    def _start_perfmon_detection(
        self, *, capture: str = "perfmon", auto: bool = False
    ) -> None:
        if not IS_WINDOWS:
            return
        blg = (
            self._perfmon_input_path()
            if capture == "perfmon"
            else self._perfmon_capture2_path()
        )
        if blg is None or not blg.is_file():
            return
        if capture == "perfmon":
            processors_var, disks_var = (
                self.perfmon_processors_var,
                self.perfmon_disks_var,
            )
        else:
            processors_var, disks_var = (
                self.perfmon2_processors_var,
                self.perfmon2_disks_var,
            )
        source = blg.resolve()
        if (
            auto
            and self._perfmon_detect_sources.get(capture) == source
            and (processors_var.get().strip() or disks_var.get().strip())
        ):
            return
        self._perfmon_detect_sources[capture] = source
        self._perfmon_detect_tokens[capture] += 1
        token = self._perfmon_detect_tokens[capture]
        processors_var.set(DETECTING)
        disks_var.set(DETECTING)

        def worker() -> None:
            try:
                lines = relog_query_lines(blg)
                procs, disks, _volumes = detect_hardware_from_blg(blg, lines)
                begin, end = detect_perfmon_window(lines)
            except Exception:
                procs, disks, begin, end = 0, 0, "", ""
            self._post(
                lambda: self._apply_perfmon_detection(
                    capture, token, procs, disks, begin, end
                )
            )

        threading.Thread(target=worker, daemon=True).start()

    def _apply_perfmon_detection(
        self, capture: str, token: int, procs: int, disks: int, begin: str, end: str
    ) -> None:
        if token != self._perfmon_detect_tokens[capture]:
            return
        source = (
            self._perfmon_input_path()
            if capture == "perfmon"
            else self._perfmon_capture2_path()
        )
        if source is None or source.resolve() != self._perfmon_detect_sources.get(
            capture
        ):
            self._perfmon_detect_sources.pop(capture, None)
            return
        if capture == "perfmon":
            processors_var, disks_var = (
                self.perfmon_processors_var,
                self.perfmon_disks_var,
            )
        else:
            processors_var, disks_var = (
                self.perfmon2_processors_var,
                self.perfmon2_disks_var,
            )
        processors_var.set(str(procs) if procs > 0 else "")
        disks_var.set(str(disks) if disks > 0 else "")
        if capture == "perfmon":
            for field_key, value in (
                ("collection_start", begin),
                ("collection_end", end),
            ):
                var = self.date_field_vars[("perfmon", field_key)]
                if value and not var.get().strip():
                    try:
                        var.set(_parse_optional_datetime(value, field_key))
                    except ValueError:
                        var.set(value)
        self._on_module_review_value_changed("perfmon")

    # ------------------------------------------------------------------
    # Validation and config
    # ------------------------------------------------------------------

    def _validate_step1(self) -> tuple[list[str], set[str]]:
        errors: list[str] = []
        bad: set[str] = set()
        data_root_text = self.data_root_var.get().strip()
        if data_root_text and not Path(data_root_text).is_dir():
            errors.append("Data folder must be a valid directory if provided.")
            bad.add("data_root")
        if not self.run_name_var.get().strip():
            errors.append("Run name is required.")
            bad.add("run_name")
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
        return errors, bad

    def _validate_step2(self, bad_fields: set[str] | None = None) -> list[str]:
        errors: list[str] = []
        selected = self._selected_keys()
        if not selected:
            errors.append("Select at least one module.")
        for key in self._modules_awaiting_review(selected):
            errors.append(self._module_review_gate_message(key))
            if bad_fields is not None:
                bad_fields |= self._module_review_field_ids(key)
        for key in selected:
            status, detail = self._module_row_status(key)
            if status in {"Missing", "Not scanned", "Scanning"}:
                errors.append(f"{self._module_display_name(key)}: {detail}")
            mod = MODULE_BY_KEY[key]
            for field in self._browsable_input_fields(mod):
                manual = self._manual_field_input_path(key, field.key)
                if manual is None:
                    continue
                valid, reason = self._validate_field_input(mod, field, manual)
                if not valid:
                    errors.append(f"{mod.label}: {field.label}: {reason}")
        if "perfmon" in selected:
            capture2 = self._perfmon_capture2_path()
            primary = self._perfmon_input_path()
            capture2_id = _field_id("perfmon", "capture2_blg_path")
            if capture2 is not None:
                if not capture2.is_file() or capture2.suffix.lower() != ".blg":
                    errors.append(
                        "Capture 2 PerfMon input must be an existing .blg file."
                    )
                    if bad_fields is not None:
                        bad_fields.add(capture2_id)
                elif primary is not None and os.path.normcase(
                    str(capture2.resolve())
                ) == (os.path.normcase(str(primary.resolve()))):
                    errors.append(
                        "Capture 2 PerfMon BLG must be different from Capture 1."
                    )
                    if bad_fields is not None:
                        bad_fields.add(capture2_id)
            hardware = (
                (
                    self.perfmon_processors_var,
                    "Logical processors",
                    "perfmon:logical_processors",
                ),
                (self.perfmon_disks_var, "Physical disks", "perfmon:physical_disks"),
                (
                    self.perfmon_memory_var,
                    "Physical Memory (GB)",
                    "perfmon:physical_memory_gb",
                ),
            )
            for var, label, fid in hardware:
                value = var.get().strip()
                if value == DETECTING:
                    errors.append(
                        f"Perfmon Infrastructure Analysis: wait for {label} detection to "
                        "finish, or type the value."
                    )
                elif value and not self._positive_int_or_blank(value):
                    errors.append(f"PerfMon {label} must be a positive whole number.")
                    if bad_fields is not None:
                        bad_fields.add(fid)
        for key in selected:
            for field in MODULE_BY_KEY[key].inputs_schema:
                if field.kind != "datetime_optional":
                    continue
                var = self.date_field_vars[(key, field.key)]
                value = var.get().strip()
                if not value:
                    continue
                try:
                    var.set(_parse_optional_datetime(value, field.label))
                except ValueError:
                    errors.append(
                        f"{MODULE_BY_KEY[key].label}: {field.label} must use "
                        "MM-DD-YYYY HH:MM or MM-DD-YYYY."
                    )
                    if bad_fields is not None:
                        bad_fields.add(_field_id(key, field.key))
        return errors

    def _build_raw_inputs(self, mod: Module) -> dict:
        values: dict[str, object] = {}
        perfmon_ints = {
            "logical_processors": self.perfmon_processors_var,
            "physical_disks": self.perfmon_disks_var,
            "physical_memory_gb": self.perfmon_memory_var,
            "capture2_logical_processors": self.perfmon2_processors_var,
            "capture2_physical_disks": self.perfmon2_disks_var,
            "capture2_physical_memory_gb": self.perfmon2_memory_var,
        }
        perfmon_bools = {
            "is_vm": self.perfmon_vm_var,
            "capture2_is_vm": self.perfmon2_vm_var,
        }
        for field in mod.inputs_schema:
            if field.kind == "datetime_optional":
                values[field.key] = (
                    self.date_field_vars[(mod.key, field.key)].get().strip()
                )
            elif mod.key == "perfmon" and field.key in perfmon_ints:
                values[field.key] = self._positive_int_or_blank(
                    perfmon_ints[field.key].get()
                )
            elif mod.key == "perfmon" and field.key in perfmon_bools:
                values[field.key] = bool(perfmon_bools[field.key].get())
            elif field.kind in BROWSABLE_INPUT_KINDS:
                path = self._resolved_input_for_field(mod, field)
                values[field.key] = _display_path(path) if path else ""
            else:
                values[field.key] = ""
        return values

    def _manual_inputs_by_module(self, keys: list[str]) -> dict[str, dict[str, str]]:
        manual: dict[str, dict[str, str]] = {}
        for key in keys:
            fields: dict[str, str] = {}
            for field in MODULE_BY_KEY[key].inputs_schema:
                if field.kind not in BROWSABLE_INPUT_KINDS:
                    continue
                path = self._manual_field_input_path(key, field.key)
                if path is not None:
                    fields[field.key] = _display_path(path)
            if fields:
                manual[key] = fields
        return manual

    def _build_config(self) -> dict:
        selected = self._selected_keys()
        return {
            "run_name": self.run_name_var.get().strip(),
            "output_folder": _display_path(self.output_folder_var.get())
            or DEFAULT_WORK_DIR,
            "data_root": _display_path(self.data_root_var.get()),
            "modules": selected,
            "inputs": {
                key: self._build_raw_inputs(MODULE_BY_KEY[key]) for key in selected
            },
            # Inputs chosen by hand. The engine never replaces these with a
            # discovered path, wherever they live.
            "manual_inputs": self._manual_inputs_by_module(selected),
        }

    # ------------------------------------------------------------------
    # Step 3: run
    # ------------------------------------------------------------------

    def _build_step3(self) -> None:
        frame = ctk.CTkFrame(self.content, fg_color="transparent")
        frame.grid(row=0, column=0, sticky="nsew")
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)
        selected = self._selected_keys()
        self._progress_order = list(selected)
        self._progress_completed = set()
        self._progress_current = None
        self._module_run_started = {}
        self._canvas_status_pills = {}

        legend_row = ctk.CTkFrame(frame, fg_color="transparent")
        legend_row.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        ctk.CTkLabel(
            legend_row, text="Outputs", text_color=INK, font=(UI_FONT, 13, "bold")
        ).pack(side="left", padx=(0, 16))
        for index, term in enumerate(OUTPUT_TERM_ORDER):
            entry = ctk.CTkFrame(legend_row, fg_color="transparent")
            entry.pack(side="left", padx=(0 if index == 0 else 16, 0))
            ctk.CTkLabel(entry, text="", image=_table_icon(term, 24)).pack(side="left")
            ctk.CTkLabel(entry, text=term, text_color=INK, font=(UI_FONT, 14)).pack(
                side="left", padx=(6, 0)
            )

        details_holder = ctk.CTkFrame(frame, fg_color="transparent")
        details_holder.grid(row=1, column=0, sticky="ew")
        self._add_run_details_strip(details_holder)

        tables_holder = ctk.CTkFrame(frame, fg_color="transparent", height=1)
        tables_holder.grid(row=2, column=0, sticky="nsew")
        tables_holder.grid_columnconfigure(0, weight=1)
        tables = self._scrollable(tables_holder)
        tables.grid(row=0, column=0, sticky="new")

        def cap_tables_height(_event=None) -> None:
            try:
                available = tables_holder.winfo_height()
                wanted = min(520, available)
                if available > 1 and int(tables.cget("height")) != wanted:
                    tables.configure(height=wanted)
            except (TclError, ValueError):
                pass

        tables_holder.bind("<Configure>", cap_tables_height, add="+")
        if selected:
            card = self._add_module_status_table(tables, "Analysis Modules", selected)
            for key in selected:
                self._add_step3_canvas_row(card, key)
            ctk.CTkFrame(card, fg_color="transparent", height=4).pack(fill="x")
        self._add_unselected_row(tables, selected)

        strip_holder = ctk.CTkFrame(frame, fg_color="transparent")
        strip_holder.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        card = ctk.CTkFrame(
            strip_holder,
            fg_color=PAPER,
            corner_radius=12,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.pack(fill="x", padx=(0, 4), pady=(0, 14))
        self._populate_run_action_strip(card, selected)
        if self._build_running:
            self._restore_progress_view()

    def _add_run_details_strip(self, parent) -> None:
        card = self._add_form_section(parent, "Run Details")
        header = card.winfo_children()[0]
        ctk.CTkButton(
            header,
            text="Change on earlier steps",
            command=lambda: self._show_step(1),
            fg_color="transparent",
            hover_color=PANEL,
            text_color=PLUM,
            height=26,
            corner_radius=8,
            font=(UI_FONT, 14, "bold"),
        ).pack(side="right", padx=(0, 10))
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=18, pady=14)
        folder = _display_path(self.output_folder_var.get()) or "-"
        selected = self._selected_keys()
        selected_names = [self._module_display_name(key) for key in selected]
        not_selected = [
            self._module_display_name(mod.key)
            for mod in MODULES
            if mod.key not in selected
        ]
        modules_text = ", ".join(selected_names) or "-"
        if not_selected:
            modules_text += "\nNot selected: " + ", ".join(not_selected)
        values = [
            ("Run Name", self.run_name_var.get().strip() or "-"),
            ("Modules", modules_text),
            ("Output Folder", folder),
        ]
        for col, (label_text, value) in enumerate(values):
            grid_col = col * 2
            is_last = col == len(values) - 1
            row.grid_columnconfigure(grid_col, weight=1 if is_last else 0)
            if col:
                tk.Frame(row, bg=RUN_DETAIL_RULE, width=1).grid(
                    row=0, column=grid_col - 1, sticky="ns", padx=24
                )
            cell = ctk.CTkFrame(row, fg_color="transparent")
            cell.grid(row=0, column=grid_col, sticky="nsew" if is_last else "nw")
            if is_last:
                cell.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(
                cell,
                text=label_text,
                text_color=INK,
                font=(UI_FONT, 15, "bold"),
                anchor="w",
            ).pack(anchor="w")
            value_label = ctk.CTkLabel(
                cell,
                text=value,
                text_color=INK,
                font=(UI_FONT, 14),
                anchor="w",
                justify="left",
                **({"width": 1} if is_last else {}),
            )
            if is_last:
                value_label.pack(anchor="w", fill="x", pady=(4, 0))
                if folder != "-":
                    self._left_ellipsize_label(value_label, folder, font_size=14)
            else:
                value_label.pack(anchor="w", pady=(4, 0))

    def _step3_row_grid(self, parent):
        row = ctk.CTkFrame(parent, fg_color="transparent", height=1)
        row.pack(fill="x", padx=18)
        row.grid_columnconfigure(0, minsize=self._S3_MODULE_MIN)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, minsize=self._S3_OUTPUTS_MIN)
        row.grid_columnconfigure(3, minsize=self._S3_STATUS_MIN)
        return row

    def _add_module_status_table(self, parent, title: str, keys: list[str]):
        card = self._add_form_section(parent, title)
        header = card.winfo_children()[0]
        count = len(keys)
        ctk.CTkLabel(
            header,
            text=f"{count} module{'s' if count != 1 else ''} selected",
            text_color=INK,
            font=(UI_FONT, 14),
        ).pack(side="right", padx=(0, 14))
        head = self._step3_row_grid(card)
        headers = [
            ("Module", "w"),
            ("Description", "w"),
            ("Outputs", "e"),
            ("Build Status", "e"),
        ]
        for col, (text, anchor) in enumerate(headers):
            ctk.CTkLabel(
                head, text=text, text_color=INK, font=(UI_FONT, 14, "bold"), anchor=anchor
            ).grid(
                row=0,
                column=col,
                sticky="ew",
                padx=(0, 0 if col == 3 else self._S3_GAP),
                pady=10,
            )
        return card

    def _step3_fonts(self) -> dict[str, tkfont.Font]:
        fonts = self.__dict__.get("_s3_row_fonts")
        if fonts is None:
            fonts = {
                "name": tkfont.Font(family=UI_FONT, size=-15, weight="bold"),
                "desc": tkfont.Font(family=UI_FONT, size=-15),
                "pill": tkfont.Font(family=UI_FONT, size=-13, weight="bold"),
            }
            self.__dict__["_s3_row_fonts"] = fonts
        return fonts

    def _module_output_terms(self, key: str) -> list[str]:
        raw = (MODULE_BY_KEY[key].outputs or "").split(",")
        terms = [part.strip() for part in raw if part.strip() in OUTPUT_TERM_ORDER]
        return sorted(set(terms), key=OUTPUT_TERM_ORDER.index)

    def _add_step3_canvas_row(self, card, key: str) -> None:
        fonts = self._step3_fonts()
        row_h = self._S3_ROW_HEIGHT
        gap = self._S3_GAP
        canvas = tk.Canvas(card, height=row_h, bd=0, highlightthickness=0, bg=PAPER)
        canvas.pack(fill="x", padx=2)
        rule = canvas.create_line(0, 0, 2000, 0, fill=ROW_RULE)
        inset = 16
        mid = row_h // 2
        canvas.create_image(inset, mid, image=_canvas_icon("check_tile", 16), anchor="w")
        name_max = self._S3_MODULE_MIN - gap - 13
        canvas.create_text(
            inset + 23,
            mid,
            text=_truncate_for_width(
                self._module_display_name(key), fonts["name"], name_max
            ),
            font=fonts["name"],
            fill=INK,
            anchor="w",
        )
        desc_text = MODULE_DETAILS.get(key, {}).get("summary", "")
        desc_item = canvas.create_text(
            inset + self._S3_MODULE_MIN,
            mid,
            text=desc_text,
            font=fonts["desc"],
            fill=INK,
            anchor="w",
        )
        badge_items = [
            canvas.create_image(0, mid, image=_canvas_icon(term, 24), anchor="e")
            for term in self._module_output_terms(key)
        ]
        pill_w, pill_h = 118, 24
        style = S3_STATUS_PILL_STYLES["not_started"]
        pill_bg_item = canvas.create_image(
            0, mid, image=_pill_bg_photo(style[0], style[1], pill_w, pill_h), anchor="e"
        )
        pill_text_item = canvas.create_text(
            0, mid, text="Not started", font=fonts["pill"], fill=style[2], anchor="center"
        )
        self._canvas_status_pills[key] = {
            "canvas": canvas,
            "bg": pill_bg_item,
            "text": pill_text_item,
            "width": pill_w,
            "height": pill_h,
        }

        def _relayout(_event=None, c=canvas) -> None:
            try:
                width = c.winfo_width()
                if width <= 1:
                    return
                right = width - inset
                c.coords(rule, 0, 0, width, 0)
                c.coords(pill_bg_item, right, mid)
                c.coords(pill_text_item, right - pill_w / 2, mid)
                badge_right = right - pill_w - gap
                x = badge_right
                for item in reversed(badge_items):
                    c.coords(item, x, mid)
                    x -= 30
                desc_max = (
                    badge_right - self._S3_OUTPUTS_MIN - (inset + self._S3_MODULE_MIN)
                )
                c.itemconfigure(
                    desc_item,
                    text=_truncate_for_width(
                        desc_text, fonts["desc"], max(40, desc_max + 90)
                    ),
                )
            except TclError:
                pass

        canvas.bind("<Configure>", _relayout, add="+")

    def _add_unselected_row(self, parent, selected: list[str]) -> None:
        unselected = [mod.key for mod in MODULES if mod.key not in set(selected)]
        if not unselected:
            return
        card = ctk.CTkFrame(
            parent,
            fg_color=PAPER,
            corner_radius=12,
            border_width=1,
            border_color=HAIRLINE,
        )
        card.pack(fill="x", padx=(0, 4), pady=(0, 14))
        head = ctk.CTkFrame(card, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=10)
        head.grid_columnconfigure(0, weight=1)
        count = len(unselected)
        title_holder = ctk.CTkFrame(head, fg_color="transparent")
        title_holder.grid(row=0, column=0, sticky="w")
        caret = ctk.CTkLabel(
            title_holder,
            text="",
            image=_caret_icon(False),
            width=12,
            height=12,
            fg_color="transparent",
        )
        caret.grid(row=0, column=0, padx=(0, 8))
        title = ctk.CTkLabel(
            title_holder,
            text=f"{count} module{'s' if count != 1 else ''} {'were' if count != 1 else 'was'} not selected",
            text_color=INK,
            font=(UI_FONT, 15, "bold"),
            anchor="w",
        )
        title.grid(row=0, column=1, sticky="w")
        body = ctk.CTkFrame(card, fg_color="transparent")

        def reason_for(key: str) -> str:
            if not self._module_available(key):
                return "Not available on this OS. Needs a Windows-only tool (relog.exe)."
            if self._module_selection_status(key)[0] == "Missing":
                return "Needs a file. Fix it on step 2."
            return "Not selected on step 2."

        built = {"done": False}

        def toggle() -> None:
            if body.winfo_manager():
                body.pack_forget()
                caret.configure(image=_caret_icon(False))
                link.configure(text="Show")
                return
            if not built["done"]:
                built["done"] = True
                for key in unselected:
                    line = ctk.CTkFrame(body, fg_color="transparent", height=1)
                    line.pack(fill="x", pady=2)
                    line.grid_columnconfigure(0, minsize=self._S3_MODULE_MIN)
                    line.grid_columnconfigure(1, weight=1)
                    ctk.CTkLabel(
                        line,
                        text=self._module_display_name(key),
                        text_color=INK,
                        font=(UI_FONT, 15, "bold"),
                        anchor="w",
                    ).grid(row=0, column=0, sticky="w")
                    ctk.CTkLabel(
                        line,
                        text=reason_for(key),
                        text_color=INK,
                        font=(UI_FONT, 15),
                        anchor="w",
                    ).grid(row=0, column=1, sticky="w", padx=(10, 0))
            body.pack(fill="x", padx=14, pady=(0, 10))
            caret.configure(image=_caret_icon(True))
            link.configure(text="Hide")

        link = ctk.CTkButton(
            head,
            text="Show",
            command=toggle,
            fg_color="transparent",
            hover_color=PANEL,
            text_color=PLUM,
            width=60,
            height=26,
            corner_radius=8,
            font=(UI_FONT, 15, "bold"),
        )
        link.grid(row=0, column=1, sticky="e")
        title.bind("<Button-1>", lambda _e: toggle())

    def _populate_run_action_strip(self, card, selected: list[str]) -> None:
        card.grid_columnconfigure(1, weight=1)
        self.progress_status_var = ctk.StringVar(value="Not started")
        self.progress_meta_var = ctk.StringVar(
            value=f"{len(selected)} module{'s' if len(selected) != 1 else ''}"
        )
        self.progress_guidance_var = ctk.StringVar(value="")
        build_btn = self._pill_button(card, "Build", self._run_engine, fg=PLUM)
        build_btn.configure(
            height=48,
            width=self._action_button_width("Build", 40),
            font=(UI_FONT, 15, "bold"),
        )
        build_btn.grid(row=0, column=0, rowspan=2, sticky="w", padx=(16, 14), pady=16)
        self.build_button = build_btn
        ctk.CTkLabel(
            card,
            textvariable=self.progress_status_var,
            text_color=INK,
            font=(UI_FONT, 13),
            anchor="w",
        ).grid(row=0, column=1, sticky="sew", pady=(16, 2))
        ctk.CTkLabel(
            card,
            textvariable=self.progress_meta_var,
            text_color=INK,
            font=(UI_FONT, 13),
            anchor="e",
        ).grid(row=0, column=2, sticky="se", padx=(10, 14), pady=(16, 2))
        self.progress_bar = ctk.CTkProgressBar(
            card,
            height=10,
            corner_radius=5,
            fg_color=RUN_DETAIL_RULE,
            progress_color=PLUM,
        )
        self.progress_bar.grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(0, 14), pady=(0, 16)
        )
        self.progress_bar.set(0)
        buttons = ctk.CTkFrame(card, fg_color="transparent")
        buttons.grid(row=0, column=3, rowspan=2, sticky="e", padx=(0, 16), pady=16)
        self.view_logs_button = self._secondary_toolbar_button(
            buttons, "View Logs", self._view_logs
        )
        self.view_logs_button.configure(
            height=40,
            width=100,
            font=(UI_FONT, 14, "bold"),
            state="normal" if self._log_chunks or self._build_running else "disabled",
        )
        self.view_logs_button.pack(side="left", padx=(0, 8))
        self.open_output_button = self._secondary_toolbar_button(
            buttons, "Open Output", self._open_output_folder
        )
        self.open_output_button.configure(
            height=40,
            width=112,
            font=(UI_FONT, 14, "bold"),
            state="normal" if self._output_folder_to_open() is not None else "disabled",
        )
        self.open_output_button.pack(side="left", padx=(0, 8))
        self.cancel_button = self._secondary_toolbar_button(
            buttons, "Cancel", self._cancel_run
        )
        self.cancel_button.configure(
            height=40,
            width=80,
            font=(UI_FONT, 14, "bold"),
            text_color=CLAY,
            state="normal" if self._build_running else "disabled",
        )
        self.cancel_button.pack(side="left")
        self.progress_guidance_label = ctk.CTkLabel(
            card,
            textvariable=self.progress_guidance_var,
            text_color=INK,
            fg_color=PANEL,
            corner_radius=8,
            font=(UI_FONT, 14),
            wraplength=980,
            justify="left",
            anchor="w",
        )
        self.progress_guidance_label.grid(
            row=2, column=0, columnspan=4, sticky="ew", padx=16, pady=(0, 12)
        )
        self.progress_guidance_label.grid_remove()

    def _restore_progress_view(self) -> None:
        for key in self._progress_completed:
            self._set_status_cell(key, "done", "Done")
        if self._progress_current:
            self._set_status_cell(self._progress_current, "running", "Running")
        self._update_progress_bar()
        self.build_button.configure(state="disabled", text="Building")

    def _set_status_cell(self, key: str, state: str, text: str | None = None) -> None:
        bg, border, text_color = S3_STATUS_PILL_STYLES.get(
            state, S3_STATUS_PILL_STYLES["not_started"]
        )
        if text is None:
            text = state.replace("_", " ").capitalize()
        pill = self._canvas_status_pills.get(key)
        if pill is None:
            return
        try:
            canvas = pill["canvas"]
            if canvas.winfo_exists():
                canvas.itemconfigure(
                    pill["bg"],
                    image=_pill_bg_photo(bg, border, pill["width"], pill["height"]),
                )
                canvas.itemconfigure(pill["text"], text=text, fill=text_color)
        except TclError:
            pass

    def _mark_progress_current(self, key: str) -> None:
        if self._progress_current and self._progress_current != key:
            self._mark_progress_done(self._progress_current)
        self._progress_current = key
        self._module_run_started[key] = time.monotonic()
        self._set_status_cell(key, "running", "Running")
        if hasattr(self, "progress_status_var"):
            total = len(self._progress_order)
            position = (
                self._progress_order.index(key) + 1
                if key in self._progress_order
                else total
            )
            self.progress_status_var.set(
                f"{position} of {total} · {self._module_display_name(key)}"
            )
        self._update_progress_bar()

    def _mark_progress_done(self, key: str) -> None:
        if key in self._progress_completed:
            return
        self._progress_completed.add(key)
        started = self._module_run_started.get(key)
        if started is not None:
            secs = int(time.monotonic() - started)
            minutes, remainder = divmod(secs, 60)
            timing = f"{minutes}m {remainder}s" if minutes else f"{remainder}s"
            self._set_status_cell(key, "done", f"Done · {timing}")
        else:
            self._set_status_cell(key, "done", "Done")
        self._update_progress_bar()

    def _update_progress_bar(self) -> None:
        total = len(self._progress_order)
        if not total or not hasattr(self, "progress_bar"):
            return
        try:
            if self.progress_bar.winfo_exists():
                self.progress_bar.set(len(self._progress_completed) / total)
        except TclError:
            pass
        self._update_progress_meta()

    def _update_progress_meta(self) -> None:
        if not hasattr(self, "progress_meta_var"):
            return
        total = len(self._progress_order)
        if self._build_started_at is not None and (
            self._build_running or self._progress_completed
        ):
            elapsed = int(time.monotonic() - self._build_started_at)
            minutes, secs = divmod(max(0, elapsed), 60)
            self.progress_meta_var.set(f"Elapsed {minutes:02d}:{secs:02d}")
        else:
            self.progress_meta_var.set(f"{total} module{'s' if total != 1 else ''}")

    def _tick_elapsed_timer(self) -> None:
        self._elapsed_timer_id = None
        self._update_progress_meta()
        if self._build_running:
            self._elapsed_timer_id = self.after(1000, self._tick_elapsed_timer)

    def _output_folder_to_open(self) -> Path | None:
        if self._run_folder is not None and self._run_folder.is_dir():
            return self._run_folder
        return None

    def _refresh_open_output_buttons(self) -> None:
        state = "normal" if self._output_folder_to_open() is not None else "disabled"
        buttons = [
            button
            for button in [getattr(self, "open_output_button", None)]
            + self._open_output_buttons[:]
            if button is not None
        ]
        for button in buttons:
            try:
                if button.winfo_exists():
                    button.configure(state=state)
                else:
                    self._open_output_buttons.remove(button)
            except TclError:
                if button in self._open_output_buttons:
                    self._open_output_buttons.remove(button)

    def _open_output_folder(self) -> None:
        folder = self._output_folder_to_open()
        if folder is None:
            return
        try:
            open_path(folder)
        except OSError as exc:
            messagebox.showerror("Could not open", f"{folder}\n\n{exc}")

    # ------------------------------------------------------------------
    # Running the engine
    # ------------------------------------------------------------------

    def _run_engine(self) -> None:
        if self._build_running:
            return
        errors, bad = self._validate_step1()
        errors += self._validate_step2(bad)
        if errors:
            self._show_errors("Not ready", errors)
            return
        config = self._build_config()
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
        self._clear_captured_log()
        self._diagnostics.update_metadata(
            selected_modules=self._selected_keys(),
            build_started=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        self._diagnostics.record("Build requested", modules=len(self._selected_keys()))
        self._run_folder = None
        self._run_log_path = None
        self._progress_completed = set()
        self._progress_current = None
        for key in self._progress_order:
            self._set_status_cell(key, "not_started", "Queued")
        self._build_running = True
        self._cancel_requested = False
        self._build_started_at = time.monotonic()
        self.build_button.configure(state="disabled", text="Building")
        self.cancel_button.configure(state="normal")
        self.view_logs_button.configure(state="normal")
        self._refresh_open_output_buttons()
        self.progress_status_var.set("Starting...")
        self.progress_guidance_var.set("")
        self.progress_guidance_label.grid_remove()
        self._sync_nav()
        self._append_log(f"Config saved: {CONFIG_PATH}\n")
        threading.Thread(
            target=self._run_worker, args=(CONFIG_PATH,), daemon=True
        ).start()
        self.after(100, self._drain_log)
        self._tick_elapsed_timer()

    def _run_worker(self, config_path: Path) -> None:
        python_exe = sys.executable
        if IS_WINDOWS:
            pythonw = Path(sys.executable).parent / "pythonw.exe"
            if pythonw.exists():
                python_exe = str(pythonw)
        cmd = [
            python_exe,
            str(APP_DIR / "run_diagnostics.py"),
            "--config",
            str(config_path),
            "--yes",
        ]
        code = 1
        started = time.perf_counter()
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
            self._diagnostics.record(
                "Build engine process",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                return_code=code,
            )
            self._log_queue.put(f"__EXIT__{code}")

    def _drain_log(self) -> None:
        started = time.perf_counter()
        finished: int | None = None
        chunks: list[str] = []
        processed = 0
        while processed < _LOG_DRAIN_MAX_ITEMS:
            if (time.perf_counter() - started) * 1000 >= _LOG_DRAIN_BUDGET_MS:
                break
            try:
                item = self._log_queue.get_nowait()
            except queue.Empty:
                break
            if item.startswith("__EXIT__"):
                finished = int(item[len("__EXIT__") :] or 1)
            else:
                chunks.append(item)
            processed += 1
        if chunks:
            self._append_log("".join(chunks))
        elapsed_ms = (time.perf_counter() - started) * 1000
        if processed or elapsed_ms >= _LOG_DRAIN_BUDGET_MS:
            self._diagnostics.record(
                "Build log drain",
                elapsed_ms=elapsed_ms,
                items=processed,
                queue_depth=self._log_queue.qsize(),
            )
        if finished is not None:
            self._set_done(finished == 0)
            return
        if self._build_running:
            delay = 10 if not self._log_queue.empty() else 100
            self.after(delay, self._drain_log)

    def _clear_captured_log(self) -> None:
        self._log_chunks.clear()
        self._log_chunk_chars = 0
        self._log_truncated = False

    def _append_captured_log(self, text: str) -> None:
        if not text:
            return
        self._log_chunks.append(text)
        self._log_chunk_chars = self.__dict__.get("_log_chunk_chars", 0) + len(text)
        while self._log_chunk_chars > _MAX_CAPTURED_LOG_CHARS and self._log_chunks:
            if isinstance(self._log_chunks, deque):
                removed = self._log_chunks.popleft()
            else:
                removed = self._log_chunks.pop(0)
            self._log_chunk_chars -= len(removed)
            self._log_truncated = True

    def _captured_log_text(self) -> str:
        text = "".join(self._log_chunks)
        if not self.__dict__.get("_log_truncated", False):
            return text
        return (
            "Earlier UI log output was omitted to keep the Workbench responsive. "
            "Open the run log for the complete build log.\n" + text
        )

    @staticmethod
    def _trim_log_viewer(viewer: ctk.CTkTextbox) -> None:
        try:
            line_count = int(str(viewer.index("end-1c")).split(".", 1)[0])
            extra = line_count - _MAX_LOG_VIEWER_LINES
            if extra > 0:
                viewer.delete("1.0", f"{extra + 1}.0")
        except (TclError, ValueError):
            pass

    def _append_log(self, text: str) -> None:
        self._append_captured_log(text)
        for viewer in list(self._log_viewers):
            try:
                if not viewer.winfo_exists():
                    self._log_viewers.remove(viewer)
                    continue
                viewer.configure(state="normal")
                viewer.insert("end", text)
                self._trim_log_viewer(viewer)
                viewer.see("end")
                viewer.configure(state="disabled")
            except TclError:
                self._log_viewers.remove(viewer)
        for line in text.splitlines():
            for key, header in STEP_HEADERS.items():
                if key in self._progress_order and f"Step: {header}" in line:
                    self._mark_progress_current(key)
            match = _RUN_FOLDER_RE.match(line)
            if match:
                self._run_folder = Path(match.group(1))
                self._footer_run_label.configure(text=str(self._run_folder))
                self._refresh_open_output_buttons()
            match = _RUN_LOG_RE.match(line)
            if match:
                self._run_log_path = Path(match.group(1))

    def _set_done(self, success: bool) -> None:
        self._build_running = False
        self._update_progress_meta()
        self.build_button.configure(state="normal", text="Build")
        self.cancel_button.configure(state="disabled")
        self.view_logs_button.configure(state="normal")
        self._refresh_open_output_buttons()
        self._sync_nav()
        if self._cancel_requested:
            self.progress_status_var.set("Build canceled.")
            if self._progress_current:
                self._set_status_cell(self._progress_current, "failed", "Canceled")
            self._write_ui_diagnostics("canceled")
            return
        if success:
            for key in self._progress_order:
                self._mark_progress_done(key)
            self.progress_status_var.set("Build complete.")
            folder = self._output_folder_to_open()
            self.progress_guidance_var.set(
                f"Build complete. Output folder: {folder if folder else 'the selected output folder'}. "
                "Use Open Output to review the generated files."
            )
            self.progress_guidance_label.grid()
            self._write_ui_diagnostics("completed")
        else:
            if self._progress_current:
                self._set_status_cell(self._progress_current, "failed", "Failed")
            self.progress_status_var.set("Build finished with errors. See View Logs.")
            self._write_ui_diagnostics("failed")

    def _write_ui_diagnostics(self, result: str) -> None:
        """Save UI responsiveness evidence beside a completed engine run."""
        run_folder = self._run_folder
        if run_folder is None:
            return
        build_elapsed_ms = 0.0
        if self._build_started_at is not None:
            build_elapsed_ms = (time.monotonic() - self._build_started_at) * 1000
        self._diagnostics.record(
            "Build completed",
            elapsed_ms=build_elapsed_ms,
            result=result,
        )
        path = run_folder / f"{run_folder.name}_UI_Diagnostics.json"
        try:
            self._diagnostics.write_json(
                path,
                result=result,
                heartbeat_max_lag_ms=round(self._max_heartbeat_lag_ms, 2),
                heartbeat_samples=len(self._heartbeat_samples),
                process_resources=process_resource_metrics(),
            )
            self._append_log(f"UI diagnostics: {path}\n")
        except OSError as exc:
            self._append_log(f"WARNING: Could not write UI diagnostics: {exc}\n")

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

    def _view_logs(self) -> None:
        window = ctk.CTkToplevel(self)
        window.title("Build Logs")
        self.update_idletasks()
        win_w, win_h = 920, 640
        x = self.winfo_rootx() + max(0, (self.winfo_width() - win_w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - win_h) // 2)
        window.geometry(f"{win_w}x{win_h}+{x}+{y}")
        window.minsize(760, 480)
        window.configure(fg_color=CANVAS)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(1, weight=1)
        window.transient(self)
        window.after(50, lambda: (window.lift(), window.focus_force()))
        header = ctk.CTkFrame(
            window,
            fg_color=PAPER,
            corner_radius=14,
            border_width=1,
            border_color=HAIRLINE,
        )
        header.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            header, text="Build Logs", text_color=INK, font=(UI_FONT, 24, "bold")
        ).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 0))
        if self._run_log_path and self._run_log_path.exists():
            source = f"Run log file: {self._run_log_path}"
        else:
            source = "Captured engine output from this session."
        ctk.CTkLabel(
            header,
            text=source,
            text_color=MUTED,
            font=(UI_FONT, 12),
            wraplength=820,
            justify="left",
        ).grid(row=1, column=0, sticky="w", padx=20, pady=(2, 16))
        log_box = ctk.CTkTextbox(
            window,
            corner_radius=24,
            fg_color=LOG_BG,
            text_color=LOG_TEXT,
            font=("Consolas", 12),
        )
        log_box.grid(row=1, column=0, sticky="nsew", padx=18, pady=10)
        log_box.insert(
            "1.0", self._captured_log_text() or "No build log has been captured yet."
        )
        log_box.see("end")
        log_box.configure(state="disabled")
        self._log_viewers.append(log_box)
        actions = ctk.CTkFrame(
            window,
            fg_color=PAPER,
            corner_radius=14,
            border_width=1,
            border_color=HAIRLINE,
        )
        actions.grid(row=2, column=0, sticky="ew", padx=18, pady=(6, 18))
        actions.grid_columnconfigure(0, weight=1)
        if self._run_log_path is not None:
            self._pill_button(
                actions,
                "Open Log File",
                lambda: open_path(self._run_log_path),
                fg=PAPER,
                text_color=INK,
            ).grid(row=0, column=0, sticky="w", padx=14, pady=12)
        open_output = self._pill_button(
            actions, "Open Output", self._open_output_folder, fg=PAPER, text_color=INK
        )
        open_output.configure(
            state="normal" if self._output_folder_to_open() is not None else "disabled"
        )
        self._open_output_buttons.append(open_output)
        open_output.bind(
            "<Destroy>",
            lambda _event, button=open_output: (
                self._open_output_buttons.remove(button)
                if button in self._open_output_buttons
                else None
            ),
        )
        open_output.grid(row=0, column=1, padx=(8, 0), pady=12)
        self._pill_button(actions, "Close", window.destroy, fg=FOG, text_color=INK).grid(
            row=0, column=2, padx=(8, 14), pady=12
        )

    def _on_close(self) -> None:
        if self._build_running and not messagebox.askyesno(
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
