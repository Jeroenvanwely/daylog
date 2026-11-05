"""Tijdhulpjes. Alles wordt opgeslagen als ISO-8601 in UTC met vaste precisie,
zodat strings in SQLite lexicografisch sorteren als tijd."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp zonder tijdzone: {value!r}")
    return dt.astimezone(UTC)


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="milliseconds")


def local_day(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).date().isoformat()


def day_bounds(day: str, tz: str) -> tuple[str, str]:
    """UTC-grenzen [start, eind) van een lokale kalenderdag."""
    zone = ZoneInfo(tz)
    start = datetime.combine(date.fromisoformat(day), time.min, tzinfo=zone)
    end = datetime.combine(date.fromisoformat(day) + timedelta(days=1), time.min, tzinfo=zone)
    return to_iso(start), to_iso(end)


def local_hm(value: str, tz: str) -> str:
    return parse_ts(value).astimezone(ZoneInfo(tz)).strftime("%H:%M")
