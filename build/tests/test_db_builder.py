"""
Tests for db_builder.DatabaseBuilder.

All Neo4j I/O is mocked — no live database required.
"""

from __future__ import annotations

import csv
import os
import tempfile
from unittest.mock import MagicMock

from build_config import BuildConfig
from db_builder import DatabaseBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_driver(side_effects=None):
    """Return a mocked neo4j Driver with a mocked .session() context manager."""
    driver = MagicMock()
    neo_session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=neo_session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)
    return driver, neo_session


def _capture_cypher(neo_session) -> list[str]:
    """Collect all Cypher strings passed to execute_write / execute_read."""
    captured: list[str] = []

    def side_effect(fn, *args, **kwargs):
        tx = MagicMock()
        tx.run = MagicMock(return_value=MagicMock(single=MagicMock(return_value={"deleted": 0})))
        fn(tx, *args, **kwargs)
        if tx.run.called:
            for c in tx.run.call_args_list:
                captured.append(c.args[0] if c.args else "")
        return MagicMock()

    neo_session.execute_write.side_effect = side_effect
    neo_session.execute_read.side_effect = side_effect
    return captured


# ---------------------------------------------------------------------------
# Task 1 tests
# ---------------------------------------------------------------------------

def test_create_constraints_uses_english_labels():
    """Constraint Cypher must reference English labels, not Italian ones."""
    driver, neo_session = _make_driver()
    captured = _capture_cypher(neo_session)

    db = DatabaseBuilder(driver)
    db.create_constraints()

    combined = " ".join(captured)

    # English labels that MUST appear
    for label in ("Session", "Debate", "Phase", "Speech", "Chunk", "Vote"):
        assert label in combined, f"Expected English label '{label}' in constraints"

    # Italian labels that must NOT appear as node labels
    italian_labels = ("Seduta", "Dibattito", "Intervento", "Votazione")
    for label in italian_labels:
        assert f":{label}" not in combined and f"({label}" not in combined, (
            f"Italian label '{label}' must not appear in constraints"
        )


def test_batch_write_splits_at_batch_size():
    """_batch_write with batch_size=2 and 5 items must call execute_write 3 times."""
    driver, neo_session = _make_driver()
    neo_session.execute_write.return_value = MagicMock()

    config = BuildConfig(batch_size=2)
    db = DatabaseBuilder(driver, config)

    items = [{"id": i} for i in range(5)]
    fn = MagicMock()
    db._batch_write(neo_session, fn, items)

    assert neo_session.execute_write.call_count == 3, (
        f"Expected 3 execute_write calls for 5 items with batch_size=2, "
        f"got {neo_session.execute_write.call_count}"
    )


def test_create_votes_cypher_uses_session():
    """Vote Cypher must reference Session and HAS_VOTE (not Debate)."""
    driver, neo_session = _make_driver()
    _capture_cypher(neo_session)

    # Call the static transaction function directly via a fake tx
    tx = MagicMock()
    cypher_calls: list[str] = []
    tx.run = lambda q, **kwargs: cypher_calls.append(q) or MagicMock()

    batch = [{
        "id": "leg19_sed1_vot_0",
        "number": 1, "type": "N", "subject": "test",
        "present": 400, "voters": 390, "abstained": 5,
        "majority": 196, "inFavor": 200, "against": 190,
        "onMission": 10, "outcome": "approvato",
        "sessionId": "leg19_sed1",
    }]
    DatabaseBuilder._create_votes(tx, batch)

    combined = " ".join(cypher_calls)
    assert "Session" in combined, "Vote Cypher must reference Session label"
    assert "HAS_VOTE" in combined, "Vote Cypher must use HAS_VOTE relationship"
    assert "Debate" not in combined, "Vote Cypher must NOT reference Debate (votes are session-level)"


