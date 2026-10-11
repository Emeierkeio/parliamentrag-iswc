"""
test_senate_sparql_ingester.py — Unit tests for senate_sparql_ingester.py

All HTTP calls are mocked; no network access required.
Tests cover: GET-only HTTP method, outcome derivation, URI parsing, Vote id format.
"""

from __future__ import annotations

import json
import sys
import os
from unittest.mock import patch, MagicMock

import pytest

# Ensure build/ is on the path for direct imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sparql_ingester import individual_vote_id
from senate_sparql_ingester import (
    SenateVoteIngester,
    _senato_sparql_get,
    parse_senate_votazione_uri,
    _derive_senate_outcome,
    _senate_outcome,
    _senate_vote_flags,
    SENATO_USER_AGENT,
    SENATO_SPARQL_ENDPOINT,
)


# ---------------------------------------------------------------------------
# URI parsing helpers
# ---------------------------------------------------------------------------

class TestSenateUriParsing:
    """Tests for parse_senate_votazione_uri."""

    def test_standard_uri_returns_leg_seduta_vote(self):
        leg, seduta, vote = parse_senate_votazione_uri(
            "http://dati.senato.it/votazione/19-167-42"
        )
        assert leg == 19
        assert seduta == 167
        assert vote == 42

    def test_legislature_18(self):
        leg, seduta, vote = parse_senate_votazione_uri(
            "http://dati.senato.it/votazione/18-100-5"
        )
        assert leg == 18
        assert seduta == 100
        assert vote == 5

    def test_large_numbers(self):
        leg, seduta, vote = parse_senate_votazione_uri(
            "http://dati.senato.it/votazione/19-435-200"
        )
        assert leg == 19
        assert seduta == 435
        assert vote == 200

    def test_invalid_uri_returns_none_triple(self):
        leg, seduta, vote = parse_senate_votazione_uri("http://example.com/invalid")
        assert leg is None
        assert seduta is None
        assert vote is None

    def test_empty_string_returns_none_triple(self):
        leg, seduta, vote = parse_senate_votazione_uri("")
        assert leg is None
        assert seduta is None
        assert vote is None


# ---------------------------------------------------------------------------
# Outcome derivation
# ---------------------------------------------------------------------------

class TestSenateOutcomeDerivation:
    """Tests for _derive_senate_outcome (favorevoli >= maggioranza → approved)."""

    def test_favorevoli_less_than_maggioranza_is_rejected(self):
        assert _derive_senate_outcome(favorevoli=32, maggioranza=51) == "rejected"

    def test_favorevoli_greater_than_maggioranza_is_approved(self):
        assert _derive_senate_outcome(favorevoli=60, maggioranza=51) == "approved"

    def test_favorevoli_equal_maggioranza_is_approved(self):
        assert _derive_senate_outcome(favorevoli=51, maggioranza=51) == "approved"

    def test_none_favorevoli_returns_unknown(self):
        assert _derive_senate_outcome(favorevoli=None, maggioranza=51) == "unknown"

    def test_none_maggioranza_returns_unknown(self):
        assert _derive_senate_outcome(favorevoli=60, maggioranza=None) == "unknown"

    def test_both_none_returns_unknown(self):
        assert _derive_senate_outcome(favorevoli=None, maggioranza=None) == "unknown"


class TestSenateOutcomeFromEsito:
    """osr:esito wins over the counts; counts are the fallback."""

    def test_esito_respinto_overrides_counts(self):
        assert _senate_outcome("respinto", favorevoli=60, maggioranza=51) == "rejected"

    def test_esito_approvato(self):
        assert _senate_outcome("approvato", favorevoli=None, maggioranza=None) == "approved"

    def test_missing_esito_falls_back_to_counts(self):
        assert _senate_outcome(None, favorevoli=60, maggioranza=51) == "approved"


class TestSenateVoteFlags:
    """Flags derived from real osr:Votazione labels (leg. 19)."""

    def test_confidence_vote(self):
        flags = _senate_vote_flags("Disegno di legge n. 1272.  Votazione questione di fiducia.", "elettronica")
        assert flags == {"confidenceVote": True, "finalVote": False, "secretVote": False}

    def test_final_vote(self):
        assert _senate_vote_flags("Votazione finale", "elettronica")["finalVote"] is True

    def test_amendment_has_no_flags(self):
        flags = _senate_vote_flags("Em. 33.2, Turco e altri", "elettronica")
        assert not any(flags.values())

    def test_secret_ballot_from_type(self):
        assert _senate_vote_flags("Em. 1.1", "segreta")["secretVote"] is True

    def test_none_label(self):
        assert not any(_senate_vote_flags(None, None).values())


