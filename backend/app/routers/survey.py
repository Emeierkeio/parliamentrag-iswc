"""
Survey router for A/B blind evaluations of ParliamentRAG vs Baseline RAG,
and simple Likert-scale evaluation for queries without a predefined baseline.
"""

import json
import logging
import os
from typing import List, Optional, Dict
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query

from app.models.survey import (
    SurveyResponse,
    SurveyResponseCreate,
    SurveyWithChat,
    SurveyStats,
    SurveyListResponse,
    SURVEY_QUESTIONS,
    AB_DIMENSIONS,
    OPTIONAL_AB_DIMS,
    SimpleRatingResponse,
    SimpleRatingCreate,
)
from app.services.retention import require_storage_open

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/surveys", tags=["surveys"])

# Path to evaluation_set.json (backend root)
_EVAL_SET_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "evaluation_set.json")


def _get_client():
    """Get Neo4j client, reusing history router's pattern."""
    from ..services.neo4j_client import get_neo4j_client
    try:
        return get_neo4j_client()
    except RuntimeError:
        from ..config import get_settings
        from ..services.neo4j_client import init_neo4j_client
        settings = get_settings()
        return init_neo4j_client(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )


def ensure_survey_constraint():
    """Drop old per-chat uniqueness constraints (now multi-evaluator: uniqueness is (chat_id, evaluator_id) enforced in code)."""
    client = _get_client()
    for label in ["SurveyEvaluation", "SimpleRating"]:
        try:
            client.query(f"DROP CONSTRAINT {label.lower()}_chat_id IF EXISTS")
        except Exception as e:
            logger.debug(f"Could not drop constraint {label}.chat_id: {e}")


def _load_evaluation_set_raw() -> dict:
    """Load raw evaluation_set.json (values may be str or dict)."""
    try:
        path = os.path.normpath(_EVAL_SET_PATH)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning(f"evaluation_set.json not found at {_EVAL_SET_PATH}")
        return {}
    except Exception as e:
        logger.error(f"Failed to load evaluation_set.json: {e}")
        return {}


def _load_evaluation_set() -> Dict[str, str]:
    """Load topic → baseline_text mapping (handles both old str and new dict values)."""
    raw = _load_evaluation_set_raw()
    result: Dict[str, str] = {}
    for topic, value in raw.items():
        if isinstance(value, dict):
            result[topic] = value.get("baseline_answer", "")
        else:
            result[topic] = value
    return result


def _load_evaluation_set_full() -> Dict[str, dict]:
    """Load topic → {baseline_answer, baseline_experts} (normalises old str entries)."""
    raw = _load_evaluation_set_raw()
    result: Dict[str, dict] = {}
    for topic, value in raw.items():
        if isinstance(value, dict):
            result[topic] = value
        else:
            result[topic] = {"baseline_answer": value, "baseline_experts": []}
    return result


def _survey_to_neo4j_params(survey: SurveyResponse) -> dict:
    """Convert a SurveyResponse to Neo4j node properties."""
    params = {
        "id": survey.id,
        "chat_id": survey.chat_id,
        "timestamp": survey.timestamp.isoformat() if isinstance(survey.timestamp, datetime) else str(survey.timestamp),
        "overall_satisfaction_a": survey.overall_satisfaction_a,
        "overall_satisfaction_b": survey.overall_satisfaction_b,
        "overall_preference": survey.overall_preference,
        "would_recommend": survey.would_recommend,
        "feedback_positive": survey.feedback_positive or "",
        "feedback_improvement": survey.feedback_improvement or "",
        "evaluator_role": survey.evaluator_role or "",
        "evaluation_context": survey.evaluation_context or "",
        "evaluator_id": survey.evaluator_id or "",
        "ab_assignment": json.dumps(survey.ab_assignment, ensure_ascii=False) if survey.ab_assignment else "",
        "baseline_authority_avg": survey.baseline_authority_avg if survey.baseline_authority_avg is not None else -1.0,
        "group_authority_votes": json.dumps(survey.group_authority_votes, ensure_ascii=False) if survey.group_authority_votes else "",
    }
    # Serialize each A/B dimension as JSON string
    for dim in AB_DIMENSIONS:
        dim_data = getattr(survey, dim, None)
        if dim_data:
            params[dim] = json.dumps(dim_data.model_dump(), ensure_ascii=False)
        else:
            params[dim] = ""
    # Serialize individual citation evaluations as JSON strings
    params["citation_evaluations_a"] = json.dumps(
        [ce.model_dump() for ce in survey.citation_evaluations_a], ensure_ascii=False
    )
    params["citation_evaluations_b"] = json.dumps(
        [ce.model_dump() for ce in survey.citation_evaluations_b], ensure_ascii=False
    )
    return params


