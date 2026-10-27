# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Shared Word hierarchy and explanatory callouts for report modules."""

from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor


def _ensure_bullet_style(document):
    """Use a template-owned numbering definition that survives body injection."""
    from docx.enum.style import WD_STYLE_TYPE

    numbering = document.part.numbering_part.element
    abstract_ids = [
        int(e.get(qn("w:abstractNumId"))) for e in numbering.findall(qn("w:abstractNum"))
    ]
    num_ids = [int(e.get(qn("w:numId"))) for e in numbering.findall(qn("w:num"))]
    if "ReportBullet" in document.styles:
        style = document.styles["ReportBullet"]
    else:
        style = document.styles.add_style("ReportBullet", WD_STYLE_TYPE.PARAGRAPH)
    properties = style.element.get_or_add_pPr()
    old = properties.find(qn("w:numPr"))
    old_id = old.find(qn("w:numId")) if old is not None else None
    num = next(
        (
            n
            for n in numbering.findall(qn("w:num"))
            if old_id is not None and n.get(qn("w:numId")) == old_id.get(qn("w:val"))
        ),
        None,
    )
    reference = num.find(qn("w:abstractNumId")) if num is not None else None
    abstract = next(
        (
            n
            for n in numbering.findall(qn("w:abstractNum"))
            if reference is not None
            and n.get(qn("w:abstractNumId")) == reference.get(qn("w:val"))
        ),
        None,
    )
    if abstract is None:
        abstract_id = max(abstract_ids, default=-1) + 1
        num_id = max(num_ids, default=0) + 1
        abstract = OxmlElement("w:abstractNum")
        abstract.set(qn("w:abstractNumId"), str(abstract_id))
        numbering.append(abstract)
        num = OxmlElement("w:num")
        num.set(qn("w:numId"), str(num_id))
        reference = OxmlElement("w:abstractNumId")
        reference.set(qn("w:val"), str(abstract_id))
        num.append(reference)
        numbering.append(num)
    num_id = num.get(qn("w:numId"))
    # OOXML requires all abstract definitions before concrete list instances.
    numbering.remove(abstract)
    first_instance = next(
        (i for i, node in enumerate(numbering) if node.tag == qn("w:num")),
        len(numbering),
    )
    numbering.insert(first_instance, abstract)
    # A real single-level bullet definition works in Word and other readers.
    # Style-only numbering without a level association is read inconsistently.
    for child in list(abstract):
        abstract.remove(child)
    kind = OxmlElement("w:multiLevelType")
    kind.set(qn("w:val"), "singleLevel")
    abstract.append(kind)
    level = OxmlElement("w:lvl")
    level.set(qn("w:ilvl"), "0")
    for tag, value in [
        ("start", "1"),
        ("numFmt", "bullet"),
        ("pStyle", "ReportBullet"),
        ("suff", "tab"),
        ("lvlText", "\u2022"),
        ("lvlJc", "left"),
    ]:
        child = OxmlElement("w:" + tag)
        child.set(qn("w:val"), value)
        level.append(child)
    abstract.append(level)
    paragraph_properties = OxmlElement("w:pPr")
    tabs = OxmlElement("w:tabs")
    tab = OxmlElement("w:tab")
    tab.set(qn("w:val"), "num")
    tab.set(qn("w:pos"), "280")
    tabs.append(tab)
    paragraph_properties.append(tabs)
    indent = OxmlElement("w:ind")
    indent.set(qn("w:left"), "280")
    indent.set(qn("w:hanging"), "200")
    paragraph_properties.append(indent)
    level.append(paragraph_properties)
    runs = OxmlElement("w:rPr")
    fonts = OxmlElement("w:rFonts")
    family = document.styles["Normal"].font.name or "Aptos"
    for key in ("ascii", "hAnsi", "cs", "eastAsia"):
        fonts.set(qn("w:" + key), family)
    runs.append(fonts)
    level.append(runs)
    style.base_style = document.styles["Normal"]
    style.paragraph_format.left_indent = Pt(14)
    style.paragraph_format.first_line_indent = Pt(-10)
    if old is not None:
        style.element.get_or_add_pPr().remove(old)
    properties = OxmlElement("w:numPr")
    for tag, value in [("ilvl", "0"), ("numId", str(num_id))]:
        child = OxmlElement("w:" + tag)
        child.set(qn("w:val"), value)
        properties.append(child)
    parent = style.element.get_or_add_pPr()
    preceding = {
        qn("w:" + name)
        for name in (
            "pStyle",
            "keepNext",
            "keepLines",
            "pageBreakBefore",
            "framePr",
            "widowControl",
        )
    }
    position = next(
        (i for i, child in enumerate(parent) if child.tag not in preceding), len(parent)
    )
    parent.insert(position, properties)


