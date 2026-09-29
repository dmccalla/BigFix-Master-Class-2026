#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
run_code_sweep.py -- the quality and security gate.

Runs every configured check, keeps each tool's output, and writes a JSON
report, a Markdown report and a one-page executive summary under
Temp/Code_Sweeps/<timestamp>/. By default it audits only and changes nothing.

Steps, in order:

  pytest          the test suite
  ruff-check      lint (add --apply-ruff-fixes to let it fix)
  ruff-format     formatting check (add --apply-ruff-fixes to reformat)
  bandit          static security analysis of the shipped Python
  pip-audit       known vulnerabilities in the installed packages
  pip-licenses    license inventory of the installed packages
  cyclonedx-py    CycloneDX SBOM of the installed packages
  gitleaks        secret scan of the working tree (skipped when not installed)
  vulture         dead code report (advisory)
  mypy            type check (advisory)

Usage:
  python Build/run_code_sweep.py
  python Build/run_code_sweep.py --apply-ruff-fixes
  python Build/run_code_sweep.py --fail-fast
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_ROOT = REPO_ROOT / "Temp" / "Code_Sweeps"
SOURCE_DIRS = ("App", "Build", "Get", "Inject", "Lib", "Utilities")
SHIPPED_DIRS = ("App", "Get", "Inject", "Lib", "Utilities")


@dataclass
class SweepStep:
    name: str
    command: list[str]
    mutates: bool = False
    output_file: str | None = None
    required: bool = True
    timeout_seconds: int | None = 1800


@dataclass
class StepResult:
    name: str
    command: str
    returncode: int | None
    duration_seconds: float
    status: str
    mutates: bool
    stdout_file: str | None = None
    stderr_file: str | None = None
    parsed_output_file: str | None = None
    notes: str = ""


def _quote(command: list[str]) -> str:
    return subprocess.list2cmdline([str(part) for part in command])


def _tool_available(command: list[str]) -> bool:
    if not command:
        return False
    executable = command[0]
    if executable == sys.executable or Path(executable).exists():
        return True
    return shutil.which(executable) is not None


def _source_targets() -> list[str]:
    return [folder for folder in SOURCE_DIRS if (REPO_ROOT / folder).exists()]


def _shipped_targets() -> list[str]:
    # Only folders that hold Python. mypy exits 2 on a folder without any,
    # and Utilities ships PowerShell and an executable.
    return [
        folder
        for folder in SHIPPED_DIRS
        if (REPO_ROOT / folder).exists() and any((REPO_ROOT / folder).rglob("*.py"))
    ]


def build_steps(*, apply_ruff_fixes: bool, skip_pip_audit: bool) -> list[SweepStep]:
    py = sys.executable
    steps = [
        SweepStep("pytest", [py, "-m", "pytest", "-q"]),
        SweepStep(
            "ruff-check",
            [py, "-m", "ruff", "check", *_source_targets(), "Tests"]
            + (["--fix"] if apply_ruff_fixes else []),
            mutates=apply_ruff_fixes,
        ),
        SweepStep(
            "ruff-format",
            [py, "-m", "ruff", "format", *_source_targets(), "Tests"]
            + ([] if apply_ruff_fixes else ["--check"]),
            mutates=apply_ruff_fixes,
        ),
        SweepStep(
            "bandit",
            [
                py,
                "-m",
                "bandit",
                "-c",
                "pyproject.toml",
                "-r",
                *_shipped_targets(),
                "-f",
                "json",
            ],
            output_file="bandit.json",
        ),
    ]
    if not skip_pip_audit:
        steps.append(
            SweepStep(
                "pip-audit",
                [py, "-m", "pip_audit", "-f", "columns", "--progress-spinner", "off"],
                output_file="pip-audit.txt",
            )
        )
    steps.extend(
        [
            SweepStep(
                "pip-licenses",
                [
                    py,
                    "-m",
                    "piplicenses",
                    "--format=json",
                    "--with-urls",
                    "--with-license-file",
                    "--no-license-path",
                ],
                output_file="pip-licenses.json",
            ),
            SweepStep(
                "cyclonedx-py",
                [
                    py,
                    "-m",
                    "cyclonedx_py",
                    "environment",
                    "--of",
                    "JSON",
                    py,
                ],
                output_file="cyclonedx-bom.json",
            ),
            SweepStep(
                "gitleaks",
                [
                    "gitleaks",
                    "detect",
                    "--source",
                    str(REPO_ROOT),
                    "--no-banner",
                    "--report-format",
                    "json",
                    "--report-path",
                    "-",
                ],
                output_file="gitleaks.json",
                required=False,
            ),
            SweepStep(
                "vulture",
                [py, "-m", "vulture", *_shipped_targets(), "--min-confidence", "80"],
                output_file="vulture.txt",
                required=False,
            ),
            SweepStep(
                "mypy",
                [
                    py,
                    "-m",
                    "mypy",
                    "--ignore-missing-imports",
                    "--no-error-summary",
                    "--exclude",
                    r"(^|[/\\])sitecustomize\.py$",
                    *_shipped_targets(),
                ],
                output_file="mypy.txt",
                required=False,
            ),
        ]
    )
    return steps


