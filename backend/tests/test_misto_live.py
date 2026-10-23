"""Misto components of the graph join the expected parties without a config change."""

import pytest

from app.config import get_config
from app.services import misto_live, neo4j_client
from app.services.authority.coalition_logic import CoalitionLogic


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def query(self, cypher, parameters=None, database="neo4j"):
        return self.rows


@pytest.fixture
def graph(monkeypatch):
    def use(rows):
        misto_live.reset()
        monkeypatch.setattr(neo4j_client, "_client", FakeClient(rows))
    yield use
    misto_live.reset()


def test_new_senate_component_is_a_party_of_the_senate(graph):
    graph([{"name": "Civici Marche", "chamber": "senato"},
           {"name": "Avanti PSI", "chamber": "senato"},
           {"name": "Alleanza Verdi e Sinistra", "chamber": "senato"},
           {"name": "Azione-Renew Europe", "chamber": "senato"}])
    config = get_config()
    assert config.coalitions["misto"].count("Civici Marche") == 1
    assert config.coalitions["misto"].count("Avanti PSI") == 1
    assert config.get_coalition("Civici Marche") == "misto"
    assert CoalitionLogic().get_coalition("Civici Marche") == "misto"
    assert "Civici Marche" in config.get_all_parties(["camera", "senato"])
    assert "Civici Marche" not in config.get_all_parties(["camera"])
    # AVS and Azione of the Senate count for their groups, not as parties
    assert "Azione-Renew Europe" not in config.get_all_parties(["camera", "senato"])
    assert "Alleanza Verdi e Sinistra" not in config.coalitions["misto"]


def test_without_a_client_the_config_is_unchanged(monkeypatch):
    misto_live.reset()
    monkeypatch.setattr(neo4j_client, "_client", None)
    config = get_config()
    assert config.coalitions == config.load_config()["coalitions"]


def test_graph_down_keeps_the_last_list(graph, monkeypatch):
    graph([{"name": "Civici Marche", "chamber": "senato"}])
    assert "Civici Marche" in get_config().coalitions["misto"]

    class Down:
        def query(self, *a, **k):
            raise RuntimeError("down")
    misto_live._cache["at"] = 0.0
    monkeypatch.setattr(neo4j_client, "_client", Down())
    assert "Civici Marche" in get_config().coalitions["misto"]