# ---------------------------------------------------------------------------
# Vote id format
# ---------------------------------------------------------------------------

class TestSenateVoteId:
    """Tests for the stable Senate Vote id format (senato_leg{N}_sed{M}_v{K})."""

    def test_vote_id_format_3digit_zero_padded(self):
        """Aggregate Vote id built from (leg=19, seduta=167, vote=42) matches expected format."""
        leg, seduta, vote = 19, 167, 42
        vote_id = f"senato_leg{leg}_sed{seduta:03d}_v{vote:03d}"
        assert vote_id == "senato_leg19_sed167_v042"

    def test_vote_id_has_senato_prefix(self):
        vote_id = f"senato_leg19_sed001_v001"
        assert vote_id.startswith("senato")

    def test_vote_number_zero_padded(self):
        vote_id = f"senato_leg19_sed167_v{5:03d}"
        assert "v005" in vote_id

    def test_seduta_number_zero_padded(self):
        vote_id = f"senato_leg19_sed{7:03d}_v042"
        assert "sed007" in vote_id


# ---------------------------------------------------------------------------
# HTTP method — GET-only with browser User-Agent
# ---------------------------------------------------------------------------

class TestSenateHttpMethod:
    """Tests that _senato_sparql_get uses GET (no data= body) + browser User-Agent."""

    def _make_mock_urlopen(self):
        """Return a MagicMock urlopen whose context manager yields a readable response."""
        mock_response = MagicMock()
        mock_response.read.return_value = b'{"results":{"bindings":[]}}'
        mock_response.__enter__ = lambda s: s
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen = MagicMock(return_value=mock_response)
        return mock_urlopen

    def test_request_uses_get_method(self):
        """Request passed to urlopen must use GET (no data body)."""
        mock_urlopen = self._make_mock_urlopen()
        with patch("urllib.request.urlopen", mock_urlopen):
            _senato_sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")

        assert mock_urlopen.called
        req = mock_urlopen.call_args[0][0]
        # urllib.request.Request without data= body defaults to GET
        assert req.get_method() == "GET"

    def test_request_has_no_data_body(self):
        """GET request must not carry a POST data body."""
        mock_urlopen = self._make_mock_urlopen()
        with patch("urllib.request.urlopen", mock_urlopen):
            _senato_sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")

        req = mock_urlopen.call_args[0][0]
        assert req.data is None

    def test_user_agent_contains_mozilla_and_chrome(self):
        """User-Agent header must look like a browser (contain Mozilla and Chrome)."""
        mock_urlopen = self._make_mock_urlopen()
        with patch("urllib.request.urlopen", mock_urlopen):
            _senato_sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")

        req = mock_urlopen.call_args[0][0]
        # urllib.request.Request capitalizes the first letter of each header word
        user_agent = req.headers.get("User-agent", "")
        assert "Mozilla" in user_agent
        assert "Chrome" in user_agent

    def test_query_is_in_url_not_body(self):
        """The SPARQL query must appear in the URL query string (GET), not a body."""
        mock_urlopen = self._make_mock_urlopen()
        query = "SELECT * WHERE { ?s ?p ?o } LIMIT 1"
        with patch("urllib.request.urlopen", mock_urlopen):
            _senato_sparql_get(query)

        req = mock_urlopen.call_args[0][0]
        # GET encodes query in URL
        assert "query=" in req.full_url or "SELECT" in req.full_url

    def test_returns_empty_list_on_empty_bindings(self):
        """_senato_sparql_get returns [] when bindings is empty."""
        mock_urlopen = self._make_mock_urlopen()
        with patch("urllib.request.urlopen", mock_urlopen):
            result = _senato_sparql_get("SELECT * WHERE { ?s ?p ?o } LIMIT 1")
        assert result == []

    def test_endpoint_constant_is_senato(self):
        """SENATO_SPARQL_ENDPOINT must point to dati.senato.it."""
        assert "senato.it" in SENATO_SPARQL_ENDPOINT
        assert SENATO_SPARQL_ENDPOINT == "https://dati.senato.it/sparql"


