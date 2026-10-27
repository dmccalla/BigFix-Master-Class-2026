#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Select resolved evaluation results before raw client timing captures."""

from __future__ import annotations

import csv
from pathlib import Path

from Lib.Core.besapi_capture import sample_capture_lines


def evaluation_source_sort_key(path: Path) -> tuple:
    """Resolution adds names and preserves property IDs before aggregation.

    Copying or extracting a collection can change file timestamps. The resolved
    results in that collection remain preferable to its raw timing captures.
    """
    try:
        if path.suffix.lower() == ".xml":
            lines = sample_capture_lines(path, 1)
            columns = next(csv.reader(lines), [])
        else:
            with path.open(encoding="utf-8-sig", newline="") as handle:
                columns = next(csv.reader(handle), [])
    except (OSError, UnicodeError, csv.Error):
        columns = []
    structured = "Result" in columns and bool(
        set(columns)
        & {
            "ClientProcessingSeconds",
            "ClientEvaluationSeconds",
            "TotalClientProcessingSeconds",
            "TotalClientEvaluationSeconds",
            "AvgClientProcessingSeconds",
            "AvgClientEvaluationSeconds",
            "Occurrences",
        }
    )
    return (
        not structured,
        "-detail" in path.stem.lower(),
        -path.stat().st_mtime,
        path.name.lower(),
    )
