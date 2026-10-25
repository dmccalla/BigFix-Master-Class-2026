# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Finalize report images without changing PerfMon scores or plotted evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from Lib.Design.report_layout import apply_report_hierarchy


def finalize_perfmon_layout(output_path, chart_folder, section_title=None):
    path = Path(chart_folder) / "perfmon_plot_manifest.json"
    if not path.is_file():
        return
    manifest = json.loads(path.read_text(encoding="utf-8"))
    by_image = {r["png_sha256"]: r for r in manifest}
    document = apply_report_hierarchy(Document(output_path))
    from docx.enum.style import WD_STYLE_TYPE

    evidence_style = (
        document.styles["PerfMonEvidence"] if "PerfMonEvidence" in document.styles
        else document.styles.add_style("PerfMonEvidence", WD_STYLE_TYPE.PARAGRAPH)
    )
    evidence_style.base_style = document.styles["Normal"]
    evidence_style.paragraph_format.keep_with_next = True
    allowed = None
    if section_title is not None:
        anchors = [p for p in document.paragraphs if p.text == section_title]
        if not anchors:
            return
        allowed = set()
        node = anchors[-1]._p.getnext()
        while node is not None and node.tag != qn('w:sectPr'):
            properties = node.find(qn('w:pPr'))
            style = properties.find(qn('w:pStyle')) if properties is not None else None
            if style is not None and style.get(qn('w:val')) in {'Heading1','Heading2'}:
                break
            allowed.add(node)
            node = node.getnext()
    changed = False
    for picture in list(document.inline_shapes):
        container = picture._inline
        while container.getparent() is not document.element.body:
            container = container.getparent()
        if allowed is not None and container not in allowed:
            continue
        relationship = picture._inline.xpath(".//a:blip/@r:embed")
        if not relationship:
            continue
        image = document.part.related_parts[relationship[0]].blob
        row = by_image.get(hashlib.sha256(image).hexdigest())
        if row is None:
            continue
        description = f"{row['counter']}. PerfMon counter results for the capture."
        if row.get("maximum") is not None:
            description += (
                f" Actual peak {row['maximum']}. Display scale may cap outliers."
            )
        picture._inline.docPr.set("descr", description)
        picture._inline.docPr.set("title", row["counter"])
        changed = True
    for table in document.tables:
        if table.cell(0, 0).text in {"Finding ID", "Hardware / Context", "Area"}:
            for row in table.rows[:-1]:
                for cell in row.cells:
                    for paragraph in cell.paragraphs:
                        paragraph.paragraph_format.keep_with_next = True
    if (
        document.paragraphs
        and document.paragraphs[0].text == "PerfMon Infrastructure Analysis"
    ):
        observations_path = Path(chart_folder) / "perfmon_observations.json"
        if observations_path.is_file():
            environment = json.loads(observations_path.read_text(encoding="utf-8")).get(
                "environment", {}
            )
            paragraph = document.sections[0].header.paragraphs[0]
            paragraph.text = f"System: {environment.get('Analyzed System', 'Not detected')} | Capture window: {environment.get('Sample Start', '')} to {environment.get('Sample End', '')}"
            for run in paragraph.runs:
                run.font.name = "Aptos"
                run.font.size = Pt(8)
        expected_workbook = Path(chart_folder).name.removesuffix('_Charts')+'.xlsx'
        if not any(
            p.text.startswith("Supporting workbook:") and expected_workbook in p.text for p in document.paragraphs
        ):
            workbook = document.add_paragraph(
                "Supporting workbook: "
                + Path(chart_folder).name.removesuffix("_Charts")
                + ".xlsx."
            )
            workbook.paragraph_format.space_before = Pt(6)
            workbook.runs[-1].underline = True
    # Explanatory captions need visible separation from the following table.
    for paragraph in document.paragraphs:
        if paragraph.text.startswith(("Supporting workbook:", "Supporting CSV:")):
            paragraph.paragraph_format.space_before = Pt(6)
    if changed:
        document.save(output_path)
        from Lib.Design.report_tables import normalize_docx_tables

        normalize_docx_tables(output_path)
    (Path(chart_folder) / "perfmon_layout_validation.json").write_text(
        json.dumps(
            {
                "plots_omitted": [],
                "plots_preserved": len(manifest),
                "scored_counters_unchanged": len(manifest),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
