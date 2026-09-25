#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""
Shared input helpers for the module scripts.

These helpers keep standalone script arguments and UI validation aligned:
clean paths the same way, validate files consistently, and resolve output paths
with the same defaults. There are no interactive prompts. Scripts fail fast
when a required argument is missing or invalid.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path


def open_path(path) -> None:
    """Open a file or folder with the OS's default handler (cross-platform).

    Windows uses ``os.startfile``; macOS uses ``open``; other POSIX uses
    ``xdg-open``. May raise ``OSError`` when the target or opener is
    unavailable, so GUI callers can surface a message -- matching the previous
    ``os.startfile`` behavior on Windows.
    """
    target = str(path)
    if sys.platform == "win32":
        os.startfile(target)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", target], check=False)
    else:
        subprocess.run(["xdg-open", target], check=False)


# Default working/output folder prefilled in prompts and the UI. A clearly named
# folder under the user's Documents on both Windows and macOS, so generated
# reports land somewhere discoverable and per-user rather than a disposable-
# sounding C:\Temp. Falls back to the home folder if Documents does not exist.
# Created on demand when a report is written; the user can always choose another.
_documents = Path.home() / "Documents"
_work_base = _documents if _documents.is_dir() else Path.home()
DEFAULT_WORK_DIR = str(_work_base / "Master Class Diagnostics")


def clean_user_path(value) -> str:
    """Strip whitespace and surrounding quotes from a user-entered path."""
    if value is None:
        return ""
    return str(value).strip().strip('"').strip("'")


def normalize_extensions(
    extensions: set[str] | tuple[str, ...] | list[str],
) -> set[str]:
    normalized = set()
    for extension in extensions:
        text = str(extension).strip().lower()
        if not text:
            continue
        normalized.add(text if text.startswith(".") else f".{text}")
    return normalized


def resolve_existing_file(
    candidate_text: str, label: str, extensions: set[str] | tuple[str, ...] | list[str]
) -> Path:
    """Resolve and validate an existing input file."""
    candidate_text = clean_user_path(candidate_text)
    allowed_extensions = normalize_extensions(extensions)

    if not candidate_text:
        raise ValueError(f"{label} cannot be blank.")

    candidate = Path(candidate_text).expanduser()
    display_path = candidate.resolve(strict=False)

    if candidate.is_dir():
        raise ValueError(
            f"{label} points to a folder, not a file.\n"
            f"Entered value : {candidate_text}\n"
            f"Checked path  : {display_path}\n"
            "Tip: Enter the filename or the full path to the file."
        )

    if not candidate.exists():
        message = [
            f"{label} was not found.",
            f"Entered value : {candidate_text}",
            f"Checked path  : {display_path}",
        ]
        if not candidate.is_absolute():
            message.append(f"Current folder: {Path.cwd()}")
            message.append(
                "Tip: If the file is in this folder, enter only the filename."
            )
            message.append("     Otherwise, enter the full path to the file.")
        raise ValueError("\n".join(message))

    if not candidate.is_file():
        raise ValueError(f"{label} is not a file: {display_path}")

    if allowed_extensions and candidate.suffix.lower() not in allowed_extensions:
        ext_list = ", ".join(sorted(allowed_extensions))
        raise ValueError(
            f"{label} has an unsupported extension.\n"
            f"Entered file        : {display_path}\n"
            f"Supported extensions: {ext_list}"
        )

    return candidate.resolve()


def resolve_existing_docx(candidate_text: str, label: str = "Word document") -> Path:
    return resolve_existing_file(candidate_text, label, {".docx"})


