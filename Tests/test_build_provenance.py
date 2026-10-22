# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Build provenance (Design, 10-20): the Comments property names the commit
and the template file, never a local folder."""

from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document

from Lib.Core import build_provenance as bp


def _core_xml(path: Path) -> str:
    with zipfile.ZipFile(path) as package:
        return package.read("docProps/core.xml").decode("utf-8")


def test_comment_names_the_template_file_and_never_its_folder(tmp_path) -> None:
    template = tmp_path / "Users" / "someone" / "Templates" / "Report_Template.dotx"

    comment = bp.provenance_comment("abc1234-dirty", template)

    assert comment == "Commit abc1234-dirty · Template Report_Template.dotx"
    assert "someone" not in comment


def test_comments_property_is_written_once_and_replaced(tmp_path) -> None:
    report = tmp_path / "report.docx"
    Document().save(report)

    assert bp.set_document_comments(report, "Commit abc1234 · Template A.dotx")
    assert bp.set_document_comments(report, "Commit def5678 · Template B & C.dotx")

    core = _core_xml(report)
    assert core.count("<dc:description>") == 1
    assert "Template B &amp; C.dotx</dc:description>" in core
    assert (
        Document(report).core_properties.comments
        == "Commit def5678 · Template B & C.dotx"
    )


def test_description_is_added_when_core_properties_has_none() -> None:
    core = (
        '<?xml version="1.0"?><cp:coreProperties xmlns:cp="http://schemas.'
        'openxmlformats.org/package/2006/metadata/core-properties"></cp:coreProperties>'
    )

    updated = bp._with_description(core, "Commit abc · Template T.dotx")

    assert 'xmlns:dc="http://purl.org/dc/elements/1.1/"' in updated
    assert updated.endswith(
        "<dc:description>Commit abc · Template T.dotx</dc:description>"
        "</cp:coreProperties>"
    )


def test_build_commit_is_unknown_without_a_git_checkout(tmp_path) -> None:
    assert bp.build_commit(tmp_path / "not-a-checkout") == "unknown"


def test_a_file_that_is_not_a_word_package_raises_value_error(tmp_path) -> None:
    placeholder = tmp_path / "report.docx"
    placeholder.write_text("not a package", encoding="utf-8")

    try:
        bp.set_document_comments(placeholder, "Commit abc")
    except ValueError as exc:
        assert "report.docx" in str(exc)
    else:
        raise AssertionError("expected ValueError")
