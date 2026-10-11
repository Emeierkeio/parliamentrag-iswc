"""
Authority scorer for query-dependent speaker authority.

Orchestrates all authority components and applies:
- Query-dependent weighting
- Temporal coalition logic
"""
import logging
from datetime import date
from typing import List, Dict, Any, Optional

from ..neo4j_client import Neo4jClient
from .coalition_logic import CoalitionLogic
from .components import (
    ProfessionComponent,
    EducationComponent,
    CommitteeComponent,
    ActsComponent,
    InterventionsComponent,
    RoleComponent,
    parse_neo4j_date,
)
from ...config import get_config

logger = logging.getLogger(__name__)

# Global bound on the heavy authority fetches (act/speech embeddings, up to
# ~10MB/tx): with several concurrent pipelines the per-pipeline ThreadPools
# added up and the Neo4j transaction pool (2.1GiB) saturated, failing whole
# tasks (observed 2026-07-24 with 2 simultaneous queries). The semaphore
# applies across ALL pipelines in the process.
import threading as _threading
_FETCH_SEMAPHORE = _threading.Semaphore(4)


class AuthorityScorer:
    """
    Computes query-dependent authority scores for speakers.

    Authority(speaker, query, date) = Σ wi × component_i

    Components:
    - Profession relevance (semantic similarity)
    - Education relevance (semantic similarity)
    - Committee membership (temporal + topic relevance)
    - Acts on topic (count with time decay)
    - Interventions on topic (count with time decay)
    - Institutional role (role weights)
    """

    def __init__(self, neo4j_client: Neo4jClient):
        self.client = neo4j_client
        self.config = get_config()
        self.coalition_logic = CoalitionLogic()

        self.components = {
            "profession": ProfessionComponent(),
            "education": EducationComponent(),
            "committee": CommitteeComponent(),
            "acts": ActsComponent(),
            "interventions": InterventionsComponent(),
            "role": RoleComponent(),
        }

        authority_config = self.config.load_config().get("authority", {})
        weights = authority_config.get("weights", {})

        self.weights = {
            "profession": weights.get("profession", 0.10),
            "education": weights.get("education", 0.10),
            "committee": weights.get("committee", 0.20),
            "acts": weights.get("acts", 0.25),
            "interventions": weights.get("interventions", 0.30),
            "role": weights.get("role", 0.05),
        }

    def compute_authority(
        self,
        speaker_id: str,
        query_embedding: List[float],
        reference_date: Optional[date] = None
    ) -> Dict[str, Any]:
        """
        Compute the authority score for a single speaker.

        Args:
            speaker_id: ID of the speaker (deputy or government member)
            query_embedding: Embedding of the query
            reference_date: Reference date (default: today)

        Returns:
            Dictionary with total score and component breakdown
        """
        if reference_date is None:
            reference_date = date.today()

        # A residual TransientError (transaction pool still saturated after
        # the retries) must NOT crash the calling pipeline: fall back to the
        # same default authority used for missing speakers.
        try:
            speaker_data = self._fetch_speaker_data(speaker_id, reference_date)
        except Exception as exc:
            logger.warning(f"Authority fetch failed for {speaker_id}: {exc}")
            speaker_data = None

        if not speaker_data:
            logger.warning(f"No data found for speaker {speaker_id}")
            return {
                "speaker_id": speaker_id,
                "total_score": 0.5,
                "components": {},
                "coalition": "unknown",
            }

        current_group = speaker_data.get("current_group", "MISTO")
        memberships = speaker_data.get("group_memberships", [])

        speaker_data["acts"] = self.coalition_logic.filter_activities_by_coalition(
            speaker_data.get("acts", []),
            memberships,
            reference_date,
            current_group
        )

        speaker_data["interventions"] = self.coalition_logic.filter_activities_by_coalition(
            speaker_data.get("interventions", []),
            memberships,
            reference_date,
            current_group
        )

        component_scores = {}
        for name, component in self.components.items():
            score = component.compute(speaker_data, query_embedding, reference_date)
            component_scores[name] = score

        total_score = sum(
            self.weights[name] * score
            for name, score in component_scores.items()
        )
        total_score = max(0.0, min(1.0, total_score))

        name = f"{speaker_data.get('first_name', '')} {speaker_data.get('last_name', '')}".strip()
        component_summary = "  ".join(
            f"{k}={v:.2f}(w={self.weights[k]:.2f})"
            for k, v in component_scores.items()
        )
        logger.debug(
            f"AuthorityScorer [{name or speaker_id}] total={total_score:.3f} | {component_summary}"
        )

        role_component = self.components.get("role")
        institutional_role = getattr(role_component, "matched_role_label", None)

        return {
            "speaker_id": speaker_id,
            "total_score": total_score,
            "components": component_scores,
            "coalition": self.coalition_logic.get_coalition(current_group),
            "current_group": current_group,
            "institutional_role": institutional_role,
        }

    def compute_all_authority(
        self,
        speaker_ids: List[str],
        query_embedding: List[float],
        reference_date: Optional[date] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """
        Compute authority scores for many speakers with parallel fetch and scoring.

        Two phases: per-speaker DB fetches on a 4-worker ThreadPoolExecutor
        (bounded further by the process-wide fetch semaphore), then CPU-side
        component scoring on a second 4-worker pool. Speakers whose fetch or
        scoring fails get the default result (total_score 0.5).

        Returns {speaker_id: full_authority_result_dict} for every requested
        speaker.
        """
        import time as _time
        from concurrent.futures import ThreadPoolExecutor, as_completed

        if reference_date is None:
            reference_date = date.today()

        if not speaker_ids:
            return {}

        _t0 = _time.perf_counter()

        # --- Step 1: parallel per-speaker DB fetch ---
        # UNWIND+CALL batch queries execute CALL iterations sequentially in Neo4j,
        # giving ~0.8s/speaker × 48 = 39s. Parallel individual queries let Neo4j
        # process up to max_workers speakers simultaneously → ~5-10s total.
        # max_workers 6→4: with 6 concurrent fetches the Neo4j transaction pool
        # (2.1GiB) saturated and ~5-20/46 speakers failed with
        # MemoryPoolOutOfMemoryError → default authority 0.5 and degraded party
        # ranking (observed 2026-07-23). Retry and the global bound live in
        # _fetch_speaker_data (they apply to every caller).
        all_data: Dict[str, Any] = {}
        with ThreadPoolExecutor(max_workers=min(4, max(1, len(speaker_ids)))) as db_pool:
            db_futures = {
                db_pool.submit(self._fetch_speaker_data, sid, reference_date): sid
                for sid in speaker_ids
            }
            for fut in as_completed(db_futures):
                sid = db_futures[fut]
                try:
                    data = fut.result()
                    if data:
                        all_data[sid] = data
                except Exception as exc:
                    logger.warning(f"DB fetch failed for {sid}: {exc}")

        _t_db = _time.perf_counter()
        logger.info(
            f"[AUTHORITY] DB parallel fetch: {len(all_data)}/{len(speaker_ids)} speakers "
            f"in {(_t_db - _t0)*1000:.0f}ms"
        )

        # Default result for speakers not found in DB
        results: Dict[str, Dict[str, Any]] = {
            sid: {
                "speaker_id": sid,
                "total_score": 0.5,
                "components": {},
                "coalition": "unknown",
            }
            for sid in speaker_ids
            if sid not in all_data
        }

        # --- Step 2: parallel CPU-side component scoring ---
        def _score_speaker(sid: str) -> tuple:
            speaker_data = dict(all_data[sid])  # shallow copy, avoids cross-thread mutation
            current_group = speaker_data.get("current_group", "MISTO")
            memberships = speaker_data.get("group_memberships") or []

            speaker_data["acts"] = self.coalition_logic.filter_activities_by_coalition(
                speaker_data.get("acts") or [], memberships, reference_date, current_group
            )
            speaker_data["interventions"] = self.coalition_logic.filter_activities_by_coalition(
                speaker_data.get("interventions") or [], memberships, reference_date, current_group
            )

            component_scores = {}
            for name, component in self.components.items():
                component_scores[name] = component.compute(
                    speaker_data, query_embedding, reference_date
                )

            total_score = max(
                0.0,
                min(1.0, sum(self.weights[n] * s for n, s in component_scores.items())),
            )

            name_str = (
                f"{speaker_data.get('first_name', '')} {speaker_data.get('last_name', '')}".strip()
            )
            component_summary = "  ".join(
                f"{k}={v:.2f}(w={self.weights[k]:.2f})" for k, v in component_scores.items()
            )
            logger.debug(
                f"AuthorityScorer [{name_str or sid}] total={total_score:.3f} | {component_summary}"
            )

            role_component = self.components.get("role")
            institutional_role = getattr(role_component, "matched_role_label", None)

            return sid, {
                "speaker_id": sid,
                "total_score": total_score,
                "components": component_scores,
                "coalition": self.coalition_logic.get_coalition(current_group),
                "current_group": current_group,
                "institutional_role": institutional_role,
            }

        # Cap CPU-scoring workers at 4: compute_all_authority runs inside
        # asyncio's run_in_executor, so K concurrent requests would create
        # K×n_workers threads for scoring.
        n_workers = min(4, max(1, len(all_data)))
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(_score_speaker, sid): sid for sid in all_data}
            for future in as_completed(futures):
                sid = futures[future]
                try:
                    _, result = future.result()
                    results[sid] = result
                except Exception as exc:
                    logger.error(f"Authority scoring failed for {sid}: {exc}")
                    results[sid] = {
                        "speaker_id": sid,
                        "total_score": 0.5,
                        "components": {},
                        "coalition": "unknown",
                    }

        _t_cpu = _time.perf_counter()
        logger.info(
            f"[AUTHORITY] CPU scoring: {len(results)} speakers "
            f"in {(_t_cpu - _t_db)*1000:.0f}ms | "
            f"total {(_t_cpu - _t0)*1000:.0f}ms"
        )

        return results

    def _fetch_speaker_data(
        self,
        speaker_id: str,
        reference_date: date,
        retries: int = 2,
    ) -> Optional[Dict[str, Any]]:
        """Fetch speaker data with global concurrency bound + transient retry.

        The global semaphore limits the heavy fetches across ALL concurrent
        pipelines; the retry covers residual MemoryPoolOutOfMemoryErrors
        (transient: by the retry, concurrent transactions have freed memory).
        Applies to every caller (batch pool AND compute_authority).
        """
        import time as _t
        from neo4j.exceptions import TransientError

        for attempt in range(retries + 1):
            try:
                with _FETCH_SEMAPHORE:
                    return self._fetch_speaker_data_once(speaker_id, reference_date)
            except TransientError:
                if attempt == retries:
                    raise
                _t.sleep(0.8 * (attempt + 1))
        return None

    def _fetch_speaker_data_once(
        self,
        speaker_id: str,
        reference_date: date
    ) -> Optional[Dict[str, Any]]:
        """Fetch all data needed to score a speaker, trying Deputy then GovernmentMember."""
        cypher = """
        MATCH (d:Deputy {id: $speaker_id})
        OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        WITH d, collect({
            group: g.name,
            start_date: mg.start_date,
            end_date: mg.end_date
        }) AS group_memberships

        OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
        WITH d, group_memberships, collect({
            committee_name: c.name,
            committee_embedding: c.embedding,
            start_date: mc.start_date,
            end_date: mc.end_date
        }) AS committee_memberships

        // Institutional roles (president, vice president, secretary of committees)
        OPTIONAL MATCH (d)-[rp:IS_PRESIDENT]->(cp:Committee)
        WITH d, group_memberships, committee_memberships, collect({
            role_type: 'president',
            committee_name: cp.name,
            committee_embedding: cp.embedding,
            start_date: rp.start_date,
            end_date: rp.end_date
        }) AS president_roles

        OPTIONAL MATCH (d)-[rv:IS_VICE_PRESIDENT]->(cv:Committee)
        WITH d, group_memberships, committee_memberships, president_roles, collect({
            role_type: 'vice_president',
            committee_name: cv.name,
            committee_embedding: cv.embedding,
            start_date: rv.start_date,
            end_date: rv.end_date
        }) AS vice_president_roles

        OPTIONAL MATCH (d)-[rs:IS_SECRETARY]->(cs:Committee)
        WITH d, group_memberships, committee_memberships, president_roles, vice_president_roles, collect({
            role_type: 'secretary',
            committee_name: cs.name,
            committee_embedding: cs.embedding,
            start_date: rs.start_date,
            end_date: rs.end_date
        }) AS secretary_roles

        // schema v2: official roles as properties on MEMBER_OF_COMMITTEE
        OPTIONAL MATCH (d)-[rm:MEMBER_OF_COMMITTEE]->(cm:Committee)
        WHERE rm.role IN ['president', 'vice_president', 'secretary']
        WITH d, group_memberships, committee_memberships, president_roles, vice_president_roles, secretary_roles, collect(
            CASE WHEN cm IS NOT NULL
                 THEN {role_type: rm.role, committee_name: cm.name,
                       committee_embedding: cm.embedding,
                       start_date: rm.start_date, end_date: rm.end_date}
            END
        ) AS v2_officer_roles

        WITH d, group_memberships, committee_memberships,
             president_roles + vice_president_roles + secretary_roles + v2_officer_roles AS institutional_roles

        CALL {
            WITH d
            OPTIONAL MATCH (d)-[ar:PRIMARY_SIGNATORY|CO_SIGNATORY]->(a:ParliamentaryAct)
            // Undated acts last: Neo4j sorts nulls first in DESC order
            WITH a, ar ORDER BY coalesce(a.presentation_date, date('1900-01-01')) DESC LIMIT 500
            RETURN collect(
                CASE WHEN a IS NOT NULL
                     THEN {uri: a.uri, date: a.presentation_date,
                           signatory_type: type(ar),
                           // Bills have an empty dc:description: fall back to the title
                           description_embedding: coalesce(a.description_embedding, a.title_embedding)}
                END
            ) AS acts
        }
        WITH d, group_memberships, committee_memberships, institutional_roles, acts

        // Memory bound (2026-07-23): without LIMIT this fetch materializes the
        // embeddings of EVERY speech of each speaker — with the v2 native lists
        // it OOMed the container twice. 300 recent speeches are enough for
        // topic relevance and cap the transfer at ~15MB/speaker.
        CALL {
            WITH d
            OPTIONAL MATCH (i:Speech)-[:SPOKEN_BY]->(d)
            OPTIONAL MATCH (i)<-[:CONTAINS_SPEECH]-(:Phase)<-[:HAS_PHASE]-(:Debate)<-[:HAS_DEBATE]-(s:Session)
            WHERE s.date >= date() - duration({years: 4})
            WITH i, s ORDER BY s.date DESC LIMIT 300
            RETURN collect(
                CASE WHEN i IS NOT NULL
                     THEN {speech_id: i.id, date: s.date, text_embedding: i.text_embedding}
                END
            ) AS interventions
        }
        WITH d, group_memberships, committee_memberships, institutional_roles, acts, interventions

        RETURN d.id AS speaker_id,
               d.first_name AS first_name,
               d.last_name AS last_name,
               d.profession_embedding AS profession_embedding,
               d.education_embedding AS education_embedding,
               group_memberships,
               committee_memberships,
               institutional_roles,
               acts,
               interventions
        """

        with self.client.session() as session:
            result = session.run(cypher, speaker_id=speaker_id)
            record = result.single()

            if record:
                data = dict(record)

                current_group = "MISTO"
                for membership in data.get("group_memberships", []):
                    start = parse_neo4j_date(membership.get("start_date"))
                    end = parse_neo4j_date(membership.get("end_date"))

                    if start and start <= reference_date:
                        if not end or end >= reference_date:
                            current_group = membership.get("group", "MISTO")
                            break

                data["current_group"] = current_group
                return data

        cypher_gov = """
        MATCH (m:GovernmentMember {id: $speaker_id})
        OPTIONAL MATCH (i:Speech)-[:SPOKEN_BY]->(m)
        OPTIONAL MATCH (i)<-[:CONTAINS_SPEECH]-(:Phase)<-[:HAS_PHASE]-(:Debate)<-[:HAS_DEBATE]-(s:Session)
        WITH m, collect({
            speech_id: i.id,
            date: s.date
        }) AS interventions

        RETURN m.id AS speaker_id,
               m.first_name AS first_name,
               m.last_name AS last_name,
               m.institutional_role AS government_position,
               [] AS group_memberships,
               [] AS committee_memberships,
               [] AS institutional_roles,
               [] AS acts,
               interventions
        """

        with self.client.session() as session:
            result = session.run(cypher_gov, speaker_id=speaker_id)
            record = result.single()

            if record:
                data = dict(record)
                # Government members are always "maggioranza" by definition
                data["current_group"] = "GOVERNO"
                return data

        return None
