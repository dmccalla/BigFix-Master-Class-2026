#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Build Docs/Master_Class_Lab_Guide.docx from the Master Class lab guide template.

The template (Templates/Master_Class_LabGuide_Template.docx) supplies the
cover, the information page, the Contents field, the revision table, and the
paragraph and table formatting. This script keeps that front matter, drops the
template's example exercises, and writes the Workbench exercises with the
screenshots under Docs/Lab_Guide_Assets.

    uv run python Utilities/capture_lab_guide_screenshots.py
    uv run python Utilities/capture_lab_guide_task_screenshots.py
    uv run python Build/build_lab_guide.py

The Contents field is refreshed by Word afterwards (Build/update_lab_guide_contents.ps1),
which this script runs when PowerShell is available.
"""

from __future__ import annotations

import copy
import shutil
import subprocess
import sys
from pathlib import Path

from docx import Document
from docx.oxml import parse_xml
from docx.oxml.ns import qn
from docx.shared import Inches

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = PROJECT_ROOT / "Templates" / "Master_Class_LabGuide_Template.docx"
ASSETS = PROJECT_ROOT / "Docs" / "Lab_Guide_Assets"
OUTPUT = PROJECT_ROOT / "Docs" / "Master_Class_Lab_Guide.docx"
CONTENTS_SCRIPT = PROJECT_ROOT / "Build" / "update_lab_guide_contents.ps1"

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_W = f'xmlns:w="{W}"'
SITE = "Performance and Config Analysis"
GUIDE_VERSION = "0.2"
GUIDE_DATE = "September 29, 2026"
IMAGE_WIDTH = Inches(6.6)
TASK_IMAGE_WIDTH = Inches(6.0)


# ---------------------------------------------------------------------------
# Template access
# ---------------------------------------------------------------------------


def body_blocks(document):
    return [
        child for child in document.element.body if child.tag in (qn("w:p"), qn("w:tbl"))
    ]


def block_text(block) -> str:
    return "".join(t.text or "" for t in block.iter(qn("w:t"))).strip()


def find_block(document, prefix: str, tag: str = "w:p"):
    for block in body_blocks(document):
        if block.tag == qn(tag) and block_text(block).startswith(prefix):
            return block
    raise LookupError(f"template block not found: {prefix!r}")


def strip_bookmarks(element) -> None:
    for tag in ("w:bookmarkStart", "w:bookmarkEnd"):
        for node in list(element.iter(qn(tag))):
            node.getparent().remove(node)


def set_paragraph_text(paragraph, text: str) -> None:
    """Keep the first run's formatting, drop the rest, set the text."""
    runs = list(paragraph.iter(qn("w:r")))
    keep = None
    for run in runs:
        if run.find(qn("w:t")) is not None:
            keep = run
            break
    if keep is None:
        keep = runs[0]
    for run in runs:
        if run is not keep:
            run.getparent().remove(run)
    for child in list(keep):
        if child.tag != qn("w:rPr"):
            keep.remove(child)
    t = parse_xml(f'<w:t {_W} xml:space="preserve"></w:t>')
    t.text = text
    keep.append(t)


class Exemplars:
    """Paragraphs and tables cloned from the template for their formatting."""

    def __init__(self, document) -> None:
        self.h1 = find_block(document, "Student exercises")
        self.h2 = find_block(document, "Overview")
        self.body = find_block(document, "In this exercise, you will install")
        self.note = find_block(document, "NOTE:")
        self.important = find_block(document, "Important:")
        self.done = find_block(document, "You have now successfully completed Exercise 1")
        self.table = find_block(document, "Host Name", "w:tbl")
        for block in body_blocks(document):
            if block.tag != qn("w:p") or block_text(block):
                continue
            # The cover picture paragraph carries a section break in its
            # properties. Cloning it would start a new section per screenshot.
            if next(block.iter(qn("w:sectPr")), None) is not None:
                continue
            # The drawing sits inside a run, so search the subtree.
            if next(block.iter(qn("w:drawing")), None) is not None:
                self.picture = block
                break
        else:
            raise LookupError("template has no screenshot paragraph")


