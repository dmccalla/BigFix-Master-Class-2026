#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
run_diagnostics.py -- Master Class Diagnostics Workbench engine.

Runs the three analysis modules from a JSON config written by the desktop UI
and collects their outputs under one run folder:

  - Client Performance Analysis   (Get/get_loop_health.py)
  - Perfmon Infrastructure Analysis    (Get/get_perfmon_charts.py)
  - FillDB Performance Analysis        (Get/get_filldb_performance.py)

Each module writes its own Mini Report, Infographic, and Excel outputs. There
is no combined report.

Usage:
    python run_diagnostics.py --config <config.json> --yes

Config keys:
    run_name        Optional label used for the run folder and file prefix.
    output_folder   Where the run folder is created (default: Documents).
    data_root       Optional folder searched for module inputs.
    modules         List of module keys to run, in order.
    inputs          {module key: {field key: value}}.
    manual_inputs   {module key: {field key: path}} for inputs the user chose
                    by hand. These are never replaced by discovery.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import platform
import re
import socket
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = Path(__file__).resolve().parent
GET_DIR = PROJECT_ROOT / "Get"
INJECT_DIR = PROJECT_ROOT / "Inject"
TEMPLATES_DIR = PROJECT_ROOT / "Templates"
for folder in (PROJECT_ROOT, APP_DIR, GET_DIR):
    if folder.exists() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from Lib.Core.besapi_capture import sample_capture_lines
from Lib.Core.input_utils import (
    DEFAULT_WORK_DIR,
    clean_user_path,
    resolve_existing_file,
    resolve_existing_folder,
)
from Lib.Core.performance_diagnostics import (
    PerformanceRecorder,
    process_resource_metrics,
)
from Lib.Core.subprocess_window import hidden_subprocess_kwargs

_SUBPROCESS_KWARGS = hidden_subprocess_kwargs()

APP_TITLE = "Master Class Diagnostics Workbench"
STYLE_TEMPLATE_NAME = "Diagnostics_Style_Template.docx"

# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------


