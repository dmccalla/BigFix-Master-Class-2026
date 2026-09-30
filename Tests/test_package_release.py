# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Exercise Windows staging and ZIP generation without installing dependencies."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "Build" / "package_release.ps1"
PACKAGE = "Master-Class-Diagnostics-Workbench-1.0.0-dev"
POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or not POWERSHELL, reason="Windows PowerShell required"
)

LOAD_FUNCTIONS = r"""
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    $env:PACKAGE_SCRIPT, [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$ast.FindAll({ param($node)
    $node -is [Management.Automation.Language.FunctionDefinitionAst]
}, $false) | ForEach-Object { Invoke-Expression $_.Extent.Text }
"""

# Substitute only external tool calls in a disposable copy of the parsed script.
# The staging, copy, manifest, archive and cleanup statements run unchanged.
BUILD_FIXTURE = LOAD_FUNCTIONS + r"""
$text = Get-Content -Raw -LiteralPath $env:PACKAGE_SCRIPT
$edits = @($ast.FindAll({ param($node)
    ($node -is [Management.Automation.Language.CommandAst] -and
     $node.CommandElements[0].Extent.Text -in @('$toolPython', '$runtimePython')) -or
    ($node -is [Management.Automation.Language.FunctionDefinitionAst] -and
     $node.Name -eq 'Get-RepoPython')
}, $true))
foreach ($node in ($edits | Sort-Object { $_.Extent.StartOffset } -Descending)) {
    if ($node -is [Management.Automation.Language.CommandAst]) {
        $extent = $node.CommandElements[0].Extent
        $replacement = 'Invoke-TestPython'
    } else {
        $extent = $node.Extent
        $replacement = "function Get-RepoPython { 'test-python' }"
    }
    $text = $text.Remove($extent.StartOffset, $extent.EndOffset - $extent.StartOffset).
        Insert($extent.StartOffset, $replacement)
}
$fixtureScript = Join-Path $env:FIXTURE_ROOT 'Build\package_release.ps1'
[IO.File]::WriteAllText($fixtureScript, $text)
function git {
    if ($args -contains 'ls-files') {
        Get-Content -Raw (Join-Path $env:FIXTURE_ROOT 'files.json') | ConvertFrom-Json
    } elseif ($args -contains 'rev-parse') {
        '0123456789012345678901234567890123456789'
    } elseif ($args -notcontains 'status') { throw "Unexpected git call: $args" }
}
function Invoke-TestPython {
    $global:LASTEXITCODE = 0
    if ($args[0] -eq '-c') {
        Write-Host "TEST_WORK_ROOT=$workRoot"
    } elseif ($args[1] -eq 'venv') {
        New-Item -ItemType Directory -Path $args[2] | Out-Null
        if ($env:FAIL_BUILD -eq '1') { throw 'Injected environment failure' }
    } elseif ($args[1] -eq 'pip') {
        return
    } elseif ($args[1] -eq 'cyclonedx_py') {
        [IO.File]::WriteAllText($args[[Array]::IndexOf($args, '-o') + 1], '{}')
    } elseif ($args[0] -like '*third_party_notices.py') {
        [IO.File]::WriteAllText($args[1], 'Fixture notices')
    } else { throw "Unexpected Python call: $args" }
}
$options = @{ AllowDevVersion = $true; AllowDirtyTree = $true }
if ($env:KEEP_STAGING -eq '1') { $options.KeepStaging = $true }
if ($env:VALIDATE_ONLY -eq '1') { $options.ValidateOnly = $true }
& $fixtureScript @options -OutputPath $env:PACKAGE_OUTPUT
"""


