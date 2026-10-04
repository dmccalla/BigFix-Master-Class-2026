# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Contracts for the ten deployment queries verified through Session Relevance."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import quote, unquote

import pytest
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
LOCAL_TASKS = ROOT / "Tasks and Analyses"
LOCAL_COLLECTORS = (
    LOCAL_TASKS
    / "Individual Tasks"
    / "BigFix Master Class -- Collect Deployment Information (2.0).bes",
)


def test_local_collectors_are_discovered_independent_of_checkout_name() -> None:
    assert LOCAL_COLLECTORS
    assert all(path.is_relative_to(LOCAL_TASKS) for path in LOCAL_COLLECTORS)
    assert all(path.is_file() for path in LOCAL_COLLECTORS)


# Exact expressions preserve labels, source sets, zero fallbacks, and tuple order.
EXPECTED = {
    "Using Efficient MIME": (
        "generalInfoFileXML",
        '"Using Efficient MIME?: " & ((not exists bes deployment options "usePre70ClientCompatibleMIME" AND not exists value of bes deployment options "usePre70ClientCompatibleMIME") as string)',
    ),
    "Maximum Number of Clients per Relay": (
        "relayServerInfoFileXML",
        '"Maximum Number of Clients per Relay: " & ((if (exists results whose (exists value of it and value of it != "BES Root Server") of bes properties "Relay" whose (reserved flag of it)) then (maximum of multiplicities of unique values of values of results whose (exists value of it and value of it != "BES Root Server") of bes properties "Relay" whose (reserved flag of it)) else 0) as string)',
    ),
    "Minimum Number of Clients per Relay": (
        "relayServerInfoFileXML",
        '"Minimum Number of Clients per Relay: " & ((if (exists results whose (exists value of it and value of it != "BES Root Server") of bes properties "Relay" whose (reserved flag of it)) then (minimum of multiplicities of unique values of values of results whose (exists value of it and value of it != "BES Root Server") of bes properties "Relay" whose (reserved flag of it)) else 0) as string)',
    ),
    "Number of Clients with Unknown Relay Distance": (
        "relayServerInfoFileXML",
        '"Number of Clients with Unknown Relay Distance: " & (number of results whose (error flag of it) of bes properties "Distance to BES Relay" whose (reserved flag of it)) as string',
    ),
    "Average Number of Computers Managed by Non-Master Operators": (
        "operatorInfoFileXML",
        '"Average Number of Computers Managed by Non-Master Operators: " & ((if (exists bes users whose (not master flag of it) ) then ( mean of (if (exists administered computers of it) then (number of administered computers of it) else 0) of bes users whose (not master flag of it) as integer) else 0) as string)',
    ),
    "Number of Bes Roles": (
        "operatorInfoFileXML",
        '"Number of Bes Roles: " & (number of bes roles as string)',
    ),
    "Average number of Components per Baselines": (
        "contentInfoFileXML",
        '"Average number of Components per Baselines: " & ((if (exists bes fixlets whose (baseline flag of it)) then (mean of (number of components of component groups of it) of bes fixlets whose (baseline flag of it) as integer) else 0) as string)',
    ),
    "Maximum Number of Components per Baseline": (
        "contentInfoFileXML",
        '"Maximum Number of Components per Baseline: " & ((if (exists bes fixlets whose (baseline flag of it)) then (maximum of (number of components of component groups of it) of bes fixlets whose (baseline flag of it)) else 0) as string)',
    ),
    "Number of Master Operator Fixlets": (
        "contentInfoFileXML",
        '"Number of Master Operator Fixlets: " & number of bes fixlets whose (fixlet flag of it and master flag of issuer of it) as string',
    ),
    "Number of Master Operator Tasks": (
        "contentInfoFileXML",
        '"Number of Master Operator Tasks: " & number of bes fixlets whose (task flag of it and master flag of issuer of it) as string',
    ),
    "Total Number of Master Operator Fixlets and Tasks": (
        "contentInfoFileXML",
        '"Total Number of Master Operator Fixlets and Tasks: " & number of bes fixlets whose ((fixlet flag of it OR task flag of it) AND master flag of issuer of it) as string',
    ),
    "Total Number of Master Operator Analyses": (
        "contentInfoFileXML",
        '"Total Number of Master Operator Analyses: " & number of bes fixlets whose (analysis flag of it AND master flag of issuer of it) as string',
    ),
    "external_sites": (
        "contentInfoFileXML",
        '(display name of it,version of it as string,number of subscribed computers of it as string,(if exists modification times of fixlets whose (exist modification time of it) of it then (maximum of modification times of fixlets whose (exist modification time of it) of it) as string else "Not Reported"),url of it) of unique values of  sites of bes fixlets whose (NOT (Custom Flag of it) AND (NOT (custom site flag of it)) AND (NOT (operator site flag of it)))',
    ),
    "property_heading": (
        "propertyInfoFileXML",
        '("//===== Custom BES Properties with frequent evaluations (sub 15 minutes) ================")',
    ),
}