class RunLog:
    """
    Accumulates a structured run log that is both printed to the console
    and written to a .log file in the run folder at the end of the run.
    """

    SEP = "=" * 56
    SEP2 = "-" * 56
    MODULE_SEP = "=" * 72

    def __init__(self, diagnostics: PerformanceRecorder | None = None):
        self._lines: list[str] = []
        self._started: datetime = datetime.now()
        self._module_total = 0
        self._module_index = 0
        self.diagnostics = diagnostics

    def _emit(self, line: str) -> None:
        """Print to console and store for file output."""
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        console_line = str(line).encode(encoding, errors="replace").decode(encoding)
        print(console_line, flush=True)
        self._lines.append(line)

    def header(self, title: str) -> None:
        self._emit("")
        self._emit(self.SEP)
        self._emit(f"   {title}")
        self._emit(self.SEP)
        self._emit(f"   Started   : {self._started.strftime('%Y-%m-%d %H:%M:%S')}")
        self._emit(f"   Host      : {socket.gethostname()}")
        self._emit(f"   Platform  : {platform.system()} {platform.release()}")
        self._emit(f"   Python    : {sys.version.split()[0]}")
        self._emit(self.SEP)
        self._emit("")

    def section(self, title: str) -> None:
        if title.startswith("Step:"):
            self.module_section(title)
            return
        self._emit("")
        self._emit(self.SEP2)
        self._emit(f"   {title}")
        self._emit(self.SEP2)

    def set_module_total(self, total: int) -> None:
        self._module_total = max(0, int(total or 0))
        self._module_index = 0

    def module_section(self, title: str) -> None:
        self._module_index += 1
        module_name = title.removeprefix("Step:").strip() or title
        if self._module_total:
            progress = f"MODULE {self._module_index:02d} OF {self._module_total:02d}"
        else:
            progress = f"MODULE {self._module_index:02d}"
        self._emit("")
        self._emit(self.MODULE_SEP)
        self._emit(f"   {progress}")
        self._emit(f"   Step: {module_name}")
        self._emit(self.MODULE_SEP)

    def info(self, label: str, value: Any = "") -> None:
        if value != "":
            self._emit(f"   {label:<20}: {value}")
        else:
            self._emit(f"   {label}")

    def command(self, script_name: str, args: list[str]) -> None:
        self._emit(f"   [RUN] {script_name}")
        command_rows = _command_argument_rows(args)
        if command_rows:
            self._emit("     Parameters:")
            for label, value in command_rows:
                self._emit(f"       {label:<24}: {value}")

    def child_output(self, line: str) -> None:
        if line:
            self._emit(f"     {line}")

    def warn(self, message: str) -> None:
        self._emit(f"   [WARNING] {message}")

    def warning(self, message: str) -> None:
        """Compatibility alias for call sites that use logging-style naming."""
        self.warn(message)

    def error(self, message: str) -> None:
        self._emit(f"   [ERROR]   {message}")

    def ok(self, message: str) -> None:
        self._emit(f"   [OK]      {message}")

    def blank(self) -> None:
        self._emit("")

    def inputs(self, label: str, summary_rows: list[tuple[str, str]]) -> None:
        """Log a module's input summary as its own separated block."""
        self._emit("")
        self._emit(f"   [{label}]")
        self._emit("   " + "-" * 40)
        for k, v in summary_rows:
            self._emit(f"     {k:<16}: {v}")

    def footer(self, run_folder: Path | None, elapsed: float) -> None:
        self._emit("")
        self._emit(self.SEP)
        self._emit("   Run complete")
        self._emit(self.SEP)
        self._emit(f"   Finished  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        self._emit(f"   Elapsed   : {elapsed:.1f}s")
        if run_folder:
            self._emit(f"   Run folder: {run_folder}")
        self._emit(self.SEP)
        self._emit("")

    def write(self, log_path: Path) -> None:
        """Write accumulated log to file."""
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("\n".join(self._lines) + "\n", encoding="utf-8")
            print(f"   Run log   : {log_path}", flush=True)
        except Exception as exc:
            print(f"   [WARNING] Could not write run log: {exc}", flush=True)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


@dataclass
class InputField:
    """
    Declares one input that a module needs.

    key         Key used in the inputs dict.
    kind        One of: file | file_optional | folder_optional | int |
                int_detected | bool | datetime_optional
    label       Human-readable label shown to the user.
    patterns    Discovery globs or folder names this field is matched by,
                for fields resolved outside Module.file_patterns (the loop
                ancillaries). The UI's LOOKS FOR column renders the same list.
    extensions  Allowed file extensions for file fields (e.g. {'.blg'}).
    default     Default value for 'int' fields.
    min_val     Minimum value for 'int' and 'int_detected' fields.
    max_val     Maximum value for 'int' fields.
    """

    key: str
    kind: str
    label: str
    patterns: tuple = ()
    extensions: set | None = None
    default: Any = None
    min_val: int = 0
    max_val: int = 999999


@dataclass
class Module:
    """
    Self-contained description of one analysis module.

    key           Unique identifier (no spaces).
    label         Display name shown in the UI.
    inputs_schema list[InputField]: declarative description of every input.
    run           callable(inputs, style_template, ts, log) -> None
    summary       callable(inputs) -> list[tuple[str, str]]
    done          callable(inputs, ts) -> list[str]
    pre_collect   Optional callable(inputs_so_far) -> dict of extra keys.
                  Used for hardware detection from a BLG (runs relog.exe).
    """

    key: str
    label: str
    inputs_schema: list[InputField]
    run: Callable[[dict, Path | None, str, RunLog | None], None]
    summary: Callable[[dict], list[tuple[str, str]]]
    done: Callable[[dict, str], list[str]]
    pre_collect: Callable[[dict], dict] | None = None
    note: str | None = None
    windows_only: bool = False
    outputs: str = ""
    file_pattern: str | None = None
    # file_patterns lists every glob the primary-input discovery tries, in
    # order. Empty means [file_pattern]. The UI renders this same list in the
    # LOOKS FOR column, so discovery and the display can never drift apart.
    file_patterns: list = field(default_factory=list)
    file_key: str | None = None
    discovery_subpaths: list = field(default_factory=list)
    recursive_discovery: bool = False
    module_subfolder: str = ""


@dataclass
class SourceValidation:
    ok: bool
    reason: str = ""
    details: str = ""


# ---------------------------------------------------------------------------
# Input helpers
# ---------------------------------------------------------------------------


def validate_loop_workbook(path: Path) -> SourceValidation:
    """Reject obvious non-Basic Client Performance Counters exports."""
    if "advanced" in path.name.casefold():
        return SourceValidation(
            False,
            (
                "Client Performance Analysis requires the "
                "'Client Performance Counters - Basic' Excel/CSV export. "
                "The Advanced export has extra data and is not supported."
            ),
        )
    suffix = path.suffix.lower()
    first_line = ""
    if suffix == ".csv":
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                first_line = handle.readline().rstrip("\r\n")
        except OSError:
            first_line = ""
    elif suffix == ".xml":
        sampled = sample_capture_lines(path, 1)
        first_line = sampled[0] if sampled else ""
    if first_line:
        header = first_line.casefold()
        if (
            "result" in header
            and "occurrences" in header
            and "maximum" not in header
            and "average" not in header
        ):
            return SourceValidation(
                False,
                (
                    "Client Performance Analysis requires the client loop "
                    "counter CSV or XML capture, not the Top 10 evaluation results."
                ),
            )
    return SourceValidation(True)


def _source_validation_message(result: SourceValidation) -> str:
    message = result.reason
    if result.details:
        message = f"{message} {result.details}"
    return message


def parse_config_bool(value: object | None, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in (None, ""):
        return default
    if isinstance(value, int):
        if value in (0, 1):
            return bool(value)
        raise ValueError(f"Expected boolean config value, got integer {value}.")
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "yes", "y", "1"}:
            return True
        if normalized in {"false", "no", "n", "0"}:
            return False
    raise ValueError(f"Expected boolean config value, got {value!r}.")


def _parse_optional_datetime(value: object | None, label: str) -> str:
    formatted = clean_user_path(value)
    if not formatted:
        return ""
    for fmt in (
        "%m-%d-%Y %H:%M",
        "%m-%d-%y %H:%M",
        "%m/%d/%Y %H:%M",
        "%m/%d/%y %H:%M",
        "%Y-%m-%d %H:%M",
        "%m-%d-%Y %H:%M:%S",
        "%m-%d-%y %H:%M:%S",
        "%m/%d/%Y %H:%M:%S",
        "%m/%d/%y %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%m-%d-%Y",
        "%m-%d-%y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%d",
    ):
        try:
            parsed = datetime.strptime(formatted, fmt)
            if "%H" not in fmt:
                return parsed.strftime("%m-%d-%Y")
            if "%S" in fmt:
                return parsed.strftime("%m-%d-%Y %H:%M:%S")
            return parsed.strftime("%m-%d-%Y %H:%M")
        except ValueError:
            pass
    raise ValueError(f"{label} must be a date/time like 05-01-2026 13:45.")


def _validate_input_file(mod: Module, input_field: InputField, path: Path) -> None:
    if mod.key == "loop" and input_field.key == mod.file_key:
        loop_validation = validate_loop_workbook(path)
        if not loop_validation.ok:
            raise ValueError(_source_validation_message(loop_validation))


def _resolve_input_value_from_config(
    mod: Module,
    input_field: InputField,
    raw: object | None,
    inputs: dict,
    pre_collect_cache: dict | None,
) -> tuple[object, dict | None]:
    kind = input_field.kind
    if kind == "file":
        value = resolve_existing_file(raw, input_field.label, input_field.extensions)
        _validate_input_file(mod, input_field, value)

    elif kind == "file_optional":
        value = (
            resolve_existing_file(raw, input_field.label, input_field.extensions)
            if raw
            else None
        )
        if value is not None:
            _validate_input_file(mod, input_field, value)

    elif kind == "folder_optional":
        value = resolve_existing_folder(raw, input_field.label) if raw else None

    elif kind == "int":
        value = input_field.default if raw in (None, "") else int(raw)
        if not (input_field.min_val <= value <= input_field.max_val):
            raise ValueError(
                f"{input_field.label} must be between {input_field.min_val} "
                f"and {input_field.max_val}."
            )

    elif kind == "int_detected":
        if raw not in (None, ""):
            value = int(raw)
        elif mod.pre_collect is not None:
            if pre_collect_cache is None:
                pre_collect_cache = mod.pre_collect(inputs)
            value = pre_collect_cache.get(f"_detected_{input_field.key}", 0)
        else:
            value = 0
        if value < input_field.min_val:
            raise ValueError(
                f"{input_field.label} must be at least {input_field.min_val}."
            )

    elif kind == "bool":
        value = parse_config_bool(raw, default=False)

    elif kind == "datetime_optional":
        value = _parse_optional_datetime(raw, input_field.label)

    else:
        raise ValueError(f"Unknown InputField kind '{kind}' for key '{input_field.key}'")

    return value, pre_collect_cache


def collect_inputs_from_config(mod: Module, raw_inputs: dict) -> dict:
    """Validate and normalize module inputs supplied by the UI/config file."""
    inputs: dict = {}
    _pre_collect_cache: dict | None = None

    for input_field in mod.inputs_schema:
        raw = raw_inputs.get(input_field.key)
        value, _pre_collect_cache = _resolve_input_value_from_config(
            mod, input_field, raw, inputs, _pre_collect_cache
        )
        inputs[input_field.key] = value

    return inputs


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def discover_module_input(folder: Path, mod: Module) -> Path | None:
    """Return the discovered primary input for a module, or None.

    Searches discovery_subpaths (relative to folder) before the root, globs
    each candidate directory in order, and returns the newest match, XML
    captures first.
    """
    if mod.file_key is None or mod.file_pattern is None:
        return None

    primary = next((f for f in mod.inputs_schema if f.key == mod.file_key), None)
    search_dirs = [folder / sp for sp in mod.discovery_subpaths] + [folder]
    file_patterns = mod.file_patterns or [mod.file_pattern]
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        globber = search_dir.rglob if mod.recursive_discovery else search_dir.glob
        matches: list[Path] = []
        for pattern in file_patterns:
            matches.extend(globber(pattern))
        matches = list(dict.fromkeys(matches))
        if primary and primary.extensions:
            matches = [p for p in matches if p.suffix.lower() in primary.extensions]
        # XML captures first, newest within each format. The formatted log is
        # written seconds after the capture so a pure mtime sort would always
        # shadow the XML.
        matches.sort(key=lambda p: (p.suffix.lower() != ".xml", -p.stat().st_mtime))
        if matches:
            for match in matches:
                if mod.key == "loop" and not validate_loop_workbook(match).ok:
                    continue
                return match
            return None
    return None


def scan_input_folder(folder: Path) -> dict[str, Path | None]:
    """Discover the primary input for every module under one data root."""
    return {mod.key: discover_module_input(folder, mod) for mod in MODULES}


_LOOP_EVALUATION_FILE_PATTERNS = (
    "*top10-query-results*.csv",
    "*top10*.csv",
    "*top10*.txt",
    "*top10*.xml",
    "*property-query-results*.csv",
    "*property-query-results*.txt",
    "*evaluation*time*.csv",
    "*evaluation*time*.txt",
    "*evaluation*time*.log",
    "*property*evaluation*.csv",
    "*property*evaluation*.txt",
    "*property*evaluation*.log",
    "*loop*offender*.csv",
    "*loop*offender*.txt",
    "*top*offender*.csv",
    "*top*offender*.txt",
)

_LOOP_UDP_NOTIFICATION_FILE_PATTERNS = (
    "*udp-notification*.csv",
    "*udp_notification*.csv",
    "*udp-notification*.xml",
    "*udp_notification*.xml",
    "*udp-ping*.csv",
    "*udp_ping*.csv",
    "*receiving*udp*.csv",
)

# The folder name _find_deployment_info_folder matches. LOOP_SCHEMA's
# deployment_info_folder field references it so LOOKS FOR shows the same name.
_DEPLOYMENT_INFO_DIR_NAME = "Deployment_Information"


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


def _path_contains(root: Path, path: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except (ValueError, OSError):
        return False


def _loop_context_roots(data_root: Path | None, loop_input: Path | None) -> list[Path]:
    roots: list[Path] = []
    if loop_input is not None:
        current = loop_input.resolve(strict=False).parent
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
        while True:
            roots.append(current)
            if current == stop:
                break
            parent = current.parent
            if parent == current:
                break
            current = parent
    if data_root is not None:
        roots.append(data_root)
        roots.append(data_root / "Results")

    scoped: list[Path] = []
    for root in roots:
        scoped.extend(
            [
                root,
                root / "Client_Loop",
                root / "Results" / "Client_Loop",
                root / _DEPLOYMENT_INFO_DIR_NAME,
                root / "Results" / _DEPLOYMENT_INFO_DIR_NAME,
            ]
        )
    return _unique_existing_dirs(scoped)


def _loop_optional_path_in_scope(
    data_root: Path | None, loop_input: Path | None, path: Path
) -> bool:
    return any(
        _path_contains(root, path) for root in _loop_context_roots(data_root, loop_input)
    )


def _looks_like_loop_evaluation_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".txt", ".log", ".xml"}:
        return False

    if suffix == ".xml":
        lines = sample_capture_lines(path, 50)
        if not lines:
            return False
    else:
        try:
            with path.open(encoding="utf-8", errors="replace") as handle:
                lines = [line.rstrip("\r\n") for line in itertools.islice(handle, 50)]
        except OSError:
            return False

    header = "\n".join(lines[:3]).casefold()
    if "result" in header and (
        "clientprocessingseconds" in header
        or "clientevaluationseconds" in header
        or "totalclientprocessingseconds" in header
        or "totalclientevaluationseconds" in header
        or "occurrences" in header
    ):
        return True

    raw_timing = re.compile(
        r'^\s*(?:"?\d+"?[,\s]+)?'
        r'(?:"?\d+(?:\.\d+)?%"?[,\s]+)?'
        r'"?\d+(?:\.\d+)?:\s*.+\.\d+:.+',
        re.IGNORECASE,
    )
    return any(raw_timing.match(line) for line in lines)


def _find_loop_evaluation_file(search_dirs: list[Path]) -> Path | None:
    candidates: list[Path] = []
    for search_dir in search_dirs:
        for pattern in _LOOP_EVALUATION_FILE_PATTERNS:
            try:
                candidates.extend(p for p in search_dir.glob(pattern) if p.is_file())
            except OSError:
                continue

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(
        key=lambda p: (
            not p.stem.lower().endswith("-detail"),
            -p.stat().st_mtime,
            p.name.lower(),
        )
    )
    for candidate in candidates:
        if _looks_like_loop_evaluation_file(candidate):
            return candidate.resolve()
    return None


def _looks_like_udp_notification_file(path: Path) -> bool:
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".xml"}:
        return False
    if suffix == ".xml":
        sampled = sample_capture_lines(path, 1)
        if not sampled:
            return False
        # The BESAPI capture has no header row. Its answers are the data rows.
        fields = [field.strip() for field in sampled[0].split(",")]
        if len(fields) >= 4 and re.match(
            r"^(?:true|false|yes|no|not reported)\b", fields[-1], re.IGNORECASE
        ):
            return True
        header_row = next(csv.reader([sampled[0]]), [])
        columns = {str(column).strip().casefold() for column in header_row}
    else:
        try:
            with path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                columns = {
                    str(column).strip().casefold() for column in reader.fieldnames or []
                }
        except OSError:
            return False

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
        and any(column.endswith("receiving udp pings") for column in columns)
    )


