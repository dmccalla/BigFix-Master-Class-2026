#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
Generates a BigFix Client Loop Performance Summary from an Excel or CSV input file.

PowerShell-to-Python conversion of Get-LoopHealthChart.ps1.

Input file requirements:
  - Optional computer/device name column, such as "Computer Name"
  - Maximum loop time column, such as "Maximum cycle seconds"
  - Average loop time column, such as "Average cycle seconds"
  - Headerless Basic Agent Counter CSV exports are also accepted as:
    computer name, maximum loop minutes, average loop minutes

The script auto-detects the computer, maximum, and average columns by name.
If no computer column exists, the report still works.

Output:
  - PNG image suitable for pasting into a Word health-check document
  - Excel workbook with:
      - Health Summary
      - Fix These First
      - Source Data
  - Word document with the PNG and summary tables

Default thresholds:
  Healthy  : <  00:30:00
  Warning  : >= 00:30:00 and <= 01:00:00
  Critical : >  01:00:00

Install dependencies:
  pip install pandas openpyxl matplotlib pillow python-docx

Examples:
  python get_loop_health_chart.py

  python get_loop_health_chart.py \
      --input-file ./client_loop.xlsx \
      --output-folder C:/Temp \
      --report-start-date 04-22-2026 \
      --report-end-date 04-29-2026
