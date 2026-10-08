"""Chat endpoints streaming pipeline results in the SSE format the frontend expects."""
import json
import logging
import asyncio
import os
import time
from datetime import date
from typing import Optional, List, Dict, Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from ..services.neo4j_client import Neo4jClient
from ..services.translation import translate_citation_batch, translate_response_text, translate_compass_axes
from ..services.compass import IdeologyScorer
from ..services.retrieval.commission_matcher import get_commission_matcher
from ..services.task_store import get_task_store
from ..services.response_cache import (
    build_cache_key,
    config_fingerprint,
    get_data_version,
    get_inflight_registry,
    get_response_cache,
    mirror_task,
    replay_into_task,
)
from ..services.deps import get_services
from ..config import get_config

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Chat"])


class TaskCancelledError(Exception):
    """Raised when the user explicitly cancels a running pipeline."""


def _raise_if_cancelled(task_id: str, store) -> None:
    """Synchronous check — raises TaskCancelledError if the task was cancelled."""
    if store.is_cancelled(task_id):
        raise TaskCancelledError(f"Task {task_id} was cancelled by the user")


class ChatRequest(BaseModel):
    """Request model matching frontend expectations."""
    query: str = Field(..., min_length=3, max_length=4000)
    mode: str = Field(default="standard")  # "standard" or "high_quality"
    task_id: Optional[str] = Field(default=None)  # Client-provided task ID for reconnection
    locale: str = Field(default="it")  # Language for response/citation translation ("it" | "en")




def sse_event(event_type: str, data: Any) -> str:
    """Format SSE event."""
    if isinstance(data, dict):
        payload = {"type": event_type, **data}
    else:
        payload = {"type": event_type, "data": data}
    return f"data: {json.dumps(payload, default=str)}\n\n"


# Limit concurrent pipeline executions to prevent thread pool and Neo4j connection exhaustion.
# Each pipeline opens a ThreadPoolExecutor(10) + several OpenAI calls concurrently.
# 5 per worker is the default ceiling; adjust with _MAX_CONCURRENT_PIPELINES env var.
_MAX_CONCURRENT_PIPELINES = int(os.environ.get("MAX_CONCURRENT_PIPELINES", "5"))
_pipeline_semaphore: Optional[asyncio.Semaphore] = None
_pipeline_counter_lock: Optional[asyncio.Lock] = None
_waiting_queue: list[str] = []  # ordered list of waiting task_ids (front = next to run)
_pipeline_active: int = 0       # tasks currently running


def _get_pipeline_semaphore() -> asyncio.Semaphore:
    global _pipeline_semaphore
    if _pipeline_semaphore is None:
        _pipeline_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_PIPELINES)
    return _pipeline_semaphore


def _get_counter_lock() -> asyncio.Lock:
    global _pipeline_counter_lock
    if _pipeline_counter_lock is None:
        _pipeline_counter_lock = asyncio.Lock()
    return _pipeline_counter_lock


async def _acquire_pipeline_slot(
    semaphore: asyncio.Semaphore,
    emit_fn,
    task_id: str,
    max_wait: int = 300,   # 5-minute hard timeout
    check_every: int = 10,  # send position update every N seconds
) -> bool:
    """Acquire a pipeline slot, emitting periodic queue-position updates.

    Returns True if the slot was acquired, False if max_wait expired.
    asyncio.wait_for cancels the acquire() coroutine on timeout, which removes
    us from the semaphore waiters list before we retry. Position tracking uses
    an ordered list so each task knows its rank as tasks ahead of it finish.
    """
    global _waiting_queue, _pipeline_active
    lock = _get_counter_lock()

    # Fast path: slot available immediately
    if not semaphore.locked():
        await semaphore.acquire()
        async with lock:
            _pipeline_active += 1
        logger.info(f"[SEMAPHORE] Task {task_id} acquired immediately (active={_pipeline_active})")
        return True

    # Slow path: add to ordered waiting queue
    async with lock:
        _waiting_queue.append(task_id)
        position = len(_waiting_queue)   # 1-indexed position in queue
        ahead = position - 1             # people ahead of this task
        active_now = _pipeline_active
    logger.info(f"[SEMAPHORE] Task {task_id} queued (position={position}, ahead={ahead}, active={active_now})")

    def _current_position() -> tuple[int, int]:
        """Return (position, ahead) for this task. Must be called under lock."""
        try:
            pos = _waiting_queue.index(task_id) + 1
        except ValueError:
            pos = 1
        return pos, pos - 1

    try:
        await emit_fn("waiting", {
            "queue_position": position,
            "ahead_count": ahead,
            "active_count": active_now,
            "elapsed_seconds": 0,
        })

        elapsed = 0
        while elapsed < max_wait:
            try:
                await asyncio.wait_for(semaphore.acquire(), timeout=check_every)
                async with lock:
                    _pipeline_active += 1
                logger.info(f"[SEMAPHORE] Task {task_id} acquired after {elapsed}s "
                            f"(active={_pipeline_active}, still_waiting={len(_waiting_queue) - 1})")
                return True
            except asyncio.TimeoutError:
                elapsed += check_every
                async with lock:
                    position, ahead = _current_position()
                    active_now = _pipeline_active
                logger.info(f"[SEMAPHORE] Task {task_id} still waiting "
                            f"({elapsed}s, position={position}, ahead={ahead}, active={active_now})")
                await emit_fn("waiting", {
                    "queue_position": position,
                    "ahead_count": ahead,
                    "active_count": active_now,
                    "elapsed_seconds": elapsed,
                })

        logger.warning(f"[SEMAPHORE] Task {task_id} timed out after {max_wait}s")
        return False

    finally:
        async with lock:
            try:
                _waiting_queue.remove(task_id)
            except ValueError:
                pass