def _find_udp_notification_file(search_dirs: list[Path]) -> Path | None:
    candidates: list[Path] = []
    for search_dir in search_dirs:
        for pattern in _LOOP_UDP_NOTIFICATION_FILE_PATTERNS:
            try:
                candidates.extend(p for p in search_dir.glob(pattern) if p.is_file())
            except OSError:
                continue

    candidates = list(dict.fromkeys(candidates))
    candidates.sort(key=lambda p: (-p.stat().st_mtime, p.name.lower()))
    for candidate in candidates:
        if _looks_like_udp_notification_file(candidate):
            return candidate.resolve()
    return None


def _find_deployment_info_folder(search_dirs: list[Path]) -> Path | None:
    for search_dir in search_dirs:
        candidates = [
            search_dir,
            search_dir / _DEPLOYMENT_INFO_DIR_NAME,
            search_dir / "Results" / _DEPLOYMENT_INFO_DIR_NAME,
        ]
        for candidate in candidates:
            if candidate.is_dir() and candidate.name == _DEPLOYMENT_INFO_DIR_NAME:
                return candidate.resolve()
    return None


def discover_loop_ancillary_inputs(
    data_root: Path | None, loop_input: Path | None
) -> dict[str, Path | None]:
    """Discover optional inputs that enrich the Client Loop module."""
    search_dirs = _loop_context_roots(data_root, loop_input)
    return {
        "deployment_info_folder": _find_deployment_info_folder(search_dirs),
        "top_offenders_file": _find_loop_evaluation_file(search_dirs),
        "udp_notifications_file": _find_udp_notification_file(search_dirs),
    }


# ---------------------------------------------------------------------------
# Child processes
# ---------------------------------------------------------------------------


def find_script(filename: str) -> Path:
    for folder in (GET_DIR, INJECT_DIR, APP_DIR):
        candidate = folder / filename
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"{filename} was not found under Get, Inject, or App.")


def run_python(script: Path, args: list[str], log: RunLog | None = None) -> int:
    """Stream a Python child's output, raising if it exits unsuccessfully."""
    python_exe = sys.executable
    if sys.platform == "win32":
        pythonw = Path(sys.executable).parent / "pythonw.exe"
        if pythonw.exists():
            python_exe = str(pythonw)
    cmd = [python_exe, str(script)] + args
    if log:
        log.command(script.name, args)
    else:
        print(f"\n  [RUN] {script.name}")
        for label, value in _command_argument_rows(args):
            print(f"          {label:<22}: {value}")
        print()

    # stdin=DEVNULL prevents child scripts from blocking on interactive prompts.
    started = time.perf_counter()
    returncode: int | None = None
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_SUBPROCESS_KWARGS,
        )
        if process.stdout is None:
            raise RuntimeError(f"{script.name} started without a readable stdout pipe.")
        pending_child_line: str | None = None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\r\n")
            pending_child_line = _emit_normalized_child_output(
                line, pending_child_line, log
            )
        _flush_child_output(pending_child_line, log)
        returncode = process.wait()
    finally:
        if log is not None and log.diagnostics is not None:
            log.diagnostics.record(
                "Child script",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                detail=script.name,
                return_code=returncode,
            )

    if returncode != 0:
        raise RuntimeError(f"{script.name} exited with code {returncode}")
    return returncode


