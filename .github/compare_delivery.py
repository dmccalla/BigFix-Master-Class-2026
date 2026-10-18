# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Compare the three products' saved known-answer report results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def compare(paths: list[Path]) -> dict:
    if len(paths) != 3 or len({path.resolve() for path in paths}) != 3:
        raise ValueError("Supply three distinct product result files")
    reports = [json.loads(path.read_text(encoding="utf-8")) for path in paths]
    if any(report.get("schema") != 1 for report in reports):
        raise ValueError("Unknown delivery result schema")
    differences = {
        key: [report.get(key) for report in reports]
        for key in ("case", "metrics", "frequency", "top10", "chart", "finding_ids")
        if any(report.get(key) != reports[0].get(key) for report in reports[1:])
    }
    return {
        "passed": not differences,
        "sources": [str(path) for path in paths],
        "differences": differences,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.reports)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
