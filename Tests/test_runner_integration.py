# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
import run_diagnostics as runner
from docx import Document
from PIL import Image, ImageStat

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "SampleData" / "BigFix Master Class 2026"


@pytest.mark.integration
@pytest.mark.slow
@pytest.mark.skipif(
    os.environ.get("WORKBENCH_RUN_E2E") != "1" or sys.platform != "win32",
    reason="Set WORKBENCH_RUN_E2E=1 on Windows to run real module builds",
)
@pytest.mark.parametrize(
    "module_key,mode",
    [
        (key, mode)
        for key in ("loop", "filldb", "perfmon")
        for mode in ("discovered", "manual")
    ]
    + [("perfmon", "manual_two_captures")],
)
def test_modules_with_real_generators(
    tmp_path_factory, module_key: str, mode: str
) -> None:
    # Leave room for the run prefix and Perfmon's required counter suffixes.
    tmp_path = tmp_path_factory.mktemp("mc")
    if not (SAMPLES / "Perfmon" / "server.blg").is_file():
        pytest.skip("Master Class sample evidence is not installed")
    assert shutil.which("relog.exe"), "Windows relog.exe is required"
    discovered = runner.scan_input_folder(SAMPLES)
    assert all(discovered.values()), discovered
    mod = runner.MODULE_BY_KEY[module_key]
    inputs = {module_key: {mod.file_key: str(discovered[module_key])}}
    manual_inputs = {}
    if mode.startswith("manual"):
        # Copy inputs away from the data root to exercise explicit manual choices.
        manual = tmp_path / "manual"
        manual.mkdir()
        # The client capture lives wherever the scan found it (the lab set
        # keeps it under Results), with its companion files beside it.
        loop_dir = Path(discovered["loop"]).parent
        sources = {
            "loop": next(loop_dir.glob("Client_Loop_*.csv")),
            "filldb": SAMPLES / "FillDB_Performance" / "FillDBPerf_analysis.csv",
            "perfmon": SAMPLES / "Perfmon" / "server.blg",
        }
        for key, source in sources.items():
            if key != module_key:
                continue
            path = Path(shutil.copy2(source, manual / source.name))
            field = runner.MODULE_BY_KEY[key].file_key
            inputs[key][field] = str(path)
            manual_inputs[key] = {field: str(path)}
        for field, source in {
            "top_offenders_file": loop_dir / "top10-query-results.csv",
            "udp_notifications_file": loop_dir / "udp-notification-results.csv",
        }.items():
            if module_key != "loop":
                continue
            path = Path(shutil.copy2(source, manual / source.name))
            inputs["loop"][field] = str(path)
            manual_inputs["loop"][field] = str(path)
    if mode == "manual_two_captures":
        # Reuse the sample BLG to exercise both captures without new evidence.
        inputs["perfmon"]["capture2_blg_path"] = str(discovered["perfmon"])
        manual_inputs["perfmon"]["capture2_blg_path"] = str(discovered["perfmon"])

    for field in (
        "logical_processors",
        "physical_disks",
        "physical_memory_gb",
        "capture2_logical_processors",
        "capture2_physical_disks",
        "capture2_physical_memory_gb",
    ):
        if module_key == "perfmon":
            inputs["perfmon"][field] = 0
    config = {
        "run_name": "E2E",
        "output_folder": str(tmp_path),
        "data_root": str(SAMPLES),
        "modules": [module_key],
        "inputs": inputs,
        "manual_inputs": manual_inputs,
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    context = runner.build_run_context(str(config_path))
    for key, fields in manual_inputs.items():
        for field, path in fields.items():
            assert context.module_inputs[key][field] == Path(path)

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "App" / "run_diagnostics.py"),
            "--config",
            str(config_path),
            "--yes",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
        timeout=600,
    )
    console_path = tmp_path / "console.log"
    console_path.write_text(result.stdout + result.stderr, encoding="utf-8")
    assert result.returncode == 0, f"Build failed. See {console_path}"
    assert "Run complete" in result.stdout
    assert "[ERROR]" not in result.stdout
    manifests = list(tmp_path.glob("E2E_*/*_Run_Manifest.json"))
    assert len(manifests) == 1
    manifest_path = manifests[0]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["modules"] == [module_key]
    folder = manifest_path.parent
    prefix = manifest["file_prefix"]
    expected = {
        "loop": [
            f"Client_Loop/{prefix}_Client_Loop.xlsx",
            f"Client_Loop/{prefix}_Client_Loop.png",
            f"Client_Loop/{prefix}_Client_Loop.docx",
        ],
        "filldb": [
            f"FillDB_Performance/{prefix}_FillDB_Performance.png",
            f"FillDB_Performance/{prefix}_FillDB_Performance.docx",
        ],
        "perfmon": [
            f"Perfmon/{prefix}_Perfmon.xlsx",
            f"Perfmon/{prefix}_Perfmon_Mini_Report.docx",
        ],
    }[module_key]
    captures = ["Perfmon"] if module_key == "perfmon" else []
    if mode == "manual_two_captures":
        expected.append(f"Perfmon/{prefix}_Perfmon_Capture_2.xlsx")
        captures.append("Perfmon_Capture_2")
    for capture in captures:
        charts = list((folder / "Perfmon" / f"{prefix}_{capture}_Charts").glob("*.png"))
        assert charts
        expected.extend(path.relative_to(folder).as_posix() for path in charts)
    for relative in expected:
        assert relative in manifest["files"]
        artifact = folder / relative
        assert artifact.is_file() and artifact.stat().st_size > 0
        if artifact.suffix == ".png":
            with Image.open(artifact) as image:
                assert min(image.size) > 10, artifact
                assert max(ImageStat.Stat(image.convert("RGB")).var) > 1, artifact
        else:
            with zipfile.ZipFile(artifact) as archive:
                assert archive.testzip() is None
    if module_key == "perfmon":
        report = Document(folder / "Perfmon" / f"{prefix}_Perfmon_Mini_Report.docx")
        paragraphs = "\n".join(p.text for p in report.paragraphs)
        assert "PerfMon Capture 1" in paragraphs
        assert ("PerfMon Capture 2" in paragraphs) == (mode == "manual_two_captures")
    saved_log = (folder / f"{prefix}_RunLog.txt").read_text(encoding="utf-8")
    assert "Run complete" in saved_log
    assert "[ERROR]" not in saved_log