def _neo4j_record_to_dict(r: dict) -> dict:
    """Convert a Neo4j SurveyEvaluation record to a plain dict compatible with SurveyResponse."""
    result = {
        "id": r["id"],
        "chat_id": r["chat_id"],
        "timestamp": r.get("timestamp", ""),
        "overall_satisfaction_a": r.get("overall_satisfaction_a", 0),
        "overall_satisfaction_b": r.get("overall_satisfaction_b", 0),
        "overall_preference": r.get("overall_preference", "equal"),
        "would_recommend": r.get("would_recommend", False),
        "feedback_positive": r.get("feedback_positive") or None,
        "feedback_improvement": r.get("feedback_improvement") or None,
        "evaluator_role": r.get("evaluator_role") or None,
        "evaluation_context": r.get("evaluation_context") or None,
        "evaluator_id": r.get("evaluator_id") or None,
        "ab_assignment": json.loads(r["ab_assignment"]) if r.get("ab_assignment") else None,
        "baseline_authority_avg": r.get("baseline_authority_avg") if r.get("baseline_authority_avg") and r.get("baseline_authority_avg") >= 0 else None,
        "group_authority_votes": json.loads(r["group_authority_votes"]) if r.get("group_authority_votes") else None,
    }
    # Deserialize A/B dimensions from JSON strings
    # Optional dims (source_relevance/authority/coverage) return None if absent in legacy records
    for dim in AB_DIMENSIONS:
        raw = r.get(dim)
        if raw:
            try:
                result[dim] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result[dim] = None if dim in OPTIONAL_AB_DIMS else {"rating_a": 0, "rating_b": 0, "preference": "equal"}
        else:
            result[dim] = None if dim in OPTIONAL_AB_DIMS else {"rating_a": 0, "rating_b": 0, "preference": "equal"}
    # Deserialize individual citation evaluations
    for field in ("citation_evaluations_a", "citation_evaluations_b"):
        raw = r.get(field)
        if raw:
            try:
                result[field] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                result[field] = []
        else:
            result[field] = []
    return result


# Field list shared by all SurveyEvaluation Cypher queries.
_SURVEY_FIELDS = (
    "s.id AS id, s.chat_id AS chat_id, s.timestamp AS timestamp, "
    "s.overall_satisfaction_a AS overall_satisfaction_a, "
    "s.overall_satisfaction_b AS overall_satisfaction_b, "
    "s.overall_preference AS overall_preference, "
    "s.would_recommend AS would_recommend, "
    "s.feedback_positive AS feedback_positive, "
    "s.feedback_improvement AS feedback_improvement, "
    "s.evaluator_role AS evaluator_role, "
    "s.evaluation_context AS evaluation_context, "
    "s.evaluator_id AS evaluator_id, "
    "s.ab_assignment AS ab_assignment, "
    "s.baseline_authority_avg AS baseline_authority_avg, "
    "s.group_authority_votes AS group_authority_votes, "
    "s.citation_evaluations_a AS citation_evaluations_a, "
    "s.citation_evaluations_b AS citation_evaluations_b, "
    + ", ".join(f"s.{d} AS {d}" for d in AB_DIMENSIONS)
)


def _load_surveys() -> List[dict]:
    """Load all A/B surveys from Neo4j. Returns list of dicts compatible with SurveyResponse."""
    client = _get_client()
    results = client.query(f"""
        MATCH (s:SurveyEvaluation)
        RETURN {_SURVEY_FIELDS}
        ORDER BY s.timestamp DESC
    """)
    return [_neo4j_record_to_dict(r) for r in results]


def _get_chat_by_id(chat_id: str) -> Optional[dict]:
    """Get a specific chat by ID from Neo4j."""
    client = _get_client()
    result = client.query("""
        MATCH (c:ChatHistory {id: $id})
        RETURN c.id AS id, c.query AS query, c.answer AS answer,
               c.timestamp AS timestamp, c.ab_assignment AS ab_assignment
    """, {"id": chat_id})
    return result[0] if result else None


