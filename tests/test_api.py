import uuid

import pytest
from fastapi.testclient import TestClient

from daylog import db
from daylog.api import create_app


@pytest.fixture
def client(settings):
    return TestClient(create_app(settings))


def headers(cid: str, token: str = "secret") -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Chunk-Id": cid,
        "X-Started-At": "2026-11-02T10:31:00Z",
        "X-Lat": "52.3667",
        "X-Lon": "4.865",
    }


def test_upload_requires_token(client):
    r = client.post("/api/chunks", content=b"x", headers=headers(str(uuid.uuid4()), "wrong"))
    assert r.status_code == 401


def test_upload_is_stored_and_idempotent(client, settings):
    cid = str(uuid.uuid4())
    r = client.post("/api/chunks", content=b"audio-bytes", headers=headers(cid))
    assert r.status_code == 200 and r.json() == {"id": cid, "duplicate": False}
    assert (settings.inbox_dir / f"{cid}.m4a").read_bytes() == b"audio-bytes"

    again = client.post("/api/chunks", content=b"audio-bytes", headers=headers(cid))
    assert again.json()["duplicate"] is True

    conn = db.connect(settings.db_path)
    row = conn.execute("SELECT * FROM chunks").fetchone()
    assert row["status"] == "pending"
    assert row["started_at"] == "2026-11-02T10:31:00.000+00:00"
    assert row["lat"] == pytest.approx(52.3667)


def test_rejects_empty_and_bad_timestamp(client):
    assert (
        client.post("/api/chunks", content=b"", headers=headers(str(uuid.uuid4()))).status_code
        == 422
    )
    bad = headers(str(uuid.uuid4())) | {"X-Started-At": "2026-11-02T10:31:00"}
    assert client.post("/api/chunks", content=b"x", headers=bad).status_code == 422


def test_pages_render(client, settings):
    conn = db.connect(settings.db_path)
    conn.execute("INSERT INTO chunks (id, started_at, received_at) VALUES ('c', 't', 't')")
    conn.execute("INSERT INTO speakers (id, centroid, name) VALUES (1, ?, 'Car')", (b"\x00" * 12,))
    conn.execute(
        "INSERT INTO conversations (id, day, start_at, end_at, title, tags) VALUES "
        "(1, '2026-11-02', '2026-11-02T09:00:00.000+00:00', '2026-11-02T09:05:00.000+00:00', "
        "'Koffie met Car', '[\"thuis\"]')"
    )
    conn.execute(
        "INSERT INTO segments (chunk_id, conversation_id, speaker_id, start_at, end_at, text) "
        "VALUES ('c', 1, 1, '2026-11-02T09:00:00.000+00:00', '2026-11-02T09:00:05.000+00:00', "
        "'zullen we <script> koffie halen')"
    )
    conn.commit()

    assert "2026-11-02" in client.get("/").text
    assert "Koffie met Car" in client.get("/day/2026-11-02").text
    page = client.get("/c/1").text
    assert "10:00" in page  # UTC 09:00 = 10:00 Amsterdam
    assert "<script>" not in page

    found = client.get("/search", params={"q": "koff"}).text
    assert "<mark>koffie</mark>" in found and "<script>" not in found

    r = client.post(
        "/speakers/1", data={"action": "rename", "name": "Car B"}, follow_redirects=False
    )
    assert r.status_code == 303
    assert "Car B" in client.get("/speakers").text
