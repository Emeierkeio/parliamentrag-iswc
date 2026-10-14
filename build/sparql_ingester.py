"""
sparql_ingester.py — SPARQL enrichment from dati.camera.it

Fetches per-deputy individual vote records and committee officer roles from the
Italian Chamber of Deputies SPARQL endpoint, then writes the data to Neo4j.

Schema changes:
  - IndividualVote {id, outcome} nodes with VOTED and ON_VOTE relationships
  - MEMBER_OF_COMMITTEE.officerRole, officerRoleStart, officerRoleEnd properties

Usage (CLI):
    python build/sparql_ingester.py --neo4j-uri bolt://localhost:7689

Usage (library):
    from sparql_ingester import SparqlIngester
    ingester = SparqlIngester(driver)
    stats = ingester.ingest_votes()
    stats = ingester.ingest_committee_roles()
"""

from __future__ import annotations

import html
import json
import logging
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from neo4j.exceptions import TransientError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

SPARQL_ENDPOINT = "https://dati.camera.it/sparql"

OUTCOME_MAP: dict[str, str] = {
    "Favorevole": "favor",
    "Contrario": "against",
    "Astensione": "abstain",
    "Non ha votato": "absent",
    # Secret ballots publish participation only: the deputy voted, how is not
    # public. Mapping it to "absent" counted 391 voters of PDL 2822-B as absent.
    "Ha votato": "secret",
}

BATCH_SIZE = 500          # Neo4j write batch size
SPARQL_PAGE_SIZE = 1000   # HTTP pagination page size
SPARQL_TIMEOUT = 150      # seconds — dati.camera.it vote queries can be slow
SPARQL_WORKERS = 4        # concurrent SPARQL requests (be polite to the endpoint)

# Concurrent deputies MERGE relationships onto the same shared Vote nodes, so
# parallel write transactions deadlock (ForsetiClient). SPARQL fetches stay
# parallel; Neo4j writes are serialized through this lock.
_NEO4J_WRITE_LOCK = threading.Lock()
_WRITE_RETRIES = 5

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_VOTAZIONE_URI_RE = re.compile(r"/vs\d+_(\d+)_(\d+)$")
_PERSONA_ID_RE = re.compile(r"/p(\d+)$")
# Legislature-agnostic deputato URI (deputato.rdf/d{person}_{leg})
_DEPUTATO_URI_RE = re.compile(r"deputato\.rdf/d(\d+)_\d+$")


# ---------------------------------------------------------------------------
# URI parsing helpers (pure functions, easily testable)
# ---------------------------------------------------------------------------

def sparql_dep_uri_to_neo4j_id(uri: str) -> Optional[str]:
    """Convert a SPARQL deputato URI to a Neo4j Deputy.id (persona.rdf).

    Example:
        "http://dati.camera.it/ocd/deputato.rdf/d308908_19"
        -> "http://dati.camera.it/ocd/persona.rdf/p308908"
    """
    m = _DEPUTATO_URI_RE.search(uri)
    if not m:
        return None
    person_id = m.group(1)
    return f"http://dati.camera.it/ocd/persona.rdf/p{person_id}"


def individual_vote_id(
    chamber: str, legislature: int, person_id: str, session_num: int, vote_num: int,
) -> str:
    """IndividualVote id. Sitting numbers restart every legislature, so the id
    carries it; Camera XIX keeps the original unscoped form, which the 6.9M
    nodes already in the graph use."""
    if chamber == "camera" and legislature == 19:
        return f"iv_{chamber}_{person_id}_{session_num}_{vote_num}"
    return f"iv_{chamber}_leg{legislature}_{person_id}_{session_num}_{vote_num}"


def clean_sparql_text(value: Optional[str]) -> Optional[str]:
    """Normalizza un letterale testuale di dati.camera.it.

    Alcuni campi (es. dc:description delle votazioni) arrivano con entità
    HTML doppiamente codificate ("&amp;#39;"): due passate di unescape le
    risolvono entrambe; una passata sola è comunque idempotente sul testo
    già pulito.
    """
    if not value:
        return None
    return html.unescape(html.unescape(value)).strip() or None


def parse_votazione_uri(uri: str) -> tuple[Optional[int], Optional[int]]:
    """Extract (session_number, vote_number) from a votazione URI.

    Example:
        "http://dati.camera.it/ocd/votazione.rdf/vs19_029_089"
        -> (29, 89)
    """
    m = _VOTAZIONE_URI_RE.search(uri)
    if not m:
        return None, None
    return int(m.group(1)), int(m.group(2))


def _extract_person_id_from_neo4j_id(neo4j_id: str) -> Optional[str]:
    """Extract numeric person_id string from a Neo4j Deputy.id (persona.rdf/p{id})."""
    m = _PERSONA_ID_RE.search(neo4j_id)
    if not m:
        return None
    return m.group(1)


def _to_int(row: dict, key: str) -> Optional[int]:
    """Safely extract an integer from a SPARQL binding row dict.

    Returns None when the key is absent or the value is not a valid integer.
    """
    val = row.get(key, {}).get("value")
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# SPARQL HTTP helper
# ---------------------------------------------------------------------------