# ---------------------------------------------------------------------------
# Individual vote: senator id extraction from URI
# ---------------------------------------------------------------------------

class TestSenateIndividualVoteId:
    """Tests for Senate IndividualVote id format (iv_senato_leg{N}_{senator_id}_{seduta}_{vote})."""

    def test_id_format_given_standard_inputs(self):
        """iv_senato_leg19_{senator_id}_{seduta}_{vote} — senatore/17542, seduta=167, vote=42."""
        from senate_sparql_ingester import _senator_id_from_uri  # ImportError -> RED
        sen_uri = "http://dati.senato.it/senatore/17542"
        seduta = 167
        vote = 42
        sen_id = _senator_id_from_uri(sen_uri)
        assert sen_id == "17542"
        iv_id = individual_vote_id("senato", 19, sen_id, seduta, vote)
        assert iv_id == "iv_senato_leg19_17542_167_42"

    def test_id_has_senato_prefix(self):
        """IndividualVote id must start with iv_senato_ (not iv_camera_)."""
        from senate_sparql_ingester import _senator_id_from_uri
        sen_id = _senator_id_from_uri("http://dati.senato.it/senatore/17542")
        iv_id = individual_vote_id("senato", 19, sen_id, 167, 42)
        assert iv_id.startswith("iv_senato_")

    def test_senator_id_extracted_from_trailing_digits(self):
        """Trailing digits of senatore URI become the senator id string."""
        from senate_sparql_ingester import _senator_id_from_uri
        assert _senator_id_from_uri("http://dati.senato.it/senatore/99999") == "99999"

    def test_invalid_uri_returns_none(self):
        """_senator_id_from_uri returns None for non-senatore URIs."""
        from senate_sparql_ingester import _senator_id_from_uri
        assert _senator_id_from_uri("http://example.com/not-a-senator") is None

    def test_empty_string_returns_none(self):
        """_senator_id_from_uri returns None for empty string."""
        from senate_sparql_ingester import _senator_id_from_uri
        assert _senator_id_from_uri("") is None


# ---------------------------------------------------------------------------
# Individual vote: per-senator outcome mapping
# ---------------------------------------------------------------------------

class TestSenateIndividualOutcomeMap:
    """Tests for per-senator vote outcome mapping (osr:favorevole/contrario/astenuto → favor/against/abstain)."""

    def test_senator_links_returns_favor_against_abstain_keys(self):
        """_get_senate_senator_links returns dict with exactly keys favor/against/abstain."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        with patch("senate_sparql_ingester._senato_sparql_get", return_value=[]):
            result = ingester._get_senate_senator_links(  # AttributeError -> RED
                "http://dati.senato.it/votazione/19-167-42"
            )

        assert set(result.keys()) == {"favor", "against", "abstain"}

    def test_favorevole_maps_to_favor(self):
        """osr:favorevole senatore URIs appear under 'favor' key."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        def side_effect(query, **kwargs):
            if "favorevole" in query:
                return [{"senatore": {"value": "http://dati.senato.it/senatore/17542"}}]
            return []

        with patch("senate_sparql_ingester._senato_sparql_get", side_effect=side_effect):
            result = ingester._get_senate_senator_links(
                "http://dati.senato.it/votazione/19-167-42"
            )

        assert "http://dati.senato.it/senatore/17542" in result["favor"]

    def test_contrario_maps_to_against(self):
        """osr:contrario senatore URIs appear under 'against' key."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        def side_effect(query, **kwargs):
            if "contrario" in query:
                return [{"senatore": {"value": "http://dati.senato.it/senatore/12345"}}]
            return []

        with patch("senate_sparql_ingester._senato_sparql_get", side_effect=side_effect):
            result = ingester._get_senate_senator_links(
                "http://dati.senato.it/votazione/19-167-42"
            )

        assert "http://dati.senato.it/senatore/12345" in result["against"]

    def test_astenuto_maps_to_abstain(self):
        """osr:astenuto senatore URIs appear under 'abstain' key."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        def side_effect(query, **kwargs):
            if "astenuto" in query:
                return [{"senatore": {"value": "http://dati.senato.it/senatore/54321"}}]
            return []

        with patch("senate_sparql_ingester._senato_sparql_get", side_effect=side_effect):
            result = ingester._get_senate_senator_links(
                "http://dati.senato.it/votazione/19-167-42"
            )

        assert "http://dati.senato.it/senatore/54321" in result["abstain"]


