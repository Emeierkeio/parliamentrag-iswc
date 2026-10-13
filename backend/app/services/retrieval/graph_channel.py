"""
Graph/metadata retrieval channel: finds evidence through parliamentary
structure (acts, signatories, committees) rather than text similarity.

Act matching is hybrid: lexical keyword match first, then a semantic rerank
on the act embeddings already stored in the graph (title, Eurovoc,
description), so no dedicated vector index is needed for this channel.
"""
import logging
import re
from typing import List, Dict, Any, Optional
from datetime import datetime

import numpy as np

from ..neo4j_client import Neo4jClient
from ...models.evidence import (
    normalize_speaker_name, normalize_party_name, compute_chunk_span,
)
from ...config import get_config

from ..archive import RETRIEVAL_ROW, fill_rows
from .scope import DEFAULT_SCOPE, Scope, scope_param, session_clause

logger = logging.getLogger(__name__)


def cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    a_arr = np.array(a)
    b_arr = np.array(b)
    norm_a = np.linalg.norm(a_arr)
    norm_b = np.linalg.norm(b_arr)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(a_arr, b_arr) / (norm_a * norm_b))


class GraphChannel:
    """
    Graph/metadata retrieval channel.

    Traverses Act -> Signatory -> Speech -> Chunk, with hybrid act matching
    (lexical + semantic on stored act embeddings) and optional date filtering.
    """

    def __init__(self, neo4j_client: Neo4jClient):
        """Initialize with a Neo4j client and the app config."""
        self.client = neo4j_client
        self.config = get_config()

    def extract_keywords(self, query: str) -> List[str]:
        """Extract stopword-filtered keywords and bigrams for lexical act matching."""
        # Remove common Italian stopwords (including articulated prepositions)
        stopwords = {
            "il", "la", "lo", "i", "gli", "le", "un", "una", "uno",
            "di", "a", "da", "in", "con", "su", "per", "tra", "fra",
            "del", "della", "dello", "dei", "degli", "delle",
            "al", "alla", "allo", "ai", "agli", "alle",
            "dal", "dalla", "dallo", "dai", "dagli", "dalle",
            "nel", "nella", "nello", "nei", "negli", "nelle",
            "sul", "sulla", "sullo", "sui", "sugli", "sulle",
            "col", "coi",
            "e", "o", "ma", "che", "chi", "cui", "quale", "quali",
            "come", "dove", "quando", "perché", "quanto",
            "è", "sono", "essere", "stato", "stata", "stati", "state",
            "ha", "hanno", "avere", "aveva", "avevano",
            "si", "non", "più", "anche", "già", "poi", "però", "quindi",
            "qual", "cosa", "posizione", "partiti", "partito",
            "query", "originale",
        }

        words = re.findall(r'\b\w+\b', query.lower())
        keywords_raw = [w for w in words if w not in stopwords and len(w) > 2]

        # Deduplicate while preserving order
        seen: set = set()
        keywords = [w for w in keywords_raw if not (w in seen or seen.add(w))]

        # Also include bigrams for compound terms
        bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words)-1)
                   if words[i] not in stopwords and words[i+1] not in stopwords]

        # Deduplicate bigrams preserving order
        seen_bi: set = set()
        bigrams_dedup = [b for b in bigrams if not (b in seen_bi or seen_bi.add(b))]

        return keywords + bigrams_dedup[:5]

    def retrieve(
        self,
        query: str,
        query_embedding: List[float],
        top_k: Optional[int] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        scope: Scope = DEFAULT_SCOPE,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve evidence through graph traversal.

        Strategy:
        1. Find relevant ParliamentaryAct via hybrid matching
        2. Get signatories (PRIMARY_SIGNATORY, CO_SIGNATORY)
        3. Traverse to their speeches and chunks

        Args:
            query: User query text
            query_embedding: Query embedding vector
            top_k: Number of results to return
            date_start: Optional start date filter
            date_end: Optional end date filter

        Returns:
            List of evidence candidates
        """
        graph_config = self.config.retrieval.get("graph_channel", {})
        top_k = top_k or graph_config.get("max_acts_per_query", 100)

        keywords = self.extract_keywords(query)
        logger.info(f"Graph channel: keywords = {keywords}")

        if not keywords:
            logger.warning("No keywords extracted, skipping graph channel")
            return []

        relevant_acts = self._find_relevant_acts(keywords, top_k=top_k)

        if not relevant_acts:
            logger.info("No relevant acts found via lexical search")
            return []

        reranked_acts = self._semantic_rerank(relevant_acts, query_embedding)

        act_uris = [act["uri"] for act in reranked_acts[:50]]
        chunks = self._get_chunks_from_signatories(
            act_uris,
            query_embedding=query_embedding,
            date_start=date_start,
            date_end=date_end,
            scope=scope,
        )

        logger.info(f"Graph channel: retrieved {len(chunks)} chunks from {len(act_uris)} acts")
        return chunks

    def _find_relevant_acts(
        self,
        keywords: List[str],
        top_k: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Find relevant ParliamentaryAct via lexical matching.

        Matches against eurovoc, title, and description fields.
        """
        # Build OR conditions for keywords using word-boundary regex.
        # Using =~ instead of CONTAINS prevents false positives where the keyword
        # appears as a substring of a larger token (e.g. "SSN" inside a word
        # containing "ssn", or "ssn" matching acts that only mention "ASN").
        # (?i) makes the match case-insensitive; \b marks word boundaries.
        conditions = []
        params = {}
        for i, kw in enumerate(keywords):
            param_name = f"kw{i}"
            params[param_name] = f"(?i).*\\b{re.escape(kw.lower())}\\b.*"
            conditions.append(f"""
                a.eurovoc =~ ${param_name} OR
                a.title =~ ${param_name} OR
                a.description =~ ${param_name}
            """)

        where_clause = " OR ".join(conditions)

        cypher = f"""
        MATCH (a:ParliamentaryAct)
        WHERE {where_clause}
        RETURN a.uri AS uri,
               a.title AS title,
               a.description AS description,
               a.eurovoc AS eurovoc,
               a.presentation_date AS date,
               a.type AS type,
               a.title_embedding AS title_embedding,
               a.eurovoc_embedding AS eurovoc_embedding,
               a.description_embedding AS description_embedding
        LIMIT {top_k}
        """

        return self.client.query(cypher, params)

    def _semantic_rerank(
        self,
        acts: List[Dict[str, Any]],
        query_embedding: List[float]
    ) -> List[Dict[str, Any]]:
        """
        Rerank acts using semantic similarity with embeddings.

        Uses title_embedding if available, else default score.
        """
        threshold = self.config.retrieval.get("graph_channel", {}).get(
            "semantic_similarity_threshold", 0.4
        )

        scored_acts = []
        for act in acts:
            emb_title = act.get("title_embedding")
            emb_eurovoc = act.get("eurovoc_embedding")
            emb_description = act.get("description_embedding")

            similarities = []
            if emb_title and len(emb_title) == len(query_embedding):
                similarities.append(cosine_similarity(query_embedding, emb_title))
            if emb_eurovoc and len(emb_eurovoc) == len(query_embedding):
                similarities.append(cosine_similarity(query_embedding, emb_eurovoc))
            if emb_description and len(emb_description) == len(query_embedding):
                similarities.append(cosine_similarity(query_embedding, emb_description))

            if similarities:
                act["similarity"] = max(similarities)
            else:
                act["similarity"] = 0.5  # Default for missing embeddings

            if act["similarity"] >= threshold:
                scored_acts.append(act)

        return sorted(scored_acts, key=lambda x: x["similarity"], reverse=True)

    def _get_chunks_from_signatories(
        self,
        act_uris: List[str],
        query_embedding: List[float],
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        scope: Scope = DEFAULT_SCOPE,
    ) -> List[Dict[str, Any]]:
        """
        Get chunks from speeches by act signatories, filtered by chunk-level
        semantic similarity to the query.

        Traverses: Act <- SIGNATORY - Deputy -> SPOKEN_BY <- Speech -> Chunk
        """
        if not act_uris:
            return []

        date_conditions = []
        params = {"act_uris": act_uris}

        # s.date is a Neo4j Date: cast the string bounds with date() so the
        # comparison is Date-vs-Date (string-vs-Date silently matches nothing).
        if date_start:
            date_conditions.append("s.date >= date($date_start)")
            params["date_start"] = date_start
        if date_end:
            date_conditions.append("s.date <= date($date_end)")
            params["date_end"] = date_end
        date_conditions.append(session_clause())
        params["scope"] = scope_param(scope)

        date_clause = " AND ".join(date_conditions) if date_conditions else "1=1"

        graph_cfg = self.config.retrieval.get("graph_channel", {})
        # Candidates are fetched wide and capped AFTER similarity ranking:
        # the production Neo4j predates vector.similarity.cosine(), so the
        # relevance ordering happens in Python on the returned embeddings.
        # ORDER BY c.id only makes the wide fetch deterministic.
        candidate_limit = graph_cfg.get("signatory_candidate_limit", 500)
        chunk_cap = graph_cfg.get("signatory_chunk_cap", 200)
        params["candidate_limit"] = candidate_limit

        cypher = f"""
        MATCH (speaker)-[:PRIMARY_SIGNATORY|CO_SIGNATORY]->(a:ParliamentaryAct)
        WHERE a.uri IN $act_uris
        WITH DISTINCT speaker
        MATCH (i:Speech)-[:SPOKEN_BY]->(speaker)
        MATCH (i)-[:HAS_CHUNK]->(c:Chunk)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)<-[:HAS_DEBATE]-(s:Session)
        WHERE {date_clause}
        OPTIONAL MATCH (speaker)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= date()
              OR (mg.final_in_legislature AND mg.legislature = s.legislature))
        OPTIONAL MATCH (speaker)-[mcp:MEMBER_OF_COMPONENT]->(mcomp:MistoComponent)
        WHERE mcp.start_date <= s.date AND (mcp.end_date IS NULL OR mcp.end_date >= s.date)
        RETURN c.id AS chunk_id,
               c.text AS chunk_text,
               c.embedding AS embedding,
               i.id AS speech_id,
               i.text AS text,
               speaker.id AS speaker_id,
               speaker.first_name AS speaker_first_name,
               speaker.last_name AS speaker_last_name,
               CASE WHEN coalesce(i.speaker_in_government, 'GovernmentMember' IN labels(speaker)) THEN 'GovernmentMember' ELSE 'Deputy' END AS speaker_type,
               g.name AS party,
               s.id AS session_id,
               s.date AS session_date,
               s.number AS session_number,
               coalesce(d.parent_debate_title, d.title) AS debate_title,
               mcomp.name AS misto_component,
               c.citability_score AS citability_score,
               c.citability_class AS citability_class,
               c.best_quote AS best_quote
        ORDER BY c.id
        LIMIT $candidate_limit
        """

        results = fill_rows(self.client.query(cypher, params), **RETRIEVAL_ROW)
        processed = self._process_results(results)

        # Filter chunks by semantic similarity to the query.
        # Signatories may speak on many unrelated topics; this step removes
        # chunks that are topically irrelevant to the current query.
        # Both the stored similarity and the threshold are on the normalized
        # (1+cos)/2 scale shared with the dense channel.
        threshold = self.config.retrieval.get("graph_channel", {}).get(
            "chunk_similarity_threshold", 0.65
        )
        filtered = []
        for chunk in processed:
            emb = chunk.get("embedding")
            if emb and len(emb) == len(query_embedding):
                normalized = (1.0 + cosine_similarity(query_embedding, emb)) / 2.0
                chunk["similarity"] = normalized
                if normalized >= threshold:
                    filtered.append(chunk)
            else:
                filtered.append(chunk)  # Keep chunks with missing embeddings

        n_dropped = len(processed) - len(filtered)
        if n_dropped:
            logger.debug(
                f"Graph channel: dropped {n_dropped}/{len(processed)} chunks "
                f"below chunk_similarity_threshold={threshold}"
            )

        # Cap AFTER ranking by similarity, so the cap keeps the most relevant
        # candidates instead of an arbitrary id-ordered subset (issue #24).
        # Chunks without an embedding carry the 0.5 neutral prior and sort
        # accordingly.
        if len(filtered) > chunk_cap:
            filtered.sort(key=lambda ch: ch.get("similarity", 0.0), reverse=True)
            logger.info(
                f"Graph channel: capping {len(filtered)} candidates to the "
                f"{chunk_cap} most similar"
            )
            filtered = filtered[:chunk_cap]
        return filtered

    def _process_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Process raw results into evidence format."""
        processed = []
        config = get_config()

        for row in results:
            try:
                text = row.get("text", "")
                # chunk_text is the citation source, exact by construction
                # (invariant C8); the span locates it inside the speech for
                # position-aware heuristics and integrity checks.
                quote_text = row.get("chunk_text", "") or text
                span_start, span_end = compute_chunk_span(
                    text, row.get("chunk_text", "")
                )

                # If party is NULL the speaker's current group doesn't cover
                # this session date (e.g. they switched group after the debate).
                # Skip the result — the deputy should only be cited for speeches
                # made while in their current group.
                party = row.get("party")
                speaker_role = row.get("speaker_type", "Deputy")
                if party is None and speaker_role != "GovernmentMember":
                    logger.debug(
                        f"Skipping chunk {row.get('chunk_id')}: speaker "
                        f"{row.get('speaker_last_name')} has no current group "
                        f"covering session date {row.get('session_date')}"
                    )
                    continue
                if speaker_role == "GovernmentMember":
                    party = party or "GOVERNO"
                    coalition = "governo"
                else:
                    coalition = config.get_coalition(party) if party else "opposizione"

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
                    "speaker_id": row.get("speaker_id", ""),
                    "speaker_name": normalize_speaker_name(row.get('speaker_first_name', ''), row.get('speaker_last_name', '')),
                    "speaker_role": row.get("speaker_type", "Deputy"),
                    "party": normalize_party_name(party),
                    "coalition": coalition,
                    "date": date_obj,
                    "chunk_text": row.get("chunk_text", ""),
                    "quote_text": quote_text,
                    "text": text,  # Full speech text — needed by surgeon for sentence expansion
                    "span_start": span_start,
                    "span_end": span_end,
                    "debate_title": row.get("debate_title"),
                    "session_number": row.get("session_number", 0),
                    # Neutral prior on the normalized (1+cos)/2 scale for
                    # chunks whose embedding is missing; overwritten with the
                    # real normalized similarity in _get_chunks_from_signatories.
                    "similarity": 0.5,
                    "embedding": row.get("embedding"),  # For compass PCA
                    # Citability pre-computed at index time (Phase 1); None on
                    # chunks not yet classified, treated as neutral (0.5) by
                    # the merger
                    "citability_score": row.get("citability_score"),
                    "citability_class": row.get("citability_class"),
                    "best_quote": row.get("best_quote"),
                    "misto_component": row.get("misto_component"),
                    "retrieval_channel": "graph"
                })
            except Exception as e:
                logger.error(f"Error processing graph result: {e}")
                continue

        return processed
