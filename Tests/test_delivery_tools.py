# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Exercise failure detection and safe offline planning of delivery checks."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent if (ROOT.parent / ".github/lab_scenarios.py").is_file() else ROOT


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, REPO / ".github" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_cross_product_comparison_detects_changed_answers(tmp_path):
    tool = load_tool("compare_delivery")
    paths = []
    baseline = {"schema": 1, "case": "qa", "metrics": {"score": 56}}
    for index in range(3):
        path = tmp_path / f"product-{index}.json"
        path.write_text(json.dumps(baseline))
        paths.append(path)
    assert tool.compare(paths)["passed"]
    changed = copy.deepcopy(baseline)
    changed["metrics"]["score"] = 57
    paths[2].write_text(json.dumps(changed))
    assert not tool.compare(paths)["passed"]
    assert "metrics" in tool.compare(paths)["differences"]


def test_cross_product_comparison_requires_three_distinct_results(tmp_path):
    with pytest.raises(ValueError, match="three distinct"):
        load_tool("compare_delivery").compare([tmp_path / "same.json"] * 3)


def test_lab_plan_uses_configurable_server_and_one_allowlisted_target(tmp_path):
    tool = load_tool("lab_scenarios")
    config = tool.configuration(
        REPO / ".github/lab-scenarios.example.json",
        "https://handoff.example.invalid:52311",
        42,
        "QA Site",
    )
    assert config["allowed_computer_ids"] == [42]
    assert all(scenario["computer_id"] == 42 for scenario in config["scenarios"])
    assert config["server_url"] == "https://handoff.example.invalid:52311"
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    runtime = load_tool("bigfix_lab_runtime")
    assert runtime.load_config(path)["site_name"] == "QA Site"
    assert runtime.main(["plan", "--config", str(path)]) == 0


@pytest.mark.parametrize(
    "server",
    ["http://example.invalid", "https://user:password@example.invalid", "not-a-url"],
)
def test_lab_configuration_rejects_plaintext_or_embedded_credentials(server):
    with pytest.raises(ValueError, match="HTTPS"):
        load_tool("lab_scenarios").configuration(
            REPO / ".github/lab-scenarios.example.json", server, 42, "QA"
        )


def test_lab_run_requires_explicit_scenario_and_execution_confirmation(
    tmp_path, monkeypatch
):
    tool = load_tool("lab_scenarios")
    config = tool.configuration(
        REPO / ".github/lab-scenarios.example.json",
        "https://lab.example.invalid",
        42,
        "QA",
    )
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    runtime = load_tool("bigfix_lab_runtime")
    monkeypatch.setattr(runtime, "_api_from_environment", lambda *args: object())
    assert runtime.main(["run", "--config", str(path)]) == 2
    scenario = config["scenarios"][0]["name"]
    assert runtime.main(["run", "--config", str(path), "--scenario", scenario]) == 2
    assert (
        runtime.main(
            [
                "run",
                "--config",
                str(path),
                "--scenario",
                scenario,
                "--execute",
                "--confirm-server",
                "other.invalid",
            ]
        )
        == 2
    )


def zip_fixture(tmp_path, members):
    archive = tmp_path / "release.zip"
    with zipfile.ZipFile(archive, "w") as zipped:
        for name, content in members.items():
            zipped.writestr(name, content)
    Path(str(archive) + ".sha256").write_text(
        hashlib.sha256(archive.read_bytes()).hexdigest() + " release.zip\n"
    )
    return archive


def test_release_smoke_rejects_wrong_commit(tmp_path):
    archive = zip_fixture(
        tmp_path,
        {"release-manifest.json": json.dumps({"source_commit": "other", "files": []})},
    )
    with pytest.raises(ValueError, match="different commit"):
        load_tool("release_smoke").verify_archive(archive, tmp_path / "out", "expected")


def test_release_smoke_detects_modified_payload(tmp_path):
    manifest = {
        "source_commit": "expected",
        "files": [
            {"path": "data.txt", "bytes": 3, "sha256": hashlib.sha256(b"old").hexdigest()}
        ],
    }
    archive = zip_fixture(
        tmp_path, {"release-manifest.json": json.dumps(manifest), "data.txt": "new"}
    )
    with pytest.raises(ValueError, match="Manifest mismatch"):
        load_tool("release_smoke").verify_archive(archive, tmp_path / "out", "expected")


def test_release_smoke_rejects_escaping_zip_member(tmp_path):
    archive = zip_fixture(tmp_path, {"../escape.txt": "outside"})
    with pytest.raises(ValueError, match="Unsafe ZIP member"):
        load_tool("release_smoke").verify_archive(archive, tmp_path / "out", "expected")
    assert not (tmp_path / "escape.txt").exists()
