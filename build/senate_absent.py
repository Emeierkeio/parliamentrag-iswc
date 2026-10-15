#!/usr/bin/env python3
"""
Absent senators in the Senate roll calls, from the composition of the Senate.

  python build/senate_absent.py --neo4j-uri bolt://localhost:7692 [--legislature 19]

dati.senato.it names who voted for, against or abstained, and (when the
ingester asks for it) who was on leave or present without voting; it has no
"absent" predicate (audit 14/10/2026). The Camera graph has an IndividualVote
for every deputy, absent ones included, so the per-group bars of the two
chambers are only comparable if the Senate has them too.

For every Senate vote that has named votes, each senator in office on the day
(data/senatori_{roman}.csv, mandatoStart/mandatoEnd) with no IndividualVote
gets one with outcome 'absent'. The id is the one the ingester would give, so
a later run of senate_sparql_ingester.py that knows the reason (mission,
present_not_voting) sets it on the same node. Offline and idempotent.
"""

import argparse
import csv
import logging
import os
import sys
from collections import Counter
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sparql_ingester import individual_vote_id  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN = {18: "xviii", 19: "xix"}

# Votes with named votes; secret ballots and quorum checks without names
# have none, and absences there would be invented.
READ_VOTES = """
MATCH (s:Session {chamber: 'senato', legislature: $leg})-[:HAS_VOTE]->(v:Vote)
WHERE EXISTS { (v)<-[:ON_VOTE]-(:IndividualVote) }
RETURN v.id AS id, s.number AS session, v.number AS vote, s.date AS date,
       [(v)<-[:ON_VOTE]-(:IndividualVote)<-[:VOTED]-(p:Person) | p.senato_id] AS voted
"""

WRITE_ABSENT = """
UNWIND $rows AS row
MATCH (p:Person {senato_id: row.senator})
MATCH (v:Vote {id: row.vote})
MERGE (iv:IndividualVote {id: row.id})
ON CREATE SET iv.outcome = 'absent'
MERGE (p)-[:VOTED]->(iv)
MERGE (iv)-[:ON_VOTE]->(v)
RETURN count(iv) AS n
"""


def load_mandates(path: str) -> list[tuple[str, date, date | None]]:
    """(senatore URI, start, end or None) from senatori_{roman}.csv."""
    def day(s: str) -> date | None:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8])) if len(s) == 8 else None

    with open(path, newline="", encoding="utf-8") as f:
        return [(r["senatore"], day(r["mandatoStart"]), day(r["mandatoEnd"]))
                for r in csv.DictReader(f) if day(r["mandatoStart"])]


def in_office(mandates, on: date) -> set[str]:
    return {uri for uri, start, end in mandates if start <= on and (end is None or on <= end)}


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Absent senators in the Senate roll calls")
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--dry-run", action="store_true", help="count only, write nothing")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    roman = ROMAN.get(args.legislature, f"leg{args.legislature}")
    mandates = load_mandates(os.path.join(REPO, "data", f"senatori_{roman}.csv"))

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    with driver.session() as s:
        known = {r["sid"] for r in s.run(
            "MATCH (p:Person) WHERE p.senato_id IS NOT NULL RETURN p.senato_id AS sid")}
        rows = []
        for v in s.run(READ_VOTES, leg=args.legislature):
            stats["votes"] += 1
            members = in_office(mandates, v["date"].to_native())
            voted = set(v["voted"])
            stats["voted_not_in_office"] += len(voted - members)
            for sen in sorted(members - voted):
                if sen not in known:
                    stats["senator_not_in_graph"] += 1
                    continue
                rows.append({
                    "senator": sen, "vote": v["id"],
                    "id": individual_vote_id("senato", args.legislature, sen.rsplit("/", 1)[-1],
                                             v["session"], v["vote"]),
                })
        stats["absent_rows"] = len(rows)
        if not args.dry_run:
            for i in range(0, len(rows), 5000):
                chunk = rows[i:i + 5000]
                s.execute_write(lambda tx, c=chunk: tx.run(WRITE_ABSENT, rows=c).consume())
    driver.close()
    for k, n in sorted(stats.items()):
        logger.info("%s: %d", k, n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
