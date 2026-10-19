"""
repair_vote_readings.py — votes of a later reading linked to the first one,
and EuroVoc subjects the Camera's provisional classification got wrong.

1. Readings. dati.camera.it links the roll calls on a bill's second reading
   (C.2822-B) to its first reading (ocd:rif_attoCamera → ac19_2822); the
   vote description names the reading voted ("PDL 2822-B - ARTICOLO 8").
   For every Camera vote whose description names a reading code (-B ... -H;
   "-A" is the committee text of the same reading) that differs from the
   linked act, and that the act reaches through NEXT_READING, the ON_ACT
   moves to that reading.

2. EuroVoc. Camera acts tagged with http://eurovoc.europa.eu/7816 ("regioni
   della Repubblica ceca") carry it from the provisional automatic
   classification, which means "Repubblica" there (the label aic.camera.it
   shows). None of them is about the Czech Republic (95 acts on 2026-10-19):
   the HAS_SUBJECT goes; ingest_acts_camera.py no longer writes it.

The backend already reads around both (timeline_service._later_readings,
search.EUROVOC_MISMATCHED); this fixes the graph, the RDF dump and the HF
export. The SPARQL ingest re-links votes of the last days to the first
reading: run this after it.

Usage:
    python build/repair_vote_readings.py --neo4j-uri bolt://... [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

EUROVOC_MISMAPPED = ["http://eurovoc.europa.eu/7816"]

READING_PAIRS = r"""
MATCH (s:Session)-[:HAS_VOTE]->(v:Vote)-[r:ON_ACT]->(a:ParliamentaryAct)
WHERE coalesce(s.chamber, 'camera') = 'camera' AND v.description IS NOT NULL
WITH v, r, a, [x IN apoc.text.regexGroups(v.description, '\\b(\\d+(?:-\\d+)*-[B-H])\\b') | x[1]] AS codes
WHERE size(codes) > 0 AND NOT a.number IN codes
MATCH (a)-[:NEXT_READING*1..4]->(b:ParliamentaryAct)
WHERE b.number IN codes
RETURN v.id AS vote, a.uri AS old, b.uri AS new, a.number AS old_number, b.number AS new_number
"""

MOVE_READINGS = """
UNWIND $rows AS row
MATCH (v:Vote {id: row.vote})-[r:ON_ACT]->(:ParliamentaryAct {uri: row.old})
MATCH (b:ParliamentaryAct {uri: row.new})
MERGE (v)-[n:ON_ACT]->(b)
SET n += properties(r)
DELETE r
RETURN count(*) AS n
"""

EUROVOC_EDGES = """
MATCH (a:ParliamentaryAct)-[r:HAS_SUBJECT]->(c:EurovocConcept)
WHERE c.uri IN $uris AND coalesce(a.chamber, 'camera') = 'camera'
RETURN a.uri AS act, c.uri AS concept, c.label_it AS label
"""

DROP_EUROVOC = """
MATCH (a:ParliamentaryAct)-[r:HAS_SUBJECT]->(c:EurovocConcept)
WHERE c.uri IN $uris AND coalesce(a.chamber, 'camera') = 'camera'
DELETE r
RETURN count(*) AS n
"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--neo4j-uri", default=None)
    parser.add_argument("--neo4j-user", default=None)
    parser.add_argument("--neo4j-password", default=None)
    parser.add_argument("--dry-run", action="store_true", help="read only: print what would change")
    args = parser.parse_args()

    from dotenv import load_dotenv
    from neo4j import READ_ACCESS, WRITE_ACCESS, GraphDatabase

    load_dotenv(REPO_ROOT / ".env")
    uri = args.neo4j_uri or os.environ.get("NEO4J_URI")
    if not uri:
        sys.exit("--neo4j-uri or NEO4J_URI required")
    password = args.neo4j_password or os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set")
    driver = GraphDatabase.driver(uri, auth=(args.neo4j_user or os.environ.get("NEO4J_USER", "neo4j"), password))
    mode = READ_ACCESS if args.dry_run else WRITE_ACCESS
    with driver.session(default_access_mode=mode) as session:
        pairs = [dict(r) for r in session.run(READING_PAIRS)]
        edges = [dict(r) for r in session.run(EUROVOC_EDGES, uris=EUROVOC_MISMAPPED)]
        moves: dict[tuple, int] = {}
        for p in pairs:
            key = (p["old_number"], p["new_number"])
            moves[key] = moves.get(key, 0) + 1
        print(f"{uri}: {len(pairs)} votes linked to an earlier reading")
        for (old, new), n in sorted(moves.items()):
            print(f"  ON_ACT C.{old} -> C.{new}: {n} votes")
        print(f"{len(edges)} HAS_SUBJECT to {', '.join(EUROVOC_MISMAPPED)} on Camera acts"
              + (f" ({edges[0]['label']})" if edges else ""))
        if args.dry_run:
            print("Dry run, nothing written.")
        else:
            moved = session.run(MOVE_READINGS, rows=pairs).single()["n"] if pairs else 0
            dropped = session.run(DROP_EUROVOC, uris=EUROVOC_MISMAPPED).single()["n"]
            print(f"Moved {moved} ON_ACT, dropped {dropped} HAS_SUBJECT.")
    driver.close()


if __name__ == "__main__":
    main()
