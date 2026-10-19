#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Maintainer-only controlled lab test runtime
# Standalone utility: retain this notice when copying this file outside the repository.
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Run guarded logging-task tests against a dedicated BigFix lab.

The harness has three modes:

* ``plan`` validates the configuration and task XML without using the network.
* ``check`` verifies API access, target identity, and client preconditions.
* ``run`` imports temporary task copies, launches narrowly targeted actions,
  polls their results, and evaluates client-context relevance assertions.

``run`` is intentionally difficult to invoke accidentally. The caller must pass
``--execute`` and repeat the configured server hostname with ``--confirm-server``.
Every target computer ID must also be present in the configuration allowlist.

Credentials are read only from environment variables. ``BIGFIX_TOKEN`` is
preferred. ``BIGFIX_USERNAME`` and ``BIGFIX_PASSWORD`` provide a Basic Auth
fallback for older BigFix versions.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import ssl
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib import error, parse, request
from xml.etree import ElementTree as ET

REPO_ROOT = Path(__file__).resolve().parents[1]
TERMINAL_ACTION_STATES = {
    "cancelled",
    "completed",
    "constrained",
    "download failed",
    "error",
    "expired",
    "failed",
    "fixed",
    "invalid signature",
    "not relevant",
    "stopped",
}
SUCCESS_ACTION_STATES = {"completed", "fixed"}


class HarnessError(RuntimeError):
    """A configuration, API, or assertion failure."""


class AmbiguousRequestError(HarnessError):
    """A non-retried write may have reached BigFix before its response was lost."""


@dataclass
class HTTPResult:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class AssertionResult:
    name: str
    query: str
    expected: str
    actual: str
    passed: bool


@dataclass
class StepResult:
    name: str
    task_file: str = ""
    task_sha256: str = ""
    content_type: str = ""
    content_id: int | None = None
    action_id: int | None = None
    action_state: str = ""
    generated_action_id: int | None = None
    generated_action_state: str = ""
    forbidden_generated_action_verified: bool = False
    assertions: list[AssertionResult] = field(default_factory=list)


@dataclass
class ScenarioResult:
    name: str
    computer_id: int
    passed: bool = False
    error: str = ""
    preconditions: list[AssertionResult] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)


Transport = Callable[[str, str, bytes | None, dict[str, str]], HTTPResult]


def _artifact_identity(path: Path) -> tuple[str, str]:
    resolved = path.resolve()
    relative = resolved.relative_to(REPO_ROOT.resolve()).as_posix()
    digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    return relative, digest


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _element_text(element: ET.Element, name: str) -> str | None:
    for child in element.iter():
        if _local_name(child.tag) == name and child.text is not None:
            return child.text.strip()
    return None


def extract_resource_id(payload: bytes | str, resource_name: str) -> int:
    """Extract a task, action, or query ID from common BES API responses."""
    text = (
        payload.decode("utf-8", errors="replace")
        if isinstance(payload, bytes)
        else payload
    )
    stripped = text.strip()
    if stripped.isdigit():
        return int(stripped)

    try:
        root = ET.fromstring(stripped)
    except ET.ParseError as exc:
        raise HarnessError(
            f"The API returned invalid XML for {resource_name}: {exc}"
        ) from exc

    for element in root.iter():
        if _local_name(element.tag).lower() == resource_name.lower():
            value = _element_text(element, "ID")
            if value and value.isdigit():
                return int(value)
            resource = element.attrib.get("Resource", "")
            match = re.search(r"/(\d+)(?:[/?#]|$)", resource)
            if match:
                return int(match.group(1))

    for element in root.iter():
        value = element.attrib.get("Resource", "")
        match = re.search(r"/(\d+)(?:[/?#]|$)", value)
        if match:
            return int(match.group(1))

    ids = [
        (element.text or "").strip()
        for element in root.iter()
        if _local_name(element.tag) == "ID"
    ]
    numeric = [int(value) for value in ids if value.isdigit()]
    if len(numeric) == 1:
        return numeric[0]
    raise HarnessError(f"The API response did not contain a {resource_name} ID")


