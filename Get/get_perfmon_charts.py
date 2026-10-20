#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
get_perfmon_charts.py -- PerfMon Infrastructure Analysis

Produces:
  - Excel workbook  (findings, worst offenders, raw data, per-counter charts)
  - PNG graphs      (for Word injection via Inject-PerfmonCharts.ps1)
  - Observations JSON sidecar for Word template observation text

Usage -- Windows (BLG input):
    python get_perfmon_chart.py --input server.blg --output results.xlsx

Usage -- any platform (CSV pre-exported via relog):
    relog server.blg -f CSV -o server.csv          # run once on Windows
    python get_perfmon_chart.py --input server.csv --output results.xlsx

Hardware context flags (improve threshold accuracy):
    --memory-gb 24  --processors 16  --disks 8  --virtual-machine

Requirements:
    pip install pandas matplotlib xlsxwriter numpy
"""

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
INJECT_DIR = PROJECT_ROOT / "Inject"
for folder in (PROJECT_ROOT, INJECT_DIR):
    if folder.exists() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import matplotlib

matplotlib.use("Agg")  # non-interactive backend -- must be before pyplot import
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from Lib.Themes.chart_theme import THEME, choose_font
from Lib.Themes.workbook_theme import xlsxwriter_formats

_FONT_FAMILY = choose_font()
import pandas as pd
import xlsxwriter

import Lib.Core.report_log as log
from Lib.Core.document_stamp import add_stamp_arguments, stamp_from_args
from Lib.Core.input_utils import (
    clean_user_path as shared_clean_user_path,
)
from Lib.Core.input_utils import (
    resolve_existing_file as shared_resolve_existing_file,
)
from Lib.Core.input_utils import (
    resolve_output_file as shared_resolve_output_file,
)
from Lib.Core.subprocess_window import hidden_subprocess_kwargs

_SUBPROCESS_KWARGS = hidden_subprocess_kwargs()

# ---------------------------------------------------------------------------
# Performance counters to extract from the BLG file.
# relog.exe does not support multiple -c flags on the command line, so these
# are written to a temporary counter file (-cf) and passed in one call.
# Wildcards (*) capture all instances (e.g. every physical disk, every NIC).
# Avg. Disk sec/Transfer is renamed to Avg. Disk ms/Transfer after loading
# because we multiply by 1000 to convert seconds -> milliseconds for readability.
# ---------------------------------------------------------------------------
# Counters to extract from BLG
# ---------------------------------------------------------------------------
COUNTERS = [
    # PRF-INF-01: Storage Queue Depth
    r"\PhysicalDisk(*)\Current Disk Queue Length",
    # PRF-INF-02: Storage Latency  (rendered as Avg. Disk ms/Transfer after x1000)
    r"\PhysicalDisk(*)\Avg. Disk sec/Transfer",
    # PRF-INF-03: Storage Operations/Second
    r"\PhysicalDisk(*)\Disk Transfers/sec",
    # PRF-INF-04: CPU Utilization
    r"\Processor(_Total)\% Processor Time",
    # PRF-INF-05: CPU Latency
    r"\System\Processor Queue Length",
    # PRF-INF-06: CPU Privileged Time
    r"\Processor(_Total)\% Privileged Time",
    # PRF-INF-07: Network Health
    r"\Network Interface(*)\Packets Outbound Discarded",
    r"\Network Interface(*)\Packets Outbound Errors",
    r"\Network Interface(*)\Packets Received Discarded",
    r"\Network Interface(*)\Packets Received Errors",
    # PRF-INF-09: Memory Health
    r"\Paging File(_Total)\% Usage Peak",
    # PRF-INF-09 context, not charted. Commit Limit is physical memory plus the
    # page file, so the page file size is Commit Limit minus physical memory.
    r"\Memory\Commit Limit",
]

# Chart palette
_BLUE = "#0F5FDC"
_NEARBLACK = "#000032"
_RED = "#C5283D"
_GREEN_BG = "#1F8A5B"
_RED_BG = "#C5283D"
_ALPHA = 0.12


# ---------------------------------------------------------------------------
# Chart color palette â shared with inject_perfmon_charts.py for visual
# consistency between PNG graphs and the Word document.
# _ALPHA is used for threshold band fills (semi-transparent background).
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Counter name helpers
# ---------------------------------------------------------------------------


def is_packet_counter(name: str) -> bool:
    """Return whether a counter is a cumulative packet error/discard counter."""
    return "Packets_" in name and ("Errors" in name or "Discarded" in name)


def counter_analysis_series(series: pd.Series, name: str) -> pd.Series:
    """Return the values used for scoring and charting a counter.

    Windows network packet error/discard counters are cumulative. Analyze their
    non-negative increase between samples so a pre-existing counter value is not
    reported as packet loss throughout the entire capture window.
    """
    values = pd.to_numeric(series, errors="coerce")
    if not is_packet_counter(name):
        return values

    delta = values.diff()
    # A negative delta indicates a counter reset or wrap. It is not evidence of
    # packet errors, so leave that interval unscored instead of inventing a value.
    return delta.where(delta >= 0)


MEMORY_NOT_SUPPLIED = "physical memory was not supplied"
COMMIT_LIMIT_MISSING = "capture has no Memory Commit Limit counter"


def commit_limit_column(df: pd.DataFrame, usage_col: str) -> str | None:
    """Return the Commit Limit column from the same host as a page file column."""
    prefix = usage_col.split("Paging_File")[0]
    name = f"{prefix}Memory_Commit_Limit"
    return name if name in df.columns else None


def page_file_not_scored_reason(df: pd.DataFrame, usage_col: str, memory_gb: int) -> str:
    """Return why PRF-INF-09 cannot be scored, or an empty string when it can."""
    if memory_gb <= 0:
        return MEMORY_NOT_SUPPLIED
    if commit_limit_column(df, usage_col) is None:
        return COMMIT_LIMIT_MISSING
    return ""


def page_file_percent_of_memory(
    usage_pct: pd.Series, commit_limit_bytes: pd.Series, memory_gb: int
) -> pd.Series:
    """Return page file in use as a percent of physical memory (PRF-INF-09).

    Paging File % Usage Peak is a percent of the page file. The NFR guide sets
    the limit as a percent of physical memory. Commit Limit is physical memory
    plus the page file, so the page file size is Commit Limit minus physical
    memory.
    """
    ram_bytes = memory_gb * 1024**3
    commit = pd.to_numeric(commit_limit_bytes, errors="coerce")
    page_file_bytes = (commit - ram_bytes).clip(lower=0)
    used_bytes = pd.to_numeric(usage_pct, errors="coerce") / 100 * page_file_bytes
    return used_bytes / ram_bytes * 100


def clean_counter_name(path: str, include_host: bool = False) -> str:
    """Convert a raw relog CSV column header to a safe identifier."""
    host_match = re.match(r"^\\\\([^\\]+)\\", path)
    host_prefix = ""
    if include_host and host_match:
        host_prefix = re.sub(r"[^A-Za-z0-9]+", "_", host_match.group(1)).strip("_")

    name = re.sub(r"^\\\\[^\\]+\\", "", path)  # strip \\SERVER\
    name = re.sub(r"[\\/:*?\[\]()\% ]", "_", name)
    name = re.sub(r"\.", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    name = name.replace("Avg_Disk_sec_Transfer", "Avg_Disk_ms_Transfer")
    return f"{host_prefix}_{name}" if host_prefix else name


def unique_counter_name(name: str, seen: dict[str, int]) -> str:
    """Return a stable unique counter name while preserving metric suffixes."""
    count = seen.get(name, 0) + 1
    seen[name] = count
    if count == 1:
        return name
    return f"Duplicate_{count}_{name}"


def perfmon_hosts_from_columns(columns: list[str]) -> list[str]:
    """Return host names found in raw PerfMon counter paths."""
    hosts: list[str] = []
    seen: set[str] = set()
    for column in columns:
        match = re.match(r"^\\\\([^\\]+)\\", str(column))
        if not match:
            continue
        host = match.group(1).strip()
        key = host.lower()
        if host and key not in seen:
            hosts.append(host)
            seen.add(key)
    return hosts


def perfmon_host_label(hosts: list[str] | tuple[str, ...] | None) -> str:
    """Return a compact label for the analyzed PerfMon system."""
    host_list = [str(host).strip() for host in hosts or [] if str(host).strip()]
    if not host_list:
        return "Not detected"
    if len(host_list) == 1:
        return host_list[0]
    if len(host_list) <= 3:
        return "Multiple hosts: " + ", ".join(host_list)
    return "Multiple hosts: " + ", ".join(host_list[:3]) + f" + {len(host_list) - 3} more"


def perfmon_chart_title(
    counter_name: str, sample_window: str, host_name: str = ""
) -> str:
    """Build the per-counter chart title with analyzed-system context."""
    host = str(host_name or "").strip() or "Not detected"
    metric_note = (
        " (non-negative increase between samples)"
        if is_packet_counter(counter_name)
        else " (page file in use as a percent of physical memory)"
        if "Usage_Peak" in counter_name
        else ""
    )
    return (
        f"{counter_name}{metric_note}\nSystem: {host} | Capture window: {sample_window}"
    )


def perfmon_context_line(sample_window: str, host_name: str = "") -> str:
    host = str(host_name or "").strip() or "Not detected"
    return f"System: {host}  |  Capture window: {sample_window}"


def counter_category(name: str) -> str:
    if "Disk" in name:
        return "Disk"
    if "Processor" in name:
        return "CPU"
    if "Network" in name:
        return "Network"
    if "Paging" in name or "Usage_Peak" in name:
        return "Memory"
    return "Other"


# ---------------------------------------------------------------------------
# Threshold logic
# ---------------------------------------------------------------------------


def get_threshold(
    name: str,
    memory_gb: int = 0,
    disk_count: int = 0,
    vm: bool = False,
    logical_processors: int = 0,
) -> dict | None:
    """
    Returns a threshold dict or None if the counter has no defined threshold.

    Threshold dict keys:
      type     "max" â value must stay below critical/warn limits.
               "range" â value should stay within min..critical (e.g. CPU on VMs
               where both too-low and too-high indicate a problem).
      critical Absolute upper limit (or max for range type).
      warn     Warning level below critical (may be None).
      note     Human-readable explanation of the threshold.

    Hardware context parameters scale thresholds where the NFR allows:
      - PRF-INF-01 disk-queue family (Current / Avg / Avg Read / Avg Write Disk
        Queue Length) scales the _Total instance with disk_count; per-drive
        instances stay at <= 1.
      - PRF-INF-04 % Processor Time becomes a 50-80% range on VMs.
      - PRF-INF-09 scores page file use as a percent of physical memory. It
        needs memory_gb and the Commit Limit counter, and is not scored
        without them.
      - logical_processors is accepted for compatibility with callers/tests;
        PRF-INF-05 remains a fixed <= 4 threshold in the current NFR guide.
    Other NFR thresholds are fixed values (latency 1ms, CPU queue 4, etc.).
    Returns None for counters with no defined threshold (informational only).
    """

    # Whole disk-queue family scales per spindle: Current, Avg, and the Avg Read /
    # Avg Write queue lengths all follow the "<= ~1 outstanding I/O per disk" rule
    # because queued work parallelizes across spindles. (System Processor Queue
    # Length has no "Disk" in its name, so it is excluded here and handled below.)
    if "Disk" in name and "Queue_Length" in name:
        if "_Total_" in name and disk_count > 0:
            return {
                "type": "max",
                "critical": disk_count,
                "warn": None,
                "label": f"<= {disk_count} (1 per disk x {disk_count} disks)",
                "note": f"<= 1 per disk x {disk_count} disks = <= {disk_count}",
            }
        return {
            "type": "max",
            "critical": 1,
            "warn": None,
            "label": "<= 1 per physical device",
            "note": "<= 1 (per physical device)",
        }

    # Storage latency (ms per I/O). Intentionally a FIXED budget, not scaled per
    # spindle: a single transfer takes the same time regardless of disk count, so
    # scaling it up by disk_count would let bigger systems pass with worse latency.
    # 1ms is a deliberate DB-tier target (SSD/NVMe class) and is meant to be
    # aggressive; do not "loosen" it without a methodology change. (Confirmed
    # 2026-06-28.)
    if "Avg_Disk_ms_Transfer" in name:
        return {
            "type": "max",
            "critical": 1,
            "warn": None,
            "label": "<= 1ms",
            "note": "<= 1ms",
        }

    if "Processor_Time" in name:
        if vm:
            return {
                "type": "range",
                "min": 50,
                "critical": 80,
                "warn": None,
                "label": "50-80% (VM)",
                "note": "50-80% (VM)",
            }
        return {
            "type": "max",
            "critical": 80,
            "warn": None,
            "label": "<= 80%",
            "note": "<= 80%",
        }

    if "Privileged_Time" in name:
        return {
            "type": "max",
            "critical": 10,
            "warn": None,
            "label": "<= 10%",
            "note": "<= 10%",
        }

    if "Processor_Queue_Length" in name:
        note = "<= 4 (System Processor Queue Length)"
        if logical_processors > 0:
            note += (
                f"; logical processors supplied: {logical_processors} "
                "(recorded for context, not used to scale this NFR threshold)"
            )
        return {
            "type": "max",
            "critical": 4,
            "warn": None,
            "label": "<= 4",
            "note": note,
        }

    if is_packet_counter(name):
        return {
            "type": "max",
            "critical": 0,
            "warn": None,
            "label": "~= 0 increase (no packet errors/discards)",
            "note": (
                "Packet errors and discards should approach zero per interface; "
                "evaluated as the non-negative increase between samples"
            ),
        }

    if "Disk_Transfers_sec" in name:
        return {
            "type": "informational",
            "label": "No saturation; DBMS storage should support 5,000 transfers/sec",
            "note": "No passive fail threshold; check for saturation/flatlining and DBMS storage capability for 5,000 transfers/sec",
        }

    if "Usage_Peak" in name:
        note = (
            f"Page file in use should be <= 5% of physical memory. "
            f"Physical memory of the analyzed system: {memory_gb} GB "
            f"(the host the PerfMon capture is from, which may differ from the "
            f"root server)."
            if memory_gb > 0
            else "Page file in use should be <= 5% of physical memory. "
            "Physical memory was not supplied, so this area cannot be verified. "
            "Cannot Verify earns 25 points in the score."
        )
        return {
            "type": "max",
            "critical": 5,
            "warn": None,
            "label": "<= 5% of physical memory",
            "note": note,
        }

    return None


def sample_status(value, threshold: dict | None) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "Blank"
    if threshold is None:
        return "OK"
    t = threshold["type"]
    if t == "range":
        if value > threshold["critical"]:
            return "Critical"
        if value < threshold.get("min", 0):
            return "Warning"
        return "OK"
    if t == "informational":
        return "OK"
    if value > threshold["critical"]:
        return "Critical"
    if threshold.get("warn") is not None and value > threshold["warn"]:
        return "Warning"
    return "OK"


def threshold_source(name: str, mem_src: str, cpu_src: str, disk_src: str) -> str:
    if "Usage_Peak" in name:
        return f"Memory context: {mem_src}"
    if "Processor_Queue_Length" in name:
        return "Fixed NFR threshold"
    if "Disk_Queue" in name:
        return f"Disk context: {disk_src}"
    return "Fixed threshold"


SECTION_COUNTER_RULES: "OrderedDict[str, list[str]]" = OrderedDict(
    [
        ("Storage Queue Depth", ["Avg_Disk_Queue_Length", "Current_Disk_Queue_Length"]),
        ("Storage Latency", ["Avg_Disk_ms_Transfer"]),
        ("Storage Operations", ["Disk_Transfers_sec"]),
        ("CPU Privileged Time", ["Privileged_Time"]),
        ("CPU Utilization", ["Processor_Time"]),
        ("CPU Latency", ["Processor_Queue_Length"]),
        (
            "Network Health",
            [
                "Packets_Outbound_Discarded",
                "Packets_Outbound_Errors",
                "Packets_Received_Discarded",
                "Packets_Received_Errors",
            ],
        ),
        ("Memory Health", ["Usage_Peak"]),
    ]
)


def counter_section(counter_name: str) -> str:
    for section, tokens in SECTION_COUNTER_RULES.items():
        if any(token in counter_name for token in tokens):
            if section == "CPU Utilization" and "Privileged_Time" in counter_name:
                continue
            return section
    return "Other"


def status_rank(status: str) -> int:
    return {"Critical": 0, "Warning": 1, "Not Available": 2, "OK": 3}.get(status, 4)


def fmt_number(value) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if number == 0:
        return "0"
    if abs(number) >= 100:
        return f"{number:.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.2f}"


def short_threshold_text(value: str) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        return "the documented standard"
    if text in {"No threshold defined", "No matching counter data"}:
        return text
    if "packet errors and discards" in text.lower():
        return "no packet-error/discard increase between samples"
    if "no passive fail" in text.lower() or text.lower().startswith("no saturation"):
        return text
    match = re.search(
        r"(?:<=|>=|<|>)\s*\d+(?:\.\d+)?\s*"
        r"(?:%(?:\s+of\s+physical\s+memory)?|ms|sec|seconds?|errors?"
        r"|per\s+physical\s+device)?",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(0).strip() if match else text


def count_phrase(count: int, singular: str, plural: str | None = None) -> str:
    """Return a readable count phrase with natural singular/plural wording."""
    word = singular if count == 1 else (plural or f"{singular}s")
    return f"{count} {word}"


def observation_for_findings(section: str, section_findings: list[dict]) -> dict:
    if not section_findings:
        return {
            "section": section,
            "status": "Not Available",
            "observation": (
                "No matching counter data was available for this section in the supplied "
                "PerfMon capture. Confirm the collection profile included the required "
                "counter before treating this area as validated."
            ),
            "counters": [],
            "counters_detail": [],
            "threshold": "No matching counter data",
            "threshold_source": "",
            "confidence": "Not Available",
            "peak_violation_window": "",
            "samples": 0,
            "violations": 0,
            "warnings": 0,
        }

    ordered = sorted(
        section_findings,
        key=lambda item: (
            status_rank(item.get("Status", "")),
            -int(item.get("Violations", 0)),
            -float(item.get("ViolationPercent", 0)),
            -int(item.get("Warnings", 0)),
            -float(item.get("Maximum") or 0),
        ),
    )
    worst = ordered[0]
    status = worst.get("Status", "Unknown")
    counters = [item.get("Counter", "") for item in ordered if item.get("Counter")]
    threshold = worst.get("Threshold", "the documented standard")
    threshold_display = short_threshold_text(threshold)
    samples = int(worst.get("Samples", 0) or 0)
    violations = int(worst.get("Violations", 0) or 0)
    warnings = int(worst.get("Warnings", 0) or 0)
    violation_pct = fmt_number(worst.get("ViolationPercent", 0))
    warning_pct = fmt_number(worst.get("WarningPercent", 0))
    average = fmt_number(worst.get("Average", 0))
    maximum = fmt_number(worst.get("Maximum", 0))
    peak_window = worst.get("PeakViolationWindow", "No threshold breach detected")
    confidence = worst.get("Confidence", "Unknown")
    threshold_src = worst.get("ThresholdSource", "")

    if status == "Not Available" and worst.get("NotScoredReason"):
        reason = str(worst["NotScoredReason"])
        result = (
            f"{reason[:1].upper()}{reason[1:]}, so this area cannot be verified. "
            "Cannot Verify earns 25 points in the score. PRF-INF-09 measures page "
            "file use against physical memory."
        )
    elif status == "Not Available":
        result = (
            f"No samples were recorded for {worst.get('Counter', 'this counter')} "
            f"during this capture window, so it could not be verified against "
            f"{threshold_display}. Do not treat this area as validated."
        )
    elif status == "Critical":
        metric = (
            "had an average per-sample increase of"
            if is_packet_counter(str(worst.get("Counter", "")))
            else "averaged"
        )
        result = (
            f"The standard was not met for this capture window. The worst counter "
            f"{metric} {average} against the standard ({threshold_display})."
        )
        if samples and violations * 2 > samples:
            result += (
                f" The average stayed over the limit for most of the capture. It "
                f"peaked at {maximum}, with {violations} of {samples} readings "
                f"({violation_pct}%) above the standard. Breach window: {peak_window}."
            )
        else:
            result += (
                f" {violations} of {samples} readings ({violation_pct}%) were over the "
                f"limit, in the breach window {peak_window}. They raised the average "
                f"over the limit. The other {samples - violations} readings met the "
                f"standard. It peaked at {maximum}."
            )
    elif status == "Warning":
        result = (
            f"The standard was met for critical-threshold purposes, but warning-level "
            f"activity was observed. The worst counter averaged {average} against "
            f"{threshold_display} -- inside the critical limit but in the warning range -- "
            f"with a peak of {maximum} and {warnings} of {samples} readings "
            f"({warning_pct}%) in the warning range. This should be watched for "
            f"sustained recurrence before the next capture."
        )
    elif threshold == "No threshold defined":
        result = (
            f"No fixed NFR threshold is defined for this counter set. The captured data "
            f"was retained for trend review; the highest observed value was {maximum} "
            f"and the average was {average}."
        )
    elif "no passive fail" in threshold.lower() or threshold.lower().startswith(
        "no saturation"
    ):
        # Counters like Disk Transfers/sec have no pass/fail limit -- they are
        # reviewed for saturation/flat-lining. Splicing the descriptive label into
        # "remained within {threshold}" produced an incoherent sentence.
        result = (
            f"This counter has no pass/fail threshold; it is reviewed for saturation "
            f"or flat-lining rather than a fixed limit. The highest observed value "
            f"was {maximum} and the average was {average} across {samples} readings."
        )
    else:
        result = (
            f"The standard was met for this capture window. The worst counter "
            f"averaged {average}, within {threshold_display}, across {samples} readings "
            f"(peak {maximum})."
        )
        if violations or warnings:
            result += (
                f" {violations} reading(s) briefly exceeded the standard and "
                f"{warnings} were in the warning range, but the sustained average "
                f"stayed within the limit."
            )

    if confidence and confidence != "High" and status != "Not Available":
        if confidence == "Medium":
            # Medium means a value was supplied by the user, not detected.
            result += (
                " Confidence is medium because one or more hardware context "
                "values were supplied or inferred and not detected from the capture."
            )
        else:
            result += f" Confidence is {confidence.lower()} because one or more hardware context values were inferred or not supplied."

    if len(ordered) > 1:
        non_ok = [item for item in ordered if item.get("Status") != "OK"]
        if non_ok:
            review_verb = "needs" if len(non_ok) == 1 else "need"
            result += (
                f" {count_phrase(len(non_ok), 'related counter')} {review_verb} review "
                "in this section."
            )
        else:
            reviewed_verb = "was" if len(ordered) == 1 else "were"
            result += (
                f" {count_phrase(len(ordered), 'related counter')} {reviewed_verb} reviewed "
                "and all met the standard."
            )

    return {
        "section": section,
        "status": status,
        "observation": result,
        "counters": counters,
        "counters_detail": [
            {
                "counter": item.get("Counter", ""),
                "category": item.get("Category", ""),
                "status": item.get("Status", ""),
                "confidence": item.get("Confidence", ""),
                "average": item.get("Average"),
                "maximum": item.get("Maximum"),
                "violations": item.get("Violations", 0),
                "violation_percent": item.get("ViolationPercent", 0),
                "warnings": item.get("Warnings", 0),
                "warning_percent": item.get("WarningPercent", 0),
                "samples": item.get("Samples", 0),
                "threshold": item.get("Threshold", ""),
                "threshold_source": item.get("ThresholdSource", ""),
                "sample_start": item.get("SampleStart", ""),
                "sample_end": item.get("SampleEnd", ""),
                "peak_violation_window": item.get("PeakViolationWindow", ""),
                "not_scored_reason": item.get("NotScoredReason", ""),
            }
            for item in ordered
        ],
        "worst_counter": worst.get("Counter", ""),
        "threshold": threshold,
        "threshold_source": threshold_src,
        "confidence": confidence,
        "average": worst.get("Average"),
        "maximum": worst.get("Maximum"),
        "violations": violations,
        "warnings": warnings,
        "samples": samples,
        "peak_violation_window": peak_window,
    }


def build_perfmon_observations(findings: list[dict], env_rows: list[dict]) -> dict:
    grouped: dict[str, list[dict]] = {section: [] for section in SECTION_COUNTER_RULES}
    for finding in findings:
        section = counter_section(str(finding.get("Counter", "")))
        if section in grouped:
            grouped[section].append(finding)

    sections = {
        section: observation_for_findings(section, grouped[section])
        for section in SECTION_COUNTER_RULES
    }

    total = len(findings)
    critical = sum(1 for item in findings if item.get("Status") == "Critical")
    warning = sum(1 for item in findings if item.get("Status") == "Warning")
    unavailable = sum(1 for item in findings if item.get("Status") == "Not Available")
    ok = sum(1 for item in findings if item.get("Status") == "OK")
    unavailable_suffix = (
        f"; {count_phrase(unavailable, 'counter')} could not be verified"
        if unavailable
        else ""
    )
    ok_verb = "was" if ok == 1 else "were"
    worst = sorted(
        findings,
        key=lambda item: (
            status_rank(item.get("Status", "")),
            -int(item.get("Violations", 0)),
            -float(item.get("ViolationPercent", 0)),
            -float(item.get("Maximum") or 0),
        ),
    )[:3]

    if critical:
        posture = (
            f"PerfMon analysis reviewed {count_phrase(total, 'counter')} across the "
            f"capture window. {count_phrase(critical, 'counter')} did not "
            f"meet the NFR standard; {count_phrase(warning, 'counter')} should be "
            f"monitored; {count_phrase(ok, 'counter')} {ok_verb} within standard"
            f"{unavailable_suffix}."
        )
    elif warning:
        posture = (
            f"PerfMon analysis reviewed {count_phrase(total, 'counter')} across the "
            f"capture window. No counters failed the NFR standard; "
            f"{count_phrase(warning, 'counter')} should be monitored; "
            f"{count_phrase(ok, 'counter')} {ok_verb} within standard"
            f"{unavailable_suffix}."
        )
    elif unavailable:
        posture = (
            f"PerfMon analysis reviewed {count_phrase(total, 'counter')} across the "
            f"capture window. No counters failed the NFR standard; "
            f"{count_phrase(unavailable, 'counter')} could not be verified; "
            f"{count_phrase(ok, 'counter')} {ok_verb} within standard."
        )
    else:
        posture = (
            f"PerfMon analysis found all {count_phrase(ok, 'reviewed counter')} within the defined "
            "NFR standards for the capture window."
        )

    env = {row.get("Setting"): row.get("Value") for row in env_rows}
    analyzed_system = str(env.get("Analyzed System") or "Not detected")
    summary_lines = [
        posture,
        (
            f"Analyzed system: {analyzed_system}. Capture window: "
            f"{env.get('Sample Start', 'unknown')} to "
            f"{env.get('Sample End', 'unknown')} across {env.get('Sample Count', 'unknown')} readings."
        ),
    ]
    review_items = []
    for item in worst:
        if item.get("Status") == "OK":
            continue
        if item.get("Status") == "Not Available":
            reason = (
                "physical memory was not supplied"
                if item.get("NotScoredReason") == MEMORY_NOT_SUPPLIED
                else "no samples recorded"
            )
            review_items.append(f"{item.get('Counter')} - Cannot Verify; {reason}")
        else:
            review_items.append(
                f"{item.get('Counter')} - {item.get('Status')}; "
                f"peak {fmt_number(item.get('Maximum'))}"
            )
    if review_items:
        summary_lines.append("Highest-priority review items:")
    else:
        summary_lines.append("Highest-priority review items: none identified.")

    return {
        "schema_version": 1,
        "source_script": "get_perfmon_charts.py",
        "environment": env,
        "summary": {
            "status_counts": {
                "Critical": critical,
                "Warning": warning,
                "Not Available": unavailable,
                "OK": ok,
                "Total": total,
            },
            "lines": summary_lines,
            "priority_items": review_items,
        },
        "sections": sections,
    }


def export_perfmon_observations(observations: dict, chart_folder: str | Path) -> Path:
    out_path = Path(chart_folder) / "perfmon_observations.json"
    out_path.write_text(json.dumps(observations, indent=2), encoding="utf-8")
    return out_path


def confidence_rating(name: str, mem_src: str, cpu_src: str, disk_src: str) -> str:
    high = {"Detected from BLG"}
    medium = {"User Supplied", "Parameter Supplied"}
    if "Usage_Peak" in name:
        src = mem_src
    elif "Processor_Queue_Length" in name:
        src = cpu_src
    elif "Disk_Queue" in name:
        src = disk_src
    else:
        return "High"
    if src in high:
        return "High"
    if src in medium:
        return "Medium"
    return "Low"


def peak_violation_window(df: pd.DataFrame, col: str, threshold: dict | None) -> str:
    if threshold is None:
        return "No threshold defined"
    mask = df[col].apply(lambda v: sample_status(v, threshold) == "Critical")
    viol = df.loc[mask, "Time"].dropna()
    if viol.empty:
        return "No critical violations detected"
    fmt = "%m-%d-%Y %H:%M:%S"
    return f"{viol.iloc[0].strftime(fmt)} - {viol.iloc[-1].strftime(fmt)}"


def axis_max(
    values: pd.Series, percentile: float = 0.98, padding: float = 1.15
) -> float | None:
    clean = values.dropna()
    clean = clean[clean >= 0]
    if clean.empty:
        return None
    p = float(clean.quantile(percentile))
    return max(float(math.ceil(p * padding)), 1.0)


def perfmon_chart_axis_max(max_raw: float, threshold: dict | None) -> float:
    critical = 0.0
    if threshold and threshold.get("critical") is not None:
        try:
            critical = max(float(threshold["critical"]), 0.0)
        except (TypeError, ValueError):
            critical = 0.0
    basis = max(float(max_raw or 0), critical)
    if basis <= 0:
        return 1.0
    chart_max = basis * 1.25
    if max_raw > 0:
        # Keep high pass thresholds from recreating a mostly empty 0-100 chart.
        chart_max = min(chart_max, float(max_raw) * 2)
    return max(chart_max, 1.0)


def time_window_phrase(times: pd.Series) -> str:
    valid = pd.Series(pd.to_datetime(times, errors="coerce")).dropna()
    if valid.empty:
        return "unknown duration"
    seconds = max((valid.max() - valid.min()).total_seconds(), 0)
    if seconds < 3600:
        return f"{int(round(seconds / 60))} min"
    hours = seconds / 3600
    return f"{hours:.1f} hr" if hours < 10 else f"{hours:.0f} hr"


def zero_counter_strip_text(
    col: str, has_samples: bool, not_scored_reason: str = ""
) -> tuple[str, str, str]:
    """Return the message, status label, and status color for a zero chart."""
    if not_scored_reason:
        return f"Not scored: {not_scored_reason}", "CANNOT VERIFY", "#595959"
    if not has_samples:
        return "No samples recorded", "CANNOT VERIFY", "#595959"
    if is_packet_counter(col):
        return "No packet errors or discards recorded", "PASS", "#1F8A5B"
    if "Usage_Peak" in col:
        return "0% page-file usage recorded", "PASS", "#1F8A5B"
    return "All recorded values were 0", "PASS", "#1F8A5B"


_CHART_FILENAME_SUFFIXES = (
    "Packets_Outbound_Discarded",
    "Packets_Outbound_Errors",
    "Packets_Received_Discarded",
    "Packets_Received_Errors",
    "Current_Disk_Queue_Length",
    "Avg_Disk_ms_Transfer",
    "Disk_Transfers_sec",
    "Processor_Queue_Length",
    "Processor_Time",
    "Privileged_Time",
    "Usage_Peak",
)


def perfmon_chart_filename(counter: str, png_folder: str | os.PathLike[str]) -> str:
    """Return a portable PNG name without losing injection's metric suffix.

    Windows can reject a valid chart when a long network-interface instance is
    combined with a customer/run folder path. Keep the metric suffix so the
    injector's filename patterns still match, and add a digest so shortened
    names remain unique.
    """
    original = f"{counter}.png"
    folder_text = os.path.abspath(os.fspath(png_folder))
    max_name_length = 240 - len(folder_text) - 1
    if len(original) <= max_name_length:
        return original

    digest = hashlib.sha1(counter.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    suffix = next(
        (value for value in _CHART_FILENAME_SUFFIXES if counter.endswith(value)),
        counter[-32:],
    )
    stem_length = max_name_length - len(".png")
    prefix_length = stem_length - len(digest) - len(suffix) - 2
    required_prefix = "PhysicalDisk" if counter.startswith("PhysicalDisk_") else ""
    compact = f"{required_prefix + '_' if required_prefix else ''}{digest}_{suffix}.png"
    if len(compact) > max_name_length:
        raise ValueError(
            f"PerfMon output path is too long to retain the counter name: {folder_text}. "
            "Choose a shorter output folder or run name."
        )
    if prefix_length > 0:
        return f"{counter[:prefix_length]}_{digest}_{suffix}.png"
    return compact


def render_zero_counter_strip(
    col: str,
    png_path: str,
    times: pd.Series,
    threshold: dict | None,
    sample_window: str,
    has_samples: bool,
    sample_count: int = 0,
    true_max: float = 0,
    host_name: str = "",
    not_scored_reason: str = "",
) -> None:
    fig = plt.figure(figsize=(14.3, 1.15), dpi=200)
    fig.patch.set_facecolor("white")
    ax = fig.add_axes((0, 0, 1, 1))
    ax.axis("off")

    message, result_label, result_color = zero_counter_strip_text(
        col, has_samples, not_scored_reason
    )
    window_text = "" if not_scored_reason else f" over {time_window_phrase(times)}"
    standard = f"Standard: {threshold['label']}" if threshold else "Standard: not defined"
    max_display = f"{true_max:g}%" if "Usage_Peak" in col else f"{true_max:g}"

    fig.text(
        0.025,
        0.74,
        col,
        fontsize=13,
        fontweight="bold",
        color=THEME.title,
        family=_FONT_FAMILY,
    )
    fig.text(
        0.025,
        0.38,
        f"{message}{window_text} - {result_label}",
        fontsize=20,
        fontweight="bold",
        color=result_color,
        family=_FONT_FAMILY,
    )
    fig.text(
        0.975,
        0.39,
        standard,
        ha="right",
        fontsize=12,
        color=THEME.text,
        family=_FONT_FAMILY,
    )
    fig.text(
        0.025,
        0.12,
        perfmon_context_line(sample_window, host_name)
        if not_scored_reason
        else f"{perfmon_context_line(sample_window, host_name)}  |  "
        f"Recorded samples: {sample_count:,}  |  True Max: {max_display}",
        fontsize=11,
        color=THEME.text,
        family=_FONT_FAMILY,
    )

    fig.savefig(
        png_path, dpi=200, facecolor="white", bbox_inches="tight", pad_inches=0.05
    )
    plt.close(fig)


# ---------------------------------------------------------------------------
# BLG handling (Windows only)
#
# .blg (Binary Log) is the native Windows Performance Monitor binary format.
# Python cannot read it directly â relog.exe (included with Windows) is used
# to convert it to CSV, which pandas then loads.
#
# inspect_blg() runs relog -q (query mode, no conversion) to read the counter
# list and detect hardware configuration without touching the data.
#
# blg_to_csv() does the actual conversion. The counter list is written to a
# temp file because relog does not support multiple -c flags. The temp file is
# deleted in a finally block to guarantee cleanup even if conversion fails.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def inspect_blg(blg_path: str) -> tuple[int, int]:
    """Return (detected_processors, detected_disks) from relog -q."""
    try:
        r = subprocess.run(
            ["relog.exe", blg_path, "-q"],
            capture_output=True,
            text=True,
            timeout=600,
            stdin=subprocess.DEVNULL,
            **_SUBPROCESS_KWARGS,
        )
        lines = r.stdout.splitlines() + r.stderr.splitlines()
    except Exception:
        return 0, 0
    procs, disks = set(), set()
    for line in lines:
        m = re.search(r"\\Processor\((\d+)\)\\", line)
        if m:
            procs.add(m.group(1))
        m = re.search(r"\\PhysicalDisk\((?!_Total)([^)]+)\)\\", line)
        if m:
            disks.add(m.group(1))
    return len(procs), len(disks)


def blg_to_csv(
    blg_path: str, counters: list[str], csv_path: str, timeout_seconds: int = 1800
) -> None:
    # relog.exe doesn't support multiple -c flags; use a counter file via -cf
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as cf:
        cf_path = cf.name
        for c in counters:
            cf.write(c + "\n")
    try:
        try:
            subprocess.run(
                [
                    "relog.exe",
                    blg_path,
                    "-f",
                    "CSV",
                    "-o",
                    csv_path,
                    "-cf",
                    cf_path,
                    "-y",
                ],
                check=True,
                timeout=timeout_seconds,
                capture_output=True,
                stdin=subprocess.DEVNULL,
                **_SUBPROCESS_KWARGS,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "relog.exe timed out while converting the BLG file. "
                f"Timeout was {timeout_seconds} seconds. Try a smaller BLG, "
                "pre-export the BLG to CSV, or rerun with a larger --relog-timeout."
            ) from exc
    finally:
        os.unlink(cf_path)


# ---------------------------------------------------------------------------
# Data loading and normalization
#
# relog CSV columns are named with the full counter path, e.g.:
#   \\SERVER\PhysicalDisk(_Total)\Avg. Disk Queue Length
# clean_counter_name() strips the server prefix and replaces special characters
# to produce safe column names for pandas and Excel.
#
# Avg. Disk sec/Transfer values are multiplied by 1000 to convert to ms.
# This matches the naming rename (sec -> ms) done in clean_counter_name().
#
# Returns (df, counter_cols) where counter_cols lists only the performance
# counter columns (not Sample/Time), used everywhere downstream.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def load_and_normalize(csv_path: str) -> tuple[pd.DataFrame, list[str]]:
    """
    Load relog CSV, clean column names, parse timestamps, convert sec->ms.
    Returns (df, counter_col_names).
    """
    raw = pd.read_csv(csv_path, low_memory=False)
    cols = list(raw.columns)
    perfmon_hosts = perfmon_hosts_from_columns(cols)
    time_col = cols[0]

    include_host = len(perfmon_hosts) > 1
    seen_counter_names: dict[str, int] = {}
    rename_map = {}
    counter_cols = []
    for col in cols[1:]:
        if col.startswith("\\") or re.match(r"^\\\\", col):
            clean = unique_counter_name(
                clean_counter_name(col, include_host=include_host),
                seen_counter_names,
            )
            rename_map[col] = clean
            counter_cols.append(clean)

    df = raw.rename(columns=rename_map)
    df.attrs["perfmon_hosts"] = perfmon_hosts
    df.attrs["perfmon_host_label"] = perfmon_host_label(perfmon_hosts)
    df.insert(0, "Sample", range(1, len(df) + 1))
    df["Time"] = pd.to_datetime(df[time_col], errors="coerce")
    df = df.drop(columns=[time_col], errors="ignore")

    for col in counter_cols:
        if col not in df.columns:
            continue
        df[col] = pd.to_numeric(df[col], errors="coerce")
        if "Avg_Disk_ms_Transfer" in col:
            df[col] = df[col] * 1000

    # Commit Limit is context for PRF-INF-09, not a counter to chart or score.
    counter_cols = [col for col in counter_cols if "Commit_Limit" not in col]
    return df, counter_cols


# ---------------------------------------------------------------------------
# Analysis
#
# analyze() is the core processing function. For each counter column it:
#   1. Clips extreme outliers using the percentile/padding axis scale so that
#      a single spike does not compress the entire chart.
#   2. Classifies every sample as OK / Warning / Critical using get_threshold().
#   3. Computes a rolling average (window configurable, default 10 samples)
#      to smooth out transient spikes in chart display.
#   4. Produces split series (_OK, _Warning, _Critical columns) so each status
#      band can be plotted in a different color.
#   5. Builds a findings dict for the Excel Findings and Worst Offenders sheets.
#
# chart_df is a copy of df â the original raw data is never modified so the
# Raw Data sheet always contains unclipped values.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def analyze(
    df: pd.DataFrame,
    counter_cols: list[str],
    memory_gb: int,
    disk_count: int,
    vm: bool,
    rolling_window: int,
    pct: float,
    pad: float,
    sample_start_str: str,
    sample_end_str: str,
    mem_src: str,
    cpu_src: str,
    disk_src: str,
) -> tuple[pd.DataFrame, list[dict]]:
    """
    Build chart_df (analysis values + rolling avg + split series) and findings.
    The original df is left unchanged for the Raw Data workbook sheet.
    """
    chart_df = df.copy()
    analysis_df = df.copy()
    findings = []
    new_cols = {}  # accumulated then concat'd once to avoid fragmentation

    for col in counter_cols:
        if col not in df.columns:
            continue
        not_scored_reason = ""
        # A blank page file counter keeps the "No samples" message. Only a
        # counter with data can be not scored for missing context.
        if "Usage_Peak" in col and pd.to_numeric(df[col], errors="coerce").notna().any():
            not_scored_reason = page_file_not_scored_reason(df, col, memory_gb)
            if not_scored_reason:
                analysis_df[col] = pd.Series(float("nan"), index=df.index)
            else:
                analysis_df[col] = page_file_percent_of_memory(
                    df[col], df[commit_limit_column(df, col)], memory_gb
                )
        else:
            analysis_df[col] = counter_analysis_series(df[col], col)
        chart_df[col] = analysis_df[col]
        vals = analysis_df[col].dropna()
        thr = get_threshold(col, memory_gb, disk_count, vm)
        if vals.empty:
            findings.append(
                {
                    "Counter": col,
                    "Category": counter_category(col),
                    "Status": "Not Available",
                    "Confidence": "Not Available",
                    "Average": None,
                    "Maximum": None,
                    "Violations": 0,
                    "ViolationPercent": 0.0,
                    "Warnings": 0,
                    "WarningPercent": 0.0,
                    "Samples": 0,
                    "Threshold": thr["note"] if thr else "No threshold defined",
                    "ThresholdSource": threshold_source(col, mem_src, cpu_src, disk_src),
                    "SampleStart": sample_start_str,
                    "SampleEnd": sample_end_str,
                    "PeakViolationWindow": (
                        f"Not scored: {not_scored_reason}"
                        if not_scored_reason
                        else "No samples recorded"
                    ),
                    "NotScoredReason": not_scored_reason,
                }
            )
            continue

        avg_val = float(vals.mean())
        max_val = float(vals.max())
        amax = axis_max(vals, pct, pad)
        # Clip extreme outliers for display (matching PS behavior)
        if amax is not None:
            chart_df[col] = chart_df[col].clip(upper=amax * 0.98)

        # Per-sample status drives the violation counts shown as detail. It uses
        # the real readings, not the values clipped for the chart, so a spike the
        # chart flattens is still counted. The counter's overall status is judged
        # on the AVERAGE, not the peak (2026-07-02, per user: a transient spike
        # must not fail an otherwise-healthy counter; the sustained average is
        # what scores).
        statuses = analysis_df[col].apply(lambda v: sample_status(v, thr))
        n_crit = int((statuses == "Critical").sum())
        n_warn = int((statuses == "Warning").sum())
        n_samp = int(vals.count())

        overall = sample_status(avg_val, thr)

        v_pct = round(n_crit / n_samp * 100, 2) if n_samp > 0 else 0.0
        w_pct = round(n_warn / n_samp * 100, 2) if n_samp > 0 else 0.0

        # Collect derived columns -- added via concat after the loop
        new_cols[f"{col}_RollingAvg"] = (
            chart_df[col].rolling(window=rolling_window, min_periods=1).mean()
        )
        new_cols[f"{col}_OK"] = chart_df[col].where(statuses == "OK")
        new_cols[f"{col}_Warning"] = chart_df[col].where(statuses == "Warning")
        new_cols[f"{col}_Critical"] = chart_df[col].where(statuses == "Critical")

        findings.append(
            {
                "Counter": col,
                "Category": counter_category(col),
                "Status": overall,
                "Confidence": confidence_rating(col, mem_src, cpu_src, disk_src),
                "Average": round(avg_val, 2),
                "Maximum": round(max_val, 2),
                "Violations": n_crit,
                "ViolationPercent": v_pct,
                "Warnings": n_warn,
                "WarningPercent": w_pct,
                "Samples": n_samp,
                "Threshold": thr["note"] if thr else "No threshold defined",
                "ThresholdSource": threshold_source(col, mem_src, cpu_src, disk_src),
                "SampleStart": sample_start_str,
                "SampleEnd": sample_end_str,
                "PeakViolationWindow": peak_violation_window(analysis_df, col, thr),
            }
        )

    if new_cols:
        chart_df = pd.concat(
            [chart_df, pd.DataFrame(new_cols, index=chart_df.index)], axis=1
        )

    return chart_df, findings


# ---------------------------------------------------------------------------
# Excel export
#
# Workbook sheets:
#   Environment   â run parameters (input file, hardware context, thresholds).
#   Findings      â one row per counter with status, averages, violation counts.
#   Worst Offenders â filtered/sorted subset of Findings (violations only).
#   Raw Data      â unmodified counter values as loaded from the CSV.
#   ChartData     â clipped + rolling average + status-split series for charts.
#
# xlsxwriter is used instead of openpyxl because it is significantly faster
# for write-only workbooks and supports embedded charts natively.
#
# _to_excel_serial() converts pandas Timestamps to Excel OADate serial numbers
# so that the ChartData Time column renders as dates on scatter chart axes.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------


def _to_excel_serial(ts) -> float | None:
    """Convert a pandas Timestamp to an Excel OADate serial number."""
    try:
        return (ts - pd.Timestamp("1899-12-30")).total_seconds() / 86400
    except Exception:
        return None


def export_excel(
    df_raw: pd.DataFrame,
    df_chart: pd.DataFrame,
    findings: list[dict],
    env_rows: list[dict],
    counter_cols: list[str],
    output_path: str,
    rolling_window: int,
    sample_start_str: str,
    sample_end_str: str,
    memory_gb: int = 0,
    disk_count: int = 0,
    vm: bool = False,
    host_name: str = "",
    stamp: str = "",
) -> None:

    wb = xlsxwriter.Workbook(output_path, {"nan_inf_to_errors": True})
    base_formats = xlsxwriter_formats(wb)
    fmt = {
        "hdr": base_formats["header"],
        "cell": base_formats["cell"],
        "ok": base_formats["status_pass"],
        "warn": base_formats["status_warning"],
        "crit": base_formats["status_fail"],
        "unavailable": base_formats["status_neutral"],
    }
    status_fmt = {
        "OK": fmt["ok"],
        "Warning": fmt["warn"],
        "Critical": fmt["crit"],
        "Not Available": fmt["unavailable"],
    }

    def write_header_row(ws, headers: list[str], row: int = 0):
        for c, h in enumerate(headers):
            ws.write(row, c, h, fmt["hdr"])

    def write_data_rows(
        ws, headers: list[str], rows: list[list], start: int = 1, status_col: int = -1
    ):
        for r, row in enumerate(rows, start):
            for c, val in enumerate(row):
                f = (
                    status_fmt.get(str(val), fmt["cell"])
                    if c == status_col
                    else fmt["cell"]
                )
                if val is None or (isinstance(val, float) and math.isnan(val)):
                    ws.write_blank(r, c, None, f)
                else:
                    ws.write(r, c, val, f)

    # ---- Environment -------------------------------------------------------
    # The document stamp occupies row 0 of the first sheet, so its header and
    # data shift down one row when a stamp is supplied.
    ws_env = wb.add_worksheet("Environment")
    env_offset = 0
    if stamp:
        ws_env.write_string(0, 0, stamp)
        env_offset = 1
    write_header_row(ws_env, ["Setting", "Value"], row=env_offset)
    write_data_rows(
        ws_env,
        ["Setting", "Value"],
        [[r["Setting"], r["Value"]] for r in env_rows],
        start=env_offset + 1,
    )
    ws_env.autofit()

    # ---- Findings ----------------------------------------------------------
    ws_find = wb.add_worksheet("Findings")
    f_keys = list(findings[0].keys()) if findings else []
    s_col = f_keys.index("Status") if "Status" in f_keys else -1
    write_header_row(ws_find, f_keys)
    write_data_rows(
        ws_find, f_keys, [[f[k] for k in f_keys] for f in findings], status_col=s_col
    )
    ws_find.autofit()

    # ---- Worst Offenders ---------------------------------------------------
    ws_worst = wb.add_worksheet("Worst Offenders")
    worst = sorted(
        [
            f
            for f in findings
            if f["Status"] == "Not Available" or f["Violations"] > 0 or f["Warnings"] > 0
        ],
        key=lambda x: (
            -x["Violations"],
            -x["ViolationPercent"],
            -x["Warnings"],
            -(float(x["Maximum"]) if x["Maximum"] is not None else 0),
        ),
    )
    write_header_row(ws_worst, f_keys)
    write_data_rows(
        ws_worst, f_keys, [[w[k] for k in f_keys] for w in worst], status_col=s_col
    )
    ws_worst.autofit()

    # ---- Raw Data ----------------------------------------------------------
    ws_raw = wb.add_worksheet("Raw Data")
    raw_cols = list(df_raw.columns)
    write_header_row(ws_raw, raw_cols)
    for r, (_, row) in enumerate(df_raw.iterrows(), 1):
        for c, col in enumerate(raw_cols):
            val = row[col]
            if pd.isna(val):
                ws_raw.write_blank(r, c, None, fmt["cell"])
            elif isinstance(val, (pd.Timestamp, datetime)):
                ws_raw.write(r, c, str(val), fmt["cell"])
            else:
                ws_raw.write(r, c, val, fmt["cell"])
    ws_raw.freeze_panes(1, 0)
    ws_raw.autofit()

    # ---- ChartData ---------------------------------------------------------
    ws_cd = wb.add_worksheet("ChartData")
    cd_cols = list(df_chart.columns)  # mutable -- threshold helper cols appended below
    write_header_row(ws_cd, cd_cols)

    n_data_rows = len(df_chart)

    # Write ChartData body (Time column as Excel serial for scatter charts)
    time_cd_idx = cd_cols.index("Time") if "Time" in cd_cols else -1
    for r, (_, row) in enumerate(df_chart.iterrows(), 1):
        for c, col in enumerate(cd_cols):
            val = row[col]
            if col == "Time":
                serial = _to_excel_serial(val) if not pd.isna(val) else None
                if serial is not None:
                    ws_cd.write_number(r, c, serial)
                else:
                    ws_cd.write_blank(r, c, None)
            elif pd.isna(val):
                ws_cd.write_blank(r, c, None)
            else:
                ws_cd.write(r, c, val)
    ws_cd.freeze_panes(1, 0)

    sample_window = f"{sample_start_str} - {sample_end_str}"
    analyzed_system = str(host_name or "").strip() or "Not detected"

    # ---- Per-counter chart sheets ------------------------------------------
    for col in counter_cols:
        if col not in cd_cols:
            continue

        finding = next((f for f in findings if f["Counter"] == col), None)
        thr = get_threshold(col, memory_gb=memory_gb, disk_count=disk_count, vm=vm)

        # Safe sheet name
        sheet_name = re.sub(r"[:\\/*?\[\]]", "_", col)
        if len(sheet_name) > 31:
            sheet_name = sheet_name[:31]

        try:
            ws_ctr = wb.add_worksheet(sheet_name)
        except Exception:
            continue

        raw_idx = cd_cols.index(col) if col in cd_cols else None
        rolling_key = f"{col}_RollingAvg"
        rol_idx = cd_cols.index(rolling_key) if rolling_key in cd_cols else None

        # Threshold helper column appended to ChartData on the fly
        thr_idx = None
        if thr and thr.get("critical") is not None:
            thr_idx = len(cd_cols)
            header = f"Standard_{col}"
            cd_cols.append(header)
            ws_cd.write(0, thr_idx, header, fmt["hdr"])
            for row_r in range(1, n_data_rows + 1):
                ws_cd.write_number(row_r, thr_idx, thr["critical"])

        # Build scatter chart
        chart = wb.add_chart({"type": "scatter", "subtype": "straight"})
        chart.set_title(
            {
                "name": perfmon_chart_title(col, sample_window, analyzed_system),
                "name_font": {"size": 14, "bold": True},
            }
        )
        chart.set_size({"width": 1400, "height": 700})
        chart.set_x_axis({"name": "Time", "num_format": "mm/dd hh:mm"})
        chart.set_y_axis({"name": "Value", "min": 0})
        chart.set_legend({"position": "bottom"})

        if raw_idx is not None:
            chart.add_series(
                {
                    "name": col,
                    "categories": [
                        "ChartData",
                        1,
                        time_cd_idx,
                        n_data_rows,
                        time_cd_idx,
                    ],
                    "values": ["ChartData", 1, raw_idx, n_data_rows, raw_idx],
                    "line": {"color": _BLUE, "width": 2},
                    "marker": {"type": "none"},
                }
            )

        if rol_idx is not None:
            chart.add_series(
                {
                    "name": f"{rolling_window}-sample rolling avg",
                    "categories": [
                        "ChartData",
                        1,
                        time_cd_idx,
                        n_data_rows,
                        time_cd_idx,
                    ],
                    "values": ["ChartData", 1, rol_idx, n_data_rows, rol_idx],
                    "line": {"color": "#000000", "width": 3, "dash_type": "dash"},
                    "marker": {"type": "none"},
                }
            )

        if thr_idx is not None and thr is not None:
            chart.add_series(
                {
                    "name": f"Standard: {thr['label']}",
                    "categories": [
                        "ChartData",
                        1,
                        time_cd_idx,
                        n_data_rows,
                        time_cd_idx,
                    ],
                    "values": ["ChartData", 1, thr_idx, n_data_rows, thr_idx],
                    "line": {"color": _RED, "width": 2, "dash_type": "dash"},
                    "marker": {"type": "none"},
                }
            )

        ws_ctr.insert_chart("B2", chart)

        # Metadata below chart
        meta = 38
        status_val = finding["Status"] if finding else "Unknown"
        ws_ctr.write(meta, 0, "Counter", fmt["hdr"])
        ws_ctr.write(meta, 1, col, fmt["cell"])
        ws_ctr.write(meta + 1, 0, "Status", fmt["hdr"])
        ws_ctr.write(meta + 1, 1, status_val, status_fmt.get(status_val, fmt["cell"]))
        ws_ctr.write(meta + 2, 0, "Sample Window", fmt["hdr"])
        ws_ctr.write(meta + 2, 1, sample_window, fmt["cell"])
        ws_ctr.write(meta + 3, 0, "Analyzed System", fmt["hdr"])
        ws_ctr.write(meta + 3, 1, analyzed_system, fmt["cell"])
        if thr:
            ws_ctr.write(meta + 4, 0, "Standard", fmt["hdr"])
            ws_ctr.write(meta + 4, 1, thr["note"], fmt["cell"])
        ws_ctr.set_column(0, 0, 20)
        ws_ctr.set_column(1, 1, 60)

    wb.close()


# ---------------------------------------------------------------------------
# PNG graphs
# ---------------------------------------------------------------------------


def export_png_charts(
    df: pd.DataFrame,
    counter_cols: list[str],
    findings: list[dict],
    png_folder: str,
    rolling_window: int,
    pct: float,
    pad: float,
    sample_start_str: str,
    sample_end_str: str,
    memory_gb: int = 0,
    disk_count: int = 0,
    vm: bool = False,
    host_name: str = "",
) -> None:
    os.makedirs(png_folder, exist_ok=True)
    for stale_png in Path(png_folder).glob("*.png"):
        try:
            stale_png.unlink()
        except OSError as exc:
            log.warn(f"Could not remove stale PerfMon graph {stale_png}: {exc}")

    sample_window = f"{sample_start_str} - {sample_end_str}"
    analyzed_system = str(host_name or "").strip() or "Not detected"
    times = df["Time"]
    span_hours = (
        (times.max() - times.min()).total_seconds() / 3600 if not times.empty else 0
    )

    for col in counter_cols:
        if col not in df.columns:
            continue
        finding = next((f for f in findings if f["Counter"] == col), None)
        if finding is None:
            continue

        raw_vals = df[col].dropna()
        thr = get_threshold(col, memory_gb=memory_gb, disk_count=disk_count, vm=vm)
        max_raw = float(raw_vals.max()) if not raw_vals.empty else 0

        png_path = os.path.join(png_folder, perfmon_chart_filename(col, png_folder))
        if max_raw == 0:
            render_zero_counter_strip(
                col,
                png_path,
                times,
                thr,
                sample_window,
                has_samples=not raw_vals.empty,
                sample_count=int(raw_vals.count()),
                true_max=max_raw,
                host_name=analyzed_system,
                not_scored_reason=finding.get("NotScoredReason", ""),
            )
            log.result("Graph (PNG)", png_path)
            continue

        amax = perfmon_chart_axis_max(max_raw, thr)

        # --- Figure ---------------------------------------------------------
        fig, ax = plt.subplots(figsize=(14.3, 7.2), dpi=200)
        fig.patch.set_facecolor("white")
        ax.set_facecolor("white")

        # Background zones
        if thr and amax:
            crit = thr.get("critical")
            if crit is not None and crit > 0:
                ax.axhspan(0, min(crit, amax), alpha=_ALPHA, color=_GREEN_BG, zorder=0)
                if crit < amax:
                    ax.axhspan(crit, amax, alpha=_ALPHA, color=_RED_BG, zorder=0)
            elif crit == 0:
                ax.axhspan(0, amax, alpha=_ALPHA, color=_RED_BG, zorder=0)
            else:
                ax.axhspan(0, amax, alpha=_ALPHA, color=_GREEN_BG, zorder=0)

        ax.plot(times, df[col], color=_BLUE, linewidth=2, label="_nolegend_", zorder=3)

        # Rolling average
        rolling_col = f"{col}_RollingAvg"
        if rolling_col in df.columns:
            ax.plot(
                times,
                df[rolling_col],
                color=_NEARBLACK,
                linewidth=3,
                linestyle="--",
                label=f"{rolling_window}-sample rolling avg",
                zorder=4,
            )

        # Threshold / standard legend entry
        extra_handles = []
        if thr:
            if thr.get("critical") is not None:
                if thr["critical"] <= amax:
                    ax.axhline(
                        y=thr["critical"],
                        color=_RED,
                        linewidth=2,
                        linestyle="--",
                        zorder=5,
                    )
                extra_handles.append(
                    Line2D(
                        [0],
                        [0],
                        color=_RED,
                        linewidth=2,
                        linestyle="--",
                        label=f"Standard: {thr['label']}",
                    )
                )
            else:
                extra_handles.append(
                    Line2D(
                        [0],
                        [0],
                        color=_NEARBLACK,
                        linewidth=0,
                        marker="s",
                        markersize=8,
                        label=f"Standard: {thr['label']}",
                    )
                )

        # Axes limits and formatting
        if amax:
            ax.set_ylim(0, amax)
        ax.set_xlim(times.min(), times.max())

        if span_hours <= 1:
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=15))
        elif span_hours <= 6:
            ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
        elif span_hours <= 24:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=1))
        else:
            ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, ha="center", fontsize=12)

        ax.tick_params(axis="y", labelsize=14)
        ax.grid(True, color="#DCDCDC", linewidth=0.8, zorder=1)

        # Subtitle (scale note)
        true_max_str = f"{max_raw:.3f}" if max_raw else "0"
        scale_note = f"Y-Axis: 0 to {amax:.3g}  |  True Max: {true_max_str}"
        if "Avg_Disk_ms" in col:
            scale_note += "  |  Unit: ms"
        if thr and thr.get("critical") is not None:
            scale_note += f"  |  Standard: {thr['note']}"

        fig.suptitle(
            perfmon_chart_title(col, sample_window, analyzed_system),
            fontsize=15,
            fontweight="bold",
            color=THEME.title,
            fontfamily=_FONT_FAMILY,
        )
        fig.text(
            0.5,
            0.01,
            scale_note,
            ha="center",
            fontsize=12,
            color=THEME.text,
            family=_FONT_FAMILY,
        )

        # Legend below axes, compact enough to preserve plot height in Word.
        plt.subplots_adjust(top=0.88, bottom=0.18, left=0.07, right=0.97)

        handles = ax.get_legend_handles_labels()[0] + extra_handles
        if handles:
            ax.legend(
                handles=handles,
                loc="upper center",
                bbox_to_anchor=(0.5, -0.13),
                ncol=min(2, len(handles)),
                fontsize=11,
                frameon=True,
                borderpad=0.8,
                handlelength=2.5,
                handletextpad=0.8,
                columnspacing=1.4,
            )

        fig.savefig(png_path, dpi=200, facecolor="white")
        plt.close(fig)
        log.result("Graph (PNG)", png_path)


# ---------------------------------------------------------------------------
# CLI input helpers
# ---------------------------------------------------------------------------


def clean_user_path(value) -> str:
    """Strip whitespace and surrounding quotes from a user-entered path."""
    return shared_clean_user_path(value)


def resolve_existing_perfmon_input(candidate_text: str) -> Path:
    """
    Resolve the input .blg or .csv file from a full path, relative path, or
    bare filename in the current working folder.
    """
    candidate = shared_resolve_existing_file(
        candidate_text, "PerfMon input file", {".blg", ".csv"}
    )

    if candidate.suffix.lower() == ".blg" and sys.platform != "win32":
        raise ValueError(
            ".blg files require Windows because relog.exe is required.\n"
            f"Entered file: {candidate}\n"
            "Tip: On Windows, export the BLG to CSV first:\n"
            "     relog input.blg -f CSV -o input.csv"
        )

    return candidate.resolve()


def resolve_output_xlsx(candidate_text: str, default_name: str) -> Path:
    """
    Resolve the output .xlsx path.

    Blank input uses default_name in the current working folder. A filename-only
    value also saves in the current working folder. Missing or different
    extensions are changed to .xlsx.
    """
    return shared_resolve_output_file(
        candidate_text, default_name, ".xlsx", "Output Excel workbook"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PerfMon Infrastructure Analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--input", "-i", help=".blg (Windows) or .csv file")
    parser.add_argument("--output", "-o", help="Output .xlsx path")
    parser.add_argument(
        "--template", "-t", help="Word template .docx to inject charts into (optional)"
    )
    parser.add_argument("--memory-gb", type=int, default=0, metavar="GB")
    parser.add_argument("--processors", type=int, default=0)
    parser.add_argument("--disks", type=int, default=0)
    parser.add_argument("--virtual-machine", action="store_true")
    parser.add_argument("--percentile", type=float, default=0.98)
    parser.add_argument("--padding", type=float, default=1.15)
    parser.add_argument("--rolling-window", type=int, default=10)
    parser.add_argument(
        "--relog-timeout",
        type=int,
        default=1800,
        help="Seconds to allow relog.exe BLG-to-CSV conversion before timing out.",
    )
    parser.add_argument(
        "--skip-docx",
        action="store_true",
        help="Skip Word template injection even when --template is given.",
    )
    add_stamp_arguments(parser)
    args = parser.parse_args()

    log.title("PerfMon Infrastructure Analysis")

    if not clean_user_path(args.input):
        print("PerfMon input file is required. Pass it with --input.", file=sys.stderr)
        raise SystemExit(2)
    try:
        in_path = resolve_existing_perfmon_input(args.input)
        default_out = in_path.with_suffix(".xlsx").name
        out_path = resolve_output_xlsx(args.output, default_out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(2)
    # ---- Hardware context --------------------------------------------------
    memory_gb = args.memory_gb
    n_cpu = args.processors
    n_disk = args.disks

    vm = args.virtual_machine

    mem_src = "Not supplied"
    cpu_src = "Not supplied"
    disk_src = "Not supplied"

    ext = in_path.suffix.lower()

    if ext == ".blg":
        log.step("Inspecting BLG counter list")
        det_cpu, det_disk = inspect_blg(str(in_path))
    else:
        det_cpu = det_disk = 0

    if n_cpu > 0:
        cpu_src = "Parameter Supplied"
    elif det_cpu > 0:
        n_cpu = det_cpu
        cpu_src = "Detected from BLG"

    if n_disk > 0:
        disk_src = "Parameter Supplied"
    elif det_disk > 0:
        n_disk = det_disk
        disk_src = "Detected from BLG"

    if memory_gb > 0:
        mem_src = "Parameter Supplied"

    log.detail("Logical Processors", f"{n_cpu} ({cpu_src})")
    log.detail("Physical Disk Count", f"{n_disk} ({disk_src})")
    log.detail(
        "Physical Memory GB",
        f"{memory_gb if memory_gb else 'Not supplied'} ({mem_src})",
    )

    # ---- Convert BLG -> CSV ------------------------------------------------
    csv_path = str(in_path)
    tmp_csv = None
    if ext == ".blg":
        log.step("Extracting selected counters from BLG")
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as tmp_handle:
            tmp_csv = tmp_handle.name
        try:
            blg_to_csv(str(in_path), COUNTERS, tmp_csv, args.relog_timeout)
        except RuntimeError as exc:
            if tmp_csv and os.path.exists(tmp_csv):
                os.unlink(tmp_csv)
            sys.exit(f"ERROR: {exc}")
        csv_path = tmp_csv

    # ---- Load + normalize --------------------------------------------------
    log.step("Normalizing PerfMon data")
    try:
        df_raw, counter_cols = load_and_normalize(csv_path)
    finally:
        if tmp_csv and os.path.exists(tmp_csv):
            os.unlink(tmp_csv)

    if df_raw.empty or not counter_cols:
        sys.exit("ERROR: No counter data found in input file.")

    analyzed_system = str(df_raw.attrs.get("perfmon_host_label") or "Not detected")
    log.detail("Analyzed system", analyzed_system)

    times_valid = df_raw["Time"].dropna()
    sample_start = times_valid.iloc[0]
    sample_end = times_valid.iloc[-1]
    ss_str = sample_start.strftime("%m-%d-%Y %H:%M")
    se_str = sample_end.strftime("%m-%d-%Y %H:%M")
    log.detail("Sample window", f"{ss_str} - {se_str}")

    # ---- Analyze -----------------------------------------------------------
    log.step("Building chart data, findings, and violation series")
    df_chart, findings = analyze(
        df_raw,
        counter_cols,
        memory_gb,
        n_disk,
        vm,
        args.rolling_window,
        args.percentile,
        args.padding,
        ss_str,
        se_str,
        mem_src,
        cpu_src,
        disk_src,
    )

    # ---- Environment rows --------------------------------------------------
    env_rows = [
        {"Setting": "Analyzed System", "Value": analyzed_system},
        {"Setting": "Input File", "Value": str(in_path)},
        {"Setting": "Output XLSX", "Value": str(out_path)},
        {
            "Setting": "Analyzed System Physical Memory (GB)",
            "Value": memory_gb or "Not supplied",
        },
        {"Setting": "Physical Memory Source", "Value": mem_src},
        {
            "Setting": "Logical Processor Count",
            "Value": n_cpu or "Not detected/supplied",
        },
        {"Setting": "Logical Processor Source", "Value": cpu_src},
        {"Setting": "Physical Disk Count", "Value": n_disk or "Not detected/supplied"},
        {"Setting": "Physical Disk Source", "Value": disk_src},
        {"Setting": "Virtual Machine", "Value": vm},
        {"Setting": "Sample Start", "Value": ss_str},
        {"Setting": "Sample End", "Value": se_str},
        {"Setting": "Sample Count", "Value": len(df_raw)},
        {
            "Setting": "Packet Counter Analysis",
            "Value": (
                "Cumulative packet error/discard counters are evaluated as "
                "non-negative increases between samples; raw values remain in Raw Data."
            ),
        },
        {"Setting": "Percentile Used For Scaling", "Value": args.percentile},
        {"Setting": "Chart Scale Padding", "Value": args.padding},
        {"Setting": "Rolling Average Window", "Value": args.rolling_window},
    ]

    # ---- Export Excel ------------------------------------------------------
    log.step("Creating Excel workbook")
    if out_path.exists():
        out_path.unlink()
    export_excel(
        df_raw,
        df_chart,
        findings,
        env_rows,
        counter_cols,
        str(out_path),
        args.rolling_window,
        ss_str,
        se_str,
        memory_gb=memory_gb,
        disk_count=n_disk,
        vm=vm,
        host_name=analyzed_system,
        stamp=stamp_from_args(args),
    )

    # ---- Export PNGs -------------------------------------------------------
    png_folder = str(out_path.parent / (out_path.stem + "_Charts"))
    log.step("Exporting PNG graphs")
    export_png_charts(
        df_chart,
        counter_cols,
        findings,
        png_folder,
        args.rolling_window,
        args.percentile,
        args.padding,
        ss_str,
        se_str,
        memory_gb=memory_gb,
        disk_count=n_disk,
        vm=vm,
        host_name=analyzed_system,
    )
    log.result("PNG graphs", png_folder)
    log.detail("Pass this folder to inject_perfmon_charts.py via --chart-folder")

    observations = build_perfmon_observations(findings, env_rows)
    observations_path = export_perfmon_observations(observations, png_folder)
    log.result("JSON", observations_path)

    # ---- Export Word document (optional) -----------------------------------
    docx_out = None
    if not args.skip_docx and args.template:
        try:
            tmpl_path = shared_resolve_existing_file(
                shared_clean_user_path(args.template),
                "Word template",
                {".docx"},
            )
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_docx = tmpl_path.stem + f"_Perfmon_{ts}.docx"
            docx_out = shared_resolve_output_file(
                "", default_docx, ".docx", "Output Word document"
            )
            import inject_perfmon_charts as _inj

            _inj.inject_perfmon_charts(
                chart_folder=Path(png_folder),
                template_path=tmpl_path,
                output_path=docx_out,
            )
        except ValueError as exc:
            log.warn(f"Skipping docx generation: {exc}")
            docx_out = None

    # ---- Done --------------------------------------------------------------
    log.ok("PerfMon analysis built")
    log.result("Excel", out_path)
    log.detail("Workbook includes")
    for sheet in [
        "Environment",
        "Findings",
        "Worst Offenders",
        "Raw Data",
        "ChartData",
        "Per-counter charts",
    ]:
        log.detail("Sheet", sheet)
    if docx_out:
        log.result("Word document", docx_out)


if __name__ == "__main__":
    main()
