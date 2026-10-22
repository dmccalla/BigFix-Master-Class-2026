# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

import contextlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from Lib.Design import html_charts

_CLOSED = "Target page, context or browser has been closed"


def _chart_page():
    page = Mock()
    page.locator.return_value.screenshot.side_effect = lambda *, path: Path(
        path
    ).write_bytes(b"rendered")
    return page


def _chart_browser(*pages):
    browser = Mock()
    browser.is_connected.return_value = True
    browser.new_page.side_effect = list(pages)
    return browser


@pytest.fixture
def chart_runtime(monkeypatch):
    page = _chart_page()
    browser = _chart_browser(page)
    launch = Mock(return_value=browser)
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=launch))
    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: contextlib.nullcontext(playwright),
    )
    monkeypatch.setattr(html_charts, "_ensure_playwright_browser_windows_hidden", Mock())
    monkeypatch.setattr(
        html_charts, "_hide_playwright_driver_window", contextlib.nullcontext
    )
    monkeypatch.setattr(html_charts, "_browser_channels", lambda: ("msedge", "chrome"))
    build_html = Mock(return_value="<html></html>")
    monkeypatch.setattr(html_charts, "_build_html", build_html)
    return SimpleNamespace(
        page=page, browser=browser, launch=launch, build_html=build_html
    )


def test_render_batch_reuses_browser_and_preserves_options(chart_runtime, tmp_path):
    second = _chart_page()
    chart_runtime.browser.new_page.side_effect = [chart_runtime.page, second]
    outputs = [tmp_path / "first.png", tmp_path / "second.png"]
    jobs = [("dashboard", {"title": str(i)}, out) for i, out in enumerate(outputs)]

    assert (
        html_charts.render_charts(
            jobs, scale=2, card_width=1000, type_floor_native_px=40, type_scale=1.2
        )
        == outputs
    )

    chart_runtime.launch.assert_called_once_with(channel="msedge", headless=True)
    assert chart_runtime.browser.new_page.call_count == 2
    for page, (_, data, out) in zip((chart_runtime.page, second), jobs):
        page.set_content.assert_called_once_with(
            "<html></html>", wait_until="networkidle"
        )
        page.wait_for_function.assert_called_once_with("window.__RENDERED__ === true")
        page.locator.assert_called_once_with("#mount")
        page.close.assert_called_once_with()
        assert out.read_bytes() == b"rendered"
        assert json.loads(out.with_suffix(".chartdata.json").read_text()) == {
            "chart": "dashboard",
            **data,
        }
    chart_runtime.browser.new_page.assert_called_with(device_scale_factor=2)
    chart_runtime.build_html.assert_called_with(
        "dashboard", {"title": "1"}, 1000, type_floor_css_px=20, type_scale=1.2
    )
    chart_runtime.browser.close.assert_called_once_with()


def test_render_launch_falls_back_to_next_channel(chart_runtime, tmp_path):
    chart_runtime.launch.side_effect = [
        PlaywrightError("unavailable"),
        chart_runtime.browser,
    ]

    assert html_charts.render_chart("dashboard", {}, tmp_path / "chart.png").exists()
    assert [call.kwargs["channel"] for call in chart_runtime.launch.call_args_list] == [
        "msedge",
        "chrome",
    ]


def test_render_reports_all_launch_failures(chart_runtime, tmp_path):
    error = PlaywrightError("unavailable")
    chart_runtime.launch.side_effect = error

    with pytest.raises(RuntimeError, match="No system Chromium") as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value.__cause__ is error
    assert chart_runtime.launch.call_count == 2
    chart_runtime.browser.new_page.assert_not_called()


