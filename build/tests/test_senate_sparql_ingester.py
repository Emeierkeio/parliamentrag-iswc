"""
test_senate_sparql_ingester.py — Unit tests for senate_sparql_ingester.py

All HTTP calls are mocked; no network access required.
Tests cover: GET-only HTTP method, outcome derivation, URI parsing, Vote id format.
"""

from __future__ import annotations

import sys
import os
from unittest.mock import patch, MagicMock


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

    def test_no_confidence_motion_is_not_a_confidence_vote(self):
        label = "Mozione n.62, Patuanelli e altri, di sfiducia individuale nei confronti del Ministro"
        assert _senate_vote_flags(label, "elettronica")["confidenceVote"] is False

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
# Individual votes: bulk links, per-vote resume, failures
# ---------------------------------------------------------------------------

OSR = "http://dati.senato.it/osr/"


def _row(v, prop, sen):
    return {"v": {"value": v}, "p": {"value": OSR + prop}, "senatore": {"value": sen}}


class TestSenatorLinksBulk:
    """One request per chunk of votazioni, rows grouped by votazione and outcome."""

    def test_groups_rows_by_votazione_and_outcome(self):
        v1, v2 = (f"http://dati.senato.it/votazione/19-300-{n}" for n in (1, 2))
        rows = [_row(v1, "favorevole", "s/1"), _row(v1, "astenuto", "s/2"),
                _row(v1, "inCongedoMissione", "s/3"), _row(v2, "contrario", "s/1")]
        seduta = "http://dati.senato.it/sedutaassemblea/24207"
        with patch("senate_sparql_ingester._senato_sparql_get", return_value=rows) as get:
            links = SenateVoteIngester(None)._get_senate_senator_links_bulk([(seduta, 1, 2)])
        assert get.call_count == 1
        assert get.call_args.kwargs["strict"] is True
        query = get.call_args.args[0]
        assert f"?v osr:seduta <{seduta}>" in query and "?n >= 1 && ?n <= 2" in query
        assert "?p = osr:inCongedoMissione" in query and "?p = osr:presenteNonVotante" in query
        assert links[v1] == {("favor", None): ["s/1"], ("abstain", None): ["s/2"],
                             ("absent", "mission"): ["s/3"]}
        assert links[v2] == {("against", None): ["s/1"]}

    def test_reasons_only_asks_two_predicates(self):
        from senate_sparql_ingester import REASON_PREDICATES
        seduta = "http://dati.senato.it/sedutaassemblea/24207"
        with patch("senate_sparql_ingester._senato_sparql_get", return_value=[]) as get:
            SenateVoteIngester(None)._get_senate_senator_links_bulk([(seduta, 1, 2)], REASON_PREDICATES)
        query = get.call_args.args[0]
        assert "osr:favorevole" not in query and "?p = osr:presenteNonVotante" in query


def _pending(n_votes, session=300):
    return [{"session": session, "vote": k, "id": f"senato_leg19_sed{session}_v{k:03d}",
             "expected": 1} for k in range(1, n_votes + 1)]


