"""Real benchmark remains inert without recordings; WER is not field accuracy."""

import json

from scripts import benchmark_stt


def test_no_recordings_never_loads_a_model(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(benchmark_stt, "local_engine", lambda *args: calls.append(args))
    monkeypatch.setattr(benchmark_stt, "require_memory", lambda *args: calls.append(args))
    manifest, output = tmp_path / "manifest.json", tmp_path / "report.json"
    manifest.write_text(json.dumps({"samples": [{"id": "01", "audio_path": None}]}))
    assert benchmark_stt.benchmark(manifest, "faster-whisper", "missing-model", output) == 2
    assert not calls
    assert json.loads(output.read_text())["status"] == "no-recordings"


def test_wer_case_punctuation_and_real_errors():
    assert benchmark_stt.wer("Qizil, atirgul!", "qizil atirgul") == 0
    assert benchmark_stt.wer("qizil atirgul", "oq atirgul") == 0.5
    assert benchmark_stt.wer("qizil atirgul", "") == 1
