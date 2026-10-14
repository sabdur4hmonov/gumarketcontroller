"""Build public text sidecars once; never compress private pages/photos."""

from __future__ import annotations

import gzip
from pathlib import Path
from typing import TypedDict

import brotli
from scripts.cp25_load.resources import available_mib

from gulbot.web.render import STATIC

TEXT_SUFFIXES = frozenset({".css", ".js", ".svg"})


class AssetSizes(TypedDict):
    asset: str
    raw: int
    gzip: int
    brotli: int


def compress(root: Path) -> list[AssetSizes]:
    root = root.resolve()
    sizes: list[AssetSizes] = []
    for path in sorted(root.rglob("*")):
        if path.suffix not in TEXT_SUFFIXES or path.is_symlink() or not path.is_file():
            continue
        if not path.resolve().is_relative_to(root):
            raise ValueError("Static asset escapes the public root")
        raw = path.read_bytes()
        if len(raw) > 1_048_576:
            raise ValueError("Static text asset exceeds the bounded compression input")
        gz = gzip.compress(raw, compresslevel=6, mtime=0)
        br = brotli.compress(raw, quality=6)
        for extension, data in ((".gz", gz), (".br", br)):
            output = path.with_suffix(path.suffix + extension)
            if output.is_symlink():
                raise ValueError("Cannot overwrite a symlink sidecar")
            # Same-directory atomic replace; rebuilding cannot serve partial output.
            temporary = path.with_suffix(path.suffix + extension + ".tmp")
            if temporary.is_symlink():
                raise ValueError("Cannot write a symlink temporary sidecar")
            temporary.write_bytes(data)
            temporary.replace(output)
        sizes.append(
            {
                "asset": path.relative_to(root).as_posix(),
                "raw": len(raw),
                "gzip": len(gz),
                "brotli": len(br),
            }
        )
    return sizes


def main() -> None:
    if available_mib() < 768:
        raise SystemExit("Waiting for RAM: static compression needs768MiB; no retry")
    sizes = compress(STATIC)
    print(f"Public assets: {len(sizes)}")
    for key, total in (
        ("raw", sum(row["raw"] for row in sizes)),
        ("gzip", sum(row["gzip"] for row in sizes)),
        ("brotli", sum(row["brotli"] for row in sizes)),
    ):
        print(key, total, "bytes")


if __name__ == "__main__":
    main()