def _sparql_get(query: str, timeout: int = SPARQL_TIMEOUT, max_retries: int = 3) -> list[dict]:
    """Execute a SPARQL SELECT query and return the bindings list.

    Uses urllib (stdlib) to avoid additional dependencies.
    Retries with exponential backoff on transient failures (rate limiting, empty responses).
    Returns an empty list on persistent failure — never raises.
    """
    import time as _time

    post_data = urllib.parse.urlencode({
        "query": query,
        "format": "application/sparql-results+json",
    }).encode("utf-8")

    for attempt in range(1, max_retries + 1):
        req = urllib.request.Request(
            SPARQL_ENDPOINT,
            data=post_data,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "User-Agent": "Mozilla/5.0 ParliamentRAG",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if not raw or not raw.strip():
                    raise ValueError("Empty response body")
                data = json.loads(raw)
                # Success — add a small delay to be polite to the endpoint
                _time.sleep(0.5)
                return data.get("results", {}).get("bindings", [])
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            if attempt < max_retries:
                wait = 5 * attempt  # 5s, 10s, 15s
                logger.warning("SPARQL request failed (attempt %d/%d, retrying in %ds): %s",
                               attempt, max_retries, wait, exc)
                _time.sleep(wait)
            else:
                logger.warning("SPARQL request failed after %d attempts: %s", max_retries, exc)
                return []
        except (json.JSONDecodeError, ValueError) as exc:
            if attempt < max_retries:
                wait = 10 * attempt  # 10s, 20s, 30s — longer for rate limiting
                logger.warning("SPARQL response not JSON (attempt %d/%d, retrying in %ds): %s",
                               attempt, max_retries, wait, exc)
                _time.sleep(wait)
            else:
                logger.warning("SPARQL response not JSON after %d attempts: %s", max_retries, exc)
                return []
        except Exception as exc:
            if attempt < max_retries:
                wait = 10 * attempt
                logger.warning("Unexpected SPARQL error (attempt %d/%d, retrying in %ds): %s",
                               attempt, max_retries, wait, exc)
                _time.sleep(wait)
            else:
                logger.warning("Unexpected SPARQL error after %d attempts: %s", max_retries, exc)
                return []
    return []  # Should not reach here


# ---------------------------------------------------------------------------
# SparqlIngester class
# ---------------------------------------------------------------------------

class SparqlIngester:
    """Enriches the Neo4j graph from dati.camera.it SPARQL endpoint."""

    def __init__(self, driver) -> None:
        self._driver = driver

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_votes(
        self,
        limit_deputies: int = 0,
        workers: int = SPARQL_WORKERS,
        chamber: str = "camera",
        legislature: int = 19,
    ) -> dict:
        """Fetch individual vote records from SPARQL and write IndividualVote nodes.

        Args:
            limit_deputies: If > 0, only process that many deputies (for testing).
            workers: Number of concurrent SPARQL request threads.
            chamber: 'camera' or 'senato' — scopes deputy and session queries.
            legislature: Legislature number (18 or 19) — scopes session queries.

        Returns:
            Stats dict: {"deputies_processed": N, "votes_written": N, "votes_skipped": N}
        """
        # Without this constraint every MERGE on IndividualVote.id is a full
        # label scan — throughput collapses once a few hundred thousand nodes exist.
        with self._driver.session() as neo_session:
            neo_session.run(
                "CREATE CONSTRAINT IF NOT EXISTS FOR (iv:IndividualVote) REQUIRE iv.id IS UNIQUE"
            ).consume()

        deputies = self._fetch_all_deputies(chamber=chamber)
        logger.info("Found %d deputies in Neo4j", len(deputies))
        if limit_deputies > 0:
            deputies = deputies[:limit_deputies]
            logger.info("Limited to %d deputies (test mode)", limit_deputies)

        # Check which deputies already have votes — skip them to allow resume
        already_done = self._get_deputies_with_votes(chamber=chamber)
        logger.info("Deputies already enriched with votes: %d", len(already_done))

        # Build work list (skip already-done and unparseable)
        work = []
        deputies_skipped_resume = 0
        for i, deputy in enumerate(deputies):
            neo4j_id = deputy["id"]
            person_id = _extract_person_id_from_neo4j_id(neo4j_id)
            if not person_id:
                logger.warning("  SKIP — cannot extract person_id from %s", neo4j_id)
                continue
            if neo4j_id in already_done:
                deputies_skipped_resume += 1
                continue
            dep_sparql_uri = f"http://dati.camera.it/ocd/deputato.rdf/d{person_id}_{legislature}"
            work.append((neo4j_id, person_id, dep_sparql_uri))

        # Ministri-deputati: esistono solo come GovernmentMember ma votano in
        # Aula; senza questo blocco i loro voti individuali si perdono.
        if chamber == "camera":
            for gov in self._fetch_government_deputies():
                if gov["id"] in already_done:
                    deputies_skipped_resume += 1
                    continue
                dep_sparql_uri = (
                    f"http://dati.camera.it/ocd/deputato.rdf/d{gov['person_id']}_{legislature}"
                )
                work.append((gov["id"], gov["person_id"], dep_sparql_uri))

        if deputies_skipped_resume:
            logger.info("Resumed: skipping %d deputies already enriched", deputies_skipped_resume)
        logger.info("Deputies to process: %d (with %d workers)", len(work), workers)

        # Thread-safe counters
        lock = threading.Lock()
        total_written = 0
        total_skipped = 0
        done_count = 0

        def _process_deputy(item):
            nonlocal total_written, total_skipped, done_count
            neo4j_id, person_id, dep_sparql_uri = item
            logger.info("  Querying votes for person %s ...", person_id)
            written, skipped = self._ingest_deputy_votes(
                neo4j_id, person_id, dep_sparql_uri, chamber=chamber, legislature=legislature
            )
            with lock:
                total_written += written
                total_skipped += skipped
                done_count += 1
                logger.info("  [%d/%d] person %s → written=%d skipped=%d (total: %d written, %d skipped)",
                            done_count, len(work), person_id, written, skipped, total_written, total_skipped)

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_process_deputy, item): item for item in work}
            for future in as_completed(futures):
                exc = future.exception()
                if exc:
                    item = futures[future]
                    logger.error("  Error processing person %s: %s", item[1], exc)

        logger.info(
            "Vote ingestion complete: deputies=%d, votes_written=%d, votes_skipped=%d",
            len(deputies), total_written, total_skipped,
        )
        return {
            "deputies_processed": len(deputies),
            "votes_written": total_written,
            "votes_skipped": total_skipped,
        }

    def ingest_individual_votes_for_recent_sittings(
        self,
        legislature: int = 19,
        start_session: int = 1,
        chamber: str = "camera",
    ) -> dict:
        """Individual votes for the sittings from start_session on, queried
        per votazione instead of per deputy.

        The per-deputy path (ingest_votes) resumes by skipping deputies that
        already have votes, which makes it blind to new sittings after the
        first full build. This is the incremental complement: bounded by
        sitting number, idempotent MERGEs, cheap enough for the daily update.
        """
        # SPARQL rows carry deputato URIs; their person number resolves through
        # camera_id, which also covers ministers on legacy gov_* nodes and
        # senators who sat in the Camera.
        person_to_neo4j = self._camera_person_index()

        sittings = sorted(
            n for n in self._get_camera_sittings_in_db(legislature)
            if n is not None and int(n) >= start_session
        )
        logger.info(
            "Individual-vote ingest for %d sittings (legislature=%s, start=%s)",
            len(sittings), legislature, start_session,
        )

        total_written = 0
        total_skipped = 0
        for num in sittings:
            rows = self._get_camera_votes_for_sitting(legislature, num)
            uris = sorted({
                r.get("votazione", {}).get("value", "")
                for r in rows if r.get("votazione", {}).get("value")
            })
            sitting_written = 0
            for uri in uris:
                w, s = self._ingest_votazione_individual_votes(
                    uri, person_to_neo4j, chamber=chamber, legislature=legislature,
                )
                total_written += w
                total_skipped += s
                sitting_written += w
            logger.info("  sitting %s: %d individual votes written (total: %d)",
                        num, sitting_written, total_written)

        logger.info(
            "Individual-vote ingest complete: sittings=%d, written=%d, skipped=%d",
            len(sittings), total_written, total_skipped,
        )
        return {
            "sittings_processed": len(sittings),
            "votes_written": total_written,
            "votes_skipped": total_skipped,
        }

    def _ingest_votazione_individual_votes(
        self,
        votazione_uri: str,
        person_to_neo4j: dict[str, str],
        chamber: str = "camera",
        legislature: int = 19,
    ) -> tuple[int, int]:
        """Individual votes of one votazione. Returns (written, skipped)."""
        session_num, vote_num = parse_votazione_uri(votazione_uri)
        if session_num is None or vote_num is None:
            return 0, 0
        written = 0
        skipped = 0
        offset = 0
        while True:
            bindings = self._get_votazione_individual_votes(votazione_uri, offset=offset)
            if not bindings:
                break
            batch = []
            for row in bindings:
                dep_uri = row.get("deputato", {}).get("value", "")
                tipo = row.get("tipo", {}).get("value", "")
                pid_match = _DEPUTATO_URI_RE.search(dep_uri)
                if not pid_match:
                    skipped += 1
                    continue
                neo4j_id = person_to_neo4j.get(pid_match.group(1))
                if not neo4j_id:
                    skipped += 1
                    continue
                batch.append({
                    "id": individual_vote_id(
                        chamber, legislature, pid_match.group(1), session_num, vote_num,
                    ),
                    "deputyId": neo4j_id,
                    "sessionNumber": session_num,
                    "voteNumber": vote_num,
                    "outcome": OUTCOME_MAP.get(tipo, "absent"),
                })
            if batch:
                w, s = self._write_votes(batch, chamber=chamber, legislature=legislature)
                written += w
                skipped += s
            if len(bindings) < SPARQL_PAGE_SIZE:
                break
            offset += SPARQL_PAGE_SIZE
        return written, skipped

    def ingest_committee_roles(
        self,
        chamber: str = "camera",
        legislature: int = 19,
    ) -> dict:
        """Fetch committee officer roles from SPARQL and enrich MEMBER_OF_COMMITTEE.

        Args:
            chamber: 'camera' or 'senato' — scopes deputy queries.
            legislature: Legislature number (18 or 19) — used to build deputato SPARQL URI.

        Returns:
            Stats dict: {"deputies_processed": N, "roles_written": N}
        """
        deputies = self._fetch_all_deputies(chamber=chamber)
        logger.info("Found %d deputies in Neo4j", len(deputies))
        total_roles = 0

        for i, deputy in enumerate(deputies):
            neo4j_id = deputy["id"]
            person_id = _extract_person_id_from_neo4j_id(neo4j_id)
            if not person_id:
                continue

            dep_sparql_uri = f"http://dati.camera.it/ocd/deputato.rdf/d{person_id}_{legislature}"
            bindings = self._get_committee_roles(dep_sparql_uri)
            if not bindings:
                continue

            batch = self._prepare_committee_role_batch(bindings, neo4j_id)
            if not batch:
                continue

            roles_written = self._write_committee_roles(batch)
            total_roles += roles_written
            logger.info("  [%d/%d] person %s → %d roles (total: %d)",
                        i + 1, len(deputies), person_id, roles_written, total_roles)

        logger.info(
            "Committee role ingestion complete: deputies=%d, roles_written=%d",
            len(deputies), total_roles,
        )
        return {
            "deputies_processed": len(deputies),
            "roles_written": total_roles,
        }

    def ingest_camera_aggregate_votes(
        self,
        legislature: int = 19,
        start_session: int = 350,
        limit_sessions: int = 0,
        only_sessions: Optional[set[int]] = None,
    ) -> dict:
        """Ingest aggregate Vote nodes from Camera SPARQL for votazioni not yet in the graph.

        A votazione is skipped when its sitting already has a Vote with the same
        number, so XML-sourced votes (Camera XIX sittings 1-349, different id
        scheme) are never duplicated. Skipping whole sittings with at least one
        vote instead left 59 sittings empty and 23 without their last votazione,
        often the final vote (PDL 1275, sitting 210).

        Args:
            legislature: Legislature number (18 or 19).
            start_session: Only process sessions >= this number (default 350, first post-XML).
            limit_sessions: If > 0, cap the number of sittings processed (for testing).
            only_sessions: If given, process exactly these sittings (start_session ignored).

        Returns:
            Stats dict: {"sittings_processed": N, "votes_written": N}
        """
        sittings = self._get_camera_sittings_in_db(legislature)
        existing = self._get_camera_vote_numbers(legislature)
        if only_sessions is not None:
            todo = sorted(n for n in sittings if n in only_sessions)
        else:
            todo = sorted(n for n in sittings if n >= start_session)
        if limit_sessions:
            todo = todo[:limit_sessions]
        logger.info(
            "Camera aggregate ingest: %d/%d sittings to process (legislature=%d, start=%d)",
            len(todo), len(sittings), legislature, start_session,
        )
        written = 0
        for num in todo:
            bindings = self._get_camera_votes_for_sitting(legislature, num)
            batch = []
            for row in bindings:
                session_num, vote_num = parse_votazione_uri(
                    row.get("votazione", {}).get("value", "")
                )
                if vote_num is None or vote_num in existing.get(num, ()):
                    continue
                approvato = row.get("approvato", {}).get("value")
                outcome = (
                    "approved" if approvato == "1"
                    else ("rejected" if approvato == "0" else "unknown")
                )
                batch.append({
                    "id": f"camera_leg{legislature}_sed{num:03d}_v{vote_num:03d}",
                    "sessionNumber": num,
                    "voteNumber": vote_num,
                    "label": clean_sparql_text(row.get("label", {}).get("value")),
                    "type": row.get("tipo", {}).get("value"),
                    "present": _to_int(row, "presenti"),
                    "voters": _to_int(row, "votanti"),
                    "inFavor": _to_int(row, "favorevoli"),
                    "against": _to_int(row, "contrari"),
                    "abstained": _to_int(row, "astenuti"),
                    "majority": _to_int(row, "maggioranza"),
                    "outcome": outcome,
                    "description": clean_sparql_text(row.get("descrizione", {}).get("value")),
                    "finalVote": row.get("finale", {}).get("value") == "1",
                    "confidenceVote": row.get("fiducia", {}).get("value") == "1",
                    "secretVote": row.get("segreta", {}).get("value") == "1",
                    "actUri": row.get("atto", {}).get("value"),
                    "actTitle": clean_sparql_text(row.get("attoTitolo", {}).get("value")),
                    "aicUri": row.get("aic", {}).get("value"),
                    "aicTitle": clean_sparql_text(row.get("aicTitolo", {}).get("value")),
                })
            if batch:
                written += self._write_camera_aggregate_votes(batch, legislature)
                logger.info("  sitting %d: %d votes written (total so far: %d)", num, len(batch), written)
        logger.info(
            "Camera aggregate ingest complete: sittings=%d, votes_written=%d",
            len(todo), written,
        )
        return {"sittings_processed": len(todo), "votes_written": written}

    # ------------------------------------------------------------------
    # Batch preparation helpers (testable without DB)
    # ------------------------------------------------------------------

    def _prepare_vote_batch(
        self,
        bindings: list[dict],
        deputy_neo4j_id: str,
        person_id: str,
        chamber: str = "camera",
        legislature: int = 19,
    ) -> list[dict]:
        """Convert SPARQL vote bindings to Neo4j batch dicts.

        Skips any binding where the votazione URI cannot be parsed.
        The IndividualVote id carries a chamber prefix to prevent Camera/Senate collisions.
        """
        batch = []
        for row in bindings:
            votazione_uri = row.get("votazione", {}).get("value", "")
            tipo = row.get("tipo", {}).get("value", "")
            session_num, vote_num = parse_votazione_uri(votazione_uri)
            if session_num is None or vote_num is None:
                continue
            outcome = OUTCOME_MAP.get(tipo, "absent")
            iv_id = individual_vote_id(chamber, legislature, person_id, session_num, vote_num)
            batch.append({
                "id": iv_id,
                "deputyId": deputy_neo4j_id,
                "sessionNumber": session_num,
                "voteNumber": vote_num,
                "outcome": outcome,
            })
        return batch

    def _prepare_committee_role_batch(
        self,
        bindings: list[dict],
        deputy_neo4j_id: str,
    ) -> list[dict]:
        """Convert SPARQL committee role bindings to Neo4j batch dicts."""
        batch = []
        for row in bindings:
            committee_name = row.get("organoLabel", {}).get("value", "")
            role = row.get("carica", {}).get("value", "")
            start_date = row.get("startDate", {}).get("value", None)
            end_date = row.get("endDate", {}).get("value", None) if "endDate" in row else None
            if not committee_name or not role:
                continue
            batch.append({
                "deputyId": deputy_neo4j_id,
                "committeeName": committee_name,
                "role": role,
                "startDate": start_date,
                "endDate": end_date,
            })
        return batch

    # ------------------------------------------------------------------
    # SPARQL query methods
    # ------------------------------------------------------------------

    def _get_deputy_votes_page(self, dep_sparql_uri: str, offset: int = 0) -> list[dict]:
        """Fetch one page of vote records for a deputy from the SPARQL endpoint."""
        query = f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>

