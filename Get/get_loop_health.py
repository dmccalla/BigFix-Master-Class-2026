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
from Lib.Core.capture_time import capture_time_text
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
from Lib.Design import report_tables, status_spine
from Lib.Themes.workbook_theme import (
    WORKBOOK_THEME,
    finish_openpyxl_workbook,
    xlsxwriter_options,
)

try:
    from docx import Document
    from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
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
    avg_good: int = 0
    avg_good_pct: float = 0.0
    good_threshold_seconds: float = 0.0
    avg_over_critical: int = 0


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
    # MM-DD-YYYY HH:MM of the Content_Info capture the relevant counts come from.
    content_captured: str = ""


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

    if seconds_float >= 60 * 60:
        hours, remainder = divmod(int(math.floor(seconds_float)), 3600)
        minutes, secs = divmod(remainder, 60)
        parts = [f"{hours} {'hour' if hours == 1 else 'hours'}"]
        if minutes:
            parts.append(f"{minutes} {'minute' if minutes == 1 else 'minutes'}")
        if secs:
            parts.append(f"{secs} {'second' if secs == 1 else 'seconds'}")
        return " ".join(parts)

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
    rendered = f"{value * 100:.{decimals}f}"
    if value > 0 and float(rendered) == 0:
        return f"<{10**-decimals:.{decimals}f}%"
    return f"{rendered}%"


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


def _content_capture_time(folder: Path, patterns: list[str]) -> str:
    """The Report Generated time of the Content_Info capture that holds the
    relevant counts, as MM-DD-YYYY HH:MM, or "" when it cannot be read."""
    for path in _candidate_files(folder, patterns):
        text = read_capture_or_log_text(path)
        if not re.search(r"Number of Fixlets\s*:", text, flags=re.IGNORECASE):
            continue
        match = re.search(r"Report Generated\s*:\s*([^\r\n]+)", text, re.IGNORECASE)
        return capture_time_text(match.group(1)) if match else ""
    return ""


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


UDP_NOTIFICATION_COLUMNS = (
    "Computer Name",
    "IPv4 Addresses",
    "Relay",
    "Platform Health Check - Receiving UDP Pings",
)
_UDP_STATUS_RE = re.compile(r"^(?:true|false|yes|no|not reported)\b", re.IGNORECASE)


def udp_capture_rows(text: str) -> list[list[str]]:
    """Rows of a headerless UDP BESAPI capture.

    Splits each answer the way query_properties.ps1 does: on commas, with
    any extra leading fields folded into the computer name, keeping only
    answers whose fourth field is a UDP status.
    """
    rows: list[list[str]] = []
    for line in text.splitlines():
        if not line.strip() or re.match(r"^\s*Computer Name\s*,", line):
            continue
        parts = line.split(",")
        if len(parts) < 4:
            continue
        if len(parts) > 4:
            lead = len(parts) - 3
            parts = [",".join(parts[:lead]), *parts[lead:]]
        parts = [part.strip() for part in parts]
        if _UDP_STATUS_RE.match(parts[3]):
            rows.append(parts)
    return rows


def _is_udp_notifications_file(path: Path) -> bool:
    if path.suffix.lower() not in {".csv", ".xml"}:
        return False
    if path.suffix.lower() == ".xml":
        sampled = sample_capture_lines(path, 1)
        if sampled and udp_capture_rows(sampled[0]):
            return True

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
            r"Number of Activ(?:ated|ed|e) Analyses\s*:\s*([\d,]+)",
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
            r"(?:Total )?Number of Master Operator Analyses\s*:\s*([\d,]+)",
        ),
        content_captured=_content_capture_time(folder, content_patterns),
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


def _actionsite_size_status_for_value(
    value: float | None, soft_warning: float, hard_ceiling: float
) -> str:
    """ActionSite size: Healthy up to the soft warning, Critical over the ceiling."""
    if value is None:
        return status_spine.NOT_ASSESSED.word
    if value > hard_ceiling:
        return status_spine.CRITICAL.word
    if value > soft_warning:
        return status_spine.NEEDS_ATTENTION.word
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


def _content_as_of(pressure: ActionSitePressure) -> str:
    """Names the capture behind a relevant count, which the Deployment Overview
    can show from a different capture (Duncan, 10-21)."""
    if not pressure.content_captured:
        return ""
    return f", as of the {pressure.content_captured} capture"


def _fixlets_tasks_value(pressure: ActionSitePressure) -> str:
    total = _fixlets_tasks_total(pressure)
    relevant = _fixlets_tasks_relevant_total(pressure)
    if total is None:
        return "Not detected"
    return (
        f"{_count_or_zero(relevant)} relevant of {total:,} total"
        f"{_content_as_of(pressure)}. "
        f"Fixlets: {_count_or_zero(pressure.fixlets_relevant_count)} relevant of "
        f"{_count_or_zero(pressure.fixlets_total_count)}. "
        f"Tasks: {_count_or_zero(pressure.tasks_relevant_count)} relevant of "
        f"{_count_or_zero(pressure.tasks_total_count)}."
    )


def _analyses_value(pressure: ActionSitePressure) -> str:
    if pressure.analyses_total_count is None and pressure.active_analyses_count is None:
        return "Not detected"
    relevant_total = (
        "not detected"
        if pressure.analyses_total_count is None
        else f"{_count_or_zero(pressure.analyses_relevant_count)} relevant of "
        f"{pressure.analyses_total_count:,} total{_content_as_of(pressure)}"
    )
    return f"{relevant_total}. {_count_or_zero(pressure.active_analyses_count)} active."


def _properties_value(pressure: ActionSitePressure) -> str:
    return _total_with_parts(
        pressure.properties_count,
        [
            f"{_count_or_zero(pressure.active_properties_count)} active",
            f"{_count_or_zero(pressure.custom_properties_count)} with the BigFix custom flag",
        ],
    )


# ---------------------------------------------------------------------------
# Evaluation Frequency: how often each active property is evaluated
# ---------------------------------------------------------------------------

PROPERTY_INTERVAL_SECTION = "Active Properties by Evaluation Interval"
RETRIEVED_PROPERTY_SECTION = "Retrieved Properties by Evaluation Interval"
PROPERTY_SOURCE_NOTE = (
    "The property count uses the BigFix property custom flag. "
    "Evaluation Frequency groups active analysis properties by source site. "
    "These are different classifications."
)
RETRIEVED_PROPERTY_SOURCE_NOTE = (
    "The property count uses the BigFix property custom flag. "
    "Evaluation Frequency groups active analysis properties by source site and "
    "retrieved properties by type. These are different classifications."
)
CONTENT_CAPTURE_NOTE = (
    "Content counts come from a separate deployment capture. Its timestamp is "
    "shown with the counts and may differ from the client loop collection period."
)
PROPERTY_INTERVAL_WIDTH = 9
RETRIEVED_PROPERTY_WIDTH = 6
PROPERTY_INTERVAL_FREQUENT_MINUTES = 15.0
PROPERTY_INTERVAL_GUIDELINE_MINUTES = 360.0
INTERVAL_BAND_ORDER = (
    "Every report",
    "Under 15 minutes",
    "15 minutes to 1 hour",
    "1 hour to 6 hours",
    "6 hours or longer",
    "Unreadable",
)


@dataclass
class PropertyInterval:
    name: str
    analysis: str
    site: str
    issuer: str
    interval_minutes: float | None
    content_source: str


@dataclass
class RetrievedProperty:
    """A property that belongs to no analysis, such as Computer Name."""

    name: str
    site_id: str
    item_id: str
    index: str
    interval_minutes: float | None
    property_type: str

    @property
    def reserved(self) -> bool:
        return self.property_type.lower() == "reserved"

    @property
    def content_source(self) -> str:
        """Reserved, or the Evaluation Frequency column the property counts in.

        BigFix default retrieved properties count as External.
        """
        if self.reserved:
            return "Reserved"
        return "Custom" if self.property_type.lower() == "custom" else "External"


@dataclass
class PropertyIntervalSummary:
    source_file: Path
    properties: list[PropertyInterval]
    # None for a capture made before the retrieved property section.
    retrieved: list[RetrievedProperty] | None = None

    @property
    def counted_retrieved(self) -> list[RetrievedProperty]:
        """Retrieved properties that count. A reserved property's interval cannot
        be changed, so reserved properties are left out."""
        return [item for item in self.retrieved or [] if not item.reserved]

    @property
    def counted(self) -> list[PropertyInterval | RetrievedProperty]:
        """Every property Evaluation Frequency and CLT-01 count."""
        return [*self.properties, *self.counted_retrieved]


def parse_interval_minutes(text: str) -> float | None:
    """Minutes for a BigFix interval string, or None when none is set.

    The collection writes 00:00:00 for every report, 01:00:00 style clocks,
    and "1 day" style spans. no-val means the property has no interval, and
    BigFix evaluates such a property every report, so it reads as 0 minutes.
    None is left for a value that cannot be read, shown as Unreadable.
    """
    value = text.strip().lower()
    if not value or value == "no-val":
        return 0.0
    minutes = 0.0
    matched = False
    day = re.search(r"(\d+)\s*days?", value)
    if day:
        minutes += int(day.group(1)) * 1440
        matched = True
    clock = re.search(r"(\d+):(\d{2}):(\d{2})", value)
    if clock:
        minutes += (
            int(clock.group(1)) * 60 + int(clock.group(2)) + int(clock.group(3)) / 60
        )
        matched = True
    return minutes if matched else None


