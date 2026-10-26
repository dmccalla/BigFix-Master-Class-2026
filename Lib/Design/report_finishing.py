# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Finish the approved cover, callouts and short report guidance blocks."""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph

NOTE_SYMBOL = "[i]"
TIP_SYMBOL = "[?]"


def _text(node):
    return "".join(part.text or "" for part in node.iter(qn("w:t")))


def _style(node):
    properties = node.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    return style.get(qn("w:val"), "") if style is not None else ""


def _cover(table):
    rows = table.findall(qn("w:tr"))
    if not rows:
        return
    headers = [_text(cell).strip().casefold() for cell in rows[0].findall(qn("w:tc"))]
    if headers != ["prepared for", "report version"]:
        return
    widths = (2000, 2400)
    properties = table.find(qn("w:tblPr"))
    width = properties.find(qn("w:tblW"))
    width.set(qn("w:w"), str(sum(widths)))
    width.set(qn("w:type"), "dxa")
    grid = table.find(qn("w:tblGrid"))
    for column, size in zip(grid, widths, strict=True):
        column.set(qn("w:w"), str(size))
    for row in rows:
        for cell, size in zip(row.findall(qn("w:tc")), widths, strict=True):
            cell.find(qn("w:tcPr")).find(qn("w:tcW")).set(qn("w:w"), str(size))


def _method_paragraph(node, text):
    paragraph = Paragraph(node, None)
    paragraph.text = text
    paragraph_properties = node.get_or_add_pPr()
    numbering = paragraph_properties.find(qn("w:numPr"))
    if numbering is not None:
        paragraph_properties.remove(numbering)
    style = paragraph_properties.find(qn("w:pStyle"))
    if style is None:
        style = OxmlElement("w:pStyle")
        paragraph_properties.insert(0, style)
    style.set(qn("w:val"), "Normal")
    paragraph.paragraph_format.left_indent = Pt(28)
    paragraph.paragraph_format.first_line_indent = Pt(0)
    paragraph.paragraph_format.space_after = Pt(4)
    paragraph.paragraph_format.keep_together = True
    for run in paragraph.runs:
        run.bold = False
    return paragraph


def _methods(body):
    for node in list(body.iter(qn("w:p"))):
        text = _text(node).strip()
        if not text.startswith("Identify expensive content.") or "(1) " not in text:
            continue
        following = node.getnext()
        if (
            following is None
            or following.tag != qn("w:p")
            or not _text(following).strip().startswith("(2) ")
        ):
            continue
        prefix, first = text.split("(1) ", 1)
        paragraph = Paragraph(node, None)
        paragraph.clear()
        paragraph.add_run("Identify expensive content.").bold = True
        paragraph.add_run(prefix[len("Identify expensive content.") :].rstrip())
        paragraph.paragraph_format.keep_with_next = True
        method = OxmlElement("w:p")
        node.addnext(method)
        _method_paragraph(method, "(1) " + first).paragraph_format.keep_with_next = True
        _method_paragraph(
            following, _text(following).strip()
        ).paragraph_format.keep_with_next = False


def _icons(body):
    for run in body.iter(qn("w:r")):
        parts = list(run.iter(qn("w:t")))
        text = "".join(part.text or "" for part in parts)
        if "\U0001f4dd" not in text and "\U0001f4a1" not in text:
            continue
        kind = "NOTE" if "\U0001f4dd" in text else "TIP"
        for part in parts:
            part.text = (
                (part.text or "")
                .replace("\U0001f4dd", NOTE_SYMBOL)
                .replace("\U0001f4a1", TIP_SYMBOL)
            )
        properties = run.get_or_add_rPr()
        fonts = properties.get_or_add_rFonts()
        for key in ("ascii", "hAnsi", "cs", "eastAsia"):
            fonts.set(qn("w:" + key), "Aptos")
        for key in tuple(fonts.attrib):
            if key.endswith("Theme"):
                del fonts.attrib[key]
        properties.get_or_add_b().set(qn("w:val"), "1")
        properties.get_or_add_sz().set(qn("w:val"), "24")
        color = properties.get_or_add_color()
        color.set(qn("w:val"), "17707F" if kind == "NOTE" else "065F46")


def _compact_sections(body):
    in_methodology = False
    headings = [_text(node).strip() for node in body if _style(node) == "Heading1"]
    release_mini = headings[:1] == ["Release Intelligence Mini Report"]
    for node in body:
        if node.tag != qn("w:p"):
            continue
        paragraph = Paragraph(node, None)
        text = _text(node).strip()
        style = _style(node)
        if style == "Heading1":
            in_methodology = text == "Methodology"
        if release_mini and style in {"Heading2", "Heading3"}:
            paragraph.paragraph_format.space_before = Pt(8)
            paragraph.paragraph_format.space_after = Pt(4)
        if in_methodology and style == "Heading2":
            paragraph.paragraph_format.space_before = Pt(4)
            paragraph.paragraph_format.space_after = Pt(2)
        elif in_methodology and text and not style.startswith("Heading"):
            paragraph.paragraph_format.space_before = Pt(0)
            paragraph.paragraph_format.space_after = Pt(0)


def finish_report_body(body):
    """Preserve report wording while applying the remaining D-item formatting."""
    for table in body.iter(qn("w:tbl")):
        _cover(table)
    _methods(body)
    _icons(body)
    _compact_sections(body)