def run_step(step: SweepStep, output_dir: Path) -> StepResult:
    command_text = _quote(step.command)
    if not _tool_available(step.command):
        return StepResult(
            step.name,
            command_text,
            None,
            0.0,
            "skipped",
            step.mutates,
            notes="Tool not installed.",
        )
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            step.command,
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=step.timeout_seconds,
            stdin=subprocess.DEVNULL,
        )
        returncode: int | None = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
        notes = ""
    except subprocess.TimeoutExpired as exc:
        returncode = None
        stdout = (
            (exc.stdout or b"").decode("utf-8", "replace")
            if isinstance(exc.stdout, bytes)
            else (exc.stdout or "")
        )
        stderr = (
            (exc.stderr or b"").decode("utf-8", "replace")
            if isinstance(exc.stderr, bytes)
            else (exc.stderr or "")
        )
        notes = f"Timed out after {step.timeout_seconds}s."
    duration = time.perf_counter() - started
    stdout_file = output_dir / f"{step.name}.stdout.txt"
    stderr_file = output_dir / f"{step.name}.stderr.txt"
    stdout_file.write_text(stdout, encoding="utf-8")
    stderr_file.write_text(stderr, encoding="utf-8")
    parsed_file = None
    if step.output_file:
        parsed_file = output_dir / step.output_file
        parsed_file.write_text(stdout, encoding="utf-8")
    if returncode == 0:
        status = "passed"
    elif step.required:
        status = "failed"
    else:
        status = "warning"
    # bandit exits 1 whenever it reports anything, Low included. The gate
    # reads the severities instead: High fails, anything lower is a warning
    # that the executive summary escalates to Review Recommended.
    if step.name == "bandit" and returncode == 1 and parsed_file is not None:
        counts = _bandit_counts(output_dir)
        status = "failed" if counts["High"] else "warning"
        notes = f"High {counts['High']}, Medium {counts['Medium']}, Low {counts['Low']}."
    # gitleaks exits 1 when it finds something: a warning worth reading, not a
    # broken tool. A broken tool is exit 2 or worse.
    if step.name == "gitleaks" and returncode == 1:
        status = "failed"
        notes = "Secrets or credentials reported. Read gitleaks.json."
    return StepResult(
        step.name,
        command_text,
        returncode,
        duration,
        status,
        step.mutates,
        str(stdout_file.relative_to(output_dir)),
        str(stderr_file.relative_to(output_dir)),
        str(parsed_file.relative_to(output_dir)) if parsed_file else None,
        notes,
    )


def _bandit_counts(output_dir: Path) -> dict[str, int]:
    path = output_dir / "bandit.json"
    counts = {"High": 0, "Medium": 0, "Low": 0}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return counts
    for result in data.get("results", []):
        severity = str(result.get("issue_severity", "")).capitalize()
        if severity in counts:
            counts[severity] += 1
    return counts


def _pip_audit_clean(output_dir: Path, results: list[StepResult]) -> bool | None:
    """pip-audit exits 0 on a clean environment and 1 with findings."""
    result = next((r for r in results if r.name == "pip-audit"), None)
    if result is None or result.returncode is None:
        return None
    return result.returncode == 0


def _license_summary(output_dir: Path) -> dict[str, int]:
    path = output_dir / "pip-licenses.json"
    summary: dict[str, int] = {}
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return summary
    for row in rows:
        name = str(row.get("License", "UNKNOWN"))
        summary[name] = summary.get(name, 0) + 1
    return dict(sorted(summary.items(), key=lambda item: (-item[1], item[0])))


def _sbom_component_count(output_dir: Path) -> int | None:
    path = output_dir / "cyclonedx-bom.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return len(data.get("components", []))


