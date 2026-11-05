"""Command line: `daylog serve`, `daylog process`, `daylog resummarize`, `daylog place-add`."""

from __future__ import annotations

import logging

import typer

from daylog import db
from daylog.config import Settings

app = typer.Typer(no_args_is_help=True, add_completion=False)


def _summarizer(settings: Settings):
    if not settings.anthropic_api_key:
        return None
    from daylog.summarize import ClaudeSummarizer

    return ClaudeSummarizer(settings.anthropic_api_key, settings.anthropic_model)


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start upload-API + webview. Bereikbaar maken voor je telefoon met `tailscale serve`."""
    import uvicorn

    from daylog.api import create_app

    uvicorn.run(create_app(Settings()), host=host, port=port)


@app.command()
def process() -> None:
    """Verwerk alle wachtende chunks en vat de geraakte dagen samen."""
    from daylog.asr import MLXWhisperTranscriber
    from daylog.diarize import PyannoteDiarizer
    from daylog.pipeline import Pipeline

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    s = Settings()
    conn = db.connect(s.db_path)
    pending = conn.execute("SELECT count(*) FROM chunks WHERE status = 'pending'").fetchone()[0]
    if not pending:
        typer.echo("Niets te verwerken.")
        return
    pipeline = Pipeline(
        conn,
        s,
        transcriber=MLXWhisperTranscriber(s.whisper_model),
        diarizer=PyannoteDiarizer(s.diarization_model, s.hf_token),
        summarizer=_summarizer(s),
    )
    days = pipeline.run()
    typer.echo(f"{pending} chunks verwerkt; dagen bijgewerkt: {', '.join(sorted(days)) or '-'}")


@app.command()
def resummarize(day: str) -> None:
    """Herbouw gesprekken en samenvattingen van één dag (YYYY-MM-DD), bv. na sprekers hernoemen."""
    from daylog.conversations import rebuild_day
    from daylog.summarize import summarize_day

    s = Settings()
    conn = db.connect(s.db_path)
    rebuild_day(conn, day, s.timezone, s.conversation_gap_minutes)
    summarizer = _summarizer(s)
    if summarizer is None:
        raise typer.Exit("ANTHROPIC_API_KEY ontbreekt")
    summarize_day(conn, day, summarizer, s.timezone)
    typer.echo(f"{day} opnieuw samengevat.")


@app.command("place-add")
def place_add(name: str, lat: float, lon: float, radius_m: float = 150) -> None:
    """Geef een locatie een naam (bv. thuis, HDK) zodat gesprekken die plek krijgen."""
    conn = db.connect(Settings().db_path)
    with conn:
        conn.execute(
            "INSERT INTO places (name, lat, lon, radius_m) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(name) DO UPDATE SET lat = excluded.lat, lon = excluded.lon, "
            "radius_m = excluded.radius_m",
            (name, lat, lon, radius_m),
        )
    typer.echo(f"Plek '{name}' opgeslagen.")


if __name__ == "__main__":
    app()
