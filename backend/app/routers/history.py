"""
History endpoint for chat conversation history.

Stores complete chat sessions in Neo4j for persistence across deploys.
"""
import json
import logging
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from uuid import uuid4
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..services.neo4j_client import get_neo4j_client
from ..services.retention import require_storage_open

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["History"])


def _strip_markdown(text: str) -> str:
    """Remove markdown formatting for clean preview text."""
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
    text = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'\[CIT:[^\]]+\]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class ChatHistoryItem(BaseModel):
    """A stored chat session with full response data."""
    id: str = Field(default_factory=lambda: str(uuid4()))
    query: str
    answer: str
    preview: str = ""
    timestamp: datetime = Field(default_factory=lambda: datetime.now(tz=ZoneInfo("Europe/Rome")))

    citations: List[Dict[str, Any]] = []
    experts: List[Dict[str, Any]] = []
    commissioni: List[Dict[str, Any]] = []
    balance: Optional[Dict[str, Any]] = None
    compass: Optional[Dict[str, Any]] = None

    topic_stats: Optional[Dict[str, Any]] = None
    trace: Optional[Dict[str, Any]] = None  # pipeline trace: per-stage durations/counters

    # A/B Baseline comparison fields (optional for backwards compatibility)
    baseline_answer: Optional[str] = None
    ab_assignment: Optional[Dict[str, str]] = None  # e.g. {"A": "system", "B": "baseline"}


class HistoryListResponse(BaseModel):
    """Response for history list endpoint."""
    history: List[Dict[str, Any]] = []


def _get_client():
    try:
        return get_neo4j_client()
    except RuntimeError:
        # Global client not initialized yet - create and register it
        from ..config import get_settings
        from ..services.neo4j_client import init_neo4j_client
        settings = get_settings()
        return init_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )


def ensure_constraint():
    """Create uniqueness constraint on ChatHistory.id if not exists."""
    try:
        _get_client().query(
            "CREATE CONSTRAINT chat_history_id IF NOT EXISTS FOR (c:ChatHistory) REQUIRE c.id IS UNIQUE"
        )
    except Exception as e:
        logger.debug(f"Constraint already exists or error: {e}")


@router.get("/history")
async def get_history() -> HistoryListResponse:
    """Get chat history list for sidebar display."""
    client = _get_client()
    results = client.query("""
        MATCH (c:ChatHistory)
        RETURN c.id AS id, c.query AS query, c.preview AS preview,
               c.timestamp AS timestamp
        ORDER BY c.timestamp DESC
        LIMIT 50
    """)

    history_list = []
    for r in results:
        history_list.append({
            "id": r["id"],
            "query": r["query"],
            "preview": r.get("preview", ""),
            "timestamp": r["timestamp"],
        })
    return HistoryListResponse(history=history_list)


@router.post("/history", dependencies=[Depends(require_storage_open)])
async def save_chat(chat: ChatHistoryItem) -> ChatHistoryItem:
    """Save a chat session to history."""
    # The id is the only access control on GET /history/{id}: always a fresh
    # server-side UUID4, never one chosen by the client
    chat.id = str(uuid4())
    try:
        clean_text = _strip_markdown(chat.answer)
        chat.preview = clean_text[:100] + "..." if len(clean_text) > 100 else clean_text

        client = _get_client()

        # Serialize with size limits to avoid Neo4j property size issues
        citations_json = json.dumps(chat.citations, ensure_ascii=False, default=str)
        experts_json = json.dumps(chat.experts, ensure_ascii=False, default=str)
        commissioni_json = json.dumps(chat.commissioni, ensure_ascii=False, default=str)
        balance_json = json.dumps(chat.balance, ensure_ascii=False, default=str) if chat.balance else ""
        compass_json = json.dumps(chat.compass, ensure_ascii=False, default=str) if chat.compass else ""
        topic_stats_json = json.dumps(chat.topic_stats, ensure_ascii=False, default=str) if chat.topic_stats else ""
        trace_json = json.dumps(chat.trace, ensure_ascii=False, default=str) if chat.trace else ""
        ab_assignment_json = json.dumps(chat.ab_assignment, ensure_ascii=False) if chat.ab_assignment else ""

        baseline_value = (chat.baseline_answer or "")[:50000]

        client.query("""
            CREATE (c:ChatHistory {
                id: $id,
                query: $query,
                answer: $answer,
                preview: $preview,
                timestamp: $timestamp,
                citations: $citations,
                experts: $experts,
                commissioni: $commissioni,
                balance: $balance,
                compass: $compass,
                topic_stats: $topic_stats,
                trace: $trace,
                baseline_answer: $baseline_answer,
                ab_assignment: $ab_assignment
            })
        """, {
            "id": chat.id,
            "query": chat.query,
            "answer": chat.answer[:50000],  # Limit answer size
            "preview": chat.preview,
            "timestamp": chat.timestamp.isoformat(),
            "citations": citations_json,
            "experts": experts_json,
            "commissioni": commissioni_json,
            "balance": balance_json,
            "compass": compass_json,
            "topic_stats": topic_stats_json,
            "trace": trace_json,
            "baseline_answer": baseline_value,
            "ab_assignment": ab_assignment_json,
        })

        # Keep only last 50 chats — skip chats that have associated survey evaluations
        client.query("""
            MATCH (c:ChatHistory)
            WHERE NOT EXISTS { MATCH (s:SurveyEvaluation {chat_id: c.id}) }
              AND NOT EXISTS { MATCH (r:SimpleRating {chat_id: c.id}) }
            WITH c ORDER BY c.timestamp DESC
            SKIP 50
            DELETE c
        """)

        logger.info(f"[HISTORY-SAVE] Saved chat to history: {chat.id}, query: {chat.query[:50]}...")
        return chat
    except Exception as e:
        logger.error(f"Failed to save chat to history: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save chat: {str(e)}")


