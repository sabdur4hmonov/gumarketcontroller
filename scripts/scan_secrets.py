"""Scan tracked files plus staged/new paths for configured secrets before push.

Print filenames/reasons ONLY, never matching values. Real configured secrets
are compared as bytes, which also covers token suffixes in accidental logs.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path

from pydantic import SecretStr

from gulbot.config import get_settings

# Exact synthetic CP21 TOKEN/OTHER fixtures in test_seed_bot_token.py. No file
# is exempted, and configured secrets are checked before these regex exceptions.
SYNTHETIC_TOKEN_HASHES = {
    "9493ae593b45cbaafce4677cf9fc8cac0be3b9abbab346e69b8274d6623d3766",
    "6ca8602317b0afbc31b395e0f8986fa0c62da7534595cf095438d90fc1a3a4af",
}


def scan(extra: list[Path]) -> int:
    settings = get_settings()
    secrets = [
        v.get_secret_value().encode()
        for v in settings.model_dump().values()
        if isinstance(v, SecretStr) and len(v.get_secret_value()) >= 12
    ]
    # The secret half of a bot token must not escape by losing its public id.
    secrets += [v.split(b":", 1)[1] for v in secrets if b":" in v]
    paths = (
        subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    problems: set[str] = set()
    for path in {*[Path(p) for p in paths if p], *extra}:
        if not path.is_file():
            continue
        if path.name == ".env" or path.name.startswith(".env.") and path.name != ".env.example":
            problems.add(str(path))
        data = path.read_bytes()
        if any(value in data for value in secrets):
            problems.add(str(path))
        for match in re.finditer(rb"\b\d{6,12}:([A-Za-z0-9_-]{35,})\b", data):
            token = match.group(1)
            marker = token.lower()
            fake = (
                b"test" in marker
                or b"marker" in marker
                or len(set(token)) <= 2
                or b"example" in marker
                or hashlib.sha256(match.group()).hexdigest() in SYNTHETIC_TOKEN_HASHES
            )
            if not fake:
                problems.add(str(path))
    if problems:
        print("Possible secret in: " + ", ".join(sorted(problems)))
        return 1
    print(f"Secrets scan passed ({len(paths) - 1} tracked files); no secret values printed.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="*")
    raise SystemExit(scan(parser.parse_args().paths))
