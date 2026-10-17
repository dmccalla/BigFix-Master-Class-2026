# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Configure and invoke the explicit, allowlisted lab scenarios."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit


def configuration(
    template: Path, server_url: str, computer_id: int, site_name: str
) -> dict:
    parsed = urlsplit(server_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("Supply an HTTPS lab server URL without embedded credentials")
    if computer_id <= 0:
        raise ValueError("Supply a positive lab computer ID")
    config = json.loads(template.read_text(encoding="utf-8"))
    config.update(
        server_url=server_url.rstrip("/"),
        site_name=site_name,
        allowed_computer_ids=[computer_id],
    )
    for scenario in config["scenarios"]:
        scenario["computer_id"] = computer_id
        for step in scenario["steps"]:
            if "rootServerName" in step.get("parameters", {}):
                step["parameters"]["rootServerName"] = parsed.hostname
    return config


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("plan", "check", "run"))
    parser.add_argument(
        "--server-url",
        default=os.environ.get("BIGFIX_SERVER_URL", "https://BFROOT1.dmc.lab:52311"),
    )
    parser.add_argument(
        "--computer-id",
        type=int,
        default=int(os.environ.get("BIGFIX_LAB_COMPUTER_ID", "8317784")),
    )
    parser.add_argument(
        "--site-name", default=os.environ.get("BIGFIX_LAB_SITE", "BigFix Workbench Test")
    )
    parser.add_argument("--output", type=Path, required=True)
    args, harness_args = parser.parse_known_args()
    here = Path(__file__).resolve().parent
    args.output.mkdir(parents=True, exist_ok=True)
    config = configuration(
        here / "lab-scenarios.example.json",
        args.server_url,
        args.computer_id,
        args.site_name,
    )
    path = args.output / "lab-config.json"
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    spec = importlib.util.spec_from_file_location(
        "bigfix_lab_runtime", here / "bigfix_lab_runtime.py"
    )
    runtime = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = runtime
    spec.loader.exec_module(runtime)
    selected = [
        value
        for scenario in config["scenarios"]
        for value in ("--scenario", scenario["name"])
        if scenario.get("enabled", True)
    ]
    raise SystemExit(
        runtime.main(
            [
                args.command,
                "--config",
                str(path),
                "--report",
                str(args.output / "lab-results.json"),
                *selected,
                *harness_args,
            ]
        )
    )