@pytest.mark.parametrize(
    "stage", ["new_page", "set_content", "wait_for_function", "screenshot", "close"]
)
def test_render_recovers_once_from_target_closure(chart_runtime, tmp_path, stage, caplog):
    error = PlaywrightError(_CLOSED)
    if stage == "new_page":
        chart_runtime.browser.new_page.side_effect = error
    elif stage == "screenshot":
        chart_runtime.page.locator.return_value.screenshot.side_effect = error
    else:
        getattr(chart_runtime.page, stage).side_effect = error
    recovered_page = _chart_page()
    recovered = _chart_browser(recovered_page)
    chart_runtime.launch.side_effect = [chart_runtime.browser, recovered]
    output = tmp_path / "chart.png"

    assert html_charts.render_chart("dashboard", {"title": "Original"}, output) == output

    assert chart_runtime.launch.call_count == 2
    chart_runtime.build_html.assert_called_once()
    chart_runtime.browser.close.assert_called_once()
    recovered.close.assert_called_once()
    recovered_page.close.assert_called_once()
    assert output.read_bytes() == b"rendered"
    assert (
        json.loads(output.with_suffix(".chartdata.json").read_text())["title"]
        == "Original"
    )
    assert "retrying once" in caplog.text


def test_render_recovers_from_disconnected_browser(chart_runtime, tmp_path):
    chart_runtime.browser.is_connected.return_value = False
    chart_runtime.browser.new_page.side_effect = PlaywrightError("Connection closed")
    recovered = _chart_browser(_chart_page())
    chart_runtime.launch.side_effect = [chart_runtime.browser, recovered]

    assert html_charts.render_chart("dashboard", {}, tmp_path / "chart.png").exists()
    assert chart_runtime.launch.call_count == 2


def test_render_retry_does_not_replay_completed_jobs(chart_runtime, tmp_path):
    first = chart_runtime.page
    chart_runtime.browser.new_page.side_effect = [first, PlaywrightError(_CLOSED)]
    second = _chart_page()
    chart_runtime.launch.side_effect = [chart_runtime.browser, _chart_browser(second)]
    outputs = [tmp_path / "first.png", tmp_path / "second.png"]

    assert (
        html_charts.render_charts([("dashboard", {}, out) for out in outputs]) == outputs
    )

    first.locator.return_value.screenshot.assert_called_once_with(path=str(outputs[0]))
    second.locator.return_value.screenshot.assert_called_once_with(path=str(outputs[1]))


@pytest.mark.parametrize("later_job", [False, True])
def test_render_recovery_budget_is_one_per_batch(chart_runtime, tmp_path, later_job):
    chart_runtime.browser.new_page.side_effect = PlaywrightError(_CLOSED)
    exhausted = PlaywrightError(_CLOSED)
    pages = [_chart_page(), exhausted] if later_job else [exhausted]
    recovered = _chart_browser(*pages)
    chart_runtime.launch.side_effect = [chart_runtime.browser, recovered]
    outputs = [tmp_path / "first.png", tmp_path / "second.png"]

    with pytest.raises(PlaywrightError) as caught:
        html_charts.render_charts([("dashboard", {}, out) for out in outputs])

    assert caught.value is exhausted
    assert chart_runtime.launch.call_count == 2
    assert outputs[0].with_suffix(".chartdata.json").exists() is later_job
    assert not outputs[1].exists()
    recovered.close.assert_called_once()


def test_render_recovery_launch_failure_propagates(chart_runtime, tmp_path):
    chart_runtime.browser.new_page.side_effect = PlaywrightError(_CLOSED)
    unavailable = PlaywrightError("relaunch unavailable")
    chart_runtime.launch.side_effect = [chart_runtime.browser, unavailable, unavailable]

    with pytest.raises(RuntimeError, match="relaunch unavailable"):
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert chart_runtime.launch.call_count == 3
    chart_runtime.browser.close.assert_called_once()


@pytest.mark.parametrize("connected", [True, False])
@pytest.mark.parametrize(
    "error",
    [PlaywrightTimeoutError("timeout"), OSError(_CLOSED), ValueError("invalid data")],
)
def test_render_does_not_retry_timeout_or_non_browser_errors(
    chart_runtime, tmp_path, connected, error
):
    chart_runtime.browser.is_connected.return_value = connected
    chart_runtime.page.set_content.side_effect = error

    with pytest.raises(type(error)) as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value is error
    chart_runtime.launch.assert_called_once()
    chart_runtime.page.close.assert_called_once()
    chart_runtime.browser.close.assert_called_once()


