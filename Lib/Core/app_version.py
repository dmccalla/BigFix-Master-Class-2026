# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
app_version.py -- single source of truth for the Workbench version.

The version is declared in exactly one place: the ``version`` field in
pyproject.toml. Anything that shows or records a version reads it from here,
so bumping a release is a one-line edit in one file.

Release bookkeeping lives in two other places, both maintained by hand:

  * CHANGELOG.md at the repo root records what changed in each version.
  * A git tag (vMAJOR.MINOR.PATCH) marks the exact commit the version shipped
    from. The tag, not the file, is the permanent record.

Tests/test_version.py keeps the three in agreement: it fails the suite if
pyproject declares a release version that CHANGELOG.md has no section for.

Usage:

    from Lib.Core import app_version

    app_version.version()          # "1.0.0"
    app_version.display_version()  # "v1.0.0"
"""

from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

# Returned when pyproject.toml cannot be read or declares no version. Shaped
# like a real version so callers never have to special-case the failure, but
# obviously not a release.
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