# ---------------------------------------------------------------------------
# Numbering
# ---------------------------------------------------------------------------


class Numbering:
    """Fresh list instances so every step list restarts at 1."""

    def __init__(self, document) -> None:
        self.part = document.part.numbering_part.element
        self.next_num = max(
            (int(n.get(qn("w:numId"))) for n in self.part.iter(qn("w:num"))),
            default=0,
        )
        self.steps_abstract = self._abstract(
            900, '<w:numFmt w:val="decimal"/><w:lvlText w:val="%1."/>'
        )
        self.bullet_abstract = self._abstract(
            901,
            '<w:numFmt w:val="bullet"/><w:lvlText w:val="&#8226;"/>',
            '<w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/></w:rPr>',
        )

    def _abstract(self, ident: int, fmt: str, rpr: str = "<w:rPr/>") -> int:
        xml = (
            f'<w:abstractNum {_W} w:abstractNumId="{ident}">'
            '<w:multiLevelType w:val="singleLevel"/>'
            f'<w:lvl w:ilvl="0"><w:start w:val="1"/>{fmt}<w:lvlJc w:val="left"/>'
            '<w:pPr><w:ind w:left="1080" w:hanging="360"/></w:pPr>'
            f"{rpr}</w:lvl></w:abstractNum>"
        )
        first_num = self.part.find(qn("w:num"))
        node = parse_xml(xml)
        if first_num is not None:
            first_num.addprevious(node)
        else:
            self.part.append(node)
        return ident

    def new_list(self, abstract: int) -> int:
        self.next_num += 1
        self.part.append(
            parse_xml(
                f'<w:num {_W} w:numId="{self.next_num}">'
                f'<w:abstractNumId w:val="{abstract}"/>'
                '<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
                "</w:num>"
            )
        )
        return self.next_num


# ---------------------------------------------------------------------------
# Writer
# ---------------------------------------------------------------------------