def test_render_does_not_retry_connected_browser_error(chart_runtime, tmp_path):
    error = PlaywrightError("invalid selector")
    chart_runtime.page.locator.return_value.screenshot.side_effect = error

    with pytest.raises(PlaywrightError) as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value is error
    chart_runtime.launch.assert_called_once()


@pytest.mark.parametrize("stage", ["html", "mkdir", "sidecar"])
def test_render_does_not_retry_data_or_output_failure(
    chart_runtime, tmp_path, monkeypatch, stage
):
    error = (
        OSError("output unavailable") if stage != "html" else ValueError("bad payload")
    )
    if stage == "html":
        chart_runtime.build_html.side_effect = error
    elif stage == "mkdir":
        monkeypatch.setattr(Path, "mkdir", Mock(side_effect=error))
    else:
        monkeypatch.setattr(Path, "write_text", Mock(side_effect=error))

    with pytest.raises(type(error)) as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value is error
    chart_runtime.launch.assert_called_once()
    chart_runtime.browser.close.assert_called_once()


@pytest.mark.parametrize("resource", ["page", "browser", "both"])
def test_render_cleanup_preserves_original_failure(chart_runtime, tmp_path, resource):
    error = ValueError("original failure")
    chart_runtime.page.set_content.side_effect = error
    if resource in ("page", "both"):
        chart_runtime.page.close.side_effect = RuntimeError("page cleanup failure")
    if resource in ("browser", "both"):
        chart_runtime.browser.close.side_effect = RuntimeError("browser cleanup failure")

    with pytest.raises(ValueError) as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value is error
    chart_runtime.page.close.assert_called_once()
    chart_runtime.browser.close.assert_called_once()


def test_render_recovery_survives_failed_cleanup(chart_runtime, tmp_path):
    chart_runtime.page.set_content.side_effect = PlaywrightError(_CLOSED)
    chart_runtime.page.close.side_effect = RuntimeError("page cleanup failure")
    chart_runtime.browser.close.side_effect = RuntimeError("browser cleanup failure")
    recovered = _chart_browser(_chart_page())
    chart_runtime.launch.side_effect = [chart_runtime.browser, recovered]

    assert html_charts.render_chart("dashboard", {}, tmp_path / "chart.png").exists()
    assert chart_runtime.launch.call_count == 2


@pytest.mark.parametrize("resource", ["page", "browser"])
def test_render_cleanup_failure_without_prior_error_is_reported(
    chart_runtime, tmp_path, resource
):
    error = RuntimeError("cleanup failure")
    getattr(chart_runtime, resource).close.side_effect = error

    with pytest.raises(RuntimeError) as caught:
        html_charts.render_chart("dashboard", {}, tmp_path / "chart.png")

    assert caught.value is error
    chart_runtime.launch.assert_called_once()


def _chart_path_with_length(folder, length):
    prefix_length = len(str(folder.absolute()).encode("utf-16-le")) // 2 + 1
    return folder / ("x" * (length - prefix_length - len(".png")) + ".png")


def test_windows_chart_preflight_accepts_sidecar_at_boundary(monkeypatch, tmp_path):
    monkeypatch.setattr(html_charts.sys, "platform", "win32")
    output = _chart_path_with_length(tmp_path, 248)

    html_charts._validate_chart_destination(output)

    assert len(str(output.with_suffix(".chartdata.json"))) == 259


@pytest.mark.parametrize("png_length", [249, 260])
def test_windows_chart_preflight_rejects_before_any_batch_writes(
    chart_runtime, monkeypatch, tmp_path, png_length
):
    monkeypatch.setattr(html_charts.sys, "platform", "win32")
    folder = tmp_path / "not-created"
    output = _chart_path_with_length(folder, png_length)
    jobs = [("dashboard", {}, folder / "first.png"), ("dashboard", {}, output)]
    offending = output if png_length == 260 else output.with_suffix(".chartdata.json")

    with pytest.raises(
        ValueError, match="Choose a shorter output folder or run name"
    ) as caught:
        html_charts.render_charts(jobs)

    assert str(offending) in str(caught.value)
    assert not folder.exists()
    chart_runtime.launch.assert_not_called()
    html_charts._ensure_playwright_browser_windows_hidden.assert_not_called()


