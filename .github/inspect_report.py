# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""Render the generated report and retain page images and layout findings."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

import pypdfium2 as pdfium


def inspect_report(document: Path, output: Path, soffice: str) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    profile = output / "office-profile"
    result = subprocess.run(
        [
            soffice,
            "-env:UserInstallation=" + profile.resolve().as_uri(),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output),
            str(document.resolve()),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
        stdin=subprocess.DEVNULL,
    )
    (output / "office.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    pdf_path = output / (document.stem + ".pdf")
    if result.returncode or not pdf_path.is_file():
        raise RuntimeError("Report conversion failed. See " + str(output / "office.log"))
    issues = []
    pages = []
    texts = []
    with pdfium.PdfDocument(pdf_path) as pdf:
        if not len(pdf):
            raise ValueError("Rendered report has no pages")
        for index in range(len(pdf)):
            page = pdf[index]
            textpage = page.get_textpage()
            text = textpage.get_text_range()
            texts.append(text)
            width, height = page.get_size()
            textpage.count_rects()
            for rect_index in range(textpage.count_rects()):
                left, bottom, right, top = textpage.get_rect(rect_index)
                if left < -1 or bottom < -1 or right > width + 1 or top > height + 1:
                    issues.append(
                        {
                            "page": index + 1,
                            "issue": "text outside page",
                            "rect": [left, bottom, right, top],
                        }
                    )
            bitmap = page.render(scale=1.25)
            image = bitmap.to_pil()
            image_path = output / f"page-{index + 1:02d}.png"
            image.save(image_path)
            pages.append(
                {
                    "page": index + 1,
                    "image": image_path.name,
                    "text_characters": len(text.strip()),
                }
            )
            bitmap.close()
            textpage.close()
            page.close()
    joined = " ".join(" ".join(texts).split())
    for expected in (
        "Evaluation Frequency",
        "Cost of Repeated Evaluations",
        "QA Every Report",
        "CLT-02",
        "35.8",
    ):
        if expected not in joined:
            issues.append({"issue": "expected report content missing", "text": expected})
    review_notes = []
    label = "QA Every Report"
    if label in joined and not any(label in " ".join(text.split()) for text in texts):
        review_notes.append(
            "The known property label spans a page boundary. Review table row pagination in Word."
        )
    (output / "report-text.txt").write_text("\n".join(texts), encoding="utf-8")
    report = {
        "passed": not issues,
        "renderer": "LibreOffice/PDFium",
        "pages": pages,
        "issues": issues,
        "review_notes": review_notes,
    }
    (output / "layout-results.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--soffice",
        default=shutil.which("soffice")
        or "C:/Program Files/LibreOffice/program/soffice.exe",
    )
    args = parser.parse_args()
    result = inspect_report(args.document, args.output, args.soffice)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["passed"] else 1)
