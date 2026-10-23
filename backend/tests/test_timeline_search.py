"""Sittings search: Lucene query and speech excerpts."""
from app.services.timeline_service import _excerpt, lucene_query


def test_lucene_query_single_word():
    assert lucene_query("superenalotto") == "superenalotto"


def test_lucene_query_phrase_scores_higher():
    assert lucene_query("legge di bilancio") == '"legge di bilancio"^4 OR (legge AND di AND bilancio)'


def test_lucene_query_escapes_and_quotes_operators():
    assert lucene_query("art. 2-bis") == '"art. 2\\-bis"^4 OR (art. AND 2\\-bis)'
    assert lucene_query("not") == '"not"'
    assert lucene_query("   ") is None


def test_excerpt_centres_on_the_word():
    text = "uno " * 100 + "estrazioni del Superenalotto ogni settimana " + "due " * 100
    out = _excerpt(text, "superenalotto")
    assert "Superenalotto" in out
    assert out.startswith("…") and out.endswith("…")


def test_excerpt_finds_inflected_forms():
    assert "giochi" in _excerpt("x " * 200 + "i giochi olimpici " + "y " * 200, "gioco")


def test_excerpt_short_text_unchanged():
    assert _excerpt("Testo breve.", "breve") == "Testo breve."
