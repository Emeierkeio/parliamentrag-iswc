"""
Authority score components.

Each component contributes to the overall authority score.
All scores are normalized to [0, 1] using percentile-based normalization.
"""
import json
import math
import logging
import threading
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import List, Dict, Any, Optional, Union

import numpy as np

from ...config import get_config

logger = logging.getLogger(__name__)


def parse_neo4j_date(date_value: Any) -> Optional[date]:
    """
    Parse a date value from Neo4j to Python date.

    Neo4j may return dates as:
    - neo4j.time.Date objects
    - Strings in DD/MM/YYYY or YYYYMMDD format
    - Float/int values like 20250612.0
    - datetime.date objects
    - None
    """
    if date_value is None:
        return None

    if isinstance(date_value, date):
        return date_value

    # Neo4j Date object
    if hasattr(date_value, 'to_native'):
        return date_value.to_native()

    # Numeric YYYYMMDD, e.g. 20250612.0 or 20250612
    if isinstance(date_value, (float, int)):
        try:
            date_str = str(int(date_value))
            if len(date_str) == 8:
                return datetime.strptime(date_str, "%Y%m%d").date()
        except (ValueError, OverflowError):
            pass
        logger.warning(f"Could not parse date number: {date_value}")
        return None

    if isinstance(date_value, str):
        if not date_value.strip():
            return None

        # Drop a decimal part if present, e.g. "20250612.0" -> "20250612"
        date_str = date_value.split('.')[0].strip()

        for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%Y%m%d"):
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue
        logger.warning(f"Could not parse date string: {date_value}")
        return None

    logger.warning(f"Unknown date type: {type(date_value)} - {date_value}")
    return None


def parse_embedding(embedding_value: Any) -> Optional[List[float]]:
    """
    Parse an embedding value from Neo4j to a list of floats.

    Neo4j may return embeddings as:
    - List of floats (pass through)
    - JSON string representation of a list
    - String representation with brackets
    - None
    """
    if embedding_value is None:
        return None

    if isinstance(embedding_value, list):
        try:
            return [float(x) for x in embedding_value]
        except (ValueError, TypeError):
            logger.warning(f"Could not convert list to floats: {type(embedding_value)}")
            return None

    if isinstance(embedding_value, np.ndarray):
        return embedding_value.tolist()

    if isinstance(embedding_value, str):
        if not embedding_value.strip():
            return None

        try:
            parsed = json.loads(embedding_value)
            if isinstance(parsed, list):
                return [float(x) for x in parsed]
        except json.JSONDecodeError:
            pass

        # Last resort: Python list repr (single quotes etc. break json.loads)
        try:
            cleaned = embedding_value.strip()
            if cleaned.startswith('[') and cleaned.endswith(']'):
                import ast
                parsed = ast.literal_eval(cleaned)
                if isinstance(parsed, list):
                    return [float(x) for x in parsed]
        except (ValueError, SyntaxError):
            pass

        logger.warning(f"Could not parse embedding string (length {len(embedding_value)})")
        return None

    logger.warning(f"Unknown embedding type: {type(embedding_value)}")
    return None


def cosine_similarity(vec1: Union[List[float], Any], vec2: Union[List[float], Any]) -> float:
    """Compute cosine similarity between two vectors, parsing raw DB values as needed."""
    v1 = parse_embedding(vec1) if not isinstance(vec1, list) or (vec1 and not isinstance(vec1[0], (int, float))) else vec1
    v2 = parse_embedding(vec2) if not isinstance(vec2, list) or (vec2 and not isinstance(vec2[0], (int, float))) else vec2

    if not v1 or not v2:
        return 0.0

    a = np.array(v1, dtype=np.float64)
    b = np.array(v2, dtype=np.float64)

    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)

    if norm_a == 0 or norm_b == 0:
        return 0.0

    return float(dot_product / (norm_a * norm_b))


def time_decay(days_ago: int, half_life_days: int) -> float:
    """
    Compute exponential time decay.

    Args:
        days_ago: Number of days since the activity
        half_life_days: Half-life in days

    Returns:
        Decay factor in [0, 1]
    """
    if days_ago < 0:
        return 1.0

    lambda_decay = math.log(2) / half_life_days
    return math.exp(-lambda_decay * days_ago)


