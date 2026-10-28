# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Chart evidence must agree with uncapped readings and VM assessments."""

from __future__ import annotations

import get_perfmon_charts as perfmon
import matplotlib.axes
import matplotlib.figure
import numpy as np
import pandas as pd
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg


def analyze(counter, values, vm=False):
    frame = pd.DataFrame(
        {
            "Time": pd.date_range("2026-06-14", periods=len(values), freq="min"),
            counter: values,
        }
    )
    chart, findings = perfmon.analyze(
        frame,
        [counter],
        12,
        1,
        vm,
        3,
        0.5,
        1.1,
        "start",
        "end",
        "Supplied",
        "Detected",
        "Detected",
    )
    return frame, chart, findings


def test_rolling_average_uses_original_samples_when_plot_is_capped():
    counter = "System_Processor_Queue_Length"
    original, chart, findings = analyze(counter, [1, 1, 100, 1, 1])
    assert chart[counter].iloc[2] < 100
    assert chart[counter + "_RollingAvg"].iloc[2] == pytest.approx(34)
    assert findings[0]["Average"] == pytest.approx(20.8)
    assert findings[0]["Maximum"] == 100
    assert original[counter].tolist() == [1, 1, 100, 1, 1]


def capture_figures(monkeypatch):
    captured = []
    original = matplotlib.figure.Figure.savefig

    def save(figure, *args, **kwargs):
        FigureCanvasAgg(figure).draw()
        captured.append(figure)
        original(figure, *args, **kwargs)

    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", save)
    return captured


def export(chart, counter, findings, destination, vm=False):
    perfmon.export_png_charts(
        chart,
        [counter],
        findings,
        str(destination),
        3,
        0.5,
        1.1,
        "start",
        "end",
        memory_gb=12,
        disk_count=1,
        vm=vm,
        host_name="test-root",
    )


def test_zero_vm_cpu_strip_uses_assessed_advisory(monkeypatch, tmp_path):
    counter = "Processor_Total_Processor_Time"
    _, chart, findings = analyze(counter, [0, 0, 0], vm=True)
    assert findings[0]["Status"] == "Warning"
    figures = capture_figures(monkeypatch)
    export(chart, counter, findings, tmp_path, vm=True)
    labels = [t.get_text() for t in figures[0].texts]
    assert any("ADVISORY" in label for label in labels)
    assert not any("PASS" in label for label in labels)


def test_vm_cpu_plot_draws_the_lower_boundary(monkeypatch, tmp_path):
    counter = "Processor_Total_Processor_Time"
    _, chart, findings = analyze(counter, [20, 30, 40], vm=True)
    figures = capture_figures(monkeypatch)
    export(chart, counter, findings, tmp_path, vm=True)
    axis = figures[0].axes[0]
    assert any(
        len(line.get_ydata()) == 2 and np.allclose(line.get_ydata(), [50, 50])
        for line in axis.lines
    )
    assert any(
        "VM advisory floor" in label for label in axis.get_legend_handles_labels()[1]
    ) or any("VM advisory floor" in t.get_text() for t in axis.get_legend().get_texts())


def test_long_zero_strip_standard_does_not_overlap_result(monkeypatch, tmp_path):
    figures = capture_figures(monkeypatch)
    perfmon.render_zero_counter_strip(
        "PhysicalDisk_F_Disk_Transfers_sec",
        str(tmp_path / "zero.png"),
        pd.Series(pd.date_range("2026-06-14", periods=3, freq="min")),
        {
            "label": "No saturation under load. The 5,000 transfers/sec guide value is reference context only."
        },
        "start - end",
        True,
        sample_count=3,
        status="OK",
    )
    figure = figures[0]
    renderer = FigureCanvasAgg(figure).get_renderer()
    standard = next(t for t in figure.texts if t.get_text().startswith("Standard:"))
    result = next(t for t in figure.texts if "All recorded values" in t.get_text())
    assert not standard.get_window_extent(renderer).overlaps(
        result.get_window_extent(renderer)
    )


def test_excel_vm_chart_includes_both_cpu_boundaries(tmp_path):
    import zipfile

    counter = "Processor_Total_Processor_Time"
    raw, chart, findings = analyze(counter, [20, 30, 40], vm=True)
    output = tmp_path / "vm.xlsx"
    perfmon.export_excel(
        raw,
        chart,
        findings,
        [],
        [counter],
        str(output),
        3,
        "start",
        "end",
        memory_gb=12,
        disk_count=1,
        vm=True,
    )
    with zipfile.ZipFile(output) as archive:
        charts = [
            archive.read(name).decode()
            for name in archive.namelist()
            if name.startswith("xl/charts/chart") and name.endswith(".xml")
        ]
        cpu = next(xml for xml in charts if "VM advisory floor" in xml)
        assert "VM advisory floor: 50%" in cpu
        assert "Standard:" in cpu
        assert ">50<" in cpu and ">80<" in cpu
