"""Senators: education is not published by dati.senato.it, so its weight is
spread over the other components instead of counting as zero."""

import pytest

from app.services.authority.scorer import AuthorityScorer


def _scorer(weights):
    s = AuthorityScorer.__new__(AuthorityScorer)
    s.weights = weights
    return s


WEIGHTS = {"profession": 0.15, "education": 0.10, "committee": 0.25,
           "acts": 0.20, "interventions": 0.25, "role": 0.05}


def test_deputies_keep_the_configured_weights():
    assert _scorer(WEIGHTS)._weights_for({"education_unpublished": False}) == WEIGHTS


def test_senators_redistribute_education():
    w = _scorer(WEIGHTS)._weights_for({"education_unpublished": True})
    assert w["education"] == 0.0
    assert sum(w.values()) == pytest.approx(1.0)
    assert w["committee"] / w["acts"] == pytest.approx(0.25 / 0.20)
