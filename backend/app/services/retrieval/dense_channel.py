"""
Dense retrieval channel: semantic search on pre-computed chunk embeddings
via Neo4j's native vector index, or via the Postgres text archive for the
scopes it covers (services/archive.py); archive hits are joined to the graph
by chunk id, so both paths return the same rows.

Similarity scores are on the Neo4j vector-index scale, cosine mapped to
[0,1] as (1+cos)/2. The graph channel normalizes to the same scale so the
merger can compare the two channels.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..neo4j_client import Neo4jClient
from ...models.evidence import (
    normalize_speaker_name, normalize_party_name, compute_chunk_span, speaking_party,
)
from ...config import get_config

from ..archive import RETRIEVAL_ROW, fill_rows, get_archive
from .scope import DEFAULT_SCOPE, Scope, scope_param, session_clause, vector_indexes

logger = logging.getLogger(__name__)


# Candidate chunks from the Neo4j vector index, or from a list of archive hits
# ($hits: [{id, similarity}]); both bind c and score for HIT_BODY.
VECTOR_HEAD = """
        CALL db.index.vector.queryNodes($index_name, $top_k, $query_embedding)
        YIELD node AS c, score"""
HITS_HEAD = """
        UNWIND $hits AS hit
        MATCH (c:Chunk {id: hit.id})
        WITH c, hit.similarity AS score"""


class DenseChannel:
    """
    Dense retrieval channel using vector similarity search.

    Performs semantic search on Chunk.embedding using Neo4j vector index.
    """

    def __init__(self, neo4j_client: Neo4jClient):
        """Initialize with a Neo4j client and the app config."""
        self.client = neo4j_client
        self.config = get_config()

    def retrieve(
        self,
        query_embedding: List[float],
        top_k: Optional[int] = None,
        similarity_threshold: Optional[float] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        scope: Scope = DEFAULT_SCOPE,
    ) -> List[Dict[str, Any]]:
        """
        Perform vector similarity search.

        Args:
            query_embedding: Query embedding vector (1536 dimensions)
            top_k: Number of results to return
            similarity_threshold: Minimum similarity score, on the Neo4j
                vector-index scale (cosine mapped to [0,1] as (1+cos)/2)
            date_start: Optional session-date lower bound, "YYYY-MM-DD"
            date_end: Optional session-date upper bound, "YYYY-MM-DD"
            scope: (chamber, legislature) pairs to search

        Returns:
            List of evidence candidates with metadata
        """
        retrieval_config = self.config.retrieval.get("dense_channel", {})
        top_k = top_k or retrieval_config.get("top_k", 200)
        threshold = similarity_threshold or retrieval_config.get("similarity_threshold", 0.55)
        index_name = retrieval_config.get("index_name", "chunk_embedding_index")

        logger.info(f"Dense channel: retrieving top {top_k} chunks (threshold={threshold})")

        # s.date is a Neo4j Date: cast the string bounds with date() so the
        # comparison is Date-vs-Date (string-vs-Date silently matches nothing).
        date_filter = ""
        params: Dict[str, Any] = {
            "index_name": index_name,
            "top_k": top_k,
            "query_embedding": query_embedding,
            "threshold": threshold
        }
        if date_start:
            date_filter += " AND s.date >= date($date_start)"
            params["date_start"] = date_start
        if date_end:
            date_filter += " AND s.date <= date($date_end)"
            params["date_end"] = date_end
        date_filter += " AND " + session_clause()
        params["scope"] = scope_param(scope)

        # No MATCH clause may precede db.index.vector.queryNodes: the index
        # procedure must be the first clause or Neo4j falls back to a scan.
        cypher = VECTOR_HEAD + self.HIT_BODY.format(date_filter=date_filter)

        archive = get_archive()
        archived = [p for p in scope if archive and archive.covers(p)]
        graph_scope = tuple(p for p in scope if p not in archived)

        results: List[Dict[str, Any]] = []
        if graph_scope:
            for index in vector_indexes(self.client, graph_scope, index_name):
                results.extend(self.client.query(
                    cypher, {**params, "index_name": index, "scope": scope_param(graph_scope)}))
        for pair in archived:
            hits = archive.search(query_embedding, pair, top_k, threshold, date_start, date_end)
            results.extend(self.client.query(
                HITS_HEAD + self.HIT_BODY.format(date_filter=date_filter),
                {**params, "hits": hits, "scope": scope_param((pair,))}))
        if len(results) > top_k:
            results = sorted(results, key=lambda r: r["similarity"], reverse=True)[:top_k]
        fill_rows(results, **RETRIEVAL_ROW)

        logger.info(f"Dense channel: retrieved {len(results)} chunks")
        return self._process_results(results)

    # Everything after the candidate chunks c and their score: speaker, sitting
    # and group of each chunk. Shared by the Neo4j index and the archive path.
    HIT_BODY = """
        WHERE score >= $threshold
        MATCH (c)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(speaker)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)<-[:HAS_DEBATE]-(s:Session)
        WHERE 1=1{date_filter}
        // Deputy's party: only if the membership is still active today (for a closed
        // legislature: still active on its last day, final_in_legislature).
        // If the deputy switched group (mg.end_date < date()), the chunk is
        // attributed to the new group or discarded — never to the previous group.
        OPTIONAL MATCH (speaker)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= date()
              OR (mg.final_in_legislature AND mg.legislature = s.legislature))
        // Current party: present group (membership still open).
        OPTIONAL MATCH (speaker)-[mg_now:MEMBER_OF_GROUP]->(g_now:ParliamentaryGroup)
        WHERE mg_now.end_date IS NULL
        // Gruppo Misto component at speech date: the Misto contains opposed
        // components (+Europa vs Futuro Nazionale Vannacci), so attribution
        // goes to the component, never to the monolithic Misto.
        OPTIONAL MATCH (speaker)-[mcp:MEMBER_OF_COMPONENT]->(mcomp:MistoComponent)
        WHERE mcp.start_date <= s.date AND (mcp.end_date IS NULL OR mcp.end_date >= s.date)
        RETURN c.id AS chunk_id,
               c.text AS chunk_text,
               c.embedding AS embedding,
               c.index AS chunk_index,
               i.id AS speech_id,
               i.text AS text,
               i.url AS url,
               speaker.id AS speaker_id,
               speaker.first_name AS speaker_first_name,
               speaker.last_name AS speaker_last_name,
               CASE WHEN coalesce(i.speaker_in_government, 'GovernmentMember' IN labels(speaker)) THEN 'GovernmentMember' ELSE 'Deputy' END AS speaker_type,
               g.name AS party,
               g_now.name AS current_party,
               s.id AS session_id,
               s.date AS session_date,
               s.number AS session_number,
               coalesce(d.parent_debate_title, d.title) AS debate_title,
               mcomp.name AS misto_component,
               c.citability_score AS citability_score,
               c.citability_class AS citability_class,
               c.best_quote AS best_quote,
               score AS similarity
        ORDER BY score DESC
        """

    def _process_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process raw query results into structured evidence candidates.

        Computes quote_text from text using offsets.
        """
        processed = []
        config = get_config()

        for row in results:
            try:
                text = row.get("text", "")
                # chunk_text is the citation source, exact by construction
                # (invariant C8); the span locates it inside the speech for
                # position-aware heuristics and integrity checks.
                quote_text = row.get("chunk_text", "") or text
                if not quote_text:
                    logger.warning(f"Missing text for chunk {row.get('chunk_id')}")
                span_start, span_end = compute_chunk_span(
                    text, row.get("chunk_text", "")
                )

                # Determine coalition using the historical party (group at speech time).
                # current_party is the group the speaker belongs to TODAY — used only
                # to compute party_changed, never for attribution or coalition assignment.
                group = row.get("party")           # historical (at speech date)
                # A Misto speaker counts for their component (+Europa, AVS…)
                party = speaking_party(group, row.get("misto_component"))
                current_party_raw = row.get("current_party")  # today's group
                speaker_role = row.get("speaker_type", "Deputy")

                if party is None and speaker_role != "GovernmentMember":
                    # Chunk with no historical attribution (missing DB data): skip.
                    logger.debug(
                        f"Skipping chunk {row.get('chunk_id')}: no historical group found "
                        f"for speaker {row.get('speaker_last_name')} at {row.get('session_date')}"
                    )
                    continue

                if speaker_role == "GovernmentMember":
                    party = party or "GOVERNO"
                    coalition = "governo"
                    party_changed = False
                    current_party_display = None
                else:
                    coalition = config.get_coalition(party) if party else "opposizione"
                    # Group, not component: a Misto senator still in the
                    # Misto has not changed party
                    historical_display = normalize_party_name(group)
                    current_party_display = normalize_party_name(current_party_raw) if current_party_raw else None
                    # Changed if today's group differs from the historical one
                    party_changed = bool(
                        current_party_display and current_party_display != historical_display
                    )

                # Parse date - handles both Neo4j Date objects and string formats
                session_date = row.get("session_date")
                if session_date is not None:
                    if hasattr(session_date, 'to_native'):
                        # Neo4j Date object
                        date_obj = session_date.to_native()
                    elif isinstance(session_date, str) and session_date:
                        try:
                            # Handle DD/MM/YYYY format (legacy)
                            date_obj = datetime.strptime(session_date, "%d/%m/%Y").date()
                        except ValueError:
                            date_obj = datetime.now().date()
                    else:
                        date_obj = datetime.now().date()
                else:
                    date_obj = datetime.now().date()

                processed.append({
                    "evidence_id": row.get("chunk_id", ""),
                    "doc_id": row.get("session_id", ""),
                    "speech_id": row.get("speech_id", ""),
                    # senato.it link to the speech (Senate only; Camera links
                    # are built by the frontends from the id)
                    "url": row.get("url"),
                    "speaker_id": row.get("speaker_id", ""),
                    "speaker_name": normalize_speaker_name(row.get('speaker_first_name', ''), row.get('speaker_last_name', '')),
                    "speaker_role": row.get("speaker_type", "Deputy"),
                    "party": normalize_party_name(party),
                    "coalition": coalition,
                    # Group-switch transparency: if True, current_party shows today's group
                    "party_changed": party_changed,
                    "current_party": current_party_display if party_changed else None,
                    "date": date_obj,
                    "chunk_text": row.get("chunk_text", ""),
                    "quote_text": quote_text,
                    "text": text,  # Full speech text — needed by surgeon for sentence expansion
                    "span_start": span_start,
                    "span_end": span_end,
                    "debate_title": row.get("debate_title"),
                    "session_number": row.get("session_number", 0),
                    "similarity": row.get("similarity", 0.0),
                    "embedding": row.get("embedding"),  # For compass PCA
                    # Citability pre-computed at index time (Phase 1); None on
                    # chunks not yet classified, treated as neutral (0.5) by
                    # the merger
                    "citability_score": row.get("citability_score"),
                    "citability_class": row.get("citability_class"),
                    "best_quote": row.get("best_quote"),
                    "misto_component": row.get("misto_component"),
                    "retrieval_channel": "dense"
                })
            except Exception as e:
                logger.error(f"Error processing result: {e}")
                continue

        return processed
