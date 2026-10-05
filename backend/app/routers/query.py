"""
Main query endpoint for Multi-View RAG.

Supports both synchronous and SSE streaming responses.
"""
import json
import time
import logging
import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional, List, Dict, Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..services.neo4j_client import Neo4jClient
from ..services.authority.coalition_logic import CoalitionLogic
from ..services.deps import get_services
from ..services.translation import translate_citation_batch, translate_response_text, translate_compass_axes
from ..services.domain_check import check_domain
from ..services.relevance_gate import gate_payload, domain_notice
from ..services.response_cache import (
    build_cache_key,
    config_fingerprint,
    get_data_version,
    get_inflight_registry,
    get_response_cache,
    mirror_task,
    replay_into_task,
)
from ..services.retrieval.commission_matcher import get_commission_matcher
from ..services.task_store import get_task_store
from ..config import get_config

logger = logging.getLogger(__name__)

from ..log_context import new_query_id  # noqa: E402
router = APIRouter(prefix="/api", tags=["Query"])

# Pipeline concurrency limiter, shared across all requests in the same
# process. With WORKERS=1 (Dockerfile default) this enforces a single active
# pipeline across the entire server.
_MAX_CONCURRENT_PIPELINES = int(os.environ.get("MAX_CONCURRENT_PIPELINES", "1"))
_pipeline_semaphore: Optional[asyncio.Semaphore] = None


def _get_pipeline_semaphore() -> asyncio.Semaphore:
    global _pipeline_semaphore
    if _pipeline_semaphore is None:
        _pipeline_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PIPELINES)
    return _pipeline_semaphore


def _task_cancelled(task_id: Optional[str]) -> bool:
    """Check whether the client cancelled this task via DELETE /api/chat/task/{id}."""
    if not task_id:
        return False
    try:
        return get_task_store().is_cancelled(task_id)
    except Exception:
        return False


def _request_locale_from_headers(http_request: Optional[Request]) -> str:
    from ..services.translation import LANG_NAMES
    code = (
        http_request.headers.get("accept-language", "it") if http_request else "it"
    ).strip()[:2].lower()
    return code if code in LANG_NAMES else "it"


async def _stream_task_queue(task_id: str) -> "AsyncGenerator[str, None]":
    """Yield a task's queued events as SSE lines until the None sentinel."""
    store = get_task_store()
    queue = store.get_queue(task_id)
    if not queue:
        return
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=60.0)
        except asyncio.TimeoutError:
            yield ": keepalive\n\n"
            continue
        if event is None:
            break
        yield f"data: {json.dumps(event, default=str)}\n\n"


async def _rate_limited_query(
    request: "QueryRequest",
    http_request: Optional[Request] = None,
) -> "AsyncGenerator[str, None]":
    """Mirror pipeline events to the task store while streaming them to the client.

    With a client-provided task_id, every SSE event also lands in the task
    store so GET/DELETE /api/chat/task/{task_id} can replay or cancel the run.
    The direct stream has priority: any store failure is logged and skipped,
    never propagated.

    Response cache and in-flight dedup sit BEFORE the semaphore: a cache hit
    replays the stored events instantly (no pipeline, no queue slot, no
    waiting screen); an identical in-flight request follows the leader task
    instead of running a second pipeline.
    """
    cache = get_response_cache()
    inflight = get_inflight_registry()
    cache_key: Optional[str] = None
    my_task_id = request.task_id or get_task_store().generate_task_id()

    if cache.enabled:
        data_version = await get_data_version()
        if data_version:
            cache_key = build_cache_key(
                query=request.query,
                locale=_request_locale_from_headers(http_request),
                mode="standard",
                data_version=data_version,
                config_fingerprint=config_fingerprint(get_config().load_config()),
                extra={
                    "top_k": request.top_k,
                    "date_start": request.date_start,
                    "date_end": request.date_end,
                },
            )

            cached_events = await cache.lookup(cache_key)
            if cached_events is not None:
                store = get_task_store()
                await store.create_task(my_task_id)
                await replay_into_task(my_task_id, cached_events)
                async for line in _stream_task_queue(my_task_id):
                    yield line
                return

            leader_id = await inflight.claim(cache_key, my_task_id)
            if leader_id is not None:
                store = get_task_store()
                await store.create_task(my_task_id)
                asyncio.create_task(mirror_task(
                    my_task_id, leader_id,
                    locale=_request_locale_from_headers(http_request),
                ))
                async for line in _stream_task_queue(my_task_id):
                    yield line
                return

    store = None
    if request.task_id:
        try:
            store = get_task_store()
            await store.cleanup_expired()
            await store.create_task(request.task_id)
        except Exception as exc:
            logger.warning(f"[TaskStore] create_task failed for {request.task_id}: {exc}")
            store = None

    error_message: Optional[str] = None
    collected_events: list = []
    try:
        async for event in _semaphore_gated_query(request, http_request):
            if store or cache_key:
                try:
                    payload = json.loads(event.split("data: ", 1)[1])
                    if payload.get("type") == "error":
                        error_message = str(payload.get("message", "pipeline error"))
                    if cache_key:
                        collected_events.append(payload)
                    if store:
                        await store.add_event(request.task_id, payload)
                except Exception as exc:
                    logger.warning(f"[TaskStore] add_event failed for {request.task_id}: {exc}")
            yield event

        if store:
            try:
                # cancel_task already set the terminal status; do not overwrite it
                if not store.is_cancelled(request.task_id):
                    if error_message is not None:
                        await store.fail_task(request.task_id, error_message)
                    else:
                        await store.complete_task(request.task_id)
            except Exception as exc:
                logger.warning(f"[TaskStore] finalize failed for {request.task_id}: {exc}")

        # Store on clean completion only. Partial runs (client disconnect,
        # cancellation) carry no "complete" event and are refused by store().
        if (
            cache_key
            and error_message is None
            and not (store and store.is_cancelled(request.task_id))
        ):
            await cache.store(cache_key, collected_events)
    finally:
        if cache_key:
            await inflight.release(cache_key, my_task_id)


async def _semaphore_gated_query(
    request: "QueryRequest",
    http_request: Optional[Request] = None,
) -> "AsyncGenerator[str, None]":
    """Wrapper that acquires the pipeline semaphore before delegating to
    process_query_streaming, ensuring at most _MAX_CONCURRENT_PIPELINES
    pipelines run concurrently inside a single worker process."""
    from ..services import usage_guard

    locale = (http_request.headers.get("accept-language", "it") if http_request else "it").strip()[:2].lower()

    # Global kill-switch: OpenAI monthly quota exhausted — explain and stop
    if usage_guard.quota_exhausted():
        yield f"data: {json.dumps({'type': 'error', 'code': 'quota_exhausted', 'message': usage_guard.block_message('quota', locale)})}\n\n"
        return

    # Per-IP limits on the expensive pipeline — explain scope and retry time
    ip = usage_guard.client_ip(http_request)
    allowed, scope, retry_min = usage_guard.check_and_register(ip)
    if not allowed:
        yield f"data: {json.dumps({'type': 'error', 'code': 'rate_limited', 'message': usage_guard.block_message(scope, locale, retry_min)})}\n\n"
        return

    # Correlation id: every log line of this query (including those from
    # default-executor threads) carries the same qid
    qid = new_query_id()
    # No client IP here: a log line must never tie a question to who asked it
    logger.info(f'Query accettata (qid={qid}, locale={locale}): "{request.query[:150]}"')

    semaphore = _get_pipeline_semaphore()
    # Notify the client immediately if it will have to wait.
    if semaphore._value == 0:
        _accept = (http_request.headers.get("accept-language", "it") if http_request else "it").strip()[:2].lower()
        _wait_msg = ('Il sistema sta elaborando un altra richiesta. Attendi...' if _accept == 'it'
                     else 'The system is processing another request. Please wait...')
        yield (
            f"data: {json.dumps({'type': 'waiting', 'message': _wait_msg})}\n\n"
        )
    await semaphore.acquire()
    try:
        async for event in process_query_streaming(request, http_request):
            yield event
    finally:
        semaphore.release()


