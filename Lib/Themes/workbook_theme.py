#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
workbook_theme.py -- shared Excel workbook theme for supporting artifacts.

This is the workbook equivalent of chart_theme.py. Generators should import
these tokens and helpers instead of defining local fonts, fills, borders, and
status palettes.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from Lib.Design import status_spine
from Lib.Design.design_system import DESIGN_SYSTEM as DS


def _clean(color: str) -> str:
    return str(color or "").strip().lstrip("#").upper()


def xw_color(color: str) -> str:
    """Return an xlsxwriter-friendly #RRGGBB color."""
    clean = _clean(color)
    return f"#{clean}" if clean else ""


def ox_color(color: str) -> str:
    """Return an openpyxl-friendly RRGGBB color."""
    return _clean(color)


@dataclass(frozen=True)
class WorkbookTheme:
    """Shared Excel design tokens sourced from the design system."""

    # Common, no-install font matching the UI and charts so the package
    # stays consistent.
    font_name: str = "Segoe UI"
    mono_font_name: str = "Courier New"
    body_size: int = 10
    header_size: int = 10
    title_size: int = 16

    title: str = ox_color(DS.midnight.hex_value)
    text: str = ox_color(DS.midnight.hex_value)
    muted: str = ox_color(DS.text_muted.hex_value)
    header_bg: str = ox_color(DS.midnight.hex_value)
    header_fg: str = ox_color(DS.white.hex_value)
    section_bg: str = ox_color(DS.teal_dark.hex_value)
    section_fg: str = ox_color(DS.white.hex_value)
    meta_bg: str = ox_color(DS.tech_grey.hex_value)
    border: str = ox_color(DS.border_light.hex_value)
    alt_row: str = "F4F9FC"
    input_bg: str = ox_color(DS.white.hex_value)
    readonly_bg: str = "E8F1FB"
    calculated_bg: str = "E8EAF0"
    disabled_bg: str = "F3F4F6"

    pass_fg: str = ox_color(status_spine.HEALTHY.text)
    pass_bg: str = "E8F5E9"
    warning_fg: str = ox_color(status_spine.NEEDS_ATTENTION.text)
    warning_bg: str = "FFF8E7"
    fail_fg: str = ox_color(DS.critical.hex_value)
    fail_bg: str = "FDECEA"
    neutral_fg: str = ox_color(status_spine.NOT_ASSESSED.text)
    neutral_bg: str = "F3F4F6"
    action_bg: str = "FCEAE9"

    critical_fg: str = "9C0006"
    critical_bg: str = "FDECEA"
    high_fg: str = ox_color(DS.critical.hex_value)
    high_bg: str = "FCEAE9"
    medium_fg: str = ox_color(status_spine.NEEDS_ATTENTION.text)
    medium_bg: str = "FFF8E7"
    low_fg: str = ox_color(DS.accent_blue.hex_value)
    low_bg: str = "E3F0FB"
    info_fg: str = ox_color(DS.text_muted.hex_value)
    info_bg: str = "F3F4F6"

    consultant_fg: str = ox_color(DS.accent_blue.hex_value)
    auto_fg: str = ox_color(DS.success.hex_value)


WORKBOOK_THEME = WorkbookTheme()


def normalize_status(value: object) -> str:
    return str(value or "").strip().casefold()


def status_key(value: object) -> str:
    key = normalize_status(value)
    if key in {"pass", "passed", "ok", "complete", "healthy", "good"}:
        return "pass"
    if key in {"warning", "advisory", "review", "in progress", "medium"}:
        return "warning"
    if key in {"fail", "failed", "critical", "blocker", "blocked", "high"}:
        return "fail"
    if key in {"cannot verify", "not evaluated", "not available", "deferred", "info"}:
        return "neutral"
    return "cell"


def severity_key(value: object) -> str:
    key = normalize_status(value)
    return {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "info": "info",
        "informational": "info",
    }.get(key, "info")


