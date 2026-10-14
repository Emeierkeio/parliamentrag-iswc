"""
test_sparql_ingester.py — Unit tests for sparql_ingester.py

All HTTP calls are mocked; no network access required.
"""

from __future__ import annotations

import inspect
import sys
import os
import json
from typing import Optional
from unittest.mock import patch, MagicMock


# Ensure build/ is on the path for direct imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sparql_ingester import (
    sparql_dep_uri_to_neo4j_id,
    parse_votazione_uri,
    OUTCOME_MAP,
    SparqlIngester,
    _sparql_get,
    SPARQL_PAGE_SIZE,
)


# ---------------------------------------------------------------------------
# URI parsing helpers
# ---------------------------------------------------------------------------

class TestSparqlDepUriToNeo4jId:
    """test_sparql_dep_uri_to_neo4j_id"""

    def test_standard_conversion(self):
        uri = "http://dati.camera.it/ocd/deputato.rdf/d308908_19"
        result = sparql_dep_uri_to_neo4j_id(uri)
        assert result == "http://dati.camera.it/ocd/persona.rdf/p308908"

    def test_different_person_id(self):
        uri = "http://dati.camera.it/ocd/deputato.rdf/d123456_19"
        result = sparql_dep_uri_to_neo4j_id(uri)
        assert result == "http://dati.camera.it/ocd/persona.rdf/p123456"

    def test_invalid_uri_returns_none(self):
        assert sparql_dep_uri_to_neo4j_id("http://example.com/invalid") is None

    def test_empty_string_returns_none(self):
        assert sparql_dep_uri_to_neo4j_id("") is None

    def test_missing_legislature_suffix_returns_none(self):
        # Without _19 pattern it should not match
        assert sparql_dep_uri_to_neo4j_id("http://dati.camera.it/ocd/deputato.rdf/d308908") is None


class TestParseVotazioneUri:
    """test_parse_votazione_uri"""

    def test_standard_uri(self):
        uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_029_089"
        session, vote = parse_votazione_uri(uri)
        assert session == 29
        assert vote == 89

    def test_leading_zeros_stripped(self):
        uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_001_001"
        session, vote = parse_votazione_uri(uri)
        assert session == 1
        assert vote == 1

    def test_large_numbers(self):
        uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_250_150"
        session, vote = parse_votazione_uri(uri)
        assert session == 250
        assert vote == 150

    def test_invalid_uri_returns_none_tuple(self):
        session, vote = parse_votazione_uri("http://example.com/invalid")
        assert session is None
        assert vote is None

    def test_empty_string_returns_none_tuple(self):
        session, vote = parse_votazione_uri("")
        assert session is None
        assert vote is None

    def test_leg18_uri_parsed(self):
        """Legislature-18 vs18_ URI must parse identically."""
        uri = "http://dati.camera.it/ocd/votazione.rdf/vs18_028_026"
        session, vote = parse_votazione_uri(uri)
        assert session == 28
        assert vote == 26


# ---------------------------------------------------------------------------
# Outcome mapping
# ---------------------------------------------------------------------------

class TestOutcomeMapping:
    """test_outcome_mapping"""

    def test_favorevole_maps_to_favor(self):
        assert OUTCOME_MAP["Favorevole"] == "favor"

    def test_contrario_maps_to_against(self):
        assert OUTCOME_MAP["Contrario"] == "against"

    def test_astensione_maps_to_abstain(self):
        assert OUTCOME_MAP["Astensione"] == "abstain"

    def test_non_ha_votato_maps_to_absent(self):
        assert OUTCOME_MAP["Non ha votato"] == "absent"

    def test_ha_votato_is_secret_not_absent(self):
        # Secret ballots publish participation only: the deputy did vote
        assert OUTCOME_MAP["Ha votato"] == "secret"

    def test_all_five_outcomes_present(self):
        assert set(OUTCOME_MAP.values()) == {"favor", "against", "abstain", "absent", "secret"}


# ---------------------------------------------------------------------------
# Batch preparation
# ---------------------------------------------------------------------------