class QueryRequest(BaseModel):
    """Request model for query endpoint."""
    query: str = Field(..., min_length=3, max_length=1000, description="User query")
    top_k: int = Field(default=100, ge=10, le=500, description="Number of evidence pieces")
    date_start: Optional[str] = Field(default=None, description="Start date filter (YYYY-MM-DD)")
    date_end: Optional[str] = Field(default=None, description="End date filter (YYYY-MM-DD)")
    stream: bool = Field(default=True, description="Enable SSE streaming")
    task_id: Optional[str] = Field(default=None, description="Client-provided task ID for cancellation/reconnection")


class CitationInfo(BaseModel):
    """Citation information."""
    citation_id: str
    chunk_id: str
    quote_text: str
    speaker_name: str
    party: str
    date: str
    span_start: int
    span_end: int


class QueryResponse(BaseModel):
    """Response model for non-streaming queries.

    `experts` uses the same per-party dict shape emitted by the streaming
    `experts` SSE event (see _compute_experts), so both paths stay consistent.
    """
    text: str
    citations: List[CitationInfo]
    experts: List[Dict[str, Any]]
    compass: Optional[Dict[str, Any]]
    metadata: Dict[str, Any]



async def process_query_streaming(
    request: QueryRequest,
    http_request: Optional[Request] = None,
) -> AsyncGenerator[str, None]:
    """
    Process query with SSE streaming.

    Yields SSE events as the pipeline progresses.
    """
    request_locale = "it"
    if http_request:
        accept_lang = http_request.headers.get("accept-language", "it")
        from ..services.translation import LANG_NAMES
        code = accept_lang.strip()[:2].lower()
        request_locale = code if code in LANG_NAMES else "it"

    services = get_services()
    pipeline_t0 = time.perf_counter()
    from ..llm_recorder import start_recording, set_llm_stage
    llm_recorder = start_recording()

    # English progress/messages for every non-Italian locale (fr/de/es/pt included)
    _en = request_locale != "it"

    try:
        # Domain check (issue #22): runs while retrieval works. Never blocks
        # on its own; the result gets awaited only where it changes the output.
        domain_task = asyncio.create_task(check_domain(request.query, request_locale))

        # Step 1: Progress - Starting
        yield f"data: {json.dumps({'type': 'progress', 'step': 1, 'message': 'Query analysis and retrieval...' if _en else 'Avvio retrieval...'})}\n\n"

        # Commission surfacing (issue #26): keyword match over an in-memory
        # mapping, no I/O per call, so it runs inline before retrieval.
        # Display only — the retrieval boost is decided elsewhere.
        _commissions_t0 = time.perf_counter()
        commissions_at = round((_commissions_t0 - pipeline_t0) * 1000, 1)
        relevant_commissions: List[Dict[str, Any]] = []
        try:
            relevant_commissions = get_commission_matcher().find_relevant_commissions(
                query=request.query, top_k=3, min_score=0.1
            )
            yield f"data: {json.dumps({'type': 'commissioni', 'commissioni': relevant_commissions}, default=str)}\n\n"
        except Exception as exc:
            logger.error(f"[COMMISSIONS] Matching failed (pipeline continues): {exc}", exc_info=True)
        commissions_ms = (time.perf_counter() - _commissions_t0) * 1000

        # Step 2: retrieval (locale: non-Italian queries are translated by
        # the rewriter before embedding, the corpus is Italian)
        retrieval_result = await services["retrieval"].retrieve(
            query=request.query,
            top_k=request.top_k,
            date_start=request.date_start,
            date_end=request.date_end,
            locale=request_locale
        )

        evidence_list = retrieval_result["evidence"]
        # Include fields excluded from JSON responses (exclude=True) for internal pipeline use.
        # embedding: compass PCA; text: CitationSurgeon sentence-boundary expansion
        evidence_dicts = []
        for e in evidence_list:
            d = e.model_dump()
            if e.embedding is not None:
                d["embedding"] = e.embedding
            if e.text:
                d["text"] = e.text
            evidence_dicts.append(d)

        _ev_msg = (f'Found {len(evidence_list)} evidence pieces' if _en
                   else f'Trovate {len(evidence_list)} evidenze')
        yield f"data: {json.dumps({'type': 'progress', 'step': 2, 'message': _ev_msg})}\n\n"

        # Out-of-domain gate (issue #22): blocks only when both signals agree,
        # few dense evidences above threshold and domain check out of domain.
        # Thin evidence alone is not enough: legitimate niche topics (e.g.
        # recent acts with few floor debates) proceed and the writer handles
        # per-group scarcity. False positive observed 2026-08-22: "Cinema and
        # audiovisual regulation" from the welcome chips. Thresholds:
        # build/calibrate_relevance_gate.py.
        gate_cfg = services["retrieval"].config.retrieval.get("relevance_gate", {})
        relevance = retrieval_result["metadata"].get("relevance", {})
        if (gate_cfg.get("enabled", True)
                and relevance.get("chunks_above_floor", 0)
                < gate_cfg.get("min_chunks_above_floor", 10)):
            domain = await domain_task
            if domain.get("in_domain", True):
                logger.info(
                    f"[RELEVANCE_GATE] Thin evidence but in-domain, proceeding: "
                    f"{request.query!r} {relevance}")
            else:
                logger.info(f"[RELEVANCE_GATE] Blocked {request.query!r}: {relevance}")
                payload = gate_payload(
                    request.query, domain.get("suggestions", []), request_locale)
                yield f"data: {json.dumps({'type': 'gate', 'data': payload}, default=str)}\n\n"
                _meta = {**retrieval_result["metadata"], "relevance_gate": "blocked"}
                yield f"data: {json.dumps({'type': 'complete', 'metadata': _meta}, default=str)}\n\n"
                return

        # Step 3: Authority scoring
        yield f"data: {json.dumps({'type': 'progress', 'step': 3, 'message': 'Computing authority scores...' if _en else 'Calcolo authority scores...'})}\n\n"

        _authority_t0 = time.perf_counter()
        speaker_ids = list(set(e.speaker_id for e in evidence_list if e.speaker_id))
        query_embedding = await asyncio.get_running_loop().run_in_executor(
            None, lambda: services["retrieval"].embed_query(request.query)
        )

        # Batch authority: 2 DB queries for all speakers + parallel CPU scoring
        authority_all = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: services["authority"].compute_all_authority(speaker_ids, query_embedding),
        )
        authority_ms = (time.perf_counter() - _authority_t0) * 1000
        authority_scores = {sid: r["total_score"] for sid, r in authority_all.items()}
        authority_details = authority_all

        # Inject authority scores into evidence dicts so generation can sort by authority
        for ed in evidence_dicts:
            sid = ed.get("speaker_id", "")
            ed["authority_score"] = authority_scores.get(sid, 0.0)

        experts = await _compute_experts(
            evidence_list, authority_scores, authority_details, services["neo4j"]
        )

        yield f"data: {json.dumps({'type': 'experts', 'data': experts}, default=str)}\n\n"

        if (http_request and await http_request.is_disconnected()) or _task_cancelled(request.task_id):
            logger.info("[QUERY] Client disconnected or task cancelled before compass – aborting")
            domain_task.cancel()
            return

        # Step 4: compass analysis (2D text-based positioning)
        # Generation does not consume the compass output: it starts here in a
        # thread and is awaited only downstream of generation. Wall clock =
        # max(compass, generation) instead of their sum (~15-25s saved).
        yield f"data: {json.dumps({'type': 'progress', 'step': 4, 'message': 'Ideological compass analysis...' if _en else 'Analisi compass ideologico...'})}\n\n"

        compass_ms = None
        compass_at = round((time.perf_counter() - pipeline_t0) * 1000, 1)
        compass_groups = 0
        compass_method = None
        compass_meta_info = None

        def _run_compass():
            set_llm_stage("compass")
            _t0 = time.perf_counter()
            result = services["ideology"].compute_2d_text_positions(
                evidence_dicts, query=request.query)
            return result, (time.perf_counter() - _t0) * 1000

        compass_future = asyncio.get_running_loop().run_in_executor(None, _run_compass)
        # If the generator exits early (client gone), the compass thread keeps
        # running to completion: retrieve its result/exception so it never
        # surfaces as an "exception was never retrieved" warning.
        compass_future.add_done_callback(
            lambda f: f.cancelled() or f.exception()
        )

        if (http_request and await http_request.is_disconnected()) or _task_cancelled(request.task_id):
            logger.info("[QUERY] Client disconnected or task cancelled before generation – aborting")
            domain_task.cancel()
            return

        # Step 5: Generation
        yield f"data: {json.dumps({'type': 'progress', 'step': 5, 'message': 'Generating multi-view answer...' if _en else 'Generazione risposta multi-view...'})}\n\n"

        _generation_t0 = time.perf_counter()
        set_llm_stage("generation")
        generation_result = await services["generation"].generate(
            query=request.query,
            evidence_list=evidence_dicts,
            query_context=retrieval_result.get("metadata", {}).get("rewritten_query"),
        )
        set_llm_stage(None)
        generation_ms = (time.perf_counter() - _generation_t0) * 1000
        logger.info(f"[QUERY] Generation done. citations={len(generation_result.get('citations', []))}, "
                     f"extra_citation_ids={len(generation_result.get('extra_citation_ids', []))}")

        # Compass: it ran in parallel with generation, so by this point it is
        # (almost always) already done — the residual wait is ~0
        try:
            compass_result, compass_ms = await compass_future
            compass_data = {
                "meta": compass_result.get("meta", {}),
                "axes": compass_result.get("axes", {}),
                "groups": compass_result.get("groups", []),
                "scatter_sample": compass_result.get("scatter_sample", []),
            }
            compass_groups = len(compass_data.get("groups", []))
            compass_method = compass_data.get("meta", {}).get("axis_method")
            compass_meta_info = {
                "method": compass_method,
                "variance": compass_data.get("meta", {}).get("total_variance_explained"),
                "stable": compass_data.get("meta", {}).get("is_stable"),
            }
            logger.info(
                f"[COMPASS] groups={compass_groups}, "
                f"variance={compass_data.get('meta', {}).get('explained_variance_ratio')}, "
                f"dimensionality={compass_data.get('meta', {}).get('dimensionality')}, "
                f"is_stable={compass_data.get('meta', {}).get('is_stable')}"
            )
            if request_locale != "it":
                compass_data = await translate_compass_axes(compass_data, target_lang=request_locale)
            yield f"data: {json.dumps({'type': 'compass', 'data': compass_data}, default=str)}\n\n"
        except Exception as _compass_err:
            logger.error(f"[COMPASS] Failed (pipeline continues): {_compass_err}", exc_info=True)

        # Send topic statistics for the frontend's clickable intro stats
        topic_stats = generation_result.get("topic_statistics")
        if topic_stats:
            # Enrich speakers_detail with profile URL, profession, education, committee from Neo4j
            speakers_detail = topic_stats.get("speakers_detail", [])
            interventions_detail = topic_stats.get("interventions_detail", [])
            speaker_ids_for_enrichment = list(set(
                [s["speaker_id"] for s in speakers_detail if s.get("speaker_id")]
                + [i["speaker_id"] for i in interventions_detail if i.get("speaker_id")]
            ))
            if speaker_ids_for_enrichment:
                enrichment_data = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _batch_fetch_speaker_enrichment(services["neo4j"], speaker_ids_for_enrichment)
                )
                for speaker in speakers_detail:
                    sid = speaker.get("speaker_id", "")
                    if sid in enrichment_data:
                        info = enrichment_data[sid]
                        speaker["camera_profile_url"] = info.get("camera_profile_url")
                        # The photo was already extracted by the fetch but never
                        # applied: the stats modal showed initials (2026-07-24)
                        speaker["photo"] = info.get("photo")
                        speaker["profession"] = info.get("profession")
                        speaker["education"] = info.get("education")
                        speaker["committee"] = info.get("committee")
                        if info.get("institutional_role"):
                            speaker["institutional_role"] = info["institutional_role"]
                for intervention in interventions_detail:
                    sid = intervention.get("speaker_id", "")
                    if sid in enrichment_data:
                        intervention["photo"] = enrichment_data[sid].get("photo")

            ts_payload = {
                "intervention_count": topic_stats.get("intervention_count", 0),
                "speaker_count": topic_stats.get("speaker_count", 0),
                "first_date": (
                    topic_stats["first_date"].strftime("%Y-%m-%d")
                    if hasattr(topic_stats.get("first_date"), "strftime")
                    else str(topic_stats.get("first_date", ""))
                ),
                "last_date": (
                    topic_stats["last_date"].strftime("%Y-%m-%d")
                    if hasattr(topic_stats.get("last_date"), "strftime")
                    else str(topic_stats.get("last_date", ""))
                ),
                "speakers_detail": speakers_detail,
                "interventions_detail": interventions_detail,
                "sessions_detail": topic_stats.get("sessions_detail", []),
            }
            yield f"data: {json.dumps({'type': 'topic_stats', **ts_payload}, default=str)}\n\n"
            logger.info(
                f"[TOPIC_STATS] Sent: {ts_payload['intervention_count']} interventions, "
                f"{ts_payload['speaker_count']} speakers, "
                f"{len(ts_payload['sessions_detail'])} sessions"
            )

        # Step 6: Initial citations (first 20 from retrieval, sent early for UI)
        citations_data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _build_citations_for_frontend(evidence_dicts, neo4j_client=services["neo4j"])
        )
        logger.debug(f"[QUERY] Initial citations: {len(citations_data)} (from evidence_dicts[:20])")
        yield f"data: {json.dumps({'type': 'citations', 'data': citations_data}, default=str)}\n\n"

        # Resolve extra citation IDs via DB lookup
        import re as _re
        final_text = generation_result.get("text", "")
        extra_citation_ids = generation_result.get("extra_citation_ids", [])
        extra_evidence_map: Dict[str, Dict[str, Any]] = {}

        if extra_citation_ids:
            logger.info(f"[QUERY:CITATIONS] Resolving {len(extra_citation_ids)} extra IDs from DB: {extra_citation_ids[:5]}")
            try:
                db_rows = await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: services["neo4j"].query(
                        """
                        UNWIND $chunk_ids AS cid
                        MATCH (c:Chunk {id: cid})<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(speaker)
                        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)<-[:HAS_DEBATE]-(s:Session)
                        OPTIONAL MATCH (speaker)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
                          WHERE mg.start_date <= s.date
                            AND (mg.end_date IS NULL OR mg.end_date >= s.date)
                        RETURN c.id AS chunk_id,
                               c.text AS chunk_text,
                               i.id AS speech_id,
                               i.text AS text,
                               speaker.id AS speaker_id,
                               speaker.first_name AS speaker_first_name,
                               speaker.last_name AS speaker_last_name,
                               CASE WHEN 'GovernmentMember' IN labels(speaker)
                                    THEN 'GovernmentMember' ELSE 'Deputy' END AS speaker_type,
                               g.name AS party,
                               s.id AS session_id,
                               s.date AS session_date,
                               coalesce(d.parent_debate_title, d.title) AS debate_title
                        """,
                        {"chunk_ids": extra_citation_ids}
                    )
                )
                from ..models.evidence import (
                    normalize_speaker_name, normalize_party_name, compute_chunk_span,
                )
                config = get_config()
                for row in db_rows:
                    eid = row.get("chunk_id", "")
                    party = normalize_party_name(row.get("party") or "MISTO")
                    session_date = row.get("session_date")
                    if session_date is not None and hasattr(session_date, 'to_native'):
                        date_obj = session_date.to_native()
                    elif isinstance(session_date, str) and session_date:
                        from datetime import datetime as _dt
                        try:
                            date_obj = _dt.strptime(session_date, "%d/%m/%Y").date()
                        except ValueError:
                            date_obj = _dt.now().date()
                    else:
                        date_obj = date.today()

                    speaker_role = row.get("speaker_type", "Deputy")
                    if speaker_role == "GovernmentMember":
                        coalition = "governo"
                    else:
                        coalition = config.get_coalition(party)

                    span_start, span_end = compute_chunk_span(
                        row.get("text", "") or "",
                        row.get("chunk_text", "") or "",
                    )
                    extra_evidence_map[eid] = {
                        "evidence_id": eid,
                        "chunk_text": row.get("chunk_text", ""),
                        "quote_text": row.get("chunk_text", ""),
                        "speech_id": row.get("speech_id", ""),
                        "speaker_id": row.get("speaker_id", ""),
                        "speaker_name": normalize_speaker_name(
                            row.get("speaker_first_name", ""),
                            row.get("speaker_last_name", "")
                        ),
                        "speaker_role": speaker_role,
                        "party": party,
                        "coalition": coalition,
                        "date": date_obj,
                        "span_start": span_start,
                        "span_end": span_end,
                        "debate_title": row.get("debate_title", ""),
                        "session_id": row.get("session_id", ""),
                    }
                found_ids = set(extra_evidence_map.keys())
                missing_ids = set(extra_citation_ids) - found_ids
                logger.info(f"[QUERY:CITATIONS] DB lookup done: {len(found_ids)} found, {len(missing_ids)} not in DB")
                if missing_ids:
                    logger.warning(f"[QUERY:CITATIONS] IDs not in DB (will strip): {list(missing_ids)[:5]}")

                # Strip links for IDs that truly don't exist in DB
                if missing_ids:
                    def _strip_missing(match):
                        href = match.group(2)
                        if href in missing_ids:
                            logger.warning(f"[QUERY:CITATIONS] Stripping non-existent ID: {href}")
                            return match.group(1)
                        return match.group(0)
                    final_text = _re.sub(
                        r'\[([^\]]+)\]\((leg1[89]_[^)]+)\)',
                        _strip_missing,
                        final_text
                    )
            except Exception as e:
                logger.error(f"[QUERY:CITATIONS] DB lookup failed: {e}", exc_info=True)
                extra_ids_set = set(extra_citation_ids)
                def _strip_extra(match):
                    if match.group(2) in extra_ids_set:
                        return match.group(1)
                    return match.group(0)
                final_text = _re.sub(
                    r'\[([^\]]+)\]\((leg1[89]_[^)]+)\)',
                    _strip_extra,
                    final_text
                )
        else:
            logger.debug("[QUERY:CITATIONS] No extra citation IDs to resolve")

        # Build complete citation_details
        text_evidence_ids = set(_re.findall(r'\]\((leg1[89]_[^)]+)\)', final_text))
        evidence_map_for_cit = {e.get("evidence_id"): e for e in evidence_dicts}
        evidence_map_for_cit.update(extra_evidence_map)
        logger.debug(f"[QUERY:CITATIONS] text_links={len(text_evidence_ids)}, evidence_map={len(evidence_map_for_cit)} (original={len(evidence_dicts)}, extra={len(extra_evidence_map)})")

        gen_citations = generation_result.get("citations", [])
        tracked_ids = {c.get("evidence_id") for c in gen_citations}

        for eid in text_evidence_ids:
            if eid not in tracked_ids and eid in evidence_map_for_cit:
                ev = evidence_map_for_cit[eid]
                gen_citations.append({
                    "evidence_id": eid,
                    "quote_text": ev.get("quote_text", "") or ev.get("chunk_text", ""),
                    "speaker_name": ev.get("speaker_name", ""),
                    "party": ev.get("party", ""),
                    "date": str(ev.get("date", "")),
                    "span_start": ev.get("span_start", 0),
                    "span_end": ev.get("span_end", 0),
                })
                tracked_ids.add(eid)
                logger.info(f"[QUERY:CITATIONS] Recovered from text: {eid}")
            elif eid not in tracked_ids:
                logger.warning(f"[QUERY:CITATIONS] ID in text but NOT in any map: {eid}")

        # Send citation_details to update the sidebar with all cited chunks
        all_evidence_for_verify = evidence_dicts + list(extra_evidence_map.values())
        _verify_t0 = time.perf_counter()
        verified_citations = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _build_verified_citations(gen_citations, all_evidence_for_verify, neo4j_client=services["neo4j"])
        )
        verify_ms = (time.perf_counter() - _verify_t0) * 1000
        logger.info(f"[QUERY:CITATIONS] {len(verified_citations)} citations built (text_links={len(text_evidence_ids)}, tracked={len(gen_citations)}, map={len(evidence_map_for_cit)})")
        if request_locale != "it":
            logger.info("[QUERY:TRANSLATE] Translating %d citations (locale=%s)", len(verified_citations), request_locale)
            verified_citations = await translate_citation_batch(verified_citations, target_lang=request_locale)
        yield f"data: {json.dumps({'type': 'citation_details', 'citations': verified_citations}, default=str)}\n\n"

        # Update experts: filter to cited parties and prefer cited speakers.
        # The initial experts event (sent before generation) included the top-authority
        # speaker per party from the retrieved pool.  After generation we know which
        # parties were actually cited, and which specific speaker was cited per party.
        # We replace the initial experts with a citation-aligned list:
        #   - Only parties that have at least one citation are shown (fixes "Misto with
        #     no citations still showing Della Vedova"-type confusion).
        #   - For each cited party we prefer the highest-authority CITED speaker.
        #     If the pre-selected expert was cited, we keep them; otherwise we build
        #     a fresh expert entry for the cited speaker (fixes "Italia Viva cites Del
        #     Barba but shows Giachetti" confusion).
        if gen_citations:
            # party → speaker_id with highest authority among cited speakers
            cited_party_best: Dict[str, str] = {}
            for cit in gen_citations:
                eid = cit.get("evidence_id", "")
                ev = evidence_map_for_cit.get(eid, {})
                speaker_id = ev.get("speaker_id", "") or cit.get("speaker_id", "")
                party = (cit.get("party") or ev.get("party", "")).strip()
                speaker_role = ev.get("speaker_role", "Deputy")
                if not speaker_id or not party or speaker_role == "GovernmentMember":
                    continue
                score = authority_scores.get(speaker_id, 0)
                cur = cited_party_best.get(party)
                if cur is None or score > authority_scores.get(cur, 0):
                    cited_party_best[party] = speaker_id

            if cited_party_best:
                expert_by_group = {e["group"]: e for e in experts}
                final_experts: List[Dict[str, Any]] = []
                speakers_to_fetch: List[tuple] = []  # (party, speaker_id)

                for party, best_sid in cited_party_best.items():
                    existing = expert_by_group.get(party)
                    if existing and existing["id"] == best_sid:
                        final_experts.append(existing)
                    else:
                        speakers_to_fetch.append((party, best_sid))

                if speakers_to_fetch:
                    loop = asyncio.get_running_loop()
                    with ThreadPoolExecutor(max_workers=min(10, len(speakers_to_fetch))) as pool:
                        fetch_futs = [
                            loop.run_in_executor(pool, _fetch_speaker_details, services["neo4j"], sid)
                            for _, sid in speakers_to_fetch
                        ]
                        fetched_sp = await asyncio.gather(*fetch_futs)

                    coalition_logic_obj = CoalitionLogic()
                    for (party, sid), sp_info in zip(speakers_to_fetch, fetched_sp):
                        details = authority_details.get(sid, {})
                        components = details.get("components", {})
                        score = authority_scores.get(sid, 0)
                        first_name = sp_info.get("first_name") or ""
                        last_name = sp_info.get("last_name") or ""
                        if not first_name and not last_name:
                            for cit in gen_citations:
                                eid = cit.get("evidence_id", "")
                                ev = evidence_map_for_cit.get(eid, {})
                                if ev.get("speaker_id") == sid:
                                    parts = (cit.get("speaker_name") or ev.get("speaker_name", "")).split(" ", 1)
                                    first_name = parts[0] if parts else ""
                                    last_name = parts[1] if len(parts) > 1 else ""
                                    break
                        final_experts.append({
                            "id": sid,
                            "first_name": first_name,
                            "last_name": last_name,
                            "group": party,
                            "coalition": coalition_logic_obj.get_coalition(party),
                            "authority_score": round(score, 2),
                            "relevant_speeches_count": sum(
                                1 for ev in all_evidence_for_verify
                                if ev.get("speaker_id") == sid
                            ),
                            "camera_profile_url": sp_info.get("camera_profile_url"),
                            "photo": sp_info.get("photo"),
                            "profession": sp_info.get("profession"),
                            "education": sp_info.get("education"),
                            "committee": sp_info.get("current_committee"),
                            "institutional_role": details.get("institutional_role") or sp_info.get("institutional_role"),
                            "score_breakdown": {
                                "speeches": round(components.get("interventions", 0), 2),
                                "acts": round(components.get("acts", 0), 2),
                                "committee": round(components.get("committee", 0), 2),
                                "profession": round(components.get("profession", 0), 2),
                                "education": round(components.get("education", 0), 2),
                                "role": round(components.get("role", 0), 2),
                            },
                        })

                final_experts.sort(key=lambda e: e["authority_score"], reverse=True)
                experts = final_experts
                logger.info(f"[QUERY:EXPERTS] Updated experts after generation: {len(experts)} (from {len(cited_party_best)} cited parties)")
                yield f"data: {json.dumps({'type': 'experts', 'data': final_experts}, default=str)}\n\n"

        if request_locale != "it":
            final_text = await translate_response_text(final_text, target_lang=request_locale)

        # Non-blocking domain notice (issue #22): the evidence gate passed
        # but the LLM check flags the query as out of scope. Prepended after
        # translation because the notice is already localized.
        domain = await domain_task
        if not domain.get("in_domain", True):
            final_text = domain_notice(
                domain.get("suggestions", []), request_locale) + final_text

        # Step 7: Stream text chunks
        chunk_size = 100
        for i in range(0, len(final_text), chunk_size):
            if (http_request and await http_request.is_disconnected()) or _task_cancelled(request.task_id):
                logger.info("[QUERY] Client disconnected or task cancelled during text streaming – aborting")
                return
            chunk = final_text[i:i+chunk_size]
            yield f"data: {json.dumps({'type': 'chunk', 'data': chunk})}\n\n"
            await asyncio.sleep(0.02)  # Small delay for streaming effect

        # Trace: behind the scenes of the pipeline.
        # Durations and counters only: no prompts, no evidence texts.
        _r_meta = retrieval_result.get("metadata", {})
        _gen_stage_meta = generation_result.get("metadata", {}).get("stages", {})

        def _gen_child(key: str, info: Dict[str, Any]) -> Dict[str, Any]:
            s = _gen_stage_meta.get(key, {})
            child: Dict[str, Any] = {"key": key, "ms": s.get("duration_ms"), "info": info}
            if s.get("model"):
                child["model"] = s["model"]
            return child

        trace = {
            "total_ms": round((time.perf_counter() - pipeline_t0) * 1000),
            "rewritten_query": _r_meta.get("rewritten_query"),
            "stages": [
                {"key": "commissions", "ms": round(commissions_ms, 1), "at": commissions_at,
                 "info": {"matched": len(relevant_commissions)}},
                {"key": "retrieval", "ms": round(_r_meta.get("processing_time_ms") or 0, 1), "at": 0,
                 "info": {"dense": _r_meta.get("dense_channel_count", 0),
                          "graph": _r_meta.get("graph_channel_count", 0),
                          "selected": len(evidence_dicts)}},
                {"key": "authority", "ms": round(authority_ms, 1),
                 "at": round((_authority_t0 - pipeline_t0) * 1000, 1),
                 "info": {"speakers": len(speaker_ids), "experts": len(experts)}},
                {"key": "compass", "ms": round(compass_ms, 1) if compass_ms is not None else None,
                 "at": round(compass_at, 1) if compass_at is not None else None,
                 "info": {"groups": compass_groups, "method": compass_method}},
                {"key": "generation", "ms": round(generation_ms, 1),
                 "at": round((_generation_t0 - pipeline_t0) * 1000, 1),
                 "info": {"chars": len(final_text)},
                 "children": [
                     _gen_child("analyst", {
                         "claims": _gen_stage_meta.get("analyst", {}).get("claims_count")}),
                     _gen_child("sectional", {
                         "sections": _gen_stage_meta.get("sectional", {}).get("sections_count"),
                         "citations_bound": _gen_stage_meta.get("sectional", {}).get("citations_bound")}),
                     _gen_child("integrator", {
                         "citations_repaired": _gen_stage_meta.get("integrator", {}).get("citations_repaired")}),
                     _gen_child("surgeon", {
                         "citations_inserted": _gen_stage_meta.get("surgeon", {}).get("citations_inserted"),
                         "citations_failed": _gen_stage_meta.get("surgeon", {}).get("citations_failed")}),
                 ]},
                {"key": "verification", "ms": round(verify_ms, 1),
                 "at": round((_verify_t0 - pipeline_t0) * 1000, 1),
                 "info": {"citations_verified": len(verified_citations)}},
            ],
        }

        # Recorded LLM calls (model, duration, tokens, estimated cost,
        # I/O previews)
        trace["llm"] = llm_recorder.totals()
        trace["llm_calls"] = llm_recorder.sorted_calls()

        # Sample of the retrieval pool in merge order: the score components
        # that drive multi-view selection, evidence by evidence
        trace["retrieval_sample"] = [
            {
                "id": d.get("evidence_id"),
                "speaker": d.get("speaker_name"),
                "party": d.get("party"),
                "coalition": d.get("coalition"),
                "similarity": round(d.get("similarity") or 0, 3),
                "authority": round(d.get("authority_score") or 0, 3),
                "citability": round(d["citability_score"], 3) if d.get("citability_score") is not None else None,
                "date": str(d.get("date") or ""),
            }
            for d in evidence_dicts[:30]
        ]
        trace["party_coverage"] = _r_meta.get("party_coverage")
        trace["compass_meta"] = compass_meta_info
        trace["domain"] = {"in_domain": domain.get("in_domain", True)}

        # Citation ledger: the state of each citation through the pipeline
        # (bound → in_text → resolved/failed), semantic coherence and
        # discard reasons. It is the "why" behind every [«quote»].
        _integrity = generation_result.get("metadata", {}).get("citation_integrity", {})
        _final_rep = _integrity.get("final", {})
        _ledger = []
        for status_name, entries in (_final_rep.get("by_status") or {}).items():
            # "registered" = evidence retrieved but never a citation candidate:
            # nearly the whole retrieval pool, just noise in the ledger
            if status_name == "registered":
                continue
            for e in entries:
                _ledger.append({
                    "evidence_id": e.get("evidence_id"),
                    "status": status_name,
                    "speaker": e.get("speaker"),
                    "party": e.get("party"),
                    "section_party": e.get("section_party"),
                    "coherence_score": round(e["coherence_score"], 3) if e.get("coherence_score") is not None else None,
                    "error": (str(e["error"])[:200] if e.get("error") else None),
                })
        trace["citations_report"] = {
            "expected": _final_rep.get("total_expected"),
            "resolved": _final_rep.get("resolved"),
            "failed": _final_rep.get("failed"),
            "orphaned": _final_rep.get("orphaned"),
            "success_rate": round(_final_rep["success_rate"], 3) if _final_rep.get("success_rate") is not None else None,
            "coherence": _integrity.get("coherence"),
            "unsupported_claims": [
                str(c)[:200] for c in (_integrity.get("unsupported_claims") or [])[:10]
            ],
            "ledger": _ledger,
        }

        yield f"data: {json.dumps({'type': 'trace', 'trace': trace}, default=str)}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'metadata': retrieval_result['metadata']}, default=str)}\n\n"

    except Exception as e:
        logger.error(f"Query processing error: {e}")
        from ..services import usage_guard
        if usage_guard.looks_like_quota_error(e):
            # OpenAI budget exhausted: trip the kill-switch so subsequent
            # queries get the clear explanation without hitting the API.
            usage_guard.mark_quota_exhausted()
            _loc = (http_request.headers.get("accept-language", "it") if http_request else "it").strip()[:2].lower()
            yield f"data: {json.dumps({'type': 'error', 'code': 'quota_exhausted', 'message': usage_guard.block_message('quota', _loc)})}\n\n"
        else:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"


