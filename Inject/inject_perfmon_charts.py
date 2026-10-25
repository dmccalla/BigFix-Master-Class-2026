#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
inject_perfmon_charts.py -- PerfMon Chart Injector

Python conversion of Inject-PerfmonCharts.ps1.

Purpose:
  Injects PerfMon PNG graphs produced by get_perfmon_charts.py into a Word
  document.

Behavior:
  - Scans the graph PNG folder for files.
  - Maps PNG names to PerfMon template sections.
  - Opens the Word template as a DOCX/Open XML package.
  - Discovers placeholder images in the PerfMon appendix at runtime.
  - Replaces placeholder image paragraphs when placeholders exist.
  - Inserts chart images after section headings when no placeholder exists.
  - Replaces each area's "Your observations go here" when
    perfmon_observations.json exists. The General Observations placeholder stays.
  - Adds a short PerfMon infrastructure summary when observations are available.
  - Writes a new output .docx.

This does not require Microsoft Word to be installed.

Expected graph folder:
  The folder created by get_perfmon_chart.py, usually:
      <output workbook stem>_Charts

Examples:
  python inject_perfmon_charts.py

  python inject_perfmon_charts.py ^
      --chart-folder "C:\\Temp\\perfmon_Charts" ^
      --template-path "C:\\Temp\\Style_Template.docx"

  python inject_perfmon_charts.py ^
      --chart-folder ".\\perfmon_Charts" ^
      --template-path ".\\Style_Template.docx" ^
      --output-path ".\\Perfmon_Mini_Report.docx"
