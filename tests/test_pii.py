from daylog.pii import ChainRedactor, KnownNamesRedactor, RegexRedactor


def test_regex_redacts_structured_pii():
    r = RegexRedactor()
    text = (
        "Mail jan@example.com of bel 06-12345678, IBAN NL91 ABNA 0417 1643 00, "
        "BSN 111222333, postcode 1056 AB."
    )
    out = r.redact(text)
    for leaked in ("jan@example.com", "12345678", "0417", "111222333", "1056 AB"):
        assert leaked not in out
    assert "[EMAIL]" in out and "[TELEFOON]" in out and "[IBAN]" in out
    assert "[BSN]" in out and "[POSTCODE]" in out


def test_bsn_requires_elfproef():
    assert "123456789" in RegexRedactor().redact("ordernummer 123456789")


def test_known_names_become_tokens_case_insensitive():
    r = ChainRedactor([KnownNamesRedactor({"Car": "{S2}"}), RegexRedactor()])
    assert r.redact("hoi car, hoe is het met Carla?") == "hoi {S2}, hoe is het met Carla?"
