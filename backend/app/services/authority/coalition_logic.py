"""
Temporal coalition logic for authority scoring.

Core rule: when a deputy crosses the maggioranza/opposizione boundary, their
prior authority contributions are invalidated.
"""
import logging
from datetime import date
from typing import List, Dict, Tuple

from .components import parse_neo4j_date
from ...config import get_config

logger = logging.getLogger(__name__)


class CoalitionLogic:
    """
    Handles temporal coalition membership and authority validity.

    Core principle: Authority earned while in one coalition does NOT
    carry over when switching to the opposing coalition.
    """

    def __init__(self):
        self.config = get_config()
        self._coalition_cache: Dict[str, str] = {}

    def get_coalition(self, group_name: str) -> str:
        """
        Get coalition for a parliamentary group.

        Args:
            group_name: Name of the parliamentary group

        Returns:
            "maggioranza" or "opposizione"
        """
        if not group_name:
            return "opposizione"

        if group_name in self._coalition_cache:
            return self._coalition_cache[group_name]

        coalitions = self.config.load_config().get("coalitions", {})

        # Government members are always in maggioranza
        if group_name.upper() in ("GOVERNO",):
            self._coalition_cache[group_name] = "maggioranza"
            return "maggioranza"
        # Normalize for comparison: uppercase + collapse whitespace around hyphens
        # DB may return "AZIONE-POPOLARI" while config has "Azione - Popolari"
        def normalize(name: str) -> str:
            return name.upper().replace(" - ", "-").replace("- ", "-").replace(" -", "-")

        from ...models.evidence import normalize_party_name

        # Senate group names map onto the same party as the Camera ones
        group_norm = normalize(normalize_party_name(group_name))

        for g in coalitions.get("maggioranza", []):
            if normalize(g) == group_norm:
                self._coalition_cache[group_name] = "maggioranza"
                return "maggioranza"

        for g in coalitions.get("opposizione", []):
            if normalize(g) == group_norm:
                self._coalition_cache[group_name] = "opposizione"
                return "opposizione"

        # Gruppo Misto: its own coalition — it cannot be assigned to one side,
        # as it contains politically opposed components.
        for g in coalitions.get("misto", []):
            if normalize(g) == group_norm:
                self._coalition_cache[group_name] = "misto"
                return "misto"

        # Default unknown groups to opposition
        logger.warning(f"Unknown group '{group_name}', defaulting to opposizione")
        self._coalition_cache[group_name] = "opposizione"
        return "opposizione"

    def authority_carries_over(
        self,
        old_group: str,
        new_group: str
    ) -> bool:
        """
        Check if authority from old_group is valid for new_group.

        Returns FALSE if crossing MAGGIORANZA ↔ OPPOSIZIONE boundary.

        Args:
            old_group: Previous parliamentary group
            new_group: Current parliamentary group

        Returns:
            True if authority carries over, False otherwise
        """
        old_coalition = self.get_coalition(old_group)
        new_coalition = self.get_coalition(new_group)

        if old_coalition == new_coalition:
            return True

        logger.info(
            f"Coalition crossing detected: {old_group} ({old_coalition}) → "
            f"{new_group} ({new_coalition}). Authority invalidated."
        )
        return False

    def get_valid_periods(
        self,
        memberships: List[Dict],
        reference_date: date,
        current_group: str
    ) -> List[Tuple[date, date, str]]:
        """
        Get time periods where authority contributions are valid.

        Only periods in the SAME coalition as current_group count.

        Args:
            memberships: List of group memberships with dates
                         [{"group": str, "start_date": date, "end_date": date}, ...]
            reference_date: Reference date for authority calculation
            current_group: Current parliamentary group of the speaker

        Returns:
            List of (start_date, end_date, group_name) tuples for valid periods
        """
        current_coalition = self.get_coalition(current_group)
        valid_periods = []

        for membership in memberships:
            group = membership.get("group", "")
            start = parse_neo4j_date(membership.get("start_date"))
            end = parse_neo4j_date(membership.get("end_date"))

            if not start:
                continue

            # Ongoing membership: cap at reference_date
            if not end or end > reference_date:
                end = reference_date

            if start > reference_date:
                continue

            if self.get_coalition(group) == current_coalition:
                valid_periods.append((start, end, group))
            else:
                logger.debug(
                    f"Excluding period {start} - {end} in {group} "
                    f"(coalition mismatch with current {current_group})"
                )

        return valid_periods

    def filter_activities_by_coalition(
        self,
        activities: List[Dict],
        memberships: List[Dict],
        reference_date: date,
        current_group: str
    ) -> List[Dict]:
        """
        Filter activities to only those in valid coalition periods.

        Args:
            activities: List of activities (interventions, acts, etc.)
                        Each must have a "date" field
            memberships: List of group memberships with dates
            reference_date: Reference date for authority calculation
            current_group: Current parliamentary group

        Returns:
            Filtered list of activities in valid coalition periods
        """
        valid_periods = self.get_valid_periods(
            memberships, reference_date, current_group
        )

        if not valid_periods:
            return []

        valid_activities = []
        for activity in activities:
            activity_date = parse_neo4j_date(activity.get("date"))
            if not activity_date:
                continue

            for start, end, _ in valid_periods:
                if start <= activity_date <= end:
                    valid_activities.append(activity)
                    break

        logger.debug(
            f"Coalition filter: {len(valid_activities)}/{len(activities)} "
            f"activities valid for coalition {self.get_coalition(current_group)}"
        )

        return valid_activities