def _powershell(code: str, **env: str) -> subprocess.CompletedProcess[str]:
    encoded = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    return subprocess.run(
        [POWERSHELL, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        env={**os.environ, "PACKAGE_SCRIPT": str(SCRIPT), **env},
        capture_output=True,
        text=True,
        errors="replace",
        timeout=60,
        check=False,
    )


@pytest.fixture
def package_fixture():
    # Keep source paths short too: Copy-Item must be able to read the long BES name.
    with tempfile.TemporaryDirectory(prefix="mcp-") as directory:
        root = Path(directory)
        (root / "Build").mkdir()
        files = [
            "README.md", "CHANGELOG.md", "LICENSE", "NOTICE", "requirements.txt",
            "Launchers/Run Diagnostics Workbench.cmd", "App/diagnostics_workbench_ui.py",
            "App/run_diagnostics.py", "Utilities/MXFillDBPerf.exe",
            "Templates/Diagnostics_Style_Template.docx", "pyproject.toml",
            "Tasks and Analyses/Individual Tasks/WARNING_ BigFix Master Class -- "
            "POST HEALTH CHECK ONLY - FillDB Performance Logging Set to Non-Default (2.0).bes",
        ]
        for relative in files:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture\n")
        (root / "pyproject.toml").write_text('[project]\nversion = "1.0.0-dev"\n')
        (root / "files.json").write_text(json.dumps(files))
        yield root, files


@pytest.mark.parametrize("keep", [False, True])
def test_short_staging_preserves_archive_and_manifest(package_fixture, keep):
    root, files = package_fixture
    output = "output-" + "x" * 70
    legacy = root / output / PACKAGE / "keep.txt"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("previous failed build")
    legacy_env = root / output / "_sbom_env" / "keep.txt"
    legacy_env.parent.mkdir()
    legacy_env.write_text("previous environment")
    result = _powershell(
        BUILD_FIXTURE, FIXTURE_ROOT=str(root), PACKAGE_OUTPUT=output,
        KEEP_STAGING=str(int(keep)),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    workspace = Path(re.search(r"TEST_WORK_ROOT=(.+)", result.stdout)[1].strip())
    try:
        assert workspace.parent.resolve() == Path(tempfile.gettempdir()).resolve()
        assert workspace.name.startswith("mc-")
        assert workspace.exists() == keep
        assert not (workspace / "_sbom_env").exists()
        assert legacy.read_text() == "previous failed build"
        assert legacy_env.read_text() == "previous environment"
        assert len(str(root / output / PACKAGE / files[-1])) >= 260
        assert len(str(workspace / PACKAGE / files[-1])) < 260
        archive = root / output / f"{PACKAGE}.zip"
        checksum = Path(f"{archive}.sha256").read_text().split()[0]
        assert checksum == hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as zipped:
            contents = {
                entry.filename.removeprefix(f"{PACKAGE}/"): zipped.read(entry)
                for entry in zipped.infolist() if not entry.is_dir()
            }
            assert all(name.startswith(f"{PACKAGE}/") for name in zipped.namelist())
        assert set(contents) == set(files) | {
            "START_HERE.txt", "sbom.cyclonedx.json", "THIRD_PARTY_NOTICES.md",
            "release-manifest.json",
        }
        for relative in files:
            expected = (root / relative).read_bytes()
            if relative.endswith(".cmd"):
                expected = expected.replace(b"\n", b"\r\n")
            assert contents[relative] == expected
        manifest = json.loads(contents["release-manifest.json"])
        assert {entry["path"] for entry in manifest["files"]} == (
            set(contents) - {"release-manifest.json"}
        )
        for entry in manifest["files"]:
            data = contents[entry["path"]]
            assert entry["bytes"] == len(data)
            assert entry["sha256"] == hashlib.sha256(data).hexdigest()
        if keep:
            assert f"Staging folder  : {workspace / PACKAGE}" in result.stdout
    finally:
        if workspace.exists():
            cleanup = _powershell(
                LOAD_FUNCTIONS + "Remove-PackageDirectory $env:TARGET $env:PARENT",
                TARGET=str(workspace), PARENT=str(workspace.parent),
            )
            assert cleanup.returncode == 0, cleanup.stdout + cleanup.stderr


def test_failed_build_cleans_owned_workspace(package_fixture):
    root, _ = package_fixture
    result = _powershell(
        BUILD_FIXTURE, FIXTURE_ROOT=str(root), PACKAGE_OUTPUT="output", FAIL_BUILD="1",
    )
    assert result.returncode != 0
    assert "Injected environment failure" in result.stderr
    workspace = Path(re.search(r"TEST_WORK_ROOT=(.+)", result.stdout)[1].strip())
    assert not workspace.exists()
    assert not list((root / "output").glob("*.zip"))


def test_validate_only_does_not_stage_or_call_python(package_fixture):
    root, _ = package_fixture
    result = _powershell(
        BUILD_FIXTURE, FIXTURE_ROOT=str(root), PACKAGE_OUTPUT="output", VALIDATE_ONLY="1",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "TEST_WORK_ROOT=" not in result.stdout
    assert not (root / "output").exists()


def test_long_temp_path_fails_before_staging_or_python(package_fixture):
    root, _ = package_fixture
    temporary = root / ("long-temp-" + "x" * 50)
    temporary.mkdir()
    result = _powershell(
        BUILD_FIXTURE, FIXTURE_ROOT=str(root), PACKAGE_OUTPUT="output",
        TEMP=str(temporary), TMP=str(temporary),
    )
    assert result.returncode != 0
    assert "Set TEMP to a shorter directory" in result.stderr
    assert "TEST_WORK_ROOT=" not in result.stdout
    assert not list(temporary.iterdir())


@pytest.mark.parametrize("suffix", [".zip", ".zip.sha256"])
def test_output_directory_is_not_recursively_replaced(package_fixture, suffix):
    root, _ = package_fixture
    sentinel = root / "output" / f"{PACKAGE}{suffix}" / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep")
    result = _powershell(
        BUILD_FIXTURE, FIXTURE_ROOT=str(root), PACKAGE_OUTPUT="output",
    )
    assert result.returncode != 0
    assert "Refusing to replace a directory or reparse point" in result.stderr
    assert "TEST_WORK_ROOT=" not in result.stdout
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("target", ["owned", "owned-other", "owned/../outside"])
def test_cleanup_rejects_parent_sibling_and_traversal(tmp_path, target):
    parent = tmp_path / "owned"
    parent.mkdir()
    destination = tmp_path / target
    destination.mkdir(exist_ok=True)
    sentinel = destination / "keep.txt"
    sentinel.write_text("keep")
    result = _powershell(
        LOAD_FUNCTIONS + "Remove-PackageDirectory $env:TARGET $env:PARENT",
        TARGET=str(destination), PARENT=str(parent),
    )
    assert result.returncode != 0
    assert "Refusing cleanup outside" in result.stderr
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize("target", ["owned", "owned/link", "owned/link/child"])
def test_cleanup_rejects_reparse_descendants_and_ancestors(tmp_path, target):
    result = _powershell(
        LOAD_FUNCTIONS + r"""
$parent = $env:TEST_ROOT
$owned = New-Item -ItemType Directory -Path (Join-Path $parent 'owned')
$outside = New-Item -ItemType Directory -Path (Join-Path $parent 'outside\child') -Force
$sentinel = Join-Path $outside.FullName 'keep.txt'
[IO.File]::WriteAllText($sentinel, 'keep')
$link = Join-Path $owned.FullName 'link'
New-Item -ItemType Junction -Path $link -Target $outside.Parent.FullName | Out-Null
try {
    try {
        Remove-PackageDirectory (Join-Path $parent $env:TARGET) $parent
        throw 'Unsafe cleanup was accepted'
    } catch {
        if ($_ -notmatch 'reparse point') { throw }
    }
    if ([IO.File]::ReadAllText($sentinel) -ne 'keep') { throw 'Sentinel changed' }
} finally {
    [IO.Directory]::Delete($link)
}
""",
        TEST_ROOT=str(tmp_path), TARGET=target,
    )
    assert result.returncode == 0, result.stdout + result.stderr
