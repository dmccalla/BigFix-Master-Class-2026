# Copyright (c) 2026 Duncan McCalla
# SPDX-License-Identifier: MIT
#
# Master Class Diagnostics Workbench
# See the LICENSE and NOTICE files in the project root for license text and attribution.

"""Low-overhead performance evidence for the Master Class Workbench.

The recorder is deliberately dependency-free and safe to use from worker
threads. It captures compact, JSON-serializable timing and resource evidence
that can accompany a test run without changing the generated diagnostics.
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any


class _ProcessMemoryCountersEx(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("PageFaultCount", ctypes.c_uint32),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivateUsage", ctypes.c_size_t),
    ]


def process_resource_metrics() -> dict[str, float | int]:
    """Return inexpensive process metrics without adding a psutil dependency."""
    if os.name != "nt":
        return {}
    try:
        kernel32 = ctypes.windll.kernel32
        psapi = ctypes.windll.psapi
        user32 = ctypes.windll.user32
        kernel32.GetCurrentProcess.restype = ctypes.c_void_p
        handle = kernel32.GetCurrentProcess()

        metrics: dict[str, float | int] = {}
        counters = _ProcessMemoryCountersEx()
        counters.cb = ctypes.sizeof(_ProcessMemoryCountersEx)
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessMemoryCountersEx),
            ctypes.c_uint32,
        ]
        psapi.GetProcessMemoryInfo.restype = ctypes.c_int
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            metrics["rss_mb"] = round(counters.WorkingSetSize / (1024 * 1024), 2)
            metrics["private_mb"] = round(counters.PrivateUsage / (1024 * 1024), 2)

        user32.GetGuiResources.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        user32.GetGuiResources.restype = ctypes.c_uint32
        metrics["gdi_objects"] = int(user32.GetGuiResources(handle, 0))
        metrics["user_objects"] = int(user32.GetGuiResources(handle, 1))
        return metrics
    except (AttributeError, OSError, ValueError):
        return {}


class PerformanceRecorder:
    """Bounded, thread-safe timing and resource recorder for one app process."""

    def __init__(self, component: str, *, event_limit: int = 240) -> None:
        self.component = component
        self._started_at = time.perf_counter()
        self._started_wall = datetime.now().astimezone().isoformat(timespec="seconds")
        self._events: deque[dict[str, Any]] = deque(maxlen=event_limit)
        self._metadata: dict[str, Any] = {}
        self._lock = threading.Lock()

    def reset(self, **metadata: Any) -> None:
        """Begin a fresh recording window without allocating a new recorder."""
        with self._lock:
            self._started_at = time.perf_counter()
            self._started_wall = datetime.now().astimezone().isoformat(timespec="seconds")
            self._events.clear()
            self._metadata = dict(metadata)

    def update_metadata(self, **metadata: Any) -> None:
        with self._lock:
            self._metadata.update(metadata)

    def record(
        self,
        name: str,
        *,
        elapsed_ms: float | None = None,
        detail: str = "",
        **metadata: Any,
    ) -> None:
        """Add a compact event; callers may safely invoke this from workers."""
        event: dict[str, Any] = {
            "time": datetime.now().astimezone().isoformat(timespec="seconds"),
            "name": str(name),
        }
        if elapsed_ms is not None:
            event["elapsed_ms"] = round(max(0.0, float(elapsed_ms)), 2)
        if detail:
            event["detail"] = str(detail)
        event.update(metadata)
        with self._lock:
            self._events.append(event)

    def snapshot(self, **metadata: Any) -> dict[str, Any]:
        """Return JSON-ready evidence without paths, captured input, or secrets."""
        with self._lock:
            payload_metadata = {**self._metadata, **metadata}
            events = list(self._events)
            started = self._started_wall
            elapsed_ms = (time.perf_counter() - self._started_at) * 1000
        return {
            "schema_version": 1,
            "component": self.component,
            "started": started,
            "generated": datetime.now().astimezone().isoformat(timespec="seconds"),
            "elapsed_ms": round(max(0.0, elapsed_ms), 2),
            "runtime": {
                "python": sys.version.split()[0],
                "platform": platform.platform(),
                "pid": os.getpid(),
            },
            "metadata": payload_metadata,
            "events": events,
        }

    def write_json(self, path: Path | str, **metadata: Any) -> Path:
        """Write the snapshot atomically enough for a completed run artifact."""
        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.snapshot(**metadata), indent=2, default=str) + "\n",
            encoding="utf-8",
        )
        return destination
