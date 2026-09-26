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
Run this script to regenerate the template; never edit the .docx by hand.

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

BODY_FONT = "Inter"
INK = RGBColor(0x00, 0x00, 0x32)
TABLE_STYLE_ID = "BigFixContent"

# The shared table look: navy header row with white bold text, light banding,
# a hairline grid with no inside vertical rules, centered cells.
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
      <w:contextualSpacing/>
      <w:jc w:val="center"/>
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

HEADING_SIZES = {1: 20, 2: 16, 3: 14, 4: 12}


def _set_font(style, size_pt: int | None = None, bold: bool | None = None) -> None:
    font = style.font
    font.name = BODY_FONT
    font.color.rgb = INK
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


def build(output: Path = OUTPUT) -> Path:
    document = Document()
    styles = document.styles

    _set_font(styles["Normal"], size_pt=11)
    for level, size in HEADING_SIZES.items():
        _set_font(styles[f"Heading {level}"], size_pt=size, bold=True)
    for name in ("Title", "Caption", "List Bullet", "List Number", "List Paragraph"):
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
