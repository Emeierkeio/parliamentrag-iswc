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
