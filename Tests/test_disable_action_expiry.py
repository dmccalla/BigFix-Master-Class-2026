# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Generated disable actions must outlive the logging they turn off.

Every logging task posts a disable action that applies once the saved expiration
passes. That action ends after EndDateTimeLocalOffset. A fixed offset lapses before
a long duration finishes and leaves logging on, so the offset is computed from the
same duration parameter as the expiration, plus 24 hours.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
# Some layouts keep the tasks one level above the tests folder's parent.
TASKS = next(
    path
    for path in (ROOT / "Tasks and Analyses", ROOT.parent / "Tasks and Analyses")
    if path.is_dir()
)
FILES = sorted(
    path
    for path in TASKS.rglob("*.bes")
    if "EndDateTimeLocalOffset" in path.read_text(encoding="utf-8")
)
OFFSET = re.compile(
    r"EndDateTimeLocalOffset(?:>|&gt;)(?P<value>.*?)(?:<|&lt;)/EndDateTimeLocalOffset"
)
EXPIRATION = re.compile(
    r'Expiration"\s*=\s*"\{now \+ \(parameter "(?P<name>[A-Za-z0-9]+)" as integer \* hour\)\}"'
)
COMPUTED = re.compile(
    r'^P\{\(\(parameter "(?P<a>[A-Za-z0-9]+)" as integer \+ 24\) / 24\)\}'
    r'DT\{\(\(parameter "(?P<b>[A-Za-z0-9]+)" as integer \+ 24\) mod 24\)\}H$'
)


def test_logging_tasks_with_a_disable_action_are_found() -> None:
    assert FILES, "No task posts a generated disable action"


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.stem[:60])
def test_disable_action_offset_follows_the_logging_duration(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    offsets = list(OFFSET.finditer(text))
    assert offsets

    for match in offsets:
        value = match.group("value")
        assert value != "P2D", "A fixed 2 day offset ends before a long duration does"
        computed = COMPUTED.match(value)
        assert computed, f"Unexpected offset expression: {value}"
        assert computed.group("a") == computed.group("b")
        durations = {m.group("name") for m in EXPIRATION.finditer(text[: match.start()])}
        assert computed.group("a") in durations, (
            "The offset must use a duration that sets the expiration"
        )