async def process_chat_background(
    request: ChatRequest,
    task_id: str,
    cache_key: Optional[str] = None,
):
    """
    Process chat pipeline in the background, storing events in TaskStore.

    This runs independently of the SSE connection so that mobile browsers
    can disconnect without losing results. When cache_key is given, this
    run is the in-flight leader for that key: the completed event list is
    stored in the response cache and the key is released at the end.
    """
    store = get_task_store()

    async def emit(event_type: str, data: Any):
        """Emit an SSE event to both the task store and format it."""
        if isinstance(data, dict):
            payload = {"type": event_type, **data}
        else:
            payload = {"type": event_type, "data": data}
        await store.add_event(task_id, payload)

    services = get_services()
    pipeline_start = time.time()
    step_times: Dict[str, float] = {}

    logger.info(f"[PIPELINE START] Task: {task_id}")
    logger.info(f"[PIPELINE START] Query: {request.query[:80]}...")
    logger.info(f"[PIPELINE START] Mode: {request.mode}, Locale: {request.locale}")

    _en = request.locale != "it"
    def _t(it: str, en: str) -> str:
        return en if _en else it

    semaphore = _get_pipeline_semaphore()
    acquired = await _acquire_pipeline_slot(semaphore, emit, task_id)
    if not acquired:
        msg = _t("Il sistema è troppo occupato al momento. Riprova tra qualche minuto.",
                 "The system is too busy right now. Please try again in a few minutes.")
        await emit("error", {"message": msg})
        await store.fail_task(task_id, "Timeout in coda")
        if cache_key:
            await get_inflight_registry().release(cache_key, task_id)
        return

    try:
        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 1, "total": 8, "message": _t("Analisi query", "Query analysis")})
        step_times["step_1_init"] = time.time() - step_start
        logger.info(f"[TIMING] Step 1 (Init): {step_times['step_1_init']*1000:.1f}ms")

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 2, "total": 8, "message": _t("Commissioni", "Committees")})

        commission_matcher = get_commission_matcher()
        relevant_commissions = commission_matcher.find_relevant_commissions(
            query=request.query, top_k=3, min_score=0.1
        )
        await emit("commissioni", {"commissioni": relevant_commissions})
        step_times["step_2_commissioni"] = time.time() - step_start
        logger.info(f"[TIMING] Step 2 (Commissioni): {step_times['step_2_commissioni']*1000:.1f}ms - {len(relevant_commissions)} found")

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 3, "total": 8, "message": _t("Esperti", "Authoritative sources")})

        logger.info("[RETRIEVAL] Starting dual-channel retrieval...")
        retrieval_start = time.time()

        def _do_retrieval():
            return services["retrieval"].retrieve_sync(query=request.query, top_k=100)

        retrieval_result = await asyncio.get_running_loop().run_in_executor(None, _do_retrieval)
        retrieval_time = time.time() - retrieval_start
        logger.info(f"[TIMING] Retrieval completed: {retrieval_time*1000:.1f}ms")

        evidence_list = retrieval_result["evidence"]
        evidence_dicts = []
        for e in evidence_list:
            d = e.model_dump()
            d["embedding"] = e.embedding
            evidence_dicts.append(d)

        logger.info(f"[RETRIEVAL] Retrieved {len(evidence_list)} evidence pieces")
        logger.info(f"[RETRIEVAL] Dense: {retrieval_result['metadata'].get('dense_channel_count', 0)}, "
                   f"Graph: {retrieval_result['metadata'].get('graph_channel_count', 0)}")

        # UI step 1 detail: report what actually happened — query embedding
        # plus hybrid retrieval with per-channel counts.
        _dense_n = retrieval_result['metadata'].get('dense_channel_count', 0)
        _graph_n = retrieval_result['metadata'].get('graph_channel_count', 0)
        await emit("step_result", {
            "step": 1,
            "detail": _t(
                f"Embedding semantico della query; retrieval ibrido: {_dense_n} "
                f"risultati vettoriali + {_graph_n} dal grafo dei firmatari → "
                f"{len(evidence_list)} evidenze selezionate",
                f"Query embedding; hybrid retrieval: {_dense_n} vector results "
                f"+ {_graph_n} from the signatories graph → "
                f"{len(evidence_list)} selected evidence pieces",
            ),
        })

        speaker_ids = list(set(
            e.speaker_id for e in evidence_list
            if e.speaker_id and e.speaker_role == "Deputy"
        ))
        logger.info(f"[AUTHORITY] Computing scores for {len(speaker_ids)} unique speakers...")
        authority_start = time.time()

        query_embedding = await asyncio.get_running_loop().run_in_executor(
            None, lambda: services["retrieval"].embed_query(request.query)
        )

        authority_scores = {}
        authority_details = {}
        if speaker_ids:
            from concurrent.futures import ThreadPoolExecutor

            def _compute_single(sid):
                return sid, services["authority"].compute_authority(sid, query_embedding)

            loop = asyncio.get_running_loop()
            with ThreadPoolExecutor(max_workers=min(10, len(speaker_ids))) as pool:
                futures = [loop.run_in_executor(pool, _compute_single, sid) for sid in speaker_ids]
                results = await asyncio.gather(*futures)

            for sid, result in results:
                authority_scores[sid] = result["total_score"]
                authority_details[sid] = result

        # Write computed authority scores back into evidence_dicts so that the
        # generation pipeline can use real scores for per-party citation ranking.
        # (evidence_dicts are built from model_dump() before scoring, so
        # authority_score is 0.0 by default until this back-fill.)
        for d in evidence_dicts:
            sid = d.get("speaker_id", "")
            if sid in authority_scores:
                d["authority_score"] = authority_scores[sid]

        authority_time = time.time() - authority_start
        step_times["step_3_authority"] = time.time() - step_start
        logger.info(f"[TIMING] Authority scoring: {authority_time*1000:.1f}ms")
        logger.info(f"[TIMING] Step 3 (Esperti) total: {step_times['step_3_authority']*1000:.1f}ms")

        experts = await _compute_experts_for_frontend(
            evidence_list, authority_scores, authority_details, services["neo4j"]
        )
        maggioranza_experts = sum(1 for e in experts if e.get("coalizione") == "maggioranza")
        opposizione_experts = sum(1 for e in experts if e.get("coalizione") == "opposizione")
        logger.info(f"[EXPERTS] Found {len(experts)} experts: {maggioranza_experts} maggioranza, {opposizione_experts} opposizione")

        await emit("experts", {"experts": experts})

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 4, "total": 8, "message": _t("Interventi", "Speeches")})

        citations = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _build_citations_for_frontend(evidence_dicts, neo4j_client=services["neo4j"])
        )
        if citations:
            logger.debug(f"[CITATIONS] Sample citation[0]: deputy={citations[0].get('deputy_first_name')} {citations[0].get('deputy_last_name')}, "
                        f"group={citations[0].get('group')}, coalition={citations[0].get('coalition')}, "
                        f"text_len={len(citations[0].get('text', ''))}")
        await emit("citations", {"citations": citations})
        step_times["step_4_citations"] = time.time() - step_start
        logger.info(f"[TIMING] Step 4 (Interventi): {step_times['step_4_citations']*1000:.1f}ms - {len(citations)} citations")

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 5, "total": 8, "message": _t("Statistiche", "Statistics")})

        balance = _compute_balance_metrics(evidence_dicts)
        await emit("balance", balance)
        step_times["step_5_balance"] = time.time() - step_start
        logger.info(f"[TIMING] Step 5 (Statistiche): {step_times['step_5_balance']*1000:.1f}ms")
        logger.info(f"[BALANCE] Maggioranza: {balance.get('maggioranza_percentage', 0):.1f}%, "
                   f"Opposizione: {balance.get('opposizione_percentage', 0):.1f}%, "
                   f"Bias: {balance.get('bias_score', 0):.2f}")

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 6, "total": 8, "message": _t("Bussola Ideologica", "Ideological Compass")})

        compass_data = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _compute_compass_data(services["ideology"], evidence_dicts, query=request.query)
        )
        logger.info(f"[COMPASS] meta={compass_data.get('meta', {})}, "
                   f"groups_count={len(compass_data.get('groups', []))}, "
                   f"axes_keys={list(compass_data.get('axes', {}).keys())}")
        if request.locale != "it":
            compass_data = await translate_compass_axes(compass_data, target_lang=request.locale)
        await emit("compass", compass_data)
        step_times["step_6_compass"] = time.time() - step_start
        logger.info(f"[TIMING] Step 6 (Bussola): {step_times['step_6_compass']*1000:.1f}ms")

        _raise_if_cancelled(task_id, store)
        step_start = time.time()
        await emit("progress", {"step": 7, "total": 8, "message": _t("Generazione", "Generation")})

        logger.info("[GENERATION] Starting 4-stage generation pipeline...")
        generation_start = time.time()

        generation_result = await services["generation"].generate(
            query=request.query, evidence_list=evidence_dicts,
            query_context=retrieval_result.get("metadata", {}).get("rewritten_query"),
        )

        generation_time = time.time() - generation_start
        logger.info(f"[TIMING] Generation pipeline: {generation_time*1000:.1f}ms")

        final_text = generation_result.get("text", "")

        # UI step 7 detail
        _gen_stages = generation_result.get("metadata", {}).get("stages", {})
        _n_sections = _gen_stages.get("sectional", {}).get("sections_count", 0)
        _n_cits = _gen_stages.get("surgeon", {}).get("citations_inserted", 0)
        await emit("step_result", {
            "step": 7,
            "detail": _t(
                f"{_n_sections} sezioni di gruppo scritte, {_n_cits} citazioni "
                f"verbatim verificate e inserite ({generation_time:.0f}s)",
                f"{_n_sections} group sections written, {_n_cits} verbatim "
                f"citations verified and inserted ({generation_time:.0f}s)",
            ),
        })

        topic_stats = generation_result.get("topic_statistics")
        if topic_stats:
            # Enrich speakers/interventions with photo URLs from Neo4j
            speakers_detail = topic_stats.get("speakers_detail", [])
            interventions_detail = topic_stats.get("interventions_detail", [])
            neo4j = services.get("neo4j")
            if neo4j:
                all_sids = list(set(
                    s.get("speaker_id", "") for s in speakers_detail
                ) | set(
                    i.get("speaker_id", "") for i in interventions_detail
                    if i.get("speaker_id")
                ))
                photo_map = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: _batch_fetch_photos(neo4j, [s for s in all_sids if s])
                )
                for s in speakers_detail:
                    s["photo"] = photo_map.get(s.get("speaker_id", ""))
                for i in interventions_detail:
                    i["photo"] = photo_map.get(i.get("speaker_id", ""))

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
            await emit("topic_stats", ts_payload)
            logger.info(
                f"[TOPIC_STATS] Sent: {ts_payload['intervention_count']} interventions, "
                f"{ts_payload['speaker_count']} speakers, "
                f"{len(ts_payload['sessions_detail'])} sessions"
            )

        # The writer may cite chunk IDs outside the initial evidence list:
        # verify them against Neo4j and fetch their metadata, stripping links
        # whose IDs do not exist.
        import re as _re
        extra_citation_ids = generation_result.get("extra_citation_ids", [])
        extra_evidence_map: Dict[str, Dict[str, Any]] = {}

        if extra_citation_ids:
            logger.info(f"[CITATIONS] Resolving {len(extra_citation_ids)} extra citation IDs from DB...")
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
                        "speaker_role": row.get("speaker_type", "Deputy"),
                        "party": party,
                        "coalition": config.get_coalition(party),
                        "date": date_obj,
                        "span_start": span_start,
                        "span_end": span_end,
                        "debate_title": row.get("debate_title", ""),
                        "session_id": row.get("session_id", ""),
                    }
                found_ids = set(extra_evidence_map.keys())
                missing_ids = set(extra_citation_ids) - found_ids
                logger.info(
                    f"[CITATIONS] DB lookup: {len(found_ids)} found, "
                    f"{len(missing_ids)} not in DB"
                )

                if missing_ids:
                    def _strip_missing(match):
                        href = match.group(2)
                        if href in missing_ids:
                            logger.warning(f"[CITATIONS] Stripping non-existent ID: {href}")
                            return match.group(1)
                        return match.group(0)
                    final_text = _re.sub(
                        r'\[([^\]]+)\]\((leg1[89]_[^)]+)\)',
                        _strip_missing,
                        final_text
                    )
            except Exception as e:
                logger.error(f"[CITATIONS] DB lookup failed: {e}", exc_info=True)
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

        if request.locale != "it":
            final_text = await translate_response_text(final_text, target_lang=request.locale)

        chunk_size = 50
        logger.info(f"[GENERATION] Generated {len(final_text)} chars, streaming in {len(final_text)//chunk_size + 1} chunks")

        for i in range(0, len(final_text), chunk_size):
            chunk = final_text[i:i+chunk_size]
            await emit("chunk", {"content": chunk})
            await asyncio.sleep(0.02)

        step_times["step_7_generation"] = time.time() - step_start
        logger.info(f"[TIMING] Step 7 (Generazione) total: {step_times['step_7_generation']*1000:.1f}ms")

        # Build the complete citation list, recovering IDs that appear in the
        # text but were not tracked by the generation stage.
        text_evidence_ids = set(_re.findall(r'\]\((leg1[89]_[^)]+)\)', final_text))
        evidence_map_for_cit = {e.get("evidence_id"): e for e in evidence_dicts}
        evidence_map_for_cit.update(extra_evidence_map)

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
                logger.info(f"[CITATIONS] Recovered from text scan: {eid}")

        logger.info(f"[CITATIONS] {len(gen_citations)} total citations ({len(text_evidence_ids)} in text, {len(tracked_ids)} tracked)")

        all_evidence_for_verify = evidence_dicts + list(extra_evidence_map.values())
        verify_start = time.time()
        verified_citations = await asyncio.get_running_loop().run_in_executor(
            None, lambda: _build_verified_citations(gen_citations, all_evidence_for_verify, neo4j_client=services["neo4j"])
        )
        verify_time = time.time() - verify_start
        logger.info(f"[CITATIONS] {len(verified_citations)} verified citations to send")
        if request.locale != "it":
            verified_citations = await translate_citation_batch(verified_citations, target_lang=request.locale)
        await emit("citation_details", {"citations": verified_citations})

        if request.mode == "high_quality":
            _raise_if_cancelled(task_id, store)
            step_start = time.time()
            await emit("progress", {"step": 8, "total": 8, "message": _t("Valutazione", "Evaluation")})
            await emit("hq_variants", {
                "variants": [{"text": final_text}]
            })
            step_times["step_8_valutazione"] = time.time() - step_start
            logger.info(f"[TIMING] Step 8 (Valutazione): {step_times['step_8_valutazione']*1000:.1f}ms")

        total_time = time.time() - pipeline_start
        step_times["total"] = total_time

        logger.info("[PIPELINE COMPLETE] Summary:")
        logger.info(f"  Total time: {total_time*1000:.1f}ms ({total_time:.2f}s)")
        logger.info(f"  Evidence: {len(evidence_list)} pieces from {len(speaker_ids)} speakers")
        logger.info(f"  Balance: {balance.get('maggioranza_percentage', 0):.1f}% / {balance.get('opposizione_percentage', 0):.1f}%")
        logger.info(f"  Generated: {len(final_text)} chars, {len(verified_citations)} citations")
        logger.info("[TIMING BREAKDOWN]:")
        for step_name, step_time in step_times.items():
            if step_name != "total":
                pct = (step_time / total_time) * 100 if total_time > 0 else 0
                logger.info(f"  {step_name}: {step_time*1000:.1f}ms ({pct:.1f}%)")

        # UI step 8 detail
        await emit("step_result", {
            "step": 8,
            "detail": _t(
                f"Analisi salvata nello storico — {total_time:.0f}s totali, "
                f"{len(final_text):,} caratteri, {len(verified_citations)} citazioni",
                f"Analysis saved to history — {total_time:.0f}s total, "
                f"{len(final_text):,} characters, {len(verified_citations)} citations",
            ),
        })

        # Behind-the-scenes pipeline trace: durations and counters only, no
        # prompts and no evidence texts.
        _gen_stage_meta = generation_result.get("metadata", {}).get("stages", {})

        def _gen_child(key: str, info: Dict[str, Any]) -> Dict[str, Any]:
            s = _gen_stage_meta.get(key, {})
            child: Dict[str, Any] = {"key": key, "ms": s.get("duration_ms"), "info": info}
            if s.get("model"):
                child["model"] = s["model"]
            return child

        trace = {
            "total_ms": round(total_time * 1000),
            "rewritten_query": retrieval_result.get("metadata", {}).get("rewritten_query"),
            "stages": [
                {"key": "commissions", "ms": round(step_times.get("step_2_commissioni", 0) * 1000, 1),
                 "info": {"matched": len(relevant_commissions)}},
                {"key": "retrieval", "ms": round(retrieval_time * 1000, 1),
                 "info": {"dense": _dense_n, "graph": _graph_n, "selected": len(evidence_list)}},
                {"key": "authority", "ms": round(authority_time * 1000, 1),
                 "info": {"speakers": len(speaker_ids), "experts": len(experts)}},
                {"key": "citations_preview", "ms": round(step_times.get("step_4_citations", 0) * 1000, 1),
                 "info": {"citations": len(citations)}},
                {"key": "balance", "ms": round(step_times.get("step_5_balance", 0) * 1000, 1),
                 "info": {"maggioranza_pct": round(balance.get("maggioranza_percentage", 0), 1),
                          "opposizione_pct": round(balance.get("opposizione_percentage", 0), 1)}},
                {"key": "compass", "ms": round(step_times.get("step_6_compass", 0) * 1000, 1),
                 "info": {"groups": len(compass_data.get("groups", [])),
                          "method": compass_data.get("meta", {}).get("axis_method")}},
                {"key": "generation", "ms": round(generation_time * 1000, 1),
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
                {"key": "verification", "ms": round(verify_time * 1000, 1),
                 "info": {"citations_verified": len(verified_citations)}},
            ],
        }
        await emit("trace", {"trace": trace})

        await emit("complete", {
            "metadata": {
                **retrieval_result.get("metadata", {}),
                "timing": {k: round(v * 1000, 1) for k, v in step_times.items()},
            }
        })

        await store.complete_task(task_id)

        if cache_key:
            state = await store.get_task(task_id)
            if state and state.status == "completed":
                await get_response_cache().store(cache_key, state.events)

    except TaskCancelledError:
        total_time = time.time() - pipeline_start
        logger.info(f"[PIPELINE] Task {task_id} cancelled after {total_time*1000:.1f}ms")
        await store.cancel_task(task_id)
    except Exception as e:
        total_time = time.time() - pipeline_start
        logger.error(f"[PIPELINE ERROR] Failed after {total_time*1000:.1f}ms: {e}", exc_info=True)
        await emit("error", {"message": str(e)})
        await store.fail_task(task_id, str(e))
    finally:
        global _pipeline_active
        async with _get_counter_lock():
            _pipeline_active = max(0, _pipeline_active - 1)
        semaphore.release()
        if cache_key:
            await get_inflight_registry().release(cache_key, task_id)
        logger.info(f"[PIPELINE] Semaphore released for task {task_id} "
                    f"(active={_pipeline_active}, waiting={len(_waiting_queue)})")


async def stream_from_task(task_id: str) -> AsyncGenerator[str, None]:
    """
    Stream SSE events from a background task via its queue.

    If the client disconnects, the background task keeps running.
    The client can reconnect and poll for results via GET /api/chat/task/{task_id}.
    """
    store = get_task_store()
    queue = store.get_queue(task_id)
    if not queue:
        yield sse_event("error", {"message": f"Task {task_id} not found"})
        return

    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=60.0)
            if event is None:  # Sentinel: task completed
                break
            yield f"data: {json.dumps(event, default=str)}\n\n"
        except asyncio.TimeoutError:
            # Send keepalive comment to prevent proxy timeouts
            yield ": keepalive\n\n"
        except Exception:
            break


