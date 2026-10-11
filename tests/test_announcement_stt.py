"""Fake-engine deterministic tests, queue isolation and hard-kill audio cleanup."""

import io
import json
import subprocess
import sys
import wave
from types import SimpleNamespace

import pytest

from gulbot.announcements import stt
from gulbot.announcements.audio_guard import scrub
from gulbot.config import Settings
from gulbot.worker.app import app
from gulbot.worker.stt_tasks import STT_HARD_LIMIT, STT_SOFT_LIMIT, transcribe_voice


class FakeEngine:
    def __init__(self, *, fail=False):
        self.fail = fail

    def transcribe(self, wav):
        assert wav.exists()
        if self.fail:
            raise ValueError("fake recognition error")
        return stt.Transcript("qizil atirgul ellik bitta dona 450 ming so'm", "fake")


@pytest.mark.parametrize("fail", [False, True])
def test_fake_engine_and_immediate_deletion(tmp_path, monkeypatch, fail):
    source, wav = tmp_path / "source.ogg", tmp_path / "normalised.wav"
    source.write_bytes(b"fake voice")
    monkeypatch.setattr(stt, "convert_audio", lambda src, dst: dst.write_bytes(b"wav"))
    settings = Settings(stt_gemini_enabled=False)
    if fail:
        with pytest.raises(ValueError):
            stt.transcribe(source, wav, settings, engine=FakeEngine(fail=True))
    else:
        result = stt.transcribe(source, wav, settings, engine=FakeEngine())
        assert result.engine == "fake" and "450 ming" in result.text
    assert not source.exists() and not wav.exists()


def test_conversion_error_also_deletes(tmp_path, monkeypatch):
    source, wav = tmp_path / "voice.ogg", tmp_path / "voice.wav"
    source.write_bytes(b"voice")

    def fail(*args):
        raise RuntimeError("conversion failed")

    monkeypatch.setattr(stt, "convert_audio", fail)
    with pytest.raises(RuntimeError):
        stt.transcribe(source, wav, Settings(), engine=FakeEngine())
    assert not source.exists() and not wav.exists()