class Guide:
    def __init__(self, document) -> None:
        self.document = document
        self.ex = Exemplars(document)
        self.numbering = Numbering(document)
        self.body = document.element.body
        self.sect_pr = self.body.find(qn("w:sectPr"))

    def _append(self, element) -> None:
        self.sect_pr.addprevious(element)
        return element

    def heading1(self, text: str) -> None:
        p = copy.deepcopy(self.ex.h1)
        strip_bookmarks(p)
        set_paragraph_text(p, text)
        self._append(p)

    def heading2(self, text: str) -> None:
        p = copy.deepcopy(self.ex.h2)
        strip_bookmarks(p)
        set_paragraph_text(p, text)
        self._append(p)

    def para(
        self, text: str, *, bold_prefix: str | None = None, indent: int | None = None
    ):
        p = copy.deepcopy(self.ex.body)
        set_paragraph_text(p, text)
        if indent is not None:
            ind = p.find(qn("w:pPr")).find(qn("w:ind"))
            ind.set(qn("w:left"), str(indent))
            ind.set(qn("w:firstLine"), "0")
        if bold_prefix:
            run = next(r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None)
            label = copy.deepcopy(run)
            label.find(qn("w:t")).text = bold_prefix
            rpr = label.find(qn("w:rPr"))
            for tag in ("w:b", "w:bCs"):
                node = rpr.find(qn(tag))
                if node is None:
                    node = parse_xml(f"<{tag} {_W}/>")
                    rpr.insert(1, node)
                node.attrib.pop(qn("w:val"), None)
            run.addprevious(label)
        self._append(p)
        return p

    def label(self, text: str) -> None:
        p = self.para(text)
        run = next(r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None)
        rpr = run.find(qn("w:rPr"))
        for tag in ("w:b", "w:bCs"):
            node = rpr.find(qn(tag))
            if node is None:
                node = parse_xml(f"<{tag} {_W}/>")
                rpr.insert(1, node)
            node.attrib.pop(qn("w:val"), None)

    def note(self, text: str) -> None:
        self.para(text, bold_prefix="NOTE: ", indent=720)

    def important(self, text: str) -> None:
        p = copy.deepcopy(self.ex.important)
        runs = [r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None]
        runs[0].find(qn("w:t")).text = "Important"
        runs[1].find(qn("w:t")).text = ": " + text
        for extra in runs[2:]:
            extra.getparent().remove(extra)
        self._append(p)

    def done(self, number: int) -> None:
        p = copy.deepcopy(self.ex.done)
        set_paragraph_text(p, f"You have now successfully completed Exercise {number}.")
        self._append(p)

    def _list(self, items: list[str], abstract: int, num_id: int | None = None) -> None:
        if num_id is None:
            num_id = self.numbering.new_list(abstract)
        for item in items:
            p = copy.deepcopy(self.ex.body)
            set_paragraph_text(p, item)
            ppr = p.find(qn("w:pPr"))
            ind = ppr.find(qn("w:ind"))
            ind.set(qn("w:left"), "1080")
            ind.set(qn("w:hanging"), "360")
            ind.attrib.pop(qn("w:firstLine"), None)
            num_pr = parse_xml(
                f'<w:numPr {_W}><w:ilvl w:val="0"/><w:numId w:val="{num_id}"/></w:numPr>'
            )
            ppr.insert(0, num_pr)
            self._append(p)

    def steps(self, items: list[str], *, restart: bool = False) -> None:
        """Numbered steps. A screenshot between calls keeps the numbering
        going, so only the first call of a step list passes restart=True."""
        if restart or getattr(self, "_steps_num", None) is None:
            self._steps_num = self.numbering.new_list(self.numbering.steps_abstract)
        self._list(items, self.numbering.steps_abstract, self._steps_num)

    def bullets(self, items: list[str]) -> None:
        self._list(items, self.numbering.bullet_abstract)

    def picture(self, name: str, width=IMAGE_WIDTH) -> None:
        path = ASSETS / name
        if not path.is_file():
            raise FileNotFoundError(path)
        p = copy.deepcopy(self.ex.picture)
        for run in list(p.iter(qn("w:r"))):
            run.getparent().remove(run)
        self._append(p)
        from docx.text.paragraph import Paragraph

        Paragraph(p, self.document._body).add_run().add_picture(str(path), width=width)

    def code(self, lines: list[str]) -> None:
        for line in lines:
            p = self.para(line, indent=720)
            run = next(r for r in p.iter(qn("w:r")) if r.find(qn("w:t")) is not None)
            rpr = run.find(qn("w:rPr"))
            fonts = rpr.find(qn("w:rFonts"))
            for attr in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
                fonts.set(qn(attr), "Consolas")
            ppr = p.find(qn("w:pPr"))
            spacing = ppr.find(qn("w:spacing"))
            spacing.set(qn("w:before"), "0")
            spacing.set(qn("w:after"), "0")

    def table(self, headers: list[str], rows: list[list[str]], widths: list[int]) -> None:
        tbl = copy.deepcopy(self.ex.table)
        template_rows = tbl.findall(qn("w:tr"))
        head_row, data_row = template_rows[0], template_rows[1]
        for row in template_rows:
            tbl.remove(row)
        grid = tbl.find(qn("w:tblGrid"))
        for col in list(grid):
            grid.remove(col)
        for width in widths:
            grid.append(parse_xml(f'<w:gridCol {_W} w:w="{width}"/>'))
        tbl.find(qn("w:tblPr")).find(qn("w:tblW")).set(qn("w:w"), str(sum(widths)))

        def build_row(exemplar, values, header: bool):
            cells = exemplar.findall(qn("w:tc"))
            # Cell 1 of the template rows is the narrow numbering column.
            # Cell 2 carries the formatting the guide's tables use.
            proto = cells[1]
            row = copy.deepcopy(exemplar)
            for cell in row.findall(qn("w:tc")):
                row.remove(cell)
            for value, width in zip(values, widths):
                cell = copy.deepcopy(proto)
                tc_pr = cell.find(qn("w:tcPr"))
                tcw = tc_pr.find(qn("w:tcW"))
                if tcw is None:
                    tcw = parse_xml(f'<w:tcW {_W} w:w="{width}" w:type="dxa"/>')
                    tc_pr.append(tcw)
                tcw.set(qn("w:w"), str(width))
                paragraph = cell.find(qn("w:p"))
                set_paragraph_text(paragraph, value)
                jc = paragraph.find(qn("w:pPr")).find(qn("w:jc"))
                if not header and jc is not None:
                    jc.getparent().remove(jc)
                row.append(cell)
            tr_pr = row.find(qn("w:trPr"))
            if tr_pr is not None:
                height = tr_pr.find(qn("w:trHeight"))
                if height is not None:
                    tr_pr.remove(height)
                if header:
                    hdr = tr_pr.find(qn("w:tblHeader"))
                    if hdr is not None:
                        hdr.attrib.pop(qn("w:val"), None)
            return row

        tbl.append(build_row(head_row, headers, True))
        for values in rows:
            tbl.append(build_row(data_row, values, False))
        self._append(tbl)
        self.para("")