def test_windows_chart_preflight_resolves_relative_destination(monkeypatch, tmp_path):
    monkeypatch.setattr(html_charts.sys, "platform", "win32")
    monkeypatch.chdir(tmp_path)
    output = _chart_path_with_length(tmp_path, 249)

    with pytest.raises(ValueError, match="Chart output path is too long"):
        html_charts._validate_chart_destination(output.name)


def test_windows_chart_preflight_counts_utf16_units(monkeypatch, tmp_path):
    monkeypatch.setattr(html_charts.sys, "platform", "win32")
    output = _chart_path_with_length(tmp_path, 248)
    output = output.with_name("\U0001f600" + output.name[1:])

    with pytest.raises(ValueError, match="260 UTF-16 units"):
        html_charts._validate_chart_destination(output)


def test_chart_preflight_leaves_non_windows_paths_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(html_charts.sys, "platform", "linux")

    html_charts._validate_chart_destination(_chart_path_with_length(tmp_path, 300))


def test_report_width_override_includes_snapshot_chart() -> None:
    html = html_charts._build_html("snapshot", {}, card_width=1600)

    assert ".card,.dashcard,.snapshot{width:1600px !important;}" in html
    assert "snapshotSection" not in html
    assert "snapshotTitle" not in html
    assert "snapshotEyebrow" not in html
    assert "snapshotGrid" in html
    assert (
        ".snapshotGrid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) minmax(0,1.25fr);gap:12px"
        in html
    )
    assert 'data-card-row-group="snapshot"' in html


def test_chart_template_has_numeric_layout_guardrails() -> None:
    html = html_charts._build_html("loop", {}, card_width=1600)

    assert "font-family:'Roboto Condensed',sans-serif" in html
    assert "font-feature-settings:'tnum' 1" in html
    assert "font-variant-numeric:tabular-nums;" in html
    assert "'zero' 1" not in html
    assert ".statGrid.three{grid-template-columns:repeat(3,minmax(0,1fr));}" in html
    assert ".statGrid.four{grid-template-columns:repeat(4,minmax(0,1fr));}" in html
    assert "grid-template-columns:repeat(4,minmax(0,1fr));gap:16px" in html
    assert ".metricLabel,.metricCaption,.statValue" in html
    assert "const fmtMetric = v =>" in html
    assert "fitNumericValues();" in html
    assert "${fmtMetric(val)}" in html
    assert "${fmtMetric(k.big)}" in html


def test_html_charts_default_to_word_readable_width() -> None:
    assert html_charts._REPORT_CARD_WIDTH == 2250
    assert html_charts._DEFAULT_SCALE == 1.0
    assert html_charts._TYPE_FLOOR_NATIVE_PX == 38.0
    assert html_charts._TYPE_SCALE == 1.0


def test_chart_template_has_report_text_size_floor() -> None:
    html = html_charts._build_html("loop", {}, card_width=960)

    assert "window.CHART_TYPE_SCALE = 1.000000;" in html
    assert "window.CHART_TYPE_FLOOR_CSS_PX = 38.000000;" in html
    assert "function scaleTypeRamp" in html
    assert "function enforceTypeFloor" in html
    assert "if(Number.isFinite(size) && size < floor)" in html
    assert "scaleTypeRamp();\n  fitNumericValues();" in html


def test_chart_template_uses_contrast_safe_bar_text_fills() -> None:
    html = html_charts._build_html("loop", {}, card_width=960)

    assert "function standardStatusColor(color)" in html
    assert "background:${standardStatusColor(c)}" in html
    assert "background: ${filldbStatusColor(x)}" in html


def test_analysis_score_headers_use_shared_non_wrapping_lockup() -> None:
    html = html_charts._build_html("perfmon", {}, card_width=960)

    assert "function scoreLockup" in html
    assert "function analysisHeader" in html
    assert "const scoreText = numeric ? d.score" in html
    assert "${scoreText}" in html
    assert (
        "flex-direction:column;align-items:flex-end;white-space:nowrap;flex:none" in html
    )
    assert "white-space:normal" in html
    assert "analysisHeader(payload,{scoreSize:60,bar:true,statusWord:true})" in html


