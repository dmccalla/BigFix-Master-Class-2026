# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

TASK = (
    Path(__file__).resolve().parents[1]
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Deployment Information (2.0).bes"
)


@pytest.mark.parametrize("response", ["Fields", "Options"])
def test_optional_admin_xml_checks_size_before_parsing(response: str) -> None:
    script = ET.parse(TASK).findtext(".//ActionScript")
    assert script is not None
    parameter = f'parameter "generalInfoFileAdminTool{response}XML"'
    guard = (
        f"if {{if exists files ({parameter}) whose (size of it > 0) "
        f"then exists xml documents of files ({parameter}) else false}}"
    )
    assert guard in script
    block = script.split(guard, 1)[1].split("endif", 1)[0]
    assert "else" in block
    assert "were not available to the supplied API account" in block
