#!/usr/bin/env python3
"""
Rapporteurs (relatori) of the bills of both chambers.

  (:Bill)-[:REPORTED_BY {role, roles_raw, date, venues, committee, source}]->(:Person)

One relationship per bill and person. role is the strongest standing the
person had on the bill: minoranza > maggioranza > relatore > facente_funzione
> sostituto. A plain "relatore" is the only rapporteur, so he speaks for the
committee majority, as the transcripts' "Relatore" label does.

Camera (dati.camera.it, one SPARQL query per field): ocd:rif_relatore of each
ocd:atto, with dc:type "maggioranza"/"minoranza" or none. The record names
the deputy only in its label ("SCHIFONE Marta, relatore per la maggioranza"),
matched to the XIX deputies by surname and first name; no nomination date.
committee is the committee the bill was assigned to in sede referente.

Senato (dati.senato.it, one query, cached in data/senato_{roman}_relatori.csv):
osr:relatore of each Ddl of the Senate branch, with the senator's URI,
tipoRelatore (relatore, facente funzione, sostituto), diMinoranza, organo
(commissione, assemblea) and dataNomina; date is the first nomination.
Exit 3 = dati.senato.it refused the request.

Idempotent: MERGE on (bill, person), SET of values from the source.

    python build/ingest_reporters.py --neo4j-uri bolt://... --chamber camera|senato [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from typing import Optional

from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_acts_camera import VIRTUOSO_CAP, Sparql  # noqa: E402

logger = logging.getLogger("ingest_reporters")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "xviii", 19: "xix"}
LEG_URI = "<http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}>"

ROLE_RANK = {"minoranza": 5, "maggioranza": 4, "relatore": 3, "facente_funzione": 2, "sostituto": 1}

CAMERA_REPORTERS = """
SELECT DISTINCT ?a ?r ?label ?type WHERE {{
  ?a a ocd:atto ; ocd:rif_leg {leg} ; ocd:rif_relatore ?r .
  OPTIONAL {{ ?r rdfs:label ?label }} OPTIONAL {{ ?r dc:type ?type }}
}}"""

CAMERA_COMMITTEES = """
SELECT DISTINCT ?a ?committee WHERE {{
  ?a a ocd:atto ; ocd:rif_leg {leg} ; ocd:rif_relatore ?r ; ocd:rif_assegnazione ?as .
  ?as ocd:sede ?sede ; ocd:rif_organo ?o . ?o rdfs:label ?committee .
  FILTER(LCASE(STR(?sede)) = "referente")
}}"""

SENATE_REPORTERS = """PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?ddl ?sen ?label ?tipo ?min ?data ?organo WHERE {{
  ?ddl a osr:Ddl ; osr:legislatura {leg} ; osr:ramo ?ramo ; osr:relatore ?r .
  FILTER(str(?ramo) = "S")
  OPTIONAL {{ ?r osr:senatore ?sen }} OPTIONAL {{ ?r rdfs:label ?label }}
  OPTIONAL {{ ?r osr:tipoRelatore ?tipo }} OPTIONAL {{ ?r osr:diMinoranza ?min }}
  OPTIONAL {{ ?r osr:dataNomina ?data }} OPTIONAL {{ ?r osr:organo ?organo }}
}}"""

SENATE_FIELDS = ["ddl", "sen", "label", "tipo", "min", "data", "organo"]


def fold(text: Optional[str]) -> str:
    """Upper case, no accents, apostrophes and hyphens as spaces, single spaces."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"['’`\-.]", " ", t).split())


def split_camera_label(label: Optional[str]) -> Optional[tuple[str, str]]:
    """('SCHIFONE', 'MARTA') from 'SCHIFONE Marta, relatore per la maggioranza'.

    The surname is the run of upper-case words before the first name.
    """
    name = (label or "").split(",")[0].strip()
    words = name.split()
    i = 0
    while i < len(words) and words[i] == words[i].upper() and any(c.isalpha() for c in words[i]):
        i += 1
    if i == 0 or i == len(words):
        return None
    return fold(" ".join(words[:i])), fold(" ".join(words[i:]))


def match_deputy(name: tuple[str, str], deputies: dict[tuple[str, str], str]) -> Optional[str]:
    """Person id of a deputy from a folded (surname, first name); None when unknown or ambiguous.

    The registry and the rapporteur records disagree on second names, short
    first names and double surnames ("IEZZI Igor" is IEZZI IGOR GIANCARLO,
    "AMICH Enzo" AMICH VINCENZO, "SACCANI JOTTI Gloria" SACCANI GLORIA): a
    looser match is accepted only when it points to one deputy.
    """
    if name in deputies:
        return deputies[name]
    last, first = name
    same_surname = {pid for (cl, _), pid in deputies.items() if cl == last}
    if len(same_surname) == 1:
        return same_surname.pop()
    first_words = set(first.split())

    def compatible(cand_last: str, cand_first: str) -> bool:
        surname_ok = cand_last == last or (cand_last + " ").startswith(last + " ") \
            or (last + " ").startswith(cand_last + " ")
        return surname_ok and bool(first_words & set(cand_first.split()))

    found = {pid for (cl, cf), pid in deputies.items() if compatible(cl, cf)}
    return found.pop() if len(found) == 1 else None


def camera_role(rtype: Optional[str], label: Optional[str]) -> str:
    t = (rtype or "").strip().lower()
    if t in ("maggioranza", "minoranza"):
        return t
    low = (label or "").lower()
    if "minoranza" in low:
        return "minoranza"
    if "maggioranza" in low:
        return "maggioranza"
    return "relatore"


def senate_role(tipo: Optional[str], minority: Optional[str]) -> str:
    if (minority or "").strip() in ("1", "true"):
        return "minoranza"
    t = (tipo or "").strip().lower()
    if t.startswith("facente"):
        return "facente_funzione"
    if t.startswith("sostitut"):
        return "sostituto"
    return "relatore"


def merge_reports(records: list[dict]) -> list[dict]:
    """One row per (bill, person): strongest role, all raw roles, first date, venues."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        grouped[(r["bill"], r["person"])].append(r)
    out = []
    for (bill, person), rs in sorted(grouped.items()):
        roles = sorted({r["role"] for r in rs}, key=lambda x: -ROLE_RANK[x])
        dates = sorted(r["date"] for r in rs if r.get("date"))
        venues = sorted({r["venue"] for r in rs if r.get("venue")})
        committees = sorted({r["committee"] for r in rs if r.get("committee")})
        out.append({
            "bill": bill, "person": person, "role": roles[0], "roles_raw": roles,
            "date": dates[0] if dates else None, "venues": venues or None,
            "committee": "; ".join(committees) or None, "source": rs[0]["source"],
        })
    return out


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def camera_records(sp: Sparql, leg: int, deputies: dict[tuple[str, str], str],
                   bills: set[str], stats: Counter) -> list[dict]:
    rows = sp.select(CAMERA_REPORTERS.format(leg=LEG_URI.format(leg=leg)))
    if len(rows) >= VIRTUOSO_CAP:
        raise RuntimeError("relatori della Camera oltre il limite di righe: dividere la query")
    committees: dict[str, set[str]] = defaultdict(set)
    for r in sp.select(CAMERA_COMMITTEES.format(leg=LEG_URI.format(leg=leg))):
        committees[r["a"]].add(" ".join(r["committee"].split()))
    out = []
    for r in rows:
        stats["camera_source_rows"] += 1
        if r["a"] not in bills:
            stats["camera_bill_missing"] += 1
            continue
        name = split_camera_label(r.get("label"))
        person = match_deputy(name, deputies) if name else None
        if person and name not in deputies:
            stats["camera_loose_match"] += 1
            logger.info("relatore %r -> %s", r.get("label"), person)
        if not person:
            stats["camera_person_missing"] += 1
            logger.warning("relatore non trovato tra i deputati: %r (%s)", r.get("label"), r["a"])
            continue
        out.append({"bill": r["a"], "person": person, "role": camera_role(r.get("type"), r.get("label")),
                    "date": None, "venue": None,
                    "committee": "; ".join(sorted(committees.get(r["a"], ()))) or None,
                    "source": "dati.camera.it"})
    return out


# ---------------------------------------------------------------------------
# Senato
# ---------------------------------------------------------------------------

def download_senate(leg: int, path: str) -> list[dict]:
    from senate_sparql_ingester import _senato_sparql_get
    bindings = _senato_sparql_get(SENATE_REPORTERS.format(leg=leg), strict=True)
    if len(bindings) >= 10000:
        raise RuntimeError("relatori del Senato oltre il limite di righe: dividere la query")
    rows = [{k: b.get(k, {}).get("value", "") for k in SENATE_FIELDS} for b in bindings]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SENATE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    logger.info("%d righe -> %s", len(rows), os.path.basename(path))
    return rows


def senate_records(rows: list[dict], senators: dict[str, str], bills: set[str], stats: Counter) -> list[dict]:
    out = []
    for r in rows:
        stats["senato_source_rows"] += 1
        if r["ddl"] not in bills:
            stats["senato_bill_missing"] += 1
            continue
        person = senators.get(r.get("sen") or "")
        if not person:
            stats["senato_person_missing"] += 1
            logger.warning("relatore non trovato tra i senatori: %r (%s)", r.get("label"), r["ddl"])
            continue
        out.append({"bill": r["ddl"], "person": person, "role": senate_role(r.get("tipo"), r.get("min")),
                    "date": (r.get("data") or "")[:10] or None, "venue": r.get("organo") or None,
                    "committee": None, "source": "dati.senato.it"})
    return out


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

WRITE = """
UNWIND $rows AS row
MATCH (b:ParliamentaryAct {uri: row.bill}) WHERE b:Bill
MATCH (p:Person {id: row.person})
MERGE (b)-[r:REPORTED_BY]->(p)
SET r.role = row.role, r.roles_raw = row.roles_raw, r.venues = row.venues,
    r.committee = row.committee, r.source = row.source,
    r.date = CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--chamber", choices=("camera", "senato"), required=True)
    ap.add_argument("--cached", action="store_true", help="Senato: read the cached CSV, no request")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between Camera SPARQL calls")
    ap.add_argument("--dry-run", action="store_true", help="read the sources, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD non impostata")

    stats: Counter = Counter()
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        with driver.session() as session:
            bills = {r["uri"] for r in session.run(
                "MATCH (b:Bill {chamber: $c}) RETURN b.uri AS uri", c=args.chamber)}
            if args.chamber == "camera":
                deputies = {}
                for r in session.run("""
                        MATCH (p:Person) WHERE $m IN coalesce(p.mandates, [])
                        RETURN p.id AS id, p.last_name AS last, p.first_name AS first""",
                                     m=f"camera_{args.leg}"):
                    deputies[(fold(r["last"]), fold(r["first"]))] = r["id"]
                records = camera_records(Sparql(args.delay), args.leg, deputies, bills, stats)
            else:
                path = os.path.join(DATA_DIR, f"senato_{ROMAN.get(args.leg, args.leg)}_relatori.csv")
                if args.cached:
                    with open(path, encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))
                else:
                    from senate_sparql_ingester import SenateEndpointBlocked, SenateRequestFailed
                    try:
                        rows = download_senate(args.leg, path)
                    except (SenateEndpointBlocked, SenateRequestFailed) as exc:
                        logger.warning("dati.senato.it rifiuta la richiesta: %s", exc)
                        return 3
                senators = {r["sid"]: r["id"] for r in session.run(
                    "MATCH (p:Person) WHERE p.senato_id IS NOT NULL RETURN p.senato_id AS sid, p.id AS id")}
                records = senate_records(rows, senators, bills, stats)
            merged = merge_reports(records)
            stats["relationships"] = len(merged)
            stats["bills_with_reporter"] = len({m["bill"] for m in merged})
            for m in merged:
                stats[f"role_{m['role']}"] += 1
            if not args.dry_run:
                for i in range(0, len(merged), 1000):
                    session.run(WRITE, rows=merged[i:i + 1000]).consume()
    finally:
        driver.close()
    for k in sorted(stats):
        logger.info("%s: %d", k, stats[k])
    return 0


if __name__ == "__main__":
    sys.exit(main())
