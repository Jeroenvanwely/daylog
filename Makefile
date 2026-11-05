.PHONY: help install install-ml lint format test check serve process ios clean

help:  ## Toon deze hulp
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-12s %s\n", $$1, $$2}'

install:  ## Lichte deps (API, web, tests) — zonder ML
	uv sync

install-ml:  ## Incl. mlx-whisper en pyannote (alleen op de Mac)
	uv sync --extra ml

lint:  ## Ruff lint + format-check
	uv run ruff check .
	uv run ruff format --check .

format:  ## Code formatteren en autofixes
	uv run ruff format .
	uv run ruff check --fix .

test:  ## Pytest (zonder ML-stack, met fakes)
	uv run pytest

check: lint test  ## Alles wat CI ook draait

serve:  ## Upload-API + webview op 127.0.0.1:8000
	uv run daylog serve

process:  ## Verwerk wachtende chunks en vat dagen samen
	uv run daylog process

ios:  ## Genereer het Xcode-project (brew install xcodegen)
	cd ios && xcodegen generate

clean:  ## Caches weg (data/ blijft staan)
	rm -rf .pytest_cache .ruff_cache **/__pycache__
