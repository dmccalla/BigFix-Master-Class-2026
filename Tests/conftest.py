# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = PROJECT_ROOT / "App"
GET_DIR = PROJECT_ROOT / "Get"
INJECT_DIR = PROJECT_ROOT / "Inject"
LIB_CORE_DIR = PROJECT_ROOT / "Lib" / "Core"
LIB_ANALYSIS_DIR = PROJECT_ROOT / "Lib" / "Analysis"
LIB_DESIGN_DIR = PROJECT_ROOT / "Lib" / "Design"
LIB_THEMES_DIR = PROJECT_ROOT / "Lib" / "Themes"

# Tests import scripts as modules from the App/Get/Inject folders and the
# shared root modules (chart_theme, input_utils, ...). Mirror the runtime
# search path so import behavior is exercised consistently.
for path in (
    PROJECT_ROOT,
    APP_DIR,
    GET_DIR,
    INJECT_DIR,
    LIB_CORE_DIR,
    LIB_ANALYSIS_DIR,
    LIB_DESIGN_DIR,
    LIB_THEMES_DIR,
):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
