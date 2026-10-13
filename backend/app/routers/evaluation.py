"""
Evaluation router for scientific assessment of ParliamentRAG.
Computes automated metrics from stored pipeline data and combines
them with human survey evaluations for dashboard visualization.
"""

import csv
import io
import json
import logging
import math
import re
import unicodedata
from datetime import datetime
from typing import List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.models.evaluation import (
    AutomatedMetrics,
    AggregatedMetrics,
    ABComparisonStats,
    CombinedEvaluation,
    EvaluationDashboardData,
)
from app.models.survey import SurveyResponse, AB_DIMENSIONS, SimpleRatingResponse
from app.routers.survey import _load_surveys, _calculate_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/evaluation", tags=["evaluation"])

# 10 parliamentary groups in the system
ALL_PARTIES = 10

# Known parliamentary groups — Governo is excluded from party coverage count
KNOWN_PARTIES = {
    "Fratelli d'Italia",
    "Lega - Salvini Premier",
    "Forza Italia - Berlusconi Presidente - PPE",
    "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
    "Partito Democratico - Italia Democratica e Progressista",
    "Movimento 5 Stelle",
    "Alleanza Verdi e Sinistra",
    "Azione - Popolari Europeisti Riformatori - Renew Europe",
    "Italia Viva - Casa Riformista",
    "Misto",
}

# Keyword sets for each group — at least one keyword must appear in the answer text
PARTY_KEYWORDS: List[List[str]] = [
    ["Fratelli d'Italia", "FdI"],
    ["Lega"],
    ["Forza Italia"],
    ["Noi Moderati"],
    ["Partito Democratico", "PD"],
    ["Movimento 5 Stelle", "M5S"],
    ["Azione"],
    ["Italia Viva"],
    ["Alleanza Verdi", "AVS", "Verdi e Sinistra"],
    ["Misto"],
]