class TestIndividualIngest:
    def _ingester(self, pending):
        ing = SenateVoteIngester(MagicMock())
        ing._get_votes_without_individual_votes = MagicMock(return_value=pending)
        ing._get_senate_seduta_uris = MagicMock(
            return_value={n: f"http://dati.senato.it/sedutaassemblea/{n}" for n in range(1, 500)}
        )
        ing._get_votes_without_reasons = MagicMock(return_value=pending)
        ing._write_senate_individual_votes = MagicMock(side_effect=lambda b: len(b))
        ing._mark_individual_missing = MagicMock()
        ing._mark_reasons_checked = MagicMock()
        return ing

    def test_packs_votes_across_sittings(self):
        pending = _pending(15, session=300) + _pending(10, session=301)
        ing = self._ingester(pending)
        ing._get_senate_senator_links_bulk = MagicMock(return_value={})
        ing.ingest_individual_votes(19)
        assert ing._get_senate_senator_links_bulk.call_count == 1
        ranges = ing._get_senate_senator_links_bulk.call_args.args[0]
        assert [(lo, hi) for _, lo, hi in ranges] == [(1, 15), (1, 10)]

    def test_vote_without_names_is_marked(self):
        ing = self._ingester(_pending(2))
        v1 = "http://dati.senato.it/votazione/19-300-1"
        ing._get_senate_senator_links_bulk = MagicMock(
            return_value={v1: {("favor", None): ["http://dati.senato.it/senatore/1"]}}
        )
        stats = ing.ingest_individual_votes(19)
        assert stats["ivotes_written"] == 1
        ing._mark_individual_missing.assert_called_once_with(["senato_leg19_sed300_v002"])
        ing._mark_reasons_checked.assert_called_once_with(["senato_leg19_sed300_v001"])

    def test_only_leave_counts_as_without_names(self):
        # Names of senators on leave alone do not make a roll call
        ing = self._ingester(_pending(1))
        v1 = "http://dati.senato.it/votazione/19-300-1"
        ing._get_senate_senator_links_bulk = MagicMock(
            return_value={v1: {("absent", "mission"): ["http://dati.senato.it/senatore/1"]}}
        )
        ing.ingest_individual_votes(19)
        ing._mark_individual_missing.assert_called_once_with(["senato_leg19_sed300_v001"])

    def test_reasons_only_writes_reason_on_ingester_id(self):
        ing = self._ingester(_pending(2))
        v1 = "http://dati.senato.it/votazione/19-300-1"
        ing._get_senate_senator_links_bulk = MagicMock(
            return_value={v1: {("absent", "mission"): ["http://dati.senato.it/senatore/7"]}}
        )
        ing.ingest_individual_votes(19, reasons_only=True)
        ing._get_votes_without_individual_votes.assert_not_called()
        batch = ing._write_senate_individual_votes.call_args.args[0]
        assert batch == [{"id": "iv_senato_leg19_7_300_1", "senatorUri": "http://dati.senato.it/senatore/7",
                          "voteId": "senato_leg19_sed300_v001", "outcome": "absent", "reason": "mission"}]
        ing._mark_individual_missing.assert_not_called()
        ing._mark_reasons_checked.assert_called_once_with(
            ["senato_leg19_sed300_v001", "senato_leg19_sed300_v002"])

    def test_failed_request_marks_nothing(self):
        from senate_sparql_ingester import SenateRequestFailed
        ing = self._ingester(_pending(3))
        ing._get_senate_senator_links_bulk = MagicMock(side_effect=SenateRequestFailed("500"))
        stats = ing.ingest_individual_votes(19)
        ing._mark_individual_missing.assert_not_called()
        assert stats["ivotes_written"] == 0 and not stats["aborted"]

    def test_blocked_endpoint_aborts(self):
        from senate_sparql_ingester import SenateEndpointBlocked
        ing = self._ingester(_pending(60))
        ing._get_senate_senator_links_bulk = MagicMock(side_effect=SenateEndpointBlocked("403"))
        stats = ing.ingest_individual_votes(19)
        assert stats["aborted"] and ing._get_senate_senator_links_bulk.call_count == 1


class TestPackRanges:
    def _p(self, session, vote):
        return {"session": session, "vote": vote, "id": f"{session}-{vote}", "expected": 1}

    def test_width_counts_gaps(self):
        from senate_sparql_ingester import _pack_ranges
        # votes 1 and 100 of one sitting: a single range 1..100 would exceed the budget
        chunks = _pack_ranges([self._p(300, 1), self._p(300, 100)])
        assert len(chunks) == 2

    def test_big_sitting_split(self):
        from senate_sparql_ingester import _pack_ranges, INDIVIDUAL_CHUNK
        chunks = _pack_ranges([self._p(300, v) for v in range(1, 101)])
        assert all(c[-1]["vote"] - c[0]["vote"] + 1 <= INDIVIDUAL_CHUNK for c in chunks)
        assert sum(len(c) for c in chunks) == 100 and len(chunks) == 3

    def test_small_sittings_packed_up_to_limit(self):
        from senate_sparql_ingester import _pack_ranges, INDIVIDUAL_SITTINGS
        chunks = _pack_ranges([self._p(n, 1) for n in range(1, 31)])
        assert [len(c) for c in chunks[:-1]] == [INDIVIDUAL_SITTINGS] * (len(chunks) - 1)
        assert sum(len(c) for c in chunks) == 30


