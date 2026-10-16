"""Neo4j stopped (nightly backup, outage): the API answers 503 data_unavailable, not 500."""
import pytest
from fastapi.testclient import TestClient
from neo4j.exceptions import ServiceUnavailable, SessionExpired

from app.main import app
from app.services.neo4j_client import get_neo4j_client


class _DownClient:
    def __init__(self, exc: Exception):
        self.exc = exc

    def __getattr__(self, name):
        def fail(*_, **__):
            raise self.exc
        return fail


@pytest.mark.parametrize("exc", [ServiceUnavailable("down"), SessionExpired("gone")])
def test_unreachable_graph_is_503(exc):
    app.dependency_overrides[get_neo4j_client] = lambda: _DownClient(exc)
    try:
        resp = TestClient(app, raise_server_exceptions=False).get("/api/timeline/sessions/x/votes")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 503
    assert resp.headers["retry-after"] == "30"
    body = resp.json()
    assert body["code"] == "data_unavailable"
    assert body["detail"].startswith("I dati del Parlamento non sono raggiungibili")
