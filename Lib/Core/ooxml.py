# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Small Open XML helpers for safe DOCX body splices."""

from __future__ import annotations

import re

_BOOKMARK_MARKER_RE = re.compile(
    r'<w:bookmark(Start|End)\b[^>]*\bw:id="([^"]+)"[^>]*/?>'
)
_DOC_PR_RE = re.compile(r'(<wp:docPr\b[^>]*\bid=")(\d+)(")')


def _has_bookmark_marker(fragment_xml: str, kind: str, bookmark_id: str) -> bool:
    return (
        re.search(
            rf'<w:bookmark{kind}\b[^>]*\bw:id="{re.escape(bookmark_id)}"[^>]*/?>',
            fragment_xml,
        )
        is not None
    )


def next_docpr_id(doc_xml: str) -> int:
    """Return the next available wp:docPr id in a document XML part."""
    ids = [int(match.group(2)) for match in _DOC_PR_RE.finditer(doc_xml)]
    return max(ids, default=0) + 1


def renumber_docpr_ids(fragment_xml: str, start_at: int) -> tuple[str, int]:
    """Renumber every wp:docPr id in an inserted fragment from start_at."""
    next_id = max(1, int(start_at))
    changed = 0

    def replace(match: re.Match) -> str:
        nonlocal next_id, changed
        replacement = f"{match.group(1)}{next_id}{match.group(3)}"
        next_id += 1
        changed += 1
        return replacement

    return _DOC_PR_RE.sub(replace, fragment_xml), changed


def deduplicate_docpr_ids(doc_xml: str) -> tuple[str, int]:
    """Renumber duplicate wp:docPr ids, preserving the first occurrence."""
    seen: set[int] = set()
    next_id = next_docpr_id(doc_xml)
    changed = 0

    def replace(match: re.Match) -> str:
        nonlocal next_id, changed
        current = int(match.group(2))
        if current not in seen:
            seen.add(current)
            return match.group(0)
        while next_id in seen:
            next_id += 1
        replacement = f"{match.group(1)}{next_id}{match.group(3)}"
        seen.add(next_id)
        next_id += 1
        changed += 1
        return replacement

    return _DOC_PR_RE.sub(replace, doc_xml), changed


def splice_preserving_bookmarks(
    doc_xml: str,
    start: int,
    end: int,
    replacement_xml: str,
) -> tuple[str, int]:
    """Replace a body range without orphaning crossing bookmark markers.

    Several report injectors replace a character range in word/document.xml.
    Word often stores heading and OLE bookmarks with one marker just inside the
    replaced range and the matching marker outside it. A plain string splice
    deletes one side and leaves Word with an invalid bookmark range. This helper
    keeps the crossing marker by moving it to the end of the inserted content;
    bookmarks wholly inside the removed range are removed with the old content.
    """
    if start < 0 or end < start:
        raise ValueError("Invalid Open XML splice range.")

    markers = list(_BOOKMARK_MARKER_RE.finditer(doc_xml))
    starts_by_id: dict[str, list[int]] = {}
    ends_by_id: dict[str, list[int]] = {}
    for marker in markers:
        target = starts_by_id if marker.group(1) == "Start" else ends_by_id
        target.setdefault(marker.group(2), []).append(marker.start())

    preserved: list[str] = []
    for marker in markers:
        if not (start <= marker.start() < end):
            continue
        bookmark_id = marker.group(2)
        if marker.group(1) == "Start":
            if any(
                position >= end for position in ends_by_id.get(bookmark_id, [])
            ) and not _has_bookmark_marker(replacement_xml, "Start", bookmark_id):
                preserved.append(marker.group(0))
        elif any(
            position < start for position in starts_by_id.get(bookmark_id, [])
        ) and not _has_bookmark_marker(replacement_xml, "End", bookmark_id):
            preserved.append(marker.group(0))

    return (
        doc_xml[:start] + replacement_xml + "".join(preserved) + doc_xml[end:],
        len(preserved),
    )
