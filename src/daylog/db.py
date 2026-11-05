"""SQLite-opslag met FTS5 voor zoeken. Eén bestand, geen server nodig."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id          TEXT PRIMARY KEY,          -- UUID, gegenereerd door de telefoon (idempotent)
    started_at  TEXT NOT NULL,             -- ISO UTC
    lat         REAL,
    lon         REAL,
    path        TEXT,
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending | done | empty | failed
    error       TEXT,
    received_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_status ON chunks(status, started_at);

CREATE TABLE IF NOT EXISTS speakers (
    id         INTEGER PRIMARY KEY,
    name       TEXT,
    is_me      INTEGER NOT NULL DEFAULT 0,
    centroid   BLOB NOT NULL,              -- float32, L2-genormaliseerd
    n_obs      INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT,
    last_seen  TEXT
);

CREATE TABLE IF NOT EXISTS conversations (
    id       INTEGER PRIMARY KEY,
    day      TEXT NOT NULL,                -- lokale datum YYYY-MM-DD
    start_at TEXT NOT NULL,
    end_at   TEXT NOT NULL,
    lat      REAL,
    lon      REAL,
    place    TEXT,
    title    TEXT,
    summary  TEXT,
    tags     TEXT                          -- JSON-lijst
);
CREATE INDEX IF NOT EXISTS conversations_day ON conversations(day, start_at);

CREATE TABLE IF NOT EXISTS segments (
    id              INTEGER PRIMARY KEY,
    chunk_id        TEXT NOT NULL REFERENCES chunks(id),
    conversation_id INTEGER REFERENCES conversations(id),
    speaker_id      INTEGER REFERENCES speakers(id),
    start_at        TEXT NOT NULL,
    end_at          TEXT NOT NULL,
    text            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS segments_time ON segments(start_at);
CREATE INDEX IF NOT EXISTS segments_conv ON segments(conversation_id);

CREATE TABLE IF NOT EXISTS days (
    day     TEXT PRIMARY KEY,
    summary TEXT
);

CREATE TABLE IF NOT EXISTS places (
    id       INTEGER PRIMARY KEY,
    name     TEXT NOT NULL UNIQUE,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    radius_m REAL NOT NULL DEFAULT 150
);

-- Full-text search (external content: FTS volgt de tabellen via triggers).
CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
    text, content='segments', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE OF text ON segments BEGIN
    INSERT INTO segments_fts(segments_fts, rowid, text) VALUES ('delete', old.id, old.text);
    INSERT INTO segments_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    title, summary, content='conversations', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, title, summary)
    VALUES (new.id, coalesce(new.title, ''), coalesce(new.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, title, summary)
    VALUES ('delete', old.id, coalesce(old.title, ''), coalesce(old.summary, ''));
END;
CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE OF title, summary ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, title, summary)
    VALUES ('delete', old.id, coalesce(old.title, ''), coalesce(old.summary, ''));
    INSERT INTO conversations_fts(rowid, title, summary)
    VALUES (new.id, coalesce(new.title, ''), coalesce(new.summary, ''));
END;
"""


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    return conn


# Markers voor snippet(); de web-laag escapet de tekst en zet ze om naar <mark>.
MARK_START, MARK_END = "\x02", "\x03"


def fts_query(q: str) -> str | None:
    """Zet vrije invoer om naar een veilige FTS5-query (prefix-match op elk woord)."""
    tokens = re.findall(r"\w+", q, flags=re.UNICODE)
    return " ".join(f'"{t}"*' for t in tokens) or None


def search(conn: sqlite3.Connection, q: str, limit: int = 100) -> dict[str, list[sqlite3.Row]]:
    match = fts_query(q)
    if match is None:
        return {"conversations": [], "segments": []}
    conversations = conn.execute(
        """
        SELECT c.* FROM conversations_fts f JOIN conversations c ON c.id = f.rowid
        WHERE conversations_fts MATCH ? ORDER BY c.start_at DESC LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    segments = conn.execute(
        f"""
        SELECT s.id, s.start_at, s.conversation_id, s.speaker_id, c.title AS conversation_title,
               snippet(segments_fts, 0, '{MARK_START}', '{MARK_END}', '…', 16) AS snippet
        FROM segments_fts f JOIN segments s ON s.id = f.rowid
        LEFT JOIN conversations c ON c.id = s.conversation_id
        WHERE segments_fts MATCH ? ORDER BY s.start_at DESC LIMIT ?
        """,
        (match, limit),
    ).fetchall()
    return {"conversations": conversations, "segments": segments}