def _normalize_for_verbatim(text: str) -> str:
    """Normalize text for verbatim match comparison.

    Strips differences caused by:
    - Unicode normalization (accents, ligatures)
    - Case differences
    - Punctuation
    - Whitespace inconsistencies
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_apostrophes(text: str) -> str:
    """Normalise all apostrophe/quote variants to a plain ASCII apostrophe.

    LLM outputs often use typographic apostrophes (U+2019 '\u2019', U+2018 '\u2018')
    or prime signs (U+02BC) while the PARTY_KEYWORDS list uses straight apostrophes.
    NFKC normalisation doesn't collapse these, so we do it explicitly.
    """
    for char in ("\u2019", "\u2018", "\u02BC", "\u0060", "\u00B4"):
        text = text.replace(char, "'")
    return text


_CLAIM_VERBS = re.compile(
    r'\b(?:sostiene|afferma|dichiara|propone|critica|vuole|chiede|denuncia|'
    r'contesta|ribadisce|respinge|difende)\b',
    re.IGNORECASE,
)


def _compute_unsupported_claim_rate(answer: str) -> Tuple[float, int, int]:
    """Share of claim-verb sentences that carry no citation.

    Citation links are masked to a «» marker before sentence splitting
    (their IDs contain periods). Deterministic proxy: synthesis sentences
    legitimately exist, so the target is a low rate, not zero.
    """
    if not answer:
        return 0.0, 0, 0
    masked = re.sub(r'\[«[^\]]*»\]\([^)]+\)', '«»', answer)
    sentences = [s.strip() for s in re.split(r'[.!?]', masked) if s.strip()]
    claim_sentences = [s for s in sentences if _CLAIM_VERBS.search(s)]
    unsupported = [s for s in claim_sentences if '«' not in s]
    rate = len(unsupported) / len(claim_sentences) if claim_sentences else 0.0
    return rate, len(unsupported), len(claim_sentences)


def _count_parties_in_text(answer: str) -> int:
    """Count how many of the 10 known parliamentary groups are mentioned in the answer text."""
    answer_norm = _normalize_apostrophes(unicodedata.normalize("NFKC", answer)).lower()
    count = 0
    for keywords in PARTY_KEYWORDS:
        if any(_normalize_apostrophes(kw).lower() in answer_norm for kw in keywords):
            count += 1
    return count


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


def _fetch_all_chats() -> List[dict]:
    """Fetch all ChatHistory nodes with full data from Neo4j."""
    client = _get_client()
    results = client.query("""
        MATCH (c:ChatHistory)
        RETURN c.id AS id, c.query AS query, c.answer AS answer,
               c.timestamp AS timestamp, c.citations AS citations,
               c.experts AS experts, c.baseline_answer AS baseline_answer
        ORDER BY c.timestamp DESC
    """)

    chats = []
    for r in results:
        chats.append({
            "id": r["id"],
            "query": r["query"],
            "answer": r.get("answer", ""),
            "timestamp": r.get("timestamp", ""),
            "citations": json.loads(r["citations"]) if r.get("citations") else [],
            "experts": json.loads(r["experts"]) if r.get("experts") else [],
            "baseline_answer": r.get("baseline_answer") or "",
        })
    return chats


def _build_expert_full_lookup(chats: List[dict]) -> dict:
    """Build a (first_name_lower, last_name_lower) → {score, party} lookup from stored chat experts."""
    lookup = {}
    for chat in chats:
        for expert in chat.get("experts", []):
            fn = (expert.get("first_name") or "").strip().lower()
            ln = (expert.get("last_name") or "").strip().lower()
            score = expert.get("authority_score") or expert.get("total_score") or 0
            party = expert.get("party") or expert.get("group") or ""
            if fn and ln and score:
                key = (fn, ln)
                if key not in lookup or score > lookup[key]["score"]:
                    lookup[key] = {"score": score, "party": party}
    return lookup


def _compute_baseline_authority_full(
    baseline_text: str,
    expert_full_lookup: dict,
) -> tuple:
    """
    Match deputies in baseline_text using the full expert lookup.
    Returns (overall_avg, {party: avg_score}) or (None, None) if no matches.

    Matching strategy (in order, stops at first match per expert):
    1. Full "fn ln" or "ln fn" substring match.
    2. ln as a whole word (works for single-word surnames).
    3. Last word of ln as whole word (handles compound surnames like "Elena Boschi" → "Boschi").
    4. fn as whole word (last resort for short texts citing just a first name, rare).
    """
    if not baseline_text or not expert_full_lookup:
        return None, None
    text_lower = baseline_text.lower()
    party_scores: dict = {}
    all_matched_scores: list = []

    for (fn, ln), info in expert_full_lookup.items():
        score = info["score"]
        party = info["party"]
        matched = False

        if f"{fn} {ln}" in text_lower or f"{ln} {fn}" in text_lower:
            matched = True
        elif len(ln) >= 4 and re.search(r'\b' + re.escape(ln) + r'\b', text_lower):
            matched = True
        elif " " in ln:
            # Compound surname: try just the last word (e.g. "elena boschi" → "boschi")
            last_word = ln.rsplit(" ", 1)[-1]
            if len(last_word) >= 4 and re.search(r'\b' + re.escape(last_word) + r'\b', text_lower):
                matched = True

        if matched:
            all_matched_scores.append(score)
            if party:
                party_scores.setdefault(party, []).append(score)

    if not all_matched_scores:
        return None, None

    overall = round(sum(all_matched_scores) / len(all_matched_scores), 4)
    by_group = {p: round(sum(s) / len(s), 4) for p, s in party_scores.items()} or None
    return overall, by_group


def _compute_baseline_authority_from_precomputed(
    baseline_experts: List[dict],
) -> tuple:
    """
    Compute baseline authority from pre-computed experts (query-specific scores).
    These experts already have authority scores computed with the specific query embedding,
    so they are directly comparable to the system's per-chat authority_by_group.
    Returns (overall_avg, {party: avg_score}) or (None, None) if no data.
    """
    if not baseline_experts:
        return None, None
    party_scores: dict = {}
    all_scores: list = []
    for e in baseline_experts:
        score = e.get("authority_score", 0) or 0
        party = e.get("group", "") or e.get("party", "")
        if score > 0:
            all_scores.append(score)
            if party:
                party_scores.setdefault(party, []).append(score)
    if not all_scores:
        return None, None
    overall = round(sum(all_scores) / len(all_scores), 4)
    by_group = {p: round(sum(s) / len(s), 4) for p, s in party_scores.items()} or None
    return overall, by_group


def _fetch_chunk_texts(chunk_ids: List[str]) -> dict:
    """Batch-fetch chunk texts from Neo4j. Returns {chunk_id: text}."""
    if not chunk_ids:
        return {}
    from ..services.archive import fill_rows

    client = _get_client()
    results = client.query("""
        UNWIND $ids AS cid
        MATCH (c:Chunk {id: cid})
        RETURN cid, c.text AS text
    """, {"ids": chunk_ids})
    fill_rows(results, chunk_fields={"cid": {"text": "text"}})
    return {r["cid"]: r.get("text") or "" for r in results}


def _compute_automated_metrics(
    chat: dict,
    chunk_texts: dict,
    expert_full_lookup: Optional[dict] = None,
    baseline_precomputed_experts: Optional[List[dict]] = None,
    authority_spread_std: Optional[float] = None,
    authority_spread_stats: Optional[dict] = None,
) -> AutomatedMetrics:
    """Compute automated metrics from a single chat's stored data.

    Args:
        chat: Chat data dict (id, query, answer, citations, experts, baseline_answer).
        chunk_texts: Pre-fetched {chunk_id: text} mapping for verbatim match.
        expert_full_lookup: Optional full expert lookup for baseline per-group authority (fallback).
        baseline_precomputed_experts: Optional pre-computed baseline experts with query-specific
            authority scores (preferred over expert_full_lookup for accurate comparison).
        authority_spread_std: Optional pre-computed std dev of ALL deputies' scores for this topic
            (from compute_topic_authority_spread.py). When present, used directly as
            authority_discrimination instead of the cited-experts std dev.
    """
    chat_id = chat["id"]
    citations = chat.get("citations", [])
    experts = chat.get("experts", [])
    answer = chat.get("answer", "")

    # 1. Party Coverage — only count known parliamentary groups (excludes "Governo")
    parties_found = set()
    party_breakdown = {}
    for cit in citations:
        group = cit.get("group", "") or cit.get("party", "")
        if group and group in KNOWN_PARTIES:
            parties_found.add(group)
            party_breakdown[group] = party_breakdown.get(group, 0) + 1
    parties_represented = len(parties_found)
    party_coverage = min(parties_represented / ALL_PARTIES, 1.0) if ALL_PARTIES > 0 else 0

    # 2. Citation Fidelity: verbatim_count / citations_total
    # Unified metric: a citation passes only if it has text AND that text appears verbatim
    # in the source chunk.  Denominator is citations_total so missing quote_text also fails.
    citations_total = len(citations)
    verbatim_count = 0
    for cit in citations:
        chunk_id = cit.get("evidence_id") or cit.get("chunk_id", "")
        if not chunk_id:
            continue
        stored_text = cit.get("full_text", "") or cit.get("quote_text", "")
        if not stored_text:
            continue
        chunk_text = chunk_texts.get(chunk_id, "")
        if not chunk_text:
            continue
        norm_stored = _normalize_for_verbatim(stored_text)
        norm_chunk = _normalize_for_verbatim(chunk_text)
        if norm_stored == norm_chunk or norm_stored in norm_chunk or norm_chunk in norm_stored:
            verbatim_count += 1
    verbatim_match_score = verbatim_count / max(citations_total, 1) if citations_total > 0 else 0.0

    # 4. Authority Utilization: mean authority_score of cited experts
    auth_scores = [
        e.get("authority_score", 0) or e.get("total_score", 0)
        for e in experts
        if e.get("authority_score") or e.get("total_score")
    ]
    avg_auth = sum(auth_scores) / len(auth_scores) if auth_scores else 0.0

    # 4b. Per-group authority breakdown (system) — from the authority scores of
    # deputies actually cited in the answer, not the top-retrieved expert per party.
    # Strategy:
    #   1. Build a (first_name, last_name) → score lookup from this chat's query-specific experts.
    #   2. Also build a party → (fn, ln, score) lookup for the stored top expert per party.
    #   3. For each citation, look up the cited deputy's score by name.
    #   4. Fallback to the stored top expert for that party (query-specific, not the global max).
    #      This ensures authority_by_group is always based on query-specific scores and
    #      stays consistent with the survey panel which also uses chatData.experts.
    expert_name_lookup: dict = {}
    party_top_expert: dict = {}  # party → (fn, ln, score) for query-specific fallback
    for e in experts:
        fn = (e.get("first_name") or "").strip().lower()
        ln = (e.get("last_name") or "").strip().lower()
        score = e.get("authority_score", 0) or e.get("total_score", 0)
        party = e.get("group") or e.get("party") or ""
        if fn and ln and score:
            expert_name_lookup[(fn, ln)] = score
            if party and party not in party_top_expert:
                party_top_expert[party] = (fn, ln, score)

    group_cited_deputies: dict = {}  # {party: {(fn, ln): score}}
    for cit in citations:
        g = cit.get("group", "") or cit.get("party", "")
        if not g:
            continue
        fn = (cit.get("deputy_first_name") or "").strip().lower()
        ln = (cit.get("deputy_last_name") or "").strip().lower()
        if not fn and not ln:
            continue
        score = expert_name_lookup.get((fn, ln))
        if score is None:
            # Fallback: use the stored top expert for this party (query-specific).
            # Never use expert_full_lookup here — it carries scores from other queries,
            # which would make authority_by_group inconsistent with the survey panel.
            top = party_top_expert.get(g)
            if top:
                fn, ln, score = top
        if score:
            group_cited_deputies.setdefault(g, {})[(fn, ln)] = score

    authority_by_group = {
        p: round(sum(scores.values()) / len(scores), 4)
        for p, scores in group_cited_deputies.items()
        if scores
    }

    # 5. Authority Discrimination (Authority Spread):
    # Prefer pre-computed std across ALL deputies for this topic (from
    # compute_topic_authority_spread.py), which gives a meaningful signal about
    # how much authority scores vary across the full parliament on that topic.
    # Falls back to cited-experts std when no pre-computed data is available.
    if authority_spread_std is not None:
        auth_discrimination = authority_spread_std
    elif len(auth_scores) >= 2:
        mean_a = avg_auth
        variance_a = sum((x - mean_a) ** 2 for x in auth_scores) / len(auth_scores)
        auth_discrimination = math.sqrt(variance_a)
    else:
        auth_discrimination = 0.0

    # 6. Response Completeness: how many of the 10 groups are mentioned in the answer text
    parties_in_text = _count_parties_in_text(answer)
    completeness = min(parties_in_text / ALL_PARTIES, 1.0)

    # 6b. Unsupported claim rate (deterministic text proxy)
    ucr, ucr_count, claim_count = _compute_unsupported_claim_rate(answer)

    # 7. Baseline authority (per-chat, per-group)
    # Prefer pre-computed baseline experts (query-specific scores) for an accurate
    # apples-to-apples comparison with the system's authority_by_group.
    # Fall back to expert_full_lookup text-matching only when no pre-computed data exists.
    baseline_authority = None
    baseline_authority_by_group = None
    if baseline_precomputed_experts:
        baseline_authority, baseline_authority_by_group = _compute_baseline_authority_from_precomputed(
            baseline_precomputed_experts
        )
    else:
        baseline_text = chat.get("baseline_answer", "")
        if baseline_text and expert_full_lookup:
            baseline_authority, baseline_authority_by_group = _compute_baseline_authority_full(
                baseline_text, expert_full_lookup
            )

    return AutomatedMetrics(
        chat_id=chat_id,
        party_coverage_score=round(party_coverage, 4),
        parties_represented=parties_represented,
        parties_total=ALL_PARTIES,
        party_breakdown=party_breakdown,
        citations_total=citations_total,
        verbatim_match_score=round(verbatim_match_score, 4),
        verbatim_match_count=verbatim_count,
        authority_utilization=round(avg_auth, 4),
        experts_count=len(experts),
        authority_discrimination=round(auth_discrimination, 4),
        response_completeness=round(completeness, 4),
        unsupported_claim_rate=round(ucr, 4),
        unsupported_claim_count=ucr_count,
        claim_sentence_count=claim_count,
        authority_by_group=authority_by_group,
        baseline_authority=baseline_authority,
        baseline_authority_by_group=baseline_authority_by_group,
        authority_spread_stats=authority_spread_stats,
    )


def _compute_ci(values: List[float], confidence: float = 0.95) -> Tuple[float, float]:
    """Compute confidence interval using t-distribution approximation."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (values[0], values[0])

    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std_err = math.sqrt(variance / n)

    # t-value approximation for 95% CI
    t_val = 2.0 if n < 30 else 1.96
    margin = t_val * std_err

    return (round(max(0, mean - margin), 4), round(min(1, mean + margin), 4))