SELECT ?voto ?votazione ?tipo
WHERE {{
  ?voto a ocd:voto ;
        ocd:rif_deputato <{dep_sparql_uri}> ;
        ocd:rif_votazione ?votazione ;
        dc:type ?tipo .
}}
LIMIT {SPARQL_PAGE_SIZE}
OFFSET {offset}
"""
        return _sparql_get(query)

    def _get_votazione_individual_votes(self, votazione_uri: str, offset: int = 0) -> list[dict]:
        """Fetch one page of individual vote records for a single votazione.

        DISTINCT: the triples sit in more than one graph, so every vote came
        back twice and was written twice."""
        query = f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>

SELECT DISTINCT ?deputato ?tipo
WHERE {{
  ?voto a ocd:voto ;
        ocd:rif_votazione <{votazione_uri}> ;
        ocd:rif_deputato ?deputato ;
        dc:type ?tipo .
}}
LIMIT {SPARQL_PAGE_SIZE}
OFFSET {offset}
"""
        return _sparql_get(query)

    def _get_committee_roles(self, dep_sparql_uri: str) -> list[dict]:
        """Fetch committee officer roles for a deputy from the SPARQL endpoint."""
        query = f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT ?organoLabel ?carica ?startDate ?endDate
WHERE {{
  ?ufficio a ocd:ufficioParlamentare ;
           ocd:rif_deputato <{dep_sparql_uri}> ;
           ocd:rif_organo ?organo ;
           ocd:carica ?carica ;
           ocd:startDate ?startDate .
  ?organo rdfs:label ?organoLabel .
  OPTIONAL {{ ?ufficio ocd:endDate ?endDate . }}
}}
"""
        return _sparql_get(query)

    def _get_camera_votes_for_sitting(self, legislature: int, session_num: int) -> list[dict]:
        """Fetch aggregate vote records for one Camera sitting from SPARQL.

        Uses SELECT DISTINCT because each Camera votazione has two rdf:type triples,
        causing duplicate rows without DISTINCT. The seduta URI is written both
        with and without zero padding (s19_004 next to s19_24), so both are tried.
        """
        seduta_uris = " ".join(sorted({
            f"<http://dati.camera.it/ocd/seduta.rdf/s{legislature}_{session_num}>",
            f"<http://dati.camera.it/ocd/seduta.rdf/s{legislature}_{session_num:03d}>",
        }))
        query = f"""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>

