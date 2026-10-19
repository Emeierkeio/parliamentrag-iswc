"""
ingest_acts_camera.py — Chamber acts of a legislature, read act by act from dati.camera.it.

The previous ingest (build_and_update._ingest_atti) asked the SPARQL endpoint
for the acts of each sitting deputy, so it never saw Government bills (their
first signatory is a blank node with ocd:rif_persona), bills from regions,
CNEL and popular initiative, acts of former deputies and bills whose
signatories withdrew (AC 1275). This script lists every act of the
legislature instead and reads it in blocks:

  1. list   ocd:atto and ocd:aic (Chamber branch) with ods:modified,
            paged under Virtuoso's 10,000-row cap;
  2. detail scalar fields, signatories and subjects in blocks of URIs (VALUES);
  3. write  MERGE (a:ParliamentaryAct {uri}) with chamber, legislature, family
            label and kind (decision D1), initiative, PRESENTED_BY the
            Government and PRESENTED by its ministers (decision D3).

Writes are additive: a value missing at the source never erases one in the
graph, and no relationship is deleted. When a title or description changes
its embedding is cleared, so precalculate_embeddings.py computes it again.

Incremental: --since-meta reads the newest ods:modified seen by the previous
run from SchemaMeta and only asks for acts modified after it (minus a day).

Usage:
    python build/ingest_acts_camera.py --neo4j-uri bolt://localhost:7690 [--since-meta]
        [--classes atto,aic] [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import html
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import requests
from neo4j import GraphDatabase

sys.path.insert(0, str(Path(__file__).resolve().parent))
from act_kinds import aic_kind, bill_kind, camera_initiative, initiative_from_title  # noqa: E402

logger = logging.getLogger("ingest_acts_camera")

SPARQL_CAMERA = "https://dati.camera.it/sparql"
SPARQL_EUROVOC = "https://publications.europa.eu/webapi/rdf/sparql"
EUROVOC_CACHE = Path("data/eurovoc.csv")
# Concepts the Camera's provisional automatic classification assigns with
# another meaning: 7816 "regioni della Repubblica ceca" stands for
# "Repubblica" there (build/repair_vote_readings.py).
EUROVOC_MISMAPPED = {"http://eurovoc.europa.eu/7816"}
VIRTUOSO_CAP = 10000
META_KEY = "acts_camera_modified"

PREFIXES = """
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX ods: <http://lod.xdams.org/ontologies/ods/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>
"""

# Class -> (extra triple pattern, block size). Bills carry long signatory
# lists, oversight acts long descriptions.
CLASSES = {
    "atto": ("?a a ocd:atto .", 100),
    "aic": ("?a a ocd:aic ; ocd:ramo 'Camera dei Deputati' .", 150),
}

DEPUTY_URI_RE = re.compile(r"/deputato\.rdf/d(\d+)_\d+$")
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


class Sparql:
    def __init__(self, delay: float):
        self.delay = delay
        self.http = requests.Session()
        self.http.headers.update({"Accept": "application/sparql-results+json",
                                  "User-Agent": "ParliamentRAG-acts/1.0 (+https://www.parliamentrag.it)"})
        self.calls = 0

    def select(self, query: str, endpoint: str = SPARQL_CAMERA, timeout: int = 180) -> list[dict]:
        # The endpoint answers 502 for minutes at a time (16/10/2026): back off up to ~15 minutes.
        attempts = 8 if endpoint == SPARQL_CAMERA else 2
        for attempt in range(attempts):
            time.sleep(self.delay)
            try:
                # POST: a block of VALUES does not fit in a GET URL (414).
                r = self.http.post(endpoint, data={"query": PREFIXES + query,
                                         "format": "json" if endpoint == SPARQL_CAMERA
                                         else "application/sparql-results+json"},
                                   timeout=timeout)
                if 400 <= r.status_code < 500 and r.status_code != 429:
                    raise RuntimeError(f"SPARQL {r.status_code}: {r.text[:300]}")
                r.raise_for_status()
                self.calls += 1
                return [{k: v["value"] for k, v in b.items()} for b in r.json()["results"]["bindings"]]
            except (requests.RequestException, ValueError) as exc:
                wait = min(30 * (attempt + 1), 180)
                logger.warning("SPARQL failed (%s), retry in %ds", exc, wait)
                time.sleep(wait)
        raise RuntimeError(f"SPARQL endpoint unreachable after {attempts} attempts")


def clean(text: Optional[str]) -> Optional[str]:
    """HTML entities and tags out, whitespace collapsed; None when empty."""
    if not text:
        return None
    text = SPACE_RE.sub(" ", TAG_RE.sub(" ", html.unescape(html.unescape(text)))).strip()
    return text or None


def iso_day(raw: Optional[str]) -> Optional[str]:
    s = (raw or "").strip()
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}" if len(s) == 8 and s.isdigit() else None


def persona_of_deputy(uri: str) -> Optional[str]:
    m = DEPUTY_URI_RE.search(uri or "")
    return f"http://dati.camera.it/ocd/persona.rdf/p{m.group(1)}" if m else None


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------

def list_acts(sp: Sparql, cls: str, leg: int, since: Optional[str]) -> dict[str, str]:
    """{act URI: ods:modified} for one class.

    Partitioned by year of dc:date (by month when a year reaches the row cap):
    a paged ORDER BY over the 31,000 oversight acts makes Virtuoso fail with
    HTTP 500 (16/10/2026).
    """
    pattern, _ = CLASSES[cls]
    flt = f'FILTER(?m > "{since}"^^xsd:dateTime)' if since else ""

    def part(prefix: str) -> list[dict]:
        return sp.select(f"""
            SELECT ?a (MAX(?m) AS ?mod) WHERE {{
              {pattern}
              ?a ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}> ;
                 dc:date ?d .
              FILTER(STRSTARTS(STR(?d), "{prefix}"))
              OPTIONAL {{ ?a ods:modified ?m }}
              {flt}
            }} GROUP BY ?a
        """)

    out: dict[str, str] = {}
    for year in range(2000, datetime.now().year + 1):
        rows = part(str(year))
        if len(rows) >= VIRTUOSO_CAP:
            rows = [r for month in range(1, 13) for r in part(f"{year}{month:02d}")]
        for r in rows:
            out[r["a"]] = r.get("mod", "")
    undated = sp.select(f"""
        SELECT (COUNT(DISTINCT ?a) AS ?n) WHERE {{ {pattern}
          ?a ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}> .
          FILTER NOT EXISTS {{ ?a dc:date ?d }} }}""")
    if undated and int(undated[0]["n"]):
        logger.warning("%s: %s atti senza dc:date esclusi dall'elenco", cls, undated[0]["n"])
    return out


def _values(uris: list[str]) -> str:
    return "VALUES ?a { " + " ".join(f"<{u}>" for u in uris) + " }"


def _select_block(sp: Sparql, query_for, uris: list[str]) -> list[dict]:
    """Run query_for(uris); split the block when Virtuoso hits its row cap."""
    rows = sp.select(query_for(uris))
    if len(rows) < VIRTUOSO_CAP or len(uris) == 1:
        return rows
    half = len(uris) // 2
    return _select_block(sp, query_for, uris[:half]) + _select_block(sp, query_for, uris[half:])


def fetch_details(sp: Sparql, uris: list[str]) -> dict[str, dict]:
    """Fields, signatories and subjects of a block of acts.

    One query per multi-valued property: joining them multiplies the rows,
    and Virtuoso fails to compile VALUES with UNION and BIND (SP031).
    """
    def q(body: str) -> list[dict]:
        return _select_block(sp, lambda u: body.replace("$VALUES", _values(u)), uris)

    scalars = q("""
        SELECT ?a (SAMPLE(?type) AS ?type) (SAMPLE(?title) AS ?title) (SAMPLE(?descr) AS ?descr)
               (SAMPLE(?start) AS ?start) (SAMPLE(?date) AS ?date) (SAMPLE(?id) AS ?id)
               (SAMPLE(?init) AS ?init) (SAMPLE(?nat) AS ?nat) (SAMPLE(?page) AS ?page)
               (MAX(?mod) AS ?mod)
        WHERE { $VALUES
          OPTIONAL { ?a dc:type ?type }       OPTIONAL { ?a dc:title ?title }
          OPTIONAL { ?a dc:description ?descr }
          OPTIONAL { ?a ocd:startDate ?start } OPTIONAL { ?a dc:date ?date }
          OPTIONAL { ?a dc:identifier ?id }    OPTIONAL { ?a ocd:iniziativa ?init }
          OPTIONAL { ?a ocd:rif_natura ?nat }  OPTIONAL { ?a dcterms:isReferencedBy ?page }
          OPTIONAL { ?a ods:modified ?mod }
        } GROUP BY ?a""")
    primary = q("SELECT DISTINCT ?a ?f WHERE { $VALUES ?a ocd:primo_firmatario ?f }")
    co = q("SELECT DISTINCT ?a ?f WHERE { $VALUES ?a ocd:altro_firmatario ?f }")
    # Government bills: the first signatory is a blank node naming the minister.
    government = q("""SELECT DISTINCT ?a ?persona ?office WHERE { $VALUES
        ?a ocd:primo_firmatario ?f . ?f ocd:rif_persona ?persona . OPTIONAL { ?f ocd:ruolo ?office } }""")
    subjects = q("""SELECT DISTINCT ?a ?ev WHERE { $VALUES ?a dcterms:subject ?ev
        FILTER(STRSTARTS(STR(?ev), "http://eurovoc.europa.eu/")) }""")
    recipients = q("""SELECT DISTINCT ?a ?recipient WHERE { $VALUES
        ?a ocd:destinatario ?d . ?d rdfs:label ?recipient }""")

    acts: dict[str, dict] = {}
    for r in scalars:
        acts[r["a"]] = {**r, "signers": [], "eurovoc": [], "recipients": []}
    for rows, role in ((primary, "primo"), (co, "altro")):
        for r in rows:
            persona = persona_of_deputy(r["f"])
            if persona and r["a"] in acts:
                acts[r["a"]]["signers"].append({"role": role, "persona": persona, "government": False})
    for r in government:
        if r["a"] in acts:
            acts[r["a"]]["signers"].append({"role": "primo", "persona": r["persona"],
                                            "government": True, "office": r.get("office")})
    for r in subjects:
        if r["a"] in acts:
            acts[r["a"]]["eurovoc"].append(r["ev"])
    for r in recipients:
        if r["a"] in acts:
            acts[r["a"]]["recipients"].append(clean(r["recipient"]))
    return acts


class EurovocLabels:
    """Italian prefLabel of EuroVoc concepts: graph, then local cache, then the EU endpoint."""

    def __init__(self, sp: Sparql, known: dict[str, str]):
        self.sp = sp
        self.labels = dict(known)
        if EUROVOC_CACHE.exists():
            with EUROVOC_CACHE.open(encoding="utf-8") as f:
                for row in csv.reader(f):
                    if len(row) >= 2 and row[1] and row[0] not in self.labels:
                        self.labels[row[0]] = row[1]
        self.disabled = False

    def resolve(self, uris: set[str]) -> None:
        missing = sorted(u for u in uris if u not in self.labels)
        for i in range(0, len(missing), 50):
            if self.disabled:
                return
            chunk = missing[i:i + 50]
            try:
                rows = self.sp.select(f"""
                    PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
                    SELECT ?a ?l WHERE {{ {_values(chunk)} ?a skos:prefLabel ?l FILTER(LANG(?l) = "it") }}
                """, endpoint=SPARQL_EUROVOC, timeout=30)
            except RuntimeError:
                logger.warning("EuroVoc endpoint down: new concepts stay without a subject link")
                self.disabled = True
                return
            for r in rows:
                self.labels[r["a"]] = r["l"]


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

def to_row(uri: str, d: dict, labels: dict[str, str]) -> Optional[dict]:
    is_bill = "/attocamera.rdf/" in uri
    type_raw = clean(d.get("type"))
    if is_bill:
        title = clean(d.get("title"))
        family, kind = bill_kind(d.get("nat"), title)
        initiative = camera_initiative(d.get("init"))
        if initiative is None:
            initiative = ("parlamentare" if any(not s["government"] for s in d["signers"])
                          else initiative_from_title(title))
        # dc:description of a bill only says which law it became
        description, law_raw = None, clean(d.get("descr"))
    else:
        fk = aic_kind(type_raw)
        if fk is None:
            logger.warning("unknown act type %r (%s): no family label", type_raw, uri)
            family, kind = None, None
        else:
            family, kind = fk
        initiative = None
        # Same normalisation as the old writer (unescape only), so unchanged
        # titles and descriptions keep their embeddings.
        title = html.unescape(d["title"]) if d.get("title") else None
        description = html.unescape(d["descr"]) if d.get("descr") else None
        law_raw = None
    return {
        "uri": uri,
        "family": family,
        "kind": kind,
        "type": type_raw,
        "title": title,
        "description": description,
        "law_raw": law_raw,
        "number": clean(d.get("id")),
        "date": iso_day(d.get("start")) or iso_day(d.get("date")),
        "initiative": initiative,
        "initiative_raw": clean(d.get("init")),
        "nature": (d.get("nat") or "").rsplit("/", 1)[-1] or None,
        "source_page": d.get("page"),
        "recipient": next((r for r in d["recipients"] if r), None),
        "modified": d.get("mod"),
        "concepts": [{"uri": u, "label": labels[u]} for u in sorted(set(d["eurovoc"]))
                     if labels.get(u) and u not in EUROVOC_MISMAPPED],
        "primary": sorted({s["persona"] for s in d["signers"] if s["role"] == "primo" and not s["government"]}),
        "co": sorted({s["persona"] for s in d["signers"] if s["role"] == "altro" and not s["government"]}),
        "presenters": sorted({(s["persona"], s.get("office") or "") for s in d["signers"] if s["government"]}),
    }


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

WRITE_ACT = """
UNWIND $rows AS row
MERGE (a:ParliamentaryAct {uri: row.uri})
WITH a, row,
     (a.title IS NOT NULL AND row.title IS NOT NULL AND a.title <> row.title) AS new_title,
     (a.description IS NOT NULL AND row.description IS NOT NULL AND a.description <> row.description) AS new_descr