def _compute_ci_unbounded(values: List[float]) -> Tuple[float, float]:
    """Compute CI without upper bound clamping (for authority_discrimination)."""
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    if n == 1:
        return (values[0], values[0])

    mean = sum(values) / n
    variance = sum((x - mean) ** 2 for x in values) / (n - 1)
    std_err = math.sqrt(variance / n)
    t_val = 2.0 if n < 30 else 1.96
    margin = t_val * std_err

    return (round(max(0, mean - margin), 4), round(mean + margin, 4))


def _compute_aggregated(
    metrics_list: List[AutomatedMetrics],
    baseline_party_coverage_list: Optional[List[float]] = None,
    baseline_citation_fidelity_list: Optional[List[float]] = None,
    baseline_completeness_list: Optional[List[float]] = None,
    baseline_authority_list: Optional[List[float]] = None,
) -> AggregatedMetrics:
    """Compute aggregated metrics with confidence intervals."""
    n = len(metrics_list)
    if n == 0:
        return AggregatedMetrics(
            total_chats=0,
            avg_party_coverage=0,
            avg_verbatim_match=0, avg_response_completeness=0,
            avg_authority_utilization=0, avg_authority_discrimination=0,
            ci_party_coverage=(0, 0),
            ci_verbatim_match=(0, 0), ci_response_completeness=(0, 0),
            ci_authority_utilization=(0, 0), ci_authority_discrimination=(0, 0),
        )

    pc = [m.party_coverage_score for m in metrics_list]
    vm = [m.verbatim_match_score for m in metrics_list]
    au = [m.authority_utilization for m in metrics_list]
    ad = [m.authority_discrimination for m in metrics_list]
    rc = [m.response_completeness for m in metrics_list]

    result = AggregatedMetrics(
        total_chats=n,
        avg_party_coverage=round(sum(pc) / n, 4),
        avg_verbatim_match=round(sum(vm) / n, 4),
        avg_authority_utilization=round(sum(au) / n, 4),
        avg_authority_discrimination=round(sum(ad) / n, 4),
        avg_response_completeness=round(sum(rc) / n, 4),
        ci_party_coverage=_compute_ci(pc),
        ci_verbatim_match=_compute_ci(vm),
        ci_authority_utilization=_compute_ci(au),
        ci_authority_discrimination=_compute_ci_unbounded(ad),
        ci_response_completeness=_compute_ci(rc),
    )

    ucr = [m.unsupported_claim_rate for m in metrics_list]
    result.avg_unsupported_claim_rate = round(sum(ucr) / n, 4)
    result.ci_unsupported_claim_rate = _compute_ci(ucr)

    # Baseline comparison metrics (optional, pre-computed by enrich_evaluation_set.py)
    if baseline_party_coverage_list and len(baseline_party_coverage_list) > 0:
        bpc_n = len(baseline_party_coverage_list)
        result.avg_baseline_party_coverage = round(sum(baseline_party_coverage_list) / bpc_n, 4)
        result.ci_baseline_party_coverage = _compute_ci(baseline_party_coverage_list)

    if baseline_citation_fidelity_list and len(baseline_citation_fidelity_list) > 0:
        bcf_n = len(baseline_citation_fidelity_list)
        result.avg_baseline_citation_fidelity = round(sum(baseline_citation_fidelity_list) / bcf_n, 4)
        result.ci_baseline_citation_fidelity = _compute_ci(baseline_citation_fidelity_list)

    if baseline_completeness_list and len(baseline_completeness_list) > 0:
        bn = len(baseline_completeness_list)
        result.avg_baseline_response_completeness = round(sum(baseline_completeness_list) / bn, 4)
        result.ci_baseline_response_completeness = _compute_ci(baseline_completeness_list)

    if baseline_authority_list and len(baseline_authority_list) > 0:
        ban = len(baseline_authority_list)
        result.avg_baseline_authority = round(sum(baseline_authority_list) / ban, 4)
        result.ci_baseline_authority = _compute_ci(baseline_authority_list)

    return result


