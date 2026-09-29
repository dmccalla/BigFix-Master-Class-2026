#!/usr/bin/env python3
# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""html_charts.py -- render report infographics from the design HTML, exactly.

The design handoff's `chart_afters.html` is the source of truth for every chart
(START_HERE: "Exact chart markup/styles -> chart_afters.html ... the renders
come from this"). Rather than reconstruct that design in matplotlib (which drifts
chart by chart), we render the design markup itself: inject the real data into a
data-driven copy of that HTML and screenshot each chart with a headless browser.
The PNG is the design, pixel for pixel -- deviation is impossible by construction.

Rendering uses Playwright driving the *system* Chrome/Edge (channel="chrome" /
"msedge"), so no Chromium download is required -- a Chromium-based browser just
has to be present (Edge ships with Windows). One browser is launched per run and
reused across charts.

Public API:
    render_chart(chart, data, output_png)      # one chart
    render_charts([(chart, data, png), ...])    # batch, one browser

`chart` is a template chart id ("loop", "balance", "scorecard", "platformhealth",
"opmaturity", "perfmon", "dashboard", "risks", "strengths", "filldb",
"overview", "snapshot"). `data` is the chart's data dict (see
Assets/chart_template.html for each chart's shape).
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import functools
import json
import logging
import os
import subprocess
import sys
from pathlib import Path

from Lib.Core.subprocess_window import CREATE_NO_WINDOW
from Lib.Design import status_spine

_ROOT = Path(__file__).resolve().parents[2]
_TEMPLATE = _ROOT / "Assets" / "chart_template.html"
_FONT_DIR = _ROOT / "Fonts" / "Roboto"
_FONT_FILES = (
    ("Roboto", 400, _FONT_DIR / "Roboto-Regular.ttf"),
    ("Roboto", 700, _FONT_DIR / "Roboto-Bold.ttf"),
    ("Roboto Condensed", 700, _FONT_DIR / "RobotoCondensed-Bold.ttf"),
)
_DEFAULT_SCALE = 1.0
# Reference chart PNGs are 2250px wide, authored natively at that size.
# 2250px at 7.5in placement = 300 DPI. Type floor is 38px = 9.1pt.
_REPORT_CARD_WIDTH = 2250
_TYPE_FLOOR_NATIVE_PX = 38.0
_TYPE_SCALE = 1.0


@functools.lru_cache(maxsize=1)
def _fontface() -> str:
    """Build base64-embedded @font-face blocks for the reference chart fonts."""
    blocks: list[str] = []
    for family, weight, path in _FONT_FILES:
        if not path.is_file():
            raise FileNotFoundError(f"Required chart font is missing: {path}")
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        blocks.append(
            f"@font-face{{font-family:'{family}';"
            f"src:url(data:font/ttf;base64,{b64}) format('truetype');"
            f"font-weight:{weight};font-style:normal;font-display:block;}}"
        )
    return f"<style>{''.join(blocks)}</style>"


def _build_html(
    chart: str,
    data: dict,
    card_width: int | None = None,
    type_floor_css_px: float | None = None,
    type_scale: float | None = None,
) -> str:
    """Inject the embedded font and {chart, data} into the design template.

    ``card_width`` overrides the rendered card width (CSS px). The design cards
    are authored natively at 2250px for 300 DPI placement at 7.5 in in Word.
    An optional card_width allows rendering at different widths for testing;
    the card content reflows (sub-text wraps, cards grow taller): only width
    changes, not the design's palette.
    """
    template = _TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps({"chart": chart, **data})
    spine = json.dumps(status_spine.chart_palette())
    floor = type_floor_css_px or (_TYPE_FLOOR_NATIVE_PX / _DEFAULT_SCALE)
    scale = _TYPE_SCALE if type_scale is None else type_scale
    html = template.replace("<!--__FONTFACE__-->", _fontface()).replace(
        "/*__DATA__*/",
        (
            f"window.SPINE = {spine};\n"
            f"window.CHART_TYPE_SCALE = {scale:.6f};\n"
            f"window.CHART_TYPE_FLOOR_CSS_PX = {floor:.6f};\n"
            f"window.DATA = {payload};"
        ),
    )
    if card_width:
        html = html.replace(
            "</head>",
            f"<style>.card,.dashcard,.snapshot{{width:{card_width}px !important;}}</style></head>",
            1,
        )
    return html


def _browser_channels():
    """System browser channels to try, in order (no Chromium download)."""
    if sys.platform == "win32":
        return ("msedge", "chrome")
    return ("chrome", "msedge")


@functools.lru_cache(maxsize=1)
def _ensure_playwright_browser_windows_hidden() -> None:
    """Patch Playwright's Windows browser spawn to avoid console flashes."""
    if sys.platform != "win32":
        return
    try:
        import playwright

        bundle = (
            Path(playwright.__file__).resolve().parent
            / "driver"
            / "package"
            / "lib"
            / "coreBundle.js"
        )
        text = bundle.read_text(encoding="utf-8")
        if (
            'detached: process.platform !== "win32",\n'
            "    env: options2.env,\n"
            "    cwd: options2.cwd,\n"
            "    shell: options2.shell,\n"
            "    stdio,\n"
            "    windowsHide: true\n"
            "  };"
        ) in text:
            return
        needle = (
            'detached: process.platform !== "win32",\n'
            "    env: options2.env,\n"
            "    cwd: options2.cwd,\n"
            "    shell: options2.shell,\n"
            "    stdio\n"
            "  };"
        )
        replacement = (
            'detached: process.platform !== "win32",\n'
            "    env: options2.env,\n"
            "    cwd: options2.cwd,\n"
            "    shell: options2.shell,\n"
            "    stdio,\n"
            "    windowsHide: true\n"
            "  };"
        )
        if needle in text:
            bundle.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    except Exception:
        return