class TestVoteBatchPreparation:
    """test_vote_batch_preparation"""

    MOCK_VOTE_BINDINGS = [
        {
            "voto": {"value": "http://dati.camera.it/ocd/voto.rdf/vd19_029_089_308908"},
            "votazione": {"value": "http://dati.camera.it/ocd/votazione.rdf/vs19_029_089"},
            "tipo": {"value": "Favorevole"},
        },
        {
            "voto": {"value": "http://dati.camera.it/ocd/voto.rdf/vd19_029_090_308908"},
            "votazione": {"value": "http://dati.camera.it/ocd/votazione.rdf/vs19_029_090"},
            "tipo": {"value": "Contrario"},
        },
    ]

    def test_batch_has_correct_deputy_id(self):
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        person_id = "308908"
        batches = ingester._prepare_vote_batch(self.MOCK_VOTE_BINDINGS, deputy_neo4j_id, person_id)
        assert all(b["deputyId"] == deputy_neo4j_id for b in batches)

    def test_batch_has_session_and_vote_numbers(self):
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        person_id = "308908"
        batches = ingester._prepare_vote_batch(self.MOCK_VOTE_BINDINGS, deputy_neo4j_id, person_id)
        assert batches[0]["sessionNumber"] == 29
        assert batches[0]["voteNumber"] == 89
        assert batches[1]["sessionNumber"] == 29
        assert batches[1]["voteNumber"] == 90

    def test_batch_has_mapped_outcome(self):
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        person_id = "308908"
        batches = ingester._prepare_vote_batch(self.MOCK_VOTE_BINDINGS, deputy_neo4j_id, person_id)
        assert batches[0]["outcome"] == "favor"
        assert batches[1]["outcome"] == "against"

    def test_batch_has_correct_id_format(self):
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        person_id = "308908"
        batches = ingester._prepare_vote_batch(self.MOCK_VOTE_BINDINGS, deputy_neo4j_id, person_id)
        assert batches[0]["id"] == "iv_camera_308908_29_89"
        assert batches[1]["id"] == "iv_camera_308908_29_90"

    def test_id_has_chamber_prefix(self):
        """_prepare_vote_batch with chamber='camera' produces ids with 'iv_camera_' prefix."""
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        person_id = "308908"
        batches = ingester._prepare_vote_batch(
            self.MOCK_VOTE_BINDINGS, deputy_neo4j_id, person_id, chamber="camera"
        )
        assert len(batches) > 0
        assert all(b["id"].startswith("iv_camera_") for b in batches)

    def test_invalid_votazione_uri_skipped(self):
        """Bindings with unparseable votazione URI produce no batch entry."""
        ingester = SparqlIngester(driver=MagicMock())
        bad_bindings = [
            {
                "voto": {"value": "http://example.com/bad"},
                "votazione": {"value": "http://example.com/bad"},
                "tipo": {"value": "Favorevole"},
            }
        ]
        batches = ingester._prepare_vote_batch(bad_bindings, "http://dati.camera.it/ocd/persona.rdf/p999", "999")
        assert batches == []


class TestCommitteeRoleBatchPreparation:
    """test_committee_role_batch_preparation"""

    MOCK_COMMITTEE_BINDINGS = [
        {
            "organoLabel": {"value": "Commissione bilancio"},
            "carica": {"value": "PRESIDENTE"},
            "startDate": {"value": "20220913"},
            "endDate": {"value": "20231231"},
        },
        {
            "organoLabel": {"value": "Commissione giustizia"},
            "carica": {"value": "VICEPRESIDENTE"},
            "startDate": {"value": "20230101"},
            # no endDate
        },
    ]

    def test_batch_has_deputy_id(self):
        ingester = SparqlIngester(driver=MagicMock())
        deputy_neo4j_id = "http://dati.camera.it/ocd/persona.rdf/p308908"
        batches = ingester._prepare_committee_role_batch(self.MOCK_COMMITTEE_BINDINGS, deputy_neo4j_id)
        assert all(b["deputyId"] == deputy_neo4j_id for b in batches)

    def test_batch_has_committee_name(self):
        ingester = SparqlIngester(driver=MagicMock())
        batches = ingester._prepare_committee_role_batch(
            self.MOCK_COMMITTEE_BINDINGS, "http://dati.camera.it/ocd/persona.rdf/p308908"
        )
        assert batches[0]["committeeName"] == "Commissione bilancio"
        assert batches[1]["committeeName"] == "Commissione giustizia"

    def test_batch_has_role(self):
        ingester = SparqlIngester(driver=MagicMock())
        batches = ingester._prepare_committee_role_batch(
            self.MOCK_COMMITTEE_BINDINGS, "http://dati.camera.it/ocd/persona.rdf/p308908"
        )
        assert batches[0]["role"] == "PRESIDENTE"
        assert batches[1]["role"] == "VICEPRESIDENTE"

    def test_batch_has_start_date(self):
        ingester = SparqlIngester(driver=MagicMock())
        batches = ingester._prepare_committee_role_batch(
            self.MOCK_COMMITTEE_BINDINGS, "http://dati.camera.it/ocd/persona.rdf/p308908"
        )
        assert batches[0]["startDate"] == "20220913"

    def test_batch_missing_end_date_is_none(self):
        ingester = SparqlIngester(driver=MagicMock())
        batches = ingester._prepare_committee_role_batch(
            self.MOCK_COMMITTEE_BINDINGS, "http://dati.camera.it/ocd/persona.rdf/p308908"
        )
        assert batches[0]["endDate"] == "20231231"
        assert batches[1]["endDate"] is None


