#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Capture the Lab Guide's Workbench screenshots from the desktop app.

The captures come from ``DiagnosticsWorkbenchUI`` itself, driven with the
sample capture under ``SampleData``. All app state is redirected to ``Temp``
so the operator's own last-build settings are not touched.

    uv run python Utilities/capture_lab_guide_screenshots.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from PIL import ImageGrab

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CAPTURE_ROOT = PROJECT_ROOT / "Temp" / "Lab_Guide_Capture"
OUTPUT_DIR = PROJECT_ROOT / "Docs" / "Lab_Guide_Assets"
SAMPLE_ROOT = PROJECT_ROOT / "SampleData" / "BigFix Master Class 2026"

os.environ["LOCALAPPDATA"] = str(CAPTURE_ROOT / "LocalAppData")
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "App"))

import customtkinter as ctk  # noqa: E402
import diagnostics_workbench_ui as ui  # noqa: E402


def pump(app: ui.DiagnosticsWorkbenchUI, seconds: float = 0.5) -> None:
    """Process Tk callbacks for a bounded period without entering mainloop."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)


def capture(widget, filename: str) -> Path:
    widget.update_idletasks()
    left = int(widget.winfo_rootx())
    top = int(widget.winfo_rooty())
    width = int(widget.winfo_width())
    height = int(widget.winfo_height())
    if width <= 1 or height <= 1:
        raise RuntimeError(f"Widget has no drawable area: {widget}")
    image = ImageGrab.grab(bbox=(left, top, left + width, top + height))
    path = OUTPUT_DIR / filename
    image.save(path, optimize=True)
    print(f"captured {path.relative_to(PROJECT_ROOT)} ({image.width}x{image.height})")
    return path


def scan_sample(app: ui.DiagnosticsWorkbenchUI) -> None:
    """Run the folder scan on the main thread so the result is deterministic."""
    app.data_root_var.set(str(SAMPLE_ROOT))
    app.output_folder_var.set(str(CAPTURE_ROOT / "Output"))
    app.run_name_var.set("Lab_Run_01")
    found = ui.scan_input_folder(SAMPLE_ROOT)
    ancillary = ui.discover_loop_ancillary_inputs(SAMPLE_ROOT, found.get("loop"))
    app._scan_token += 1
    app._scan_thread = None
    # Hardware detection runs relog in a worker that needs mainloop(). The
    # detected values are filled in directly below instead.
    app._start_perfmon_detection = lambda auto=False: None
    app._scan_inputs_complete(SAMPLE_ROOT, found, ancillary, app._scan_token)
    missing = [key for key, path in found.items() if path is None]
    if missing:
        raise RuntimeError(f"Sample data did not resolve for: {missing}")
    print(app.scan_confirmation_var.get())
    pump(app, 0.5)


def fill_module_inputs(app: ui.DiagnosticsWorkbenchUI) -> None:
    for (key, field), var in app.date_field_vars.items():
        if key == "loop" and not var.get().strip():
            var.set("06-10-2026" if "start" in field else "06-14-2026")
    app.perfmon_processors_var.set("4")
    app.perfmon_disks_var.set("2")
    app.perfmon_memory_var.set("16")
    app.perfmon_vm_var.set(True)


def expand(app: ui.DiagnosticsWorkbenchUI, key: str) -> None:
    app._expand_module_row(key)
    pump(app, 1.0)
    controls = app._module_card_controls.get(key) or {}
    if controls.get("expansion_wrapper") is None:
        raise RuntimeError(f"Details did not expand for {key}")


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (CAPTURE_ROOT / "LocalAppData").mkdir(parents=True, exist_ok=True)
    ctk.set_appearance_mode("light")
    app = ui.DiagnosticsWorkbenchUI()
    app.geometry("1400x980+40+20")
    # The grab is a screen region, so the window must be in front of every
    # other window for the whole run.
    app.attributes("-topmost", True)
    app.lift()
    app.focus_force()
    pump(app, 1.5)
    try:
        capture(app, "lg-01-step-1-first-launch.png")
        scan_sample(app)
        capture(app, "lg-02-step-1-folders-scanned.png")

        app._show_step(2)
        pump(app, 1.5)
        fill_module_inputs(app)
        pump(app, 0.5)
        capture(app, "lg-03-step-2-modules.png")
        for key in ("loop", "perfmon", "filldb"):
            expand(app, key)
            capture(app, f"lg-04-step-2-{key}-details.png")
        app._collapse_module_row()
        pump(app, 0.5)

        app._show_step(3)
        pump(app, 1.5)
        capture(app, "lg-05-step-3-build.png")
    finally:
        app.destroy()
    return 0


if __name__ == "__main__":
    sys.exit(main())
