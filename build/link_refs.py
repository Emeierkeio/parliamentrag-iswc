"""
link_refs.py — resolve NER references on chunks to graph entities.

Turns the raw NER strings stored at ingest time into typed relationships:
  - personRefs -> (Chunk)-[:MENTIONS]->(Person) (deputies and government members)
  - lawRefs "A.C. <n>" -> (Chunk)-[:CITES]->(ParliamentaryAct)

Resolution is deliberately conservative:
  - Person names match the roster (Deputy + GovernmentMember, both carry the
    Person label) by full name, or by surname only when that surname is unique
    in the roster; ambiguous surnames are skipped rather than guessed.
  - Act citations resolve only "A.C. <n>" references against Camera bill
    numbers ("Progetto di Legge"/"pdl"), exact number first, then the base
    number for lettered variants (547 matches 547-A). "A.S." (Senate) numbers
    stay unresolved: the graph only holds Camera acts.

Two entry points:
  - annotate_chunks(): used by db_builder during ingest — adds mentionIds and
    citesUris to chunk dicts before the batched write.
  - CLI backfill: re-runs the law regex on stored chunk text (older chunks
    were ingested before the A.C. pattern existed), refreshes c.lawRefs and
    creates the relationships for the whole DB. Idempotent (MERGE only).

    python build/link_refs.py [--neo4j-uri bolt://localhost:7690] [--batch-size 2000]
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from pathlib import Path

from ner import extract_law_refs

REPO_ROOT = Path(__file__).resolve().parent.parent

# Camera bill references: "A.C. 2505", "A.C. n. 547-A"
_AC_REF = re.compile(r'\bA\.\s?C\.\s*(?:n\.\s*)?(\d+(?:-[A-Z]+)?)')

# Act types whose `number` is a bare bill number comparable to an A.C. citation
BILL_TYPES = ("Progetto di Legge", "pdl")


class DeputyResolver:
    """Match NER person strings against the Person roster (deputies + gov. members)."""

    def __init__(self, deputies: list[dict]):
        # deputies: [{id, first_name, last_name}, ...]
        self._full: dict[str, str] = {}
        surname_count: dict[str, int] = {}
        surname_id: dict[str, str] = {}
        for d in deputies:
            first = (d.get("first_name") or "").strip().lower()
            last = (d.get("last_name") or "").strip().lower()
            if not last:
                continue
            self._full[f"{first} {last}"] = d["id"]
            self._full[f"{last} {first}"] = d["id"]
            surname_count[last] = surname_count.get(last, 0) + 1
            surname_id[last] = d["id"]
        self._surname = {
            ln: did for ln, did in surname_id.items() if surname_count[ln] == 1
        }

    def resolve(self, name: str) -> str | None:
        """Return the Person id for a NER person string, or None."""
        key = " ".join(name.strip().lower().split())
        if not key:
            return None
        if key in self._full:
            return self._full[key]
        # Whole ref as surname (covers "Della Vedova")
        if key in self._surname:
            return self._surname[key]
        # Last token as surname, only when unique in the roster
        last_tok = key.rsplit(" ", 1)[-1]
        return self._surname.get(last_tok)


def extract_ac_numbers(law_refs: list[str]) -> list[str]:
    """Camera bill numbers cited as A.C. in a list of law reference strings."""
    numbers = []
    for ref in law_refs:
        m = _AC_REF.search(ref)
        if m and m.group(1) not in numbers:
            numbers.append(m.group(1))
    return numbers


class ActIndex:
    """Map A.C. citation numbers to ParliamentaryAct URIs."""

    def __init__(self, acts: list[dict]):
        # acts: [{uri, number}, ...] — bill types only
        self._exact: dict[str, str] = {}
        self._base: dict[str, str] = {}
        for a in acts:
            num = (a.get("number") or "").strip()
            if not num:
                continue
            self._exact[num] = a["uri"]
            base = num.split("-")[0]
            # Prefer the unlettered act as base target (547 over 547-A)
            if base == num or base not in self._base:
                self._base.setdefault(base, a["uri"])
        for num, uri in self._exact.items():
            if "-" not in num:
                self._base[num] = uri

    def resolve(self, ac_number: str) -> str | None:
        return self._exact.get(ac_number) or self._base.get(ac_number.split("-")[0])


def load_resolver(session) -> DeputyResolver:
    rows = session.run(
        "MATCH (p:Person) RETURN p.id AS id, p.first_name AS first_name, "
        "p.last_name AS last_name"
    )
    return DeputyResolver([dict(r) for r in rows])


def load_act_index(session) -> ActIndex:
    rows = session.run(
        "MATCH (a:ParliamentaryAct) WHERE a.type IN $types "
        "RETURN a.uri AS uri, a.number AS number",
        types=list(BILL_TYPES),
    )
    return ActIndex([dict(r) for r in rows])


def annotate_chunks(chunks: list[dict], resolver: DeputyResolver, act_index: ActIndex) -> None:
    """Add mentionIds / citesUris to chunk dicts (in-place), from their NER fields."""
    for chunk in chunks:
        mention_ids = []
        for name in chunk.get("personRefs") or []:
            did = resolver.resolve(name)
            if did and did not in mention_ids:
                mention_ids.append(did)
        chunk["mentionIds"] = mention_ids

        cites = []
        for num in extract_ac_numbers(chunk.get("lawRefs") or []):
            uri = act_index.resolve(num)
            if uri and uri not in cites:
                cites.append(uri)
        chunk["citesUris"] = cites


def write_links(session, chunks: list[dict], refresh_law_refs: bool = False) -> tuple[int, int]:
    """Batched MERGE of MENTIONS/CITES for annotated chunk dicts."""
    mentions = [
        {"cid": c["id"], "did": did}
        for c in chunks for did in c.get("mentionIds") or []
    ]
    cites = [
        {"cid": c["id"], "uri": uri}
        for c in chunks for uri in c.get("citesUris") or []
    ]
    if refresh_law_refs:
        session.execute_write(lambda tx: tx.run(
            "UNWIND $rows AS row MATCH (c:Chunk {id: row.id}) "
            "SET c.lawRefs = row.lawRefs",
            rows=[{"id": c["id"], "lawRefs": c["lawRefs"]} for c in chunks],
        ))
    if mentions:
        session.execute_write(lambda tx: tx.run(
            "UNWIND $rows AS row "
            "MATCH (c:Chunk {id: row.cid}) MATCH (p:Person {id: row.did}) "
            "MERGE (c)-[:MENTIONS]->(p)",
            rows=mentions,
        ))
    if cites:
        session.execute_write(lambda tx: tx.run(
            "UNWIND $rows AS row "
            "MATCH (c:Chunk {id: row.cid}) MATCH (a:ParliamentaryAct {uri: row.uri}) "
            "MERGE (c)-[:CITES]->(a)",
            rows=cites,
        ))
    return len(mentions), len(cites)


def main():
    parser = argparse.ArgumentParser(description="Backfill MENTIONS/CITES from chunk NER fields")
    parser.add_argument("--neo4j-uri", default=None)
    parser.add_argument("--batch-size", type=int, default=2000)
    args = parser.parse_args()

    from dotenv import load_dotenv
    from neo4j import GraphDatabase

    load_dotenv(REPO_ROOT / ".env")
    uri = args.neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    t0 = time.time()
    with driver.session() as session:
        resolver = load_resolver(session)
        act_index = load_act_index(session)
        total = session.run("MATCH (c:Chunk) RETURN count(c) AS n").single()["n"]
        print(f"Backfilling {total} chunks (batch {args.batch_size})...")

        done = tot_mentions = tot_cites = 0
        last_id = ""
        while True:
            rows = session.run(
                "MATCH (c:Chunk) WHERE c.id > $last AND c.text IS NOT NULL "
                "RETURN c.id AS id, c.text AS text, c.personRefs AS personRefs "
                "ORDER BY c.id LIMIT $limit",
                last=last_id, limit=args.batch_size,
            ).data()
            if not rows:
                break
            last_id = rows[-1]["id"]
            for c in rows:
                # Stored lawRefs predate the A.C./UE/d.P.R. patterns — redo on text
                c["lawRefs"] = extract_law_refs(c["text"] or "")
            annotate_chunks(rows, resolver, act_index)
            n_m, n_c = write_links(session, rows, refresh_law_refs=True)
            done += len(rows)
            tot_mentions += n_m
            tot_cites += n_c
            print(f"  {done}/{total} chunks — {tot_mentions} MENTIONS, {tot_cites} CITES", flush=True)

    driver.close()
    print(f"Done in {time.time() - t0:.0f}s: {tot_mentions} MENTIONS, {tot_cites} CITES.")


if __name__ == "__main__":
    main()
