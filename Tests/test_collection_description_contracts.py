# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "Tasks and Analyses" / "Individual Tasks"
FILES = {
    "agent": "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes",
    "filldb": "BigFix Master Class -- Enable FillDB Performance Logging (2.0).bes",
}
STUBS = """() => {
    window.calls = []; window.dialogs = [];
    window.scenario = {master: true, windows: true, busy: false};
    window.EvaluateRelevance = q => {
        if (q === 'master flag of current console user') return scenario.master ? 'True' : 'False';
        if (q === 'host name of root server') return 'root.example.invalid';
        if (q.includes('operating system of it starts with')) return scenario.windows ? 'True' : 'False';
        if (q.includes('exists bes action')) return scenario.busy ? 'True' : 'False';
        if (q.includes('analysis flag') || q.includes('exists activations')) return 'True';
        throw new Error('Unexpected relevance: ' + q);
    };
    window.Relevance = q => {
        if (q === 'id of current fixlet') return 101;
        if (q === 'id of current bes site') return 202;
        throw new Error('Unexpected relevance: ' + q);
    };
    window.TakeSecureFixletAction = (...args) => calls.push(args);
    window.TakeFixletAction = () => { throw new Error('Credentials must use secure parameters'); };
    window.alert = message => dialogs.push(message);
    window.confirm = message => { dialogs.push(message); return false; };
}"""


def description(key):
    return ET.parse(TASKS / FILES[key]).getroot()[0].findtext("Description")


class ElementIds(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.ids.extend(value for name, value in attrs if name == "id")


@pytest.mark.parametrize("key", FILES)
def test_literal_javascript_dom_lookups_resolve(key):
    html = description(key)
    ids = ElementIds(html).ids
    lookups = re.findall(r"getElementById\(\s*['\"]([^'\"]+)['\"]\s*\)", html)
    assert len(ids) == len(set(ids)), "Duplicate description element IDs"
    assert lookups
    assert set(lookups) <= set(ids)


@pytest.fixture(scope="module")
def browser():
    if os.environ.get("WORKBENCH_RUN_E2E") != "1" or sys.platform != "win32":
        pytest.skip(
            "Set WORKBENCH_RUN_E2E=1 on Windows for offline Edge description checks"
        )
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="msedge", headless=True)
        yield browser
        browser.close()


@pytest.fixture
def page(browser, tmp_path):
    context = browser.new_context(viewport={"width": 1280, "height": 1000})
    context.route("**/*", lambda route: route.abort())
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    yield page
    try:
        evidence = page.evaluate("() => ({calls, dialogs})")
        evidence.update(page_errors=errors, browser_version=browser.version)
        (tmp_path / "browser.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        page.screenshot(path=str(tmp_path / "description.png"), full_page=True)
        assert not errors
    finally:
        context.close()


def load(page, key):
    page.goto("about:blank")
    page.evaluate(STUBS)
    page.set_content("<!doctype html><html><body>" + description(key) + "</body></html>")
    fill_credentials(page, key)
    if key == "filldb":
        page.locator("#fillDBPerfLogsSizeMB").fill("500")
        page.locator("#fillDBPerfLogsDuration").fill("1")


def fill_credentials(page, key):
    username = "apiUserName" if key == "agent" else "apiUsername"
    for element, value in (
        (username, "dummy-mo"),
        ("apiPassword", "dummy-only-password"),
        ("apiPasswordConfirm", "dummy-only-password"),
    ):
        page.locator("#" + element).fill(value)


def invoke(page):
    page.evaluate("calls.length = 0; dialogs.length = 0")
    assert page.evaluate("document.body.ontakeaction({contentID:'Action1'})") is False
    return page.evaluate("calls")


def expected_call(key, **overrides):
    public = {"rootServerName": "root.example.invalid"}
    secure = {"apiUsername": "dummy-mo", "apiPassword": "dummy-only-password"}
    if key == "agent":
        public["generateLogFiles"] = "0"
        public.update(overrides)
    else:
        secure.update(
            fillDBPerfLogsDuration="1",
            fillDBPerfLogsNoDisable=False,
            fillDBPerfLogsSizeMB="500",
            fillDBPerfLogsSizeByte=524288000,
            fillDBPerfLogsSizeNoLimit=False,
        )
        secure.update(overrides)
    return [101, 202, "Action1", public, secure]


@pytest.mark.parametrize("generate_logs", [False, True])
def test_agent_launch_uses_secure_username_and_password(page, generate_logs):
    load(page, "agent")
    page.locator("#generateLogFiles").set_checked(generate_logs)
    assert invoke(page) == [
        expected_call("agent", generateLogFiles="1" if generate_logs else "0")
    ]


def test_filldb_automatic_launch_parameters(page):
    load(page, "filldb")
    assert invoke(page) == [expected_call("filldb")]


def test_filldb_duration_checkbox_round_trip(page):
    load(page, "filldb")
    fields = (
        "apiUsername",
        "apiPassword",
        "apiPasswordConfirm",
        "fillDBPerfLogsDuration",
    )
    page.locator("#fillDBPerfLogsNoDisable").check()
    for field in fields:
        assert page.locator("#" + field).is_disabled()
        assert page.locator("#" + field).input_value() == ""
    assert invoke(page) == [
        expected_call(
            "filldb",
            apiUsername="",
            apiPassword="",
            fillDBPerfLogsDuration="",
            fillDBPerfLogsNoDisable=True,
        )
    ]
    page.locator("#fillDBPerfLogsNoDisable").uncheck()
    for field in fields:
        assert page.locator("#" + field).is_enabled()
        assert page.locator("#" + field).input_value() == ""
    assert invoke(page) == []
    assert page.evaluate("dialogs.length") > 0
    fill_credentials(page, "filldb")
    page.locator("#fillDBPerfLogsDuration").fill("1")
    assert invoke(page) == [expected_call("filldb")]


@pytest.mark.parametrize("manual_disable", [False, True])
def test_filldb_nonwindows_root_cannot_launch(page, manual_disable):
    load(page, "filldb")
    page.locator("#fillDBPerfLogsNoDisable").set_checked(manual_disable)
    page.evaluate("scenario.windows = false")
    assert invoke(page) == []
    assert page.evaluate("dialogs") == [
        "This task can only be run on Windows-based BigFix root servers"
    ]


@pytest.mark.parametrize("key", FILES)
@pytest.mark.parametrize(
    "guard", ["nonmaster", "busy", "blank_username", "password_mismatch"]
)
def test_launch_guards_still_block(page, key, guard):
    load(page, key)
    if guard == "nonmaster":
        page.evaluate("scenario.master = false")
    elif guard == "busy":
        page.evaluate("scenario.busy = true")
    elif guard == "blank_username":
        page.locator("#apiUserName" if key == "agent" else "#apiUsername").fill("")
    else:
        page.locator("#apiPasswordConfirm").fill("different")
    assert invoke(page) == []
    assert page.evaluate("dialogs.length") > 0
