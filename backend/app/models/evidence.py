"""
Evidence models for the Multi-View RAG system.

Citation integrity invariant: chunk_text is a retrieval preview and may be
preprocessed, while quote_text is extracted verbatim from speech.text via
offsets and is the only valid citation source. Citations are verified by
re-extracting from offsets, never by comparing against chunk_text, and no
fuzzy matching is involved.
"""
from datetime import date as date_type
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator


# Name normalisation (deterministic, applied at retrieval time)

PARTY_DISPLAY_NAMES: dict[str, str] = {
    "FRATELLI D'ITALIA": "Fratelli d'Italia",
    "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA": "Partito Democratico - Italia Democratica e Progressista",
    "LEGA - SALVINI PREMIER": "Lega - Salvini Premier",
    "MOVIMENTO 5 STELLE": "Movimento 5 Stelle",
    "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE": "Forza Italia - Berlusconi Presidente - PPE",
    "ALLEANZA VERDI E SINISTRA": "Alleanza Verdi e Sinistra",
    "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE": "Azione - Popolari Europeisti Riformatori - Renew Europe",
    "ITALIA VIVA-CASA RIFORMISTA (IV-CR)": "Italia Viva - Casa Riformista",
    "ITALIA VIVA-IL CENTRO-RENEW EUROPE": "Italia Viva - Il Centro - Renew Europe",
    "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE": "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
    # Historical names of renamed groups (a rename chain, not distinct groups):
    # the joint Azione-IV group renamed itself to Azione-PER-RE when IV left
    # (those who left got a new membership; those who stayed keep the
    # membership under the old label)
    "AZIONE - ITALIA VIVA - RENEW EUROPE": "Azione - Popolari Europeisti Riformatori - Renew Europe",
    "NOI MODERATI": "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
    "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC, ITALIA AL CENTRO)-MAIE": "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
    "MISTO": "Misto",
    "GOVERNO": "Governo",
    # Senate groups (dati.senato.it names, current denomination). Same party as
    # the Camera group, so "tutti i gruppi" counts it once across chambers;
    # FdI, PD, M5S, FI-PPE already match once case is ignored.
    "LEGA SALVINI PREMIER - PARTITO SARDO D'AZIONE": "Lega - Salvini Premier",
    "ITALIA VIVA - CASA RIFORMISTA": "Italia Viva - Casa Riformista",
    "CIVICI D'ITALIA-UDC-NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE": "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
    "PER LE AUTONOMIE (SVP-PATT, CAMPOBASE)": "Per le Autonomie (SVP-PATT, Campobase)",
}


def _party_key(name: str) -> str:
    return " ".join(name.upper().replace(" - ", "-").replace("- ", "-").replace(" -", "-").split())


_PARTY_BY_KEY: dict[str, str] = {_party_key(k): v for k, v in PARTY_DISPLAY_NAMES.items()}
_PARTY_BY_KEY.update({_party_key(v): v for v in PARTY_DISPLAY_NAMES.values()})


def normalize_speaker_name(first_name: str, last_name: str) -> str:
    """Return speaker name in title case (e.g. 'Mario Rossi')."""
    full = f"{first_name} {last_name}".strip()
    return full.title() if full else ""


def normalize_party_name(raw_party: str) -> str:
    """Map a DB group name (Camera UPPERCASE, Senate mixed case) or a display
    name to the display name of its party."""
    if not raw_party:
        return "Misto"
    return _PARTY_BY_KEY.get(_party_key(raw_party), raw_party.title())


class IdeologyScore(BaseModel):
    """Ideological positioning score for a fragment or speaker."""
    left: float = Field(ge=0.0, le=1.0, description="Left positioning score")
    center: float = Field(ge=0.0, le=1.0, description="Center positioning score")
    right: float = Field(ge=0.0, le=1.0, description="Right positioning score")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence in the score")
    method: Literal["kde", "mean_ellipse", "insufficient_data"] = Field(
        description="Method used to compute the score"
    )