def resolve_existing_folder(
    candidate_text: str, label: str, required_glob: str = ""
) -> Path:
    candidate_text = clean_user_path(candidate_text)
    if not candidate_text:
        raise ValueError(f"{label} cannot be blank.")

    candidate = Path(candidate_text).expanduser()
    display_path = candidate.resolve(strict=False)

    if not candidate.exists():
        message = [
            f"{label} folder was not found.",
            f"Entered value : {candidate_text}",
            f"Checked path  : {display_path}",
        ]
        if not candidate.is_absolute():
            message.append(f"Current folder: {Path.cwd()}")
            message.append(
                "Tip: If the folder is in this folder, enter only the folder name."
            )
            message.append("     Otherwise, enter the full path to the folder.")
        raise ValueError("\n".join(message))

    if not candidate.is_dir():
        raise ValueError(
            f"{label} must be a folder, but the path is a file.\n"
            f"Entered value : {candidate_text}\n"
            f"Checked path  : {display_path}"
        )

    if required_glob and not any(candidate.glob(required_glob)):
        raise ValueError(
            f"{label} does not contain files matching {required_glob}.\n"
            f"Entered value : {candidate_text}\n"
            f"Checked path  : {display_path}"
        )

    return candidate.resolve()


def resolve_output_file(
    candidate_text: str | None,
    default_path: Path | str,
    extension: str,
    label: str = "Output file",
) -> Path:
    """Resolve an output path, applying the requested extension when needed."""
    candidate_text = clean_user_path(candidate_text)
    candidate = (
        Path(candidate_text).expanduser() if candidate_text else Path(default_path)
    )
    extension = extension.lower()
    extension = extension if extension.startswith(".") else f".{extension}"

    if candidate.suffix.lower() != extension:
        candidate = candidate.with_suffix(extension)

    display_path = candidate.resolve(strict=False)
    parent = candidate.parent.resolve(strict=False)

    if not parent.exists():
        raise ValueError(
            f"{label} folder does not exist.\n"
            f"Entered value : {candidate_text if candidate_text else str(default_path)}\n"
            f"Folder checked: {parent}\n"
            "Tip: Enter a filename only to save in the current folder, "
            "or enter a full path to an existing folder."
        )

    if candidate.exists() and candidate.is_dir():
        raise ValueError(
            f"{label} path points to a folder, not a file.\n"
            f"Checked path: {display_path}"
        )

    return display_path


def resolve_output_docx(
    candidate_text: str | None,
    default_path: Path | str,
    label: str = "Output Word document",
) -> Path:
    return resolve_output_file(candidate_text, default_path, ".docx", label)


def resolve_output_png(
    candidate_text: str | None, default_path: Path | str, label: str = "Output PNG"
) -> Path:
    return resolve_output_file(candidate_text, default_path, ".png", label)


def resolve_output_json(
    candidate_text: str | None, default_path: Path | str, label: str = "Output JSON"
) -> Path:
    return resolve_output_file(candidate_text, default_path, ".json", label)


def docx_contains_text_or_style(
    path: Path, style_id: str = "", required_text: str = ""
) -> bool:
    try:
        with zipfile.ZipFile(path, "r") as package:
            names = set(package.namelist())
            document_xml = package.read("word/document.xml").decode(
                "utf-8", errors="ignore"
            )
            styles_xml = (
                package.read("word/styles.xml").decode("utf-8", errors="ignore")
                if "word/styles.xml" in names
                else ""
            )
    except (OSError, KeyError, zipfile.BadZipFile):
        return False

    style_ok = not style_id or style_id in document_xml or style_id in styles_xml
    text_ok = not required_text or required_text.lower() in document_xml.lower()
    return style_ok and text_ok


def discover_docx_template(
    style_id: str = "", required_text: str = "", script_file: str | None = None
) -> Path | None:
    script_dir = Path(script_file).resolve().parent if script_file else Path.cwd()
    search_dirs = []
    for folder in (
        Path.cwd(),
        script_dir,
        script_dir / "Templates",
        script_dir.parent / "Templates",
    ):
        resolved = folder.resolve(strict=False)
        if resolved.exists() and resolved.is_dir() and resolved not in search_dirs:
            search_dirs.append(resolved)

    candidates = []
    for folder in search_dirs:
        for pattern in ("*.docx", "*.dotx"):
            for path in folder.glob(pattern):
                if path.name.startswith("~$"):
                    continue
                if docx_contains_text_or_style(
                    path, style_id=style_id, required_text=required_text
                ):
                    candidates.append(path.resolve())

    generated_markers = (
        ".dbinfo",
        ".filldb",
        "withdbinfo",
        "withfilldb",
        "withloop",
        "injection_test",
        "perfmon_multichart",
        "deployment_overview",
        "loop_device",
    )

    def score(path: Path) -> tuple:
        name = path.name.lower()
        folder = path.parent.name.lower()
        return (
            0 if "template" in folder else 1,
            0 if "template" in name or "example" in name else 1,
            1 if any(marker in name for marker in generated_markers) else 0,
            len(name),
            str(path).lower(),
        )

    return sorted(set(candidates), key=score)[0] if candidates else None


