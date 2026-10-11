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


class SenateRequestFailed(RuntimeError):
    """One request failed after its retries (strict mode only), so an empty
    answer is not mistaken for "no votes"."""


# Consecutive all-retries-failed requests before declaring the endpoint blocked.
_CIRCUIT_BREAKER_THRESHOLD = 5
_consecutive_failures = 0

# Politeness delay after each successful request. 2026-07-05: 0.5s got the
# run rate-banned mid-flight (886 sittings x 2+ queries) — keep >= 1.5s.
_POLITENESS_DELAY = 1.5
# Votazioni per individual-vote request: 45 x ~200 senators stays under the
# endpoint's 10,000-row cap. Requests select them by sitting and vote-number
# range, because listing votazione URIs hits the WAF's URL size limit
# (40 URIs got a 403, 2026-10-11).
INDIVIDUAL_CHUNK = 45
# Sittings packed into one individual-vote request (URL size, as above).
INDIVIDUAL_SITTINGS = 15
# Sittings per aggregate request: same URL size limit, ~150 votazioni each at most.
SITTING_CHUNK = 20
# Recent sittings are re-checked: the endpoint publishes votes with a delay.
RECHECK_DAYS = 30


def _senato_sparql_get(
    query: str,
    timeout: int = SPARQL_TIMEOUT,
    max_retries: int = 3,
    strict: bool = False,
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
                if strict:
                    raise SenateRequestFailed(str(exc))
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
                if strict:
                    raise SenateRequestFailed(str(exc))
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
                if strict:
                    raise SenateRequestFailed(str(exc))
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
                if strict:
                    raise SenateRequestFailed(str(exc))
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


def _pack_ranges(pending: list[dict]) -> list[list[dict]]:
    """Split pending votes (sorted by sitting, vote) into request-sized chunks.

    A request asks for vote-number ranges, which may also span votes already
    done, so the budget counts range widths (rows ~ width x 200 senators),
    not pending votes; at most INDIVIDUAL_SITTINGS ranges per request.
    """
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    width = 0          # sum of range widths in cur
    lo = None          # first vote of the open range (same sitting as cur[-1])
    for p in pending:
        same = cur and cur[-1]["session"] == p["session"]
        if same and width - (cur[-1]["vote"] - lo + 1) + (p["vote"] - lo + 1) <= INDIVIDUAL_CHUNK:
            width += p["vote"] - cur[-1]["vote"]
            cur.append(p)
            continue
        n_ranges = len({q["session"] for q in cur})
        if cur and (width + 1 > INDIVIDUAL_CHUNK or same or n_ranges >= INDIVIDUAL_SITTINGS):
            chunks.append(cur)
            cur, width = [], 0
        cur.append(p)
        width += 1
        lo = p["vote"]
    if cur:
        chunks.append(cur)
    return chunks


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
        sittings: Optional[set[int]] = None,
    ) -> dict:
        """Fetch aggregate Senate Vote nodes from SPARQL and write to Neo4j.

        dati.senato.it blocks an IP after ~400 requests whatever the pace
        (2026-10-11: at 1.5 s and at 4 s between requests), so requests are
        batched: one query maps sitting numbers to URIs, then one query per
        SITTING_CHUNK sittings. A sitting answered without error is marked
        `senate_votes_checked` and skipped next time, so sittings without
        roll calls cost nothing on later runs; recent ones are re-checked
        because the endpoint publishes votes with some delay.

        Args:
            legislature: Legislature number (18 or 19).
            limit_sessions: If > 0, process at most this many sittings (for testing).
            force: Re-fetch checked sittings too (MERGE by id keeps
                IndividualVote links intact), e.g. after adding a field.
            sittings: Restrict the run to these sitting numbers.
        """
        logger.info("Starting Senate aggregate vote ingest — legislature %d", legislature)

        in_db = self._get_senate_sittings_in_db(legislature)
        if sittings is not None:
            in_db &= sittings
        done = set() if force else self._get_senate_sittings_checked(legislature)
        todo = sorted(in_db - done)
        logger.info("%d sittings to check (%d already checked)", len(todo), len(in_db & done))
        if limit_sessions:
            todo = todo[:limit_sessions]

        stats = {"sittings_processed": 0, "votes_written": 0, "aborted": False}
        if not todo:
            return stats
        try:
            seduta_uris = self._get_senate_seduta_uris(legislature)
        except (SenateEndpointBlocked, SenateRequestFailed) as exc:
            logger.error("ABORTING: sitting URIs not available: %s", exc)
            stats["aborted"] = True
            return stats

        unknown = [n for n in todo if n not in seduta_uris]
        if unknown:
            logger.warning("No sedutaassemblea URI for sittings %s", unknown)
        todo = [n for n in todo if n in seduta_uris]

        for i in range(0, len(todo), SITTING_CHUNK):
            chunk = todo[i : i + SITTING_CHUNK]
            num_of = {seduta_uris[n]: n for n in chunk}
            try:
                bindings = self._get_senate_votes_for_sedute(list(num_of))
            except SenateEndpointBlocked as exc:
                logger.error("ABORTING run at leg%d sed%d: %s", legislature, chunk[0], exc)
                stats["aborted"] = True
                break
            except SenateRequestFailed as exc:
                logger.warning("  sittings %d-%d failed, left for the next run: %s",
                               chunk[0], chunk[-1], exc)
                continue

            batch = []
            for b in bindings:
                session_num = num_of.get(b.get("seduta", {}).get("value", ""))
                _, _, vote_num = parse_senate_votazione_uri(b.get("votazione", {}).get("value", ""))
                if session_num is None or vote_num is None:
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
            self._mark_sittings_checked(legislature, chunk)
            stats["votes_written"] += written
            stats["sittings_processed"] += len(chunk)
            logger.info("  leg%d sed%d-%d: %d votes written",
                        legislature, chunk[0], chunk[-1], written)

        logger.info(
            "Senate aggregate ingest complete — %d sittings, %d votes",
            stats["sittings_processed"], stats["votes_written"],
        )
        return stats

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

    def _get_senate_sittings_checked(self, legislature: int) -> set[int]:
        """Sittings already answered by the endpoint (or holding votes from
        runs that predate the marker), except the last RECHECK_DAYS days."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (s:Session {chamber:'senato', legislature:$legislature}) "
                "WHERE (s.senate_votes_checked IS NOT NULL OR (s)-[:HAS_VOTE]->()) "
                "  AND (s.date IS NULL OR s.date < date() - duration({days: $days})) "
                "RETURN s.number AS n",
                legislature=legislature, days=RECHECK_DAYS,
            )
            return {record["n"] for record in result if record["n"] is not None}

    def _mark_sittings_checked(self, legislature: int, numbers: list[int]) -> None:
        with self._driver.session() as neo_session:
            neo_session.run(
                "MATCH (s:Session {chamber:'senato', legislature:$legislature}) "
                "WHERE s.number IN $numbers SET s.senate_votes_checked = date()",
                legislature=legislature, numbers=numbers,
            )

    def _get_votes_without_individual_votes(self, legislature: int) -> list[dict]:
        """Senate votes whose per-senator rows are still to fetch.

        Secret ballots have no names, and a vote the endpoint answered with no
        names is marked `individual_missing`, so neither is asked again.
        """
        with self._driver.session() as neo_session:
            result = neo_session.run(
                """
                MATCH (s:Session {chamber:'senato', legislature:$legislature})-[:HAS_VOTE]->(v:Vote)
                WHERE NOT coalesce(v.secretVote, false)
                  AND v.individual_missing IS NULL
                  AND coalesce(v.inFavor, 0) + coalesce(v.against, 0) + coalesce(v.abstained, 0) > 0
                  AND NOT EXISTS { (v)<-[:ON_VOTE]-(:IndividualVote) }
                RETURN s.number AS session, v.number AS vote, v.id AS id,
                       coalesce(v.inFavor, 0) + coalesce(v.against, 0)
                       + coalesce(v.abstained, 0) AS expected
                ORDER BY session, vote
                """,
                legislature=legislature,
            )
            return [r.data() for r in result]

    # ------------------------------------------------------------------
    # SPARQL query methods
    # ------------------------------------------------------------------

    def _get_senate_seduta_uris(self, legislature: int) -> dict[int, str]:
        """{sitting number: SedutaAssemblea URI} for a legislature, one request."""
        query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?seduta ?numero WHERE {{
  ?seduta a osr:SedutaAssemblea ;
          osr:legislatura {legislature} ;
          osr:numeroSeduta ?numero .
}}
"""
        uris: dict[int, str] = {}
        for b in _senato_sparql_get(query, strict=True):
            num = _int_or_none(b, "numero")
            if num is not None:
                uris.setdefault(num, b["seduta"]["value"])
        return uris

    def _get_senate_votes_for_sedute(self, seduta_uris: list[str]) -> list[dict]:
        """All Votazione bindings for a chunk of sittings (strict: raises on failure)."""
        sfilter = " || ".join(f"?seduta = <{u}>" for u in seduta_uris)
        query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?seduta ?votazione ?label ?tipo ?presenti ?votanti ?favorevoli ?contrari ?astenuti ?maggioranza ?congedo ?esito