def xlsxwriter_formats(workbook, theme: WorkbookTheme = WORKBOOK_THEME) -> dict:
    """Create standard xlsxwriter formats for project workbooks."""

    base = {
        "font_name": theme.font_name,
        "font_size": theme.body_size,
        "border": 1,
        "border_color": xw_color(theme.border),
        "valign": "top",
    }

    def fmt(**kwargs):
        data = dict(base)
        data.update(kwargs)
        return workbook.add_format(data)

    formats = {
        "title": fmt(
            bold=True,
            font_size=theme.title_size,
            font_color=xw_color(theme.header_fg),
            bg_color=xw_color(theme.title),
            align="left",
            valign="vcenter",
        ),
        "section": fmt(
            bold=True,
            font_size=12,
            font_color=xw_color(theme.section_fg),
            bg_color=xw_color(theme.section_bg),
            align="left",
            valign="vcenter",
        ),
        "header": fmt(
            bold=True,
            font_size=theme.header_size,
            font_color=xw_color(theme.header_fg),
            bg_color=xw_color(theme.header_bg),
            text_wrap=True,
            align="center",
            valign="vcenter",
        ),
        "header_left": fmt(
            bold=True,
            font_size=theme.header_size,
            font_color=xw_color(theme.header_fg),
            bg_color=xw_color(theme.header_bg),
            text_wrap=True,
            align="left",
            valign="vcenter",
        ),
        "cell": fmt(text_wrap=True),
        "bold": fmt(bold=True, text_wrap=True),
        "center": fmt(align="center", valign="vcenter"),
        "int": fmt(num_format="#,##0"),
        "wrap": fmt(text_wrap=True, italic=True, font_color=xw_color(theme.muted)),
        "note": fmt(
            italic=True,
            font_size=9,
            font_color=xw_color(theme.muted),
            bg_color=xw_color(theme.meta_bg),
            text_wrap=True,
        ),
        "mono": fmt(
            font_name=theme.mono_font_name,
            font_size=8,
            text_wrap=True,
        ),
        "meta_label": fmt(
            bold=True,
            font_color=xw_color(theme.text),
            bg_color=xw_color(theme.meta_bg),
        ),
        "meta_value": fmt(
            font_color=xw_color(theme.title),
            bg_color=xw_color(theme.input_bg),
            bottom=2,
            bottom_color=xw_color(theme.section_bg),
        ),
        "readonly": fmt(
            bg_color=xw_color(theme.readonly_bg),
            font_color=xw_color(theme.text),
            align="center",
            valign="vcenter",
        ),
        "manual": fmt(
            bg_color=xw_color(theme.input_bg),
            font_color=xw_color(theme.title),
            align="center",
            valign="vcenter",
        ),
        "calculated": fmt(
            italic=True,
            bg_color=xw_color(theme.calculated_bg),
            font_color=xw_color(theme.text),
            align="center",
            valign="vcenter",
        ),
        "disabled": fmt(
            font_size=9,
            font_color=xw_color(theme.muted),
            bg_color=xw_color(theme.disabled_bg),
            align="center",
            valign="vcenter",
            text_wrap=True,
        ),
    }

    for key, fg, bg in (
        ("pass", theme.pass_fg, theme.pass_bg),
        ("warning", theme.warning_fg, theme.warning_bg),
        ("fail", theme.fail_fg, theme.fail_bg),
        ("neutral", theme.neutral_fg, theme.neutral_bg),
    ):
        formats[f"status_{key}"] = fmt(
            bold=True,
            font_color=xw_color(fg),
            bg_color=xw_color(bg),
            align="center",
            valign="vcenter",
        )

    for key, fg, bg in (
        ("critical", theme.critical_fg, theme.critical_bg),
        ("high", theme.high_fg, theme.high_bg),
        ("medium", theme.medium_fg, theme.medium_bg),
        ("low", theme.low_fg, theme.low_bg),
        ("info", theme.info_fg, theme.info_bg),
    ):
        formats[f"severity_{key}"] = fmt(
            font_color=xw_color(fg),
            bg_color=xw_color(bg),
            text_wrap=True,
        )
        formats[f"severity_{key}_bold"] = fmt(
            bold=True,
            font_color=xw_color(fg),
            bg_color=xw_color(bg),
            text_wrap=True,
        )

    return formats


def xlsxwriter_status_format(formats: dict, status: object):
    key = status_key(status)
    return formats.get(f"status_{key}", formats["cell"])


def xlsxwriter_severity_format(formats: dict, severity: object, *, bold: bool = False):
    key = severity_key(severity)
    suffix = "_bold" if bold else ""
    return formats.get(f"severity_{key}{suffix}", formats["cell"])


def openpyxl_styles(theme: WorkbookTheme = WORKBOOK_THEME) -> SimpleNamespace:
    """Create standard openpyxl style objects."""

    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

    thin = Side(style="thin", color=ox_color(theme.border))
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    return SimpleNamespace(
        thin=thin,
        border=border,
        header_fill=PatternFill("solid", fgColor=ox_color(theme.header_bg)),
        header_font=Font(
            name=theme.font_name,
            size=theme.header_size,
            bold=True,
            color=ox_color(theme.header_fg),
        ),
        title_font=Font(
            name=theme.font_name,
            size=theme.title_size,
            bold=True,
            color=ox_color(theme.title),
        ),
        subtitle_font=Font(
            name=theme.font_name,
            size=10,
            italic=True,
            color=ox_color(theme.muted),
        ),
        body_font=Font(
            name=theme.font_name,
            size=theme.body_size,
            color=ox_color(theme.text),
        ),
        body_italic=Font(
            name=theme.font_name,
            size=theme.body_size,
            italic=True,
            color=ox_color(theme.muted),
        ),
        alt_fill=PatternFill("solid", fgColor=ox_color(theme.alt_row)),
        meta_fill=PatternFill("solid", fgColor=ox_color(theme.meta_bg)),
        alignment=Alignment(vertical="top", wrap_text=True),
        header_alignment=Alignment(
            horizontal="center", vertical="center", wrap_text=True
        ),
    )


