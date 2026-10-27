# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""PRF-INF-09 scores page file use as a percent of physical memory.

The NFR guide sets the limit at 5% of physical memory. Paging File % Usage
Peak is a percent of the page file, so the Workbench converts it with the
Memory Commit Limit counter. Without physical memory the counter is not scored.
"""

from __future__ import annotations

import get_perfmon_charts as perfmon
import pandas as pd
import pytest

GIB = 1024**3
USAGE = "Paging_File_Total_Usage_Peak"
COMMIT = "Memory_Commit_Limit"


def _frame(usage: list, commit: list | None) -> pd.DataFrame:
    data = {
        "Sample": range(1, len(usage) + 1),
        "Time": pd.date_range("2026-06-14 20:00", periods=len(usage), freq="min"),
        USAGE: usage,
    }
    if commit is not None:
        data[COMMIT] = commit
    return pd.DataFrame(data)


def _analyze(df: pd.DataFrame, memory_gb: int) -> dict:
    _chart, findings = perfmon.analyze(
        df,
        [USAGE],
        memory_gb,
        0,
        False,
        10,
        0.98,
        1.15,
        "06-14-2026 20:00",
        "06-14-2026 20:03",
        "Parameter Supplied" if memory_gb else "Not supplied",
        "Not supplied",
        "Not supplied",
    )
    return next(item for item in findings if item["Counter"] == USAGE)


def test_page_file_use_is_converted_to_a_percent_of_physical_memory() -> None:
    # 16 GiB commit limit and 12 GiB of RAM leave a 4 GiB page file. Half of it
    # in use is 2 GiB, which is 16.67% of physical memory.
    result = perfmon.page_file_percent_of_memory(
        pd.Series([50.0]), pd.Series([16 * GIB]), 12
    )
    assert result.iloc[0] == pytest.approx(2 / 12 * 100)


def test_scored_counter_uses_the_physical_memory_basis() -> None:
    finding = _analyze(_frame([3.0, 3.0, 3.0], [16 * GIB] * 3), 12)

    assert finding["Status"] == "OK"
    assert finding["Average"] == pytest.approx(1.0)
    assert not finding.get("NotScoredReason")
    assert "physical memory" in finding["Threshold"]


def test_counter_is_not_scored_without_physical_memory() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 0)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == perfmon.MEMORY_NOT_SUPPLIED
    assert finding["PeakViolationWindow"] == (
        f"Not compared with the limit: {perfmon.MEMORY_NOT_SUPPLIED}"
    )


def test_counter_is_not_scored_without_the_commit_limit_counter() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], None), 12)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == perfmon.COMMIT_LIMIT_MISSING


def test_blank_page_file_counter_still_reports_no_samples() -> None:
    finding = _analyze(_frame([None, None, None], [16 * GIB] * 3), 0)

    assert finding["Status"] == "Not Available"
    assert finding["NotScoredReason"] == ""
    assert finding["PeakViolationWindow"] == "No samples recorded"


def test_not_scored_observation_names_the_reason() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 0)
    observation = perfmon.observation_for_findings("Memory Health", [finding])

    assert observation["status"] == "Not Available"
    assert perfmon.MEMORY_NOT_SUPPLIED in observation["observation"].lower()
    assert "No samples were recorded" not in observation["observation"]
    assert observation["observation"].startswith(
        "Physical memory was not supplied, so this area cannot be verified. "
        "Cannot Verify earns 25 points in the score."
    )
    assert "not scored" not in observation["observation"]


def test_commit_limit_is_collected_but_never_charted(tmp_path) -> None:
    assert r"\Memory\Commit Limit" in perfmon.COUNTERS

    csv_path = tmp_path / "capture.csv"
    csv_path.write_text(
        '"(PDH-CSV 4.0)","\\\\BFROOT1\\Paging File(_Total)\\% Usage Peak",'
        '"\\\\BFROOT1\\Memory\\Commit Limit"\n'
        f'"06/14/2026 20:17:40.000","47.1","{16 * GIB}"\n',
        encoding="utf-8",
    )
    df, counter_cols = perfmon.load_and_normalize(str(csv_path))

    assert counter_cols == [USAGE]
    assert COMMIT in df.columns
    assert df[COMMIT].iloc[0] == 16 * GIB


def test_not_scored_strip_names_the_reason() -> None:
    message, label, _color = perfmon.zero_counter_strip_text(
        USAGE, False, perfmon.MEMORY_NOT_SUPPLIED
    )
    assert message == f"Not compared with the limit: {perfmon.MEMORY_NOT_SUPPLIED}"
    assert label == "CANNOT VERIFY"


def test_scored_observation_keeps_the_physical_memory_basis() -> None:
    finding = _analyze(_frame([47.0, 47.0, 47.0], [16 * GIB] * 3), 12)
    observation = perfmon.observation_for_findings("Memory Health", [finding])

    assert observation["status"] == "Critical"
    assert "a limit of 5% of physical memory" in observation["observation"]


def test_missing_memory_strip_keeps_reason_result_and_standard_separate(
    tmp_path, monkeypatch
):
    from matplotlib.figure import Figure

    saved = []
    original = Figure.savefig

    def inspect(figure, *args, **kwargs):
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        boxes = [
            (text.get_text(), text.get_window_extent(renderer)) for text in figure.texts
        ]
        for index, (left_text, left) in enumerate(boxes):
            for right_text, right in boxes[index + 1 :]:
                assert not left.overlaps(right), (left_text, right_text)
        saved.extend(text for text, _ in boxes)
        return original(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", inspect)
    perfmon.render_zero_counter_strip(
        USAGE,
        str(tmp_path / "missing_memory.png"),
        _frame([1, 1], None)["Time"],
        {"label": "5% of physical memory"},
        "06-14-2026 20:00 to 20:01",
        True,
        sample_count=2,
        not_scored_reason=perfmon.MEMORY_NOT_SUPPLIED,
    )
    assert "CANNOT VERIFY" in saved
    assert f"Not compared with the limit: {perfmon.MEMORY_NOT_SUPPLIED}" in saved


@pytest.mark.parametrize("memory_gb", [12, 128])
def test_nonzero_paging_plot_keeps_footer_legend_and_axis_labels_separate(
    tmp_path, monkeypatch, memory_gb
):
    from matplotlib.figure import Figure

    frame = _frame([47.0, 48.0, 47.5], [(memory_gb + 4) * GIB] * 3)
    chart, findings = perfmon.analyze(
        frame,
        [USAGE],
        memory_gb,
        0,
        False,
        10,
        0.98,
        1.15,
        "06-14-2026 20:00",
        "06-14-2026 20:03",
        "Parameter Supplied",
        "Not supplied",
        "Not supplied",
    )
    inspected = []
    original = Figure.savefig

    def inspect(figure, *args, **kwargs):
        figure.canvas.draw()
        renderer = figure.canvas.get_renderer()
        footer = next(t for t in figure.texts if t.get_text().startswith("Y-Axis:"))
        footer_box = footer.get_window_extent(renderer)
        axes = figure.axes[0]
        legend_box = axes.get_legend().get_window_extent(renderer)
        assert not footer_box.overlaps(legend_box)
        for tick in axes.get_xticklabels():
            if tick.get_visible() and tick.get_text():
                assert not legend_box.overlaps(tick.get_window_extent(renderer))
        for box in (footer_box, legend_box):
            assert figure.bbox.contains(box.x0, box.y0)
            assert figure.bbox.contains(box.x1, box.y1)
        inspected.append(footer.get_text())
        return original(figure, *args, **kwargs)

    monkeypatch.setattr(Figure, "savefig", inspect)
    perfmon.export_png_charts(
        chart,
        [USAGE],
        findings,
        str(tmp_path / "Charts"),
        10,
        0.98,
        1.15,
        "06-14-2026 20:00",
        "06-14-2026 20:03",
        memory_gb=memory_gb,
    )
    assert len(inspected) == 1
    assert "Actual peak:" in inspected[0]
    assert "physical memory" in inspected[0]