# ---------------------------------------------------------------------------
# Front matter edits
# ---------------------------------------------------------------------------


def update_front_matter(document) -> None:
    title = find_block(document, "Student Workbook")
    set_paragraph_text(title, "Student Lab Guide")
    subtitle = copy.deepcopy(title)
    set_paragraph_text(subtitle, "Automated Performance and Configuration Analysis")
    title.addprevious(subtitle)
    date = find_block(document, "June 2024")
    set_paragraph_text(date, GUIDE_DATE)

    revisions = find_block(document, "Release Date", "w:tbl")
    rows = revisions.findall(qn("w:tr"))
    entries = [
        ("September 28, 2026", "0.1", "Master Class team", "Initial lab guide draft."),
        (
            GUIDE_DATE,
            GUIDE_VERSION,
            "Master Class team",
            "Screenshots and the current Workbench workflow.",
        ),
    ]
    for row, values in zip(rows[1:], entries):
        for cell, value in zip(row.findall(qn("w:tc")), values):
            set_paragraph_text(cell.find(qn("w:p")), value)
    for row in rows[1 + len(entries) :]:
        for cell in row.findall(qn("w:tc")):
            set_paragraph_text(cell.find(qn("w:p")), "")


def drop_template_exercises(document) -> None:
    # The cover paragraph also starts with "BigFix Master Class", so anchor
    # on the first Heading 1 with exactly that text.
    start = None
    for block in body_blocks(document):
        if block.tag != qn("w:p"):
            continue
        ppr = block.find(qn("w:pPr"))
        style = ppr.find(qn("w:pStyle")) if ppr is not None else None
        if (
            style is not None
            and style.get(qn("w:val")) == "Heading1"
            and block_text(block) == "BigFix Master Class"
        ):
            start = block
            break
    if start is None:
        raise LookupError("template Heading 1 'BigFix Master Class' not found")
    body = document.element.body
    removing = False
    for child in list(body):
        if child is start:
            removing = True
        if child.tag == qn("w:sectPr"):
            continue
        if removing:
            body.remove(child)


# ---------------------------------------------------------------------------
# Content
# ---------------------------------------------------------------------------

MODULE_TABLE = [
    [
        "Agent Performance",
        "BigFix Master Class -- Agent Performance Counters - Basic (2.0) analysis and "
        "BigFix Master Class -- Collect Agent Performance Counter Analysis Data (2.0) task",
        "Client_Loop XML or CSV. Optional Top 10, UDP, and Deployment_Information captures.",
    ],
    [
        "Perfmon",
        "BigFix Master Class -- Setup and Run Perfmon Counters (2.0)",
        "The Perfmon .blg file from every targeted server.",
    ],
    [
        "FillDB",
        "BigFix Master Class -- Enable FillDB Performance Logging (2.0)",
        "FillDBPerf.log and its rollover files after logging is disabled.",
    ],
]