SET a.chamber = 'camera', a.legislature = $leg,
    a.type = coalesce(row.type, a.type), a.type_raw = coalesce(row.type, a.type_raw),
    a.kind = coalesce(row.kind, a.kind),
    a.title = coalesce(row.title, a.title),
    a.title_embedding = CASE WHEN new_title THEN null ELSE a.title_embedding END,
    a.description = coalesce(row.description, a.description),
    a.description_embedding = CASE WHEN new_descr OR (new_title AND coalesce(a.description, '') = '')
                                   THEN null ELSE a.description_embedding END,
    a.law_raw = coalesce(row.law_raw, a.law_raw),
    a.number = coalesce(row.number, a.number),
    a.recipient = coalesce(row.recipient, a.recipient),
    a.initiative = coalesce(row.initiative, a.initiative),
    a.initiative_raw = coalesce(row.initiative_raw, a.initiative_raw),
    a.nature = coalesce(row.nature, a.nature),
    a.source_page = coalesce(row.source_page, a.source_page),
    a.source_modified = coalesce(row.modified, a.source_modified)
FOREACH (_ IN CASE WHEN row.date IS NULL THEN [] ELSE [1] END |
    SET a.presentation_date = date(row.date))
FOREACH (ev IN row.concepts |
    MERGE (c:EurovocConcept {uri: ev.uri}) ON CREATE SET c.label_it = ev.label
    MERGE (a)-[:HAS_SUBJECT]->(c))
