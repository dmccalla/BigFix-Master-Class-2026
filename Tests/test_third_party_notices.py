"""The release notices come from the environment that runs the script."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Build" / "third_party_notices.py"


def _run(tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess[str], Path]:
    target = tmp_path / "THIRD_PARTY_NOTICES.md"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(target), *extra],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )
    return result, target


def _table_rows(text: str) -> list[list[str]]:
    rows = []
    for line in text.splitlines():
        if line.startswith("| ") and not line.startswith("| Package"):
            rows.append([cell.strip() for cell in line.strip("|").split("|")])
    return rows


def test_writes_the_runtime_inventory(tmp_path: Path) -> None:
    result, target = _run(tmp_path, "--ignore", "pip")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("Notices : ")
    rows = _table_rows(target.read_text(encoding="utf-8"))
    names = {row[0].lower() for row in rows}
    # The test environment holds the runtime packages this repo pins.
    assert {"customtkinter", "python-docx", "openpyxl"} <= names
    assert "pip" not in names
    assert all(len(row) == 4 for row in rows)
    assert all(row[1] and row[2] for row in rows), (
        "every row carries a version and a license"
    )
    assert rows == sorted(rows, key=lambda row: row[0].lower())


def test_ignore_is_case_insensitive(tmp_path: Path) -> None:
    result, target = _run(tmp_path, "--ignore", "Python-Docx")
    assert result.returncode == 0, result.stderr
    names = {row[0].lower() for row in _table_rows(target.read_text(encoding="utf-8"))}
    assert "python-docx" not in names
