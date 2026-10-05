"""Admin key rules: admin endpoints fail closed, site endpoints stay open."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.services.api_keys import api_key_middleware, is_admin_only, parse_keys


def _app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(api_key_middleware)

    @app.get("/api/history")
    def history_list():
        return {"history": []}

    @app.post("/api/history")
    def history_save():
        return {"id": "new"}

    @app.get("/api/history/{chat_id}")
    def history_item(chat_id: str):
        return {"id": chat_id}

    @app.delete("/api/history/{chat_id}")
    def history_delete(chat_id: str):
        return {"deleted": chat_id}

    @app.delete("/api/history")
    def history_clear():
        return {"cleared": True}

    @app.get("/api/evaluation/dashboard")
    def dashboard():
        return {}

    @app.put("/api/config")
    def config_put():
        return {}

    @app.get("/api/config")
    def config_get():
        return {}

    @app.get("/api/surveys")
    def surveys():
        return []

    @app.post("/api/query")
    def query():
        return {"ok": True}

    return app


KEYS = "fascicoli:site:s3cret,me:admin:adm"
ADMIN = {"X-API-Key": "adm"}


def test_parse_keys_skips_malformed_entries():
    keys = parse_keys("a:site:x, b:root:y, c:developer:, d:admin:z")
    assert [(k.name, k.scope) for k in keys] == [("a", "site"), ("d", "admin")]


def test_admin_rules():
    assert is_admin_only("GET", "/api/history")
    assert is_admin_only("GET", "/api/history/")
    assert is_admin_only("GET", "//api//history")
    assert is_admin_only("HEAD", "/api/history")
    assert not is_admin_only("GET", "/api/history/abc")
    assert not is_admin_only("POST", "/api/history")
    assert is_admin_only("DELETE", "/api/history/abc")
    assert is_admin_only("DELETE", "/api/history")
    assert is_admin_only("POST", "/api/history/abc/baseline-experts")
    assert is_admin_only("PUT", "/api/config")
    assert is_admin_only("POST", "/api/config/reload")
    assert not is_admin_only("GET", "/api/config")
    assert not is_admin_only("GET", "/api/config/last-update")
    assert not is_admin_only("POST", "/api/config/translate")
    assert is_admin_only("GET", "/api/evaluation/dashboard")
    assert is_admin_only("GET", "/api/evaluation/export/csv")
    assert is_admin_only("GET", "/api/surveys")
    assert is_admin_only("GET", "/api/surveys/stats/summary")
    assert is_admin_only("GET", "/api/surveys/chats/pending")
    assert is_admin_only("DELETE", "/api/surveys/abc")
    assert not is_admin_only("POST", "/api/surveys")
    assert not is_admin_only("GET", "/api/surveys/abc")
    assert not is_admin_only("POST", "/api/query")
    assert not is_admin_only("POST", "/api/chat")


def test_admin_denied_without_any_key_configured(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    client = TestClient(_app())
    assert client.get("/api/history").status_code == 403
    assert client.delete("/api/history").status_code == 403
    assert client.delete("/api/history/abc").status_code == 403
    assert client.get("/api/evaluation/dashboard").status_code == 403
    assert client.put("/api/config").status_code == 403
    # Even a header cannot unlock anything when no admin key exists
    assert client.get("/api/history", headers=ADMIN).status_code == 403


def test_admin_denied_with_only_site_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", "fascicoli:site:s3cret")
    client = TestClient(_app())
    assert client.get("/api/history", headers={"X-API-Key": "s3cret"}).status_code == 403


def test_site_routes_open_without_keys(monkeypatch):
    monkeypatch.delenv("API_KEYS", raising=False)
    client = TestClient(_app())
    assert client.post("/api/query").status_code == 200
    assert client.post("/api/history").status_code == 200
    assert client.get("/api/history/abc").status_code == 200
    assert client.get("/api/config").status_code == 200


def test_admin_rules_with_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", KEYS)
    client = TestClient(_app())
    assert client.get("/api/history").status_code == 401
    assert client.get("/api/history", headers={"X-API-Key": "s3cret"}).status_code == 403
    assert client.get("/api/history", headers={"X-API-Key": "wrong"}).status_code == 403
    assert client.get("/api/history", headers=ADMIN).status_code == 200
    assert client.delete("/api/history/abc", headers=ADMIN).status_code == 200
    assert client.delete("/api/history", headers=ADMIN).status_code == 200
    assert client.get("/api/evaluation/dashboard", headers=ADMIN).status_code == 200
    assert client.put("/api/config", headers=ADMIN).status_code == 200
    assert client.get("/api/surveys", headers=ADMIN).status_code == 200


def test_site_routes_open_with_keys(monkeypatch):
    monkeypatch.setenv("API_KEYS", KEYS)
    client = TestClient(_app())
    assert client.post("/api/query").status_code == 200
    assert client.get("/api/history/abc").status_code == 200
    assert client.get("/api/config").status_code == 200
