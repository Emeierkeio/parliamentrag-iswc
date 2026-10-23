"""
Timeline endpoints for browsing parliamentary sessions, debates, and speaker summaries.

Read-only endpoints serving pre-computed AI summaries from Neo4j.

Endpoints:
  GET /api/timeline                             → paginated session list
  GET /api/timeline/debates/{debate_id}         → debate detail
  GET /api/timeline/speakers/{debate_id}/{speaker_id} → speaker AI summary
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from ..models.timeline import (
    DebateDetailResponse,
    SpeakerSummaryResponse,
    TimelineResponse,
    VoteActTextResponse,
    VoteDetailResponse,
    VoteInfo,
)
from ..services.neo4j_client import Neo4jClient, get_neo4j_client
from ..services import timeline_service

router = APIRouter(prefix="/api/timeline", tags=["timeline"])


@router.get("")
async def get_timeline(
    request: Request,
    before: Optional[str] = None,
    limit: int = 20,
    chamber: str = "camera",  # demo DB is Camera-only
    legislature: int = 19,
    search: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    with_votes: bool = False,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> TimelineResponse:
    """Get paginated timeline of parliamentary sessions, most recent first."""
    locale = request.headers.get("Accept-Language", "it")[:2]
    return await timeline_service.get_sessions(
        neo4j=neo4j,
        locale=locale,
        before=before,
        limit=limit,
        chamber=chamber,
        legislature=legislature,
        search=search,
        from_date=from_date,
        to_date=to_date,
        with_votes=with_votes,
    )


@router.get("/debates/{debate_id}")
async def get_debate_detail(
    debate_id: str,
    request: Request,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> DebateDetailResponse:
    """Get detailed debate information with phases, speakers, votes, and acts."""
    locale = request.headers.get("Accept-Language", "it")[:2]
    return await timeline_service.get_debate_detail(
        neo4j=neo4j,
        debate_id=debate_id,
        locale=locale,
    )


@router.get("/sessions/{session_id}/votes")
async def get_session_votes(
    session_id: str,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> list[VoteInfo]:
    """List every roll-call vote of a sitting (votes are recorded per sitting)."""
    return await timeline_service.get_session_votes(neo4j=neo4j, session_id=session_id)


@router.get("/votes/{vote_id}")
async def get_vote_detail(
    vote_id: str,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> VoteDetailResponse:
    """Get roll-call detail: metadata, per-party breakdown, individual votes."""
    return await timeline_service.get_vote_detail(neo4j=neo4j, vote_id=vote_id)


@router.get("/votes/{vote_id}/act-text")
async def get_vote_act_text(
    vote_id: str,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> VoteActTextResponse:
    """Full text of the amendment/article the roll call voted on (Allegato A)."""
    result = await timeline_service.get_vote_act_text(neo4j=neo4j, vote_id=vote_id)
    if result is None:
        raise HTTPException(status_code=404, detail="No extractable text for this vote")
    return result


@router.get("/speakers/{debate_id}/{speaker_id:path}")
async def get_speaker_summary(
    debate_id: str,
    speaker_id: str,
    request: Request,
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> SpeakerSummaryResponse:
    """Get AI-generated speaker position summary for a specific debate."""
    locale = request.headers.get("Accept-Language", "it")[:2]
    return await timeline_service.get_speaker_summary(
        neo4j=neo4j,
        debate_id=debate_id,
        speaker_id=speaker_id,
        locale=locale,
    )
