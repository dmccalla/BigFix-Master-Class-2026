# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# BigFix Master Class
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Regression coverage for product analysis selection in shared BigFix sites.

The catalog below models session inspector results. These tests execute the
description's JavaScript and inspect the actual property predicates. They do
not substitute for evaluating relevance against a running BigFix server.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

PROJECT = Path(__file__).resolve().parents[1]
CONTENT_ROOT = PROJECT
ANALYSIS_TITLE = "BigFix Master Class -- Client Performance Counters - Basic (2.0)"
PRODUCT_TITLES = (
    "BigFix Platform Health Check -- Client Performance Counters - Basic (2.0)",
    "BigFix Master Class -- Client Performance Counters - Basic (2.0)",
    "TA Health Check -- Client Performance Counters - Basic (2.0)",
)
TASKS = (
    CONTENT_ROOT
    / "Tasks and Analyses"
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes",
)
SOURCES = (PROJECT / "Utilities" / "query_properties.ps1", *TASKS)
NODE = shutil.which("node")


def _script(source: Path) -> str:
    if source.suffix == ".ps1":
        return source.read_text(encoding="utf-8")
    return ET.parse(source).getroot().findtext(".//ActionScript") or ""


def _predicates(source: Path) -> list[str]:
    script = _script(source)
    marker = "set of bes properties whose ("
    predicates = []
    offset = 0
    while (found := script.find(marker, offset)) >= 0:
        start = found + len(marker)
        end, depth, quoted = start, 1, False
        while depth:
            char = script[end]
            if char == '"':
                quoted = not quoted
            elif not quoted:
                depth += (char == "(") - (char == ")")
            end += 1
        predicate = script[start : end - 1]
        if '"Platform Health Check -' in predicate:
            predicates.append(predicate)
        offset = end
    assert predicates
    return predicates


def _select(predicate: str, catalog: list[dict]) -> list[str]:
    """Resolve the name/source/site constraints against a known inspector catalog."""
    names = set(re.findall(r'"(Platform Health Check -[^\"]+)"', predicate))
    source = re.search(r'name of source analysis of it = "([^\"]+)"', predicate)
    site = re.search(r'name of site of source analysis of it = "([^\"]+)"', predicate)
    return sorted(
        prop["id"]
        for prop in catalog
        if prop["name"] in names
        and (source is None or prop["analysis"] == source.group(1))
        and (site is None or prop["site"] == site.group(1))
    )


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
@pytest.mark.parametrize("site", ["actionsite", "Renamed Lab Site", "TA Health Check"])
def test_properties_select_only_the_current_product_with_all_analyses_present(
    source, site
):
    for predicate in _predicates(source):
        name = re.search(r'"(Platform Health Check -[^\"]+)"', predicate).group(1)
        catalog = [
            {"id": title, "name": name, "analysis": title, "site": site}
            for title in PRODUCT_TITLES
        ]
        assert _select(predicate, catalog) == [ANALYSIS_TITLE], predicate


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_missing_product_never_falls_back_to_another_products_values(source):
    for predicate in _predicates(source):
        name = re.search(r'"(Platform Health Check -[^\"]+)"', predicate).group(1)
        catalog = [
            {"id": title, "name": name, "analysis": title, "site": "actionsite"}
            for title in PRODUCT_TITLES
            if title != ANALYSIS_TITLE
        ]
        assert _select(predicate, catalog) == [], predicate


@pytest.mark.parametrize("source", SOURCES, ids=lambda path: path.name)
def test_duplicate_copies_of_the_current_analysis_remain_detectable(source):
    for predicate in _predicates(source):
        name = re.search(r'"(Platform Health Check -[^\"]+)"', predicate).group(1)
        catalog = [
            {
                "id": "first",
                "name": name,
                "analysis": ANALYSIS_TITLE,
                "site": "actionsite",
            },
            {
                "id": "second",
                "name": name,
                "analysis": ANALYSIS_TITLE,
                "site": "Other Site",
            },
        ]
        assert _select(predicate, catalog) == ["first", "second"], predicate


