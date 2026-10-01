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
    / "BigFix Master Class -- Agent Performance Counters - Basic (2.0).bes"
)
COLLECTOR = (
    ROOT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Agent Performance Counter Analysis Data (2.0).bes"
)
SETTING_NAMES = (
    "_BESClient_Resource_ScaleWorkTimeWithCPUCores",
    "_BESClient_Resource_MaxCoreUtilization",
    "_BESClient_Resource_WorkTypeScalar",
)
PROPERTY_NAMES = (
    "Platform Health Check - Agent Multicore Scaling Enabled",
    "Platform Health Check - Agent Multicore Max Core Utilization",
    "Platform Health Check - Agent Multicore Work Type Scalar",
)
IDLE_SETTING_NAMES = (
    "_BESClient_Resource_WorkIdle",
    "_BESClient_Resource_SleepIdle",
)
IDLE_PROPERTY_NAMES = (
    "Platform Health Check - Agent CPU Work Idle",
    "Platform Health Check - Agent CPU Sleep Idle",
)


def test_agent_multicore_analysis_is_valid_and_queries_each_setting() -> None:
    ElementTree.parse(ANALYSIS)
    content = ANALYSIS.read_text(encoding="utf-8")

    for setting_name, property_name in zip(SETTING_NAMES, PROPERTY_NAMES, strict=True):
        assert setting_name in content
        assert property_name in content
    assert content.count('version of client >= "11.0.7.0" as version') == 3
    assert content.count('else "Not Applicable"') == 3
    for setting_name, property_name in zip(
        IDLE_SETTING_NAMES, IDLE_PROPERTY_NAMES, strict=True
    ):
        assert setting_name in content
        assert property_name in content


def test_agent_cpu_settings_collector_reads_all_fifteen_fields() -> None:
    ElementTree.parse(COLLECTOR)
    content = COLLECTOR.read_text(encoding="utf-8")

    for property_name in (*PROPERTY_NAMES, *IDLE_PROPERTY_NAMES):
        assert property_name in content
    assert "item 14 of it" in content
    assert "SplitAnswerFields $Line 15" in content
    assert '$parts[14].Trim()' in content