def test_create_speeches_no_preprocessed_text():
    """Speech Cypher must not contain preprocessedText or preprocessed_text."""
    tx = MagicMock()
    cypher_calls: list[str] = []
    tx.run = lambda q, **kwargs: cypher_calls.append(q) or MagicMock()

    batch = [{
        "id": "leg19_sed1_int1",
        "text": "Hello world",
        "speakingRole": None,
        "phaseId": "leg19_sed1_fase1",
        "deputatoId": None,
        "cognome_nome": None,
    }]
    DatabaseBuilder._create_speeches(tx, batch)

    combined = " ".join(cypher_calls)
    assert "preprocessedText" not in combined, "Speech Cypher must not contain preprocessedText"
    assert "preprocessed_text" not in combined, "Speech Cypher must not contain preprocessed_text"


def test_create_chunks_no_dead_properties():
    """Chunk Cypher must not contain startCharRaw, endCharRaw, or charCount."""
    tx = MagicMock()
    cypher_calls: list[str] = []
    tx.run = lambda q, **kwargs: cypher_calls.append(q) or MagicMock()

    batch = [{"id": "sp1_chunk_0", "text": "chunk text", "index": 0, "speechId": "sp1"}]
    DatabaseBuilder._create_chunks(tx, batch)

    combined = " ".join(cypher_calls)
    for dead_prop in ("startCharRaw", "endCharRaw", "charCount",
                      "start_char_raw", "end_char_raw", "char_count"):
        assert dead_prop not in combined, (
            f"Chunk Cypher must not contain dead property '{dead_prop}'"
        )


def test_session_no_complete_date():
    """Session Cypher must not contain completeDate or complete_date."""
    tx = MagicMock()
    cypher_calls: list[str] = []
    tx.run = lambda q, **kwargs: cypher_calls.append(q) or MagicMock()

    session_data = {
        "id": "leg19_sed1",
        "legislature": 19,
        "number": 1,
        "year": 2022,
        "month": 10,
        "day": 13,
        "chamber": "camera",
        "date": "2022-10-13",
    }
    DatabaseBuilder._create_session(tx, session_data)

    combined = " ".join(cypher_calls)
    assert "completeDate" not in combined, "Session Cypher must not contain completeDate"
    assert "complete_date" not in combined, "Session Cypher must not contain complete_date"


# ---------------------------------------------------------------------------
# Task 2 tests
# ---------------------------------------------------------------------------

def test_load_deputies_uses_unwind():
    """load_deputies must call execute_write with Cypher containing UNWIND."""
    driver, neo_session = _make_driver()
    captured = _capture_cypher(neo_session)

    # Create a minimal temp CSV
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, "deputati_xix.csv")
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=[
                "deputato", "nome", "cognome", "gender",
                "descrizione", "foto", "schedaCamera", "mandatoCamera", "mandatoStart",
            ])
            writer.writeheader()
            writer.writerow({
                "deputato": "http://dati.camera.it/ocd/deputato.rdf/d00001_19",
                "nome": "Mario",
                "cognome": "Rossi",
                "gender": "M",
                "descrizione": "laurea;avvocato",
                "foto": "",
                "schedaCamera": "",
                "mandatoCamera": "",
                "mandatoStart": "",
            })

        db = DatabaseBuilder(driver)
        db.load_deputies(tmpdir)

    combined = " ".join(captured)
    assert "UNWIND" in combined, "load_deputies must use UNWIND in its Cypher"


def test_get_existing_session_numbers_returns_set():
    """get_existing_session_numbers must return a Python set of integers."""
    driver = MagicMock()
    neo_session = MagicMock()
    driver.session.return_value.__enter__ = MagicMock(return_value=neo_session)
    driver.session.return_value.__exit__ = MagicMock(return_value=False)

    # Simulate execute_read returning records with a 'number' key
    neo_session.execute_read.return_value = [{"number": 42}, {"number": 7}]

    db = DatabaseBuilder(driver)
    result = db.get_existing_session_numbers()

    assert isinstance(result, set), "get_existing_session_numbers must return a set"
    assert result == {42, 7}, f"Expected {{42, 7}}, got {result}"