class TestAggregateIngest:
    def _ingester(self, in_db, checked):
        ing = SenateVoteIngester(MagicMock())
        ing._get_senate_sittings_in_db = MagicMock(return_value=set(in_db))
        ing._get_senate_sittings_checked = MagicMock(return_value=set(checked))
        ing._get_senate_seduta_uris = MagicMock(
            return_value={n: f"http://dati.senato.it/sedutaassemblea/{n}" for n in in_db}
        )
        ing._write_senate_votes = MagicMock(side_effect=lambda b, leg: len(b))
        ing._mark_sittings_checked = MagicMock()
        return ing

    def test_checked_sittings_cost_no_request(self):
        ing = self._ingester(range(1, 31), checked=range(1, 26))
        ing._get_senate_votes_for_sedute = MagicMock(return_value=[])
        ing.ingest_aggregate_votes(19)
        assert ing._get_senate_votes_for_sedute.call_count == 1
        ing._mark_sittings_checked.assert_called_once_with(19, [26, 27, 28, 29, 30])

    def test_sittings_batched(self):
        import math
        from senate_sparql_ingester import SITTING_CHUNK
        ing = self._ingester(range(1, 46), checked=())
        ing._get_senate_votes_for_sedute = MagicMock(return_value=[])
        ing.ingest_aggregate_votes(19)
        assert ing._get_senate_votes_for_sedute.call_count == math.ceil(45 / SITTING_CHUNK)

    def test_failed_chunk_not_marked_checked(self):
        from senate_sparql_ingester import SenateRequestFailed
        ing = self._ingester(range(1, 6), checked=())
        ing._get_senate_votes_for_sedute = MagicMock(side_effect=SenateRequestFailed("500"))
        stats = ing.ingest_aggregate_votes(19)
        ing._mark_sittings_checked.assert_not_called()
        assert not stats["aborted"]

    def test_rows_mapped_to_sitting(self):
        ing = self._ingester([300], checked=())
        ing._get_senate_votes_for_sedute = MagicMock(return_value=[{
            "seduta": {"value": "http://dati.senato.it/sedutaassemblea/300"},
            "votazione": {"value": "http://dati.senato.it/votazione/19-300-2"},
            "favorevoli": {"value": "83"}, "contrari": {"value": "52"},
            "astenuti": {"value": "0"}, "maggioranza": {"value": "68"},
            "esito": {"value": "approvato"}, "label": {"value": "Votazione finale"},
        }])
        ing.ingest_aggregate_votes(19)
        row = ing._write_senate_votes.call_args.args[0][0]
        assert row["id"] == "senato_leg19_sed300_v002"
        assert row["outcome"] == "approved" and row["finalVote"] is True


class TestUrlSize:
    """Worst-case requests stay under the WAF's GET URL limit."""

    def _url_len(self, query):
        import urllib.parse
        return len(urllib.parse.urlencode({"query": query, "format": "application/sparql-results+json"}))

    def test_requests_fit_the_waf_limit(self):
        import senate_sparql_ingester as m
        captured = []
        ing = SenateVoteIngester(None)
        with patch.object(m, "_senato_sparql_get", side_effect=lambda q, **k: captured.append(q) or []):
            ing._get_senate_votes_for_sedute(
                [f"http://dati.senato.it/sedutaassemblea/{24000 + i}" for i in range(m.SITTING_CHUNK)]
            )
            ing._get_senate_senator_links_bulk(
                [(f"http://dati.senato.it/sedutaassemblea/{24000 + i}", 100, 145)
                 for i in range(m.INDIVIDUAL_SITTINGS)]
            )
        assert all(self._url_len(q) <= m.MAX_URL_CHARS for q in captured), [self._url_len(q) for q in captured]