"""

from __future__ import annotations

import argparse
import fnmatch
import html
import json
import re
import shutil
import sys
import zipfile
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from struct import unpack

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GET_DIR = PROJECT_ROOT / "Get"
for folder in (PROJECT_ROOT, GET_DIR):
    if folder.exists() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

from defusedxml import ElementTree as ET

import Lib.Core.report_log as log
from Lib.Core.input_utils import (
    clean_user_path as shared_clean_user_path,
)
from Lib.Core.input_utils import (
    resolve_existing_docx as shared_resolve_existing_docx,
)
from Lib.Core.input_utils import (
    resolve_existing_folder as shared_resolve_existing_folder,
)
from Lib.Core.input_utils import (
    resolve_output_docx as shared_resolve_output_docx,
)
from Lib.Core.ooxml import splice_preserving_bookmarks
from Lib.Design import report_tables
from Lib.Themes.chart_theme import THEME

IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)
EMU_PER_INCH = 914400
DXA_PER_INCH = 1440
PNG_DPI = 200

# PerfMon scorecard styling mirrors the BigFix Platform health scorecard and
# dashboard palette. These foreground colors meet WCAG AA contrast on white.
PERFMON_SCORECARD_TITLE = "PerfMon Counters Analysis Scorecard"
PERFMON_SCORECARD_FIGSIZE = (15.08, 9.08)
PERFMON_SCORE_WEIGHTS = {
    "PASS": 1.0,  # nosec B105: a status label, not a credential
    "ADVISORY": 0.55,
    "FAIL": 0.0,
    "CANNOT VERIFY": 0.25,
}
CHART_BG_PAGE = THEME.bg_page
CHART_BG_CARD = THEME.bg_card
CHART_TITLE = THEME.title
CHART_TEXT = THEME.text
CHART_MUTED = THEME.muted
CHART_BORDER = THEME.border
CHART_TRACK = THEME.track
CHART_BLUE = THEME.blue
CHART_PURPLE = THEME.purple
CHART_PASS = THEME.pass_color
CHART_ADVISORY = THEME.warning_color
CHART_FAIL = THEME.fail_color
CHART_CANNOT = THEME.cannot_verify_color


def xml_attr_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def xml_text_escape(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text_paragraph_xml(text: str, bold_prefix: str = "") -> str:
    if bold_prefix and text.startswith(bold_prefix):
        rest = text[len(bold_prefix) :].lstrip()
        return (
            "<w:p>"
            "<w:r><w:rPr><w:b/></w:rPr>"
            f"<w:t>{xml_text_escape(bold_prefix)}</w:t></w:r>"
            f'<w:r><w:t xml:space="preserve"> {xml_text_escape(rest)}</w:t></w:r>'
            "</w:p>"
        )
    return f"<w:p><w:r><w:t>{xml_text_escape(text)}</w:t></w:r></w:p>"


def bullet_paragraph_xml(text: str) -> str:
    """Build a simple Word-compatible bullet paragraph."""
    return (
        "<w:p>"
        '<w:pPr><w:ind w:left="360" w:hanging="180"/></w:pPr>'
        '<w:r><w:t xml:space="preserve">• </w:t></w:r>'
        f"<w:r><w:t>{xml_text_escape(text)}</w:t></w:r>"
        "</w:p>"
    )


def heading_paragraph_xml(text: str, level: int = 3) -> str:
    level = min(max(int(level), 1), 9)
    return (
        "<w:p>"
        f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
        "<w:r><w:rPr><w:b/></w:rPr>"
        f"<w:t>{xml_text_escape(text)}</w:t></w:r>"
        "</w:p>"
    )


def score_note_heading_xml(text: str) -> str:
    return (
        "<w:p>"
        '<w:pPr><w:pStyle w:val="Heading3"/>'
        '<w:spacing w:before="80" w:after="40"/></w:pPr>'
        '<w:r><w:rPr><w:b/><w:color w:val="0B1640"/></w:rPr>'
        f"<w:t>{xml_text_escape(text)}</w:t></w:r>"
        "</w:p>"
    )


def perfmon_score_method_note_xml() -> str:
    xml = "\n".join(
        [
            score_note_heading_xml("How This Score Is Calculated"),
            text_paragraph_xml(
                "The PerfMon Infrastructure Score is based on how each monitored "
                "counter area compares to its applicable threshold during the "
                "capture window:"
            ),
            text_paragraph_xml("Pass: 100 points | Advisory: 55 points | Cannot Verify: 25 points | Fail: 0 points"),
            text_paragraph_xml(
                "Formula: Pass% x 100 + Advisory% x 55 + Cannot Verify% x 25 + Fail% x 0",
                bold_prefix="Formula:",
            ),
            text_paragraph_xml(
                "Each area takes the status of its worst counter, judged on that "
                "counter's average. A few high readings can raise an average over "
                "the limit. Each area section gives the peak and the number of "
                "readings over the limit."
            ),
            text_paragraph_xml(
                "Score ranges: 90 to 100 is Healthy, 70 to 89 is Needs Attention and "
                "0 to 69 is Critical.",
                bold_prefix="Score ranges:",
            ),
        ]
    )

    paragraphs = re.findall(r'<w:p>.*?</w:p>', xml, re.DOTALL)
    for index, paragraph in enumerate(paragraphs):
        if '<w:pPr>' not in paragraph:
            keep = '<w:keepNext/>' if index < len(paragraphs)-1 else ''
            revised = paragraph.replace('<w:p>', '<w:p><w:pPr>'+keep+'<w:spacing w:before="0" w:after="60"/></w:pPr>', 1)
            xml = xml.replace(paragraph,revised,1)
    return xml


def status_icon(status: str) -> str:
    """Return the compact visual marker shown beside each PerfMon result."""
    return {
        "OK": "✓",
        "Warning": "!",
        "Critical": "✗",
        "Not Available": "?",
    }.get(status, "?")


def status_color(status: str) -> str:
    """Return WCAG AA compliant text colors for status labels on white."""
    return {
        "OK": "187A43",
        "Warning": "B45309",
        "Critical": "C2410C",
        "Not Available": "595959",
    }.get(status, "595959")


def status_label(status: str) -> str:
    """Translate internal status names into report-friendly labels."""
    return {
        "OK": "Pass",
        "Warning": "Advisory",
        "Critical": "Fail",
        "Not Available": "Cannot Verify",
    }.get(status, status or "Unknown")


def status_paragraph_xml(status: str, label: str, text: str) -> str:
    """Build a single Word paragraph with a colored status marker and label."""
    color = status_color(status)
    icon = status_icon(status)
    properties = (
        '<w:pPr><w:pStyle w:val="PerfMonEvidence"/></w:pPr>'
        if label in {"Observation", "Counter"} else ""
    )
    return (
        "<w:p>"
        f"{properties}"
        f'<w:r><w:rPr><w:b/><w:color w:val="{color}"/></w:rPr>'
        f"<w:t>{xml_text_escape(icon)}</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        "<w:r><w:rPr><w:b/></w:rPr>"
        f"<w:t>{xml_text_escape(label)}:</w:t></w:r>"
        '<w:r><w:t xml:space="preserve"> </w:t></w:r>'
        f"<w:r><w:t>{xml_text_escape(text)}</w:t></w:r>"
        "</w:p>"
    )


def observation_paragraph_xml(section: dict, review_level: int = 4) -> str:
    """Render an observation paragraph from one section of perfmon_observations.json.

    ``review_level`` is the heading level for Affected Counters Requiring Review,
    one below the area heading it belongs to.
    """
    status = section.get("status", "Not Available")
    observation = section.get("observation", "").strip()
    xml = status_paragraph_xml(status, "Observation", observation)
    review_items = [
        item
        for item in section.get("counters_detail", [])
        if item.get("status", "Not Available") not in {"OK", ""}
    ]
    if review_items:
        xml += heading_paragraph_xml(
            "Affected Counters Requiring Review", level=review_level
        )
        for item in review_items:
            item_status = item.get("status", "Not Available")
            details = []
            if item.get("average") is not None:
                details.append(f"average {format_report_number(item['average'])}")
            if item.get("maximum") is not None:
                details.append(f"peak {format_report_number(item['maximum'])}")
            if item.get("violations"):
                violation_percent = item.get("violation_percent")
                violation_text = f"{item['violations']} readings"
                if violation_percent is not None:
                    violation_text += f" ({format_report_number(violation_percent)}%)"
                details.append(f"{violation_text} over the limit")
            name = item.get("counter", "Unnamed counter")
            if details:
                line = f"{name}: {', '.join(details)}."
            elif item.get("not_scored_reason"):
                line = (
                    f"{name}. It was not compared with the limit because "
                    f"{item['not_scored_reason']}."
                )
            else:
                line = f"{name}: no samples were available for verification."
            xml += status_paragraph_xml(item_status, "Counter", line)
    return xml


def table_cell_xml(
    text: str, width: int, bold: bool = False, color: str | None = None
) -> str:
    """One cell of the PerfMon summary table. Borders, header navy fill and row
    banding all come from the shared BigFixContent table style, so this cell
    carries no inline shading/borders of its own -- pass ``color`` only for
    semantic status text. Keeps every report table sourced from the one style."""
    bold_xml = "<w:b/>" if bold else ""
    color_xml = f'<w:color w:val="{color}"/>' if color else ""
    return (
        "<w:tc>"
        f'<w:tcPr><w:tcW w:w="{width}" w:type="dxa"/></w:tcPr>'
        "<w:p><w:r>"
        f"<w:rPr>{bold_xml}{color_xml}</w:rPr>"
        f"<w:t>{xml_text_escape(text)}</w:t>"
        "</w:r></w:p>"
        "</w:tc>"
    )


def format_report_number(value) -> str:
    number = float(value)
    if number == 0:
        return "0"
    if abs(number) >= 100:
        return f"{number:,.0f}"
    if abs(number) >= 10:
        return f"{number:.1f}"
    return f"{number:.2f}"


def report_standard(text: str) -> str:
    text = text.replace("<= 1ms", "1 ms or less").replace("<= 1 ms", "1 ms or less")
    text = text.replace("<= 1 per disk x 1 disks = <= 1", "1 per disk \u00d7 1 disk = 1")
    return text


def build_perfmon_summary_table_xml(observations: dict) -> str:
    """Build the compact General Observations table from PerfMon section results."""
    sections = observations.get("sections", {})
    if not sections:
        return ""

    widths = [2200, 1550, 3150, 2900, 1000]
    # Use the project's custom named table style defined in the report
    # template's styles.xml. Same style every other injector adopts so
    # all tables look consistent without per-cell shading overrides.
    xml = (
        "<w:tbl><w:tblPr>"
        '<w:tblStyle w:val="BigFixContent"/>'
        '<w:tblW w:w="5000" w:type="pct"/>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
        + "</w:tblGrid>"
    )
    headers = ["Area", "Status", "Standard / Basis", "Observed", "Points"]
    xml += (
        "<w:tr>"
        + "".join(
            table_cell_xml(header, widths[idx], bold=True)
            for idx, header in enumerate(headers)
        )
        + "</w:tr>"
    )

    for section in SECTION_COUNTER_MAP.keys():
        item = sections.get(section)
        if not item:
            continue
        status = item.get("status", "Unknown")
        observed_parts = []
        if item.get("average") is not None:
            observed_parts.append(f"avg {format_report_number(item['average'])}")
        if item.get("maximum") is not None:
            observed_parts.append(f"peak {format_report_number(item['maximum'])}")
        if item.get("violations"):
            observed_parts.append(f"{item['violations']} readings over")
        if item.get("warnings") and item.get("range_floor"):
            observed_parts.append(
                f"{item['warnings']} readings under {item['range_floor']}%"
            )
        if item.get("samples"):
            observed_parts.append(f"{item['samples']} readings")
        observed = ", ".join(observed_parts) or ("Not evaluated" if status == "Not Available" else "Reviewed")
        points = perfmon_section_score(aggregate_perfmon_scorecard(observations).get(section, {}))
        xml += (
            "<w:tr>"
            + table_cell_xml(section, widths[0])
            + table_cell_xml(
                f"{status_icon(status)} {status_label(status)}",
                widths[1],
                color=status_color(status),
                bold=True,
            )
            + table_cell_xml(report_standard(str(item.get("threshold", "See NFR standard"))), widths[2])
            + table_cell_xml(observed, widths[3])
            + table_cell_xml(str(points) if points is not None else "Not assessed", widths[4])
            + "</w:tr>"
        )

    return xml + "</w:tbl><w:p/>"


def build_perfmon_hardware_context_xml(observations: dict) -> str:
    """Build the Hardware / Context table that closes the Capture Summary."""
    environment = observations.get("environment", {})
    if not environment:
        return ""

    def value_with_source(value_key: str, source_key: str, suffix: str = "") -> str:
        value = environment.get(value_key)
        if value_key == "Virtual Machine" and value in (False, "False", "No") and environment.get(source_key) in (None, "", "Not detected", "Not supplied"):
            return "Not supplied"
        if value is None or value == "":
            return ""
        value_text = str(value)
        if isinstance(value, bool):
            value_text = "Yes" if value else "No"
        if value_text == "Not supplied":
            return value_text
        if suffix:
            value_text += suffix
        source = environment.get(source_key)
        if source == "Parameter Supplied":
            source = "User supplied"
        if source:
            value_text += f" ({source})"
        return value_text

    rows = [
        (
            "Logical Processors",
            value_with_source("Logical Processor Count", "Logical Processor Source"),
        ),
        (
            "Physical Memory",
            value_with_source(
                "Analyzed System Physical Memory (GB)",
                "Physical Memory Source",
                " GB",
            ),
        ),
        (
            "Physical Disks",
            value_with_source("Physical Disk Count", "Physical Disk Source"),
        ),
        (
            "Virtual Machine",
            value_with_source("Virtual Machine", "Virtual Machine Source"),
        ),
    ]
    rows = [(label, str(value)) for label, value in rows if value not in (None, "")]
    if not rows:
        return ""

    widths = [3000, 6800]
    xml = (
        "<w:tbl><w:tblPr>"
        '<w:tblStyle w:val="BigFixContent"/>'
        '<w:tblW w:w="5000" w:type="pct"/>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
        + "</w:tblGrid>"
    )
    xml += (
        "<w:tr>"
        + table_cell_xml("Hardware / Context", widths[0], bold=True)
        + table_cell_xml("Value / Source", widths[1], bold=True)
        + "</w:tr>"
    )
    for label, value in rows:
        xml += (
            "<w:tr>"
            + table_cell_xml(label, widths[0])
            + table_cell_xml(value, widths[1])
            + "</w:tr>"
        )
    return xml + "</w:tbl><w:p/>"


# Maps each SECTION_COUNTER_MAP key to a single keyword that must appear in
# the template section heading for that section.  Multiple keys can share a
# keyword (e.g. all three storage keys map to "Storage") so that charts for
# grouped metrics land under the same template heading.
_SECTION_HEADING_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Storage Queue Depth": (
        "Storage Queue Depth",
        "Current Disk Queue Length",
    ),
    "Storage Latency": (
        "Storage Latency",
        "Avg Disk ms/Transfer",
        "Average Disk ms/Transfer",
        "Avg. Disk sec/Transfer",
        "Average Disk sec/Transfer",
    ),
    "Storage Operations": (
        "Storage Operations",
        "Disk Transfers/sec",
        "Disk Transfers",
    ),
    "CPU Privileged Time": ("CPU Privileged Time", "Privileged Time"),
    "CPU Utilization": ("CPU Utilization", "Processor Time"),
    "CPU Latency": ("CPU Latency", "Processor Queue Length"),
    "Network Health": ("Network Health", "Packets Outbound", "Packets Received"),
    "Memory Health": ("Memory Health", "Paging File", "Usage Peak"),
}

# Section keyword -> chart filename pattern mapping.
# Keywords are matched against heading text, case-insensitive.
# Multiple chart patterns can map to one section and are injected in order.
SECTION_COUNTER_MAP: OrderedDict[str, list[str]] = OrderedDict(
    [
        # PRF-INF-01: Storage Queue Depth.
        (
            "Storage Queue Depth",
            ["*PhysicalDisk_*_Current_Disk_Queue*"],
        ),
        # PRF-INF-02: Storage Latency
        (
            "Storage Latency",
            ["*PhysicalDisk_*_Avg_Disk_ms_Transfer*"],
        ),
        # PRF-INF-03: Storage Operations/Second
        (
            "Storage Operations",
            ["*PhysicalDisk_*_Disk_Transfers_sec*"],
        ),
        # PRF-INF-06: CPU Privileged Time
        ("CPU Privileged Time", ["*Privileged_Time*"]),
        # PRF-INF-04: CPU Utilization
        ("CPU Utilization", ["*Processor_Time*"]),
        # PRF-INF-05: CPU Latency
        ("CPU Latency", ["*Processor_Queue_Length*"]),
        # PRF-INF-07: Network Health
        (
            "Network Health",
            [
                "*Packets_Outbound_Discarded*",
                "*Packets_Outbound_Errors*",
                "*Packets_Received_Discarded*",
                "*Packets_Received_Errors*",
            ],
        ),
        # PRF-INF-09: Memory Health
        ("Memory Health", ["*Usage_Peak*"]),
    ]
)

PERFMON_SECTION_SOURCE_IDS = {
    "Storage Queue Depth": "PRF-INF-01",
    "Storage Latency": "PRF-INF-02",
    "Disk Latency": "PRF-INF-02",
    "Storage Operations": "PRF-INF-03",
    "CPU Utilization": "PRF-INF-04",
    "CPU Latency": "PRF-INF-05",
    "CPU Privileged Time": "PRF-INF-06",
    "Network Health": "PRF-INF-07",
    "Memory Health": "PRF-INF-09",
}


def clean_user_path(value) -> str:
    """Strip whitespace and surrounding quotes from a user-entered path."""
    return shared_clean_user_path(value)


def resolve_existing_folder(candidate_text: str, label: str) -> Path:
    """
    Resolve an input folder from a full path, relative path, or bare folder
    name in the current working folder.
    """
    return shared_resolve_existing_folder(candidate_text, label, "*.png")


def resolve_existing_docx(candidate_text: str, label: str) -> Path:
    """
    Resolve an input .docx file from a full path, relative path, or bare
    filename in the current working folder.
    """
    return shared_resolve_existing_docx(candidate_text, label)


def resolve_output_docx(candidate_text: str, default_path: Path) -> Path:
    """
    Resolve the output .docx path.

    Blank input uses default_path. A filename-only value saves in the current
    folder. A missing or different extension is changed to .docx.
    """
    return shared_resolve_output_docx(candidate_text, default_path)


def read_zip_text(zip_path: Path, member_name: str) -> str:
    with zipfile.ZipFile(zip_path, "r") as zf:
        try:
            data = zf.read(member_name)
        except KeyError as exc:
            raise ValueError(f"Missing required DOCX part: {member_name}") from exc
    return data.decode("utf-8")


def delete_zip_member(zip_path: Path, member_name: str) -> None:
    """
    zipfile cannot delete in place, so rebuild the archive without the member.
    """
    temp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")

    with (
        zipfile.ZipFile(zip_path, "r") as src,
        zipfile.ZipFile(temp_path, "w", zipfile.ZIP_DEFLATED) as dst,
    ):
        for item in src.infolist():
            if item.filename == member_name:
                continue
            dst.writestr(item, src.read(item.filename))

    temp_path.replace(zip_path)


def write_or_replace_zip_member(zip_path: Path, member_name: str, data: bytes) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        exists = member_name in zf.namelist()

    if exists:
        delete_zip_member(zip_path, member_name)

    with zipfile.ZipFile(zip_path, "a", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(member_name, data)


def validate_docx_package(docx_path: Path) -> None:
    with zipfile.ZipFile(docx_path, "r") as zf:
        bad_member = zf.testzip()
        if bad_member:
            raise ValueError(f"DOCX zip validation failed at member: {bad_member}")

        names = zf.namelist()
        duplicate_members = sorted({name for name in names if names.count(name) > 1})
        if duplicate_members:
            raise ValueError(
                f"DOCX contains duplicate zip members: {', '.join(duplicate_members[:5])}"
            )

        for member_name in (
            "[Content_Types].xml",
            "word/document.xml",
            "word/_rels/document.xml.rels",
        ):
            ET.fromstring(zf.read(member_name))

        doc_xml = zf.read("word/document.xml").decode("utf-8")
        docpr_ids = re.findall(r'<wp:docPr\b[^>]*\bid="(\d+)"', doc_xml)
        duplicate_docpr_ids = sorted(
            {doc_id for doc_id in docpr_ids if docpr_ids.count(doc_id) > 1}, key=int
        )
        if duplicate_docpr_ids:
            raise ValueError(
                f"DOCX contains duplicate drawing IDs: {', '.join(duplicate_docpr_ids[:10])}"
            )

        rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8")
        package_names = set(names)
        missing_targets: list[str] = []
        for rel in re.findall(r"<Relationship\b[^>]*/?>", rels_xml, flags=re.IGNORECASE):
            if IMAGE_REL_TYPE not in rel and "image" not in rel.lower():
                continue
            target_match = re.search(r'\bTarget="([^"]+)"', rel)
            if not target_match:
                continue
            target = target_match.group(1).replace("\\", "/")
            target = target.removeprefix("../")
            if not target.startswith("word/"):
                target = f"word/{target}"
            if target not in package_names:
                missing_targets.append(target)
        if missing_targets:
            raise ValueError(
                "DOCX contains image relationships pointing to missing media: "
                + ", ".join(sorted(set(missing_targets))[:10])
            )


def copy_docx_to_output(template_path: Path, output_path: Path) -> None:
    if template_path.resolve() == output_path.resolve():
        raise ValueError("OutputPath cannot be the same file as TemplatePath.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, output_path)


def scan_chart_folder(chart_folder: Path) -> list[Path]:
    png_files = sorted(chart_folder.glob("*.png"), key=chart_sort_key)

    if not png_files:
        raise ValueError(f"No PNG files found in: {chart_folder}")

    return png_files


def chart_sort_key(path: Path) -> tuple[str, int, str]:
    """
    Keep summary charts before instance charts within the same metric.

    Example:
      PhysicalDisk_Total_Avg_Disk_ms_Transfer.png
      PhysicalDisk_0_C_Avg_Disk_ms_Transfer.png
      PhysicalDisk_1_D_Avg_Disk_ms_Transfer.png
    """
    name = path.stem.lower()
    metric = name
    for suffix in (
        "avg_disk_ms_transfer",
        "avg_disk_queue_length",
        "current_disk_queue_length",
        "packets_received_errors",
        "disk_transfers_sec",
        "privileged_time",
        "processor_time",
        "processor_queue_length",
        "usage_peak",
    ):
        if name.endswith(suffix):
            prefix = name[: -len(suffix)].rstrip("_")
            object_name = prefix.split("_", 1)[0]
            metric = f"{object_name}_{suffix}"
            break
    total_rank = 0 if "_total_" in name else 1
    return metric, total_rank, name


def map_patterns_to_pngs(png_files: list[Path]) -> OrderedDict[str, list[Path]]:
    """
    Map each pattern in SECTION_COUNTER_MAP to ALL PNG files that match it.

    Returns OrderedDict[pattern, list[Path]], a list because a server with
    multiple physical disks produces one PNG per disk instance, and all of them
    should be injected under the corresponding section.

    For sections that use replace mode (template has placeholder images), the
    first PNG in the list replaces the first placeholder, the second replaces
    the second, and so on.  Any extras beyond the placeholder count are
    appended after the last placeholder.

    For sections that use insert mode (no placeholders), all matched PNGs are
    inserted in sorted order after the section heading.
    """
    pattern_to_pngs: OrderedDict[str, list[Path]] = OrderedDict()

    for section, patterns in SECTION_COUNTER_MAP.items():
        for pattern in patterns:
            matches = sorted(
                [png for png in png_files if fnmatch.fnmatchcase(png.stem, pattern)],
                key=chart_sort_key,
            )
            if matches:
                pattern_to_pngs[pattern] = matches
                for png in matches:
                    log.detail("Mapped", f"{png.name} -> {section} ({pattern})")
            else:
                pattern_to_pngs[pattern] = []

    return pattern_to_pngs


def get_document_paragraphs(doc_xml: str) -> list[re.Match[str]]:
    para_pattern = re.compile(
        r"<w:p\b[^>]*>(?:(?!<w:p\b).)*?</w:p>",
        flags=re.DOTALL,
    )
    return list(para_pattern.finditer(doc_xml))


def paragraph_plain_text(paragraph_xml: str) -> str:
    text_nodes = re.findall(
        r"<w:(?:t|instrText)\b[^>]*>(.*?)</w:(?:t|instrText)>",
        paragraph_xml,
        flags=re.DOTALL,
    )
    if text_nodes:
        text = "".join(html.unescape(node) for node in text_nodes)
        text = re.sub(r"\s+", " ", text).strip()
        return text
    text = re.sub(r"<[^>]+>", " ", paragraph_xml)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def is_toc_or_field_paragraph(paragraph_xml: str, text: str = "") -> bool:
    haystack = f"{paragraph_xml} {text}"
    return bool(
        re.search(
            r"PAGEREF|TOC\\|HYPERLINK\s+\\l|w:fldChar|w:instrText",
            haystack,
            flags=re.IGNORECASE,
        )
    )


def is_heading_paragraph(paragraph_xml: str) -> bool:
    if paragraph_heading_level(paragraph_xml):
        return True
    return bool(
        re.search(
            r"w:pStyle\b[^>]*w:val=\"[^\"]*Heading|<w:outlineLvl\b",
            paragraph_xml,
            flags=re.IGNORECASE,
        )
    )


def paragraph_heading_level(paragraph_xml: str) -> int:
    """Return the Word heading level for a paragraph, or 0 for body text."""
    style_match = re.search(
        r"w:pStyle\b[^>]*w:val=\"[^\"]*Heading(\d+)\"",
        paragraph_xml,
        flags=re.IGNORECASE,
    )
    if style_match:
        return int(style_match.group(1))
    outline_match = re.search(
        r"<w:outlineLvl\b[^>]*w:val=\"(\d+)\"",
        paragraph_xml,
        flags=re.IGNORECASE,
    )
    if outline_match:
        return int(outline_match.group(1)) + 1
    return 0


def is_perfmon_counters_heading(paragraph_xml: str, text: str) -> bool:
    """Return True for the actual PerfMon analysis section heading."""
    if not text or not is_heading_paragraph(paragraph_xml):
        return False
    return bool(
        re.search(
            r"(Appendix\b.*)?PerfMon\s+Counters\s+(Data|Analysis)",
            text,
            flags=re.IGNORECASE,
        )
        or re.search(r"^PART\s+1\b.*\bInfrastructure\b", text, flags=re.IGNORECASE)
    )


def perfmon_section_key_for_text(text: str) -> str | None:
    """Map a template heading/caption to a PerfMon counter section key."""
    normalized_text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalized_text:
        return None
    for section_key, aliases in _SECTION_HEADING_KEYWORDS.items():
        for alias in aliases:
            words = re.split(r"\s+", alias.strip())
            if all(
                re.search(re.escape(word), normalized_text, flags=re.IGNORECASE)
                for word in words
            ):
                return section_key
    return None


def is_perfmon_section_heading_candidate(paragraph_xml: str, text: str) -> bool:
    """Return True when text is likely a counter subsection heading/caption."""
    if is_heading_paragraph(paragraph_xml):
        return True
    normalized = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(normalized) > 80:
        return False
    return not re.match(
        r"^(Detail|Note|Standard|Value\(s\)|Observation)\b",
        normalized,
        flags=re.IGNORECASE,
    )


def find_perfmon_summary_insert_point(doc_xml: str) -> int | None:
    """
    Locate the real PerfMon appendix General Observations area.

    The report also mentions PerfMon in Root Server checklist rows and the ToC.
    Anchoring to Appendix D + General Observations prevents the generated
    infrastructure summary from landing in those earlier references.
    """
    paragraphs = get_document_paragraphs(doc_xml)
    appendix_index: int | None = None

    for idx, pm in enumerate(paragraphs):
        para = pm.group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        if not is_heading_paragraph(para):
            continue
        if re.search(
            r"(Appendix\b.*)?PerfMon\s+Counters\s+(Data|Analysis)",
            text,
            flags=re.IGNORECASE,
        ):
            appendix_index = idx
            break

    if appendix_index is None:
        return None

    for idx in range(appendix_index + 1, len(paragraphs)):
        para = paragraphs[idx].group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        if re.fullmatch(r"General\s+Observations", text, flags=re.IGNORECASE):
            insert_at = paragraphs[idx].start() + len(para)
            for following in paragraphs[idx + 1 :]:
                following_para = following.group(0)
                following_text = paragraph_plain_text(following_para)
                if following_text and is_heading_paragraph(following_para):
                    break
                insert_at = following.start() + len(following_para)
            return insert_at
        if (
            idx > appendix_index
            and text.startswith("Appendix")
            and is_heading_paragraph(para)
        ):
            break

    return None


def insert_after_general_observations_placeholder(
    doc_xml: str, summary_xml: str
) -> tuple[str, bool]:
    """Insert summary XML after the General Observations placeholder.

    The placeholder is the consultant's space, so it stays in the report.
    """
    paragraphs = get_document_paragraphs(doc_xml)
    appendix_index: int | None = None

    for idx, pm in enumerate(paragraphs):
        para = pm.group(0)
        text = paragraph_plain_text(para)
        if (
            text
            and not is_toc_or_field_paragraph(para, text)
            and is_perfmon_counters_heading(para, text)
        ):
            appendix_index = idx
            break

    if appendix_index is None:
        return doc_xml, False

    general_index: int | None = None
    for idx in range(appendix_index + 1, len(paragraphs)):
        para = paragraphs[idx].group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        if re.fullmatch(r"General\s+Observations", text, flags=re.IGNORECASE):
            general_index = idx
            break
        if is_heading_paragraph(para) and re.search(
            r"Storage|CPU|Network|Memory", text, flags=re.IGNORECASE
        ):
            break

    if general_index is None:
        return doc_xml, False

    placeholder_end: int | None = None

    for following in paragraphs[general_index + 1 :]:
        para = following.group(0)
        text = paragraph_plain_text(para)
        if text and is_heading_paragraph(para):
            break
        if re.search(r"Your\s+observations\s+go\s+here", text, flags=re.IGNORECASE):
            placeholder_end = following.end()
            break

    if placeholder_end is None:
        return doc_xml, False

    return doc_xml[:placeholder_end] + summary_xml + doc_xml[placeholder_end:], True


def load_perfmon_observations(chart_folder: Path) -> dict:
    candidates = [
        chart_folder / "perfmon_observations.json",
        *sorted(chart_folder.glob("*observations*.json")),
        *sorted(chart_folder.glob("*Observations*.json")),
    ]
    for candidate in candidates:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                log.detail("Loaded observations", candidate.name)
                return data
            except (OSError, json.JSONDecodeError) as exc:
                log.warn(f"Could not read observations file {candidate.name}: {exc}")
                return {}
    log.detail(
        "No perfmon_observations.json found; observation text will not be updated."
    )
    return {}


def perfmon_status_bucket(status: str) -> str:
    """Translate generated PerfMon statuses into report scorecard buckets."""
    return {
        "OK": "PASS",
        "Warning": "ADVISORY",
        "Critical": "FAIL",
        "Not Available": "CANNOT VERIFY",
    }.get(str(status or "").strip(), "CANNOT VERIFY")


def aggregate_perfmon_scorecard(
    observations: dict,
) -> OrderedDict[str, dict[str, int]]:
    """Aggregate perfmon_observations.json into the report's PerfMon subsections."""
    rows: OrderedDict[str, dict[str, int]] = OrderedDict(
        (section, {status: 0 for status in PERFMON_SCORE_WEIGHTS})
        for section in SECTION_COUNTER_MAP.keys()
    )
    sections = observations.get("sections", {}) if observations else {}
    for section_name, section_data in sections.items():
        normalized_name = re.sub(r"\s+", " ", str(section_name or "")).strip()
        if normalized_name not in rows:
            continue
        status = perfmon_status_bucket(section_data.get("status", "Not Available"))
        rows[normalized_name][status] += 1
    return rows


