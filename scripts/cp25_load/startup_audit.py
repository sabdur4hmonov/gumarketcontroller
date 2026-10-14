"""Step-boundary RAM/top-process evidence. Warm-only daytime; infrastructure first at night."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .reference_measure import ENTRY, REFERENCE, ROOT, provenance
from .resources import atomic_json, available_mib
from .tonight import note


def snapshot(label: str) -> dict[str, Any]:
    # Process names/PIDs/working sets only; never command lines or environment.
    command = (
        "Get-CimInstance Win32_Process | Sort-Object {[long]$_.WorkingSetSize} -Descending | "
        "Select-Object -First 5 Name,ProcessId,WorkingSetSize | ConvertTo-Json -Compress"
    )
    free = available_mib()
    result = subprocess.run(
        ["pwsh", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=True,
    )
    return {
        "at": datetime.now(UTC).isoformat(),
        "label": label,
        "free_mib": round(free, 2),
        "top5": json.loads(result.stdout),
        "runtime_provenance": provenance(ROOT, "after"),
    }


def step(
    label: str,
    command: list[str],
    records: list[dict[str, Any]],
    output: Path,
    *,
    minimum: int = 1280,
) -> bool:
    before = snapshot(label + ":before")
    records.append(before)
    atomic_json(output / "startup.json", records)
    note(f"Startup {label}: actual precheck {before['free_mib']}MiB.")
    if before["free_mib"] < minimum:
        records.append({"label": label, "status": "waiting for RAM", "required_mib": minimum})
        atomic_json(output / "startup.json", records)
        note(f"Startup {label}: waiting for RAM; no retry.")
        return False
    run = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    (output / (label + ".log")).write_text(run.stdout + run.stderr, encoding="utf-8")
    records.append({"label": label, "exit_code": run.returncode})
    records.append(snapshot(label + ":after"))
    atomic_json(output / "startup.json", records)
    if run.returncode != 0:
        raise RuntimeError(f"Startup {label} failed; inspect its log; no retry")
    return True


def prepare(output: Path, *, warm_only: bool) -> bool:
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []
    if not warm_only and sys.platform == "win32":
        if not step(
            "docker-wsl-start", ["docker", "desktop", "start", "--timeout", "90"], records, output
        ):
            return False
    if warm_only:
        for name in ("gulbot-postgres", "gulbot-redis"):
            running = subprocess.run(
                ["docker", "inspect", "--format", "{{.State.Running}}", name],
                capture_output=True,
                text=True,
                timeout=15,
            )
            if running.returncode != 0 or running.stdout.strip() != "true":
                note("Startup audit: cold Docker/container start waiting for evening RAM.")
                return False
    if not step(
        "docker-wsl", ["docker", "info", "--format", "{{.ServerVersion}}"], records, output
    ):
        return False
    for service in ("postgres", "redis"):
        if not step(
            service,
            [
                "docker",
                "compose",
                "up",
                "-d",
                "--wait",
                "--wait-timeout",
                "60",
                "--no-recreate",
                "--no-build",
                "--pull",
                "never",
                service,
            ],
            records,
            output,
        ):
            return False
    imports = (
        "import json,aiogram,gulbot.worker.tasks;"
        "from scripts.cp25_load.resources import rss_mib;"
        "print(json.dumps({'kind':'imports only; no task run','peak_rss_mib':rss_mib()}))"
    )
    if not step("venv-imports", [sys.executable, "-c", imports], records, output):
        return False
    return step(
        "reference-db-seed",
        [
            sys.executable,
            str(ENTRY),
            "--source",
            str(REFERENCE),
            "--phase",
            "before",
            "--role",
            "seed",
            "--shops",
            "2",
            "--output",
            str(output / "seed-only"),
        ],
        records,
        output,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warm-only", action="store_true")
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / ".cp22-stage/cp25"):
        raise SystemExit("Startup audit must stay in owned staging")
    if not prepare(output, warm_only=args.warm_only):
        raise SystemExit(3)


if __name__ == "__main__":
    main()