SELECT DISTINCT ?votazione ?label ?tipo ?approvato ?favorevoli ?contrari
                ?presenti ?votanti ?astenuti ?maggioranza ?data
                ?descrizione ?finale ?fiducia ?segreta ?atto ?attoTitolo ?aic ?aicTitolo
WHERE {{
  VALUES ?seduta {{ {seduta_uris} }}
  ?votazione a <http://dati.camera.it/ocd/votazione> ;
             ocd:rif_seduta ?seduta .
  OPTIONAL {{ ?votazione rdfs:label ?label . }}
  OPTIONAL {{ ?votazione dc:type ?tipo . }}
  OPTIONAL {{ ?votazione ocd:approvato ?approvato . }}
  OPTIONAL {{ ?votazione ocd:favorevoli ?favorevoli . }}
  OPTIONAL {{ ?votazione ocd:contrari ?contrari . }}
  OPTIONAL {{ ?votazione ocd:presenti ?presenti . }}
  OPTIONAL {{ ?votazione ocd:votanti ?votanti . }}
  OPTIONAL {{ ?votazione ocd:astenuti ?astenuti . }}
  OPTIONAL {{ ?votazione ocd:maggioranza ?maggioranza . }}
  OPTIONAL {{ ?votazione dc:date ?data . }}
  OPTIONAL {{ ?votazione dc:description ?descrizione . }}
  OPTIONAL {{ ?votazione ocd:votazioneFinale ?finale . }}
  OPTIONAL {{ ?votazione ocd:richiestaFiducia ?fiducia . }}
  OPTIONAL {{ ?votazione ocd:votazioneSegreta ?segreta . }}
  OPTIONAL {{ ?votazione ocd:rif_attoCamera ?atto .
              OPTIONAL {{ ?atto dc:title ?attoTitolo . }} }}
  OPTIONAL {{ ?votazione ocd:rif_aic ?aic .
              OPTIONAL {{ ?aic dc:title ?aicTitolo . }} }}
}}
"""
        return _sparql_get(query)

    # ------------------------------------------------------------------
    # Neo4j read/write helpers for Camera aggregate votes
    # ------------------------------------------------------------------

    def _get_camera_sittings_in_db(self, legislature: int) -> set[int]:
        """Return all Camera session numbers in Neo4j for the given legislature."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (s:Session) WHERE coalesce(s.chamber, 'camera') = 'camera' "
                "AND s.legislature = $legislature RETURN s.number AS n",
                legislature=legislature,
            )
            return {record["n"] for record in result if record["n"] is not None}

    def _get_camera_vote_numbers(self, legislature: int) -> dict[int, set[int]]:
        """Return Camera session number -> numbers of the Vote nodes it already has."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (s:Session)-[:HAS_VOTE]->(v:Vote) "
                "WHERE coalesce(s.chamber, 'camera') = 'camera' "
                "AND s.legislature = $legislature AND v.number IS NOT NULL "
                "RETURN s.number AS n, collect(DISTINCT toInteger(v.number)) AS votes",
                legislature=legislature,
            )
            return {
                record["n"]: set(record["votes"])
                for record in result if record["n"] is not None
            }

    def _get_camera_votazioni(self, legislature: int) -> dict[int, dict[int, str]]:
        """Every votazione of the legislature on dati.camera.it, as
        session number -> {vote number: votazione URI}. Keyset pagination: large OFFSETs
        return HTTP 500 on Virtuoso."""
        leg_uri = f"http://dati.camera.it/ocd/legislatura.rdf/repubblica_{legislature}"
        out: dict[int, dict[int, str]] = {}
        last = ""
        while True:
            query = f"""
