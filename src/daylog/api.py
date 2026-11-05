"""FastAPI: upload-endpoint voor de iPhone + een simpele webview (logboek, zoeken, sprekers)."""

from __future__ import annotations

import json
import secrets
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from daylog import db
from daylog.config import Settings
from daylog.speakers import SpeakerRegistry, display_name
from daylog.timeutil import local_hm, parse_ts, to_iso

TEMPLATES = Path(__file__).parent / "templates"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    settings.inbox_dir.mkdir(parents=True, exist_ok=True)
    db.connect(settings.db_path).close()  # schema aanmaken

    app = FastAPI(title="daylog", docs_url=None, redoc_url=None)
    templates = Jinja2Templates(directory=TEMPLATES)
    templates.env.filters["hm"] = lambda v: local_hm(v, settings.timezone) if v else ""
    templates.env.filters["tags"] = lambda v: json.loads(v) if v else []
    templates.env.filters["mark"] = lambda v: Markup(
        str(escape(v or "")).replace(db.MARK_START, "<mark>").replace(db.MARK_END, "</mark>")
    )

    def get_conn() -> Iterator:
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def require_token(authorization: str | None = Header(None)) -> None:
        expected = f"Bearer {settings.api_token}"
        if not authorization or not secrets.compare_digest(authorization, expected):
            raise HTTPException(401, "invalid token")

    def speaker_names(conn) -> dict[int, str]:
        return {r["id"]: display_name(r) for r in conn.execute("SELECT * FROM speakers")}

    # ---------- API ----------

    @app.get("/api/health")
    def health() -> dict:
        return {"ok": True}

    @app.post("/api/chunks", dependencies=[Depends(require_token)])
    async def upload_chunk(
        request: Request,
        x_chunk_id: str = Header(),
        x_started_at: str = Header(),
        x_lat: float | None = Header(None),
        x_lon: float | None = Header(None),
        conn=Depends(get_conn),
    ) -> dict:
        """Body = rauw audiobestand (m4a). Metadata in headers, zodat iOS het als
        background upload vanaf een bestand kan versturen. Idempotent op X-Chunk-Id."""
        try:
            chunk_id = str(uuid.UUID(x_chunk_id))
            started = parse_ts(x_started_at)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

        if conn.execute("SELECT 1 FROM chunks WHERE id = ?", (chunk_id,)).fetchone():
            return {"id": chunk_id, "duplicate": True}

        dest = settings.inbox_dir / f"{chunk_id}.m4a"
        tmp = dest.with_suffix(".part")
        limit, size = settings.max_upload_mb * 1024 * 1024, 0
        with tmp.open("wb") as f:
            async for part in request.stream():
                size += len(part)
                if size > limit:
                    f.close()
                    tmp.unlink(missing_ok=True)
                    raise HTTPException(413, "chunk te groot")
                f.write(part)
        if size == 0:
            tmp.unlink(missing_ok=True)
            raise HTTPException(422, "lege upload")
        tmp.rename(dest)

        with conn:
            conn.execute(
                """INSERT OR IGNORE INTO chunks (id, started_at, lat, lon, path, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chunk_id, to_iso(started), x_lat, x_lon, str(dest), to_iso(datetime.now(UTC))),
            )
        return {"id": chunk_id, "duplicate": False}

    # ---------- Web ----------

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, conn=Depends(get_conn)):
        days = conn.execute(
            """SELECT c.day, count(*) AS n, d.summary FROM conversations c
               LEFT JOIN days d ON d.day = c.day GROUP BY c.day ORDER BY c.day DESC LIMIT 60"""
        ).fetchall()
        stats = conn.execute("SELECT status, count(*) AS n FROM chunks GROUP BY status").fetchall()
        return templates.TemplateResponse(
            request, "index.html", {"days": days, "stats": {r["status"]: r["n"] for r in stats}}
        )

    @app.get("/day/{day}", response_class=HTMLResponse)
    def day_view(day: str, request: Request, conn=Depends(get_conn)):
        convs = conn.execute(
            "SELECT * FROM conversations WHERE day = ? ORDER BY start_at", (day,)
        ).fetchall()
        summary = conn.execute("SELECT summary FROM days WHERE day = ?", (day,)).fetchone()
        return templates.TemplateResponse(
            request,
            "day.html",
            {
                "day": day,
                "conversations": convs,
                "summary": summary["summary"] if summary else None,
            },
        )

    @app.get("/c/{cid}", response_class=HTMLResponse)
    def conversation_view(cid: int, request: Request, conn=Depends(get_conn)):
        conv = conn.execute("SELECT * FROM conversations WHERE id = ?", (cid,)).fetchone()
        if conv is None:
            raise HTTPException(404)
        segs = conn.execute(
            "SELECT * FROM segments WHERE conversation_id = ? ORDER BY start_at", (cid,)
        ).fetchall()
        return templates.TemplateResponse(
            request,
            "conversation.html",
            {"c": conv, "segments": segs, "names": speaker_names(conn)},
        )

    @app.get("/search", response_class=HTMLResponse)
    def search_view(request: Request, q: str = "", conn=Depends(get_conn)):
        results = db.search(conn, q) if q.strip() else None
        return templates.TemplateResponse(
            request, "search.html", {"q": q, "results": results, "names": speaker_names(conn)}
        )

    @app.get("/speakers", response_class=HTMLResponse)
    def speakers_view(request: Request, conn=Depends(get_conn)):
        rows = conn.execute(
            """SELECT sp.*, count(s.id) AS n_segments FROM speakers sp
               LEFT JOIN segments s ON s.speaker_id = sp.id
               GROUP BY sp.id ORDER BY sp.is_me DESC, n_segments DESC"""
        ).fetchall()
        return templates.TemplateResponse(
            request,
            "speakers.html",
            {"speakers": rows, "names": {r["id"]: display_name(r) for r in rows}},
        )

    @app.post("/speakers/{sid}")
    def speaker_action(
        sid: int,
        action: str = Form(),
        name: str = Form(""),
        into: int | None = Form(None),
        conn=Depends(get_conn),
    ):
        reg = SpeakerRegistry(conn, settings.speaker_match_threshold)
        with conn:
            if action == "rename":
                reg.rename(sid, name.strip())
            elif action == "me":
                reg.set_me(sid)
            elif action == "merge" and into is not None:
                reg.merge(keep=into, drop=sid)
            else:
                raise HTTPException(400, "onbekende actie")
        return RedirectResponse("/speakers", status_code=303)

    return app