def _command_argument_rows(args: list[str]) -> list[tuple[str, str]]:
    """Render CLI arguments as readable key/value rows for the run log."""
    rows: list[tuple[str, str]] = []
    i = 0
    while i < len(args):
        token = str(args[i])
        if token.startswith("--"):
            if "=" in token:
                label, value = token.split("=", 1)
                rows.append((label, value))
                i += 1
            elif i + 1 < len(args) and not str(args[i + 1]).startswith("--"):
                rows.append((token, str(args[i + 1])))
                i += 2
            else:
                rows.append((token, "Yes"))
                i += 1
        else:
            rows.append(("Argument", token))
            i += 1
    return rows


def _is_child_output_rule(line: str) -> bool:
    """Return True when a child script prints a decorative separator line."""
    stripped = line.strip()
    return (
        len(stripped) >= 8 and len(set(stripped)) == 1 and stripped[0] in {"=", "-", "_"}
    )


def _is_standalone_child_heading(line: str) -> bool:
    """Identify child-script title lines that are followed by separators."""
    stripped = line.strip()
    if not stripped or line != stripped or len(stripped) > 100 or ":" in stripped:
        return False
    title_words = ("Analyzer", "Generator", "Injector", "Parser", "Analysis")
    return stripped.startswith("BigFix ") or stripped.endswith(title_words)


def _format_child_output(line: str) -> str:
    """Convert banner-style child output into plain nested log details."""
    stripped = line.strip()
    wrapped_heading = re.match(r"^[=\-]{3,}\s*(.+?)\s*[=\-]{3,}$", stripped)
    if wrapped_heading:
        return wrapped_heading.group(1).strip()
    return line


def _write_child_output(line: str, log: RunLog | None) -> None:
    formatted = _format_child_output(line)
    if not formatted.strip():
        return
    if log:
        log.child_output(formatted)
    else:
        print(f"     {formatted}")


def _emit_normalized_child_output(
    line: str, pending_line: str | None, log: RunLog | None
) -> str | None:
    """Drop decorative child banners so the run log keeps one structure."""
    if not line.strip():
        return pending_line

    if _is_child_output_rule(line):
        if pending_line and not _is_standalone_child_heading(pending_line):
            _write_child_output(pending_line, log)
        return None

    if pending_line is not None:
        _write_child_output(pending_line, log)
    return line


def _flush_child_output(pending_line: str | None, log: RunLog | None) -> None:
    if pending_line is not None:
        _write_child_output(pending_line, log)


def _warn(message: str, log: RunLog | None = None) -> None:
    if log:
        log.warning(message)
    else:
        print(f"  WARNING: {message}")


def _print_step_header(title: str, log: RunLog | None = None) -> None:
    if log:
        log.section(title)
    else:
        print("\n" + "=" * 56)
        print(f"   {title}")
        print("=" * 56)


def _rename_glob(
    folder: Path, pattern: str, new_name: str, log: RunLog | None = None
) -> Path | None:
    """Rename the newest file matching pattern to new_name; return the new path."""
    candidates = sorted(
        folder.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if not candidates:
        return None
    old = candidates[0]
    new = old.parent / new_name
    if old != new:
        try:
            old.rename(new)
        except OSError as exc:
            if log:
                log.warning(f"Could not rename {old.name} to {new_name}: {exc}")
            return old
    return new


def _require_output_files(*paths: Path) -> None:
    """Fail the run when a required artifact is missing or empty."""
    for path in paths:
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"Required output is missing or empty: {path}")


def _require_perfmon_outputs(out_xlsx: Path) -> Path:
    _require_output_files(out_xlsx)
    chart_folder = out_xlsx.parent / (out_xlsx.stem + "_Charts")
    charts = sorted(chart_folder.glob("*.png"))
    if not charts:
        raise RuntimeError(f"Required PNG graphs are missing or empty: {chart_folder}")
    _require_output_files(*charts)
    return chart_folder


# ---------------------------------------------------------------------------
# Hardware detection from BLG (pre_collect for the Perfmon module)
# ---------------------------------------------------------------------------


def relog_query_lines(blg_path: Path, timeout: int = 600) -> list[str]:
    """Run `relog.exe <blg> -q` once and return its output lines.

    The output carries both the capture window header (Begin/End) and the
    full counter list, so one invocation feeds hardware detection and window
    detection together. relog parses the whole BLG for this (about 5 seconds
    per 250 MB), so callers that need both must not run it twice.
    """
    result = subprocess.run(
        ["relog.exe", str(blg_path), "-q"],
        capture_output=True,
        text=True,
        timeout=timeout,
        stdin=subprocess.DEVNULL,
        **_SUBPROCESS_KWARGS,
    )
    return result.stdout.splitlines() + result.stderr.splitlines()


def detect_hardware_from_blg(
    blg_path: Path, query_lines: list[str] | None = None
) -> tuple[int, int, int]:
    """Returns (logical_processors, physical_disks, volume_count); 0 if undetectable.

    physical_disks counts PhysicalDisk instances. volume_count counts the
    distinct drive letters across them for diagnostics only.
    """
    try:
        lines = query_lines if query_lines is not None else relog_query_lines(blg_path)
        procs, disks, volumes = set(), set(), set()
        for line in lines:
            for m in re.finditer(
                r"\\Processor(?:\s+Information)?\(([^)]+)\)\\",
                line,
                flags=re.IGNORECASE,
            ):
                inst = m.group(1).strip()
                if inst.casefold() == "_total" or inst.casefold().endswith(",_total"):
                    continue
                procs.add(inst)
            m = re.search(r"\\PhysicalDisk\((?!_Total)([^)]+)\)\\", line, re.IGNORECASE)
            if m:
                inst = m.group(1)
                disks.add(inst)
                for letter in re.findall(r"[A-Za-z]:", inst):
                    volumes.add(letter.upper())
        return len(procs), len(disks), len(volumes)
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        print(f"  WARNING: Could not detect hardware from BLG: {exc}")
        return 0, 0, 0


def detect_perfmon_window(query_lines: list[str]) -> tuple[str, str]:
    """Return the (begin, end) capture window from relog -q output, or blanks."""
    begin = end = ""
    for line in query_lines:
        stripped = line.strip()
        if stripped.lower().startswith("begin:"):
            begin = stripped.split(":", 1)[1].strip()
        elif stripped.lower().startswith("end:"):
            end = stripped.split(":", 1)[1].strip()
    return begin, end


def perfmon_pre_collect(inputs: dict) -> dict:
    """Called after blg_path is known; detects and displays hardware values."""
    print("\n  Detecting hardware from BLG...")
    procs, disks, volumes = detect_hardware_from_blg(inputs["blg_path"])

    if procs > 0:
        print(f"  Logical processors : {procs} (detected)")
    else:
        print("  Logical processors : Not detected")

    if disks > 0:
        vol = f"  ({volumes} volume{'s' if volumes != 1 else ''})" if volumes else ""
        print(f"  Physical disks     : {disks} (detected){vol}")
    else:
        print("  Physical disks     : Not detected")

    print()
    return {
        "_detected_logical_processors": procs,
        "_detected_physical_disks": disks,
        "_detected_volume_count": volumes,
    }


