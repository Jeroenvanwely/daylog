"""Koppel Whisper-woorden aan diarization-turns en groepeer ze tot uitspraken."""

from __future__ import annotations

from dataclasses import dataclass

from daylog.asr import Word
from daylog.diarize import Turn


@dataclass
class Utterance:
    speaker: str
    start: float
    end: float
    text: str


def _overlap(w: Word, t: Turn) -> float:
    return max(0.0, min(w.end, t.end) - max(w.start, t.start))


def align(
    words: list[Word], turns: list[Turn], tolerance: float = 0.5, max_gap: float = 1.5
) -> list[Utterance]:
    """Wijs elk woord toe aan de turn met de meeste overlap.

    Woorden die verder dan `tolerance` seconden van elke turn liggen worden weggegooid:
    dat is bijna altijd Whisper die tekst hallucineert in stilte of ruis.
    """
    utterances: list[Utterance] = []
    for w in words:
        best, best_ov = None, 0.0
        for t in turns:
            ov = _overlap(w, t)
            if ov > best_ov:
                best, best_ov = t, ov
        if best is None:
            near = [
                t for t in turns if t.start - tolerance <= w.end and w.start <= t.end + tolerance
            ]
            if not near:
                continue
            mid = (w.start + w.end) / 2
            best = min(near, key=lambda t: abs((t.start + t.end) / 2 - mid))

        prev = utterances[-1] if utterances else None
        if prev and prev.speaker == best.speaker and w.start - prev.end <= max_gap:
            prev.text += w.text
            prev.end = w.end
        else:
            utterances.append(Utterance(best.speaker, w.start, w.end, w.text))

    for u in utterances:
        u.text = " ".join(u.text.split())
    return [u for u in utterances if u.text]