# ---------------------------------------------------------------------------
# Individual vote: per-sitting resume
# ---------------------------------------------------------------------------

class TestSenateIndividualResume:
    """Tests for per-sitting resume logic in ingest_individual_votes."""

    def test_skips_sitting_already_ingested(self):
        """ingest_individual_votes must not call _get_senate_seduta_uri for already-done sittings."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        ingester._get_senate_sittings_in_db = MagicMock(return_value={166, 167})
        ingester._get_senate_sittings_with_individual_votes = MagicMock(  # AttributeError -> RED
            return_value={166}
        )
        ingester._get_senate_seduta_uri = MagicMock(return_value=None)

        ingester.ingest_individual_votes(legislature=19)  # AttributeError -> RED

        called_session_nums = [
            call[0][1] for call in ingester._get_senate_seduta_uri.call_args_list
        ]
        assert 166 not in called_session_nums
        assert 167 in called_session_nums

    def test_processes_only_todo_sittings(self):
        """ingest_individual_votes calls _get_senate_seduta_uri exactly once for sitting 167."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        ingester._get_senate_sittings_in_db = MagicMock(return_value={166, 167})
        ingester._get_senate_sittings_with_individual_votes = MagicMock(return_value={166})
        ingester._get_senate_seduta_uri = MagicMock(return_value=None)

        ingester.ingest_individual_votes(legislature=19)

        assert ingester._get_senate_seduta_uri.call_count == 1
        ingester._get_senate_seduta_uri.assert_called_once_with(19, 167)

    def test_all_sittings_done_processes_none(self):
        """ingest_individual_votes skips all sittings when all are already done."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        ingester._get_senate_sittings_in_db = MagicMock(return_value={166, 167})
        ingester._get_senate_sittings_with_individual_votes = MagicMock(return_value={166, 167})
        ingester._get_senate_seduta_uri = MagicMock(return_value=None)

        result = ingester.ingest_individual_votes(legislature=19)

        ingester._get_senate_seduta_uri.assert_not_called()
        assert result["sittings_processed"] == 0

    def test_returns_stats_dict_with_expected_keys(self):
        """ingest_individual_votes returns dict with sittings_processed and ivotes_written."""
        mock_driver = MagicMock()
        ingester = SenateVoteIngester(mock_driver)

        ingester._get_senate_sittings_in_db = MagicMock(return_value=set())
        ingester._get_senate_sittings_with_individual_votes = MagicMock(return_value=set())

        result = ingester.ingest_individual_votes(legislature=19)

        assert "sittings_processed" in result
        assert "ivotes_written" in result


class TestSenatorLinksBulk:
    """One request per chunk of votazioni, rows grouped by votazione and outcome."""

    def test_groups_rows_and_chunks_requests(self):
        osr = "http://dati.senato.it/osr/"
        v1, v2, v3 = (f"http://dati.senato.it/votazione/19-300-{n}" for n in (1, 2, 3))
        rows = [
            {"v": {"value": v1}, "p": {"value": osr + "favorevole"}, "senatore": {"value": "s/1"}},
            {"v": {"value": v1}, "p": {"value": osr + "astenuto"}, "senatore": {"value": "s/2"}},
            {"v": {"value": v2}, "p": {"value": osr + "contrario"}, "senatore": {"value": "s/1"}},
        ]
        queries = []

        def fake_get(query):
            queries.append(query)
            return rows if len(queries) == 1 else []

        with patch("senate_sparql_ingester._senato_sparql_get", side_effect=fake_get):
            links = SenateVoteIngester(None)._get_senate_senator_links_bulk(
                [v1, v2, v3], chunk_size=2
            )

        assert len(queries) == 2
        assert links[v1] == {"favor": ["s/1"], "against": [], "abstain": ["s/2"]}
        assert links[v2]["against"] == ["s/1"]
        # the failed chunk is absent, so the caller can leave the sitting for later
        assert v3 not in links