"""

from __future__ import annotations

import argparse
import csv
import io
import ipaddress
import itertools
import math
import re
import statistics
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd

import Lib.Core.report_log as log
from Lib.Core.besapi_capture import read_capture_or_log_text, sample_capture_lines
from Lib.Core.document_stamp import (
    add_stamp_arguments,
    stamp_docx_document,
    stamp_from_args,
    stamp_worksheet,
)
from Lib.Core.input_utils import (
    clean_user_path as shared_clean_user_path,
)
from Lib.Core.input_utils import (
    resolve_existing_file as shared_resolve_existing_file,
)
from Lib.Core.input_utils import (
    resolve_existing_folder as shared_resolve_existing_folder,
)
from Lib.Design import status_spine
from Lib.Themes.workbook_theme import WORKBOOK_THEME, finish_openpyxl_workbook

try:
    from docx import Document
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
except ImportError:  # handled later only if docx output is needed
    Document = None


@dataclass
class ProcessedRow:
    computer_name: str
    max_loop: str
    avg_loop: str
    max_seconds: float
    avg_seconds: float
    receiving_udp_pings: str = ""
    relay: str = ""
    subnet: str = ""
    command_polling_enabled: str = ""
    command_polling_interval: str = ""
    command_polling_interval_seconds: int | None = None
    command_polling_review: str = ""
    fast_hash_verify_enabled: str = ""
    fast_hash_verify_work: str = ""
    fast_hash_verify_sleep: str = ""
    agent_multicore_scaling_enabled: str = ""
    agent_total_physical_cpu_core_count: str = ""
    agent_cpu_work_idle: str = ""
    agent_cpu_sleep_idle: str = ""


@dataclass
class ReportMetrics:
    total_devices: int
    score_total_devices: int
    overall_status: str
    environment_score: int
    score_driver: str
    score_breakdown: str
    report_start_text: str
    report_end_text: str
    report_span_text: str
    generated_at_text: str
    avg_mean_seconds: float
    avg_median_seconds: float
    avg_max_seconds: float
    slowest_avg_seconds: float
    peak_max_seconds: float
    avg_healthy: int
    avg_warning: int
    avg_critical: int
    avg_healthy_pct: float
    avg_warning_pct: float
    avg_critical_pct: float
    avg_over_120: int
    avg_over_120_pct: float
    not_reported_count: int
    error_count: int
    not_reported_pct: float
    error_pct: float
    total_issue_count: int
    total_issue_pct: float
    healthy_threshold_seconds: float
    critical_threshold_seconds: float
    fix_first_count: int


@dataclass
class ActionSitePressure:
    deployment_info_folder: Path
    actionsite_size_kb: int | None = None
    master_operator_count: int | None = None
    master_open_actions: int | None = None
    external_site_count: int | None = None
    custom_site_count: int | None = None
    automatic_computer_group_count: int | None = None
    manual_computer_group_count: int | None = None
    fixlets_relevant_count: int | None = None
    fixlets_total_count: int | None = None
    tasks_relevant_count: int | None = None
    tasks_total_count: int | None = None
    analyses_relevant_count: int | None = None
    analyses_total_count: int | None = None
    active_analyses_count: int | None = None
    properties_count: int | None = None
    active_properties_count: int | None = None
    custom_properties_count: int | None = None
    master_operator_fixlets: int | None = None
    master_operator_tasks: int | None = None
    master_operator_fixlets_tasks_total: int | None = None
    master_operator_analyses: int | None = None


@dataclass
class LoopOffenderSummary:
    rank: int
    occurrences: int
    total_client_processing_seconds: float
    max_client_processing_seconds: float
    avg_client_processing_seconds: float
    result: str


@dataclass
class UdpNotificationSummary:
    source_file: Path
    total_devices: int
    receiving_count: int
    not_receiving_count: int
    unknown_count: int
    relay_rows: list[list[str]]
    subnet_rows: list[list[str]]
    rows: list[dict[str, Any]] = field(default_factory=list)
    not_receiving_missing_relay_count: int = 0
    not_receiving_missing_subnet_count: int = 0
    not_receiving_missing_rollup_data_count: int = 0


@dataclass
class CommandPollingSummary:
    total_devices: int
    enabled_count: int
    disabled_count: int
    not_set_count: int
    unknown_count: int
    enabled_missing_interval_count: int
    interval_below_loop_count: int
    no_udp_polling_gap_count: int
    relay_rows: list[list[str]]
    subnet_rows: list[list[str]]


@dataclass
class FastHashVerifySummary:
    total_devices: int
    enabled_count: int
    disabled_count: int
    not_set_count: int
    unknown_count: int
    settings_rows: list[list[str]]


@dataclass
class AgentMulticoreSummary:
    total_devices: int
    settings_rows: list[list[str]]


@dataclass
class AgentCpuIdleSummary:
    total_devices: int
    settings_rows: list[list[str]]


# Accessible, colorblind-safer palette from the PowerShell version.
TABLE_STYLE_ID = "BigFixContent"


LOOP_INPUT_EXTENSIONS = {".xml", ".xlsx", ".xlsm", ".xls", ".csv"}
EXCEL_INPUT_EXTENSIONS = {".xlsx", ".xlsm", ".xls"}

COMMAND_POLLING_ENABLED_COLUMN_NAMES = (
    "Platform Health Check - Command Polling Enabled",
    "Platform Health Check - Command Polling Enbaled",
    "Command Polling Enabled",
    "Command Polling Enbaled",
    "_BESClient_Comm_CommandPollEnable",
)
COMMAND_POLLING_INTERVAL_COLUMN_NAMES = (
    "Platform Health Check - Command Polling Minutes",
    "Command Polling Minutes",
    "Platform Health Check - Command Polling Interval",
    "Platform Health Check - Command Polling Seconds",
    "Command Polling Interval",
    "Command Polling Interval Seconds",
    "Command Polling Seconds",
    "_BESClient_Comm_CommandPollIntervalSeconds",
)
COMMAND_POLLING_HEADROOM_SECONDS = 600

FAST_HASH_VERIFY_ENABLED_COLUMN_NAMES = (
    "Platform Health Check - FastHashVerify Enabled",
    "FastHashVerify Enabled",
    "_BESClient_Download_FastHashVerify",
)
FAST_HASH_VERIFY_WORK_COLUMN_NAMES = (
    "Platform Health Check - FastHashVerify Work ms",
    "FastHashVerify Work ms",
    "_BESClient_Resource_WorkFastHashVerify",
)
FAST_HASH_VERIFY_SLEEP_COLUMN_NAMES = (
    "Platform Health Check - FastHashVerify Sleep ms",
    "FastHashVerify Sleep ms",
    "_BESClient_Resource_SleepFastHashVerify",
)
AGENT_MULTICORE_SCALING_COLUMN_NAMES = (
    "Platform Health Check - Agent Multicore Scaling Enabled",
    "Agent Multicore Scaling Enabled",
    "_BESClient_Resource_ScaleWorkTimeWithCPUCores",
)
AGENT_TOTAL_PHYSICAL_CPU_CORE_COUNT_COLUMN_NAMES = (
    "Platform Health Check - Agent Total Physical CPU Core Count",
    "Agent Total Physical CPU Core Count",
)
AGENT_CPU_WORK_IDLE_COLUMN_NAMES = (
    "Platform Health Check - Agent CPU Work Idle",
    "Agent CPU Work Idle",
    "_BESClient_Resource_WorkIdle",
)
AGENT_CPU_SLEEP_IDLE_COLUMN_NAMES = (
    "Platform Health Check - Agent CPU Sleep Idle",
    "Agent CPU Sleep Idle",
    "_BESClient_Resource_SleepIdle",
)


def parse_timespan_to_seconds(value: str) -> float:
    """Parse HH:MM:SS-like threshold strings to seconds."""
    seconds = convert_to_seconds(value)
    if seconds is None:
        raise ValueError(f"Could not parse threshold as a time span: {value}")
    return float(seconds)


# ---------------------------------------------------------------------------
# Time conversion helpers
#
# Loop time values arrive in multiple formats from different BigFix versions:
#   HH:MM:SS string    e.g. '00:45:23'
#   Numeric seconds    e.g. 2723.0
#   Numeric minutes    detected when the column name says minutes
#
# convert_to_seconds() normalises all formats to a float number of seconds.
# convert_to_hhmmss() formats seconds back to HH:MM:SS for display.
# ---------------------------------------------------------------------------
def _column_unit_hint(column_name: str | None) -> str:
    """Infer the intended unit from common agent loop column names."""
    text = str(column_name or "").lower()
    if re.search(r"\b(sec|secs|second|seconds)\b", text):
        return "seconds"
    if re.search(r"\b(min|mins|minute|minutes)\b", text):
        return "minutes"
    if re.search(r"\b(hr|hrs|hour|hours)\b", text):
        return "hours"
    return ""


def _numeric_loop_value_to_seconds(value: float, column_name: str | None = None) -> float:
    """Convert numeric loop values using column units when available.

    BigFix exports are not perfectly consistent. Some workbooks contain true
    Excel time values, some contain raw seconds, and others contain raw minutes
    even though the chart expects HH:MM:SS. Prefer explicit column units, then
    fall back to Excel's fractional-day convention only for values below 1.
    """
    unit = _column_unit_hint(column_name)
    if unit == "seconds":
        return float(value)
    if unit == "minutes":
        return float(value) * 60.0
    if unit == "hours":
        return float(value) * 3600.0

    # Excel time values are stored as fractions of a day. Values >= 1 without
    # an explicit unit are more likely raw seconds than an Excel duration.
    if abs(float(value)) < 1:
        return float(value) * 86400.0
    return float(value)


def convert_to_seconds(value: Any, column_name: str | None = None) -> float | None:
    """Convert common loop duration formats to seconds."""
    if value is None:
        return None

    if pd.isna(value):
        return None

    if isinstance(value, timedelta):
        return float(value.total_seconds())

    if isinstance(value, datetime):
        return float(
            value.time().hour * 3600 + value.time().minute * 60 + value.time().second
        )

    if isinstance(value, time):
        return float(value.hour * 3600 + value.minute * 60 + value.second)

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return _numeric_loop_value_to_seconds(float(value), column_name)

    text = str(value).strip()
    if not text:
        return None

    # Numeric strings follow the same unit-aware handling as numeric cells.
    try:
        return _numeric_loop_value_to_seconds(float(text), column_name)
    except ValueError:
        pass

    # Standard duration: H:MM:SS, HH:MM:SS, or HH:MM:SS.ffffff
    match = re.match(r"^(\d+):(\d{1,2}):(\d{1,2})(?:\.(\d+))?$", text)
    if match:
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return float(hours * 3600 + minutes * 60 + seconds)

    # Common manual entry shortcut: MM:SS. Normalize to HH:MM:SS semantics.
    match = re.match(r"^(\d+):(\d{1,2})(?:\.(\d+))?$", text)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return float(minutes * 60 + seconds)

    # Some exports show durations as a date/time string, e.g. 12/30/1899 00:40:18.
    parsed = pd.to_datetime(text, errors="coerce")
    if not pd.isna(parsed):
        return float(parsed.hour * 3600 + parsed.minute * 60 + parsed.second)

    return None


def normalize_loop_time_columns(
    df: pd.DataFrame, max_column: str, avg_column: str
) -> pd.DataFrame:
    """Normalize selected loop time columns to HH:MM:SS display values.

    The downstream report works from seconds, but normalizing the source
    dataframe first makes all generated "Source Data" and display rows stable
    even when the workbook columns were left as General, numeric seconds, or
    numeric minutes instead of a proper time format.
    """
    normalized = df.copy()
    for column in (max_column, avg_column):
        normalized[column] = normalized[column].apply(
            lambda value: (
                convert_to_hhmmss(convert_to_seconds(value, column))
                if convert_to_seconds(value, column) is not None
                else value
            )
        )
    return normalized


def convert_to_hhmmss(seconds: float | None) -> str:
    if seconds is None:
        return "00:00:00"
    try:
        if math.isnan(float(seconds)):
            return "00:00:00"
    except TypeError:
        return "00:00:00"

    total = int(math.floor(float(seconds)))
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_duration_for_report(seconds: float | None) -> str:
    if seconds is None:
        return "00:00:00"
    try:
        seconds_float = float(seconds)
        if math.isnan(seconds_float):
            return "00:00:00"
    except (TypeError, ValueError):
        return "00:00:00"

    if seconds_float > 60 * 60:
        hours = seconds_float / 3600
        if abs(hours - round(hours)) < 0.05:
            hour_count = int(round(hours))
            unit = "hour" if hour_count == 1 else "hours"
            return f"{hour_count} {unit}"
        return f"{hours:.1f} hours"

    return convert_to_hhmmss(seconds_float)


def convert_to_report_date_or_none(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if not text:
        return None

    parsed = pd.to_datetime(text, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.date()


def format_report_date(value: date | None) -> str:
    if value is None:
        return "Not provided"
    return value.strftime("%m-%d-%Y")


def format_report_span(start_value: date | None, end_value: date | None) -> str:
    if start_value is None or end_value is None:
        return "Not provided"
    days = (end_value - start_value).days + 1
    if days < 1:
        return "Invalid range"
    if days == 1:
        return "1 day"
    return f"{days} days"


def pct(value: float, decimals: int = 1) -> str:
    return f"{value * 100:.{decimals}f}%"


def clean_user_path(value: str | None) -> str:
    """
    Normalize path text entered at a prompt or passed as an argument.

    Accepts quoted paths, unquoted paths, filenames, relative paths, and paths
    with leading/trailing whitespace.
    """
    return shared_clean_user_path(value)


def resolve_existing_loop_input(candidate_text: str) -> Path:
    """
    Resolve an input workbook/CSV from either:
      - a full path, such as C:\\Temp\\LoopData.xlsx
      - a relative path, such as .\\Input\\LoopData.xlsx
      - a filename in the current working folder, such as LoopData.xlsx
    """
    return shared_resolve_existing_file(
        candidate_text, "input file", LOOP_INPUT_EXTENSIONS
    )


_LOOP_HEADER_HINT_RE = re.compile(
    r"\b(computer|hostname|device|endpoint|machine|max|maximum|avg|average|cycle|loop|sec|secs|second|seconds|min|mins|minute|minutes|hour|hours)\b",
    re.IGNORECASE,
)


def _has_descriptive_loop_headers(columns: pd.Index) -> bool:
    return any(_LOOP_HEADER_HINT_RE.search(str(column)) for column in columns)


def _load_headerless_basic_counter_csv(csv_source) -> pd.DataFrame:
    df = pd.read_csv(csv_source, header=None)
    columns = [
        "Computer Name",
        "Maximum Cycle Minutes",
        "Average Cycle Minutes",
        "Last UDP Ping",
        "Receiving UDP Pings",
        "Platform Health Check - Command Polling Enabled",
        "Platform Health Check - Command Polling Minutes",
        "Platform Health Check - FastHashVerify Enabled",
        "Platform Health Check - FastHashVerify Work ms",
        "Platform Health Check - FastHashVerify Sleep ms",
        "Platform Health Check - Agent Multicore Scaling Enabled",
        "Platform Health Check - Agent CPU Work Idle",
        "Platform Health Check - Agent CPU Sleep Idle",
        "Platform Health Check - Agent Total Physical CPU Core Count",
    ]
    if len(df.columns) != len(columns):
        raise ValueError(
            "Headerless Client Performance captures must contain all 14 collection fields."
        )
    df.columns = columns
    return df


def _looks_like_loop_csv_metric(value: str) -> bool:
    text = str(value).strip()
    if not text:
        return False

    folded = text.casefold()
    if folded in {"not reported", "error"}:
        return True
    if "property does not exist" in folded or "multiple results" in folded:
        return True
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return True
    return bool(re.fullmatch(r"\d+:\d{1,2}(?::\d{1,2}(?:\.\d+)?)?", text))


def _repair_loop_capture_row_with_commas(row: list[str], expected: int) -> list[str]:
    tail_count = expected - 4
    tail = [value.strip() for value in row[-tail_count:]]
    middle = row[:-tail_count]

    for idx in range(1, len(middle) - 1):
        if _looks_like_loop_csv_metric(middle[idx]) and _looks_like_loop_csv_metric(
            middle[idx + 1]
        ):
            computer_name = ",".join(middle[:idx]).strip()
            max_cycle = middle[idx].strip()
            avg_cycle = middle[idx + 1].strip()
            last_udp = ",".join(middle[idx + 2 :]).strip()
            return [computer_name, max_cycle, avg_cycle, last_udp, *tail]

    return []


def _merge_extra_leading_csv_fields(row: list[str], expected: int) -> list[str]:
    if len(row) == expected:
        return row
    if len(row) < expected:
        return []
    if expected == 14:
        repaired = _repair_loop_capture_row_with_commas(row, expected)
        if repaired:
            return repaired
    leading_count = len(row) - expected + 1
    return [",".join(row[:leading_count]).strip(), *row[leading_count:]]


def _load_loose_loop_csv_text(csv_text: str) -> pd.DataFrame:
    rows = [
        row
        for row in csv.reader(io.StringIO(csv_text))
        if any(str(value).strip() for value in row)
    ]
    if not rows:
        return pd.DataFrame()

    header = [str(value).strip() for value in rows[0]]
    has_header = any(_LOOP_HEADER_HINT_RE.search(column) for column in header)
    if has_header:
        columns = header
        data_rows = rows[1:]
        expected = len(columns)
    else:
        columns = [
            "Computer Name",
            "Maximum Cycle Minutes",
            "Average Cycle Minutes",
            "Last UDP Ping",
            "Receiving UDP Pings",
            "Platform Health Check - Command Polling Enabled",
            "Platform Health Check - Command Polling Minutes",
            "Platform Health Check - FastHashVerify Enabled",
            "Platform Health Check - FastHashVerify Work ms",
            "Platform Health Check - FastHashVerify Sleep ms",
            "Platform Health Check - Agent Multicore Scaling Enabled",
            "Platform Health Check - Agent CPU Work Idle",
            "Platform Health Check - Agent CPU Sleep Idle",
            "Platform Health Check - Agent Total Physical CPU Core Count",
        ]
        expected = 14
        data_rows = rows

    normalized = [
        _merge_extra_leading_csv_fields([str(value) for value in row], expected)
        for row in data_rows
    ]
    if any(len(row) != expected for row in normalized):
        raise ValueError(
            "Headerless Client Performance captures must contain all 14 collection fields."
        )
    return pd.DataFrame(normalized, columns=columns)


def _load_loop_csv_text(csv_text: str) -> pd.DataFrame:
    try:
        df = pd.read_csv(io.StringIO(csv_text))
    except pd.errors.ParserError:
        df = _load_loose_loop_csv_text(csv_text)
    df.columns = [str(column).strip() for column in df.columns]
    if not _has_descriptive_loop_headers(df.columns):
        try:
            return _load_headerless_basic_counter_csv(io.StringIO(csv_text))
        except pd.errors.ParserError:
            return _load_loose_loop_csv_text(csv_text)
    return df


def load_loop_input(input_file: Path) -> pd.DataFrame:
    """Load the Client Performance Counters - Basic export.

    Accepts the raw BESAPI .xml capture (whose answer lines are the CSV
    rows), a formatted CSV, or an Excel workbook.
    """
    suffix = input_file.suffix.lower()
    if suffix == ".xml":
        csv_text = read_capture_or_log_text(input_file)
        return _load_loose_loop_csv_text(csv_text)
    if suffix == ".csv":
        return _load_loop_csv_text(input_file.read_text(encoding="utf-8-sig"))
    if suffix in EXCEL_INPUT_EXTENSIONS:
        # Sheet selection mirrors Import-Excel default behavior: first worksheet.
        return pd.read_excel(input_file)
    raise ValueError(
        "Unsupported loop input file extension. Expected .xml, .xlsx, .xlsm, .xls, or .csv."
    )


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_int_text(value: str) -> int:
    return int(str(value).replace(",", "").strip())


def _candidate_files(folder: Path, patterns: list[str]) -> list[Path]:
    seen: set[Path] = set()
    candidates: list[Path] = []
    for pattern in patterns:
        matches = [p for p in folder.rglob(pattern) if p.is_file()]
        matches.sort(key=lambda p: (p.stat().st_mtime, p.name), reverse=True)
        for path in matches:
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            candidates.append(path)
    return candidates


def _first_int_from_latest_file(
    folder: Path, patterns: list[str], regex: str
) -> int | None:
    # Recursive: Deployment_Information captures are grouped into subfolders by
    # the collection tasks, and older packages are flat. Both resolve.
    for path in _candidate_files(folder, patterns):
        match = re.search(
            regex,
            read_capture_or_log_text(path),
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return _parse_int_text(match.group(1))
    return None


def _first_int_pair_from_latest_file(
    folder: Path, patterns: list[str], regex: str
) -> tuple[int | None, int | None]:
    # Recursive, for the same reason as _first_int_from_latest_file above.
    for path in _candidate_files(folder, patterns):
        match = re.search(
            regex,
            read_capture_or_log_text(path),
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if match:
            return _parse_int_text(match.group(1)), _parse_int_text(match.group(2))
    return None, None


def _actionsite_size_kb_from_deployment_info(folder: Path) -> int | None:
    for path in _candidate_files(
        folder,
        ["General_Info*.xml", "General_Info*.log", "General_Info*"],
    ):
        text = read_capture_or_log_text(path)
        match = re.search(
            r"Actionsite Size\s*:\s*(?P<value>[^\r\n]+)",
            text,
            flags=re.IGNORECASE | re.MULTILINE,
        )
        if not match:
            continue
        value = match.group("value").strip()
        size_match = re.search(r"([\d,]+)\s*KB\b", value, re.IGNORECASE)
        if size_match:
            return _parse_int_text(size_match.group(1))
        log.warn(
            f"Actionsite Size value in {path.name} was not parseable; "
            "treating it as not collected."
        )
        return None
    return None


def _path_contains(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False
    except OSError:
        return False


def _unique_existing_dirs(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    out: list[Path] = []
    for path in paths:
        try:
            resolved = path.resolve()
        except OSError:
            continue
        if resolved in seen or not resolved.is_dir():
            continue
        seen.add(resolved)
        out.append(resolved)
    return out


def _loop_context_search_dirs(
    input_file: Path, data_root: Path | None = None
) -> list[Path]:
    current = input_file.resolve(strict=False).parent
    if data_root is not None and _path_contains(data_root, current):
        stop = data_root.resolve(strict=False)
    else:
        stop = next(
            (
                parent
                for parent in [current, *current.parents]
                if parent.name.casefold() == "results"
            ),
            current.parent,
        )

    roots: list[Path] = []
    while True:
        roots.append(current)
        if current == stop:
            break
        parent = current.parent
        if parent == current:
            break
        current = parent
    if data_root is not None:
        roots.extend([data_root, data_root / "Results"])

    search_dirs: list[Path] = []
    for root in roots:
        search_dirs.extend(
            [
                root,
                root / "Client_Loop",
                root / "Results" / "Client_Loop",
                root / "Deployment_Information",
                root / "Results" / "Deployment_Information",
            ]
        )
    return _unique_existing_dirs(search_dirs)


def discover_deployment_info_folder(
    input_file: Path, data_root: Path | None = None
) -> Path | None:
    """Find Deployment_Information near the loop input file when available."""
    candidates: list[Path] = []
    for folder in _loop_context_search_dirs(input_file, data_root):
        if folder.name.casefold() == "deployment_information":
            return folder.resolve()
        candidates.extend(
            [
                folder / "Deployment_Information",
                folder / "Results" / "Deployment_Information",
            ]
        )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate.resolve()

    return None


def _header_columns(path: Path) -> list[str]:
    """First-row column names from a CSV file or a BESAPI .xml capture."""
    if path.suffix.lower() == ".xml":
        sampled = sample_capture_lines(path, 1)
        if not sampled:
            return []
        return next(csv.reader([sampled[0]]), [])
    try:
        df = pd.read_csv(path, nrows=1)
    except Exception:
        return []
    return [str(column) for column in df.columns]


def _is_loop_offenders_csv(path: Path) -> bool:
    columns = _header_columns(path)
    return "Result" in columns and (
        "TotalClientProcessingSeconds" in columns
        or "TotalClientEvaluationSeconds" in columns
        or "ClientProcessingSeconds" in columns
        or "ClientEvaluationSeconds" in columns
        or "Occurrences" in columns
    )


def _is_loop_evaluation_times_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix in {".csv", ".xml"} and _is_loop_offenders_csv(path):
        return True

    if suffix not in {".txt", ".log", ".csv", ".xml"}:
        return False

    if suffix == ".xml":
        lines = sample_capture_lines(path, 50)
    else:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                lines = list(itertools.islice(handle, 50))
        except OSError:
            return False

    return any(
        parse_evaluation_time_line(line.rstrip("\r\n")) is not None for line in lines
    )


def discover_loop_offenders_file(
    input_file: Path, data_root: Path | None = None
) -> Path | None:
    """Find client evaluation timing/offender data near the loop input file."""
    patterns = [
        "*top10-query-results*.csv",
        "*top10*.csv",
        "*top10*.txt",
        "*top10*.xml",
        "*property-query-results*.csv",
        "*property-query-results*.txt",
        "*evaluation*time*.txt",
        "*evaluation*time*.log",
        "*property*evaluation*.txt",
        "*property*evaluation*.log",
        "*loop*offender*.csv",
        "*loop*offender*.txt",
        "*top*offender*.csv",
        "*top*offender*.txt",
    ]
    candidates: list[Path] = []

    for parent in _loop_context_search_dirs(input_file, data_root):
        for pattern in patterns:
            candidates.extend(p for p in parent.glob(pattern) if p.is_file())

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(
        key=lambda p: (
            "-detail" in p.stem.lower(),
            -p.stat().st_mtime,
            p.name,
        )
    )

    for candidate in candidates:
        if _is_loop_evaluation_times_file(candidate):
            return candidate.resolve()

    return None


def _is_udp_notifications_file(path: Path) -> bool:
    if path.suffix.lower() not in {".csv", ".xml"}:
        return False

    columns = {str(column).strip().casefold() for column in _header_columns(path)}
    return (
        bool(columns & {"computer name", "computername", "computer"})
        and bool(
            columns
            & {
                "ip address",
                "ip addresses",
                "ipaddress",
                "ipaddresses",
                "ipv4 address",
                "ipv4 addresses",
                "ipv4address",
                "ipv4addresses",
                "ip",
            }
        )
        and "relay" in columns
        and bool(
            columns
            & {
                "receiving udp pings",
                "platform health check - receiving udp pings",
                "udp pings",
            }
        )
    )


def discover_udp_notifications_file(
    input_file: Path, data_root: Path | None = None
) -> Path | None:
    """Find UDP notification coverage data near the loop input file."""
    patterns = [
        "*udp-notification*.csv",
        "*udp_notification*.csv",
        "*udp-notification*.xml",
        "*udp_notification*.xml",
        "*udp-ping*.csv",
        "*udp_ping*.csv",
        "*receiving*udp*.csv",
    ]
    candidates: list[Path] = []

    for parent in _loop_context_search_dirs(input_file, data_root):
        for pattern in patterns:
            candidates.extend(p for p in parent.glob(pattern) if p.is_file())

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda p: (-p.stat().st_mtime, p.name))

    for candidate in candidates:
        if _is_udp_notifications_file(candidate):
            return candidate.resolve()

    return None


def parse_actionsite_pressure(folder: Path | None) -> ActionSitePressure | None:
    if folder is None:
        return None

    if not folder.is_dir():
        return None

    content_patterns = ["Content_Info*.xml", "Content_Info*.log", "Content_Info*"]
    fixlets_relevant, fixlets_total = _first_int_pair_from_latest_file(
        folder,
        content_patterns,
        r"Number of Fixlets\s*:\s*([\d,]+)\s*/\s*([\d,]+)",
    )
    tasks_relevant, tasks_total = _first_int_pair_from_latest_file(
        folder,
        content_patterns,
        r"Number of Tasks\s*:\s*([\d,]+)\s*/\s*([\d,]+)",
    )
    analyses_relevant, analyses_total = _first_int_pair_from_latest_file(
        folder,
        content_patterns,
        r"Number of Analyses\s*:\s*([\d,]+)\s*/\s*([\d,]+)",
    )

    return ActionSitePressure(
        deployment_info_folder=folder,
        actionsite_size_kb=_actionsite_size_kb_from_deployment_info(folder),
        master_operator_count=_first_int_from_latest_file(
            folder,
            ["Operator_Info*.xml", "Operator_Info*.log", "Operator_Info*"],
            r"Number of Master Operators\s*:\s*([\d,]+)",
        ),
        master_open_actions=_first_int_from_latest_file(
            folder,
            ["Action_Info*.xml", "Action_Info*.log", "Action_Info*"],
            r"Number of open actions issued by master operators\s*:\s*([\d,]+)",
        ),
        external_site_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of External Sites\s*:\s*([\d,]+)",
        ),
        custom_site_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Custom Sites\s*:\s*([\d,]+)",
        ),
        automatic_computer_group_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Automatic Computer Groups\s*:\s*([\d,]+)",
        ),
        manual_computer_group_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Manual Computer Groups\s*:\s*([\d,]+)",
        ),
        fixlets_relevant_count=fixlets_relevant,
        fixlets_total_count=fixlets_total,
        tasks_relevant_count=tasks_relevant,
        tasks_total_count=tasks_total,
        analyses_relevant_count=analyses_relevant,
        analyses_total_count=analyses_total,
        active_analyses_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Active Analyses\s*:\s*([\d,]+)",
        ),
        properties_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Properties\s*:\s*([\d,]+)",
        ),
        # Tolerant of the label drift in the collection tasks: "Activated"
        # (correct), "Actived" (typo), or "Active" all carry the same relevance
        # and value. Matching any keeps Contributing Factors in agreement with the
        # Property Summary (feedback 3e: was reading 0 by only matching "Active").
        active_properties_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Activ(?:ated|ed|e) Properties\s*:\s*([\d,]+)",
        ),
        custom_properties_count=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Custom Properties\s*:\s*([\d,]+)",
        ),
        master_operator_fixlets=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Master Operator Fixlets\s*:\s*([\d,]+)",
        ),
        master_operator_tasks=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Number of Master Operator Tasks\s*:\s*([\d,]+)",
        ),
        master_operator_fixlets_tasks_total=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Total Number of Master Operator Fixlets and Tasks\s*:\s*([\d,]+)",
        ),
        master_operator_analyses=_first_int_from_latest_file(
            folder,
            content_patterns,
            r"Total Number of Master Operator Analyses\s*:\s*([\d,]+)",
        ),
    )


def actionsite_size_mb(pressure: ActionSitePressure) -> float | None:
    if pressure.actionsite_size_kb is None:
        return None
    return pressure.actionsite_size_kb / 1024.0


def master_operator_custom_content_total(
    pressure: ActionSitePressure,
) -> int | None:
    fixlets_tasks = pressure.master_operator_fixlets_tasks_total
    if fixlets_tasks is None:
        parts = [
            value
            for value in (
                pressure.master_operator_fixlets,
                pressure.master_operator_tasks,
            )
            if value is not None
        ]
        fixlets_tasks = sum(parts) if parts else None

    if fixlets_tasks is None and pressure.master_operator_analyses is None:
        return None

    return (fixlets_tasks or 0) + (pressure.master_operator_analyses or 0)


def format_optional_int(value: int | None) -> str:
    return "Not detected" if value is None else f"{value:,}"


def _sum_if_any(*values: int | None) -> int | None:
    detected = [value for value in values if value is not None]
    return sum(detected) if detected else None


def _count_or_zero(value: int | None) -> str:
    return "0" if value is None else f"{value:,}"


def _total_with_parts(total: int | None, parts: list[str]) -> str:
    if total is None:
        return "Not detected"
    return f"{total:,} total ({', '.join(parts)})"


def _status_for_thresholds(
    checks: list[tuple[float | None, float]],
) -> str:
    detected = [value for value, _threshold in checks if value is not None]
    if not detected:
        return status_spine.NOT_ASSESSED.word
    if any(value > threshold for value, threshold in checks if value is not None):
        return status_spine.NEEDS_ATTENTION.word
    return status_spine.HEALTHY.word


def format_optional_seconds(value: float) -> str:
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _actionsite_status_for_value(value: float | None, threshold: float) -> str:
    if value is None:
        return status_spine.NOT_ASSESSED.word
    if value > threshold:
        return status_spine.NEEDS_ATTENTION.word
    return status_spine.HEALTHY.word


def _actionsite_size_status_for_value(value: float | None, threshold: float) -> str:
    if value is None:
        return status_spine.NOT_ASSESSED.word
    if value > threshold:
        return "Review"
    return status_spine.HEALTHY.word


def _actionsite_custom_content_value(pressure: ActionSitePressure) -> str:
    custom_total = master_operator_custom_content_total(pressure)
    if custom_total is None:
        return "Not detected"

    # Show fixlets, tasks, and analyses individually. Fall back to the combined
    # fixlets+tasks total only when the log doesn't break them out separately.
    if (
        pressure.master_operator_fixlets is not None
        or pressure.master_operator_tasks is not None
    ):
        details = [
            f"{_count_or_zero(pressure.master_operator_fixlets)} fixlets",
            f"{_count_or_zero(pressure.master_operator_tasks)} tasks",
            f"{_count_or_zero(pressure.master_operator_analyses)} analyses",
        ]
    else:
        details = [
            f"{_count_or_zero(pressure.master_operator_fixlets_tasks_total)} fixlets/tasks",
            f"{_count_or_zero(pressure.master_operator_analyses)} analyses",
        ]

    return f"{custom_total:,} total ({', '.join(details)})"


def _subscribed_sites_total(pressure: ActionSitePressure) -> int | None:
    return _sum_if_any(pressure.external_site_count, pressure.custom_site_count)


def _subscribed_sites_value(pressure: ActionSitePressure) -> str:
    return _total_with_parts(
        _subscribed_sites_total(pressure),
        [
            f"{_count_or_zero(pressure.external_site_count)} external",
            f"{_count_or_zero(pressure.custom_site_count)} custom",
        ],
    )


def _computer_groups_total(pressure: ActionSitePressure) -> int | None:
    return _sum_if_any(
        pressure.automatic_computer_group_count,
        pressure.manual_computer_group_count,
    )


def _computer_groups_value(pressure: ActionSitePressure) -> str:
    return _total_with_parts(
        _computer_groups_total(pressure),
        [
            f"{_count_or_zero(pressure.automatic_computer_group_count)} automatic",
            f"{_count_or_zero(pressure.manual_computer_group_count)} manual",
        ],
    )


def _fixlets_tasks_total(pressure: ActionSitePressure) -> int | None:
    return _sum_if_any(pressure.fixlets_total_count, pressure.tasks_total_count)


def _fixlets_tasks_relevant_total(pressure: ActionSitePressure) -> int | None:
    return _sum_if_any(pressure.fixlets_relevant_count, pressure.tasks_relevant_count)


def _fixlets_tasks_value(pressure: ActionSitePressure) -> str:
    total = _fixlets_tasks_total(pressure)
    relevant = _fixlets_tasks_relevant_total(pressure)
    if total is None:
        return "Not detected"
    return (
        f"{_count_or_zero(relevant)} / {total:,} relevant/total "
        f"({_count_or_zero(pressure.fixlets_relevant_count)} / "
        f"{_count_or_zero(pressure.fixlets_total_count)} fixlets, "
        f"{_count_or_zero(pressure.tasks_relevant_count)} / "
        f"{_count_or_zero(pressure.tasks_total_count)} tasks)"
    )


def _analyses_value(pressure: ActionSitePressure) -> str:
    if pressure.analyses_total_count is None and pressure.active_analyses_count is None:
        return "Not detected"
    relevant_total = (
        "not detected"
        if pressure.analyses_total_count is None
        else f"{_count_or_zero(pressure.analyses_relevant_count)} / "
        f"{pressure.analyses_total_count:,} relevant/total"
    )
    return f"{relevant_total}; {_count_or_zero(pressure.active_analyses_count)} active"


def _properties_value(pressure: ActionSitePressure) -> str:
    return _total_with_parts(
        pressure.properties_count,
        [
            f"{_count_or_zero(pressure.active_properties_count)} active",
            f"{_count_or_zero(pressure.custom_properties_count)} custom",
        ],
    )


def actionsite_pressure_rows(pressure: ActionSitePressure) -> list[list[str]]:
    size_mb = actionsite_size_mb(pressure)
    if size_mb is None:
        size_value = "Not detected"
    else:
        size_value = f"{size_mb:,.1f} MB ({pressure.actionsite_size_kb:,} KB)"

    custom_value = _actionsite_custom_content_value(pressure)
    custom_total = master_operator_custom_content_total(pressure)
    if custom_total is None:
        custom_status = status_spine.NOT_ASSESSED.word
    elif custom_total >= 50:
        custom_status = status_spine.NEEDS_ATTENTION.word
    else:
        custom_status = status_spine.HEALTHY.word
    return [
        [
            "ActionSite size",
            size_value,
            _actionsite_size_status_for_value(size_mb, 10.0),
            "Healthy at 10 MB or below; review when over 10 MB.",
        ],
        [
            "Subscribed sites",
            _subscribed_sites_value(pressure),
            _status_for_thresholds([(_subscribed_sites_total(pressure), 100)]),
            "Healthy at 100 or fewer; review when over 100.",
        ],
        [
            "Computer groups",
            _computer_groups_value(pressure),
            _status_for_thresholds([(_computer_groups_total(pressure), 100)]),
            "Healthy at 100 or fewer; review when over 100.",
        ],
        [
            "Fixlets and tasks",
            _fixlets_tasks_value(pressure),
            _status_for_thresholds([(_fixlets_tasks_total(pressure), 80_000)]),
            "Healthy at 80,000 total or fewer; review when over 80,000.",
        ],
        [
            "Analyses",
            _analyses_value(pressure),
            _status_for_thresholds(
                [
                    (pressure.analyses_total_count, 10_000),
                    (pressure.active_analyses_count, 500),
                ]
            ),
            "Healthy at 10,000 total or fewer and 500 active or fewer; review if either is over threshold.",
        ],
        [
            "Properties",
            _properties_value(pressure),
            _status_for_thresholds(
                [
                    (pressure.properties_count, 10_000),
                    (pressure.active_properties_count, 500),
                ]
            ),
            "Healthy at 10,000 total or fewer and 500 active or fewer; review if either is over threshold.",
        ],
        [
            "Master operators",
            format_optional_int(pressure.master_operator_count),
            _actionsite_status_for_value(pressure.master_operator_count, 5),
            "Healthy at 5 or fewer; review when over 5.",
        ],
        [
            "Open actions issued by master operators",
            format_optional_int(pressure.master_open_actions),
            _actionsite_status_for_value(pressure.master_open_actions, 25),
            "Healthy at 25 or fewer; review when over 25.",
        ],
        [
            "Master-operator fixlets/tasks/analyses",
            custom_value,
            custom_status,
            "Healthy below 50 combined; review at 50 or more.",
        ],
    ]


def _float_from_row(row: pd.Series, *names: str) -> float:
    for name in names:
        if name in row and not pd.isna(row[name]):
            try:
                return float(str(row[name]).replace(",", "").strip())
            except ValueError:
                continue
    return 0.0


def _int_from_row(row: pd.Series, *names: str) -> int:
    for name in names:
        if name in row and not pd.isna(row[name]):
            try:
                return int(float(str(row[name]).replace(",", "").strip()))
            except ValueError:
                continue
    return 0


def get_background_evaluation_result(site_name: str) -> str:
    site_text = site_name.strip()
    if site_text.startswith("CustomSite_"):
        return (
            "Background Evaluation of Custom Site: "
            f"{site_text.removeprefix('CustomSite_')}"
        )

    return f"Background Evaluation of External Site: {site_text}"


def parse_loop_lookup_result(lookup_text: str) -> str:
    match = re.match(
        r"^(?P<site>.+)\.(?P<analysis_id>\d+):(?P<property>.+)$",
        lookup_text.strip(),
    )
    if not match:
        return lookup_text.strip()

    site = match.group("site").strip()
    prop = match.group("property").strip()

    if prop.lower() == "background evaluation":
        return get_background_evaluation_result(site)

    if site.startswith("CustomSite_"):
        site_text = site.removeprefix("CustomSite_")
        site_kind = "Custom Site"
    else:
        site_text = site
        site_kind = "External Site"

    return f"{prop} of {site_kind}: {site_text}"


def parse_evaluation_time_line(line: str) -> dict[str, Any] | None:
    clean = str(line or "").strip().strip('"').strip()
    if not clean:
        return None

    if re.match(r"^Count\s+Percentage\s+Result$", clean, flags=re.IGNORECASE):
        return None

    match = re.match(
        r'^(?:"?(?P<count>\d+)"?[,\s]+)?'
        r'(?:"?(?P<percentage>\d+(?:\.\d+)?%)"?[,\s]+)?'
        r'"?(?P<seconds>\d+(?:\.\d+)?):\s*(?P<lookup>.+?)"?\s*$',
        clean,
    )
    if not match:
        return None

    seconds = float(match.group("seconds"))
    lookup = match.group("lookup").strip()

    return {
        "ClientProcessingSeconds": seconds,
        "Result": parse_loop_lookup_result(lookup),
    }


def load_evaluation_times_input(path: Path) -> pd.DataFrame:
    rows = []
    for line in read_capture_or_log_text(path).splitlines():
        row = parse_evaluation_time_line(line)
        if row is not None:
            rows.append(row)

    return pd.DataFrame(rows)


def aggregate_loop_offenders(
    df: pd.DataFrame, top_count: int = 10
) -> list[LoopOffenderSummary]:
    if "Result" not in df.columns:
        return []

    if (
        "TotalClientProcessingSeconds" in df.columns
        or "TotalClientEvaluationSeconds" in df.columns
        or "AvgClientProcessingSeconds" in df.columns
        or "AvgClientEvaluationSeconds" in df.columns
    ):
        rows: list[LoopOffenderSummary] = []
        for _, row in df.iterrows():
            result = str(row.get("Result", "")).strip()
            if not result:
                continue
            occurrences = _int_from_row(row, "Occurrences", "Count")
            total_seconds = _float_from_row(
                row,
                "TotalClientProcessingSeconds",
                "TotalClientEvaluationSeconds",
            )
            avg_seconds = _float_from_row(
                row,
                "AvgClientProcessingSeconds",
                "AvgClientEvaluationSeconds",
            )
            if avg_seconds <= 0 and total_seconds > 0 and occurrences > 0:
                avg_seconds = total_seconds / occurrences
            if total_seconds <= 0 and avg_seconds > 0 and occurrences > 0:
                total_seconds = avg_seconds * occurrences
            rows.append(
                LoopOffenderSummary(
                    rank=0,
                    occurrences=occurrences,
                    total_client_processing_seconds=total_seconds,
                    max_client_processing_seconds=_float_from_row(
                        row,
                        "MaxClientProcessingSeconds",
                        "MaxClientEvaluationSeconds",
                    ),
                    avg_client_processing_seconds=avg_seconds,
                    result=result,
                )
            )
    elif (
        "ClientProcessingSeconds" in df.columns or "ClientEvaluationSeconds" in df.columns
    ):
        rows = []
        for result, group in df.groupby("Result", dropna=True):
            result_text = str(result).strip()
            if not result_text:
                continue
            seconds = [
                _float_from_row(row, "ClientProcessingSeconds", "ClientEvaluationSeconds")
                for _, row in group.iterrows()
            ]
            total = sum(seconds)
            occurrences = len(seconds)
            rows.append(
                LoopOffenderSummary(
                    rank=0,
                    occurrences=occurrences,
                    total_client_processing_seconds=total,
                    max_client_processing_seconds=max(seconds) if seconds else 0.0,
                    avg_client_processing_seconds=total / occurrences
                    if occurrences
                    else 0.0,
                    result=result_text,
                )
            )
    elif "Occurrences" in df.columns:
        rows = []
        for _, row in df.iterrows():
            result = str(row.get("Result", "")).strip()
            if not result:
                continue
            occurrences = _int_from_row(row, "Occurrences", "Count")
            rows.append(
                LoopOffenderSummary(
                    rank=0,
                    occurrences=occurrences,
                    total_client_processing_seconds=float(occurrences),
                    max_client_processing_seconds=0.0,
                    avg_client_processing_seconds=0.0,
                    result=result,
                )
            )
    else:
        return []

    rows.sort(
        key=lambda item: (
            -item.avg_client_processing_seconds,
            -item.total_client_processing_seconds,
            -item.occurrences,
            item.result,
        )
    )

    if top_count > 0:
        rows = rows[:top_count]

    for idx, row in enumerate(rows, start=1):
        row.rank = idx

    return rows


def load_loop_offenders(
    offenders_file: Path | None, top_count: int = 10
) -> list[LoopOffenderSummary]:
    if offenders_file is None:
        return []

    if not offenders_file.is_file():
        return []

    df: pd.DataFrame
    suffix = offenders_file.suffix.lower()
    if suffix in {".csv", ".xml"}:
        try:
            if suffix == ".xml":
                df = pd.read_csv(io.StringIO(read_capture_or_log_text(offenders_file)))
            else:
                df = pd.read_csv(offenders_file)
        except Exception:
            df = load_evaluation_times_input(offenders_file)
        else:
            if "Result" not in df.columns:
                df = load_evaluation_times_input(offenders_file)
    else:
        df = load_evaluation_times_input(offenders_file)

    return aggregate_loop_offenders(df, top_count=top_count)


def format_loop_offender_seconds(seconds: float | None) -> str:
    try:
        seconds_float = float(seconds)
    except (TypeError, ValueError):
        return "Not available"
    if math.isnan(seconds_float) or seconds_float <= 0:
        return "Not available"
    return f"{seconds_float:,.3f}".rstrip("0").rstrip(".")


def format_loop_offender_strip_seconds(seconds: float | None) -> str:
    try:
        seconds_float = float(seconds)
    except (TypeError, ValueError):
        return "Not available"
    if math.isnan(seconds_float) or seconds_float <= 0:
        return "Not available"
    return f"{seconds_float:,.1f} s"


def compact_loop_offender_label(result: str, limit: int = 56) -> str:
    text = str(result or "").strip()
    for pattern in (
        r"^Background Evaluation of External Site:\s*",
        r"^Background Evaluation of Custom Site:\s*",
        r"^Evaluate Property \d+ of External Site:\s*",
        r"^Evaluate Property \d+ of Custom Site:\s*",
    ):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    display_name = re.search(r"Display Name=([^|]+)", text)
    if display_name:
        text = display_name.group(1).strip()
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        return f"{text[: limit - 3].rstrip()}..."
    return text or "Not available"


def _column_lookup(df: pd.DataFrame, *names: str) -> str | None:
    wanted = {name.casefold() for name in names}
    for column in df.columns:
        if str(column).strip().casefold() in wanted:
            return str(column)
    return None


def parse_udp_receiving(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    text = str(value).strip().casefold()
    if not text or text in {"nan", "none", "not reported", "error"}:
        return None
    if text in {"true", "yes", "1", "receiving", "received"}:
        return True
    if text in {"false", "no", "0", "not receiving", "not received"}:
        return False
    if "does not exist" in text or "duplicate" in text:
        return None
    return None


def normalize_relay_name(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.casefold() in {"nan", "none", "not reported"}:
        return "Not reported"
    if "://" in text:
        parsed = urlparse(text)
        if parsed.hostname:
            return parsed.hostname
    text = text.split(";")[0].strip()
    if "/" in text:
        text = text.split("/", 1)[0].strip()
    if ":" in text and not re.match(r"^\[[0-9a-fA-F:]+\]", text):
        text = text.split(":", 1)[0].strip()
    return text or "Not reported"


def ipv4_subnet_24(value: Any) -> str:
    text = str(value or "")
    for match in re.finditer(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text):
        try:
            ip = ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        if ip.version != 4 or ip.is_loopback or ip.is_unspecified:
            continue
        return str(ipaddress.ip_network(f"{ip}/24", strict=False))
    return "Unknown"


def _normalized_column_key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


def _column_lookup_normalized(df: pd.DataFrame, names: tuple[str, ...]) -> str | None:
    wanted = {_normalized_column_key(name) for name in names}
    for column in df.columns:
        if _normalized_column_key(column) in wanted:
            return str(column)
    return None


def auto_detect_command_polling_columns(
    df: pd.DataFrame,
) -> tuple[str | None, str | None]:
    """Find command polling columns from the 2.0 agent counter analysis."""
    return (
        _column_lookup_normalized(df, COMMAND_POLLING_ENABLED_COLUMN_NAMES),
        _column_lookup_normalized(df, COMMAND_POLLING_INTERVAL_COLUMN_NAMES),
    )


def auto_detect_fast_hash_verify_columns(
    df: pd.DataFrame,
) -> tuple[str | None, str | None, str | None]:
    """Find FastHashVerify columns from the 2.0 agent counter analysis."""
    return (
        _column_lookup_normalized(df, FAST_HASH_VERIFY_ENABLED_COLUMN_NAMES),
        _column_lookup_normalized(df, FAST_HASH_VERIFY_WORK_COLUMN_NAMES),
        _column_lookup_normalized(df, FAST_HASH_VERIFY_SLEEP_COLUMN_NAMES),
    )


def auto_detect_agent_multicore_scaling_column(df: pd.DataFrame) -> str | None:
    """Find the 11.0.7 agent multicore switch column."""
    return _column_lookup_normalized(df, AGENT_MULTICORE_SCALING_COLUMN_NAMES)


def auto_detect_agent_total_physical_cpu_core_count_column(
    df: pd.DataFrame,
) -> str | None:
    """Find the total physical CPU core count column."""
    return _column_lookup_normalized(df, AGENT_TOTAL_PHYSICAL_CPU_CORE_COUNT_COLUMN_NAMES)


def auto_detect_agent_cpu_idle_columns(
    df: pd.DataFrame,
) -> tuple[str | None, str | None]:
    """Find the client CPU idle setting columns."""
    return (
        _column_lookup_normalized(df, AGENT_CPU_WORK_IDLE_COLUMN_NAMES),
        _column_lookup_normalized(df, AGENT_CPU_SLEEP_IDLE_COLUMN_NAMES),
    )


def auto_detect_udp_receiving_column(df: pd.DataFrame) -> str | None:
    return _column_lookup_normalized(
        df,
        (
            "Receiving UDP Pings",
            "Platform Health Check - Receiving UDP Pings",
            "UDP Pings",
        ),
    )


def parse_command_polling_enabled(value: Any) -> str:
    if value is None:
        return "Not Set"
    try:
        if pd.isna(value):
            return "Not Set"
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    folded = text.casefold()
    if not folded or folded in {"nan", "none", "not set", "not reported"}:
        return "Not Set"
    if folded in {"1", "true", "yes", "enabled", "enable"}:
        return "Enabled"
    if folded in {"0", "false", "no", "disabled", "disable", "not enabled"}:
        return "Disabled"
    if "does not exist" in folded or "duplicate" in folded or "error" in folded:
        return "Unknown"
    return "Unknown"


def parse_fast_hash_verify_enabled(value: Any) -> str:
    """Normalize the FastHashVerify boolean while preserving an unset state."""
    if value is None:
        return "Not Set"
    try:
        if pd.isna(value):
            return "Not Set"
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    folded = text.casefold()
    if not folded or folded in {"nan", "none", "not set", "not reported"}:
        return "Not Set"
    if folded in {"1", "true", "yes", "enabled", "enable"}:
        return "Enabled"
    if folded in {"0", "false", "no", "disabled", "disable"}:
        return "Disabled"
    if "does not exist" in folded or "duplicate" in folded or "error" in folded:
        return "Unknown"
    return "Unknown"


def display_fast_hash_verify_ms(value: Any) -> str:
    """Display a FastHashVerify work/sleep value with its documented unit."""
    if value is None:
        return "Not Set"
    try:
        if pd.isna(value):
            return "Not Set"
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    folded = text.casefold()
    if not folded or folded in {"nan", "none", "not set", "not reported"}:
        return "Not Set"
    if "does not exist" in folded or "duplicate" in folded or "error" in folded:
        return "Unknown"
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return f"{float(text):g} ms"
    return text


def display_client_setting(value: Any) -> str:
    """Return an unmodified client setting value with explicit empty states."""
    if value is None:
        return "Not Set"
    try:
        if pd.isna(value):
            return "Not Set"
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    folded = text.casefold()
    if not folded or folded in {"nan", "none", "not set", "not reported"}:
        return "Not Set"
    if "does not exist" in folded or "duplicate" in folded or "error" in folded:
        return "Unknown"
    return text


def parse_agent_multicore_scaling(value: Any) -> str:
    """Normalize the supported multicore switch without inferring a default."""
    setting = display_client_setting(value)
    if setting in {"Not Set", "Not Applicable", "Unknown"}:
        return setting
    if setting.casefold() in {"1", "true", "yes", "on", "enabled", "enable"}:
        return "On"
    if setting.casefold() in {"0", "false", "no", "off", "disabled", "disable"}:
        return "Off"
    return "Unknown"


def configured_cpu_duty_cycle(work: str, sleep: str) -> str:
    """Return the configured work-time share without inferring client defaults."""
    values = (work, sleep)
    if values == ("Not Applicable", "Not Applicable"):
        return "Not Applicable"
    if any(value == "Unknown" for value in values):
        return "Unknown"
    if any(value in {"", "Not Set"} for value in values):
        return "Not Set"

    parsed: list[float] = []
    for value in values:
        match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(?:ms)?", value, re.IGNORECASE)
        if not match:
            return "Unknown"
        parsed.append(float(match.group(1)))

    total = sum(parsed)
    if total <= 0:
        return "Unknown"
    return f"{parsed[0] / total * 100:.1f}%"


def is_command_polling_minutes_column(column_name: str | None) -> bool:
    """Return whether the collected command-polling value is expressed in minutes."""
    return "minute" in str(column_name or "").casefold()


def parse_command_polling_interval_seconds(
    value: Any, column_name: str | None = None
) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass

    text = str(value).strip()
    if not text:
        return None
    if text.casefold() in {
        "nan",
        "none",
        "not set",
        "not reported",
        "not enabled",
        "disabled",
    }:
        return None

    if is_command_polling_minutes_column(column_name):
        try:
            minutes = float(text)
        except ValueError:
            return None
        return max(0, int(round(minutes * 60)))

    seconds = convert_to_seconds(text, "Command Polling Interval Seconds")
    if seconds is None:
        return None
    return max(0, int(round(seconds)))


def format_command_polling_interval(seconds: int | float | None) -> str:
    if seconds is None:
        return "Not Set"
    seconds_int = int(round(float(seconds)))
    if seconds_int <= 0:
        return "0 sec"
    if seconds_int % 3600 == 0:
        hours = seconds_int // 3600
        unit = "hour" if hours == 1 else "hours"
        return f"{hours:,} {unit} ({seconds_int:,} sec)"
    if seconds_int % 60 == 0:
        minutes = seconds_int // 60
        unit = "min" if minutes == 1 else "min"
        return f"{minutes:,} {unit} ({seconds_int:,} sec)"
    return f"{seconds_int:,} sec"


def display_command_polling_interval(
    raw_value: Any, seconds: int | None, status: str, column_name: str | None = None
) -> str:
    if status == "Disabled":
        return "Not Enabled"
    text = str(raw_value or "").strip()
    if not text or text.casefold() in {"nan", "none"}:
        return "Not Set" if status == "Enabled" else ""
    if seconds is not None:
        if is_command_polling_minutes_column(column_name):
            return f"{seconds / 60:g} min"
        return format_command_polling_interval(seconds)
    return text


def suggested_command_polling_seconds(avg_loop_seconds: float) -> int:
    return max(
        0,
        int(math.ceil(float(avg_loop_seconds) + COMMAND_POLLING_HEADROOM_SECONDS)),
    )


def is_udp_not_receiving(value: Any) -> bool:
    return parse_udp_receiving(value) is False


def load_udp_notification_summary(path: Path | None) -> UdpNotificationSummary | None:
    if path is None or not path.is_file():
        return None

    try:
        if path.suffix.lower() == ".xml":
            df = pd.read_csv(io.StringIO(read_capture_or_log_text(path)))
        else:
            df = pd.read_csv(path)
    except Exception:
        return None

    computer_col = _column_lookup(df, "Computer Name", "ComputerName", "Computer")
    ip_col = _column_lookup(
        df,
        "IP Address",
        "IP Addresses",
        "IPAddress",
        "IPAddresses",
        "IPv4 Address",
        "IPv4 Addresses",
        "IPv4Address",
        "IPv4Addresses",
        "IP",
    )
    relay_col = _column_lookup(df, "Relay")
    udp_col = _column_lookup(
        df,
        "Receiving UDP Pings",
        "Platform Health Check - Receiving UDP Pings",
        "UDP Pings",
    )
    if not all([computer_col, ip_col, relay_col, udp_col]):
        return None

    rows: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        status = parse_udp_receiving(row.get(udp_col))
        rows.append(
            {
                "computer": str(row.get(computer_col, "")).strip(),
                "ip": str(row.get(ip_col, "")).strip(),
                "relay": normalize_relay_name(row.get(relay_col)),
                "status": status,
                "subnet": ipv4_subnet_24(row.get(ip_col)),
            }
        )

    total = len(rows)
    receiving = sum(1 for row in rows if row["status"] is True)
    not_receiving = sum(1 for row in rows if row["status"] is False)
    unknown = total - receiving - not_receiving

    relay_rows: list[list[str]] = []
    relay_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        relay_groups.setdefault(row["relay"], []).append(row)
    missing_relay = sum(
        1 for row in rows if row["status"] is False and row["relay"] == "Not reported"
    )
    missing_subnet = sum(
        1 for row in rows if row["status"] is False and row["subnet"] == "Unknown"
    )
    missing_rollup_data = sum(
        1
        for row in rows
        if row["status"] is False
        and (row["relay"] == "Not reported" or row["subnet"] == "Unknown")
    )

    for relay, group in relay_groups.items():
        if relay == "Not reported":
            continue
        reported = [row for row in group if row["status"] is not None]
        failing = [row for row in group if row["status"] is False]
        if not failing:
            continue
        failing_count = len(failing)
        reported_count = len(reported)
        pct_value = (len(failing) / len(reported)) if reported else 0.0
        relay_rows.append(
            [
                relay,
                f"{failing_count:,} / {reported_count:,}",
                f"{pct_value * 100:.1f}%",
            ]
        )
    relay_rows.sort(
        key=lambda row: (
            -int(row[1].split("/", 1)[0].replace(",", "").strip()),
            -float(row[2].rstrip("%")),
            row[0].casefold(),
        )
    )
    relay_rows = relay_rows[:10]

    subnet_reported_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] is not None and row["subnet"] != "Unknown":
            subnet_reported_groups.setdefault(row["subnet"], []).append(row)
    subnet_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row["status"] is False and row["subnet"] != "Unknown":
            subnet_groups.setdefault(row["subnet"], []).append(row)
    subnet_rows: list[list[str]] = []
    for subnet, group in subnet_groups.items():
        relays = sorted({row["relay"] for row in group if row["relay"]})
        reported_count = len(subnet_reported_groups.get(subnet, []))
        subnet_rows.append(
            [
                subnet,
                f"{len(group):,} / {reported_count:,}",
                "; ".join(relays[:3]) if relays else "Not reported",
            ]
        )
    subnet_rows.sort(
        key=lambda row: (
            -int(row[1].split("/", 1)[0].replace(",", "").strip()),
            row[0].casefold(),
        )
    )
    subnet_rows = subnet_rows[:10]

    return UdpNotificationSummary(
        source_file=path,
        total_devices=total,
        receiving_count=receiving,
        not_receiving_count=not_receiving,
        unknown_count=unknown,
        relay_rows=relay_rows,
        subnet_rows=subnet_rows,
        rows=rows,
        not_receiving_missing_relay_count=missing_relay,
        not_receiving_missing_subnet_count=missing_subnet,
        not_receiving_missing_rollup_data_count=missing_rollup_data,
    )


def count_with_denominator(count: int, total: int) -> str:
    return f"{count:,} / {total:,}"


def udp_coverage_rows(summary: UdpNotificationSummary) -> list[list[str]]:
    total = summary.total_devices
    denominator = total if total else 1
    return [
        [
            "Receiving UDP Pings",
            count_with_denominator(summary.receiving_count, total),
            pct(summary.receiving_count / denominator),
        ],
        [
            "Not Receiving UDP Pings",
            count_with_denominator(summary.not_receiving_count, total),
            pct(summary.not_receiving_count / denominator),
        ],
        [
            "Not Reported / Error",
            count_with_denominator(summary.unknown_count, total),
            pct(summary.unknown_count / denominator),
        ],
    ]


def udp_notification_data_notes(summary: UdpNotificationSummary) -> list[str]:
    notes: list[str] = []
    if summary.not_receiving_count == 0:
        notes.append(
            "No clients in the UDP notification data reported that they were not "
            "receiving UDP pings, so relay and subnet issue rollups were not generated."
        )
        return notes
    if (
        summary.not_receiving_missing_relay_count
        and summary.not_receiving_missing_subnet_count
    ):
        missing_count = summary.not_receiving_missing_rollup_data_count or max(
            summary.not_receiving_missing_relay_count,
            summary.not_receiving_missing_subnet_count,
        )
        notes.append(
            f"{missing_count:,} client(s) not receiving UDP pings did not report a "
            "relay and/or IPv4 address, and were excluded from the corresponding "
            "rollups."
        )
    elif summary.not_receiving_missing_relay_count:
        notes.append(
            f"{summary.not_receiving_missing_relay_count:,} client(s) not receiving "
            "UDP pings did not report a relay, so they were excluded from the relay "
            "issue rollup."
        )
    elif summary.not_receiving_missing_subnet_count:
        notes.append(
            f"{summary.not_receiving_missing_subnet_count:,} client(s) not receiving "
            "UDP pings did not report an IPv4 address, so they were excluded from "
            "the IPv4 /24 subnet issue rollup."
        )
    if not summary.relay_rows:
        notes.append(
            "No relay issue rollup was generated because the clients not receiving "
            "UDP pings did not include usable relay data."
        )
    if not summary.subnet_rows:
        notes.append(
            "No subnet issue rollup was generated because the clients not receiving "
            "UDP pings did not include usable IPv4 address data."
        )
    return notes


def command_polling_coverage_rows(
    summary: CommandPollingSummary,
) -> list[list[str]]:
    total = summary.total_devices
    denominator = total if total else 1
    return [
        [
            "Command Polling Enabled",
            count_with_denominator(summary.enabled_count, total),
            pct(summary.enabled_count / denominator),
        ],
        [
            "Command Polling Disabled",
            count_with_denominator(summary.disabled_count, total),
            pct(summary.disabled_count / denominator),
        ],
        [
            "Command Polling Not Set",
            count_with_denominator(summary.not_set_count, total),
            pct(summary.not_set_count / denominator),
        ],
        [
            "Command Polling Unknown",
            count_with_denominator(summary.unknown_count, total),
            pct(summary.unknown_count / denominator),
        ],
        [
            "Enabled with Missing Interval",
            count_with_denominator(summary.enabled_missing_interval_count, total),
            pct(summary.enabled_missing_interval_count / denominator),
        ],
        [
            "Interval Below Average Loop",
            count_with_denominator(summary.interval_below_loop_count, total),
            pct(summary.interval_below_loop_count / denominator),
        ],
        [
            "No UDP and Polling Disabled/Not Set",
            count_with_denominator(summary.no_udp_polling_gap_count, total),
            pct(summary.no_udp_polling_gap_count / denominator),
        ],
    ]


def resolve_existing_folder(candidate_text: str) -> Path:
    """
    Resolve an output folder from either:
      - a full path, such as C:\\Temp\\Reports
      - a relative path, such as .\\Reports
      - a simple folder name under the current working folder
      - blank, which means use the current working folder
    """
    candidate_text = clean_user_path(candidate_text)

    if not candidate_text:
        return Path.cwd().resolve()

    candidate = Path(candidate_text).expanduser()
    display_path = candidate.resolve(strict=False)

    if not candidate.exists():
        message = [
            "Output folder was not found.",
            f"Entered value : {candidate_text}",
            f"Checked path  : {display_path}",
        ]

        if not candidate.is_absolute():
            message.append(f"Current folder: {Path.cwd()}")
            message.append(
                "Tip: Enter a folder name in this folder, or enter a full folder path."
            )

        raise ValueError("\n".join(message))

    if not candidate.is_dir():
        raise ValueError(
            "Output destination is not a folder.\n"
            f"Entered value : {candidate_text}\n"
            f"Checked path  : {display_path}"
        )

    return candidate.resolve()


def prompt_for_report_date(label: str, current_value: str | None) -> date | None:
    """Return a parsed date when the consultant supplied one, or None.

    Report dates are optional: the UI's date pickers explicitly advertise
    "Leave blank to use the full data range," so when the value is absent we
    return None rather than prompting on stdin. (The old behavior prompted,
    which dead-locked the builder subprocess with an EOF error because the
    UI doesn't connect stdin to the child.) Invalid non-empty values still
    raise so a typo isn't silently swallowed.
    """
    if not current_value:
        return None
    parsed = convert_to_report_date_or_none(current_value)
    if parsed is None:
        raise ValueError(f"{label} could not be parsed as a date: {current_value}")
    return parsed


# ---------------------------------------------------------------------------
# Column detection
#
# The input workbook column names are not standardized, different BigFix
# analyses use different headers. auto_detect_columns() tries to identify the
# three required columns (computer name, maximum loop time, average loop time)
# by matching common keywords against column names.
#
# Fall-back heuristic: if keyword matching fails, positional assignment is
# used (col 0 = max, col 1 = avg for 2-column workbooks; col 0 = name, col 1
# = max, col 2 = avg for 3+ column workbooks).
# ---------------------------------------------------------------------------
def auto_detect_columns(df: pd.DataFrame) -> tuple[str | None, str, str]:
    columns = [str(c) for c in df.columns]
    if len(columns) < 2:
        raise ValueError("Workbook must contain at least 2 columns.")

    def first_matching(pattern: str) -> str | None:
        regex = re.compile(pattern, re.IGNORECASE)
        return next((c for c in columns if regex.search(c)), None)

    computer_column = first_matching(r"computer|hostname|device|endpoint|machine")
    max_column = first_matching(r"max|maximum")
    avg_column = first_matching(r"avg|average")

    if not max_column or not avg_column:
        if len(columns) == 2:
            max_column = columns[0]
            avg_column = columns[1]
        elif len(columns) >= 3:
            if not computer_column:
                computer_column = columns[0]
            max_column = columns[1]
            avg_column = columns[2]

    if not max_column or not avg_column:
        raise ValueError(
            "Could not determine maximum and average loop columns. "
            "Expected names like 'Maximum cycle seconds' and 'Average cycle seconds'."
        )

    return computer_column, max_column, avg_column


def process_rows(
    df: pd.DataFrame,
    computer_column: str | None,
    max_column: str,
    avg_column: str,
    udp_data: dict[str, dict[str, str]] | None = None,
    command_polling_enabled_column: str | None = None,
    command_polling_interval_column: str | None = None,
    fast_hash_verify_enabled_column: str | None = None,
    fast_hash_verify_work_column: str | None = None,
    fast_hash_verify_sleep_column: str | None = None,
    agent_multicore_scaling_column: str | None = None,
    agent_total_physical_cpu_core_count_column: str | None = None,
    agent_cpu_work_idle_column: str | None = None,
    agent_cpu_sleep_idle_column: str | None = None,
) -> tuple[list[ProcessedRow], int, int]:
    processed: list[ProcessedRow] = []
    not_reported_count = 0
    error_count = 0
    inline_udp_column = auto_detect_udp_receiving_column(df)
    if not command_polling_enabled_column and not command_polling_interval_column:
        command_polling_enabled_column, command_polling_interval_column = (
            auto_detect_command_polling_columns(df)
        )
    if not any(
        (
            fast_hash_verify_enabled_column,
            fast_hash_verify_work_column,
            fast_hash_verify_sleep_column,
        )
    ):
        (
            fast_hash_verify_enabled_column,
            fast_hash_verify_work_column,
            fast_hash_verify_sleep_column,
        ) = auto_detect_fast_hash_verify_columns(df)
    if not agent_multicore_scaling_column:
        agent_multicore_scaling_column = auto_detect_agent_multicore_scaling_column(df)
    if not agent_total_physical_cpu_core_count_column:
        agent_total_physical_cpu_core_count_column = (
            auto_detect_agent_total_physical_cpu_core_count_column(df)
        )
    if not agent_cpu_work_idle_column and not agent_cpu_sleep_idle_column:
        agent_cpu_work_idle_column, agent_cpu_sleep_idle_column = (
            auto_detect_agent_cpu_idle_columns(df)
        )

    for _, row in df.iterrows():
        max_sec = convert_to_seconds(row.get(max_column), max_column)
        avg_sec = convert_to_seconds(row.get(avg_column), avg_column)
        computer_name = ""
        if computer_column:
            raw_name = row.get(computer_column)
            if raw_name is not None and not pd.isna(raw_name):
                computer_name = str(raw_name)

        if max_sec is not None and avg_sec is not None:
            receiving_udp = ""
            relay = ""
            subnet = ""
            if udp_data and computer_name in udp_data:
                udp_row = udp_data[computer_name]
                receiving_udp = udp_row.get("receiving", "")
                relay = udp_row.get("relay", "")
                subnet = udp_row.get("subnet", "")
            elif inline_udp_column:
                udp_status = parse_udp_receiving(row.get(inline_udp_column))
                receiving_udp = (
                    "Yes"
                    if udp_status is True
                    else ("No" if udp_status is False else "Unknown")
                )

            polling_status = ""
            polling_interval = ""
            polling_interval_seconds = None
            if command_polling_enabled_column:
                polling_status = parse_command_polling_enabled(
                    row.get(command_polling_enabled_column)
                )
            if command_polling_interval_column:
                raw_interval = row.get(command_polling_interval_column)
                polling_interval_seconds = parse_command_polling_interval_seconds(
                    raw_interval, command_polling_interval_column
                )
                if not polling_status and str(raw_interval or "").strip():
                    if str(raw_interval).strip().casefold() == "not enabled":
                        polling_status = "Disabled"
                    elif polling_interval_seconds is not None:
                        polling_status = "Enabled"
                    else:
                        polling_status = "Unknown"
                polling_interval = display_command_polling_interval(
                    raw_interval,
                    polling_interval_seconds,
                    polling_status,
                    command_polling_interval_column,
                )

            fast_hash_enabled = ""
            fast_hash_work = ""
            fast_hash_sleep = ""
            if fast_hash_verify_enabled_column:
                fast_hash_enabled = parse_fast_hash_verify_enabled(
                    row.get(fast_hash_verify_enabled_column)
                )
            if fast_hash_verify_work_column:
                fast_hash_work = display_fast_hash_verify_ms(
                    row.get(fast_hash_verify_work_column)
                )
            if fast_hash_verify_sleep_column:
                fast_hash_sleep = display_fast_hash_verify_ms(
                    row.get(fast_hash_verify_sleep_column)
                )

            multicore_scaling = ""
            if agent_multicore_scaling_column:
                multicore_scaling = parse_agent_multicore_scaling(
                    row.get(agent_multicore_scaling_column)
                )

            physical_cpu_core_count = ""
            if agent_total_physical_cpu_core_count_column:
                physical_cpu_core_count = display_client_setting(
                    row.get(agent_total_physical_cpu_core_count_column)
                )

            cpu_work_idle = ""
            cpu_sleep_idle = ""
            if agent_cpu_work_idle_column:
                cpu_work_idle = display_client_setting(
                    row.get(agent_cpu_work_idle_column)
                )
            if agent_cpu_sleep_idle_column:
                cpu_sleep_idle = display_client_setting(
                    row.get(agent_cpu_sleep_idle_column)
                )

            processed.append(
                ProcessedRow(
                    computer_name=computer_name,
                    max_loop=convert_to_hhmmss(max_sec),
                    avg_loop=convert_to_hhmmss(avg_sec),
                    max_seconds=round(float(max_sec), 2),
                    avg_seconds=round(float(avg_sec), 2),
                    receiving_udp_pings=receiving_udp,
                    relay=relay,
                    subnet=subnet,
                    command_polling_enabled=polling_status,
                    command_polling_interval=polling_interval,
                    command_polling_interval_seconds=polling_interval_seconds,
                    fast_hash_verify_enabled=fast_hash_enabled,
                    fast_hash_verify_work=fast_hash_work,
                    fast_hash_verify_sleep=fast_hash_sleep,
                    agent_multicore_scaling_enabled=multicore_scaling,
                    agent_total_physical_cpu_core_count=physical_cpu_core_count,
                    agent_cpu_work_idle=cpu_work_idle,
                    agent_cpu_sleep_idle=cpu_sleep_idle,
                )
            )
        else:
            avg_raw = row.get(avg_column)
            avg_text = "" if avg_raw is None or pd.isna(avg_raw) else str(avg_raw).strip()
            if re.search(r"error", avg_text, re.IGNORECASE):
                error_count += 1
            else:
                not_reported_count += 1

    return processed, not_reported_count, error_count


def _command_polling_group_rows(
    rows: list[ProcessedRow], group_attr: str
) -> list[list[str]]:
    groups: dict[str, list[ProcessedRow]] = {}
    for row in rows:
        key = str(getattr(row, group_attr, "") or "Not reported")
        groups.setdefault(key, []).append(row)

    output: list[list[str]] = []
    for key, group in groups.items():
        status_counts = Counter(row.command_polling_enabled or "Unknown" for row in group)
        no_udp_polling_gap = sum(
            1
            for row in group
            if is_udp_not_receiving(row.receiving_udp_pings)
            and row.command_polling_enabled in {"Disabled", "Not Set"}
        )
        enabled_missing_interval = sum(
            1
            for row in group
            if row.command_polling_enabled == "Enabled"
            and row.command_polling_interval_seconds is None
        )
        below_loop = sum(
            1
            for row in group
            if row.command_polling_enabled == "Enabled"
            and row.command_polling_interval_seconds is not None
            and row.command_polling_interval_seconds < row.avg_seconds
        )

        output.append(
            [
                key,
                f"{len(group):,}",
                f"{status_counts['Enabled']:,}",
                f"{status_counts['Disabled']:,}",
                f"{status_counts['Not Set']:,}",
                f"{status_counts['Unknown']:,}",
                f"{enabled_missing_interval:,}",
                f"{below_loop:,}",
                f"{no_udp_polling_gap:,}",
            ]
        )

    output.sort(
        key=lambda row: (
            -_parse_int_text(row[8]),
            -_parse_int_text(row[7]),
            -_parse_int_text(row[6]),
            -(_parse_int_text(row[3]) + _parse_int_text(row[4])),
            row[0].casefold(),
        )
    )
    return output


def analyze_command_polling(
    rows: list[ProcessedRow],
) -> CommandPollingSummary | None:
    polling_rows = [
        row for row in rows if row.command_polling_enabled or row.command_polling_interval
    ]
    if not polling_rows:
        return None

    enabled_count = 0
    disabled_count = 0
    not_set_count = 0
    unknown_count = 0
    enabled_missing_interval_count = 0
    interval_below_loop_count = 0
    no_udp_polling_gap_count = 0

    for row in polling_rows:
        status = row.command_polling_enabled or "Unknown"
        no_udp = is_udp_not_receiving(row.receiving_udp_pings)

        if status == "Enabled":
            enabled_count += 1
        elif status == "Disabled":
            disabled_count += 1
        elif status == "Not Set":
            not_set_count += 1
        else:
            unknown_count += 1

        review = ""
        if status == "Unknown":
            review = "Command polling setting could not be interpreted."
        elif status == "Enabled" and row.command_polling_interval_seconds is None:
            enabled_missing_interval_count += 1
            review = "Polling is enabled, but no interval was reported."
        elif (
            status == "Enabled"
            and row.command_polling_interval_seconds is not None
            and row.command_polling_interval_seconds < row.avg_seconds
        ):
            interval_below_loop_count += 1
            review = "Current polling interval is below the average loop time."
        elif no_udp and status in {"Disabled", "Not Set"}:
            no_udp_polling_gap_count += 1
            review = (
                "No UDP received and polling is disabled or not set. Review for "
                "command polling if faster response is required."
            )
        elif no_udp:
            review = (
                "No UDP received. Review relay, subnet, and polling fields in "
                "the workbook with customer network context."
            )
        else:
            review = "No immediate polling issue detected."

        row.command_polling_review = review

    return CommandPollingSummary(
        total_devices=len(polling_rows),
        enabled_count=enabled_count,
        disabled_count=disabled_count,
        not_set_count=not_set_count,
        unknown_count=unknown_count,
        enabled_missing_interval_count=enabled_missing_interval_count,
        interval_below_loop_count=interval_below_loop_count,
        no_udp_polling_gap_count=no_udp_polling_gap_count,
        relay_rows=_command_polling_group_rows(polling_rows, "relay"),
        subnet_rows=_command_polling_group_rows(polling_rows, "subnet"),
    )


def analyze_fast_hash_verify(
    rows: list[ProcessedRow],
) -> FastHashVerifySummary | None:
    fast_hash_rows = [
        row
        for row in rows
        if row.fast_hash_verify_enabled
        or row.fast_hash_verify_work
        or row.fast_hash_verify_sleep
    ]
    if not fast_hash_rows:
        return None

    counts = Counter(row.fast_hash_verify_enabled or "Not Set" for row in fast_hash_rows)
    settings = Counter(
        (
            row.fast_hash_verify_work or "Not Set",
            row.fast_hash_verify_sleep or "Not Set",
        )
        for row in fast_hash_rows
    )
    settings_rows = [
        [work, sleep, configured_cpu_duty_cycle(work, sleep), f"{count:,}"]
        for (work, sleep), count in sorted(
            settings.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return FastHashVerifySummary(
        total_devices=len(fast_hash_rows),
        enabled_count=counts["Enabled"],
        disabled_count=counts["Disabled"],
        not_set_count=counts["Not Set"],
        unknown_count=counts["Unknown"],
        settings_rows=settings_rows,
    )


def fast_hash_verify_coverage_rows(
    summary: FastHashVerifySummary,
) -> list[list[str]]:
    total = summary.total_devices
    denominator = max(total, 1)

    def percent(count: int) -> str:
        return f"{count / denominator * 100:.1f}%"

    return [
        ["Enabled", f"{summary.enabled_count:,}", percent(summary.enabled_count)],
        ["Disabled", f"{summary.disabled_count:,}", percent(summary.disabled_count)],
        ["Not Set", f"{summary.not_set_count:,}", percent(summary.not_set_count)],
        ["Unknown", f"{summary.unknown_count:,}", percent(summary.unknown_count)],
    ]


def analyze_agent_multicore(
    rows: list[ProcessedRow],
) -> AgentMulticoreSummary | None:
    """Group the supported 11.0.7 agent multicore switch without assessing it."""
    multicore_rows = [row for row in rows if row.agent_multicore_scaling_enabled]
    if not multicore_rows:
        return None

    settings = Counter(
        (
            row.agent_multicore_scaling_enabled or "Not Set",
            row.agent_total_physical_cpu_core_count or "Not Reported",
        )
        for row in multicore_rows
    )
    settings_rows = [
        [scaling, physical_core_count, f"{count:,}"]
        for (scaling, physical_core_count), count in sorted(
            settings.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return AgentMulticoreSummary(
        total_devices=len(multicore_rows),
        settings_rows=settings_rows,
    )


def analyze_agent_cpu_idle(rows: list[ProcessedRow]) -> AgentCpuIdleSummary | None:
    """Group reported client CPU idle settings without assessing them."""
    idle_rows = [
        row for row in rows if row.agent_cpu_work_idle or row.agent_cpu_sleep_idle
    ]
    if not idle_rows:
        return None

    settings = Counter(
        (
            row.agent_cpu_work_idle or "Not Set",
            row.agent_cpu_sleep_idle or "Not Set",
        )
        for row in idle_rows
    )
    settings_rows = [
        [
            work_idle,
            sleep_idle,
            configured_cpu_duty_cycle(work_idle, sleep_idle),
            f"{count:,}",
        ]
        for (work_idle, sleep_idle), count in sorted(
            settings.items(), key=lambda item: (-item[1], item[0])
        )
    ]
    return AgentCpuIdleSummary(
        total_devices=len(idle_rows),
        settings_rows=settings_rows,
    )


def calculate_metrics(
    processed: list[ProcessedRow],
    total_source_rows: int,
    not_reported_count: int,
    error_count: int,
    healthy_threshold_seconds: float,
    critical_threshold_seconds: float,
    report_start: date,
    report_end: date,
    generated_at: datetime,
) -> tuple[ReportMetrics, list[ProcessedRow]]:
    if critical_threshold_seconds <= healthy_threshold_seconds:
        raise ValueError("CriticalThreshold must be greater than HealthyThreshold.")

    total_devices = len(processed)
    if total_devices == 0:
        raise ValueError(
            "No valid rows found after parsing. Confirm the selected maximum and average columns contain loop time values."
        )

    total_issue_count = not_reported_count + error_count
    avg_healthy = sum(1 for r in processed if r.avg_seconds < healthy_threshold_seconds)
    avg_warning = sum(
        1
        for r in processed
        if healthy_threshold_seconds <= r.avg_seconds <= critical_threshold_seconds
    )
    avg_critical = (
        sum(1 for r in processed if r.avg_seconds > critical_threshold_seconds)
        + total_issue_count
    )

    safe_total_rows = max(1, total_source_rows)
    score_total_devices = total_devices + total_issue_count
    safe_score_total = max(1, score_total_devices)

    avg_healthy_pct = avg_healthy / safe_score_total
    avg_warning_pct = avg_warning / safe_score_total
    avg_critical_pct = avg_critical / safe_score_total

    avg_seconds_list = [r.avg_seconds for r in processed]
    avg_mean = sum(avg_seconds_list) / total_devices
    avg_median = statistics.median(avg_seconds_list)
    avg_max = sum(r.max_seconds for r in processed) / total_devices
    slowest_avg = max(avg_seconds_list)
    peak_max = max(r.max_seconds for r in processed)

    avg_over_120_seconds = 120 * 60
    avg_over_120 = sum(1 for r in processed if r.avg_seconds > avg_over_120_seconds)
    avg_over_120_pct = avg_over_120 / total_devices

    avg_over_60_devices = [
        r for r in processed if r.avg_seconds > critical_threshold_seconds
    ]
    fix_first_count = (
        math.ceil(len(avg_over_60_devices) * 0.25) if avg_over_60_devices else 0
    )
    fix_first_devices = sorted(
        avg_over_60_devices, key=lambda r: r.avg_seconds, reverse=True
    )[:fix_first_count]

    environment_score = round(
        (avg_healthy_pct * 100) + (avg_warning_pct * 67) + (avg_critical_pct * 34)
    )
    environment_score = max(0, min(100, environment_score))

    if environment_score < 70:
        overall_status = "CRITICAL"
    elif environment_score < 90:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"

    score_driver = "Average Loop Health Score = Healthy% x 100 + Warning% x 67 + Critical% x 34. Critical includes > 60 minutes plus Not Reported/Error rows."
    score_breakdown = f"{pct(avg_healthy_pct, 0)} Healthy, {pct(avg_warning_pct, 0)} Warning, {pct(avg_critical_pct, 0)} Critical -> Average Loop Health Score {environment_score}"

    metrics = ReportMetrics(
        total_devices=total_devices,
        score_total_devices=score_total_devices,
        overall_status=overall_status,
        environment_score=environment_score,
        score_driver=score_driver,
        score_breakdown=score_breakdown,
        report_start_text=format_report_date(report_start),
        report_end_text=format_report_date(report_end),
        report_span_text=format_report_span(report_start, report_end),
        generated_at_text=f"{generated_at.month}/{generated_at.day}/{generated_at.year} {generated_at:%H:%M:%S}",
        avg_mean_seconds=avg_mean,
        avg_median_seconds=avg_median,
        avg_max_seconds=avg_max,
        slowest_avg_seconds=slowest_avg,
        peak_max_seconds=peak_max,
        avg_healthy=avg_healthy,
        avg_warning=avg_warning,
        avg_critical=avg_critical,
        avg_healthy_pct=avg_healthy_pct,
        avg_warning_pct=avg_warning_pct,
        avg_critical_pct=avg_critical_pct,
        avg_over_120=avg_over_120,
        avg_over_120_pct=avg_over_120_pct,
        not_reported_count=not_reported_count,
        error_count=error_count,
        not_reported_pct=not_reported_count / safe_total_rows,
        error_pct=error_count / safe_total_rows,
        total_issue_count=total_issue_count,
        total_issue_pct=total_issue_count / safe_total_rows,
        healthy_threshold_seconds=healthy_threshold_seconds,
        critical_threshold_seconds=critical_threshold_seconds,
        fix_first_count=fix_first_count,
    )

    return metrics, fix_first_devices


def processed_to_dataframe(rows: list[ProcessedRow]) -> pd.DataFrame:
    has_udp_data = any(r.receiving_udp_pings for r in rows)
    has_udp_context = any(r.relay or r.subnet for r in rows)
    has_command_polling_data = any(
        r.command_polling_enabled or r.command_polling_interval for r in rows
    )
    has_fast_hash_verify_data = any(
        r.fast_hash_verify_enabled or r.fast_hash_verify_work or r.fast_hash_verify_sleep
        for r in rows
    )
    has_agent_multicore_data = any(
        r.agent_multicore_scaling_enabled or r.agent_total_physical_cpu_core_count
        for r in rows
    )
    has_agent_cpu_idle_data = any(
        r.agent_cpu_work_idle or r.agent_cpu_sleep_idle for r in rows
    )

    data = []
    for r in rows:
        row_dict = {
            "ComputerName": r.computer_name,
            "MaxLoop": format_duration_for_report(r.max_seconds),
            "AvgLoop": format_duration_for_report(r.avg_seconds),
            "MaxSeconds": r.max_seconds,
            "AvgSeconds": r.avg_seconds,
        }
        if has_udp_data:
            row_dict["Receiving UDP Pings"] = r.receiving_udp_pings
        if has_udp_context:
            row_dict["Relay"] = r.relay
            row_dict["Subnet"] = r.subnet
        if has_command_polling_data:
            row_dict["Command Polling"] = r.command_polling_enabled
            row_dict["Command Polling Minutes"] = r.command_polling_interval
            row_dict["Suggested Command Polling Interval Seconds"] = (
                suggested_command_polling_seconds(r.avg_seconds)
            )
            row_dict["Command Polling Review"] = r.command_polling_review
        if has_fast_hash_verify_data:
            row_dict["FastHashVerify"] = r.fast_hash_verify_enabled
            row_dict["FastHashVerify Work"] = r.fast_hash_verify_work
            row_dict["FastHashVerify Sleep"] = r.fast_hash_verify_sleep
            row_dict["FastHashVerify Configured Duty Cycle (%)"] = (
                configured_cpu_duty_cycle(
                    r.fast_hash_verify_work,
                    r.fast_hash_verify_sleep,
                )
            )
        if has_agent_multicore_data:
            row_dict["Client Multicore Scaling"] = r.agent_multicore_scaling_enabled
            row_dict["Client Total Physical CPU Core Count"] = (
                r.agent_total_physical_cpu_core_count
            )
        if has_agent_cpu_idle_data:
            row_dict["Client CPU Work Idle"] = r.agent_cpu_work_idle
            row_dict["Client CPU Sleep Idle"] = r.agent_cpu_sleep_idle
            row_dict["Client CPU Idle Configured Duty Cycle (%)"] = (
                configured_cpu_duty_cycle(
                    r.agent_cpu_work_idle,
                    r.agent_cpu_sleep_idle,
                )
            )
        data.append(row_dict)
    return pd.DataFrame(data)


def generate_png(
    metrics: ReportMetrics,
    png_output: Path,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
) -> None:
    """Render the Client Loop Performance infographic from the design HTML.

    Builds the chart's data from ReportMetrics and screenshots the design
    template via html_charts -- pixel-exact to the handoff, no reconstruction.
    """
    from Lib.Design import html_charts

    scored_total = metrics.score_total_devices
    h_min = metrics.healthy_threshold_seconds / 60.0
    c_min = metrics.critical_threshold_seconds / 60.0

    def fmt_min(value: float) -> str:
        return f"{value:g}"

    # Status -> class/label, score color, and any module finding line.
    cls, status_label, score_color, finding_impact = {
        "HEALTHY": (
            "st-healthy",
            status_spine.HEALTHY.word,
            status_spine.HEALTHY.mark,
            "",
        ),
        "WARNING": (
            "st-attention",
            status_spine.NEEDS_ATTENTION.word,
            status_spine.NEEDS_ATTENTION.mark,
            "High",
        ),
        "CRITICAL": (
            "st-critical",
            status_spine.CRITICAL.word,
            status_spine.CRITICAL.mark,
            "Critical",
        ),
    }.get(
        metrics.overall_status,
        (
            "st-attention",
            status_spine.NOT_ASSESSED.word,
            status_spine.NOT_ASSESSED.mark,
            "",
        ),
    )

    def m_s(seconds: float) -> str:
        total = int(round(seconds))
        minutes, secs = divmod(total, 60)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            return f"{hours}h {minutes:02d}m"
        return f"{minutes}m {secs:02d}s"

    # Distribution: only the non-zero buckets become labelled segments; thin
    # segments get a min width + smaller number (matches the design).
    buckets = [
        (metrics.avg_healthy, status_spine.HEALTHY.mark),
        (metrics.avg_warning, status_spine.NEEDS_ATTENTION.mark),
        (metrics.avg_critical, status_spine.CRITICAL.mark),
    ]
    seg_total = sum(c for c, _ in buckets) or 1
    dist = []
    for cnt, color in buckets:
        if cnt <= 0:
            continue
        pct = cnt / seg_total * 100
        seg = {
            "pct": round(pct, 3),
            "color": color,
            "num": f"{cnt:,}",
            "fs": 18 if pct >= 8 else 16,
        }
        if pct < 8:
            seg["minw"] = 64
        dist.append(seg)

    legend = [
        {
            "color": status_spine.HEALTHY.mark,
            "label": f"Healthy under {fmt_min(h_min)} min",
            "count": f"{metrics.avg_healthy:,}",
            "pct": round(metrics.avg_healthy_pct * 100, 1)
            if metrics.avg_healthy
            else None,
        },
        {
            "color": status_spine.NEEDS_ATTENTION.mark,
            "label": f"Needs Attention {fmt_min(h_min)} to {fmt_min(c_min)} min",
            "count": f"{metrics.avg_warning:,}",
            "pct": round(metrics.avg_warning_pct * 100, 1)
            if metrics.avg_warning
            else None,
        },
        {
            "color": status_spine.CRITICAL.mark,
            "label": f"Critical over {fmt_min(c_min)} min",
            "count": f"{metrics.avg_critical:,}",
            "pct": round(metrics.avg_critical_pct * 100, 1)
            if metrics.avg_critical
            else None,
        },
    ]

    meta = f"{scored_total:,} devices scored"
    if metrics.report_span_text:
        meta += f" &middot; {metrics.report_span_text} collection"

    top_offender = loop_offenders[0] if loop_offenders else None
    if top_offender:
        slow_value = format_loop_offender_strip_seconds(
            top_offender.avg_client_processing_seconds
        )
        slow_detail = compact_loop_offender_label(top_offender.result)
    else:
        slow_value = "Not available"
        slow_detail = "Top 10 data not provided"

    data = {
        "title": "Client Loop Performance",
        "meta": meta,
        "findingsLine": (f"Raises 1 {finding_impact} finding" if finding_impact else ""),
        "findings": (
            [
                {
                    "id": "CLT-01",
                    "text": (
                        f"{finding_impact}, client evaluation loop health "
                        "below the healthy threshold"
                    ),
                }
            ]
            if finding_impact
            else []
        ),
        "score": metrics.environment_score,
        "scoreColor": score_color,
        "status": {"cls": cls, "label": status_label},
        "barPct": max(0, min(100, metrics.environment_score)),
        "barColor": score_color,
        "distLabel": f"Loop distribution &middot; {scored_total:,} devices scored",
        "dist": dist,
        "legend": legend,
        "footer": [
            {"label": "Average loop time", "value": m_s(metrics.avg_mean_seconds)},
            {
                "label": "Slowest evaluation",
                "value": slow_value,
                "caption": slow_detail,
            },
            {
                "label": "Severe loops over 120 min",
                "value": f"{metrics.avg_over_120:,}",
                "caption": "None recorded" if metrics.avg_over_120 == 0 else "",
                "color": (
                    status_spine.HEALTHY.mark
                    if metrics.avg_over_120 == 0
                    else status_spine.CRITICAL.mark
                ),
            },
        ],
        "context": context_strip_tiles(metrics, loop_offenders, udp_summary),
    }
    html_charts.render_chart("loop", data, png_output)


def autosize_excel_columns(path: Path) -> None:
    finish_openpyxl_workbook(path)


def _spine_hex(value: str) -> str:
    return str(value or "").strip().lstrip("#").upper()


def _spine_level(status: str) -> status_spine.SpineLevel:
    normalized = str(status or "").strip()
    if normalized.lower() == "review":
        return status_spine.NEEDS_ATTENTION
    return status_spine.BY_WORD.get(normalized, status_spine.NOT_ASSESSED)


def style_actionsite_pressure_excel(path: Path) -> None:
    from openpyxl import load_workbook
    from openpyxl.styles import Font, PatternFill

    wb = load_workbook(path)
    sheet_name = next(
        (
            name
            for name in ("Contributing Factors", "Client Loop Penalties")
            if name in wb.sheetnames
        ),
        None,
    )
    if sheet_name is None:
        wb.save(path)
        return

    ws = wb[sheet_name]
    status_col = None
    for cell in ws[1]:
        if str(cell.value or "").strip().casefold() == "status":
            status_col = cell.column
            break

    if status_col is None:
        wb.save(path)
        return

    for row_idx in range(2, ws.max_row + 1):
        cell = ws.cell(row=row_idx, column=status_col)
        level = _spine_level(str(cell.value or ""))
        cell.fill = PatternFill("solid", fgColor=_spine_hex(level.bg))
        cell.font = Font(
            name=WORKBOOK_THEME.font_name,
            size=WORKBOOK_THEME.body_size,
            bold=True,
            color=_spine_hex(level.text),
        )

    wb.save(path)


def generate_excel(
    metrics: ReportMetrics,
    processed: list[ProcessedRow],
    fix_first_devices: list[ProcessedRow],
    excel_output: Path,
    actionsite_pressure: ActionSitePressure | None = None,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
    command_polling_summary: CommandPollingSummary | None = None,
    fast_hash_verify_summary: FastHashVerifySummary | None = None,
    agent_multicore_summary: AgentMulticoreSummary | None = None,
    agent_cpu_idle_summary: AgentCpuIdleSummary | None = None,
    stamp: str = "",
) -> None:
    metrics_rows = [
        ("Total Devices", metrics.total_devices),
        ("Overall Status", metrics.overall_status),
        ("Average Loop Health Score", f"{metrics.environment_score} / 100"),
        ("Score Method", metrics.score_driver),
        ("Score Breakdown", metrics.score_breakdown),
        ("Report Start", metrics.report_start_text),
        ("Report End", metrics.report_end_text),
        ("Report Range", metrics.report_span_text),
        ("Generated At", metrics.generated_at_text),
        ("Average Loop Mean", format_duration_for_report(metrics.avg_mean_seconds)),
        ("Average Loop Median", format_duration_for_report(metrics.avg_median_seconds)),
        ("Average Max Loop", format_duration_for_report(metrics.avg_max_seconds)),
        (
            "Slowest Average Loop",
            format_duration_for_report(metrics.slowest_avg_seconds),
        ),
        ("Peak Observed", format_duration_for_report(metrics.peak_max_seconds)),
        (
            "Average Loop Healthy",
            f"{metrics.avg_healthy} ({pct(metrics.avg_healthy_pct)})",
        ),
        (
            "Average Loop Warning",
            f"{metrics.avg_warning} ({pct(metrics.avg_warning_pct)})",
        ),
        (
            "Average Loop Critical",
            f"{metrics.avg_critical} ({pct(metrics.avg_critical_pct)})",
        ),
        (
            "Average Loop > 120 Minutes",
            f"{metrics.avg_over_120} ({pct(metrics.avg_over_120_pct)})",
        ),
        (
            "Fix These First Devices",
            f"{metrics.fix_first_count} (top 25% of devices with avg loop > 60 minutes)",
        ),
        (
            "Not Reported",
            f"{metrics.not_reported_count} ({pct(metrics.not_reported_pct)})",
        ),
        ("Error", f"{metrics.error_count} ({pct(metrics.error_pct)})"),
        (
            "Total Reporting Issues",
            f"{metrics.total_issue_count} ({pct(metrics.total_issue_pct)})",
        ),
        ("Healthy Threshold", convert_to_hhmmss(metrics.healthy_threshold_seconds)),
        ("Critical Threshold", convert_to_hhmmss(metrics.critical_threshold_seconds)),
    ]
    if command_polling_summary:
        metrics_rows.extend(
            [
                ("Command Polling Enabled", command_polling_summary.enabled_count),
                ("Command Polling Disabled", command_polling_summary.disabled_count),
                ("Command Polling Not Set", command_polling_summary.not_set_count),
                (
                    "No UDP and Polling Disabled/Not Set",
                    command_polling_summary.no_udp_polling_gap_count,
                ),
                (
                    "Command Polling Interval Below Average Loop",
                    command_polling_summary.interval_below_loop_count,
                ),
            ]
        )
    if fast_hash_verify_summary:
        metrics_rows.extend(
            [
                ("FastHashVerify Enabled", fast_hash_verify_summary.enabled_count),
                ("FastHashVerify Disabled", fast_hash_verify_summary.disabled_count),
                ("FastHashVerify Not Set", fast_hash_verify_summary.not_set_count),
                ("FastHashVerify Unknown", fast_hash_verify_summary.unknown_count),
            ]
        )
    metrics_df = pd.DataFrame(metrics_rows, columns=["Metric", "Value"])
    bands_start_row = len(metrics_rows) + 3

    bands_df = pd.DataFrame(
        [
            {
                "Basis": "Average Loop",
                "Band": "Healthy",
                "Definition": f"< {convert_to_hhmmss(metrics.healthy_threshold_seconds)}",
                "Count": metrics.avg_healthy,
                "Percent": metrics.avg_healthy_pct,
            },
            {
                "Basis": "Average Loop",
                "Band": "Warning",
                "Definition": f">= {convert_to_hhmmss(metrics.healthy_threshold_seconds)} and <= {convert_to_hhmmss(metrics.critical_threshold_seconds)}",
                "Count": metrics.avg_warning,
                "Percent": metrics.avg_warning_pct,
            },
            {
                "Basis": "Average Loop",
                "Band": "Critical",
                "Definition": f"> {convert_to_hhmmss(metrics.critical_threshold_seconds)}",
                "Count": metrics.avg_critical,
                "Percent": metrics.avg_critical_pct,
            },
        ]
    )

    source_df = processed_to_dataframe(processed)

    if fix_first_devices:
        fix_df = processed_to_dataframe(fix_first_devices)
    else:
        fix_df = pd.DataFrame(
            [
                {
                    "ComputerName": "No devices over 60 minute average loop",
                    "MaxLoop": "",
                    "AvgLoop": "",
                    "MaxSeconds": "",
                    "AvgSeconds": "",
                }
            ]
        )

    with pd.ExcelWriter(excel_output, engine="openpyxl") as writer:
        metrics_df.to_excel(writer, sheet_name="Health Summary", index=False, startrow=0)
        bands_df.to_excel(
            writer, sheet_name="Health Summary", index=False, startrow=bands_start_row
        )
        fix_df.to_excel(writer, sheet_name="Fix These First", index=False)
        source_df.to_excel(writer, sheet_name="Source Data", index=False)
        if loop_offenders:
            offenders_df = pd.DataFrame(
                [
                    {
                        "Rank": item.rank,
                        "AverageEvalTimeSeconds": format_loop_offender_seconds(
                            item.avg_client_processing_seconds
                        ),
                        "Occurrences": item.occurrences,
                        "Result": item.result,
                    }
                    for item in loop_offenders
                ]
            )
            offenders_df.to_excel(writer, sheet_name="Evaluation Offenders", index=False)
        if actionsite_pressure:
            pressure_df = pd.DataFrame(
                actionsite_pressure_rows(actionsite_pressure),
                columns=["Metric", "Value", "Status", "Basis"],
            )
            pressure_df.to_excel(writer, sheet_name="Contributing Factors", index=False)
        if udp_summary:
            pd.DataFrame(
                udp_coverage_rows(udp_summary),
                columns=["Status", "Devices / Source", "Percent"],
            ).to_excel(writer, sheet_name="UDP Coverage", index=False)
            udp_notes = udp_notification_data_notes(udp_summary)
            if udp_notes:
                pd.DataFrame({"Note": udp_notes}).to_excel(
                    writer, sheet_name="UDP Data Notes", index=False
                )
            if udp_summary.relay_rows:
                pd.DataFrame(
                    udp_summary.relay_rows,
                    columns=[
                        "Relay",
                        "NotReceivingUdpPings / ReportedClients",
                        "PercentOfReportedClients",
                    ],
                ).to_excel(writer, sheet_name="UDP Issues by Relay", index=False)
            if udp_summary.subnet_rows:
                pd.DataFrame(
                    udp_summary.subnet_rows,
                    columns=[
                        "Subnet",
                        "NotReceivingUdpPings / ReportedClients",
                        "ServingRelays",
                    ],
                ).to_excel(writer, sheet_name="UDP Issues by Subnet", index=False)
        if command_polling_summary:
            pd.DataFrame(
                command_polling_coverage_rows(command_polling_summary),
                columns=["Status", "Devices / Source", "Percent"],
            ).to_excel(writer, sheet_name="Polling Summary", index=False)
            if command_polling_summary.relay_rows:
                pd.DataFrame(
                    command_polling_summary.relay_rows,
                    columns=[
                        "Relay",
                        "Devices",
                        "Enabled",
                        "Disabled",
                        "NotSet",
                        "Unknown",
                        "EnabledMissingInterval",
                        "IntervalBelowLoop",
                        "NoUdpAndPollingOff",
                    ],
                ).to_excel(writer, sheet_name="Polling by Relay", index=False)
            if command_polling_summary.subnet_rows:
                pd.DataFrame(
                    command_polling_summary.subnet_rows,
                    columns=[
                        "Subnet",
                        "Devices",
                        "Enabled",
                        "Disabled",
                        "NotSet",
                        "Unknown",
                        "EnabledMissingInterval",
                        "IntervalBelowLoop",
                        "NoUdpAndPollingOff",
                    ],
                ).to_excel(writer, sheet_name="Polling by Subnet", index=False)
        if fast_hash_verify_summary:
            pd.DataFrame(
                fast_hash_verify_coverage_rows(fast_hash_verify_summary),
                columns=["Status", "Devices / Source", "Percent"],
            ).to_excel(writer, sheet_name="FastHashVerify Summary", index=False)
            pd.DataFrame(
                fast_hash_verify_summary.settings_rows,
                columns=[
                    "Work (ms)",
                    "Sleep (ms)",
                    "Configured Duty Cycle (%)",
                    "Devices",
                ],
            ).to_excel(writer, sheet_name="FastHashVerify Settings", index=False)
        if agent_multicore_summary:
            pd.DataFrame(
                agent_multicore_summary.settings_rows,
                columns=[
                    "Scale Work Time With CPU Cores",
                    "Total Physical CPU Cores",
                    "Devices",
                ],
            ).to_excel(writer, sheet_name="Client Multicore Settings", index=False)
        if agent_cpu_idle_summary:
            pd.DataFrame(
                agent_cpu_idle_summary.settings_rows,
                columns=[
                    "Work Idle (ms)",
                    "Sleep Idle (ms)",
                    "Configured Duty Cycle (%)",
                    "Devices",
                ],
            ).to_excel(writer, sheet_name="Client CPU Idle Settings", index=False)

    autosize_excel_columns(excel_output)
    if actionsite_pressure:
        style_actionsite_pressure_excel(excel_output)

    if stamp:
        from openpyxl import load_workbook

        wb = load_workbook(excel_output)
        stamp_worksheet(wb.worksheets[0], stamp)
        wb.save(excel_output)


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_text(
    cell,
    text: str,
    bold: bool = False,
    color: str | None = None,
) -> None:
    cell.text = ""
    p = cell.paragraphs[0]
    run = p.add_run(text)
    run.bold = bold
    # Font family and size come from the shared BigFixContent style once merged
    # into the report, so this table matches every other data table.

    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_table_style(table, style_id: str = TABLE_STYLE_ID) -> None:
    """Apply the report table style by id without requiring it in this docx."""
    tbl_pr = table._tbl.tblPr
    tbl_style = tbl_pr.find(qn("w:tblStyle"))
    if tbl_style is None:
        tbl_style = OxmlElement("w:tblStyle")
        tbl_pr.insert(0, tbl_style)
    tbl_style.set(qn("w:val"), style_id)


def set_table_look(table) -> None:
    """Enable BigFixContent's conditional formatting (navy first row + horizontal
    row banding). A programmatically built table has no tblLook, so Word would
    otherwise ignore the style's first-row/banding rules. Mirrors the 04A0 look
    used by the template's own tables and the XML injectors."""
    tbl_pr = table._tbl.tblPr
    look = tbl_pr.find(qn("w:tblLook"))
    if look is None:
        look = OxmlElement("w:tblLook")
        tbl_pr.append(look)
    for attr, val in (
        ("w:val", "04A0"),
        ("w:firstRow", "1"),
        ("w:lastRow", "0"),
        ("w:firstColumn", "1"),
        ("w:lastColumn", "0"),
        ("w:noHBand", "0"),
        ("w:noVBand", "1"),
    ):
        look.set(qn(attr), val)


