"""
test_integration.py — Integration tests for the ParliamentRAG build pipeline.

These tests run AFTER `make db-all` against a live Neo4j instance and verify
that all schema requirements are met. Tests are skipped by default and only
executed when the integration marker is enabled:

    pytest -m integration tests/test_integration.py

Environment variables:
    NEO4J_URI       Bolt URI of the target Neo4j instance (default: bolt://localhost:7689)
    NEO4J_USER      Neo4j username (default: neo4j)
    NEO4J_PASSWORD  Neo4j password (required)
"""

import os
import pytest
from neo4j import GraphDatabase

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:7689")
NEO4J_USER = os.environ.get("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def driver():
    """Create a Neo4j driver for the module and close it when done."""
    d = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    yield d
    d.close()


@pytest.fixture(scope="module")
def session(driver):
    """Yield a Neo4j session scoped to the module."""
    with driver.session() as s:
        yield s


# ---------------------------------------------------------------------------
# Vote node tests
# ---------------------------------------------------------------------------


def test_vote_nodes_exist(session):
    """Vote nodes must be present in the graph after make db-all."""
    result = session.run("MATCH (v:Vote) RETURN count(v) AS cnt")
    cnt = result.single()["cnt"]
    assert cnt > 0, f"Expected Vote nodes but found {cnt}"


def test_vote_linked_to_session(session):
    """Votes must be linked from Session via HAS_VOTE, not from Debate."""
    result = session.run(
        "MATCH (s:Session)-[:HAS_VOTE]->(v:Vote) RETURN count(v) AS cnt"
    )
    cnt = result.single()["cnt"]
    assert cnt > 0, (
        f"Expected Session-[:HAS_VOTE]->Vote edges but found {cnt}. "
        "Votes must be linked at session level, not debate level."
    )

    # Verify the incorrect Debate-[:HAS_VOTE]->Vote pattern does NOT exist
    bad_result = session.run(
        "MATCH (:Debate)-[:HAS_VOTE]->(:Vote) RETURN count(*) AS cnt"
    )
    bad_cnt = bad_result.single()["cnt"]
    assert bad_cnt == 0, (
        f"Found {bad_cnt} Debate-[:HAS_VOTE]->Vote edges — "
        "votes should be linked to Session, not Debate."
    )


# ---------------------------------------------------------------------------
# Debate-to-Act linking
# ---------------------------------------------------------------------------


def test_discusses_edges_exist(session):
    """DISCUSSES edges must connect Debate nodes to ParliamentaryAct nodes."""
    result = session.run(
        "MATCH (d:Debate)-[:DISCUSSES]->(a:ParliamentaryAct) RETURN count(*) AS cnt"
    )
    cnt = result.single()["cnt"]
    assert cnt > 0, (
        f"Expected Debate-[:DISCUSSES]->ParliamentaryAct edges but found {cnt}"
    )


# ---------------------------------------------------------------------------
# Speech schema tests
# ---------------------------------------------------------------------------


def test_speaking_role_populated(session):
    """At least some Speech nodes must have a non-null speakingRole property."""
    result = session.run(
        "MATCH (sp:Speech) WHERE sp.speakingRole IS NOT NULL RETURN count(sp) AS cnt"
    )
    cnt = result.single()["cnt"]
    assert cnt > 0, (
        f"Expected Speech nodes with speakingRole but found {cnt}. "
        "Speeches by ministers/committee reporters must carry speakingRole."
    )


# ---------------------------------------------------------------------------
# Phase schema tests
# ---------------------------------------------------------------------------


def test_phase_type_populated(session):
    """At least some Phase nodes must have a non-null phaseType property."""
    result = session.run(
        "MATCH (p:Phase) WHERE p.phaseType IS NOT NULL RETURN count(p) AS cnt"
    )
    cnt = result.single()["cnt"]
    assert cnt > 0, (
        f"Expected Phase nodes with phaseType but found {cnt}. "
        "Phase titles must be mapped to English enum values."
    )


# ---------------------------------------------------------------------------
# Italian-property cleanup tests
# ---------------------------------------------------------------------------


def test_no_italian_properties(session):
    """Dead Italian-schema properties must not exist on any node."""
    checks = [
        (
            "MATCH (c:Chunk) WHERE c.startCharRaw IS NOT NULL RETURN count(c) AS cnt",
            "Chunk.startCharRaw",
        ),
        (
            "MATCH (c:Chunk) WHERE c.endCharRaw IS NOT NULL RETURN count(c) AS cnt",
            "Chunk.endCharRaw",
        ),
        (
            "MATCH (sp:Speech) WHERE sp.preprocessedText IS NOT NULL "
            "OR sp.preprocessed_text IS NOT NULL RETURN count(sp) AS cnt",
            "Speech.preprocessedText / Speech.preprocessed_text",
        ),
        (
            "MATCH (s:Session) WHERE s.completeDate IS NOT NULL "
            "OR s.complete_date IS NOT NULL RETURN count(s) AS cnt",
            "Session.completeDate / Session.complete_date",
        ),
    ]
    for query, label in checks:
        result = session.run(query)
        cnt = result.single()["cnt"]
        assert cnt == 0, (
            f"Found {cnt} nodes with Italian property '{label}' — "
            "all Italian-schema properties must be removed."
        )


# ---------------------------------------------------------------------------
# Italian-label cleanup tests
# ---------------------------------------------------------------------------


def test_no_italian_labels(session):
    """Italian node labels (Seduta, Dibattito, Fase, Intervento, Votazione) must not exist."""
    result = session.run("CALL db.labels() YIELD label RETURN collect(label) AS labels")
    labels = result.single()["labels"]
    italian_labels = ["Seduta", "Dibattito", "Fase", "Intervento", "Votazione"]
    found = [lbl for lbl in italian_labels if lbl in labels]
    assert not found, (
        f"Italian node labels still present in schema: {found}. "
        "All labels must be English PascalCase."
    )


# ---------------------------------------------------------------------------
# Session schema tests
# ---------------------------------------------------------------------------


def test_session_has_date_property(session):
    """Session nodes must have a Neo4j Date `date` property (not a string)."""
    # Check that at least some sessions have a date
    result = session.run(
        "MATCH (s:Session) WHERE s.date IS NOT NULL RETURN count(s) AS cnt"
    )
    cnt = result.single()["cnt"]
    assert cnt > 0, f"Expected Session nodes with date but found {cnt}"

    # Check that the date property is a Neo4j Date type (not a plain string)
    sample = session.run(
        "MATCH (s:Session) WHERE s.date IS NOT NULL RETURN s.date AS d LIMIT 1"
    )
    record = sample.single()
    assert record is not None, "No Session with date found for type check"
    date_val = record["d"]
    # Neo4j Date objects have year/month/day attributes; plain strings do not
    assert hasattr(date_val, "year") and hasattr(date_val, "month") and hasattr(date_val, "day"), (
        f"Session.date is type {type(date_val).__name__} — expected Neo4j Date. "
        "Use neo4j.time.Date, not a plain string."
    )


# ---------------------------------------------------------------------------
# Chunk schema tests
# ---------------------------------------------------------------------------


def test_chunk_minimal_properties(session):
    """Chunk nodes must carry only the expected minimal set of properties.

    Required: id, text, index.
    Optional (set later): embedding.
    Forbidden: charCount, startCharRaw, endCharRaw and any alignment_map keys.
    """
    result = session.run("MATCH (c:Chunk) RETURN keys(c) AS k LIMIT 1")
    record = result.single()
    if record is None:
        pytest.skip("No Chunk nodes found — run make db-all first")

    keys = set(record["k"])
    forbidden_keys = {"charCount", "startCharRaw", "endCharRaw"}

    present_forbidden = keys & forbidden_keys
    assert not present_forbidden, (
        f"Chunk node has forbidden properties: {present_forbidden}. "
        "Only id, text, index (and optionally embedding) are permitted."
    )
    assert "id" in keys, "Chunk must have 'id' property"
    assert "text" in keys, "Chunk must have 'text' property"
    assert "index" in keys, "Chunk must have 'index' property"
