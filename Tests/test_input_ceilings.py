# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Every input has a documented ceiling and a hung module is stopped.

Each limit is tested just under and just over its value. The ceilings are
lowered with monkeypatch so the tests stay small and fast.
"""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import get_loop_health as loop
import pandas as pd
import pytest
import run_diagnostics as runner

from Lib.Core import input_limits as limits


def _check(path: Path) -> None:
    """Run the engine's own file check as a module input would."""
    mod = next(m for m in runner.MODULES if m.key == "perfmon")
    field = next(f for f in mod.inputs_schema if f.kind == "file")
    runner._validate_input_file(mod, field, path)


def _write(path: Path, size: int) -> Path:
    path.write_bytes(b"a,b\n" + b"1,2\n" * (max(size - 4, 0) // 4))
    return path


# ---------------------------------------------------------------- file sizes


def test_capture_at_the_limit_is_accepted_and_one_over_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "TEXT_CAPTURE_LIMIT", 100)
    at_limit = _write(tmp_path / "at.csv", 100)
    assert at_limit.stat().st_size == 100
    _check(at_limit)

    over = tmp_path / "over.csv"
    over.write_bytes(at_limit.read_bytes() + b"x")
    with pytest.raises(ValueError, match="limit for capture and log files"):
        _check(over)


def test_perfmon_capture_has_its_own_ceiling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "PERFMON_LIMIT", 64)
    monkeypatch.setattr(limits, "TEXT_CAPTURE_LIMIT", 10)
    small = tmp_path / "ok.blg"
    small.write_bytes(b"\x01" * 64)
    big = tmp_path / "big.blg"
    big.write_bytes(b"\x01" * 65)
    _check(small)
    with pytest.raises(ValueError, match="PerfMon"):
        _check(big)


def test_the_advanced_setting_raises_size_ceilings_and_is_clamped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "TEXT_CAPTURE_LIMIT", 100)
    path = _write(tmp_path / "big.csv", 250)
    with pytest.raises(ValueError):
        _check(path)

    monkeypatch.setenv(limits.MULTIPLIER_ENV, "3")
    _check(path)
    assert limits.override_note()

    monkeypatch.setenv(limits.MULTIPLIER_ENV, "99")
    assert limits.limit_multiplier() == limits.MAX_MULTIPLIER
    for bad in ("0", "-2", "two", "", "2.5"):
        monkeypatch.setenv(limits.MULTIPLIER_ENV, bad)
        assert limits.limit_multiplier() == 1
    monkeypatch.delenv(limits.MULTIPLIER_ENV)
    assert limits.override_note() == ""


# ------------------------------------------------------------------ archives


def _zip(path: Path, members: dict[str, bytes]) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return path


def test_a_decompression_bomb_is_refused(tmp_path: Path) -> None:
    bomb = _zip(tmp_path / "bomb.xlsx", {"sheet.xml": b"\x00" * (8 * limits.MIB)})
    assert bomb.stat().st_size < 100_000
    with pytest.raises(ValueError, match="decompression bomb"):
        _check(bomb)


def test_an_ordinary_office_file_is_accepted(tmp_path: Path) -> None:
    data = bytes(range(256)) * 200
    _check(_zip(tmp_path / "ok.xlsx", {"a.xml": data, "b.xml": data[::-1]}))


def test_expanded_size_and_entry_count_ceilings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "ARCHIVE_ENTRY_LIMIT", 3)
    many = _zip(tmp_path / "many.docx", {f"m{i}.txt": b"x" * 50 for i in range(4)})
    with pytest.raises(ValueError, match="4 entries"):
        _check(many)
    exact = _zip(tmp_path / "exact.docx", {f"m{i}.txt": b"x" * 50 for i in range(3)})
    _check(exact)

    monkeypatch.setattr(limits, "ARCHIVE_ENTRY_LIMIT", 100)
    monkeypatch.setattr(limits, "ARCHIVE_EXPANDED_LIMIT", 1000)
    rng = bytes((i * 37 + i // 7) % 256 for i in range(1200))
    with pytest.raises(ValueError, match="expands to"):
        _check(_zip(tmp_path / "big.docx", {"a.bin": rng}))


# ------------------------------------------------------------------- folders


def test_a_folder_with_an_oversize_file_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "PERFMON_LIMIT", 10)
    (tmp_path / "Perfmon").mkdir()
    (tmp_path / "Perfmon" / "server.blg").write_bytes(b"\x01" * 11)
    with pytest.raises(ValueError, match="PerfMon"):
        runner._validate_input_folder(tmp_path, "Data folder")


def test_a_folder_with_too_many_entries_is_not_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "MAX_FOLDER_ENTRIES", 5)
    for index in range(5):
        (tmp_path / f"f{index}.txt").write_text("data", encoding="utf-8")
    runner._validate_input_folder(tmp_path, "Data folder")
    (tmp_path / "f5.txt").write_text("data", encoding="utf-8")
    with pytest.raises(ValueError, match="too large to scan"):
        runner._validate_input_folder(tmp_path, "Data folder")
    with pytest.raises(limits.InputLimitError):
        runner.scan_input_folder(tmp_path)