PREFIX ocd: <http://dati.camera.it/ocd/>

SELECT DISTINCT ?votazione
WHERE {{
  ?votazione a ocd:votazione ;
             ocd:rif_leg <{leg_uri}> .
  FILTER(STR(?votazione) > "{last}")
}}
ORDER BY ?votazione
LIMIT 10000
"""
            bindings = _sparql_get(query)
            if not bindings:
                break
            for row in bindings:
                uri = row["votazione"]["value"]
                session_num, vote_num = parse_votazione_uri(uri)
                if session_num is not None and vote_num is not None:
                    out.setdefault(session_num, {})[vote_num] = uri
            last = bindings[-1]["votazione"]["value"]
            if len(bindings) < 10000:
                break
        if not out:
            raise RuntimeError("dati.camera.it returned no votazioni (endpoint down?)")
        return out

    def find_camera_vote_gaps(self, legislature: int = 19) -> dict[int, dict[int, str]]:
        """Votazioni published on dati.camera.it but missing from the graph,
        as session number -> {vote number: votazione URI}."""
        published = self._get_camera_votazioni(legislature)
        existing = self._get_camera_vote_numbers(legislature)
        gaps = {}
        for num, votes in published.items():
            have = existing.get(num, set())
            missing = {n: uri for n, uri in votes.items() if n not in have}
            if missing:
                gaps[num] = missing
        return gaps

    def fill_camera_vote_gaps(self, legislature: int = 19) -> dict:
        """Compare the whole legislature with dati.camera.it and write the
        missing votazioni: aggregate Vote nodes, then their individual votes."""
        gaps = self.find_camera_vote_gaps(legislature)
        sittings_in_db = self._get_camera_sittings_in_db(legislature)
        no_session = sorted(n for n in gaps if n not in sittings_in_db)
        if no_session:
            logger.warning("Sittings with votes on dati.camera.it but no Session node: %s", no_session)
        logger.info(
            "Camera vote gaps: %d votazioni in %d sittings",
            sum(len(v) for v in gaps.values()), len(gaps),
        )
        agg = self.ingest_camera_aggregate_votes(
            legislature=legislature, only_sessions=set(gaps),
        )
        person_to_neo4j = self._camera_person_index()
        written = 0
        skipped = 0
        for num in sorted(gaps):
            if num not in sittings_in_db:
                continue
            for _, uri in sorted(gaps[num].items()):
                w, s = self._ingest_votazione_individual_votes(
                    uri, person_to_neo4j, chamber="camera", legislature=legislature,
                )
                written += w
                skipped += s
            logger.info("  sitting %d: individual votes written so far %d", num, written)
        return {
            "gap_votazioni": sum(len(v) for v in gaps.values()),
            "gap_sittings": len(gaps),
            "sittings_without_session": no_session,
            "aggregate_written": agg["votes_written"],
            "individual_written": written,
            "individual_skipped": skipped,
        }

    def _write_camera_aggregate_votes(self, batch: list[dict], legislature: int) -> int:
        """Write aggregate Vote nodes and HAS_VOTE relationships for Camera sessions.

        Matches the Vote node shape from db_builder._create_votes, plus the
        SPARQL-only enrichments:
          Vote {id, number, type, subject, description, finalVote,
                confidenceVote, present, voters, abstained, majority,
                inFavor, against, outcome}
        and, when the votazione references an atto Camera, the relationship
        (v)-[:ON_ACT]->(ParliamentaryAct {uri}).

        Returns the count of Vote nodes written (MERGEd).
        """
        cypher = """