# ---------------------------------------------------------------------------
# Style template for the Word Mini Reports
# ---------------------------------------------------------------------------


def resolve_style_template(candidate_text: object | None = None) -> Path | None:
    """Return the Word style template the Mini Reports clone their styles from.

    An explicit path wins. Otherwise Templates/Diagnostics_Style_Template.docx
    is used when present. None means the module falls back to a blank
    document.
    """
    configured = clean_user_path(candidate_text)
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file() and candidate.suffix.lower() == ".docx":
            return candidate.resolve()
    default = TEMPLATES_DIR / STYLE_TEMPLATE_NAME
    return default.resolve() if default.is_file() else None


# ---------------------------------------------------------------------------
# Module 1: Perfmon Infrastructure Analysis
# ---------------------------------------------------------------------------

PERFMON_SCHEMA: list[InputField] = [
    InputField(
        key="blg_path",
        kind="file",
        label="Capture 1 Perfmon .blg File",
        extensions={".blg"},
    ),
    InputField(
        key="logical_processors",
        kind="int_detected",
        label="Capture 1 Logical Processors",
        min_val=0,
    ),
    InputField(
        key="physical_disks",
        kind="int_detected",
        label="Capture 1 Physical Disks",
        min_val=0,
    ),
    InputField(
        key="physical_memory_gb",
        kind="int",
        label="Capture 1 Physical Memory (GB)",
        default=0,
        min_val=0,
    ),
    InputField(
        key="is_vm",
        kind="bool",
        label="Capture 1 Virtual Machine?",
    ),
    InputField(
        key="capture2_blg_path",
        kind="file_optional",
        label="Capture 2 Perfmon .blg File",
        extensions={".blg"},
    ),
    InputField(
        key="capture2_logical_processors",
        kind="int_detected",
        label="Capture 2 Logical Processors",
        min_val=0,
    ),
    InputField(
        key="capture2_physical_disks",
        kind="int_detected",
        label="Capture 2 Physical Disks",
        min_val=0,
    ),
    InputField(
        key="capture2_physical_memory_gb",
        kind="int",
        label="Capture 2 Physical Memory (GB)",
        default=0,
        min_val=0,
    ),
    InputField(
        key="capture2_is_vm",
        kind="bool",
        label="Capture 2 Virtual Machine?",
    ),
    InputField(
        key="collection_start",
        kind="datetime_optional",
        label="Collection Start Date/Time",
    ),
    InputField(
        key="collection_end",
        kind="datetime_optional",
        label="Collection End Date/Time",
    ),
]


def _write_perfmon_mini_report(
    chart_folder: Path,
    capture2_chart_folder: Path | None,
    style_template: Path | None,
    output_path: Path,
    log: RunLog | None = None,
) -> bool:
    """Build the standalone PerfMon Mini Report from the chart folder(s)."""
    from tempfile import TemporaryDirectory

    from Lib.Themes.word_stub_utils import (
        add_stub_front_matter,
        apply_standalone_narrow_margins,
        create_stub_document_from_template,
    )

    with TemporaryDirectory(prefix="perfmon_mini_") as temp_dir:
        temp_folder = Path(temp_dir)
        base_path = temp_folder / "PerfMon_Mini_Report_Base.docx"
        primary_path = (
            temp_folder / "PerfMon_Mini_Report_Primary.docx"
            if capture2_chart_folder
            else output_path
        )
        if style_template is not None:
            document = create_stub_document_from_template(style_template)
        else:
            from docx import Document

            document = apply_standalone_narrow_margins(Document())
        add_stub_front_matter(document, "Perfmon Infrastructure Analysis")
        document.save(str(base_path))

        run_python(
            find_script("inject_perfmon_charts.py"),
            [
                "--chart-folder",
                str(chart_folder),
                "--template-path",
                str(base_path),
                "--output-path",
                str(primary_path),
                "--append-only",
                "--include-automated-findings",
                "--section-title",
                "PerfMon Capture 1",
            ],
            log,
        )
        _require_output_files(primary_path)

        if capture2_chart_folder:
            run_python(
                find_script("inject_perfmon_charts.py"),
                [
                    "--chart-folder",
                    str(capture2_chart_folder),
                    "--template-path",
                    str(primary_path),
                    "--output-path",
                    str(output_path),
                    "--append-only",
                    "--include-automated-findings",
                    "--section-title",
                    "PerfMon Capture 2",
                ],
                log,
            )
            _require_output_files(output_path)

    if log:
        log.info("PerfMon Mini Report", str(output_path))
    return True


def _perfmon_chart_args(
    blg_path: Path,
    out_xlsx: Path,
    *,
    rolling_window: int,
    processors: int = 0,
    disks: int = 0,
    memory_gb: int = 0,
    is_vm: bool = False,
) -> list[str]:
    args = [
        "--input",
        str(blg_path),
        "--output",
        str(out_xlsx),
        "--rolling-window",
        str(rolling_window),
        "--skip-docx",
    ]
    if processors:
        args += ["--processors", str(processors)]
    if disks:
        args += ["--disks", str(disks)]
    if memory_gb:
        args += ["--memory-gb", str(memory_gb)]
    if is_vm:
        args += ["--virtual-machine"]
    return args


def run_perfmon_pipeline(
    inputs: dict,
    style_template: Path | None,
    ts: str,
    log: RunLog | None = None,
) -> None:
    _print_step_header("Step: Perfmon Infrastructure Analysis", log)
    capture2_blg_path = inputs.get("capture2_blg_path")
    if log:
        log.info("Capture 1 BLG", str(inputs["blg_path"]))
        if capture2_blg_path:
            log.info("Capture 2 BLG", str(capture2_blg_path))
        log.info("Output folder", str(inputs["_out_folder"]))
        log.info(
            "Note",
            "Parsing and analyzing the BLG file may take several minutes for large files.",
        )
        log.blank()
    sys.stdout.flush()

    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    out_xlsx = inputs["_out_folder"] / f"{prefix}_Perfmon.xlsx"
    args = _perfmon_chart_args(
        inputs["blg_path"],
        out_xlsx,
        rolling_window=10,
        processors=inputs.get("logical_processors") or 0,
        disks=inputs.get("physical_disks") or 0,
        memory_gb=inputs.get("physical_memory_gb") or 0,
        is_vm=bool(inputs.get("is_vm")),
    )
    run_python(find_script("get_perfmon_charts.py"), args, log)

    chart_folder = _require_perfmon_outputs(out_xlsx)
    if log:
        log.info("Output Excel", str(out_xlsx))
        log.info("Graph folder", str(chart_folder))

    capture2_chart_folder: Path | None = None
    if capture2_blg_path:
        capture2_out_xlsx = inputs["_out_folder"] / f"{prefix}_Perfmon_Capture_2.xlsx"
        capture2_args = _perfmon_chart_args(
            capture2_blg_path,
            capture2_out_xlsx,
            rolling_window=10,
            processors=inputs.get("capture2_logical_processors") or 0,
            disks=inputs.get("capture2_physical_disks") or 0,
            memory_gb=inputs.get("capture2_physical_memory_gb") or 0,
            is_vm=bool(inputs.get("capture2_is_vm")),
        )
        run_python(find_script("get_perfmon_charts.py"), capture2_args, log)
        capture2_chart_folder = _require_perfmon_outputs(capture2_out_xlsx)
        if log:
            log.info("Capture 2 Excel", str(capture2_out_xlsx))
            log.info("Capture 2 graphs", str(capture2_chart_folder))

    mini_report_path = inputs["_out_folder"] / f"{prefix}_Perfmon_Mini_Report.docx"
    _write_perfmon_mini_report(
        chart_folder, capture2_chart_folder, style_template, mini_report_path, log
    )