def _batch_fetch_deputy_cards(neo4j_client: Neo4jClient, speaker_ids: List[str]) -> Dict[str, str]:
    """Batch-fetch deputy_card URLs for a list of speaker IDs. Returns {speaker_id: url}."""
    if not speaker_ids:
        return {}
    cypher = """
    UNWIND $ids AS sid
    OPTIONAL MATCH (d:Deputy {id: sid})
    OPTIONAL MATCH (m:GovernmentMember {id: sid})
    WITH sid, coalesce(d.deputy_card, m.deputy_card) AS url
    WHERE url IS NOT NULL
    RETURN sid, url
    """
    result_map: Dict[str, str] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher, ids=list(set(speaker_ids)))
        for record in result:
            result_map[record["sid"]] = record["url"]
    return result_map


def _batch_fetch_photos(neo4j_client: Neo4jClient, speaker_ids: List[str]) -> Dict[str, str]:
    """Batch-fetch photo URLs for a list of speaker IDs. Returns {speaker_id: url}."""
    if not speaker_ids:
        return {}
    cypher = """
    UNWIND $ids AS sid
    OPTIONAL MATCH (d:Deputy {id: sid})
    WITH sid, d.photo AS url
    WHERE url IS NOT NULL
    RETURN sid, url
    """
    result_map: Dict[str, str] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher, ids=list(set(speaker_ids)))
        for record in result:
            result_map[record["sid"]] = record["url"]
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
    // Also check if a Deputy matches a GovernmentMember by name (indexed lookup, no full scan)
    OPTIONAL MATCH (d:Deputy {id: sid})
    OPTIONAL MATCH (gm:GovernmentMember {first_name: d.first_name, last_name: d.last_name})
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


