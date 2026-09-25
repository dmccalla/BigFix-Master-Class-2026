# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Windows subprocess window helpers."""

from __future__ import annotations

import subprocess
import sys

CREATE_NO_WINDOW = 0x08000000
CREATE_NEW_PROCESS_GROUP = 0x00000200


def hidden_subprocess_kwargs(*, new_process_group: bool = False) -> dict:
    """Return kwargs that keep child processes hidden on Windows."""
    if sys.platform != "win32":
        return {}

    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)

    creationflags = CREATE_NO_WINDOW
    if new_process_group:
        creationflags |= CREATE_NEW_PROCESS_GROUP

    return {
        "creationflags": creationflags,
        "startupinfo": startupinfo,
    }
