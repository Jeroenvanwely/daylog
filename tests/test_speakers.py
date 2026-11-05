import numpy as np
from conftest import unit

from daylog.speakers import SpeakerRegistry


def test_same_voice_is_recognised_across_chunks(conn):
    reg = SpeakerRegistry(conn, threshold=0.8)
    first = reg.assign([unit(1, 0, 0), unit(0, 1, 0)], "2026-11-02T08:00:00.000+00:00")
    second = reg.assign([unit(0.05, 1, 0), unit(1, 0.05, 0)], "2026-11-03T08:00:00.000+00:00")
    assert first == [1, 2]
    assert second == [2, 1]
    assert conn.execute("SELECT count(*) FROM speakers").fetchone()[0] == 2


def test_two_local_speakers_never_share_one_global_id(conn):
    reg = SpeakerRegistry(conn, threshold=0.5)
    reg.assign([unit(1, 0, 0)], "t")
    # Beide lijken op spreker 1; alleen de beste match mag hem krijgen.
    ids = reg.assign([unit(1, 0.1, 0), unit(1, 0.3, 0)], "t")
    assert ids[0] == 1
    assert ids[1] not in (None, 1)


def test_nan_or_missing_embedding_gets_none(conn):
    reg = SpeakerRegistry(conn, threshold=0.5)
    nan = np.full(3, np.nan, dtype=np.float32)
    assert reg.assign([None, nan], "t") == [None, None]


def test_merge_moves_segments_and_keeps_name(conn):
    reg = SpeakerRegistry(conn, threshold=0.99)
    a, b = reg.assign([unit(1, 0, 0), unit(0, 1, 0)], "t")
    reg.rename(b, "Car")
    conn.execute("INSERT INTO chunks (id, started_at, received_at) VALUES ('c', 't', 't')")
    conn.execute(
        "INSERT INTO segments (chunk_id, speaker_id, start_at, end_at, text) "
        "VALUES ('c', ?, 't', 't', 'hoi')",
        (b,),
    )
    reg.merge(keep=a, drop=b)
    row = conn.execute("SELECT * FROM speakers").fetchall()
    assert len(row) == 1 and row[0]["name"] == "Car" and row[0]["n_obs"] == 2
    assert conn.execute("SELECT speaker_id FROM segments").fetchone()[0] == a
