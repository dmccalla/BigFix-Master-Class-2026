# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Apply the reviewed Client layout to live module output, using current data."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from docx.text.paragraph import Paragraph
from lxml import etree

from Lib.Design import html_charts
from Lib.Design.report_layout import (
    add_callout,
    compact_table_header_style,
    normalize_heading_typography,
    normalize_section_spacing,
)
from Lib.Themes.word_stub_utils import set_picture_alt_text


def _text(node):
    return "".join(node.xpath(".//w:t/text()"))


def _count(value):
    value = str(value).split("/")[0].replace(",", "")
    try:
        return float(re.match(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)", value).group())
    except (ValueError, AttributeError):
        return 0


def apply_client_layout(
    document, output_path, module, *, sections, render_details=True, **context
):
    """Replace supporting tables with truthful charts; retain workbook detail."""
    m = module
    body = document.element.body
    metrics = context["metrics"]
    jobs = []

    def heading(label):
        return sections.get(label)

    def replace_table(label, kind, data, alt):
        if not render_details:
            return
        h = heading(label)
        if h is None:
            raise ValueError(f"Missing Client section anchor: {label}")
        table = h._p.getnext()
        while table is not None and table.tag != qn("w:tbl"):
            if table.tag == qn("w:p") and table.find(qn("w:pPr")) is not None:
                style = table.find(qn("w:pPr")).find(qn("w:pStyle"))
                if style is not None and style.get(qn("w:val"), "").startswith("Heading"):
                    raise ValueError(f"Missing Client data table: {label}")
            table = table.getnext()
        if table is None:
            raise ValueError(f"Missing Client data table: {label}")
        path = Path(output_path).with_suffix("") / (kind + "_" + str(len(jobs)) + ".png")
        path.parent.mkdir(parents=True, exist_ok=True)
        jobs.append(("clientdetail", {"kind": kind, **data}, path, table, alt))

    rows = []
    colors = ["#187A43", "#4E8F2B", "#B45309", "#C2410C", "#C2410C"]
    for index, row in enumerate(m.loop_group_rows(metrics)):
        rows.append(
            {
                "label": row[0] + " | " + row[3],
                "count": _count(row[1]),
                "color": colors[min(index, 4)],
            }
        )
    replace_table(
        "Loop Health",
        "groups",
        {"total": metrics.score_total_devices, "rows": rows},
        "Devices grouped by average loop time, with counts and percentages of all scored devices.",
    )
    offenders = context.get("loop_offenders") or []
    intervals = context.get("property_intervals")
    if offenders:
        rows = []
        for item in offenders:
            raw = item.result
            kind = m.offender_kind(raw)
            name = m.format_loop_offender_evaluation(raw, intervals)
            if kind == 0:
                name = m.compact_loop_offender_label(raw, limit=1000)
            rows.append(
                {
                    "rank": item.rank,
                    "seconds": item.avg_client_processing_seconds,
                    "occurrences": item.occurrences,
                    "name": name,
                    "property": kind in {1, 2},
                    "interval": m.offender_interval(raw, intervals),
                }
            )
        alt = "Top evaluations by average processing time. " + " ".join(
            f"{r['rank']}. {r['name']}: {r['seconds']:.1f} seconds, {r['occurrences']:,} occurrences"
            + (f", interval {r['interval']}." if r["property"] else ".")
            for r in rows
        )
        replace_table("Top 10 Most Expensive Evaluations", "costs", {"rows": rows}, alt)
    if intervals:
        buckets = m.property_interval_band_counts(intervals)
        rows = [
            {
                "label": label,
                "count": entry["total"],
                "custom": entry["custom"],
                "external": entry["external"],
                "status": m.interval_band_status(label),
            }
            for label, entry in buckets.items()
            if label != "Unreadable" or entry["total"]
        ]
        frequent = sum(
            r["count"] for r in rows if r["label"] in {"Every report", "Under 15 minutes"}
        )
        alt = (
            f"Property evaluation intervals among {len(intervals.counted):,} counted properties. "
            + " ".join(f"{r['label']}: {r['count']:,}, {r['status']}." for r in rows)
            + f" Counted in CLT-01: {frequent:,}."
        )
        replace_table(
            "Evaluation Frequency",
            "frequency",
            {"total": len(intervals.counted), "rows": rows, "frequent": frequent},
            alt,
        )
        h = heading("Evaluation Frequency")
        if h is not None and render_details:
            lead = next((p for p in document.paragraphs if p._p is h._p.getnext()), None)
            if lead is not None:
                lead.text = m.evaluation_frequency_lead(intervals, graphic=True)
            reserved = next(
                (
                    p
                    for p in document.paragraphs
                    if p.text.startswith("Reserved properties are")
                ),
                None,
            )
            if reserved is not None:
                table = add_callout(
                    document, reserved.text.replace("this table", "this graphic")
                )
                before, after = table._tbl.getprevious(), table._tbl.getnext()
                reserved._p.addprevious(before)
                reserved._p.addprevious(table._tbl)
                reserved._p.addprevious(after)
                reserved._p.getparent().remove(reserved._p)
    pressure = context.get("actionsite_pressure")
    if pressure:
        anchor = heading("Contributing Factors")
        values = [
            (
                "Fixlets and tasks",
                m._sum_if_any(
                    pressure.fixlets_relevant_count, pressure.tasks_relevant_count
                ),
                m._sum_if_any(pressure.fixlets_total_count, pressure.tasks_total_count),
            ),
            (
                "Active analyses",
                pressure.active_analyses_count,
                pressure.analyses_total_count,
            ),
            (
                "Active properties",
                pressure.active_properties_count,
                pressure.properties_count,
            ),
        ]
        rows = [
            {"label": name, "count": count, "total": total}
            for name, count, total in values
            if count is not None and total is not None
        ]
        if anchor is not None and rows and render_details:
            title = document.add_heading("Content Counts", level=4)
            anchor._p.addprevious(title._p)
            marker = OxmlElement("w:p")
            anchor._p.addprevious(marker)
            path = Path(output_path).with_suffix("") / "content_counts.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            jobs.append(
                (
                    "clientdetail",
                    {"kind": "counts", "rows": rows},
                    path,
                    marker,
                    "Relevant Fixlets and tasks, active analyses and active properties. Each bar uses its own total. The counts do not measure a share of loop time.",
                )
            )
        if pressure.content_captured:
            for table in document.tables:
                if len(table.columns) == 4 and table.cell(0, 0).text == "Metric":
                    for row in table.rows[1:]:
                        row.cells[1].text = re.sub(
                            r", as of the .*? capture\.", ".", row.cells[1].text
                        )
    idle = context.get("agent_cpu_idle_summary")
    if idle:
        rows = [
            {
                "work": _count(r[0]),
                "sleep": _count(r[1]),
                "duty": r[2],
                "count": _count(r[3]),
            }
            for r in idle.settings_rows
            if _count(r[0]) + _count(r[1]) > 0
        ]
        if rows:
            replace_table(
                "CPU Idle Settings",
                "duty",
                {
                    "total": idle.total_devices,
                    "rows": rows,
                    "unset": sum(
                        _count(r[3])
                        for r in idle.settings_rows
                        if _count(r[0]) + _count(r[1]) == 0
                    ),
                },
                "Configured CPU work and sleep intervals. Bar segments represent time, not the percentage of devices.",
            )
    multicore = context.get("agent_multicore_summary")
    if multicore:
        source = {r[0]: _count(r[1]) for r in multicore.settings_rows}
        order = ["On", "Not Applicable", "Not Set", "Off", "Unknown"]
        colors = {
            "On": "#0C7E88",
            "Not Applicable": "#000032",
            "Not Set": "#AEB8C6",
            "Off": "#76879D",
            "Unknown": "#AEB8C6",
        }
        rows = [
            {
                "label": label,
                "count": source[label],
                "color": colors.get(label, "#AEB8C6"),
                "missing": label == "Not Set",
            }
            for label in order
            if source.get(label)
        ]
        rows += [
            {"label": label, "count": count, "color": "#AEB8C6"}
            for label, count in source.items()
            if label not in order and count
        ]
        replace_table(
            "Multicore CPU Scaling",
            "distribution",
            {"total": multicore.total_devices, "rows": rows},
            "Multicore configuration coverage. "
            + " ".join(f"{r['label']}: {int(r['count']):,} devices." for r in rows),
        )
    fast = context.get("fast_hash_verify_summary")
    if fast:
        coverage = m.fast_hash_verify_coverage_rows(fast)
        colors = {
            "Enabled": "#0C7E88",
            "Not Set": "#AEB8C6",
            "Disabled": "#76879D",
            "Unknown": "#AEB8C6",
        }
        rows = [
            {
                "label": r[0],
                "count": _count(r[1]),
                "color": colors.get(r[0], "#AEB8C6"),
                "missing": r[0] == "Not Set",
            }
            for r in coverage
            if _count(r[1])
        ]
        replace_table(
            "FastHashVerify",
            "distribution",
            {"total": fast.total_devices, "rows": rows},
            "Devices by FastHashVerify configuration. Segment lengths represent device counts, not configured duty cycle.",
        )
        settings = [
            {
                "work": _count(r[0]),
                "sleep": _count(r[1]),
                "duty": r[2],
                "count": _count(r[3]),
            }
            for r in fast.settings_rows
            if _count(r[0]) + _count(r[1]) > 0
        ]
        label = "FastHashVerify settings"
        if settings:
            h = sections.get("FastHashVerify settings")
            if h is not None:
                h.style = document.styles["Heading 4"]
                replace_table(
                    label,
                    "duty",
                    {
                        "total": fast.total_devices,
                        "rows": settings,
                        "unset": sum(
                            _count(r[3])
                            for r in fast.settings_rows
                            if _count(r[0]) + _count(r[1]) == 0
                        ),
                    },
                    "Configured FastHashVerify work and sleep intervals. Bar segments represent time. The device count identifies Clients with these settings.",
                )

    udp = context.get("udp_summary")
    if udp:
        replace_table(
            "UDP Notification Coverage",
            "distribution",
            {
                "total": udp.total_devices,
                "rows": [
                    {
                        "label": "Receiving UDP pings",
                        "count": udp.receiving_count,
                        "color": "#187A43",
                    },
                    {
                        "label": "Not receiving UDP pings",
                        "count": udp.not_receiving_count,
                        "color": "#B45309",
                    },
                    {
                        "label": "Not reported / error",
                        "count": udp.unknown_count,
                        "color": "#AEB8C6",
                    },
                ],
            },
            "UDP notification statuses among records in the UDP capture. Relay rollups use each relay's reported-client population.",
        )
    polling = context.get("command_polling_summary")
    if polling and not render_details:
        from docx.table import Table

        anchor = heading("Command Polling")
        table = anchor._p.getnext()
        while table is not None and table.tag != qn("w:tbl"):
            table = table.getnext()
        if table is None:
            raise ValueError("Missing Command Polling data table")
        coverage = Table(table, document)
        for row in list(coverage.rows)[5:]:
            table.remove(row._tr)
        check_heading = document.add_heading("Reported Polling Checks", level=4)
        table.addnext(check_heading._p)
        note = document.add_paragraph(
            "These checks can overlap. Their counts should not be added."
        )
        check_heading._p.addnext(note._p)
        before = len(document.tables)
        m.build_word_table(
            document,
            ["Status", "Devices / Total", "% of Total"],
            m.command_polling_coverage_rows(polling)[4:],
        )
        note._p.addnext(document.tables[before]._tbl)
        for paragraph in list(document.paragraphs):
            if paragraph.text.startswith("The first four rows add up"):
                paragraph.text = paragraph.text.split(". ", 1)[0] + "."
    if polling and render_details:
        source = m.command_polling_coverage_rows(polling)
        rows = [
            {
                "label": r[0].replace("Command Polling ", ""),
                "count": _count(r[1]),
                "color": "#0C7E88" if i == 0 else "#AEB8C6",
                "missing": i == 2,
            }
            for i, r in enumerate(source[:4])
            if _count(r[1])
        ]
        checks = [{"label": r[0], "count": _count(r[1])} for r in source[4:]]
        replace_table(
            "Command Polling",
            "distribution",
            {"total": polling.total_devices, "rows": rows},
            "Devices by Command Polling configuration, including visible unset states.",
        )
        coverage_job = jobs[-1]
        check_heading = document.add_heading("Reported Polling Checks", level=4)
        sections["Reported Polling Checks"] = check_heading
        marker = OxmlElement("w:p")
        coverage_job[3].addnext(marker)
        coverage_job[3].addnext(check_heading._p)
        path = Path(output_path).with_suffix("") / "reported_polling_checks.png"
        jobs.append(
            (
                "clientdetail",
                {"kind": "checks", "total": polling.total_devices, "checks": checks},
                path,
                marker,
                "Three potentially overlapping polling checks. These check counts must not be added.",
            )
        )
        lead = next(
            (
                p
                for p in document.paragraphs
                if p.text.startswith("The first four rows add up")
            ),
            None,
        )
        if lead is not None:
            lead._p.getparent().remove(lead._p)

    if jobs:
        html_charts.render_charts([(kind, data, path) for kind, data, path, _, _ in jobs])
    for _, _, path, table, alt in jobs:
        shape = document.add_picture(str(path), width=Inches(7.5))
        set_picture_alt_text(shape, alt)
        paragraph = document.paragraphs[-1]
        paragraph.paragraph_format.space_after = Pt(8)
        table.addprevious(paragraph._p)
        table.getparent().remove(table)
    # Put the score explanation immediately after the main graphic.
    score = heading("How the Score Is Calculated")
    loop = (
        heading("Reading the Infographic")
        or heading("Automated Findings")
        or heading("Loop Health")
    )
    if score is not None and loop is not None:
        nodes = [score._p]
        node = score._p.getnext()
        while node is not None:
            pr = node.find(qn("w:pPr"))
            if (
                pr is not None
                and pr.find(qn("w:pStyle")) is not None
                and pr.find(qn("w:pStyle")).get(qn("w:val"), "").startswith("Heading")
            ):
                break
            if node.tag == qn("w:sectPr"):
                break
            nodes.append(node)
            node = node.getnext()
        # The short method note should not leave its last sentence at the top
        # of the next page, particularly when the standalone notice is present.
        paragraphs = [node for node in nodes if node.tag == qn("w:p")]
        for node in paragraphs[:-1]:
            Paragraph(node, document).paragraph_format.keep_with_next = True
        for node in nodes:
            loop._p.addprevious(node)
    cpu = heading("Client Settings")
    if cpu is not None:
        cpu.text = "CPU Settings"
        sections["CPU Settings"] = cpu
        stop = cpu._p.getnext()
        nodes = [cpu._p]
        while stop is not None and stop.tag != qn("w:sectPr"):
            nodes.append(stop)
            stop = stop.getnext()
        notification = heading("Notification and Polling")
        if notification is not None:
            for node in nodes:
                notification._p.addprevious(node)
    cpu = heading("CPU Settings")
    if cpu is not None:
        stop = heading("Notification and Polling")
        blocks = {}
        node = cpu._p.getnext()
        current = None
        while node is not None and (stop is None or node is not stop._p):
            label = next(
                (
                    name
                    for name in (
                        "CPU Idle Settings",
                        "Multicore CPU Scaling",
                        "FastHashVerify",
                    )
                    if heading(name) is not None and node is heading(name)._p
                ),
                None,
            )
            if label is not None:
                current = label
                blocks[current] = []
            if current is not None:
                blocks[current].append(node)
            node = node.getnext()
        anchor = stop._p if stop is not None else body[-1]
        for label in ("CPU Idle Settings", "Multicore CPU Scaling", "FastHashVerify"):
            for node in blocks.get(label, []):
                anchor.addprevious(node)
        idle_heading = heading("CPU Idle Settings")
        if idle_heading is not None:
            note = add_callout(
                document, "BigFix default: 10 ms work, 480 ms sleep (about 2%)."
            )
            before, after = note._tbl.getprevious(), note._tbl.getnext()
            anchor = heading("Multicore CPU Scaling")
            if anchor is not None:
                anchor._p.addprevious(before)
                anchor._p.addprevious(note._tbl)
                anchor._p.addprevious(after)
    udp_heading = heading("UDP Notification Coverage")
    if udp_heading is not None:
        note = add_callout(
            document,
            "UDP coverage uses the records in the UDP capture. Relay rollups use each relay's reported-client population. Devices without a relay can be included in the UDP capture.",
        )
        before, after = note._tbl.getprevious(), note._tbl.getnext()
        anchor = udp_heading._p.getnext()
        while (
            anchor is not None
            and not anchor.xpath(".//w:drawing")
            and anchor.tag != qn("w:tbl")
        ):
            anchor = anchor.getnext()
        if anchor is not None:
            anchor.addnext(after)
            anchor.addnext(note._tbl)
            anchor.addnext(before)
    # Callouts use the same treatment as the full-report template.
    source_notes = [
        p
        for p in document.paragraphs
        if p.text.startswith(
            (
                "The property totals and the Evaluation Frequency chart",
                "The content totals show the deployment",
                "The client loop results were collected separately",
            )
        )
    ]
    if source_notes:
        note = add_callout(document, "\n".join(p.text for p in source_notes))
        before = note._tbl.getprevious()
        after = note._tbl.getnext()
        source_notes[0]._p.addprevious(before)
        source_notes[0]._p.addprevious(note._tbl)
        source_notes[0]._p.addprevious(after)
        for paragraph in source_notes:
            paragraph._p.getparent().remove(paragraph._p)
    frequency_heading = heading("Evaluation Frequency")
    if frequency_heading is not None and render_details:
        frequency_heading.paragraph_format.page_break_before = True
    guidance = etree.parse(str(Path(__file__).with_name("client_guidance.xml")))
    loop = heading("Loop Health")
    if loop is not None:
        loop._p.addprevious(
            _guidance_block(guidance.getroot().find("why"), "ClientGuidanceWhy")
        )
    body.insert(
        len(body) - 1,
        _guidance_block(
            guidance.getroot().find("starting-points"), "ClientGuidanceStartingPoints"
        ),
    )
    for paragraph in document.paragraphs:
        if paragraph.style.name == "Heading 3":
            node = paragraph._p.getnext()
            if node is not None and node.tag == qn("w:p"):
                Paragraph(node, document).paragraph_format.keep_with_next = True
    for table in document.tables:
        if table.cell(0, 0).text in {"Metric", "Finding ID"}:
            for row in table.rows[:-1]:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.keep_with_next = True

    compact_table_header_style(document)
    normalize_heading_typography(document)
    normalize_section_spacing(document)
    from Lib.Design.report_layout import bind_report_bullets

    bind_report_bullets(document)


def _guidance_block(nodes, tag):
    """Mark mini guidance so the full injector can use its own template text."""
    block = OxmlElement("w:sdt")
    properties = OxmlElement("w:sdtPr")
    marker = OxmlElement("w:tag")
    marker.set(qn("w:val"), tag)
    properties.append(marker)
    block.append(properties)
    content = OxmlElement("w:sdtContent")
    for node in nodes:
        content.append(deepcopy(node))
    if tag == "ClientGuidanceStartingPoints":
        paragraph = next(n for n in content if n.tag == qn("w:p"))
        properties = paragraph.find(qn("w:pPr"))
        if properties is None:
            properties = OxmlElement("w:pPr")
            paragraph.insert(0, properties)
        page_break = properties.find(qn("w:pageBreakBefore"))
        if page_break is not None:
            properties.remove(page_break)
        else:
            page_break = OxmlElement("w:pageBreakBefore")
        preceding = {qn("w:" + name) for name in ("pStyle", "keepNext", "keepLines")}
        position = next(
            (i for i, child in enumerate(properties) if child.tag not in preceding),
            len(properties),
        )
        properties.insert(position, page_break)
    block.append(content)
    return block
