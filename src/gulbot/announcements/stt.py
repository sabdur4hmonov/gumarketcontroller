"""Swappable, local-first speech recognition; imported ONLY by STT worker/CLI."""

from __future__ import annotations

import base64
import importlib
import json
import subprocess
import urllib.request
import wave
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from gulbot.announcements.resources import require_memory
from gulbot.config import Settings


@dataclass(frozen=True)
class Transcript:
    text: str
    engine: str


class SpeechEngine(Protocol):
    def transcribe(self, wav: Path) -> Transcript: ...


class WhisperEngine:
    def __init__(self, model_path: str, threads: int = 2) -> None:
        # Local paths ONLY: opening a missing model must not download one on a
        # laptop or silently contact Hugging Face during a customer's message.
        if not model_path or not Path(model_path).is_dir():
            raise ValueError("STT_MODEL_PATH must be an installed CTranslate2 model directory")
        require_memory(1.5)
        module = importlib.import_module("faster_whisper")
        self.model = module.WhisperModel(
            model_path,
            device="cpu",
            compute_type="int8",
            cpu_threads=threads,
            num_workers=1,
            local_files_only=True,
        )

    def transcribe(self, wav: Path) -> Transcript:
        segments, _ = self.model.transcribe(
            str(wav),
            language="uz",
            beam_size=5,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 300},
            condition_on_previous_text=False,
        )
        return Transcript(" ".join(str(s.text).strip() for s in segments).strip(), "faster-whisper")


class VoskEngine:
    def __init__(self, model_path: str) -> None:
        if not model_path or not Path(model_path).is_dir():
            raise ValueError("STT_MODEL_PATH must be an installed Vosk Uzbek directory")
        require_memory(0.4)
        self.module = importlib.import_module("vosk")
        self.model = self.module.Model(model_path)

    def transcribe(self, wav: Path) -> Transcript:
        with wave.open(str(wav), "rb") as stream:
            recognizer = self.module.KaldiRecognizer(self.model, 16000)
            parts: list[str] = []
            while chunk := stream.readframes(4000):
                if recognizer.AcceptWaveform(chunk):
                    parts.append(str(json.loads(recognizer.Result()).get("text", "")))
            parts.append(str(json.loads(recognizer.FinalResult()).get("text", "")))
        return Transcript(" ".join(parts).strip(), "vosk")


@lru_cache(maxsize=1)
def local_engine(name: str, model_path: str, threads: int) -> SpeechEngine:
    # Only synchronous model weights are reused, never Bot/DB/Redis clients.
    if name == "faster-whisper":
        return WhisperEngine(model_path, threads)
    if name == "vosk":
        return VoskEngine(model_path)
    raise ValueError("STT_ENGINE must be faster-whisper or vosk")


def convert_audio(source: Path, destination: Path) -> None:
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-t",
            "120",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(destination),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
    )


def transcribe(
    source: Path, wav: Path, settings: Settings, *, engine: SpeechEngine | None = None
) -> Transcript:
    try:
        convert_audio(source, wav)
        try:
            result = (
                engine
                or local_engine(
                    settings.stt_engine, settings.stt_model_path, settings.stt_cpu_threads
                )
            ).transcribe(wav)
        except Exception:
            if not (
                settings.stt_gemini_enabled
                and settings.gemini_api_key.get_secret_value()
                and settings.stt_gemini_model
            ):
                raise
            result = gemini_fallback(wav, settings)
        if not result.text or len(result.text) > 4096:
            raise ValueError("speech was empty or too long")
        return result
    finally:
        source.unlink(missing_ok=True)
        wav.unlink(missing_ok=True)


def gemini_fallback(wav: Path, settings: Settings) -> Transcript:
    if not (
        settings.stt_gemini_enabled
        and settings.gemini_api_key.get_secret_value()
        and settings.stt_gemini_model
    ):
        raise ValueError("Gemini fallback is disabled")
    model = settings.stt_gemini_model
    if any(
        ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._"
        for ch in model
    ):
        raise ValueError("invalid Gemini model identifier")
    data = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "Transcribe this Uzbek voice note exactly. Return only its Uzbek "
                            "transcript, no translation or commentary."
                        )
                    },
                    {
                        "inlineData": {
                            "mimeType": "audio/wav",
                            "data": base64.b64encode(wav.read_bytes()).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 2048},
    }
    request = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=json.dumps(data).encode(),
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": settings.gemini_api_key.get_secret_value(),
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        result = json.load(response)
    text = " ".join(str(p.get("text", "")) for p in result["candidates"][0]["content"]["parts"])
    return Transcript(text.strip(), "gemini-opt-in")
