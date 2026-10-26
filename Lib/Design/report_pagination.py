# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Keep report evidence groups together without changing their content."""

from __future__ import annotations

import re

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt
from docx.text.paragraph import Paragraph


def _text(node):
    return "".join(element.text or "" for element in node.iter(qn("w:t")))


def _heading(node):
    properties = node.find(qn("w:pPr"))
    style = properties.find(qn("w:pStyle")) if properties is not None else None
    return style is not None and style.get(qn("w:val"), "").startswith("Heading")


def _row_group(rows, document):
    """Join only the supplied rows; the last row ends the keep chain."""
    for index, row in enumerate(rows):
        properties = row.find(qn("w:trPr"))
        if properties is None:
            properties = OxmlElement("w:trPr")
            row.insert(0, properties)
        if properties.find(qn("w:cantSplit")) is None:
            properties.insert(0, OxmlElement("w:cantSplit"))
        for node in row.iter(qn("w:p")):
            paragraph = Paragraph(node, document)
            paragraph.paragraph_format.keep_together = True
            paragraph.paragraph_format.keep_with_next = index < len(rows) - 1


def apply_report_pagination(document):
    """Apply the scoped D-item grouping rules to full and standalone output."""
    _paginate_body(document.element.body, document)
    return document


def paginate_document_xml(root):
    """Apply the same rules at the shared saved-report finalization point."""
    from docx.oxml import parse_xml
    from lxml import etree

    body = root.find(qn("w:body"))
    if body is None:
        return False
    before = etree.tostring(body)
    parsed = parse_xml(before)
    _paginate_body(parsed)
    if etree.tostring(parsed) == before:
        return False
    root.replace(body, parsed)
    return True


