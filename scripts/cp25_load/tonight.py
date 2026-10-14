"""One-shot isolated before/after fleets; gate separately after remaining work."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .resources import available_mib

ROOT = Path(__file__).resolve().parents[2]


def note(message: str) -> None:
    with (ROOT / "docs" / "CP25_STATUS.md").open("a", encoding="utf-8") as stream:
        stream.write(f"\n{datetime.now(UTC).isoformat()} — {message}\n")


def precheck(label: str) -> None:
    free = available_mib()
    note(f"{label}: actual precheck free RAM {free:.2f} MiB.")
    if free < 3072:
        message = f"{label}: precheck refused at {free:.0f} MiB (<3072); no retry."
        note(message)
        raise RuntimeError(message)


def stop_owned(child: subprocess.Popen[Any]) -> None:
    if child.poll() is not None:
        return
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(child.pid), "/T", "/F"],
            capture_output=True,
            timeout=15,
            check=True,
        )
    else:
        import signal

        os.killpg(child.pid, signal.SIGTERM)
    child.wait(timeout=20)


def job(
    label: str, command: list[str], *, cwd: Path, output: Path, environment: dict[str, str]
) -> Path:
    precheck(label)
    log = output / (label + ".log")
    print(f"Starting {label}; log {log}", flush=True)
    with log.open("wb") as stream:
        child = subprocess.Popen(
            command,
            cwd=cwd,
            stdout=stream,
            stderr=subprocess.STDOUT,
            env=environment,
            start_new_session=sys.platform != "win32",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        try:
            while child.poll() is None:
                if available_mib() < 512:
                    note(
                        f"{label}: runtime RAM floor crossed; stopping only owned "
                        f"PID {child.pid}. No retry."
                    )
                    stop_owned(child)
                    raise RuntimeError(f"{label}: memory-aborted, not a passing result")
                time.sleep(0.5)
            if child.returncode != 0:
                note(
                    f"{label}: failed exit {child.returncode}; inspect "
                    f"{log.relative_to(ROOT)}. No retry."
                )
                raise RuntimeError(f"{label} failed; no later jobs launched")
        finally:
            stop_owned(child)
    return log


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--before-ref", default=None)
    gate_options = parser.add_mutually_exclusive_group()
    gate_options.add_argument("--gate-only", action="store_true")
    gate_options.add_argument("--include-gate", action="store_true")
    args = parser.parse_args()
    precheck("tonight bootstrap")
    ref = (
        args.before_ref
        or (ROOT / "docs" / "CP25_BEFORE_REF.txt").read_text(encoding="utf-8").strip()
    )
    commit = subprocess.run(
        ["git", "rev-parse", "--verify", ref + "^{commit}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("Invalid frozen baseline commit")
    output = ROOT / ".cp22-stage" / "cp25" / ("tonight-" + uuid.uuid4().hex)
    output.mkdir(parents=True)
    from .reference_measure import BEFORE, REFERENCE, provenance

    if commit != BEFORE:
        raise ValueError("Use the reviewed immediate pre-change commit f8f73b8")
    if not args.gate_only:
        provenance(REFERENCE, "before")  # exact ref + clean production paths
    base_env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "POSTGRES_TEST_DB": "gulbot_cp25_test",
        "REDIS_DB_BROKER": "6",
        "REDIS_DB_RESULTS": "7",
        "REDIS_DB_TEST": "8",
        "REDIS_DB_FSM": "15",
    }
    try:
        if not args.gate_only:
            for phase, source in (("before", REFERENCE), ("after", ROOT)):
                environment = {
                    **base_env,
                    "PYTHONPATH": str(source / "src") + os.pathsep + str(source),
                }
                for scale in (100, 500, 1000):
                    label = f"{phase}-{scale}"
                    job(
                        label,
                        [
                            sys.executable,
                            "-u",
                            str(ROOT / "scripts/cp25_load/reference_measure.py"),
                            "--source",
                            str(source),
                            "--phase",
                            phase,
                            "--scales",
                            str(scale),
                            "--output",
                            str(output / label),
                        ],
                        cwd=source,
                        output=output,
                        environment=environment,
                    )
            note(
                f"Before/after measurements complete in {output.relative_to(ROOT)}; "
                "assess validity before using the tables."
            )
            if not args.include_gate:
                note(
                    "Measurement queue stops here. Finish remaining focused checks/shadow "
                    "implementation, then use tonight --gate-only. No push."
                )
                return
        environment = {
            **base_env,
            "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT),
            "PYTEST_ADDOPTS": "",
        }
        collection = job(
            "collect",
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts="],
            cwd=ROOT,
            output=output,
            environment=environment,
        )
        count = re.search(r"(\d+) tests collected", collection.read_text(encoding="utf-8"))
        if count is None:
            raise ValueError("Cannot prove full collection count")
        environment["PYTEST_ADDOPTS"] = "--junitxml=" + str(output / "gate.xml")
        job(
            "full-gate",
            ["pwsh", "-NoProfile", "-File", "make.ps1", "check"],
            cwd=ROOT,
            output=output,
            environment=environment,
        )
        import xml.etree.ElementTree as ET

        suite = ET.parse(output / "gate.xml").getroot().find("testsuite")
        if (
            suite is None
            or int(suite.attrib["tests"]) != int(count[1])
            or any(int(suite.attrib.get(key, "0")) for key in ("failures", "errors", "skipped"))
        ):
            raise ValueError("Full gate XML must match collection with zero failures/errors/skips")
        job(
            "secrets",
            [sys.executable, "scripts/scan_secrets.py"],
            cwd=ROOT,
            output=output,
            environment=environment,
        )
        (output / "COMPLETE.json").write_text(
            json.dumps(
                {
                    "before_ref": commit,
                    "after_ref": subprocess.run(
                        ["git", "rev-parse", "HEAD"],
                        cwd=ROOT,
                        capture_output=True,
                        text=True,
                        check=True,
                        timeout=15,
                    ).stdout.strip(),
                    "tests": int(count[1]),
                    "status": "full gate complete; measurement validity and capacity "
                    "review are separate; no push",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        note(
            f"Tonight measurements/gate complete in {output.relative_to(ROOT)}; "
            "no automatic push or merge."
        )
    finally:
        # No private environment file is copied into the reference checkout.
        pass


if __name__ == "__main__":
    main()
