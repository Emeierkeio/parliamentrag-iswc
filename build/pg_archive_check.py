#!/usr/bin/env python3
"""
Retrieval with and without the Postgres text archive, on the same queries.

Runs the backend's dense channel twice per query, once on Neo4j only and
once with the archived scopes searched on Postgres, and compares the
candidates: overlap, rows per chamber, and whether the archived rows carry
the same chunk text, speech text and embedding that Neo4j holds. Then runs
the full retrieval with the archive on, to exercise the coverage fill,
the signatory chunks and the neighbor expansion.

Needs a graph that still has the archived text (the staging one), so the
two paths can be compared:

  NEO4J_URI=bolt://localhost:7692 CHAMBERS=camera,senato \\
  ARCHIVE_URL=postgresql://... python build/pg_archive_check.py --scope senato_19
"""

import argparse
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from pg_archive_bench import QUERIES  # noqa: E402


def cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--scope", default="senato_19", help="archived scope, e.g. senato_19")
    ap.add_argument("--full", type=int, default=3, help="queries to run through the full retrieval")
    args = ap.parse_args()

    if not os.environ.get("NEO4J_URI") or not os.environ.get("ARCHIVE_URL"):
        print("NEO4J_URI and ARCHIVE_URL must be set explicitly (never the production graph)")
        return 2

    from app.services.archive import get_archive
    from app.services.neo4j_client import Neo4jClient
    from app.services.retrieval.engine import RetrievalEngine
    from app.services.retrieval.scope import default_scope

    client = Neo4jClient(os.environ["NEO4J_URI"], os.environ.get("NEO4J_USER", "neo4j"),
                         os.environ["NEO4J_PASSWORD"])
    engine = RetrievalEngine(client)
    scope = default_scope()
    chamber = args.scope.rpartition("_")[0]
    os.environ["ARCHIVE_SCOPES"] = args.scope
    archive = get_archive()
    print(f"graph {os.environ['NEO4J_URI']}, scope {scope}, archived {args.scope}")

    def dense(embedding, archived: bool):
        os.environ["ARCHIVE_SCOPES"] = args.scope if archived else ""
        t = time.perf_counter()
        rows = engine.dense_channel.retrieve(query_embedding=embedding, scope=scope)
        return rows, time.perf_counter() - t

    overlaps, t_off, t_on, problems = [], [], [], []
    for q in QUERIES:
        emb = engine.embed_query(q)
        off, a = dense(emb, False)
        on, b = dense(emb, True)
        t_off.append(a)
        t_on.append(b)
        ids_off = {r["evidence_id"] for r in off}
        ids_on = {r["evidence_id"] for r in on}
        overlaps.append(len(ids_off & ids_on) / max(1, len(ids_off)))
        by_id = {r["evidence_id"]: r for r in off}
        archived_ids = set(archive.chunks(ids_on | ids_off))
        arch = [r for r in on if r["evidence_id"] in archived_ids and r["evidence_id"] in by_id]
        n_arch_on = len(ids_on & archived_ids)
        n_arch_off = len(ids_off & archived_ids)
        for r in arch:
            ref = by_id[r["evidence_id"]]
            if r["chunk_text"] != ref["chunk_text"] or r["text"] != ref["text"]:
                problems.append((q, r["evidence_id"], "testo diverso"))
            elif not r.get("embedding") or cosine(r["embedding"], ref["embedding"]) < 0.9999:
                problems.append((q, r["evidence_id"], "embedding diverso"))
            elif r["party"] != ref["party"] or r["speaker_id"] != ref["speaker_id"]:
                problems.append((q, r["evidence_id"], "metadati diversi"))
        print(f"  {q[:48]:48}  {len(off):3}/{len(on):3} righe, {chamber} {n_arch_off:3}/{n_arch_on:3},"
              f" overlap {overlaps[-1]:.3f}, {1000*a:.0f}/{1000*b:.0f} ms")

    os.environ["ARCHIVE_SCOPES"] = args.scope
    print(f"\ndense: overlap medio {statistics.mean(overlaps):.3f} (min {min(overlaps):.3f}),"
          f" p50 {1000*statistics.median(t_off):.0f} ms Neo4j / {1000*statistics.median(t_on):.0f} ms archivio")
    print(f"righe dell'archivio diverse da Neo4j: {len(problems)}")
    for p in problems[:10]:
        print("  ", p)

    for q in QUERIES[:args.full]:
        t = time.perf_counter()
        out = engine.retrieve_sync(q, scope=scope)
        ev = out["evidence"]
        ids = {getattr(e, "evidence_id", None) for e in ev}
        n_arch = len(ids & set(archive.chunks(ids)))
        missing = sum(1 for e in ev if not getattr(e, "quote_text", None))
        print(f"\nretrieval completo «{q[:40]}»: {len(ev)} evidenze, {n_arch} {chamber},"
              f" senza testo {missing}, {time.perf_counter() - t:.1f} s")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
