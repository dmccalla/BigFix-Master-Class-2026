# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Validate the approved copy-command note in the shipped tasks."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

TASKS = Path(__file__).resolve().parents[1] / "Tasks and Analyses"
NOTES = [
    path
    for path in sorted(TASKS.rglob("*.bes"))
    if "Windows <TT>xcopy</TT>" in path.read_text(encoding="utf-8-sig")
]


@pytest.mark.parametrize("path", NOTES, ids=lambda path: path.stem)
def test_xcopy_exit_code_note(path):
    description = next(iter(ET.fromstring(path.read_bytes()))).findtext("Description", "")
    assert "<TT>xcopy</TT> returns 0 for a successful copy" in description
    assert "1 when no matching files were found" in description
    assert "1 is acceptable only when those files are optional" in description
    assert "uses 1 when files were copied" not in description


def test_copy_exit_code_notes_are_present():
    assert NOTES, "Expected task descriptions with xcopy exit-code notes"
