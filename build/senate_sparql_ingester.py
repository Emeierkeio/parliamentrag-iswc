"""
senate_sparql_ingester.py — Senate aggregate vote ingest from dati.senato.it via SPARQL

Ingests Senate aggregate Vote nodes for both legislatures (XVIII, XIX) from the Italian
Senate SPARQL endpoint. Senate endpoint requires GET requests with a browser User-Agent
(POST returns 403). Queries are scoped per-seduta to avoid 5xx timeouts from global
Votazione queries.

Schema:
    Session {chamber:'senato'} -[:HAS_VOTE]-> Vote

Vote id format: senato_leg{N}_sed{MMM}_v{KKK}  (no collision with Camera or XML-sourced nodes)
Outcome derivation: favorevoli >= maggioranza -> "approved" else "rejected" (no approvato flag).

Usage (CLI):
    python build/senate_sparql_ingester.py --aggregate-only --legislature 19

Usage (library):
    from senate_sparql_ingester import SenateVoteIngester
    ingester = SenateVoteIngester(driver)
    stats = ingester.ingest_aggregate_votes(legislature=19)
"""

from __future__ import annotations

import json
import logging
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from sparql_ingester import individual_vote_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

SENATO_SPARQL_ENDPOINT = "https://dati.senato.it/sparql"

SENATO_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

SPARQL_TIMEOUT = 150   # seconds — Senate endpoint can be slow
BATCH_SIZE = 500       # Neo4j write batch size

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_SEN_VOTAZIONE_URI_RE = re.compile(r"/votazione/(\d+)-(\d+)-(\d+)$")
_SENATORE_URI_RE = re.compile(r"/senatore/(\d+)$")


def _senator_id_from_uri(uri: str) -> Optional[str]:
    """Extract senator id string from a senatore URI.

    Example:
        "http://dati.senato.it/senatore/17542" -> "17542"

    Returns None if URI does not match.
    """
    m = _SENATORE_URI_RE.search(uri)
    return m.group(1) if m else None

# ---------------------------------------------------------------------------
# Pure helpers (URI parsing, outcome derivation)
# ---------------------------------------------------------------------------


def parse_senate_votazione_uri(uri: str) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """Extract (legislature, seduta_num, vote_num) from a Senate votazione URI.

    Example:
        "http://dati.senato.it/votazione/19-167-42"
        -> (19, 167, 42)

    Returns (None, None, None) if the URI does not match.
    """
    m = _SEN_VOTAZIONE_URI_RE.search(uri)
    if not m:
        return None, None, None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def _derive_senate_outcome(favorevoli: Optional[int], maggioranza: Optional[int]) -> str:
    """Derive vote outcome from counts.

    Senate has no explicit approvato flag. Outcome is:
        favorevoli >= maggioranza -> "approved"
        otherwise                 -> "rejected"
        either is None            -> "unknown"
    """
    if favorevoli is None or maggioranza is None:
        return "unknown"
    return "approved" if favorevoli >= maggioranza else "rejected"


_SENATE_ESITO = {"approvato": "approved", "respinto": "rejected"}
_FINAL_VOTE_RE = re.compile(r"votazione finale|nel suo complesso", re.IGNORECASE)


def _senate_outcome(
    esito: Optional[str], favorevoli: Optional[int], maggioranza: Optional[int]
) -> str:
    """osr:esito when present (approvato/respinto), counts as a fallback."""
    if esito and esito.strip().lower() in _SENATE_ESITO:
        return _SENATE_ESITO[esito.strip().lower()]
    return _derive_senate_outcome(favorevoli, maggioranza)


def _senate_vote_flags(label: Optional[str], tipo: Optional[str]) -> dict:
    """Camera-style boolean flags. osr:Votazione has no explicit ones, so they
    come from the label ("Votazione questione di fiducia", "Votazione finale")
    and from tipoVotazione for secret ballots."""
    label = label or ""
    return {
        "confidenceVote": "fiducia" in label.lower(),
        "finalVote": bool(_FINAL_VOTE_RE.search(label)),
        "secretVote": "segret" in (tipo or "").lower() or "scrutinio segreto" in label.lower(),
    }


