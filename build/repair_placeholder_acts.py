"""
repair_placeholder_acts.py — resolve placeholder acts to their real record.

Debate ingest creates placeholder ParliamentaryAct nodes from the XML
"argomenti" (db_builder._create_act_links) whenever no act with the synthetic
URI exists — which is always, because SPARQL-enriched acts use the real
dati.camera.it URI. The real act often lands later (or already exists under a
different number format), leaving duplicates:

  - mozione:  placeholder number "1-00004"  vs real MOZIONE number "1/00004"
  - pdl:      placeholder number "5-A" (committee version) vs real
              "Progetto di Legge" number "5"; exact matches also occur
  - doc:      "Doc. IV-ter, n. 13-A" vs the document node camera:19:doc:IV-ter:13
              (ingest_documents.py); "Doc. XXII, nn. 11-14-16-A" stands for
              three documents and moves to each of them

This pass re-points every DISCUSSES (Debate) and CITES (Chunk) edge from the
placeholder to the matched real acts, then deletes the placeholder; a
document placeholder only when every document it names is a node. Idempotent:
it is wired into `make update-data`, so placeholders created by a new sitting
get resolved as soon as the real act arrives from SPARQL on a later run.

Usage:
    python build/repair_placeholder_acts.py [--neo4j-uri bolt://...] [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from doc_refs import doc_keys, doc_uri  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_resolution(session, legislature: int = 19) -> list[dict]:
    """Pair each placeholder with the real acts it stands for (if ingested)."""
    real_mozioni = {
        r["number"]: r["uri"]
        for r in session.run(
            # Senate motions share the numbering (1/00062): Chamber ones only.
            "MATCH (a:Motion {chamber: 'camera'}) "
            "WHERE a.isPlaceholder IS NULL RETURN a.number AS number, a.uri AS uri")
    }
    real_bills = {
        r["number"]: r["uri"]
        for r in session.run(
            "MATCH (a:Bill {chamber: 'camera'}) "
            "WHERE a.isPlaceholder IS NULL RETURN a.number AS number, a.uri AS uri")
    }
    documents = {r["uri"] for r in session.run(
        "MATCH (a:ParliamentaryDocument {chamber: 'camera'}) WHERE a.isPlaceholder IS NULL RETURN a.uri AS uri")}

    pairs = []
    for r in session.run(
        "MATCH (p:ParliamentaryAct {isPlaceholder: true}) "
        "RETURN p.uri AS uri, p.type AS type, p.number AS number"
    ):
        number = (r["number"] or "").strip()
        target = None
        if r["type"] == "mozione":
            # XML writes 1-00004, the SPARQL AIC dataset writes 1/00004
            target = real_mozioni.get(number.replace("-", "/"))
        elif r["type"] == "pdl":
            # Exact first, then the base bill for lettered/combined variants
            # (547-A and 547-548-A both belong to bill 547)
            target = real_bills.get(number) or real_bills.get(number.split("-")[0])
        elif r["type"] == "doc":
            # Only the Chamber's transcripts create document placeholders.
            uris = [doc_uri("camera", legislature, *k) for k in doc_keys(number)]
            if uris and all(u in documents for u in uris):
                pairs.append({"placeholder": r["uri"], "reals": uris})
            continue
        if target:
            pairs.append({"placeholder": r["uri"], "reals": [target]})
    return pairs


def apply(session, pairs: list[dict]) -> None:
    session.execute_write(lambda tx: tx.run(
        """
        UNWIND $pairs AS pair
        MATCH (p:ParliamentaryAct {uri: pair.placeholder})
        CALL {
            WITH p, pair
            UNWIND pair.reals AS uri
            MATCH (real:ParliamentaryAct {uri: uri})
            CALL {
                WITH p, real
                MATCH (d:Debate)-[:DISCUSSES]->(p)
                MERGE (d)-[:DISCUSSES]->(real)
            }
            CALL {
                WITH p, real
                MATCH (c:Chunk)-[:CITES]->(p)
                MERGE (c)-[:CITES]->(real)
            }
        }
        DETACH DELETE p
        """, pairs=pairs))


def main():
    parser = argparse.ArgumentParser(description="Resolve placeholder acts to real acts")
    parser.add_argument("--neo4j-uri", default=None)
    parser.add_argument("--neo4j-user", default=None)
    parser.add_argument("--neo4j-password", default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    load_dotenv(REPO_ROOT / ".env")
    uri = args.neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = args.neo4j_user or os.environ.get("NEO4J_USER", "neo4j")
    password = args.neo4j_password or os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    t0 = time.time()
    with driver.session() as session:
        before = {
            r["type"]: r["n"] for r in session.run(
                "MATCH (p:ParliamentaryAct {isPlaceholder: true}) "
                "RETURN p.type AS type, count(*) AS n")
        }
        pairs = build_resolution(session)
        print(f"{uri}: {sum(before.values())} placeholders {before} — "
              f"{len(pairs)} resolvable")
        if args.dry_run or not pairs:
            print("Nothing applied." if not pairs else "Dry run, nothing applied.")
        else:
            apply(session, pairs)
            after = {
                r["type"]: r["n"] for r in session.run(
                    "MATCH (p:ParliamentaryAct {isPlaceholder: true}) "
                    "RETURN p.type AS type, count(*) AS n")
            }
            print(f"Resolved {len(pairs)} placeholders in {time.time() - t0:.0f}s "
                  f"— remaining {sum(after.values())} {after}")
    driver.close()


if __name__ == "__main__":
    main()
