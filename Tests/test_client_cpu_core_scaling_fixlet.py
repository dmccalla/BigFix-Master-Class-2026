# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Contract checks for the Master Class client CPU core scaling Fixlet."""

from __future__ import annotations

from pathlib import Path

from defusedxml import ElementTree as ET

FIXLET = (
    Path(__file__).resolve().parents[1]
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Enable Client CPU Core Scaling (2.0).bes"
)


def test_client_cpu_core_scaling_fixlet_is_a_reusable_1107_fixlet() -> None:
    root = ET.parse(FIXLET).getroot()
    fixlet = root.find("Fixlet")

    assert fixlet is not None
    assert fixlet.findtext("Title") == (
        "BigFix Master Class -- Enable Client CPU Core Scaling (2.0)"
    )
    assert fixlet.findtext("Category") == "BigFix Master Class"
    assert fixlet.findtext("Domain") == "BES "
    assert fixlet.find("SourceSeverity") is None

    relevance = "\n".join(item.text or "" for item in fixlet.findall("Relevance"))
    assert 'version of client >= "11.0.7.0" as version' in relevance
    assert (
        'not exists values whose (it = "1") of settings '
        '"_BESClient_Resource_ScaleWorkTimeWithCPUCores" of client'
    ) in relevance

    action = fixlet.find("DefaultAction")
    assert action is not None
    script = action.findtext("ActionScript") or ""
    assert 'setting "_BESClient_Resource_ScaleWorkTimeWithCPUCores"="1"' in script
    assert "_BESClient_Resource_WorkIdle" not in script
    assert "_BESClient_Resource_SleepIdle" not in script

    description = fixlet.findtext("Description") or ""
    assert "hc-wrap" in description
    assert "READ BEFORE YOU RUN" in description
    assert "BigFix 11.0.7 or later" in description
