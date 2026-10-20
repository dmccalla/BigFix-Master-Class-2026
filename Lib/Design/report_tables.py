# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""One layout rule for report tables (Design change list 10-20, Section 2).

Layout applies to tables styled BigFixContent whose width is dxa or auto:
10800 dxa wide (the 7.5 in text area at 0.5 in margins) with the grid scaled to
match, left aligned, no indent, fixed layout, and a header row that repeats on
each page, sits at the left like the body rows and stays with the first body
row. Code-built tables (an equal split of columns) get widths from their text.
Tables with set widths keep their proportions.

Column alignment applies to the same tables and to BigFixContent tables with a
percent width. A column is right aligned, header and cells, when every filled
body cell is a number, a number with a unit or a time. Every other column is
left aligned. A percent-width table that already sets the alignment of its own
header cells (the Check Results dashboard tables) keeps it.

Tables with no style and tables in any other style are left alone. Tell the
groups apart by style, width type and the table's own formatting, never by the
section a table sits in.
"""

from __future__ import annotations

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
    "mhz|ghz"
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


# Aptos 11 pt character widths in twips, rounded up, used to size code-built
# columns. Bold runs about 10% wider. A cell also loses its left and right
# margins (113 dxa each in BigFixContent), plus a little room for rounding.
_NARROW = set(".,:;'|!il1()[] ")
_CELL_PADDING_DXA = 290
_BOLD = 1.1


def _text_dxa(text: str, bold: bool = False) -> int:
    width = 0
    for char in text:
        if char in _NARROW:
            width += 65
        elif char.isupper() or char in "%@&wmWM":
            width += 150
        elif char.isdigit():
            width += 125
        else:
            width += 120
    return round(width * (_BOLD if bold else 1))


def _column_text(rows: list, count: int) -> list[tuple[int, int, int]]:
    """(longest header word, longest word, longest single-line text) per column,
    in twips, cell margins included."""
    heads = [0] * count
    words = [0] * count
    lines = [0] * count
    for index, tr in enumerate(rows):
        bold = index == 0
        for tc, column, span in _row_cells(tr):
            if span != 1 or column >= count:
                continue
            for paragraph in tc.iter(W + "p"):
                text = " ".join("".join(paragraph.itertext()).split())
                if not text:
                    continue
                longest = max(_text_dxa(word, bold) for word in text.split())
                if bold:
                    heads[column] = max(heads[column], longest)
                words[column] = max(words[column], longest)
                lines[column] = max(lines[column], _text_dxa(text, bold))
    return [
        (
            head + _CELL_PADDING_DXA,
            word + _CELL_PADDING_DXA,
            max(line, word) + _CELL_PADDING_DXA,
        )
        for head, word, line in zip(heads, words, lines, strict=True)
    ]


def _share(floor: list[int], want: list[int]) -> list[int]:
    """Give each column its floor, then split what is left by how much more
    each column wants."""
    spare = TEXT_WIDTH_DXA - sum(floor)
    extra = [max(goal - least, 0) for goal, least in zip(want, floor, strict=True)]
    if not sum(extra):
        return [least + spare // len(floor) for least in floor]
    return [
        least + round(spare * more / sum(extra))
        for least, more in zip(floor, extra, strict=True)
    ]


def _content_widths(rows: list, count: int) -> list[int]:
    """Column widths that add up to the text width, sized from the text.

    Every column gets its longest word when the table can hold them all, so
    nothing breaks mid-word. When it cannot, header words still stay whole and
    Word breaks a long cell value where its column ends. No hidden break
    characters are added, because readers copy names such as relays into
    searches. The rest of the width goes to the columns whose text would wrap.
    """
    needs = _column_text(rows, count)
    heads = [head for head, _, _ in needs]
    words = [word for _, word, _ in needs]
    lines = [line for _, _, line in needs]
    if sum(lines) <= TEXT_WIDTH_DXA:
        total = sum(lines)
        return [round(width * TEXT_WIDTH_DXA / total) for width in lines]
    if sum(words) <= TEXT_WIDTH_DXA:
        return _share(words, lines)
    if sum(heads) <= TEXT_WIDTH_DXA:
        return _share(heads, words)
    total = sum(heads)
    return [round(width * TEXT_WIDTH_DXA / total) for width in heads]


def _layout_grid(tbl, rows: list, size_from_text: bool) -> list[int]:
    """Set the grid to the text width and return it.

    In a Mini Report build a table whose columns are an equal split was built by
    code with no widths of its own, so its widths come from its text. Every other
    table keeps the proportions of its widths. The Full Report only scales, so a
    template table with equal columns (Document Control) keeps them.
    """
    grid = tbl.find(W + "tblGrid")
    if grid is None:
        grid = etree.Element(W + "tblGrid")
        tbl.insert(1, grid)
    cols = grid.findall(W + "gridCol")
    widths = [int(col.get(W + "w", "0") or 0) for col in cols]
    if not widths:
        return []
    total = sum(widths)
    if size_from_text and len(widths) > 1 and max(widths) - min(widths) <= 1:
        scaled = _content_widths(rows, len(widths))
    elif total <= 0:
        scaled = [TEXT_WIDTH_DXA // len(widths)] * len(widths)
    else:
        scaled = [round(width * TEXT_WIDTH_DXA / total) for width in widths]
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
            if not text:
                continue
            covered = range(column, column + span)
            if span > 1 or not is_number_cell(text):
                words.update(covered)
            else:
                filled[column] = filled.get(column, 0) + 1
    return {col for col in range(column_count) if filled.get(col) and col not in words}


def _align_cell(tc, alignment: str) -> None:
    for paragraph in tc.findall(W + "p"):
        p_pr = _first_child(paragraph, "pPr")
        _set(_child(p_pr, "jc", _PPR_ORDER), val=alignment)


def _apply_layout(tbl, size_from_text: bool) -> None:
    tbl_pr = tbl.find(W + "tblPr")
    _set(_child(tbl_pr, "tblW", _TBLPR_ORDER), w=str(TEXT_WIDTH_DXA), type="dxa")
    _set(_child(tbl_pr, "jc", _TBLPR_ORDER), val="left")
    _set(_child(tbl_pr, "tblInd", _TBLPR_ORDER), w="0", type="dxa")
    _set(_child(tbl_pr, "tblLayout", _TBLPR_ORDER), type="fixed")

    rows = tbl.findall(W + "tr")
    grid = _layout_grid(tbl, rows, size_from_text)
    if not rows or not grid:
        return

    tr_pr = rows[0].find(W + "trPr")
    if tr_pr is None:
        tr_pr = etree.Element(W + "trPr")
        prex = rows[0].find(W + "tblPrEx")
        rows[0].insert(1 if prex is not None else 0, tr_pr)
    _child(tr_pr, "tblHeader", _TRPR_ORDER)
    # Keep the header row whole and with the first body row, so a table never
    # starts at a page bottom with only its header. The style's header rule
    # turns cantSplit off, so set it on the row.
    _set(_child(tr_pr, "cantSplit", _TRPR_ORDER), val="1")
    if len(rows) > 1:
        for paragraph in rows[0].iter(W + "p"):
            _child(_first_child(paragraph, "pPr"), "keepNext", _PPR_ORDER)
    # BigFixContent centers its header row as a row, which would sit it to the
    # right of the body rows on a left-aligned table.
    _set(_child(tr_pr, "jc", _TRPR_ORDER), val="left")

    for tr in rows:
        for tc, column, span in _row_cells(tr):
            tc_pr = _first_child(tc, "tcPr")
            width = sum(grid[column : column + span])
            _set(_child(tc_pr, "tcW", _TCPR_ORDER), w=str(width), type="dxa")


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


def normalize_table(tbl, size_from_text: bool = True) -> bool:
    """Apply the rule to one table. False when the table is left alone.

    ``size_from_text`` sizes equal-split columns from their text. The Mini Report
    builders that create those tables pass True. Steps that work on a whole report
    they did not build (the Full Report, the PerfMon injector) pass False.
    """
    if not aligns_columns(tbl):
        return False
    if in_scope(tbl):
        _apply_layout(tbl, size_from_text)
    _apply_column_alignment(tbl)
    return True


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


def normalize_report_tables(root, size_from_text: bool = True) -> int:
    """Apply the rule to every top-level table under ``root``. Returns the count."""
    changed = 0
    for tbl in list(root.iter(W + "tbl")):
        if any(ancestor.tag == W + "tbl" for ancestor in tbl.iterancestors()):
            continue
        changed += normalize_table(tbl, size_from_text)
    return changed


def normalize_docx_tables(docx_path: Path, size_from_text: bool = True) -> int:
    """Rewrite ``word/document.xml`` of a saved .docx with the rule applied."""
    docx_path = Path(docx_path)
    with zipfile.ZipFile(docx_path) as zin:
        root = etree.fromstring(zin.read("word/document.xml"))
        changed = normalize_report_tables(root, size_from_text)
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


def normalize_document_xml(document_xml: str, size_from_text: bool = True) -> str:
    """Return ``word/document.xml`` text with the rule applied."""
    root = etree.fromstring(document_xml.encode("utf-8"))
    if not normalize_report_tables(root, size_from_text):
        return document_xml
    return _serialize(root).decode("utf-8")