def _get_ab_assignment(chat_id: str) -> Optional[Dict[str, str]]:
    """Get the A/B assignment for a chat to de-blind results."""
    chat = _get_chat_by_id(chat_id)
    if not chat or not chat.get("ab_assignment"):
        return None
    ab = chat["ab_assignment"]
    if isinstance(ab, str):
        try:
            return json.loads(ab)
        except (json.JSONDecodeError, TypeError):
            return None
    return ab


def _deblind_preference(preference: str, ab_assignment: Dict[str, str]) -> str:
    """Convert A/B preference to system/baseline/equal."""
    if preference == "equal":
        return "equal"
    mapped = ab_assignment.get(preference)
    return mapped if mapped in ("system", "baseline") else "equal"


def _calculate_stats(surveys: List[dict]) -> SurveyStats:
    """Calculate aggregated A/B statistics with de-blinding."""
    empty_stats = SurveyStats(
        total_surveys=0,
        system_avg_per_dimension={d: 0.0 for d in AB_DIMENSIONS},
        baseline_avg_per_dimension={d: 0.0 for d in AB_DIMENSIONS},
        system_avg_overall=0.0,
        baseline_avg_overall=0.0,
        system_win_rate=0.0,
        baseline_win_rate=0.0,
        tie_rate=0.0,
        per_dimension_preference={d: {"system": 0, "baseline": 0, "equal": 0} for d in AB_DIMENSIONS},
        recommendation_rate=0.0,
    )

    if not surveys:
        return empty_stats

    # Collect de-blinded ratings
    system_ratings: Dict[str, List[float]] = {d: [] for d in AB_DIMENSIONS}
    baseline_ratings: Dict[str, List[float]] = {d: [] for d in AB_DIMENSIONS}
    system_overall: List[float] = []
    baseline_overall: List[float] = []
    per_dim_pref: Dict[str, Dict[str, int]] = {
        d: {"system": 0, "baseline": 0, "equal": 0} for d in AB_DIMENSIONS
    }
    overall_pref = {"system": 0, "baseline": 0, "equal": 0}
    valid_count = 0

    for s in surveys:
        # Prefer per-evaluator ab_assignment stored on SurveyEvaluation; fall back to ChatHistory for legacy records
        ab_assignment = s.get("ab_assignment") or _get_ab_assignment(s.get("chat_id", ""))
        if not ab_assignment:
            continue

        valid_count += 1
        is_a_system = ab_assignment.get("A") == "system"

        for dim in AB_DIMENSIONS:
            dim_data = s.get(dim, {})
            if isinstance(dim_data, dict):
                rating_a = dim_data.get("rating_a", 0)
                rating_b = dim_data.get("rating_b", 0)
                pref = dim_data.get("preference", "equal")

                if is_a_system:
                    system_ratings[dim].append(rating_a)
                    baseline_ratings[dim].append(rating_b)
                else:
                    system_ratings[dim].append(rating_b)
                    baseline_ratings[dim].append(rating_a)

                deblinded_pref = _deblind_preference(pref, ab_assignment)
                per_dim_pref[dim][deblinded_pref] += 1

        # Overall satisfaction
        sat_a = s.get("overall_satisfaction_a", 0)
        sat_b = s.get("overall_satisfaction_b", 0)
        if is_a_system:
            system_overall.append(sat_a)
            baseline_overall.append(sat_b)
        else:
            system_overall.append(sat_b)
            baseline_overall.append(sat_a)

        # Overall preference
        overall_p = _deblind_preference(s.get("overall_preference", "equal"), ab_assignment)
        overall_pref[overall_p] += 1

    # Aggregate per-group authority votes (de-blinded)
    group_auth_pref: Dict[str, Dict[str, int]] = {}
    for s in surveys:
        ab_assign = s.get("ab_assignment") or _get_ab_assignment(s.get("chat_id", ""))
        if not ab_assign:
            continue
        is_a_sys = ab_assign.get("A") == "system"
        votes = s.get("group_authority_votes")
        if not isinstance(votes, dict):
            continue
        for gkey, vote in votes.items():
            if gkey not in group_auth_pref:
                group_auth_pref[gkey] = {"system": 0, "equal": 0, "baseline": 0}
            if vote == 0:
                group_auth_pref[gkey]["equal"] += 1
            elif vote == -1:  # A is better
                group_auth_pref[gkey]["system" if is_a_sys else "baseline"] += 1
            elif vote == 1:   # B is better
                group_auth_pref[gkey]["baseline" if is_a_sys else "system"] += 1

    if valid_count == 0:
        return empty_stats

    def safe_avg(lst):
        return round(sum(lst) / len(lst), 2) if lst else 0.0

    system_avg_dim = {d: safe_avg(system_ratings[d]) for d in AB_DIMENSIONS}
    baseline_avg_dim = {d: safe_avg(baseline_ratings[d]) for d in AB_DIMENSIONS}

    total_pref = sum(overall_pref.values()) or 1
    system_win = round(overall_pref["system"] / total_pref * 100, 1)
    baseline_win = round(overall_pref["baseline"] / total_pref * 100, 1)
    tie = round(overall_pref["equal"] / total_pref * 100, 1)

    valid_surveys = [s for s in surveys if s.get("ab_assignment") or _get_ab_assignment(s.get("chat_id", ""))]
    recommendations = sum(1 for s in valid_surveys if s.get("would_recommend", False))
    recommendation_rate = round((recommendations / len(valid_surveys)) * 100, 1) if valid_surveys else 0.0

    return SurveyStats(
        total_surveys=valid_count,
        system_avg_per_dimension=system_avg_dim,
        baseline_avg_per_dimension=baseline_avg_dim,
        system_avg_overall=safe_avg(system_overall),
        baseline_avg_overall=safe_avg(baseline_overall),
        system_win_rate=system_win,
        baseline_win_rate=baseline_win,
        tie_rate=tie,
        per_dimension_preference=per_dim_pref,
        group_authority_preference=group_auth_pref if group_auth_pref else None,
        recommendation_rate=recommendation_rate,
    )