def perfmon_section_score(counts: dict[str, int]) -> int | None:
    """Return a 0-100 score for one PerfMon subsection, or None when unscored."""
    total = sum(counts.get(status, 0) for status in PERFMON_SCORE_WEIGHTS)
    if total <= 0:
        return None
    weighted = sum(
        counts.get(status, 0) * weight for status, weight in PERFMON_SCORE_WEIGHTS.items()
    )
    return round(weighted / total * 100)


def perfmon_rating(score: int | None) -> tuple[str, str]:
    """Return the display rating and color for a PerfMon score."""
    if score is None:
        return "Not Scored", CHART_CANNOT
    if score >= 90:
        return "Healthy", CHART_PASS
    if score >= 75:
        return "Stable", CHART_PASS
    if score >= 60:
        return "Needs Attention", CHART_ADVISORY
    if score >= 40:
        return "At Risk", CHART_FAIL
    return "Critical", CHART_FAIL


def perfmon_overall_score(perfmon_counts: dict[str, dict[str, int]]) -> int | None:
    """Return the score across all automated PerfMon counter areas."""
    totals = {status: 0 for status in PERFMON_SCORE_WEIGHTS}
    for counts in perfmon_counts.values():
        for status in totals:
            totals[status] += counts.get(status, 0)
    return perfmon_section_score(totals)


