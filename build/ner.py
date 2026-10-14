"""
ner.py — NER extraction module for parliamentary chunk text.

Design rationale:
  - Law references (lawRefs): extracted via regex patterns.
    The spaCy Italian model it_core_news_lg does NOT include a LAW entity label —
    its entities are limited to PER, ORG, LOC, MISC. A custom regex approach is
    therefore the only reliable method for Italian legislative citations.

  - Person references (personRefs): extracted using spaCy's PER entity label from
    it_core_news_lg. Short entities (len <= 2) are filtered to remove noise.

  - enrich_chunks_with_ner(): modifies chunk dicts in-place with both fields.
    Uses nlp.pipe() for batch efficiency (batch_size=100).

Usage:
    from ner import enrich_chunks_with_ner, load_ner_model
    nlp = load_ner_model()
    enrich_chunks_with_ner(chunks, nlp)
"""

from __future__ import annotations

import re
from typing import List

# ---------------------------------------------------------------------------
# Law reference regex patterns
# ---------------------------------------------------------------------------

LAW_PATTERNS = [
    # decreto legislativo / decreto-legge / D.L. / DL / D.Lgs / DLgs
    # with optional number/year
    re.compile(
        r'\b(?:D\.?L(?:gs)?\.?|decreto(?:[-\s]legge|\s+legislativo)?|legge)\s+(?:n\.\s*)?\d+(?:/\d{2,4})?',
        re.I,
    ),
    # Standalone D.lgs / D.Lgs / DLgs variants (alternate spacing)
    re.compile(
        r'\bD\.?\s*(?:L(?:gs)?|lgs)\.?\s*\d+(?:[/-]\d{2,4})?',
        re.I,
    ),
    # d.P.R. — decreto del Presidente della Repubblica
    re.compile(
        r'\bd\.?\s*P\.?\s*R\.?\s*(?:n\.\s*)?\d+(?:/\d{2,4})?',
        re.I,
    ),
    # testo unico / T.U.
    re.compile(
        r'\btesto\s+unico\b|\bT\.U\.',
        re.I,
    ),
    # Direttive e regolamenti UE: "direttiva 2006/112/CE", "regolamento (UE) 2016/679"
    re.compile(
        r'\b(?:direttiva|regolamento)\s+(?:\(?\s*(?:UE|CE|CEE)\s*\)?\s+)?(?:n\.\s*)?\d+/\d+(?:/(?:UE|CE|CEE))?',
        re.I,
    ),
    # Atti Camera/Senato: "A.C. 2505", "A.S. 1234-B" — resolvable to
    # ParliamentaryAct nodes in the graph. Case-sensitive: "a.c." in lowercase
    # prose is almost never an act reference.
    re.compile(
        r'\bA\.\s?[CS]\.\s*(?:n\.\s*)?\d+(?:-[A-Z]+)?',
    ),
    # art. / articolo with optional comma number
    re.compile(
        r'\bart(?:icolo)?\.?\s*\d+(?:\s+(?:comma|c\.)\s*\d+)?',
        re.I,
    ),
    # Costituzione / Cost.
    re.compile(
        r'\bCostituzione\b|\bCost\.\b',
        re.I,
    ),
]


def extract_law_refs(text: str) -> List[str]:
    """
    Extract Italian legislative references from text using regex patterns.

    Covers:
      - Decreti legislativi: "decreto legislativo 231", "D.L. 50/2016", "D.lgs. 81/2008"
      - Leggi: "legge n. 234/2021"
      - Articoli: "art. 10 comma 2"
      - Costituzione / Cost.

    Returns a deduplicated list of matched strings, preserving discovery order.
    """
    if not text:
        return []

    seen: set = set()
    refs: List[str] = []

    for pattern in LAW_PATTERNS:
        for match in pattern.finditer(text):
            ref = match.group(0)
            if ref not in seen:
                seen.add(ref)
                refs.append(ref)

    return refs


def extract_person_refs(doc) -> List[str]:
    """
    Extract person references from a spaCy Doc.

    Filters to entities with label_ == "PER" and text.strip() length > 2.
    Returns a deduplicated list preserving discovery order.

    Args:
        doc: A spaCy Doc object (or compatible mock with .ents attribute).
    """
    seen: set = set()
    refs: List[str] = []

    for ent in doc.ents:
        if ent.label_ == "PER":
            name = ent.text.strip()
            if len(name) > 2 and name not in seen:
                seen.add(name)
                refs.append(name)

    return refs


def load_ner_model():
    """
    Load the Italian spaCy NER model (it_core_news_lg).

    Disables 'parser' and 'tagger' pipelines for NER-only mode (speed).

    Raises:
        OSError: If it_core_news_lg is not installed.
            Install with: python -m spacy download it_core_news_lg
    """
    try:
        import spacy
        nlp = spacy.load("it_core_news_lg", disable=["parser", "tagger"])
        return nlp
    except OSError as e:
        raise OSError(
            "spaCy model 'it_core_news_lg' is not installed. "
            "Run: python -m spacy download it_core_news_lg"
        ) from e


def enrich_chunks_with_ner(chunks: List[dict], nlp=None) -> None:
    """
    Enrich a list of chunk dicts with lawRefs and personRefs in-place.

    Modifies each chunk dict to add:
      - chunk["lawRefs"]: list[str] of law references extracted via regex
      - chunk["personRefs"]: list[str] of person names from spaCy PER entities

    Uses nlp.pipe() for batch efficiency (batch_size=100).

    Args:
        chunks: List of chunk dicts with at least a "text" key.
        nlp: Optional spaCy Language model. If None, load_ner_model() is called.
             Pass an explicit nlp to avoid reloading the model on repeated calls.

    Returns:
        None (modifies chunks in-place).
    """
    if not chunks:
        return

    if nlp is None:
        nlp = load_ner_model()

    texts = [c["text"] for c in chunks]
    for doc, chunk in zip(nlp.pipe(texts, batch_size=100), chunks):
        chunk["lawRefs"] = extract_law_refs(chunk["text"])
        chunk["personRefs"] = extract_person_refs(doc)
