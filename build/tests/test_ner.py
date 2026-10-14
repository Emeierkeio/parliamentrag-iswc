"""
Unit tests for build/ner.py — NER extraction functions.

Tests are structured in two categories:
  1. Pure regex tests (no spaCy model needed) — always run
  2. spaCy model tests — marked slow, skipped if model not installed
"""
from __future__ import annotations

import pytest
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers to create mock spaCy docs without loading the model
# ---------------------------------------------------------------------------

def _make_mock_entity(text: str, label: str):
    """Return a minimal object that mimics a spaCy Span entity."""
    ent = SimpleNamespace()
    ent.text = text
    ent.label_ = label
    return ent


def _make_mock_doc(entities: list):
    """Return a minimal object that mimics a spaCy Doc with .ents attribute."""
    doc = SimpleNamespace()
    doc.ents = entities
    return doc


# ---------------------------------------------------------------------------
# Import module under test
# ---------------------------------------------------------------------------
from ner import extract_law_refs, extract_person_refs, enrich_chunks_with_ner


# ---------------------------------------------------------------------------
# Law ref extraction tests (pure regex — no spaCy)
# ---------------------------------------------------------------------------

class TestExtractLawRefs:
    def test_extract_law_refs_decreto_legislativo(self):
        text = "Si applica il decreto legislativo 231 alle società."
        result = extract_law_refs(text)
        assert any("decreto legislativo 231" in r for r in result), f"Expected law ref in {result}"

    def test_extract_law_refs_dl_with_year(self):
        text = "L'articolo 4 del D.L. 50/2016 prevede..."
        result = extract_law_refs(text)
        assert any("D.L. 50/2016" in r or "D.L. 50" in r for r in result), f"Expected D.L. ref in {result}"

    def test_extract_law_refs_dlgs(self):
        text = "Il D.lgs. 81/2008 disciplina la sicurezza sul lavoro."
        result = extract_law_refs(text)
        assert len(result) > 0, f"Expected at least one law ref, got {result}"

    def test_extract_law_refs_legge(self):
        text = "Ai sensi della legge n. 234/2021..."
        result = extract_law_refs(text)
        assert any("234" in r for r in result), f"Expected legge ref in {result}"

    def test_extract_law_refs_articolo(self):
        text = "Come previsto dall'art. 10 comma 2 della Costituzione..."
        result = extract_law_refs(text)
        assert any("art." in r.lower() or "art" in r.lower() for r in result), f"Expected art. ref in {result}"

    def test_extract_law_refs_constitution(self):
        text = "Ai sensi della Costituzione italiana..."
        result = extract_law_refs(text)
        assert any("Costituzione" in r or "Cost." in r for r in result), f"Expected Costituzione ref in {result}"

    def test_extract_law_refs_no_duplicates(self):
        text = "Il decreto legislativo 231 è chiaro. Il decreto legislativo 231 prevede anche..."
        result = extract_law_refs(text)
        # Should deduplicate — the same ref should not appear twice
        # (exact string normalization may vary, just check no obvious dups)
        assert len(result) == len(set(result)), f"Duplicates found: {result}"

    def test_extract_law_refs_empty(self):
        text = "Questa frase non contiene riferimenti normativi specifici."
        result = extract_law_refs(text)
        assert result == [], f"Expected [], got {result}"

    def test_extract_law_refs_returns_list(self):
        result = extract_law_refs("")
        assert isinstance(result, list)

    def test_extract_law_refs_multiple_patterns(self):
        text = "Il D.L. 50/2016 e la legge 234/2021 sono entrambi rilevanti."
        result = extract_law_refs(text)
        assert len(result) >= 1, f"Expected at least one law ref, got {result}"


# ---------------------------------------------------------------------------
# Person ref extraction tests (mock spaCy doc)
# ---------------------------------------------------------------------------

class TestExtractPersonRefs:
    def test_extract_person_refs_basic(self):
        doc = _make_mock_doc([
            _make_mock_entity("Mario Rossi", "PER"),
        ])
        result = extract_person_refs(doc)
        assert "Mario Rossi" in result

    def test_extract_person_refs_filters_short(self):
        """PER entities with text length <= 2 chars must be excluded."""
        doc = _make_mock_doc([
            _make_mock_entity("A", "PER"),
            _make_mock_entity("AB", "PER"),
            _make_mock_entity("ABC", "PER"),
        ])
        result = extract_person_refs(doc)
        assert "A" not in result
        assert "AB" not in result
        assert "ABC" in result  # len 3 > 2, should be included

    def test_extract_person_refs_ignores_non_per(self):
        doc = _make_mock_doc([
            _make_mock_entity("Roma", "LOC"),
            _make_mock_entity("Mario Rossi", "PER"),
        ])
        result = extract_person_refs(doc)
        assert "Roma" not in result
        assert "Mario Rossi" in result

    def test_extract_person_refs_deduplicates(self):
        doc = _make_mock_doc([
            _make_mock_entity("Mario Rossi", "PER"),
            _make_mock_entity("Mario Rossi", "PER"),
        ])
        result = extract_person_refs(doc)
        assert result.count("Mario Rossi") == 1

    def test_extract_person_refs_empty_doc(self):
        doc = _make_mock_doc([])
        result = extract_person_refs(doc)
        assert result == []

    def test_extract_person_refs_strips_whitespace(self):
        """Entities with whitespace-padded text should still be filtered by len."""
        doc = _make_mock_doc([
            _make_mock_entity("  A  ", "PER"),
        ])
        result = extract_person_refs(doc)
        # " A ".strip() == "A", len 1 <= 2 → excluded
        assert result == []


