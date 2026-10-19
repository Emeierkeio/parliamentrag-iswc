"""Measure the retrieval-pool impact of matching acts on their EuroVoc subjects.

Until 2026-10-19 the graph channel matched keywords against a.eurovoc and
reranked on a.eurovoc_embedding, two v1 properties absent from the v2 graph:
acts were found by title and description only. The fix matches the labels of
the (a)-[:HAS_SUBJECT]->(:EurovocConcept) subjects and reranks on their
embeddings too (card #136). This script runs both versions of the graph
channel for every topic in evaluation_set.json, merges each with the same
dense-channel output and reports the pool deltas.

Cost: one embedding call per topic, no generation. Read-only on the graph.

Usage: venv/bin/python scripts/eval_graph_subjects_delta.py
"""
import copy
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.deps import get_services  # noqa: E402


def find_acts_before_fix(channel, keywords, top_k=100):
    """_find_relevant_acts as it was: title and description only, since
    a.eurovoc does not exist in the v2 graph."""
    params = {}
    conditions = []
    for i, kw in enumerate(keywords):
        params[f"kw{i}"] = f"(?i).*\\b{re.escape(kw.lower())}\\b.*"
        conditions.append(f"a.title =~ $kw{i} OR a.description =~ $kw{i}")
    cypher = f"""
    MATCH (a:ParliamentaryAct)
    WHERE {" OR ".join(conditions)}
    RETURN a.uri AS uri, a.title AS title, a.description AS description,
           a.presentation_date AS date, a.type AS type,
           a.title_embedding AS title_embedding,
           a.description_embedding AS description_embedding
    LIMIT {top_k}
    """
    return channel.client.query(cypher, params)


def pool_stats(merged):
    channels, parties = {}, set()
    for r in merged:
        ch = r.get("retrieval_channel", "?")
        channels[ch] = channels.get(ch, 0) + 1
        if r.get("party"):
            parties.add(r["party"])
    return {
        "size": len(merged),
        "graph_share": round(channels.get("graph", 0) / max(1, len(merged)), 3),
        "parties": len(parties),
    }


def main():
    services = get_services()
    engine = services["retrieval"]
    graph_channel = engine.graph_channel
    eval_set = json.load(open(Path(__file__).resolve().parents[1] / "evaluation_set.json"))
    new_find = graph_channel._find_relevant_acts

    rows = []
    for topic in eval_set:
        emb = engine.embed_query(topic)
        dense = engine.dense_channel.retrieve(query_embedding=emb, top_k=200)

        keywords = graph_channel.extract_keywords(topic)
        acts_new = new_find(keywords)
        acts_old = find_acts_before_fix(graph_channel, keywords)
        graph_new = graph_channel.retrieve(query=topic, query_embedding=emb)
        graph_channel._find_relevant_acts = lambda kws, top_k=100: find_acts_before_fix(
            graph_channel, kws, top_k)
        try:
            graph_old = graph_channel.retrieve(query=topic, query_embedding=emb)
        finally:
            graph_channel._find_relevant_acts = new_find

        merged_new = engine.merger.merge(dense, copy.deepcopy(graph_new), None, top_k=100)
        merged_old = engine.merger.merge(dense, copy.deepcopy(graph_old), None, top_k=100)
        ids_new = {r["evidence_id"] for r in merged_new}
        ids_old = {r["evidence_id"] for r in merged_old}

        row = {
            "topic": topic[:50],
            "acts_old": len(acts_old),
            "acts_new": len(acts_new),
            "acts_via_subject": len({a["uri"] for a in acts_new} - {a["uri"] for a in acts_old}),
            "graph_old": len(graph_old),
            "graph_new": len(graph_new),
            "old": pool_stats(merged_old),
            "new": pool_stats(merged_new),
            "jaccard_overlap": round(len(ids_new & ids_old) / max(1, len(ids_new | ids_old)), 3),
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)

    n = len(rows)
    mean = lambda f: round(sum(f(r) for r in rows) / n, 3)  # noqa: E731
    print("\n=== SUMMARY over", n, "topics ===")
    print("mean acts found old/new:", mean(lambda r: r["acts_old"]), mean(lambda r: r["acts_new"]))
    print("mean graph chunks old/new:", mean(lambda r: r["graph_old"]), mean(lambda r: r["graph_new"]))
    print("mean graph share old/new:", mean(lambda r: r["old"]["graph_share"]),
          mean(lambda r: r["new"]["graph_share"]))
    print("mean parties in pool old/new:", mean(lambda r: r["old"]["parties"]),
          mean(lambda r: r["new"]["parties"]))
    print("mean pool jaccard overlap old vs new:", mean(lambda r: r["jaccard_overlap"]))


if __name__ == "__main__":
    main()
