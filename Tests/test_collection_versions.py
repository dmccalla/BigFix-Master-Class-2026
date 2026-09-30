# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

CONTENT = Path(__file__).resolve().parents[1] / "Tasks and Analyses"
FILES = sorted(CONTENT.rglob("*.bes"))


def test_collection_content_is_present():
    assert FILES


@pytest.mark.parametrize("path", FILES, ids=lambda path: path.stem)
def test_collection_titles_and_filenames_use_version_2_0(path):
    item = ET.parse(path).getroot()[0]
    title = item.findtext("Title")
    assert title and title.endswith(" (2.0)"), title
    assert path.stem == title.replace(":", "_"), path.name