# ---------------------------------------------------------------------------
# SPARQL query pagination
# ---------------------------------------------------------------------------

class TestSparqlQueryPagination:
    """test_sparql_query_pagination"""

    def test_offset_included_in_query(self):
        """_get_deputy_votes_page with offset=1000 must include OFFSET 1000 in the query string."""
        ingester = SparqlIngester(driver=MagicMock())
        dep_uri = "http://dati.camera.it/ocd/deputato.rdf/d308908_19"

        captured_queries = []

        def fake_sparql_get(query, timeout=30):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_deputy_votes_page(dep_uri, offset=1000)

        assert len(captured_queries) == 1
        assert "OFFSET 1000" in captured_queries[0]

    def test_zero_offset_not_included(self):
        """offset=0 should use OFFSET 0 or simply omit it — either way the query must work."""
        ingester = SparqlIngester(driver=MagicMock())
        dep_uri = "http://dati.camera.it/ocd/deputato.rdf/d308908_19"

        captured_queries = []

        def fake_sparql_get(query, timeout=30):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_deputy_votes_page(dep_uri, offset=0)

        assert len(captured_queries) == 1
        # Query must contain LIMIT clause
        assert "LIMIT" in captured_queries[0]

    def test_limit_is_page_size(self):
        """Query must include LIMIT equal to SPARQL_PAGE_SIZE."""
        ingester = SparqlIngester(driver=MagicMock())
        dep_uri = "http://dati.camera.it/ocd/deputato.rdf/d308908_19"

        captured_queries = []

        def fake_sparql_get(query, timeout=30):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_deputy_votes_page(dep_uri, offset=0)

        assert str(SPARQL_PAGE_SIZE) in captured_queries[0]


# ---------------------------------------------------------------------------
# Timeout / error handling
# ---------------------------------------------------------------------------

class TestSparqlTimeoutHandling:
    """test_sparql_timeout_handling"""

    def test_timeout_returns_empty_list(self):
        """_sparql_get must return [] on urllib.error.URLError (timeout)."""
        import urllib.error
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timed out")):
            result = _sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        assert result == []

    def test_http_error_returns_empty_list(self):
        """_sparql_get must return [] on urllib.error.HTTPError."""
        import urllib.error
        http_err = urllib.error.HTTPError(
            url="https://dati.camera.it/sparql",
            code=500,
            msg="Internal Server Error",
            hdrs=None,  # type: ignore[arg-type]
            fp=None,
        )
        with patch("urllib.request.urlopen", side_effect=http_err):
            result = _sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        assert result == []

    def test_exception_returns_empty_list(self):
        """_sparql_get must return [] on any unexpected exception."""
        with patch("urllib.request.urlopen", side_effect=Exception("unexpected")):
            result = _sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        assert result == []

    def test_valid_response_parsed(self):
        """_sparql_get must parse and return bindings on a valid JSON response."""
        bindings = [{"s": {"value": "http://example.com/foo"}}]
        response_json = json.dumps({
            "results": {"bindings": bindings}
        }).encode("utf-8")

        mock_response = MagicMock()
        mock_response.read.return_value = response_json
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_response):
            result = _sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")

        assert result == bindings


