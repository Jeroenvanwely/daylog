from datetime import UTC, datetime, timedelta

from daylog.conversations import Place, SegLite, nearest_place, split_into_groups


def seg(i: int, start_min: int, dur_min: int = 1, place: str | None = None) -> SegLite:
    t0 = datetime(2026, 11, 2, 8, 0, tzinfo=UTC) + timedelta(minutes=start_min)
    return SegLite(i, t0, t0 + timedelta(minutes=dur_min), place, None, None)


def test_split_on_silence_gap():
    groups = split_into_groups([seg(1, 0), seg(2, 5), seg(3, 30)], timedelta(minutes=10))
    assert [[s.id for s in g] for g in groups] == [[1, 2], [3]]


def test_split_on_place_change_even_without_gap():
    groups = split_into_groups(
        [seg(1, 0, place="thuis"), seg(2, 2, place="HDK"), seg(3, 3)], timedelta(minutes=10)
    )
    assert [[s.id for s in g] for g in groups] == [[1], [2, 3]]


def test_nearest_place_respects_radius():
    places = [Place("thuis", 52.3667, 4.8650, 150)]
    assert nearest_place(52.3668, 4.8651, places) == "thuis"
    assert nearest_place(52.3800, 4.9000, places) is None
    assert nearest_place(None, None, places) is None
