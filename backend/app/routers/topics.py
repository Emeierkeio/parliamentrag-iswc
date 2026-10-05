"""
Ready topic dossiers: the latest saved answer for each curated topic.

A dossier is a saved "posizione dei gruppi sul tema" answer (ChatHistory),
rendered by the frontend at /tema/{id}. Only curated topics and exact
topic-form queries are listed, so the endpoint never exposes free-text
questions typed by visitors.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from ..services.neo4j_client import Neo4jClient, get_neo4j_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/topics", tags=["Topics"])

# Same list and order as the Italian chips in frontend/src/lib/constants.ts.
CURATED_TOPICS = [
    "PNRR",
    "riforma sanitaria",
    "transizione energetica",
    "salario minimo",
    "conflitto in Ucraina",
    "autonomia differenziata",
    "riforma della giustizia",
    "flussi migratori",
]

TOPIC_QUERY_PREFIX = "qual è la posizione dei gruppi parlamentari sul tema: "


class TopicDossier(BaseModel):
    topic: str
    id: Optional[str] = None
    timestamp: Optional[str] = None
    interventions: Optional[int] = None
    speakers: Optional[int] = None


def _latest_dossiers(neo4j: Neo4jClient, topics: list[str]) -> dict[str, dict]:
    rows = neo4j.query(
        """
        UNWIND $topics AS topic
        MATCH (c:ChatHistory)
        WHERE toLower(c.query) = $prefix + toLower(topic) + '?'
          AND c.answer IS NOT NULL AND size(c.answer) > 500
        WITH topic, c ORDER BY c.timestamp DESC
        WITH topic, collect(c)[0] AS c
        RETURN topic, c.id AS id, c.timestamp AS timestamp, c.topic_stats AS stats
        """,
        {"topics": topics, "prefix": TOPIC_QUERY_PREFIX},
    )
    return {r["topic"]: r for r in rows}


def _to_dossier(topic: str, row: Optional[dict]) -> TopicDossier:
    if not row:
        return TopicDossier(topic=topic)
    stats = {}
    try:
        stats = json.loads(row["stats"]) if isinstance(row["stats"], str) else (row["stats"] or {})
    except (TypeError, ValueError):
        logger.warning("Unreadable topic_stats on dossier %s", row["id"])
    return TopicDossier(
        topic=topic,
        id=row["id"],
        timestamp=str(row["timestamp"]) if row["timestamp"] else None,
        interventions=stats.get("intervention_count"),
        speakers=stats.get("speaker_count"),
    )


@router.get("")
async def list_topics(neo4j: Neo4jClient = Depends(get_neo4j_client)) -> list[TopicDossier]:
    """Curated topics, each with its latest dossier when one exists."""
    found = _latest_dossiers(neo4j, CURATED_TOPICS)
    return [_to_dossier(t, found.get(t)) for t in CURATED_TOPICS]


@router.get("/match")
async def match_topic(
    q: str = Query(..., min_length=2, max_length=120),
    neo4j: Neo4jClient = Depends(get_neo4j_client),
) -> TopicDossier:
    """The latest dossier whose topic is exactly `q` (case-insensitive)."""
    topic = q.strip()
    return _to_dossier(topic, _latest_dossiers(neo4j, [topic]).get(topic))
