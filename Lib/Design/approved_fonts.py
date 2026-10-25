# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Prefer local Office typefaces, with the shipped chart fonts as a fallback."""

from __future__ import annotations

import base64
import functools
import os
import struct
from pathlib import Path


def _font_names(path):
    data = path.read_bytes()
    count = struct.unpack_from(">H", data, 4)[0]
    for i in range(count):
        tag, _, offset, _ = struct.unpack_from(">4sIII", data, 12 + i * 16)
        if tag != b"name":
            continue
        _, records, strings = struct.unpack_from(">HHH", data, offset)
        names = {}
        for j in range(records):
            platform, _, _, name, size, start = struct.unpack_from(
                ">HHHHHH", data, offset + 6 + j * 12
            )
            if name in (1, 2, 16, 17):
                raw = data[offset + strings + start : offset + strings + start + size]
                names[name] = raw.decode(
                    "utf-16-be" if platform in (0, 3) else "latin1", errors="replace"
                )
        return names
    return {}


@functools.lru_cache(maxsize=1)
def _local_body_fonts():
    cloud = (
        Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local")))
        / "Microsoft/FontCache/4/CloudFonts/Aptos"
    )
    windows = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    try:
        candidates = [*cloud.glob("*.ttf"), *windows.glob("aptos*.ttf")]
    except OSError:
        candidates = []
    found = {}
    for path in candidates:
        try:
            names = _font_names(path)
        except (OSError, ValueError, struct.error):
            continue
        if names.get(16, names.get(1)) != "Aptos":
            continue
        style = names.get(17, names.get(2, "")).lower()
        if style in ("regular", "bold"):
            found[style] = path
    return found


def fontface_css(fallback_files):
    """Embed available body fonts; never require a user's font installation.

    Both fallback files ship with each application. The internal CSS alias
    lets the same chart markup use either font without losing its layout.
    No local font is copied into the application or its distribution.
    """
    local = _local_body_fonts()
    if not {"regular", "bold"}.issubset(local):
        local = {}
    fallback = {weight: path for _, weight, path in fallback_files[:2]}
    blocks = []
    for style, weight in (("regular", 400), ("bold", 700)):
        path = local.get(style, fallback[weight])
        try:
            content = path.read_bytes()
        except OSError:
            path = fallback[weight]
            content = path.read_bytes()
        fmt = "opentype" if path.suffix.lower() == ".otf" else "truetype"
        encoded = base64.b64encode(content).decode("ascii")
        blocks.append(
            f"@font-face{{font-family:'Aptos';font-weight:{weight};font-style:normal;font-display:block;src:url(data:font/{path.suffix[1:]};base64,{encoded}) format('{fmt}');}}"
        )
    return "<style>" + "".join(blocks) + "</style>"