def _queries(path: Path) -> list[tuple[str, str, str]]:
    root = ET.parse(path).getroot()
    found = []
    for node in root.iter("ActionScript"):
        for line in (node.text or "").splitlines():
            if line.lstrip().startswith("//"):
                continue
            match = re.search(
                r'GET query --relevance=(\S+)\s+>>?\s+\{parameter "([^"]+)"\}',
                line,
            )
            if match:
                encoded, capture = match.groups()
                found.append((capture, unquote(encoded), encoded))
    return found


def _selected(path: Path, key: str) -> list[tuple[str, str]]:
    capture, _ = EXPECTED[key]
    marker = {
        "external_sites": "(display name of it,version of it as string,",
        "property_heading": "Custom BES Properties with frequent evaluations",
        "Number of Master Operator Fixlets": '"Number of Master Operator Fixlets: "',
        "Number of Master Operator Tasks": '"Number of Master Operator Tasks: "',
        "Total Number of Master Operator Fixlets and Tasks": '"Total Number of Master Operator Fixlets and Tasks: "',
        "Total Number of Master Operator Analyses": '"Total Number of Master Operator Analyses: "',
    }.get(key, key)
    return [
        (query, encoded)
        for target, query, encoded in _queries(path)
        if target == capture and marker in query
    ]


@pytest.mark.parametrize("path", LOCAL_COLLECTORS, ids=lambda path: path.stem)
@pytest.mark.parametrize("key", EXPECTED)
def test_decoded_query_preserves_metric_and_capture_contract(
    path: Path, key: str
) -> None:
    selected = _selected(path, key)
    assert len(selected) == 1, (path, key, selected)
    query, encoded = selected[0]
    assert query == EXPECTED[key][1]
    assert query.isascii()
    assert quote(query, safe="") == encoded


@pytest.mark.parametrize("path", LOCAL_COLLECTORS, ids=lambda path: path.stem)
def test_external_site_timestamp_keeps_a_nonblank_fourth_column(path: Path) -> None:
    query = _selected(path, "external_sites")[0][0]
    assert query.startswith(
        "(display name of it,version of it as string,"
        "number of subscribed computers of it as string,"
    )
    assert 'else "Not Reported"),url of it)' in query
    assert 'else ""' not in query
    assert (
        "if exists modification times of fixlets whose (exist modification time of it) of it"
        " then (maximum of modification times of fixlets whose (exist modification time of it)"
        " of it) as string"
    ) in query


# Fingerprints cover original decoded strings, capture destinations, and order.
# Parentheses are excluded so wrappers cannot silently change headings or spacers.
LITERAL_CAPTURE_CONTRACTS = {
    "Individual Tasks": (
        110,
        "fb354a3f291ccd7e6afece9fc3a30a8631a515111448df560655ac7963c30063",
    ),
}
DEPLOYMENT_CAPTURE_TARGETS = {
    "generalInfoFileXML",
    "rootServerInfoFileXML",
    "relayServerInfoFileXML",
    "relayAffiliationInfoFileXML",
    "clientInfoFileXML",
    "clientSettingsInfoFileXML",
    "operatorInfoFileXML",
    "contentInfoFileXML",
    "propertyInfoFileXML",
    "actionInfoFileXML",
}


@pytest.mark.parametrize("path", LOCAL_COLLECTORS, ids=lambda path: path.stem)
def test_no_bare_string_literal_reaches_get_query(path: Path) -> None:
    bare = [
        (capture, query)
        for capture, query, _ in _queries(path)
        if capture in DEPLOYMENT_CAPTURE_TARGETS and re.fullmatch(r'"[^"]*"', query)
    ]
    assert not bare, bare


@pytest.mark.parametrize("path", LOCAL_COLLECTORS, ids=lambda path: path.stem)
def test_literal_text_destinations_and_order_are_unchanged(path: Path) -> None:
    literals = [
        (capture, query[1:-1])
        for capture, query, encoded in _queries(path)
        if capture in DEPLOYMENT_CAPTURE_TARGETS and re.fullmatch(r'\("[^"]*"\)', query)
    ]
    expected_count, expected_digest = LITERAL_CAPTURE_CONTRACTS[path.parent.name]
    assert len(literals) == expected_count
    payload = "".join(f"{capture}\t{query}\n" for capture, query in literals)
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == expected_digest