def build_sourced_action_xml(
    site_name: str,
    task_id: int,
    computer_id: int,
    parameters: dict[str, str],
    secure_parameters: dict[str, str],
    action_name: str = "Action1",
) -> bytes:
    root = ET.Element(
        "BES",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "BES.xsd",
        },
    )
    sourced = ET.SubElement(root, "SourcedFixletAction")
    source = ET.SubElement(sourced, "SourceFixlet")
    ET.SubElement(source, "Sitename").text = site_name
    ET.SubElement(source, "FixletID").text = str(task_id)
    ET.SubElement(source, "Action").text = action_name
    target = ET.SubElement(sourced, "Target")
    ET.SubElement(target, "ComputerID").text = str(computer_id)
    for name, value in sorted(parameters.items()):
        ET.SubElement(sourced, "Parameter", {"Name": name}).text = str(value)
    for name, value in sorted(secure_parameters.items()):
        ET.SubElement(sourced, "SecureParameter", {"Name": name}).text = str(value)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def build_client_query_xml(computer_id: int, relevance: str) -> bytes:
    root = ET.Element(
        "BESAPI",
        {
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:noNamespaceSchemaLocation": "BESAPI.xsd",
        },
    )
    query = ET.SubElement(root, "ClientQuery")
    ET.SubElement(query, "ApplicabilityRelevance").text = "true"
    ET.SubElement(query, "QueryText").text = relevance
    ET.SubElement(query, "UseClientContext").text = "true"
    target = ET.SubElement(query, "Target")
    ET.SubElement(target, "ComputerID").text = str(computer_id)
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def content_type(payload: bytes | str) -> str:
    """Return Task or Fixlet for a single deployable BES XML document."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise HarnessError(f"Content XML is not well formed: {exc}") from exc
    kinds = [
        _local_name(element.tag)
        for element in root
        if _local_name(element.tag) in {"Task", "Fixlet"}
    ]
    if len(kinds) != 1:
        raise HarnessError(f"Expected one Task or Fixlet in BES XML, found {len(kinds)}")
    return kinds[0]


def clone_content_xml(path: Path, suffix: str) -> bytes:
    """Return a temporary task/fixlet copy with a clearly marked title."""
    raw = path.read_text(encoding="utf-8-sig")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise HarnessError(f"Task XML is not well formed: {path}: {exc}") from exc
    contents = [
        element for element in root if _local_name(element.tag) in {"Task", "Fixlet"}
    ]
    if len(contents) != 1:
        raise HarnessError(
            f"Expected one Task or Fixlet in {path}, found {len(contents)}"
        )
    title = next(
        (child for child in contents[0] if _local_name(child.tag) == "Title"), None
    )
    if title is None or not (title.text or "").strip():
        raise HarnessError(f"Task has no title: {path}")
    old_title = title.text or ""
    title.text = f"{old_title} [AUTOTEST {suffix}]"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


# Backward-compatible name for callers that only need to clone a Task.
clone_task_xml = clone_content_xml


def _parse_action_state(
    payload: bytes, computer_id: int, *, success_state: str = "Fixed"
) -> str:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise HarnessError(f"Action status response is invalid XML: {exc}") from exc

    for computer in root.iter():
        if _local_name(computer.tag) != "Computer":
            continue
        candidate = computer.attrib.get("ID") or _element_text(computer, "ID")
        if candidate != str(computer_id):
            continue
        status = _element_text(computer, "Status") or ""
        state = _element_text(computer, "State") or ""
        normalized = _normalize_action_state(status, state, success_state=success_state)
        if normalized:
            return normalized

    for key in ("Status", "State"):
        value = _element_text(root, key)
        if value:
            return value
    return "Pending"


def _normalize_action_state(
    status: str, state: str, *, success_state: str = "Fixed"
) -> str:
    """Normalize BigFix's human-readable REST status into harness states."""
    lowered = status.strip().lower()
    if "executed successfully" in lowered:
        return success_state
    if "not relevant" in lowered:
        return "Not Relevant"
    if "failed" in lowered:
        return "Failed"
    if "not reported" in lowered or "not yet reported" in lowered:
        return "Pending"

    canonical = {
        "cancelled": "Cancelled",
        "constrained": "Constrained",
        "error": "Error",
        "expired": "Expired",
        "failed": "Failed",
        "fixed": "Fixed",
        "not relevant": "Not Relevant",
        "stopped": "Stopped",
    }
    if lowered in canonical:
        return canonical[lowered]

    state_fallback = {"3": success_state, "4": "Failed"}
    return state_fallback.get(state.strip(), status.strip())


