# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Credentials and operator text in task command lines must be quoted and validated.

The task forms collect API and database credentials and pass them into cmd.exe,
curl and sqlcmd command lines. Quoting keeps the shell metacharacters (& | < > ^)
inert, and the forms reject the one character quoting cannot protect, a double
quote. The SQL form also restricts the names it pastes into the collection script.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
SITE = next(
    p / "Tasks and Analyses" for p in HERE.parents if (p / "Tasks and Analyses").is_dir()
)
TASKS = sorted(SITE.rglob("*.bes"))
SECRET_PARAMS = ("apiPassword", "sharePassword", "dbPassword")


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8-sig", errors="replace")


def _active_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("//")]


def test_task_files_are_found() -> None:
    assert TASKS, f"no .bes files under {SITE}"


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_iem_login_quotes_the_credentials(path: Path) -> None:
    for line in _active_lines(_text(path)):
        if "--password=" in line and 'parameter "apiPassword"' in line:
            assert '--user="{parameter "apiUsername"}"' in line, line[:160]
            assert '--password="{parameter "apiPassword"}"' in line, line[:160]


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_curl_quotes_the_credentials(path: Path) -> None:
    for line in _active_lines(_text(path)):
        if "curl" in line and 'parameter "apiUsername"' in line:
            assert (
                '--user "{parameter "apiUsername"}:{parameter "apiPassword"}"' in line
            ), line[:160]


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_forms_reject_a_double_quote_in_api_credentials(path: Path) -> None:
    text = _text(path)
    reads = len(
        re.findall(
            r"(?:var apiPassword|password)\s*=\s*.*getElementById\([^)]*\)\.value", text
        )
    )
    checks = len(re.findall(r"""(?:apiPassword|password)\.indexOf\('"'\)""", text))
    assert checks >= reads, f"{reads} password reads but {checks} double quote checks"


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_no_line_echoes_a_secret_parameter(path: Path) -> None:
    for line in _text(path).splitlines():
        if re.search(r"\becho\b", line) and any(
            f'parameter "{name}"' in line for name in SECRET_PARAMS
        ):
            pytest.fail(f"secret echoed: {line.strip()[:120]}")


def _pattern(text: str, variable: str) -> re.Pattern[str]:
    match = re.search(r"!/(\^[^/]+\$)/\.test\(" + variable + r"\)", text)
    assert match, f"no allow-list for {variable}"
    # JavaScript's $ means end of input. Python's also matches before a trailing newline.
    return re.compile(match.group(1)[:-1] + r"\Z")


SQL_TASK = next((p for p in TASKS if "Collect SQL Server Information" in p.name), None)


@pytest.mark.skipif(SQL_TASK is None, reason="SQL task is not part of this repository")
def test_sql_form_restricts_the_names_it_pastes_into_the_script() -> None:
    text = _text(SQL_TASK)
    hostname = _pattern(text, "dbHostname")
    database = _pattern(text, "dbName")
    instance = _pattern(text, "dbInstance")
    for good in ("BFROOT1", "bigfix-db.example.com", "10.1.2.3"):
        assert hostname.match(good)
    for good in ("BFEnterprise", "BFEnterprise_2", "My DB-1"):
        assert database.match(good)
    for good in ("SQLEXPRESS", "BF_INST-1"):
        assert instance.match(good)
    hostile = ["x'; DROP TABLE t;--", "a]b", "$(Evil)", 'a"b', "a;b", "a\\b", "a b\n"]
    for bad in hostile:
        assert not database.match(bad), bad
        assert not hostname.match(bad), bad
        assert not instance.match(bad), bad
    assert "dbFullUsername.indexOf('\"')" in text
    assert "dbPassword.indexOf('\"')" in text


SHARE_TASK = next((p for p in TASKS if "Log File Upload Monitor" in p.name), None)


@pytest.mark.skipif(
    SHARE_TASK is None, reason="upload monitor is not part of this repository"
)
def test_share_connection_is_removed_after_the_copy() -> None:
    lines = _active_lines(_text(SHARE_TASK))
    connect = next(i for i, ln in enumerate(lines) if "net use" in ln and "/USER:" in ln)
    copy = next(
        i
        for i, ln in enumerate(lines)
        if "xcopy" in ln and 'parameter "remoteShare"' in ln
    )
    delete = next(i for i, ln in enumerate(lines) if "net use" in ln and "/delete" in ln)
    assert connect < copy < delete
