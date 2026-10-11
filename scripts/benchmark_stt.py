"""One command, serial real-engine benchmark; never downloads models.

python scripts/benchmark_stt.py --manifest docs/cp22-samples.json \
    --engine faster-whisper --model <local-model-directory> --output <report.json>

Add audio paths to the ten sample rows after the owner records them. Reports
missing audio honestly. Voice copies/wav are scrubbed; originals stay owner's.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from gulbot.announcements.extraction import extract
from gulbot.announcements.lexicon import normalize_word
from gulbot.announcements.resources import peak_rss_gib, require_memory
from gulbot.announcements.stt import local_engine, transcribe
from gulbot.config import Settings


def wer(reference: str, hypothesis: str) -> float:
    expected = re.findall(r"\w+", normalize_word(reference))
    actual = re.findall(r"\w+", normalize_word(hypothesis))
    previous = list(range(len(actual) + 1))
    for i, word in enumerate(expected, 1):
        row = [i]
        for j, target in enumerate(actual, 1):
            row.append(min(row[-1] + 1, previous[j] + 1, previous[j - 1] + (word != target)))
        previous = row
    return previous[-1] / max(1, len(expected))


def benchmark(manifest: Path, engine_name: str, model: str, output: Path) -> int:
    samples = json.loads(manifest.read_text(encoding="utf-8"))
    if isinstance(samples, dict):
        samples = samples["samples"]
    rows: list[dict[str, Any]] = []
    usable = [s for s in samples if s.get("audio_path") and Path(s["audio_path"]).is_file()]
    if not usable:
        output.write_text(
            json.dumps(
                {
                    "status": "no-recordings",
                    "samples": len(samples),
                    "note": "Owner bouquet recordings needed; no model loaded or downloaded.",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print("No bouquet recordings supplied; benchmark report records this limitation.")
        return 2
    free = require_memory(3.0 if engine_name == "faster-whisper" else 1.0)
    started = time.perf_counter()
    engine = local_engine(engine_name, model, 2)
    load_seconds = time.perf_counter() - started
    settings = Settings(stt_engine=engine_name, stt_model_path=model, stt_gemini_enabled=False)
    for sample in usable:
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="cp22-bench-") as directory:
            source, wav = Path(directory) / "voice.ogg", Path(directory) / "voice.wav"
            shutil.copyfile(sample["audio_path"], source)
            result = transcribe(source, wav, settings, engine=engine)
        transcription_seconds = time.perf_counter() - started
        fields = extract(result.text)
        expected = dict(sample.get("expected_fields", {}))
        if "price_uzs" in expected:
            expected["price"] = expected.pop("price_uzs")
        accuracy = {
            key: getattr(fields, key) == value
            for key, value in expected.items()
            if key in {"flowers", "colour", "count", "price"}
        }
        rows.append(
            {
                "id": sample["id"],
                "text": result.text,
                "seconds": transcription_seconds,
                "fields": fields.data(),
                "field_accuracy": accuracy,
                "wer": wer(sample["reference_text"], result.text)
                if sample.get("reference_text")
                else None,
                "peak_rss_gib": peak_rss_gib(),
            }
        )
    output.write_text(
        json.dumps(
            {
                "status": "measured",
                "engine": engine_name,
                "model": model,
                "free_ram_before_gib": free,
                "load_seconds": load_seconds,
                "threads": 2,
                "cpu": platform.processor(),
                "logical_cpus": os.cpu_count(),
                "platform": platform.platform(),
                "decode": {"language": "uz", "compute_type": "int8", "beam_size": 5}
                if engine_name == "faster-whisper"
                else {"sample_rate": 16000},
                "model_bytes": sum(p.stat().st_size for p in Path(model).rglob("*") if p.is_file()),
                "model_revision": Path(model).name
                if re.fullmatch(r"[0-9a-f]{40}", Path(model).name)
                else "Record the installed model's pinned revision beside this report",
                "peak_rss_gib": peak_rss_gib(),
                "latency_p50_seconds": sorted(r["seconds"] for r in rows)[
                    math.ceil(len(rows) * 0.5) - 1
                ],
                "latency_p95_seconds": sorted(r["seconds"] for r in rows)[
                    math.ceil(len(rows) * 0.95) - 1
                ],
                "field_accuracy": {
                    key: sum(r["field_accuracy"].get(key) is True for r in rows)
                    / sum(key in r["field_accuracy"] for r in rows)
                    for key in {k for r in rows for k in r["field_accuracy"]}
                },
                "rows": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Benchmarked {len(rows)} recordings serially; report: {output}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=Path("docs/cp22-samples.json"))
    parser.add_argument("--engine", choices=["faster-whisper", "vosk"], required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(benchmark(args.manifest, args.engine, args.model, args.output))