def _fetch_speaker_details(neo4j_client: Neo4jClient, speaker_id: str) -> Dict[str, Any]:
    """Fetch detailed speaker information from Neo4j."""
    # Try Deputy first
    cypher = """
    MATCH (d:Deputy {id: $speaker_id})
    OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
    WHERE mc.end_date IS NULL OR mc.end_date >= date()
    WITH d, collect(c.name)[0] AS current_committee

    // Get institutional roles using CALL subqueries
    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rp:IS_PRESIDENT]->(cp:Committee)
        WHERE rp.end_date IS NULL OR rp.end_date >= date()
        WITH d, collect(DISTINCT 'Presidente ' + cp.name) AS v1_president_roles
        // committee offices: MEMBER_OF_COMMITTEE.officerRole (role only as fallback)
        OPTIONAL MATCH (d)-[rpm:MEMBER_OF_COMMITTEE]->(cpm:Committee)
        WHERE (rpm.officerRole = 'PRESIDENTE' OR (rpm.officerRole IS NULL AND rpm.role = 'president'))
          AND (coalesce(rpm.officerRoleEnd, rpm.end_date) IS NULL OR coalesce(rpm.officerRoleEnd, rpm.end_date) >= date())
        WITH v1_president_roles, collect(DISTINCT 'Presidente ' + cpm.name) AS v2_president_roles
        RETURN v1_president_roles + v2_president_roles AS president_roles
    }
    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rv:IS_VICE_PRESIDENT]->(cv:Committee)
        WHERE rv.end_date IS NULL OR rv.end_date >= date()
        WITH d, collect(DISTINCT 'Vicepresidente ' + cv.name) AS v1_vice_roles
        // committee offices: MEMBER_OF_COMMITTEE.officerRole (role only as fallback)
        OPTIONAL MATCH (d)-[rvm:MEMBER_OF_COMMITTEE]->(cvm:Committee)
        WHERE (rvm.officerRole = 'VICEPRESIDENTE' OR (rvm.officerRole IS NULL AND rvm.role = 'vice_president'))
          AND (coalesce(rvm.officerRoleEnd, rvm.end_date) IS NULL OR coalesce(rvm.officerRoleEnd, rvm.end_date) >= date())
        WITH v1_vice_roles, collect(DISTINCT 'Vicepresidente ' + cvm.name) AS v2_vice_roles
        RETURN v1_vice_roles + v2_vice_roles AS vice_roles
    }
    CALL {
        WITH d
        OPTIONAL MATCH (d)-[rs:IS_SECRETARY]->(cs:Committee)
        WHERE rs.end_date IS NULL OR rs.end_date >= date()
        WITH d, collect(DISTINCT 'Segretario ' + cs.name) AS v1_secretary_roles
        // committee offices: MEMBER_OF_COMMITTEE.officerRole (role only as fallback)
        OPTIONAL MATCH (d)-[rsm:MEMBER_OF_COMMITTEE]->(csm:Committee)
        WHERE (rsm.officerRole = 'SEGRETARIO' OR (rsm.officerRole IS NULL AND rsm.role = 'secretary'))
          AND (coalesce(rsm.officerRoleEnd, rsm.end_date) IS NULL OR coalesce(rsm.officerRoleEnd, rsm.end_date) >= date())
        WITH v1_secretary_roles, collect(DISTINCT 'Segretario ' + csm.name) AS v2_secretary_roles
        RETURN v1_secretary_roles + v2_secretary_roles AS secretary_roles
    }
    WITH d, current_committee, president_roles + vice_roles + secretary_roles AS all_roles

    RETURN d.id AS id,
           d.first_name AS first_name,
           d.last_name AS last_name,
           d.profession AS profession,
           d.education AS education,
           d.deputy_card AS camera_profile_url,
           d.photo AS photo,
           current_committee,
           CASE WHEN size(all_roles) > 0 THEN all_roles[0] ELSE null END AS institutional_role
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


async def _patch_experts_for_cited_speakers(
    experts: List[Dict[str, Any]],
    gen_citations: List[Dict[str, Any]],
    evidence_dicts: List[Dict[str, Any]],
    authority_scores: Dict[str, float],
    authority_details: Dict[str, Dict[str, Any]],
    neo4j_client,
) -> Optional[List[Dict[str, Any]]]:
    """
    Post-generation expert correction.

    The pre-generation ranking picks the top-authority speaker per party.
    After generation, the writer may have cited a different speaker whose
    evidence produced a stronger verbatim quote.  When that happens, update
    the affected expert entries to show the actually-cited speaker.

    Returns the corrected experts list if any entries changed, else None.
    """
    from ..services.authority.coalition_logic import CoalitionLogic
    from concurrent.futures import ThreadPoolExecutor

    coalition_logic = CoalitionLogic()

    # evidence_id → evidence dict (needs speaker_id)
    eid_to_ev: Dict[str, Dict[str, Any]] = {
        e["evidence_id"]: e
        for e in evidence_dicts
        if e.get("evidence_id") and e.get("speaker_id")
    }

    # First cited speaker per party (from generation result citations)
    party_to_cited: Dict[str, Dict[str, Any]] = {}
    for cit in gen_citations:
        party = cit.get("party", "")
        if not party or party in party_to_cited:
            continue
        ev = eid_to_ev.get(cit.get("evidence_id", ""))
        if ev and ev.get("speaker_id"):
            party_to_cited[party] = ev

    party_to_idx: Dict[str, int] = {e.get("group", ""): i for i, e in enumerate(experts)}

    to_update = []  # (expert_idx, cited_ev)
    for party, cited_ev in party_to_cited.items():
        idx = party_to_idx.get(party)
        if idx is None:
            continue
        if experts[idx].get("id") != cited_ev["speaker_id"]:
            to_update.append((idx, cited_ev))
            logger.info(
                f"[EXPERTS_PATCH] {party}: "
                f"top_ranked={experts[idx].get('last_name')} "
                f"→ cited={cited_ev.get('speaker_name')}"
            )

    if not to_update:
        return None

    # Fetch details for all updated speakers in parallel
    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=min(10, len(to_update))) as pool:
        futures = [
            loop.run_in_executor(pool, _fetch_speaker_details, neo4j_client, cited_ev["speaker_id"])
            for _, cited_ev in to_update
        ]
        speaker_details_list = await asyncio.gather(*futures)

    updated = list(experts)
    for (idx, cited_ev), speaker_info in zip(to_update, speaker_details_list):
        sid = cited_ev["speaker_id"]
        party = cited_ev.get("party", "")
        name_parts = cited_ev.get("speaker_name", "").split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        details = authority_details.get(sid, {})
        components = details.get("components", {})
        coalition = coalition_logic.get_coalition(party)
        relevant_count = sum(1 for e in evidence_dicts if e.get("speaker_id") == sid)

        updated[idx] = {
            "id": sid,
            "first_name": first_name,
            "last_name": last_name,
            "group": party,
            "coalition": coalition,
            "authority_score": round(authority_scores.get(sid, 0.5), 2),
            "relevant_speeches_count": relevant_count,
            "photo": speaker_info.get("photo"),
            "camera_profile_url": speaker_info.get("camera_profile_url"),
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
        }

    return updated


async def _compute_experts_for_frontend(
    evidence_list: List[Any],
    authority_scores: Dict[str, float],
    authority_details: Dict[str, Dict[str, Any]],
    neo4j_client: Neo4jClient
) -> List[Dict[str, Any]]:
    """Compute experts in frontend-expected format with full details."""
    from ..services.authority.coalition_logic import CoalitionLogic
    from concurrent.futures import ThreadPoolExecutor
    coalition_logic = CoalitionLogic()

    party_speakers: Dict[str, Dict[str, Dict]] = {}

    for evidence in evidence_list:
        # GovernmentMember should not be considered as experts
        if evidence.speaker_role == "GovernmentMember":
            continue
        # Use current party if the speaker has changed group (same logic as pipeline.py).
        party = (
            evidence.current_party
            if evidence.party_changed and evidence.current_party
            else evidence.party
        )
        speaker_id = evidence.speaker_id
        speaker_name = evidence.speaker_name

        if party not in party_speakers:
            party_speakers[party] = {}

        if speaker_id not in party_speakers[party]:
            party_speakers[party][speaker_id] = {
                "speaker_name": speaker_name,
                "authority_score": authority_scores.get(speaker_id, 0.5),
                "best_similarity": evidence.similarity if hasattr(evidence, "similarity") else 0.0,
                "count": 0,
                "party": party,
            }
        else:
            # Track best chunk similarity for this speaker (used in ranking formula)
            sim = evidence.similarity if hasattr(evidence, "similarity") else 0.0
            if sim > party_speakers[party][speaker_id]["best_similarity"]:
                party_speakers[party][speaker_id]["best_similarity"] = sim

        party_speakers[party][speaker_id]["count"] += 1

    # Collect top speakers per party using the same formula as _group_evidence_by_party:
    # 0.70 * authority + 0.30 * best_chunk_similarity → survey shows the cited speaker.
    top_speakers_info = []
    for party, speakers in party_speakers.items():
        if speakers:
            def _combined_score(s, _speakers=speakers):
                return 0.70 * _speakers[s]["authority_score"] + 0.30 * _speakers[s]["best_similarity"]
            top_speaker_id = max(speakers.keys(), key=_combined_score)
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
            # Additional details for frontend
            "photo": speaker_info.get("photo"),
            "camera_profile_url": speaker_info.get("camera_profile_url"),
            "profession": speaker_info.get("profession"),
            "education": speaker_info.get("education"),
            "committee": speaker_info.get("current_committee"),
            "institutional_role": details.get("institutional_role") or speaker_info.get("institutional_role"),
            # Score breakdown
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


def _build_citations_for_frontend(
    evidence_dicts: List[Dict[str, Any]],
    neo4j_client: Neo4jClient = None,
) -> List[Dict[str, Any]]:
    """
    Build citations in frontend-expected format.

    Frontend expects: deputy_first_name, deputy_last_name, text, group, coalition, date
    Uses evidence_id as chunk_id so links in generated text match the sidebar.
    """
    from ..services.authority.coalition_logic import CoalitionLogic
    coalition_logic = CoalitionLogic()
    citations = []

    if evidence_dicts:
        sample = evidence_dicts[0]
        logger.debug(f"[CITATIONS_DEBUG] evidence_dicts[0] keys: {list(sample.keys())}")
        logger.debug(f"[CITATIONS_DEBUG] speaker_name={sample.get('speaker_name')}, "
                    f"party={sample.get('party')}, coalition={sample.get('coalition')}")

    deputy_card_map: Dict[str, str] = {}
    gov_role_map: Dict[str, str] = {}
    if neo4j_client:
        speaker_ids = [e.get("speaker_id", "") for e in evidence_dicts[:20] if e.get("speaker_id")]
        deputy_card_map = _batch_fetch_deputy_cards(neo4j_client, speaker_ids)
        # Look up government roles for every speaker, not just GovernmentMembers:
        # deputies may also hold government office (e.g. ministers who are MPs).
        gov_role_map = _batch_fetch_gov_roles(neo4j_client, speaker_ids)

    for i, e in enumerate(evidence_dicts[:20]):  # Limit for UI
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

        cit_data: Dict[str, Any] = {
            "chunk_id": evidence_id,  # For linking
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
            "camera_profile_url": deputy_card_map.get(speaker_id),
        }
        # Group-change transparency: always show when the deputy switched party.
        if e.get("party_changed") and e.get("current_party"):
            cit_data["party_changed"] = True
            cit_data["current_party"] = e["current_party"]
        # Gruppo Misto component at the speech date: without it the frontend
        # would attribute positions of opposing components (+Europa vs Futuro
        # Nazionale Vannacci) to the monolithic "Misto".
        if e.get("misto_component"):
            cit_data["misto_component"] = e["misto_component"]
        if is_government:
            role = gov_role_map.get(speaker_id)
            if not role and neo4j_client:
                # Fallback: fetch role directly for GovernmentMember not in batch
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


def _compute_balance_metrics(
    evidence_dicts: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Compute balance metrics in frontend-expected format."""
    from ..services.authority.coalition_logic import CoalitionLogic
    coalition_logic = CoalitionLogic()

    maggioranza_count = 0
    opposizione_count = 0

    for e in evidence_dicts:
        party = e.get("party", "MISTO")
        coalition = coalition_logic.get_coalition(party)
        if coalition == "maggioranza":
            maggioranza_count += 1
        elif coalition == "misto":
            # The Gruppo Misto cannot be assigned to either side (it holds
            # opposing components): excluded from the binary balance.
            continue
        else:
            opposizione_count += 1

    total = maggioranza_count + opposizione_count
    if total == 0:
        total = 1

    magg_pct = (maggioranza_count / total) * 100
    opp_pct = (opposizione_count / total) * 100

    # Bias score: 0 = perfectly balanced, higher = more biased
    bias_score = abs(magg_pct - 50) / 50

    return {
        "maggioranza_percentage": round(magg_pct, 1),
        "opposizione_percentage": round(opp_pct, 1),
        "bias_score": round(bias_score, 2),
    }


