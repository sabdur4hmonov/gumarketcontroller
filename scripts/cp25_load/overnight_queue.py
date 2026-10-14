"""One-shot serial measurement stages; hand profile evidence back to this chat."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .reference_measure import BEFORE, ENTRY, REFERENCE, ROOT, write_certified
from .resources import available_mib
from .tonight import note, stop_owned

STAGE = ROOT / ".cp22-stage/cp25/overnight-20261013"
SCALES = (10, 25, 50, 100, 500, 1000)


def plan(stage: str) -> list[tuple[str, int, bool]]:
    if stage == "before":
        return [("before", scale, False) for scale in SCALES] + [("before", 25, True)]
    if stage == "after":
        return [("after", scale, False) for scale in SCALES]
    raise ValueError("Only before/after measurement stages")


def save(path: Path, data: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def admit(free: float) -> bool:
    return free >= 3072  # optional smaller-scale exception is deliberately unused


def prerequisites(state: dict[str, Any], tooling: bool, reviewed: bool, stage: str) -> bool:
    readings = state.get("readings", [])
    return bool(
        state.get("phase") == "ready"
        and readings
        and readings[-1]["streak"] >= 2
        and tooling
        and (stage == "before" or reviewed)
    )


def verify(result: dict[str, Any], phase: str, scale: int) -> None:
    cert = result.get("runtime_provenance", {})
    assert cert.get("executed_tree_sha256") and "git_status_porcelain" in cert
    if phase == "before":
        assert cert["production_commit"] == BEFORE and cert["git_status_porcelain"] == ""
        assert cert["database_revision"] == "a24d9e7b2c10"
    assert result["shops"] == scale and result["healthy_replies"] == scale * 4
    assert result["expected_reminder_sends"] == scale and result["expected_order_sends"] == scale
    assert sum(tick["sent"] for tick in result["worker"]["reminder_ticks"]) == scale
    assert sum(tick["sent"] for tick in result["worker"]["order_ticks"]) == scale
    assert result["telegram_uploads"] == 0


def publish_tables() -> None:
    """Replace only the fresh-run section; retain historical invalidated rows."""
    start, end = "<!-- CP25 CERTIFIED TABLES START -->", "<!-- CP25 CERTIFIED TABLES END -->"
    lines = [start, "", "### CP25 certified overnight measurements", ""]
    lines += [
        "Harness limits: **5 ms artificial delay per Bot API RPC; 0.1 customer",
        "messages/s/shop** (three customer updates plus one owner announcement).",
        "Reminder and order tasks run sequentially in **100-shop batches**, each",
        "with a fresh asyncio loop. Broker and prefork scheduling are excluded.",
        "Tick totals describe a single-process upper bound, not a production",
        "Celery fleet figure. These runs cannot certify 4/8/24 GB fleet capacity.",
        "Startup guard: 100+ stays3072MiB; small scales use a valid same-scale",
        "measured aggregate peak+1024MiB, otherwise3072MiB. Evening command",
        "checks fresh RAM after infrastructure; no renewed RAM polling.",
        "The original bounded two-reading wait is retained as history.",
        "Runtime floor remains512MiB.",
        "Results with sampled free RAM below 1024 MiB are excluded as pressure",
        "runs. No unmeasured row is extrapolated. RSS/shop is amortized measured",
        "process RSS including fixed overhead, not an incremental memory slope.",
        "",
        "Before source: clean `" + BEFORE + "`.",
        "",
    ]
    for stage in ("before", "after"):
        path = STAGE / (stage + "-ledger.json")
        ledger = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"rows": []}
        rows = {row["shops"]: row for row in ledger["rows"] if not row["profile"]}
        lines += [
            f"**{stage.upper()}**",
            "",
            "|Shops|Status|Commit / tree SHA|Start / min free MiB|Reply p50/p95/p99 ms|"
            "Reminder / order tick s|Bot/worker DB connections; queries / ms|Redis ops|",
            "|---|---|---|---|---|---|---|---|",
        ]
        resources = []
        for scale in SCALES:
            row = rows.get(scale)
            if row is None:
                lines.append(f"|{scale}|queued; RAM gate pending|—|—|—|—|—|—|")
                continue
            free = (
                str(row["precheck_free_mib"])
                + " / "
                + str(row.get("minimum_sampled_free_mib", "—"))
            )
            if row["status"] != "measured":
                lines.append(
                    f"|{scale}|{row['status']} ({row.get('reason', '')})|—|{free}|—|—|—|—|"
                )
                continue
            result = json.loads(Path(row["result"]).read_text(encoding="utf-8"))
            cert = result["runtime_provenance"]
            revision = cert["production_commit"][:8] + " / " + cert["executed_tree_sha256"][:12]
            latency = "/".join(str(result[key]) for key in ("p50_ms", "p95_ms", "p99_ms"))
            ticks = "/".join(
                f"{sum(t['seconds'] for t in result['worker'][key]):.3f}"
                for key in ("reminder_ticks", "order_ticks")
            )
            db = "; ".join(
                f"{result[role]['db']['peak_connections']}; "
                f"{result[role]['db']['queries']} / {result[role]['db']['query_total_ms']}"
                for role in ("bot", "worker")
            )
            redis = str(sum(result["bot"]["redis_ops"].values()))
            lines.append(f"|{scale}|measured|{revision}|{free}|{latency}|{ticks}|{db}|{redis}|")
            for role, key in (
                ("bot", "bot"),
                ("worker", "worker"),
                ("API stub", "api_process"),
                ("coordinator", "coordinator_process"),
            ):
                data = result[key]["resources"] if role in ("bot", "worker") else result[key]
                resources.append(
                    f"|{scale}|{role}|{data['peak_rss_mib']}|{data['cpu_seconds']}|"
                    f"{data['cpu_percent_one_core']}|{data['peak_rss_mib'] / scale:.3f}|"
                    f"{data['cpu_seconds'] / scale:.5f}|"
                )
        if resources:
            lines += [
                "",
                "|Shops|Process|Peak RSS MiB|CPU seconds|CPU % one core|"
                "RSS MiB/shop|CPU seconds/shop|",
                "|---|---|---|---|---|---|---|",
                *resources,
            ]
        lines += [""]
    lines += ["Full certificates/raw measurements: `docs/capacity/cp25-clean-*.json`.", "", end]
    section = "\n".join(lines)
    for name in ("CHECKPOINTS.md", "CP25_STATUS.md"):
        target = ROOT / "docs" / name
        if name == "CP25_STATUS.md":
            # Append snapshots: never rewrite concurrent RAM watcher's log.
            with target.open("a", encoding="utf-8") as stream:
                stream.write("\n\n" + datetime.now(UTC).isoformat() + "\n" + section + "\n")
            continue
        content = target.read_text(encoding="utf-8")
        if start in content:
            left, rest = content.split(start, 1)
            _, right = rest.split(end, 1)
            content = left + section + right
        else:
            content += "\n\n" + section + "\n"
        target.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("before", "after"), required=True)
    args = parser.parse_args()
    ram = json.loads((STAGE / "ram-state.json").read_text(encoding="utf-8"))
    if not prerequisites(
        ram,
        (STAGE / "TOOLING_VALIDATED.json").exists(),
        (STAGE / "PROFILE_REVIEWED.json").exists(),
        args.stage,
    ):
        raise SystemExit("Two-reading RAM gate, certified tooling and profile stage order required")
    ledger_path = STAGE / (args.stage + "-ledger.json")
    if ledger_path.exists():
        raise SystemExit("Stage already attempted; inspect its ledger, never repeat automatically")
    lock = STAGE / "measurement.lock"
    descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.write(descriptor, str(os.getpid()).encode())
    os.close(descriptor)
    ledger: dict[str, Any] = {
        "stage": args.stage,
        "pid": os.getpid(),
        "started_at": datetime.now(UTC).isoformat(),
        "phase": "running",
        "rows": [],
        "active": None,
    }
    save(ledger_path, ledger)
    try:
        for phase, scale, profile in plan(args.stage):
            label = f"{phase}-{scale}" + ("-profile" if profile else "")
            free = available_mib()
            row: dict[str, Any] = {
                "label": label,
                "shops": scale,
                "profile": profile,
                "precheck_at": datetime.now(UTC).isoformat(),
                "precheck_free_mib": free,
            }
            note(f"{label}: actual free RAM {free:.2f}MiB, required3072.")
            if not admit(free):
                row.update(status="not run: RAM", reason="precheck <3072MiB")
                ledger["rows"].append(row)
                save(ledger_path, ledger)
                publish_tables()
                continue
            source = REFERENCE if phase == "before" else ROOT
            output = STAGE / label
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
                str(output),
            ]
            if profile:
                command.append("--profile")
            log = STAGE / (label + ".log")
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
                ledger["active"] = {"label": label, "pid": child.pid, "output": str(output)}
                save(ledger_path, ledger)
                ram_abort = False
                try:
                    while child.poll() is None:
                        if available_mib() < 512:
                            ram_abort = True
                            note(
                                f"{label}: runtime floor512 crossed; "
                                f"stop owned PID{child.pid}, no retry."
                            )
                            stop_owned(child)
                            break
                        time.sleep(0.5)
                finally:
                    stop_owned(child)
            ledger["active"] = None
            text = log.read_text(encoding="utf-8", errors="replace")
            refused = any(
                marker in text
                for marker in (
                    "Measurement refused below",
                    "Scale refused below",
                    "Heavy scales need 3072",
                    "below 512",
                )
            )
            if ram_abort or (child.returncode != 0 and refused):
                row.update(
                    status="not run: RAM", reason="attempt refused/aborted; no valid measurement"
                )
            elif child.returncode != 0:
                row.update(status="failed", exit_code=child.returncode, log=str(log))
                ledger["rows"].append(row)
                raise RuntimeError(f"{label} failed; inspect log; no automatic retry")
            else:
                result = json.loads(
                    (output / str(scale) / "result.json").read_text(encoding="utf-8")
                )
                verify(result, phase, scale)
                minimum = result["infrastructure"]["min_sampled_free_mib"]
                row["minimum_sampled_free_mib"] = minimum
                if minimum < 1024:
                    row.update(
                        status="not run: RAM",
                        reason="completed under pressure (<1024MiB free); excluded from baseline",
                    )
                else:
                    row.update(
                        status="measured",
                        result=str(output / str(scale) / "result.json"),
                        commit=result["runtime_provenance"]["production_commit"],
                        tree_sha256=result["runtime_provenance"]["executed_tree_sha256"],
                    )
                    public = ROOT / "docs/capacity" / ("cp25-clean-" + label + ".json")
                    write_certified(public, result, result["runtime_provenance"])
            ledger["rows"].append(row)
            save(ledger_path, ledger)
            publish_tables()
            note(f"{label}: {row['status']}; ledger {ledger_path.relative_to(ROOT)}.")
        ledger["phase"] = "profile_review" if args.stage == "before" else "focused_checks"
    except BaseException as error:
        ledger["phase"] = "failed"
        ledger["error_type"] = type(error).__name__
        raise
    finally:
        ledger["active"] = None
        ledger["finished_at"] = datetime.now(UTC).isoformat()
        save(ledger_path, ledger)
        lock.unlink(missing_ok=True)
        note(f"Overnight {args.stage} stage: {ledger['phase']}; inspect ledger before continuing.")


if __name__ == "__main__":
    main()
