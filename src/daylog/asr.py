"""Speech-to-text. MLX Whisper draait native op de M1-GPU (niet in Docker!)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class Word:
    text: str
    start: float  # seconden vanaf begin chunk
    end: float


class Transcriber(Protocol):
    def transcribe(self, wav: Path) -> list[Word]: ...


class MLXWhisperTranscriber:
    def __init__(self, model: str) -> None:
        self.model = model

    def transcribe(self, wav: Path) -> list[Word]:
        import mlx_whisper  # lazy: alleen op de Mac geïnstalleerd

        result = mlx_whisper.transcribe(
            str(wav),
            path_or_hf_repo=self.model,
            word_timestamps=True,
            # Voorkomt dat Whisper in een hallucinatie-loop blijft hangen bij stilte/ruis.
            condition_on_previous_text=False,
        )
        return [
            Word(w["word"], float(w["start"]), float(w["end"]))
            for seg in result.get("segments", [])
            for w in seg.get("words", [])
        ]