def add_bullet(document, text):
    """Add a real Word bullet with the shared template's numbering style."""
    _ensure_bullet_style(document)
    paragraph = document.add_paragraph(text, style="ReportBullet")
    bind_report_bullets(document)
    return paragraph


def bind_report_bullets(document):
    """Carry explicit list references through copied guidance and body injection."""
    _ensure_bullet_style(document)
    number = document.styles["ReportBullet"].element.find(qn("w:pPr")).find(qn("w:numPr"))
    from copy import deepcopy

    for paragraph in document.element.body.iter(qn("w:p")):
        properties = paragraph.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        if style is None or style.get(qn("w:val")) != "ReportBullet":
            continue
        previous = properties.find(qn("w:numPr"))
        if previous is not None:
            properties.remove(previous)
        before = {
            qn("w:" + name)
            for name in (
                "pStyle",
                "keepNext",
                "keepLines",
                "pageBreakBefore",
                "framePr",
                "widowControl",
            )
        }
        position = next(
            (i for i, child in enumerate(properties) if child.tag not in before),
            len(properties),
        )
        properties.insert(position, deepcopy(number))


def configure_heading_styles(document, *, client_mini=False):
    """Use one heading family and distinguish sections from compact subheadings."""
    # Preserve each template's font family and paragraph defaults. Standalone
    # distributions deliberately use their body family for headings as well.
    heading_family = document.styles["Heading 2"].font.name or "Aptos"
    specifications = [
        ("Heading 1", 28, heading_family, 0, 12),
        ("Heading 2", 24, heading_family, 20, 6),
        ("Heading 3", 20, heading_family, 20, 6),
        ("Heading 4", 14, heading_family, 16, 6),
        ("Heading 5", 11, heading_family, 10, 3),
    ]
    if client_mini:
        specifications[1] = ("Heading 2", 20, heading_family, 20, 6)
        specifications[2] = ("Heading 3", 14, heading_family, 16, 6)
    for name, points, family, before, after in specifications:
        style = document.styles[name]
        style.font.name = family
        style.font.size = Pt(points)
        style.font.bold = True
        style.font.italic = False
        style.font.color.rgb = RGBColor.from_string(
            "007A8A"
            if name == "Heading 4" or (client_mini and name == "Heading 3")
            else "000032"
        )
        fonts = style.element.get_or_add_rPr().find(qn("w:rFonts"))
        for key in list(fonts.attrib):
            del fonts.attrib[key]
        for key in ("ascii", "hAnsi", "cs", "eastAsia"):
            fonts.set(qn("w:" + key), family)
        for tag in ("sz", "szCs"):
            element = style.element.get_or_add_rPr().find(qn("w:" + tag))
            if element is None:
                element = OxmlElement("w:" + tag)
                style.element.get_or_add_rPr().append(element)
            element.set(qn("w:val"), str(points * 2))
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.keep_together = True
        ppr = style.element.get_or_add_pPr()
        old = ppr.find(qn("w:pBdr"))
        if old is not None:
            ppr.remove(old)
    configure_capacity_host_styles(document)
    compact_table_header_style(document)


def configure_capacity_host_styles(document):
    """Separate each server comparison without adding navigation headings or boxes."""
    from docx.enum.style import WD_STYLE_TYPE

    for name, points, bold, before, after in (
        ("Capacity Host", 12, True, 14, 2),
        ("Capacity Host Details", 11, False, 0, 4),
    ):
        style = (
            document.styles[name]
            if name in document.styles
            else document.styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
        )
        style.base_style = document.styles["Normal"]
        style.font.size = Pt(points)
        style.font.bold = bold
        style.font.italic = False
        style.font.color.rgb = RGBColor.from_string("000032")
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.line_spacing = 1
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.keep_together = True


