# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import zipfile
from pathlib import Path

import input_utils
import pytest


def test_clean_user_path_strips_whitespace_and_quotes() -> None:
    assert input_utils.clean_user_path('  "C:/Temp/file.txt"  ') == "C:/Temp/file.txt"
    assert input_utils.clean_user_path(None) == ""


def test_normalize_extensions_accepts_mixed_forms() -> None:
    assert input_utils.normalize_extensions(["log", ".TXT", " "]) == {".log", ".txt"}


def test_resolve_existing_file_validates_extension(tmp_path: Path) -> None:
    source = tmp_path / "Dashboard.LOG"
    source.write_text("example", encoding="utf-8")

    resolved = input_utils.resolve_existing_file(str(source), "dashboard log", {".log"})

    assert resolved == source.resolve()


def test_resolve_existing_file_rejects_wrong_extension(tmp_path: Path) -> None:
    source = tmp_path / "Dashboard.csv"
    source.write_text("example", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported extension"):
        input_utils.resolve_existing_file(str(source), "dashboard log", {".log"})


def test_resolve_existing_folder_can_require_matching_files(tmp_path: Path) -> None:
    (tmp_path / "chart.png").write_bytes(b"png")

    resolved = input_utils.resolve_existing_folder(
        str(tmp_path), "chart folder", "*.png"
    )

    assert resolved == tmp_path.resolve()


def test_resolve_output_file_adds_extension_and_requires_existing_parent(
    tmp_path: Path,
) -> None:
    resolved = input_utils.resolve_output_file(
        str(tmp_path / "Report"),
        tmp_path / "Default.docx",
        ".docx",
    )

    assert resolved == (tmp_path / "Report.docx").resolve(strict=False)

    with pytest.raises(ValueError, match="folder does not exist"):
        input_utils.resolve_output_file(
            str(tmp_path / "missing" / "Report"),
            tmp_path / "Default.docx",
            ".docx",
        )


def test_docx_contains_text_or_style_reads_minimal_package(tmp_path: Path) -> None:
    docx_path = tmp_path / "template.docx"
    with zipfile.ZipFile(docx_path, "w") as package:
        package.writestr(
            "word/document.xml", "<w:document>Executive Summary</w:document>"
        )
        package.writestr("word/styles.xml", '<w:style w:styleId="ReportTitle"/>')

    assert input_utils.docx_contains_text_or_style(
        docx_path,
        style_id="ReportTitle",
        required_text="executive summary",
    )
    assert not input_utils.docx_contains_text_or_style(
        docx_path,
        required_text="not present",
    )


def test_docx_contains_text_or_style_returns_false_for_bad_docx(tmp_path: Path) -> None:
    bad_docx = tmp_path / "bad.docx"
    bad_docx.write_text("not a zip", encoding="utf-8")

    assert not input_utils.docx_contains_text_or_style(
        bad_docx, required_text="anything"
    )


def test_add_keep_next_leaves_malformed_paragraph_xml_unchanged() -> None:
    fragment = "not a Word paragraph"

    assert input_utils._add_keep_next(fragment) == fragment
