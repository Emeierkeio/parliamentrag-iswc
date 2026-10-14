"""
Evidence endpoint for retrieving full evidence details.

Provides exact quote extraction with verification.
"""
import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Path
from pydantic import BaseModel

from ..services.archive import RETRIEVAL_ROW, fill_rows
from ..services.neo4j_client import Neo4jClient
from ..models.evidence import (
    compute_chunk_span,
    compute_quote_text,
    verify_citation_integrity,
)
from ..config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/evidence", tags=["Evidence"])


class EvidenceResponse(BaseModel):
    """Full evidence response with exact quote."""
    evidence_id: str
    chunk_id: str
    speech_id: str
    doc_id: str
    # Official page of the speech (Senate); None for the Camera.
    url: Optional[str] = None

    # Speaker info
    speaker_id: str
    speaker_name: str
    speaker_role: str
    party: str
    coalition: str

    # Text content
    chunk_text: str  # Preview text
    quote_text: str  # exact verbatim quote
    text: Optional[str] = None  # Full intervention text (optional)

    # Offsets
    span_start: int
    span_end: int

    # Context
    date: str
    debate_title: Optional[str]
    session_number: int

    # Verification
    citation_verified: bool


# Service instance
_neo4j_client: Optional[Neo4jClient] = None


def get_neo4j():
    """Get or initialize Neo4j client."""
    global _neo4j_client
    if _neo4j_client is None:
        settings = get_settings()
        _neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )
    return _neo4j_client


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: str = Path(..., description="Evidence/Chunk ID")
):
    """
    Get full evidence details by ID.

    Returns the exact verbatim quote extracted via offsets,
    with verification status.
    """
    client = get_neo4j()

    cypher = """
    MATCH (c:Chunk {id: $evidence_id})
    MATCH (c)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(speaker)
    MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)<-[:HAS_DEBATE]-(s:Session)
    OPTIONAL MATCH (speaker)-[:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
    WHERE g IS NULL OR (
        (speaker)-[:MEMBER_OF_GROUP {end_date: null}]->(g) OR
        NOT EXISTS { MATCH (speaker)-[:MEMBER_OF_GROUP {end_date: null}]->(:ParliamentaryGroup) }
    )
    WITH c, i, speaker, d, s, g
    ORDER BY CASE WHEN g IS NOT NULL THEN 0 ELSE 1 END
    LIMIT 1

    RETURN c.id AS chunk_id,
           c.text AS chunk_text,
           i.id AS speech_id,
           i.text AS text,
           i.url AS url,
           speaker.id AS speaker_id,
           speaker.first_name AS first_name,
           speaker.last_name AS last_name,
           CASE WHEN coalesce(i.speaker_in_government, 'GovernmentMember' IN labels(speaker)) THEN 'GovernmentMember' ELSE 'Deputy' END AS speaker_role,
           g.name AS party,
           s.id AS doc_id,
           s.date AS date,
           s.number AS session_number,
           d.title AS debate_title
    """

    with client.session() as session:
        result = session.run(cypher, evidence_id=evidence_id)
        record = result.single()

        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence {evidence_id} not found"
            )

        data = fill_rows([dict(record)], **RETRIEVAL_ROW)[0]

        # Extract exact quote: span computed via find() on the chunk text
        # (exact by construction on schema v2 — C8 invariant; the stored v1
        # offsets were raw-text based and wrong ~43% of the time).
        text = data.get("text", "")
        span_start, span_end = compute_chunk_span(
            text,
            data.get("chunk_text", ""),
        )

        try:
            quote_text = compute_quote_text(text, span_start, span_end)
            citation_verified = verify_citation_integrity(
                quote_text, text, span_start, span_end
            )
        except ValueError as e:
            logger.error(f"Quote extraction failed for {evidence_id}: {e}")
            quote_text = data.get("chunk_text", "")[:200]  # Fallback to chunk preview
            citation_verified = False

        from ..services.authority.coalition_logic import CoalitionLogic
        coalition_logic = CoalitionLogic()
        party = data.get("party") or "MISTO"
        coalition = coalition_logic.get_coalition(party)

        first_name = data.get("first_name", "")
        last_name = data.get("last_name", "")
        speaker_name = f"{first_name} {last_name}".strip() or "Unknown"

        return EvidenceResponse(
            evidence_id=evidence_id,
            chunk_id=data.get("chunk_id", evidence_id),
            speech_id=data.get("speech_id", ""),
            doc_id=data.get("doc_id", ""),
            url=data.get("url"),
            speaker_id=data.get("speaker_id", ""),
            speaker_name=speaker_name,
            speaker_role=data.get("speaker_role", "Deputy"),
            party=party,
            coalition=coalition,
            chunk_text=data.get("chunk_text", ""),
            quote_text=quote_text,
            text=text if len(text) < 10000 else None,  # Omit if too large
            span_start=span_start,
            span_end=span_end,
            date=str(data.get("date", "")),
            debate_title=data.get("debate_title"),
            session_number=data.get("session_number", 0),
            citation_verified=citation_verified,
        )


@router.get("/{evidence_id}/verify")
async def verify_evidence(
    evidence_id: str = Path(..., description="Evidence/Chunk ID")
):
    """
    Verify citation integrity for an evidence piece.

    Returns verification status and details.
    """
    client = get_neo4j()

    cypher = """
    MATCH (c:Chunk {id: $evidence_id})
    MATCH (c)<-[:HAS_CHUNK]-(i:Speech)
    RETURN c.id AS chunk_id,
           c.text AS chunk_text,
           i.id AS speech_id,
           i.text AS text
    """

    with client.session() as session:
        result = session.run(cypher, evidence_id=evidence_id)
        record = result.single()

        if not record:
            raise HTTPException(
                status_code=404,
                detail=f"Evidence {evidence_id} not found"
            )

        data = fill_rows([dict(record)], **RETRIEVAL_ROW)[0]
        text = data.get("text", "")
        span_start, span_end = compute_chunk_span(
            text,
            data.get("chunk_text", ""),
        )

        try:
            quote_text = compute_quote_text(text, span_start, span_end)
            is_valid = True
            error = None
        except ValueError as e:
            quote_text = None
            is_valid = False
            error = str(e)

        return {
            "evidence_id": evidence_id,
            "is_valid": is_valid,
            "span_start": span_start,
            "span_end": span_end,
            "text_length": len(text),
            "quote_text": quote_text,
            "quote_length": len(quote_text) if quote_text else 0,
            "error": error,
        }
