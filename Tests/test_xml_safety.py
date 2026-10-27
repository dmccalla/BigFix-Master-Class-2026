# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Customer text spliced into Word XML must be escaped.

A server name, label or finding can carry markup characters. The XML builders
must emit well-formed XML that reads back as the same text, and the repository
must not parse input XML with an unhardened parser.
"""

from __future__ import annotations

import ast
from pathlib import Path

import inject_perfmon_charts as injector
import pytest
from defusedxml import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = "{" + W_NS + "}"

HOSTILE = [
    "</w:t><w:t>injected",
    "a & b < c > d \"quoted\" 'single'",
    "<!DOCTYPE x [<!ENTITY e SYSTEM 'file:///c:/windows/win.ini'>]>&e;",
    "]]> <![CDATA[ x ]]>",
    "<w:r><w:t>nested</w:t></w:r>",
]


def _read_text(fragment: str) -> str:
    root = ET.fromstring(f'<w:root xmlns:w="{W_NS}">{fragment}</w:root>')
    return "".join(node.text or "" for node in root.iter(W + "t"))


@pytest.mark.parametrize("hostile", HOSTILE)
def test_paragraph_builders_escape_hostile_text(hostile: str) -> None:
    assert hostile in _read_text(injector.bullet_paragraph_xml(hostile))
    assert hostile in _read_text(injector.heading_paragraph_xml(hostile, level=3))
    assert hostile in _read_text(injector.score_note_heading_xml(hostile))
    assert hostile in _read_text(injector.text_paragraph_xml(hostile))
    assert hostile in _read_text(
        injector.text_paragraph_xml(f"Note: {hostile}", bold_prefix="Note:")
    )
    assert hostile in _read_text(injector.table_cell_xml(hostile, 1200, bold=True))


@pytest.mark.parametrize("hostile", HOSTILE)
def test_status_paragraph_escapes_label_and_text(hostile: str) -> None:
    text = _read_text(injector.status_paragraph_xml("Good", hostile, hostile))
    assert text.count(hostile) == 2


# Stdlib parsers resolve entities. Input XML goes through defusedxml. The lxml
# sites below only read documents this tool builds or ships, never collected data.
UNSAFE_CALLS = {"parse", "fromstring", "XML", "XMLParser", "iterparse", "parseString"}
STDLIB_XML_MODULES = {
    "xml.etree.ElementTree",
    "xml.etree.cElementTree",
    "xml.dom.minidom",
    "xml.sax",
    "xml.parsers.expat",
}
LXML_PARSE_ALLOWED = {
    "Lib/Design/client_report_layout.py",
    "Lib/Design/report_tables.py",
}
SKIP_DIRS = {
    ".git",
    ".venv",
    "Tests",
    "Docs",
    "Temp",
    "Dist",
    "SampleData",
    "__pycache__",
    "output",
    "tmp",
}


def _shipped_files():
    for path in ROOT.rglob("*.py"):
        if not SKIP_DIRS & set(path.relative_to(ROOT).parts):
            yield path


def _parser_aliases(tree: ast.AST) -> tuple[set[str], set[str]]:
    """Return names bound to stdlib XML modules and names bound to lxml.etree."""
    stdlib: set[str] = set()
    lxml: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in STDLIB_XML_MODULES:
                    stdlib.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                full = f"{node.module}.{alias.name}"
                bound = alias.asname or alias.name
                if full in STDLIB_XML_MODULES or node.module in STDLIB_XML_MODULES:
                    if alias.name in UNSAFE_CALLS and node.module in STDLIB_XML_MODULES:
                        stdlib.add(bound)
                    elif full in STDLIB_XML_MODULES:
                        stdlib.add(bound)
                if full == "lxml.etree" or (
                    node.module == "lxml" and alias.name == "etree"
                ):
                    lxml.add(bound)
    return stdlib, lxml


def test_input_xml_is_never_parsed_with_the_stdlib_parsers() -> None:
    offenders: list[str] = []
    for path in _shipped_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        stdlib, _lxml = _parser_aliases(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in UNSAFE_CALLS:
                base = func.value
                while isinstance(base, ast.Attribute):
                    base = base.value
                if isinstance(base, ast.Name) and base.id in stdlib:
                    offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
            elif (
                isinstance(func, ast.Name)
                and func.id in stdlib
                and func.id in UNSAFE_CALLS
            ):
                offenders.append(f"{path.relative_to(ROOT).as_posix()}:{node.lineno}")
    assert not offenders, "Parse XML with defusedxml, not the stdlib: " + ", ".join(
        offenders
    )


def test_lxml_parsing_is_limited_to_reviewed_files() -> None:
    found: set[str] = set()
    for path in _shipped_files():
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        _stdlib, lxml = _parser_aliases(tree)
        if not lxml:
            continue
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in UNSAFE_CALLS
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in lxml
            ):
                found.add(path.relative_to(ROOT).as_posix())
    assert found <= LXML_PARSE_ALLOWED, (
        "New lxml parse sites need a review: "
        + ", ".join(sorted(found - LXML_PARSE_ALLOWED))
    )
