"""Globaal sprekerregister: koppelt lokale pyannote-sprekers (SPEAKER_00, ...) per chunk
aan vaste sprekers over dagen heen, via cosine similarity op voice embeddings."""

from __future__ import annotations

import sqlite3

import numpy as np


def _normalize(v: np.ndarray) -> np.ndarray:
    v = np.asarray(v, dtype=np.float32)
    return v / (np.linalg.norm(v) + 1e-9)


def _to_blob(v: np.ndarray) -> bytes:
    return _normalize(v).astype(np.float32).tobytes()


def _from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def display_name(row: sqlite3.Row | None) -> str:
    if row is None:
        return "Onbekend"
    if row["is_me"]:
        return row["name"] or "Ik"
    return row["name"] or f"Spreker {row['id']}"


class SpeakerRegistry:
    def __init__(self, conn: sqlite3.Connection, threshold: float) -> None:
        self.conn = conn
        self.threshold = threshold

    def assign(self, embeddings: list[np.ndarray | None], seen_at: str) -> list[int | None]:
        """Koppel de embeddings van één chunk aan globale sprekers.

        Greedy op hoogste similarity, zodat twee lokale sprekers in dezelfde chunk nooit
        op dezelfde globale spreker landen. Niet-gematchte stemmen worden nieuwe sprekers.
        Embeddings die None of NaN zijn (te weinig spraak) krijgen None.
        """
        rows = self.conn.execute("SELECT id, centroid, n_obs FROM speakers").fetchall()
        ids = [r["id"] for r in rows]
        result: list[int | None] = [None] * len(embeddings)
        valid = [i for i, e in enumerate(embeddings) if e is not None and not np.isnan(e).any()]
        if not valid:
            return result

        queries = np.stack([_normalize(embeddings[i]) for i in valid])
        pairs: list[tuple[float, int, int]] = []
        if rows:
            centroids = np.stack([_from_blob(r["centroid"]) for r in rows])
            sims = queries @ centroids.T
            pairs = [
                (float(sims[qi, ci]), qi, ci)
                for qi in range(len(valid))
                for ci in range(len(rows))
                if sims[qi, ci] >= self.threshold
            ]
        pairs.sort(reverse=True)

        used_q: set[int] = set()
        used_c: set[int] = set()
        for _, qi, ci in pairs:
            if qi in used_q or ci in used_c:
                continue
            used_q.add(qi)
            used_c.add(ci)
            self._update(
                ids[ci], _from_blob(rows[ci]["centroid"]), rows[ci]["n_obs"], queries[qi], seen_at
            )
            result[valid[qi]] = ids[ci]

        for qi, i in enumerate(valid):
            if qi not in used_q:
                result[i] = self._create(queries[qi], seen_at)
        return result

    def _update(self, sid: int, centroid: np.ndarray, n: int, emb: np.ndarray, seen_at: str):
        # Running mean, begrensd zodat een stem langzaam mag driften (andere mic, verkoudheid).
        weight = min(n, 50)
        new = (centroid * weight + emb) / (weight + 1)
        self.conn.execute(
            "UPDATE speakers SET centroid = ?, n_obs = n_obs + 1, last_seen = ? WHERE id = ?",
            (_to_blob(new), seen_at, sid),
        )

    def _create(self, emb: np.ndarray, seen_at: str) -> int:
        cur = self.conn.execute(
            "INSERT INTO speakers (centroid, first_seen, last_seen) VALUES (?, ?, ?)",
            (_to_blob(emb), seen_at, seen_at),
        )
        return int(cur.lastrowid)

    def rename(self, sid: int, name: str | None) -> None:
        self.conn.execute("UPDATE speakers SET name = ? WHERE id = ?", (name or None, sid))

    def set_me(self, sid: int) -> None:
        self.conn.execute("UPDATE speakers SET is_me = (id = ?)", (sid,))

    def merge(self, keep: int, drop: int) -> None:
        """Voeg `drop` samen in `keep` (gewogen centroid, segmenten omhangen)."""
        if keep == drop:
            return
        a = self.conn.execute("SELECT * FROM speakers WHERE id = ?", (keep,)).fetchone()
        b = self.conn.execute("SELECT * FROM speakers WHERE id = ?", (drop,)).fetchone()
        if a is None or b is None:
            raise KeyError("onbekende spreker")
        merged = _from_blob(a["centroid"]) * a["n_obs"] + _from_blob(b["centroid"]) * b["n_obs"]
        self.conn.execute(
            """UPDATE speakers SET centroid = ?, n_obs = ?, name = coalesce(name, ?),
               is_me = max(is_me, ?), first_seen = min(first_seen, ?),
               last_seen = max(last_seen, ?) WHERE id = ?""",
            (
                _to_blob(merged),
                a["n_obs"] + b["n_obs"],
                b["name"],
                b["is_me"],
                b["first_seen"],
                b["last_seen"],
                keep,
            ),
        )
        self.conn.execute("UPDATE segments SET speaker_id = ? WHERE speaker_id = ?", (keep, drop))
        self.conn.execute("DELETE FROM speakers WHERE id = ?", (drop,))
