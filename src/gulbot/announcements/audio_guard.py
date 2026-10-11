"""Tiny independent audio janitor: also survives a hard-killed prefork child.

The worker creates a private direct child of STT_AUDIO_DIR, starts this guardian
BEFORE downloading audio, and removes the directory in its normal finally.
The guardian scrubs within one polling interval after parent death or deadline.
It handles only cp22-audio-* direct children, never arbitrary supplied paths.
"""

from __future__ import annotations

import ctypes
import os
import shutil
import sys
import time
from pathlib import Path


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        kernel = ctypes.windll.kernel32
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(code))) and code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def scrub(directory: Path, root: Path) -> None:
    if (
        directory.is_symlink()
        or directory.resolve().parent != root.resolve()
        or not directory.name.startswith("cp22-audio-")
    ):
        raise ValueError("refusing audio cleanup outside the dedicated directory")
    shutil.rmtree(directory, ignore_errors=True)


def watch(directory: Path, root: Path, pid: int, seconds: int = 450) -> None:
    deadline = time.monotonic() + seconds
    while directory.exists() and alive(pid) and time.monotonic() < deadline:
        time.sleep(0.5)
    scrub(directory, root)


if __name__ == "__main__":
    watch(Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3]))