def _fetch_speaker_details(neo4j_client: Neo4jClient, speaker_id: str) -> Dict[str, Any]:
    """Fetch detailed speaker information from Neo4j."""
    cypher = """
    MATCH (d:Deputy {id: $speaker_id})
    OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
    WHERE mc.end_date IS NULL OR mc.end_date >= date()
    WITH d, collect(c.name)[0] AS current_committee

    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rp:IS_PRESIDENT]->(cp:Committee)
        WITH d, collect(DISTINCT CASE WHEN cp IS NULL THEN NULL ELSE {role: 'Presidente ' + cp.name, active: rp.end_date IS NULL OR rp.end_date >= date()} END) AS v1_president_roles
        // schema v2: role as a property on MEMBER_OF_COMMITTEE
        OPTIONAL MATCH (d)-[rpm:MEMBER_OF_COMMITTEE]->(cpm:Committee)
        WHERE rpm.role = 'president'
        WITH v1_president_roles, collect(DISTINCT CASE WHEN cpm IS NULL THEN NULL ELSE {role: 'Presidente ' + cpm.name, active: rpm.end_date IS NULL OR rpm.end_date >= date()} END) AS v2_president_roles
        RETURN v1_president_roles + v2_president_roles AS president_roles
    }
    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rv:IS_VICE_PRESIDENT]->(cv:Committee)
        WITH d, collect(DISTINCT CASE WHEN cv IS NULL THEN NULL ELSE {role: 'Vicepresidente ' + cv.name, active: rv.end_date IS NULL OR rv.end_date >= date()} END) AS v1_vice_roles
        // schema v2: role as a property on MEMBER_OF_COMMITTEE
        OPTIONAL MATCH (d)-[rvm:MEMBER_OF_COMMITTEE]->(cvm:Committee)
        WHERE rvm.role = 'vice_president'
        WITH v1_vice_roles, collect(DISTINCT CASE WHEN cvm IS NULL THEN NULL ELSE {role: 'Vicepresidente ' + cvm.name, active: rvm.end_date IS NULL OR rvm.end_date >= date()} END) AS v2_vice_roles
        RETURN v1_vice_roles + v2_vice_roles AS vice_roles
    }
    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rs:IS_SECRETARY]->(cs:Committee)
        WITH d, collect(DISTINCT CASE WHEN cs IS NULL THEN NULL ELSE {role: 'Segretario ' + cs.name, active: rs.end_date IS NULL OR rs.end_date >= date()} END) AS v1_secretary_roles
        // schema v2: role as a property on MEMBER_OF_COMMITTEE
        OPTIONAL MATCH (d)-[rsm:MEMBER_OF_COMMITTEE]->(csm:Committee)
        WHERE rsm.role = 'secretary'
        WITH v1_secretary_roles, collect(DISTINCT CASE WHEN csm IS NULL THEN NULL ELSE {role: 'Segretario ' + csm.name, active: rsm.end_date IS NULL OR rsm.end_date >= date()} END) AS v2_secretary_roles
        RETURN v1_secretary_roles + v2_secretary_roles AS secretary_roles
    }
    WITH d, current_committee, president_roles + vice_roles + secretary_roles AS all_roles

    // Prefer active roles, fall back to any role
    WITH d, current_committee, all_roles,
         [r IN all_roles WHERE r.active | r.role] AS active_roles,
         [r IN all_roles | r.role] AS any_roles

    RETURN d.id AS id,
           d.first_name AS first_name,
           d.last_name AS last_name,
           d.profession AS profession,
           d.education AS education,
           d.deputy_card AS camera_profile_url,
           d.photo AS photo,
           current_committee,
           CASE
               WHEN size(active_roles) > 0 THEN active_roles[0]
               WHEN size(any_roles) > 0 THEN any_roles[0]
               ELSE null
           END AS institutional_role
    """
    with neo4j_client.session() as session:
        result = session.run(cypher, speaker_id=speaker_id)
        record = result.single()
        if record:
            return dict(record)

    # Try GovernmentMember
    cypher_gov = """
    MATCH (m:GovernmentMember {id: $speaker_id})
    RETURN m.id AS id,
           m.first_name AS first_name,
           m.last_name AS last_name,
           m.institutional_role AS institutional_role,
           m.deputy_card AS camera_profile_url
    """
    with neo4j_client.session() as session:
        result = session.run(cypher_gov, speaker_id=speaker_id)
        record = result.single()
        if record:
            data = dict(record)
            data["profession"] = None
            data["education"] = None
            data["current_committee"] = None
            return data

    return {}


