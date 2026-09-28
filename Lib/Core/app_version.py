# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
app_version.py -- source of the Workbench version shown in the UI.

The version is declared in the ``version`` field in pyproject.toml. Anything
that shows the Workbench version reads it from here.

Usage:

    from Lib.Core import app_version

    app_version.version()          # "1.0.0"
    app_version.display_version()  # "v1.0.0"
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

# Returned when pyproject.toml cannot be read or declares no version. It keeps
# callers from having to special-case a missing version.
FALLBACK = "0.0.0+unknown"


def pyproject_path() -> Path:
    # Lib/Core/app_version.py -> Lib/Core -> Lib -> project root
    return Path(__file__).resolve().parents[2] / "pyproject.toml"


@lru_cache(maxsize=1)
def version() -> str:
    """Return the declared version, for example "1.0.0", or FALLBACK."""
    try:
        with pyproject_path().open("rb") as handle:
            declared = tomllib.load(handle)["project"]["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError):
        return FALLBACK
    declared = str(declared).strip()
    return declared or FALLBACK


def display_version() -> str:
    """Return the version shaped like its git tag, for example "v1.0.0"."""
    return f"v{version()}"
