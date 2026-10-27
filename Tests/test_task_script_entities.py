# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Relevance in a task script must be real relevance, not XML-escaped text.

The script of a task sits in a CDATA section, so an entity such as the escaped ampersand
reaches the BigFix client literally and the expression fails with "The operator amp is not
defined". The Enable Relay task carried three of them and could not run on any platform.
Entities inside a quoted string are deliberate (the collectors escape text for XML output),
and doubled braces mark text for a later pass, so only plain {expression} is checked.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

HERE = Path(__file__).resolve()
SITE = next(
    p / "Tasks and Analyses" for p in HERE.parents if (p / "Tasks and Analyses").is_dir()
)
TASKS = sorted(SITE.rglob("*.bes"))
SUBSTITUTION = re.compile(r"(?<!\{)\{(?!\{)([^{}" + chr(10) + r"]*)\}")
ENTITY = re.compile(r"&(?:amp|lt|gt|quot|apos);")


@pytest.mark.parametrize("path", TASKS, ids=lambda p: p.name[-60:])
def test_no_relevance_expression_carries_a_literal_xml_entity(path: Path) -> None:
    root = ET.fromstring(path.read_bytes())
    for element in root.iter():
        if element.tag.endswith("ActionScript") and element.text:
            for match in SUBSTITUTION.finditer(element.text):
                outside_quotes = re.sub(r'"[^"]*"', '""', match.group(1))
                assert not ENTITY.search(outside_quotes), match.group(1)[:120]