class UnifiedEvidence(BaseModel):
    """
    Evidence record.

    See the module docstring for the chunk_text / quote_text citation
    integrity invariant.
    """
    # Identifiers
    evidence_id: str = Field(description="Chunk ID - unique identifier")
    doc_id: str = Field(description="Session ID")
    speech_id: str = Field(description="Speech ID")
    speaker_id: str = Field(description="Deputy or GovernmentMember ID")
    # Official page of the speech, when the graph has one (Senate: the
    # intervention on senato.it, or its sitting). None for the Camera, whose
    # links the frontends build from speech_id.
    url: Optional[str] = Field(default=None, description="Official URL of the speech")

    # Speaker info
    speaker_name: str = Field(description="Full speaker name")
    speaker_role: Literal["Deputy", "GovernmentMember"] = Field(
        description="Speaker type"
    )
    party: str = Field(description="Parliamentary group name")
    coalition: Literal["maggioranza", "opposizione", "governo", "misto"] = Field(
        description="Coalition membership ('misto' = Gruppo Misto, non ascrivibile a uno schieramento)"
    )
    # Group-change transparency: True when the speaker has since moved to a different group
    party_changed: bool = Field(default=False, description="Whether speaker changed group after this speech")
    current_party: Optional[str] = Field(default=None, description="Current group name if party_changed is True")
    # Gruppo Misto component at speech date (e.g. "+EUROPA - STATI UNITI
    # D'EUROPA", "FUTURO NAZIONALE VANNACCI - FREE"): the Misto holds
    # opposing components, so attribution always goes to the component.
    misto_component: Optional[str] = Field(default=None, description="Misto sub-component at speech date")
    date: date_type = Field(description="Date of the intervention")

    chunk_text: str = Field(
        description="chunk.text - used for retrieval/preview ONLY. "
                    "May be preprocessed. NOT valid for citation."
    )
    quote_text: str = Field(
        description="VERBATIM extraction from speech.text[span_start:span_end]. "
                    "This is the ONLY valid citation source."
    )

    # Offset metadata for verification.
    # span_end == 0 (with span_start == 0) means "offsets unknown": the citation
    # flow extracts from chunk_text and skips span extraction when
    # span_end <= span_start.
    span_start: int = Field(ge=0, description="Start offset in text")
    span_end: int = Field(ge=0, description="End offset in text (0 = unknown)")

    # Context
    debate_title: Optional[str] = Field(default=None, description="Debate title")
    session_number: int = Field(description="Session number")

    # Scores
    similarity: float = Field(ge=0.0, le=1.0, description="Semantic similarity score")
    authority_score: float = Field(
        ge=0.0, le=1.0, default=0.0, description="Speaker authority score"
    )
    # Salience computed by the merger (stored citability or regex fallback).
    # Without this field the value was dropped at model construction and
    # recomputed with the regex in generation/pipeline.
    salience: Optional[float] = Field(
        default=None, ge=0.0, le=1.0, description="Political salience score"
    )

    # Citability pre-computed at index time (PLAN_citation_quality Phase 1).
    # None = chunk not yet classified → regex fallback at runtime.
    citability_score: Optional[float] = Field(
        default=None, ge=0.0, le=1.0,
        description="Index-time citability score from batch LLM classification"
    )
    citability_class: Optional[str] = Field(
        default=None,
        description="Citability class: substance | procedural | rhetoric | meta"
    )
    best_quote: Optional[str] = Field(
        default=None,
        description="Pre-extracted most citable verbatim sentence of the chunk"
    )
    ideology: Optional[IdeologyScore] = Field(
        default=None, description="Ideological positioning"
    )

    # Embedding for compass PCA analysis (optional, excluded from API response serialization)
    embedding: Optional[List[float]] = Field(
        default=None,
        description="Chunk embedding vector for compass analysis",
        exclude=True  # Don't include in JSON responses (too large)
    )

    # Full speech text — excluded from API responses but needed by CitationSurgeon
    # to expand mid-sentence chunk boundaries back to the sentence start.
    text: str = Field(
        default="",
        description="Full speech text (speech.text). Used by CitationSurgeon for "
                    "sentence-boundary expansion when chunk starts mid-sentence.",
        exclude=True  # Don't include in JSON responses (too large)
    )

    @field_validator("span_end")
    @classmethod
    def validate_span_order(cls, v: int, info) -> int:
        """Ensure span_end >= span_start (0/0 = offsets unknown, allowed)."""
        if "span_start" in info.data and v < info.data["span_start"]:
            raise ValueError("span_end must be >= span_start")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "evidence_id": "leg19_sed123_tit00010.int00005_chunk_2",
                "doc_id": "leg19_sed123",
                "speech_id": "leg19_sed123_tit00010.int00005",
                "speaker_id": "d300001",
                "speaker_name": "Mario Rossi",
                "speaker_role": "Deputy",
                "party": "FRATELLI D'ITALIA",
                "coalition": "maggioranza",
                "date": "2023-05-15",
                "chunk_text": "Preview text for retrieval...",
                "quote_text": "Exact verbatim quote from text",
                "span_start": 1523,
                "span_end": 1687,
                "debate_title": "Discussione DL immigrazione",
                "session_number": 123,
                "similarity": 0.85,
                "authority_score": 0.72,
                "ideology": {
                    "left": 0.1,
                    "center": 0.3,
                    "right": 0.6,
                    "confidence": 0.8,
                    "method": "kde"
                }
            }
        }