UNWIND $batch AS row
MATCH (s:Session {number: row.sessionNumber})
WHERE coalesce(s.chamber, 'camera') = 'camera' AND s.legislature = $legislature
MERGE (v:Vote {id: row.id})
SET v.number = row.voteNumber,
    v.type = row.type,
    v.subject = row.label,
    v.description = row.description,
    v.finalVote = row.finalVote,
    v.confidenceVote = row.confidenceVote,
    v.secretVote = row.secretVote,
    v.present = row.present,
    v.voters = row.voters,
    v.abstained = row.abstained,
    v.majority = row.majority,
    v.inFavor = row.inFavor,
    v.against = row.against,
    v.outcome = row.outcome
MERGE (s)-[:HAS_VOTE]->(v)
FOREACH (_ IN CASE WHEN row.actUri IS NULL THEN [] ELSE [1] END |
  MERGE (a:ParliamentaryAct {uri: row.actUri})
  SET a.title = coalesce(a.title, row.actTitle)
  MERGE (v)-[:ON_ACT]->(a)
)
FOREACH (_ IN CASE WHEN row.aicUri IS NULL THEN [] ELSE [1] END |
  MERGE (b:ParliamentaryAct {uri: row.aicUri})
  SET b.title = coalesce(b.title, row.aicTitle)
  MERGE (v)-[:ON_ACT]->(b)
)
RETURN count(*) AS written
"""
        total = 0
        for i in range(0, len(batch), BATCH_SIZE):
            chunk = batch[i:i + BATCH_SIZE]
            with self._driver.session() as neo_session:
                result = neo_session.run(cypher, batch=chunk, legislature=legislature)
                record = result.single()
                total += record["written"] if record else 0
        return total

    # ------------------------------------------------------------------
    # Neo4j write helpers
    # ------------------------------------------------------------------

    def _camera_person_index(self) -> dict[str, str]:
        """Camera person number -> Person node id, through camera_id."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (p:Person) WHERE p.camera_id IS NOT NULL "
                "RETURN p.camera_id AS cam, p.id AS id"
            )
            index: dict[str, str] = {}
            for record in result:
                pid = _extract_person_id_from_neo4j_id(record["cam"])
                if pid:
                    index[pid] = record["id"]
            return index

    def _fetch_all_deputies(self, chamber: str = "camera") -> list[dict]:
        """Return list of {id: ...} dicts for Deputy nodes filtered by chamber."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (d:Deputy) WHERE coalesce(d.chamber, 'camera') = $chamber RETURN d.id AS id",
                chamber=chamber,
            )
            return [{"id": record["id"]} for record in result if record["id"]]

    def _fetch_government_deputies(self) -> list[dict]:
        """Return [{id, person_id}] for GovernmentMembers that sit in the Camera.

        I ministri-deputati (Tajani, Giorgetti, ...) votano in Aula ma nel
        grafo esistono solo come GovernmentMember: deputy_card è il loro id
        persona Camera, la chiave per agganciare i voti individuali SPARQL.
        """
        with self._driver.session() as neo_session:
            # Guardia anti-doppione: se per la stessa persona esiste anche un
            # nodo Deputy (successo con Bellucci per uno split del nome
            # sbagliato), i voti li prende il Deputy — processarla anche qui
            # duplicherebbe ogni suo voto.
            result = neo_session.run(
                "MATCH (g:GovernmentMember) WHERE g.deputy_card IS NOT NULL "
                "AND NOT EXISTS { MATCH (d:Deputy) WHERE d.id = "
                "  'http://dati.camera.it/ocd/persona.rdf/p' + toString(g.deputy_card) } "
                "RETURN g.id AS id, g.deputy_card AS person_id"
            )
            return [
                {"id": r["id"], "person_id": str(r["person_id"])}
                for r in result
                if r["id"] and r["person_id"]
            ]

    def _get_deputies_with_votes(self, chamber: str = "camera") -> set[str]:
        """Return set of Person.id values (Deputy or GovernmentMember) that already have VOTED relationships, filtered by chamber."""
        with self._driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (d:Person)-[:VOTED]->() WHERE coalesce(d.chamber, 'camera') = $chamber "
                "RETURN DISTINCT d.id AS id",
                chamber=chamber,
            )
            return {record["id"] for record in result if record["id"]}

    def _ingest_deputy_votes(
        self,
        neo4j_id: str,
        person_id: str,
        dep_sparql_uri: str,
        chamber: str = "camera",
        legislature: int = 19,
    ) -> tuple[int, int]:
        """Page through all votes for one deputy and write them to Neo4j.

        Returns (votes_written, votes_skipped).
        """
        written = 0
        skipped = 0
        offset = 0
        page = 0

        while True:
            page += 1
            bindings = self._get_deputy_votes_page(dep_sparql_uri, offset=offset)
            if not bindings:
                if page == 1:
                    logger.debug("    No vote records found in SPARQL")
                break

            batch = self._prepare_vote_batch(
                bindings, neo4j_id, person_id, chamber=chamber, legislature=legislature,
            )
            parse_skipped = len(bindings) - len(batch)
            skipped += parse_skipped

            if batch:
                w, s = self._write_votes(batch, chamber=chamber, legislature=legislature)
                written += w
                skipped += s
                logger.debug("    Page %d: %d SPARQL rows → %d written, %d skipped", page, len(bindings), w, s + parse_skipped)

            if len(bindings) < SPARQL_PAGE_SIZE:
                break
            offset += SPARQL_PAGE_SIZE

        return written, skipped

    def _write_votes(
        self,
        batch: list[dict],
        chamber: str = "camera",
        legislature: int = 19,
    ) -> tuple[int, int]:
        """Write a batch of IndividualVote nodes to Neo4j.

        Scopes Session matching to the given chamber+legislature to prevent
        cross-legislature and cross-chamber Session number collisions.

        Returns (written, skipped) where skipped = rows with no matching Vote node.
        """
        cypher = """