WHERE {{
  ?votazione a osr:Votazione ;
             osr:seduta ?seduta .
  FILTER({sfilter})
  OPTIONAL {{ ?votazione rdfs:label ?label . }}
  OPTIONAL {{ ?votazione osr:tipoVotazione ?tipo . }}
  OPTIONAL {{ ?votazione osr:presenti ?presenti . }}
  OPTIONAL {{ ?votazione osr:votanti ?votanti . }}
  OPTIONAL {{ ?votazione osr:favorevoli ?favorevoli . }}
  OPTIONAL {{ ?votazione osr:contrari ?contrari . }}
  OPTIONAL {{ ?votazione osr:astenuti ?astenuti . }}
  OPTIONAL {{ ?votazione osr:maggioranza ?maggioranza . }}
  OPTIONAL {{ ?votazione osr:congedoMissione ?congedo . }}
  OPTIONAL {{ ?votazione osr:esito ?esito . }}
}}
"""
        return _senato_sparql_get(query, strict=True)

    def _get_senate_senator_links_bulk(self, ranges: list[tuple[str, int, int]]) -> dict:
        """Per-senator votes for (seduta URI, first vote, last vote) ranges, one request.

        The endpoint (an old Virtuoso: no BIND/VALUES) caps results at 10,000
        rows counting the OFFSET, so paging one big query fails; the caller
        keeps each request under INDIVIDUAL_CHUNK votazioni. Strict: raises
        SenateRequestFailed instead of returning a partial answer.

        Returns {votazione_uri: {"favor": [...], "against": [...], "abstain": [...]}}.
        """
        outcome_of = {
            f"http://dati.senato.it/osr/{prop}": outcome
            for prop, outcome in (
                ("favorevole", "favor"), ("contrario", "against"), ("astenuto", "abstain"),
            )
        }
        rfilter = " || ".join(
            f"(?s = <{uri}> && ?n >= {lo} && ?n <= {hi})" for uri, lo, hi in ranges
        )
        query = f"""
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?v ?p ?senatore WHERE {{
  ?v a osr:Votazione ; osr:seduta ?s ; osr:numero ?n ; ?p ?senatore .
  FILTER(({rfilter}) && (?p = osr:favorevole || ?p = osr:contrario || ?p = osr:astenuto))
}}
"""
        links: dict = {}
        for b in _senato_sparql_get(query, strict=True):
            outcome = outcome_of.get(b["p"]["value"])
            if outcome is None:
                continue
            per_vote = links.setdefault(
                b["v"]["value"], {"favor": [], "against": [], "abstain": []}
            )
            per_vote[outcome].append(b["senatore"]["value"])
        return links

    # ------------------------------------------------------------------
    # Individual votes
    # ------------------------------------------------------------------

    def ingest_individual_votes(
        self,
        legislature: int = 19,
        limit_sessions: int = 0,
    ) -> dict:
        """Ingest per-senator IndividualVote nodes for the Vote nodes in the graph.

        Works from the aggregate votes already loaded and packs vote-number
        ranges of several sittings into one request (see _pack_ranges).
        Resume is per vote: a vote is done once it has IndividualVote nodes.

        Args:
            legislature: Legislature number (18 or 19).
            limit_sessions: If > 0, only votes of the first N pending sittings.
        """
        logger.info("Starting Senate individual vote ingest — legislature %d", legislature)
        pending = self._get_votes_without_individual_votes(legislature)
        if limit_sessions:
            keep = sorted({p["session"] for p in pending})[:limit_sessions]
            pending = [p for p in pending if p["session"] in keep]
        logger.info("%d votes in %d sittings to fetch",
                    len(pending), len({p["session"] for p in pending}))

        stats = {"sittings_processed": 0, "ivotes_written": 0, "aborted": False}
        if not pending:
            return stats
        try:
            seduta_uris = self._get_senate_seduta_uris(legislature)
        except (SenateEndpointBlocked, SenateRequestFailed) as exc:
            logger.error("ABORTING: sitting URIs not available: %s", exc)
            stats["aborted"] = True
            return stats
        pending = [p for p in pending if p["session"] in seduta_uris]

        sittings_seen: set[int] = set()
        for chunk in _pack_ranges(pending):
            by_uri = {
                f"http://dati.senato.it/votazione/{legislature}-{p['session']}-{p['vote']}": p
                for p in chunk
            }
            ranges = {}
            for p in chunk:
                lo, hi = ranges.get(p["session"], (p["vote"], p["vote"]))
                ranges[p["session"]] = (min(lo, p["vote"]), max(hi, p["vote"]))
            try:
                links = self._get_senate_senator_links_bulk(
                    [(seduta_uris[n], lo, hi) for n, (lo, hi) in ranges.items()]
                )
            except SenateEndpointBlocked as exc:
                logger.error("ABORTING run at leg%d sed%d: %s",
                             legislature, chunk[0]["session"], exc)
                stats["aborted"] = True
                break
            except SenateRequestFailed as exc:
                logger.warning("  votes %s..%s failed, left for the next run: %s",
                               chunk[0]["id"], chunk[-1]["id"], exc)
                continue

            batch: list[dict] = []
            missing: list[str] = []
            for vz_uri, p in by_uri.items():
                got = links.get(vz_uri)
                if not got:
                    missing.append(p["id"])
                    continue
                n = sum(len(v) for v in got.values())
                if n != p["expected"]:
                    logger.warning("  %s: %d individual votes, aggregate says %d",
                                   p["id"], n, p["expected"])
                for outcome, uris in got.items():
                    for sen_uri in uris:
                        sen_id = _senator_id_from_uri(sen_uri)
                        if not sen_id:
                            continue
                        batch.append({
                            "id": individual_vote_id(
                                "senato", legislature, sen_id, p["session"], p["vote"]
                            ),
                            "senatorUri": sen_uri,
                            "voteId": p["id"],
                            "outcome": outcome,
                        })
            if missing:
                logger.warning("  %d votes without names at the source: %s",
                               len(missing), missing[:5])
                self._mark_individual_missing(missing)
            stats["ivotes_written"] += self._write_senate_individual_votes(batch)
            sittings_seen.update(p["session"] for p in chunk)
            logger.info("  up to leg%d sed%d: %d individual votes so far",
                        legislature, chunk[-1]["session"], stats["ivotes_written"])

        stats["sittings_processed"] = len(sittings_seen)
        logger.info(
            "Senate individual vote ingest complete — %d sittings, %d individual votes",
            stats["sittings_processed"], stats["ivotes_written"],
        )
        return stats

    def _mark_individual_missing(self, vote_ids: list[str]) -> None:
        with self._driver.session() as neo_session:
            neo_session.run(
                "MATCH (v:Vote) WHERE v.id IN $ids SET v.individual_missing = true",
                ids=vote_ids,
            )

    # ------------------------------------------------------------------
    # Neo4j write helpers
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
        "--delay",
        type=float,
        default=_POLITENESS_DELAY,
        help="Seconds between SPARQL requests (1.5 got the IP blocked after "
             "~14 minutes on 2026-10-11)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Aggregate mode: re-fetch sittings that already have votes",
    )
    args = parser.parse_args()
    _POLITENESS_DELAY = args.delay

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
