"""Configuratie via environment variables (prefix DAYLOG_) of een .env-bestand."""

from __future__ import annotations

from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="DAYLOG_", env_file=".env", extra="ignore", populate_by_name=True
    )

    data_dir: Path = Path("data")
    # Bearer token dat de iPhone meestuurt bij uploads.
    api_token: str = "change-me"
    max_upload_mb: int = 200

    timezone: str = "Europe/Amsterdam"
    # Stilte langer dan dit (minuten) start een nieuw gesprek.
    conversation_gap_minutes: int = 10

    whisper_model: str = "mlx-community/whisper-large-v3-mlx"
    diarization_model: str = "pyannote/speaker-diarization-3.1"
    hf_token: str | None = Field(None, validation_alias=AliasChoices("HF_TOKEN", "DAYLOG_HF_TOKEN"))
    # Cosine similarity waarboven een stem als een bekende spreker telt. Tunen op eigen data.
    speaker_match_threshold: float = 0.45
    delete_audio_after_processing: bool = True

    anthropic_api_key: str | None = Field(
        None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "DAYLOG_ANTHROPIC_API_KEY")
    )
    anthropic_model: str = "claude-sonnet-5-5"

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "daylog.db"
