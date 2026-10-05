"""Retention purge on a fake Neo4j: cutoff, dry run, max age, batching, writers closed."""

import asyncio
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services import retention

ROME = retention.ROME
BEFORE = datetime(2027, 12, 31, 23, 30, tzinfo=ROME)
AFTER = datetime(2028, 1, 1, 0, 30, tzinfo=ROME)


class FakeNeo4j:
    """Interpret the purge queries over an in-memory {label: [props]} graph."""

    def __init__(self, graph: dict[str, list[dict]]):
        self.graph = graph
        self.cypher: list[str] = []

    def _matches(self, label: str, bound):
        prop = retention.USER_LABELS[label]
        return [n for n in self.graph.get(label, []) if bound is None or str(n[prop])[:10] < bound]

    def query(self, cypher: str, params: dict):
        self.cypher.append(cypher)
        label = re.match(r"MATCH \(n:(\w+)\)", cypher).group(1)
        found = self._matches(label, params["bound"])
        if "DETACH DELETE" not in cypher:
            return [{"n": len(found)}]
        gone = found[: params["batch"]]
        self.graph[label] = [n for n in self.graph[label] if n not in gone]
        return [{"deleted": len(gone)}]


def graph(n_chats: int = 3) -> dict[str, list[dict]]:
    return {
        "ChatHistory": [{"id": i, "timestamp": f"2026-0{i + 1}-15T10:00:00"} for i in range(n_chats)],
        "SurveyEvaluation": [{"timestamp": "2026-09-01T10:00:00"}],
        "SimpleRating": [{"timestamp": "2026-01-10T10:00:00"}],
        "UserFeedback": [{"created_at": datetime(2026, 2, 1, tzinfo=timezone.utc)}],
        "BoothSurvey": [{"created_at": datetime(2026, 10, 1, tzinfo=timezone.utc)}],
        "Deputy": [{"id": "d1"}],
        "Speech": [{"date": "2023-01-01"}],
    }


@pytest.fixture
def settings(monkeypatch):
    s = SimpleNamespace(data_retention_until=date(2027, 12, 31), data_retention_max_days=None)
    monkeypatch.setattr(retention, "_settings", lambda: s)
    return s


def test_nothing_deleted_before_cutoff(settings):
    db = FakeNeo4j(graph())
    assert retention.purge_sync(db, at=BEFORE) == {}
    assert db.cypher == []


def test_everything_in_scope_deleted_after_cutoff(settings):
    db = FakeNeo4j(graph())
    # 23:30 UTC on Dec 31 is already Jan 1 in Rome.
    counts = retention.purge_sync(db, at=datetime(2027, 12, 31, 23, 30, tzinfo=timezone.utc))
    assert counts == {"SurveyEvaluation": 1, "SimpleRating": 1, "UserFeedback": 1, "BoothSurvey": 1, "ChatHistory": 3}
    assert all(not db.graph[label] for label in retention.USER_LABELS)
    assert db.graph["Deputy"] and db.graph["Speech"]
    assert all(re.match(r"MATCH \(n:(\w+)\)", c).group(1) in retention.USER_LABELS for c in db.cypher)


def test_dry_run_deletes_nothing(settings):
    db = FakeNeo4j(graph())
    counts = retention.purge_sync(db, at=AFTER, dry_run=True)
    assert counts["ChatHistory"] == 3 and sum(counts.values()) == 7
    assert sum(len(v) for v in db.graph.values()) == 9
    assert not any("DELETE" in c for c in db.cypher)


def test_max_age_deletes_only_old_nodes(settings):
    settings.data_retention_max_days = 90
    db = FakeNeo4j(graph())
    counts = retention.purge_sync(db, at=datetime(2026, 10, 3, 12, tzinfo=ROME))
    # Bound 2026-07-05: chats from Jan-Mar, the January rating and the February feedback go.
    assert counts == {"SurveyEvaluation": 0, "SimpleRating": 1, "UserFeedback": 1, "BoothSurvey": 0, "ChatHistory": 3}
    assert db.graph["SurveyEvaluation"] and db.graph["BoothSurvey"]


def test_deletes_in_batches(settings, monkeypatch):
    monkeypatch.setattr(retention, "BATCH", 2)
    db = FakeNeo4j(graph(n_chats=5))
    assert retention.purge_sync(db, at=AFTER)["ChatHistory"] == 5
    assert sum("ChatHistory" in c for c in db.cypher) == 3


def test_retries_a_failed_batch(settings, monkeypatch):
    monkeypatch.setattr(retention.time, "sleep", lambda _: None)
    db = FakeNeo4j(graph())
    real = db.query
    failures = iter([True])

    def flaky(cypher, params):
        if next(failures, False):
            raise RuntimeError("lock held by the other app's purge")
        return real(cypher, params)

    db.query = flaky
    assert sum(retention.purge_sync(db, at=AFTER).values()) == 7


def test_writers_get_410_after_cutoff(settings, monkeypatch):
    from app.routers import feedback

    written = []
    monkeypatch.setattr(feedback, "_get_client", lambda: SimpleNamespace(query=lambda *a: written.append(a)))
    app = FastAPI()
    app.include_router(feedback.router)
    client = TestClient(app)
    body = {"tool": "chat", "vote": "up"}

    monkeypatch.setattr(retention, "now", lambda: BEFORE)
    assert client.post("/api/feedback", json=body).status_code == 200
    monkeypatch.setattr(retention, "now", lambda: AFTER)
    assert client.post("/api/feedback", json=body).status_code == 410
    assert client.post("/api/feedback/booth", json={"q1": 5}).status_code == 410
    assert len(written) == 1


def test_daily_task_stops_cleanly(settings, monkeypatch):
    calls = []
    monkeypatch.setattr(retention, "purge_sync", lambda client: calls.append(client) or {})

    async def main():
        task = asyncio.create_task(retention.run_daily(lambda: "client"))
        await asyncio.sleep(0.05)
        await retention.stop(task)
        assert task.cancelled()

    asyncio.run(main())
    assert calls == ["client"]
