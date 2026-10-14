"""
Main retrieval engine orchestrating dual-channel retrieval.

Coordinates dense and graph channels, applies authority scoring,
and returns unified evidence records.
"""
import asyncio
import logging
import time
from typing import List, Dict, Any, Optional
from datetime import date

from ..neo4j_client import Neo4jClient
from ...key_pool import make_client
from ...tracing import stage
from ..archive import RETRIEVAL_ROW, fill_rows, get_archive
from .dense_channel import HITS_HEAD, VECTOR_HEAD, DenseChannel
from .graph_channel import GraphChannel
from .merger import ChannelMerger
from .query_rewriter import QueryRewriter
from ...models.evidence import UnifiedEvidence
from ...config import get_config, get_settings

from .scope import Scope, normalize_scope, scope_param, session_clause, vector_indexes

logger = logging.getLogger(__name__)


class RetrievalEngine:
    """
    Main retrieval engine for dual-channel evidence retrieval.

    Orchestrates:
    1. Query embedding generation
    2. Dense channel retrieval (vector search)
    3. Graph channel retrieval (metadata/structure)
    4. Channel merging with authority weighting
    5. Evidence record creation
    """

    def __init__(self, neo4j_client: Neo4jClient):
        """Initialize channels, merger, rewriter and config."""
        self.client = neo4j_client
        self.dense_channel = DenseChannel(neo4j_client)
        self.graph_channel = GraphChannel(neo4j_client)
        self.merger = ChannelMerger()
        self.query_rewriter = QueryRewriter()
        self.config = get_config()
        self.settings = get_settings()

        self.openai_client = make_client()

    def embed_query(self, query: str) -> List[float]:
        """Generate the query embedding via OpenAI (1536 dimensions)."""
        llm_config = self.config.load_config().get("llm", {})
        model = llm_config.get("embedding_model", "text-embedding-3-small")

        response = self.openai_client.embeddings.create(
            input=query,
            model=model
        )

        return response.data[0].embedding

    @stage("retrieval")
    def retrieve_sync(
        self,
        query: str,
        top_k: int = 100,
        authority_scores: Optional[Dict[str, float]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        locale: str = "it",
        scope: Optional[Scope] = None,
    ) -> Dict[str, Any]:
        """
        Perform dual-channel retrieval (synchronous version).

        Dense and graph channels run in parallel; wall-clock time is the
        slower of the two rather than their sum.

        Returns:
            Dictionary with evidence list and metadata
        """
        from concurrent.futures import ThreadPoolExecutor

        start_time = time.time()
        scope = normalize_scope(scope)

        # Rewrite short/ambiguous queries before retrieval.
        # The rewritten query is used for embedding + graph keyword search;
        # the original query is kept for logging and UI display.
        retrieval_query = self.query_rewriter.rewrite(query, locale=locale)

        logger.info(f"Generating embedding for query: {query[:50]}...")
        query_embedding = self.embed_query(retrieval_query)

        logger.info("Running dense and graph channels in parallel...")

        def run_dense():
            return self.dense_channel.retrieve(
                query_embedding=query_embedding,
                top_k=top_k * 2,  # Over-retrieve for merging
                date_start=date_start,
                date_end=date_end,
                scope=scope,
            )

        def run_graph():
            return self.graph_channel.retrieve(
                query=retrieval_query,
                query_embedding=query_embedding,
                date_start=date_start,
                date_end=date_end,
                scope=scope,
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            dense_future = executor.submit(run_dense)
            graph_future = executor.submit(run_graph)

            dense_results = dense_future.result()
            graph_results = graph_future.result()

        logger.info(f"Channels complete: dense={len(dense_results)}, graph={len(graph_results)}")

        logger.info("Merging channels...")
        merged_results = self.merger.merge(
            dense_results=dense_results,
            graph_results=graph_results,
            authority_scores=authority_scores,
            top_k=top_k
        )

        # Coverage fill: multi-view guarantee for parties below quota as well,
        # not only for absent ones. On niche topics small groups entered the
        # pool with 2-4 marginal chunks → quote picker came up empty even with
        # excellent material in the corpus (observed 2026-07-24 on
        # 'remigrazione': Misto with 2 evidences, Magi has 22 chunks on the topic).
        from collections import Counter
        min_per_party = self.config.retrieval.get("merger", {}).get("min_per_party", 5)
        # Deputies only: Government members belong in the GOVERNO section, not
        # in the party sections — technical ministers attached to MISTO
        # inflated the count and Misto appeared "at quota" with 4 usable
        # chunks (observed 2026-07-24).
        party_counts = Counter(
            r.get("party") for r in merged_results
            if r.get("party") and r.get("speaker_role") != "GovernmentMember"
        )
        all_parties = set(self.config.get_all_parties())
        under_represented = {
            p for p in all_parties if party_counts.get(p, 0) < min_per_party
        }

        fill_count = 0
        if under_represented:
            logger.info(
                f"Coverage fill: {len(under_represented)} parties under quota "
                f"({min_per_party}): {under_represented}"
            )
            fill_results = self._coverage_fill(
                query_embedding, under_represented, chunks_per_party=min_per_party,
                date_start=date_start, date_end=date_end, scope=scope,
            )
            if fill_results:
                existing_ids = {r.get("evidence_id") for r in merged_results}
                fill_results = [
                    r for r in fill_results
                    if r.get("evidence_id") not in existing_ids
                ]
                fill_count = len(fill_results)
                merged_results.extend(fill_results)
                logger.info(f"Coverage fill: added {fill_count} chunks for under-represented parties")

        # Expand to neighboring chunks when a more politically salient
        # adjacent chunk exists for the same speech
        merged_results = self._expand_neighbors(merged_results)

        evidence_list = self._to_evidence_records(merged_results)

        processing_time = (time.time() - start_time) * 1000
        party_coverage = self._compute_party_coverage(evidence_list)

        # Dense-channel similarities for the out-of-domain gate (issue #22):
        # same distribution used by build/calibrate_relevance_gate.py to
        # calibrate the thresholds, computed before merge and coverage fill.
        gate_cfg = self.config.retrieval.get("relevance_gate", {})
        gate_floor = gate_cfg.get("chunk_similarity_floor", 0.78)
        dense_sims = [r.get("similarity", 0.0) for r in dense_results]

        return {
            "evidence": evidence_list,
            "metadata": {
                "relevance": {
                    "max_similarity": max(dense_sims, default=0.0),
                    "chunks_above_floor": sum(1 for s in dense_sims if s >= gate_floor),
                    "floor": gate_floor,
                },
                "dense_channel_count": len(dense_results),
                "graph_channel_count": len(graph_results),
                "merged_count": len(merged_results),
                "party_coverage": party_coverage,
                "processing_time_ms": processing_time,
                # Query expanded by the rewriter: the generation stage (quote
                # picker) needs it to judge relevance on niche terms the
                # model may not know ("remigrazione").
                "rewritten_query": retrieval_query if retrieval_query != query else None,
            }
        }

    async def retrieve(
        self,
        query: str,
        top_k: int = 100,
        authority_scores: Optional[Dict[str, float]] = None,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        locale: str = "it",
        scope: Optional[Scope] = None,
    ) -> Dict[str, Any]:
        """
        Perform dual-channel retrieval (async).

        Runs retrieve_sync() in a thread-pool executor so the event loop
        is never blocked while embedding or querying the DB.

        Returns:
            Dictionary with evidence list and metadata
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self.retrieve_sync(
                query=query,
                top_k=top_k,
                authority_scores=authority_scores,
                date_start=date_start,
                date_end=date_end,
                locale=locale,
                scope=scope,
            ),
        )

    def _to_evidence_records(
        self,
        results: List[Dict[str, Any]]
    ) -> List[UnifiedEvidence]:
        """Convert raw results to UnifiedEvidence records."""
        evidence_list = []

        for r in results:
            try:
                evidence = UnifiedEvidence(
                    evidence_id=r.get("evidence_id", ""),
                    doc_id=r.get("doc_id", ""),
                    speech_id=r.get("speech_id", ""),
                    speaker_id=r.get("speaker_id", ""),
                    url=r.get("url"),
                    speaker_name=r.get("speaker_name", ""),
                    speaker_role=r.get("speaker_role", "Deputy"),
                    party=r.get("party", "MISTO"),
                    coalition=r.get("coalition", "opposizione"),
                    party_changed=r.get("party_changed", False),
                    current_party=r.get("current_party"),
                    date=r.get("date", date.today()),
                    chunk_text=r.get("chunk_text", ""),
                    quote_text=r.get("quote_text", ""),
                    text=r.get("text", ""),  # Full speech text for sentence expansion
                    span_start=r.get("span_start", 0),
                    span_end=r.get("span_end", 0),
                    debate_title=r.get("debate_title"),
                    session_number=r.get("session_number", 0),
                    similarity=r.get("similarity", 0.0),
                    authority_score=r.get("authority_score", 0.0),
                    salience=r.get("salience"),
                    citability_score=r.get("citability_score"),
                    citability_class=r.get("citability_class"),
                    best_quote=r.get("best_quote"),
                    misto_component=r.get("misto_component"),
                    embedding=r.get("embedding")  # For compass PCA
                )
                evidence_list.append(evidence)
            except Exception as e:
                logger.error(f"Error creating evidence record: {e}")
                continue

        return evidence_list

    # A chunk starting within this many characters of the speech start is
    # treated as introductory: Italian floor speeches typically open with
    # topic framing, and the position statement follows in the next chunk.
    _EARLY_SPEECH_SPAN_THRESHOLD = 600

    def _expand_neighbors(
        self,
        results: List[Dict[str, Any]],
        salience_threshold: float = 0.5
    ) -> List[Dict[str, Any]]:
        """Expand to neighboring chunks when they have higher political salience.

        Two complementary moves, both driven by the stored citability score:

        - Low-salience chunks are REPLACED by an adjacent chunk (prev or next
          via the NEXT relationship) when that neighbor is more citable.
        - Early-in-speech chunks (span_start below the class threshold) get
          their next chunk APPENDED when it is more citable: retrieved chunks
          often match on the introductory framing of a speech, while the
          actual position statement tends to live in the following chunk.
        """
        if not results:
            return results

        # Salience = stored index-time citability score (Phase 1);
        # chunks without a score are treated as neutral (0.5).
        for r in results:
            cit = r.get("citability_score")
            r["salience"] = float(cit) if cit is not None else 0.5

        low_salience = [r for r in results if r.get("salience", 0) < salience_threshold]
        early_speech = [
            r for r in results
            if r.get("span_start", 0) < self._EARLY_SPEECH_SPAN_THRESHOLD
            and r not in low_salience
        ]
        candidates = low_salience + early_speech

        if not candidates:
            return results

        chunk_ids = [r.get("evidence_id") for r in candidates if r.get("evidence_id")]
        if not chunk_ids:
            return results

        logger.info(
            f"Neighbor expansion: checking neighbors for {len(chunk_ids)} chunks "
            f"({len(low_salience)} low-salience, {len(early_speech)} early-speech)"
        )

        try:
            cypher = """
            UNWIND $chunk_ids AS cid
            MATCH (c:Chunk {id: cid})
            OPTIONAL MATCH (prev:Chunk)-[:NEXT]->(c)
            OPTIONAL MATCH (c)-[:NEXT]->(next:Chunk)
            MATCH (c)<-[:HAS_CHUNK]-(i:Speech)
            RETURN cid,
                   prev.id AS prev_id, prev.text AS prev_text,
                   prev.citability_score AS prev_citability,
                   prev.citability_class AS prev_citability_class,
                   prev.best_quote AS prev_best_quote,
                   prev.embedding AS prev_embedding,
                   next.id AS next_id, next.text AS next_text,
                   next.citability_score AS next_citability,
                   next.citability_class AS next_citability_class,
                   next.best_quote AS next_best_quote,
                   next.embedding AS next_embedding,
                   i.id AS speech_id,
                   i.text AS speech_text
            """
            neighbor_rows = fill_rows(
                self.client.query(cypher, {"chunk_ids": chunk_ids}),
                chunk_fields={
                    "prev_id": {"prev_text": "text", "prev_embedding": "embedding"},
                    "next_id": {"next_text": "text", "next_embedding": "embedding"},
                },
                speech_fields={"speech_id": "speech_text"},
            )
        except Exception as e:
            logger.error(f"Neighbor expansion query failed: {e}")
            return results

        neighbor_map = {}
        for row in neighbor_rows:
            neighbor_map[row["cid"]] = row

        existing_ids = {r.get("evidence_id") for r in results}

        early_speech_ids = {r.get("evidence_id") for r in early_speech}

        replaced = 0
        appended = 0
        for r in results:
            eid = r.get("evidence_id")
            if eid not in neighbor_map:
                continue

            is_low_salience = r.get("salience", 0) < salience_threshold
            is_early_speech = eid in early_speech_ids

            if not is_low_salience and not is_early_speech:
                continue

            row = neighbor_map[eid]
            current_salience = r.get("salience", 0)

            if is_low_salience:
                # Original logic: replace if a neighbor has higher salience
                best_replacement = None
                best_salience = current_salience

                if row.get("prev_text") and row.get("prev_id") not in existing_ids:
                    prev_salience = float(row.get("prev_citability") or 0.5)
                    if prev_salience > best_salience:
                        best_salience = prev_salience
                        best_replacement = ("prev", row)

                if row.get("next_text") and row.get("next_id") not in existing_ids:
                    next_salience = float(row.get("next_citability") or 0.5)
                    if next_salience > best_salience:
                        best_salience = next_salience
                        best_replacement = ("next", row)

                if best_replacement:
                    direction, nrow = best_replacement
                    prefix = "prev" if direction == "prev" else "next"
                    new_id = nrow.get(f"{prefix}_id")
                    new_text = nrow.get(f"{prefix}_text")
                    speech_text = nrow.get("speech_text", "")

                    # Schema v2: span computed via exact substring match
                    # (chunk.text ⊆ speech.text is a build-time invariant)
                    from ...models.evidence import compute_chunk_span, compute_quote_text
                    new_start, new_end = compute_chunk_span(speech_text, new_text)
                    if speech_text and new_start < new_end:
                        new_quote = compute_quote_text(speech_text, new_start, new_end)
                    else:
                        new_quote = new_text

                    r["evidence_id"] = new_id
                    r["chunk_text"] = new_text
                    r["quote_text"] = new_quote
                    r["span_start"] = new_start
                    r["span_end"] = new_end
                    r["salience"] = best_salience
                    # Keep chunk-level metadata consistent with the new text:
                    # a stale embedding/best_quote would poison the compass
                    # projection and the citation dedup downstream.
                    r["citability_score"] = nrow.get(f"{prefix}_citability")
                    r["citability_class"] = nrow.get(f"{prefix}_citability_class")
                    r["best_quote"] = nrow.get(f"{prefix}_best_quote")
                    r["embedding"] = nrow.get(f"{prefix}_embedding")
                    existing_ids.add(new_id)
                    replaced += 1

            elif is_early_speech:
                # Early-speech logic: APPEND the next chunk as additional evidence
                # rather than replacing, so the original chunk is still retrievable
                # (it may contain relevant keyword matches).
                # Only append if the next chunk has meaningfully higher salience.
                next_id = row.get("next_id")
                next_text = row.get("next_text")
                if not next_text or not next_id or next_id in existing_ids:
                    continue

                next_salience = float(row.get("next_citability") or 0.5)
                # Append only if next chunk is more opinionated than current
                if next_salience <= current_salience:
                    continue

                speech_text = row.get("speech_text", "")

                # Schema v2: span via exact substring match (see above)
                from ...models.evidence import compute_chunk_span, compute_quote_text
                next_start, next_end = compute_chunk_span(speech_text, next_text)
                if speech_text and next_start < next_end:
                    next_quote = compute_quote_text(speech_text, next_start, next_end)
                else:
                    next_quote = next_text

                # Clone the parent evidence record with the next chunk's data,
                # keeping speaker/party/date/authority metadata.
                neighbor_evidence = dict(r)
                neighbor_evidence["evidence_id"] = next_id
                neighbor_evidence["chunk_text"] = next_text
                neighbor_evidence["quote_text"] = next_quote
                neighbor_evidence["span_start"] = next_start or 0
                neighbor_evidence["span_end"] = next_end or 0
                neighbor_evidence["salience"] = next_salience
                # Chunk-level metadata must describe the appended chunk, not
                # the parent it was cloned from (compass and citation dedup
                # read these fields).
                neighbor_evidence["citability_score"] = row.get("next_citability")
                neighbor_evidence["citability_class"] = row.get("next_citability_class")
                neighbor_evidence["best_quote"] = row.get("next_best_quote")
                neighbor_evidence["embedding"] = row.get("next_embedding")
                neighbor_evidence["retrieval_channel"] = "neighbor_expansion"
                # Give a slight similarity boost to surface it near its parent
                neighbor_evidence["similarity"] = r.get("similarity", 0.0) * 0.95

                results.append(neighbor_evidence)
                existing_ids.add(next_id)
                appended += 1
                logger.info(
                    f"Early-speech expansion: appended next chunk {next_id} "
                    f"(parent={eid}, salience {current_salience:.2f}→{next_salience:.2f})"
                )

        logger.info(
            f"Neighbor expansion: replaced {replaced}/{len(low_salience)} low-salience chunks, "
            f"appended {appended}/{len(early_speech)} early-speech next chunks"
        )
        return results

    def _coverage_fill(
        self,
        query_embedding: List[float],
        missing_parties: set,
        chunks_per_party: int = 5,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
        scope: Optional[Scope] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fill coverage gaps by doing targeted vector search for missing parties.

        For each missing party, queries the vector index and filters results
        to only include speakers from that party. Date bounds, when present,
        are applied here too so the fill cannot reintroduce filtered-out
        sessions.
        """
        config = get_config()
        retrieval_config = config.retrieval.get("dense_channel", {})
        index_name = retrieval_config.get("index_name", "chunk_embedding_index")

        # s.date is a Neo4j Date: cast string bounds with date() (see channels).
        date_filter = ""
        date_params: Dict[str, Any] = {}
        if date_start:
            date_filter += " AND s.date >= date($date_start)"
            date_params["date_start"] = date_start
        if date_end:
            date_filter += " AND s.date <= date($date_end)"
            date_params["date_end"] = date_end
        scope = normalize_scope(scope)
        date_filter += " AND " + session_clause()
        archive = get_archive()
        archived = [p for p in scope if archive and archive.covers(p)]
        graph_scope = tuple(p for p in scope if p not in archived)
        indexes = vector_indexes(self.client, graph_scope, index_name) if graph_scope else []

        fill_results = []

        # Reverse of the display->DB map: DB names may carry suffixes that
        # the mechanical transformation cannot reconstruct (e.g. the rename
        # "ITALIA VIVA-CASA RIFORMISTA (IV-CR)" with the acronym at the end).
        from ...models.evidence import PARTY_DISPLAY_NAMES
        db_names_by_display: Dict[str, str] = {}
        for db_name, display in PARTY_DISPLAY_NAMES.items():
            db_names_by_display.setdefault(display, db_name)

        for party in missing_parties:
            try:
                # DB storage format: uppercase without spaces around hyphens.
                # Official map first, then the mechanical transformation as
                # fallback for unmapped names.
                normalized_party = db_names_by_display.get(
                    party,
                    party.upper().replace(" - ", "-").replace("- ", "-").replace(" -", "-"))

                body = f"""
                WHERE score >= 0.15
                MATCH (c)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(speaker)
                MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)<-[:HAS_DEBATE]-(s:Session)
                // Only current party members: membership must be active both
                // at speech date and today (for a closed legislature: on its
                // last day).
                MATCH (speaker)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
                WHERE toLower(g.name) = toLower($party_name)
                AND mg.start_date <= s.date
                AND (mg.end_date IS NULL OR mg.end_date >= s.date)
                AND (mg.end_date IS NULL OR mg.end_date >= date()
                     OR (mg.final_in_legislature AND mg.legislature = s.legislature)){date_filter}
                // Current party (used to compute party_changed in _process_results)
                OPTIONAL MATCH (speaker)-[mg_now:MEMBER_OF_GROUP]->(g_now:ParliamentaryGroup)
                WHERE mg_now.end_date IS NULL
                OPTIONAL MATCH (speaker)-[mcp:MEMBER_OF_COMPONENT]->(mcomp:MistoComponent)
                WHERE mcp.start_date <= s.date AND (mcp.end_date IS NULL OR mcp.end_date >= s.date)
                RETURN c.id AS chunk_id,
                       c.text AS chunk_text,
                       c.embedding AS embedding,
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
                LIMIT $limit
                """

                params = {
                    "top_k": 500,  # Search wider to find this party's chunks
                    "query_embedding": query_embedding,
                    "party_name": normalized_party,
                    "limit": chunks_per_party,
                    **date_params
                }
                results = []
                for index in indexes:
                    results.extend(self.client.query(VECTOR_HEAD + body, {
                        **params, "index_name": index, "scope": scope_param(graph_scope)}))
                for pair in archived:
                    hits = archive.search(query_embedding, pair, 500, 0.15, date_start, date_end)
                    results.extend(self.client.query(HITS_HEAD + body, {
                        **params, "hits": hits, "scope": scope_param((pair,))}))
                if len(indexes) + len(archived) > 1:
                    results = sorted(results, key=lambda r: r["similarity"], reverse=True)[:chunks_per_party]
                fill_rows(results, **RETRIEVAL_ROW)

                if results:
                    processed = self.dense_channel._process_results(results)
                    for r in processed:
                        r["retrieval_channel"] = "coverage_fill"
                    fill_results.extend(processed)
                    logger.info(f"Coverage fill: found {len(results)} chunks for {party}")
                else:
                    logger.warning(f"Coverage fill: no chunks found for {party}")

            except Exception as e:
                logger.error(f"Coverage fill error for {party}: {e}")

        return fill_results

    def _compute_party_coverage(
        self,
        evidence_list: List[UnifiedEvidence]
    ) -> Dict[str, int]:
        """Compute number of evidence pieces per party."""
        coverage: Dict[str, int] = {}
        for e in evidence_list:
            coverage[e.party] = coverage.get(e.party, 0) + 1
        return coverage