def perfmon_summary(inputs: dict) -> list[tuple[str, str]]:
    p = inputs
    capture2_blg = p.get("capture2_blg_path")
    rows = [
        ("Capture 1 BLG", str(p["blg_path"])),
        ("Output dir", str(p["_out_folder"])),
        (
            "Capture 1 CPUs",
            str(p["logical_processors"]) if p["logical_processors"] else "auto-detect",
        ),
        (
            "Capture 1 Disks",
            str(p["physical_disks"]) if p["physical_disks"] else "auto-detect",
        ),
        (
            "Capture 1 Memory",
            f"{p['physical_memory_gb']} GB"
            if p["physical_memory_gb"]
            else "not specified",
        ),
        ("Capture 1 VM", "Yes" if p["is_vm"] else "No"),
    ]
    if capture2_blg:
        rows.extend(
            [
                ("Capture 2 BLG", str(capture2_blg)),
                (
                    "Capture 2 CPUs",
                    str(p.get("capture2_logical_processors") or "auto-detect"),
                ),
                (
                    "Capture 2 Disks",
                    str(p.get("capture2_physical_disks") or "auto-detect"),
                ),
                (
                    "Capture 2 Memory",
                    f"{p.get('capture2_physical_memory_gb')} GB"
                    if p.get("capture2_physical_memory_gb")
                    else "not specified",
                ),
                ("Capture 2 VM", "Yes" if p.get("capture2_is_vm") else "No"),
            ]
        )
    else:
        rows.append(("Capture 2 BLG", "not supplied"))
    return rows


def perfmon_done(inputs: dict, ts: str) -> list[str]:
    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    folder = inputs["_out_folder"]
    lines = [
        f"Perfmon Excel       : {folder / f'{prefix}_Perfmon.xlsx'}",
        f"Perfmon Graphs      : {folder / f'{prefix}_Perfmon_Charts'}",
        f"Perfmon Mini Report : {folder / f'{prefix}_Perfmon_Mini_Report.docx'}",
    ]
    if inputs.get("capture2_blg_path"):
        lines.extend(
            [
                f"Perfmon Capture 2 Excel  : {folder / f'{prefix}_Perfmon_Capture_2.xlsx'}",
                f"Perfmon Capture 2 Graphs : {folder / f'{prefix}_Perfmon_Capture_2_Charts'}",
            ]
        )
    return lines


# ---------------------------------------------------------------------------
# Module 2: Client Performance Analysis
# ---------------------------------------------------------------------------

LOOP_SCHEMA: list[InputField] = [
    InputField(
        key="input_xlsx",
        kind="file",
        label="Loop counter export",
        extensions={".xml", ".xlsx", ".xlsm", ".xls", ".csv"},
    ),
    InputField(
        key="start_date",
        kind="datetime_optional",
        label="Report Start Date",
    ),
    InputField(
        key="end_date",
        kind="datetime_optional",
        label="Report End Date",
    ),
    InputField(
        key="deployment_info_folder",
        kind="folder_optional",
        label="Deployment_Information folder",
        patterns=(_DEPLOYMENT_INFO_DIR_NAME,),
    ),
    InputField(
        key="top_offenders_file",
        kind="file_optional",
        label="Top 10 slowest evaluations",
        patterns=_LOOP_EVALUATION_FILE_PATTERNS,
        extensions={".csv", ".txt", ".log", ".xml"},
    ),
    InputField(
        key="udp_notifications_file",
        kind="file_optional",
        label="UDP notifications",
        patterns=_LOOP_UDP_NOTIFICATION_FILE_PATTERNS,
        extensions={".csv", ".xml"},
    ),
]


def run_loop_pipeline(
    inputs: dict,
    style_template: Path | None,
    ts: str,
    log: RunLog | None = None,
) -> None:
    _print_step_header("Step: Client Performance Analysis", log)

    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    output_dir = inputs["_out_folder"]
    args = [
        "--input-file",
        str(inputs["input_xlsx"]),
        "--output-folder",
        str(output_dir),
    ]
    if inputs.get("start_date"):
        args += ["--report-start-date", inputs["start_date"]]
    if inputs.get("end_date"):
        args += ["--report-end-date", inputs["end_date"]]
    if inputs.get("deployment_info_folder"):
        args += ["--deployment-info-folder", str(inputs["deployment_info_folder"])]
    if inputs.get("top_offenders_file"):
        args += ["--evaluation-times-file", str(inputs["top_offenders_file"])]
    if inputs.get("udp_notifications_file"):
        args += ["--udp-notifications-file", str(inputs["udp_notifications_file"])]
    args += ["--include-automated-findings"]

    run_python(find_script("get_loop_health.py"), args, log)

    _rename_glob(
        output_dir, "Client_Loop_Analysis_*.xlsx", f"{prefix}_Client_Loop.xlsx", log
    )
    _rename_glob(
        output_dir, "Client_Loop_Analysis_*.png", f"{prefix}_Client_Loop.png", log
    )
    _rename_glob(
        output_dir,
        "Client_Loop_Analysis_*.chartdata.json",
        f"{prefix}_Client_Loop.chartdata.json",
        log,
    )
    _rename_glob(
        output_dir, "Client_Loop_Analysis_*.docx", f"{prefix}_Client_Loop.docx", log
    )
    loop_docx = output_dir / f"{prefix}_Client_Loop.docx"
    _require_output_files(
        output_dir / f"{prefix}_Client_Loop.xlsx",
        output_dir / f"{prefix}_Client_Loop.png",
        loop_docx,
    )
    if log:
        log.info("Loop docx", str(loop_docx))


def loop_summary(inputs: dict) -> list[tuple[str, str]]:
    return [
        ("Basic counters export", str(inputs["input_xlsx"])),
        ("Output dir", str(inputs["_out_folder"])),
        ("Start date", inputs["start_date"] or "full range"),
        ("End date", inputs["end_date"] or "full range"),
        (
            "Client Loop contributing factors",
            str(inputs.get("deployment_info_folder") or "auto-detect if available"),
        ),
        (
            "Client evaluation times/offenders",
            str(inputs.get("top_offenders_file") or "not provided"),
        ),
        (
            "UDP notification data",
            str(inputs.get("udp_notifications_file") or "not provided"),
        ),
    ]


def loop_done(inputs: dict, ts: str) -> list[str]:
    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    folder = inputs["_out_folder"]
    outputs = [
        ("Loop Excel", folder / f"{prefix}_Client_Loop.xlsx"),
        ("Loop PNG", folder / f"{prefix}_Client_Loop.png"),
        ("Loop Word", folder / f"{prefix}_Client_Loop.docx"),
    ]
    lines = [f"{label:<11}: {path}" for label, path in outputs if path.exists()]
    return lines or ["Loop outputs were not created. Check the module errors above."]


# ---------------------------------------------------------------------------
# Module 3: FillDB Performance Analysis
# ---------------------------------------------------------------------------

FILLDB_SCHEMA: list[InputField] = [
    InputField(
        key="input_csv",
        kind="file",
        label="FillDB Performance Log or CSV",
        # Accepts a raw FillDB perf log (the analyzer is run automatically;
        # rollover siblings in the same folder are combined in order) or an
        # already-analyzed CSV.
        extensions={".log", ".csv"},
    ),
    InputField(
        key="collection_start",
        kind="datetime_optional",
        label="Collection Start Date/Time",
    ),
    InputField(
        key="collection_end",
        kind="datetime_optional",
        label="Collection End Date/Time",
    ),
]