@contextlib.contextmanager
def _hide_playwright_driver_window():
    """Add CREATE_NO_WINDOW to Playwright's internal driver launch on Windows."""
    if sys.platform != "win32":
        yield
        return

    original = asyncio.create_subprocess_exec

    async def hidden_create_subprocess_exec(*args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | CREATE_NO_WINDOW
        startupinfo = kwargs.get("startupinfo")
        if startupinfo is None:
            startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
        return await original(*args, **kwargs)

    asyncio.create_subprocess_exec = hidden_create_subprocess_exec
    try:
        yield
    finally:
        asyncio.create_subprocess_exec = original


def _launch_chart_browser(playwright):
    last_err: Exception | None = None
    for channel in _browser_channels():
        try:
            return playwright.chromium.launch(channel=channel, headless=True)
        except Exception as exc:  # depends on host browsers
            last_err = exc
    raise RuntimeError(
        "No system Chromium-based browser found for chart rendering. "
        "Install Google Chrome or Microsoft Edge (Edge ships with "
        f"Windows). Last error: {last_err}"
    ) from last_err


def _close_chart_resource(resource) -> None:
    """Preserve an active rendering error if cleanup also fails."""
    if sys.exc_info()[0] is None:
        resource.close()
    else:
        with contextlib.suppress(Exception):
            resource.close()


def _validate_chart_destination(output: str | Path) -> None:
    """Reject Windows destinations that exceed the conventional file-path limit."""
    if sys.platform != "win32":
        return
    out = Path(os.path.abspath(output))
    sidecar = out.parent / f"{out.stem}.chartdata.json"
    for destination in (out, sidecar):
        length = len(str(destination).encode("utf-16-le")) // 2
        if length >= 260:
            raise ValueError(
                f"Chart output path is too long ({length} UTF-16 units; maximum 259): "
                f"{destination}. Choose a shorter output folder or run name."
            )


def render_charts(
    jobs: list[tuple[str, dict, str | Path]],
    *,
    scale: float = _DEFAULT_SCALE,
    card_width: int | None = _REPORT_CARD_WIDTH,
    type_floor_native_px: float = _TYPE_FLOOR_NATIVE_PX,
    type_scale: float | None = None,
) -> list[Path]:
    """Render charts, allowing one browser-closure recovery per batch."""
    for _, _, output in jobs:
        _validate_chart_destination(output)
    _ensure_playwright_browser_windows_hidden()

    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright

    outputs: list[Path] = []
    with _hide_playwright_driver_window(), sync_playwright() as p:
        browser = _launch_chart_browser(p)
        retried = False
        try:
            for chart, data, output in jobs:
                out = Path(output)
                out.parent.mkdir(parents=True, exist_ok=True)
                html = _build_html(
                    chart,
                    data,
                    card_width,
                    type_floor_css_px=type_floor_native_px / scale,
                    type_scale=type_scale,
                )
                while True:
                    try:
                        # Fresh pages keep readiness state local to this attempt.
                        page = browser.new_page(device_scale_factor=scale)
                        try:
                            page.set_content(html, wait_until="networkidle")
                            page.wait_for_function("window.__RENDERED__ === true")
                            page.locator("#mount").screenshot(path=str(out))
                        finally:
                            _close_chart_resource(page)
                        break
                    except PlaywrightTimeoutError:
                        raise
                    except PlaywrightError as exc:
                        target_closed = (
                            "Target page, context or browser has been closed" in str(exc)
                        )
                        if retried or (browser.is_connected() and not target_closed):
                            raise
                        retried = True
                        logging.getLogger(__name__).warning(
                            "Chart browser closed while rendering %s (%s); "
                            "retrying once. Error: %s",
                            chart,
                            out,
                            exc,
                        )
                        _close_chart_resource(browser)
                        browser = None
                        browser = _launch_chart_browser(p)
                # Drop a human-readable sidecar with the exact data this PNG
                # was rendered from, so the chart can be re-rendered later
                # (Build/regenerate_charts.py) without re-collecting data
                # and so a chart you disagree with can be fixed by editing
                # this JSON instead of deleting the whole image.
                sidecar = out.parent / f"{out.stem}.chartdata.json"
                sidecar.write_text(
                    json.dumps({"chart": chart, **data}, indent=2),
                    encoding="utf-8",
                )
                outputs.append(out)
        finally:
            if browser is not None:
                _close_chart_resource(browser)
    return outputs


def render_chart(
    chart: str,
    data: dict,
    output_png: str | Path,
    *,
    scale: float = _DEFAULT_SCALE,
    card_width: int | None = _REPORT_CARD_WIDTH,
    type_floor_native_px: float = _TYPE_FLOOR_NATIVE_PX,
    type_scale: float | None = None,
) -> Path:
    """Render a single chart from the design template to a PNG."""
    return render_charts(
        [(chart, data, output_png)],
        scale=scale,
        card_width=card_width,
        type_floor_native_px=type_floor_native_px,
        type_scale=type_scale,
    )[0]