async def _compute_experts(
    evidence_list: List[Any],
    authority_scores: Dict[str, float],
    authority_details: Dict[str, Dict[str, Any]],
    neo4j_client: Neo4jClient
) -> List[Dict[str, Any]]:
    """Compute experts in frontend-expected format with full details."""
    from concurrent.futures import ThreadPoolExecutor
    coalition_logic = CoalitionLogic()
    party_speakers: Dict[str, Dict[str, Dict]] = {}

    for evidence in evidence_list:
        if evidence.speaker_role == "GovernmentMember":
            continue
        party = evidence.party
        speaker_id = evidence.speaker_id
        speaker_name = evidence.speaker_name

        if party not in party_speakers:
            party_speakers[party] = {}

        if speaker_id not in party_speakers[party]:
            party_speakers[party][speaker_id] = {
                "speaker_name": speaker_name,
                # 0.0 default, consistent with the evidence-injection default:
                # compute_all_authority covers every retrieved speaker, so a
                # miss means the id was absent from the batch, not "average".
                "authority_score": authority_scores.get(speaker_id, 0.0),
                "count": 0,
                "party": party,
            }

        party_speakers[party][speaker_id]["count"] += 1

    top_speakers_info = []
    for party, speakers in party_speakers.items():
        if speakers:
            top_speaker_id = max(
                speakers.keys(),
                key=lambda s: speakers[s]["authority_score"]
            )
            top_speakers_info.append((party, top_speaker_id, speakers[top_speaker_id]))

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=min(10, max(1, len(top_speakers_info)))) as pool:
        detail_futures = [
            loop.run_in_executor(pool, _fetch_speaker_details, neo4j_client, info[1])
            for info in top_speakers_info
        ]
        speaker_details_list = await asyncio.gather(*detail_futures)

    experts = []
    for (party, top_speaker_id, top_speaker), speaker_info in zip(top_speakers_info, speaker_details_list):
        coalition = coalition_logic.get_coalition(party)

        name_parts = top_speaker["speaker_name"].split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        details = authority_details.get(top_speaker_id, {})
        components = details.get("components", {})

        experts.append({
            "id": top_speaker_id,
            "first_name": first_name,
            "last_name": last_name,
            "group": party,
            "coalition": coalition,
            "authority_score": round(top_speaker["authority_score"], 2),
            "relevant_speeches_count": top_speaker["count"],
            "camera_profile_url": speaker_info.get("camera_profile_url"),
            "photo": speaker_info.get("photo"),
            "profession": speaker_info.get("profession"),
            "education": speaker_info.get("education"),
            "committee": speaker_info.get("current_committee"),
            "institutional_role": details.get("institutional_role") or speaker_info.get("institutional_role"),
            "score_breakdown": {
                "speeches": round(components.get("interventions", 0), 2),
                "acts": round(components.get("acts", 0), 2),
                "committee": round(components.get("committee", 0), 2),
                "profession": round(components.get("profession", 0), 2),
                "education": round(components.get("education", 0), 2),
                "role": round(components.get("role", 0), 2),
            },
        })

    return experts


