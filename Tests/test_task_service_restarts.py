# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Service restarts in the tasks must wait for the service and fail visibly.

A task that stops a service, waits a fixed ten seconds, and starts it again without checking
either result can leave the service down and still report success. Every stop and start must
wait for the service state and be followed by a failure check. The curl that creates the
auto-disable action must fail on an HTTP error and be checked too, or a task can leave logging
on with no disable action and still report success.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from Utilities.service_transition_commands import service_command

HERE = Path(__file__).resolve()
SITE = next(
    p / "Tasks and Analyses" for p in HERE.parents if (p / "Tasks and Analyses").is_dir()
)
TASKS = sorted(SITE.rglob("*.bes"))
GATE = re.compile(r"^\s*continue if \{\{?exit code of action = 0\}\s*$")


def _lines(path: Path) -> list[str]:
    return path.read_bytes().decode("utf-8-sig", errors="replace").splitlines()


def _next_nonblank(lines: list[str], index: int) -> str:
    for line in lines[index + 1 :]:
        if line.strip():
            return line
    return ""


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_no_task_uses_a_blind_net_stop_or_start(path: Path) -> None:
    for line in _lines(path):
        assert not re.search(r"cmd\.exe /C net (stop|start) ", line), line.strip()[:120]


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_every_service_stop_and_start_waits_and_is_checked(path: Path) -> None:
    lines = _lines(path)
    for i, line in enumerate(lines):
        if "powershell.exe" in line and "Get-Service" in line:
            gate = _next_nonblank(lines, i)
            assert GATE.match(gate), f"no failure check after: {line.strip()[:100]}"
            identity = re.search(r"\$Name='([^']+)'; \$Target='(Stopped|Running)';", line)
            assert identity, f"Unmanaged service command: {line.strip()[:120]}"
            passes = 2 if "{{exit code" in gate else 1
            assert line.strip() == service_command(*identity.groups(), passes)
            assert "WaitForStatus(" not in line


def test_inline_service_commands_fit_windows_command_lines() -> None:
    for target in ("Stopped", "Running"):
        assert len(service_command("BES Web Reports Server", target, 2)) < 8191


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_the_disable_action_post_fails_loudly(path: Path) -> None:
    lines = _lines(path)
    for i, line in enumerate(lines):
        if "curl" in line and "-X POST" in line:
            assert line.rstrip().endswith("--fail"), line.strip()[:120]
            assert GATE.match(_next_nonblank(lines, i)), (
                f"no failure check after: {line.strip()[:100]}"
            )
