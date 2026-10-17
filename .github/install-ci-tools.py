# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Install CI tools from uv.lock. Run from the application directory."""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path


def locked_requirements(lockfile: Path) -> list[str]:
    with lockfile.open("rb") as handle:
        packages = tomllib.load(handle)["package"]
    pending = ["pytest", "ruff"]
    resolved: dict[str, str] = {}
    while pending:
        name = pending.pop()
        if name in resolved:
            continue
        matches = [package for package in packages if package["name"] == name]
        if len(matches) != 1:
            raise ValueError(
                f"Expected one locked version of {name}, found {len(matches)}"
            )
        package = matches[0]
        resolved[name] = package["version"]
        pending.extend(
            dependency["name"] for dependency in package.get("dependencies", [])
        )
    return [f"{name}=={version}" for name, version in sorted(resolved.items())]


if __name__ == "__main__":
    subprocess.run(
        [sys.executable, "-m", "pip", "install", *locked_requirements(Path("uv.lock"))],
        check=True,
    )