def skip_section_rule(doc_xml: str, pos: int) -> int:
    """Advance ``pos`` past a section heading's decorative rule image.

    Template section headings are followed by a small rule graphic (a drawing).
    Injectors that replace the zone *starting* at the heading end would delete
    that rule along with the old body. Call this on the zone start so the rule
    is preserved. Our injected charts are named ``Chart<id>``: those are NOT
    preserved (a re-run must still replace a prior chart). Empty paragraphs
    before the rule are stepped over; the first real (text) paragraph stops the
    scan with ``pos`` unchanged.
    """
    for m in re.finditer(r"<w:p\b[^>]*>.*?</w:p>", doc_xml[pos:], re.DOTALL):
        para = m.group()
        if "<w:drawing" in para:
            if re.search(r'name="Chart\d+"', para):
                return pos  # a previously-injected chart: let it be replaced
            return pos + m.end()  # decorative rule: keep it out of the zone
        if re.sub(r"<[^>]+>", "", para).strip():
            return pos  # real content reached before any rule
    return pos


def keep_section_rule(
    doc_xml: str, zone_start: int, zone_end: int, body_xml: str
) -> str:
    """Re-insert a section heading's decorative rule into replacement body XML.

    For injectors that replace a whole section (the heading is rebuilt inside
    ``body_xml``), the original heading's rule lives inside the replaced zone and
    would be lost. Lift it out of ``doc_xml[zone_start:zone_end]`` and splice it
    back into ``body_xml`` right after the body's first paragraph (the rebuilt
    heading). The rule is a vector line group (``prst="line"``) with no image
    relationship, so its XML is safe to relocate. No-op when no rule is found.
    """
    rule = ""
    for m in re.finditer(
        r"<w:p\b[^>]*>.*?</w:p>", doc_xml[zone_start:zone_end], re.DOTALL
    ):
        if 'prst="line"' in m.group():
            rule = m.group()
            break
    if not rule:
        return body_xml
    # The rebuilt heading carries keep_with_next (via the Heading1/2/3 style),
    # which only chains to the very next paragraph. Without keepNext on the
    # relocated rule too, that chain stops at the rule -- Word can still drop
    # a page break between the rule and the real lead-in/chart content right
    # after it, stranding the heading+rule on one page and the body on the
    # next. Give the rule the same keepNext so the whole group moves together.
    rule = _add_keep_next(rule)
    after_first = re.search(r"</w:p>", body_xml)
    if not after_first:
        return rule + body_xml
    return body_xml[: after_first.end()] + rule + body_xml[after_first.end() :]


def _add_keep_next(paragraph_xml: str) -> str:
    """Return paragraph_xml with <w:keepNext/> ensured in its <w:pPr>."""
    ppr_m = re.search(r"<w:pPr>(.*?)</w:pPr>", paragraph_xml, re.DOTALL)
    if ppr_m is None:
        open_tag = re.search(r"<w:p\b[^>]*>", paragraph_xml)
        if open_tag is None:
            return paragraph_xml
        open_tag_end = open_tag.end()
        return (
            paragraph_xml[:open_tag_end]
            + "<w:pPr><w:keepNext/></w:pPr>"
            + paragraph_xml[open_tag_end:]
        )
    if "<w:keepNext" in ppr_m.group(1):
        return paragraph_xml
    insert_at = ppr_m.start() + len("<w:pPr>")
    return paragraph_xml[:insert_at] + "<w:keepNext/>" + paragraph_xml[insert_at:]