@router.get("/questions")
async def get_survey_questions():
    """Get the survey questions configuration."""
    return {"questions": SURVEY_QUESTIONS}


@router.get("/evaluation-set")
async def get_evaluation_set():
    """Return the list of topics available in evaluation_set.json."""
    eval_set = _load_evaluation_set()
    return {"topics": list(eval_set.keys())}


@router.get("/stats/summary", response_model=SurveyStats)
async def get_stats_summary():
    """Get aggregated A/B survey statistics (de-blinded)."""
    surveys = _load_surveys()
    return _calculate_stats(surveys)


@router.get("/chats/evaluated")
async def get_evaluated_chat_ids(evaluator_id: Optional[str] = Query(None)):
    """Get list of chat IDs that have been evaluated (A/B or simple), optionally filtered by evaluator."""
    client = _get_client()
    if evaluator_id:
        ab_results = client.query("""
            MATCH (s:SurveyEvaluation {evaluator_id: $evaluator_id})
            RETURN s.chat_id AS chat_id
        """, {"evaluator_id": evaluator_id})
        simple_results = client.query("""
            MATCH (r:SimpleRating {evaluator_id: $evaluator_id})
            RETURN r.chat_id AS chat_id
        """, {"evaluator_id": evaluator_id})
    else:
        ab_results = client.query("MATCH (s:SurveyEvaluation) RETURN s.chat_id AS chat_id")
        simple_results = client.query("MATCH (r:SimpleRating) RETURN r.chat_id AS chat_id")
    ab_ids = [r["chat_id"] for r in ab_results]
    simple_ids = [r["chat_id"] for r in simple_results]
    all_ids = list(set(ab_ids + simple_ids))
    return {"chat_ids": all_ids, "ab_ids": ab_ids, "simple_ids": simple_ids}