def run_filldb_pipeline(
    inputs: dict,
    style_template: Path | None,
    ts: str,
    log: RunLog | None = None,
) -> None:
    _print_step_header("Step: FillDB Performance Analysis", log)
    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    output_docx = inputs["_out_folder"] / f"{prefix}_FillDB_Performance.docx"
    output_png = inputs["_out_folder"] / f"{prefix}_FillDB_Performance.png"
    args = [
        "--input",
        str(inputs["input_csv"]),
        "--word-output",
        str(output_docx),
        "--png-output",
        str(output_png),
    ]
    # Explicit blank values keep get_filldb_performance.py out of its
    # interactive prompt path when run under the UI.
    args += ["--collection-start", str(inputs.get("collection_start") or "")]
    args += ["--collection-end", str(inputs.get("collection_end") or "")]
    if style_template:
        args += ["--template", str(style_template)]

    run_python(find_script("get_filldb_performance.py"), args, log)
    _require_output_files(output_docx, output_png)
    if log:
        log.info("FillDB docx", str(output_docx))
        log.info("FillDB PNG", str(output_png))


def filldb_summary(inputs: dict) -> list[tuple[str, str]]:
    return [
        ("Input", str(inputs["input_csv"])),
        ("Output dir", str(inputs["_out_folder"])),
        ("Start", inputs["collection_start"] or "not specified"),
        ("End", inputs["collection_end"] or "not specified"),
    ]


def filldb_done(inputs: dict, ts: str) -> list[str]:
    prefix = inputs.get("_file_prefix", f"Output_{ts}")
    folder = inputs["_out_folder"]
    return [
        f"FillDB docx : {folder / f'{prefix}_FillDB_Performance.docx'}",
        f"FillDB PNG  : {folder / f'{prefix}_FillDB_Performance.png'}",
    ]


# ---------------------------------------------------------------------------
# Module registry
# ---------------------------------------------------------------------------

MODULES: list[Module] = [
    Module(
        key="loop",
        label="Client Performance Analysis",
        inputs_schema=LOOP_SCHEMA,
        run=run_loop_pipeline,
        summary=loop_summary,
        done=loop_done,
        outputs="Mini Report, Infographic, Excel",
        file_pattern="*Basic*",
        # The full discovery list. The UI's LOOKS FOR column renders this
        # same list, so keep it here and nowhere else.
        file_patterns=["Client_Loop_*.xml", "Client_Loop_*.csv", "*Basic*"],
        file_key="input_xlsx",
        discovery_subpaths=[
            "Results/Client_Loop",
            "Client_Loop",
            "Results/Analyses/Agent_Performance_Counters",
            "Analyses/Agent_Performance_Counters",
            "Client_Diagnostics",
        ],
        recursive_discovery=True,
        module_subfolder="Client_Loop",
        note=(
            "Use the Client_Loop_*.csv export or the Client Performance Counters "
            "- Basic Excel/CSV export. The Advanced export includes additional "
            "data and is not supported. The Deployment_Information folder from the "
            "Collect Deployment Information task is required and adds the "
            "Contributing Factors table. FastHashVerify, CPU idle, and client multicore "
            "client settings are included when supplied by the Client Performance Counters export."
        ),
    ),
    Module(
        key="perfmon",
        windows_only=True,
        label="Perfmon Infrastructure Analysis",
        inputs_schema=PERFMON_SCHEMA,
        run=run_perfmon_pipeline,
        summary=perfmon_summary,
        done=perfmon_done,
        pre_collect=perfmon_pre_collect,
        outputs="Mini Report, Infographic, Excel",
        file_pattern="*.blg",
        file_key="blg_path",
        discovery_subpaths=["Perfmon"],
        module_subfolder="Perfmon",
        note=(
            "Processor and disk counts are detected from the .blg file. "
            "Leave those fields blank unless you want to override the detected "
            "values. Physical memory cannot be read from the .blg, so enter it "
            "when known. Parsing a large .blg can take several minutes."
        ),
    ),
    Module(
        key="filldb",
        label="FillDB Performance Analysis",
        inputs_schema=FILLDB_SCHEMA,
        run=run_filldb_pipeline,
        summary=filldb_summary,
        done=filldb_done,
        outputs="Mini Report, Infographic",
        file_pattern="*FillDB*",
        file_key="input_csv",
        # Raw-log locations are searched first so the analyzer always runs on
        # the freshly captured logs. The pre-analyzed CSV is the fallback.
        discovery_subpaths=[
            "Logs/FillDB_Performance",
            "FillDB_Performance",
            "FillDB_Performance/Analysis",
        ],
        module_subfolder="FillDB_Performance",
    ),
]

MODULE_BY_KEY = {mod.key: mod for mod in MODULES}


# ---------------------------------------------------------------------------
# Run folder and config
# ---------------------------------------------------------------------------


def sanitize_run_name(name: str) -> str:
    """Return a filesystem-safe version of the run name."""
    clean = re.sub(r"[^\w]", "_", name.strip())
    clean = re.sub(r"_+", "_", clean).strip("_")
    return clean or "Diagnostics"


def setup_run_folder(out_folder: Path, run_name: str, ts: str) -> tuple[Path, str]:
    """
    Create and return (run_folder, file_prefix).

    run_folder  = out_folder / "{run_name}_{YYYYMMDD_HHMMSS}"
    file_prefix = "{run_name}_{YYYYMMDD_HHMMSS}"
    """
    file_prefix = f"{sanitize_run_name(run_name)}_{ts}"
    run_folder = out_folder / file_prefix
    run_folder.mkdir(parents=True, exist_ok=True)
    return run_folder, file_prefix


def attach_run_context(
    m_inputs: dict, mod: Module, run_folder: Path, file_prefix: str
) -> None:
    """Inject run-level keys into a module's inputs dict."""
    m_inputs["_run_folder"] = run_folder
    m_inputs["_file_prefix"] = file_prefix
    if mod.module_subfolder:
        out = run_folder / mod.module_subfolder
        out.mkdir(parents=True, exist_ok=True)
        m_inputs["_out_folder"] = out
    else:
        m_inputs["_out_folder"] = run_folder


def load_config(path: str) -> dict:
    config_path = Path(clean_user_path(path)).expanduser()
    if not config_path.exists():
        raise ValueError(
            f"Config file was not found: {config_path.resolve(strict=False)}"
        )
    try:
        with config_path.open("r", encoding="utf-8-sig") as handle:
            return json.load(handle)
    except OSError as exc:
        raise ValueError(f"Could not read config file: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Config file is invalid JSON: {exc}") from exc