def test_perfmon_scorecard_keeps_exempt_header_and_simple_metric_cards() -> None:
    html = html_charts._build_html("perfmon", {}, card_width=960)
    section = html[
        html.index("function buildPerfmon") : html.index("function buildDashboard")
    ]

    assert "analysisHeader(" not in section
    assert "scoreLockup(" not in section
    assert "srcHeader('PerfMon Counters'" in section
    assert "+ miniScoreScale(score, color, 'Needs Attention')" in section
    assert "+ miniScoringLine(d.scoringLine, d.sourceLine)" in section
    assert "grid-template-columns:repeat(4,1fr)" in section
    assert "srcPerfmonFindingLine(d)" in section
    assert "limit marker" not in section


def test_chart_template_uses_one_neutral_title_case_pill_grammar() -> None:
    html = html_charts._build_html("overview", {}, card_width=960)
    pill_css = html[html.index(".pill{") : html.index(".pill .dot")]

    assert "text-transform:uppercase" not in pill_css
    assert "letter-spacing:0" in pill_css
    assert "background:var(--status-bg)" in pill_css
    assert "const STATUS_BG = '#F0F2F5'" in html
    assert "background:${STATUS_BG}" in html
    assert "function statusPill" in html
    assert "function countPill" in html


def test_overview_uses_plain_status_header_without_pills() -> None:
    html = html_charts._build_html("overview", {}, card_width=960)
    active_start = html.rindex("function buildOverview")
    section = html[active_start : html.index("function srcCapacityHeader", active_start)]

    assert "const right = ''" in section
    assert "srcHeader(d.title, srcOverviewMeta(d.meta), right)" in section
    assert "SPINE[word].text" not in section
    assert "${word}</div>" not in section
    assert "statusPill(" not in section
    assert "text-transform:uppercase;color:${s.fg}" not in section
    assert "d.status.label}</span>" not in section


def test_snapshot_cards_do_not_render_status_pills() -> None:
    html = html_charts._build_html("snapshot", {}, card_width=960)
    section = html[
        html.index("function snapshotScoreCard") : html.index(
            "function snapshotFindingsCard"
        )
    ]

    assert "snapshotPill(" not in section
    assert "statusPill(" not in section
    assert "${tier||'Not Assessed'}" in section
    assert "height:20px" in section
    assert "d.platform.score, d.platform.footnote" in html


def test_filldb_workload_bars_encode_health_without_dots() -> None:
    html = html_charts._build_html("filldb", {}, card_width=960)
    section = html[
        html.index("function buildFilldb") : html.index(
            "// ---- EXECUTIVE SNAPSHOT HEADLINE CARDS ----"
        )
    ]

    assert "const color = notAssessed ? '#0B1640' : filldbStatusColor(b);" in section
    assert "background: ${color}" in section
    assert "color: ${color}; text-align: right" in section
    assert "pct > 0 && pct < 4 ? '40px'" in section
    assert "width: 640px; font-size: 38px; flex: 0 0 auto" in section
    assert "width: 320px; white-space: nowrap; font-size: 38px" in section
    assert "font-size: 38px" in section
    assert "Bar length is minutes. Color is health." in section
    # Design, 10-21: the Objects Not Healthy block and its slot are gone.
    assert "Findings raised" not in section
    assert "Objects Not Healthy" not in section
    assert "filldbDisplayLabel(b.label) !== 'Batch Rate'" in section
    assert (
        "else mount.className = (d.chart==='loop' || d.chart==='filldb') ? '' : 'card';"
        in html
    )


def test_dashboard_findings_footer_uses_distribution_counts() -> None:
    html = html_charts._build_html("dashboard", {}, card_width=960)
    start = html.rindex("function buildDashboard")
    end = html.index("function srcRiskRow", start)
    section = html[start:end]

    assert "srcDashboardFindingLine(d)" in section
    assert "srcFindingIdList(d.findingIds)" in html
    assert "RSD-01" not in section
    assert "root server below sizing recommendation" not in section


