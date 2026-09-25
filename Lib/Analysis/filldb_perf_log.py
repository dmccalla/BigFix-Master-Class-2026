#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
filldb_perf_log.py -- FillDB raw performance-log handling.

The "Enable FillDB Performance Logging" task on the BigFix root server writes a
rolling set of raw text logs: the active ``FillDBPerf.log`` plus size-rolled
siblings ``FillDBPerf.log_0``, ``FillDBPerf.log_1``, ... (100 MB per file by
default, up to a 4 GB total). The tool previously expected the
consultant to run ``MXFillDBPerf.exe`` by hand to turn those logs into the
analysis CSV the report consumes -- a step that was easy to forget.

This module runs that analysis for us. Given a raw log, a folder of logs, or an
already-analyzed CSV, it returns the analysis CSV the rest of the FillDB
pipeline already understands:

* A path that is already an analysis CSV is passed through unchanged.
* A raw log (or a folder containing the rolling set) is concatenated in true
  chronological order and fed to ``MXFillDBPerf.exe``.

Ordering matters. The analyzer derives the capture's start/end (and therefore
its duration) from the FIRST and LAST lines of the combined input, not from the
min/max timestamp it sees. The legacy BigFix combine step sorted files
alphabetically -- which places the active ``FillDBPerf.log`` *before*
``FillDBPerf.log_0`` and yields a negative capture duration. We instead order by
each file's first internal timestamp, which is robust against the rollover
naming scheme and against non-default log names.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
UTILITIES_DIR = PROJECT_ROOT / "Utilities"
ANALYZER_EXE_NAME = "MXFillDBPerf.exe"

from Lib.Core.subprocess_window import hidden_subprocess_kwargs

_SUBPROCESS_KWARGS = hidden_subprocess_kwargs()

# Header line emitted by `MXFillDBPerf.exe --format csv`. Used to recognize a
# file that is already an analysis CSV (so we pass it through rather than trying
# to re-analyze it as a raw log).
ANALYZER_CSV_FIRST_FIELD = "FillDB Object"

# Raw FillDB perf log lines start with an RFC-2822 date, then a " -- " field
# separator, e.g.:
#   Mon, 17 Nov 2025 11:36:12 -0500 -- 10880 -- GetReservedPropertyMap: 64 ms
_LINE_FIELD_SEP = " -- "

# A rollover member is "<base>.log" (the active file) or "<base>.log_<N>" (a
# size-rolled segment). Matching is case-insensitive because the active file has
# been observed as both "FillDBperf.log" and "FillDBPerf.log".
_ROLLOVER_RE = re.compile(r"^(?P<base>.+\.log)(?:_(?P<n>\d+))?$", re.IGNORECASE)

# Generous default: a multi-GB capture can take a few minutes to analyze. A
# 400 MB combined log analyzes in well under a minute, so this is headroom, not
# an expected wait.
DEFAULT_ANALYZER_TIMEOUT = 1800


def _log(log, message: str) -> None:
    """Emit a progress line to whatever the caller passed (callable or .info)."""
    if log is None:
        return
    if callable(log):
        log(message)
    elif hasattr(log, "info"):
        log.info("FillDB", message)


# ---------------------------------------------------------------------------
# Analyzer executable
# ---------------------------------------------------------------------------


def analyzer_exe_path() -> Path | None:
    """Return the path to MXFillDBPerf.exe in Utilities/, or None if absent."""
    exact = UTILITIES_DIR / ANALYZER_EXE_NAME
    if exact.is_file():
        return exact
    if UTILITIES_DIR.is_dir():
        wanted = ANALYZER_EXE_NAME.lower()
        for candidate in UTILITIES_DIR.iterdir():
            if candidate.is_file() and candidate.name.lower() == wanted:
                return candidate
    return None


# ---------------------------------------------------------------------------
# Timestamp parsing
# ---------------------------------------------------------------------------


def parse_log_timestamp(line: str) -> datetime | None:
    """Parse the leading RFC-2822 timestamp from a raw FillDB perf log line.

    Returns a timezone-aware ``datetime`` or ``None`` when the line does not
    begin with a parseable timestamp (blank lines, partial writes, etc.).
    """
    if not line:
        return None
    head = line.split(_LINE_FIELD_SEP, 1)[0].strip()
    if not head:
        return None
    try:
        parsed = parsedate_to_datetime(head)
    except (TypeError, ValueError, IndexError):
        return None
    return parsed


def _naive(value: datetime | None) -> datetime | None:
    """Drop tzinfo so the value matches the naive wall-clock metadata the rest
    of the report uses (see get_data_window)."""
    if value is None:
        return None
    return value.replace(tzinfo=None)


