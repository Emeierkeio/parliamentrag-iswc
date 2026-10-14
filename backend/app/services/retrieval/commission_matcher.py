"""
Commission topic matching for query analysis.

Identifies relevant parliamentary commissions based on query keywords
and semantic similarity.
"""
import logging
import os
from typing import List, Dict, Any, Tuple
import yaml

logger = logging.getLogger(__name__)


class CommissionMatcher:
    """
    Matches queries to relevant parliamentary commissions.

    Uses keyword matching and optional semantic similarity
    to identify which commissions are most relevant to a query.
    """

    def __init__(self):
        """Initialize with commission topic mapping from YAML."""
        self.commissioni: Dict[str, Dict] = {}
        self._load_config()

    def _load_config(self) -> None:
        """Load commission topics from YAML config."""
        # 3 levels above retrieval/ = backend/ (same as components.py:341).
        # With 4 levels the path pointed outside the backend → load failed
        # silently and commissions were always empty (observed 2026-07-24).
        config_path = os.path.join(
            os.path.dirname(__file__),
            "../../../config/commissioni_topics.yaml"
        )

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
                self.commissioni = config.get("commissioni", {})
                logger.info(f"Loaded {len(self.commissioni)} commission mappings")
        except Exception as e:
            logger.error(f"Failed to load commissioni_topics.yaml: {e}")
            self.commissioni = {}

    def _normalize_for_matching(self, text: str) -> str:
        """
        Normalize text for fuzzy matching.

        Handles Italian word variations (sanitario/sanità, etc.)
        """
        text = text.lower()
        # Common Italian suffixes/variations
        normalizations = [
            ("sanitari", "sanit"),  # sanitario, sanitaria, sanitari → sanit
            ("salute", "salut"),
            ("sanità", "sanit"),
            ("lavoro", "lavor"),
            ("lavorator", "lavor"),
            ("giustizia", "giustiz"),
            ("giudiziario", "giudiz"),
            ("ambiente", "ambient"),
            ("ambientale", "ambient"),
            ("difesa", "difes"),
            ("immigrazion", "immigr"),
            ("migrant", "migr"),
            ("scuola", "scuol"),
            ("scolastic", "scol"),
            ("istruzion", "istruz"),
            ("educazion", "educ"),
        ]
        for suffix, stem in normalizations:
            if suffix in text:
                text = text.replace(suffix, stem)
        return text

    def find_relevant_commissions(
        self,
        query: str,
        top_k: int = 3,
        min_score: float = 0.1
    ) -> List[Dict[str, Any]]:
        """
        Find commissions relevant to a query.

        Args:
            query: User query text
            top_k: Maximum number of commissions to return
            min_score: Minimum relevance score threshold

        Returns:
            List of relevant commissions with scores
        """
        query_lower = query.lower()
        query_normalized = self._normalize_for_matching(query)
        results: List[Tuple[str, float, List[str]]] = []

        for commission_name, data in self.commissioni.items():
            keywords = data.get("keywords", [])

            matched_keywords = []
            query_words = set(query_normalized.split())

            for kw in keywords:
                kw_lower = kw.lower()
                kw_normalized = self._normalize_for_matching(kw)
                kw_words = kw_normalized.split()

                # Try exact substring match in query
                if kw_lower in query_lower:
                    matched_keywords.append(kw)
                # Try word-level normalized match (avoid "riforma" matching "formazione")
                elif any(kw_word in query_words or
                        any(kw_word in qw or qw in kw_word for qw in query_words if len(qw) >= 4)
                        for kw_word in kw_words if len(kw_word) >= 4):
                    matched_keywords.append(kw)

            if matched_keywords:
                # Score on the absolute number of matches: dividing by the
                # total keyword count punished commissions with a rich
                # vocabulary (18 keywords → one exact match scored 0.06 and
                # fell below min_score). One exact match is already a strong
                # signal.
                score = min(1.0, 0.5 + 0.2 * (len(matched_keywords) - 1))
                results.append((commission_name, score, matched_keywords))

        results.sort(key=lambda x: x[1], reverse=True)

        output = []
        for name, score, matched in results[:top_k]:
            if score >= min_score:
                data = self.commissioni.get(name, {})
                output.append({
                    "nome": name,
                    "score": round(score, 2),
                    "matched_keywords": matched,
                    "categories": data.get("topic_categories", []),
                    "all_keywords": data.get("keywords", [])[:5],  # Limit for display
                })

        logger.info(f"Commission matching: query='{query[:50]}...' → {len(output)} commissions found")
        for comm in output:
            logger.info(f"  - {comm['nome'][:60]}... (score={comm['score']}, keywords={comm['matched_keywords']})")

        return output

    def get_commission_for_topic(self, topic: str) -> List[str]:
        """
        Get commission names that handle a specific topic category.

        Args:
            topic: Topic category (e.g., "health", "immigration")

        Returns:
            List of commission names
        """
        matches = []
        for name, data in self.commissioni.items():
            categories = data.get("topic_categories", [])
            if topic in categories:
                matches.append(name)
        return matches


# Singleton instance
_commission_matcher: CommissionMatcher = None


def get_commission_matcher() -> CommissionMatcher:
    """Get or create singleton CommissionMatcher instance."""
    global _commission_matcher
    if _commission_matcher is None:
        _commission_matcher = CommissionMatcher()
    return _commission_matcher
