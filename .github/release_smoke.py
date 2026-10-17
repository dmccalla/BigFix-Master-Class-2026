# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Validate an actual release ZIP and run it in a fresh runtime environment."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath


def verify_archive(archive_path: Path, output: Path, expected_commit: str) -> Path:
    checksum = Path(str(archive_path) + ".sha256")
    if (
        checksum.read_text(encoding="utf-8").split()[0].lower()
        != hashlib.sha256(archive_path.read_bytes()).hexdigest()
    ):
        raise ValueError("ZIP checksum does not match")
    destination = output / "extracted"
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive_path) as archive:
        if archive.testzip() is not None:
            raise ValueError("Corrupt ZIP member")
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate ZIP paths")
        for name in names:
            relative = PurePosixPath(name.replace("\\", "/"))
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or any(":" in part for part in relative.parts)
            ):
                raise ValueError("Unsafe ZIP member: " + name)
            target = (destination / Path(*relative.parts)).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("ZIP member escapes extraction folder")
        archive.extractall(destination)
    manifests = list(destination.rglob("release-manifest.json"))
    if len(manifests) != 1:
        raise ValueError("Expected one release manifest")
    root = manifests[0].parent
    manifest = json.loads(manifests[0].read_text(encoding="utf-8"))
    if manifest["source_commit"] != expected_commit:
        raise ValueError("ZIP was built from a different commit")
    inventory = {}
    for entry in manifest["files"]:
        relative = entry["path"]
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or relative in inventory:
            raise ValueError("Invalid manifest path: " + relative)
        content = path.read_bytes()
        if (
            len(content) != entry["bytes"]
            or hashlib.sha256(content).hexdigest() != entry["sha256"]
        ):
            raise ValueError("Manifest mismatch: " + relative)
        inventory[relative] = entry
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifests[0]
    }
    if actual != set(inventory):
        raise ValueError("Manifest does not describe the exact payload")
    requirements = list(root.rglob("requirements.txt"))
    if len(requirements) != 1:
        raise ValueError("Expected one application requirements file")
    app = requirements[0].parent
    for required in ("LICENSE", "NOTICE", "requirements.txt", "Get/get_loop_health.py"):
        if not (app / required).is_file():
            raise ValueError("Missing runtime file: " + required)
    if not list((app / "Templates").glob("*.doc*")) or not list(
        (app / "Launchers").glob("*.cmd")
    ):
        raise ValueError("Template or launcher missing")
    for launcher in (app / "Launchers").glob("*.cmd"):
        content = launcher.read_bytes()
        if content.startswith(b"\xef\xbb\xbf") or content.count(b"\n") != content.count(
            b"\r\n"
        ):
            raise ValueError("Invalid Windows launcher encoding: " + launcher.name)
    for binary in root.rglob("*.exe"):
        with binary.open("rb") as handle:
            if handle.read(2) != b"MZ":
                raise ValueError("Invalid Windows executable: " + binary.name)
    return app


def run_logged(command: list[str], log: Path, cwd: Path, *, timeout: int = 300) -> None:
    environment = dict(
        os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONNOUSERSITE="1"
    )
    environment.pop("PYTHONPATH", None)
    with log.open("w", encoding="utf-8") as output:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            timeout=timeout,
        )
    if result.returncode:
        raise RuntimeError("Packaged runtime failed. See " + str(log))


def smoke(archive: Path, output: Path, evidence: Path, expected_commit: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    app = verify_archive(archive, output, expected_commit)
    environment = output / "runtime"
    run_logged(
        [sys.executable, "-m", "venv", str(environment)], output / "venv.log", output
    )
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    run_logged(
        [str(python), "-m", "pip", "install", "-r", str(app / "requirements.txt")],
        output / "install.log",
        output,
        timeout=900,
    )
    run_logged([str(python), "-m", "pip", "check"], output / "dependencies.log", output)
    windows = []
    for gui in (app / "Build", app / "App"):
        for source in gui.glob("*_ui.py"):
            for node in ast.parse(source.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef) and any(
                    isinstance(base, ast.Attribute) and base.attr == "CTk"
                    for base in node.bases
                ):
                    windows.append((gui, source.stem, node.name))
    if len(windows) != 1:
        raise ValueError("Expected one packaged application window")
    gui, module, name = windows[0]
    probe = """import importlib,json,pathlib,sys
import customtkinter as ctk
root=pathlib.Path(sys.argv[1]); sys.path[:0]=[str(root),sys.argv[2]]
original=ctk.CTk.__init__
def hidden(self,*args,**kwargs):
    original(self,*args,**kwargs); self.withdraw()
ctk.CTk.__init__=hidden
module=importlib.import_module(sys.argv[3]); app=getattr(module,sys.argv[4])()
app.withdraw(); app.update_idletasks(); app.destroy()
print(json.dumps({'launched':sys.argv[3],'source':module.__file__}))
"""
    run_logged(
        [str(python), "-I", "-c", probe, str(app), str(gui), module, name],
        output / "launcher.log",
        output,
        timeout=90,
    )
    report = output / "report"
    report.mkdir()
    run_logged(
        [
            str(python),
            "-I",
            str(app / "Get/get_loop_health.py"),
            "--input-file",
            str(evidence / "Client_Loop.csv"),
            "--output-folder",
            str(report),
            "--deployment-info-folder",
            str(evidence / "Deployment_Information"),
            "--evaluation-times-file",
            str(evidence / "top10-query-results.csv"),
            "--report-start-date",
            "10-01-2026",
            "--report-end-date",
            "10-02-2026",
            "--include-automated-findings",
        ],
        output / "report.log",
        output,
    )
    for suffix in (".docx", ".xlsx", ".png", ".chartdata.json"):
        if len(list(report.glob("*" + suffix))) != 1:
            raise ValueError("Missing packaged report output: " + suffix)
    sidecar = json.loads(
        next(report.glob("*.chartdata.json")).read_text(encoding="utf-8")
    )
    if sidecar["score"] != 56 or [int(segment["num"]) for segment in sidecar["dist"]] != [
        1,
        2,
        3,
    ]:
        raise ValueError("Packaged report changed the known answers")
    return {
        "passed": True,
        "archive": str(archive),
        "commit": expected_commit,
        "application": str(app),
        "ui": module,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    args = parser.parse_args()
    result = smoke(
        args.archive.resolve(),
        args.output.resolve(),
        args.evidence.resolve(),
        args.expected_commit,
    )
    (args.output / "release-results.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(json.dumps(result, indent=2))
