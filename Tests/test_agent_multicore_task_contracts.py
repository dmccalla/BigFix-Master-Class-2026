# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Contract checks for the Master Class 11.0.7 agent multicore content."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = (
    ROOT
    / "Tasks and Analyses"
    / "Analyses"
    / "BigFix Master Class -- Client Performance Counters - Basic (2.0).bes"
)
COLLECTOR = (
    ROOT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes"
)
SETTING_NAMES = ("_BESClient_Resource_ScaleWorkTimeWithCPUCores",)
PROPERTY_NAMES = ("Platform Health Check - Agent Multicore Scaling Enabled",)
CORE_COUNT_PROPERTY_NAME = "Platform Health Check - Agent Total Physical CPU Core Count"
IDLE_SETTING_NAMES = (
    "_BESClient_Resource_WorkIdle",
    "_BESClient_Resource_SleepIdle",
)
IDLE_PROPERTY_NAMES = (
    "Platform Health Check - Agent CPU Work Idle",
    "Platform Health Check - Agent CPU Sleep Idle",
)


def test_agent_multicore_analysis_is_valid_and_queries_the_supported_switch() -> None:
    ElementTree.parse(ANALYSIS)
    content = ANALYSIS.read_text(encoding="utf-8")

    for setting_name, property_name in zip(SETTING_NAMES, PROPERTY_NAMES, strict=True):
        assert setting_name in content
        assert property_name in content
    assert CORE_COUNT_PROPERTY_NAME in content
    assert "(count of cpupackages) * (core of cpupackage)" in content
    assert content.count('version of client >= "11.0.7.0" as version') == 1
    assert content.count('else "Not Applicable"') == 1
    for setting_name, property_name in zip(
        IDLE_SETTING_NAMES, IDLE_PROPERTY_NAMES, strict=True
    ):
        assert setting_name in content
        assert property_name in content


def test_agent_cpu_settings_collector_reads_all_fourteen_fields() -> None:
    ElementTree.parse(COLLECTOR)
    content = COLLECTOR.read_text(encoding="utf-8")

    for property_name in (
        *PROPERTY_NAMES,
        *IDLE_PROPERTY_NAMES,
        CORE_COUNT_PROPERTY_NAME,
    ):
        assert property_name in content
    assert "item 13 of it" in content
    assert "SplitAnswerFields $Line 14" in content
    assert "$parts[13].Trim()" in content
    assert "_BESClient_Resource_MaxCoreUtilization" not in content
    assert "_BESClient_Resource_WorkTypeScalar" not in content

def test_standalone_helper_matches_embedded_fourteen_field_collector() -> None:
    utility = (ROOT / "Utilities" / "query_properties.ps1").read_text(encoding="utf-8")
    utility = utility[utility.index("# query_properties.ps1") :].strip()
    action = ElementTree.parse(COLLECTOR).getroot().findtext(".//ActionScript") or ""
    start = action.index("# query_properties.ps1")
    embedded = action[start : action.index("\n__END__", start)].strip()
    assert embedded == utility.replace("{", "{{")

    for script in (utility, embedded):
        assert "if ($parts.Count -eq 14)" in script
        assert "if ($parts.Count -ne 14)" in script
        assert '"Platform Health Check - FastHashVerify Enabled"' in script
        assert '"Platform Health Check - Agent CPU Work Idle"' in script
        assert "$parts[13].Trim()" in script
        assert "Count -eq 7" not in script
        assert '(if it = "" then "Not Applicable" else it) of concatenation ";" of values of results (item 0 of it, elements of item 10 of it)' in script
