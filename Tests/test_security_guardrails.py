# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Security guardrails enforced by the test suite.

The Workbench is local-only. It reads collected data files from disk and
writes its outputs to disk. No shipped script may import an HTTP client or
open a network connection, so an attendee can run it inside a locked-down
environment and a scanner finds nothing to ask about.

Two guardrails: the network import ban and the shell ban on subprocesses.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_EXCL_DIRS = {
    ".git",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "Temp",
    "Dist",
    "SampleData",
}

# Modules whose import means the file can make outbound network requests.
# urllib.parse and urllib.error alone are harmless and stay allowed.
_BANNED_MODULES = (
    "urllib.request",
    "http.client",
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc.client",
    "websockets",
    "paramiko",
)

_IMPORT_RE = re.compile(
    r"^\s*(?:import\s+(?P<mod>[\w.]+)|from\s+(?P<pkg>[\w.]+)\s+import\s+(?P<names>.+))",
)
# socket.gethostname() is a local lookup and stays allowed (the run log
# records the host name). Opening a connection is not.
_SOCKET_CONNECT_RE = re.compile(
    r"socket\.(?:socket|create_connection|create_server)\s*\("
)
_SHELL_TRUE_RE = re.compile(r"subprocess\.[A-Za-z_]+\([^)]*shell\s*=\s*True")


def _python_files():
    for path in sorted(ROOT.rglob("*.py")):
        if any(part in _EXCL_DIRS for part in path.relative_to(ROOT).parts):
            continue
        yield path


def _banned_imports(line: str) -> list[str]:
    match = _IMPORT_RE.match(line)
    if match is None:
        return []
    hits = []
    if match.group("mod"):
        module = match.group("mod")
        hits.extend(
            b for b in _BANNED_MODULES if module == b or module.startswith(b + ".")
        )
    else:
        pkg = match.group("pkg")
        names = [n.strip().split(" ")[0] for n in match.group("names").split(",")]
        for banned in _BANNED_MODULES:
            if pkg == banned or pkg.startswith(banned + "."):
                hits.append(banned)
            elif "." in banned:
                parent, child = banned.rsplit(".", 1)
                if pkg == parent and child in names:
                    hits.append(banned)
    return hits


def test_no_network_imports() -> None:
    offenders = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_no, line in enumerate(lines, 1):
            for banned in _banned_imports(line):
                offenders.append(f"{rel}:{line_no} imports {banned}")
            if _SOCKET_CONNECT_RE.search(line):
                offenders.append(f"{rel}:{line_no} opens a socket")
    assert not offenders, "Network access in shipped code:\n  " + "\n  ".join(offenders)


def test_no_shell_subprocesses() -> None:
    offenders = []
    for path in _python_files():
        rel = path.relative_to(ROOT).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _SHELL_TRUE_RE.finditer(text):
            line_no = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{rel}:{line_no} uses shell=True")
    assert not offenders, "Shell subprocesses in shipped code:\n  " + "\n  ".join(
        offenders
    )