def _batch_fetch_deputy_cards(neo4j_client: Neo4jClient, speaker_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch deputy_card URLs and photos for a list of speaker IDs. Returns {speaker_id: {url, photo}}."""
    if not speaker_ids:
        return {}
    cypher = """
    UNWIND $ids AS sid
    OPTIONAL MATCH (d:Deputy {id: sid})
    OPTIONAL MATCH (m:GovernmentMember {id: sid})
    WITH sid, coalesce(d.deputy_card, m.deputy_card) AS url, coalesce(d.photo, m.photo) AS photo
    WHERE url IS NOT NULL OR photo IS NOT NULL
    RETURN sid, url, photo
    """
    result_map: Dict[str, Dict[str, Any]] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher, ids=list(set(speaker_ids)))
        for record in result:
            result_map[record["sid"]] = {"url": record["url"], "photo": record["photo"]}
    return result_map


def _batch_fetch_speaker_enrichment(neo4j_client: Neo4jClient, speaker_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Batch-fetch detailed speaker info (profile URL, profession, education, committee, role) from Neo4j."""
    if not speaker_ids:
        return {}

    unique_ids = list(set(speaker_ids))

    # Fetch Deputies with full details
    cypher_deputies = """
    UNWIND $ids AS sid
    OPTIONAL MATCH (d:Deputy {id: sid})
    WITH sid, d WHERE d IS NOT NULL
    OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
    WHERE mc.end_date IS NULL OR mc.end_date >= date()
    WITH sid, d, collect(c.name)[0] AS current_committee
    RETURN sid,
           d.deputy_card AS camera_profile_url,
           d.photo AS photo,
           d.profession AS profession,
           d.education AS education,
           current_committee
    """

    result_map: Dict[str, Dict[str, Any]] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher_deputies, ids=unique_ids)
        for record in result:
            result_map[record["sid"]] = {
                "camera_profile_url": record["camera_profile_url"],
                "photo": record["photo"],
                "profession": record["profession"],
                "education": record["education"],
                "committee": record["current_committee"],
            }

    # Fetch GovernmentMembers for any IDs not found as Deputies
    missing_ids = [sid for sid in unique_ids if sid not in result_map]
    if missing_ids:
        cypher_gov = """
        UNWIND $ids AS sid
        OPTIONAL MATCH (m:GovernmentMember {id: sid})
        WITH sid, m WHERE m IS NOT NULL
        RETURN sid,
               m.deputy_card AS camera_profile_url,
               m.photo AS photo,
               m.institutional_role AS institutional_role
        """
        with neo4j_client.session() as session:
            result = session.run(cypher_gov, ids=missing_ids)
            for record in result:
                result_map[record["sid"]] = {
                    "camera_profile_url": record["camera_profile_url"],
                    "photo": record["photo"],
                    "profession": None,
                    "education": None,
                    "committee": None,
                    "institutional_role": record["institutional_role"],
                }

    return result_map