def write_third_party_notices(output_dir: Path) -> Path | None:
    """Render pip-licenses.json as THIRD_PARTY_NOTICES.md beside the reports.

    This is the developer environment's inventory, tools included, for the
    sweep report. The release's own notices are written at packaging time by
    Build/third_party_notices.py from a runtime-only environment.
    """
    path = output_dir / "pip-licenses.json"
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    lines = [
        "# Third-Party Notices",
        "",
        "Packages installed into the Workbench's private environment, with their",
        "declared licenses. Generated by the code sweep from pip-licenses.",
        "",
        "| Package | Version | License | Project |",
        "|---|---|---|---|",
    ]
    for row in sorted(rows, key=lambda r: str(r.get("Name", "")).lower()):
        name = row.get("Name", "")
        version = row.get("Version", "")
        license_name = row.get("License", "UNKNOWN")
        url = row.get("URL", "") or ""
        project = f"<{url}>" if url and url != "UNKNOWN" else ""
        lines.append(f"| {name} | {version} | {license_name} | {project} |")
    lines.append("")
    target = output_dir / "THIRD_PARTY_NOTICES.md"
    target.write_text("\n".join(lines), encoding="utf-8")
    return target


def _overall_status(
    results: list[StepResult], bandit: dict[str, int], pip_clean: bool | None
) -> tuple[str, str]:
    if any(r.status == "failed" for r in results):
        return (
            "Action Required",
            "One or more required gates failed and must be fixed before release.",
        )
    if bandit.get("High", 0) > 0:
        return (
            "Action Required",
            "Static security scanning reported high-severity findings.",
        )
    if pip_clean is False:
        return (
            "Action Required",
            "Dependency scanning reported known vulnerable packages.",
        )
    if any(r.status == "warning" for r in results) or bandit.get("Medium", 0) > 0:
        return (
            "Review Recommended",
            "Required gates passed. Advisory findings remain for review.",
        )
    return "Clean", "All configured quality and security gates passed."


def write_reports(
    output_dir: Path, results: list[StepResult], generated: str
) -> tuple[Path, str]:
    bandit = _bandit_counts(output_dir)
    pip_clean = _pip_audit_clean(output_dir, results)
    licenses = _license_summary(output_dir)
    components = _sbom_component_count(output_dir)
    status, note = _overall_status(results, bandit, pip_clean)

    report = {
        "generated": generated,
        "status": status,
        "note": note,
        "bandit": bandit,
        "pip_audit_clean": pip_clean,
        "sbom_components": components,
        "licenses": licenses,
        "steps": [asdict(r) for r in results],
    }
    (output_dir / "code_sweep_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )

    lines = [
        "# Code Sweep Executive Summary",
        "",
        f"Generated: `{generated}`",
        f"Overall status: **{status}**",
        "",
        note,
        "",
        "## Gates",
        "",
        "| Step | Status | Exit | Seconds | Notes |",
        "|---|---|---|---|---|",
    ]
    for r in results:
        code = "-" if r.returncode is None else str(r.returncode)
        lines.append(
            f"| {r.name} | {r.status} | {code} | {r.duration_seconds:.1f} | {r.notes} |"
        )
    lines += [
        "",
        "## Security",
        "",
        f"- Bandit findings: High `{bandit['High']}`, Medium `{bandit['Medium']}`, Low `{bandit['Low']}`",
        f"- pip-audit: `{'clean' if pip_clean else ('findings, see pip-audit.txt' if pip_clean is False else 'not run')}`",
        f"- SBOM components: `{components if components is not None else 'not generated'}` (cyclonedx-bom.json)",
        "",
        "## Licenses",
        "",
    ]
    lines += [f"- {name}: `{count}`" for name, count in licenses.items()] or ["- not run"]
    lines.append("")
    summary = output_dir / "code_sweep_executive_summary.md"
    summary.write_text("\n".join(lines), encoding="utf-8")
    return summary, status


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the quality and security gate.")
    parser.add_argument(
        "--apply-ruff-fixes", action="store_true", help="Let ruff fix and reformat."
    )
    parser.add_argument(
        "--skip-pip-audit",
        action="store_true",
        help="Skip the vulnerability audit (offline).",
    )
    parser.add_argument(
        "--fail-fast", action="store_true", help="Stop at the first failed required gate."
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_OUTPUT_ROOT),
        help="Where the sweep folder is created.",
    )
    args = parser.parse_args()

    generated = datetime.now(UTC).replace(microsecond=0).isoformat()
    output_dir = Path(args.output_root) / datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)

    results: list[StepResult] = []
    for step in build_steps(
        apply_ruff_fixes=args.apply_ruff_fixes, skip_pip_audit=args.skip_pip_audit
    ):
        print(f"[{step.name}] {_quote(step.command)}", flush=True)
        result = run_step(step, output_dir)
        results.append(result)
        print(
            f"    {result.status} ({result.duration_seconds:.1f}s) {result.notes}",
            flush=True,
        )
        if args.fail_fast and result.status == "failed":
            break
    write_third_party_notices(output_dir)
    summary, status = write_reports(output_dir, results, generated)
    print()
    print(f"Overall: {status}")
    print(f"Summary: {summary}")
    return 0 if status != "Action Required" else 1


if __name__ == "__main__":
    sys.exit(main())
