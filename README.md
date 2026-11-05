# daylog

Persoonlijk audiologboek. De iPhone neemt op (met een aan/uit-toggle), uploadt chunks naar je
eigen Mac, en die maakt er 's avonds een doorzoekbaar logboek van: transcript met timestamps,
herkende sprekers ("Spreker 3 hoorden we vaker"), gesprekken met titels, plek en een dagoverzicht.

Alleen voor eigen gebruik. Niets draait in de cloud behalve de samenvattingsstap (Claude API),
en die krijgt alleen geanonimiseerde tekst.

## Architectuur

```
iPhone (SwiftUI)                         Mac (M1, native Python)
┌──────────────────────┐   HTTPS via    ┌──────────────────────────────────────────────┐
│ toggle → AVAudioEngine│   Tailscale   │ POST /api/chunks → data/inbox/*.m4a + SQLite │
│ AAC-chunks van 5 min │ ─────────────▶ │                                              │
│ + locatie (sidecar)  │  background    │ `daylog process` (avond, via launchd):       │
│ buffer tot laptop    │  upload, wifi  │   ffmpeg → 16 kHz wav                        │
│ bereikbaar is        │                │   pyannote 3.1: wie sprak wanneer + embedding│
└──────────────────────┘                │   mlx-whisper large-v3: woorden + timestamps │
                                        │   align: woorden ↔ sprekers, hallucinatiefilter│
                                        │   sprekerregister: embeddings ↔ vaste IDs     │
                                        │   audio verwijderen                          │
                                        │   gesprekken knippen (stilte / plekwissel)   │
                                        │   PII-redactie → Claude → titels, samenvatting│
                                        │                                              │
                                        │ Webview: logboek, gesprek, zoeken (FTS5),    │
                                        │ sprekers hernoemen / samenvoegen / "dit ben ik"│
                                        └──────────────────────────────────────────────┘
```

### Ontwerpkeuzes

- **Telefoon doet zo min mogelijk.** Opnemen in AAC is hardware-encoded en zuinig. Er draait
  geen model op de telefoon; uploads gaan als iOS background upload, alleen via wifi.
- **ML draait native, niet in Docker.** Docker op macOS heeft geen toegang tot de M1-GPU
  (Metal/MPS), dus Whisper en pyannote zouden alleen op de CPU draaien. De ML-stack zit
  daarom in een `ml`-extra en draait via `uv` op de Mac. CI test alles zonder ML-stack,
  met fakes achter de `Transcriber`/`Diarizer`/`Summarizer`-protocollen.
- **Sprekers over dagen heen.** pyannote geeft per chunk lokale labels plus een embedding per
  stem. `SpeakerRegistry` matcht die (cosine similarity, greedy, nooit twee lokale stemmen op
  één globale spreker) aan een centroid per bekende spreker, of maakt een nieuwe aan.
- **Claude ziet geen namen.** Sprekers worden tokens (`{IK}`, `{S3}`), bekende namen in de tekst
  ook, plus regex-PII (mail, telefoon, IBAN, BSN met elfproef, postcode). Lokaal zetten we de
  tokens terug, dus "Gesprek met {S3}" wordt "Gesprek met Car".
- **Lokaal staat de tekst onge-redacteerd** zodat zoeken op namen werkt. Audio wordt na
  verwerking verwijderd.
- **SQLite + FTS5** voor opslag en zoeken: één bestand, geen server.

## Setup (Mac)

```bash
brew install ffmpeg uv tailscale
make install-ml                 # incl. mlx-whisper en pyannote.audio
cp .env.example .env            # vul token, HF_TOKEN en ANTHROPIC_API_KEY in
```

1. **pyannote:** accepteer de voorwaarden van `pyannote/speaker-diarization-3.1` en
   `pyannote/segmentation-3.0` op Hugging Face en zet een read-token in `HF_TOKEN`.
2. **Server starten:** `make serve` (luistert op 127.0.0.1:8000).
3. **Bereikbaar maken voor de telefoon:** `tailscale serve --bg 8000`. Dat geeft
   `https://<mac>.<tailnet>.ts.net` met een geldig certificaat, alleen binnen je tailnet.
   Installeer Tailscale ook op de iPhone.
4. **Plekken benoemen** (optioneel): `uv run daylog place-add thuis 52.37 4.86 --radius-m 150`.
5. **Nachtelijke batch:** zie `deploy/` voor launchd-voorbeelden (server altijd aan, process om 23:30).
   Handmatig: `make process`.

## Setup (iPhone)

Zie [`ios/README.md`](ios/README.md). Kort: `brew install xcodegen`, `make ios`, open
`ios/DayLog.xcodeproj`, zet je team, installeer op je telefoon, vul server-URL en token in.

## Gebruik

- `make serve`, open de webview via de Tailscale-URL (ook op je telefoon).
- **Sprekers:** markeer na de eerste dag je eigen stem met "Dit ben ik" en geef bekende
  stemmen een naam. Dubbele sprekers voeg je samen. Daarna: `uv run daylog resummarize 2026-11-02`.
- **Drempel tunen:** `DAYLOG_SPEAKER_MATCH_THRESHOLD`. Te veel nieuwe sprekers: omlaag.
  Verschillende mensen samengevoegd: omhoog.

## Development

```bash
make install   # lichte deps, geen ML
make check     # ruff lint + format-check + pytest
```

| Module | Verantwoordelijkheid |
|---|---|
| `api.py` | upload-endpoint (idempotent, bearer token) + webview |
| `pipeline.py` | batch: decode → diarize → transcribe → align → sprekers → opslaan |
| `asr.py`, `diarize.py` | MLX Whisper en pyannote achter een protocol |
| `align.py` | woorden aan sprekerturns koppelen, hallucinaties weggooien |
| `speakers.py` | globaal sprekerregister |
| `conversations.py` | dag opknippen in gesprekken, plekken |
| `pii.py` | redactors (regex, bekende namen, aanhaakpunt voor NER) |
| `summarize.py` | Claude: titel/samenvatting/tags per gesprek + dagoverzicht |
| `db.py` | schema, FTS5, zoeken |

## Privacy en recht

Neem alleen gesprekken op waar je zelf aan deelneemt; gesprekken van anderen opnemen waar je
niet bij bent is in Nederland strafbaar. Zet de toggle uit op werk bij klanten (vertrouwelijkheid)
en wees open naar mensen met wie je vaak praat.

## Roadmap

- PII-NER uit pii-bench inhaken (namen, adressen in vrije tekst)
- Real-time streaming (WebSocket + streaming ASR) i.p.v. einde-dag batch
- Semantisch zoeken (embeddings) naast FTS
- Eigen stem vooraf inschrijven met een enrollment-opname
