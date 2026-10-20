# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Exercise the real Windows companion archive without building dependencies."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "Build/package_perfmon_samples.ps1"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL, reason="Windows PowerShell required"
)


def powershell(code: str, **variables: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in {**os.environ, "HELPER": str(HELPER), **variables}.items()
        if key.casefold() not in {"psmodulepath", "bigfix_large_perfmon_sample_dir"}
    }
    if "BIGFIX_LARGE_PERFMON_SAMPLE_DIR" in variables:
        env["BIGFIX_LARGE_PERFMON_SAMPLE_DIR"] = variables[
            "BIGFIX_LARGE_PERFMON_SAMPLE_DIR"
        ]
    prelude = (
        "$ErrorActionPreference = 'Stop'; Set-StrictMode -Version Latest; . $env:HELPER; "
    )
    encoded = base64.b64encode((prelude + code).encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env=env,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        check=False,
    )


BUILD = r"""
$files = @(Get-LargePerfmonSampleFiles -SourceDirectory $env:SOURCE -ApplicationRoot $env:APP_ROOT)
New-LargePerfmonSampleArchive -Files $files -OutputDirectory $env:OUTPUT -Version '2.1' -ProductName 'Fixture' -SourceCommit ('a' * 40) -ArchiveRoot $env:ARCHIVE_ROOT
"""


@pytest.mark.parametrize(
    "archive_root",
    ["SampleData/Large_Perfmon", "Nested App/SampleData/Large_Perfmon"],
)
def test_companion_archive_has_exact_bytes_hashes_and_safe_layout(tmp_path, archive_root):
    source = tmp_path / "samples"
    source.mkdir()
    captures = {"Capture A.blg": b"capture A" * 1000, "Capture-B.blg": b"capture B"}
    for name, data in captures.items():
        (source / name).write_bytes(data)
    (source / "ignored.txt").write_text("Do not distribute unrelated source files")
    output = tmp_path / "output"
    result = powershell(
        BUILD,
        SOURCE=str(source),
        APP_ROOT=str(tmp_path),
        OUTPUT=str(output),
        ARCHIVE_ROOT=archive_root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    archive = output / "Sample-Data-Perfmon-Large-2.1.zip"
    checksum = archive.with_suffix(".zip.sha256").read_text().split()[0]
    assert checksum == hashlib.sha256(archive.read_bytes()).hexdigest()
    with zipfile.ZipFile(archive) as zipped:
        contents = {name: zipped.read(name) for name in zipped.namelist()}
    assert set(contents) == {
        *(f"{archive_root}/{name}" for name in captures),
        "README.txt",
        "sample-manifest.json",
    }
    manifest = json.loads(contents["sample-manifest.json"])
    assert manifest["version"] == "2.1"
    assert manifest["source_commit"] == "a" * 40
    assert {entry["path"] for entry in manifest["files"]} == (
        set(contents) - {"sample-manifest.json"}
    )
    for entry in manifest["files"]:
        assert entry["bytes"] == len(contents[entry["path"]])
        assert entry["sha256"] == hashlib.sha256(contents[entry["path"]]).hexdigest()
    for name, data in captures.items():
        assert contents[f"{archive_root}/{name}"] == data
        assert (source / name).read_bytes() == data
    assert str(source).encode() not in contents["sample-manifest.json"]
    assert not list(output.glob(".perfmon-*"))


@pytest.mark.parametrize("kind", ["missing", "empty", "zero-byte"])
def test_missing_or_empty_sources_fail_without_creating_output(tmp_path, kind):
    source = tmp_path / "samples"
    if kind != "missing":
        source.mkdir()
    if kind == "zero-byte":
        (source / "empty.blg").touch()
    output = tmp_path / "output"
    result = powershell(
        BUILD,
        SOURCE=str(source),
        APP_ROOT=str(tmp_path),
        OUTPUT=str(output),
        ARCHIVE_ROOT="SampleData/Large_Perfmon",
    )
    assert result.returncode != 0
    assert not output.exists()


def test_default_source_and_environment_override(tmp_path):
    default = tmp_path / "LocalSamples/Large_Perfmon"
    default.mkdir(parents=True)
    (default / "default.blg").write_bytes(b"default")
    explicit = tmp_path / "external"
    explicit.mkdir()
    (explicit / "external.blg").write_bytes(b"external")
    code = "(Get-LargePerfmonSampleFiles -SourceDirectory '' -ApplicationRoot $env:APP_ROOT).Name"
    result = powershell(code, APP_ROOT=str(tmp_path))
    assert result.returncode == 0 and "default.blg" in result.stdout
    result = powershell(
        code,
        APP_ROOT=str(tmp_path),
        BIGFIX_LARGE_PERFMON_SAMPLE_DIR=str(explicit),
    )
    assert result.returncode == 0 and "external.blg" in result.stdout


def test_archive_refuses_directory_destination_and_traversal(tmp_path):
    source = tmp_path / "samples"
    source.mkdir()
    (source / "sample.blg").write_bytes(b"sample")
    output = tmp_path / "output"
    sentinel = output / "Sample-Data-Perfmon-Large-2.1.zip/keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_bytes(b"keep")
    result = powershell(
        BUILD,
        SOURCE=str(source),
        APP_ROOT=str(tmp_path),
        OUTPUT=str(output),
        ARCHIVE_ROOT="SampleData/Large_Perfmon",
    )
    assert result.returncode != 0
    assert sentinel.read_bytes() == b"keep"
    result = powershell(
        BUILD,
        SOURCE=str(source),
        APP_ROOT=str(tmp_path),
        OUTPUT=str(tmp_path / "not-created"),
        ARCHIVE_ROOT="../outside",
    )
    assert result.returncode != 0
    assert not (tmp_path / "not-created").exists()