def compute_chunk_span(speech_text: str, chunk_text: str) -> tuple:
    """
    Compute the exact (start, end) of a chunk inside its speech text.

    Schema v2: chunk.text is an exact substring of speech.text (invariant C8
    enforced at build time), so find() is exact by construction. (0, 0) means
    "offsets unknown" and the citation flow falls back to chunk_text.

    Returns:
        (span_start, span_end) tuple.
    """
    if speech_text and chunk_text:
        pos = speech_text.find(chunk_text)
        if pos >= 0:
            return pos, pos + len(chunk_text)
    return 0, 0


def compute_quote_text(speech_text: str, span_start: int, span_end: int) -> str:
    """
    Extract quote using offsets, with automatic clamping and word-boundary alignment.

    This function:
    1. Clamps offsets to valid text bounds
    2. Extends start backward to the nearest word boundary (space or start of text)
    3. Extends end forward to the nearest word boundary (space or end of text)

    Args:
        speech_text: The raw speech text
        span_start: Start offset (inclusive)
        span_end: End offset (exclusive)

    Returns:
        Extracted quote aligned to word boundaries

    Raises:
        ValueError: If offsets are completely invalid (negative end, start > end after clamping)
    """
    text_len = len(speech_text)

    # Handle empty text
    if text_len == 0:
        return ""

    # Clamp offsets to valid bounds
    span_start = max(0, span_start)
    span_end = min(text_len, span_end)

    # Validate after clamping
    if span_start >= span_end:
        raise ValueError(
            f"Invalid span after clamping: start={span_start}, end={span_end}"
        )

    # Extend start backward to word boundary (find previous space or start of text)
    while span_start > 0 and speech_text[span_start] != ' ' and speech_text[span_start - 1] != ' ':
        span_start -= 1

    # Skip leading space if we landed on one
    if span_start < text_len and speech_text[span_start] == ' ':
        span_start += 1

    # Extend end forward to word boundary (find next space or end of text)
    while span_end < text_len and speech_text[span_end - 1] != ' ' and speech_text[span_end] != ' ':
        span_end += 1

    # Strip trailing space if we landed before one
    while span_end > span_start and speech_text[span_end - 1] == ' ':
        span_end -= 1

    return speech_text[span_start:span_end]


def verify_citation_integrity(
    quote_or_evidence,
    speech_text: str,
    span_start: Optional[int] = None,
    span_end: Optional[int] = None
) -> bool:
    """
    Verify a citation by re-extracting it from the source text.

    Accepts either a UnifiedEvidence (offsets read from the object) or a
    quote string with explicit span_start/span_end. Returns True when the
    re-extracted span matches the quote; False when offsets are missing.
    """
    if isinstance(quote_or_evidence, UnifiedEvidence):
        evidence = quote_or_evidence
        return speech_text[evidence.span_start:evidence.span_end] == evidence.quote_text
    if span_start is None or span_end is None:
        return False
    return speech_text[span_start:span_end] == quote_or_evidence