class AuthorityComponent(ABC):
    """Base class for authority score components."""

    def __init__(self):
        self.config = get_config()
        self.max_contribution = self.config.load_config().get(
            "authority", {}
        ).get("max_component_contribution", 0.8)

    @abstractmethod
    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        """
        Compute component score.

        Args:
            speaker_data: Speaker data from database
            query_embedding: Query embedding vector
            reference_date: Reference date for temporal calculations

        Returns:
            Score in [0, 1]
        """
        pass

    def cap_score(self, score: float) -> float:
        """Cap score to max contribution."""
        return min(score, self.max_contribution)


class ProfessionComponent(AuthorityComponent):
    """
    Profession relevance component.

    Computes semantic similarity between query and speaker's profession.
    """

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        profession_embedding = parse_embedding(speaker_data.get("profession_embedding"))

        if not profession_embedding:
            # No profession data recorded → no evidence of expertise → 0 contribution.
            # Returning 0.5 was misleading (UI showed "Non rilevata" at 50%).
            return 0.0

        similarity = cosine_similarity(query_embedding, profession_embedding)
        # Map from [-1, 1] to [0, 1]
        score = (similarity + 1) / 2

        return self.cap_score(score)


class EducationComponent(AuthorityComponent):
    """
    Education relevance component.

    Computes semantic similarity between query and speaker's education.
    """

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        education_embedding = parse_embedding(speaker_data.get("education_embedding"))

        if not education_embedding:
            # No education data recorded → no evidence of academic expertise → 0 contribution.
            return 0.0

        similarity = cosine_similarity(query_embedding, education_embedding)
        # Map from [-1, 1] to [0, 1]
        score = (similarity + 1) / 2

        return self.cap_score(score)