def _first_timestamp(path: Path, max_lines: int = 200) -> datetime | None:
    """First parseable timestamp near the top of a log file."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for _ in range(max_lines):
                line = handle.readline()
                if not line:
                    break
                ts = parse_log_timestamp(line)
                if ts is not None:
                    return ts
    except OSError:
        return None
    return None


def _last_timestamp(path: Path, tail_bytes: int = 256 * 1024) -> datetime | None:
    """Last parseable timestamp from the tail of a log file.

    Reads only the final chunk so a multi-hundred-MB log stays cheap.
    """
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > tail_bytes:
                handle.seek(-tail_bytes, os.SEEK_END)
            chunk = handle.read()
    except OSError:
        return None
    text = chunk.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        ts = parse_log_timestamp(line)
        if ts is not None:
            return ts
    return None


# ---------------------------------------------------------------------------
# Analysis-CSV detection
# ---------------------------------------------------------------------------


def looks_like_analysis_csv(path: Path) -> bool:
    """True when *path* is an already-analyzed FillDB CSV (so we pass it
    through instead of treating it as a raw log)."""
    try:
        with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
            for _ in range(20):
                line = handle.readline()
                if not line:
                    break
                stripped = line.strip()
                if not stripped:
                    continue
                first_field = stripped.split(",", 1)[0].strip()
                return first_field.lower() == ANALYZER_CSV_FIRST_FIELD.lower()
    except OSError:
        return False
    return False


# ---------------------------------------------------------------------------
# Log-set discovery and ordering
# ---------------------------------------------------------------------------


def _rollover_base(name: str) -> str | None:
    """Return the base log name (e.g. ``FillDBPerf.log``) for a rollover member,
    or None when *name* is not a ``.log`` / ``.log_<N>`` file."""
    match = _ROLLOVER_RE.match(name)
    return match.group("base") if match else None


def _group_in_folder(folder: Path, base: str) -> list[Path]:
    """All rollover members in *folder* sharing the given base name."""
    members: list[Path] = []
    base_lower = base.lower()
    try:
        entries = list(folder.iterdir())
    except OSError:
        return members
    for entry in entries:
        if not entry.is_file():
            continue
        entry_base = _rollover_base(entry.name)
        if entry_base is not None and entry_base.lower() == base_lower:
            members.append(entry)
    return members


def _total_size(files: list[Path]) -> int:
    total = 0
    for f in files:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def _best_log_set_in_folder(folder: Path) -> list[Path]:
    """Pick the most likely FillDB perf log set in *folder*.

    Files are grouped by base name. A group whose base contains "filldbperf"
    wins (the standard name); otherwise the group with the most total bytes --
    the real capture -- is used, so a stray ``.log`` never beats the actual
    rolling set. Non-``.log`` files (README .txt, prior .csv) are ignored.
    """
    groups: dict[str, list[Path]] = {}
    try:
        entries = list(folder.iterdir())
    except OSError:
        return []
    for entry in entries:
        if not entry.is_file():
            continue
        base = _rollover_base(entry.name)
        if base is None:
            continue
        groups.setdefault(base.lower(), []).append(entry)
    if not groups:
        return []
    preferred = [files for key, files in groups.items() if "filldbperf" in key]
    pool = preferred if preferred else list(groups.values())
    return max(pool, key=_total_size)


def discover_log_set(target: Path | str) -> list[Path]:
    """Return the raw FillDB perf log files implied by *target* (unordered).

    * A file: gather its rollover siblings from the same folder (so selecting
      any one segment, or the active log, picks up the whole set).
    * A folder: pick the best log set it contains.
    """
    target = Path(target)
    if target.is_file():
        base = _rollover_base(target.name)
        if base is None:
            return [target]
        group = _group_in_folder(target.parent, base)
        return group or [target]
    if target.is_dir():
        return _best_log_set_in_folder(target)
    return []


def _suffix_sort_key(path: Path) -> tuple[int, int]:
    """Fallback ordering: numbered segments ascending, the active base last."""
    match = re.search(r"\.log_(\d+)$", path.name, re.IGNORECASE)
    if match:
        return (0, int(match.group(1)))
    return (1, 0)


def order_log_files(files: list[Path]) -> list[Path]:
    """Order log files chronologically.

    Primary: each file's first internal timestamp (robust to any rollover
    naming scheme). Fallback when a timestamp can't be read from every file:
    numeric suffix order with the active (suffixless) log last.
    """
    if len(files) <= 1:
        return list(files)
    decorated = [(_first_timestamp(f), f) for f in files]
    if all(ts is not None for ts, _ in decorated):
        decorated.sort(key=lambda pair: pair[0])
        return [f for _, f in decorated]
    return sorted(files, key=_suffix_sort_key)


# ---------------------------------------------------------------------------
# Combine + analyze
# ---------------------------------------------------------------------------


def combine_logs(files: list[Path], dest_path: Path) -> Path:
    """Concatenate *files* (already ordered) into *dest_path*.

    Streams in binary to keep memory flat for hundreds-of-MB logs, and writes a
    newline between files so the last line of one segment never merges with the
    first line of the next.
    """
    dest_path = Path(dest_path)
    with dest_path.open("wb") as out:
        for f in files:
            with Path(f).open("rb") as src:
                shutil.copyfileobj(src, out, length=1024 * 1024)
            out.write(b"\n")
    return dest_path


def run_analyzer(
    log_path: Path,
    exe: Path | None = None,
    timeout: int = DEFAULT_ANALYZER_TIMEOUT,
) -> str:
    """Run ``MXFillDBPerf.exe`` on *log_path* and return the CSV text (stdout)."""
    exe = exe or analyzer_exe_path()
    if exe is None:
        raise FileNotFoundError(
            f"{ANALYZER_EXE_NAME} was not found in {UTILITIES_DIR}.\n"
            "It is required to analyze raw FillDB performance logs. On non-Windows "
            "systems, run the analyzer beforehand and provide the resulting CSV."
        )
    try:
        result = subprocess.run(
            [
                str(exe),
                "--input",
                str(log_path),
                "--format",
                "csv",
                "--stats",
                "--healthcheck",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            **_SUBPROCESS_KWARGS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"{ANALYZER_EXE_NAME} timed out after {timeout}s analyzing {log_path}."
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            f"{ANALYZER_EXE_NAME} exited with code {result.returncode}.\n{detail}"
        )
    if not result.stdout.strip():
        raise RuntimeError(f"{ANALYZER_EXE_NAME} produced no output for {log_path}.")
    return result.stdout


def _default_csv_dest(ordered: list[Path]) -> Path:
    sample = ordered[0]
    base = _rollover_base(sample.name) or sample.name
    stem = base[:-4] if base.lower().endswith(".log") else Path(base).stem
    return sample.with_name(f"{stem}_FillDB_Analysis.csv")


def ensure_analysis_csv(
    input_path: Path | str,
    *,
    dest_csv: Path | str | None = None,
    exe: Path | None = None,
    log=None,
    timeout: int = DEFAULT_ANALYZER_TIMEOUT,
) -> Path:
    """Return a FillDB analysis CSV path for *input_path*.

    * Already-analyzed CSV -> returned unchanged (no exe run).
    * Raw log / folder of logs -> combined in chronological order, analyzed by
      ``MXFillDBPerf.exe``, and written to *dest_csv* (or a sensible default).

    The combined temp log is always cleaned up; only the small CSV is kept.
    """
    input_path = Path(input_path)

    if input_path.is_file() and looks_like_analysis_csv(input_path):
        _log(log, f"Using existing FillDB analysis CSV: {input_path}")
        return input_path

    files = discover_log_set(input_path)
    if not files:
        raise ValueError(
            f"No FillDB performance logs were found at: {input_path}\n"
            "Expected a raw FillDBPerf.log (with optional .log_0, .log_1 rollover "
            "files), a folder containing them, or an analyzed FillDB CSV."
        )

    ordered = order_log_files(files)
    if len(ordered) > 1:
        _log(log, f"Combining {len(ordered)} FillDB log files in chronological order:")
        for index, f in enumerate(ordered, start=1):
            _log(log, f"  {index}. {f.name}")

    dest_csv = Path(dest_csv) if dest_csv is not None else _default_csv_dest(ordered)

    combined: Path | None = None
    try:
        if len(ordered) == 1:
            source = ordered[0]
        else:
            combined = dest_csv.with_name(dest_csv.stem + "_combined.tmp.log")
            combine_logs(ordered, combined)
            source = combined
        _log(log, "Running MXFillDBPerf.exe...")
        csv_text = run_analyzer(source, exe=exe, timeout=timeout)
    finally:
        if combined is not None and combined.exists():
            try:
                combined.unlink()
            except OSError:
                pass

    dest_csv.write_text(csv_text, encoding="utf-8")
    _log(log, f"FillDB analysis CSV written: {dest_csv}")
    return dest_csv


# ---------------------------------------------------------------------------
# Window detection (no exe run)
# ---------------------------------------------------------------------------


def detect_window_from_logs(
    target: Path | str,
) -> tuple[datetime | None, datetime | None]:
    """Return (start, end) naive datetimes for a raw FillDB log or folder,
    read from the first/last lines of the chronologically ordered set.

    Cheap by design: only the head of the first file and the tail of the last
    file are read, so this stays fast even for hundreds-of-MB captures.
    """
    files = discover_log_set(target)
    if not files:
        return None, None
    ordered = order_log_files(files)
    start = _first_timestamp(ordered[0])
    end = _last_timestamp(ordered[-1])
    return _naive(start), _naive(end)