CLIENT_SETTING_TASKS = [
    "BigFix Master Class -- Enable Client FastHashVerify Setting (Default - 25% Single Core) (1.0)",
    "BigFix Master Class -- Set CPU Utilization to 2% on Multi-Core Systems (1.0)",
    "BigFix Master Class -- Set CPU Utilization to 20% (Single Core) (1.0)",
    "BigFix Master Class -- Set Command Polling to 10 Minutes over Average Evaluation Time (1.0)",
]


def write_content(g: Guide) -> None:
    g.heading1("BigFix Master Class")
    g.heading1("Student exercises")

    g.heading2("Overview")
    g.para(
        "This lab introduces the BigFix Master Class Diagnostics Workbench. You collect "
        "operational data from a BigFix deployment with a collection task, run the "
        "matching Workbench module, and read the Mini Report it produces."
    )
    g.para("In this lab you will learn how to:")
    g.bullets(
        [
            "Connect a BigFix collection task to the data a Workbench module needs.",
            "Run the Agent Performance and Perfmon exercises on their own.",
            "Run the optional FillDB exercise when the session schedule allows.",
            "Recognize the main evidence and measurements in a Mini Report.",
        ]
    )
    g.para(
        "The three modules run one at a time. The core path is Agent Performance "
        "followed by Perfmon. FillDB is an optional third exercise. Each module "
        "writes a Mini Report, an Infographic, and for two of the modules an Excel "
        "workbook."
    )
    g.note(
        "The Mini Report is the primary artifact of this class. The Workbench has no "
        "full report mode and no scoring workbook."
    )

    g.heading2("Before you begin")
    g.para("You need the following:")
    g.bullets(
        [
            f"Access to the lab BigFix console and the custom site {SITE}.",
            "An instructor-provided BigFix account for actions that need operator permissions.",
            "The Diagnostics Workbench project folder and a writable output folder.",
            "A Windows 10 or 11 workstation with Python 3.12 or newer, Microsoft Edge or "
            "Google Chrome, and Microsoft Word and Excel.",
            "A folder for collected data. Use the instructor-provided sanitized capture "
            "when live collection takes longer than the class session.",
        ]
    )
    g.note(
        "Microsoft Word and Excel are the preferred and tested applications for the "
        "Mini Reports and workbooks. LibreOffice and other compatible applications may "
        "work, but they have not been fully vetted."
    )

    g.heading2("Shared collection workflow")
    g.para(
        f"The collection tasks are in the {SITE} site. Each exercise follows the same "
        "pattern. Prepare the required analysis or service, run the collection task, "
        "retrieve the files, and place them in the Workbench data folder."
    )
    g.table(
        ["Module", "BigFix content", "Data to retrieve"],
        MODULE_TABLE,
        [1700, 4600, 3700],
    )
    g.para("Put the files for one deployment under one data folder:")
    g.code(
        [
            "<Data Folder>\\",
            "    Client_Loop\\              Agent Performance export and optional captures",
            "    Deployment_Information\\   Optional root server information captures",
            "    Perfmon\\                  One or two Perfmon .blg captures",
            "    FillDB_Performance\\       FillDB performance logs or the analyzer CSV",
        ]
    )
    g.para("")
    g.important(
        "Perfmon logs are large and are retrieved directly from the target machines. "
        "They are not uploaded by the collection task."
    )

    # Exercise 1 --------------------------------------------------------
    g.heading2("Exercise 1: Client Performance Loop Analysis")
    g.para(
        "In this exercise, you collect client evaluation loop data and use the "
        "Workbench to review evaluation time, expensive evaluations, command polling, "
        "UDP coverage, and FastHashVerify settings."
    )
    g.label("BigFix collection")
    g.steps(
        restart=True,
        items=[
            f"In the BigFix console, open the {SITE} site.",
            "Activate BigFix Master Class -- Agent Performance Counters - Basic (2.0). "
            "If it is already active and reporting, continue. Allow 24 to 48 hours of "
            "reporting before you collect.",
        ],
    )
    g.picture("lg-task-01-agent-performance-analysis.png", TASK_IMAGE_WIDTH)
    g.steps(
        [
            "Run BigFix Master Class -- Collect Agent Performance Counter Analysis Data "
            "(2.0) against the root server. Use the instructor-provided account when the "
            "task asks for API credentials. Do not place credentials in this guide or in "
            "the collected files.",
        ]
    )
    g.picture("lg-task-02-collect-agent-performance.png", TASK_IMAGE_WIDTH)
    g.steps(
        [
            "Wait for the action to complete and retrieve the Client_Loop XML or CSV. "
            "Retrieve the optional Top 10, UDP, and Deployment_Information captures when "
            "they are present.",
            "Place the files under Client_Loop and Deployment_Information in your data folder.",
        ]
    )
    g.note(
        "The primary file is named Client_Loop_<date>_<time>.xml or .csv. The task can "
        "also produce top10-query-results.csv and udp-notification-results.csv."
    )
    g.label("Run the Workbench")
    g.steps(
        restart=True,
        items=[
            "Open Launchers and run Run Diagnostics Workbench.cmd. The first run creates "
            "the private Python environment, which takes about a minute.",
            "On Folders, set Data Folder to your data folder. The Workbench scans it and "
            "reports how many modules found their input.",
        ],
    )
    g.picture("lg-02-step-1-folders-scanned.png")
    g.steps(
        [
            "Set Output Folder and enter a Run Name that identifies your lab run. The "
            "run name prefixes every output file.",
            "Click Next. On Modules, click Clear and then tick Client Performance Loop "
            "Analysis only.",
        ]
    )
    g.picture("lg-03-step-2-modules.png")
    g.steps(
        [
            "Click Details. Confirm the loop export and the optional captures. Enter the "
            "Report Start Date and Report End Date for the collection period.",
        ]
    )
    g.picture("lg-04-step-2-loop-details.png")
    g.steps(
        [
            "Click Next. Check the Run Details strip and click Build. The module status "
            "moves from Queued to Running to Done.",
        ]
    )
    g.picture("lg-05-step-3-build.png")
    g.steps(
        [
            "When the status is Done, click Open Output and open the Mini Report in the "
            "Client_Loop folder.",
        ]
    )
    g.label("Review the result")
    g.picture("lg-out-loop-mini-report-p1.png", TASK_IMAGE_WIDTH)
    g.bullets(
        [
            "Compare the maximum and average evaluation cycle times.",
            "Review the Top 10 evaluation table when the optional capture was collected.",
            "Review command polling and UDP coverage when the optional UDP capture was collected.",
            "Review the FastHashVerify enabled, work, and sleep values. These settings "
            "matter when large patch or software update files are common.",
            "Record one observation from the Mini Report that you would investigate next.",
        ]
    )
    g.para(
        f"The {SITE} site also holds four client setting tasks that act on what this "
        "Mini Report shows. They are not part of this exercise. Use them only when the "
        "review points to a setting change:"
    )
    g.bullets(CLIENT_SETTING_TASKS)
    g.done(1)

    # Exercise 2 --------------------------------------------------------
    g.heading2("Exercise 2: Perfmon Infrastructure Analysis")
    g.para(
        "In this exercise, you capture Windows performance counters from the BigFix "
        "role servers in scope and use the Workbench to review processor, memory, "
        "disk, and network behavior against the platform requirements."
    )
    g.label("BigFix collection")
    g.steps(
        restart=True,
        items=[
            f"In the BigFix console, open the {SITE} site.",
            "Run BigFix Master Class -- Setup and Run Perfmon Counters (2.0) separately "
            "against each Windows role server in scope. Include the SQL Server host when "
            "the instructor has selected it.",
        ],
    )
    g.picture("lg-task-03-setup-perfmon.png", TASK_IMAGE_WIDTH)
    g.steps(
        [
            "Allow the counter set to run for the collection window. The task starts the "
            "BFPerf counter set and writes a README beside the results.",
            "When the capture is complete, stop BFPerf with the command in the generated "
            "README, or use the approved disable procedure for the lab environment.",
            "Retrieve the .blg file directly from every targeted machine. Keep the files "
            "separate and identify each server clearly.",
            "Place one or two .blg files under Perfmon in your data folder.",
        ]
    )
    g.note(
        "Perfmon logs are expected to be 256 MB or larger. The task does not upload "
        "them. Copy them by hand."
    )
    g.label("Run the Workbench")
    g.steps(
        restart=True,
        items=[
            "Open the Workbench and set Data Folder, Output Folder, and Run Name as in "
            "Exercise 1.",
            "On Modules, click Clear and then tick Perfmon Infrastructure Analysis only.",
            "Click Details. Confirm Capture 1. The CPUs and Disks values are detected from "
            "the capture. Enter RAM in GB and tick Virtual machine when the server is a "
            "VM. Add Capture 2 when a comparison is part of the exercise.",
        ],
    )
    g.picture("lg-04-step-2-perfmon-details.png")
    g.steps(
        [
            "Click Next and click Build. Parsing a large capture can take several minutes.",
            "When the status is Done, click Open Output. The Perfmon folder holds the Mini "
            "Report, the Excel workbook, and a _Perfmon_Charts folder with the scorecard "
            "Infographic and one chart per counter.",
        ]
    )
    g.label("Review the result")
    g.picture("lg-out-perfmon-mini-report-p1.png", TASK_IMAGE_WIDTH)
    g.bullets(
        [
            "Review the overall infrastructure result and the supporting counter observations.",
            "Identify one resource pattern that deserves a closer look.",
            "Compare two captures when a second server or a before and after capture is available.",
        ]
    )
    g.done(2)

    # Exercise 3 --------------------------------------------------------
    g.heading2("Exercise 3: FillDB Performance Analysis (optional)")
    g.para(
        "In this exercise, you collect FillDB performance logging from the root server "
        "and use the Workbench to review how quickly client reports are processed."
    )
    g.label("BigFix collection")
    g.steps(
        restart=True,
        items=[
            f"In the BigFix console, open the {SITE} site.",
            "Run BigFix Master Class -- Enable FillDB Performance Logging (2.0) against "
            "the root server. Use the default automatic disable window unless the "
            "instructor specifies another duration.",
        ],
    )
    g.picture("lg-task-04-enable-filldb-logging.png", TASK_IMAGE_WIDTH)
    g.steps(
        [
            "After the collection window, wait for logging to be disabled and retrieve "
            "FillDBPerf.log plus any rollover files from the root server.",
            "If automatic disabling was not selected, run the companion warning task or "
            "the approved disable procedure before you retrieve the log set.",
            "Place the logs, or the instructor-provided analyzer CSV, under "
            "FillDB_Performance in your data folder.",
        ]
    )
    g.important(
        "The log set must be complete and no longer active before analysis. Keep the "
        "rollover files together with FillDBPerf.log."
    )
    g.label("Run the Workbench")
    g.steps(
        restart=True,
        items=[
            "Open the Workbench and set Data Folder, Output Folder, and Run Name as in "
            "Exercise 1.",
            "On Modules, click Clear and then tick FillDB Performance Analysis only.",
            "Click Details and confirm the log. The collection dates are optional. The "
            "log span is used when they are left blank.",
        ],
    )
    g.picture("lg-04-step-2-filldb-details.png")
    g.steps(
        [
            "Click Next and click Build.",
            "When the status is Done, click Open Output and open the Mini Report and the "
            "Infographic in the FillDB_Performance folder.",
        ]
    )
    g.label("Review the result")
    g.picture("lg-out-filldb-mini-report-p1.png", TASK_IMAGE_WIDTH)
    g.bullets(
        [
            "Review the processing time summary and any objects that stand out.",
            "Connect the result to the collection window and the deployment activity at that time.",
        ]
    )
    g.done(3)

    # Reading the Mini Report --------------------------------------------
    g.heading2("Reading the Mini Report")
    g.para(
        "Each Mini Report is the narrative result for one module. Start with the score "
        "at the top, then use the supporting tables and charts to understand the "
        "evidence behind it."
    )
    g.bullets(
        [
            "Confirm the report identifies the intended run and data window.",
            "Read the score or status together with the supporting measurements.",
            "Use the detailed tables to trace an observation back to the collected data.",
            "Write down one evidence-based next question. The lab is about interpreting "
            "operational data, not about making an untested configuration change.",
        ]
    )
    g.picture("lg-out-loop-mini-report-p2.png", TASK_IMAGE_WIDTH)
    g.para(
        "The Infographic is the one page visual of the same result. The Excel "
        "workbook, where a module writes one, carries the source data and the per "
        "item detail."
    )
    g.picture("lg-out-loop-infographic.png", TASK_IMAGE_WIDTH)

    g.heading2("Completion checklist")
    g.table(
        ["Exercise", "Collection complete", "Data retrieved", "Mini Report reviewed"],
        [
            ["Agent Performance", "[ ]", "[ ]", "[ ]"],
            ["Perfmon", "[ ]", "[ ]", "[ ]"],
            ["FillDB (optional)", "[ ]", "[ ]", "[ ]"],
        ],
        [3000, 2300, 2300, 2400],
    )

    g.heading2("Troubleshooting")
    g.table(
        ["Symptom", "What to check"],
        [
            [
                "The Workbench shows Needs A File",
                "Confirm the folder layout and the file names. Open Details and choose the "
                "file with Change.",
            ],
            [
                "The Workbench shows Needs Review",
                "The input was found but a required value is blank. Open Details and fill "
                "in the dates or the RAM value.",
            ],
            [
                "Agent Performance data is missing",
                "Confirm the Basic analysis is active and reporting, then confirm the "
                "collection task completed on the root server.",
            ],
            [
                "Perfmon data is missing",
                "Confirm the .blg was copied from the target machine and is under the "
                "Perfmon folder. The counter set must be stopped first.",
            ],
            [
                "The build reports a failed module",
                "Open View Logs. The log names the input and the reason.",
            ],
            [
                "No Infographic was written",
                "The Workbench needs Edge or Chrome installed to render it. The Mini "
                "Report is still produced.",
            ],
            [
                "The app does not start after a Python upgrade",
                "Delete the .venv folder and run the launcher again.",
            ],
        ],
        [3400, 6600],
    )
    g.para("End of lab guide")


# ---------------------------------------------------------------------------


def build(output: Path = OUTPUT) -> Path:
    if not TEMPLATE.is_file():
        raise FileNotFoundError(TEMPLATE)
    document = Document(str(TEMPLATE))
    update_front_matter(document)
    # Collect the exemplar paragraphs before the template's exercises go.
    guide = Guide(document)
    drop_template_exercises(document)
    write_content(guide)
    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return output


def refresh_contents(path: Path) -> None:
    powershell = shutil.which("powershell")
    if powershell is None or not CONTENTS_SCRIPT.is_file():
        print("Contents not refreshed: open the guide in Word and update the field.")
        return
    subprocess.run(
        [
            powershell,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(CONTENTS_SCRIPT),
            "-DocPath",
            str(path),
        ],
        check=True,
    )


def main() -> int:
    path = build()
    print(f"Wrote {path}")
    refresh_contents(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
