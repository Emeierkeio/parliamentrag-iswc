#!/usr/bin/env python3
"""
Committees the bills of a legislature are assigned to, from the open data of both chambers.

  (:Bill)-[:ASSIGNED_TO {sede, mode, date, joint, source}]->(:Committee)

sede is "referente" for the committee that examines the bill and
"consultiva" for the ones that give an opinion. mode is the venue of the
examining committee as the source names it: "referente" at the Chamber,
"referente", "redigente" or "deliberante" at the Senate (the latest one when
the bill moved from one to another). date is the first assignment, joint is
true for bills assigned to joint committees ("Commissioni riunite"), which
get one edge per committee.

Camera (dati.camera.it, one query per year of assignment): ocd:rif_assegnazione
of each ocd:atto, with ocd:sede, dc:date and the committee in ocd:rif_organo.
The source records only the sede referente.

Senato (dati.senato.it, one query per year of assignment, copy in
data/senato_{roman}_assegnazioni.csv): osr:assegnazione of each Ddl of the
Senate branch, with osr:tipoCommissione (primaria, consultiva), osr:sede,
osr:dataAssegnazione and osr:organo. The label names the committee by number
("10&ordf; (Sanità e lavoro)"); the joint ones list the numbers of all and
point to each one with osr:organo, so the number of an organo comes from
its single-committee assignments. Exit 3 = dati.senato.it refused the request.

Committees are matched by name to the :Committee nodes of the chamber: the
Chamber's labels are the node names, the Senate's numbers the "Nª Commissione
permanente" ones. Bills are matched by URI.

Incremental and additive: only new or changed edges are written (MERGE on
bill, committee and sede); an edge the source no longer gives is counted and
logged, never deleted.

    python build/ingest_bill_committees.py --neo4j-uri bolt://... --chamber camera|senato|both [--cached] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import html
import logging
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from typing import Optional

from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_acts_camera import VIRTUOSO_CAP, Sparql, iso_day  # noqa: E402

logger = logging.getLogger("ingest_bill_committees")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "xviii", 19: "xix"}
LEG_URI = "<http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}>"
FIRST_YEAR = {18: 2018, 19: 2022}
BATCH = 500

CAMERA_ASSIGNMENTS = """
SELECT DISTINCT ?a ?as ?sede ?date ?title ?committee WHERE {{
  ?a a ocd:atto ; ocd:rif_leg {leg} ; ocd:rif_assegnazione ?as .
  ?as ocd:sede ?sede ; ocd:rif_organo ?o ; dc:date ?date .
  ?o rdfs:label ?committee .
  OPTIONAL {{ ?as dc:title ?title }}
  FILTER(STRSTARTS(STR(?date), "{year}"))
}}"""

SENATE_ASSIGNMENTS = """PREFIX osr: <http://dati.senato.it/osr/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT ?ddl ?tipo ?sede ?label ?organo ?data WHERE {{
  ?ddl a osr:Ddl ; osr:legislatura {leg} ; osr:ramo ?ramo ; osr:assegnazione ?as .
  FILTER(str(?ramo) = "S")
  ?as osr:tipoCommissione ?tipo ; rdfs:label ?label ; osr:dataAssegnazione ?data .
  FILTER(STRSTARTS(STR(?data), "{year}"))
  OPTIONAL {{ ?as osr:sede ?sede }} OPTIONAL {{ ?as osr:organo ?organo }}
}}"""

SENATE_FIELDS = ["ddl", "tipo", "sede", "label", "organo", "data"]

_SENATE_NUMBER = re.compile(r"^\s*(\d+)\s*ª")
_GRAPH_SENATE_NUMBER = re.compile(r"^(\d+)ª Commissione permanente\b")


def fold(text: Optional[str]) -> str:
    """Upper case, no accents, apostrophes as spaces, single spaces."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"['’`]", " ", t).split())


def senate_label(label: Optional[str]) -> str:
    """'10ª (Sanità e lavoro)' from '10&ordf; (Sanità e lavoro)', whitespace collapsed."""
    return " ".join(html.unescape(label or "").split())


def senate_number(label: Optional[str]) -> Optional[int]:
    """Committee number of a single-committee Senate label; None for joint or unnumbered ones."""
    text = senate_label(label)
    if text.lower().startswith("commissioni riunite"):
        return None
    m = _SENATE_NUMBER.match(text)
    return int(m.group(1)) if m else None


def is_joint(text: Optional[str]) -> bool:
    return "riunite" in (text or "").lower()


# ---------------------------------------------------------------------------
# Committees in the graph
# ---------------------------------------------------------------------------

class CommitteeIndex:
    """Resolve source committee names to (chamber, name) of the :Committee nodes."""

    def __init__(self, committees: list[dict]):
        self.by_fold: dict[tuple[str, str], tuple[str, str]] = {}
        self.senate_by_number: dict[int, tuple[str, str]] = {}
        self.folds: list[tuple[str, tuple[str, str]]] = []
        for c in committees:
            key = (c["chamber"], c["name"])
            self.by_fold[(c["chamber"], fold(c["name"]))] = key
            self.folds.append((fold(c["name"]), key))
            m = _GRAPH_SENATE_NUMBER.match(c["name"]) if c["chamber"] == "senato" else None
            if m:
                self.senate_by_number[int(m.group(1))] = key

    def camera(self, label: str) -> Optional[tuple[str, str]]:
        return self.by_fold.get(("camera", fold(label)))

    def senate(self, number: Optional[int], label: str) -> Optional[tuple[str, str]]:
        """By number for the permanent committees, else the one node whose name contains the label."""
        if number is not None:
            return self.senate_by_number.get(number)
        f = fold(senate_label(label))
        if not f:
            return None
        found = {key for name, key in self.folds if key[0] in ("senato", "bicamerale") and f in name}
        return found.pop() if len(found) == 1 else None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def download_camera(sp: Sparql, leg: int) -> list[dict]:
    rows = []
    for year in range(FIRST_YEAR.get(leg, 2000), datetime.now().year + 1):
        part = sp.select(CAMERA_ASSIGNMENTS.format(leg=LEG_URI.format(leg=leg), year=year))
        if len(part) >= VIRTUOSO_CAP:
            raise RuntimeError(f"assegnazioni della Camera {year} oltre il limite di righe: dividere la query")
        rows += part
    return rows


def camera_records(rows: list[dict], index: CommitteeIndex, bills: set[str], stats: Counter) -> list[dict]:
    out = []
    for r in rows:
        stats["camera_source_rows"] += 1
        if (r.get("sede") or "").strip().lower() != "referente":
            stats["camera_other_sede"] += 1
            continue
        if r["a"] not in bills:
            stats["camera_bill_missing"] += 1
            continue
        committee = index.camera(r["committee"])
        if not committee:
            stats["camera_committee_unresolved"] += 1
            logger.warning("commissione della Camera non trovata: %r (%s)", r["committee"], r["a"])
            continue
        out.append({"bill": r["a"], "chamber": committee[0], "committee": committee[1], "sede": "referente",
                    "mode": "referente", "date": iso_day(r.get("date")), "joint": is_joint(r.get("title")),
                    "source": "dati.camera.it"})
    return out


def download_senate(leg: int, path: str) -> list[dict]:
    from senate_sparql_ingester import _senato_sparql_get
    rows = []
    for year in range(FIRST_YEAR.get(leg, 2000), datetime.now().year + 1):
        bindings = _senato_sparql_get(SENATE_ASSIGNMENTS.format(leg=leg, year=year), strict=True)
        if len(bindings) >= 10000:
            raise RuntimeError(f"assegnazioni del Senato {year} oltre il limite di righe: dividere la query")
        rows += [{k: b.get(k, {}).get("value", "") for k in SENATE_FIELDS} for b in bindings]
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SENATE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    logger.info("%d righe -> %s", len(rows), os.path.basename(path))
    return rows


def senate_organ_numbers(rows: list[dict]) -> dict[str, int]:
    """Committee number of each osr:organo, from its single-committee assignments."""
    seen: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        n = senate_number(r.get("label"))
        if n is not None and r.get("organo"):
            seen[r["organo"]][n] += 1
    return {organ: c.most_common(1)[0][0] for organ, c in seen.items()}


def senate_records(rows: list[dict], index: CommitteeIndex, bills: set[str], stats: Counter) -> list[dict]:
    organs = senate_organ_numbers(rows)
    out = []
    for r in rows:
        stats["senato_source_rows"] += 1
        if r["ddl"] not in bills:
            stats["senato_bill_missing"] += 1
            continue
        tipo = (r.get("tipo") or "").strip().lower()
        if tipo not in ("primaria", "consultiva"):
            stats["senato_other_tipo"] += 1
            continue
        number = organs.get(r.get("organo") or "")
        if number is None:
            number = senate_number(r.get("label"))
        committee = index.senate(number, r.get("label") or "")
        if not committee:
            stats[f"senato_committee_unresolved_{tipo}"] += 1
            logger.info("commissione del Senato non trovata: %r (%s)", senate_label(r.get("label")), r["ddl"])
            continue
        primary = tipo == "primaria"
        out.append({"bill": r["ddl"], "chamber": committee[0], "committee": committee[1],
                    "sede": "referente" if primary else "consultiva",
                    "mode": ((r.get("sede") or "").strip().lower() or None) if primary else None,
                    "date": (r.get("data") or "")[:10] or None,
                    "joint": primary and is_joint(r.get("label")), "source": "dati.senato.it"})
    return out


def merge_assignments(records: list[dict]) -> list[dict]:
    """One row per (bill, committee, sede): first date, mode of the latest assignment, joint if any is."""
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        grouped[(r["bill"], r["chamber"], r["committee"], r["sede"])].append(r)
    out = []
    for (bill, chamber, committee, sede), rs in sorted(grouped.items()):
        rs = sorted(rs, key=lambda r: r["date"] or "")
        dates = [r["date"] for r in rs if r["date"]]
        modes = [r["mode"] for r in rs if r["mode"]]
        out.append({"bill": bill, "chamber": chamber, "committee": committee, "sede": sede,
                    "mode": modes[-1] if modes else None, "date": dates[0] if dates else None,
                    "joint": any(r["joint"] for r in rs), "source": rs[0]["source"]})
    return out


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

EXISTING = """
MATCH (b:Bill {chamber: $chamber})-[r:ASSIGNED_TO]->(c:Committee)
WHERE r.source = $source
RETURN b.uri AS bill, c.chamber AS chamber, c.name AS committee, r.sede AS sede, r.mode AS mode,
       toString(r.date) AS date, r.joint AS joint
"""

WRITE = """
UNWIND $rows AS row
MATCH (b:ParliamentaryAct {uri: row.bill}) WHERE b:Bill
MATCH (c:Committee {chamber: row.chamber, name: row.committee})
MERGE (b)-[r:ASSIGNED_TO {sede: row.sede}]->(c)
SET r.mode = row.mode, r.joint = row.joint, r.source = row.source,
    r.date = CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END
"""

_FIELDS = ("mode", "date", "joint")


def _key(r: dict) -> tuple:
    return r["bill"], r["chamber"], r["committee"], r["sede"]


def plan_writes(merged: list[dict], existing: list[dict]) -> tuple[list[dict], list[dict]]:
    """(rows to write, edges in the graph that the source no longer gives)."""
    have = {_key(e): e for e in existing}
    todo = [m for m in merged if _key(m) not in have
            or any(have[_key(m)].get(f) != m[f] for f in _FIELDS)]
    given = {_key(m) for m in merged}
    stale = [e for k, e in have.items() if k not in given]
    return todo, stale


def write_rows(driver, rows: list[dict]) -> None:
    for i in range(0, len(rows), BATCH):
        with driver.session() as session:
            session.execute_write(lambda tx, chunk=rows[i:i + BATCH]: tx.run(WRITE, rows=chunk).consume())


def run_chamber(driver, chamber: str, args, stats: Counter) -> int:
    with driver.session() as session:
        bills = {r["uri"] for r in session.run(
            "MATCH (b:Bill {chamber: $c}) WHERE coalesce(b.legislature, $leg) = $leg RETURN b.uri AS uri",
            c=chamber, leg=args.leg)}
        index = CommitteeIndex([dict(r) for r in session.run(
            "MATCH (c:Committee) WHERE c.name IS NOT NULL RETURN c.chamber AS chamber, c.name AS name")])
        source = "dati.camera.it" if chamber == "camera" else "dati.senato.it"
        existing = [dict(r) for r in session.run(EXISTING, chamber=chamber, source=source)]
    stats[f"{chamber}_bills_in_graph"] = len(bills)
    if chamber == "camera":
        records = camera_records(download_camera(Sparql(args.delay), args.leg), index, bills, stats)
    else:
        path = os.path.join(DATA_DIR, f"senato_{ROMAN.get(args.leg, args.leg)}_assegnazioni.csv")
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
        records = senate_records(rows, index, bills, stats)
    merged = merge_assignments(records)
    todo, stale = plan_writes(merged, existing)
    referente = {m["bill"] for m in merged if m["sede"] == "referente"}
    stats[f"{chamber}_relationships"] = len(merged)
    stats[f"{chamber}_relationships_referente"] = sum(1 for m in merged if m["sede"] == "referente")
    stats[f"{chamber}_relationships_consultiva"] = sum(1 for m in merged if m["sede"] == "consultiva")
    stats[f"{chamber}_bills_with_referente"] = len(referente)
    stats[f"{chamber}_bills_without_referente"] = len(bills - referente)
    stats[f"{chamber}_to_write"] = len(todo)
    stats[f"{chamber}_stale_in_graph"] = len(stale)
    for e in stale[:20]:
        logger.info("la fonte non dà più %s -> %s (%s)", e["bill"], e["committee"], e["sede"])
    if not args.dry_run and todo:
        write_rows(driver, todo)
        stats[f"{chamber}_written"] = len(todo)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--chamber", choices=("camera", "senato", "both"), required=True)
    ap.add_argument("--cached", action="store_true", help="Senato: read the cached CSV")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between Camera SPARQL calls")
    ap.add_argument("--dry-run", action="store_true", help="read the sources, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD non impostata")

    stats: Counter = Counter()
    status = 0
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password),
                                  notifications_min_severity="OFF")
    try:
        for chamber in (("camera", "senato") if args.chamber == "both" else (args.chamber,)):
            status = max(status, run_chamber(driver, chamber, args, stats))
    finally:
        driver.close()
    for k in sorted(stats):
        logger.info("%s: %d", k, stats[k])
    return status


if __name__ == "__main__":
    sys.exit(main())
