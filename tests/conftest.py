from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from daylog import db
from daylog.asr import Word
from daylog.config import Settings
from daylog.diarize import Diarization, Turn


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data", api_token="secret", anthropic_api_key=None, hf_token=None
    )


@pytest.fixture
def conn(settings: Settings):
    c = db.connect(settings.db_path)
    yield c
    c.close()


def unit(*xs: float) -> np.ndarray:
    v = np.array(xs, dtype=np.float32)
    return v / np.linalg.norm(v)


class FakeTranscriber:
    def __init__(self, words: list[Word]) -> None:
        self.words = words

    def transcribe(self, wav: Path) -> list[Word]:
        return self.words


class FakeDiarizer:
    def __init__(self, result: Diarization) -> None:
        self.result = result

    def diarize(self, wav: Path) -> Diarization:
        return self.result


class FakeSummarizer:
    def __init__(self) -> None:
        self.transcripts: list[str] = []
        self.overviews: list[str] = []

    def conversation(self, transcript: str) -> dict:
        self.transcripts.append(transcript)
        speaker = "{S2}" if "{S2}" in transcript else "{?}"
        return {"title": f"Gesprek met {speaker}", "summary": "Kort overleg.", "tags": ["thuis"]}

    def day(self, overview: str) -> str:
        self.overviews.append(overview)
        return "Rustige dag met {S2}."


def two_speaker_dialogue() -> tuple[list[Word], Diarization]:
    words = [
        Word(" Hoi", 0.0, 0.4),
        Word(" Car,", 0.4, 0.8),
        Word(" mail", 0.9, 1.2),
        Word(" naar", 1.2, 1.4),
        Word(" jan@example.com", 1.4, 2.0),
        Word(" Prima,", 3.0, 3.4),
        Word(" doe", 3.4, 3.6),
        Word(" ik.", 3.6, 3.9),
        Word(" hallucinatie", 30.0, 31.0),  # ver buiten elke turn
    ]
    dia = Diarization(
        turns=[Turn("SPEAKER_00", 0.0, 2.1), Turn("SPEAKER_01", 2.9, 4.0)],
        embeddings={"SPEAKER_00": unit(1, 0, 0), "SPEAKER_01": unit(0, 1, 0)},
    )
    return words, dia