def test_active_chart_findings_footers_do_not_invent_sample_findings() -> None:
    html = html_charts._build_html("perfmon", {}, card_width=960)
    active_region = html[html.index("function srcDashboardFindingLine") :]

    assert "PERF-13" not in active_region
    assert "storage latency above limit" not in active_region
    assert "CLT-01" not in html
    assert "client evaluation loop too slow" not in html
    assert "srcPerfmonFindingLine(d)" in active_region
    assert "srcDashboardFindingLine(d)" in active_region


def test_rollup_findings_footers_use_traceable_summaries() -> None:
    html = html_charts._build_html("dashboard", {}, card_width=960)
    source_region = html[html.index("// ---- Source transcription overrides") :]
    summary_helper = source_region[
        source_region.index("function srcFindingSummaryLine") : source_region.index(
            "function srcDate"
        )
    ]
    dashboard = source_region[
        source_region.index("function buildDashboard") : source_region.index(
            "function srcRiskRow"
        )
    ]
    perfmon = source_region[
        source_region.index("function buildPerfmon") : source_region.index(
            "function buildDashboard"
        )
    ]
    breakdown = source_region[
        source_region.index("function buildBreakdown") : source_region.index(
            "function srcBalanceRow"
        )
    ]
    balance_helpers = source_region[
        source_region.index("function srcBalanceRow") : source_region.index(
            "function buildBalance"
        )
    ]
    balance = source_region[
        source_region.index("function buildBalance") : source_region.index(
            "function srcPerfmonCaption"
        )
    ]

    assert 'data-single-line="findings-split"' in summary_helper
    assert "white-space:nowrap;overflow:hidden;text-overflow:ellipsis;" in summary_helper
    assert "function srcFindingIdList" in summary_helper
    assert "function srcFindingIdPreview" in summary_helper
    assert "+${fmtCount(clean.length - max)} more below" in summary_helper
    assert "<strong>IDs</strong>" in summary_helper
    assert ".map(f=>" not in dashboard
    assert ".map(f=>" not in perfmon
    assert "srcFooter('Findings raised', srcDashboardFindingLine(d))" in dashboard
    assert "srcFooter('Findings raised', srcPerfmonFindingLine(d))" in perfmon
    assert (
        "srcFindingSummaryLine(summaryLine) + srcFindingSummaryLine(ids)" in source_region
    )
    assert "const footerLine = srcFindingSummaryLine(" in breakdown
    assert "const footerLine = srcBalanceFindingFooter(d, count, split);" in balance
    assert "Partially Assessed" in balance_helpers
    assert "not assessed</span>" in balance_helpers
    assert "full trace below" in source_region


def test_what_needs_attention_overflow_copy_matches_design() -> None:
    """The design is Duncan's ruling of 2026-09-07, applied in commit 7652327.

    Verbatim: "WNA cards. Drop the two-card cap. Cards for every Critical and
    High finding. Remainder line reads 'N Medium and N Low in Findings and
    Recommendations.'"

    The copy lives in `Assets/chart_template.html`, not in
    `html_charts.py`. That distinction cost six days: this test failed from
    2026-09-07, and three passes reported it as pre-existing on the grounds
    that `html_charts.py` was unmodified, which was true and beside the point.

    Cite the ruling here if this copy ever changes again. A test named for a
    design that names no design cannot tell the next reader whether the test
    or the code is the stale one.
    """
    html = html_charts._build_html("risks", {}, card_width=960)

    # Layout, independent of the wording.
    assert "grid-template-columns:150px minmax(0,1fr) 150px" in html
    assert 'data-single-line="source-id"' in html
    assert "min-width:124px;text-align:center" in html

    # The chart standard's type floor. This survives whatever the copy becomes.
    assert 'style="font-size:38px;margin-top:18px;"' in html

    # The remainder line, in both the small and large variants, because the
    # template carries the substitution in both.
    remainder = (
        "${fmtCount(medium)} Medium and ${fmtCount(low)} Low "
        "in Findings and Recommendations."
    )
    assert html.count(remainder) == 2, html.count(remainder)
    assert (
        '<div style="font-size:14px;color:#0B1640;text-align:left;'
        f'margin-top:7px;">{remainder}</div>'
    ) in html
    assert f'<div style="font-size:38px;margin-top:18px;">{remainder}</div>' in html

    # Superseded wordings, each guarding against a revision coming back.
    assert "shown here" not in html
    assert "more item" not in html
    assert "Top ${fmtCount(" not in html
    assert "more in Findings &amp; Recommendations" not in html


