# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Maintain the self-contained Windows service commands shipped in BES tasks.

The PowerShell body is the readable authority. Tasks need no external download
or Python installation. Only opening braces need escaping in BigFix ActionScript;
generated cleanup actions add a second substitution pass.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BODY_PATH = Path(__file__).with_name("health_check_service_transition.ps1")
SITE = next(
    parent / "Tasks and Analyses"
    for parent in Path(__file__).resolve().parents
    if (parent / "Tasks and Analyses").is_dir()
)


def powershell_body(name: str, target: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9 _-]+", name):
        raise ValueError(f"Unsafe service name: {name!r}")
    if target not in {"Stopped", "Running"}:
        raise ValueError(f"Unknown target: {target}")
    body = BODY_PATH.read_text(encoding="utf-8").split(
        "# BEGIN INLINE SERVICE CONTROL", 1
    )[1]
    compact = " ".join(
        line.strip()
        for line in body.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert '"' not in compact
    return f"$Name='{name}'; $Target='{target}'; " + compact


def service_command(name: str, target: str, passes: int = 1) -> str:
    if passes not in {1, 2}:
        raise ValueError("Only direct and generated actions are supported")
    body = powershell_body(name, target).replace("{", "{" * (2**passes))
    return (
        'waithidden powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "'
        + body
        + '"'
    )


def refresh_tasks(site: Path) -> list[Path]:
    changed = []
    legacy = re.compile(
        r"Get-Service -Name '([^']+)'[^\r\n]+WaitForStatus\('(Stopped|Running)'"
    )
    current = re.compile(r"\$Name='([^']+)'; \$Target='(Stopped|Running)';")
    for path in sorted(site.rglob("*.bes")):
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig")
        lines = text.splitlines(keepends=True)
        replaced = []
        for index, line in enumerate(lines):
            if "waithidden powershell.exe " not in line:
                replaced.append(line)
                continue
            match = legacy.search(line) or current.search(line)
            if not match:
                replaced.append(line)
                continue
            following = next(
                value.strip() for value in lines[index + 1 :] if value.strip()
            )
            gate = re.fullmatch(
                r"continue if (\{{1,2})exit code of action = 0\}", following
            )
            if not gate:
                raise ValueError(f"Missing service failure gate in {path}:{index + 1}")
            name, target = match.groups()
            indent = line[: len(line) - len(line.lstrip())]
            ending = "\r\n" if line.endswith("\r\n") else "\n"
            replaced.append(indent + service_command(name, target, len(gate[1])) + ending)
        updated = "".join(replaced)
        if updated != text:
            bom = b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b""
            path.write_bytes(bom + updated.encode("utf-8"))
            changed.append(path)
    return changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=SITE)
    args = parser.parse_args()
    for changed_path in refresh_tasks(args.site):
        print(changed_path.name)