def interval_band(minutes: float | None) -> str:
    if minutes is None:
        return "Unreadable"
    if minutes <= 0:
        return "Every report"
    if minutes < PROPERTY_INTERVAL_FREQUENT_MINUTES:
        return "Under 15 minutes"
    if minutes < 60:
        return "15 minutes to 1 hour"
    if minutes < PROPERTY_INTERVAL_GUIDELINE_MINUTES:
        return "1 hour to 6 hours"
    return "6 hours or longer"


def interval_band_status(band: str) -> str:
    if band in {"Every report", "Under 15 minutes"}:
        return status_spine.NEEDS_ATTENTION.word
    if band in {"15 minutes to 1 hour", "1 hour to 6 hours"}:
        return status_spine.ADVISORY.word
    if band == "6 hours or longer":
        return status_spine.HEALTHY.word
    return status_spine.NOT_ASSESSED.word


def format_interval_minutes(minutes: float | None) -> str:
    if minutes is None:
        return "Unreadable"
    if minutes <= 0:
        return "Every report"
    if minutes % 1440 == 0:
        days = int(minutes // 1440)
        return f"{days} day" + ("" if days == 1 else "s")
    if minutes % 60 == 0:
        hours = int(minutes // 60)
        return f"{hours} hour" + ("" if hours == 1 else "s")
    if minutes < 60:
        return f"{minutes:g} minutes"
    return f"{int(minutes // 60)} h {int(minutes % 60)} min"


def _section_values(lines: list[str], section: str) -> list[str] | None:
    """Values of one capture section, or None when the section is absent."""
    start = next(
        (i for i, line in enumerate(lines) if line.startswith("//=") and section in line),
        None,
    )
    if start is None:
        return None
    values: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("//="):
            break
        text = line.strip()
        if not text or text.lower().startswith("column headers:"):
            continue
        values.append(text)
    return values


def _property_interval_rows(lines: list[str]) -> list[PropertyInterval] | None:
    """Rows of the interval section, or None when the section is absent."""
    values = _section_values(lines, PROPERTY_INTERVAL_SECTION)
    if values is None:
        return None
    rows: list[PropertyInterval] = []
    for i in range(0, len(values) - PROPERTY_INTERVAL_WIDTH + 1, PROPERTY_INTERVAL_WIDTH):
        chunk = values[i : i + PROPERTY_INTERVAL_WIDTH]
        rows.append(
            PropertyInterval(
                name=chunk[0],
                analysis=chunk[1],
                site=chunk[2],
                issuer=chunk[6],
                interval_minutes=parse_interval_minutes(chunk[7]),
                content_source=chunk[8],
            )
        )
    return rows


def _retrieved_property_rows(lines: list[str]) -> list[RetrievedProperty] | None:
    """Rows of the retrieved property section, or None when it is absent."""
    values = _section_values(lines, RETRIEVED_PROPERTY_SECTION)
    if values is None:
        return None
    rows: list[RetrievedProperty] = []
    for i in range(
        0, len(values) - RETRIEVED_PROPERTY_WIDTH + 1, RETRIEVED_PROPERTY_WIDTH
    ):
        chunk = values[i : i + RETRIEVED_PROPERTY_WIDTH]
        rows.append(
            RetrievedProperty(
                name=chunk[0],
                site_id=chunk[1],
                item_id=chunk[2],
                index=chunk[3],
                interval_minutes=parse_interval_minutes(chunk[4]),
                property_type=chunk[5],
            )
        )
    return rows


def parse_property_intervals(folder: Path | None) -> PropertyIntervalSummary | None:
    """Read the active property intervals from the Property_Info capture."""
    if folder is None or not folder.is_dir():
        return None
    for path in _candidate_files(
        folder, ["Property_Info*.xml", "Property_Info*.log", "Property_Info*"]
    ):
        lines = read_capture_or_log_text(path).splitlines()
        rows = _property_interval_rows(lines)
        if rows is not None:
            return PropertyIntervalSummary(
                source_file=path,
                properties=rows,
                retrieved=_retrieved_property_rows(lines),
            )
    return None


def property_interval_band_counts(
    summary: PropertyIntervalSummary,
) -> dict[str, dict[str, int]]:
    counts = {
        band: {"total": 0, "custom": 0, "external": 0} for band in INTERVAL_BAND_ORDER
    }
    for item in summary.counted:
        entry = counts[interval_band(item.interval_minutes)]
        entry["total"] += 1
        key = "custom" if item.content_source.lower() == "custom" else "external"
        entry[key] += 1
    return counts


def frequent_property_count(summary: PropertyIntervalSummary | None) -> int:
    """Active properties evaluated every report or more often than 15 minutes."""
    if summary is None:
        return 0
    return sum(
        1
        for item in summary.counted
        if interval_band(item.interval_minutes) in {"Every report", "Under 15 minutes"}
    )


def evaluation_frequency_rows(summary: PropertyIntervalSummary) -> list[list[str]]:
    counts = property_interval_band_counts(summary)
    total = len(summary.counted)
    rows: list[list[str]] = []
    for band in INTERVAL_BAND_ORDER:
        entry = counts[band]
        if band == "Unreadable" and entry["total"] == 0:
            continue
        share = (entry["total"] / total * 100) if total else 0.0
        rows.append(
            [
                band,
                count_with_denominator(entry["total"], total),
                pct(share / 100),
                f"{entry['custom']:,}",
                f"{entry['external']:,}",
                interval_band_status(band),
            ]
        )
    return rows


def active_property_rows(summary: PropertyIntervalSummary) -> list[list[Any]]:
    rows: list[list[Any]] = [
        [
            item.name,
            item.analysis,
            item.site,
            item.issuer,
            format_interval_minutes(item.interval_minutes),
            interval_band(item.interval_minutes),
            item.content_source,
        ]
        for item in summary.properties
    ]
    # A retrieved property has no analysis, source site or issuer. Reserved
    # ones are listed but not counted.
    rows.extend(
        [
            item.name,
            "",
            "",
            "",
            format_interval_minutes(item.interval_minutes),
            interval_band(item.interval_minutes),
            item.content_source,
        ]
        for item in summary.retrieved or []
    )
    return rows


def _counted_phrase(count: int, one: str, many: str) -> str:
    if not count:
        return f"no {many}"
    return f"the 1 {one}" if count == 1 else f"the {count:,} {many}"


def evaluation_frequency_lead(
    summary: PropertyIntervalSummary, *, graphic: bool = False
) -> str:
    """Opening paragraph of Evaluation Frequency."""
    if summary.retrieved is None:
        # A capture made before the retrieved property section.
        population = _counted_phrase(
            len(summary.properties),
            "active analysis property",
            "active analysis properties",
        )
    else:
        population = (
            _counted_phrase(
                len(summary.properties),
                "active analysis property",
                "active analysis properties",
            )
            + " and "
            + _counted_phrase(
                len(summary.counted_retrieved),
                "retrieved property",
                "retrieved properties",
            )
        )
    form = "graphic" if graphic else "table"
    unit = "bar" if graphic else "row"
    return (
        f"This {form} counts {len(summary.counted):,} properties: {population}. "
        f"Each {unit} shows how many are set to each evaluation interval. "
        "A property with no interval counts as Every report, because BigFix "
        "evaluates it every report."
    )


def evaluation_frequency_detail(summary: PropertyIntervalSummary) -> str:
    buckets = property_interval_band_counts(summary)
    frequent = sum(
        buckets[label]["total"] for label in ("Every report", "Under 15 minutes")
    )
    return (
        f"The Every report and Under 15 minutes rows add up to {frequent:,} properties. "
        "CLT-01 reports this count. Those two rows are rated Needs Attention, "
        "15 minutes to 6 hours is Advisory, and 6 hours or longer is Healthy."
    )


def evaluation_frequency_reserved_note(summary: PropertyIntervalSummary) -> str:
    if summary.retrieved is None:
        return ""
    return (
        "Reserved properties are the properties BigFix builds into every Client, "
        "such as Computer Name, OS and IP Address. The Client evaluates them every "
        "report and their interval cannot be changed, so this table and "
        "CLT-01 leave them out."
    )


def evaluation_frequency_source_note(summary: PropertyIntervalSummary) -> str:
    """How Evaluation Frequency sorts properties into Custom and External."""
    retrieved = (
        "It labels custom retrieved properties as Custom and BigFix default "
        "retrieved properties as External. "
        if summary.retrieved is not None
        else ""
    )
    return (
        "Evaluation Frequency labels analysis properties from custom, operator "
        "and master sites as Custom, and those from external sites as External. "
        f"{retrieved}External property intervals may be outside customer control. "
        "Review changes with the content owner."
    )


def property_source_note(summary: PropertyIntervalSummary | None) -> str:
    """The note on the custom-flagged count and the Evaluation Frequency groups."""
    if summary is not None and summary.retrieved is not None:
        return RETRIEVED_PROPERTY_SOURCE_NOTE
    return PROPERTY_SOURCE_NOTE


def _offender_property_key(result: str) -> tuple[str, str] | None:
    """(analysis, property) names from a Top 10 analysis result, else None."""
    fields: dict[str, str] = {}
    for part in result.split(" | "):
        name, sep, value = part.partition("=")
        if sep:
            fields[name.strip().lower()] = value.strip()
    analysis = fields.get("analysis name")
    prop = fields.get("name")
    if not analysis or not prop:
        return None
    return analysis.lower(), prop.lower()


TOP10_KINDS = (
    ("a site evaluation", "site evaluations"),
    ("an analysis property", "analysis properties"),
    ("a retrieved property", "retrieved properties"),
    ("another evaluation", "other evaluations"),
)


def offender_kind(result: str) -> int:
    """Index into TOP10_KINDS for one Top 10 result."""
    text = str(result or "").strip().lower()
    if text.startswith("background evaluation of"):
        return 0
    if _offender_property_key(result) is not None:
        return 1
    if text.startswith("retrieved property"):
        return 2
    return 3


def top10_kind_sentence(loop_offenders: list[LoopOffenderSummary]) -> str:
    """Say what kind of content the Top 10 rows are, accounting for every row."""
    total = len(loop_offenders)
    counts = [0] * len(TOP10_KINDS)
    for item in loop_offenders:
        counts[offender_kind(item.result)] += 1
    order = sorted(
        (index for index, count in enumerate(counts) if count),
        key=lambda index: -counts[index],
    )

    def phrase(index: int) -> str:
        one, many = TOP10_KINDS[index]
        count = counts[index]
        return f"{count} is {one}" if count == 1 else f"{count} are {many}"

    first, *rest = order
    one, many = TOP10_KINDS[first]
    count = counts[first]
    if count == 1:
        sentence = f"1 of these {total} is {one}."
    else:
        sentence = f"{count} of these {total} are {many}."
    if rest:
        parts = [phrase(index) for index in rest]
        tail = (
            parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        )
        sentence += f" {tail[0].upper()}{tail[1:]}."
    if counts[2]:
        sentence += " Retrieved properties include reserved properties."
    return sentence


def top10_interval_sentences(summary: PropertyIntervalSummary | None) -> str:
    """Say what the Top 10 Interval column holds for this capture."""
    if summary is not None and summary.retrieved is not None:
        return (
            "Interval is how often a property is set to run. A site evaluation is "
            "not a property and has no interval."
        )
    # A capture made before the retrieved property section.
    return (
        "Interval is how often an analysis property is set to run. A site "
        "evaluation is not a property and has no interval. A retrieved "
        "property's interval is not in the capture."
    )


_RETRIEVED_RESULT = re.compile(
    r"^Retrieved Property:\s*(?P<name>.*?)"
    r"(?:\s*\([^()]*\.(?P<item>\d+):Evaluate Property (?P<index>\d+)\))?\s*$",
    re.IGNORECASE,
)


def _retrieved_result(result: str) -> tuple[str, str, str] | None:
    """(name, item ID, property index) of a Top 10 retrieved property result.

    The Top 10 script writes "Retrieved Property: NAME (actionsite.13:Evaluate
    Property 1)". The IDs are empty when a result does not carry them.
    """
    match = _RETRIEVED_RESULT.match(str(result or "").strip())
    if match is None:
        return None
    return match.group("name"), match.group("item") or "", match.group("index") or ""


def _retrieved_property(
    result: str, summary: PropertyIntervalSummary | None
) -> RetrievedProperty | None:
    """The captured retrieved property a Top 10 result names, matched by ID."""
    parsed = _retrieved_result(result)
    if parsed is None or summary is None:
        return None
    _, item, index = parsed
    return next(
        (
            prop
            for prop in summary.retrieved or []
            if item and (prop.item_id, prop.index) == (item, index)
        ),
        None,
    )


def offender_interval(result: str, summary: PropertyIntervalSummary | None) -> str:
    """Interval of a Top 10 property, or why there is none."""
    key = _offender_property_key(result)
    if key is None:
        # A site evaluation has no interval.
        if str(result).strip().lower().startswith("background evaluation of"):
            return "Not a property"
        # Another evaluation, or a retrieved property in a capture made before
        # the retrieved property section.
        if (
            _retrieved_result(result) is None
            or summary is None
            or summary.retrieved is None
        ):
            return "Not collected"
        captured = _retrieved_property(result, summary)
        if captured is None:
            return "Not found"
        return format_interval_minutes(captured.interval_minutes)
    if summary is None:
        return "Not collected"
    for item in summary.properties:
        if (item.analysis.lower(), item.name.lower()) == key:
            return format_interval_minutes(item.interval_minutes)
    return "Not found"


# ---------------------------------------------------------------------------
# Minimum Analysis Interval: the Client-side floor on analysis evaluation
# ---------------------------------------------------------------------------

MINIMUM_ANALYSIS_INTERVAL_SETTING = "_BESClient_Report_MinimumAnalysisInterval"
MINIMUM_ANALYSIS_INTERVAL_NO_VALUE_SECONDS = 60
CLIENT_SETTINGS_SECTION = "CLIENT SETTINGS ="


@dataclass
class MinimumAnalysisInterval:
    raw_value: str
    seconds: int | None
    devices: int


def parse_minimum_analysis_interval(
    folder: Path | None,
) -> list[MinimumAnalysisInterval] | None:
    """Value groups of the setting from Client_Settings_Info.

    A device lists the setting only when it is set. A setting with no value
    uses the 60 second default. An empty list means no device sets it.
    """
    if folder is None or not folder.is_dir():
        return None
    name = MINIMUM_ANALYSIS_INTERVAL_SETTING.lower()
    for path in _candidate_files(
        folder, ["Client_Settings_Info*.xml", "Client_Settings_Info*.log"]
    ):
        lines = read_capture_or_log_text(path).splitlines()
        start = next(
            (
                i
                for i, line in enumerate(lines)
                if line.startswith("//=") and CLIENT_SETTINGS_SECTION in line
            ),
            None,
        )
        if start is None:
            continue
        rows: list[MinimumAnalysisInterval] = []
        i = start + 1
        while i + 2 < len(lines) and not lines[i].startswith("//="):
            if lines[i].strip().lower() != name:
                i += 1
                continue
            raw = lines[i + 1].strip()
            count = lines[i + 2].strip().replace(",", "")
            if not raw:
                seconds = MINIMUM_ANALYSIS_INTERVAL_NO_VALUE_SECONDS
            else:
                seconds = int(raw) if raw.isdigit() else None
            rows.append(
                MinimumAnalysisInterval(
                    raw_value=raw,
                    seconds=seconds,
                    devices=int(count) if count.isdigit() else 0,
                )
            )
            i += 3
        rows.sort(
            key=lambda row: -1 if row.seconds is None else row.seconds, reverse=True
        )
        return rows
    return None


def _seconds_in_words(seconds: int) -> str:
    if seconds % 60 == 0:
        minutes = seconds // 60
        return f"{minutes} minute" + ("" if minutes == 1 else "s")
    return f"{seconds:,} seconds"


def _device_count(count: int) -> str:
    return f"{count:,} device" + ("" if count == 1 else "s")


def _minimum_analysis_value(row: MinimumAnalysisInterval) -> str:
    if not row.raw_value:
        return "60 seconds (no value set)"
    return _seconds_in_words(row.seconds or 0)


def minimum_analysis_interval_effect(
    row: MinimumAnalysisInterval, average_loop_seconds: float
) -> str:
    if row.seconds is None:
        return "Cannot tell"
    if row.seconds > average_loop_seconds:
        return f"Analyses run at most once every {_seconds_in_words(row.seconds)}"
    return "No change at the average loop time"


def minimum_analysis_interval_paragraph(rows: list[MinimumAnalysisInterval]) -> str:
    total = sum(row.devices for row in rows)
    readable = [row for row in rows if row.seconds is not None]
    unreadable = sum(row.devices for row in rows if row.seconds is None)
    sentences = [f"{_device_count(total)} set {MINIMUM_ANALYSIS_INTERVAL_SETTING}."]
    if readable:
        parts = [
            f"{_device_count(row.devices)} {'sets' if row.devices == 1 else 'set'} it "
            f"to {_minimum_analysis_value(row)}"
            for row in readable
        ]
        listed = (
            parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
        )
        sentences.append(listed[0].upper() + listed[1:] + ".")
        sentences.append(
            "A device with this setting runs its analyses at most once per that interval."
        )
    if unreadable:
        verb = "has" if unreadable == 1 else "have"
        sentences.append(
            f"{_device_count(unreadable)} {verb} a value that cannot be read."
        )
    return " ".join(sentences)


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
            _actionsite_size_status_for_value(size_mb, 10.0, 25.0),
            "Healthy at 10 MB or below. Soft warning over 10 MB. Hard ceiling at 25 MB.",
        ],
        [
            "Subscribed sites",
            _subscribed_sites_value(pressure),
            _status_for_thresholds([(_subscribed_sites_total(pressure), 100)]),
            "Healthy at 100 or fewer. Review when over 100.",
        ],
        [
            "Computer groups",
            _computer_groups_value(pressure),
            _status_for_thresholds([(_computer_groups_total(pressure), 100)]),
            "Healthy at 100 or fewer. Review when over 100.",
        ],
        [
            "Fixlets and tasks",
            _fixlets_tasks_value(pressure),
            _status_for_thresholds([(_fixlets_tasks_total(pressure), 80_000)]),
            "Healthy at 80,000 total or fewer. Review when over 80,000.",
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
            "Healthy at 10,000 total or fewer and 500 active or fewer. Review if either is over threshold.",
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
            "Healthy at 10,000 total or fewer and 500 active or fewer. Review if either is over threshold.",
        ],
        [
            "Master operators",
            format_optional_int(pressure.master_operator_count),
            _actionsite_status_for_value(pressure.master_operator_count, 5),
            "Healthy at 5 or fewer. Review when over 5.",
        ],
        [
            "Open actions issued by master operators",
            format_optional_int(pressure.master_open_actions),
            _actionsite_status_for_value(pressure.master_open_actions, 25),
            "Healthy at 25 or fewer. Review when over 25.",
        ],
        [
            "Master-operator fixlets/tasks/analyses",
            custom_value,
            custom_status,
            "Healthy below 50 combined. Review at 50 or more.",
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


def format_minutes_seconds(seconds: float) -> str:
    """Format a duration the way the Infographic shows it, such as 6m 21s."""
    total = int(round(seconds))
    minutes, secs = divmod(total, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m {secs:02d}s"


def format_loop_offender_strip_seconds(seconds: float | None) -> str:
    try:
        seconds_float = float(seconds)
    except (TypeError, ValueError):
        return "Not available"
    if math.isnan(seconds_float) or seconds_float <= 0:
        return "Not available"
    return f"{seconds_float:,.1f} s"


def format_loop_offender_evaluation(
    result: str, summary: PropertyIntervalSummary | None = None
) -> str:
    """Name an analysis or retrieved property. Leave other results as they are."""
    text = str(result or "").strip()
    retrieved = _retrieved_result(text)
    if retrieved is not None:
        captured = _retrieved_property(text, summary)
        kind = "reserved" if captured is not None and captured.reserved else "retrieved"
        return f"{retrieved[0]} ({kind} property)"
    fields: dict[str, str] = {}
    for part in text.split(" | "):
        name, sep, value = part.partition("=")
        if sep:
            fields[name.strip().lower()] = value.strip()
    analysis = fields.get("analysis name")
    prop = fields.get("name") or fields.get("display name")
    if analysis and prop:
        return f"{prop} (analysis: {analysis})"
    return text


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
    return text.casefold() or "Not reported"


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
            # The BESAPI capture has no header row.
            df = pd.DataFrame(
                udp_capture_rows(read_capture_or_log_text(path)),
                columns=list(UDP_NOTIFICATION_COLUMNS),
            )
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
                pct(pct_value),
            ]
        )
    relay_rows.sort(
        key=lambda row: (
            -int(row[1].split("/", 1)[0].replace(",", "").strip()),
            -int(row[1].split("/", 1)[0].replace(",", "").strip())
            / max(int(row[1].split("/", 1)[1].replace(",", "").strip()), 1),
            row[0].casefold(),
        )
    )

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
            f"{missing_count:,} {'client' if missing_count == 1 else 'clients'} not receiving UDP pings did not report a "
            "relay and/or IPv4 address, and were excluded from the corresponding "
            "rollups."
        )
    elif summary.not_receiving_missing_relay_count:
        notes.append(
            f"{summary.not_receiving_missing_relay_count:,} {'client' if summary.not_receiving_missing_relay_count == 1 else 'clients'} not receiving "
            "UDP pings did not report a relay, so they were excluded from the relay "
            "issue rollup."
        )
    elif summary.not_receiving_missing_subnet_count:
        notes.append(
            f"{summary.not_receiving_missing_subnet_count:,} {'client' if summary.not_receiving_missing_subnet_count == 1 else 'clients'} not receiving "
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
        [
            work,
            sleep,
            configured_cpu_duty_cycle(work, sleep),
            count_with_denominator(count, len(fast_hash_rows)),
        ]
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
        return pct(count / denominator)

    return [
        [
            "Enabled",
            count_with_denominator(summary.enabled_count, total),
            percent(summary.enabled_count),
        ],
        [
            "Disabled",
            count_with_denominator(summary.disabled_count, total),
            percent(summary.disabled_count),
        ],
        [
            "Not Set",
            count_with_denominator(summary.not_set_count, total),
            percent(summary.not_set_count),
        ],
        [
            "Unknown",
            count_with_denominator(summary.unknown_count, total),
            percent(summary.unknown_count),
        ],
    ]


def analyze_agent_multicore(
    rows: list[ProcessedRow],
) -> AgentMulticoreSummary | None:
    """Group the supported 11.0.7 agent multicore switch without assessing it."""
    multicore_rows = [row for row in rows if row.agent_multicore_scaling_enabled]
    if not multicore_rows:
        return None

    settings = Counter(
        row.agent_multicore_scaling_enabled or "Not Set" for row in multicore_rows
    )
    settings_rows = [
        [scaling, count_with_denominator(count, len(multicore_rows))]
        for scaling, count in sorted(
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
            count_with_denominator(count, len(idle_rows)),
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
    good_threshold_seconds: float | None = None,
) -> tuple[ReportMetrics, list[ProcessedRow]]:
    if critical_threshold_seconds <= healthy_threshold_seconds:
        raise ValueError("CriticalThreshold must be greater than HealthyThreshold.")
    # Good runs from the healthy threshold up to this one. Without it there is no
    # Good group.
    good_seconds = (
        healthy_threshold_seconds
        if good_threshold_seconds is None
        else good_threshold_seconds
    )
    if not healthy_threshold_seconds <= good_seconds <= critical_threshold_seconds:
        raise ValueError(
            "GoodThreshold must be between HealthyThreshold and CriticalThreshold."
        )

    total_devices = len(processed)
    if total_devices == 0:
        raise ValueError(
            "No valid rows found after parsing. Confirm the selected maximum and average columns contain loop time values."
        )

    total_issue_count = not_reported_count + error_count
    avg_healthy = sum(1 for r in processed if r.avg_seconds < healthy_threshold_seconds)
    avg_good = sum(
        1 for r in processed if healthy_threshold_seconds <= r.avg_seconds < good_seconds
    )
    avg_warning = sum(
        1
        for r in processed
        if good_seconds <= r.avg_seconds <= critical_threshold_seconds
    )
    avg_over_critical = sum(
        1 for r in processed if r.avg_seconds > critical_threshold_seconds
    )
    avg_critical = avg_over_critical + total_issue_count

    safe_total_rows = max(1, total_source_rows)
    score_total_devices = total_devices + total_issue_count
    safe_score_total = max(1, score_total_devices)

    avg_healthy_pct = avg_healthy / safe_score_total
    avg_good_pct = avg_good / safe_score_total
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
        (avg_healthy_pct * LOOP_GROUP_POINTS["Healthy"])
        + (avg_good_pct * LOOP_GROUP_POINTS["Good"])
        + (avg_warning_pct * LOOP_GROUP_POINTS["Warning"])
        + (avg_critical_pct * LOOP_GROUP_POINTS["Critical"])
    )
    environment_score = max(0, min(100, environment_score))

    if environment_score < 70:
        overall_status = "CRITICAL"
    elif environment_score < 90:
        overall_status = "WARNING"
    else:
        overall_status = "HEALTHY"

    score_driver = "Average Loop Health Score = Healthy% x 100 + Good% x 85 + Warning% x 67 + Critical% x 34. Critical includes > 60 minutes plus Not Reported/Error rows."
    score_breakdown = f"{pct(avg_healthy_pct, 0)} Healthy, {pct(avg_good_pct, 0)} Good, {pct(avg_warning_pct, 0)} Warning, {pct(avg_critical_pct, 0)} Critical -> Average Loop Health Score {environment_score}"

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
        generated_at_text=f"{generated_at:%m-%d-%Y %H:%M:%S}",
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
        avg_good=avg_good,
        avg_good_pct=avg_good_pct,
        good_threshold_seconds=good_seconds,
        avg_over_critical=avg_over_critical,
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


# CLT-01 is the one Client Performance finding. It can carry several reasons,
# and its impact is the highest impact among them.
LOOP_FINDING_ID = "CLT-01"
NO_DATA_PCT_LIMIT = 5.0
_IMPACT_RANK = {"Medium": 1, "High": 2, "Critical": 3}


@dataclass
class LoopFindingReason:
    impact: str
    text: str
    section: str


def no_usable_data_raised(metrics: ReportMetrics) -> bool:
    """True when more than 5% of scored devices have no usable loop data."""
    total = metrics.score_total_devices
    if total <= 0:
        return False
    return metrics.total_issue_count / total * 100 > NO_DATA_PCT_LIMIT


def loop_finding_reasons(
    metrics: ReportMetrics,
    property_intervals: PropertyIntervalSummary | None = None,
) -> list[LoopFindingReason]:
    reasons: list[LoopFindingReason] = []
    impact = {"WARNING": "High", "CRITICAL": "Critical"}.get(
        str(metrics.overall_status or "").upper()
    )
    if impact:
        limit = 70 if impact == "Critical" else 90
        reasons.append(
            LoopFindingReason(
                impact,
                f"The client loop health score is below {limit}",
                "Loop Health",
            )
        )
    frequent = frequent_property_count(property_intervals)
    if frequent:
        subject = "1 property is" if frequent == 1 else f"{frequent:,} properties are"
        reasons.append(
            LoopFindingReason(
                "Medium",
                f"{subject} set to every report or to under 15 minutes",
                "Evaluation Frequency",
            )
        )
    if no_usable_data_raised(metrics):
        verb = "has" if metrics.total_issue_count == 1 else "have"
        reasons.append(
            LoopFindingReason(
                "Medium",
                f"{metrics.total_issue_count:,} of {metrics.score_total_devices:,} "
                f"devices ({pct(metrics.total_issue_pct)}) {verb} no usable loop data",
                "Loop Health",
            )
        )
    return reasons


def loop_finding_impact(reasons: list[LoopFindingReason]) -> str:
    return max((r.impact for r in reasons), key=_IMPACT_RANK.__getitem__, default="")


def loop_finding_text(reasons: list[LoopFindingReason]) -> str:
    """Infographic text: the impact, then each reason as its own sentence."""
    if not reasons:
        return ""
    return f"{loop_finding_impact(reasons)}. " + " ".join(f"{r.text}." for r in reasons)


def loop_findings_line(reasons: list[LoopFindingReason]) -> str:
    """Infographic header line, for example Raises 1 High finding (2 reasons)."""
    if not reasons:
        return ""
    line = f"Raises 1 {loop_finding_impact(reasons)} finding"
    if len(reasons) > 1:
        line += f" ({len(reasons)} reasons)"
    return line


def generate_png(
    metrics: ReportMetrics,
    png_output: Path,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
    property_intervals: PropertyIntervalSummary | None = None,
) -> None:
    """Render the Client Loop Performance infographic from the design HTML.

    Builds the chart's data from ReportMetrics and screenshots the design
    template via html_charts -- pixel-exact to the handoff, no reconstruction.
    """
    from Lib.Design import html_charts

    scored_total = metrics.score_total_devices
    h_min = metrics.healthy_threshold_seconds / 60.0
    g_min = metrics.good_threshold_seconds / 60.0
    c_min = metrics.critical_threshold_seconds / 60.0
    has_good = metrics.good_threshold_seconds > metrics.healthy_threshold_seconds

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

    m_s = format_minutes_seconds

    # Distribution: only the non-zero buckets become labelled segments; thin
    # segments get a min width + smaller number (matches the design).
    # Devices with no usable data are Critical, drawn as a hatched part of it.
    buckets = [
        (metrics.avg_healthy, status_spine.HEALTHY.mark, False),
        (metrics.avg_good, status_spine.GOOD.mark, False),
        (metrics.avg_warning, status_spine.NEEDS_ATTENTION.mark, False),
        (
            metrics.avg_critical - metrics.total_issue_count,
            status_spine.CRITICAL.mark,
            False,
        ),
        (metrics.total_issue_count, status_spine.CRITICAL.mark, True),
    ]
    seg_total = sum(c for c, _, _ in buckets) or 1
    dist = []
    for cnt, color, hatch in buckets:
        if cnt <= 0:
            continue
        pct = cnt / seg_total * 100
        seg = {
            "pct": round(pct, 3),
            "color": color,
            "num": f"{cnt:,}",
            "fs": 18 if pct >= 8 else 16,
        }
        if hatch:
            # The hatched part carries no printed number. The legend names it.
            seg["hatch"] = True
            seg["count"] = ""
        if pct < 8:
            seg["minw"] = 64
        dist.append(seg)

    legend = [
        {
            "color": status_spine.HEALTHY.mark,
            "label": f"Healthy under {fmt_min(h_min)} min",
            "points": LOOP_GROUP_POINTS["Healthy"],
            "count": f"{metrics.avg_healthy:,}",
            "pct": round(metrics.avg_healthy_pct * 100, 1)
            if metrics.avg_healthy
            else None,
        },
    ]
    if has_good:
        legend.append(
            {
                "color": status_spine.GOOD.mark,
                "label": f"Good {fmt_min(h_min)} to {fmt_min(g_min)} min",
                "points": LOOP_GROUP_POINTS["Good"],
                "count": f"{metrics.avg_good:,}",
                "pct": round(metrics.avg_good_pct * 100, 1) if metrics.avg_good else None,
            }
        )
    legend += [
        {
            "color": status_spine.NEEDS_ATTENTION.mark,
            "label": f"Needs Attention {fmt_min(g_min)} to {fmt_min(c_min)} min",
            "points": LOOP_GROUP_POINTS["Warning"],
            "count": f"{metrics.avg_warning:,}",
            "pct": round(metrics.avg_warning_pct * 100, 1)
            if metrics.avg_warning
            else None,
        },
        {
            "color": status_spine.CRITICAL.mark,
            "label": f"Critical over {fmt_min(c_min)} min",
            "points": LOOP_GROUP_POINTS["Critical"],
            "count": f"{metrics.avg_over_critical:,}",
            "pct": None,
        },
        {
            "color": status_spine.CRITICAL.mark,
            "label": "Critical no usable data",
            "points": LOOP_GROUP_POINTS["Critical"],
            "count": f"{metrics.total_issue_count:,}",
            "pct": None,
            "hatch": True,
        },
    ]

    meta = f"{scored_total:,} devices scored"
    # Only a real span reads as "N days collection". Missing or invalid dates
    # stay in Excel's Report Range row.
    if metrics.report_span_text.endswith(("day", "days")):
        meta += f" &middot; {metrics.report_span_text} collection"

    reasons = loop_finding_reasons(metrics, property_intervals)
    findings: list[dict[str, str]] = (
        [{"id": LOOP_FINDING_ID, "text": loop_finding_text(reasons)}] if reasons else []
    )

    top_offender = loop_offenders[0] if loop_offenders else None
    if top_offender:
        slow_value = format_loop_offender_strip_seconds(
            top_offender.avg_client_processing_seconds
        )
        slow_detail = compact_loop_offender_label(
            format_loop_offender_evaluation(top_offender.result, property_intervals)
        )
    else:
        slow_value = "Not available"
        slow_detail = "Top 10 data not provided"

    data = {
        "title": "Client Performance",
        "meta": meta,
        "findingsLine": loop_findings_line(reasons),
        "findings": findings,
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
                "label": "Devices averaging over 120 min",
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
    property_intervals: PropertyIntervalSummary | None = None,
    minimum_analysis_interval: list[MinimumAnalysisInterval] | None = None,
    stamp: str = "",
) -> None:
    metrics_rows = [
        ("Devices Scored", metrics.score_total_devices),
        ("Devices Reporting", metrics.total_devices),
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
            "Average Loop Good",
            f"{metrics.avg_good} ({pct(metrics.avg_good_pct)})",
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
        ("Good Threshold", convert_to_hhmmss(metrics.good_threshold_seconds)),
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
                "Group": "Healthy",
                "Definition": f"< {convert_to_hhmmss(metrics.healthy_threshold_seconds)}",
                "Count": metrics.avg_healthy,
                "Percent": metrics.avg_healthy_pct,
            },
            {
                "Basis": "Average Loop",
                "Group": "Good",
                "Definition": f">= {convert_to_hhmmss(metrics.healthy_threshold_seconds)} and < {convert_to_hhmmss(metrics.good_threshold_seconds)}",
                "Count": metrics.avg_good,
                "Percent": metrics.avg_good_pct,
            },
            {
                "Basis": "Average Loop",
                "Group": "Warning",
                "Definition": f">= {convert_to_hhmmss(metrics.good_threshold_seconds)} and <= {convert_to_hhmmss(metrics.critical_threshold_seconds)}",
                "Count": metrics.avg_warning,
                "Percent": metrics.avg_warning_pct,
            },
            {
                "Basis": "Average Loop",
                "Group": "Critical",
                "Definition": f"> {convert_to_hhmmss(metrics.critical_threshold_seconds)} or no usable data",
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

    with pd.ExcelWriter(
        excel_output,
        engine="xlsxwriter",
        engine_kwargs={"options": xlsxwriter_options()},
    ) as writer:
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
                        "Interval": offender_interval(item.result, property_intervals),
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
            source_notes = [property_source_note(property_intervals)]
            if actionsite_pressure.content_captured:
                source_notes.append(CONTENT_CAPTURE_NOTE)
            pd.DataFrame({"Note": source_notes}).to_excel(
                writer, sheet_name="Data Notes", index=False
            )
        if property_intervals:
            pd.DataFrame(
                evaluation_frequency_rows(property_intervals),
                columns=[
                    "Interval",
                    "Properties / Active",
                    "% of Active",
                    "Custom",
                    "External",
                    "Status",
                ],
            ).to_excel(writer, sheet_name="Evaluation Frequency", index=False)
            pd.DataFrame(
                active_property_rows(property_intervals),
                columns=[
                    "Property",
                    "Analysis",
                    "Site",
                    "Issued By",
                    "Interval",
                    "Interval Band",
                    "Content Source",
                ],
            ).to_excel(writer, sheet_name="Active Properties", index=False)
        if minimum_analysis_interval:
            pd.DataFrame(
                [
                    [
                        MINIMUM_ANALYSIS_INTERVAL_SETTING,
                        row.raw_value,
                        row.seconds,
                        row.devices,
                        minimum_analysis_interval_effect(row, metrics.avg_mean_seconds),
                    ]
                    for row in minimum_analysis_interval
                ],
                columns=[
                    "Setting",
                    "Value",
                    "Seconds Used",
                    "Devices",
                    "Effect at the Average Loop Time",
                ],
            ).to_excel(writer, sheet_name="Min Analysis Interval", index=False)
        if udp_summary:
            pd.DataFrame(
                udp_coverage_rows(udp_summary),
                columns=["Status", "Devices / Total", "% of Total"],
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
                columns=["Status", "Devices / Total", "% of Total"],
            ).to_excel(writer, sheet_name="Polling Summary", index=False)
            if command_polling_summary.relay_rows:
                pd.DataFrame(
                    command_polling_summary.relay_rows,
                    columns=[
                        "Relay",
                        "Total Devices",
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
                        "Total Devices",
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
                columns=["Status", "Devices / Total", "% of Total"],
            ).to_excel(writer, sheet_name="FastHashVerify Summary", index=False)
            pd.DataFrame(
                fast_hash_verify_summary.settings_rows,
                columns=[
                    "Work (ms)",
                    "Sleep (ms)",
                    "Configured Duty Cycle (%)",
                    "Devices / Total",
                ],
            ).to_excel(writer, sheet_name="FastHashVerify Settings", index=False)
        if agent_multicore_summary:
            pd.DataFrame(
                agent_multicore_summary.settings_rows,
                columns=[
                    "Multicore CPU Scaling Enabled",
                    "Devices / Total",
                ],
            ).to_excel(writer, sheet_name="Client Multicore Settings", index=False)
        if agent_cpu_idle_summary:
            pd.DataFrame(
                agent_cpu_idle_summary.settings_rows,
                columns=[
                    "Work Idle (ms)",
                    "Sleep Idle (ms)",
                    "Configured Duty Cycle (%)",
                    "Devices / Total",
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
    status_col: int | None = None,
) -> None:
    """
    Build a Word table using the same conservative table styling the module
    documents share:
      - BigFixContent table style
      - light blue header with black text
      - grid borders
      - wrapped text
      - column alignment, width and layout from Lib.Design.report_tables
      - clean vertical alignment
    """
    table = document.add_table(rows=1, cols=len(headers))
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

    # Spacer after every table so the injected client-loop tables don't cram
    # together -- gives separation between consecutive tables and after the last.
    document.add_paragraph()


def context_strip_tiles(
    metrics: ReportMetrics,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
) -> list[dict[str, object]]:
    score_total = metrics.score_total_devices
    if udp_summary:
        udp_value = count_with_denominator(
            udp_summary.not_receiving_count, udp_summary.total_devices
        )
        udp_detail = "Devices with no UDP pings in the UDP capture. The UDP capture and client loop capture can contain different populations."

        if udp_summary.relay_rows:
            relay_name, relay_count, _relay_pct = udp_summary.relay_rows[0]
            relay_value = str(relay_count).strip()
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

    reporting_value = count_with_denominator(metrics.total_devices, score_total)
    reporting_detail = (
        f"{metrics.total_issue_count:,} {'has' if metrics.total_issue_count == 1 else 'have'} no usable loop data"
        if metrics.total_issue_count
        else "All scored devices have usable loop data"
    )

    reporting_tile: dict[str, object] = {
        "label": "Devices reporting",
        "value": reporting_value,
        "caption": reporting_detail,
        "muted": False,
    }
    if no_usable_data_raised(metrics):
        # Red only when CLT-01 names missing loop data.
        reporting_tile["color"] = status_spine.CRITICAL.mark

    return [
        reporting_tile,
        {
            "label": "No UDP pings received",
            "value": udp_value,
            "caption": udp_detail,
            "muted": udp_muted,
        },
        {
            "label": "Relay with most UDP issues",
            "value": relay_value,
            "caption": relay_detail,
            "muted": relay_muted,
        },
    ]


def loop_group_rows(metrics: ReportMetrics) -> list[list[str]]:
    """Loop Health table rows. No usable data is its own Critical row."""
    total = metrics.score_total_devices
    h_min = f"{metrics.healthy_threshold_seconds / 60:g}"
    g_min = f"{metrics.good_threshold_seconds / 60:g}"
    c_min = f"{metrics.critical_threshold_seconds / 60:g}"
    safe = max(1, total)
    rows = [
        [
            "Healthy",
            count_with_denominator(metrics.avg_healthy, total),
            pct(metrics.avg_healthy_pct),
            f"< {h_min} minutes",
        ]
    ]
    if metrics.good_threshold_seconds > metrics.healthy_threshold_seconds:
        rows.append(
            [
                "Good",
                count_with_denominator(metrics.avg_good, total),
                pct(metrics.avg_good_pct),
                f"{h_min}-{g_min} minutes",
            ]
        )
    rows += [
        [
            "Warning",
            count_with_denominator(metrics.avg_warning, total),
            pct(metrics.avg_warning_pct),
            f"{g_min}-{c_min} minutes",
        ],
        [
            "Critical",
            count_with_denominator(metrics.avg_over_critical, total),
            pct(metrics.avg_over_critical / safe),
            f"> {c_min} minutes",
        ],
        [
            "Critical",
            count_with_denominator(metrics.total_issue_count, total),
            pct(metrics.total_issue_count / safe),
            "No usable data",
        ],
    ]
    return rows


def client_loop_infographic_key_rows(
    metrics: ReportMetrics,
    loop_offenders: list[LoopOffenderSummary] | None = None,
    udp_summary: UdpNotificationSummary | None = None,
    property_intervals: PropertyIntervalSummary | None = None,
) -> list[list[str]]:
    """Return one row per Infographic tile: the value shown and what it means."""
    context = context_strip_tiles(metrics, loop_offenders, udp_summary)
    tiles = {tile["label"]: str(tile["value"]) for tile in context}
    # The relay tile shows the affected count large and the relay name beneath
    # it. The key names the relay, because that is what the tile identifies.
    relay_tile = next(t for t in context if t["label"] == "Relay with most UDP issues")
    relay_name = (
        f"{relay_tile['value']} on {relay_tile['caption']}"
        if udp_summary and udp_summary.relay_rows
        else str(relay_tile["value"])
    )
    slowest = (
        format_loop_offender_strip_seconds(
            loop_offenders[0].avg_client_processing_seconds
        )
        if loop_offenders
        else "Not available"
    )
    raised = bool(loop_finding_reasons(metrics, property_intervals))
    h_min = f"{metrics.healthy_threshold_seconds / 60:g}"
    g_min = f"{metrics.good_threshold_seconds / 60:g}"
    c_min = f"{metrics.critical_threshold_seconds / 60:g}"
    if metrics.good_threshold_seconds > metrics.healthy_threshold_seconds:
        distribution_counts = (
            metrics.avg_healthy,
            metrics.avg_good,
            metrics.avg_warning,
            metrics.avg_over_critical,
            metrics.total_issue_count,
        )
        distribution_edges = (
            f"under {h_min}, {h_min} to {g_min}, {g_min} to {c_min}, and over {c_min}"
        )
    else:
        distribution_counts = (
            metrics.avg_healthy,
            metrics.avg_warning,
            metrics.avg_over_critical,
            metrics.total_issue_count,
        )
        distribution_edges = f"under {h_min}, {h_min} to {c_min}, and over {c_min}"
    return [
        [
            "Health score",
            f"{metrics.environment_score} / 100",
            "Average of each device's group points. See Loop Health.",
        ],
        [
            "Loop distribution",
            " · ".join(f"{count:,}" for count in distribution_counts),
            f"Devices averaging {distribution_edges} minutes per loop. The hatched "
            "part of Critical is devices with no usable data.",
        ],
        [
            "Average loop time",
            format_minutes_seconds(metrics.avg_mean_seconds),
            "Mean of every device's average loop time.",
        ],
        [
            "Slowest evaluation",
            slowest,
            "Top entry in Top 10 Most Expensive Evaluations.",
        ],
        [
            "Devices averaging over 120 min",
            f"{metrics.avg_over_120:,}",
            "Devices with an average loop time over 120 minutes.",
        ],
        [
            "Devices reporting",
            tiles["Devices reporting"],
            "Devices that reported usable loop data. Devices without it count "
            "as Critical in the distribution and the score.",
        ],
        [
            "No UDP pings received",
            tiles["No UDP pings received"],
            "Devices that receive no UDP notifications from their relay.",
        ],
        [
            "Relay with most UDP issues",
            relay_name,
            "Relay with the most devices that receive no UDP notifications.",
        ],
        [
            "Findings raised",
            LOOP_FINDING_ID if raised else "None raised",
            "CLT-01 is raised for any of three reasons. The health score is "
            "below 90. A property is set to every report or to under 15 "
            "minutes. More than 5% of devices have no usable loop data.",
        ],
    ]


def keep_with_next(paragraph):
    """Keep a heading or lead-in sentence on the same page as what follows it."""
    paragraph.paragraph_format.keep_with_next = True
    return paragraph


def add_note_paragraph(document, text: str) -> None:
    # A note under a table is its caption, so the spacer build_word_table adds
    # after the table is dropped and the note sits 4 pt under it.
    blocks = [el for el in document.element.body if el.tag != qn("w:sectPr")]
    if (
        len(blocks) >= 2
        and blocks[-2].tag == qn("w:tbl")
        and blocks[-1].tag == qn("w:p")
        and not "".join(blocks[-1].itertext()).strip()
    ):
        blocks[-1].getparent().remove(blocks[-1])
    paragraph = document.add_paragraph()
    paragraph.paragraph_format.space_before = Pt(4)
    paragraph.paragraph_format.space_after = Pt(12)
    paragraph.add_run(text)


# Rollup tables in the Mini Report stop at this many rows so a large deployment
# cannot run the report to dozens of pages. The workbook always keeps every row.
MINI_REPORT_ROLLUP_LIMIT = 10


# Points each device earns for its loop group (Duncan's option B, 10-19).
LOOP_GROUP_POINTS = {"Healthy": 100, "Good": 85, "Warning": 67, "Critical": 34}
UNREPORTED_GROUPS = {"Not reported", "Unknown"}

# The Command Polling tables in the Mini Report keep the columns that answer
# whether polling is on and has a usable interval. Disabled, Not Set and Unknown
# stay in the Excel sheets, which keep all 9 columns.
POLLING_MINI_REPORT_COLUMNS = (0, 1, 2, 6, 7, 8)
POLLING_MINI_REPORT_HEADERS = [
    "Total Devices",
    "Enabled",
    "Missing Interval",
    "Interval Below Loop",
    "No UDP + Polling Off",
]


def polling_mini_report_rows(rows: list[list[str]]) -> list[list[str]]:
    """The 9-column polling rollup rows cut to the Mini Report columns."""
    return [[row[i] for i in POLLING_MINI_REPORT_COLUMNS] for row in rows]


def _rollup_device_count(row: list[str]) -> int:
    """Total Devices is the second column of the polling rollups."""
    try:
        return int(str(row[1]).replace(",", "").split("/", 1)[0])
    except (IndexError, ValueError):
        return 0


def add_capped_rollup_table(
    document,
    heading: str,
    capped_heading: str,
    headers: list[str],
    rows: list[list[str]],
    noun: str,
) -> None:
    """Write a worst-first rollup table, keeping only the top rows in the report."""
    capped = len(rows) > MINI_REPORT_ROLLUP_LIMIT
    document.add_heading(capped_heading if capped else heading, level=4)
    build_word_table(
        document,
        headers,
        rows[:MINI_REPORT_ROLLUP_LIMIT],
    )
    if capped:
        # Devices with no relay or no usable address are a group, not a relay or
        # subnet, so they are not counted in the note.
        named = sum(1 for row in rows if str(row[0]) not in UNREPORTED_GROUPS)
        note = f"Showing {MINI_REPORT_ROLLUP_LIMIT} of {named:,} {noun}."
        unreported = sum(
            _rollup_device_count(row) for row in rows if str(row[0]) in UNREPORTED_GROUPS
        )
        if unreported:
            missing = "a relay" if noun == "relays" else "a usable address"
            note += f" {_device_count(unreported)} did not report {missing}."
        add_note_paragraph(document, note)


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
    property_intervals: PropertyIntervalSummary | None = None,
    minimum_analysis_interval: list[MinimumAnalysisInterval] | None = None,
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

    add_stub_front_matter(document, "Client Performance Analysis")
    sections = {}

    def client_heading(key, text, level):
        paragraph = document.add_heading(text, level=level)
        sections[key] = paragraph
        return paragraph

    if stamp:
        stamp_docx_document(document, stamp)

    title = (
        f"This analysis covers {metrics.score_total_devices:,} BigFix Clients from "
        f"{metrics.report_start_text} to {metrics.report_end_text}. It was generated "
        f"on {metrics.generated_at_text}."
    )
    if not loop_offenders:
        title += (
            " This capture did not include the Top 10 evaluation data. This Mini "
            "Report has no Top 10 Most Expensive Evaluations section."
        )
    document.add_paragraph(title)

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
            "Client performance chart showing health score, loop "
            "distribution, reported devices, UDP notification context, and "
            "reporting issues.",
            "Client Performance Chart",
        )
        spacer = document.add_paragraph()
        spacer.paragraph_format.space_after = Pt(8)

    keep_with_next(
        client_heading("Reading the Infographic", "Reading the Infographic", 3)
    )
    build_word_table(
        document,
        ["Infographic tile", "Value", "What it means"],
        client_loop_infographic_key_rows(
            metrics, loop_offenders, udp_summary, property_intervals
        ),
    )

    if include_automated_findings:
        reasons = loop_finding_reasons(metrics, property_intervals)
        finding_rows = (
            [
                [
                    LOOP_FINDING_ID,
                    f"{loop_finding_impact(reasons)}.\n"
                    + "\n".join(f"{r.text}. See {r.section}." for r in reasons),
                ]
            ]
            if reasons
            else []
        )
        if finding_rows:
            client_heading("Automated Findings", "Automated Findings", 3)
            build_word_table(
                document,
                ["Finding ID", "Automated Finding"],
                finding_rows,
            )

    client_heading("Loop Health", "Loop Health", 3)
    keep_with_next(
        document.add_paragraph(
            "Each device is placed in a group by its average loop time across the "
            "collection period."
        )
    )
    build_word_table(
        document,
        ["Group", "Devices / Total", "% of Total", "Rule"],
        [
            *loop_group_rows(metrics),
        ],
    )
    document.add_paragraph(
        "The slowest device averages "
        f"{format_duration_for_report(metrics.slowest_avg_seconds)} per loop. The "
        "longest single loop any device reported is "
        f"{format_duration_for_report(metrics.peak_max_seconds)}."
    )
    document.add_paragraph(
        f"{_device_count(metrics.total_issue_count)} "
        f"({pct(metrics.total_issue_pct)}) reported no usable loop data. "
        + ("It counts" if metrics.total_issue_count == 1 else "They count")
        + " as Critical in the Loop Health group and in the score. When more than "
        f"{NO_DATA_PCT_LIMIT:g}% of devices have no usable data, CLT-01 gives it "
        "as a reason."
    )

    client_heading("How the Score Is Calculated", "How the Score Is Calculated", 3)
    document.add_paragraph(
        "Each device earns points for its group. Healthy earns 100, Good 85, "
        "Warning 67 and Critical 34. The score is the average across all devices."
    )
    document.add_paragraph(
        "A score of 90 to 100 is Healthy, 70 to 89 is Warning, and 0 to 69 is Critical."
    )

    if loop_offenders or actionsite_pressure or property_intervals:
        client_heading("Loop Cost", "Loop Cost", 3)
        document.add_paragraph(
            "These sections show what the Client evaluates in each loop. They do "
            "not change the score. Evaluation Frequency can add a reason to CLT-01."
        )

    if loop_offenders:
        client_heading(
            "Top 10 Most Expensive Evaluations", "Top 10 Most Expensive Evaluations", 4
        )
        keep_with_next(
            document.add_paragraph(
                top10_kind_sentence(loop_offenders)
                + " These are the slowest evaluations each device reported, averaged across the "
                "deployment. Occurrences is how many times an evaluation appeared in "
                "a device's Top 10. " + top10_interval_sentences(property_intervals)
            )
        )
        build_word_table(
            document,
            [
                "Rank",
                "Average Eval Time (Seconds)",
                "Occurrences",
                "Evaluation",
                "Interval",
            ],
            [
                [
                    str(item.rank),
                    format_loop_offender_seconds(item.avg_client_processing_seconds),
                    f"{item.occurrences:,}",
                    format_loop_offender_evaluation(item.result, property_intervals),
                    offender_interval(item.result, property_intervals),
                ]
                for item in loop_offenders
            ],
        )

    if property_intervals:
        client_heading("Evaluation Frequency", "Evaluation Frequency", 4)
        keep_with_next(
            document.add_paragraph(evaluation_frequency_lead(property_intervals))
        )
        build_word_table(
            document,
            [
                "Interval",
                "Properties / Active",
                "% of Active",
                "Custom",
                "External",
                "Status",
            ],
            evaluation_frequency_rows(property_intervals),
            status_col=5,
        )
        document.add_paragraph(evaluation_frequency_detail(property_intervals))
        reserved_note = evaluation_frequency_reserved_note(property_intervals)
        if reserved_note:
            document.add_paragraph(reserved_note)
        document.add_paragraph(evaluation_frequency_source_note(property_intervals))
        not_set = sum(
            1 for item in property_intervals.counted if item.interval_minutes is None
        )
        if not_set:
            add_note_paragraph(
                document,
                (
                    "1 active property has an interval that could not be read. "
                    "It is listed as Unreadable and is not counted as every report."
                    if not_set == 1
                    else f"{not_set:,} active properties have an interval that "
                    "could not be read. They are listed as Unreadable and are not "
                    "counted as every report."
                ),
            )
        if minimum_analysis_interval:
            client_heading("Minimum Analysis Interval", "Minimum Analysis Interval", 4)
            document.add_paragraph(
                minimum_analysis_interval_paragraph(minimum_analysis_interval)
            )

    if actionsite_pressure:
        client_heading("Contributing Factors", "Contributing Factors", 4)
        keep_with_next(
            document.add_paragraph(
                "Deployment-wide counts that add work to every Client loop."
            )
        )
        build_word_table(
            document,
            ["Metric", "Value", "Status", "Basis"],
            actionsite_pressure_rows(actionsite_pressure),
            status_col=2,
        )
        document.add_paragraph(property_source_note(property_intervals))
        if actionsite_pressure.content_captured:
            document.add_paragraph(CONTENT_CAPTURE_NOTE)

    if udp_summary or command_polling_summary:
        client_heading("Notification and Polling", "Notification and Polling", 3)
        document.add_paragraph(
            "Relays send UDP notifications so Clients act on new content right away. "
            "Command polling is the fallback when those notifications do not arrive."
        )

    if udp_summary:
        client_heading("UDP Notification Coverage", "UDP Notification Coverage", 4)
        build_word_table(
            document,
            ["Status", "Devices / Total", "% of Total"],
            udp_coverage_rows(udp_summary),
        )
        for note in udp_notification_data_notes(udp_summary):
            add_note_paragraph(document, note)

        if udp_summary.relay_rows:
            add_capped_rollup_table(
                document,
                "UDP Notification Issues by Relay",
                f"UDP Notification Issues by Relay (Top {MINI_REPORT_ROLLUP_LIMIT})",
                [
                    "Relay",
                    "Not Receiving / Reported",
                    "% of Relay Reported Clients",
                ],
                udp_summary.relay_rows,
                "relays",
            )

        if udp_summary.subnet_rows:
            add_capped_rollup_table(
                document,
                "Top Subnets Not Receiving UDP Pings",
                f"Top {MINI_REPORT_ROLLUP_LIMIT} Subnets Not Receiving UDP Pings",
                ["Subnet", "Not Receiving / Reported", "Serving Relays"],
                udp_summary.subnet_rows,
                "subnets",
            )

    if command_polling_summary:
        client_heading("Command Polling", "Command Polling", 4)
        keep_with_next(
            document.add_paragraph(
                f"The first four rows add up to the "
                f"{command_polling_summary.total_devices:,} devices that reported "
                "polling data. The last three are checks, and a device can appear "
                "in more than one."
            )
        )
        keep_with_next(
            document.add_paragraph(
                "Interval Below Average Loop counts devices with polling enabled and "
                "an interval shorter than their own average loop time. Enabled with "
                "Missing Interval counts devices with polling enabled and no "
                "interval. No UDP and Polling Disabled/Not Set counts devices that "
                "received no UDP pings and do not poll."
            )
        )
        build_word_table(
            document,
            ["Status", "Devices / Total", "% of Total"],
            command_polling_coverage_rows(command_polling_summary),
        )

        if command_polling_summary.relay_rows:
            add_capped_rollup_table(
                document,
                "Command Polling by Relay",
                f"Command Polling by Relay (Top {MINI_REPORT_ROLLUP_LIMIT})",
                ["Relay", *POLLING_MINI_REPORT_HEADERS],
                polling_mini_report_rows(command_polling_summary.relay_rows),
                "relays",
            )

        if command_polling_summary.subnet_rows:
            add_capped_rollup_table(
                document,
                "Command Polling by Subnet",
                f"Command Polling by Subnet (Top {MINI_REPORT_ROLLUP_LIMIT})",
                ["Subnet", *POLLING_MINI_REPORT_HEADERS],
                polling_mini_report_rows(command_polling_summary.subnet_rows),
                "subnets",
            )

    if fast_hash_verify_summary or agent_cpu_idle_summary or agent_multicore_summary:
        client_heading("Client Settings", "Client Settings", 3)
        document.add_paragraph(
            "These settings control how much CPU the Client uses. They are reported "
            "for context and are not scored. Duty cycle is the work interval divided "
            "by the work and sleep intervals together. It is the configured share of "
            "time, not measured CPU use. Not Set means the collection returned no "
            "value."
        )

    if fast_hash_verify_summary:
        client_heading("FastHashVerify", "FastHashVerify", 4)
        keep_with_next(
            document.add_paragraph(
                "FastHashVerify lets the Client use more CPU while it checks the hash "
                "of a downloaded file, which shortens verification for large patches. "
                "It is off by default. When it is on, 20 ms work and 60 ms sleep is "
                "a configured duty cycle of 25% while hashing."
            )
        )
        build_word_table(
            document,
            ["Status", "Devices / Total", "% of Total"],
            fast_hash_verify_coverage_rows(fast_hash_verify_summary),
        )
        settings_heading = document.add_paragraph(
            "Reported FastHashVerify Work and Sleep Settings"
        )
        sections["FastHashVerify settings"] = settings_heading
        keep_with_next(settings_heading)
        build_word_table(
            document,
            [
                "Work (ms)",
                "Sleep (ms)",
                "Configured Duty Cycle (%)",
                "Devices / Total",
            ],
            fast_hash_verify_summary.settings_rows,
        )

    if agent_cpu_idle_summary:
        client_heading("CPU Idle Settings", "CPU Idle Settings", 4)
        keep_with_next(
            document.add_paragraph(
                "Work Idle and Sleep Idle set how long the Client works and rests "
                "during normal evaluation."
            )
        )
        build_word_table(
            document,
            [
                "Work Idle (ms)",
                "Sleep Idle (ms)",
                "Configured Duty Cycle (%)",
                "Devices / Total",
            ],
            agent_cpu_idle_summary.settings_rows,
        )

    if agent_multicore_summary:
        client_heading("Multicore CPU Scaling", "Multicore CPU Scaling", 4)
        keep_with_next(
            document.add_paragraph(
                "Available on BigFix 11.0.7 and later Clients. Not Applicable means "
                "the Client is older than 11.0.7."
            )
        )
        build_word_table(
            document,
            [
                "Multicore CPU Scaling Enabled",
                "Devices / Total",
            ],
            agent_multicore_summary.settings_rows,
        )

    from Lib.Design.client_report_layout import apply_client_layout

    apply_client_layout(
        document,
        word_output,
        sys.modules[__name__],
        sections=sections,
        render_details=png_output.exists(),
        metrics=metrics,
        actionsite_pressure=actionsite_pressure,
        loop_offenders=loop_offenders,
        property_intervals=property_intervals,
        agent_cpu_idle_summary=agent_cpu_idle_summary,
        agent_multicore_summary=agent_multicore_summary,
        fast_hash_verify_summary=fast_hash_verify_summary,
        udp_summary=udp_summary,
        command_polling_summary=command_polling_summary,
    )
    document.save(str(word_output))
    report_tables.normalize_docx_tables(word_output)


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
        default="00:15:00",
        help="Healthy threshold. Default: 00:15:00",
    )
    parser.add_argument(
        "--good-threshold",
        default="00:30:00",
        help="Good threshold. Default: 00:30:00",
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
        good_seconds = parse_timespan_to_seconds(args.good_threshold)
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
            good_threshold_seconds=good_seconds,
        )
        actionsite_pressure = parse_actionsite_pressure(deployment_info_folder)
        if actionsite_pressure is None:
            log.warn(
                "Deployment_Information folder not found. Run 'Collect Deployment "
                "Information' on the root server. The Contributing Factors "
                "table is left out of this report."
            )
        property_intervals = parse_property_intervals(deployment_info_folder)
        if deployment_info_folder is not None and property_intervals is None:
            log.warn(
                "Property_Info has no 'Active Properties by Evaluation Interval' "
                "section. Run 'Collect Deployment Information' again to add "
                "Evaluation Frequency to this report."
            )
        if property_intervals:
            log.detail(
                "Active properties with intervals", len(property_intervals.properties)
            )
            log.detail(
                "Evaluated every report or under 15 minutes",
                frequent_property_count(property_intervals),
            )
        minimum_analysis_interval = parse_minimum_analysis_interval(
            deployment_info_folder
        )
        if minimum_analysis_interval:
            log.detail(
                "Devices with a minimum analysis interval",
                sum(row.devices for row in minimum_analysis_interval),
            )
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
                "not performed; use the Client Performance Workbook with customer "
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
            property_intervals=property_intervals,
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
            property_intervals=property_intervals,
            minimum_analysis_interval=minimum_analysis_interval,
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
                property_intervals=property_intervals,
                minimum_analysis_interval=minimum_analysis_interval,
                stamp=stamp,
                include_automated_findings=args.include_automated_findings,
            )

        log.ok("Client performance analysis built")
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