def perfmon_section_source_id(section_name: object) -> str:
    """Return the NFR control ID for a PerfMon scorecard section."""
    normalized = re.sub(r"\s+", " ", str(section_name or "")).strip()
    if normalized in PERFMON_SECTION_SOURCE_IDS:
        return PERFMON_SECTION_SOURCE_IDS[normalized]
    folded = normalized.casefold()
    for section, source_id in PERFMON_SECTION_SOURCE_IDS.items():
        if section.casefold() == folded:
            return source_id
    return ""


def _perfmon_finding_number(value: object) -> str:
    """Format a captured counter value for the report display."""
    if value is None or str(value).strip() == "":
        return ""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    return format_report_number(numeric)


def perfmon_finding_context(section_data: dict) -> str:
    """Return the compact observed evidence behind one automated finding."""
    status = str(section_data.get("status", "")).strip()
    label = status_label(status)
    section = re.sub(r"\s+", " ", str(section_data.get("section", ""))).strip()
    unit = str(section_data.get("unit", ""))
    limit = str(section_data.get("limit_text", "")).strip()
    threshold = str(section_data.get("threshold", "")).strip()
    average = _perfmon_finding_number(section_data.get("average"))
    maximum = _perfmon_finding_number(section_data.get("maximum"))
    violations = int(section_data.get("violations", 0) or 0)
    warnings = int(section_data.get("warnings", 0) or 0)
    samples = int(section_data.get("samples", 0) or 0)
    see = f" See {section}." if section else ""

    if status == "Not Available":
        note = re.sub(r"should be <= ([^.]+)\.", r"should be \1 or less.", threshold)
        if note and "Cannot Verify" in note:
            return f"{label}. {note}{see}"
        return (
            f"{label}. No readings were recorded, so this area could not be checked "
            f"against {limit or threshold}.{see}"
        )

    if section_data.get("per_sample"):
        sentences = []
        if average:
            sentences.append(f"Average {average} added per sample.")
        if maximum:
            sentences.append(f"Peak {maximum}.")
        if violations and samples:
            sentences.append(
                f"{violations:,} of {samples:,} readings showed an increase."
            )
        return f"{label}. {' '.join(sentences)}{see}"

    sentences = []
    if average:
        sentences.append(
            f"Average {average}{unit}" + (f" against {limit}" if limit else "") + "."
        )
    if maximum:
        sentences.append(f"Peak {maximum}{unit}.")
    if status == "Critical" and violations:
        if samples:
            sentences.append(
                f"{violations:,} of {samples:,} readings were over the limit."
            )
        else:
            sentences.append(f"{violations:,} readings were over the limit.")
    floor = str(section_data.get("range_floor", "")).strip()
    if status == "Warning" and warnings and floor:
        if samples:
            sentences.append(f"{warnings:,} of {samples:,} readings were under {floor}%.")
        else:
            sentences.append(f"{warnings:,} readings were under {floor}%.")
    if sentences:
        return f"{label}. {' '.join(sentences)}{see}"

    observation = str(section_data.get("observation", "")).strip()
    if observation:
        return f"{label}. {observation}{see}"
    return f"{label}. No observed values were available for this assessment.{see}"


def perfmon_automated_finding_rows(observations: dict) -> list[tuple[str, str, str]]:
    """Return the non-OK NFR findings and their captured evidence."""
    findings: dict[str, tuple[str, str]] = {}
    for section_data in observations.get("sections", {}).values():
        section_name = re.sub(r"\s+", " ", str(section_data.get("section", ""))).strip()
        status = str(section_data.get("status", "")).strip()
        if not section_name or status.lower() in ("ok", "pass", "passed", "healthy"):
            continue
        source_id = perfmon_section_source_id(section_name)
        if source_id and source_id not in findings:
            findings[source_id] = (
                section_name,
                perfmon_finding_context(section_data),
            )
    return [
        (source_id, findings[source_id][0], findings[source_id][1])
        for source_id in sorted(findings)
    ]


def build_perfmon_automated_findings_table_xml(observations: dict) -> str:
    """Build the Mini Report table for scorecard-referenced findings."""
    rows = perfmon_automated_finding_rows(observations)
    if not rows:
        return ""

    widths = [1600, 2300, 6100]
    xml = heading_paragraph_xml("Automated Findings", level=3)
    xml += (
        "<w:tbl><w:tblPr>"
        '<w:tblStyle w:val="BigFixContent"/>'
        '<w:tblW w:w="5000" w:type="pct"/>'
        '<w:tblLook w:val="04A0" w:firstRow="1" w:lastRow="0" w:firstColumn="1" w:lastColumn="0" w:noHBand="0" w:noVBand="1"/>'
        "</w:tblPr><w:tblGrid>"
        + "".join(f'<w:gridCol w:w="{width}"/>' for width in widths)
        + "</w:tblGrid>"
    )
    xml += (
        "<w:tr>"
        + table_cell_xml("Finding ID", widths[0], bold=True)
        + table_cell_xml("Area", widths[1], bold=True)
        + table_cell_xml("Review Context", widths[2], bold=True)
        + "</w:tr>"
    )
    for source_id, area, context in rows:
        xml += (
            "<w:tr>"
            + table_cell_xml(source_id, widths[0])
            + table_cell_xml(area, widths[1])
            + table_cell_xml(context, widths[2])
            + "</w:tr>"
        )
    return xml + "</w:tbl><w:p/>"


