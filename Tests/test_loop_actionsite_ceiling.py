# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT

"""ActionSite size: 10 MB soft warning and 25 MB hard ceiling."""

from __future__ import annotations

import get_loop_health as loop
import pytest


@pytest.mark.parametrize(
    "size_mb,status",
    [
        (None, "Not Assessed"),
        (10.0, "Healthy"),
        (10.5, "Needs Attention"),
        (25.0, "Needs Attention"),
        (25.1, "Critical"),
    ],
)
def test_actionsite_size_status(size_mb, status) -> None:
    assert loop._actionsite_size_status_for_value(size_mb, 10.0, 25.0) == status
