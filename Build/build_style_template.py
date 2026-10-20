#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
build_style_template.py -- write Templates/Diagnostics_Style_Template.docx.

The Mini Reports clone their styles from this document (see
Lib/Themes/word_stub_utils.py). It carries no content: only the body font,
the heading styles, and the BigFixContent table style the modules use.
The styles mirror the full Workbench's report template (Aptos body, the
same heading sizes, colors, and spacing) so a Master Class Mini Report
reads like one from the full Workbench. Run this script to regenerate the
template; never edit the .docx by hand.

    python Build/build_style_template.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml import parse_xml
from docx.shared import Pt, RGBColor

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT = PROJECT_ROOT / "Templates" / "Diagnostics_Style_Template.docx"

BODY_FONT = "Aptos"
NAVY = RGBColor(0x0B, 0x16, 0x40)
SLATE = RGBColor(0x10, 0x2A, 0x54)
BLUE = RGBColor(0x14, 0x52, 0xE6)
TABLE_STYLE_ID = "BigFixContent"

# The shared table look: navy header row with white bold text, light banding,
# a hairline grid with no inside vertical rules, centered cells.
# The header row has no contextualSpacing, unlike the full Workbench's
# template. With it, Word drops the space before every header cell whose
# left neighbor has the same style, so only the first cell keeps it and its
# text sits 3 pt lower than the rest of the header row.
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
TABLE_STYLE_XML = f"""
<w:style {_W} w:type="table" w:customStyle="1" w:styleId="{TABLE_STYLE_ID}">
  <w:name w:val="BigFix Content"/>
  <w:basedOn w:val="TableNormal"/>
  <w:uiPriority w:val="49"/>
  <w:pPr><w:spacing w:before="80" w:after="80"/></w:pPr>
  <w:rPr><w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" w:cs="{BODY_FONT}"/></w:rPr>
  <w:tblPr>
    <w:tblStyleRowBandSize w:val="1"/>
    <w:tblBorders>
      <w:top w:val="single" w:sz="6" w:space="0" w:color="E3E9F1"/>
      <w:left w:val="single" w:sz="6" w:space="0" w:color="E3E9F1"/>
      <w:bottom w:val="single" w:sz="6" w:space="0" w:color="E3E9F1"/>
      <w:right w:val="single" w:sz="6" w:space="0" w:color="E3E9F1"/>
      <w:insideH w:val="single" w:sz="6" w:space="0" w:color="E3E9F1"/>
      <w:insideV w:val="nil"/>
    </w:tblBorders>
    <w:tblCellMar>
      <w:top w:w="85" w:type="dxa"/>
      <w:left w:w="113" w:type="dxa"/>
      <w:bottom w:w="85" w:type="dxa"/>
      <w:right w:w="113" w:type="dxa"/>
    </w:tblCellMar>
  </w:tblPr>
  <w:trPr><w:cantSplit/></w:trPr>
  <w:tcPr><w:vAlign w:val="center"/></w:tcPr>
  <w:tblStylePr w:type="firstRow">
    <w:pPr>
      <w:wordWrap/>
      <w:spacing w:before="80" w:after="80" w:line="240" w:lineRule="auto"/>
      <w:jc w:val="left"/>
    </w:pPr>
    <w:rPr>
      <w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" w:cs="{BODY_FONT}"/>
      <w:b/><w:bCs/><w:color w:val="FFFFFF"/><w:sz w:val="22"/>
    </w:rPr>
    <w:tblPr><w:jc w:val="center"/></w:tblPr>
    <w:trPr><w:cantSplit w:val="0"/><w:tblHeader/><w:jc w:val="center"/></w:trPr>
    <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="0B1640"/></w:tcPr>
  </w:tblStylePr>
  <w:tblStylePr w:type="firstCol">
    <w:pPr><w:jc w:val="left"/></w:pPr>
    <w:tblPr/>
    <w:tcPr><w:vAlign w:val="center"/></w:tcPr>
  </w:tblStylePr>
  <w:tblStylePr w:type="band1Horz">
    <w:rPr>
      <w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" w:cs="{BODY_FONT}"/>
      <w:color w:val="auto"/><w:sz w:val="22"/>
    </w:rPr>
    <w:tblPr/>
    <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="F4F7FB"/></w:tcPr>
  </w:tblStylePr>
  <w:tblStylePr w:type="band2Horz">
    <w:rPr>
      <w:rFonts w:ascii="{BODY_FONT}" w:hAnsi="{BODY_FONT}" w:cs="{BODY_FONT}"/>
      <w:color w:val="auto"/><w:sz w:val="22"/>
    </w:rPr>
    <w:tblPr/>
    <w:tcPr><w:shd w:val="clear" w:color="auto" w:fill="FFFFFF"/></w:tcPr>
  </w:tblStylePr>
</w:style>
"""