# ---------------------------------------------------------------------------
# Chamber-aware deputy filtering
# ---------------------------------------------------------------------------

class TestDeputyFiltering:
    """Tests that _fetch_all_deputies and _get_deputies_with_votes filter by chamber."""

    def _make_ingester_with_mock(self):
        driver = MagicMock()
        mock_neo_session = MagicMock()
        mock_neo_session.run.return_value = []
        driver.session.return_value.__enter__.return_value = mock_neo_session
        driver.session.return_value.__exit__.return_value = False
        return SparqlIngester(driver), mock_neo_session

    def test_fetch_all_deputies_cypher_has_chamber_filter(self):
        """_fetch_all_deputies must include coalesce(d.chamber,'camera')=$chamber filter."""
        ingester, mock_neo_session = self._make_ingester_with_mock()
        ingester._fetch_all_deputies(chamber="camera")
        call_args = mock_neo_session.run.call_args
        query = call_args[0][0]
        assert "coalesce(d.chamber, 'camera') = $chamber" in query

    def test_fetch_all_deputies_passes_chamber_kwarg(self):
        """_fetch_all_deputies must pass chamber= as a keyword arg to neo_session.run."""
        ingester, mock_neo_session = self._make_ingester_with_mock()
        ingester._fetch_all_deputies(chamber="camera")
        call_args = mock_neo_session.run.call_args
        assert call_args.kwargs.get("chamber") == "camera"

    def test_get_deputies_with_votes_cypher_has_chamber_filter(self):
        """_get_deputies_with_votes must include coalesce(d.chamber,'camera')=$chamber filter."""
        ingester, mock_neo_session = self._make_ingester_with_mock()
        ingester._get_deputies_with_votes(chamber="camera")
        call_args = mock_neo_session.run.call_args
        query = call_args[0][0]
        assert "coalesce(d.chamber, 'camera') = $chamber" in query

    def test_get_deputies_with_votes_passes_chamber_kwarg(self):
        """_get_deputies_with_votes must pass chamber= as a keyword arg to neo_session.run."""
        ingester, mock_neo_session = self._make_ingester_with_mock()
        ingester._get_deputies_with_votes(chamber="camera")
        call_args = mock_neo_session.run.call_args
        assert call_args.kwargs.get("chamber") == "camera"


# ---------------------------------------------------------------------------
# Vote-linking Cypher correctness (source inspection)
# ---------------------------------------------------------------------------

class TestVoteLinkingQuery:
    """Source-inspection tests: _write_votes Cypher must scope to chamber+legislature."""

    def test_write_votes_cypher_has_legislature_filter(self):
        """_write_votes Cypher must contain s.legislature = $legislature."""
        src = inspect.getsource(SparqlIngester._write_votes)
        assert "s.legislature = $legislature" in src

    def test_write_votes_cypher_has_chamber_filter(self):
        """_write_votes Cypher must contain coalesce(s.chamber,'camera') = $chamber."""
        src = inspect.getsource(SparqlIngester._write_votes)
        assert "coalesce(s.chamber, 'camera') = $chamber" in src


# ---------------------------------------------------------------------------
# Camera aggregate vote ingest
# ---------------------------------------------------------------------------