def _compute_compass_data(
    ideology_scorer: IdeologyScorer,
    evidence_dicts: List[Dict[str, Any]],
    query: str = "",
) -> Dict[str, Any]:
    """Compute compass data in the frontend-expected format.

    2D positions come from the semantic content of the evidence texts
    (see IdeologyScorer.compute_2d_text_positions), not from party membership.
    Returns the meta/axes/groups/scatter_sample structure the compass UI reads.
    """
    compass_result = ideology_scorer.compute_2d_text_positions(evidence_dicts, query=query)

    return {
        "meta": compass_result.get("meta", {}),
        "axes": compass_result.get("axes", {}),
        "groups": compass_result.get("groups", []),
        "scatter_sample": compass_result.get("scatter_sample", []),
    }


def _build_verified_citations(
    generation_citations: List[Dict],
    evidence_dicts: List[Dict],
    neo4j_client: Neo4jClient = None,
) -> List[Dict[str, Any]]:
    """
    Build verified citations with full details.

    Uses evidence_id as chunk_id for consistent linking.
    Frontend expects: deputy_first_name, deputy_last_name, text, coalition, etc.
    """
    from ..services.authority.coalition_logic import CoalitionLogic
    coalition_logic = CoalitionLogic()
    evidence_map = {e.get("evidence_id"): e for e in evidence_dicts}

    deputy_card_map: Dict[str, str] = {}
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
        # Check ALL speakers for government roles (Deputies who are also ministers)
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

        cit_data = {
            "chunk_id": eid,  # For linking
            "deputy_first_name": first_name,
            "deputy_last_name": last_name,
            "text": cit.get("quote_text", ""),
            "quote_text": cit.get("quote_text", ""),
            "full_text": evidence.get("chunk_text", ""),
            "group": group,
            "coalition": coalition,
            "date": str(cit.get("date", "")),
            "span_start": cit.get("span_start", 0),
            "span_end": cit.get("span_end", 0),
            "debate": evidence.get("debate_title", ""),
            "intervention_id": evidence.get("speech_id", ""),
            "camera_profile_url": deputy_card_map.get(speaker_id),
            "verified": True,
        }
        # Group-change transparency: read from evidence (already populated by _process_results).
        party_changed = evidence.get("party_changed") or cit.get("party_changed", False)
        current_party = evidence.get("current_party") or cit.get("current_party")
        if party_changed and current_party:
            cit_data["party_changed"] = True
            cit_data["current_party"] = current_party
        if evidence.get("misto_component"):
            cit_data["misto_component"] = evidence["misto_component"]
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


