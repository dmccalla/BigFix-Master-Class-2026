# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Preserve collected evidence while reducing deployment API load."""

import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from defusedxml import ElementTree as ET

ROOT = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "Tasks and Analyses").is_dir()
)
TASK = next(
    (ROOT / "Tasks and Analyses/Individual Tasks").glob(
        "* -- Collect Deployment Information (2.0).bes"
    )
)


def _script():
    return ET.parse(TASK).findtext(".//ActionScript")


def test_real_api_queries_are_unchanged_and_literals_do_not_reach_server():
    commands = [
        line
        for line in _script().splitlines()
        if line.startswith("waithidden ") and " -Mode Request -Resource query " in line
    ]
    entries = [
        re.search(
            r'-EncodedRelevance "(\S+)" -Capture "\{parameter "([^"\n]+)"\}"', line
        ).groups()
        for line in commands
    ]
    assert len(entries) == 177
    assert (
        hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode()).hexdigest()
        == "7d5b45bfcee38654ef4cfcac19e99447937a8b9b86d45e01afb7b3b30607c675"
    )
    assert not any(
        re.fullmatch(r'\("[^"]*"\)', unquote(encoded)) for encoded, _ in entries
    )


def test_each_real_api_request_retains_its_pause_and_local_text_has_none():
    lines = _script().splitlines()
    requests = [
        i
        for i, line in enumerate(lines)
        if line.startswith("waithidden ") and " -Mode Request " in line
    ]
    pauses = [
        i
        for i, line in enumerate(lines)
        if line.startswith("waithidden ") and "ping -n" in line
    ]
    assert len(requests) == 179
    assert pauses == [i + 4 for i in requests]


def test_default_pause_is_five_in_ui_and_action_fallback():
    class Inputs(HTMLParser):
        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            if tag == "input" and values.get("id") == "queryDelaySeconds":
                self.value = values.get("value")

    parser = Inputs()
    parser.feed(ET.parse(TASK).findtext(".//Description"))
    assert parser.value == "5"
    assert 'as string else "5"}' in _script()


def test_local_client_results_are_captured_before_optional_log_conversion():
    script = _script()
    assert script.count("// Local client relevance capture.") == 13
    assert 'waithidden cmd.exe /C echo {"Actionsite Size:' not in script
    assert not re.search(
        r'^waithidden .*echo.*>>.*parameter "rootServerInfoFile"', script, re.M
    )
    for capture, count in (("generalInfoFile", 1), ("rootServerInfoFile", 12)):
        conversion = script.index('delete "{parameter "' + capture + '"}"')
        local_blocks = list(
            re.finditer(
                r"^// Local client relevance capture\.\n(.*?)^waithidden cmd.exe /C type __createfile >> [^\n]+",
                script,
                re.M | re.S,
            )
        )
        selected = [
            m for m in local_blocks if 'parameter "' + capture + 'XML"' in m.group()
        ]
        assert len(selected) == count
        assert all(m.start() < conversion for m in selected)


def test_all_local_fragments_are_complete_besapi_documents():
    script = _script()
    fragments = re.findall(
        r"^createfile until DI_LOCAL_XML_EOF\n(.*?)\nDI_LOCAL_XML_EOF",
        script,
        re.M | re.S,
    )
    assert len(fragments) == 126
    for block in fragments:
        xml = "\n".join(line.removeprefix("appendfile ") for line in block.splitlines())
        # Client relevance is evaluated by the lab client, not by this offline check.
        xml = re.sub(
            r'(<Answer type="string">)\{.*\}(</Answer>)',
            r"\1Client &amp; relevance &lt;value&gt;\2",
            xml,
        )
        document = ET.fromstring(xml)
        assert document.tag == "BESAPI"
        assert len(document.findall("./Query/Result/Answer")) == 1
        assert (
            document.findtext("./Query/Evaluation/Time")
            == "Not applicable: local capture"
        )
        assert document.findtext("./Query/Evaluation/Plurality") == "Singular"


def test_fatal_helper_codes_are_checked_before_pacing_can_overwrite_them():
    lines = _script().splitlines()
    helpers = [
        i
        for i, line in enumerate(lines)
        if line.startswith("waithidden powershell.exe ")
        and '-File "{parameter "diRequestHelper"}"' in line
    ]
    assert len(helpers) == 182  # init, login, 179 requests, finish
    assert all(
        lines[i + 1 : i + 4]
        == ["if {exit code of action != 0}", "exit {exit code of action}", "endif"]
        for i in helpers
    )
    assert ET.parse(TASK).find(".//SuccessCriteria").get("Option") == "RunToCompletion"
    assert lines[-1] == "exit 0" or lines[-2] == "exit 0"


def test_helper_parent_folder_is_recreated_after_the_existing_tools_cleanup():
    script = _script()
    cleanup = script.index('rd /s /q "{parameter "toolsFolder"}"')
    create = script.index('folder create "{parameter "toolsFolder"}"')
    write = script.index('move __createfile "{parameter "diRequestHelper"}"')
    assert cleanup < create < write
