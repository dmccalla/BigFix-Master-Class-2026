# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Admin XML collection must not depend on readable-log generation."""

from __future__ import annotations

from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "Tasks and Analyses").is_dir()
)
TASKS = ROOT / "Tasks and Analyses"
FILES = tuple(
    (TASKS / "Individual Tasks").glob("* -- Collect Deployment Information (2.0).bes")
) + tuple((TASKS / "Combined").glob("* -- Day 1 - Deployment Data Collection (2.0).bes"))
LOG_GUARD = 'if {(parameter "generateLogFiles" | "0") = "1"}'


def _commands_with_conditions(path: Path):
    script = ET.parse(path).findtext(".//ActionScript")
    assert script
    conditions: list[str] = []
    payload_end = None
    for raw in script.splitlines():
        line = raw.strip()
        if payload_end is not None:
            if line == payload_end:
                payload_end = None
            continue
        if line.startswith(("createfile until ", "appendfile until ")):
            payload_end = line.split(" until ", 1)[1]
        elif line.startswith("if {"):
            conditions.append(line)
        elif line.startswith("elseif {"):
            conditions[-1] = line
        elif line == "else":
            conditions[-1] = "else " + conditions[-1]
        elif line == "endif":
            assert conditions, "Unmatched endif"
            conditions.pop()
        elif line.startswith("waithidden "):
            yield line, tuple(conditions)
    assert payload_end is None
    assert not conditions, "Unclosed ActionScript condition"


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.stem)
@pytest.mark.parametrize("kind", ("Fields", "Options"))
def test_admin_requests_do_not_depend_on_readable_logs(path, kind):
    requests = [
        conditions
        for command, conditions in _commands_with_conditions(path)
        if f"-Resource admin/{kind.lower()} " in command
    ]
    assert len(requests) == 1
    conditions = requests[0]
    assert not any("generateLogFiles" in condition for condition in conditions), (
        "Admin XML must be collected with readable logs both off and on"
    )
    section = "collectDeploymentInfo" if "Day 1" in path.name else "collectGeneral"
    assert any(section in condition and '"true"' in condition for condition in conditions)


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.stem)
@pytest.mark.parametrize("kind", ("Fields", "Options"))
def test_admin_log_formatting_requires_readable_logs(path, kind):
    formatting = [
        conditions
        for command, conditions in _commands_with_conditions(path)
        if command.startswith("waithidden cmd.exe /C echo {")
        and f'parameter "generalInfoFileAdminTool{kind}XML"' in command
    ]
    assert len(formatting) == 1
    assert LOG_GUARD in formatting[0]
