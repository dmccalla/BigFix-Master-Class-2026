#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
report_log.py -- Uniform run-log output for the report-builder child scripts.

The Get/Inject scripts run as subprocesses of the builder
(build_health_check_report.py). Their stdout is captured and nested under the
orchestrator's RunLog, which already prints a professional structure: a run
header, ``MODULE 01 OF 12`` sections, ``[RUN]``/``[OK]``/``[WARNING]``/
``[ERROR]`` markers, and aligned ``label : value`` rows.

Historically each child script printed in its own ad-hoc style (different title
banners, ``Done.`` vs ``DONE:``, random labels and bullets), so the captured
master log read inconsistently. This helper gives every child one small, shared
vocabulary that is byte-for-byte the same as RunLog's, so the whole log -- and
standalone console output -- reads as a single, consistent document.

Usage (in a Get/Inject script):

    import report_log as log

    log.title("FillDB Performance")
    log.step("Combining rollover logs in chronological order")
    log.ok("Analysis complete")
    log.detail("Rows", 24)
    log.result("Word document", output_path)
    log.warn("Collection window not supplied; using analyzer timestamps")
    log.error("Could not read input file")     # -> stderr

Design notes:
  * ASCII only -- renders identically in every Windows console, the .log file,
    and editors (no garbled glyphs on legacy cp1252 consoles).
  * ``detail``/``result`` carry a 2-space lead so values nest visually under the
    preceding ``[OK]``/step, both standalone and (after the orchestrator's
    5-space indent) when captured.
  * ``error`` writes to stderr so standalone exit-code-1 paths still surface
    there; the builder merges child stderr into the captured log.
  * Every line is flushed so output streams live into the builder's log view
    instead of sitting in a block buffer until the script exits.
"""

from __future__ import annotations

import sys
from typing import Any

# Width of the label column in detail/result rows. Chosen so common labels
# ("Rows", "Word document", "Chart (PNG)") align without truncation.
LABEL_WIDTH = 14


def _emit(line: str = "", *, stream=None) -> None:
    print(line, file=stream if stream is not None else sys.stdout, flush=True)


def title(name: str) -> None:
    """One concise header line for a script. No decorative banner -- the builder
    already prints the module/step header above captured output."""
    _emit(str(name))


def step(message: str) -> None:
    """A progress step, e.g. ``- Extracting counters from BLG``."""
    _emit(f"- {message}")


def detail(label: str, value: Any = "") -> None:
    """An aligned ``label : value`` row, indented to nest under the step/status
    line it follows. With no value, prints the label as an indented note."""
    if value == "":
        _emit(f"  {label}")
    else:
        _emit(f"  {label:<{LABEL_WIDTH}}: {value}")


def result(label: str, value: Any) -> None:
    """An output-artifact row (path produced by the module). Alias of detail."""
    detail(label, value)


def ok(message: str) -> None:
    _emit(f"[OK] {message}")


def warn(message: str) -> None:
    _emit(f"[WARNING] {message}")


def error(message: str) -> None:
    """Report a failure. Goes to stderr (the builder merges it into the log)."""
    _emit(f"[ERROR] {message}", stream=sys.stderr)


def blank() -> None:
    _emit("")