def render_perfmon_scorecard(observations: dict, output_path: Path) -> Path | None:
    """Render the PerfMon Infrastructure Analysis panel from the design HTML.

    Flattens the per-counter observations into the design's small-multiple panels
    (counter -> peak value + a neutral peak bar with a fixed threshold marker +
    Pass/Fail pill + threshold caption) under an overall weighted score, and
    screenshots the design template via html_charts -- pixel-exact to
    after_renders/03. One neutral bar color; status shown by the pill + marker.
    """
    if not observations:
        return None
    from Lib.Design import html_charts

    perfmon_counts = aggregate_perfmon_scorecard(observations)
    score = perfmon_overall_score(perfmon_counts) or 0

    def fmt_value(value) -> str:
        try:
            f = float(value)
            return format_report_number(f)
        except Exception:
            return str(value or "-")

    def unit_for(thr_str: str) -> str:
        # The displayed number carries its unit so "8" reads "8%" / "0.5 ms" and
        # the reader knows what the limit is measured against.
        s = str(thr_str or "")
        if "%" in s:
            return "%"
        if "ms" in s:
            return " ms"
        return ""

    def fill_for(avg_val, thr_str: str, res: str) -> int:
        # Stylized: the design marker sits at a fixed 62% (fail) / 80% (pass); the
        # fill places the AVERAGE relative to the parsed limit, clamped, so the bar
        # ends before the marker when passing and past it when failing.
        th = re.search(r"\d[\d,]*(?:\.\d+)?", str(thr_str))
        if avg_val is not None and th:
            try:
                a = float(avg_val)
                t = float(th.group().replace(",", ""))
                if t > 0:
                    mark = 62 if res == "fail" else 80
                    return round(min(100, max(8, a / t * mark)))
            except Exception:
                pass
        return 88 if res == "fail" else 55

    # A bare "limit 5%" / "limit 10%" leaves the reader asking "% of what?"; add a
    # short qualifier for the percentage counters where it is ambiguous.
    _LIMIT_OF = {
        "Memory Health": " (physical memory)",
        "CPU Privileged Time": " (CPU time)",
        "CPU Utilization": " (CPU time)",
    }

    def short_threshold(thr, section_name: str) -> str:
        # The design uses a compact caption per panel (e.g. "limit 1 ms"); the
        # raw thresholds are sentences. Pull the comparison + value (+ % / ms),
        # a saturation figure, or "approach zero"; else trim.
        s = re.sub(r"\s+", " ", str(thr or "")).strip()
        m = re.search(r"(?:<=|>=|<|>)\s*([\d,.]+)\s*(%|ms)?", s)
        if m:
            unit = m.group(2) or ""
            qualifier = _LIMIT_OF.get(section_name, "") if unit == "%" else ""
            return f"limit {m.group(1)}{unit}{qualifier}"
        if "approach zero" in s.lower():
            return "approach zero"
        m2 = re.search(r"([\d,]+)\s*(?:transfers per second|transfers/sec|/sec|/s)", s)
        if m2:
            return f"~{m2.group(1)}/s"
        return (s[:18] + "…") if len(s) > 20 else (s or "-")

    # One compact panel per *section*: exactly the design's 8-up grid. The
    # section name is short ("Storage Queue Depth"), versus the raw per-disk
    # counter names that ran the panel off the page; per-disk detail charts are
    # still inserted separately. Section-level average/threshold/status drive the
    # value/marker/pill (average, not peak -- a transient spike must not fail an
    # otherwise-healthy counter; 2026-07-02 per user).
    counters = []
    findings_summary = {"critical": 0, "warning": 0, "cannotVerify": 0}
    finding_ids: list[str] = []
    for section_data in observations.get("sections", {}).values():
        name = re.sub(r"\s+", " ", str(section_data.get("section", ""))).strip()
        if not name:
            continue
        status = str(section_data.get("status", "")).strip().lower()
        if status in ("ok", "pass", "passed", "healthy"):
            res = "pass"
        elif status in ("not available", "cannot verify"):
            res = "cannot"
        else:
            res = "fail"
        if res != "pass":
            if status in ("warning", "warn", "advisory", "needs attention"):
                findings_summary["warning"] += 1
            elif status in ("not available", "cannot verify"):
                findings_summary["cannotVerify"] += 1
            else:
                findings_summary["critical"] += 1
            source_id = perfmon_section_source_id(name)
            if source_id and source_id not in finding_ids:
                finding_ids.append(source_id)
        thr = section_data.get("threshold", "")
        avg_raw = section_data.get("average")
        if res == "cannot" and avg_raw is None:
            avg_display = "Cannot verify" if name == "Memory Health" else "No data"
        else:
            avg_display = fmt_value(avg_raw) + unit_for(thr)
        counters.append(
            [
                name,
                avg_display,
                short_threshold(thr, name),
                res,
                fill_for(avg_raw, thr, res),
            ]
        )

    if score < 70:
        score_color, cls, label = "#C5283D", "st-critical", "Critical"
    elif score < 90:
        score_color, cls, label = "#A85D00", "st-attention", "Needs Attention"
    else:
        score_color, cls, label = "#1F8A5B", "st-healthy", "Healthy"

    data = {
        "title": "PerfMon Infrastructure Analysis",
        "sub": f"{len(counters)} checks vs. thresholds · value = average · bar vs. limit marker",
        "score": score,
        "scoreColor": score_color,
        "status": {"cls": cls, "label": label},
        "counters": counters,
        "findingsSummary": {
            "total": sum(findings_summary.values()),
            **findings_summary,
        },
        "findingIds": sorted(finding_ids),
    }
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        html_charts.render_chart("perfmon", data, output_path)
        return output_path
    except Exception as exc:  # pragma: no cover - render is best-effort
        log.warn(f"PerfMon scorecard render failed: {exc}")
        return None


def find_perfmon_scorecard_insert_point(doc_xml: str) -> int | None:
    """Locate the body PerfMon heading where the scorecard should be inserted."""
    for pm in get_document_paragraphs(doc_xml):
        para = pm.group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        if is_perfmon_counters_heading(para, text):
            return pm.start() + len(para)
    return None


def perfmon_scorecard_image_xml(rid: str, png_path: Path, picture_id: int) -> str:
    """Build a centered Word image paragraph for the generated scorecard."""
    cx, cy = png_emu(png_path, 7.35)
    alt = xml_attr_escape(PERFMON_SCORECARD_TITLE)
    return (
        '<w:p><w:pPr><w:jc w:val="center"/><w:spacing w:before="120" w:after="180"/></w:pPr>'
        "<w:r><w:drawing>"
        '<wp:inline xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{picture_id}" name="{alt}" descr="{alt}"/>'
        "<wp:cNvGraphicFramePr/>"
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        f'<pic:nvPicPr><pic:cNvPr id="{picture_id}" name="{alt}" descr="{alt}"/>'
        "<pic:cNvPicPr/></pic:nvPicPr>"
        "<pic:blipFill>"
        f'<a:blip r:embed="{rid}" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/>'
        "<a:stretch><a:fillRect/></a:stretch></pic:blipFill>"
        f'<pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr>'
        "</pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def insert_perfmon_scorecard_xml(
    doc_xml: str, rid: str, png_path: Path, picture_id: int = 9100
) -> str:
    """Insert the generated scorecard directly below the PerfMon section heading."""
    # Idempotency: skip if a scorecard is already present anywhere in the doc.
    # The title appears verbatim as the image's docPr name once inserted, so a
    # whole-document substring check is reliable. (paragraph_plain_text only
    # reads a single paragraph, so on a re-injection pass -- selective update of
    # an already-built report -- it missed the existing scorecard and stacked a
    # second copy.)
    if PERFMON_SCORECARD_TITLE in doc_xml:
        return doc_xml
    insert_at = find_perfmon_scorecard_insert_point(doc_xml)
    if insert_at is None:
        log.warn(
            "Could not find PerfMon Counters Analysis heading; scorecard not inserted."
        )
        return doc_xml
    return (
        doc_xml[:insert_at]
        + "\n"
        + perfmon_scorecard_image_xml(rid, png_path, picture_id)
        + "\n"
        + perfmon_score_method_note_xml()
        + "\n"
        + doc_xml[insert_at:]
    )


def ensure_png_content_type(content_types_xml: str) -> str:
    """Ensure DOCX content types include PNG images."""
    if 'Extension="png"' in content_types_xml:
        return content_types_xml
    return content_types_xml.replace(
        "</Types>",
        '  <Default Extension="png" ContentType="image/png"/>\n</Types>',
        1,
    )


def build_summary_xml(observations: dict, include_assessment: bool = True) -> str:
    """Capture Summary: the counter sentence and the capture line, then the
    Hardware / Context table. The priority list stays in Excel Worst Offenders."""
    summary = observations.get("summary", {})
    lines = [
        str(line)
        for line in summary.get("lines", [])
        if line
        and not str(line).strip().casefold().startswith("highest-priority review items")
    ]
    hardware_xml = build_perfmon_hardware_context_xml(observations)
    if not lines and not hardware_xml:
        return ""
    xml = heading_paragraph_xml("Capture Summary", level=3)
    for line in lines:
        xml += text_paragraph_xml(line)
    return (build_assessment_by_area_xml(observations, level=3) if include_assessment else "") + xml + hardware_xml


def build_assessment_by_area_xml(observations: dict, level: int) -> str:
    """Assessment by Area, the reference table before counter detail."""
    table_xml = build_perfmon_summary_table_xml(observations)
    if not table_xml:
        return ""
    return heading_paragraph_xml("Assessment by Area", level=level) + table_xml


def insert_perfmon_summary(doc_xml: str, observations: dict) -> str:
    if not observations:
        return doc_xml
    for line in observations.get("summary", {}).get("lines", []):
        if line and str(line) in paragraph_plain_text(doc_xml):
            return doc_xml
    summary_xml = build_summary_xml(observations)
    if not summary_xml:
        return doc_xml
    doc_xml, inserted = insert_after_general_observations_placeholder(
        doc_xml, summary_xml
    )
    if inserted:
        log.step("Inserting PerfMon infrastructure summary")
        return doc_xml
    insert_at = find_perfmon_summary_insert_point(doc_xml)
    if insert_at is not None:
        log.step("Inserting PerfMon infrastructure summary")
        return doc_xml[:insert_at] + summary_xml + doc_xml[insert_at:]
    log.warn("Could not find PerfMon heading for summary insertion.")
    return doc_xml


def perfmon_area_heading_level(doc_xml: str) -> int | None:
    """Heading level of the first area heading in the PerfMon section."""
    in_perfmon = False
    perfmon_level = 0
    for pm in get_document_paragraphs(doc_xml):
        para = pm.group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        level = paragraph_heading_level(para)
        if not in_perfmon:
            if is_perfmon_counters_heading(para, text):
                in_perfmon = True
                perfmon_level = level or 1
            continue
        if level and level <= perfmon_level:
            return None
        if level and perfmon_section_key_for_text(text):
            return level
    return None


def insert_perfmon_assessment(doc_xml: str, observations: dict) -> str:
    """Put Assessment by Area at the end of the PerfMon section."""
    if not observations or not observations.get("sections"):
        return doc_xml
    if any(
        paragraph_plain_text(pm.group(0)) == "Assessment by Area"
        for pm in get_document_paragraphs(doc_xml)
    ):
        return doc_xml
    level = perfmon_area_heading_level(doc_xml)
    if level is None:
        log.warn(
            "Could not find a PerfMon area heading. Assessment by Area not inserted."
        )
        return doc_xml
    assessment_xml = build_assessment_by_area_xml(observations, level)
    if not assessment_xml:
        return doc_xml
    log.step("Inserting PerfMon Assessment by Area")
    insert_at = find_perfmon_append_insert_point(doc_xml)
    return doc_xml[:insert_at] + assessment_xml + doc_xml[insert_at:]


def replace_observation_placeholders(doc_xml: str, observations: dict) -> str:
    sections = observations.get("sections", {}) if observations else {}
    if not sections:
        return doc_xml

    replacements: list[tuple[int, int, str, str]] = []
    in_perfmon_appendix = False
    perfmon_heading_level = 0
    current_section_key: str | None = None
    current_section_level = 3

    for pm in get_document_paragraphs(doc_xml):
        para = pm.group(0)
        text = paragraph_plain_text(para)
        heading_level = paragraph_heading_level(para)

        if not in_perfmon_appendix:
            if text and is_perfmon_counters_heading(para, text):
                in_perfmon_appendix = True
                perfmon_heading_level = heading_level or 1
            continue

        if (
            heading_level
            and perfmon_heading_level
            and heading_level <= perfmon_heading_level
        ):
            break

        if text and is_perfmon_section_heading_candidate(para, text):
            matched_key = perfmon_section_key_for_text(text)
            # The area heading starts a section. A counter heading under it can
            # match the same area, so only the first match sets the level.
            if matched_key and matched_key != current_section_key:
                current_section_key = matched_key
                current_section_level = heading_level or current_section_level

        if not re.search(r"Your\s+observations\s+go\s+here", text, flags=re.IGNORECASE):
            continue

        section_key = current_section_key
        if section_key not in sections:
            continue

        section = sections[section_key]
        observation = section.get("observation", "").strip()
        if not observation:
            continue

        replacements.append(
            (
                pm.start(),
                pm.end(),
                observation_paragraph_xml(section, current_section_level + 1),
                section_key,
            )
        )

    for start, end, replacement_xml, section_key in reversed(replacements):
        doc_xml, moved_bookmarks = splice_preserving_bookmarks(
            doc_xml,
            start,
            end,
            replacement_xml,
        )
        if moved_bookmarks:
            log.detail("Bookmark boundary markers preserved", moved_bookmarks)
        log.detail("Updated observation for", section_key)

    if sections and not replacements:
        log.warn(
            "No 'Your observations go here' placeholders were found in the PerfMon section."
        )

    return doc_xml


