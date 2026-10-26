"""
Rewrite the data-volume lines in README.md from live Neo4j counts.

Run automatically at the end of `make update-data`; can also be run by hand:
    python build/update_readme_stats.py [--neo4j-uri bolt://localhost:7690]

Credentials come from NEO4J_USER / NEO4J_PASSWORD (repo-root .env is loaded).
The script targets four specific lines, matched by stable anchors:
  - "- **<N>k+ text chunks** from ..."             (Camera, the paper corpus)
  - "- **<N>k roll-call votes** with ..."          (Camera)
  - "The figures above count ... here updated to <date>."
  - "- **XIX Legislature — data as of ...** (updated incrementally): ..."
                                                  (Camera and Senato apart)
Counts are split by chamber as in /api/data/stats (backend/app/routers/data.py)
and never summed across the two houses.
"""
import argparse
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from neo4j import GraphDatabase

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"


def k(n: int) -> str:
    return f"{n / 1000:.1f}".rstrip("0").rstrip(".") + "k"


def kplus(n: int) -> str:
    return f"{n // 1000}k+"


def m(n: int) -> str:
    return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"


CHAMBERS = ("camera", "senato")

# Same split as SENATE_PREFIX_COUNTS in backend/app/routers/data.py
SENATE_PREFIXES = {
    "speeches": ("Speech", "id", ("sen_",)),
    "chunks": ("Chunk", "id", ("sen_",)),
    "ivotes": ("IndividualVote", "id", ("iv_senato_",)),
    "acts": ("ParliamentaryAct", "uri", ("http://dati.senato.it/", "senato:")),
}


def chamber_line(c: dict, ch: str) -> str:
    return (f"{c['sessions'][ch]} sessions · {k(c['speeches'][ch])} speeches · "
            f"{kplus(c['chunks'][ch])} chunks · {k(c['acts'][ch])} acts · "
            f"{k(c['votes'][ch])} roll calls with {m(c['ivotes'][ch])} individual votes")


def main():
    parser = argparse.ArgumentParser(description="Refresh README data stats from Neo4j")
    parser.add_argument("--neo4j-uri", default=None)
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    uri = args.neo4j_uri or os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set")

    driver = GraphDatabase.driver(uri, auth=(user, password))
    with driver.session() as session:
        def one(cypher, **params):
            return session.run(cypher, **params).single()["c"]

        def chamber_counts(cypher):
            rows = {r["chamber"]: r["c"] for r in session.run(cypher)}
            return {ch: rows.get(ch, 0) for ch in CHAMBERS}

        counts = {}
        # Senate nodes are told apart by id prefix, the Camera is the rest
        for key, (label, prop, prefixes) in SENATE_PREFIXES.items():
            total = one(f"MATCH (n:`{label}`) RETURN count(n) AS c")
            senato = sum(one(f"MATCH (n:`{label}`) WHERE n.`{prop}` STARTS WITH $p "
                             "RETURN count(n) AS c", p=prefix) for prefix in prefixes)
            counts[key] = {"camera": total - senato, "senato": senato}
        # Sessions ingested before the Senate carry no chamber: they are Camera
        counts["sessions"] = chamber_counts(
            "MATCH (s:Session) RETURN coalesce(s.chamber, 'camera') AS chamber, count(s) AS c")
        counts["votes"] = chamber_counts(
            "MATCH (s:Session)-[:HAS_VOTE]->(v:Vote) "
            "RETURN coalesce(s.chamber, 'camera') AS chamber, count(DISTINCT v) AS c")
        # Last `make update-data` run; falls back to newest Session date for
        # DBs stamped before SchemaMeta.updated_at existed
        last = session.run(
            "OPTIONAL MATCH (m:SchemaMeta {id: 'singleton'}) "
            "WITH date(m.updated_at) AS stamped "
            "OPTIONAL MATCH (s:Session) "
            "WITH stamped, max(s.date) AS newest "
            "RETURN coalesce(stamped, newest) AS d"
        ).single()["d"]
    driver.close()
    last_date = str(last.to_native() if hasattr(last, "to_native") else last)

    text = README.read_text(encoding="utf-8")
    cam = {key: by_chamber["camera"] for key, by_chamber in counts.items()}
    replacements = [
        (
            re.compile(r"^- \*\*[\d.,]+k\+ text chunks\*\* from .*$", re.M),
            f"- **{kplus(cam['chunks'])} text chunks** from "
            f"**{cam['sessions']} plenary sessions**, updated through {last_date}",
        ),
        (
            re.compile(r"^- \*\*[\d.,]+k roll-call votes\*\* with .*$", re.M),
            f"- **{k(cam['votes'])} roll-call votes** with **{m(cam['ivotes'])} "
            "individual vote records** linked to deputies",
        ),
        (
            re.compile(r"^The figures above count .*$", re.M),
            "The figures above count the Camera dei Deputati only: it is the corpus "
            f"behind the ISWC 2026 paper, here updated to {last_date}. The Senate "
            "figures are listed apart under Knowledge graph.",
        ),
        (
            re.compile(r"^- \*\*XIX Legislature[,—\s]+data as of .*$", re.M),
            f"- **XIX Legislature, data as of {last_date}** (updated incrementally). "
            f"Camera: {chamber_line(counts, 'camera')}. "
            f"Senato: {chamber_line(counts, 'senato')}",
        ),
    ]
    changed = 0
    for pattern, replacement in replacements:
        text, n = pattern.subn(lambda _match, r=replacement: r, text)
        if n != 1:
            print(f"WARNING: anchor matched {n} times (expected 1): {pattern.pattern}")
        changed += n
    README.write_text(text, encoding="utf-8")
    print(f"README.md: {changed}/{len(replacements)} stat lines refreshed (data as of {last_date})")


if __name__ == "__main__":
    main()