def build_word_table(
    document,
    headers: list[str],
    rows: list[list[str]],
    center_cols: set[int],
    status_col: int | None = None,
) -> None:
    """
    Build a Word table using the same conservative table styling the module
    documents share:
      - BigFixContent table style
      - light blue header with black text
      - grid borders
      - wrapped text
      - centered numeric/status columns
      - clean vertical alignment
    """
    table = document.add_table(rows=1, cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    # Header fill, borders and row banding come from the shared BigFixContent
    # style (single source of truth); tblLook turns on its conditional
    # formatting. Only the semantic status-column pill keeps an inline fill.
    set_table_style(table)
    set_table_look(table)
    table.allow_autofit = True

    for idx, header in enumerate(headers):
        cell = table.rows[0].cells[idx]
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        # Navy fill + white bold text come from BigFixContent's firstRow.
        set_cell_text(cell, header, bold=True)

        for paragraph in cell.paragraphs:
            paragraph.alignment = (
                WD_ALIGN_PARAGRAPH.CENTER
                if idx in center_cols
                else WD_ALIGN_PARAGRAPH.LEFT
            )

    for row in rows:
        cells = table.add_row().cells

        for idx, value in enumerate(row):
            cell = cells[idx]
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER

            if status_col is not None and idx == status_col:
                level = _spine_level(value)
                set_cell_shading(cell, _spine_hex(level.bg))
                set_cell_text(
                    cell,
                    value,
                    bold=True,
                    color=_spine_hex(level.text),
                )
            else:
                set_cell_text(cell, value, bold=False, color=None)

            for paragraph in cell.paragraphs:
                paragraph.alignment = (
                    WD_ALIGN_PARAGRAPH.CENTER
                    if idx in center_cols
                    else WD_ALIGN_PARAGRAPH.LEFT
                )

    # Spacer after every table so the injected client-loop tables don't cram
    # together -- gives separation between consecutive tables and after the last.
    document.add_paragraph()


def context_strip_tiles(
    metrics: ReportMetrics,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
) -> list[dict[str, object]]:
    if udp_summary:
        udp_total = udp_summary.total_devices
        udp_value = count_with_denominator(udp_summary.not_receiving_count, udp_total)
        udp_detail = (
            "All reporting clients received pings"
            if udp_summary.not_receiving_count == 0
            else "Clients without received pings"
        )

        if udp_summary.relay_rows:
            relay_name, relay_count, _relay_pct = udp_summary.relay_rows[0]
            relay_value = str(relay_count)
            relay_detail = relay_name
        else:
            relay_value = "None"
            relay_detail = "No relay rollup recorded"
        udp_muted = False
        relay_muted = False
    else:
        udp_value = "Not collected"
        udp_detail = ""
        relay_value = "Not collected"
        relay_detail = ""
        udp_muted = True
        relay_muted = True

    score_total = metrics.score_total_devices
    reporting_value = count_with_denominator(metrics.total_devices, score_total)
    reporting_detail = (
        f"{metrics.total_issue_count:,} have no usable loop data"
        if metrics.total_issue_count
        else "All scored devices have usable loop data"
    )

    return [
        {
            "label": "Devices reporting",
            "value": reporting_value,
            "caption": reporting_detail,
            "muted": False,
        },
        {
            "label": "No UDP pings received",
            "value": udp_value,
            "caption": udp_detail,
            "muted": udp_muted,
        },
        {
            "label": "Relays with UDP issues",
            "value": relay_value,
            "caption": relay_detail,
            "muted": relay_muted,
        },
    ]


def add_note_paragraph(document, text: str) -> None:
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(0)
    paragraph.paragraph_format.space_after = Pt(3)
    prefix = paragraph.add_run("NOTE: ")
    prefix.bold = True
    paragraph.add_run(text)


def add_score_method_note(document) -> None:
    heading = document.add_heading("How This Score Is Calculated", level=3)
    heading.paragraph_format.space_before = Pt(0)
    heading.paragraph_format.space_after = Pt(3)

    intro = document.add_paragraph(
        "The Client Loop Health Score is based on the percentage of devices in "
        "each average-loop-time band:"
    )
    intro.paragraph_format.space_after = Pt(3)

    for text in (
        "Healthy, under 30 minutes: 100 points",
        "Needs Attention, 30 to 60 minutes: 67 points",
        "Critical, over 60 minutes, or no usable data reported: 34 points",
    ):
        bullet = document.add_paragraph(f"- {text}")
        bullet.paragraph_format.space_after = Pt(1)

    for text in (
        "Formula: Healthy% x 100 + Needs Attention% x 67 + Critical% x 34",
        "Average loop time is used when available because it represents "
        "sustained client performance across the capture window; devices with "
        "no usable loop data are scored Critical.",
        "Score bands: 85-100 Healthy, 60-84 Needs Attention, 0-59 Critical.",
        "This score is separate from the Summary Scorecard category scores in "
        "Section 04; they use different inputs and are not expected to match.",
    ):
        para = document.add_paragraph(text)
        para.paragraph_format.space_after = Pt(3)

    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(8)


def generate_word(
    metrics: ReportMetrics,
    png_output: Path,
    word_output: Path,
    actionsite_pressure: ActionSitePressure | None = None,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
    command_polling_summary: CommandPollingSummary | None = None,
    fast_hash_verify_summary: FastHashVerifySummary | None = None,
    agent_multicore_summary: AgentMulticoreSummary | None = None,
    agent_cpu_idle_summary: AgentCpuIdleSummary | None = None,
    stamp: str = "",
    include_automated_findings: bool = False,
) -> None:
    if Document is None:
        raise RuntimeError(
            "python-docx is required for Word output. Install with: pip install python-docx"
        )

    from Lib.Themes.word_stub_utils import (
        add_stub_front_matter,
        apply_standalone_narrow_margins,
        create_styled_stub_document,
        set_picture_alt_text,
    )

    document = apply_standalone_narrow_margins(
        create_styled_stub_document(script_file=__file__)
    )

    add_stub_front_matter(document, "Client Loop Health")
    if stamp:
        stamp_docx_document(document, stamp)

    finding_scope = "loop time, expensive evaluations, and UDP notification"
    if command_polling_summary:
        finding_scope = (
            "loop time, expensive evaluations, UDP notification, and command polling"
        )
    if fast_hash_verify_summary:
        finding_scope += ", and FastHashVerify client settings"
    add_note_paragraph(
        document,
        f"The raw data used to generate these {finding_scope} findings is available "
        "in the Client Loop Workbook (Excel file) for further troubleshooting and "
        "analysis.",
    )

    # Keep the executive-style PNG first so injected reports and slide decks lead
    # with the visual summary before the supporting detail tables.
    if png_output.exists():
        # 7.5" matches the master template's visible content zone (the
        # report template uses zero page margins with paragraph-level
        # indents). Using the standalone doc's own usable_width here
        # would only yield ~7.0" because this fragment carries 0.75"
        # margins, but those margins are irrelevant once the body XML
        # is spliced into the master template.
        picture = document.add_picture(str(png_output), width=Inches(7.5))
        set_picture_alt_text(
            picture,
            "Client loop performance chart showing health score, loop "
            "distribution, reported devices, UDP notification context, and "
            "reporting issues.",
            "Client Loop Performance Chart",
        )
        spacer = document.add_paragraph()
        spacer.paragraph_format.space_after = Pt(8)

    if include_automated_findings:
        finding_impact = {
            "WARNING": "High",
            "CRITICAL": "Critical",
        }.get(str(metrics.overall_status or "").upper())
        if finding_impact:
            document.add_heading("Automated Findings", level=3)
            build_word_table(
                document,
                ["Finding ID", "Automated Finding"],
                [
                    [
                        "CLT-01",
                        f"{finding_impact}, client evaluation loop health "
                        "below the healthy threshold.",
                    ]
                ],
                {0},
            )

    document.add_heading("BigFix Client Loop Performance Summary", level=3)
    document.add_paragraph(
        f"Report Generated: {metrics.generated_at_text} | "
        f"Data Collection Range: {metrics.report_start_text} - {metrics.report_end_text}"
    )

    for line in [
        f"Overall Status: {metrics.overall_status}",
        f"Average Loop Health Score: {metrics.environment_score} / 100",
        f"Average Loop Mean: {format_duration_for_report(metrics.avg_mean_seconds)}",
        f"Slowest Average Loop: {format_duration_for_report(metrics.slowest_avg_seconds)}",
        f"Peak Observed: {format_duration_for_report(metrics.peak_max_seconds)}",
    ]:
        document.add_paragraph(line)

    add_score_method_note(document)

    # Spacer before the first table so it doesn't cram against the summary above.
    document.add_paragraph()
    document.add_heading("Average Loop Health", level=3)
    build_word_table(
        document,
        ["Band", "Devices", "Percent", "Rule"],
        [
            [
                "Healthy",
                f"{metrics.avg_healthy:,}",
                pct(metrics.avg_healthy_pct),
                "< 30 minutes",
            ],
            [
                "Warning",
                f"{metrics.avg_warning:,}",
                pct(metrics.avg_warning_pct),
                "30-60 minutes",
            ],
            [
                "Critical",
                f"{metrics.avg_critical:,}",
                pct(metrics.avg_critical_pct),
                "> 60 minutes or no usable data",
            ],
        ],
        {1, 2, 3},
    )

    document.add_heading("Reporting Issues", level=3)
    build_word_table(
        document,
        ["Status", "Devices", "% of Source"],
        [
            [
                "Not Reported",
                f"{metrics.not_reported_count:,}",
                pct(metrics.not_reported_pct),
            ],
            ["Error", f"{metrics.error_count:,}", pct(metrics.error_pct)],
            [
                "Total Issues",
                f"{metrics.total_issue_count:,}",
                pct(metrics.total_issue_pct),
            ],
        ],
        {1, 2},
    )
    document.add_paragraph(
        "Devices that did not report usable loop data are scored Critical. "
        "When this row is large, the score reflects a visibility problem at "
        "least as much as a performance problem."
    )

    if loop_offenders or actionsite_pressure:
        document.add_heading("Loop Cost Diagnostics", level=3)
        document.add_paragraph(
            "The tables below explain where loop time is being spent: the "
            "specific evaluations that cost the most, and the platform-level "
            "factors that add pressure to every evaluation cycle. These "
            "indicators provide context; they do not add to or subtract from "
            "the score."
        )

    if loop_offenders:
        document.add_heading("Top 10 Most Expensive Evaluations", level=4)
        document.add_paragraph(
            "This table starts with each client's Top 10 slowest recorded "
            "evaluations, aggregates those samples across the deployment, then "
            "shows the 10 unique evaluations with the highest average "
            "evaluation time. Occurrences are kept as supporting context "
            "because repeated slow evaluations can still add meaningful loop "
            "cost across many endpoints."
        )
        build_word_table(
            document,
            [
                "Rank",
                "Average Eval Time (Seconds)",
                "Occurrences",
                "Evaluation",
            ],
            [
                [
                    str(item.rank),
                    format_loop_offender_seconds(item.avg_client_processing_seconds),
                    f"{item.occurrences:,}",
                    item.result,
                ]
                for item in loop_offenders
            ],
            {0, 1, 2},
        )

    if actionsite_pressure:
        document.add_heading("Contributing Factors", level=4)
        build_word_table(
            document,
            ["Metric", "Value", "Status", "Basis"],
            actionsite_pressure_rows(actionsite_pressure),
            {1, 2},
            status_col=2,
        )

    if udp_summary:
        document.add_heading("Client Notification Context", level=3)
        document.add_paragraph(
            "UDP notification data helps explain whether slow client response "
            "may be caused by clients not receiving BigFix notification traffic. "
            "Clients that do not receive UDP pings may still process work, but "
            "they may not wake up promptly when new content or actions are "
            "available."
        )
        document.add_heading("UDP Notification Coverage", level=4)
        build_word_table(
            document,
            ["Status", "Devices / Source", "% of Source"],
            udp_coverage_rows(udp_summary),
            {1, 2},
        )
        for note in udp_notification_data_notes(udp_summary):
            add_note_paragraph(document, note)

        if udp_summary.relay_rows:
            document.add_heading("UDP Notification Issues by Relay", level=4)
            build_word_table(
                document,
                [
                    "Relay",
                    "Not Receiving / Reported",
                    "% of Relay Reported Clients",
                ],
                udp_summary.relay_rows,
                {1, 2},
            )

        if udp_summary.subnet_rows:
            document.add_heading("Top Subnets Not Receiving UDP Pings", level=4)
            build_word_table(
                document,
                ["Subnet", "Not Receiving / Reported", "Serving Relays"],
                udp_summary.subnet_rows,
                {1},
            )

    if command_polling_summary:
        if not udp_summary:
            document.add_heading("Client Notification Context", level=3)
            document.add_paragraph(
                "Client notification data helps explain whether delayed response "
                "is related to UDP notification reachability, command polling "
                "configuration, or both."
            )

        document.add_heading("Command Polling Review", level=4)
        document.add_paragraph(
            "Command polling can reduce delayed response when UDP notifications "
            "do not reach a client. The report does not determine whether a relay "
            "is internal, DMZ, or externally facing because that requires customer "
            "network context."
        )
        build_word_table(
            document,
            ["Status", "Devices / Source", "% of Source"],
            command_polling_coverage_rows(command_polling_summary),
            {1, 2},
        )
        document.add_paragraph(
            "Command polling data includes client loop timing, relay and subnet "
            "context, UDP notification status, the command polling enabled state, "
            "and the reported polling interval. These fields describe command "
            "polling coverage and its relationship to client evaluation timing."
        )

        if command_polling_summary.relay_rows:
            document.add_heading("Command Polling by Relay", level=4)
            build_word_table(
                document,
                [
                    "Relay",
                    "Devices",
                    "Enabled",
                    "Disabled",
                    "Not Set",
                    "Unknown",
                    "Missing Interval",
                    "Interval Below Loop",
                    "No UDP + Polling Off",
                ],
                command_polling_summary.relay_rows[:10],
                {1, 2, 3, 4, 5, 6, 7, 8},
            )

        if command_polling_summary.subnet_rows:
            document.add_heading("Command Polling by Subnet", level=4)
            build_word_table(
                document,
                [
                    "Subnet",
                    "Devices",
                    "Enabled",
                    "Disabled",
                    "Not Set",
                    "Unknown",
                    "Missing Interval",
                    "Interval Below Loop",
                    "No UDP + Polling Off",
                ],
                command_polling_summary.subnet_rows[:10],
                {1, 2, 3, 4, 5, 6, 7, 8},
            )

    if fast_hash_verify_summary:
        document.add_heading("FastHashVerify Review", level=3)
        document.add_paragraph(
            "FastHashVerify temporarily allows the BigFix Client to use more "
            "CPU while calculating downloaded file hashes. This can shorten "
            "verification time for large patch files and large software updates, "
            "especially when the client would otherwise throttle hashing. It is "
            "disabled by default. When enabled, the documented default work and "
            "sleep settings are 20 ms and 60 ms, which allows hashing to use about "
            "25% of one CPU core while it is active. Configured duty cycle is the "
            "work interval divided by the work and sleep intervals together; it is "
            "not a measurement of observed CPU usage. Not Set means the collection "
            "did not return a value, and no client default is inferred."
        )
        document.add_heading("FastHashVerify Status", level=4)
        build_word_table(
            document,
            ["Status", "Devices / Source", "% of Source"],
            fast_hash_verify_coverage_rows(fast_hash_verify_summary),
            {1, 2},
        )
        document.add_heading("Reported Work and Sleep Settings", level=4)
        build_word_table(
            document,
            ["Work (ms)", "Sleep (ms)", "Configured Duty Cycle (%)", "Devices"],
            fast_hash_verify_summary.settings_rows,
            {2, 3},
        )
        document.add_paragraph(
            "Individual client FastHashVerify values include the enabled state and "
            "the reported work and sleep intervals. These intervals show the "
            "configured balance between active hash calculation and sleep time."
        )

    if agent_cpu_idle_summary:
        document.add_heading("Client CPU Idle Settings", level=3)
        document.add_paragraph(
            "The following client CPU idle setting values were reported. They are "
            "configuration context only; no assessment or finding is derived. The "
            "configured duty cycle is work divided by the work and sleep intervals "
            "together, not a measurement of observed CPU usage."
        )
        build_word_table(
            document,
            [
                "Work Idle (ms)",
                "Sleep Idle (ms)",
                "Configured Duty Cycle (%)",
                "Devices",
            ],
            agent_cpu_idle_summary.settings_rows,
            {2, 3},
        )

    if agent_multicore_summary:
        document.add_heading("Client Multicore Settings", level=3)
        document.add_paragraph(
            "The following 11.0.7 client setting was reported. It is "
            "configuration context only; no assessment or finding is derived. "
            "Not Applicable means the client version is too old for this setting "
            "(earlier than BigFix 11.0.7)."
        )
        build_word_table(
            document,
            [
                "Scale Work Time With CPU Cores",
                "Total Physical CPU Cores",
                "Devices",
            ],
            agent_multicore_summary.settings_rows,
            {1},
        )

    document.save(str(word_output))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate BigFix Client Loop Performance Summary reports."
    )
    parser.add_argument(
        "--input-file",
        help="Input Excel workbook or CSV path/filename. Filenames are resolved from the current working folder.",
    )
    parser.add_argument(
        "--output-folder",
        help="Output folder path. Defaults to the current working folder.",
    )
    parser.add_argument(
        "--healthy-threshold",
        default="00:30:00",
        help="Healthy threshold. Default: 00:30:00",
    )
    parser.add_argument(
        "--critical-threshold",
        default="01:00:00",
        help="Critical threshold. Default: 01:00:00",
    )
    parser.add_argument("--report-start-date", help="Report start date, e.g. 04-22-2026")
    parser.add_argument("--report-end-date", help="Report end date, e.g. 04-29-2026")
    parser.add_argument(
        "--deployment-info-folder",
        help=(
            "Optional Deployment_Information folder. If omitted, the script "
            "searches near the loop input file."
        ),
    )
    parser.add_argument(
        "--evaluation-times-file",
        "--top-offenders-file",
        dest="top_offenders_file",
        help=(
            "Optional raw client evaluation timing text/log/CSV or prebuilt "
            "offender CSV. Used to add a client evaluation offenders table to "
            "the loop report."
        ),
    )
    parser.add_argument(
        "--udp-notifications-file",
        help=(
            "Optional UDP notification CSV with Computer Name, IPv4 Address/Addresses, "
            "Relay, and Receiving UDP Pings columns."
        ),
    )
    parser.add_argument(
        "--top-offenders-count",
        type=int,
        default=10,
        help="Number of unique offenders to include. Use 0 for all. Default: 10.",
    )
    parser.add_argument(
        "--skip-word", action="store_true", help="Skip Word document generation"
    )
    parser.add_argument(
        "--include-automated-findings",
        action="store_true",
        help="Include the automated findings table in the Mini Report Word document.",
    )
    add_stamp_arguments(parser)
    args = parser.parse_args()

    try:
        if not clean_user_path(args.input_file):
            raise ValueError(
                "Input Excel/CSV file is required. Pass it with --input-file."
            )
        input_file = resolve_existing_loop_input(args.input_file)
        output_folder = resolve_existing_folder(args.output_folder)
        healthy_seconds = parse_timespan_to_seconds(args.healthy_threshold)
        critical_seconds = parse_timespan_to_seconds(args.critical_threshold)
        if args.top_offenders_count < 0:
            raise ValueError("--top-offenders-count must be 0 or greater.")

        if args.deployment_info_folder:
            deployment_info_folder = shared_resolve_existing_folder(
                args.deployment_info_folder, "Deployment_Information folder"
            )
        else:
            deployment_info_folder = discover_deployment_info_folder(input_file)

        if args.top_offenders_file:
            top_offenders_file = shared_resolve_existing_file(
                args.top_offenders_file,
                "client evaluation timing/offenders file",
                {".csv", ".txt", ".log", ".xml"},
            )
        else:
            top_offenders_file = discover_loop_offenders_file(input_file)

        if args.udp_notifications_file:
            udp_notifications_file = shared_resolve_existing_file(
                args.udp_notifications_file,
                "UDP notification file",
                {".csv", ".xml"},
            )
        else:
            udp_notifications_file = discover_udp_notifications_file(input_file)

        report_start = prompt_for_report_date("Report start date", args.report_start_date)
        report_end = prompt_for_report_date("Report end date", args.report_end_date)
        # Both dates are now optional: only validate ordering when both
        # were supplied. Missing dates render downstream as "Not provided".
        if (
            report_start is not None
            and report_end is not None
            and report_end < report_start
        ):
            raise ValueError("Report end date cannot be earlier than report start date.")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        generated_at = datetime.now()
        excel_output = output_folder / f"Client_Loop_Analysis_{timestamp}.xlsx"
        png_output = output_folder / f"Client_Loop_Analysis_{timestamp}.png"
        word_output = output_folder / f"Client_Loop_Analysis_{timestamp}.docx"

        log.step("Loading input file")
        df = load_loop_input(input_file)
        if df.empty:
            raise ValueError("No data found in input file.")

        computer_column, max_column, avg_column = auto_detect_columns(df)

        log.step("Using columns")
        if computer_column:
            log.detail("Computer/Device", computer_column)
        log.detail("Maximum Loop", max_column)
        log.detail("Average Loop", avg_column)

        df = normalize_loop_time_columns(df, max_column, avg_column)
        log.detail("Time format", "normalized selected loop columns to HH:MM:SS")
        command_polling_enabled_column, command_polling_interval_column = (
            auto_detect_command_polling_columns(df)
        )
        if command_polling_enabled_column:
            log.detail("Command Polling Enabled", command_polling_enabled_column)
        if command_polling_interval_column:
            log.detail("Command Polling Interval", command_polling_interval_column)
        (
            fast_hash_verify_enabled_column,
            fast_hash_verify_work_column,
            fast_hash_verify_sleep_column,
        ) = auto_detect_fast_hash_verify_columns(df)
        if fast_hash_verify_enabled_column:
            log.detail("FastHashVerify Enabled", fast_hash_verify_enabled_column)
        if fast_hash_verify_work_column:
            log.detail("FastHashVerify Work", fast_hash_verify_work_column)
        if fast_hash_verify_sleep_column:
            log.detail("FastHashVerify Sleep", fast_hash_verify_sleep_column)
        agent_multicore_scaling_column = auto_detect_agent_multicore_scaling_column(df)
        if agent_multicore_scaling_column:
            log.detail("Client multicore scaling", agent_multicore_scaling_column)
        agent_total_physical_cpu_core_count_column = (
            auto_detect_agent_total_physical_cpu_core_count_column(df)
        )
        if agent_total_physical_cpu_core_count_column:
            log.detail(
                "Client total physical CPU core count",
                agent_total_physical_cpu_core_count_column,
            )
        agent_cpu_work_idle_column, agent_cpu_sleep_idle_column = (
            auto_detect_agent_cpu_idle_columns(df)
        )
        if agent_cpu_work_idle_column:
            log.detail("Client CPU work idle", agent_cpu_work_idle_column)
        if agent_cpu_sleep_idle_column:
            log.detail("Client CPU sleep idle", agent_cpu_sleep_idle_column)

        # Load UDP data early so it can be merged into the loop data
        udp_summary = load_udp_notification_summary(udp_notifications_file)
        udp_data_dict = {}
        if udp_summary and hasattr(udp_summary, "rows"):
            for row in udp_summary.rows:
                status_text = (
                    "Yes"
                    if row.get("status") is True
                    else ("No" if row.get("status") is False else "Unknown")
                )
                udp_data_dict[row.get("computer", "")] = {
                    "receiving": status_text,
                    "relay": row.get("relay", ""),
                    "subnet": row.get("subnet", ""),
                }

        processed, not_reported_count, error_count = process_rows(
            df,
            computer_column,
            max_column,
            avg_column,
            udp_data=udp_data_dict,
            command_polling_enabled_column=command_polling_enabled_column,
            command_polling_interval_column=command_polling_interval_column,
            fast_hash_verify_enabled_column=fast_hash_verify_enabled_column,
            fast_hash_verify_work_column=fast_hash_verify_work_column,
            fast_hash_verify_sleep_column=fast_hash_verify_sleep_column,
            agent_multicore_scaling_column=agent_multicore_scaling_column,
            agent_total_physical_cpu_core_count_column=agent_total_physical_cpu_core_count_column,
            agent_cpu_work_idle_column=agent_cpu_work_idle_column,
            agent_cpu_sleep_idle_column=agent_cpu_sleep_idle_column,
        )
        if not processed:
            log.warn("No valid rows were parsed.")
            log.detail("Detected columns")
            for column in df.columns:
                log.detail(column)
            log.detail("First few raw values from selected maximum and average columns")
            for idx, row in df.head(5).iterrows():
                log.detail(
                    f"Row {idx + 1}: [{max_column}] = '{row.get(max_column)}'    [{avg_column}] = '{row.get(avg_column)}'"
                )
            raise ValueError(
                "No valid rows found after parsing. Confirm the selected maximum and average columns contain loop time values."
            )

        metrics, fix_first_devices = calculate_metrics(
            processed=processed,
            total_source_rows=len(df),
            not_reported_count=not_reported_count,
            error_count=error_count,
            healthy_threshold_seconds=healthy_seconds,
            critical_threshold_seconds=critical_seconds,
            report_start=report_start,
            report_end=report_end,
            generated_at=generated_at,
        )
        actionsite_pressure = parse_actionsite_pressure(deployment_info_folder)
        loop_offenders = load_loop_offenders(
            top_offenders_file, top_count=args.top_offenders_count
        )
        command_polling_summary = analyze_command_polling(processed)
        fast_hash_verify_summary = analyze_fast_hash_verify(processed)
        agent_multicore_summary = analyze_agent_multicore(processed)
        agent_cpu_idle_summary = analyze_agent_cpu_idle(processed)

        log.step("Summary")
        log.detail("Devices", metrics.total_devices)
        log.detail("Status", metrics.overall_status)
        log.detail("Score", f"{metrics.environment_score} / 100")
        log.detail(
            "Report Dates", f"{metrics.report_start_text} - {metrics.report_end_text}"
        )
        log.detail("Avg Loop Mean", convert_to_hhmmss(metrics.avg_mean_seconds))
        log.detail("Slowest Avg", convert_to_hhmmss(metrics.slowest_avg_seconds))
        log.detail("Peak Observed", convert_to_hhmmss(metrics.peak_max_seconds))
        log.detail(
            "Avg Healthy", f"{metrics.avg_healthy} ({pct(metrics.avg_healthy_pct)})"
        )
        log.detail(
            "Avg Warning", f"{metrics.avg_warning} ({pct(metrics.avg_warning_pct)})"
        )
        log.detail(
            "Avg Critical", f"{metrics.avg_critical} ({pct(metrics.avg_critical_pct)})"
        )
        log.detail("Not Reported", metrics.not_reported_count)
        log.detail("Error", metrics.error_count)
        if actionsite_pressure:
            log.detail(
                "Client Loop contributing factors",
                str(actionsite_pressure.deployment_info_folder),
            )
        if loop_offenders:
            if top_offenders_file:
                log.detail("Client evaluation timing source", str(top_offenders_file))
            log.detail("Client evaluation offenders", len(loop_offenders))
        if udp_summary:
            log.detail("UDP notification source", str(udp_summary.source_file))
            log.detail("Receiving UDP pings", udp_summary.receiving_count)
            log.detail("Not receiving UDP pings", udp_summary.not_receiving_count)
            log.detail("UDP not reported/error", udp_summary.unknown_count)
        if command_polling_summary:
            log.detail("Command polling enabled", command_polling_summary.enabled_count)
            log.detail(
                "Command polling disabled/not set",
                command_polling_summary.disabled_count
                + command_polling_summary.not_set_count,
            )
            log.detail(
                "Relay placement inference",
                "not performed; use the Client Loop Workbook with customer "
                "network context",
            )
            log.detail(
                "Polling enabled with missing interval",
                command_polling_summary.enabled_missing_interval_count,
            )
            log.detail(
                "Polling interval below average loop",
                command_polling_summary.interval_below_loop_count,
            )
            log.detail(
                "No UDP and polling disabled/not set",
                command_polling_summary.no_udp_polling_gap_count,
            )
        if fast_hash_verify_summary:
            log.detail("FastHashVerify enabled", fast_hash_verify_summary.enabled_count)
            log.detail("FastHashVerify disabled", fast_hash_verify_summary.disabled_count)
            log.detail("FastHashVerify not set", fast_hash_verify_summary.not_set_count)
        if agent_multicore_summary:
            log.detail(
                "Client multicore settings reported",
                agent_multicore_summary.total_devices,
            )
        if agent_cpu_idle_summary:
            log.detail(
                "Client CPU idle settings reported",
                agent_cpu_idle_summary.total_devices,
            )

        log.step("Generating Word-friendly accessible PNG health summary")
        generate_png(
            metrics,
            png_output,
            loop_offenders=loop_offenders,
            udp_summary=udp_summary,
        )

        log.step("Generating Excel workbook")
        stamp = stamp_from_args(args)
        generate_excel(
            metrics,
            processed,
            fix_first_devices,
            excel_output,
            actionsite_pressure=actionsite_pressure,
            loop_offenders=loop_offenders,
            udp_summary=udp_summary,
            command_polling_summary=command_polling_summary,
            fast_hash_verify_summary=fast_hash_verify_summary,
            agent_multicore_summary=agent_multicore_summary,
            agent_cpu_idle_summary=agent_cpu_idle_summary,
            stamp=stamp,
        )

        if not args.skip_word:
            log.step("Generating Word document")
            generate_word(
                metrics,
                png_output,
                word_output,
                actionsite_pressure=actionsite_pressure,
                loop_offenders=loop_offenders,
                udp_summary=udp_summary,
                command_polling_summary=command_polling_summary,
                fast_hash_verify_summary=fast_hash_verify_summary,
                agent_multicore_summary=agent_multicore_summary,
                agent_cpu_idle_summary=agent_cpu_idle_summary,
                stamp=stamp,
                include_automated_findings=args.include_automated_findings,
            )

        log.ok("Client loop analysis built")
        log.result("Excel", excel_output)
        log.result("Chart (PNG)", png_output)
        if not args.skip_word:
            log.result("Word document", word_output)
        return 0

    except Exception as exc:
        log.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