def _batch_fetch_gov_roles(neo4j_client: Neo4jClient, speaker_ids: List[str]) -> Dict[str, str]:
    """
    Batch-fetch institutional roles for government members.
    Also matches Deputies who hold government positions (e.g. PM, ministers who are also MPs)
    by looking up GovernmentMember nodes with the same first_name + last_name.
    Returns {speaker_id: role}.
    """
    if not speaker_ids:
        return {}
    cypher = """
    UNWIND $ids AS sid
    // Direct GovernmentMember match
    OPTIONAL MATCH (m:GovernmentMember {id: sid})
    // Also check if a Deputy matches a GovernmentMember by name
    OPTIONAL MATCH (d:Deputy {id: sid})
    OPTIONAL MATCH (gm:GovernmentMember)
    WHERE gm.first_name = d.first_name AND gm.last_name = d.last_name
    WITH sid,
         COALESCE(m.institutional_role, gm.institutional_role) AS role
    WHERE role IS NOT NULL
    RETURN sid, role
    """
    result_map: Dict[str, str] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher, ids=list(set(speaker_ids)))
        for record in result:
            result_map[record["sid"]] = record["role"]
    return result_map


def _build_citations_for_frontend(
    evidence_dicts: List[Dict[str, Any]],
    neo4j_client: Neo4jClient = None,
) -> List[Dict[str, Any]]:
    """Build citations in frontend-expected format from evidence dicts."""
    coalition_logic = CoalitionLogic()
    citations = []

    deputy_card_map: Dict[str, Dict[str, Any]] = {}
    gov_role_map: Dict[str, str] = {}
    if neo4j_client:
        speaker_ids = [e.get("speaker_id", "") for e in evidence_dicts[:20] if e.get("speaker_id")]
        deputy_card_map = _batch_fetch_deputy_cards(neo4j_client, speaker_ids)
        gov_role_map = _batch_fetch_gov_roles(neo4j_client, speaker_ids)

    for i, e in enumerate(evidence_dicts[:20]):
        evidence_id = e.get("evidence_id", f"cit_{i+1}")
        speaker_name = e.get("speaker_name", "")
        speaker_id = e.get("speaker_id", "")
        party = e.get("party", "MISTO")
        is_government = e.get("speaker_role") == "GovernmentMember" or speaker_id in gov_role_map

        if is_government:
            group = "Governo"
            coalition = "governo"
        else:
            group = party
            coalition = coalition_logic.get_coalition(party)

        name_parts = speaker_name.split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        chunk_text = e.get("chunk_text") or ""
        quote_text = e.get("quote_text") or ""
        display_text = (chunk_text or quote_text)[:300]

        _dep_info = deputy_card_map.get(speaker_id) or {}
        cit_data: Dict[str, Any] = {
            "chunk_id": evidence_id,
            "deputy_first_name": first_name,
            "deputy_last_name": last_name,
            "text": display_text,
            "quote_text": quote_text,
            "full_text": chunk_text or quote_text,
            "group": group,
            "coalition": coalition,
            "date": str(e.get("date", "")),
            "similarity": round(e.get("similarity", 0), 2),
            "debate": e.get("debate_title", ""),
            "intervention_id": e.get("speech_id", ""),
            "camera_profile_url": _dep_info.get("url"),
            "photo": _dep_info.get("photo"),
        }
        if is_government:
            role = gov_role_map.get(speaker_id)
            if not role and neo4j_client:
                try:
                    with neo4j_client.session() as sess:
                        rec = sess.run(
                            "MATCH (m:GovernmentMember {id: $sid}) RETURN m.institutional_role AS role",
                            sid=speaker_id
                        ).single()
                        if rec and rec["role"]:
                            role = rec["role"]
                except Exception:
                    pass
            if role:
                cit_data["institutional_role"] = role
        citations.append(cit_data)

    return citations


