"""Speaker diarization met pyannote: wie sprak wanneer, plus één embedding per lokale spreker."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np


@dataclass(frozen=True)
class Turn:
    speaker: str  # lokaal label, bv. SPEAKER_00 (alleen binnen één chunk geldig)
    start: float
    end: float


@dataclass
class Diarization:
    turns: list[Turn]
    embeddings: dict[str, np.ndarray] = field(default_factory=dict)

    @property
    def labels(self) -> list[str]:
        return sorted({t.speaker for t in self.turns})


class Diarizer(Protocol):
    def diarize(self, wav: Path) -> Diarization: ...


class PyannoteDiarizer:
    def __init__(self, model: str, hf_token: str | None) -> None:
        import torch
        from pyannote.audio import Pipeline

        self.pipeline = Pipeline.from_pretrained(model, use_auth_token=hf_token)
        if torch.backends.mps.is_available():
            self.pipeline.to(torch.device("mps"))

    def diarize(self, wav: Path) -> Diarization:
        annotation, embeddings = self.pipeline(str(wav), return_embeddings=True)
        turns = [
            Turn(str(label), float(seg.start), float(seg.end))
            for seg, _, label in annotation.itertracks(yield_label=True)
        ]
        # pyannote geeft embeddings in de volgorde van annotation.labels().
        by_label = {str(lbl): embeddings[i] for i, lbl in enumerate(annotation.labels())}
        return Diarization(turns=turns, embeddings=by_label)