# Heading and body definitions copied from the full Workbench's report
# template: (size in points, color, space before, space after, extra pPr).
# The template's heading font is a licensed one this project does not ship,
# so the headings use the body font in bold instead.
HEADINGS = {
    1: dict(size=24, color=NAVY, before=240, after=180, keep=True),
    2: dict(size=18, color=SLATE, before=240, after=None, keep=True),
    # H3, H4 and H5 follow Design's 10-20 change list, Section 1: 16, 14 and
    # 12 pt, so each level is smaller than the one above. No border, no new
    # font and no change to Normal.
    3: dict(size=16, color=NAVY, before=360, after=120, keep=True, line=276),
    4: dict(size=14, color=BLUE, before=240, after=80, keep=True),
    5: dict(size=12, color=SLATE, before=200, after=40, keep=True),
}
NORMAL_SPACING = (120, 120)


def _set_font(
    style,
    size_pt: int | None = None,
    bold: bool | None = None,
    color: RGBColor | None = None,
) -> None:
    font = style.font
    font.name = BODY_FONT
    if color is not None:
        font.color.rgb = color
    if size_pt is not None:
        font.size = Pt(size_pt)
    if bold is not None:
        font.bold = bold
    # East Asian and complex-script slots fall back to the theme unless set.
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.find(
        "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}rFonts"
    )
    if rfonts is not None:
        for attr in ("ascii", "hAnsi", "cs", "eastAsia"):
            rfonts.set(
                f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{attr}",
                BODY_FONT,
            )
        for attr in ("asciiTheme", "hAnsiTheme", "cstheme", "eastAsiaTheme"):
            rfonts.attrib.pop(
                f"{{http://schemas.openxmlformats.org/wordprocessingml/2006/main}}{attr}",
                None,
            )


def _set_spacing(
    style, before: int | None, after: int | None, line: int | None = None
) -> None:
    fmt = style.paragraph_format
    fmt.space_before = Pt(before / 20) if before is not None else None
    fmt.space_after = Pt(after / 20) if after is not None else None
    if line is not None:
        fmt.line_spacing = line / 240


def build(output: Path = OUTPUT) -> Path:
    document = Document()
    styles = document.styles

    # No color on Normal or in the document defaults. A paragraph style
    # outranks a table style, so a color here would paint the BigFixContent
    # header row's white text over its navy fill.
    normal = styles["Normal"]
    _set_font(normal, size_pt=11)
    _set_spacing(normal, *NORMAL_SPACING)
    for level, spec in HEADINGS.items():
        heading = styles[f"Heading {level}"]
        _set_font(heading, size_pt=spec["size"], bold=True, color=spec["color"])
        # python-docx's stock Heading 4 is italic. The report template's is not.
        heading.font.italic = False
        _set_spacing(heading, spec["before"], spec["after"], spec.get("line"))
        heading.paragraph_format.keep_with_next = spec["keep"]
        heading.paragraph_format.keep_together = spec["keep"]
    _set_font(styles["Title"], size_pt=28)
    for name in ("Caption", "List Bullet", "List Number", "List Paragraph"):
        try:
            _set_font(styles[name])
        except KeyError:
            continue

    # Replace any earlier copy of the table style, then add ours.
    existing = [
        style
        for style in styles
        if style.type == WD_STYLE_TYPE.TABLE and style.style_id == TABLE_STYLE_ID
    ]
    for style in existing:
        style.element.getparent().remove(style.element)
    styles.element.append(parse_xml(TABLE_STYLE_XML.strip()))

    output.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(output))
    return output


def main() -> int:
    path = build()
    check = Document(str(path))
    if not any(s.style_id == TABLE_STYLE_ID for s in check.styles):
        raise SystemExit(f"{path} was written without the {TABLE_STYLE_ID} table style.")
    print(f"Wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