def compact_table_header_style(document):
    """Let the shared table style provide compact, wrapped header rows."""
    from Lib.Design.report_tables import ensure_header_paragraph_style

    ensure_header_paragraph_style(document.styles.element)
    table_style = next(
        (style for style in document.styles if style.style_id == "BigFixContent"), None
    )
    if table_style is None:
        return
    style = table_style.element
    first = next(
        (
            node
            for node in style.findall(qn("w:tblStylePr"))
            if node.get(qn("w:type")) == "firstRow"
        ),
        None,
    )
    if first is None:
        return
    properties = first.find(qn("w:pPr"))
    if properties is None:
        properties = OxmlElement("w:pPr")
        first.insert(0, properties)
    spacing = properties.find(qn("w:spacing"))
    if spacing is None:
        spacing = OxmlElement("w:spacing")
        properties.append(spacing)
    for key, value in (
        ("before", "0"),
        ("after", "0"),
        ("line", "240"),
        ("lineRule", "auto"),
    ):
        spacing.set(qn("w:" + key), value)


def apply_report_hierarchy(document):
    """Keep real Word headings consistent in standalone and injected reports."""
    _ensure_bullet_style(document)
    configure_heading_styles(document)
    # Imported template runs must inherit the same sizes and spacing as the
    # generated headings. Keep chapter icon indents and bookmark anchors.
    for paragraph in document.element.body.iter(qn("w:p")):
        properties = paragraph.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        if style is None or style.get(qn("w:val")) not in {
            "Heading1",
            "Heading2",
            "Heading3",
            "Heading4",
            "Heading5",
        }:
            continue
        for tag in ("pBdr",):
            previous = properties.find(qn("w:" + tag))
            if previous is not None:
                properties.remove(previous)
    normalize_heading_typography(document)
    normalize_section_spacing(document)
    ensure_page_numbers(document)
    return document


def normalize_heading_typography(document):
    """Make heading text inherit its paragraph font, size and weight in Word."""
    headings = {f"Heading{level}" for level in range(1, 6)}
    for paragraph in document.element.body.iter(qn("w:p")):
        properties = paragraph.find(qn("w:pPr"))
        style = properties.find(qn("w:pStyle")) if properties is not None else None
        if style is None or style.get(qn("w:val")) not in headings:
            continue
        # Character styles such as Strong can toggle an already-bold heading
        # back to regular weight. Removing direct font tags alone is not enough.
        for run_properties in paragraph.xpath("./w:pPr/w:rPr|.//w:r/w:rPr"):
            for tag in (
                "rStyle",
                "rFonts",
                "sz",
                "szCs",
                "b",
                "bCs",
                "i",
                "iCs",
                "color",
            ):
                for previous in list(run_properties.findall(qn("w:" + tag))):
                    run_properties.remove(previous)


