#!/usr/bin/env python3
"""
Re-derives the titles of Senate Debate and Phase nodes from the AKN files.

senate_parser.py used to take the printed <heading> as is: line breaks glued
words together ("costituzionalenn.") and many headings stop before the act
numbers ("... disegno di legge n."). debate_title() now falls back to the
section name. This script re-parses every sitting and updates the nodes whose
title (or Phase.phaseType) differs. Ids do not change.

Dry run by default; --apply writes.

    build/repair_senate_titles.py --neo4j-uri bolt://localhost:7692
    build/repair_senate_titles.py --neo4j-uri bolt://localhost:7690 --apply
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senate_parser import SenateStenograficoParser  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML_DIR = os.path.join(REPO, "data", "senate_xml")


def parsed_titles(xml_dir: str, legislature: int) -> tuple[dict, dict]:
    """{debate id: title}, {phase id: (title, phaseType)} from the AKN files."""
    parser = SenateStenograficoParser(legislature=legislature)
    debates: dict[str, str] = {}
    phases: dict[str, tuple[str, str]] = {}
    files = sorted(glob.glob(os.path.join(xml_dir, f"resaula_leg{legislature}_*.akn")))
    for path in files:
        try:
            parsed = parser.parse_xml_file(path)
        except Exception as exc:  # one broken file must not stop the others
            logger.warning("%s: %s", os.path.basename(path), exc)
            continue
        for d in parsed["debates"]:
            debates[d["id"]] = d["title"]
        for p in parsed["phases"]:
            phases[p["id"]] = (p["title"], p["phaseType"])
    logger.info("%d AKN files, %d debates, %d phases", len(files), len(debates), len(phases))
    return debates, phases


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    help="default: $NEO4J_PASSWORD")
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--xml-dir", default=XML_DIR)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    ap.add_argument("--show", type=int, default=10, help="examples to print")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD is required")
    from neo4j import GraphDatabase

    debates, phases = parsed_titles(args.xml_dir, args.legislature)
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session() as s:
        cur_d = {r["id"]: r["title"] for r in s.run(
            "MATCH (d:Debate) WHERE d.id IN $ids RETURN d.id AS id, d.title AS title",
            ids=list(debates))}
        cur_p = {r["id"]: (r["title"], r["type"]) for r in s.run(
            "MATCH (p:Phase) WHERE p.id IN $ids RETURN p.id AS id, p.title AS title, p.phaseType AS type",
            ids=list(phases))}

    d_rows = [{"id": i, "title": t} for i, t in debates.items() if i in cur_d and cur_d[i] != t]
    p_rows = [{"id": i, "title": t, "type": k} for i, (t, k) in phases.items()
              if i in cur_p and cur_p[i] != (t, k)]
    type_changes = sum(1 for r in p_rows if cur_p[r["id"]][1] != r["type"])
    print(f"Debate nel grafo: {len(cur_d)}/{len(debates)}; titoli da cambiare: {len(d_rows)}")
    print(f"Phase nel grafo: {len(cur_p)}/{len(phases)}; da cambiare: {len(p_rows)} "
          f"(di cui phaseType diverso: {type_changes})")
    for r in d_rows[:args.show]:
        print(f"  {cur_d[r['id']]!r}\n    -> {r['title']!r}")
    for r in [r for r in p_rows if cur_p[r["id"]][1] != r["type"]][:args.show]:
        print(f"  phaseType {cur_p[r['id']][1]} -> {r['type']}: {r['title'][:100]!r}")

    if not args.apply:
        print("Prova a secco: nessuna scrittura (--apply per scrivere).")
        driver.close()
        return 0
    with driver.session() as s:
        n_d = s.run("UNWIND $rows AS r MATCH (d:Debate {id: r.id}) SET d.title = r.title RETURN count(d) AS n",
                    rows=d_rows).single()["n"]
        n_p = s.run("UNWIND $rows AS r MATCH (p:Phase {id: r.id}) "
                    "SET p.title = r.title, p.phaseType = r.type RETURN count(p) AS n",
                    rows=p_rows).single()["n"]
    driver.close()
    print(f"Scritti: {n_d} Debate, {n_p} Phase.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