# ---------------------------------------------------------------------------
# GET-based SPARQL helper (Senate requires GET + browser User-Agent)
# ---------------------------------------------------------------------------


class SenateEndpointBlocked(RuntimeError):
    """dati.senato.it is persistently refusing requests (rate-limit ban).

    Continuing to hammer the endpoint extends the ban — callers must abort
    and resume later (resume logic skips completed sittings)."""


# Consecutive all-retries-failed requests before declaring the endpoint blocked.
_CIRCUIT_BREAKER_THRESHOLD = 5
_consecutive_failures = 0

# Politeness delay after each successful request. 2026-07-05: 0.5s got the
# run rate-banned mid-flight (886 sittings x 2+ queries) — keep >= 1.5s.
_POLITENESS_DELAY = 1.5
# Votazioni per individual-vote request. 20 x 200 senators stays under the
# endpoint's 10,000-row cap, and the GET URL under the size the senato.it WAF
# accepts (40 URIs already get a 403, measured 2026-10-11).
INDIVIDUAL_CHUNK = 20


def _senato_sparql_get(
    query: str,
    timeout: int = SPARQL_TIMEOUT,
    max_retries: int = 3,
) -> list[dict]:
    """Execute a SPARQL SELECT query against dati.senato.it and return bindings.

    dati.senato.it requires:
    - GET method (POST returns 403)
    - Browser-like User-Agent

    Retries with exponential backoff on transient failures.
    Returns [] on persistent failure of a single request; raises
    SenateEndpointBlocked after _CIRCUIT_BREAKER_THRESHOLD consecutive
    failed requests. HTTP 403 skips retries entirely (ban signal).
    """
    import time as _time

    global _consecutive_failures

    def _record_failure() -> None:
        global _consecutive_failures
        _consecutive_failures += 1
        if _consecutive_failures >= _CIRCUIT_BREAKER_THRESHOLD:
            raise SenateEndpointBlocked(
                f"{_consecutive_failures} consecutive failed requests to "
                "dati.senato.it — endpoint is blocking us. Stop the run and "
                "retry later (resume will skip completed sittings)."
            )

    params = urllib.parse.urlencode({
        "query": query,
        "format": "application/sparql-results+json",
    })
    url = f"{SENATO_SPARQL_ENDPOINT}?{params}"

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/sparql-results+json",
                "User-Agent": SENATO_USER_AGENT,
                "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw or not raw.strip():
                    raise ValueError("Empty response body")
                data = json.loads(raw)
                _consecutive_failures = 0
                _time.sleep(_POLITENESS_DELAY)
                return data.get("results", {}).get("bindings", [])
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 403:
                logger.warning("Senate SPARQL HTTP 403 (ban signal, no retry)")
                _record_failure()
                return []
            if attempt < max_retries:
                wait = 5 * attempt  # 5s, 10s, 15s
                logger.warning(
                    "Senate SPARQL request failed (attempt %d/%d, retrying in %ds): %s",
                    attempt, max_retries, wait, exc,
                )
                _time.sleep(wait)
            else:
                logger.warning(
                    "Senate SPARQL request failed after %d attempts: %s",
                    max_retries, exc,
                )
                _record_failure()
                return []
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt < max_retries:
                wait = 10 * attempt  # 10s, 20s, 30s
                logger.warning(
                    "Senate SPARQL response not JSON (attempt %d/%d, retrying in %ds): %s",
                    attempt, max_retries, wait, exc,
                )
                _time.sleep(wait)
            else:
                logger.warning(
                    "Senate SPARQL response not JSON after %d attempts: %s",
                    max_retries, exc,
                )
                _record_failure()
                return []
        except Exception as exc:
            if attempt < max_retries:
                wait = 10 * attempt
                logger.warning(
                    "Unexpected Senate SPARQL error (attempt %d/%d, retrying in %ds): %s",
                    attempt, max_retries, wait, exc,
                )
                _time.sleep(wait)
            else:
                logger.warning(
                    "Unexpected Senate SPARQL error after %d attempts: %s",
                    max_retries, exc,
                )
                _record_failure()
                return []
    return []  # Should not reach here