ACTIVATION_RUNNER = r"""
const fs = require('fs');
const vm = require('vm');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const context = {
    EvaluateRelevance: query => {
        const name = query.match(/name of it = "([^"]+)"/);
        const contains = query.match(/name of it contains "([^"]+)"/);
        const site = query.match(/name of it = "([^"]+)"\)\s*$/);
        const scoped = query.includes('of bes sites whose');
        const found = input.analyses.filter(a =>
            (!query.includes('analysis flag of it') || a.analysis) &&
            (!name || a.name === name[1]) &&
            (!contains || a.name.includes(contains[1])) &&
            (!scoped || !site || a.site === site[1]) &&
            (!query.includes('custom site flag of it') || a.custom) &&
            (!query.includes('active flag of it') || a.active)
        );
        return (query.includes('number of bes fixlets') ? found.length > 1 : found.length > 0) ? 'True' : 'False';
    }
};
vm.createContext(context);
vm.runInContext(input.assignment, context);
process.stdout.write(JSON.stringify(context[input.variable]));
"""


def _evaluate(task: Path, analyses: list[dict], variable: str) -> bool:
    description = ET.parse(task).getroot().findtext(".//Description") or ""
    assignment = re.search(
        rf"var {variable} = EvaluateRelevance\([^\n]+", description
    ).group(0)
    run = subprocess.run(
        [NODE, "-e", ACTIVATION_RUNNER],
        input=json.dumps(
            {"assignment": assignment, "analyses": analyses, "variable": variable}
        ),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(run.stdout) == "True"


def _active(task: Path, analyses: list[dict]) -> bool:
    return _evaluate(task, analyses, "isAgentPerformanceBasicActive")


def _duplicates(task: Path, analyses: list[dict]) -> bool:
    return _evaluate(task, analyses, "hasDuplicateAgentPerformanceBasicAnalyses")


def _analyses(site="actionsite") -> list[dict]:
    return [
        {
            "name": title,
            "active": True,
            "analysis": True,
            "site": site,
            "custom": site != "actionsite",
        }
        for title in PRODUCT_TITLES
    ]


@pytest.mark.skipif(NODE is None, reason="Node is required to execute task JavaScript")
@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.name)
@pytest.mark.parametrize("site", ["actionsite", "Renamed Lab Site", "TA Health Check"])
def test_all_three_analyses_active_are_recognized_regardless_of_site(task, site):
    assert _active(task, _analyses(site))


@pytest.mark.skipif(NODE is None, reason="Node is required to execute task JavaScript")
@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.name)
@pytest.mark.parametrize(
    "condition", ["inactive", "missing", "renamed", "older_version", "not_analysis"]
)
def test_other_active_products_cannot_satisfy_the_current_analysis_check(task, condition):
    analyses = _analyses()
    target = next(a for a in analyses if a["name"] == ANALYSIS_TITLE)
    if condition == "inactive":
        target["active"] = False
    elif condition == "missing":
        analyses.remove(target)
    elif condition == "renamed":
        target["name"] = "Renamed Client Analysis"
    elif condition == "older_version":
        target["name"] = target["name"].replace("(2.0)", "(1.0)")
    else:
        target["analysis"] = False
    assert not _active(task, analyses)


@pytest.mark.skipif(NODE is None, reason="Node is required to execute task JavaScript")
@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.name)
@pytest.mark.parametrize("site", ["actionsite", "Renamed Lab Site", "TA Health Check"])
def test_other_products_active_do_not_trigger_the_duplicate_warning(task, site):
    assert not _duplicates(task, _analyses(site))


@pytest.mark.skipif(NODE is None, reason="Node is required to execute task JavaScript")
@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.name)
@pytest.mark.parametrize("duplicate_active", [False, True])
def test_duplicate_copy_of_own_analysis_is_detected_across_sites(task, duplicate_active):
    analyses = _analyses()
    own = next(a for a in analyses if a["name"] == ANALYSIS_TITLE)
    analyses.append({**own, "site": "Another Custom Site", "active": duplicate_active})
    assert _duplicates(task, analyses)


@pytest.mark.skipif(NODE is None, reason="Node is required to execute task JavaScript")
@pytest.mark.parametrize("task", TASKS, ids=lambda path: path.name)
def test_many_activation_records_for_one_analysis_are_not_duplicate_copies(task):
    analyses = _analyses()
    own = next(a for a in analyses if a["name"] == ANALYSIS_TITLE)
    own["activations"] = [False, False, True, True]
    assert not _duplicates(task, analyses)