def style_openpyxl_header_row(
    ws,
    row: int = 1,
    *,
    max_col: int | None = None,
    theme: WorkbookTheme = WORKBOOK_THEME,
    horizontal: str = "center",
) -> None:
    from openpyxl.styles import Alignment

    styles = openpyxl_styles(theme)
    max_col = max_col or ws.max_column
    for col in range(1, max_col + 1):
        cell = ws.cell(row=row, column=col)
        cell.fill = styles.header_fill
        cell.font = styles.header_font
        cell.alignment = Alignment(
            horizontal=horizontal,
            vertical="center",
            wrap_text=True,
        )
        cell.border = styles.border
    ws.row_dimensions[row].height = 22


def style_openpyxl_body(
    ws,
    *,
    min_row: int = 2,
    max_row: int | None = None,
    max_col: int | None = None,
    theme: WorkbookTheme = WORKBOOK_THEME,
    alt_rows: bool = True,
) -> None:
    styles = openpyxl_styles(theme)
    max_row = max_row or ws.max_row
    max_col = max_col or ws.max_column
    for row_idx in range(min_row, max_row + 1):
        for col in range(1, max_col + 1):
            cell = ws.cell(row=row_idx, column=col)
            cell.alignment = styles.alignment
            cell.border = styles.border
            if cell.value is not None and not cell.font.bold:
                cell.font = styles.body_font
            if alt_rows and row_idx % 2 == 0:
                cell.fill = styles.alt_fill


def autosize_openpyxl_columns(
    ws,
    *,
    min_width: int = 12,
    max_width: int = 80,
    padding: int = 2,
) -> None:
    from openpyxl.utils import get_column_letter

    for col_idx, column_cells in enumerate(ws.columns, start=1):
        max_len = max(
            (len(str(cell.value)) for cell in column_cells if cell.value is not None),
            default=min_width,
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = min(
            max(max_len + padding, min_width),
            max_width,
        )


def finish_openpyxl_worksheet(
    ws,
    *,
    header_row: int = 1,
    widths: list[int] | tuple[int, ...] | None = None,
    freeze: bool = True,
    autofilter: bool = True,
    theme: WorkbookTheme = WORKBOOK_THEME,
) -> None:
    from openpyxl.utils import get_column_letter

    if ws.max_row >= header_row:
        style_openpyxl_header_row(ws, header_row, theme=theme)
    if ws.max_row > header_row:
        style_openpyxl_body(ws, min_row=header_row + 1, theme=theme)
    if widths:
        for col_idx, width in enumerate(widths, start=1):
            ws.column_dimensions[get_column_letter(col_idx)].width = width
    else:
        autosize_openpyxl_columns(ws)
    if freeze:
        ws.freeze_panes = ws.cell(row=header_row + 1, column=1).coordinate
    if autofilter and ws.max_row >= header_row:
        ws.auto_filter.ref = ws.dimensions
    ws.sheet_view.showGridLines = False


def finish_openpyxl_workbook(
    path: str | Path,
    *,
    header_row: int = 1,
    theme: WorkbookTheme = WORKBOOK_THEME,
) -> None:
    from openpyxl import load_workbook

    workbook_path = Path(path)
    wb = load_workbook(workbook_path)
    for ws in wb.worksheets:
        finish_openpyxl_worksheet(ws, header_row=header_row, theme=theme)
    wb.save(workbook_path)


def openpyxl_status_fill(status: object, theme: WorkbookTheme = WORKBOOK_THEME):
    from openpyxl.styles import PatternFill

    colors = {
        "pass": theme.pass_bg,
        "warning": theme.warning_bg,
        "fail": theme.fail_bg,
        "neutral": theme.neutral_bg,
    }
    return PatternFill(
        "solid",
        fgColor=ox_color(colors.get(status_key(status), theme.neutral_bg)),
    )


def openpyxl_status_font(status: object, theme: WorkbookTheme = WORKBOOK_THEME):
    from openpyxl.styles import Font

    colors = {
        "pass": theme.pass_fg,
        "warning": theme.warning_fg,
        "fail": theme.fail_fg,
        "neutral": theme.neutral_fg,
    }
    return Font(
        name=theme.font_name,
        size=theme.body_size,
        bold=True,
        color=ox_color(colors.get(status_key(status), theme.neutral_fg)),
    )
