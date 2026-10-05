"""Delete user-generated Neo4j nodes when the research retention period ends.

The privacy notice promises that questions, answers, feedback, surveys and
shared conversations are kept until DATA_RETENTION_UNTIL (Europe/Rome) and then
deleted. `purge` runs at startup and every 24 hours from the app lifespan;
after the cutoff the write endpoints answer 410 through `require_storage_open`,
so the daily run only has to clean up what was there before.

ParliamentRAG and Fascicoli write these labels into the same Neo4j database
and both run this purge: it only ever matches USER_LABELS, and every batch is
idempotent, so concurrent runs from either app or from several workers are safe.

    python -m app.services.retention --dry-run
"""

import argparse
import asyncio
import contextlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException

logger = logging.getLogger(__name__)

ROME = ZoneInfo("Europe/Rome")
BATCH = 1000
DAY_S = 24 * 3600
RETRIES = 3

# label -> creation timestamp property. Only these labels are ever matched:
# everything else in the graph is parliamentary data. SurveyEvaluation and
# SimpleRating point at ChatHistory by chat_id, so they go first.
# The timestamps are ISO strings (ChatHistory, SurveyEvaluation, SimpleRating)
# or Neo4j datetimes (UserFeedback, BoothSurvey): toString() of either starts
# with YYYY-MM-DD, which is all the day-granular max-age check needs.
USER_LABELS = {
    "SurveyEvaluation": "timestamp",
    "SimpleRating": "timestamp",
    "UserFeedback": "created_at",
    "BoothSurvey": "created_at",
    "ChatHistory": "timestamp",
}


def now() -> datetime:
    return datetime.now(ROME)


def _settings():
    from ..config import get_settings

    return get_settings()


@dataclass(frozen=True)
class Plan:
    """What to delete: every node, or only nodes created before `older_than`."""

    everything: bool
    older_than: Optional[datetime]

    @property
    def empty(self) -> bool:
        return not self.everything and self.older_than is None


def plan(at: Optional[datetime] = None) -> Plan:
    s = _settings()
    at = at or now()
    if at.astimezone(ROME).date() > s.data_retention_until:
        return Plan(everything=True, older_than=None)
    if s.data_retention_max_days is not None:
        return Plan(everything=False, older_than=at - timedelta(days=s.data_retention_max_days))
    return Plan(everything=False, older_than=None)


def storage_open(at: Optional[datetime] = None) -> bool:
    """Tell writers whether new user data may still be stored."""
    return not plan(at).everything


def require_storage_open() -> None:
    """FastAPI dependency for endpoints that store user data: 410 after the cutoff."""
    if not storage_open():
        raise HTTPException(status_code=410, detail="The research period has ended: new data is not stored.")


def _where(label: str) -> str:
    return f"$bound IS NULL OR substring(toString(n.{USER_LABELS[label]}), 0, 10) < $bound"


def _run(client, cypher: str, params: dict) -> list:
    for attempt in range(RETRIES):
        try:
            return client.query(cypher, params)
        except Exception:
            # A concurrent purge (the other app, another worker) may lock or
            # delete the same nodes: the batch is idempotent, so just retry it.
            if attempt == RETRIES - 1:
                raise
            time.sleep(1 + attempt)
    return []


def purge_sync(client, at: Optional[datetime] = None, dry_run: bool = False) -> dict[str, int]:
    """Delete (or only count, with dry_run) the user nodes outside the retention window."""
    p = plan(at)
    if p.empty:
        return {}
    bound = None if p.everything else p.older_than.astimezone(ROME).date().isoformat()
    counts: dict[str, int] = {}
    for label in USER_LABELS:
        where = _where(label)
        if dry_run:
            rows = _run(client, f"MATCH (n:{label}) WHERE {where} RETURN count(n) AS n", {"bound": bound})
            counts[label] = rows[0]["n"] if rows else 0
            continue
        total = 0
        while True:
            rows = _run(
                client,
                f"MATCH (n:{label}) WHERE {where} WITH n LIMIT $batch DETACH DELETE n RETURN count(*) AS deleted",
                {"bound": bound, "batch": BATCH},
            )
            deleted = rows[0]["deleted"] if rows else 0
            total += deleted
            if deleted < BATCH:
                break
        counts[label] = total
    reason = "retention period ended" if p.everything else f"older than {bound}"
    logger.info("retention purge (%s)%s: %s", reason, " dry-run" if dry_run else "", counts)
    return counts


async def run_daily(get_client) -> None:
    """Purge now and then every 24 hours until cancelled."""
    while True:
        try:
            await asyncio.to_thread(purge_sync, get_client())
        except Exception:
            logger.exception("retention purge failed, retrying in 24 hours")
        if not storage_open():
            logger.info(
                "retention period ended on %s: new user data is not stored",
                _settings().data_retention_until,
            )
        await asyncio.sleep(DAY_S)


async def stop(task: "asyncio.Task[None]") -> None:
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


def main() -> None:
    from .neo4j_client import Neo4jClient

    parser = argparse.ArgumentParser(description="Delete user data outside the retention window.")
    parser.add_argument("--dry-run", action="store_true", help="count the nodes, delete nothing")
    dry_run = parser.parse_args().dry_run

    s = _settings()
    client = Neo4jClient(uri=s.neo4j_uri, user=s.neo4j_user, password=s.neo4j_password)
    try:
        counts = purge_sync(client, dry_run=dry_run)
        after_cutoff = datetime.combine(s.data_retention_until + timedelta(days=1), datetime.min.time(), ROME)
        stored = purge_sync(client, at=after_cutoff, dry_run=True) if dry_run else {}
    finally:
        client.close()
    if plan().empty:
        print(f"nothing to purge now: data is kept until {s.data_retention_until} and DATA_RETENTION_MAX_DAYS is unset")
    for label, n in counts.items():
        print(f"{label}: {n} {'to delete' if dry_run else 'deleted'}")
    for label, n in stored.items():
        print(f"{label}: {n} stored, deleted after {s.data_retention_until}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    main()
