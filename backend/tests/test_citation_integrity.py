"""Unit tests for the citation integrity invariants in models/evidence.py.

These cover the exact-substring contract (schema v2, invariant C8): spans are
computed by exact match inside the speech text, and verification re-extracts
the span and compares it verbatim with the stored quote.
"""

from app.models.evidence import (
    compute_chunk_span,
    compute_quote_text,
    verify_citation_integrity,
    normalize_party_name,
    PARTY_DISPLAY_NAMES,
)

SPEECH = "Signor Presidente, il salario minimo è una priorità per il Paese."


def test_compute_chunk_span_exact_substring():
    chunk = "il salario minimo è una priorità"
    start, end = compute_chunk_span(SPEECH, chunk)
    assert SPEECH[start:end] == chunk


def test_compute_chunk_span_unknown_offsets_are_zero():
    assert compute_chunk_span(SPEECH, "testo assente dal discorso") == (0, 0)
    assert compute_chunk_span("", "qualcosa") == (0, 0)
    assert compute_chunk_span(SPEECH, "") == (0, 0)


def test_compute_quote_text_roundtrip():
    chunk = "salario minimo è una priorità"
    start, end = compute_chunk_span(SPEECH, chunk)
    assert compute_quote_text(SPEECH, start, end) == chunk


def test_compute_quote_text_aligns_to_word_boundaries():
    # Offsets cutting a word in half must be extended outward, never inward.
    start = SPEECH.index("salario") + 3
    end = SPEECH.index("minimo") + 3
    quote = compute_quote_text(SPEECH, start, end)
    assert "salario" in quote and "min" in quote
    assert not quote.startswith("ario")


def test_verify_citation_integrity_with_explicit_span():
    chunk = "una priorità per il Paese"
    start, end = compute_chunk_span(SPEECH, chunk)
    assert verify_citation_integrity(chunk, SPEECH, start, end) is True
    assert verify_citation_integrity("altro testo", SPEECH, start, end) is False


def test_verify_citation_integrity_missing_offsets_fails_closed():
    assert verify_citation_integrity("qualunque", SPEECH) is False


def test_normalize_party_name_maps_db_names_to_display():
    assert normalize_party_name("FRATELLI D'ITALIA") == "Fratelli d'Italia"
    for db_name, display in PARTY_DISPLAY_NAMES.items():
        assert normalize_party_name(db_name) == display