"""

WRITE_SIGNERS = """
UNWIND $rows AS row
MATCH (a:ParliamentaryAct {uri: row.uri})
// camera_id, not Deputy.id: deputies in the Government have id 'gov_<name>'.
MATCH (p:Person {camera_id: row.persona})
FOREACH (_ IN CASE WHEN row.primary THEN [1] ELSE [] END | MERGE (p)-[:PRIMARY_SIGNATORY]->(a))
FOREACH (_ IN CASE WHEN row.primary THEN [] ELSE [1] END | MERGE (p)-[:CO_SIGNATORY]->(a))
RETURN count(*) AS n
"""

WRITE_PRESENTED = """
UNWIND $rows AS row
MATCH (a:ParliamentaryAct {uri: row.uri})
MATCH (p:Person {camera_id: row.persona})
MERGE (p)-[r:PRESENTED]->(a)
SET r.role = 'proponente', r.office = row.office
RETURN count(DISTINCT row) AS n
"""

WRITE_PRESENTED_BY = """
UNWIND $rows AS row
MATCH (a:ParliamentaryAct {uri: row.uri}) MATCH (g:Government {id: row.gov})
MERGE (a)-[:PRESENTED_BY]->(g)
"""


def government_on(governments: list[dict], day: Optional[str]) -> Optional[str]:
    if not day:
        return None
    for g in governments:
        if g["start"] and g["start"] <= day and (not g["end"] or day < g["end"]):
            return g["id"]
    return None


def write_block(session, rows: list[dict], leg: int, governments: list[dict], stats: Counter) -> None:
    session.run(WRITE_ACT, rows=rows, leg=leg).consume()
    by_family = defaultdict(list)
    for r in rows:
        if r["family"]:
            by_family[r["family"]].append(r["uri"])
    for family, uris in by_family.items():  # family comes from act_kinds.FAMILIES only
        session.run(f"UNWIND $uris AS u MATCH (a:ParliamentaryAct {{uri: u}}) SET a:{family}",
                    uris=uris).consume()
        stats[f"family_{family}"] += len(uris)

    signer_rows = [{"uri": r["uri"], "persona": p, "primary": True} for r in rows for p in r["primary"]]
    signer_rows += [{"uri": r["uri"], "persona": p, "primary": False} for r in rows for p in r["co"]]
    if signer_rows:
        n = session.run(WRITE_SIGNERS, rows=signer_rows).single()["n"]
        stats["signatures"] += n
        stats["signatures_unmatched"] += len(signer_rows) - n

    presenter_rows = [{"uri": r["uri"], "persona": p, "office": o or None}
                      for r in rows for p, o in r["presenters"]]
    if presenter_rows:
        n = session.run(WRITE_PRESENTED, rows=presenter_rows).single()["n"]
        stats["presented"] += n
        stats["presented_unmatched"] += len(presenter_rows) - n

    by_gov = []
    for r in rows:
        if r["initiative"] in ("governo", "mista") and (r["presenters"] or r["initiative"] == "governo"):
            gov = government_on(governments, r["date"])
            if gov:
                by_gov.append({"uri": r["uri"], "gov": gov})
            else:
                stats["government_bill_no_government"] += 1
    if by_gov:
        session.run(WRITE_PRESENTED_BY, rows=by_gov).consume()
        stats["presented_by_government"] += len(by_gov)


def read_meta(session) -> Optional[str]:
    rec = session.run(f"MATCH (m:SchemaMeta {{id: 'singleton'}}) RETURN m.{META_KEY} AS v").single()
    return rec["v"] if rec else None


def since_from_meta(value: Optional[str]) -> Optional[str]:
    """One day before the newest ods:modified of the previous run, as xsd:dateTime."""
    if not value:
        return None
    try:
        prev = datetime.fromisoformat(value.replace(" ", "T")[:19])
    except ValueError:
        return None
    return (prev - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--classes", default="atto,aic")
    ap.add_argument("--since", help="xsd:dateTime: only acts with ods:modified after it")
    ap.add_argument("--since-meta", action="store_true",
                    help="start from the newest ods:modified seen by the previous run")
    ap.add_argument("--uris", help="comma-separated act URIs (test a few acts)")
    ap.add_argument("--limit", type=int, help="first N acts per class (test run)")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between SPARQL calls")
    ap.add_argument("--dry-run", action="store_true", help="read the source, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD non impostata")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    sp = Sparql(args.delay)
    stats: Counter = Counter()
    newest = ""
    try:
        with driver.session() as session:
            since = args.since
            if args.since_meta and not since:
                since = since_from_meta(read_meta(session))
            logger.info("Atti Camera leg %d, %s", args.leg,
                        f"modificati dopo {since}" if since else "passata completa")
            governments = [dict(r) for r in session.run("""
                MATCH (g:Government) RETURN g.id AS id, toString(g.start_date) AS start,
                       toString(g.end_date) AS end ORDER BY g.start_date""")]
            known = {r["u"]: r["l"] for r in session.run(
                "MATCH (c:EurovocConcept) WHERE c.label_it IS NOT NULL RETURN c.uri AS u, c.label_it AS l")}
            eurovoc = EurovocLabels(sp, known)

            for cls in args.classes.split(","):
                if args.uris:
                    listed = {u: "" for u in args.uris.split(",")
                              if ("/attocamera.rdf/" in u) == (cls == "atto")}
                else:
                    listed = list_acts(sp, cls, args.leg, since)
                uris = sorted(listed)[: args.limit] if args.limit else sorted(listed)
                logger.info("%s: %d atti da leggere", cls, len(uris))
                block = CLASSES[cls][1]
                for i in range(0, len(uris), block):
                    details = fetch_details(sp, uris[i:i + block])
                    eurovoc.resolve({u for d in details.values() for u in d["eurovoc"]})
                    rows = [r for u, d in details.items() if (r := to_row(u, d, eurovoc.labels))]
                    stats[f"{cls}_read"] += len(rows)
                    stats["no_title"] += sum(1 for r in rows if not r["title"])
                    for r in rows:
                        if r["family"] == "Bill":
                            stats[f"initiative_{r['initiative']}"] += 1
                        newest = max(newest, r["modified"] or "")
                    if not args.dry_run:
                        write_block(session, rows, args.leg, governments, stats)
                    logger.info("  %s %d/%d (SPARQL: %d chiamate)", cls, min(i + block, len(uris)),
                                len(uris), sp.calls)

            if not args.dry_run and newest and not (args.uris or args.limit):
                prev = read_meta(session) or ""
                if newest > prev:
                    session.run(f"MERGE (m:SchemaMeta {{id: 'singleton'}}) SET m.{META_KEY} = $v",
                                v=newest).consume()
    finally:
        driver.close()

    for k in sorted(stats):
        if stats[k]:
            logger.info("%s: %d", k, stats[k])
    if stats["signatures_unmatched"]:
        logger.info("firme senza deputato nel grafo (ex deputati): %d", stats["signatures_unmatched"])


if __name__ == "__main__":
    main()