@router.get("/chats/pending")
async def get_pending_chats(evaluator_id: Optional[str] = Query(None)):
    """
    Get evaluation_set chats not yet evaluated by this evaluator.
    Only chats whose query matches a topic in evaluation_set.json are returned (always A/B type).
    If evaluator_id is provided, excludes chats already evaluated by that evaluator.
    """
    logger.info(f"[PENDING-CHATS] Fetching pending chats for evaluator={evaluator_id!r}")

    eval_set_full = _load_evaluation_set_full()
    if not eval_set_full:
        return {"pending": [], "total": 0}

    client = _get_client()

    # Fetch chats not yet evaluated by this evaluator (or all chats if no evaluator_id)
    if evaluator_id:
        pending_results = client.query("""
            MATCH (c:ChatHistory)
            WHERE NOT EXISTS {
                MATCH (s:SurveyEvaluation {chat_id: c.id, evaluator_id: $evaluator_id})
            }
            RETURN c.id AS id, c.query AS query, c.preview AS preview, c.timestamp AS timestamp
            ORDER BY c.timestamp DESC
        """, {"evaluator_id": evaluator_id})
    else:
        pending_results = client.query("""
            MATCH (c:ChatHistory)
            RETURN c.id AS id, c.query AS query, c.preview AS preview, c.timestamp AS timestamp
            ORDER BY c.timestamp DESC
        """)

    pending = []
    for r in pending_results:
        query = r.get("query", "")
        query_lower = query.lower()

        # Only include chats matching a topic in evaluation_set (always A/B type)
        matched_topic = None
        topic_data: dict = {}
        for topic, data in eval_set_full.items():
            if topic.lower() in query_lower:
                matched_topic = topic
                topic_data = data
                break

        if not matched_topic:
            continue

        baseline_citations = []
        baseline_metrics = topic_data.get("baseline_metrics", {})
        if isinstance(baseline_metrics, dict):
            for cit in baseline_metrics.get("citations", []):
                baseline_citations.append({
                    "speaker": cit.get("speaker", ""),
                    "group": cit.get("group", ""),
                    "date": cit.get("date", ""),
                    "quote": cit.get("quote", ""),
                    "verbatim_verified": cit.get("verbatim_verified", False),
                })

        pending.append({
            "id": r["id"],
            "query": query,
            "preview": r.get("preview", ""),
            "timestamp": r.get("timestamp", ""),
            "evaluation_type": "ab",
            "matched_topic": matched_topic,
            "baseline_answer": topic_data.get("baseline_answer", ""),
            "baseline_experts": topic_data.get("baseline_experts", []),
            "baseline_citations": baseline_citations,
        })

    logger.info(f"[PENDING-CHATS] Total pending: {len(pending)}")
    return {"pending": pending, "total": len(pending)}