def _paginate_body(body, document=None):
    for table in list(body.iter(qn("w:tbl"))):
        properties = table.find(qn("w:tblPr"))
        style = properties.find(qn("w:tblStyle")) if properties is not None else None
        if style is None or style.get(qn("w:val")) != "BigFixContent":
            continue
        rows = table.findall(qn("w:tr"))
        if not rows:
            continue
        headers = [_text(cell).strip() for cell in rows[0].findall(qn("w:tc"))]
        if headers == ["Source ID", "Description", "Impact", "Suggested Remediation"]:
            while (
                len(rows) > 1
                and not _text(rows[-1]).strip()
                and not rows[-1].xpath(
                    ".//w:drawing|.//w:pict|.//w:fldSimple|.//w:instrText|.//w:vMerge"
                )
            ):
                table.remove(rows.pop())
        # These are the specific opening-table splits in D4. Large findings
        # and inventory tables retain their existing pagination rules.
        starts = {
            ("Infographic tile", "Value", "What it means"),
            ("FillDB Object", "Count", "Time (ms)", "Rate/s", "Health Check"),
            ("Hardware / Context", "Value / Source"),
            ("Setting Name", "Value", "Number of Machines"),
        }
        if tuple(headers) in starts and len(rows) >= 3:
            _row_group(rows[:3], document)
        if (
            headers == ["Resource", "Required", "Observed", "Short by", "Basis"]
            and len(rows) == 4
        ):
            _row_group(rows, document)
            previous = table.getprevious()
            for _ in range(3):
                if previous is None or previous.tag != qn("w:p"):
                    break
                Paragraph(previous, document).paragraph_format.keep_with_next = True
                previous = previous.getprevious()
        if (
            headers
            == ["Host", "Roles", "Cores", "RAM", "Storage", "Platform", "Source"]
            and len(rows) <= 6
        ):
            _row_group(rows, document)
        if (
            headers == ["Section", "Passed", "Warning", "Failed", "Total"]
            and len(rows) >= 3
        ):
            if _text(rows[-1].find(qn("w:tc"))).strip().upper() == "TOTAL":
                _row_group(rows[-2:], document)

    nodes = list(body)
    for index, node in enumerate(nodes):
        text = _text(node).strip()
        if node.tag == qn("w:p"):
            paragraph = Paragraph(node, document)
            if text == "Technical Evidence" and _heading(node):
                label = node.getprevious()
                if label is not None and _text(label).strip() == "SECTION 08":
                    previous = label.getprevious()
                    while (
                        previous is not None
                        and previous.tag == qn("w:p")
                        and not _text(previous).strip()
                        and not previous.xpath(".//w:drawing|.//w:pict|.//w:sectPr")
                    ):
                        before = previous.getprevious()
                        body.remove(previous)
                        previous = before
                    Paragraph(label, document).paragraph_format.page_break_before = True
                    paragraph.paragraph_format.page_break_before = False
            if "/* Property Name */" in text and '"Single Property"' in text:
                from docx.enum.text import WD_ALIGN_PARAGRAPH

                paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
            if text.startswith("Detail:") or text.startswith("Standard:"):
                paragraph.paragraph_format.keep_with_next = True
                paragraph.paragraph_format.keep_together = True
            if re.match(r"^[^A-Za-z]*Observation:", text):
                paragraph.paragraph_format.keep_with_next = False
                paragraph.paragraph_format.keep_together = True
            if text == "Capture Summary":
                for following in nodes[index + 1 :]:
                    if following.tag != qn("w:p") or _heading(following):
                        break
                    Paragraph(
                        following, document
                    ).paragraph_format.keep_with_next = True
            if text == "Optimal Performance Targets":
                bullets = []
                for following in nodes[index + 1 : index + 4]:
                    if (
                        following.tag != qn("w:p")
                        or _heading(following)
                        or not _text(following).strip()
                    ):
                        break
                    bullets.append(following)
                if len(bullets) == 3:
                    for number, bullet in enumerate(bullets):
                        fmt = Paragraph(bullet, document).paragraph_format
                        fmt.keep_together = True
                        fmt.keep_with_next = number < 2
            if text == "How This Score Is Calculated":
                for following in nodes[index + 1 :]:
                    if (
                        following.tag != qn("w:p")
                        or _heading(following)
                        or following.xpath(".//w:drawing|.//w:pict")
                    ):
                        break
                    Paragraph(following, document).paragraph_format.space_after = Pt(4)
            if text == "Evaluation Frequency":
                for following in nodes[index + 1 :]:
                    if _heading(following):
                        break
                    if following.tag == qn("w:p") and following.xpath(".//w:drawing"):
                        Paragraph(
                            following, document
                        ).paragraph_format.keep_with_next = False
                        break
        if (
            "UDP coverage uses the records in the UDP capture" in text
            and node.tag == qn("w:tbl")
        ):
            previous = node.getprevious()
            while (
                previous is not None
                and previous.tag == qn("w:p")
                and not _text(previous).strip()
                and not previous.xpath(".//w:drawing|.//w:pict|.//w:sectPr")
            ):
                previous = previous.getprevious()
            if (
                previous is not None
                and previous.tag == qn("w:p")
                and previous.xpath(".//w:drawing")
            ):
                cursor = previous
                while cursor is not node:
                    Paragraph(cursor, document).paragraph_format.keep_with_next = True
                    cursor = cursor.getnext()
    # The query lives inside the TIP callout's cell in both report forms.
    for node in body.iter(qn("w:p")):
        text = _text(node)
        if "/* Property Name */" in text and '"Single Property"' in text:
            from docx.enum.text import WD_ALIGN_PARAGRAPH

            Paragraph(node, document).alignment = WD_ALIGN_PARAGRAPH.LEFT

    # Word requires a final paragraph after an ending table. Keep that empty
    # marker small so it cannot create a page containing only the footer.
    last = body[-2] if len(body) > 1 and body[-1].tag == qn("w:sectPr") else body[-1]
    if (
        last.tag == qn("w:p")
        and not _text(last).strip()
        and not last.xpath(
            ".//w:drawing|.//w:pict|.//w:sectPr|.//w:fldSimple|.//w:instrText"
        )
    ):
        previous = last.getprevious()
        if previous is not None and previous.tag == qn("w:tbl"):
            fmt = Paragraph(last, document).paragraph_format
            fmt.space_before = Pt(0)
            fmt.space_after = Pt(0)
            fmt.line_spacing = Pt(1)
            fmt.keep_with_next = False
