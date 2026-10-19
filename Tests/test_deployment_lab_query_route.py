# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Lab checks use the normal query route used by the deployment collector."""

import importlib.util
import sys
from pathlib import Path
from urllib.parse import parse_qs

ROOT = next(
    p for p in Path(__file__).resolve().parents if (p / "Tasks and Analyses").is_dir()
)


def test_lab_session_queries_preserve_values_without_forcing_explorer_only():
    spec = importlib.util.spec_from_file_location(
        "deployment_route_runtime", ROOT / ".github/bigfix_lab_runtime.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime
    spec.loader.exec_module(runtime)
    relevance = '("A & B: 50%", number of bes computers)'
    calls = []

    def transport(method, path, body, headers):
        calls.append((method, path))
        assert headers["Content-Type"] == "application/x-www-form-urlencoded"
        assert parse_qs(body.decode("utf-8")) == {
            "relevance": [relevance],
            "output": ["json"],
        }
        return runtime.HTTPResult(200, b'{"result":["A & B: 50%",14],"evaltime_ms":0.1}')

    api = runtime.BigFixAPI(
        "https://lab.example.invalid:52311", token="test-token", transport=transport
    )
    assert api.session_query(relevance) == ["A & B: 50%", 14]
    assert calls == [("POST", "/api/query")]
