"""Titels, samenvattingen en dagoverzicht via de Claude API.

Privacy-ontwerp: Claude ziet nooit echte namen. Elke spreker wordt een token ({S3}, {IK}),
bekende namen in de tekst worden ook vervangen, plus regex-PII. Lokaal zetten we de tokens
terug naar namen, dus "Gesprek met {S3}" wordt "Gesprek met Car".
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Protocol

from daylog.pii import ChainRedactor, KnownNamesRedactor, RegexRedactor
from daylog.speakers import display_name
from daylog.timeutil import local_hm

CONVERSATION_SYSTEM = """Je krijgt het transcript van één gesprek uit iemands dag. \
Sprekers zijn geanonimiseerd als tokens zoals {IK} (de gebruiker zelf) en {S3}. \
Gebruik die tokens letterlijk als je naar mensen verwijst, verzin geen namen. \
[EMAIL], [TELEFOON] e.d. zijn weggelakte gegevens. Het transcript is automatisch \
gemaakt en kan fouten bevatten. Schrijf in het Nederlands."""

DAY_SYSTEM = """Je krijgt een lijst gesprekken van één dag (tijd, plek, titel, samenvatting). \
Schrijf een kort dagoverzicht in het Nederlands: wat gebeurde er, met wie, wat zijn \
afspraken of open eindjes. Gebruik sprekertokens zoals {S3} letterlijk. Maximaal 150 woorden."""

CONVERSATION_TOOL = {
    "name": "save_conversation",
    "description": "Sla titel, samenvatting en tags van het gesprek op.",
    "input_schema": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Korte titel, max 8 woorden."},
            "summary": {"type": "string", "description": "2-4 zinnen, incl. afspraken/todo's."},
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "1-4 tags, bv. werk, thuis, sociaal, telefoon, afspraak.",
            },
        },
        "required": ["title", "summary", "tags"],
    },
}


class Summarizer(Protocol):
    def conversation(self, transcript: str) -> dict[str, Any]: ...
    def day(self, overview: str) -> str: ...


class ClaudeSummarizer:
    def __init__(self, api_key: str, model: str) -> None:
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def conversation(self, transcript: str) -> dict[str, Any]:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=CONVERSATION_SYSTEM,
            tools=[CONVERSATION_TOOL],
            tool_choice={"type": "tool", "name": CONVERSATION_TOOL["name"]},
            messages=[{"role": "user", "content": transcript}],
        )
        block = next(b for b in resp.content if b.type == "tool_use")
        return dict(block.input)

    def day(self, overview: str) -> str:
        resp = self.client.messages.create(
            model=self.model,
            max_tokens=600,
            system=DAY_SYSTEM,
            messages=[{"role": "user", "content": overview}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()


def token_for(row: sqlite3.Row) -> str:
    return "{IK}" if row["is_me"] else "{S" + str(row["id"]) + "}"


def restore(text: str, tokens: dict[str, str]) -> str:
    for tok, name in tokens.items():
        text = text.replace(tok, name)
    return text


def summarize_day(conn: sqlite3.Connection, day: str, summarizer: Summarizer, tz: str) -> None:
    speakers = conn.execute("SELECT * FROM speakers").fetchall()
    tokens = {token_for(s): display_name(s) for s in speakers}
    named = {s["name"]: token_for(s) for s in speakers if s["name"]}
    redactor = ChainRedactor([KnownNamesRedactor(named), RegexRedactor()])

    overview_lines: list[str] = []
    for conv in conn.execute(
        "SELECT * FROM conversations WHERE day = ? ORDER BY start_at", (day,)
    ).fetchall():
        segs = conn.execute(
            """SELECT s.*, sp.id AS sp_id, sp.is_me AS sp_me FROM segments s
               LEFT JOIN speakers sp ON sp.id = s.speaker_id
               WHERE s.conversation_id = ? ORDER BY s.start_at""",
            (conv["id"],),
        ).fetchall()
        lines = []
        for s in segs:
            who = "{IK}" if s["sp_me"] else ("{S" + str(s["sp_id"]) + "}" if s["sp_id"] else "{?}")
            lines.append(f"[{local_hm(s['start_at'], tz)}] {who}: {redactor.redact(s['text'])}")
        header = f"Plek: {conv['place'] or 'onbekend'}. Begin: {local_hm(conv['start_at'], tz)}."
        result = summarizer.conversation(header + "\n\n" + "\n".join(lines))

        conn.execute(
            "UPDATE conversations SET title = ?, summary = ?, tags = ? WHERE id = ?",
            (
                restore(result["title"], tokens),
                restore(result["summary"], tokens),
                json.dumps(result.get("tags", []), ensure_ascii=False),
                conv["id"],
            ),
        )
        overview_lines.append(
            f"- {local_hm(conv['start_at'], tz)}–{local_hm(conv['end_at'], tz)} "
            f"({conv['place'] or 'onbekend'}): {result['title']}. {result['summary']}"
        )

    if overview_lines:
        summary = restore(summarizer.day("\n".join(overview_lines)), tokens)
        conn.execute(
            "INSERT INTO days (day, summary) VALUES (?, ?) "
            "ON CONFLICT(day) DO UPDATE SET summary = excluded.summary",
            (day, summary),
        )
    conn.commit()