class CommitteeComponent(AuthorityComponent):
    """
    Committee membership component.

    Computes score based on:
    - Temporal membership validity
    - Topic relevance of committee to query

    Relevance is computed in two stages:
    1. PRIMARY: cosine similarity between query and the committee's YAML topic keywords
       (cached per committee name after first API call).  The keyword text is far
       richer than the committee name alone, giving much better discrimination for
       short queries like "Salario minimo" vs "XI COMMISSIONE (LAVORO PUBBLICO E PRIVATO)".
    2. FALLBACK: cosine similarity with the committee name embedding stored in Neo4j
       (used for committees not listed in commissioni_topics.yaml).
    """

    # Class-level caches shared across all instances (process lifetime)
    _keyword_embedding_cache: Dict[str, Optional[List[float]]] = {}
    _yaml_cache: Optional[Dict[str, Any]] = None
    _cache_lock = threading.Lock()

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        memberships = speaker_data.get("committee_memberships", [])

        if not memberships:
            return 0.0

        committee_scores: List[tuple] = []  # (name, relevance)

        for membership in memberships:
            membership_start = parse_neo4j_date(membership.get("start_date"))
            membership_end = parse_neo4j_date(membership.get("end_date"))

            if membership_start and membership_start > reference_date:
                continue

            if membership_end and membership_end < reference_date:
                continue

            # Committee is active at reference_date — compute topic relevance
            committee_name = membership.get("committee_name", "unknown")
            topic_relevance = self._compute_topic_relevance(membership, query_embedding)
            committee_scores.append((committee_name, topic_relevance))

            logger.debug(
                f"CommitteeComponent: {committee_name!r} relevance={topic_relevance:.4f}"
            )

        if not committee_scores:
            return 0.0

        # Use MAX relevance — the best-matching committee defines authority.
        # Averaging would penalise deputies who happen to sit on many committees,
        # giving a lower score even though their membership in the relevant
        # committee is just as valid.
        best_name, score = max(committee_scores, key=lambda x: x[1])
        logger.debug(
            f"CommitteeComponent: best={best_name!r} score={score:.4f} "
            f"(max of {len(committee_scores)} active committees)"
        )

        return self.cap_score(score)

    def _load_yaml(self) -> Dict[str, Any]:
        """Load and cache commissioni_topics.yaml at the class level."""
        if CommitteeComponent._yaml_cache is not None:
            return CommitteeComponent._yaml_cache

        import yaml
        import os
        config_path = os.path.join(
            os.path.dirname(__file__),
            "../../../config/commissioni_topics.yaml"
        )
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            logger.warning(f"Commission topics config not found: {config_path}")
            data = None
        except yaml.YAMLError as exc:
            logger.warning(f"Commission topics config is invalid YAML: {exc}")
            data = None

        # safe_load returns None for an empty file; callers expect a dict.
        if not isinstance(data, dict):
            if data is not None:
                logger.warning(
                    f"Commission topics config is not a mapping: {type(data).__name__}"
                )
            data = {}

        with self._cache_lock:
            CommitteeComponent._yaml_cache = data
        return data

    def _compute_topic_relevance(
        self,
        membership: Dict[str, Any],
        query_embedding: List[float]
    ) -> float:
        """Compute topic relevance between committee and query.

        PRIMARY path: embed the committee's YAML keyword text and compare with
        the query embedding.  Keywords like "lavoro occupazione contratti sindacati"
        are far more discriminative than the committee name alone, especially for
        short queries ("Salario minimo" vs "XI COMMISSIONE (LAVORO PUBBLICO E PRIVATO)").

        FALLBACK: if the committee is not in the YAML, use the stored Neo4j embedding
        of the committee name.
        """
        committee_name = membership.get("committee_name", "")

        # --- PRIMARY: YAML keyword embedding ---
        topics_config = self._load_yaml()
        commissioni = topics_config.get("commissioni", {})
        commission_data = commissioni.get(committee_name, {})

        if not commission_data:
            # Try partial name match (handles minor name variations)
            for name, data in commissioni.items():
                if committee_name in name or name in committee_name:
                    commission_data = data
                    committee_name = name  # use canonical name for cache key
                    break

        if commission_data:
            keywords = commission_data.get("keywords", [])
            if keywords:
                kw_embedding = self._get_cached_keyword_embedding(committee_name, keywords)
                if kw_embedding:
                    similarity = cosine_similarity(query_embedding, kw_embedding)
                    return max(0.0, similarity)
                # API unavailable but committee is in YAML → moderate default
                return 0.4

        # --- FALLBACK: committee name embedding stored in Neo4j ---
        committee_embedding = parse_embedding(membership.get("committee_embedding"))
        if committee_embedding:
            similarity = cosine_similarity(query_embedding, committee_embedding)
            return max(0.0, similarity)

        return 0.2  # Unknown committee, no embedding

    def _get_cached_keyword_embedding(
        self,
        committee_name: str,
        keywords: List[str]
    ) -> Optional[List[float]]:
        """Return (possibly cached) embedding for the committee's keyword text.

        Uses the same model as query embeddings (text-embedding-3-small) so that
        cosine similarity is semantically meaningful.  Result is stored in a
        class-level dict to survive across multiple authority computations.
        """
        if committee_name in self._keyword_embedding_cache:
            return self._keyword_embedding_cache[committee_name]

        keyword_text = " ".join(keywords)
        embedding: Optional[List[float]] = None
        try:
            from ...key_pool import make_client
            llm_config = self.config.load_config().get("llm", {})
            model = llm_config.get("embedding_model", "text-embedding-3-small")
            client = make_client()
            response = client.embeddings.create(input=keyword_text, model=model)
            embedding = response.data[0].embedding
            logger.debug(
                f"Cached keyword embedding for '{committee_name}' "
                f"({len(keywords)} keywords, model={model})"
            )
        except Exception as exc:
            logger.warning(
                f"Could not embed keywords for committee '{committee_name}': {exc}"
            )

        with self._cache_lock:
            self._keyword_embedding_cache[committee_name] = embedding

        return embedding


