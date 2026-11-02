#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Ceilings on what the tool accepts as input.

Every input file, folder, configuration file and typed value has a limit, so a
wrong or hostile selection fails with a clear message instead of exhausting
memory, disk or time. The ceilings sit well above real collections. The largest
measured inputs are a 396 MB PerfMon capture, a 142 MB Top 10 capture and a
36 MB Client Performance capture for 300,000 endpoints.

An advanced setting raises the size ceilings for a legitimate outlier such as a
week-long PerfMon capture. Set BIGFIX_HC_INPUT_LIMIT_MULTIPLIER to a whole number
from 1 to 8. The run log records that it was used. The archive ratio, entry
count, folder and text ceilings are never raised.
"""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

KIB = 1024
MIB = 1024 * KIB
GIB = 1024 * MIB

TEXT_CAPTURE_LIMIT = 1 * GIB
PERFMON_LIMIT = 4 * GIB
ARCHIVE_COMPRESSED_LIMIT = 250 * MIB
ARCHIVE_EXPANDED_LIMIT = 2 * GIB
ARCHIVE_RATIO_LIMIT = 100
ARCHIVE_ENTRY_LIMIT = 10_000
JSON_LIMIT = 16 * MIB
JSON_DEPTH_LIMIT = 12
MAX_ENDPOINT_ROWS = 2_000_000
MAX_FOLDER_ENTRIES = 50_000
MAX_FOLDER_DEPTH = 12
MAX_PATH_TEXT_CHARS = 1_024
MAX_FIELD_TEXT_CHARS = 2_000

MULTIPLIER_ENV = "BIGFIX_HC_INPUT_LIMIT_MULTIPLIER"
MAX_MULTIPLIER = 8

ARCHIVE_SUFFIXES = {".docx", ".dotx", ".xlsx", ".xlsm", ".xltx", ".zip"}
PERFMON_SUFFIXES = {".blg"}
JSON_SUFFIXES = {".json"}
PATH_KEY_ENDINGS = ("path", "folder", "file", "root", "dir", "template")


class InputLimitError(ValueError):
    """An input is over a documented ceiling."""


def limit_multiplier() -> int:
    """Return the size multiplier from the advanced setting, 1 when unset or invalid."""
    raw = os.environ.get(MULTIPLIER_ENV, "").strip()
    if raw.isascii() and raw.isdigit():
        return max(1, min(int(raw), MAX_MULTIPLIER))
    return 1


def override_note() -> str:
    """Return a run log line when the size ceilings were raised, else blank."""
    factor = limit_multiplier()
    if factor == 1:
        return ""
    return f"Input size limits are raised {factor} times by {MULTIPLIER_ENV}."


def format_size(size: int) -> str:
    if size >= GIB:
        return f"{size / GIB:.1f} GiB"
    if size >= MIB:
        return f"{size / MIB:.1f} MiB"
    return f"{size / KIB:.1f} KiB"


def _kind_and_limit(path: Path) -> tuple[str, int]:
    suffix = path.suffix.lower()
    if suffix in PERFMON_SUFFIXES:
        return "PerfMon", PERFMON_LIMIT
    if suffix in ARCHIVE_SUFFIXES:
        return "Office and archive", ARCHIVE_COMPRESSED_LIMIT
    if suffix in JSON_SUFFIXES:
        return "JSON", JSON_LIMIT
    return "capture and log", TEXT_CAPTURE_LIMIT


def size_limit_for(path: Path) -> int:
    return _kind_and_limit(path)[1] * limit_multiplier()


def _raise_hint() -> str:
    return (
        f"Choose a smaller file. For a genuine outlier, set {MULTIPLIER_ENV} "
        f"to a whole number from 2 to {MAX_MULTIPLIER} and start again."
    )


def file_size_problem(path: Path, label: str, size: int | None = None) -> str:
    """Return why a file is too large, or blank when it is within its ceiling."""
    if size is None:
        size = path.stat().st_size
    kind, base = _kind_and_limit(path)
    limit = base * limit_multiplier()
    if size <= limit:
        return ""
    return (
        f"{label} is {format_size(size)}, over the {format_size(limit)} limit "
        f"for {kind} files. {_raise_hint()}"
    )


def archive_problem(path: Path, label: str) -> str:
    """Return why a zip based file looks like a decompression bomb, or blank."""
    factor = limit_multiplier()
    try:
        with zipfile.ZipFile(path) as archive:
            members = archive.infolist()
    except (zipfile.BadZipFile, OSError):
        return ""
    if len(members) > ARCHIVE_ENTRY_LIMIT:
        return (
            f"{label} holds {len(members):,} entries, over the "
            f"{ARCHIVE_ENTRY_LIMIT:,} entry limit."
        )
    expanded = sum(member.file_size for member in members)
    if expanded > ARCHIVE_EXPANDED_LIMIT * factor:
        return (
            f"{label} expands to {format_size(expanded)}, over the "
            f"{format_size(ARCHIVE_EXPANDED_LIMIT * factor)} limit. {_raise_hint()}"
        )
    packed = max(path.stat().st_size, 1)
    if expanded / packed > ARCHIVE_RATIO_LIMIT:
        return (
            f"{label} expands more than {ARCHIVE_RATIO_LIMIT} times its stored size, "
            "which is how a decompression bomb looks."
        )
    return ""


def endpoint_rows_problem(count: int, label: str = "The capture") -> str:
    if count <= MAX_ENDPOINT_ROWS:
        return ""
    return (
        f"{label} holds {count:,} endpoint rows, over the "
        f"{MAX_ENDPOINT_ROWS:,} row limit."
    )


def bounded_walk(root: Path) -> list[Path]:
    """Return every file under *root*, failing when the tree is implausibly big.

    Links are not followed. The walk stops as soon as the entry or depth ceiling
    is crossed, so selecting a drive root fails quickly instead of scanning it.
    """
    files: list[Path] = []
    entries = 0
    root_depth = len(root.parts)
    for current, folders, names in os.walk(root, followlinks=False):
        depth = len(Path(current).parts) - root_depth
        if depth > MAX_FOLDER_DEPTH:
            raise InputLimitError(
                f"The folder is nested more than {MAX_FOLDER_DEPTH} levels deep."
            )
        entries += len(folders) + len(names)
        if entries > MAX_FOLDER_ENTRIES:
            raise InputLimitError(
                f"The folder holds more than {MAX_FOLDER_ENTRIES:,} files and folders. "
                "Select the collection folder, not a drive or a parent folder."
            )
        files.extend(Path(current, name) for name in names)
    return files


def _check_json_value(value: object, key: str, depth: int) -> None:
    if depth > JSON_DEPTH_LIMIT:
        raise InputLimitError(
            f"The JSON is nested more than {JSON_DEPTH_LIMIT} levels deep."
        )
    if isinstance(value, dict):
        for child_key, child in value.items():
            _check_json_value(child, str(child_key), depth + 1)
    elif isinstance(value, list):
        for child in value:
            _check_json_value(child, key, depth + 1)
    elif isinstance(value, str):
        pathlike = key.lower().endswith(PATH_KEY_ENDINGS)
        limit = MAX_PATH_TEXT_CHARS if pathlike else MAX_FIELD_TEXT_CHARS
        if len(value) > limit:
            raise InputLimitError(
                f"The value for '{key}' is {len(value):,} characters, "
                f"over the {limit:,} character limit."
            )


def read_json_file(path: Path, label: str = "JSON file") -> object:
    """Read a JSON file within the size, depth and text ceilings."""
    problem = file_size_problem(path, label)
    if problem:
        raise InputLimitError(problem)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except RecursionError as exc:
        raise InputLimitError(f"{label} is nested too deeply.") from exc
    _check_json_value(data, "", 0)
    return data


def bind_text_limit(variable, limit: int) -> None:
    """Cut anything typed or pasted into a Tk text variable at *limit* characters."""

    def enforce(*_args) -> None:
        text = variable.get()
        if len(text) > limit:
            variable.set(text[:limit])

    variable.trace_add("write", enforce)
