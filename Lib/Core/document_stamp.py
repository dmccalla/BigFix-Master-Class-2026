#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""document_stamp.py -- the one place the document stamp is formatted.

Every document a run produces carries the customer name and the assessment
dates in its body (Document_Stamp_Handoff_2026-09-07). One function builds
the string so the wording, the date format, and the separator never drift
between generators. The placement helpers here move content around without
formatting anything themselves.

Known exception (ruled 2026-09-07): Findings_Scoring_Review.xlsx is not
stamped. Its Scoring Data sheet is read by fixed row numbers throughout
get_hc_scoring, so shifting row 1 would break the validation readers and
refresh-mode reuse of consultant workbooks from earlier builds. Its existing
Customer / Report Date meta row stands in for the stamp until the row
constants move to named ranges in a pass of their own.
"""

from __future__ import annotations

from datetime import datetime

# U+00B7 with a space on each side, per the handoff.
_SEPARATOR = " · "

_DATE_INPUT_FORMATS = ("%m-%d-%Y", "%m/%d/%Y", "%Y-%m-%d", "%m-%d-%y", "%m/%d/%y")


def _display_date(value: object) -> str:
    """Render one assessment date as MM-DD-YYYY, or "" when unparseable."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(raw, fmt).strftime("%m-%d-%Y")
        except ValueError:
            continue
    return raw


def document_stamp(
    customer: object, start_date: object = "", end_date: object = ""
) -> str:
    """The stamp line, exactly as every document prints it.

    When every value is blank the stamp is an empty string and the document
    carries no stamp line. Otherwise blank values keep their label and print
    a dash. The dates read as one value: both fields present renders "start
    to end", anything less is a dash.
    """
    customer_text = str(customer or "").strip()
    start = _display_date(start_date)
    end = _display_date(end_date)
    if not (customer_text or start or end):
        return ""
    customer_text = customer_text or "-"
    dates_text = f"{start} to {end}" if start and end else "-"
    return f"Customer: {customer_text}{_SEPARATOR}Assessment dates: {dates_text}"


def add_stamp_arguments(parser) -> None:
    """Add the three stamp options a generator needs on its command line."""
    parser.add_argument(
        "--customer",
        default="",
        help="Customer name printed in the document stamp line.",
    )
    parser.add_argument(
        "--assessment-start-date",
        default="",
        help="Assessment start date printed in the document stamp line.",
    )
    parser.add_argument(
        "--assessment-end-date",
        default="",
        help="Assessment end date printed in the document stamp line.",
    )


def stamp_from_args(args) -> str:
    """Build the stamp line from parsed command line arguments."""
    return document_stamp(
        getattr(args, "customer", ""),
        getattr(args, "assessment_start_date", ""),
        getattr(args, "assessment_end_date", ""),
    )


def is_stamp_text(text: object) -> bool:
    """True when a paragraph's text is a document stamp line."""
    cleaned = str(text or "").strip()
    return cleaned.startswith("Customer: ") and "Assessment dates: " in cleaned


def strip_stamp_paragraphs_xml(body_xml: str) -> str:
    """Remove stamp paragraphs from raw body XML before report injection.

    The stamp belongs to the standalone document. When an injector lifts a
    module document's body into a larger assembled document, that document
    keeps its own front matter and the stamp must not ride along.
    """
    import re

    def _plain(paragraph_xml: str) -> str:
        return "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", paragraph_xml))

    def _keep(match: re.Match[str]) -> str:
        return "" if is_stamp_text(_plain(match.group(0))) else match.group(0)

    return re.sub(r"<w:p\b[^>]*(?:/>|>.*?</w:p>)", _keep, body_xml, flags=re.DOTALL)


def stamp_docx_document(document, stamp: str) -> None:
    """Insert the stamp as one body paragraph under the first heading.

    python-docx documents only. Body style, no direct formatting. When the
    document has no heading the stamp becomes the first paragraph.
    """
    paragraphs = document.paragraphs
    heading_index = None
    for index, paragraph in enumerate(paragraphs):
        if (paragraph.style.name or "").startswith(("Heading", "Title")):
            heading_index = index
            break
    stamp_paragraph = document.add_paragraph(stamp)
    if heading_index is not None and heading_index + 1 < len(paragraphs):
        anchor = paragraphs[heading_index + 1]
        anchor._p.addprevious(stamp_paragraph._p)
    elif heading_index is None and paragraphs:
        paragraphs[0]._p.addprevious(stamp_paragraph._p)
    # A heading as the last element leaves add_paragraph's position correct.


def stamp_worksheet(worksheet, stamp: str) -> None:
    """Put the stamp in A1 of a worksheet and shift everything down one row.

    openpyxl worksheets only. Merged ranges, the freeze pane, the auto
    filter, row heights, data validations, and conditional formats all move
    with the content, so the sheet reads exactly as before below row 1.
    """
    from copy import copy

    from openpyxl.utils.cell import coordinate_from_string
    from openpyxl.worksheet.cell_range import CellRange

    merged = [str(r) for r in worksheet.merged_cells.ranges]
    for ref in merged:
        worksheet.unmerge_cells(ref)

    worksheet.insert_rows(1)

    def shift_range(ref: str) -> str:
        cell_range = CellRange(ref)
        cell_range.shift(0, 1)
        return str(cell_range)

    for ref in merged:
        worksheet.merge_cells(shift_range(ref))

    if worksheet.freeze_panes:
        column, row = coordinate_from_string(worksheet.freeze_panes)
        worksheet.freeze_panes = f"{column}{row + 1}"

    if worksheet.auto_filter.ref:
        worksheet.auto_filter.ref = shift_range(worksheet.auto_filter.ref)

    # insert_rows moves cell values and styles, not the row metadata.
    dimensions = worksheet.row_dimensions
    for row_index in sorted((i for i in dimensions if i >= 1), reverse=True):
        dimension = dimensions.pop(row_index)
        dimension.index = row_index + 1
        dimensions[row_index + 1] = dimension

    for validation in worksheet.data_validations.dataValidation:
        shifted = [shift_range(str(ref)) for ref in validation.sqref.ranges]
        validation.sqref.ranges = [CellRange(ref) for ref in shifted]

    formatting = worksheet.conditional_formatting
    old_rules = [(str(block.sqref), list(block.rules)) for block in formatting]
    formatting._cf_rules.clear()
    for sqref, rules in old_rules:
        shifted = " ".join(shift_range(part) for part in str(sqref).split())
        for rule in rules:
            rule = copy(rule)
            formatting.add(shifted, rule)

    worksheet["A1"] = stamp
