#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""capture_time.py -- a capture's Report Generated stamp as report text."""

from __future__ import annotations

from datetime import datetime

_STAMP_FORMATS = (
    "%a, %d %b %Y %H:%M:%S %z",
    "%a, %d %b %Y %H:%M:%S",
    "%d %b %Y %H:%M:%S",
)


def capture_time_text(value: str) -> str:
    """A capture's Report Generated stamp ("Sun, 14 Jun 2026 14:50:23 -0400") as
    MM-DD-YYYY HH:MM, or "" when it cannot be read."""
    text = " ".join(str(value or "").split())
    for fmt in _STAMP_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%m-%d-%Y %H:%M")
        except ValueError:
            continue
    return ""