def test_loop_legend_normalizes_attention_to_warning() -> None:
    html = html_charts._build_html("loop", {}, card_width=960)

    assert ".replace(/^Needs Attention\\b/i,'Warning')" in html


def test_scorecard_header_does_not_repeat_coverage_line() -> None:
    html = html_charts._build_html("scorecard", {}, card_width=960)
    section = html[
        html.index("function buildScorecard") : html.index("// ---- SCORE BREAKDOWN")
    ]

    assert "const headerPayload = Object.assign({}, d, {coverageLine:''});" in section
    assert "scoreLockup(headerPayload,56,{statusWord:true})" in section
    assert 'coverageLine?`<div class="metricCaption"' in section


def test_balance_and_breakdowns_suppress_duplicate_header_coverage() -> None:
    html = html_charts._build_html("balance", {}, card_width=960)

    assert "function dedupeCoverageStats" in html
    assert "scoreLockup(headerPayload,56,{statusWord:true})" in html
    assert "analysisHeader(payload,{scoreSize:60,bar:true,statusWord:true})" in html
    assert "cleanSub = 'out of 100'" in html
    assert "cleanSub = 'focus areas'" in html


def test_not_assessed_rows_do_not_report_clean_findings() -> None:
    html = html_charts._build_html("balance", {}, card_width=960)
    breakdown_start = html.index("function renderBreakdown")
    breakdown_null = html[
        html.index("if(score==null){", breakdown_start) : html.index(
            "const b=bandOf", breakdown_start
        )
    ]
    balance_start = html.index("function balRow")
    balance_null = html[balance_start : html.index("const b=bandOf", balance_start)]

    assert "impactSplitHTML(split)" not in breakdown_null
    assert "impactSplitHTML(split)" not in balance_null
    assert "Not Assessed" in breakdown_null
    assert "Not Assessed" in balance_null


def test_snapshot_findings_card_omits_focus_area_label() -> None:
    html = html_charts._build_html("snapshot", {}, card_width=960)
    section = html[
        html.index("function snapshotFindingsCard") : html.index("function buildSnapshot")
    ]

    assert "focus areas" not in section
    assert "const sourceLine = ''" in section


def test_category_score_rows_keep_standard_category_labels_on_one_line() -> None:
    html = html_charts._build_html("platformhealth", {}, card_width=960)

    assert "grid-template-columns:440px minmax(0,1fr) 170px 620px" in html
    assert "grid-template-columns:250px minmax(0,1fr) 72px 260px" not in html
    assert 'data-single-line="category-label"' in html
    assert 'data-single-line="findings-split"' in html


def test_dashboard_section_health_rows_have_non_wrapping_label_and_count_columns() -> (
    None
):
    html = html_charts._build_html("dashboard", {}, card_width=960)
    dash_start = html.index("function buildDashboard")
    start = html.index("const rows =", dash_start)
    section = html[start : html.index("return srcHeader", start)]

    assert "display:flex;align-items:center;gap:24px;" in section
    assert 'data-single-line="object-label"' in section
    assert "width:440px;font-size:38px;flex:0 0 auto;" in section
    assert "width:500px;font-size:38px;text-align:right;flex:0 0 auto;" in section
    # Build handoff Part 1.2: no hyphen in "Needs Attention".
    assert "Section Health &middot; Failed and Needs Attention First" in html
    assert "needs-attention" not in html.lower()


def test_chart_template_marks_cells_for_rendered_single_line_validation() -> None:
    html = html_charts._build_html("dashboard", {}, card_width=960)

    assert "function markSingleLineCells" in html
    assert 'data-single-line="subtitle"' not in html
    assert 'data-single-line="card-subline"' not in html
    assert 'data-single-line="source-id"' in html
    assert 'data-single-line="object-label"' in html