def _load_simple_ratings() -> List[dict]:
    """Load all SimpleRating nodes from Neo4j."""
    client = _get_client()
    results = client.query("""
        MATCH (r:SimpleRating)
        RETURN r.id AS id, r.chat_id AS chat_id, r.timestamp AS timestamp,
               r.answer_clarity AS answer_clarity,
               r.answer_quality AS answer_quality,
               r.balance_perception AS balance_perception,
               r.balance_fairness AS balance_fairness,
               r.feedback AS feedback,
               r.evaluator_id AS evaluator_id
    """)
    return [dict(r) for r in results]


@router.get("/dashboard", response_model=EvaluationDashboardData)
async def get_dashboard():
    """Get full evaluation dashboard data with automated + human metrics."""
    chats = _fetch_all_chats()

    # Batch-fetch chunk texts for verbatim match across all chats
    all_chunk_ids = []
    for chat in chats:
        for cit in chat.get("citations", []):
            cid = cit.get("evidence_id") or cit.get("chunk_id", "")
            if cid:
                all_chunk_ids.append(cid)
    chunk_texts = _fetch_chunk_texts(list(set(all_chunk_ids)))

    # Build full expert lookup for baseline per-group authority (fallback only)
    expert_full_lookup = _build_expert_full_lookup(chats)

    # Load pre-computed baseline experts from evaluation_set.json (query-specific scores).
    # These are used instead of expert_full_lookup to get comparable authority scores.
    from app.routers.survey import _load_evaluation_set_raw as _load_eval_set_raw_inner
    _eval_set_raw_for_experts = _load_eval_set_raw_inner()
    # Build {topic_lower: baseline_experts}, {topic_lower: authority_spread_std},
    # and {topic_lower: authority_spread_dict} for fast lookup
    _topic_to_baseline_experts: dict = {}
    _topic_to_authority_spread_std: dict = {}
    _topic_to_authority_spread: dict = {}
    for _topic, _entry in _eval_set_raw_for_experts.items():
        if isinstance(_entry, dict):
            _experts = _entry.get("baseline_experts", [])
            if _experts:
                _topic_to_baseline_experts[_topic.lower()] = _experts
            _spread = _entry.get("authority_spread")
            if _spread and _spread.get("std") is not None:
                _topic_to_authority_spread_std[_topic.lower()] = _spread["std"]
                _topic_to_authority_spread[_topic.lower()] = _spread

    def _find_baseline_experts(query: str) -> Optional[List[dict]]:
        q = query.lower()
        for topic_l, experts in _topic_to_baseline_experts.items():
            if topic_l in q or q in topic_l:
                return experts
        return None

    def _find_authority_spread_std(query: str) -> Optional[float]:
        q = query.lower()
        for topic_l, std in _topic_to_authority_spread_std.items():
            if topic_l in q or q in topic_l:
                return std
        return None

    def _find_authority_spread(query: str) -> Optional[dict]:
        q = query.lower()
        for topic_l, spread in _topic_to_authority_spread.items():
            if topic_l in q or q in topic_l:
                return spread
        return None

    metrics_map = {}
    for chat in chats:
        try:
            bl_experts = _find_baseline_experts(chat.get("query", ""))
            spread_std = _find_authority_spread_std(chat.get("query", ""))
            spread_stats = _find_authority_spread(chat.get("query", ""))
            metrics_map[chat["id"]] = _compute_automated_metrics(
                chat, chunk_texts, expert_full_lookup,
                baseline_precomputed_experts=bl_experts,
                authority_spread_std=spread_std,
                authority_spread_stats=spread_stats,
            )
        except Exception as e:
            logger.warning(f"Failed to compute metrics for chat {chat['id']}: {e}")

    surveys = _load_surveys()
    survey_map = {}
    for s in surveys:
        cid = s.get("chat_id")
        if cid:
            try:
                survey_map[cid] = SurveyResponse(**s)
            except Exception:
                pass

    simple_ratings_raw = _load_simple_ratings()
    simple_map = {}
    for r in simple_ratings_raw:
        cid = r.get("chat_id")
        if cid:
            try:
                simple_map[cid] = SimpleRatingResponse(**r)
            except Exception:
                pass

    per_chat = []
    for chat in chats:
        cid = chat["id"]
        automated = metrics_map.get(cid)
        if not automated:
            continue
        per_chat.append(CombinedEvaluation(
            chat_id=cid,
            chat_query=chat.get("query", ""),
            timestamp=str(chat.get("timestamp", "")),
            automated=automated,
            human=survey_map.get(cid),
            human_simple=simple_map.get(cid),
        ))

    # Baseline metrics: prefer pre-computed baseline_metrics (written by
    # scripts/enrich_evaluation_set.py) which provide citation-based party coverage
    # and citation fidelity comparable to the system metrics.
    # Fall back to text-based detection for completeness / authority.
    # Reuse the already-loaded eval set (avoids a second file read).
    eval_set_raw = _eval_set_raw_for_experts

    baseline_party_coverage_list: List[float] = []
    baseline_citation_fidelity_list: List[float] = []
    baseline_completeness_list: List[float] = []

    for entry in eval_set_raw.values():
        if isinstance(entry, str):
            entry = {"baseline_answer": entry}
        bm = entry.get("baseline_metrics")
        if bm:
            # Citation-based party coverage (from enrich_evaluation_set.py)
            if bm.get("baseline_party_coverage") is not None:
                baseline_party_coverage_list.append(bm["baseline_party_coverage"])
            if bm.get("baseline_citation_fidelity") is not None:
                baseline_citation_fidelity_list.append(bm["baseline_citation_fidelity"])

        # Text-based completeness (both sides text-based → comparable)
        baseline_text = entry.get("baseline_answer", "") if isinstance(entry, dict) else entry
        if baseline_text:
            parties_in_bl = _count_parties_in_text(baseline_text)
            baseline_completeness_list.append(min(parties_in_bl / ALL_PARTIES, 1.0))

    # Baseline authority: prefer pre-computed query-specific experts from evaluation_set.json.
    # Fall back to text-matching with expert_full_lookup only when no pre-computed data exists.
    baseline_authority_list: List[float] = []
    all_group_baseline_from_set: dict = {}
    for entry in eval_set_raw.values():
        if isinstance(entry, str):
            entry = {"baseline_answer": entry}
        bl_experts = entry.get("baseline_experts", [])
        if bl_experts:
            overall, by_group = _compute_baseline_authority_from_precomputed(bl_experts)
        else:
            baseline_text = entry.get("baseline_answer", "")
            overall, by_group = _compute_baseline_authority_full(baseline_text, expert_full_lookup)
        if overall is not None:
            baseline_authority_list.append(overall)
        if by_group:
            for party, score in by_group.items():
                all_group_baseline_from_set.setdefault(party, []).append(score)

    # Also include any surveys that explicitly stored baseline_authority_avg
    for s in surveys:
        baa = s.get("baseline_authority_avg")
        if baa is not None and baa >= 0:
            baseline_authority_list.append(baa)

    all_metrics = list(metrics_map.values())

    # Compute avg_baseline_authority_by_group:
    # prefer per-chat breakdown (chats with stored baseline_answer), fall back to eval_set
    all_group_baseline_from_chats: dict = {}
    for m in all_metrics:
        if m.baseline_authority_by_group:
            for party, score in m.baseline_authority_by_group.items():
                all_group_baseline_from_chats.setdefault(party, []).append(score)

    merged_group_baseline = all_group_baseline_from_chats if all_group_baseline_from_chats else all_group_baseline_from_set
    avg_baseline_by_group = (
        {p: round(sum(s) / len(s), 4) for p, s in merged_group_baseline.items()}
        if merged_group_baseline else None
    )

    automated_aggregate = _compute_aggregated(
        all_metrics,
        baseline_party_coverage_list or None,
        baseline_citation_fidelity_list or None,
        baseline_completeness_list or None,
        baseline_authority_list or None,
    )
    automated_aggregate.avg_baseline_authority_by_group = avg_baseline_by_group
    human_aggregate = _calculate_stats(surveys) if surveys else None

    # Compute A/B comparison stats from human aggregate
    ab_comparison = None
    if human_aggregate and human_aggregate.total_surveys > 0:
        ab_comparison = ABComparisonStats(
            total_evaluations=human_aggregate.total_surveys,
            system_win_rate=human_aggregate.system_win_rate,
            baseline_win_rate=human_aggregate.baseline_win_rate,
            tie_rate=human_aggregate.tie_rate,
            system_avg_ratings=human_aggregate.system_avg_per_dimension,
            baseline_avg_ratings=human_aggregate.baseline_avg_per_dimension,
            system_avg_overall=human_aggregate.system_avg_overall,
            baseline_avg_overall=human_aggregate.baseline_avg_overall,
            per_dimension_preference=human_aggregate.per_dimension_preference,
            group_authority_preference=human_aggregate.group_authority_preference,
        )

    return EvaluationDashboardData(
        automated_aggregate=automated_aggregate,
        human_aggregate=human_aggregate,
        ab_comparison=ab_comparison,
        per_chat=per_chat,
        total_chats=len(chats),
        total_evaluated=len(survey_map),
        total_simple_rated=len(simple_map),
    )