UNWIND $batch AS row
MATCH (d:Person {id: row.deputyId})
MATCH (s:Session {number: row.sessionNumber})-[:HAS_VOTE]->(v:Vote {number: row.voteNumber})
WHERE coalesce(s.chamber, 'camera') = $chamber AND s.legislature = $legislature
MERGE (iv:IndividualVote {id: row.id})
SET iv.outcome = row.outcome
MERGE (d)-[:VOTED]->(iv)
MERGE (iv)-[:ON_VOTE]->(v)
RETURN count(*) AS written
"""
        count_cypher = """
UNWIND $batch AS row
OPTIONAL MATCH (s:Session {number: row.sessionNumber})-[:HAS_VOTE]->(v:Vote {number: row.voteNumber})
WHERE coalesce(s.chamber, 'camera') = $chamber AND s.legislature = $legislature
WITH row, v
WHERE v IS NULL
RETURN count(*) AS skipped
"""
        written = 0
        skipped = 0
        chunk_size = BATCH_SIZE

        for i in range(0, len(batch), chunk_size):
            chunk = batch[i:i + chunk_size]
            for attempt in range(_WRITE_RETRIES):
                try:
                    with _NEO4J_WRITE_LOCK, self._driver.session() as neo_session:
                        result = neo_session.run(cypher, batch=chunk, chamber=chamber, legislature=legislature)
                        record = result.single()
                        written += record["written"] if record else 0
                        skip_result = neo_session.run(count_cypher, batch=chunk, chamber=chamber, legislature=legislature)
                        skip_record = skip_result.single()
                        skipped += skip_record["skipped"] if skip_record else 0
                    break
                except TransientError as exc:
                    if attempt == _WRITE_RETRIES - 1:
                        raise
                    wait = 0.5 * (2 ** attempt)
                    logger.warning("    Transient Neo4j error (attempt %d/%d), retrying in %.1fs: %s",
                                   attempt + 1, _WRITE_RETRIES, wait, exc.code)
                    time.sleep(wait)

        return written, skipped

    def _write_committee_roles(self, batch: list[dict]) -> int:
        """Enrich MEMBER_OF_COMMITTEE relationships with officer role data.

        Returns the number of relationships updated.
        """
        cypher = """
UNWIND $batch AS row
MATCH (d:Deputy {id: row.deputyId})-[r:MEMBER_OF_COMMITTEE]->(c:Committee)
WHERE toLower(c.name) CONTAINS toLower(row.committeeName)
SET r.officerRole = row.role,
    r.officerRoleStart = CASE WHEN row.startDate IS NOT NULL THEN date(row.startDate) ELSE NULL END,
    r.officerRoleEnd = CASE WHEN row.endDate IS NOT NULL THEN date(row.endDate) ELSE NULL END
