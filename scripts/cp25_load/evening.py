"""Infrastructure -> fresh RAM -> frozen BEFORE -> profile review -> AFTER.

Prepared daytime; invoke only AFTER the owner says RAM is free. No heartbeat,
RAM waiting/retry loop, full gate, push or merge. The review barrier uses stdin,
not an automatic guess at profile attribution. Run in an interactive terminal.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import overnight_queue as queue
from .reference_measure import ENTRY, REFERENCE, ROOT, provenance, scale_gate, write_certified
from .resources import available_mib
from .startup_audit import prepare
from .tonight import job, note, stop_owned


def pending_guards() -> list[str]:
    from .mutations import mutations

    required = {
        m.name
        for m in mutations()
        if (
            m.name.startswith(("candidate ", "shadow ", "small ", "startup ", "evening "))
            and m.name != "small scale excluded"
        )
        or m.name
        in ("static builder ignores resolved root", "static builder writes temporary symlink")
    }
    report = ROOT / "docs/CP25_RUNTIME_MUTATIONS.json"
    caught = (
        {
            row["guard"]
            for row in json.loads(report.read_text(encoding="utf-8"))["results"]
            if row["assertion_caught"]
        }
        if report.exists()
        else set()
    )
    return sorted(required - caught)


def profile_approved(review: Path, profile: Path) -> bool:
    if not review.is_file() or not profile.is_file():
        return False
    data = json.loads(review.read_text(encoding="utf-8"))
    return bool(
        data.get("status") == "reviewed"
        and data.get("attribution")
        and data.get("profile_sha256") == hashlib.sha256(profile.read_bytes()).hexdigest()
        and data.get("after_tree_sha256") == provenance(ROOT, "after")["executed_tree_sha256"]
    )


def measured_peak(result: dict[str, Any]) -> float:
    """Conservative sum of process/container peaks; they need not coincide."""
    return float(
        result["bot"]["resources"]["peak_rss_mib"]
        + result["worker"]["resources"]["peak_rss_mib"]
        + result["api_process"]["peak_rss_mib"]
        + result["coordinator_process"]["peak_rss_mib"]
        + sum(
            data["sampled_peak_memory_mib"]
            for data in result["infrastructure"]["containers"].values()
        )
    )


def run_one(
    phase: str, scale: int, profile: bool, output: Path, peaks: dict[int, float]
) -> dict[str, Any]:
    label = f"{phase}-{scale}" + ("-profile" if profile else "")
    free = available_mib()  # one admission observation; no retry/wait
    peak = peaks.get(scale) if scale in (10, 25, 50) else None
    floor = scale_gate(scale, peak)
    row: dict[str, Any] = {
        "label": label,
        "shops": scale,
        "profile": profile,
        "precheck_at": datetime.now(UTC).isoformat(),
        "precheck_free_mib": free,
        "required_mib": floor,
        "measured_peak_basis_mib": peak,
    }
    note(f"Evening {label}: actual free {free:.2f}MiB; required{floor}MiB.")
    if free < floor:
        return {**row, "status": "not run: RAM", "reason": "one admission refused; no retry"}
    source = REFERENCE if phase == "before" else ROOT
    directory = output / label
    command = [
        sys.executable,
        "-u",
        str(ENTRY),
        "--source",
        str(source),
        "--phase",
        phase,
        "--scales",
        str(scale),
        "--output",
        str(directory),
    ]
    if peak is not None:
        command += ["--small-peak-mib", str(peak)]
    if profile:
        command.append("--profile")
    log = output / (label + ".log")
    with log.open("wb") as stream:
        child = subprocess.Popen(
            command,
            cwd=source,
            env={**os.environ, "PYTHONUTF8": "1"},
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=sys.platform != "win32",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        queue.save(output / "active.json", {"label": label, "pid": child.pid})
        deadline = time.monotonic() + 5400
        aborted = False
        try:
            # Only supervise a live owned job, never wait for RAM admission.
            while child.poll() is None:
                if available_mib() < 512:
                    aborted = True
                    stop_owned(child)
                    break
                if time.monotonic() > deadline:
                    stop_owned(child)
                    raise TimeoutError("Owned scale exceeded its wall deadline")
                time.sleep(0.5)
        finally:
            stop_owned(child)
            (output / "active.json").unlink(missing_ok=True)
    log_text = log.read_text(encoding="utf-8", errors="replace")
    if aborted or (
        child.returncode != 0
        and any(
            message in log_text
            for message in (
                "Measurement refused below",
                "Scale refused below",
                "Heavy scales need 3072",
                "below 512",
            )
        )
    ):
        return {**row, "status": "not run: RAM", "reason": "owned job refused/aborted; no retry"}
    if child.returncode != 0:
        raise RuntimeError(f"{label} failed; inspect {log}; no automatic retry")
    result_path = directory / str(scale) / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    queue.verify(result, phase, scale)
    minimum = result["infrastructure"]["min_sampled_free_mib"]
    if minimum < 1024:
        return {
            **row,
            "status": "not run: RAM",
            "reason": "pressure run excluded",
            "minimum_sampled_free_mib": minimum,
        }
    peak = measured_peak(result)
    if not profile:
        peaks[scale] = max(peaks.get(scale, 0), peak)
    cert = result["runtime_provenance"]
    public = ROOT / "docs/capacity" / ("cp25-clean-" + label + ".json")
    write_certified(public, result, cert)
    return {
        **row,
        "status": "measured",
        "result": str(result_path),
        "minimum_sampled_free_mib": minimum,
        "aggregate_peak_mib": peak,
        "commit": cert["production_commit"],
        "tree_sha256": cert["executed_tree_sha256"],
    }


def run_stage(stage: str, output: Path, peaks: dict[int, float]) -> dict[str, Any]:
    ledger_path = output / (stage + "-ledger.json")
    if ledger_path.exists():
        raise RuntimeError("Stage already attempted; preserve it, never retry automatically")
    ledger: dict[str, Any] = {"stage": stage, "phase": "running", "rows": [], "pid": os.getpid()}
    queue.save(ledger_path, ledger)
    try:
        for phase, scale, profile in queue.plan(stage):
            ledger["rows"].append(run_one(phase, scale, profile, output, peaks))
            queue.save(ledger_path, ledger)
            queue.save(output / "measured-peaks.json", {str(k): v for k, v in peaks.items()})
            queue.publish_tables()
        ledger["phase"] = "profile_review" if stage == "before" else "focused_checks"
    except BaseException:
        ledger["phase"] = "failed"
        raise
    finally:
        queue.save(ledger_path, ledger)
        note(f"Evening {stage}: {ledger['phase']}; ledger {ledger_path.relative_to(ROOT)}.")
    return ledger


def main() -> None:
    output = (
        ROOT
        / ".cp22-stage/cp25"
        / ("evening-" + datetime.now(UTC).strftime("%Y%m%d") + "-" + uuid.uuid4().hex[:8])
    )
    output.mkdir(parents=True)
    # Shared with the earlier driver: do not allow two measurement controllers.
    lock = ROOT / ".cp22-stage/cp25/evening-measurement.lock"
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(fd, str(os.getpid()).encode())
    os.close(fd)
    queue.STAGE = output
    try:
        provenance(REFERENCE, "before")
        if not prepare(output / "startup", warm_only=False):
            raise SystemExit("waiting for RAM; infrastructure step refused once")
        free = available_mib()
        note(f"Evening AFTER infrastructure: actual free RAM {free:.2f}MiB; floor3072.")
        queue.save(
            output / "admission.json",
            {
                "free_mib": free,
                "floor_mib": 3072,
                "at": datetime.now(UTC).isoformat(),
                "infrastructure_ready": True,
            },
        )
        if free < 3072:
            raise SystemExit("waiting for RAM after infrastructure; no retry")
        missing = pending_guards()
        if missing:
            environment = {
                **os.environ,
                "POSTGRES_TEST_DB": "gulbot_cp25_test",
                "REDIS_DB_BROKER": "6",
                "REDIS_DB_RESULTS": "7",
                "REDIS_DB_TEST": "8",
                "REDIS_DB_FSM": "15",
            }
            job(
                "remaining-focused-guards",
                [
                    sys.executable,
                    "-u",
                    "-m",
                    "scripts.cp25_load.mutations",
                    "--report",
                    "docs/CP25_RUNTIME_MUTATIONS.json",
                    "--only",
                    *missing,
                ],
                cwd=ROOT,
                output=output,
                environment=environment,
            )
            if pending_guards():
                raise SystemExit("Remaining assertion guards are not proven; no capacity run")
        peaks: dict[int, float] = {}
        before = run_stage("before", output, peaks)
        if before["rows"][-1]["status"] != "measured":
            raise SystemExit("waiting for RAM: profile25 refused; AFTER cannot start")
        profile = output / "before-25-profile/25/tick-profile.json"
        review = output / "PROFILE_REVIEWED.json"
        print(
            f"PROFILE REVIEW REQUIRED: {profile}\nWrite {review} after actual attribution/tests.",
            flush=True,
        )
        # This is an explicit evidence barrier, not RAM polling or an automatic fix.
        input("Agent: finish profile review, then press Enter to continue AFTER. ")
        if not profile_approved(review, profile):
            raise SystemExit("AFTER refused: profile/source evidence has not been reviewed")
        run_stage("after", output, peaks)
        print(f"Measurements ended in {output}. No full gate/push/merge.")
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