# ---------------------------------------------------------------------------
# None-safe integer extraction
# ---------------------------------------------------------------------------


def _int_or_none(binding: dict, key: str) -> Optional[int]:
    """Safely extract an integer from a SPARQL binding dict."""
    val = binding.get(key, {}).get("value")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# SenateVoteIngester class
# ---------------------------------------------------------------------------


class SenateVoteIngester:
    """Ingests Senate aggregate Vote nodes from dati.senato.it SPARQL endpoint."""

    def __init__(self, driver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_aggregate_votes(
        self,
        legislature: int = 19,
        limit_sessions: int = 0,
        force: bool = False,
    ) -> dict:
        """Fetch aggregate Senate Vote nodes from SPARQL and write to Neo4j.

        Args:
            legislature: Legislature number (18 or 19).
            limit_sessions: If > 0, process at most this many sittings (for testing).
            force: Re-fetch sittings that already have votes (MERGE by id keeps
                IndividualVote links intact), e.g. after adding a field.

        Returns:
            Stats dict: {"sittings_processed": N, "votes_written": N}
        """
        logger.info(
            "Starting Senate aggregate vote ingest — legislature %d", legislature
        )

        # 1. Session numbers present in DB for this legislature
        sittings = self._get_senate_sittings_in_db(legislature)
        logger.info("Found %d Senate sessions in DB for legislature %d", len(sittings), legislature)

        # 2. Skip sittings that already have HAS_VOTE (idempotency / resume)
        done = set() if force else self._get_senate_sittings_with_votes(legislature)
        todo = sorted(sittings - done)
        logger.info(
            "%d sittings need aggregate votes (%d already done)",
            len(todo), len(done),
        )

        if limit_sessions:
            todo = todo[:limit_sessions]
            logger.info("Limited to %d sessions (test mode)", limit_sessions)

        sittings_processed = 0
        total_votes_written = 0
        aborted = False

        for session_num in todo:
            logger.debug("Processing sitting %d/%d ...", session_num, legislature)

            # Resolve the sedutaassemblea URI for this session
            try:
                seduta_uri = self._get_senate_seduta_uri(legislature, session_num)
            except SenateEndpointBlocked as exc:
                logger.error(
                    "ABORTING run at leg%d sed%d: %s",
                    legislature, session_num, exc,
                )
                aborted = True
                break
            if not seduta_uri:
                logger.warning(
                    "  leg%d sed%d: no sedutaassemblea URI found — skipping",
                    legislature, session_num,
                )
                continue

            # Fetch all votazioni for this seduta
            try:
                votazioni = self._get_senate_votes_for_seduta(seduta_uri)
            except SenateEndpointBlocked as exc:
                logger.error(
                    "ABORTING run at leg%d sed%d: %s",
                    legislature, session_num, exc,
                )
                aborted = True
                break
            if not votazioni:
                logger.debug(
                    "  leg%d sed%d: no votazioni returned — skipping",
                    legislature, session_num,
                )
                sittings_processed += 1
                continue

            # Build batch and write
            batch = []
            for b in votazioni:
                vot_uri = b.get("votazione", {}).get("value", "")
                _, _, vote_num = parse_senate_votazione_uri(vot_uri)
                if vote_num is None:
                    logger.debug("    Skipping unparseable votazione URI: %s", vot_uri)
                    continue

                favorevoli = _int_or_none(b, "favorevoli")
                maggioranza = _int_or_none(b, "maggioranza")
                label = b.get("label", {}).get("value")
                tipo = b.get("tipo", {}).get("value")

                batch.append({
                    "id": f"senato_leg{legislature}_sed{session_num:03d}_v{vote_num:03d}",
                    "sessionNumber": session_num,
                    "voteNumber": vote_num,
                    "label": label,
                    "type": tipo,
                    "present": _int_or_none(b, "presenti"),
                    "voters": _int_or_none(b, "votanti"),
                    "inFavor": favorevoli,
                    "against": _int_or_none(b, "contrari"),
                    "abstained": _int_or_none(b, "astenuti"),
                    "majority": maggioranza,
                    "onMission": _int_or_none(b, "congedo"),
                    "outcome": _senate_outcome(
                        b.get("esito", {}).get("value"), favorevoli, maggioranza
                    ),
                    **_senate_vote_flags(label, tipo),
                })

            written = self._write_senate_votes(batch, legislature)
            total_votes_written += written
            sittings_processed += 1
            logger.info(
                "  leg%d sed%d: %d votes written", legislature, session_num, written
            )

        logger.info(
            "Senate aggregate ingest complete — %d sittings, %d votes",
            sittings_processed, total_votes_written,
        )
        return {
            "sittings_processed": sittings_processed,
            "votes_written": total_votes_written,
            "aborted": aborted,
        }

    # ------------------------------------------------------------------
    # Neo4j read helpers
    # ------------------------------------------------------------------

    def _get_senate_sittings_in_db(self, legislature: int) -> set[int]:
        """Return session numbers present in DB for chamber='senato', this legislature."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (s:Session {chamber:'senato', legislature:$legislature}) "
                "RETURN s.number AS n",
                legislature=legislature,
            )
            return {record["n"] for record in result if record["n"] is not None}

    def _get_senate_sittings_with_votes(self, legislature: int) -> set[int]:
        """Return session numbers that already have HAS_VOTE rels for chamber='senato'."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (s:Session {chamber:'senato', legislature:$legislature})"
                "-[:HAS_VOTE]->(:Vote) "
                "RETURN DISTINCT s.number AS n",
                legislature=legislature,
            )
            return {record["n"] for record in result if record["n"] is not None}

    def _get_senate_sittings_with_individual_votes(self, legislature: int) -> set[int]:
        """Return session numbers where senators already have VOTED rels for this legislature.

        Resume is per-sitting: if ANY senator in a sitting already has a VOTED rel linking
        through an IndividualVote to a Vote in this Senate session, that sitting is skipped.
        """
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (:Person)-[:VOTED]->(:IndividualVote)"
                "-[:ON_VOTE]->(:Vote)<-[:HAS_VOTE]-(s:Session {legislature:$legislature, chamber:'senato'}) "
                "RETURN DISTINCT s.number AS num",
                legislature=legislature,
            )
            return {record["num"] for record in result if record["num"] is not None}

    # ------------------------------------------------------------------
    # SPARQL query methods
    # ------------------------------------------------------------------

    def _get_senate_seduta_uri(
        self, legislature: int, session_num: int
    ) -> Optional[str]:
        """Resolve the SedutaAssemblea URI for a given legislature + session number."""
        query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?seduta WHERE {{
  ?seduta a osr:SedutaAssemblea ;
          osr:legislatura {legislature} ;
          osr:numeroSeduta {session_num} .
}}
LIMIT 1
"""
        bindings = _senato_sparql_get(query)
        if not bindings:
            return None
        return bindings[0].get("seduta", {}).get("value")

    def _get_senate_votes_for_seduta(self, seduta_uri: str) -> list[dict]:
        """Fetch all Votazione bindings for a given SedutaAssemblea URI."""
        query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?votazione ?label ?tipo ?presenti ?votanti ?favorevoli ?contrari ?astenuti ?maggioranza ?congedo ?esito
WHERE {{
  ?votazione a osr:Votazione ;
             osr:seduta <{seduta_uri}> .
  OPTIONAL {{ ?votazione rdfs:label ?label . }}
  OPTIONAL {{ ?votazione osr:tipoVotazione ?tipo . }}
  OPTIONAL {{ ?votazione osr:presenti ?presenti . }}
  OPTIONAL {{ ?votazione osr:votanti ?votanti . }}
  OPTIONAL {{ ?votazione osr:favorevoli ?favorevoli . }}
  OPTIONAL {{ ?votazione osr:contrari ?contrari . }}
  OPTIONAL {{ ?votazione osr:astenuti ?astenuti . }}
  OPTIONAL {{ ?votazione osr:esito ?esito . }}
  OPTIONAL {{ ?votazione osr:maggioranza ?maggioranza . }}
  OPTIONAL {{ ?votazione osr:congedoMissione ?congedo . }}
}}
"""
        return _senato_sparql_get(query)

    def _get_senate_senator_links(self, votazione_uri: str) -> dict:
        """Return per-senator vote links for a Votazione URI.

        Executes three separate SPARQL queries (one per outcome) to retrieve
        the senator URIs that voted favorevole, contrario, or astenuto.

        Returns:
            {"favor": [uri, ...], "against": [uri, ...], "abstain": [uri, ...]}
        """
        results: dict = {}
        for prop, outcome in [
            ("favorevole", "favor"),
            ("contrario", "against"),
            ("astenuto", "abstain"),
        ]:
            query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?senatore WHERE {{
  <{votazione_uri}> osr:{prop} ?senatore .
}}
"""
            bindings = _senato_sparql_get(query)
            results[outcome] = [
                b["senatore"]["value"] for b in bindings if "senatore" in b
            ]
        return results

    def _get_senate_senator_links_bulk(
        self, votazione_uris: list[str], chunk_size: int = INDIVIDUAL_CHUNK
    ) -> dict:
        """Per-senator votes for many votazioni, a few requests per sitting.

        The endpoint (an old Virtuoso: no BIND/VALUES) caps results at 10,000
        rows counting the OFFSET, so paging one big query fails; chunks of
        votazioni stay under the cap and under the WAF's URL size limit.

        Returns {votazione_uri: {"favor": [...], "against": [...], "abstain": [...]}}
        with only the votazioni that came back; a failed chunk is simply absent.
        """
        outcome_of = {
            f"http://dati.senato.it/osr/{prop}": outcome
            for prop, outcome in (
                ("favorevole", "favor"), ("contrario", "against"), ("astenuto", "abstain"),
            )
        }
        links: dict = {}
        for i in range(0, len(votazione_uris), chunk_size):
            chunk = votazione_uris[i : i + chunk_size]
            vfilter = " || ".join(f"?v = <{u}>" for u in chunk)
            query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?v ?p ?senatore WHERE {{
  ?v a osr:Votazione ; ?p ?senatore .
  FILTER(({vfilter}) && (?p = osr:favorevole || ?p = osr:contrario || ?p = osr:astenuto))
}}
"""
            for b in _senato_sparql_get(query):
                outcome = outcome_of.get(b["p"]["value"])
                if outcome is None:
                    continue
                per_vote = links.setdefault(
                    b["v"]["value"], {"favor": [], "against": [], "abstain": []}
                )
                per_vote[outcome].append(b["senatore"]["value"])
        return links

    # ------------------------------------------------------------------
    # Neo4j write helpers
    # ------------------------------------------------------------------

    def ingest_individual_votes(
        self,
        legislature: int = 19,
        limit_sessions: int = 0,
    ) -> dict:
        """Ingest per-senator IndividualVote nodes for all Senate sittings not yet processed.

        Resume is per-sitting: sittings where senators already have VOTED rels are skipped.
        IndividualVote ids come from sparql_ingester.individual_vote_id (chamber and legislature scoped).

        Args:
            legislature: Legislature number (18 or 19).
            limit_sessions: If > 0, process at most this many sittings (for testing).

        Returns:
            Stats dict: {"sittings_processed": N, "ivotes_written": N}
        """
        logger.info(
            "Starting Senate individual vote ingest — legislature %d", legislature
        )

        sittings = self._get_senate_sittings_in_db(legislature)
        done = self._get_senate_sittings_with_individual_votes(legislature)
        todo = sorted(sittings - done)
        logger.info(
            "%d sittings to process for individual votes (%d already done)",
            len(todo), len(done),
        )

        if limit_sessions:
            todo = todo[:limit_sessions]
            logger.info("Limited to %d sessions (test mode)", limit_sessions)

        total = 0
        sittings_processed = 0
        aborted = False

        for num in todo:
            try:
                seduta_uri = self._get_senate_seduta_uri(legislature, num)
                if not seduta_uri:
                    logger.warning(
                        "  leg%d sed%d: no sedutaassemblea URI found — skipping",
                        legislature, num,
                    )
                    continue

                votazioni = self._get_senate_votes_for_seduta(seduta_uri)
            except SenateEndpointBlocked as exc:
                logger.error("ABORTING run at leg%d sed%d: %s", legislature, num, exc)
                aborted = True
                break
            if not votazioni:
                logger.debug(
                    "  leg%d sed%d: no votazioni returned — skipping",
                    legislature, num,
                )
                sittings_processed += 1
                continue

            by_uri = {}
            for vz in votazioni:
                vz_uri = vz.get("votazione", {}).get("value", "")
                _, _, vote = parse_senate_votazione_uri(vz_uri)
                if vote is None:
                    logger.debug("    Skipping unparseable votazione URI: %s", vz_uri)
                    continue
                expected = sum(
                    _int_or_none(vz, k) or 0 for k in ("favorevoli", "contrari", "astenuti")
                )
                by_uri[vz_uri] = (vote, expected)

            try:
                links = self._get_senate_senator_links_bulk(list(by_uri))
            except SenateEndpointBlocked as exc:
                logger.error("ABORTING run at leg%d sed%d: %s", legislature, num, exc)
                aborted = True
                break

            # A chunk that failed comes back empty: write nothing for this
            # sitting, so the per-sitting resume retries it on the next run.
            missing = [
                u for u, (_, expected) in by_uri.items()
                if expected and u not in links
            ]
            if missing:
                logger.warning(
                    "  leg%d sed%d: %d/%d votazioni without individual votes — "
                    "sitting left for the next run",
                    legislature, num, len(missing), len(by_uri),
                )
                continue

            batch: list[dict] = []
            for vz_uri, (vote, expected) in by_uri.items():
                vote_id = f"senato_leg{legislature}_sed{num:03d}_v{vote:03d}"
                got = sum(len(v) for v in links.get(vz_uri, {}).values())
                if got != expected:
                    logger.warning(
                        "  %s: %d individual votes, aggregate says %d",
                        vote_id, got, expected,
                    )
                for outcome, uris in links.get(vz_uri, {}).items():
                    for sen_uri in uris:
                        sen_id = _senator_id_from_uri(sen_uri)
                        if not sen_id:
                            continue
                        batch.append({
                            "id": individual_vote_id("senato", legislature, sen_id, num, vote),
                            "senatorUri": sen_uri,
                            "voteId": vote_id,
                            "outcome": outcome,
                        })

            if batch:
                written = self._write_senate_individual_votes(batch)
                total += written
                logger.info(
                    "  leg%d sed%d: %d individual votes written",
                    legislature, num, written,
                )

            sittings_processed += 1

        logger.info(
            "Senate individual vote ingest complete — %d sittings, %d individual votes",
            sittings_processed, total,
        )
        return {"sittings_processed": sittings_processed, "ivotes_written": total, "aborted": aborted}

    # ------------------------------------------------------------------
    # Neo4j read helpers
    # ------------------------------------------------------------------

    def _write_senate_votes(self, batch: list[dict], legislature: int) -> int:
        """Write a batch of aggregate Senate Vote nodes to Neo4j.

        Matches Senate Session by number+legislature, MERGEs Vote by stable id,
        links Session -[:HAS_VOTE]-> Vote.

        Returns the number of Vote nodes written/merged.
        """
        if not batch:
            return 0

        cypher = """
UNWIND $batch AS row
MATCH (s:Session {number: row.sessionNumber, chamber: 'senato', legislature: $legislature})
MERGE (v:Vote {id: row.id})
SET v.number = row.voteNumber,
    v.type = row.type,
    v.subject = row.label,
    v.present = row.present,
    v.voters = row.voters,
    v.majority = row.majority,
    v.inFavor = row.inFavor,
    v.against = row.against,
    v.abstained = row.abstained,
    v.onMission = row.onMission,
    v.outcome = row.outcome,
    v.confidenceVote = row.confidenceVote,
    v.finalVote = row.finalVote,
    v.secretVote = row.secretVote
MERGE (s)-[:HAS_VOTE]->(v)
RETURN count(*) AS written
"""
        total_written = 0
        for i in range(0, len(batch), BATCH_SIZE):
            chunk = batch[i : i + BATCH_SIZE]
            with self._driver.session() as neo_session:
                result = neo_session.run(cypher, batch=chunk, legislature=legislature)
                record = result.single()
                total_written += record["written"] if record else 0

        return total_written

    def _write_senate_individual_votes(self, batch: list[dict]) -> int:
        """Write a batch of IndividualVote nodes and their VOTED/ON_VOTE rels to Neo4j.

        Matches the senator's Person through senato_id (the node id differs
        for senators who also sat in the Camera or in the government).
        Matches Vote by stable senate id (no number collision possible due to senato_ prefix).
        MERGEs IndividualVote node and both relationships idempotently.

        Args:
            batch: List of dicts with keys: id, senatorUri, voteId, outcome.

        Returns:
            Number of IndividualVote nodes merged in this batch.
        """
        if not batch:
            return 0

        cypher = """
UNWIND $batch AS row
MATCH (d:Person {senato_id: row.senatorUri})
MATCH (v:Vote {id: row.voteId})
MERGE (iv:IndividualVote {id: row.id})
SET iv.outcome = row.outcome
MERGE (d)-[:VOTED]->(iv)
MERGE (iv)-[:ON_VOTE]->(v)
RETURN count(*) AS written
"""
        total_written = 0
        for i in range(0, len(batch), BATCH_SIZE):
            chunk = batch[i : i + BATCH_SIZE]
            with self._driver.session() as neo_session:
                result = neo_session.run(cypher, batch=chunk)
                record = result.single()
                total_written += record["written"] if record else 0

        return total_written


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Senate SPARQL enrichment — aggregate Vote nodes from dati.senato.it"
    )
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7689")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"), required=os.environ.get("NEO4J_PASSWORD") is None)
    parser.add_argument(
        "--legislature",
        type=int,
        default=19,
        help="Legislature number to ingest (18 or 19, default: 19)",
    )
    parser.add_argument(
        "--limit-sessions",
        type=int,
        default=0,
        help="Limit to N sittings for testing (0 = all)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Ingest only aggregate Vote nodes (mutually exclusive with --individual-only)",
    )
    mode.add_argument(
        "--individual-only",
        action="store_true",
        help="Ingest only individual senator IndividualVote nodes per sitting (mutually exclusive with --aggregate-only)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Aggregate mode: re-fetch sittings that already have votes",
    )
    args = parser.parse_args()

    from neo4j import GraphDatabase  # type: ignore[import]

    driver = GraphDatabase.driver(
        args.neo4j_uri,
        auth=(args.neo4j_user, args.neo4j_password),
    )

    try:
        ingester = SenateVoteIngester(driver)

        if args.individual_only:
            stats = ingester.ingest_individual_votes(
                legislature=args.legislature,
                limit_sessions=args.limit_sessions,
            )
            print(
                f"Done — sittings_processed={stats['sittings_processed']}, "
                f"ivotes_written={stats['ivotes_written']}"
            )
            if stats.get("aborted"):
                print(
                    "ABORTED early: dati.senato.it is blocking requests (HTTP 403). "
                    "Progress is saved — rerun later to resume from the next sitting."
                )
                sys.exit(3)
        else:
            # Default (no flag) or --aggregate-only: run aggregate ingest
            stats = ingester.ingest_aggregate_votes(
                legislature=args.legislature,
                limit_sessions=args.limit_sessions,
                force=args.force,
            )
            print(
                f"Done — sittings_processed={stats['sittings_processed']}, "
                f"votes_written={stats['votes_written']}"
            )
            if stats.get("aborted"):
                print(
                    "ABORTED early: dati.senato.it is blocking requests (HTTP 403). "
                    "Progress is saved — rerun later to resume from the next sitting."
                )
                sys.exit(3)
    finally:
        driver.close()