def normalize_section_spacing(document):
    """Let heading styles own section gaps without changing cover or table layout."""
    from docx.text.paragraph import Paragraph

    headings = {f"Heading{level}" for level in range(1, 6)}

    def heading_style(node):
        style = node.find(qn("w:pPr") + "/" + qn("w:pStyle"))
        return style.get(qn("w:val")) if style is not None else None

    def disposable_spacer(node):
        if node is None or node.tag != qn("w:p"):
            return False
        if "".join(node.xpath(".//w:t/text()")).strip():
            return False
        if node.xpath(
            ".//w:drawing|.//w:pict|.//w:object|.//w:br|.//w:sectPr"
            "|.//w:bookmarkStart|.//w:bookmarkEnd|.//w:fldChar|.//w:fldSimple"
            "|.//w:instrText|.//w:sdt|.//w:footnoteReference|.//w:endnoteReference"
            "|.//w:commentRangeStart|.//w:commentRangeEnd|.//w:sym|.//w:tab"
            "|.//w:lastRenderedPageBreak|./w:pPr/w:numPr|./w:pPr/w:pageBreakBefore"
        ):
            return False
        return True

    def adjacent(node, direction):
        """Follow paragraph flow through tagged guidance without flattening it."""
        candidate = getattr(node, direction)()
        container = node.getparent()
        while candidate is None and container is not None:
            if container.tag == qn("w:sdtContent"):
                container = container.getparent()
            if container is None or container.tag != qn("w:sdt"):
                break
            candidate = getattr(container, direction)()
            container = container.getparent()
        while candidate is not None and candidate.tag == qn("w:sdt"):
            content = candidate.find(qn("w:sdtContent"))
            if content is None or not len(content):
                break
            candidate = content[-1] if direction == "getprevious" else content[0]
        return candidate

    def remove_body_auto_spacing(node, side):
        if node is None or node.tag != qn("w:p"):
            return
        if (
            heading_style(node) in headings
            or not "".join(node.xpath(".//w:t/text()")).strip()
        ):
            return
        if node.xpath(".//w:drawing|.//w:pict|.//w:br|.//w:sectPr"):
            return
        spacing = node.get_or_add_pPr().get_or_add_spacing()
        spacing.set(qn("w:" + side), "0")
        spacing.set(qn("w:" + side + "Autospacing"), "0")
        spacing.attrib.pop(qn("w:" + side + "Lines"), None)

    started = False
    for node in list(document.element.body.iter(qn("w:p"))):
        if node.getparent() is None:
            continue
        if any(
            parent.tag in {qn("w:tc"), qn("w:txbxContent")}
            for parent in node.iterancestors()
        ):
            continue
        style = heading_style(node)
        first_heading = style == "Heading1" and not started
        if style == "Heading1":
            started = True
        if not started or style not in headings:
            continue
        spacing = node.find(qn("w:pPr") + "/" + qn("w:spacing"))
        if spacing is not None:
            for name in (
                "before",
                "after",
                "beforeLines",
                "afterLines",
                "beforeAutospacing",
                "afterAutospacing",
            ):
                spacing.attrib.pop(qn("w:" + name), None)
            if not spacing.attrib:
                spacing.getparent().remove(spacing)
        directions = ("getnext",) if first_heading else ("getprevious", "getnext")
        for direction in directions:
            neighbor = adjacent(node, direction)
            while disposable_spacer(neighbor):
                parent = neighbor.getparent()
                parent.remove(neighbor)
                neighbor = adjacent(node, direction)
        if not first_heading:
            remove_body_auto_spacing(adjacent(node, "getprevious"), "after")
        introduction = adjacent(node, "getnext")
        remove_body_auto_spacing(introduction, "before")
        if introduction is not None and introduction.tag == qn("w:p"):
            text = "".join(introduction.xpath(".//w:t/text()")).strip()
            if (
                text
                and len(text) <= 500
                and heading_style(introduction) not in headings
                and not introduction.xpath(".//w:drawing|.//w:pict")
            ):
                Paragraph(introduction, document).paragraph_format.keep_together = True
        if style == "Heading1":
            label = node.getprevious()
            if (
                not first_heading
                and label is not None
                and label.tag == qn("w:p")
                and "".join(label.xpath(".//w:t/text()")).startswith("SECTION ")
            ):
                previous = label.getprevious()
                has_boundary = previous is not None and (
                    any(e.get(qn("w:type")) == "page" for e in previous.iter(qn("w:br")))
                    or any(True for _ in previous.iter(qn("w:sectPr")))
                )
                if not has_boundary:
                    Paragraph(label, document).paragraph_format.page_break_before = True
            rule = node.getnext()
            if (
                rule is None
                or rule.tag != qn("w:p")
                or "".join(rule.xpath(".//w:t/text()")).strip()
            ):
                continue
            extents = rule.xpath(".//wp:anchor/wp:extent")
            if extents and all(
                int(e.get("cx", "0")) >= 914400 and int(e.get("cy", "0")) <= 12700
                for e in extents
            ):
                paragraph = Paragraph(rule, document)
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(12)
                paragraph.paragraph_format.line_spacing = Pt(6)
                paragraph.paragraph_format.keep_with_next = True


def ensure_page_numbers(document):
    """Keep live page fields in generated reports without replacing custom footers."""
    from docx.enum.text import WD_ALIGN_PARAGRAPH

    sections = document.sections
    for index, section in enumerate(sections):
        section.footer_distance = min(section.footer_distance, Pt(14.4))
        section.different_first_page_header_footer = len(sections) > 1 and index == 0
        footer = section.footer
        if footer.paragraphs and any(
            p.text.strip() or p._p.xpath(".//w:instrText|.//w:fldSimple")
            for p in footer.paragraphs
        ):
            continue
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        paragraph.paragraph_format.space_before = Pt(0)
        paragraph.paragraph_format.space_after = Pt(0)
        for position, instruction in enumerate(("PAGE", "NUMPAGES")):
            if position:
                paragraph.add_run(" / ")
            field = OxmlElement("w:fldSimple")
            field.set(qn("w:instr"), instruction)
            run = paragraph.add_run("1")
            run.font.name = document.styles["Normal"].font.name or "Aptos"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor.from_string("000032")
            field.append(run._r)
            paragraph._p.append(field)
        for run in paragraph.runs:
            run.font.name = document.styles["Normal"].font.name or "Aptos"
            run.font.size = Pt(9)
            run.font.color.rgb = RGBColor.from_string("000032")