# ---------------------------------------------------------------------------
# enrich_chunks_with_ner tests (mock nlp pipe)
# ---------------------------------------------------------------------------

class TestEnrichChunksWithNer:
    def _make_mock_nlp(self, entities_per_chunk: list[list]):
        """Create a mock nlp that returns pre-configured docs via .pipe()."""
        docs = [_make_mock_doc(ents) for ents in entities_per_chunk]

        class MockNlp:
            def pipe(self, texts, batch_size=100):
                return iter(docs)

        return MockNlp()

    def test_enrich_chunks_batch(self):
        """enrich_chunks_with_ner adds lawRefs and personRefs keys to each chunk dict."""
        chunks = [
            {"id": "c1", "text": "Il decreto legislativo 231 è importante."},
            {"id": "c2", "text": "Mario Rossi ha parlato di riforme."},
        ]
        entities_per_chunk = [
            [],  # c1: no PER entities
            [_make_mock_entity("Mario Rossi", "PER")],  # c2: one person
        ]
        mock_nlp = self._make_mock_nlp(entities_per_chunk)
        enrich_chunks_with_ner(chunks, nlp=mock_nlp)

        assert "lawRefs" in chunks[0], "lawRefs key missing from chunk 0"
        assert "personRefs" in chunks[0], "personRefs key missing from chunk 0"
        assert "lawRefs" in chunks[1], "lawRefs key missing from chunk 1"
        assert "personRefs" in chunks[1], "personRefs key missing from chunk 1"

        # c1 should have a law ref
        assert any("decreto" in r.lower() or "231" in r for r in chunks[0]["lawRefs"]), \
            f"Expected decreto legislativo 231 in lawRefs: {chunks[0]['lawRefs']}"

        # c2 should have person ref
        assert "Mario Rossi" in chunks[1]["personRefs"], \
            f"Expected Mario Rossi in personRefs: {chunks[1]['personRefs']}"

    def test_enrich_chunks_modifies_in_place(self):
        """enrich_chunks_with_ner should modify chunks in-place (no return value)."""
        chunks = [{"id": "c1", "text": "testo senza riferimenti normativi"}]
        mock_nlp = self._make_mock_nlp([[]])
        result = enrich_chunks_with_ner(chunks, nlp=mock_nlp)
        assert result is None, "enrich_chunks_with_ner should return None"
        assert "lawRefs" in chunks[0]
        assert "personRefs" in chunks[0]

    def test_enrich_chunks_empty_list(self):
        """Enriching an empty list should not raise."""
        mock_nlp = self._make_mock_nlp([])
        enrich_chunks_with_ner([], nlp=mock_nlp)  # Should not raise

    def test_enrich_chunks_lawrefs_are_lists(self):
        chunks = [{"id": "c1", "text": "nessun riferimento"}]
        mock_nlp = self._make_mock_nlp([[]])
        enrich_chunks_with_ner(chunks, nlp=mock_nlp)
        assert isinstance(chunks[0]["lawRefs"], list)
        assert isinstance(chunks[0]["personRefs"], list)


# ---------------------------------------------------------------------------
# Slow tests (require it_core_news_lg installed)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_load_ner_model_slow():
    """Integration test: load_ner_model() should return a usable spaCy pipeline."""
    pytest.importorskip("spacy")
    from ner import load_ner_model
    nlp = load_ner_model()
    assert nlp is not None
    # Should have only NER component (parser and tagger disabled)
    assert "ner" in nlp.pipe_names or len(nlp.pipe_names) >= 1


@pytest.mark.slow
def test_enrich_chunks_real_model_slow():
    """Integration test: full pipeline with real spaCy model (no mock)."""
    pytest.importorskip("spacy")
    from ner import enrich_chunks_with_ner, load_ner_model
    try:
        nlp = load_ner_model()
    except OSError:
        pytest.skip("it_core_news_lg not installed")

    chunks = [
        {"id": "c1", "text": "Il decreto legislativo 81/2008 tutela i lavoratori."},
    ]
    enrich_chunks_with_ner(chunks, nlp=nlp)
    assert "lawRefs" in chunks[0]
    assert "personRefs" in chunks[0]
    assert isinstance(chunks[0]["lawRefs"], list)
