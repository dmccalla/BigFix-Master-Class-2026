#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Capture the Lab Guide's task screenshots from the .bes source files.

Each task's description HTML is rendered in the installed Edge or Chrome,
the way the console shows it, and the presentation block is screenshotted.

    uv run python Utilities/capture_lab_guide_task_screenshots.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from defusedxml import ElementTree as ET
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_ROOT = PROJECT_ROOT / "Tasks and Analyses"
OUTPUT_DIR = PROJECT_ROOT / "Docs" / "Lab_Guide_Assets"

CAPTURES = (
    (
        TASK_ROOT
        / "Analyses"
        / "BigFix Master Class -- Client Performance Counters - Basic (2.0).bes",
        "lg-task-01-agent-performance-analysis.png",
        700,
    ),
    (
        TASK_ROOT
        / "Individual Tasks"
        / "BigFix Master Class -- Collect Client Performance Counter Analysis Data (2.0).bes",
        "lg-task-02-collect-agent-performance.png",
        1200,
    ),
    (
        TASK_ROOT
        / "Individual Tasks"
        / "BigFix Master Class -- Setup and Run Perfmon Counters (2.0).bes",
        "lg-task-03-setup-perfmon.png",
        900,
    ),
    (
        TASK_ROOT
        / "Individual Tasks"
        / "BigFix Master Class -- Enable FillDB Performance Logging (2.0).bes",
        "lg-task-04-enable-filldb-logging.png",
        1200,
    ),
)


def description_html(path: Path) -> str:
    root = ET.parse(path).getroot()
    description = root.find(".//Description")
    if description is None or not description.text:
        raise ValueError(f"No Description HTML found in {path}")
    return re.sub(
        r"<script\b[^>]*>.*?</script>",
        "",
        description.text,
        flags=re.IGNORECASE | re.DOTALL,
    )


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = [str(path) for path, _name, _height in CAPTURES if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing BES source files:\n" + "\n".join(missing))

    with sync_playwright() as playwright:
        browser = None
        errors: list[str] = []
        for options in ({"channel": "msedge"}, {"channel": "chrome"}, {}):
            try:
                browser = playwright.chromium.launch(headless=True, **options)
                break
            except Exception as exc:  # pragma: no cover - depends on host browser
                errors.append(str(exc))
        if browser is None:
            raise RuntimeError("Could not start a browser:\n" + "\n".join(errors))

        page = browser.new_page(
            viewport={"width": 1120, "height": 1000},
            device_scale_factor=1,
        )
        for source, filename, max_height in CAPTURES:
            markup = (
                "<!doctype html><html><head><meta charset='utf-8'>"
                "<style>html,body{margin:0;background:#fff;}body{padding:12px;}</style>"
                f"</head><body>{description_html(source)}</body></html>"
            )
            page.set_content(markup, wait_until="load")
            task_view = page.locator(".hc, .hc-wrap").first
            task_view.wait_for(state="visible")
            box = task_view.bounding_box()
            if box is None:
                raise RuntimeError(f"Task presentation did not render for {source}")
            width = min(1080, int(box["width"]) + 2)
            height = min(max_height, int(box["height"]) + 2)
            # End the capture above the reference sections so no sentence is
            # cut in half. The analysis has none of them and keeps its height.
            cutoff = page.evaluate(
                """() => {
                    const heads = Array.from(document.querySelectorAll('.hc-sec'));
                    const stop = heads.find(h => /^(Supported Platforms|Action log note|Version and Release Notes)/.test(h.textContent.trim()));
                    return stop ? stop.getBoundingClientRect().top : null;
                }"""
            )
            if cutoff is not None:
                above = int(cutoff - box["y"]) - 10
                # A short task keeps its full height when the first reference
                # section sits near the top of the presentation.
                if above >= 0.6 * box["height"]:
                    height = min(max_height, above)
            output = OUTPUT_DIR / filename
            page.screenshot(
                path=output,
                clip={
                    "x": max(0, box["x"]),
                    "y": max(0, box["y"]),
                    "width": width,
                    "height": height,
                },
            )
            print(
                f"captured {output.relative_to(PROJECT_ROOT)} "
                f"({width}x{height}) from {source.name}"
            )
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
