# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
"""Shared geometry for horizontal report meters at the native 2250px width."""

BAR_HEIGHT_PX = 40
BAR_RADIUS_PX = BAR_HEIGHT_PX // 2


def css_tokens() -> str:
    return (
        ":root{"
        f"--progress-bar-height:{BAR_HEIGHT_PX}px;"
        f"--progress-bar-radius:{BAR_RADIUS_PX}px;"
        "}"
    )
