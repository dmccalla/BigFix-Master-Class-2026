#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
Shared helpers for BESAPI XML captures.

The collection tasks query the BigFix REST API with the IEM CLI and append
each response to a per-report .xml capture. A capture is therefore a
CONCATENATION of BESAPI documents, one per query, optionally interleaved
with raw "ERROR: Query line N failed:" lines when a query fails. It cannot
be parsed as a single XML document.

Historically the tasks also converted each capture to a formatted text file
(one line per Answer element) that the builder parsed. That conversion is
now optional on the collection side, so the builder reads the capture
directly: capture_to_log_text() reconstructs the same line-oriented text in
memory and the existing parsers consume it unchanged. Failed-query ERROR
lines are passed through so downstream failure handling keeps working.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from defusedxml import ElementTree as ET

REST_QUERY_ERROR_RE = re.compile(r"^ERROR:\s+Query line \d+ failed:", re.IGNORECASE)

_BESAPI_DOC_RE = re.compile(r"<BESAPI\b.*?</BESAPI>", re.DOTALL)


def split_besapi_documents(text: str) -> list[str]:
    """Split a concatenated BESAPI capture into individual XML documents."""
    parts = re.split(r"(?=<\?xml\b)", text)
    return [part.strip() for part in parts if part.strip()]


def parse_besapi_fragment(fragment: str):
    """Parse one capture fragment, tolerating stray non-XML lines around it.

    Returns the BESAPI Element, or None when the fragment holds no document
    (for example a block of failed-query ERROR output).
    """
    match = _BESAPI_DOC_RE.search(fragment)
    if match is None:
        return None
    return ET.fromstring(match.group(0))


def capture_to_log_text(text: str) -> str:
    """Reconstruct the formatted log text from a BESAPI capture.

    Mirrors the collection task conversion: one line per Answer element, in
    document order. Raw lines matching the failed-query marker are passed
    through in place so parsers and validators still see collection
    failures.
    """
    lines: list[str] = []
    for fragment in split_besapi_documents(text):
        for raw_line in fragment.splitlines():
            if REST_QUERY_ERROR_RE.match(raw_line.strip()):
                lines.append(raw_line.strip())
        try:
            root = parse_besapi_fragment(fragment)
        except ET.ParseError:
            continue
        if root is None:
            continue
        for answer in root.iter("Answer"):
            lines.append(answer.text or "")
    return "\n".join(lines)


def read_capture_or_log_text(path: Path, encoding: str = "utf-8-sig") -> str:
    """Read a collection source as formatted log text.

    A .xml capture is reconstructed via capture_to_log_text(). Any other
    file is returned as-is. Callers keep their existing line-oriented
    parsers either way.
    """
    text = path.read_text(encoding=encoding, errors="replace")
    if path.suffix.lower() == ".xml":
        return capture_to_log_text(text)
    return text


_SECTION_MARKER_RE = re.compile(r"^//=+\s+(.+?)\s*=+\s*$")


def _merge_key(line: str) -> str | None:
    if ":" not in line:
        return None
    key, _, _value = line.partition(":")
    key = re.sub(r"\s+", " ", key).strip().lower()
    if not key or key.startswith("//") or key.startswith("column headers"):
        return None
    return key


def _section_key(line: str) -> str | None:
    match = _SECTION_MARKER_RE.match(line.strip())
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip().lower()


def merge_capture_text(primary_text: str, secondary_text: str) -> str:
    """Merge two line-oriented capture texts with ``primary_text`` winning.

    Deployment Information now has split authority: the XML capture carries the
    REST API answers, while the legacy log may carry client-relevance lines that
    are not in the API. Keep API values when both sources emit the same key, and
    append log-only key/value lines. Whole duplicate section blocks from a full
    legacy log are skipped so the API section body remains authoritative.
    """
    primary_lines = primary_text.splitlines()
    secondary_lines = secondary_text.splitlines()
    if not primary_lines:
        return secondary_text
    if not secondary_lines:
        return primary_text

    primary_keys = {key for line in primary_lines if (key := _merge_key(line))}
    primary_sections = {
        section for line in primary_lines if (section := _section_key(line))
    }

    merged = list(primary_lines)
    skipping_secondary_section = False
    for line in secondary_lines:
        section = _section_key(line)
        if section is not None:
            skipping_secondary_section = section in primary_sections
            if skipping_secondary_section:
                continue
        elif skipping_secondary_section:
            continue

        key = _merge_key(line)
        if key and key in primary_keys:
            continue
        merged.append(line)

    return "\n".join(merged)