def test_converter_mono_16k_pcm_and_no_shell(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(stt.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    stt.convert_audio(tmp_path / "input with spaces.ogg", tmp_path / "out.wav")
    args, kwargs = calls[0]
    assert args[args.index("-ac") + 1] == "1"
    assert args[args.index("-ar") + 1] == "16000"
    assert args[args.index("-c:a") + 1] == "pcm_s16le"
    assert kwargs.get("shell", False) is False and kwargs["timeout"] == 30


def test_stt_queue_time_limits_and_off_by_default():
    assert transcribe_voice.queue == "stt"
    assert transcribe_voice.soft_time_limit == STT_SOFT_LIMIT == 360
    assert transcribe_voice.time_limit == STT_HARD_LIMIT == 420
    assert transcribe_voice.acks_late is False
    assert app.conf.task_routes["gulbot.transcribe_voice"]["queue"] == "stt"
    settings = Settings()
    assert not settings.stt_gemini_enabled
    assert not settings.gemini_api_key.get_secret_value()


def test_gemini_needs_both_flag_and_key(tmp_path, monkeypatch):
    called = []
    monkeypatch.setattr(stt.urllib.request, "urlopen", lambda *args, **kwargs: called.append(True))
    for settings in [
        Settings(stt_gemini_enabled=False, gemini_api_key="fake"),
        Settings(stt_gemini_enabled=True, gemini_api_key=""),
    ]:
        with pytest.raises(ValueError):
            stt.gemini_fallback(tmp_path / "never-read.wav", settings)
    assert called == []


def test_missing_model_never_downloads(tmp_path):
    with pytest.raises(ValueError):
        stt.WhisperEngine(str(tmp_path / "missing"))
    with pytest.raises(ValueError):
        stt.VoskEngine(str(tmp_path / "missing"))


def test_hard_killed_parent_audio_guard_scrubs(tmp_path):
    directory = tmp_path / "cp22-audio-test"
    directory.mkdir()
    (directory / "voice.wav").write_bytes(b"private voice")
    parent = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    guard = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "gulbot.announcements.audio_guard",
            str(directory),
            str(tmp_path),
            str(parent.pid),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        parent.kill()
        parent.wait(timeout=5)
        guard.wait(timeout=8)
        assert guard.returncode == 0
        assert not directory.exists()
    finally:
        if parent.poll() is None:
            parent.kill()
            parent.wait(timeout=5)
        if guard.poll() is None:
            guard.kill()
            guard.wait(timeout=5)


def test_janitor_refuses_unrelated_files(tmp_path):
    unrelated = tmp_path / "other-project"
    unrelated.mkdir()
    with pytest.raises(ValueError):
        scrub(unrelated, tmp_path)
    assert unrelated.exists()


def test_whisper_adapter_uz_int8_cpu_no_download(tmp_path, monkeypatch):
    calls = []

    class Model:
        def __init__(self, path, **kwargs):
            calls.append(kwargs)

        def transcribe(self, path, **kwargs):
            calls.append(kwargs)
            return iter([SimpleNamespace(text="qizil atirgul")]), None

    monkeypatch.setattr(stt, "require_memory", lambda minimum: 4.0)
    monkeypatch.setattr(
        stt.importlib, "import_module", lambda name: SimpleNamespace(WhisperModel=Model)
    )
    result = stt.WhisperEngine(str(tmp_path), 2).transcribe(tmp_path / "voice.wav")
    assert result.text == "qizil atirgul"
    assert calls[0]["compute_type"] == "int8" and calls[0]["device"] == "cpu"
    assert calls[0]["local_files_only"] is True and calls[0]["cpu_threads"] == 2
    assert calls[1]["language"] == "uz" and calls[1]["vad_filter"] is True
    assert calls[1]["condition_on_previous_text"] is False


def test_vosk_adapter_swappable(tmp_path, monkeypatch):
    class Recognizer:
        def __init__(self, model, rate):
            assert rate == 16000

        def AcceptWaveform(self, chunk):
            return False

        def FinalResult(self):
            return json.dumps({"text": "oq atirgul"})

    monkeypatch.setattr(stt, "require_memory", lambda minimum: 1.0)
    monkeypatch.setattr(
        stt.importlib,
        "import_module",
        lambda name: SimpleNamespace(Model=lambda path: object(), KaldiRecognizer=Recognizer),
    )
    wav = tmp_path / "voice.wav"
    with wave.open(str(wav), "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(16000)
        writer.writeframes(b"\0" * 160)
    assert stt.VoskEngine(str(tmp_path)).transcribe(wav).text == "oq atirgul"


def test_gemini_opt_in_request_and_fallback_cleanup(tmp_path, monkeypatch):
    requests = []

    class Response(io.BytesIO):
        pass

    def request(req, *, timeout):
        requests.append(req)
        assert timeout == 30
        return Response(
            json.dumps(
                {"candidates": [{"content": {"parts": [{"text": "qizil atirgul"}]}}]}
            ).encode()
        )

    monkeypatch.setattr(stt.urllib.request, "urlopen", request)
    monkeypatch.setattr(stt, "convert_audio", lambda source, wav: wav.write_bytes(b"wav"))
    settings = Settings(
        stt_gemini_enabled=True, gemini_api_key="dummy-key", stt_gemini_model="reviewed-model"
    )
    source, wav = tmp_path / "voice.ogg", tmp_path / "voice.wav"
    source.write_bytes(b"voice")
    result = stt.transcribe(source, wav, settings, engine=FakeEngine(fail=True))
    assert result.text == "qizil atirgul" and result.engine == "gemini-opt-in"
    assert not source.exists() and not wav.exists()
    assert "dummy-key" not in requests[0].full_url
    assert requests[0].get_header("X-goog-api-key") == "dummy-key"
    assert (
        json.loads(requests[0].data)["contents"][0]["parts"][1]["inlineData"]["mimeType"]
        == "audio/wav"
    )