class TestCameraAggregateQuery:
    """Tests for Camera aggregate SPARQL query structure and Vote id format."""

    def test_query_contains_select_distinct(self):
        """The camera aggregate query for a sitting must use SELECT DISTINCT
        (each votazione has two rdf:type triples — without DISTINCT rows are doubled)."""
        ingester = SparqlIngester(driver=MagicMock())
        captured_queries: list[str] = []

        def fake_sparql_get(query, timeout=30, max_retries=3):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_camera_votes_for_sitting(19, 405)

        assert len(captured_queries) == 1
        assert "SELECT DISTINCT" in captured_queries[0]

    def test_query_contains_correct_seduta_uri(self):
        """The aggregate query for (leg=19, session=405) must reference seduta.rdf/s19_405."""
        ingester = SparqlIngester(driver=MagicMock())
        captured_queries: list[str] = []

        def fake_sparql_get(query, timeout=30, max_retries=3):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_camera_votes_for_sitting(19, 405)

        assert "seduta.rdf/s19_405" in captured_queries[0]

    def test_query_tries_padded_and_unpadded_seduta_uri(self):
        """dati.camera.it writes rif_seduta both as s19_004 and s19_24."""
        ingester = SparqlIngester(driver=MagicMock())
        captured_queries: list[str] = []

        def fake_sparql_get(query, timeout=30, max_retries=3):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_camera_votes_for_sitting(19, 4)

        assert "seduta.rdf/s19_4>" in captured_queries[0]
        assert "seduta.rdf/s19_004>" in captured_queries[0]

    def test_query_contains_approvato(self):
        """The aggregate query must request ocd:approvato (Camera outcome flag)."""
        ingester = SparqlIngester(driver=MagicMock())
        captured_queries: list[str] = []

        def fake_sparql_get(query, timeout=30, max_retries=3):
            captured_queries.append(query)
            return []

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            ingester._get_camera_votes_for_sitting(19, 405)

        assert "ocd:approvato" in captured_queries[0]

    def test_aggregate_vote_id_format(self):
        """Vote id for (leg=19, session=405, vote=13) must be 'camera_leg19_sed405_v013'."""
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={405})
        ingester._get_camera_vote_numbers = MagicMock(return_value={})

        vote_uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_405_013"
        ingester._get_camera_votes_for_sitting = MagicMock(return_value=[{
            "votazione": {"value": vote_uri},
            "approvato": {"value": "1"},
        }])

        written_ids: list[str] = []

        def fake_write(batch, legislature):
            for item in batch:
                written_ids.append(item["id"])
            return len(batch)

        ingester._write_camera_aggregate_votes = fake_write
        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=405)

        assert "camera_leg19_sed405_v013" in written_ids


class TestCameraAggregateSkip:
    """Tests that ingest_camera_aggregate_votes skips votazioni already in the graph."""

    @staticmethod
    def _binding(session: int, vote: int) -> dict:
        return {"votazione": {"value": f"http://dati.camera.it/ocd/votazione.rdf/vs19_{session:03d}_{vote:03d}"}}

    def test_writes_only_missing_vote_numbers(self):
        """A sitting with votes 1-2 from XML gets only the missing vote 3 (the final one)."""
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={210})
        ingester._get_camera_vote_numbers = MagicMock(return_value={210: {1, 2}})
        ingester._get_camera_votes_for_sitting = MagicMock(
            return_value=[self._binding(210, n) for n in (1, 2, 3)]
        )
        written: list[dict] = []
        ingester._write_camera_aggregate_votes = lambda batch, legislature: written.extend(batch) or len(batch)

        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=1)

        assert [w["voteNumber"] for w in written] == [3]

    def test_sitting_with_all_votes_writes_nothing(self):
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={349})
        ingester._get_camera_vote_numbers = MagicMock(return_value={349: {1}})
        ingester._get_camera_votes_for_sitting = MagicMock(return_value=[self._binding(349, 1)])
        ingester._write_camera_aggregate_votes = MagicMock(return_value=0)

        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=1)

        ingester._write_camera_aggregate_votes.assert_not_called()

    def test_only_sessions_overrides_start_session(self):
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={4, 210, 405})
        ingester._get_camera_vote_numbers = MagicMock(return_value={})
        ingester._get_camera_votes_for_sitting = MagicMock(return_value=[])
        ingester._write_camera_aggregate_votes = MagicMock(return_value=0)

        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=350, only_sessions={4, 210})

        fetched = [c[0][1] for c in ingester._get_camera_votes_for_sitting.call_args_list]
        assert fetched == [4, 210]

    def test_start_session_filters_earlier_sittings(self):
        """Sittings below start_session must be excluded from the fetch."""
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={200, 405})
        ingester._get_camera_vote_numbers = MagicMock(return_value={})
        ingester._get_camera_votes_for_sitting = MagicMock(return_value=[])
        ingester._write_camera_aggregate_votes = MagicMock(return_value=0)

        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=350)

        calls = ingester._get_camera_votes_for_sitting.call_args_list
        fetched_sessions = [c[0][1] for c in calls]
        assert 200 not in fetched_sessions
        assert 405 in fetched_sessions