def _newest_match(folder: Path, patterns: tuple[str, ...]) -> Path | None:
    seen: set[Path] = set()
    matches: list[Path] = []
    for pattern in patterns:
        for path in folder.rglob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            matches.append(path)
    if not matches:
        return None
    return max(matches, key=lambda p: p.stat().st_mtime)


def newest_capture_source_pair(
    folder: Path, stem: str, log_patterns: tuple[str, ...] | None = None
) -> tuple[Path | None, Path | None]:
    """Return newest XML and newest legacy source separately for one stem."""
    if not folder.is_dir():
        return None, None
    xml = _newest_match(folder, (f"{stem}*.xml",))
    legacy = _newest_match(folder, log_patterns or (f"{stem}*.log", f"{stem}*.txt"))
    return xml, legacy


def read_merged_capture_or_log_text(
    folder: Path,
    stem: str,
    log_patterns: tuple[str, ...] | None = None,
    encoding: str = "utf-8-sig",
) -> str:
    """Read XML plus companion legacy log for a single deployment-info stem.

    The XML text is primary. A companion log contributes only fields or section
    bodies absent from the XML. When only one source exists, that source is read
    normally.
    """
    xml, legacy = newest_capture_source_pair(folder, stem, log_patterns)
    if xml is None and legacy is None:
        return ""
    if xml is None:
        return read_capture_or_log_text(legacy, encoding) if legacy else ""
    xml_text = read_capture_or_log_text(xml, encoding)
    if legacy is None:
        return xml_text
    legacy_text = read_capture_or_log_text(legacy, encoding)
    return merge_capture_text(xml_text, legacy_text)


_ANSWER_LINE_RE = re.compile(r"<Answer\b[^>]*>(?P<text>[^<]*)</Answer>")


def sample_capture_lines(path: Path, count: int) -> list[str]:
    """Stream the first *count* reconstructed log lines from a capture.

    Cheap sniffing helper for validators and discovery: captures put each
    Answer element on its own line, so header checks never need to parse the
    whole document. Entities are unescaped to match full reconstruction.
    Multi-line Answer payloads are skipped, which is fine for sniffing.
    """
    lines: list[str] = []
    try:
        with path.open(encoding="utf-8-sig", errors="replace") as handle:
            for raw in handle:
                match = _ANSWER_LINE_RE.search(raw)
                if match:
                    lines.append(html.unescape(match.group("text")))
                    if len(lines) >= count:
                        break
    except OSError:
        return []
    return lines


def all_capture_sources(
    folder: Path, stem: str, log_patterns: tuple[str, ...] | None = None
) -> list[Path]:
    """Return EVERY collection source for *stem*, newest first.

    ``newest_capture_source`` returns exactly one file, which is correct for the
    captures that are one file per deployment. Server capacity is not one of
    those: every BigFix role server writes its own file against the same stem,
    so resolving to the newest would silently discard the rest and the module
    would describe a deployment from one host with no sign the others existed.

    This is deliberately a separate function rather than a flag on
    ``newest_capture_source``. The single-file behaviour is right for every
    other caller and must not change underneath them.

    Ordering is newest first, so a caller deduplicating by host keeps the most
    recent file per host by taking the first it sees. Deduplication is the
    caller's job, because the host is a value inside the file rather than
    something this function can read without parsing it.
    """
    if not folder.is_dir():
        return []
    patterns = (f"{stem}*.xml",) + (log_patterns or (f"{stem}*.log", f"{stem}*.txt"))
    found: list[Path] = []
    seen: set[Path] = set()
    for pattern in patterns:
        for path in folder.rglob(pattern):
            if not path.is_file():
                continue
            resolved = path.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(path)
    found.sort(key=lambda p: (-p.stat().st_mtime, p.name))
    return found


def newest_capture_source(
    folder: Path, stem: str, log_patterns: tuple[str, ...] | None = None
) -> Path | None:
    """Return the newest collection source for *stem* in *folder*.

    Prefers the XML capture over the legacy formatted log, newest by
    modification time within each format. The stem match is prefix-based
    ("General_Info*") so historical captures with naming quirks still
    resolve. Pass log_patterns to override the legacy patterns when the log
    name does not share the stem (for example the dashboard data logs).

    The search is recursive. The collection tasks group Deployment_Information
    captures into subfolders (Server, Relays, Clients, Content, Operators,
    General), and older captures are a single flat folder. Searching the tree
    resolves both, so a data package collected before the grouping change
    still builds.
    """
    if not folder.is_dir():
        return None
    patterns = (f"{stem}*.xml",) + (log_patterns or (f"{stem}*.log", f"{stem}*.txt"))
    for pattern in patterns:
        matches = [p for p in folder.rglob(pattern) if p.is_file()]
        if matches:
            return max(matches, key=lambda p: p.stat().st_mtime)
    return None