def _build_verified_citations(
    generation_citations: List[Dict],
    evidence_dicts: List[Dict],
    neo4j_client: Neo4jClient = None,
) -> List[Dict[str, Any]]:
    """
    Build verified citations with full details for citation_details event.

    Uses evidence_id as chunk_id for consistent linking.
    """
    coalition_logic = CoalitionLogic()
    evidence_map = {e.get("evidence_id"): e for e in evidence_dicts}

    deputy_card_map: Dict[str, Dict[str, Any]] = {}
    gov_role_map: Dict[str, str] = {}
    if neo4j_client:
        speaker_ids = []
        for cit in generation_citations:
            eid = cit.get("evidence_id", "")
            evidence = evidence_map.get(eid, {})
            sid = cit.get("speaker_id") or evidence.get("speaker_id", "")
            if sid:
                speaker_ids.append(sid)
        deputy_card_map = _batch_fetch_deputy_cards(neo4j_client, speaker_ids)
        gov_role_map = _batch_fetch_gov_roles(neo4j_client, speaker_ids)

    verified = []
    for cit in generation_citations:
        eid = cit.get("evidence_id", "")
        evidence = evidence_map.get(eid, {})
        party = cit.get("party", evidence.get("party", "MISTO"))
        speaker_id = cit.get("speaker_id") or evidence.get("speaker_id", "")
        speaker_role = cit.get("speaker_role") or evidence.get("speaker_role", "Deputy")
        is_government = speaker_role == "GovernmentMember" or speaker_id in gov_role_map

        if is_government:
            group = "Governo"
            coalition = "governo"
        else:
            group = party
            coalition = coalition_logic.get_coalition(party)

        speaker_name = cit.get("speaker_name", evidence.get("speaker_name", ""))
        name_parts = speaker_name.split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        _dep_info = deputy_card_map.get(speaker_id) or {}
        cit_data: Dict[str, Any] = {
            "chunk_id": eid,
            "deputy_first_name": first_name,
            "deputy_last_name": last_name,
            "text": cit.get("quote_text", "") or evidence.get("chunk_text", ""),
            "quote_text": cit.get("quote_text", ""),
            "full_text": evidence.get("chunk_text", ""),
            "group": group,
            "coalition": coalition,
            "date": str(cit.get("date", "")),
            "span_start": cit.get("span_start", 0),
            "span_end": cit.get("span_end", 0),
            "debate": evidence.get("debate_title", ""),
            "intervention_id": evidence.get("speech_id", ""),
            "camera_profile_url": _dep_info.get("url"),
            "photo": _dep_info.get("photo"),
            "verified": True,
        }
        if is_government:
            role = gov_role_map.get(speaker_id)
            if not role and neo4j_client:
                try:
                    with neo4j_client.session() as sess:
                        rec = sess.run(
                            "MATCH (m:GovernmentMember {id: $sid}) RETURN m.institutional_role AS role",
                            sid=speaker_id
                        ).single()
                        if rec and rec["role"]:
                            role = rec["role"]
                except Exception:
                    pass
            if role:
                cit_data["institutional_role"] = role
        verified.append(cit_data)

    return verified


