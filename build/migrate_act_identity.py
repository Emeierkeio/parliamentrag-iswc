#!/usr/bin/env python3
"""
Readings of a bill grouped into one legislative process (decision D2).

  (:Bill)-[:PART_OF {reading, chamber}]->(:LegislativeProcess {id, legislature, title})
  (:Bill)-[:NEXT_READING]->(:Bill)

Each reading stays a Bill with its official URI. The process comes from the
Senate's osr:Ddl phases sharing an idDdl (data/senato_{roman}_ddl.csv, written
by download_senate_ddl.py): the Senate lists the Chamber's readings too (ramo
C, numeroFase = the Chamber number), so one iter holds C.107, S.816, C.107-B.
Chamber bills the Senate does not list get a process of their own, keyed by
the base number. Readings are ordered by presentation date. No network;
idempotent.

    python build/migrate_act_identity.py --neo4j-uri bolt://... [--dry-run]
"""

import argparse
import csv
import logging
import os
import sys
from collections import Counter, defaultdict

logger = logging.getLogger("migrate_act_identity")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN = {18: "xviii", 19: "xix"}
CAMERA_BILL = "http://dati.camera.it/ocd/attocamera.rdf/ac{leg}_{number}"


def processes(phases: list[dict], leg: int, camera_bills: dict[str, str],
              senate_bills: set[str]) -> list[dict]:
    """One row per reading: process id, act URI, reading number, chamber.

    camera_bills: Chamber bill URI -> number, as in the graph; senate_bills:
    Senate bill URIs in the graph. Phases whose act is not in the graph are
    left out, and so are processes left with no reading.
    """
    by_iter: dict[str, list[dict]] = defaultdict(list)
    for p in phases:
        if p["ramo"] == "S":
            uri = p["ddl"] if p["ddl"] in senate_bills else None
        else:
            uri = CAMERA_BILL.format(leg=leg, number=p["numero"])
            uri = uri if uri in camera_bills else None
        if uri:
            by_iter[f"senato:{leg}:iter:{p['idDdl']}"].append(
                {"uri": uri, "date": p["dataPresentazione"] or "", "number": p["numero"],
                 "chamber": "senato" if p["ramo"] == "S" else "camera", "title": p["titolo"]})
    covered = {r["uri"] for rs in by_iter.values() for r in rs}
    for uri, number in camera_bills.items():
        if uri not in covered:
            base = number.split("-")[0]
            by_iter[f"camera:{leg}:ac:{base}"].append(
                {"uri": uri, "date": "", "number": number, "chamber": "camera", "title": None})
    rows = []
    for pid, readings in by_iter.items():
        readings.sort(key=lambda r: (r["date"], r["number"]))
        title = next((r["title"] for r in readings if r["title"]), None)
        for i, r in enumerate(readings, 1):
            rows.append({"process": pid, "uri": r["uri"], "reading": i, "chamber": r["chamber"],
                         "title": title,
                         "next": readings[i]["uri"] if i < len(readings) else None})
    return rows


WRITE = """
UNWIND $rows AS row
MERGE (lp:LegislativeProcess {id: row.process})
SET lp.legislature = $leg, lp.title = coalesce(row.title, lp.title)
WITH lp, row
MATCH (a:ParliamentaryAct {uri: row.uri})
OPTIONAL MATCH (a)-[old:PART_OF]->(other:LegislativeProcess) WHERE other <> lp
DELETE old
MERGE (a)-[r:PART_OF]->(lp)
SET r.reading = row.reading, r.chamber = row.chamber
WITH a, row
OPTIONAL MATCH (a)-[n:NEXT_READING]->(x) WHERE x.uri <> coalesce(row.next, '')
DELETE n
WITH a, row WHERE row.next IS NOT NULL
MATCH (b:ParliamentaryAct {uri: row.next})
MERGE (a)-[:NEXT_READING]->(b)
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Legislative processes of the bills")
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    leg = args.legislature
    path = os.path.join(REPO, "data", f"senato_{ROMAN[leg]}_ddl.csv")
    phases = list(csv.DictReader(open(path, encoding="utf-8")))
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session() as s:
        camera_bills = {r["uri"]: r["number"] for r in s.run(
            "MATCH (a:Bill {chamber: 'camera'}) WHERE a.uri STARTS WITH $p AND a.number IS NOT NULL "
            "RETURN a.uri AS uri, a.number AS number", p=CAMERA_BILL.format(leg=leg, number=""))}
        senate_bills = {r["uri"] for r in s.run(
            "MATCH (a:Bill {chamber: 'senato', legislature: $leg}) RETURN a.uri AS uri", leg=leg)}
        rows = processes(phases, leg, camera_bills, senate_bills)
        stats = Counter(r["chamber"] for r in rows)
        sizes = Counter(Counter(r["process"] for r in rows).values())
        if not args.dry_run:
            for i in range(0, len(rows), 2000):
                s.run(WRITE, rows=rows[i:i + 2000], leg=leg).consume()
    driver.close()
    logger.info("%d phases in %s; graph: %d Chamber bills, %d Senate bills",
                len(phases), os.path.basename(path), len(camera_bills), len(senate_bills))
    logger.info("readings linked: %s%s", dict(stats), " (dry run)" if args.dry_run else "")
    logger.info("processes by number of readings: %s", dict(sorted(sizes.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
