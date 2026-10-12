#!/usr/bin/env python3
"""
Postgres archive vs Neo4j on the same queries (PLAN_data_platform.md, 9.4).

For each query: exact top-k on Postgres (sequential scan, the ground truth),
HNSW top-k on Postgres, vector index top-k on Neo4j; recall@k against the
exact result and latency. A second pass adds a date filter, which Postgres
applies inside the index scan (iterative scan) and Neo4j after it.
"""

import argparse
import os
import statistics
import sys
import time

import psycopg

QUERIES = [
    "premierato ed elezione diretta del Presidente del Consiglio",
    "autonomia differenziata delle regioni",
    "salario minimo e contratti di lavoro",
    "separazione delle carriere dei magistrati",
    "immigrazione e accordo con l'Albania",
    "caro energia e bollette delle famiglie",
    "legge di bilancio e pressione fiscale",
    "guerra in Ucraina e invio di armi",
    "liste d'attesa nella sanità pubblica",
    "cambiamento climatico e transizione ecologica",
    "Piano nazionale di ripresa e resilienza",
    "sicurezza sul lavoro e morti bianche",
    "riforma della giustizia e intercettazioni",
    "scuola, docenti precari e concorsi",
    "violenza contro le donne e femminicidi",
    "conflitto a Gaza e riconoscimento della Palestina",
    "ponte sullo Stretto di Messina",
    "superbonus e crediti edilizi",
    "carceri e sovraffollamento",
    "intelligenza artificiale e regolazione",
]


def pct(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--pg", required=True)
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--neo4j-index", default="chunk_embedding_senato_19")
    ap.add_argument("-k", type=int, default=50)
    ap.add_argument("--ef-search", type=int, default=100)
    args = ap.parse_args()

    from neo4j import GraphDatabase
    from openai import OpenAI

    oa = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    embs = [d.embedding for d in oa.embeddings.create(
        input=QUERIES, model="text-embedding-3-small").data]
    driver = GraphDatabase.driver(args.neo4j_uri, auth=("neo4j", args.neo4j_password))
    k = args.k

    def vec(e):
        return "[" + ",".join(f"{v:.6g}" for v in e) + "]"

    results = {}
    with psycopg.connect(args.pg, autocommit=True) as pg, driver.session() as neo:
        pg.execute(f"SET hnsw.ef_search = {args.ef_search}")
        pg.execute("SET hnsw.iterative_scan = relaxed_order")
        for flt_name, pg_where, neo_where, params in [
            ("nessun filtro", "assembly = 'senato' AND term = 19", "", {}),
            ("solo 2025", "assembly = 'senato' AND term = 19 AND session_date >= '2025-01-01' "
             "AND session_date < '2026-01-01'",
             "WHERE s.date >= date('2025-01-01') AND s.date < date('2026-01-01')", {}),
        ]:
            rec_hnsw, rec_neo, t_exact, t_hnsw, t_neo = [], [], [], [], []
            for e in embs:
                v = vec(e)
                q = (f"SELECT id FROM chunk WHERE {pg_where} "
                     f"ORDER BY embedding <=> %s::halfvec LIMIT {k}")
                pg.execute("SET enable_indexscan = off")
                t = time.perf_counter()
                exact = [r[0] for r in pg.execute(q, (v,)).fetchall()]
                t_exact.append(time.perf_counter() - t)
                pg.execute("SET enable_indexscan = on")
                t = time.perf_counter()
                hnsw = [r[0] for r in pg.execute(q, (v,)).fetchall()]
                t_hnsw.append(time.perf_counter() - t)
                # Neo4j: index first, then the date filter (how the dense channel works today)
                cypher = (
                    f"CALL db.index.vector.queryNodes($idx, $kk, $e) YIELD node AS c, score "
                    f"MATCH (c)<-[:HAS_CHUNK]-(:Speech)<-[:CONTAINS_SPEECH]-(:Phase)<-[:HAS_PHASE]-"
                    f"(:Debate)<-[:HAS_DEBATE]-(s:Session) {neo_where} "
                    f"RETURN c.id AS id ORDER BY score DESC LIMIT $k"
                )
                kk = k if not neo_where else k * 10
                t = time.perf_counter()
                neo_ids = [r["id"] for r in neo.run(cypher, idx=args.neo4j_index, kk=kk, e=e, k=k)]
                t_neo.append(time.perf_counter() - t)
                gold = set(exact)
                rec_hnsw.append(len(gold & set(hnsw)) / max(1, len(gold)))
                rec_neo.append(len(gold & set(neo_ids)) / max(1, len(gold)))
            results[flt_name] = (rec_hnsw, rec_neo, t_exact, t_hnsw, t_neo)

        size = pg.execute("SELECT pg_size_pretty(pg_total_relation_size('chunk')), "
                          "pg_size_pretty(pg_relation_size('chunk_embedding_hnsw')), count(*) FROM chunk").fetchone()
    driver.close()

    print(f"chunk: {size[2]} righe, tabella+indici {size[0]}, indice HNSW {size[1]}")
    for name, (rh, rn, te, th, tn) in results.items():
        print(f"\n## {name} (k={k}, {len(QUERIES)} domande)")
        print(f"  recall@{k}  Postgres HNSW {statistics.mean(rh):.3f} (min {min(rh):.2f})"
              f" | Neo4j {statistics.mean(rn):.3f} (min {min(rn):.2f})")
        print(f"  latenza ms  esatta p50 {1000*statistics.median(te):.0f}"
              f" | HNSW p50 {1000*statistics.median(th):.0f} p95 {1000*pct(th, .95):.0f}"
              f" | Neo4j p50 {1000*statistics.median(tn):.0f} p95 {1000*pct(tn, .95):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