@router.get("/history/{chat_id}")
async def get_chat(chat_id: str) -> Dict[str, Any]:
    """Get a specific chat session by ID."""
    client = _get_client()
    result = client.query("""
        MATCH (c:ChatHistory {id: $id})
        RETURN c.id AS id, c.query AS query, c.answer AS answer,
               c.timestamp AS timestamp, c.citations AS citations,
               c.experts AS experts, c.commissioni AS commissioni,
               c.balance AS balance, c.compass AS compass,
               c.topic_stats AS topic_stats, c.trace AS trace,
               c.baseline_answer AS baseline_answer, c.ab_assignment AS ab_assignment
    """, {"id": chat_id})

    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")

    r = result[0]
    return {
        "id": r["id"],
        "query": r["query"],
        "answer": r["answer"],
        "timestamp": r["timestamp"],
        "citations": json.loads(r["citations"]) if r.get("citations") else [],
        "experts": json.loads(r["experts"]) if r.get("experts") else [],
        "commissioni": json.loads(r["commissioni"]) if r.get("commissioni") else [],
        "balance": json.loads(r["balance"]) if r.get("balance") else None,
        "compass": json.loads(r["compass"]) if r.get("compass") else None,
        "topic_stats": json.loads(r["topic_stats"]) if r.get("topic_stats") else None,
        "trace": json.loads(r["trace"]) if r.get("trace") else None,
        "baseline_answer": r.get("baseline_answer") or None,
        "ab_assignment": json.loads(r["ab_assignment"]) if r.get("ab_assignment") else None,
    }


class BaselineExpertsRequest(BaseModel):
    """Request body for baseline-experts endpoint."""
    baseline_text: Optional[str] = None