def _parse_client_query_result(
    payload: bytes, computer_id: int
) -> tuple[bool, str] | None:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise HarnessError(f"Client query response is invalid XML: {exc}") from exc
    for result in root.iter():
        if _local_name(result.tag) != "QueryResult":
            continue
        candidate = _element_text(result, "ComputerID")
        if candidate != str(computer_id):
            continue
        failed = (_element_text(result, "IsFailure") or "0") not in {
            "0",
            "false",
            "False",
        }
        return failed, _element_text(result, "Result") or ""
    return None


class BigFixAPI:
    """Small standard-library client for the BigFix REST endpoints used here."""

    def __init__(
        self,
        server_url: str,
        *,
        token: str = "",
        username: str = "",
        password: str = "",
        verify_tls: bool = True,
        timeout_seconds: int = 60,
        transport: Transport | None = None,
    ) -> None:
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        if token:
            self.authorization = f"Bearer {token}"
        elif username and password:
            encoded = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
            self.authorization = f"Basic {encoded}"
        else:
            raise HarnessError(
                "Set BIGFIX_TOKEN, or set both BIGFIX_USERNAME and BIGFIX_PASSWORD."
            )
        self.ssl_context = ssl.create_default_context()
        if not verify_tls:
            self.ssl_context = ssl._create_unverified_context()  # noqa: SLF001

    def _request(
        self,
        method: str,
        path: str,
        body: bytes | None = None,
        *,
        content_type: str = "application/xml",
        accept: str = "application/xml",
    ) -> HTTPResult:
        headers = {
            "Accept": accept,
            "Authorization": self.authorization,
            "User-Agent": "BigFix-Health-Check-Logging-Test-Harness/2.0",
        }
        if body is not None:
            headers["Content-Type"] = content_type
        if self.transport is not None:
            result = self.transport(method, path, body, headers)
            if not 200 <= result.status < 300:
                raise HarnessError(
                    f"BigFix API {method} {path} returned HTTP {result.status}"
                )
            return result

        req = request.Request(
            f"{self.server_url}{path}", data=body, headers=headers, method=method
        )
        retryable = method == "GET" or (method == "POST" and path == "/api/query")
        attempts = 4 if retryable else 1
        for attempt in range(1, attempts + 1):
            try:
                with request.urlopen(  # noqa: S310 - explicit BigFix API client
                    req, timeout=self.timeout_seconds, context=self.ssl_context
                ) as response:
                    return HTTPResult(
                        status=response.status,
                        body=response.read(),
                        headers=dict(response.headers.items()),
                    )
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip()
                if len(detail) > 1000:
                    detail = detail[:1000] + "..."
                raise HarnessError(
                    f"BigFix API {method} {path} returned HTTP {exc.code}: {detail}"
                ) from exc
            except (error.URLError, OSError, TimeoutError) as exc:
                if attempt < attempts:
                    delay = min(2**attempt, 10)
                    print(
                        f"      WARN BigFix API {method} {path} connection "
                        f"interrupted; retrying in {delay}s ({attempt}/{attempts})"
                    )
                    time.sleep(delay)
                    continue
                reason = getattr(exc, "reason", exc)
                exception_type = (
                    AmbiguousRequestError
                    if method == "POST" and not retryable
                    else HarnessError
                )
                raise exception_type(
                    f"BigFix API {method} {path} failed after {attempts} "
                    f"attempt(s): {reason}"
                ) from exc

        raise HarnessError(f"BigFix API {method} {path} failed unexpectedly")

    def session_query(self, relevance: str) -> list[Any]:
        # Use the ordinary API route, matching the collector and supporting normal engine selection.
        payload = parse.urlencode({"relevance": relevance, "output": "json"}).encode(
            "utf-8"
        )
        result = self._request(
            "POST",
            "/api/query",
            payload,
            content_type="application/x-www-form-urlencoded",
            accept="application/json",
        )
        try:
            parsed = json.loads(result.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HarnessError(f"Session relevance returned invalid JSON: {exc}") from exc
        if "error" in parsed:
            raise HarnessError(f"Session relevance failed: {parsed['error']}")
        values = parsed.get("result", [])
        return values if isinstance(values, list) else [values]

    def import_content(self, site_name: str, content_xml: bytes) -> tuple[str, int]:
        kind = content_type(content_xml)
        site = parse.quote(site_name, safe="")
        collection = "tasks" if kind == "Task" else "fixlets"
        result = self._request("POST", f"/api/{collection}/custom/{site}", content_xml)
        return kind, extract_resource_id(result.body, kind)

    def delete_content(self, site_name: str, kind: str, content_id: int) -> None:
        site = parse.quote(site_name, safe="")
        resource = "task" if kind == "Task" else "fixlet"
        self._request("DELETE", f"/api/{resource}/custom/{site}/{content_id}")

    def launch_task(
        self,
        site_name: str,
        task_id: int,
        computer_id: int,
        parameters: dict[str, str],
        secure_parameters: dict[str, str],
        action_name: str = "Action1",
        *,
        recovery_seconds: int = 30,
        recovery_poll_seconds: float = 2,
    ) -> int:
        xml = build_sourced_action_xml(
            site_name,
            task_id,
            computer_id,
            parameters,
            secure_parameters,
            action_name,
        )
        try:
            result = self._request("POST", "/api/actions", xml)
            return extract_resource_id(result.body, "Action")
        except AmbiguousRequestError as exc:
            if '"' in site_name:
                raise HarnessError(
                    "Cannot recover an interrupted action POST for a site name "
                    "containing a quote"
                ) from exc
            relevance = (
                "ids of bes actions whose (id of source fixlet of it = "
                f'{task_id} and name of site of source fixlet of it = "{site_name}")'
            )
            deadline = time.monotonic() + recovery_seconds
            while True:
                recovered = sorted(
                    int(value)
                    for value in self.session_query(relevance)
                    if str(value).isdigit()
                )
                if len(recovered) == 1:
                    print(
                        "      WARN recovered action "
                        f"{recovered[0]} after its API response was interrupted"
                    )
                    return recovered[0]
                if len(recovered) > 1:
                    raise HarnessError(
                        "Interrupted action POST is ambiguous: temporary task "
                        f"{task_id} sourced actions {', '.join(map(str, recovered))}"
                    ) from exc
                if time.monotonic() >= deadline:
                    raise exc
                time.sleep(recovery_poll_seconds)

    def action_state(
        self,
        action_id: int,
        computer_id: int,
        *,
        success_state: str = "Fixed",
    ) -> str:
        result = self._request("GET", f"/api/action/{action_id}/status")
        return _parse_action_state(result.body, computer_id, success_state=success_state)

    def wait_for_action(
        self,
        action_id: int,
        computer_id: int,
        *,
        timeout_seconds: int,
        poll_seconds: float,
        success_state: str = "Fixed",
    ) -> str:
        deadline = time.monotonic() + timeout_seconds
        last = "Pending"
        while time.monotonic() < deadline:
            last = self.action_state(action_id, computer_id, success_state=success_state)
            if last.lower() in TERMINAL_ACTION_STATES:
                return last
            time.sleep(poll_seconds)
        raise HarnessError(
            f"Action {action_id} did not finish for computer {computer_id}; last state: {last}"
        )

    def delete_action(self, action_id: int) -> None:
        self._request("DELETE", f"/api/action/{action_id}")

    def client_query(
        self,
        computer_id: int,
        relevance: str,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
        result = self._request(
            "POST", "/api/clientquery", build_client_query_xml(computer_id, relevance)
        )
        query_id = extract_resource_id(result.body, "ClientQuery")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            response = self._request("GET", f"/api/clientqueryresults/{query_id}?stats=1")
            parsed = _parse_client_query_result(response.body, computer_id)
            if parsed is not None:
                failed, value = parsed
                if failed:
                    raise HarnessError(
                        f"Client relevance failed on computer {computer_id}: {value}"
                    )
                return value
            time.sleep(poll_seconds)
        raise HarnessError(
            f"Client query {query_id} timed out waiting for computer {computer_id}"
        )


def _required_string(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise HarnessError(f"{context}.{key} must be a non-empty string")
    return value.strip()


def load_config(path: Path) -> dict[str, Any]:
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise HarnessError(f"Cannot read configuration {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise HarnessError(f"Configuration is not valid JSON: {path}: {exc}") from exc
    if not isinstance(config, dict):
        raise HarnessError("Configuration root must be a JSON object")

    server = _required_string(config, "server_url", "config")
    parsed_url = parse.urlsplit(server)
    if parsed_url.scheme != "https" or not parsed_url.hostname:
        raise HarnessError("config.server_url must be an HTTPS URL with a hostname")
    _required_string(config, "site_name", "config")

    allowed = config.get("allowed_computer_ids")
    if (
        not isinstance(allowed, list)
        or not allowed
        or any(not isinstance(value, int) or value <= 0 for value in allowed)
    ):
        raise HarnessError("config.allowed_computer_ids must contain positive integers")
    if len(set(allowed)) != len(allowed):
        raise HarnessError("config.allowed_computer_ids contains duplicates")

    scenarios = config.get("scenarios")
    if not isinstance(scenarios, list) or not scenarios:
        raise HarnessError("config.scenarios must be a non-empty list")
    names: set[str] = set()
    for index, scenario in enumerate(scenarios, 1):
        context = f"scenario[{index}]"
        if not isinstance(scenario, dict):
            raise HarnessError(f"{context} must be an object")
        name = _required_string(scenario, "name", context)
        if name in names:
            raise HarnessError(f"Duplicate scenario name: {name}")
        names.add(name)
        computer_id = scenario.get("computer_id")
        if not isinstance(computer_id, int) or computer_id <= 0:
            raise HarnessError(f"{context}.computer_id must be a positive integer")
        if computer_id not in allowed:
            raise HarnessError(
                f"{context}.computer_id {computer_id} is not in allowed_computer_ids"
            )
        steps = scenario.get("steps")
        if not isinstance(steps, list) or not steps:
            raise HarnessError(f"{context}.steps must be a non-empty list")
        for step_index, step in enumerate(steps, 1):
            step_context = f"{context}.steps[{step_index}]"
            if not isinstance(step, dict):
                raise HarnessError(f"{step_context} must be an object")
            _required_string(step, "name", step_context)
            task_file = REPO_ROOT / _required_string(step, "task_file", step_context)
            if not task_file.is_file():
                raise HarnessError(f"Task file does not exist: {task_file}")
            clone_content_xml(task_file, "PLAN")
    return config


def _env_parameters(mapping: Any, context: str) -> dict[str, str]:
    if mapping is None:
        return {}
    if not isinstance(mapping, dict):
        raise HarnessError(
            f"{context} must be an object mapping parameter names to env vars"
        )
    values: dict[str, str] = {}
    for name, env_name in mapping.items():
        if not isinstance(name, str) or not isinstance(env_name, str):
            raise HarnessError(f"{context} keys and values must be strings")
        value = os.environ.get(env_name)
        if value is None:
            raise HarnessError(f"Required environment variable is not set: {env_name}")
        values[name] = value
    return values


def _literal_parameters(value: Any, context: str) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise HarnessError(f"{context} must be an object")
    return {str(name): str(parameter) for name, parameter in value.items()}


def _evaluate_assertion(actual: str, assertion: dict[str, Any]) -> tuple[bool, str]:
    operators = [
        key
        for key in ("equals", "contains", "not_contains", "matches")
        if key in assertion
    ]
    if len(operators) != 1:
        raise HarnessError(
            "Each assertion must define exactly one of equals, contains, not_contains, or matches"
        )
    operator = operators[0]
    expected = str(assertion[operator])
    if operator == "equals":
        return actual == expected, f"equals {expected!r}"
    if operator == "contains":
        return expected in actual, f"contains {expected!r}"
    if operator == "not_contains":
        return expected not in actual, f"does not contain {expected!r}"
    return re.search(expected, actual) is not None, f"matches /{expected}/"


def run_assertions(
    api: BigFixAPI,
    computer_id: int,
    assertions: Any,
    *,
    timeout_seconds: int,
    poll_seconds: float,
) -> list[AssertionResult]:
    if assertions is None:
        return []
    if not isinstance(assertions, list):
        raise HarnessError("Assertions must be a list")
    results = []
    for index, assertion in enumerate(assertions, 1):
        if not isinstance(assertion, dict):
            raise HarnessError(f"Assertion {index} must be an object")
        name = str(assertion.get("name") or f"assertion {index}")
        query = _required_string(assertion, "query", name)
        actual = api.client_query(
            computer_id,
            query,
            timeout_seconds=timeout_seconds,
            poll_seconds=poll_seconds,
        )
        passed, expected = _evaluate_assertion(actual, assertion)
        result = AssertionResult(name, query, expected, actual, passed)
        results.append(result)
        print(f"      {'PASS' if passed else 'FAIL'} {name}: {actual}")
        if not passed:
            raise HarnessError(
                f"Assertion failed for computer {computer_id}: {name}; "
                f"expected {expected}, got {actual!r}"
            )
    return results


def _find_generated_action(
    api: BigFixAPI,
    *,
    after_action_id: int,
    title_contains: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> int:
    if '"' in title_contains:
        raise HarnessError("generated_action.title_contains cannot contain a quote")
    relevance = (
        "ids of bes actions whose "
        f'(id of it > {after_action_id} and name of it contains "{title_contains}")'
    )
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        values = api.session_query(relevance)
        ids = [int(value) for value in values if str(value).isdigit()]
        if ids:
            return max(ids)
        time.sleep(poll_seconds)
    raise HarnessError(
        f"No generated action containing {title_contains!r} appeared after action {after_action_id}"
    )


def _assert_no_generated_action(
    api: BigFixAPI,
    *,
    after_action_id: int,
    title_contains: str,
    observation_seconds: int,
    poll_seconds: float,
) -> None:
    if '"' in title_contains:
        raise HarnessError(
            "forbidden_generated_action.title_contains cannot contain a quote"
        )
    relevance = (
        "ids of bes actions whose "
        f'(id of it > {after_action_id} and name of it contains "{title_contains}")'
    )
    deadline = time.monotonic() + observation_seconds
    while time.monotonic() < deadline:
        values = api.session_query(relevance)
        ids = [int(value) for value in values if str(value).isdigit()]
        if ids:
            raise HarnessError(
                f"Unexpected generated action {max(ids)} containing {title_contains!r} "
                f"appeared after action {after_action_id}"
            )
        time.sleep(poll_seconds)


def _selected_scenarios(
    config: dict[str, Any], selected_names: set[str]
) -> list[dict[str, Any]]:
    scenarios = [item for item in config["scenarios"] if item.get("enabled", True)]
    if selected_names:
        known = {item["name"] for item in scenarios}
        missing = selected_names - known
        if missing:
            raise HarnessError(
                f"Unknown or disabled scenario(s): {', '.join(sorted(missing))}"
            )
        scenarios = [item for item in scenarios if item["name"] in selected_names]
    if not scenarios:
        raise HarnessError("No enabled scenarios were selected")
    return scenarios


def _api_from_environment(config: dict[str, Any], insecure: bool) -> BigFixAPI:
    return BigFixAPI(
        config["server_url"],
        token=os.environ.get("BIGFIX_TOKEN", ""),
        username=os.environ.get("BIGFIX_USERNAME", ""),
        password=os.environ.get("BIGFIX_PASSWORD", ""),
        verify_tls=not insecure,
        timeout_seconds=int(config.get("request_timeout_seconds", 60)),
    )


def print_plan(config: dict[str, Any], scenarios: list[dict[str, Any]]) -> None:
    print(f"Server: {config['server_url']}")
    print(f"Temporary task site: {config['site_name']}")
    print(
        f"Allowlisted computer IDs: {', '.join(map(str, config['allowed_computer_ids']))}"
    )
    print("Scenarios:")
    for scenario in scenarios:
        print(f"  - {scenario['name']} -> computer {scenario['computer_id']}")
        for step in scenario["steps"]:
            print(f"      {step['name']}: {step['task_file']}")


def check_scenarios(
    api: BigFixAPI,
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
) -> list[ScenarioResult]:
    timeout = int(config.get("client_query_timeout_seconds", 120))
    poll = float(config.get("poll_seconds", 5))
    server_times = api.session_query("now as string")
    print(
        f"Connected to BigFix server; server time: "
        f"{server_times[0] if server_times else 'unknown'}"
    )
    results = []
    for scenario in scenarios:
        computer_id = int(scenario["computer_id"])
        result = ScenarioResult(scenario["name"], computer_id)
        print(f"  Checking {scenario['name']} on computer {computer_id}")
        try:
            identity = api.client_query(
                computer_id,
                '(computer id as string) & "|" & computer name & "|" & '
                "(operating system as string)",
                timeout_seconds=timeout,
                poll_seconds=poll,
            )
            print(f"      target: {identity}")
            result.preconditions = run_assertions(
                api,
                computer_id,
                scenario.get("preconditions", []),
                timeout_seconds=timeout,
                poll_seconds=poll,
            )
            result.passed = True
        except HarnessError as exc:
            result.error = str(exc)
            print(f"      FAIL {exc}")
        results.append(result)
    return results


def run_scenarios(
    api: BigFixAPI,
    config: dict[str, Any],
    scenarios: list[dict[str, Any]],
    *,
    cleanup_successful: bool,
    cleanup_on_failure: bool,
) -> list[ScenarioResult]:
    poll = float(config.get("poll_seconds", 5))
    action_timeout = int(config.get("action_timeout_seconds", 900))
    query_timeout = int(config.get("client_query_timeout_seconds", 120))
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    results: list[ScenarioResult] = []

    for scenario in scenarios:
        computer_id = int(scenario["computer_id"])
        scenario_result = ScenarioResult(scenario["name"], computer_id)
        imported_content: list[tuple[str, int]] = []
        created_actions: list[int] = []
        print(f"Running {scenario['name']} on computer {computer_id}")
        try:
            scenario_result.preconditions = run_assertions(
                api,
                computer_id,
                scenario.get("preconditions", []),
                timeout_seconds=query_timeout,
                poll_seconds=poll,
            )
            for index, step in enumerate(scenario["steps"], 1):
                step_result = StepResult(step["name"])
                scenario_result.steps.append(step_result)
                task_path = REPO_ROOT / step["task_file"]
                step_result.task_file, step_result.task_sha256 = _artifact_identity(
                    task_path
                )
                suffix = f"{run_id} {scenario['name']} {index}"
                task_xml = clone_content_xml(task_path, suffix)
                print(f"  Importing {step['name']}: {task_path.name}")
                kind, content_id = api.import_content(config["site_name"], task_xml)
                imported_content.append((kind, content_id))
                step_result.content_type = kind
                step_result.content_id = content_id

                parameters = _literal_parameters(
                    step.get("parameters"),
                    f"{scenario['name']}.{step['name']}.parameters",
                )
                parameters.update(
                    _env_parameters(
                        step.get("parameters_from_env"),
                        f"{scenario['name']}.{step['name']}.parameters_from_env",
                    )
                )
                secure = _env_parameters(
                    step.get("secure_parameters_from_env"),
                    f"{scenario['name']}.{step['name']}.secure_parameters_from_env",
                )
                action_id = api.launch_task(
                    config["site_name"],
                    content_id,
                    computer_id,
                    parameters,
                    secure,
                    str(step.get("action", "Action1")),
                )
                created_actions.append(action_id)
                step_result.action_id = action_id
                print(f"  Action {action_id} issued; waiting for computer {computer_id}")
                state = api.wait_for_action(
                    action_id,
                    computer_id,
                    timeout_seconds=int(step.get("timeout_seconds", action_timeout)),
                    poll_seconds=poll,
                    success_state="Completed" if kind == "Task" else "Fixed",
                )
                step_result.action_state = state
                if state.lower() not in SUCCESS_ACTION_STATES:
                    raise HarnessError(f"Action {action_id} ended in state {state}")
                print(f"      PASS action {action_id}: {state}")
                step_result.assertions = run_assertions(
                    api,
                    computer_id,
                    step.get("assertions", []),
                    timeout_seconds=query_timeout,
                    poll_seconds=poll,
                )

                forbidden = step.get("forbidden_generated_action")
                if forbidden is not None:
                    if not isinstance(forbidden, dict):
                        raise HarnessError("forbidden_generated_action must be an object")
                    contains = _required_string(
                        forbidden, "title_contains", "forbidden_generated_action"
                    )
                    _assert_no_generated_action(
                        api,
                        after_action_id=action_id,
                        title_contains=contains,
                        observation_seconds=int(forbidden.get("observation_seconds", 30)),
                        poll_seconds=poll,
                    )
                    step_result.forbidden_generated_action_verified = True
                    print(
                        f"      PASS no generated action containing {contains!r} appeared"
                    )

                generated = step.get("generated_action")
                if generated is not None:
                    if not isinstance(generated, dict):
                        raise HarnessError("generated_action must be an object")
                    contains = _required_string(
                        generated, "title_contains", "generated_action"
                    )
                    generated_id = _find_generated_action(
                        api,
                        after_action_id=action_id,
                        title_contains=contains,
                        timeout_seconds=int(generated.get("spawn_timeout_seconds", 180)),
                        poll_seconds=poll,
                    )
                    created_actions.append(generated_id)
                    step_result.generated_action_id = generated_id
                    print(f"      PASS generated action found: {generated_id}")
                    if generated.get("wait_for_completion", True):
                        generated_state = api.wait_for_action(
                            generated_id,
                            computer_id,
                            timeout_seconds=int(
                                generated.get("timeout_seconds", action_timeout)
                            ),
                            poll_seconds=poll,
                            success_state="Completed",
                        )
                        step_result.generated_action_state = generated_state
                        if generated_state.lower() not in SUCCESS_ACTION_STATES:
                            raise HarnessError(
                                f"Generated action {generated_id} ended in state {generated_state}"
                            )
                        print(
                            f"      PASS generated action {generated_id}: {generated_state}"
                        )
                    step_result.assertions.extend(
                        run_assertions(
                            api,
                            computer_id,
                            generated.get("assertions", []),
                            timeout_seconds=query_timeout,
                            poll_seconds=poll,
                        )
                    )
            scenario_result.passed = True
        except HarnessError as exc:
            scenario_result.error = str(exc)
            print(f"  FAIL {scenario['name']}: {exc}")
        finally:
            should_cleanup = (scenario_result.passed and cleanup_successful) or (
                not scenario_result.passed and cleanup_on_failure
            )
            if should_cleanup:
                for action_id in reversed(created_actions):
                    try:
                        api.delete_action(action_id)
                    except HarnessError as exc:
                        print(f"  WARN could not delete action {action_id}: {exc}")
                for kind, content_id in reversed(imported_content):
                    try:
                        api.delete_content(config["site_name"], kind, content_id)
                    except HarnessError as exc:
                        print(
                            f"  WARN could not delete {kind.lower()} {content_id}: {exc}"
                        )
            elif imported_content or created_actions:
                print("  Test objects retained as action-history evidence.")
        results.append(scenario_result)
    return results


def _write_report(
    path: Path, command: str, config: dict[str, Any], results: list[ScenarioResult]
) -> None:
    report = {
        "generated_utc": datetime.now(UTC).isoformat(),
        "command": command,
        "server_url": config["server_url"],
        "site_name": config["site_name"],
        "results": [asdict(result) for result in results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Report: {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check", "run"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        help="run one named scenario; repeat to select several",
    )
    parser.add_argument(
        "--insecure", action="store_true", help="disable TLS verification"
    )
    parser.add_argument("--execute", action="store_true", help="required for run")
    parser.add_argument(
        "--confirm-server",
        default="",
        help="required for run; must exactly match server_url hostname",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="deprecated compatibility option; test objects are retained by default",
    )
    parser.add_argument(
        "--cleanup-successful",
        action="store_true",
        help="delete temporary actions and content after successful scenarios",
    )
    parser.add_argument(
        "--cleanup-on-failure",
        action="store_true",
        help="delete temporary objects even when a scenario fails",
    )
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_config(args.config.resolve())
        if args.command == "run" and not args.scenario:
            raise HarnessError("run requires at least one --scenario")
        scenarios = _selected_scenarios(config, set(args.scenario))
        print_plan(config, scenarios)
        if args.command == "plan":
            return 0

        api = _api_from_environment(config, args.insecure)
        if args.command == "check":
            results = check_scenarios(api, config, scenarios)
        else:
            hostname = parse.urlsplit(config["server_url"]).hostname or ""
            if not args.execute:
                raise HarnessError("run requires --execute")
            if args.confirm_server.lower() != hostname.lower():
                raise HarnessError(f"run requires --confirm-server {hostname} exactly")
            results = run_scenarios(
                api,
                config,
                scenarios,
                cleanup_successful=args.cleanup_successful,
                cleanup_on_failure=args.cleanup_on_failure,
            )
        if args.report:
            _write_report(args.report.resolve(), args.command, config, results)
        return 0 if all(result.passed for result in results) else 1
    except HarnessError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
