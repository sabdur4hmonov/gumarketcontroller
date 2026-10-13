"""Resource counters without a model, benchmark package, or external process."""

from __future__ import annotations

import ctypes
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def rss_mib() -> float:
    if sys.platform == "win32":

        class Counters(ctypes.Structure):
            _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
                (name, ctypes.c_size_t)
                for name in (
                    "peak",
                    "working",
                    "paged_peak",
                    "paged",
                    "nonpaged_peak",
                    "nonpaged",
                    "pagefile",
                    "pagefile_peak",
                )
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = ctypes.c_void_p
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(Counters),
            ctypes.c_ulong,
        ]
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if not psapi.GetProcessMemoryInfo(
            kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return float(counters.peak / 1048576)
    if sys.platform.startswith("linux"):
        import resource

        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
    raise RuntimeError("Resource measurement supports Windows and Linux")


def available_mib() -> float:
    if sys.platform == "win32":

        class Memory(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong)
                for name in (
                    "total_phys",
                    "available_phys",
                    "total_page",
                    "available_page",
                    "total_virtual",
                    "available_virtual",
                    "extended",
                )
            ]

        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(Memory)]
        if not kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
            raise ctypes.WinError(ctypes.get_last_error())
        return float(memory.available_phys / 1048576)
    with open("/proc/meminfo", encoding="ascii") as stream:
        for line in stream:
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
    raise RuntimeError("Cannot measure free memory")


@dataclass
class Resources:
    started: float = field(default_factory=time.perf_counter)
    cpu_started: float = field(default_factory=time.process_time)
    peak_rss_mib: float = 0

    def sample(self) -> None:
        self.peak_rss_mib = max(self.peak_rss_mib, rss_mib())

    def result(self) -> dict[str, float | int]:
        self.sample()
        elapsed = max(time.perf_counter() - self.started, 0.000001)
        cpu = time.process_time() - self.cpu_started
        return {
            "pid": os.getpid(),
            "elapsed_s": round(elapsed, 3),
            "cpu_seconds": round(cpu, 3),
            "cpu_percent_one_core": round(cpu / elapsed * 100, 2),
            "peak_rss_mib": round(self.peak_rss_mib, 2),
        }


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent / 100
    left = int(position)
    right = min(left + 1, len(ordered) - 1)
    return round(ordered[left] + (ordered[right] - ordered[left]) * (position - left), 3)


def atomic_json(path: Path, data: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
    temporary.replace(path)
