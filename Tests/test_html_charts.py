# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from Lib.Design import html_charts


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
    assert "+ srcScoreBar(score, color)" in section
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
    assert "Bar length is minutes. Colour is health." in section
    assert "Findings raised" in section
    assert "None raised." in section
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
    assert "failed and needs-attention first" in html


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