def _parse_module_inputs_from_config(
    selected: list[Module],
    raw_inputs: dict,
    data_root: Path | None,
    manual_inputs: dict | None = None,
) -> dict[str, dict]:
    """Resolve every selected module's inputs from the config.

    manual_inputs maps a module key to the input keys the user chose by hand
    (the UI writes it as {module: {field: path}}). A loop optional path that
    is not under the data root or the loop input's folder is normally treated
    as stale and replaced by discovery. A path the user chose is never
    replaced, wherever it lives.
    """
    discovered: dict[str, Path | None] = {}
    if data_root is not None and data_root.is_dir():
        discovered = scan_input_folder(data_root)

    module_inputs: dict[str, dict] = {}
    for mod in selected:
        manual_keys = set((manual_inputs or {}).get(mod.key) or ())
        mod_raw_inputs = dict(raw_inputs.get(mod.key, {}) or {})
        if mod.key == "loop":
            raw_loop_input = mod_raw_inputs.get(mod.file_key)
            loop_input = (
                Path(str(raw_loop_input)) if raw_loop_input else discovered.get(mod.key)
            )
            loop_ancillary = discover_loop_ancillary_inputs(data_root, loop_input)
            for key, path in loop_ancillary.items():
                if path is not None and not str(mod_raw_inputs.get(key) or "").strip():
                    mod_raw_inputs[key] = str(path)
            for key in (
                "deployment_info_folder",
                "top_offenders_file",
                "udp_notifications_file",
            ):
                raw_value = str(mod_raw_inputs.get(key) or "").strip()
                if not raw_value:
                    continue
                if key in manual_keys:
                    continue
                if _loop_optional_path_in_scope(data_root, loop_input, Path(raw_value)):
                    continue
                replacement = loop_ancillary.get(key)
                mod_raw_inputs[key] = str(replacement) if replacement else ""
        m_inputs = collect_inputs_from_config(mod, mod_raw_inputs)
        m_inputs["_out_folder"] = Path()
        module_inputs[mod.key] = m_inputs
    return module_inputs


@dataclass
class RunContext:
    selected: list[Module]
    module_inputs: dict[str, dict]
    style_template: Path | None
    out_folder: Path
    run_name: str
    config: dict


def build_run_context(config_path: str) -> RunContext:
    config = load_config(config_path)
    requested_keys = [
        key for key in (config.get("modules") or []) if key in MODULE_BY_KEY
    ]
    if not requested_keys:
        raise ValueError("Config does not select any known modules.")
    selected = [MODULE_BY_KEY[key] for key in requested_keys]

    out_folder = resolve_existing_folder(
        config.get("output_folder") or DEFAULT_WORK_DIR, "Output Folder"
    )
    data_root_raw = clean_user_path(config.get("data_root", ""))
    data_root = Path(data_root_raw).expanduser() if data_root_raw else None
    manual_inputs = {
        key: value
        for key, value in (config.get("manual_inputs") or {}).items()
        if key in MODULE_BY_KEY
    }
    module_inputs = _parse_module_inputs_from_config(
        selected, dict(config.get("inputs") or {}), data_root, manual_inputs
    )
    return RunContext(
        selected=selected,
        module_inputs=module_inputs,
        style_template=resolve_style_template(config.get("template")),
        out_folder=out_folder,
        run_name=str(config.get("run_name", "")).strip(),
        config=dict(config),
    )


def _print_run_summary(context: RunContext, run_folder: Path) -> None:
    print("\n" + "=" * 56)
    print("   Ready to run")
    print("=" * 56 + "\n")
    print(f"  Run name      : {context.run_name or '(none)'}")
    print(f"  Run folder    : {run_folder}\n")
    for mod in context.selected:
        print(f"  [{mod.label}]")
        for k, v in mod.summary(context.module_inputs[mod.key]):
            print(f"    {k:<14}: {v}")
        print()


def _write_run_manifest(
    run_folder: Path, file_prefix: str, context: RunContext, log: RunLog
) -> None:
    """Record what the run produced so the UI can open the outputs."""
    files = sorted(
        path.relative_to(run_folder).as_posix()
        for path in run_folder.rglob("*")
        if path.is_file()
    )
    manifest = {
        "app": APP_TITLE,
        "run_name": context.run_name,
        "file_prefix": file_prefix,
        "modules": [mod.key for mod in context.selected],
        "config": context.config,
        "files": files,
    }
    path = run_folder / f"{file_prefix}_Run_Manifest.json"
    try:
        path.write_text(json.dumps(manifest, indent=2, default=str), encoding="utf-8")
        log.info("Run manifest", str(path))
    except OSError as exc:
        log.warning(f"Could not write the run manifest: {exc}")


def _write_run_diagnostics(
    run_folder: Path,
    file_prefix: str,
    diagnostics: PerformanceRecorder,
    log: RunLog,
    *,
    result: str,
) -> None:
    """Persist compact engine evidence for test feedback and support review."""
    path = run_folder / f"{file_prefix}_Run_Diagnostics.json"
    try:
        diagnostics.write_json(
            path,
            result=result,
            process_resources=process_resource_metrics(),
        )
        log.info("Run diagnostics", str(path))
    except OSError as exc:
        log.warning(f"Could not write run diagnostics: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=f"{APP_TITLE}: run the selected analysis modules.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", help="JSON config written by the desktop UI.")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm the run. There is no interactive confirmation prompt.",
    )
    args = parser.parse_args()

    if not args.config or not args.yes:
        print(
            "ERROR: --config <file> and --yes are both required. "
            "Run from the desktop UI, or pass both on the command line.",
            file=sys.stderr,
        )
        return 2

    print()
    print("=" * 56)
    print(f"   {APP_TITLE}")
    print("=" * 56)
    print()

    log: RunLog | None = None
    run_folder: Path | None = None
    file_prefix = ""
    run_start = datetime.now()
    ts = run_start.strftime("%Y%m%d_%H%M%S")
    diagnostics = PerformanceRecorder("engine")

    try:
        started = time.perf_counter()
        context = build_run_context(args.config)
        diagnostics.record(
            "Build run context",
            elapsed_ms=(time.perf_counter() - started) * 1000,
        )
        diagnostics.update_metadata(
            selected_modules=[mod.key for mod in context.selected],
            module_count=len(context.selected),
        )
        run_folder, file_prefix = setup_run_folder(
            context.out_folder, context.run_name, ts
        )
        for mod in context.selected:
            attach_run_context(
                context.module_inputs[mod.key], mod, run_folder, file_prefix
            )
        print(f"RUN_FOLDER: {run_folder}", flush=True)
        _print_run_summary(context, run_folder)

        log = RunLog(diagnostics)
        log.header(APP_TITLE)
        log.info("Run name", context.run_name or "(none)")
        log.info("File prefix", file_prefix)
        log.info("Run folder", str(run_folder))
        log.info(
            "Style template",
            str(context.style_template) if context.style_template else "(blank document)",
        )
        log.section("Inputs")
        for mod in context.selected:
            log.inputs(mod.label, mod.summary(context.module_inputs[mod.key]))

        log.set_module_total(len(context.selected))
        for mod in context.selected:
            started = time.perf_counter()
            try:
                mod.run(context.module_inputs[mod.key], context.style_template, ts, log)
            except Exception:
                diagnostics.record(
                    "Module pipeline",
                    elapsed_ms=(time.perf_counter() - started) * 1000,
                    detail=mod.key,
                    result="failed",
                )
                raise
            diagnostics.record(
                "Module pipeline",
                elapsed_ms=(time.perf_counter() - started) * 1000,
                detail=mod.key,
                result="completed",
            )

        log.section("Outputs")
        for mod in context.selected:
            for line in mod.done(context.module_inputs[mod.key], ts):
                log.info(line)
        _write_run_manifest(run_folder, file_prefix, context, log)
        _write_run_diagnostics(
            run_folder, file_prefix, diagnostics, log, result="completed"
        )

        elapsed = (datetime.now() - run_start).total_seconds()
        log.footer(run_folder, elapsed)
        log.write(run_folder / f"{file_prefix}_RunLog.txt")
        return 0

    except Exception as exc:
        message = f"{type(exc).__name__}: {exc}"
        if log is not None:
            log.error(message)
            if run_folder is not None:
                _write_run_diagnostics(
                    run_folder, file_prefix, diagnostics, log, result="failed"
                )
                log.write(run_folder / f"{file_prefix}_RunLog.txt")
        else:
            print(f"\n  ERROR: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
