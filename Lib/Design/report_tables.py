# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""One layout rule for report tables (Design change list 10-20, Section 2, and
the 10-20 build handoff, Part 3).

Layout applies to tables styled BigFixContent whose width is dxa or auto:
10800 dxa wide (the 7.5 in text area at 0.5 in margins), left aligned, no
indent, fixed layout, and a header row that repeats on each page, sits at the
left like the body rows and stays with the first body row. Column widths come
from Design: a table with known columns takes its fixed widths, a template
table keeps the proportions of its own widths, and every other table is
measured from its text.

Column alignment and the header kept with the first body row apply to the same
tables and to BigFixContent data tables with a percent width. A column is right
aligned, header and cells, when every filled body cell is a number, a number
with a unit or a time. Every other column is left aligned. A percent-width
table that sets the alignment of its own cells (the Check Results dashboard
tables) keeps it, and each header takes the alignment of its column.

Tables with no style and tables in any other style are left alone. Tell the
groups apart by style, width type and the table's own formatting, never by the
section a table sits in. The cell and table properties of every table are
written in schema order, because Word misdraws shading out of order.
"""

from __future__ import annotations

import math
import re
import zipfile
from pathlib import Path

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"

TEXT_WIDTH_DXA = 10800
TABLE_STYLE = "BigFixContent"

# Schema order of the children that this module sets, so an inserted element
# lands where Word expects it.
_TBLPR_ORDER = (
    "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize "
    "tblW jc tblCellSpacing tblInd tblBorders shd tblLayout tblCellMar tblLook "
    "tblCaption tblDescription tblPrChange"
).split()
_TRPR_ORDER = (
    "cnfStyle divId gridBefore gridAfter wBefore wAfter cantSplit trHeight "
    "tblHeader tblCellSpacing jc hidden ins del trPrChange"
).split()
_TCPR_ORDER = (
    "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection "
    "tcFitText vAlign hideMark headers cellIns cellDel cellMerge tcPrChange"
).split()
_PPR_ORDER = (
    "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr "
    "suppressLineNumbers pBdr shd tabs suppressAutoHyphens kinsoku wordWrap "
    "overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
    "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc "
    "textDirection textAlignment textboxTightWrap outlineLvl divId cnfStyle rPr "
    "sectPr pPrChange"
).split()

_NUMBER = r"[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_UNITS = (
    "%|ms|s|sec|secs|second|seconds|min|mins|minute|minutes|h|hr|hrs|hour|hours|"
    "day|days|b|bytes|kb|mb|gb|tb|kb/s|mb/s|gb/s|/s|lines/s|ops/s|mbps|gbps|"
    "mhz|ghz|core|cores"
)
_NUMBER_CELL = re.compile(
    rf"(?:{_NUMBER}\s?(?:{_UNITS})?"  # 1,234  12.3 MB  45%
    rf"|{_NUMBER}\s?%?\s?/\s?{_NUMBER}\s?%?"  # 27 / 100
    r"|\d{1,3}:\d{2}(?::\d{2}(?:\.\d+)?)?)",  # 00:12:34
    re.IGNORECASE,
)


def is_number_cell(text: str) -> bool:
    """True when a cell holds only a number, a number with a unit or a time."""
    value = " ".join(text.replace(" ", " ").split())
    return bool(_NUMBER_CELL.fullmatch(value))


def _child(parent, tag: str, order: list[str]):
    """Return the w:tag child, creating it in schema order when missing."""
    found = parent.find(W + tag)
    if found is not None:
        return found
    element = etree.SubElement(parent, W + tag)
    parent.remove(element)
    rank = order.index(tag)
    for index, sibling in enumerate(parent):
        name = etree.QName(sibling).localname
        if name in order and order.index(name) > rank:
            parent.insert(index, element)
            return element
    parent.append(element)
    return element


def _first_child(parent, tag: str):
    """Return a w:tag child that must be the first child, creating it there."""
    found = parent.find(W + tag)
    if found is None:
        found = etree.Element(W + tag)
        parent.insert(0, found)
    return found


def _set(element, **attrs: str) -> None:
    for name, value in attrs.items():
        element.set(W + name, value)


def _width_type(tbl) -> str | None:
    """The tblW type of a BigFixContent table, or None for any other table."""
    tbl_pr = tbl.find(W + "tblPr")
    if tbl_pr is None:
        return None
    style = tbl_pr.find(W + "tblStyle")
    if style is None or style.get(W + "val") != TABLE_STYLE:
        return None
    width = tbl_pr.find(W + "tblW")
    return "auto" if width is None else width.get(W + "type", "dxa")


def in_scope(tbl) -> bool:
    """BigFixContent tables with a dxa or auto width take the layout rule."""
    return _width_type(tbl) in ("dxa", "auto")


def _sets_own_header_alignment(tbl) -> bool:
    first = tbl.find(W + "tr")
    if first is None:
        return False
    paragraphs = list(first.iter(W + "p"))
    return bool(paragraphs) and all(
        paragraph.find(f"{W}pPr/{W}jc") is not None for paragraph in paragraphs
    )


def aligns_columns(tbl) -> bool:
    """BigFixContent data tables take the column alignment rule."""
    if in_scope(tbl):
        return True
    return _width_type(tbl) == "pct" and not _sets_own_header_alignment(tbl)


# Fixed widths for tables with known columns (build handoff, Part 3B and
# Appendix A), keyed by the header row. Each set adds up to 10800.
_COMMAND_POLLING = (
    "Total Devices",
    "Enabled",
    "Missing Interval",
    "Interval Below Loop",
    "No UDP + Polling Off",
)
FIXED_WIDTHS: dict[tuple[str, ...], tuple[int, ...]] = {
    ("Version", "Date", "Notes"): (1200, 1800, 7800),
    ("Area", "Findings", "Source IDs"): (3000, 3000, 4800),
    ("Source ID", "Description", "Impact", "Suggested Remediation"): (
        1500,
        3224,
        1163,
        4913,
    ),
    ("Group", "Devices / Total", "% of Total", "Rule"): (1900, 1900, 1700, 5300),
    (
        "Rank",
        "Average Eval Time (Seconds)",
        "Occurrences",
        "Evaluation",
        "Interval",
    ): (1000, 1700, 1700, 4900, 1500),
    (
        "Interval",
        "Properties / Active",
        "% of Active",
        "Custom",
        "External",
        "Status",
    ): (2400, 1900, 1400, 1300, 1400, 2400),
    ("Metric", "Value", "Status", "Basis"): (2400, 2600, 1300, 4500),
    ("Status", "Devices / Total", "% of Total"): (5400, 2700, 2700),
    ("Relay", "Not Receiving / Reported", "% of Relay Reported Clients"): (
        4200,
        3200,
        3400,
    ),
    ("Subnet", "Not Receiving / Reported", "Serving Relays"): (2800, 2800, 5200),
    ("Relay", *_COMMAND_POLLING): (3000, 1300, 1300, 1700, 1700, 1800),
    ("Subnet", *_COMMAND_POLLING): (3000, 1300, 1300, 1700, 1700, 1800),
    ("Multicore CPU Scaling Enabled", "Devices / Total"): (7000, 3800),
    ("Infographic tile", "Value", "What it means"): (2600, 2200, 6000),
    ("Resource", "Required", "Observed", "Short by", "Basis"): (
        1300,
        1300,
        1900,
        1300,
        5000,
    ),
    ("Setting Name", "Value", "Number of Machines"): (6400, 2200, 2200),
    ("Timeframe", "State", "Count"): (6400, 2200, 2200),
    ("Site", "State", "Count"): (6400, 2200, 2200),
    ("FillDB Object", "Count", "Time (ms)", "Rate/s", "Health Check"): (
        3270,
        1490,
        1390,
        1220,
        3430,
    ),
    ("Statistic", "Value"): (6980, 3820),
}

# Template tables keep the proportions of their own widths (Design, 10-20).
KEEP_PROPORTIONS: frozenset[tuple[str, ...]] = frozenset(
    {
        ("Infrastructure", "Operational Maturity"),
        ("Reader", "Start Here", "Purpose"),
        ("ID", "Check Instructions", "Notes and Findings"),
        ("Resource Name", "Description"),
    }
)

# Columns whose cells never wrap: a Source ID must not break at its hyphen.
NO_WRAP_COLUMNS: dict[tuple[str, ...], tuple[int, ...]] = {
    ("Source ID", "Description", "Impact", "Suggested Remediation"): (0,),
}

# Design's method for tables built from data (build handoff, Part 3B): about
# 105 twips per character of Aptos 11 pt, header words bold (about 10% wider)
# and 226 twips of cell margins.
_CHAR_DXA = 105
_HEADER_BOLD = 1.1
_CELL_MARGINS_DXA = 226
_LEAST_COLUMN_DXA = 1000
_MOST_FLOOR_DXA = 2600
_WORD_CAP = 22
_TEXT_CAP = 70
_SHARE_BASE = 150


def _cell_words(tc) -> str:
    return " ".join("".join(tc.itertext()).split())


def header_key(rows: list) -> tuple[str, ...]:
    """The header row's cell text, used to look up a table's fixed widths."""
    if not rows:
        return ()
    return tuple(_cell_words(tc) for tc in rows[0].findall(W + "tc"))


def measured_widths(rows: list, count: int) -> list[int]:
    """Column widths from the text, by Design's method (Part 3B).

    Each column gets its least width: its longest header word (bold) or its
    longest body word (capped at 22 characters), never below 1000 or above
    2600. Its natural width comes from the 80th percentile length of its body
    cells (capped at 70 characters). The rest of the width is shared in
    proportion to natural minus least, plus 150, rounded to 10, and the widest
    column takes up the difference so the total is exactly 10800.
    """
    heads = [0] * count
    for tc, column, span in _row_cells(rows[0]):
        if span == 1 and column < count:
            heads[column] = max(
                (len(word) for word in _cell_words(tc).split()), default=0
            )
    words = [0] * count
    lengths: list[list[int]] = [[] for _ in range(count)]
    for tr in rows[1:]:
        for tc, column, span in _row_cells(tr):
            if span != 1 or column >= count:
                continue
            text = _cell_words(tc)
            words[column] = max(
                words[column],
                max((min(len(word), _WORD_CAP) for word in text.split()), default=0),
            )
            lengths[column].append(min(len(text), _TEXT_CAP))
    least: list[float] = []
    natural: list[float] = []
    for column in range(count):
        floor = (
            max(heads[column] * _CHAR_DXA * _HEADER_BOLD, words[column] * _CHAR_DXA)
            + _CELL_MARGINS_DXA
        )
        floor = min(max(floor, _LEAST_COLUMN_DXA), _MOST_FLOOR_DXA)
        ordered = sorted(lengths[column]) or [0]
        p80 = ordered[max(0, math.ceil(0.8 * len(ordered)) - 1)]
        least.append(floor)
        natural.append(max(p80 * _CHAR_DXA + _CELL_MARGINS_DXA, floor))
    spare = TEXT_WIDTH_DXA - sum(least)
    weights = [nat - low + _SHARE_BASE for low, nat in zip(least, natural, strict=True)]
    widths = [
        round((low + spare * weight / sum(weights)) / 10) * 10
        for low, weight in zip(least, weights, strict=True)
    ]
    widest = widths.index(max(widths))
    widths[widest] += TEXT_WIDTH_DXA - sum(widths)
    return widths


def _layout_grid(tbl, rows: list) -> list[int]:
    """Set the grid to the text width and return it.

    A table with known columns takes its fixed widths. A template table keeps
    the proportions of its own widths. Every other table is measured from its
    text.
    """
    grid = tbl.find(W + "tblGrid")
    if grid is None:
        grid = etree.Element(W + "tblGrid")
        tbl.insert(1, grid)
    cols = grid.findall(W + "gridCol")
    widths = [int(col.get(W + "w", "0") or 0) for col in cols]
    if not widths:
        return []
    key = header_key(rows)
    fixed = FIXED_WIDTHS.get(key)
    if fixed is not None and len(fixed) == len(widths):
        scaled = list(fixed)
    elif key in KEEP_PROPORTIONS and sum(widths) > 0:
        scaled = [round(width * TEXT_WIDTH_DXA / sum(widths)) for width in widths]
    elif len(rows) > 1:
        scaled = measured_widths(rows, len(widths))
    else:
        scaled = [TEXT_WIDTH_DXA // len(widths)] * len(widths)
    scaled[-1] += TEXT_WIDTH_DXA - sum(scaled)
    for col, width in zip(cols, scaled, strict=True):
        col.set(W + "w", str(width))
    return scaled


def _row_cells(tr) -> list[tuple[object, int, int]]:
    """(cell, first grid column, grid span) for each cell in a row."""
    column = 0
    tr_pr = tr.find(W + "trPr")
    if tr_pr is not None:
        before = tr_pr.find(W + "gridBefore")
        if before is not None:
            column = int(before.get(W + "val", "0"))
    cells = []
    for tc in tr.findall(W + "tc"):
        tc_pr = tc.find(W + "tcPr")
        span_el = tc_pr.find(W + "gridSpan") if tc_pr is not None else None
        span = int(span_el.get(W + "val", "1")) if span_el is not None else 1
        cells.append((tc, column, span))
        column += span
    return cells


def _cell_text(tc) -> str:
    return "".join(tc.itertext()).strip()


def _number_columns(rows: list, column_count: int) -> set[int]:
    filled: dict[int, int] = {}
    words: set[int] = set()
    for tr in rows[1:]:
        for tc, column, span in _row_cells(tr):
            text = _cell_text(tc)
            # A cell merged across columns, such as a host label row, belongs
            # to no single column, so it does not decide any column.
            if not text or span > 1:
                continue
            if not is_number_cell(text):
                words.add(column)
            else:
                filled[column] = filled.get(column, 0) + 1
    return {col for col in range(column_count) if filled.get(col) and col not in words}


def _align_cell(tc, alignment: str) -> None:
    for paragraph in tc.findall(W + "p"):
        p_pr = _first_child(paragraph, "pPr")
        _set(_child(p_pr, "jc", _PPR_ORDER), val=alignment)


def _header_row_properties(header):
    tr_pr = header.find(W + "trPr")
    if tr_pr is None:
        tr_pr = etree.Element(W + "trPr")
        prex = header.find(W + "tblPrEx")
        header.insert(1 if prex is not None else 0, tr_pr)
    return tr_pr


def _keep_header_with_body(tbl) -> None:
    """Keep the header row whole and with the first body row, so a table never
    starts at a page bottom with only its header. The style's header rule turns
    cantSplit off, so set it on the row."""
    rows = tbl.findall(W + "tr")
    if len(rows) < 2:
        return
    tr_pr = _header_row_properties(rows[0])
    _set(_child(tr_pr, "cantSplit", _TRPR_ORDER), val="1")
    for paragraph in rows[0].iter(W + "p"):
        _child(_first_child(paragraph, "pPr"), "keepNext", _PPR_ORDER)


def _apply_layout(tbl) -> None:
    tbl_pr = tbl.find(W + "tblPr")
    _set(_child(tbl_pr, "tblW", _TBLPR_ORDER), w=str(TEXT_WIDTH_DXA), type="dxa")
    _set(_child(tbl_pr, "jc", _TBLPR_ORDER), val="left")
    _set(_child(tbl_pr, "tblInd", _TBLPR_ORDER), w="0", type="dxa")
    _set(_child(tbl_pr, "tblLayout", _TBLPR_ORDER), type="fixed")

    rows = tbl.findall(W + "tr")
    grid = _layout_grid(tbl, rows)
    if not rows or not grid:
        return

    tr_pr = _header_row_properties(rows[0])
    _child(tr_pr, "tblHeader", _TRPR_ORDER)
    # BigFixContent centers its header row as a row, which would sit it to the
    # right of the body rows on a left-aligned table.
    _set(_child(tr_pr, "jc", _TRPR_ORDER), val="left")

    no_wrap = NO_WRAP_COLUMNS.get(header_key(rows), ())
    for index, tr in enumerate(rows):
        for tc, column, span in _row_cells(tr):
            tc_pr = _first_child(tc, "tcPr")
            width = sum(grid[column : column + span])
            _set(_child(tc_pr, "tcW", _TCPR_ORDER), w=str(width), type="dxa")
            if index and span == 1 and column in no_wrap:
                _child(tc_pr, "noWrap", _TCPR_ORDER)


def _apply_column_alignment(tbl) -> None:
    rows = tbl.findall(W + "tr")
    grid = tbl.find(W + "tblGrid")
    column_count = len(grid.findall(W + "gridCol")) if grid is not None else 0
    if not rows or not column_count:
        return
    numbers = _number_columns(rows, column_count)
    for tr in rows:
        for tc, column, span in _row_cells(tr):
            _align_cell(tc, "right" if column in numbers and span == 1 else "left")


_SAME_ALIGNMENT = {"start": "left", "end": "right"}


def _header_follows_column(tbl) -> bool:
    """A table that aligns its own cells (the Check Results dashboard tables)
    keeps them, and each header cell takes the alignment of its column, so a
    centered header never sits over left-aligned cells. True when a header
    cell changed."""
    rows = tbl.findall(W + "tr")
    if len(rows) < 2:
        return False
    found: dict[int, set[str]] = {}
    for tr in rows[1:]:
        for tc, column, span in _row_cells(tr):
            if span != 1:
                continue
            for paragraph in tc.findall(W + "p"):
                jc = paragraph.find(f"{W}pPr/{W}jc")
                value = jc.get(W + "val", "left") if jc is not None else "left"
                found.setdefault(column, set()).add(_SAME_ALIGNMENT.get(value, value))
    changed = False
    for tc, column, span in _row_cells(rows[0]):
        values = found.get(column, set())
        if span != 1 or len(values) != 1:
            continue
        want = next(iter(values))
        have = set()
        for paragraph in tc.findall(W + "p"):
            jc = paragraph.find(f"{W}pPr/{W}jc")
            value = jc.get(W + "val", "left") if jc is not None else "left"
            have.add(_SAME_ALIGNMENT.get(value, value))
        if have != {want}:
            _align_cell(tc, want)
            changed = True
    return changed


def normalize_table(tbl) -> bool:
    """Apply the rule to one table. False when the table is left alone."""
    width_type = _width_type(tbl)
    if width_type is None:
        return False
    if not aligns_columns(tbl):
        return _header_follows_column(tbl)
    if in_scope(tbl):
        _apply_layout(tbl)
    _keep_header_with_body(tbl)
    _apply_column_alignment(tbl)
    return True


def _put_in_order(parent, order: list[str]) -> bool:
    """Sort the children of ``parent`` into schema order. True when it moved any.

    Children the order does not name keep their places after the named ones.
    """
    rank = {name: index for index, name in enumerate(order)}
    children = list(parent)

    def place(element) -> int:
        if not isinstance(element.tag, str):
            return len(order)
        return rank.get(etree.QName(element).localname, len(order))

    ordered = sorted(children, key=place)
    if ordered == children:
        return False
    for element in children:
        parent.remove(element)
    parent.extend(ordered)
    return True


def order_table_properties(root) -> int:
    """Write every table's tblPr and every cell's tcPr in schema order. Returns
    the number of property sets that moved."""
    moved = 0
    for tbl_pr in root.iter(W + "tblPr"):
        moved += _put_in_order(tbl_pr, _TBLPR_ORDER)
    for tc_pr in root.iter(W + "tcPr"):
        moved += _put_in_order(tc_pr, _TCPR_ORDER)
    return moved


def _serialize(root) -> bytes:
    """Write the document back the way Word and python-docx write it.

    lxml writes an empty element as self-closing (<w:t xml:space="preserve"/>).
    Later report steps find text with a <w:t ...>...</w:t> pattern that would run
    past a self-closing tag into the markup after it, so empty text elements keep
    their open and close tags.
    """
    for element in root.iter(W + "t", W + "instrText", W + "delText"):
        if element.text is None:
            element.text = ""
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def normalize_report_tables(root) -> int:
    """Apply the rule to every top-level table under ``root`` and put every
    table's properties in schema order. Returns the count of changes."""
    changed = 0
    for tbl in list(root.iter(W + "tbl")):
        if any(ancestor.tag == W + "tbl" for ancestor in tbl.iterancestors()):
            continue
        changed += normalize_table(tbl)
    return changed + order_table_properties(root)


def normalize_docx_tables(docx_path: Path) -> int:
    """Rewrite ``word/document.xml`` of a saved .docx with the rule applied."""
    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path) as zin:
        root = etree.fromstring(zin.read("word/document.xml"))
        changed = normalize_report_tables(root)
        if not changed:
            return 0
        data = _serialize(root)
        tmp_path = docx_path.with_name(f"{docx_path.name}.tmp")
        with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                payload = data if item.filename == "word/document.xml" else zin.read(item)
                zout.writestr(item, payload)
    tmp_path.replace(docx_path)
    return changed


def normalize_document_xml(document_xml: str) -> str:
    """Return ``word/document.xml`` text with the rule applied."""
    root = etree.fromstring(document_xml.encode("utf-8"))
    if not normalize_report_tables(root):
        return document_xml
    return _serialize(root).decode("utf-8")
