"""
Authority ranking endpoint.

Given a topic, computes authority scores for every deputy and returns
them ranked by score (descending).
"""
import asyncio
import logging
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..config import get_settings
from ..services.authority import AuthorityScorer
from ..services.authority.coalition_logic import CoalitionLogic
from ..services.neo4j_client import Neo4jClient
from ..services.retrieval import RetrievalEngine

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Authority Ranking"])

# Global service instances (lazy-init)
_neo4j_client: Optional[Neo4jClient] = None
_retrieval_engine: Optional[RetrievalEngine] = None
_authority_scorer: Optional[AuthorityScorer] = None

# Ranking cache: normalized topic → response dict.
# Computation takes minutes, so a proxy timeout on the first request must not
# throw the result away; retries and repeated topics are served instantly.
_RANKING_CACHE_MAX = 50
_ranking_cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
# In-flight dedup: concurrent requests for the same topic share one computation.
_ranking_inflight: Dict[str, "asyncio.Task"] = {}


def _get_services():
    global _neo4j_client, _retrieval_engine, _authority_scorer
    if _neo4j_client is None:
        settings = get_settings()
        _neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
        )
        _retrieval_engine = RetrievalEngine(_neo4j_client)
        _authority_scorer = AuthorityScorer(_neo4j_client)
    return _neo4j_client, _retrieval_engine, _authority_scorer


class RankingRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=500)


def _fetch_all_deputy_ids(neo4j_client: Neo4jClient) -> List[str]:
    """Fetch all deputy IDs from Neo4j."""
    cypher = "MATCH (d:Deputy) RETURN d.id AS id"
    with neo4j_client.session() as session:
        result = session.run(cypher)
        return [record["id"] for record in result]


def _fetch_deputy_details_batch(neo4j_client: Neo4jClient, deputy_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Fetch details for multiple deputies in a single query."""
    cypher = """
    UNWIND $ids AS did
    MATCH (d:Deputy {id: did})
    OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
    WHERE mc.end_date IS NULL OR mc.end_date >= date()
    WITH d, collect(c.name) AS committees

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
    WITH d, committees,
         president_roles + vice_roles + secretary_roles AS all_roles

    RETURN d.id AS id,
           d.first_name AS first_name,
           d.last_name AS last_name,
           d.profession AS profession,
           d.education AS education,
           d.deputy_card AS camera_profile_url,
           d.photo AS photo,
           committees,
           CASE WHEN size(all_roles) > 0 THEN all_roles[0] ELSE null END AS institutional_role
    """
    details: Dict[str, Dict[str, Any]] = {}
    with neo4j_client.session() as session:
        result = session.run(cypher, ids=deputy_ids)
        for record in result:
            details[record["id"]] = dict(record)
    return details


@router.post("/authority-ranking")
async def authority_ranking(request: RankingRequest):
    """Rank all deputies by authority on a given topic (cached per topic)."""
    cache_key = " ".join(request.topic.lower().split())

    cached = _ranking_cache.get(cache_key)
    if cached is not None:
        _ranking_cache.move_to_end(cache_key)
        logger.info(f"[RANKING] Cache hit for topic '{request.topic}'")
        return {**cached, "cached": True}

    # Share one computation among concurrent requests for the same topic
    task = _ranking_inflight.get(cache_key)
    if task is None:
        task = asyncio.create_task(_compute_ranking(request.topic))
        _ranking_inflight[cache_key] = task
        task.add_done_callback(lambda _t: _ranking_inflight.pop(cache_key, None))

    result = await asyncio.shield(task)

    _ranking_cache[cache_key] = result
    _ranking_cache.move_to_end(cache_key)
    while len(_ranking_cache) > _RANKING_CACHE_MAX:
        _ranking_cache.popitem(last=False)

    return result


async def _compute_ranking(topic: str) -> Dict[str, Any]:
    neo4j_client, retrieval_engine, authority_scorer = _get_services()
    coalition_logic = CoalitionLogic()

    t0 = time.time()

    # Embed in an executor: the OpenAI HTTP call is synchronous.
    query_embedding = await asyncio.get_running_loop().run_in_executor(
        None, lambda: retrieval_engine.embed_query(topic)
    )
    logger.info(f"[RANKING] Embedded topic in {(time.time()-t0)*1000:.0f}ms")

    deputy_ids = await asyncio.get_running_loop().run_in_executor(
        None, _fetch_all_deputy_ids, neo4j_client
    )
    logger.info(f"[RANKING] Found {len(deputy_ids)} deputies")

    t1 = time.time()

    def _compute_single(sid: str):
        return sid, authority_scorer.compute_authority(sid, query_embedding)

    loop = asyncio.get_running_loop()
    with ThreadPoolExecutor(max_workers=min(20, max(1, len(deputy_ids)))) as pool:
        futures = [loop.run_in_executor(pool, _compute_single, sid) for sid in deputy_ids]
        results = await asyncio.gather(*futures)

    logger.info(f"[RANKING] Authority scores computed in {(time.time()-t1)*1000:.0f}ms")

    t2 = time.time()
    details_map = await asyncio.get_running_loop().run_in_executor(
        None, _fetch_deputy_details_batch, neo4j_client, deputy_ids
    )
    logger.info(f"[RANKING] Details fetched in {(time.time()-t2)*1000:.0f}ms")

    deputies = []
    for sid, auth_result in results:
        details = details_map.get(sid, {})
        if not details:
            continue

        components = auth_result.get("components", {})
        group = auth_result.get("current_group", "MISTO")

        deputies.append({
            "id": sid,
            "first_name": details.get("first_name", ""),
            "last_name": details.get("last_name", ""),
            "group": group,
            "coalition": coalition_logic.get_coalition(group),
            "authority_score": round(auth_result["total_score"], 4),
            "score_breakdown": {
                "speeches": round(components.get("interventions", 0), 4),
                "acts": round(components.get("acts", 0), 4),
                "committee": round(components.get("committee", 0), 4),
                "profession": round(components.get("profession", 0), 4),
                "education": round(components.get("education", 0), 4),
                "role": round(components.get("role", 0), 4),
            },
            "photo": details.get("photo"),
            "camera_profile_url": details.get("camera_profile_url"),
            "profession": details.get("profession"),
            "education": details.get("education"),
            "committee": details.get("committees", [None])[0] if details.get("committees") else None,
            "committees": details.get("committees", []),
            "institutional_role": auth_result.get("institutional_role") or details.get("institutional_role"),
        })

    deputies.sort(key=lambda d: d["authority_score"], reverse=True)

    total_time = time.time() - t0
    logger.info(f"[RANKING] Total time: {total_time*1000:.0f}ms for {len(deputies)} deputies")

    return {
        "topic": topic,
        "count": len(deputies),
        "computation_time_ms": round(total_time * 1000),
        "deputies": deputies,
    }
