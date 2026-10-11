"""
repair_bills.py — presentation dates and topic embeddings for Chamber bills.

Bills (ocd:atto) publish their date in dc:date, while the acts ingest used to
read only ocd:startDate, so every "Progetto di Legge" node was left without
presentation_date and the authority ActsComponent skipped them. The ingest
now reads both; this pass fills the nodes created before the fix and any
bill whose date was published after it was ingested.

Bills also have an empty dc:description, so they never got a
description_embedding and the ActsComponent scored them with the neutral
0.5 relevance on every query. Their title states the subject of the law, so
its embedding is copied into description_embedding.

Idempotent: only fills values that are missing.

Usage:
    python build/repair_bills.py [--neo4j-uri bolt://...] [--dry-run]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import requests
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
SPARQL_CAMERA = "https://dati.camera.it/sparql"

QUERY = """
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT DISTINCT ?atto ?data WHERE {{
  ?atto a ocd:atto ;
        ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}> ;
        dc:date ?data .
}}
"""


def fetch_dates(leg: int) -> list[dict]:
    r = requests.get(SPARQL_CAMERA, params={"query": QUERY.format(leg=leg)},
                     headers={"Accept": "application/sparql-results+json"}, timeout=300)
    r.raise_for_status()
    rows = {}
    for b in r.json()["results"]["bindings"]:
        raw = b["data"]["value"].strip()
        if len(raw) == 8 and raw.isdigit():
            iso = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
            uri = b["atto"]["value"]
            rows[uri] = min(rows.get(uri, iso), iso)
    return [{"uri": u, "iso": d} for u, d in rows.items()]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD non impostata")
    dates = fetch_dates(args.leg)
    print(f"{len(dates)} progetti di legge con data dal SPARQL Camera")

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(os.environ.get("NEO4J_USER", "neo4j"), password))
    with driver.session() as s:
        missing = s.run(
            "UNWIND $rows AS row MATCH (a:ParliamentaryAct {uri: row.uri}) "
            "WHERE a.presentation_date IS NULL RETURN count(a) AS n", rows=dates).single()["n"]
        print(f"Nodi senza data che verranno corretti: {missing}")
        if not args.dry_run and missing:
            updated = s.run(
                "UNWIND $rows AS row MATCH (a:ParliamentaryAct {uri: row.uri}) "
                "WHERE a.presentation_date IS NULL "
                "SET a.presentation_date = date(row.iso) RETURN count(a) AS n", rows=dates).single()["n"]
            print(f"Aggiornati: {updated}")
        left = s.run("MATCH (a:ParliamentaryAct {type: 'Progetto di Legge'}) "
                     "WHERE a.presentation_date IS NULL RETURN count(a) AS n").single()["n"]
        print(f"Progetti di legge ancora senza data: {left}")

        no_emb = ("MATCH (a:ParliamentaryAct {type: 'Progetto di Legge'}) "
                  "WHERE a.description_embedding IS NULL AND a.title_embedding IS NOT NULL ")
        todo = s.run(no_emb + "RETURN count(a) AS n").single()["n"]
        print(f"Progetti di legge senza embedding di descrizione (copio quello del titolo): {todo}")
        if not args.dry_run and todo:
            s.run(no_emb + "CALL { WITH a SET a.description_embedding = a.title_embedding } "
                  "IN TRANSACTIONS OF 500 ROWS")
        left = s.run("MATCH (a:ParliamentaryAct {type: 'Progetto di Legge'}) "
                     "WHERE a.description_embedding IS NULL RETURN count(a) AS n").single()["n"]
        print(f"Progetti di legge ancora senza embedding: {left}")
    driver.close()


if __name__ == "__main__":
    main()
