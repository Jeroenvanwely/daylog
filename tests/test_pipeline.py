from pathlib import Path

from conftest import FakeDiarizer, FakeSummarizer, FakeTranscriber, two_speaker_dialogue

from daylog import db
from daylog.pipeline import Pipeline
from daylog.speakers import SpeakerRegistry


def add_chunk(conn, settings, cid: str, started: str) -> Path:
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    path = settings.inbox_dir / f"{cid}.m4a"
    path.write_bytes(b"fake audio")
    conn.execute(
        "INSERT INTO chunks (id, started_at, lat, lon, path, received_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (cid, started, 52.3667, 4.8650, str(path), started),
    )
    conn.commit()
    return path


def make_pipeline(conn, settings, summarizer=None):
    words, dia = two_speaker_dialogue()
    return Pipeline(
        conn,
        settings,
        FakeTranscriber(words),
        FakeDiarizer(dia),
        summarizer,
        decoder=lambda src, dst: dst.write_bytes(b""),
    )


def test_end_to_end_with_fakes(conn, settings):
    audio = add_chunk(conn, settings, "c1", "2026-11-02T09:00:00.000+00:00")
    conn.execute(
        "INSERT INTO places (name, lat, lon, radius_m) VALUES ('thuis', 52.3667, 4.865, 150)"
    )
    summarizer = FakeSummarizer()

    # Eerst sprekers benoemen zoals de gebruiker dat in de webview zou doen.
    pipe = make_pipeline(conn, settings, summarizer=None)
    assert pipe.run() == {"2026-11-02"}
    reg = SpeakerRegistry(conn, settings.speaker_match_threshold)
    reg.set_me(1)
    reg.rename(2, "Car")
    conn.commit()

    from daylog.summarize import summarize_day

    summarize_day(conn, "2026-11-02", summarizer, settings.timezone)

    assert not audio.exists(), "audio moet na verwerking weg zijn"
    assert conn.execute("SELECT status FROM chunks").fetchone()[0] == "done"
    segs = conn.execute("SELECT text, start_at FROM segments ORDER BY start_at").fetchall()
    assert len(segs) == 2
    assert segs[1]["start_at"] == "2026-11-02T09:00:03.000+00:00"

    conv = conn.execute("SELECT * FROM conversations").fetchone()
    assert conv["place"] == "thuis"
    assert conv["title"] == "Gesprek met Car"  # token lokaal teruggezet

    sent = summarizer.transcripts[0]
    assert "Car" not in sent and "jan@example.com" not in sent
    assert "{IK}: Hoi {S2}, mail naar [EMAIL]" in sent
    assert conn.execute("SELECT summary FROM days").fetchone()[0] == "Rustige dag met Car."

    hits = db.search(conn, "mail")
    assert len(hits["segments"]) == 1


def test_failed_chunk_is_marked_and_audio_kept(conn, settings):
    audio = add_chunk(conn, settings, "c2", "2026-11-02T09:00:00.000+00:00")

    def broken(src, dst):
        raise RuntimeError("ffmpeg kapot")

    pipe = make_pipeline(conn, settings)
    pipe.decoder = broken
    assert pipe.run() == set()
    row = conn.execute("SELECT status, error FROM chunks").fetchone()
    assert row["status"] == "failed" and "ffmpeg" in row["error"]
    assert audio.exists()