class ActsComponent(AuthorityComponent):
    """
    Parliamentary acts component.

    Contribution per act:
        role_weight × time_decay × topic_relevance

    Where:
    - role_weight:    1.0 for PRIMARY_SIGNATORY, 0.3 for CO_SIGNATORY
    - time_decay:     exponential decay (half_life = acts_half_life_days)
    - topic_relevance: cosine similarity(query, act.description_embedding,
                      or the title embedding when the act has no
                      description, as bills do) if the similarity is
                      >= acts_relevance_threshold; 0.5 (neutral) for acts
                      without any embedding.

    Acts whose description similarity is below the threshold are skipped
    entirely — they are not topically relevant to the query.

    Normalization: log scale with ceiling at ~500 weighted units.
    """

    # Co-signatory counts much less than primary proposer.
    PRIMARY_WEIGHT = 1.0
    CO_SIGNATORY_WEIGHT = 0.3

    # Neutral relevance applied to acts that have no description_embedding.
    NO_EMBEDDING_RELEVANCE = 0.5

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        acts = speaker_data.get("acts", [])

        if not acts:
            return 0.0

        authority_config = self.config.load_config().get("authority", {})
        time_decay_config = authority_config.get("time_decay", {})
        half_life = time_decay_config.get("acts_half_life_days", 548)
        relevance_threshold = authority_config.get("acts_relevance_threshold", 0.25)

        total_weight = 0.0
        primary_count = 0
        co_count = 0
        relevant_count = 0
        skipped_count = 0
        no_emb_count = 0

        for act in acts:
            act_date = parse_neo4j_date(act.get("date"))
            if not act_date or act_date > reference_date:
                continue

            # --- Semantic relevance filter ---
            desc_embedding = parse_embedding(act.get("description_embedding"))
            if desc_embedding:
                similarity = cosine_similarity(query_embedding, desc_embedding)
                if similarity < relevance_threshold:
                    skipped_count += 1
                    continue
                topic_relevance = similarity
            else:
                # No embedding available — count with neutral relevance so
                # older/un-embedded acts don't silently vanish from the score.
                topic_relevance = self.NO_EMBEDDING_RELEVANCE
                no_emb_count += 1

            # --- Signatory weight ---
            signatory_type = act.get("signatory_type", "PRIMARY_SIGNATORY")
            role_weight = (
                self.PRIMARY_WEIGHT
                if signatory_type == "PRIMARY_SIGNATORY"
                else self.CO_SIGNATORY_WEIGHT
            )
            if signatory_type == "PRIMARY_SIGNATORY":
                primary_count += 1
            else:
                co_count += 1
            relevant_count += 1

            days_ago = (reference_date - act_date).days
            decay = time_decay(days_ago, half_life)
            total_weight += role_weight * decay * topic_relevance

        logger.debug(
            f"ActsComponent: relevant={relevant_count} skipped={skipped_count} "
            f"no_emb={no_emb_count} primary={primary_count} co={co_count} "
            f"total_weighted={total_weight:.2f} threshold={relevance_threshold}"
        )

        # Log scale — ceiling at 20 (calibrated on ~30 relevant acts, decay≈0.7, relevance≈0.4).
        # 500 was a theoretical max never reached in practice, compressing all scores to 0–25%.
        if total_weight > 0:
            score = math.log(1 + total_weight) / math.log(1 + 20)
            score = min(score, 1.0)
        else:
            score = 0.0

        return self.cap_score(score)


class InterventionsComponent(AuthorityComponent):
    """
    Parliamentary interventions component.

    Contribution per speech:
        time_decay × topic_relevance

    Where:
    - time_decay:      exponential decay (half_life = speeches_half_life_days)
    - topic_relevance: cosine similarity(query, speech.text_embedding)
                       if similarity >= interventions_relevance_threshold;
                       0.5 (neutral) for speeches without a text_embedding.

    Speech.text_embedding is computed by build/precalculate_embeddings.py Phase 5
    (first 2000 chars of the preprocessed speech text, via text-embedding-3-small).

    Speeches below the relevance threshold are skipped entirely.
    Normalization: log scale with ceiling at ~500 weighted units.
    """

    # Neutral relevance applied to speeches that have no text_embedding yet.
    NO_EMBEDDING_RELEVANCE = 0.5

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        interventions = speaker_data.get("interventions", [])

        if not interventions:
            return 0.0

        authority_config = self.config.load_config().get("authority", {})
        time_decay_config = authority_config.get("time_decay", {})
        half_life = time_decay_config.get("speeches_half_life_days", 180)
        relevance_threshold = authority_config.get("interventions_relevance_threshold", 0.25)

        total_weight = 0.0
        dated_count = 0
        relevant_count = 0
        skipped_count = 0
        no_emb_count = 0

        for intervention in interventions:
            intervention_date = parse_neo4j_date(intervention.get("date"))
            if not intervention_date or intervention_date > reference_date:
                continue

            dated_count += 1

            # --- Semantic relevance filter ---
            text_emb = parse_embedding(intervention.get("text_embedding"))
            if text_emb:
                similarity = cosine_similarity(query_embedding, text_emb)
                if similarity < relevance_threshold:
                    skipped_count += 1
                    continue
                topic_relevance = similarity
            else:
                # Embedding not yet computed — neutral relevance (legacy speeches).
                topic_relevance = self.NO_EMBEDDING_RELEVANCE
                no_emb_count += 1

            relevant_count += 1
            days_ago = (reference_date - intervention_date).days
            decay = time_decay(days_ago, half_life)
            total_weight += decay * topic_relevance

        logger.debug(
            f"InterventionsComponent: total={len(interventions)} dated={dated_count} "
            f"relevant={relevant_count} skipped={skipped_count} no_emb={no_emb_count} "
            f"weighted={total_weight:.2f} threshold={relevance_threshold}"
        )

        # Log scale — ceiling at 20 (calibrated on ~30 relevant speeches, decay≈0.6, relevance≈0.4).
        # 500 was a theoretical max never reached in practice, compressing all scores to 0–25%.
        if total_weight > 0:
            score = math.log(1 + total_weight) / math.log(1 + 20)
            score = min(score, 1.0)
        else:
            score = 0.0

        return self.cap_score(score)


