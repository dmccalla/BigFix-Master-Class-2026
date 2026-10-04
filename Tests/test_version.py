# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Release bookkeeping guards.

Three things have to agree for a release to be traceable: the version declared
in pyproject.toml, a matching section in CHANGELOG.md, and a git tag on the
commit that shipped. The first two are checked here. The tag is created by hand
at release time.

A suffixed version ("1.0.0-dev") is in development, not released. Its notes
accumulate under [Unreleased] and the suffix comes off when the release is cut,
which is when the changelog section becomes mandatory.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

from Lib.Core import app_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"

_SEMVER = re.compile(r"^\d+\.\d+(?:\.\d+)?(?:[-+][0-9A-Za-z.\-]+)?$")
_PRERELEASE = re.compile(r"^\d+\.\d+\.\d+[-+]")


def _declared_version() -> str:
    with (PROJECT_ROOT / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def test_version_matches_pyproject() -> None:
    assert app_version.version() == _declared_version()


def test_version_is_not_the_fallback() -> None:
    assert app_version.version() != app_version.FALLBACK


def test_version_is_semver() -> None:
    declared = _declared_version()
    assert _SEMVER.match(declared), (
        f"version '{declared}' in pyproject.toml is not MAJOR.MINOR or MAJOR.MINOR.PATCH."
    )


def test_display_version_is_tag_shaped() -> None:
    assert app_version.display_version() == f"v{_declared_version()}"


def test_changelog_exists() -> None:
    assert CHANGELOG.is_file(), f"CHANGELOG.md is missing from {PROJECT_ROOT}."


def test_changelog_has_unreleased_section() -> None:
    text = CHANGELOG.read_text(encoding="utf-8")
    assert re.search(r"^## \[Unreleased\]", text, re.M), (
        "CHANGELOG.md needs an '## [Unreleased]' section to collect notes."
    )


def test_changelog_has_section_for_current_version() -> None:
    declared = _declared_version()
    if _PRERELEASE.match(declared):
        pytest.skip(f"{declared} is a development version; notes live under Unreleased.")
    text = CHANGELOG.read_text(encoding="utf-8")
    pattern = re.compile(rf"^## \[{re.escape(declared)}\]", re.M)
    assert pattern.search(text), (
        f"pyproject.toml declares {declared} but CHANGELOG.md has no "
        f"'## [{declared}]' section. Write the notes before bumping the version."
    )
