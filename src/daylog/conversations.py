"""Deel de segmenten van een dag op in gesprekken (op stiltes en plaatswissels)."""

from __future__ import annotations

import math
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta

from daylog.timeutil import day_bounds, parse_ts, to_iso


@dataclass(frozen=True)
class Place:
    name: str
    lat: float
    lon: float
    radius_m: float


@dataclass(frozen=True)
class SegLite:
    id: int
    start: datetime
    end: datetime
    place: str | None
    lat: float | None
    lon: float | None


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def nearest_place(lat: float | None, lon: float | None, places: list[Place]) -> str | None:
    if lat is None or lon is None:
        return None
    hits = [(haversine_m(lat, lon, p.lat, p.lon), p) for p in places]
    hits = [(d, p) for d, p in hits if d <= p.radius_m]
    return min(hits, key=lambda x: x[0])[1].name if hits else None


def split_into_groups(segs: list[SegLite], gap: timedelta) -> list[list[SegLite]]:
    groups: list[list[SegLite]] = []
    for s in sorted(segs, key=lambda s: s.start):
        if groups:
            prev = groups[-1][-1]
            moved = prev.place and s.place and prev.place != s.place
            if s.start - prev.end <= gap and not moved:
                groups[-1].append(s)
                continue
        groups.append([s])
    return groups


def load_places(conn: sqlite3.Connection) -> list[Place]:
    return [
        Place(r["name"], r["lat"], r["lon"], r["radius_m"])
        for r in conn.execute("SELECT * FROM places")
    ]


def rebuild_day(conn: sqlite3.Connection, day: str, tz: str, gap_minutes: int) -> list[int]:
    """Herbouw alle gesprekken van één lokale dag. Titels/samenvattingen vervallen."""
    start, end = day_bounds(day, tz)
    places = load_places(conn)
    rows = conn.execute(
        """SELECT s.id, s.start_at, s.end_at, c.lat, c.lon FROM segments s
           JOIN chunks c ON c.id = s.chunk_id
           WHERE s.start_at >= ? AND s.start_at < ? ORDER BY s.start_at""",
        (start, end),
    ).fetchall()
    segs = [
        SegLite(
            r["id"],
            parse_ts(r["start_at"]),
            parse_ts(r["end_at"]),
            nearest_place(r["lat"], r["lon"], places),
            r["lat"],
            r["lon"],
        )
        for r in rows
    ]

    ids: list[int] = []
    with conn:
        conn.execute(
            "UPDATE segments SET conversation_id = NULL WHERE start_at >= ? AND start_at < ?",
            (start, end),
        )
        conn.execute("DELETE FROM conversations WHERE day = ?", (day,))
        conn.execute("DELETE FROM days WHERE day = ?", (day,))
        for group in split_into_groups(segs, timedelta(minutes=gap_minutes)):
            counts = Counter(s.place for s in group if s.place)
            place = counts.most_common(1)[0][0] if counts else None
            located = next((s for s in group if s.lat is not None), None)
            cur = conn.execute(
                """INSERT INTO conversations (day, start_at, end_at, lat, lon, place)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    day,
                    to_iso(group[0].start),
                    to_iso(max(s.end for s in group)),
                    located.lat if located else None,
                    located.lon if located else None,
                    place,
                ),
            )
            cid = int(cur.lastrowid)
            conn.executemany(
                "UPDATE segments SET conversation_id = ? WHERE id = ?",
                [(cid, s.id) for s in group],
            )
            ids.append(cid)
    return ids