def finalize_report_document(path):
    """Apply the shared hierarchy and keep the About page's absolute artwork clear."""
    from docx import Document
    from docx.text.paragraph import Paragraph

    document = apply_report_hierarchy(Document(path))
    for paragraph in document.paragraphs:
        if paragraph.style.name == "Heading 2" and paragraph.text in {
            "Server Capacity Analysis",
            "FillDB Performance Analysis",
            "PerfMon Counters Analysis",
            "Client Performance Analysis",
        }:
            node = paragraph._p.getnext()
            while node is not None and node.tag == qn("w:p"):
                properties = node.find(qn("w:pPr"))
                style = (
                    properties.find(qn("w:pStyle")) if properties is not None else None
                )
                if style is not None and style.get(qn("w:val"), "").startswith("Heading"):
                    break
                if node.xpath(".//w:drawing|.//w:pict"):
                    break
                Paragraph(node, document).paragraph_format.keep_with_next = True
                node = node.getnext()
        if paragraph.text == "About BigFix" and paragraph.style.name == "Heading 1":
            label = paragraph._p.getprevious()
            if label is not None and "".join(label.xpath(".//w:t/text()")).startswith(
                "SECTION "
            ):
                previous = label.getprevious()
                while (
                    previous is not None
                    and previous.tag == qn("w:p")
                    and not "".join(previous.xpath(".//w:t/text()")).strip()
                    and not previous.xpath(".//w:drawing|.//w:pict|.//w:sectPr")
                ):
                    before = previous.getprevious()
                    previous.getparent().remove(previous)
                    previous = before
                Paragraph(label, document).paragraph_format.page_break_before = True
            else:
                paragraph.paragraph_format.page_break_before = True
    body = document.element.body
    last = body[-2] if body[-1].tag == qn("w:sectPr") else body[-1]
    while (
        last is not None
        and last.tag == qn("w:p")
        and not "".join(last.xpath(".//w:t/text()")).strip()
        and not last.xpath(".//w:drawing|.//w:pict|.//w:sectPr")
    ):
        previous = last.getprevious()
        body.remove(last)
        last = previous
    if last is not None and last.tag == qn("w:tbl"):
        end = document.add_paragraph()
        end.paragraph_format.space_before = Pt(0)
        end.paragraph_format.space_after = Pt(0)
        end.paragraph_format.line_spacing = Pt(1)
        end.add_run().font.size = Pt(1)
    from Lib.Design.report_finishing import finish_report_body

    finish_report_body(document.element.body)
    document.save(path)


def add_callout(document, text, kind="NOTE"):
    """Use the template's existing NOTE/TIP colors, lead and icon treatment."""
    kind = kind.upper()
    if kind not in {"NOTE", "TIP"}:
        raise ValueError("Callout kind must be NOTE or TIP")
    fill, accent, icon = (
        ("CFDBFB", "17707F", "[i]") if kind == "NOTE" else ("ECFDF5", "065F46", "[?]")
    )
    spacer = document.add_paragraph()
    spacer.paragraph_format.space_after = Pt(4)
    spacer.paragraph_format.space_before = Pt(0)
    spacer.paragraph_format.line_spacing = Pt(2)
    table = document.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)
    borders = OxmlElement("w:tcBorders")
    edge = OxmlElement("w:left")
    for key, value in [("val", "single"), ("sz", "24"), ("color", accent)]:
        edge.set(qn("w:" + key), value)
    borders.append(edge)
    properties.append(borders)
    row_properties = table.rows[0]._tr.get_or_add_trPr()
    row_properties.append(OxmlElement("w:cantSplit"))
    paragraph = cell.paragraphs[0]
    paragraph.paragraph_format.space_before = Pt(5)
    paragraph.paragraph_format.space_after = Pt(5)
    run = paragraph.add_run(icon + " ")
    run.font.name = "Aptos"
    run.bold = True
    lead = paragraph.add_run(kind + "  ")
    lead.bold = True
    lead.font.color.rgb = RGBColor.from_string(accent)
    paragraph.add_run(text)
    document.add_paragraph().paragraph_format.space_after = Pt(4)
    return table