def relationship_id_to_media(rels_xml: str) -> dict[str, str]:
    """
    Build rId -> media filename map from document.xml.rels.

    Attribute-order agnostic.
    """
    rid_to_media: dict[str, str] = {}

    for match in re.finditer(r"<Relationship\b[^>]*/?>", rels_xml, flags=re.IGNORECASE):
        rel = match.group(0)

        if IMAGE_REL_TYPE not in rel and "image" not in rel.lower():
            continue

        id_match = re.search(r'\bId="(rId\d+)"', rel)
        target_match = re.search(r'\bTarget="([^"]+)"', rel)

        if id_match and target_match:
            target = target_match.group(1).replace("\\", "/")
            media_name = Path(target).name
            if media_name:
                rid_to_media[id_match.group(1)] = media_name

    return rid_to_media


def placeholder_token(rid: str, paragraph_start: int) -> str:
    """Identify a placeholder occurrence, even when Word reuses the same rId."""
    return f"{rid}@{paragraph_start}"


def split_placeholder_token(token: str) -> tuple[str, int | None]:
    """Return the relationship id and original paragraph position for a token."""
    rid, separator, position = token.partition("@")
    if not separator:
        return rid, None
    try:
        return rid, int(position)
    except ValueError:
        return rid, None


def discover_perfmon_sections(
    doc_xml: str,
    rels_xml: str,
) -> tuple[dict[str, list[str]], dict[str, int], dict[str, str]]:
    """
    Walk template paragraphs to discover:
      - section -> placeholder occurrence tokens
      - section -> insert point immediately after heading paragraph
      - image rId -> existing media filename

    This mirrors the PowerShell approach:
      - Find the first paragraph containing "PerfMon" to enter the appendix.
      - Match sections by keyword words being present in heading text.
      - Scan image-only paragraphs before text matching/skipping.
    """
    paragraphs = get_document_paragraphs(doc_xml)
    rid_to_media = relationship_id_to_media(rels_xml)

    log.detail("Image relationships in rels", len(rid_to_media))
    for rid in sorted(rid_to_media):
        log.detail(rid, rid_to_media[rid])

    current_section_key: str | None = None
    section_rids: dict[str, list[str]] = OrderedDict()
    section_insert_points: dict[str, int] = OrderedDict()
    claimed_placeholder_tokens: set[str] = set()
    in_perfmon_appendix = False
    perfmon_heading_level = 0
    perfmon_done = False

    for pm in paragraphs:
        if perfmon_done:
            break

        para = pm.group(0)
        text = paragraph_plain_text(para)
        heading_level = paragraph_heading_level(para)

        # Skip TOC entries everywhere.
        if re.search(r"PAGEREF", text):
            continue

        # Before Perfmon appendix: watch for the entry trigger.
        if not in_perfmon_appendix:
            if text and is_perfmon_counters_heading(para, text):
                in_perfmon_appendix = True
                perfmon_heading_level = heading_level or 1
                log.detail("Entered PerfMon appendix at", text)
            continue

        # Inside Perfmon appendix.
        if (
            heading_level
            and perfmon_heading_level
            and heading_level <= perfmon_heading_level
        ):
            log.detail("Leaving PerfMon appendix at", text)
            break

        # Scan for images before text-based skipping. Image-only paragraphs have
        # little/no text and would otherwise be missed.
        if current_section_key is not None:
            for em in re.finditer(r'(?:r:embed|r:id)="(rId\d+)"', para):
                rid = em.group(1)
                token = placeholder_token(rid, pm.start())

                if token in claimed_placeholder_tokens:
                    continue

                if rid in rid_to_media:
                    section_rids.setdefault(current_section_key, [])
                    if token not in section_rids[current_section_key]:
                        section_rids[current_section_key].append(token)
                        claimed_placeholder_tokens.add(token)
                        log.detail(
                            "Found placeholder",
                            f"{rid} -> {rid_to_media[rid]} in '{current_section_key}'",
                        )
                else:
                    log.detail(
                        "Note",
                        f"r:embed/r:id='{rid}' in '{current_section_key}' is not an image rel",
                    )

            if current_section_key == "Memory Health" and section_rids.get(
                "Memory Health"
            ):
                perfmon_done = True

        if not text:
            continue

        matched_key = (
            perfmon_section_key_for_text(text)
            if is_perfmon_section_heading_candidate(para, text)
            else None
        )

        if matched_key:
            current_section_key = matched_key
            section_insert_points[matched_key] = pm.start() + len(para)
            section_rids.setdefault(matched_key, [])
            log.detail("Section matched", f"'{current_section_key}' <- '{text}'")

    if not in_perfmon_appendix:
        log.warn("Could not find any paragraph containing 'PerfMon' in the template.")
        log.detail("Paragraph text found in template:")
        for pm in paragraphs:
            text = paragraph_plain_text(pm.group(0))
            if text and not re.search(r"PAGEREF", text):
                log.detail(text)

    return section_rids, section_insert_points, rid_to_media


def build_rid_to_png_map(
    section_rids: dict[str, list[str]],
    pattern_to_pngs: OrderedDict[str, list[Path]],
) -> tuple[OrderedDict[str, Path], dict[str, list[Path]]]:
    """
    Map placeholder occurrence tokens to PNGs (replace mode), and collect any
    extra PNGs beyond the placeholder count for each section (insert-after mode).

    Returns:
        rid_to_png      placeholder token -> single PNG for replacement.
        section_extras  section_key -> list[Path] of PNGs that have no
                        corresponding placeholder and must be inserted after
                        the last placeholder paragraph.
    """
    rid_to_png: OrderedDict[str, Path] = OrderedDict()
    section_extras: dict[str, list[Path]] = {}

    for section_key, patterns in SECTION_COUNTER_MAP.items():
        if section_key not in section_rids:
            log.warn(f"Section '{section_key}' not found in template")
            continue

        placeholder_rids = section_rids[section_key]

        # Flatten all PNGs for this section across all its patterns, in order.
        all_pngs: list[Path] = []
        for pattern in patterns:
            all_pngs.extend(pattern_to_pngs.get(pattern, []))

        # Pair as many PNGs as possible with placeholder occurrences.
        limit = min(len(placeholder_rids), len(all_pngs))
        for idx in range(limit):
            rid_to_png[placeholder_rids[idx]] = all_pngs[idx]
            rid, _ = split_placeholder_token(placeholder_rids[idx])
            log.detail("Mapped", f"{rid} -> {all_pngs[idx].name}")

        # Any remaining PNGs beyond the placeholder count go into extras.
        extras = all_pngs[limit:] if placeholder_rids else []
        if extras:
            section_extras[section_key] = extras
            for png in extras:
                log.detail("Extra (will insert after placeholders)", png.name)

        if not all_pngs:
            for pattern in patterns:
                if pattern not in pattern_to_pngs or not pattern_to_pngs[pattern]:
                    log.warn(f"No PNG found for pattern '{pattern}'")

    return rid_to_png, section_extras


def next_relationship_id(rels_xml: str) -> int:
    existing = [int(m.group(1)) for m in re.finditer(r'Id="rId(\d+)"', rels_xml)]

    if not existing:
        return 1

    return max(existing) + 1


def next_picture_id(doc_xml: str) -> int:
    existing = [
        int(m.group(1)) for m in re.finditer(r'<wp:docPr\b[^>]*\bid="(\d+)"', doc_xml)
    ]
    return max(existing, default=199) + 1


def remove_relationship_by_id(rels_xml: str, rid: str) -> str:
    """
    Remove relationship element with a specific Id, attribute-order agnostic.
    """
    pattern = re.compile(
        r"\s*<Relationship\b(?=[^>]*\bId=\"" + re.escape(rid) + r"\")[^>]*/>",
        flags=re.IGNORECASE,
    )
    return pattern.sub("", rels_xml)


def add_image_relationship(rels_xml: str, rid: str, target: str) -> str:
    relationship_xml = (
        f'  <Relationship Id="{xml_attr_escape(rid)}" '
        f'Type="{IMAGE_REL_TYPE}" '
        f'Target="{xml_attr_escape(target)}"/>\n'
    )

    if "</Relationships>" not in rels_xml:
        raise ValueError(
            "Template relationship file is missing closing </Relationships> tag."
        )

    return rels_xml.replace("</Relationships>", relationship_xml + "</Relationships>", 1)


def png_dimensions(path: Path) -> tuple[int, int]:
    try:
        with path.open("rb") as handle:
            if handle.read(8) != b"\x89PNG\r\n\x1a\n":
                return 0, 0
            handle.read(8)
            return unpack(">II", handle.read(8))
    except OSError:
        return 0, 0


def usable_page_width_in(doc_xml: str, default: float = 7.5) -> float:
    sect_match = re.search(r"<w:sectPr\b.*?</w:sectPr>", doc_xml, flags=re.DOTALL)
    xml = sect_match.group(0) if sect_match else doc_xml
    page_match = re.search(r"<w:pgSz\b[^>]*\bw:w=\"(\d+)\"", xml)
    margin_match = re.search(
        r"<w:pgMar\b[^>]*\bw:left=\"(\d+)\"[^>]*\bw:right=\"(\d+)\"", xml
    )
    if not page_match or not margin_match:
        return default
    page_width = int(page_match.group(1))
    left = int(margin_match.group(1))
    right = int(margin_match.group(2))
    usable = (page_width - left - right) / DXA_PER_INCH
    return usable if usable > 1 else default


def png_emu(path: Path, max_width_in: float) -> tuple[int, int]:
    width_px, height_px = png_dimensions(path)
    if not width_px or not height_px:
        return int(max_width_in * EMU_PER_INCH), int(max_width_in * 0.5 * EMU_PER_INCH)
    width_in = width_px / PNG_DPI
    height_in = height_px / PNG_DPI
    if width_in > max_width_in:
        scale = max_width_in / width_in
        width_in *= scale
        height_in *= scale
    return int(width_in * EMU_PER_INCH), int(height_in * EMU_PER_INCH)


