#!/usr/bin/env python3
"""
Copy the Senate roll-call votes of one legislature from a graph that has them
to one that does not, without querying dati.senato.it.

  python build/copy_senate_votes.py --from bolt://localhost:7692 --to bolt://localhost:7690

dati.senato.it blocks an IP after a few hundred SPARQL requests, and loading
a whole legislature from scratch takes about that many (14/10/2026: blocked
from two IPs in one night). The source graph got the same data from
senate_sparql_ingester.py, so this copies Vote, IndividualVote, HAS_VOTE,
ON_VOTE and VOTED as they are, plus the per-sitting senate_votes_checked
marker so that the nightly ingester only asks for what is new. Voters are
matched by senato_id, which survives the merge of senator-ministers with
their government node. Idempotent (MERGE by id).
"""

import argparse
import logging
import os
import sys
import time

from neo4j import GraphDatabase

logger = logging.getLogger(__name__)

READ_VOTES = """
MATCH (s:Session {chamber: 'senato', legislature: $term})-[:HAS_VOTE]->(v:Vote)
WHERE s.number IN $numbers
RETURN s.id AS session_id, s.senate_votes_checked AS checked, v.id AS id, properties(v) AS props
"""

READ_INDIVIDUAL = """
UNWIND $vote_ids AS vid
MATCH (v:Vote {id: vid})<-[:ON_VOTE]-(iv:IndividualVote)
OPTIONAL MATCH (p:Person)-[:VOTED]->(iv)
RETURN vid AS vote_id, iv.id AS id, iv.outcome AS outcome, p.senato_id AS senato_id, p.id AS person_id
"""

WRITE_VOTES = """
UNWIND $rows AS row
MATCH (s:Session {id: row.session_id})
MERGE (v:Vote {id: row.id})
SET v += row.props
MERGE (s)-[:HAS_VOTE]->(v)
"""

WRITE_INDIVIDUAL = """
UNWIND $rows AS row
MATCH (v:Vote {id: row.vote_id})
MERGE (iv:IndividualVote {id: row.id})
SET iv.outcome = row.outcome
MERGE (iv)-[:ON_VOTE]->(v)
WITH iv, row
OPTIONAL MATCH (bySenate:Person {senato_id: row.senato_id})
OPTIONAL MATCH (byId:Person {id: row.person_id})
WITH iv, coalesce(bySenate, byId) AS p
WHERE p IS NOT NULL
MERGE (p)-[:VOTED]->(iv)
"""

MARK_CHECKED = """
UNWIND $rows AS row
MATCH (s:Session {id: row.session_id})
SET s.senate_votes_checked = row.checked
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--from", dest="src", required=True)
    ap.add_argument("--to", dest="dst", required=True)
    ap.add_argument("--user", default="neo4j")
    ap.add_argument("--password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--term", type=int, default=19)
    ap.add_argument("--sessions-per-batch", type=int, default=5)
    args = ap.parse_args()

    src = GraphDatabase.driver(args.src, auth=(args.user, args.password))
    dst = GraphDatabase.driver(args.dst, auth=(args.user, args.password))
    with src.session() as s:
        numbers = sorted(r["n"] for r in s.run(
            "MATCH (x:Session {chamber: 'senato', legislature: $t}) RETURN x.number AS n", t=args.term))
    with dst.session() as s:
        present = {r["n"] for r in s.run(
            "MATCH (x:Session {chamber: 'senato', legislature: $t}) RETURN x.number AS n", t=args.term)}
    numbers = [n for n in numbers if n in present]
    logger.info("%d sittings in both graphs", len(numbers))

    n_votes = n_iv = 0
    start = time.time()
    for i in range(0, len(numbers), args.sessions_per_batch):
        batch = numbers[i:i + args.sessions_per_batch]
        with src.session() as s:
            votes = s.run(READ_VOTES, term=args.term, numbers=batch).data()
            individual = s.run(READ_INDIVIDUAL, vote_ids=[v["id"] for v in votes]).data()
        checked = {v["session_id"]: v["checked"] for v in votes if v["checked"] is not None}
        with dst.session() as s:
            s.execute_write(lambda tx: tx.run(WRITE_VOTES, rows=votes).consume())
            for j in range(0, len(individual), 5000):
                chunk = individual[j:j + 5000]
                s.execute_write(lambda tx, c=chunk: tx.run(WRITE_INDIVIDUAL, rows=c).consume())
            s.execute_write(lambda tx: tx.run(MARK_CHECKED, rows=[
                {"session_id": k, "checked": v} for k, v in checked.items()]).consume())
        n_votes += len(votes)
        n_iv += len(individual)
        logger.info("sittings %d-%d: %d votes, %d individual (%d / %d total, %.0fs)",
                    batch[0], batch[-1], len(votes), len(individual), n_votes, n_iv,
                    time.time() - start)
    src.close()
    dst.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