def test_a_folder_nested_too_deeply_is_not_scanned(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(limits, "MAX_FOLDER_DEPTH", 2)
    (tmp_path / "a" / "b" / "c").mkdir(parents=True)
    with pytest.raises(ValueError, match="levels deep"):
        runner._validate_input_folder(tmp_path, "Data folder")


# ---------------------------------------------------------------------- JSON


def test_json_size_depth_and_text_ceilings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps({"run_name": "x" * 2000, "data_root": "y" * 1024}))
    assert limits.read_json_file(ok)["run_name"] == "x" * 2000

    long_text = tmp_path / "long.json"
    long_text.write_text(json.dumps({"run_name": "x" * 2001}))
    with pytest.raises(limits.InputLimitError, match="run_name"):
        limits.read_json_file(long_text)

    long_path = tmp_path / "path.json"
    long_path.write_text(json.dumps({"inputs": {"blg_path": "y" * 1025}}))
    with pytest.raises(limits.InputLimitError, match="blg_path"):
        limits.read_json_file(long_path)

    nested: object = "leaf"
    for _ in range(limits.JSON_DEPTH_LIMIT + 1):
        nested = {"k": nested}
    deep = tmp_path / "deep.json"
    deep.write_text(json.dumps(nested))
    with pytest.raises(limits.InputLimitError, match="nested"):
        limits.read_json_file(deep)

    monkeypatch.setattr(limits, "JSON_LIMIT", 20)
    with pytest.raises(limits.InputLimitError, match="JSON"):
        limits.read_json_file(ok)


def test_load_config_refuses_oversize_and_non_object_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"modules": ["loop"]}), encoding="utf-8-sig")
    assert runner.load_config(str(good)) == {"modules": ["loop"]}

    listing = tmp_path / "list.json"
    listing.write_text("[1, 2]")
    with pytest.raises(ValueError, match="JSON object"):
        runner.load_config(str(listing))

    monkeypatch.setattr(limits, "JSON_LIMIT", 10)
    with pytest.raises(ValueError, match="limit"):
        runner.load_config(str(good))


# ------------------------------------------------------------ rows and fields


def test_endpoint_row_ceiling_has_a_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(limits, "MAX_ENDPOINT_ROWS", 3)
    assert limits.endpoint_rows_problem(3) == ""
    assert "4 endpoint rows" in limits.endpoint_rows_problem(4)

    monkeypatch.setattr(
        loop, "_read_loop_input", lambda _p: pd.DataFrame({"Computer Name": list("abc")})
    )
    assert len(loop.load_loop_input(Path("loop.csv"))) == 3
    monkeypatch.setattr(
        loop, "_read_loop_input", lambda _p: pd.DataFrame({"Computer Name": list("abcd")})
    )
    with pytest.raises(ValueError, match="endpoint rows"):
        loop.load_loop_input(Path("loop.csv"))


class _FakeVariable:
    """Stands in for a Tk string variable, which needs no display here."""

    def __init__(self) -> None:
        self._value = ""
        self._callbacks: list = []

    def trace_add(self, _mode: str, callback) -> None:
        self._callbacks.append(callback)

    def get(self) -> str:
        return self._value

    def set(self, value: str) -> None:
        self._value = value
        for callback in list(self._callbacks):
            callback()


def test_text_entry_limit_cuts_typed_and_pasted_text() -> None:
    variable = _FakeVariable()
    limits.bind_text_limit(variable, 10)
    variable.set("short")
    assert variable.get() == "short"
    variable.set("x" * 10)
    assert variable.get() == "x" * 10
    variable.set("y" * 5000)
    assert variable.get() == "y" * 10


# -------------------------------------------------------------- run deadlines


def _child(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "child.py"
    script.write_text(body, encoding="utf-8")
    return script


def test_a_module_that_finishes_is_not_disturbed(tmp_path: Path) -> None:
    assert runner.run_python(_child(tmp_path, "pass\n"), []) == 0


def test_a_module_past_its_deadline_is_stopped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "RUN_PYTHON_DEADLINE_SECONDS", 1)
    monkeypatch.setattr(runner, "_WATCHDOG_POLL_SECONDS", 0.1)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="stopped because it ran longer"):
        runner.run_python(_child(tmp_path, "import time\ntime.sleep(120)\n"), [])
    assert time.monotonic() - started < 60


def test_a_silent_module_is_stopped_by_the_stall_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "RUN_PYTHON_STALL_SECONDS", 1)
    monkeypatch.setattr(runner, "_WATCHDOG_POLL_SECONDS", 0.1)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="gave no output"):
        runner.run_python(_child(tmp_path, "import time\ntime.sleep(120)\n"), [])
    assert time.monotonic() - started < 60
