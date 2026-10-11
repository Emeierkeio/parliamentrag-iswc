"""Retrieval scope: chamber/legislature normalization and index selection."""

import pytest

from app.services.retrieval import scope as scope_mod
from app.services.retrieval.scope import (
    DEFAULT_SCOPE, ScopeItem, normalize_scope, scope_key, scope_param, vector_indexes,
)


class FakeClient:
    def __init__(self, names):
        self.names = names

    def query(self, cypher, params=None):
        return [{"name": n} for n in self.names]


@pytest.fixture(autouse=True)
def clear_index_cache():
    scope_mod._INDEX_CACHE = None
    yield
    scope_mod._INDEX_CACHE = None


def test_default_scope_is_camera_xix():
    assert normalize_scope(None) == (("camera", 19),)
    assert normalize_scope([]) == DEFAULT_SCOPE


def test_accepts_models_dicts_and_tuples_and_dedups():
    raw = [ScopeItem(chamber="senato", legislature=19), {"chamber": "camera", "legislature": 18},
           ("senato", 19)]
    assert normalize_scope(raw) == (("camera", 18), ("senato", 19))


def test_rejects_unknown_chamber():
    with pytest.raises(ValueError):
        normalize_scope([("parlamento", 19)])


def test_default_scope_keeps_legacy_cache_key():
    assert scope_key(DEFAULT_SCOPE) is None
    assert scope_key((("camera", 18), ("camera", 19))) == "camera_18,camera_19"


def test_scope_param_is_cypher_friendly():
    assert scope_param((("camera", 19),)) == [["camera", 19]]


def test_scope_indexes_used_when_present():
    client = FakeClient(["chunk_embedding_index", "chunk_embedding_camera_19", "chunk_embedding_senato_19"])
    assert vector_indexes(client, (("camera", 19), ("senato", 19)), "chunk_embedding_index") == [
        "chunk_embedding_camera_19", "chunk_embedding_senato_19"]


def test_missing_scope_index_falls_back_to_global():
    client = FakeClient(["chunk_embedding_index"])
    assert vector_indexes(client, DEFAULT_SCOPE, "chunk_embedding_index") == ["chunk_embedding_index"]


# Default scope and chambers named in the question

import copy

from app.config import get_config
from app.services.retrieval.scope import chambers_in_question, default_scope, resolve_scope


@pytest.mark.parametrize("question, chambers", [
    ("Cosa si è detto al Senato sul premierato?", ("senato",)),
    ("Come hanno votato i senatori sulla legge elettorale?", ("senato",)),
    ("Il dibattito alla Camera sulla manovra", ("camera",)),
    ("Cosa pensano i deputati del salario minimo?", ("camera",)),
    ("Riforma delle camere di commercio", ()),
    ("Il ruolo della camera di commercio nella legge sulle PMI", ()),
    ("Cosa pensano i partiti dell'autonomia differenziata?", ()),
    ("Differenze tra Camera dei deputati e Senato sul premierato", ("camera", "senato")),
])
def test_chambers_in_question(question, chambers):
    assert chambers_in_question(question) == chambers


def _with_chambers(chambers):
    config = get_config()
    original = config.load_config()
    changed = copy.deepcopy(original)
    changed["chambers"] = chambers
    config.save_config(changed)
    return original


def test_camera_only_graph_ignores_senate_in_question():
    # production today: only the Camera is loaded
    assert default_scope() == (("camera", 19),)
    assert resolve_scope(None, "Cosa si è detto al Senato?") == (("camera", 19),)


def test_both_chambers_by_default_one_when_named():
    original = _with_chambers(["camera", "senato"])
    try:
        assert resolve_scope(None, "Cosa pensano i partiti del premierato?") == (("camera", 19), ("senato", 19))
        assert resolve_scope(None, "Cosa si è detto al Senato sul premierato?") == (("senato", 19),)
        assert resolve_scope(None, "Camera dei deputati e Senato sul premierato") == (("camera", 19), ("senato", 19))
        assert resolve_scope([{"chamber": "camera", "legislature": 19}], "al Senato") == (("camera", 19),)
    finally:
        get_config().save_config(original)