@router.get("", response_model=SurveyListResponse)
async def list_surveys(
    include_stats: bool = Query(True, description="Include aggregated statistics"),
    limit: int = Query(50, ge=1, le=200, description="Maximum surveys to return"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
):
    """List all A/B surveys with optional statistics."""

    surveys = _load_surveys()

    chat_ids = [s.get("chat_id") for s in surveys if s.get("chat_id")]

    chat_lookup = {}
    if chat_ids:
        client = _get_client()
        results = client.query("""
            MATCH (c:ChatHistory) WHERE c.id IN $ids
            RETURN c.id AS id, c.query AS query, c.preview AS preview, c.timestamp AS timestamp
        """, {"ids": chat_ids})
        chat_lookup = {r["id"]: r for r in results}

    surveys_with_chat = []
    for s in surveys:
        chat = chat_lookup.get(s.get("chat_id"))
        if chat:
            surveys_with_chat.append(
                SurveyWithChat(
                    survey=SurveyResponse(**s),
                    chat_query=chat.get("query", ""),
                    chat_preview=chat.get("preview", ""),
                    chat_timestamp=chat.get("timestamp", datetime.now()),
                )
            )

    surveys_with_chat.sort(key=lambda x: x.survey.timestamp, reverse=True)

    total = len(surveys_with_chat)
    paginated = surveys_with_chat[offset : offset + limit]

    stats = _calculate_stats(surveys) if include_stats else None

    return SurveyListResponse(
        surveys=paginated,
        total=total,
        stats=stats,
    )


@router.post("", response_model=SurveyResponse, dependencies=[Depends(require_storage_open)])
async def create_survey(survey_data: SurveyResponseCreate):
    """Create a new A/B survey response."""

    # Verify chat exists
    chat = _get_chat_by_id(survey_data.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    # Check if this evaluator already rated this chat
    client = _get_client()
    evaluator_id = survey_data.evaluator_id or ""
    existing = client.query("""
        MATCH (s:SurveyEvaluation {chat_id: $chat_id, evaluator_id: $evaluator_id})
        RETURN s.id AS id
    """, {"chat_id": survey_data.chat_id, "evaluator_id": evaluator_id})
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Survey already exists for this chat and evaluator. Use PUT to update."
        )

    # If evaluation_set topic is provided, tag the ChatHistory (idempotent, no overwrite of ab_assignment)
    if survey_data.evaluation_set_topic:
        client.query("""
            MATCH (c:ChatHistory {id: $chat_id})
            SET c.evaluation_set_topic = $topic
        """, {
            "chat_id": survey_data.chat_id,
            "topic": survey_data.evaluation_set_topic,
        })

    # Create survey response — ab_assignment is stored per-evaluator on SurveyEvaluation, not on ChatHistory
    survey_dict = survey_data.model_dump(exclude={"evaluation_set_topic"})
    survey = SurveyResponse(
        id=str(uuid4()),
        timestamp=datetime.now(),
        **survey_dict,
    )

    params = _survey_to_neo4j_params(survey)

    client.query(f"""
        CREATE (s:SurveyEvaluation {{chat_id: $chat_id, evaluator_id: $evaluator_id}})
        SET s.id = $id,
            s.timestamp = $timestamp,
            s.overall_satisfaction_a = $overall_satisfaction_a,
            s.overall_satisfaction_b = $overall_satisfaction_b,
            s.overall_preference = $overall_preference,
            s.would_recommend = $would_recommend,
            s.feedback_positive = $feedback_positive,
            s.feedback_improvement = $feedback_improvement,
            s.evaluator_role = $evaluator_role,
            s.evaluation_context = $evaluation_context,
            s.ab_assignment = $ab_assignment,
            s.baseline_authority_avg = $baseline_authority_avg,
            s.group_authority_votes = $group_authority_votes,
            s.citation_evaluations_a = $citation_evaluations_a,
            s.citation_evaluations_b = $citation_evaluations_b,
            {", ".join(f"s.{d} = ${d}" for d in AB_DIMENSIONS)}
    """, params)

    logger.info(f"A/B survey created for chat {survey_data.chat_id}")
    return survey


@router.post("/simple", response_model=SimpleRatingResponse, dependencies=[Depends(require_storage_open)])
async def create_simple_rating(rating_data: SimpleRatingCreate):
    """Create a new simple Likert-scale rating for a chat without a baseline."""

    # Verify chat exists
    chat = _get_chat_by_id(rating_data.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    client = _get_client()
    evaluator_id = rating_data.evaluator_id or ""

    # Check if this evaluator already rated this chat
    existing = client.query("""
        MATCH (r:SimpleRating {chat_id: $chat_id, evaluator_id: $evaluator_id})
        RETURN r.id AS id
    """, {"chat_id": rating_data.chat_id, "evaluator_id": evaluator_id})
    if existing:
        raise HTTPException(
            status_code=409,
            detail="Simple rating already exists for this chat and evaluator."
        )

    rating = SimpleRatingResponse(
        id=str(uuid4()),
        chat_id=rating_data.chat_id,
        timestamp=datetime.now(),
        answer_clarity=rating_data.answer_clarity,
        answer_quality=rating_data.answer_quality,
        balance_perception=rating_data.balance_perception,
        balance_fairness=rating_data.balance_fairness,
        feedback=rating_data.feedback,
        evaluator_id=evaluator_id or None,
    )

    client.query("""
        CREATE (r:SimpleRating {
            id: $id,
            chat_id: $chat_id,
            evaluator_id: $evaluator_id,
            timestamp: $timestamp,
            answer_clarity: $answer_clarity,
            answer_quality: $answer_quality,
            balance_perception: $balance_perception,
            balance_fairness: $balance_fairness,
            feedback: $feedback
        })
    """, {
        "id": rating.id,
        "chat_id": rating.chat_id,
        "evaluator_id": evaluator_id,
        "timestamp": rating.timestamp.isoformat(),
        "answer_clarity": rating.answer_clarity,
        "answer_quality": rating.answer_quality,
        "balance_perception": rating.balance_perception,
        "balance_fairness": rating.balance_fairness,
        "feedback": rating.feedback or "",
    })

    logger.info(f"Simple rating created for chat {rating_data.chat_id}")
    return rating


@router.get("/{chat_id}", response_model=SurveyResponse)
async def get_survey_by_chat(chat_id: str, evaluator_id: Optional[str] = Query(None)):
    """Get A/B survey for a specific chat. If evaluator_id is provided, returns that evaluator's response."""

    client = _get_client()
    if evaluator_id:
        result = client.query(f"""
            MATCH (s:SurveyEvaluation {{chat_id: $chat_id, evaluator_id: $evaluator_id}})
            RETURN {_SURVEY_FIELDS}
        """, {"chat_id": chat_id, "evaluator_id": evaluator_id})
    else:
        result = client.query(f"""
            MATCH (s:SurveyEvaluation {{chat_id: $chat_id}})
            RETURN {_SURVEY_FIELDS}
            ORDER BY s.timestamp DESC
            LIMIT 1
        """, {"chat_id": chat_id})

    if not result:
        raise HTTPException(status_code=404, detail="Survey not found")

    return SurveyResponse(**_neo4j_record_to_dict(result[0]))


@router.put("/{chat_id}", response_model=SurveyResponse, dependencies=[Depends(require_storage_open)])
async def update_survey(chat_id: str, survey_data: SurveyResponseCreate):
    """Update an existing A/B survey response."""

    client = _get_client()
    evaluator_id = survey_data.evaluator_id or ""
    existing = client.query("""
        MATCH (s:SurveyEvaluation {chat_id: $chat_id, evaluator_id: $evaluator_id})
        RETURN s.id AS id
    """, {"chat_id": chat_id, "evaluator_id": evaluator_id})

    if not existing:
        raise HTTPException(status_code=404, detail="Survey not found")

    survey_dict = survey_data.model_dump(exclude={"ab_assignment", "evaluation_set_topic"})
    updated = SurveyResponse(
        id=existing[0]["id"],
        timestamp=datetime.now(),
        **survey_dict,
    )

    params = _survey_to_neo4j_params(updated)
    params["match_chat_id"] = chat_id
    params["match_evaluator_id"] = evaluator_id

    dim_sets = ", ".join(f"s.{d} = ${d}" for d in AB_DIMENSIONS)

    client.query(f"""
        MATCH (s:SurveyEvaluation {{chat_id: $match_chat_id, evaluator_id: $match_evaluator_id}})
        SET s.timestamp = $timestamp,
            s.overall_satisfaction_a = $overall_satisfaction_a,
            s.overall_satisfaction_b = $overall_satisfaction_b,
            s.overall_preference = $overall_preference,
            s.would_recommend = $would_recommend,
            s.feedback_positive = $feedback_positive,
            s.feedback_improvement = $feedback_improvement,
            s.evaluator_role = $evaluator_role,
            s.evaluation_context = $evaluation_context,
            s.baseline_authority_avg = $baseline_authority_avg,
            s.group_authority_votes = $group_authority_votes,
            s.citation_evaluations_a = $citation_evaluations_a,
            s.citation_evaluations_b = $citation_evaluations_b,
            {dim_sets}
    """, params)

    logger.info(f"A/B survey updated for chat {chat_id}")
    return updated


@router.delete("/{chat_id}")
async def delete_survey(chat_id: str, evaluator_id: Optional[str] = Query(None)):
    """Delete an A/B survey. If evaluator_id is provided, deletes only that evaluator's response."""

    client = _get_client()
    if evaluator_id:
        result = client.query("""
            MATCH (s:SurveyEvaluation {chat_id: $chat_id, evaluator_id: $evaluator_id})
            DELETE s
            RETURN count(*) AS deleted
        """, {"chat_id": chat_id, "evaluator_id": evaluator_id})
    else:
        result = client.query("""
            MATCH (s:SurveyEvaluation {chat_id: $chat_id})
            DELETE s
            RETURN count(*) AS deleted
        """, {"chat_id": chat_id})

    if not result or result[0]["deleted"] == 0:
        raise HTTPException(status_code=404, detail="Survey not found")

    logger.info(f"A/B survey deleted for chat {chat_id}" + (f" evaluator {evaluator_id}" if evaluator_id else " (all evaluators)"))
    return {"message": "Survey deleted", "chat_id": chat_id}
