"""
Channel merger for dual-channel retrieval.

Merges results from dense and graph channels with:
- Relevance weighting
- Diversity (penalize same-speaker dominance)
- Party coverage
- Authority-aware reweighting
"""
import logging
from typing import List, Dict, Any, Set, Optional
from collections import defaultdict

from ...config import get_config

logger = logging.getLogger(__name__)


class ChannelMerger:
    """
    Merges results from multiple retrieval channels.

    Ensures:
    - High relevance scores are preserved
    - Speaker diversity (no single speaker dominance)
    - Party coverage (all parties represented if possible)
    - Authority-aware reweighting (optional)
    """

    def __init__(self):
        self.config = get_config()

    def merge(
        self,
        dense_results: List[Dict[str, Any]],
        graph_results: List[Dict[str, Any]],
        authority_scores: Optional[Dict[str, float]] = None,
        top_k: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Merge results from dense and graph channels.

        Returns:
            Merged and reranked results
        """
        merger_config = self.config.retrieval.get("merger", {})

        relevance_weight = merger_config.get("relevance_weight", 0.15)
        diversity_weight = merger_config.get("diversity_weight", 0.15)
        coverage_weight = merger_config.get("coverage_weight", 0.25)
        authority_weight = merger_config.get("authority_weight", 0.25)
        salience_weight = merger_config.get("salience_weight", 0.20)

        logger.info(
            f"Merging {len(dense_results)} dense + {len(graph_results)} graph results"
        )

        all_results = self._deduplicate(dense_results, graph_results)
        logger.info(f"After deduplication: {len(all_results)} unique results")

        scored_results = self._compute_scores(
            all_results,
            authority_scores,
            relevance_weight,
            diversity_weight,
            coverage_weight,
            authority_weight,
            salience_weight
        )

        final_results = self._select_diverse(scored_results, top_k)

        self._log_coverage(final_results)

        return final_results

    def _deduplicate(
        self,
        dense_results: List[Dict[str, Any]],
        graph_results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Deduplicate results by evidence_id, keeping higher similarity.
        """
        seen: Dict[str, Dict[str, Any]] = {}

        for result in dense_results:
            eid = result.get("evidence_id", "")
            if eid and (eid not in seen or result.get("similarity", 0) > seen[eid].get("similarity", 0)):
                seen[eid] = result

        for result in graph_results:
            eid = result.get("evidence_id", "")
            if eid and eid not in seen:
                seen[eid] = result

        return list(seen.values())

    def _compute_scores(
        self,
        results: List[Dict[str, Any]],
        authority_scores: Optional[Dict[str, float]],
        relevance_weight: float,
        diversity_weight: float,
        coverage_weight: float,
        authority_weight: float,
        salience_weight: float = 0.20
    ) -> List[Dict[str, Any]]:
        """Compute final scores for all results."""
        speaker_counts: Dict[str, int] = defaultdict(int)
        party_counts: Dict[str, int] = defaultdict(int)

        for r in results:
            speaker_counts[r.get("speaker_id", "")] += 1
            party_counts[r.get("party", "")] += 1

        max_speaker_count = max(speaker_counts.values()) if speaker_counts else 1
        max_party_count = max(party_counts.values()) if party_counts else 1

        for result in results:
            relevance = result.get("similarity", 0.5)

            # Diversity penalty (reduce score for over-represented speakers)
            speaker_id = result.get("speaker_id", "")
            speaker_freq = speaker_counts.get(speaker_id, 1) / max_speaker_count
            diversity = 1.0 - (0.5 * speaker_freq)  # Soft penalty

            # Coverage bonus (increase score for under-represented parties)
            party = result.get("party", "MISTO")
            party_freq = party_counts.get(party, 1) / max_party_count
            coverage = 1.0 - (0.5 * party_freq)  # Soft bonus for rare parties

            authority = 0.5  # Default
            if authority_scores and speaker_id in authority_scores:
                authority = authority_scores[speaker_id]

            # Political salience score: citability stored at index time (Phase 1).
            # The regex fallback was removed (Phase 3): the whole corpus is
            # classified and the pipeline classifies at index time; a chunk
            # without a score is neutral (0.5).
            salience = result.get("salience")
            if salience is None:
                citability = result.get("citability_score")
                salience = float(citability) if citability is not None else 0.5
                result["salience"] = salience

            final_score = (
                relevance_weight * relevance +
                diversity_weight * diversity +
                coverage_weight * coverage +
                authority_weight * authority +
                salience_weight * salience
            )

            result["final_score"] = final_score
            result["score_components"] = {
                "relevance": relevance,
                "diversity": diversity,
                "coverage": coverage,
                "authority": authority,
                "salience": salience
            }

        return results

    def _select_diverse(
        self,
        results: List[Dict[str, Any]],
        top_k: int
    ) -> List[Dict[str, Any]]:
        """
        Select top_k results while ensuring diversity.

        Uses a greedy approach that balances score with diversity.
        """
        sorted_results = sorted(results, key=lambda x: x.get("final_score", 0), reverse=True)

        selected: List[Dict[str, Any]] = []
        speaker_selected: Dict[str, int] = defaultdict(int)
        party_selected: Dict[str, int] = defaultdict(int)

        max_per_speaker = top_k // 10  # Limit per speaker
        max_per_party = top_k // 3  # Softer limit per party

        for result in sorted_results:
            if len(selected) >= top_k:
                break

            speaker_id = result.get("speaker_id", "")
            party = result.get("party", "")

            if speaker_selected[speaker_id] >= max_per_speaker:
                continue
            if party_selected[party] >= max_per_party:
                # Still allow if score is very high
                if result.get("final_score", 0) < 0.8:
                    continue

            selected.append(result)
            speaker_selected[speaker_id] += 1
            party_selected[party] += 1

        # Minimum per-party quota (multi-view guarantee). The greedy pass has
        # a per-party maximum but no minimum: on niche topics the large groups
        # saturate the pool and the small ones reach the quote picker with 2-4
        # evidences → sections without citations even when the corpus has
        # excellent material (observed 2026-07-24 on 'remigrazione': Misto
        # with 2 evidences while the Futuro Nazionale component speaks about
        # it often and Magi has 22 substance chunks on the topic).
        # Top up from the party's best candidates, evicting the worst ones
        # from over-represented parties to stay at top_k.
        min_per_party = self.config.retrieval.get("merger", {}).get("min_per_party", 5)
        known_parties = set(self.config.get_all_parties())
        selected_ids = {r.get("evidence_id") for r in selected}
        remaining_by_party: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for r in sorted_results:
            if r.get("evidence_id") not in selected_ids and r.get("party", "") in known_parties:
                remaining_by_party[r.get("party", "")].append(r)

        for party in known_parties:
            while (party_selected[party] < min_per_party
                   and remaining_by_party.get(party)):
                candidate = remaining_by_party[party].pop(0)
                if speaker_selected[candidate.get("speaker_id", "")] >= max_per_speaker:
                    continue
                if len(selected) >= top_k:
                    # victim: the lowest-scoring selected item from a party
                    # that stays above the minimum quota even after removal
                    victim = next(
                        (r for r in reversed(selected)
                         if party_selected[r.get("party", "")] > min_per_party),
                        None,
                    )
                    if victim is None:
                        break  # no donor party: never exceed top_k
                    selected.remove(victim)
                    party_selected[victim.get("party", "")] -= 1
                    speaker_selected[victim.get("speaker_id", "")] -= 1
                selected.append(candidate)
                selected_ids.add(candidate.get("evidence_id"))
                party_selected[party] += 1
                speaker_selected[candidate.get("speaker_id", "")] += 1
                logger.info(
                    f"Min-quota top-up: aggiunto chunk di "
                    f"{candidate.get('speaker_name', '?')} per '{party}' "
                    f"({party_selected[party]}/{min_per_party})"
                )

        return selected

    def _log_coverage(self, results: List[Dict[str, Any]]):
        """Log coverage statistics."""
        parties_covered: Set[str] = set()
        speakers_covered: Set[str] = set()
        channels = defaultdict(int)

        for r in results:
            parties_covered.add(r.get("party", ""))
            speakers_covered.add(r.get("speaker_id", ""))
            channels[r.get("retrieval_channel", "unknown")] += 1

        all_parties = set(self.config.get_all_parties())
        missing_parties = all_parties - parties_covered

        logger.info(
            f"Coverage: {len(parties_covered)}/{len(all_parties)} parties, "
            f"{len(speakers_covered)} speakers"
        )
        if missing_parties:
            logger.warning(f"Missing parties: {missing_parties}")
        logger.info(f"Channel distribution: {dict(channels)}")