def _match_deputies_in_text(baseline_text: str, deputies_result: List[Dict]) -> List[Dict]:
    """
    Match deputies mentioned in a text. Returns list of matched deputy dicts.
    Tries full name match first, then last-name-only word boundary match with group disambiguation.
    """
    text_lower = baseline_text.lower()
    matched_deputies = []
    matched_ids_set: set = set()

    for dep in deputies_result:
        fn = (dep.get("first_name") or "").strip()
        ln = (dep.get("last_name") or "").strip()
        if not fn or not ln:
            continue
        if f"{fn} {ln}".lower() in text_lower or f"{ln} {fn}".lower() in text_lower:
            matched_deputies.append(dep)
            matched_ids_set.add(dep["id"])

    def _group_name_in_context(group_name: str, context: str) -> bool:
        _skip = {"della", "delle", "degli", "del", "dei", "the", "per", "con", "and"}
        tokens = [t for t in re.split(r'[\s\-–/|]+', group_name.lower()) if len(t) >= 4 and t not in _skip]
        if not tokens:
            return False
        found = sum(1 for t in tokens if t in context)
        return found >= max(1, len(tokens) // 2)

    ln_to_candidates: dict = {}
    for dep in deputies_result:
        if dep["id"] in matched_ids_set:
            continue
        ln = (dep.get("last_name") or "").strip()
        if not ln:
            continue
        ln_to_candidates.setdefault(ln.lower(), []).append(dep)

    for ln_lower, candidates in ln_to_candidates.items():
        if not re.search(r'\b' + re.escape(ln_lower) + r'\b', text_lower):
            continue
        if len(candidates) == 1:
            dep = candidates[0]
            matched_deputies.append(dep)
            matched_ids_set.add(dep["id"])
        else:
            for match in re.finditer(r'\b' + re.escape(ln_lower) + r'\b', text_lower):
                start = max(0, match.start() - 80)
                end = min(len(text_lower), match.end() + 200)
                context_window = text_lower[start:end]
                for dep in candidates:
                    if dep["id"] in matched_ids_set:
                        continue
                    group_name = (dep.get("group_name") or "").strip()
                    if group_name and _group_name_in_context(group_name, context_window):
                        matched_deputies.append(dep)
                        matched_ids_set.add(dep["id"])

    return matched_deputies


async def _compute_experts_from_matched(
    query_text: str,
    matched_deputies: List[Dict],
    client: Any,
    authority_cache: Optional[Dict[str, Dict]] = None,
) -> List[Dict]:
    """
    Compute authority scores for a list of pre-matched deputies and return expert dicts.

    authority_cache: optional {speaker_id: expert_dict} from a previously computed
    run (e.g. stored in the chat's experts field). When provided, skips the heavy
    Neo4j authority computation for speakers already in the cache.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from .query import get_services
    from ..services.authority.coalition_logic import CoalitionLogic
    from ..models.evidence import normalize_party_name

    if not matched_deputies:
        return []

    matched_ids = [d["id"] for d in matched_deputies]
    cache = authority_cache or {}

    # Only run full authority computation for speakers NOT already in the cache.
    ids_to_compute = [sid for sid in matched_ids if sid not in cache]

    services = get_services()
    authority_scores: Dict[str, float] = {}
    authority_details: Dict[str, Dict] = {}

    if ids_to_compute:
        query_embedding = await asyncio.get_running_loop().run_in_executor(
            None, lambda: services["retrieval"].embed_query(query_text)
        )

        def _compute_single(sid):
            return sid, services["authority"].compute_authority(sid, query_embedding)

        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=min(10, max(1, len(ids_to_compute)))) as pool:
            futures = [loop.run_in_executor(pool, _compute_single, sid) for sid in ids_to_compute]
            auth_results = await asyncio.gather(*futures)

        for sid, res in auth_results:
            authority_scores[sid] = res["total_score"]
            authority_details[sid] = res

    # Populate scores for cached speakers (avoids full Neo4j authority recomputation)
    for sid, cached in cache.items():
        if sid not in authority_scores:
            authority_scores[sid] = cached.get("authority_score", 0.0)
            # Reconstruct authority_details-compatible dict from stored score_breakdown
            sb = cached.get("score_breakdown", {})
            authority_details[sid] = {
                "total_score": cached.get("authority_score", 0.0),
                "institutional_role": cached.get("institutional_role"),
                "components": {
                    "interventions": sb.get("speeches", 0),
                    "acts": sb.get("acts", 0),
                    "committee": sb.get("committee", 0),
                    "profession": sb.get("profession", 0),
                    "education": sb.get("education", 0),
                },
            }

    # For speakers served from cache, committee info is already stored — skip Neo4j
    # for those and only query for speakers that needed fresh computation.
    committees_map: Dict[str, Dict] = {}
    if ids_to_compute:
        committees_result = client.query("""
            UNWIND $ids AS sid
            MATCH (d:Deputy {id: sid})
            OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
            WHERE mc.end_date IS NULL OR mc.end_date >= date()
            RETURN sid, collect(c.name)[0] AS current_committee,
                   d.institutional_role AS institutional_role
        """, {"ids": ids_to_compute})
        committees_map = {r["sid"]: r for r in committees_result}

    dep_map = {d["id"]: d for d in matched_deputies}
    coalition_logic = CoalitionLogic()
    experts = []

    for dep_id in matched_ids:
        dep = dep_map.get(dep_id)
        if not dep:
            continue
        auth = authority_details.get(dep_id, {})
        components = auth.get("components", {})
        committee_info = committees_map.get(dep_id, {})
        # For cached speakers, use stored committee/role info
        cached_expert = cache.get(dep_id, {})
        coalition = coalition_logic.get_coalition(dep.get("group_name", ""))
        experts.append({
            "id": dep_id,
            "first_name": (dep.get("first_name") or "").title(),
            "last_name": (dep.get("last_name") or "").title(),
            "group": normalize_party_name(dep.get("group_name", "")),
            "coalition": coalition,
            "authority_score": round(authority_scores.get(dep_id, 0.0), 2),
            "relevant_speeches_count": 0,
            "photo": dep.get("photo"),
            "camera_profile_url": dep.get("camera_profile_url"),
            "profession": dep.get("profession"),
            "education": dep.get("education"),
            "committee": committee_info.get("current_committee") or cached_expert.get("committee"),
            "institutional_role": (
                auth.get("institutional_role")
                or committee_info.get("institutional_role")
                or cached_expert.get("institutional_role")
            ),
            "score_breakdown": {
                "speeches": round(components.get("interventions", 0), 2),
                "acts": round(components.get("acts", 0), 2),
                "committee": round(components.get("committee", 0), 2),
                "profession": round(components.get("profession", 0), 2),
                "education": round(components.get("education", 0), 2),
                "role": round(components.get("role", 0), 2),
            },
        })

    experts.sort(key=lambda e: e["authority_score"], reverse=True)
    return experts


@router.post("/history/{chat_id}/baseline-experts")
async def get_baseline_experts(chat_id: str, body: BaselineExpertsRequest) -> Dict[str, Any]:
    """
    Extract deputies mentioned in the baseline text and compute their authority scores.
    The baseline text is passed in the request body (from evaluation_set.json on the client).
    If pre-computed experts are already cached in evaluation_set.json, this endpoint is
    no longer called by the frontend.
    """
    client = _get_client()

    result = client.query("""
        MATCH (c:ChatHistory {id: $id})
        RETURN c.query AS query, c.baseline_answer AS baseline_answer, c.experts AS experts_json
    """, {"id": chat_id})

    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")

    chat_data = result[0]
    query_text = chat_data.get("query") or ""
    baseline_text = body.baseline_text or chat_data.get("baseline_answer") or ""

    if not baseline_text:
        return {"experts": []}

    # Build authority cache from already-computed experts stored in this chat.
    # This avoids re-running heavy Neo4j authority queries for speakers whose
    # scores were already computed during the main pipeline execution.
    authority_cache: Dict[str, Dict] = {}
    experts_json_raw = chat_data.get("experts_json")
    if experts_json_raw:
        try:
            stored = json.loads(experts_json_raw) if isinstance(experts_json_raw, str) else experts_json_raw
            authority_cache = {e["id"]: e for e in stored if e.get("id")}
            logger.info(f"[BASELINE-EXPERTS] Authority cache loaded: {len(authority_cache)} speakers from chat experts")
        except Exception:
            pass

    deputies_result = client.query("""
        MATCH (d:Deputy)
        WHERE d.first_name IS NOT NULL AND d.last_name IS NOT NULL
        OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        WHERE mg.end_date IS NULL
        WITH d, collect(g.name)[0] AS group_name
        RETURN d.id AS id, d.first_name AS first_name, d.last_name AS last_name,
               coalesce(group_name, 'MISTO') AS group_name,
               d.deputy_card AS camera_profile_url,
               d.photo AS photo,
               d.profession AS profession, d.education AS education
    """)

    matched = _match_deputies_in_text(baseline_text, deputies_result)
    cached_count = sum(1 for m in matched if m["id"] in authority_cache)
    logger.info(
        f"[BASELINE-EXPERTS] Matched {len(matched)}/{len(deputies_result)} deputies "
        f"({cached_count} from cache, {len(matched) - cached_count} need computation)"
    )
    if not matched:
        return {"experts": []}

    experts = await _compute_experts_from_matched(query_text, matched, client, authority_cache)
    return {"experts": experts}


@router.delete("/history/{chat_id}")
async def delete_chat(chat_id: str) -> Dict[str, Any]:
    """Delete a chat from history and its associated survey/rating."""
    client = _get_client()
    # Delete associated A/B survey and simple rating if any
    client.query("""
        MATCH (s:SurveyEvaluation {chat_id: $id})
        DELETE s
    """, {"id": chat_id})
    client.query("""
        MATCH (r:SimpleRating {chat_id: $id})
        DELETE r
    """, {"id": chat_id})
    result = client.query("""
        MATCH (c:ChatHistory {id: $id})
        DELETE c
        RETURN count(*) AS deleted
    """, {"id": chat_id})

    if not result or result[0]["deleted"] == 0:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {"deleted": True, "id": chat_id}


@router.delete("/history")
async def clear_history() -> Dict[str, Any]:
    """Clear all chat history and associated surveys/ratings."""
    client = _get_client()
    # Delete all A/B surveys and simple ratings first
    client.query("MATCH (s:SurveyEvaluation) DELETE s")
    client.query("MATCH (r:SimpleRating) DELETE r")
    result = client.query("""
        MATCH (c:ChatHistory)
        WITH c, count(*) AS total
        DELETE c
        RETURN total
    """)
    count = result[0]["total"] if result else 0
    return {"cleared": True, "count": count}
