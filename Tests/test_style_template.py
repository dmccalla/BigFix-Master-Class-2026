# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""The Word style template the Mini Reports take their styles from."""

from __future__ import annotations

import re
import sys
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Build"))

import build_style_template  # noqa: E402

SHIPPED = ROOT / "Templates" / "Diagnostics_Style_Template.docx"


def _styles_xml(path: Path) -> str:
    with ZipFile(path) as zf:
        return zf.read("word/styles.xml").decode("utf-8")


def _style(xml: str, style_id: str) -> str:
    match = re.search(rf'<w:style [^>]*w:styleId="{style_id}".*?</w:style>', xml, re.S)
    assert match, f"style {style_id} missing"
    return match.group(0)


def _first_row(xml: str) -> str:
    table = _style(xml, "BigFixContent")
    match = re.search(r'<w:tblStylePr w:type="firstRow">.*?</w:tblStylePr>', table, re.S)
    assert match, "BigFixContent has no firstRow rule"
    return match.group(0)


def test_header_row_is_white_on_navy_without_contextual_spacing(
    tmp_path: Path,
) -> None:
    xml = _styles_xml(build_style_template.build(tmp_path / "style.docx"))
    first_row = _first_row(xml)
    assert '<w:color w:val="FFFFFF"/>' in first_row
    assert 'w:fill="0B1640"' in first_row
    # Contextual spacing drops the space before every header cell except the
    # first, so the first header cell's text sits lower than the rest.
    assert "contextualSpacing" not in first_row


def test_header_text_is_left_aligned(tmp_path: Path) -> None:
    """Word lets the style's header alignment win over a direct left, so the
    style itself must say left. Number columns go right per paragraph."""
    xml = _styles_xml(build_style_template.build(tmp_path / "style.docx"))
    header_ppr = re.search(r"<w:pPr>.*?</w:pPr>", _first_row(xml), re.S).group(0)
    assert '<w:jc w:val="left"/>' in header_ppr


def test_normal_carries_no_color(tmp_path: Path) -> None:
    """A color on Normal outranks the table style and hides the header text."""
    xml = _styles_xml(build_style_template.build(tmp_path / "style.docx"))
    normal = _style(xml, "Normal")
    assert "<w:color " not in normal
    defaults = re.search(r"<w:docDefaults>.*?</w:docDefaults>", xml, re.S).group(0)
    assert "<w:color " not in defaults


def test_shipped_template_matches_the_builder(tmp_path: Path) -> None:
    built = _styles_xml(build_style_template.build(tmp_path / "style.docx"))
    shipped = _styles_xml(SHIPPED)
    assert _style(shipped, "BigFixContent") == _style(built, "BigFixContent")
    assert _style(shipped, "Normal") == _style(built, "Normal")


def test_approved_section_and_subheading_styles(tmp_path: Path) -> None:
    """Use 20pt sections and the more visible 14pt subheadings."""
    xml = _styles_xml(build_style_template.build(tmp_path / "style.docx"))
    for style_id, half_points, before, after in (
        ("Heading3", "40", "400", "120"),
        ("Heading4", "28", "320", "120"),
        ("Heading5", "22", "200", "60"),
    ):
        style = _style(xml, style_id)
        assert f'<w:sz w:val="{half_points}"/>' in style
        assert f'w:before="{before}"' in style and f'w:after="{after}"' in style
        assert "<w:keepNext/>" in style
        assert "<w:pBdr>" not in style
    assert "<w:color " not in _style(xml, "Normal")