RETURN count(*) AS updated
"""
        total = 0
        chunk_size = BATCH_SIZE
        for i in range(0, len(batch), chunk_size):
            chunk = batch[i:i + chunk_size]
            with self._driver.session() as neo_session:
                result = neo_session.run(cypher, batch=chunk)
                record = result.single()
                total += record["updated"] if record else 0
        return total


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="SPARQL enrichment from dati.camera.it")
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7689")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"), required=os.environ.get("NEO4J_PASSWORD") is None)
    parser.add_argument(
        "--limit-deputies",
        type=int,
        default=0,
        help="Limit to N deputies for testing (0 = all)",
    )
    parser.add_argument(
        "--limit-sessions",
        type=int,
        default=0,
        help="Limit aggregate ingest to N sessions for testing (0 = all)",
    )
    parser.add_argument("--skip-votes", action="store_true", help="Skip individual vote ingestion")
    parser.add_argument("--skip-committees", action="store_true", help="Skip committee roles")
    parser.add_argument(
        "--aggregate-only",
        action="store_true",
        help="Run Camera aggregate vote ingest only (no individual votes, no committee roles)",
    )
    parser.add_argument(
        "--skip-aggregate",
        action="store_true",
        help="Skip aggregate vote ingest; run individual votes only",
    )
    parser.add_argument(
        "--legislature",
        type=int,
        default=19,
        help="Legislature number for aggregate and individual ingest (18 or 19, default 19)",
    )
    parser.add_argument(
        "--start-session",
        type=int,
        default=350,
        help="First session number for Camera aggregate ingest (default 350)",
    )
    parser.add_argument(
        "--fill-gaps",
        action="store_true",
        help=(
            "Compare the whole legislature with dati.camera.it and write the "
            "missing votazioni (aggregate + individual votes), then exit"
        ),
    )
    parser.add_argument(
        "--check-gaps",
        action="store_true",
        help="Only report votazioni missing from the graph; exit 1 if any",
    )
    parser.add_argument(
        "--individual-recent",
        action="store_true",
        help=(
            "Ingest individual votes per votazione for sittings from "
            "--start-session on (incremental update mode), then exit"
        ),
    )
    args = parser.parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j package not installed. Run: pip install neo4j", file=sys.stderr)
        sys.exit(1)

    driver = GraphDatabase.driver(
        args.neo4j_uri,
        auth=(args.neo4j_user, args.neo4j_password),
    )
    try:
        ingester = SparqlIngester(driver)

        if args.check_gaps:
            gaps = ingester.find_camera_vote_gaps(legislature=args.legislature)
            total = sum(len(v) for v in gaps.values())
            print(f"==> Camera votazioni missing from the graph: {total} in {len(gaps)} sittings")
            for num in sorted(gaps):
                print(f"    sitting {num}: {sorted(gaps[num])}")
            sys.exit(1 if gaps else 0)
        elif args.fill_gaps:
            print(f"==> Filling Camera vote gaps against dati.camera.it (leg={args.legislature})...")
            stats = ingester.fill_camera_vote_gaps(legislature=args.legislature)
            print(
                f"    Missing votazioni  : {stats['gap_votazioni']} in {stats['gap_sittings']} sittings\n"
                f"    Aggregate written  : {stats['aggregate_written']}\n"
                f"    Individual written : {stats['individual_written']}\n"
                f"    Individual skipped : {stats['individual_skipped']}"
            )
            if stats["sittings_without_session"]:
                print(f"    Sittings without Session node: {stats['sittings_without_session']}")
        elif args.individual_recent:
            # Incremental mode: individual votes for recent sittings only
            print(f"==> Ingesting individual votes per votazione (leg={args.legislature}, start={args.start_session})...")
            iv_stats = ingester.ingest_individual_votes_for_recent_sittings(
                legislature=args.legislature,
                start_session=args.start_session,
            )
            print(
                f"    Sittings processed : {iv_stats['sittings_processed']}\n"
                f"    Votes written      : {iv_stats['votes_written']}\n"
                f"    Votes skipped      : {iv_stats['votes_skipped']}"
            )
        elif args.aggregate_only:
            # Aggregate-only mode: Camera aggregate votes, nothing else
            print(f"==> Ingesting Camera aggregate votes (leg={args.legislature}, start={args.start_session})...")
            agg_stats = ingester.ingest_camera_aggregate_votes(
                legislature=args.legislature,
                start_session=args.start_session,
                limit_sessions=args.limit_sessions,
            )
            print(
                f"    Sittings processed : {agg_stats['sittings_processed']}\n"
                f"    Votes written      : {agg_stats['votes_written']}"
            )
        else:
            # Default (individual) mode: optionally run aggregate first, then individual + committees
            if not args.skip_aggregate:
                print(f"==> Ingesting Camera aggregate votes (leg={args.legislature}, start={args.start_session})...")
                agg_stats = ingester.ingest_camera_aggregate_votes(
                    legislature=args.legislature,
                    start_session=args.start_session,
                    limit_sessions=args.limit_sessions,
                )
                print(
                    f"    Sittings processed : {agg_stats['sittings_processed']}\n"
                    f"    Votes written      : {agg_stats['votes_written']}"
                )

            if not args.skip_votes:
                print(f"==> Ingesting individual votes (chamber=camera, leg={args.legislature})...")
                vote_stats = ingester.ingest_votes(
                    limit_deputies=args.limit_deputies,
                    chamber="camera",
                    legislature=args.legislature,
                )
                print(
                    f"    Deputies processed : {vote_stats['deputies_processed']}\n"
                    f"    Votes written      : {vote_stats['votes_written']}\n"
                    f"    Votes skipped      : {vote_stats['votes_skipped']}"
                )

            if not args.skip_committees:
                print("==> Enriching committee officer roles...")
                role_stats = ingester.ingest_committee_roles()
                print(
                    f"    Deputies processed : {role_stats['deputies_processed']}\n"
                    f"    Roles written      : {role_stats['roles_written']}"
                )
    finally:
        driver.close()