@router.get("/metrics/{chat_id}", response_model=AutomatedMetrics)
async def get_chat_metrics(chat_id: str):
    """Compute automated metrics for a specific chat."""
    client = _get_client()
    result = client.query("""
        MATCH (c:ChatHistory {id: $id})
        RETURN c.id AS id, c.query AS query, c.answer AS answer,
               c.timestamp AS timestamp, c.citations AS citations,
               c.experts AS experts
    """, {"id": chat_id})

    if not result:
        raise HTTPException(status_code=404, detail="Chat not found")

    r = result[0]
    chat = {
        "id": r["id"],
        "query": r["query"],
        "answer": r.get("answer", ""),
        "citations": json.loads(r["citations"]) if r.get("citations") else [],
        "experts": json.loads(r["experts"]) if r.get("experts") else [],
    }

    chunk_ids = [
        cit.get("evidence_id") or cit.get("chunk_id", "")
        for cit in chat["citations"]
        if cit.get("evidence_id") or cit.get("chunk_id")
    ]
    chunk_texts = _fetch_chunk_texts(chunk_ids)

    return _compute_automated_metrics(chat, chunk_texts)


@router.get("/export/csv")
async def export_csv():
    """Export all evaluation data as CSV for paper analysis."""
    chats = _fetch_all_chats()

    all_chunk_ids = []
    for chat in chats:
        for cit in chat.get("citations", []):
            cid = cit.get("evidence_id") or cit.get("chunk_id", "")
            if cid:
                all_chunk_ids.append(cid)
    chunk_texts = _fetch_chunk_texts(list(set(all_chunk_ids)))

    surveys = _load_surveys()
    survey_map = {s.get("chat_id"): s for s in surveys if s.get("chat_id")}

    simple_ratings = _load_simple_ratings()
    simple_map = {r.get("chat_id"): r for r in simple_ratings if r.get("chat_id")}

    output = io.StringIO()
    writer = csv.writer(output)

    from app.routers.survey import _get_ab_assignment, _deblind_preference

    dim_headers = []
    for dim in AB_DIMENSIONS:
        dim_headers.extend([
            f"{dim}_system", f"{dim}_baseline", f"{dim}_preference"
        ])

    simple_headers = [
        "simple_answer_clarity", "simple_answer_quality",
        "simple_balance_perception", "simple_balance_fairness",
        "simple_feedback",
    ]

    writer.writerow([
        "chat_id", "query", "timestamp",
        # Automated metrics
        "party_coverage", "citation_fidelity",
        "authority_utilization", "authority_discrimination", "response_completeness",
        "parties_represented", "citations_total",
        "verbatim_count", "experts_count",
        # Human A/B metrics (de-blinded)
        *dim_headers,
        "overall_satisfaction_system", "overall_satisfaction_baseline",
        "overall_preference",
        "would_recommend",
        "feedback_positive", "feedback_improvement",
        # Simple Likert rating
        *simple_headers,
    ])

    for chat in chats:
        try:
            m = _compute_automated_metrics(chat, chunk_texts)
        except Exception:
            continue

        s = survey_map.get(chat["id"], {})
        ab = _get_ab_assignment(chat["id"]) if s else None

        # De-blind A/B dimension ratings
        dim_values = []
        for dim in AB_DIMENSIONS:
            dim_data = s.get(dim, {})
            if isinstance(dim_data, dict) and ab:
                is_a_system = ab.get("A") == "system"
                r_a = dim_data.get("rating_a", "")
                r_b = dim_data.get("rating_b", "")
                pref = _deblind_preference(dim_data.get("preference", "equal"), ab) if ab else ""
                system_r = r_a if is_a_system else r_b
                baseline_r = r_b if is_a_system else r_a
                dim_values.extend([system_r, baseline_r, pref])
            else:
                dim_values.extend(["", "", ""])

        # De-blind overall satisfaction
        if ab:
            is_a_system = ab.get("A") == "system"
            sat_a = s.get("overall_satisfaction_a", "")
            sat_b = s.get("overall_satisfaction_b", "")
            overall_sys = sat_a if is_a_system else sat_b
            overall_base = sat_b if is_a_system else sat_a
            overall_pref = _deblind_preference(s.get("overall_preference", "equal"), ab)
        else:
            overall_sys = ""
            overall_base = ""
            overall_pref = ""

        sr = simple_map.get(chat["id"], {})
        simple_values = [
            sr.get("answer_clarity", ""),
            sr.get("answer_quality", ""),
            sr.get("balance_perception", ""),
            sr.get("balance_fairness", ""),
            sr.get("feedback", ""),
        ]

        writer.writerow([
            chat["id"],
            chat.get("query", ""),
            chat.get("timestamp", ""),
            m.party_coverage_score,
            m.verbatim_match_score,
            m.authority_utilization,
            m.authority_discrimination,
            m.response_completeness,
            m.parties_represented,
            m.citations_total,
            m.verbatim_match_count,
            m.experts_count,
            *dim_values,
            overall_sys, overall_base, overall_pref,
            s.get("would_recommend", ""),
            s.get("feedback_positive", ""),
            s.get("feedback_improvement", ""),
            *simple_values,
        ])

    output.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename=parliament_rag_evaluation_{timestamp}.csv"
        },
    )