@router.post("/chat")
async def chat_endpoint(request: ChatRequest, http_request: Request):
    """
    Main chat endpoint with SSE streaming.

    Uses a background task so the pipeline continues even if the client
    disconnects (e.g. mobile browser going to background).
    The client can poll GET /api/chat/task/{task_id} to recover results.
    """
    accept_lang = http_request.headers.get("accept-language", "it")
    from ..services.translation import LANG_NAMES
    _code = accept_lang.strip()[:2].lower()
    request.locale = _code if _code in LANG_NAMES else "it"
    logger.info(f"[CHAT] Accept-Language: {accept_lang!r}, resolved locale: {request.locale}")

    store = get_task_store()

    await store.cleanup_expired()

    task_id = request.task_id or store.generate_task_id()

    def _task_stream_response() -> StreamingResponse:
        async def stream_with_task_id():
            # Send task_id as the first event so the client can use it for reconnection
            yield sse_event("task_id", {"task_id": task_id})
            async for chunk in stream_from_task(task_id):
                yield chunk

        return StreamingResponse(
            stream_with_task_id(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            }
        )

    # Response cache + in-flight dedup: the lookup happens BEFORE task
    # creation and queue entry, so a hit never occupies a pipeline slot and
    # never shows the queue screen. A POST is always a new request — the
    # client-provided task_id only names the task (reconnection goes through
    # GET /api/chat/task/{id}).
    cache = get_response_cache()
    if cache.enabled:
        data_version = await get_data_version()
        if data_version:
            cache_key = build_cache_key(
                query=request.query,
                locale=request.locale,
                mode=request.mode,
                data_version=data_version,
                config_fingerprint=config_fingerprint(get_config().load_config()),
            )

            cached_events = await cache.lookup(cache_key)
            if cached_events is not None:
                await store.create_task(task_id)
                asyncio.create_task(replay_into_task(task_id, cached_events))
                return _task_stream_response()

            leader_id = await get_inflight_registry().claim(cache_key, task_id)
            if leader_id is not None:
                await store.create_task(task_id)
                asyncio.create_task(
                    mirror_task(task_id, leader_id, locale=request.locale)
                )
                return _task_stream_response()

            # Leader for this key: run the pipeline and store on success
            await store.create_task(task_id)
            asyncio.create_task(process_chat_background(request, task_id, cache_key=cache_key))
            return _task_stream_response()

    await store.create_task(task_id)

    # Launch pipeline in background (runs independently of this response)
    asyncio.create_task(process_chat_background(request, task_id))

    return _task_stream_response()


@router.get("/chat/task/{task_id}")
async def get_task_status(task_id: str):
    """
    Poll endpoint for recovering task results after SSE disconnection.

    Returns the task status and all accumulated events.
    Used by the frontend when the user returns to the page after
    the mobile browser killed the SSE connection.
    """
    store = get_task_store()
    task = await store.get_task(task_id)

    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    return JSONResponse({
        "task_id": task.task_id,
        "status": task.status,
        "events": task.events,
        "error_message": task.error_message,
    })


@router.delete("/chat/task/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a running pipeline task.

    Marks the task as cancelled; the background pipeline checks this flag
    between pipeline steps and stops early, releasing the semaphore slot.
    """
    store = get_task_store()
    task = await store.get_task(task_id)

    if not task:
        # Task may have already finished — not an error, just a no-op
        return JSONResponse({"cancelled": False, "reason": "task_not_found"})

    if task.status in ("completed", "error", "cancelled"):
        return JSONResponse({"cancelled": False, "reason": task.status})

    await store.cancel_task(task_id)
    logger.info(f"[CANCEL] Task {task_id} cancellation requested via API")
    return JSONResponse({"cancelled": True})
