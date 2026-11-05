"""PII-redactie vóór tekst naar een externe API gaat.

De regex-baseline vangt gestructureerde PII (mail, telefoon, IBAN, BSN, postcode).
Namen vangt hij NIET, op bekende sprekers na. Een NER-model (bv. uit pii-bench) hang je
in via het Redactor-protocol en ChainRedactor.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import Protocol


class Redactor(Protocol):
    def redact(self, text: str) -> str: ...


def _bsn_valid(digits: str) -> bool:
    """Elfproef voor BSN."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    weights = [9, 8, 7, 6, 5, 4, 3, 2, -1]
    return sum(int(d) * w for d, w in zip(digits, weights, strict=True)) % 11 == 0


_PATTERNS: list[tuple[str, re.Pattern[str], Callable[[str], bool] | None]] = [
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), None),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}\s?(?:[A-Z0-9]{4}\s?){2,7}[A-Z0-9]{1,4}\b"), None),
    (
        "TELEFOON",
        re.compile(r"(?<!\w)(?:\+31|0031|0)[\s-]?(?:6|[1-9]\d{1,2})(?:[\s-]?\d){7,8}\b"),
        None,
    ),
    ("BSN", re.compile(r"\b\d{9}\b"), _bsn_valid),
    ("POSTCODE", re.compile(r"\b[1-9]\d{3}\s?[A-Z]{2}\b"), None),
]


class RegexRedactor:
    def redact(self, text: str) -> str:
        for label, pattern, validate in _PATTERNS:

            def repl(m: re.Match[str], label=label, validate=validate) -> str:
                if validate and not validate(m.group(0)):
                    return m.group(0)
                return f"[{label}]"

            text = pattern.sub(repl, text)
        return text


class KnownNamesRedactor:
    """Vervangt bekende namen door een (lokaal terug te zetten) token, bv. Car -> {S2}."""

    def __init__(self, names: dict[str, str]) -> None:
        self.names = {n: tok for n, tok in names.items() if n and n.strip()}
        if self.names:
            alts = sorted((re.escape(n) for n in self.names), key=len, reverse=True)
            self._re = re.compile(r"\b(" + "|".join(alts) + r")\b", flags=re.IGNORECASE)
            self._lookup = {n.lower(): tok for n, tok in self.names.items()}

    def redact(self, text: str) -> str:
        if not self.names:
            return text
        return self._re.sub(lambda m: self._lookup[m.group(0).lower()], text)


class ChainRedactor:
    def __init__(self, redactors: Iterable[Redactor]) -> None:
        self.redactors = list(redactors)

    def redact(self, text: str) -> str:
        for r in self.redactors:
            text = r.redact(text)
        return text
