"""Batchverwerking: pending chunks -> transcript + sprekers -> gesprekken -> samenvattingen."""

from __future__ import annotations

import logging
import sqlite3
import subprocess
import tempfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

from daylog.align import align
from daylog.asr import Transcriber
from daylog.config import Settings
from daylog.conversations import rebuild_day
from daylog.diarize import Diarizer
from daylog.speakers import SpeakerRegistry
from daylog.summarize import Summarizer, summarize_day
from daylog.timeutil import local_day, parse_ts, to_iso

log = logging.getLogger(__name__)


def to_wav(src: Path, dst: Path) -> None:
    """Decodeer (AAC/m4a) naar 16 kHz mono wav, het formaat dat Whisper en pyannote willen."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-ac",
            "1",
            "-ar",
            "16000",
            str(dst),
        ],
        check=True,
    )


class Pipeline:
    def __init__(
        self,
        conn: sqlite3.Connection,
        settings: Settings,
        transcriber: Transcriber,
        diarizer: Diarizer,
        summarizer: Summarizer | None = None,
        decoder: Callable[[Path, Path], None] = to_wav,
    ) -> None:
        self.conn = conn
        self.settings = settings
        self.transcriber = transcriber
        self.diarizer = diarizer
        self.summarizer = summarizer
        self.decoder = decoder
        self.registry = SpeakerRegistry(conn, settings.speaker_match_threshold)

    def run(self) -> set[str]:
        days = self.process_pending()
        for day in sorted(days):
            self.finalize_day(day)
        return days

    def process_pending(self) -> set[str]:
        days: set[str] = set()
        pending = self.conn.execute(
            "SELECT * FROM chunks WHERE status = 'pending' ORDER BY started_at"
        ).fetchall()
        for chunk in pending:
            try:
                days |= self.process_chunk(chunk)
            except Exception as exc:  # één kapotte chunk mag de batch niet stoppen
                log.exception("chunk %s mislukt", chunk["id"])
                self.conn.execute(
                    "UPDATE chunks SET status = 'failed', error = ? WHERE id = ?",
                    (str(exc)[:500], chunk["id"]),
                )
                self.conn.commit()
        return days

    def process_chunk(self, chunk: sqlite3.Row) -> set[str]:
        audio = Path(chunk["path"])
        started = parse_ts(chunk["started_at"])
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "chunk.wav"
            self.decoder(audio, wav)
            dia = self.diarizer.diarize(wav)
            utterances = align(self.transcriber.transcribe(wav), dia.turns) if dia.turns else []

        days: set[str] = set()
        with self.conn:
            if not utterances:
                self.conn.execute("UPDATE chunks SET status = 'empty' WHERE id = ?", (chunk["id"],))
            else:
                labels = sorted({u.speaker for u in utterances})
                global_ids = self.registry.assign(
                    [dia.embeddings.get(lbl) for lbl in labels], to_iso(started)
                )
                mapping = dict(zip(labels, global_ids, strict=True))
                for u in utterances:
                    s_at = started + timedelta(seconds=u.start)
                    self.conn.execute(
                        """INSERT INTO segments (chunk_id, speaker_id, start_at, end_at, text)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            chunk["id"],
                            mapping[u.speaker],
                            to_iso(s_at),
                            to_iso(started + timedelta(seconds=u.end)),
                            u.text,
                        ),
                    )
                    days.add(local_day(s_at, self.settings.timezone))
                self.conn.execute("UPDATE chunks SET status = 'done' WHERE id = ?", (chunk["id"],))

        if self.settings.delete_audio_after_processing:
            audio.unlink(missing_ok=True)
            self.conn.execute("UPDATE chunks SET path = NULL WHERE id = ?", (chunk["id"],))
            self.conn.commit()
        return days

    def finalize_day(self, day: str) -> None:
        s = self.settings
        rebuild_day(self.conn, day, s.timezone, s.conversation_gap_minutes)
        if self.summarizer is None:
            log.warning("geen ANTHROPIC_API_KEY: %s zonder samenvatting", day)
            return
        summarize_day(self.conn, day, self.summarizer, s.timezone)