@router.post("/query")
async def query_endpoint(request: QueryRequest, http_request: Request):
    """
    Main query endpoint.

    Supports SSE streaming (default) or synchronous response.
    """
    if request.stream:
        return StreamingResponse(
            _rate_limited_query(request, http_request),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )
    else:
        # Synchronous response
        services = get_services()

        try:
            retrieval_result = await services["retrieval"].retrieve(
                query=request.query,
                top_k=request.top_k,
                date_start=request.date_start,
                date_end=request.date_end
            )

            evidence_list = retrieval_result["evidence"]
            evidence_dicts = [e.model_dump() for e in evidence_list]

            speaker_ids = list(set(e.speaker_id for e in evidence_list if e.speaker_id))
            query_embedding = await asyncio.get_running_loop().run_in_executor(
                None, lambda: services["retrieval"].embed_query(request.query)
            )

            # Batch authority: 2 DB queries for all speakers + parallel CPU scoring
            authority_all = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: services["authority"].compute_all_authority(speaker_ids, query_embedding),
            )
            authority_scores = {sid: r["total_score"] for sid, r in authority_all.items()}
            authority_details = authority_all

            # Write computed authority scores back into evidence_dicts so that
            # the generation pipeline can use real scores for per-party citation ranking.
            for ed in evidence_dicts:
                sid = ed.get("speaker_id", "")
                if sid in authority_scores:
                    ed["authority_score"] = authority_scores[sid]

            experts = await _compute_experts(
                evidence_list, authority_scores, authority_details, services["neo4j"]
            )

            coverage = services["ideology"].compute_coverage_metrics(evidence_dicts)

            gen_result = await services["generation"].generate(
                query=request.query,
                evidence_list=evidence_dicts
            )

            citations = [
                CitationInfo(
                    citation_id=f"cit_{i+1}",
                    chunk_id=c.get("evidence_id", ""),
                    quote_text=c.get("quote_text", ""),
                    speaker_name=c.get("speaker_name", ""),
                    party=c.get("party", ""),
                    date=str(c.get("date", "")),
                    span_start=c.get("span_start", 0),
                    span_end=c.get("span_end", 0),
                )
                for i, c in enumerate(gen_result.get("citations", []))
            ]

            return QueryResponse(
                text=gen_result.get("text", ""),
                citations=citations,
                experts=experts,
                compass=coverage,
                metadata=retrieval_result["metadata"]
            )

        except Exception as e:
            logger.error(f"Query error: {e}")
            raise HTTPException(status_code=500, detail=str(e))


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    try:
        services = get_services()
        services["neo4j"].verify_connectivity()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}