def new_drawing_xml(rid: str, picture_id: int, cx: int, cy: int, alt_text: str = "") -> str:
    """
    Build DrawingML for an inline image.

    Default dimensions match the PowerShell script:
      cx 6858000, cy 3429000
    """
    return (
        "<w:p>"
        "<w:r><w:rPr><w:noProof/></w:rPr><w:drawing>"
        '<wp:inline distT="0" distB="0" distL="0" distR="0" '
        'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">'
        f'<wp:extent cx="{cx}" cy="{cy}"/>'
        '<wp:effectExtent l="0" t="0" r="0" b="0"/>'
        f'<wp:docPr id="{picture_id}" name="PerfmonChart{picture_id}" descr="{xml_attr_escape(alt_text)}"/>'
        "<wp:cNvGraphicFramePr>"
        '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
        "</wp:cNvGraphicFramePr>"
        '<a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        '<pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture">'
        "<pic:nvPicPr>"
        f'<pic:cNvPr id="{picture_id}" name="PerfmonChart{picture_id}"/>'
        "<pic:cNvPicPr/>"
        "</pic:nvPicPr>"
        "<pic:blipFill>"
        f'<a:blip r:embed="{rid}"/>'
        "<a:stretch><a:fillRect/></a:stretch>"
        "</pic:blipFill>"
        "<pic:spPr>"
        f'<a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        "</pic:spPr>"
        "</pic:pic></a:graphicData></a:graphic>"
        "</wp:inline></w:drawing></w:r></w:p>"
    )


def build_injections(
    doc_xml: str,
    rid_to_png: OrderedDict[str, Path],
    section_rids: dict[str, list[str]],
    section_insert_points: dict[str, int],
    pattern_to_pngs: OrderedDict[str, list[Path]],
    section_extras: dict[str, list[Path]],
) -> list[dict]:
    """
    Build the unified injection list combining three cases:

    1. Replace mode: template has a placeholder image whose rId maps to a PNG.
                       The placeholder paragraph is replaced with the chart.

    2. Insert mode: no placeholder found for the section; charts are inserted
                       as new paragraphs immediately after the section heading.
                       All matched PNGs (including multi-disk instances) are
                       inserted together under one injection entry.

    3. Extras mode: the section had placeholders but more PNGs were found than
                       placeholders (e.g. 3 physical disk charts but only 1
                       placeholder image). The extra PNGs are inserted immediately
                       after the last placeholder paragraph.
    """
    injections: list[dict] = []

    # ---- Case 1: replace placeholders with matched PNGs --------------------
    # Track the last placeholder paragraph position per section for extras.
    section_last_placeholder_pos: dict[str, int] = {}

    for placeholder_token_value, png_path in rid_to_png.items():
        placeholder_rid, paragraph_start = split_placeholder_token(
            placeholder_token_value
        )

        if paragraph_start is not None:
            p_start = paragraph_start
            p_end = doc_xml.find("</w:p>", p_start)
            paragraph = doc_xml[p_start:p_end] if p_end >= 0 else ""
            if placeholder_rid not in paragraph:
                log.warn(f"{placeholder_rid} not found at placeholder occurrence")
                continue
            search_str = f'r:embed="{placeholder_rid}"'
            if search_str not in paragraph:
                search_str = f'r:id="{placeholder_rid}"'
        else:
            search_str = f'r:embed="{placeholder_rid}"'
            embed_idx = doc_xml.find(search_str)

            if embed_idx < 0:
                search_str = f'r:id="{placeholder_rid}"'
                embed_idx = doc_xml.find(search_str)

            if embed_idx < 0:
                log.warn(f"{placeholder_rid} not found in document")
                continue

            p_start = doc_xml.rfind("<w:p ", 0, embed_idx)
            if p_start < 0:
                p_start = doc_xml.rfind("<w:p>", 0, embed_idx)

        if p_start < 0:
            log.warn(f"Could not find paragraph start for {placeholder_rid}")
            continue

        # Find which section owns this occurrence so we can track the last position.
        for sec_key, rids in section_rids.items():
            if placeholder_token_value in rids:
                section_last_placeholder_pos[sec_key] = p_start
                break

        injections.append(
            {
                "Position": p_start,
                "Mode": "replace",
                "PngPaths": [png_path],
                "RidToRemove": placeholder_rid,
                "PlaceholderToken": placeholder_token_value,
                "SearchStr": search_str,
            }
        )

    # ---- Case 2: insert all matched PNGs after heading (no placeholder) ----
    for section_key, patterns in SECTION_COUNTER_MAP.items():
        has_placeholder = (
            section_key in section_rids and len(section_rids[section_key]) > 0
        )

        if has_placeholder:
            continue

        if section_key not in section_insert_points:
            continue

        # Collect all PNGs for this section across all its patterns.
        all_pngs: list[Path] = []
        for pattern in patterns:
            all_pngs.extend(pattern_to_pngs.get(pattern, []))

        if not all_pngs:
            continue

        injections.append(
            {
                "Position": section_insert_points[section_key],
                "Mode": "insert",
                "PngPaths": all_pngs,
                "Section": section_key,
            }
        )

    # ---- Case 3: insert extra PNGs after the last placeholder --------------
    for section_key, extra_pngs in section_extras.items():
        if not extra_pngs:
            continue

        if section_key not in section_last_placeholder_pos:
            # Fall back to the heading insert point if we lost track.
            pos = section_insert_points.get(section_key)
            if pos is None:
                log.warn(f"Cannot find insert position for extras in '{section_key}'")
                continue
        else:
            # Insert immediately after the last placeholder paragraph end.
            last_pos = section_last_placeholder_pos[section_key]
            p_end = doc_xml.find("</w:p>", last_pos)
            pos = (
                p_end + len("</w:p>")
                if p_end >= 0
                else section_last_placeholder_pos[section_key]
            )

        log.detail(
            "Inserting extra charts",
            f"{len(extra_pngs)} after placeholders for '{section_key}'",
        )
        injections.append(
            {
                "Position": pos,
                "Mode": "insert",
                "PngPaths": extra_pngs,
                "Section": section_key,
            }
        )

    return sorted(injections, key=lambda item: item["Position"], reverse=True)


def _dedup_docpr_ids(doc_xml: str) -> str:
    """Renumber duplicate wp:docPr id values so each is unique.

    Multiple injection steps (dashboard, dbinfo, filldb) each embed images
    starting from id="1", so the accumulated document can have duplicates by
    the time perfmon injection runs.  This repair pass assigns fresh IDs to
    any duplicate occurrences, keeping the first occurrence of each ID intact.
    """
    seen: set[int] = set()
    next_free: list[int] = [
        max(
            (
                int(m.group(1))
                for m in re.finditer(r'<wp:docPr\b[^>]*\bid="(\d+)"', doc_xml)
            ),
            default=0,
        )
        + 1
    ]

    def _replace(m: re.Match) -> str:
        pre = m.group(1)
        doc_id = int(m.group(2))
        post = m.group(3)
        if doc_id not in seen:
            seen.add(doc_id)
            return m.group(0)
        new_id = next_free[0]
        seen.add(new_id)
        next_free[0] = new_id + 1
        return f"{pre}{new_id}{post}"

    return re.sub(r'(<wp:docPr\b[^>]*\bid=")(\d+)(")', _replace, doc_xml)


def find_perfmon_append_insert_point(doc_xml: str) -> int:
    """Append supplemental PerfMon content before the next peer section."""
    paragraphs = get_document_paragraphs(doc_xml)
    perfmon_level = 0
    in_perfmon = False
    for pm in paragraphs:
        para = pm.group(0)
        text = paragraph_plain_text(para)
        if not text or is_toc_or_field_paragraph(para, text):
            continue
        heading_level = paragraph_heading_level(para)
        if not in_perfmon:
            if is_perfmon_counters_heading(para, text):
                in_perfmon = True
                perfmon_level = heading_level or 1
            continue
        if heading_level and perfmon_level and heading_level <= perfmon_level:
            return pm.start()

    body_end = doc_xml.rfind("</w:body>")
    section_properties = doc_xml.rfind("<w:sectPr", 0, body_end)
    if section_properties >= 0 and re.fullmatch(r"<w:sectPr\b[^>]*(?:/>|>.*?</w:sectPr>)\s*", doc_xml[section_properties:body_end], flags=re.DOTALL):
        return section_properties
    return body_end if body_end >= 0 else len(doc_xml)


def section_pngs_for_append(
    pattern_to_pngs: OrderedDict[str, list[Path]],
) -> OrderedDict[str, list[Path]]:
    by_section: OrderedDict[str, list[Path]] = OrderedDict()
    for section, patterns in SECTION_COUNTER_MAP.items():
        pngs: list[Path] = []
        seen: set[Path] = set()
        for pattern in patterns:
            for png in pattern_to_pngs.get(pattern, []):
                if png not in seen:
                    pngs.append(png)
                    seen.add(png)
        if pngs:
            by_section[section] = pngs
    return by_section


def append_perfmon_capture_section(
    chart_folder: Path,
    template_path: Path,
    output_path: Path,
    section_title: str = "Additional PerfMon Capture",
    include_automated_findings: bool = False,
) -> None:
    log.step("Scanning supplemental PerfMon graph folder")
    log.detail("Graph folder", chart_folder)

    png_files = scan_chart_folder(chart_folder)
    pattern_to_pngs = map_patterns_to_pngs(png_files)
    observations = load_perfmon_observations(chart_folder)
    scorecard_path = render_perfmon_scorecard(
        observations,
        chart_folder / "PerfMon_Counters_Analysis_Scorecard.png",
    )

    copy_docx_to_output(template_path, output_path)
    doc_xml = read_zip_text(output_path, "word/document.xml")
    rels_xml = read_zip_text(output_path, "word/_rels/document.xml.rels")
    content_types_xml = read_zip_text(output_path, "[Content_Types].xml")

    next_rid = next_relationship_id(rels_xml)
    picture_id = next_picture_id(doc_xml)
    max_chart_width_in = usable_page_width_in(doc_xml)
    section_chunks: list[str] = [heading_paragraph_xml(section_title, level=2)]

    # The server name sits right under the capture heading, above the scorecard,
    # so the reader can tell which server a capture covers at a glance.
    environment = observations.get("environment", {}) if observations else {}
    analyzed_system = str(environment.get("Analyzed System") or "").strip()
    if not analyzed_system or analyzed_system == "Not detected":
        analyzed_system = "Server name missing"
    section_chunks.append(
        "<w:p><w:pPr><w:keepNext/></w:pPr>"
        "<w:r>"
        f"<w:t>{xml_text_escape(analyzed_system)}</w:t></w:r></w:p>"
    )

    def _append_png(zf: zipfile.ZipFile, png_path: Path) -> str:
        nonlocal rels_xml, content_types_xml, next_rid, picture_id
        rid = f"rId{next_rid}"
        img_file = f"perfmon_supplemental_{next_rid}_{png_path.name}"
        member_name = f"word/media/{img_file}"
        zf.writestr(member_name, png_path.read_bytes())
        rels_xml = add_image_relationship(rels_xml, rid, f"media/{img_file}")
        content_types_xml = ensure_png_content_type(content_types_xml)
        cx, cy = png_emu(png_path, max_chart_width_in)
        xml = new_drawing_xml(rid=rid, picture_id=picture_id, cx=cx, cy=cy, alt_text="PerfMon infrastructure score and statuses for the monitored areas." if png_path == scorecard_path else png_path.stem)
        next_rid += 1
        picture_id += 1
        return xml

    with zipfile.ZipFile(output_path, "a", zipfile.ZIP_DEFLATED) as zf:
        if scorecard_path and scorecard_path.exists():
            section_chunks.append(_append_png(zf, scorecard_path))

        if scorecard_path and scorecard_path.exists():
            section_chunks.append(perfmon_score_method_note_xml())

        assessment_xml = build_assessment_by_area_xml(observations, level=3)
        if assessment_xml:
            section_chunks.append(assessment_xml)
        if include_automated_findings:
            findings_xml = build_perfmon_automated_findings_table_xml(observations)
            if findings_xml:
                section_chunks.append(findings_xml)

        summary_xml = build_summary_xml(observations, include_assessment=False)
        if summary_xml:
            section_chunks.append(summary_xml)

        for section, pngs in section_pngs_for_append(pattern_to_pngs).items():
            section_chunks.append(heading_paragraph_xml(section, level=3))
            section_data = observations.get("sections", {}).get(section, {})
            if section_data:
                section_chunks.append(observation_paragraph_xml(section_data, 4))
            for png in pngs:
                section_chunks.append(_append_png(zf, png))

    insert_at = find_perfmon_append_insert_point(doc_xml)
    new_doc_xml = doc_xml[:insert_at] + "\n".join(section_chunks) + doc_xml[insert_at:]
    new_doc_xml = _dedup_docpr_ids(new_doc_xml)
    new_doc_xml = report_tables.normalize_document_xml(new_doc_xml)

    write_or_replace_zip_member(
        output_path,
        "word/document.xml",
        new_doc_xml.encode("utf-8"),
    )
    write_or_replace_zip_member(
        output_path,
        "word/_rels/document.xml.rels",
        rels_xml.encode("utf-8"),
    )
    write_or_replace_zip_member(
        output_path,
        "[Content_Types].xml",
        content_types_xml.encode("utf-8"),
    )

    from Lib.Design.perfmon_report_layout import finalize_perfmon_layout
    finalize_perfmon_layout(output_path, chart_folder, section_title=section_title)
    validate_docx_package(output_path)
    log.ok("Supplemental PerfMon capture appended")
    log.result("Word document", output_path)