def test_snapshot_and_overview_card_rows_are_marked_without_orphans() -> None:
    html = html_charts._build_html("overview", {}, card_width=960)

    assert 'data-card-row-group="overview-kpis"' in html
    assert 'data-card-row-group="overview-ratios"' in html
    assert 'data-card-row-group="overview-activity"' in html
    assert "grid-template-columns:repeat(4,minmax(0,1fr));gap:16px" in html
    assert 'data-single-line="card-subline"' not in html


def test_zero_score_bars_have_visible_fill_not_empty_track() -> None:
    html = html_charts._build_html("platformhealth", {}, card_width=960)

    assert "function scoreFill" in html
    assert "const min = pct === 0 ? 'min-width:10px;' : ''" in html
    assert "${score==null?'':scoreFill(score, meterColor)}" in html
    assert "${scoreFill(score, barOf[b])}" in html
    assert "score==null" in html


def test_dash_separators_are_normalized_to_middle_dots() -> None:
    html = html_charts._build_html("dashboard", {}, card_width=960)

    assert "const SRC_DOT = '&middot;';" in html
    assert "Console dashboard rollup &middot;" in html
    assert "${srcText(label)} ${SRC_DOT}" in html
    assert "${fmtCount(p)} passed ${SRC_DOT}" in html


def test_strength_rows_match_reference_with_healthy_pill_and_score() -> None:
    html = html_charts._build_html("strengths", {}, card_width=960)
    section = html[
        html.index("function healthyRow") : html.index("function buildStrengths")
    ]

    assert "grid-template-columns:180px minmax(0,1fr) 70px" in section
    assert ">Healthy</span>" in section
    assert "text-align:right" in section
    assert "cleanStrengthEvidence" in section


def test_overview_bars_use_score_status_or_neutral_tracks_only() -> None:
    html = html_charts._build_html("overview", {}, card_width=960)
    section = html[
        html.index("function buildOverview") : html.index("// ---- FILLDB PERFORMANCE")
    ]

    assert "overviewStatusWord(k)" in section
    assert "#3D5A80" not in section
    assert "background:#F0F2F5;border-radius:3px;" in section


def test_mini_report_infographics_carry_the_scoring_legend() -> None:
    """Design 10-20, Section 3: larger score, ticks at 70 and 90, named ranges and
    a scoring line on the Client Performance, FillDB and PerfMon cards."""
    html = html_charts._build_html("loop", {}, card_width=960)
    helpers = html[
        html.index("function miniScoreLockup") : html.index("// ---- LOOP ----")
    ]
    assert "font-size:153px" in helpers
    assert "letter-spacing:0.14em" in helpers
    assert "left:70%" in helpers and "left:90%" in helpers
    assert "0 to 69" in helpers and "70 to 89" in helpers and "90 to 100" in helpers
    for builder, middle in (
        ("function buildLoop", "'Warning'"),
        ("function buildFilldb", "'Needs Attention'"),
        ("function buildPerfmon", "'Needs Attention'"),
    ):
        start = html.index(builder)
        section = html[start : html.index("\nfunction ", start + 10)]
        assert "miniScoreLockup(" in section, builder
        assert f", {middle})" in section, builder
        assert "miniScoringLine(d.scoringLine" in section, builder
    loop = html[
        html.index("function buildLoop") : html.index("// ---- SCORING SUMMARY ----")
    ]
    assert "${l.points} pts" in loop


def test_source_lines_sit_above_the_scoring_line() -> None:
    """CP-25 and PM-17: where the numbers live, directly above the scoring line."""
    html = html_charts._build_html("loop", {}, card_width=960)
    helper = html[
        html.index("function miniScoringLine") : html.index("// ---- LOOP ----")
    ]
    assert helper.index("${sourceLine}") < helper.index("${scoringLine}")
    assert "miniScoringLine(d.scoringLine, d.sourceLine)" in html
    perfmon = html[html.index("function buildPerfmon") :]
    assert "miniScoringLine(d.scoringLine, d.sourceLine)" in perfmon[:3000]
