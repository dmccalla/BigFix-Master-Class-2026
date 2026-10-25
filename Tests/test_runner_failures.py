# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import run_diagnostics as runner


@pytest.mark.parametrize("with_log", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_run_python_drains_child_output_before_failure(
    tmp_path: Path, capsys, with_log: bool, exit_code: int
) -> None:
    script = tmp_path / "child.py"
    script.write_text(
        "import sys\n"
        "print('child stdout', flush=True)\n"
        "sys.stderr.write('last child diagnostic')\n"
        f"sys.exit({exit_code})\n",
        encoding="utf-8",
    )
    log = runner.RunLog() if with_log else None
    if exit_code:
        with pytest.raises(RuntimeError, match=r"child\.py exited with code 7"):
            runner.run_python(script, [], log)
    else:
        assert runner.run_python(script, [], log) == 0
    console = capsys.readouterr().out
    assert "child stdout" in console
    assert "last child diagnostic" in console
    if log is not None:
        log_path = tmp_path / "child.log"
        log.write(log_path)
        saved = log_path.read_text(encoding="utf-8")
        assert "child stdout" in saved
        assert "last child diagnostic" in saved


def _configure_main(monkeypatch, tmp_path: Path, module_key: str, two_captures=True):
    mod = runner.MODULE_BY_KEY[module_key]
    inputs = {field.key: field.default or "" for field in mod.inputs_schema}
    inputs[mod.file_key] = tmp_path / "source"
    if module_key == "perfmon" and two_captures:
        inputs["capture2_blg_path"] = tmp_path / "second.blg"
    context = runner.RunContext([mod], {mod.key: inputs}, None, tmp_path, "Test", {})
    monkeypatch.setattr(runner, "build_run_context", lambda _: context)
    monkeypatch.setattr(sys, "argv", ["run_diagnostics.py", "--config", "test", "--yes"])
    return inputs


class ChildOutputs:
    """Simulate successful generators while withholding one required artifact."""

    def __init__(self, defect: str = "", state: str = "missing"):
        self.defect = defect
        self.state = state
        self.defect_path: Path | None = None
        self.calls: list[str] = []

    def write(self, key: str, path: Path) -> None:
        if key == self.defect:
            self.defect_path = path
            if self.state == "empty":
                path.touch()
            elif self.state == "directory":
                path.mkdir()
        else:
            if path.suffix == ".docx":
                from docx import Document
                Document().save(path)
            else:
                path.write_bytes(b"artifact")

    def __call__(self, script: Path, args: list[str], log=None) -> int:
        self.calls.append(script.name)
        if script.name == "get_loop_health.py":
            folder = Path(args[args.index("--output-folder") + 1])
            for ext in ("xlsx", "png", "docx"):
                self.write(f"loop_{ext}", folder / f"Client_Loop_Analysis_test.{ext}")
        elif script.name == "get_filldb_performance.py":
            for ext, flag in (("docx", "--word-output"), ("png", "--png-output")):
                self.write(f"filldb_{ext}", Path(args[args.index(flag) + 1]))
        elif script.name == "get_perfmon_charts.py":
            workbook = Path(args[args.index("--output") + 1])
            capture = 2 if "Capture_2" in workbook.name else 1
            self.write(f"capture{capture}_xlsx", workbook)
            charts = workbook.parent / (workbook.stem + "_Charts")
            if self.defect == f"capture{capture}_folder":
                self.defect_path = charts
                if self.state == "empty":
                    charts.mkdir()
                elif self.state == "directory":
                    charts.write_bytes(b"not a folder")
            else:
                charts.mkdir()
                self.write(f"capture{capture}_png", charts / "CPU.png")
        elif script.name == "inject_perfmon_charts.py":
            capture = args[args.index("--section-title") + 1][-1]
            self.write(f"mini{capture}", Path(args[args.index("--output-path") + 1]))
        else:
            pytest.fail(f"Unexpected child: {script}")
        return 0


_REQUIRED_OUTPUTS = [
    ("loop", "loop_xlsx", "Loop docx"),
    ("loop", "loop_png", "Loop docx"),
    ("loop", "loop_docx", "Loop docx"),
    ("filldb", "filldb_docx", "FillDB docx"),
    ("filldb", "filldb_png", "FillDB PNG"),
    ("perfmon", "capture1_xlsx", "Output Excel"),
    ("perfmon", "capture1_folder", "Graph folder"),
    ("perfmon", "capture1_png", "Graph folder"),
    ("perfmon", "capture2_xlsx", "Capture 2 Excel"),
    ("perfmon", "capture2_folder", "Capture 2 graphs"),
    ("perfmon", "capture2_png", "Capture 2 graphs"),
    ("perfmon", "mini1", "PerfMon Mini Report"),
    ("perfmon", "mini2", "PerfMon Mini Report"),
]


@pytest.mark.parametrize("module_key,defect,output_label", _REQUIRED_OUTPUTS)
@pytest.mark.parametrize("state", ["missing", "empty", "directory"])
def test_main_rejects_incomplete_outputs_and_preserves_log(
    monkeypatch, tmp_path: Path, capsys, module_key, defect, output_label, state
) -> None:
    _configure_main(monkeypatch, tmp_path, module_key)
    children = ChildOutputs(defect, state)
    monkeypatch.setattr(runner, "run_python", children)

    assert runner.main() == 1
    console = capsys.readouterr().out
    logs = list(tmp_path.rglob("*_RunLog.txt"))
    assert len(logs) == 1
    saved = logs[0].read_text(encoding="utf-8")
    for text in (console, saved):
        assert "[ERROR]" in text
        assert "RuntimeError" in text
        assert "missing or empty" in text
        assert str(children.defect_path.parent) in text
        assert "Run complete" not in text
        assert "   Outputs\n" not in text
        assert output_label not in text
    assert not list(tmp_path.rglob("*_Run_Manifest.json"))
    if defect == "mini2":
        assert (
            not list(tmp_path.rglob("*_Perfmon_Mini_Report.docx")) or state != "missing"
        )


@pytest.mark.parametrize(
    "module_key,failed_child",
    [("loop", 1), ("filldb", 1), *(("perfmon", n) for n in range(1, 5))],
)
def test_main_reports_real_child_failure_at_each_pipeline_stage(
    monkeypatch, tmp_path: Path, capsys, module_key: str, failed_child: int
) -> None:
    _configure_main(monkeypatch, tmp_path, module_key)
    script = tmp_path / "failed_generator.py"
    script.write_text(
        "import sys\nprint('generator diagnostic', flush=True)\nsys.exit(9)\n",
        encoding="utf-8",
    )
    run_python = runner.run_python
    children = ChildOutputs()
    calls = 0

    def run_child(child, args, log):
        nonlocal calls
        calls += 1
        if calls == failed_child:
            return run_python(script, [], log)
        return children(child, args, log)

    monkeypatch.setattr(runner, "run_python", run_child)
    assert runner.main() == 1
    assert calls == failed_child
    saved = next(tmp_path.rglob("*_RunLog.txt")).read_text(encoding="utf-8")
    for text in (capsys.readouterr().out, saved):
        assert "generator diagnostic" in text
        assert "RuntimeError: failed_generator.py exited with code 9" in text
        assert "Run complete" not in text
        assert "   Outputs\n" not in text
    assert not list(tmp_path.rglob("*_Run_Manifest.json"))


@pytest.mark.parametrize("module_key", ["loop", "filldb", "perfmon"])
def test_main_succeeds_without_optional_inputs_or_sidecars(
    monkeypatch, tmp_path: Path, capsys, module_key: str
) -> None:
    _configure_main(monkeypatch, tmp_path, module_key, two_captures=False)
    children = ChildOutputs()
    monkeypatch.setattr(runner, "run_python", children)
    assert runner.main() == 0
    assert "Run complete" in capsys.readouterr().out
    assert list(tmp_path.rglob("*_Run_Manifest.json"))
    if module_key == "perfmon":
        assert children.calls == ["get_perfmon_charts.py", "inject_perfmon_charts.py"]


def test_main_succeeds_with_both_perfmon_captures(monkeypatch, tmp_path, capsys):
    _configure_main(monkeypatch, tmp_path, "perfmon")
    children = ChildOutputs()
    monkeypatch.setattr(runner, "run_python", children)
    assert runner.main() == 0
    assert "Run complete" in capsys.readouterr().out
    assert children.calls == [
        "get_perfmon_charts.py",
        "get_perfmon_charts.py",
        "inject_perfmon_charts.py",
        "inject_perfmon_charts.py",
    ]