def inject_perfmon_charts(
    chart_folder: Path,
    template_path: Path,
    output_path: Path,
    *,
    append_only: bool = False,
    section_title: str = "Additional PerfMon Capture",
    include_automated_findings: bool = False,
) -> None:
    if append_only:
        append_perfmon_capture_section(
            chart_folder=chart_folder,
            template_path=template_path,
            output_path=output_path,
            section_title=section_title,
            include_automated_findings=include_automated_findings,
        )
        return

    log.step("Scanning graph folder")
    log.detail("Graph folder", chart_folder)

    png_files = scan_chart_folder(chart_folder)
    log.detail("PNG files found", len(png_files))

    pattern_to_pngs = map_patterns_to_pngs(png_files)
    observations = load_perfmon_observations(chart_folder)
    scorecard_path = render_perfmon_scorecard(
        observations,
        chart_folder / "PerfMon_Counters_Analysis_Scorecard.png",
    )
    if scorecard_path:
        log.detail("PerfMon scorecard", scorecard_path.name)

    log.step("Preparing output document")
    copy_docx_to_output(template_path, output_path)

    log.step("Reading template")

    doc_xml = read_zip_text(output_path, "word/document.xml")
    rels_xml = read_zip_text(output_path, "word/_rels/document.xml.rels")
    content_types_xml = read_zip_text(output_path, "[Content_Types].xml")

    log.step("Discovering placeholder images in template")

    section_rids, section_insert_points, _ = discover_perfmon_sections(doc_xml, rels_xml)

    log.step("Building chart-to-placeholder map")

    rid_to_png, section_extras = build_rid_to_png_map(section_rids, pattern_to_pngs)

    next_rid = next_relationship_id(rels_xml)
    picture_id = next_picture_id(doc_xml)

    injections = build_injections(
        doc_xml=doc_xml,
        rid_to_png=rid_to_png,
        section_rids=section_rids,
        section_insert_points=section_insert_points,
        pattern_to_pngs=pattern_to_pngs,
        section_extras=section_extras,
    )

    if not injections:
        raise ValueError(
            "No chart injection targets were found. "
            "Confirm the template contains PerfMon section headings and/or placeholder images."
        )

    log.step("Injecting charts")

    new_doc_xml = doc_xml
    new_rels_xml = rels_xml
    max_chart_width_in = usable_page_width_in(doc_xml)

    with zipfile.ZipFile(output_path, "a", zipfile.ZIP_DEFLATED) as zf:
        existing_members = set(zf.namelist())

        for injection in injections:
            if injection["Mode"] == "replace":
                log.detail(
                    "Replacing",
                    f"{injection['RidToRemove']} with: {injection['PngPaths'][0].name}",
                )
            else:
                log.detail(
                    "Inserting charts",
                    f"{len(injection['PngPaths'])} after '{injection['Section']}'",
                )

            insert_xml = ""

            for png_path in injection["PngPaths"]:
                rid = f"rId{next_rid}"
                img_file = f"perfmon_chart_{next_rid}.png"
                member_name = f"word/media/{img_file}"

                if member_name in existing_members:
                    img_file = f"perfmon_chart_{next_rid}_{png_path.name}"
                    member_name = f"word/media/{img_file}"

                zf.writestr(member_name, png_path.read_bytes())
                existing_members.add(member_name)

                new_rels_xml = add_image_relationship(
                    new_rels_xml, rid, f"media/{img_file}"
                )
                content_types_xml = ensure_png_content_type(content_types_xml)
                cx, cy = png_emu(png_path, max_chart_width_in)
                insert_xml += new_drawing_xml(
                    rid=rid, picture_id=picture_id, cx=cx, cy=cy
                )

                log.detail(png_path.name)

                next_rid += 1
                picture_id += 1

            if injection["Mode"] == "replace":
                rid_to_remove = injection["RidToRemove"]
                p_start = injection["Position"]
                p_end = new_doc_xml.find("</w:p>", p_start)
                if p_start < 0 or p_end < 0:
                    log.warn(f"Could not find paragraph bounds for {rid_to_remove}")
                    continue

                p_end += len("</w:p>")
                candidate_xml, moved_bookmarks = splice_preserving_bookmarks(
                    new_doc_xml,
                    p_start,
                    p_end,
                    insert_xml,
                )
                if moved_bookmarks:
                    log.detail("Bookmark boundary markers preserved", moved_bookmarks)
                if not re.search(
                    rf'(?:r:embed|r:id)="{re.escape(rid_to_remove)}"',
                    candidate_xml,
                ):
                    new_rels_xml = remove_relationship_by_id(new_rels_xml, rid_to_remove)
                new_doc_xml = candidate_xml
                log.ok("OK")
            else:
                position = injection["Position"]
                new_doc_xml = new_doc_xml[:position] + insert_xml + new_doc_xml[position:]
                log.ok("OK")

        if scorecard_path and scorecard_path.exists():
            rid = f"rId{next_rid}"
            img_file = "perfmon_counters_analysis_scorecard.png"
            member_name = f"word/media/{img_file}"
            if member_name in existing_members:
                img_file = f"perfmon_counters_analysis_scorecard_{next_rid}.png"
                member_name = f"word/media/{img_file}"

            scorecard_doc_xml = insert_perfmon_scorecard_xml(
                new_doc_xml, rid, scorecard_path, picture_id
            )
            if scorecard_doc_xml != new_doc_xml:
                zf.writestr(member_name, scorecard_path.read_bytes())
                existing_members.add(member_name)
                new_rels_xml = add_image_relationship(
                    new_rels_xml, rid, f"media/{img_file}"
                )
                content_types_xml = ensure_png_content_type(content_types_xml)
                new_doc_xml = scorecard_doc_xml
                next_rid += 1
                picture_id += 1
                log.detail("Inserted PerfMon scorecard", scorecard_path.name)

    # Repair any duplicate wp:docPr id values accumulated by prior injection steps
    new_doc_xml = insert_perfmon_summary(new_doc_xml, observations)
    new_doc_xml = replace_observation_placeholders(new_doc_xml, observations)
    new_doc_xml = insert_perfmon_assessment(new_doc_xml, observations)
    new_doc_xml = _dedup_docpr_ids(new_doc_xml)
    new_doc_xml = report_tables.normalize_document_xml(new_doc_xml)

    log.step("Writing output document")

    write_or_replace_zip_member(
        output_path,
        "word/document.xml",
        new_doc_xml.encode("utf-8"),
    )

    write_or_replace_zip_member(
        output_path,
        "word/_rels/document.xml.rels",
        new_rels_xml.encode("utf-8"),
    )

    write_or_replace_zip_member(
        output_path,
        "[Content_Types].xml",
        content_types_xml.encode("utf-8"),
    )

    from Lib.Design.perfmon_report_layout import finalize_perfmon_layout
    finalize_perfmon_layout(output_path, chart_folder)
    validate_docx_package(output_path)

    log.ok("PerfMon graphs injected")
    log.result("Word document", output_path)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject PerfMon PNG graphs into a Word document."
    )

    parser.add_argument(
        "--chart-folder",
        default="",
        help="Path or folder name containing PerfMon PNG graphs from get_perfmon_chart.py. Folder must contain .png files.",
    )

    parser.add_argument(
        "--template-path",
        default="",
        help="Path or filename of the Word template .docx.",
    )

    parser.add_argument(
        "--output-path",
        default=None,
        help="Optional output .docx path. If omitted, a timestamped copy is created beside the template.",
    )
    parser.add_argument(
        "--append-only",
        action="store_true",
        help="Append this PerfMon graph folder as an additional capture instead of replacing placeholders.",
    )
    parser.add_argument(
        "--include-automated-findings",
        action="store_true",
        help="Include the scorecard-referenced findings table in the Mini Report.",
    )
    parser.add_argument(
        "--section-title",
        default="Additional PerfMon Capture",
        help="Heading used when --append-only is set.",
    )

    args = parser.parse_args()

    log.title("PerfMon Chart Injection")

    try:
        if not args.chart_folder:
            raise ValueError("Chart folder is required. Pass it with --chart-folder.")
        chart_folder = resolve_existing_folder(args.chart_folder, "ChartFolder")

        if not args.template_path:
            raise ValueError("Word template is required. Pass it with --template-path.")
        template_path = resolve_existing_docx(args.template_path, "TemplatePath")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_output = template_path.with_name(
            f"{template_path.stem}_Filled_{timestamp}.docx"
        )
        output_path = resolve_output_docx(args.output_path or "", default_output)

        inject_perfmon_charts(
            chart_folder=chart_folder,
            template_path=template_path,
            output_path=output_path,
            append_only=args.append_only,
            section_title=args.section_title,
            include_automated_findings=args.include_automated_findings,
        )

        return 0

    except KeyboardInterrupt:
        log.warn("Canceled.")
        return 1
    except Exception as exc:
        log.error(str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