class RoleComponent(AuthorityComponent):
    """
    Institutional role component.

    Computes score based on:
    1. Base role weight (president > vice_president > secretary)
    2. Topic relevance bonus if the committee is relevant to the query

    Formula: base_weight × (1 + relevance_bonus)
    """

    # Base weights for institutional roles in committees
    ROLE_BASE_WEIGHTS = {
        "president": 0.7,
        "vice_president": 0.5,
        "secretary": 0.4,
    }

    # Government position weights (for GovernmentMember)
    GOVERNMENT_WEIGHTS = {
        "ministro": 0.9,
        "viceministro": 0.8,
        "sottosegretario": 0.7,
    }

    # Relevance bonus multiplier when committee is topically relevant
    RELEVANCE_BONUS = 0.3

    # Similarity threshold for topic relevance
    RELEVANCE_THRESHOLD = 0.5

    # Human-readable labels for role types
    ROLE_LABELS = {
        "president": "Presidente",
        "vice_president": "Vicepresidente",
        "secretary": "Segretario",
    }

    def __init__(self):
        super().__init__()
        # Thread-local storage prevents race conditions when compute() is called
        # concurrently from multiple threads (via ThreadPoolExecutor in the scorer).
        self._local = threading.local()

    @property
    def matched_role_label(self) -> Optional[str]:
        return getattr(self._local, "_matched_role_label", None)

    @matched_role_label.setter
    def matched_role_label(self, value: Optional[str]) -> None:
        self._local._matched_role_label = value

    def compute(
        self,
        speaker_data: Dict[str, Any],
        query_embedding: List[float],
        reference_date: date
    ) -> float:
        self.matched_role_label = None

        # Government positions (GovernmentMember) take precedence over committee roles.
        gov_position = speaker_data.get("government_position", "")
        if gov_position:
            for key, weight in self.GOVERNMENT_WEIGHTS.items():
                if key in gov_position.lower():
                    self.matched_role_label = gov_position
                    return self.cap_score(weight)

        institutional_roles = [
            r for r in speaker_data.get("institutional_roles", [])
            if r.get("committee_name")
        ]

        if not institutional_roles:
            return 0.3  # Base score for regular deputies without roles

        max_role_score = 0.3  # Minimum base
        best_role_label = None

        for role in institutional_roles:
            role_type = role.get("role_type", "")
            role_start = parse_neo4j_date(role.get("start_date"))
            role_end = parse_neo4j_date(role.get("end_date"))

            if role_start and role_start > reference_date:
                continue
            if role_end and role_end < reference_date:
                continue

            base_weight = self.ROLE_BASE_WEIGHTS.get(role_type, 0.3)

            committee_embedding = role.get("committee_embedding")
            relevance_multiplier = 1.0

            if committee_embedding and query_embedding:
                similarity = cosine_similarity(query_embedding, committee_embedding)
                if similarity >= self.RELEVANCE_THRESHOLD:
                    # Bonus proportional to similarity
                    relevance_multiplier = 1.0 + (self.RELEVANCE_BONUS * similarity)

            role_score = base_weight * relevance_multiplier
            if role_score > max_role_score:
                max_role_score = role_score
                label = self.ROLE_LABELS.get(role_type, role_type)
                committee_name = role.get("committee_name", "")
                best_role_label = f"{label} {committee_name}" if committee_name else label

        self.matched_role_label = best_role_label
        return self.cap_score(max_role_score)
