# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Helpers for standalone Word fragments that should carry report styles."""

from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from collections.abc import Iterable
from html import unescape
from pathlib import Path

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.shared import Inches

from Lib.Core.document_stamp import strip_stamp_paragraphs_xml
from Lib.Core.input_utils import discover_docx_template

TABLE_STYLE_ID = "BigFixContent"
_TEMPLATE_CONTENT_TYPE = "wordprocessingml.template.main+xml"
_DOCUMENT_CONTENT_TYPE = "wordprocessingml.document.main+xml"
STUB_NOTICE_PREFIX = "Standalone module excerpt."
# No notice paragraph: every module document here is a standalone Mini Report.
STUB_NOTICE_TEXT = ""
STANDALONE_NARROW_MARGIN_INCHES = 0.5


def _docx_compatible_template(path: Path) -> Path:
    """Return a python-docx-readable copy of a .docx or .dotx template."""
    if path.suffix.lower() != ".dotx":
        return path

    tag = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:8]
    out = Path(tempfile.gettempdir()) / f"bigfix_report_template_{tag}.docx"
    with (
        zipfile.ZipFile(path, "r") as zin,
        zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout,
    ):
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "[Content_Types].xml":
                data = (
                    data.decode("utf-8")
                    .replace(_TEMPLATE_CONTENT_TYPE, _DOCUMENT_CONTENT_TYPE)
                    .encode("utf-8")
                )
            zout.writestr(item, data)
    return out


def clear_document_body(document: DocxDocument) -> None:
    """Remove template body content while preserving section properties/styles."""
    body = document._body._element
    sect_pr = None
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            sect_pr = child
            continue
        body.remove(child)
    if sect_pr is not None and sect_pr.getparent() is None:
        body.append(sect_pr)


def create_styled_stub_document(script_file: str | None = None) -> DocxDocument:
    """Create a DOCX fragment document seeded with the project report styles."""
    template = discover_docx_template(style_id=TABLE_STYLE_ID, script_file=script_file)
    if not template:
        return apply_standalone_narrow_margins(Document())

    return create_stub_document_from_template(template)


def create_stub_document_from_template(template: Path) -> DocxDocument:
    """Create a fragment document from a specific .docx/.dotx template."""
    document = Document(str(_docx_compatible_template(template)))
    clear_document_body(document)
    apply_standalone_narrow_margins(document)
    return document


def apply_standalone_narrow_margins(document: DocxDocument) -> DocxDocument:
    """Use Word's narrow margin preset for standalone module documents."""
    margin = Inches(STANDALONE_NARROW_MARGIN_INCHES)
    for section in document.sections:
        section.top_margin = margin
        section.bottom_margin = margin
        section.left_margin = margin
        section.right_margin = margin
        section.header_distance = min(section.header_distance, Inches(0.2))
        section.footer_distance = min(section.footer_distance, Inches(0.2))
    from Lib.Design.report_layout import apply_report_hierarchy

    return apply_report_hierarchy(document)


def add_stub_front_matter(
    document: DocxDocument,
    title: str,
    notice_text: str = STUB_NOTICE_TEXT,
) -> None:
    """Add a standalone title and usage note to a generated module fragment."""
    document.add_heading(title, level=1)
    if notice_text:
        paragraph = document.add_paragraph()
        run = paragraph.add_run(notice_text)
        run.italic = True


def set_picture_alt_text(inline_shape, alt_text: str, name: str | None = None) -> None:
    """Attach concise alt text to a python-docx inserted image."""
    text = _normalise_alt_text(alt_text)
    if not text:
        return

    inline = inline_shape._inline
    doc_pr = inline.docPr
    doc_pr.set("descr", text)
    doc_pr.set("title", text)
    if name:
        doc_pr.set("name", _normalise_alt_text(name))

    for c_nv_pr in inline.xpath(".//pic:cNvPr"):
        c_nv_pr.set("descr", text)
        if name:
            c_nv_pr.set("name", _normalise_alt_text(name))


def _normalise_alt_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _plain_text(para_xml: str) -> str:
    return unescape(re.sub(r"<[^>]+>", "", para_xml)).strip()


def _normalise_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def _first_paragraph(body_xml: str) -> re.Match[str] | None:
    return re.match(r"\s*(<w:p\b.*?</w:p>)", body_xml, flags=re.DOTALL)


def _is_blank_paragraph(para_xml: str) -> bool:
    if any(tag in para_xml for tag in ("<w:drawing", "<w:pict", "<w:object")):
        return False
    return not _plain_text(para_xml)


def _strip_leading_blank_paragraphs(body_xml: str) -> str:
    body = body_xml.lstrip()
    while True:
        match = _first_paragraph(body)
        if not match or not _is_blank_paragraph(match.group(1)):
            return body
        body = body[match.end() :].lstrip()


def strip_stub_front_matter_xml(
    body_xml: str,
    titles: Iterable[str] = (),
) -> str:
    """Remove the standalone title/notice/stamp before fragment injection."""
    # The document stamp is standalone front matter too. Drop it first so the
    # title and notice sit adjacent again for the checks below.
    body = _strip_leading_blank_paragraphs(strip_stamp_paragraphs_xml(body_xml))
    title_set = {_normalise_text(title) for title in titles if title}

    match = _first_paragraph(body)
    if match and _normalise_text(_plain_text(match.group(1))) in title_set:
        body = _strip_leading_blank_paragraphs(body[match.end() :])

    match = _first_paragraph(body)
    if match:
        plain = _normalise_text(_plain_text(match.group(1)))
        if plain.startswith(_normalise_text(STUB_NOTICE_PREFIX)):
            body = _strip_leading_blank_paragraphs(body[match.end() :])

    return body