class TestCameraAggregateOutcome:
    """Tests for aggregate Vote outcome derivation from ocd:approvato."""

    def _run_ingest_with_approvato(self, approvato_value: Optional[str]) -> list[dict]:
        ingester = SparqlIngester(driver=MagicMock())
        ingester._get_camera_sittings_in_db = MagicMock(return_value={405})
        ingester._get_camera_vote_numbers = MagicMock(return_value={})

        vote_uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_405_001"
        binding: dict = {"votazione": {"value": vote_uri}}
        if approvato_value is not None:
            binding["approvato"] = {"value": approvato_value}
        ingester._get_camera_votes_for_sitting = MagicMock(return_value=[binding])

        written_batches: list[dict] = []

        def fake_write(batch, legislature):
            written_batches.extend(batch)
            return len(batch)

        ingester._write_camera_aggregate_votes = fake_write
        ingester.ingest_camera_aggregate_votes(legislature=19, start_session=405)
        return written_batches

    def test_approvato_one_maps_to_approved(self):
        """ocd:approvato '1' must produce outcome 'approved'."""
        batches = self._run_ingest_with_approvato("1")
        assert len(batches) == 1
        assert batches[0]["outcome"] == "approved"

    def test_approvato_zero_maps_to_rejected(self):
        """ocd:approvato '0' must produce outcome 'rejected'."""
        batches = self._run_ingest_with_approvato("0")
        assert len(batches) == 1
        assert batches[0]["outcome"] == "rejected"

    def test_missing_approvato_maps_to_unknown(self):
        """Missing ocd:approvato must produce outcome 'unknown'."""
        batches = self._run_ingest_with_approvato(None)
        assert len(batches) == 1
        assert batches[0]["outcome"] == "unknown"


class TestCameraVoteGaps:
    """find_camera_vote_gaps compares dati.camera.it with the graph per vote number."""

    def test_reports_empty_and_partial_sittings(self):
        ingester = SparqlIngester(driver=MagicMock())
        uri = "http://dati.camera.it/ocd/votazione.rdf/vs19_{:03d}_{:03d}".format
        ingester._get_camera_votazioni = MagicMock(return_value={
            4: {1: uri(4, 1)},
            33: {68: uri(33, 68), 69: uri(33, 69)},
            400: {1: uri(400, 1)},
        })
        ingester._get_camera_vote_numbers = MagicMock(return_value={33: {68}, 400: {1}})
        ingester._get_camera_votes_without_individuals = MagicMock(return_value={400: {1}, 33: {68}})
        # 33/68 is an annulled votazione: published without votes, not a gap
        ingester._get_votazioni_with_votes = MagicMock(return_value={uri(400, 1)})

        missing, without_individuals = ingester.find_camera_vote_gaps(19)

        assert missing == {4: {1: uri(4, 1)}, 33: {69: uri(33, 69)}}
        assert without_individuals == {400: {1: uri(400, 1)}}

    def test_strict_sparql_raises_when_endpoint_fails(self):
        """A 502 must not look like 'no votes' to the gap filler."""
        import pytest
        import urllib.error
        from sparql_ingester import SparqlUnavailable, _sparql_get

        err = urllib.error.HTTPError("u", 502, "Bad Gateway", None, None)
        with patch("urllib.request.urlopen", side_effect=err), patch("time.sleep"):
            assert _sparql_get("SELECT", max_retries=1) == []
            with pytest.raises(SparqlUnavailable):
                _sparql_get("SELECT", max_retries=1, strict=True)

    def test_votazioni_listing_uses_keyset_pagination(self):
        ingester = SparqlIngester(driver=MagicMock())
        captured: list[str] = []

        def fake_sparql_get(query, timeout=30, max_retries=3, strict=False):
            captured.append(query)
            return [{"votazione": {"value": "http://dati.camera.it/ocd/votazione.rdf/vs19_004_001"}}]

        with patch("sparql_ingester._sparql_get", side_effect=fake_sparql_get):
            out = ingester._get_camera_votazioni(19)

        assert out == {4: {1: "http://dati.camera.it/ocd/votazione.rdf/vs19_004_001"}}
        assert "OFFSET" not in captured[0]
        assert "FILTER(STR(?votazione) >" in captured[0]
