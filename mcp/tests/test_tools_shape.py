"""Tool outputs keep the backend's new fields (cards 202, 204)."""
import asyncio

import server


def _fake_get(payload):
    async def fake(path, params=None):
        return payload(path) if callable(payload) else payload
    return fake


def test_session_votes_mark_quorum_checks(monkeypatch):
    monkeypatch.setattr(server, "_get", _fake_get([
        {"id": "v1", "number": 1, "subject": "Verifica del numero legale", "description": "Verifica",
         "outcome": None, "kind": "quorum_check"},
        {"id": "v2", "number": 2, "subject": "Votazione finale", "description": "Ddl n. 1903: Delega",
         "outcome": "approved", "kind": None},
    ]))
    out = asyncio.run(server.get_session_votes("sen_leg19_sed465"))
    assert out["votes"][0]["kind"] == "quorum_check" and out["votes"][0]["outcome"] is None
    assert "kind" not in out["votes"][1]


def test_hemicycle_explains_a_quorum_check(monkeypatch):
    monkeypatch.setattr(server, "_get", _fake_get({
        "id": "v1", "subject": "Verifica del numero legale", "kind": "quorum_check", "present": 159,
        "chamber": "senato", "secret_vote": False, "participants": [], "breakdown": []}))
    out = asyncio.run(server.get_vote_hemicycle("v1"))
    out = out if isinstance(out, dict) else out
    assert "quorum" in str(out).lower()


def test_debate_keeps_component_and_continuations(monkeypatch):
    monkeypatch.setattr(server, "_get", _fake_get({
        "id": "d", "title": "t", "recap": None, "acts": [], "phases": [], "votes": [],
        "continuation_ids": ["d_approvato"],
        "speakers": [{"first_name": "Dieter", "last_name": "Steger", "party": "Minoranze Linguistiche",
                      "parliamentary_group": "MISTO", "speech_count": 1}],
    }))
    out = asyncio.run(server.get_debate("d"))
    assert out["includes_continuations"] == ["d_approvato"]
    assert out["speakers"][0]["party"] == "Minoranze Linguistiche"
    assert out["speakers"][0]["parliamentary_group"] == "MISTO"
