#!/usr/bin/env python3
"""
Senate oversight and policy acts (download_senate_aic.py) into the graph.

  (:ParliamentaryAct {uri: "senato:<leg>:aic:<numero>", chamber: 'senato',
                      official_uris, senato_url?, outcome?})
  (:Person)-[:PRIMARY_SIGNATORY|CO_SIGNATORY]->(act)

The key is the number (decision D9, 18/10/2026): it survives reformulations,
which the Senate publishes as new records with new URIs. official_uris holds
the Chamber's ocd:aic URI and every Senate record of that number; senato_url
and outcome come from the latest Senate record.

The source names signatories as "COGNOME NOME" and identifies the first one by
a Camera persona id that the senatore -> persona crosswalk covers for only a
third of the senators (2026-10-11), so people are matched by name among the
legislature's senators. No network.
"""

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from act_kinds import aic_kind  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN = {18: "xviii", 19: "xix"}
TEXT_CHARS = 4000  # description length kept for the act embedding


def name_key(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z ]", " ", text).upper().split())


def senator_index(session, legislature: int) -> dict[str, str]:
    """name key -> Person id, for "COGNOME NOME" and "NOME COGNOME"; names
    shared by two senators are left out rather than guessed."""
    rows = session.run(
        "MATCH (p:Person) WHERE $m IN coalesce(p.mandates, []) "
        "RETURN p.id AS id, p.first_name AS fn, p.last_name AS ln",
        m=f"senato_{legislature}",
    ).data()
    index: dict[str, str] = {}
    clash: set[str] = set()
    for r in rows:
        for key in (name_key(f"{r['ln']} {r['fn']}"), name_key(f"{r['fn']} {r['ln']}")):
            if key in index and index[key] != r["id"]:
                clash.add(key)
            index[key] = r["id"]
    for key in clash:
        index.pop(key, None)
    # The Senate registry uses the name in common use ("Tino Magni", "Tilde
    # Minasi"), the acts the registry name ("MAGNI CELESTINO"): a surname that
    # belongs to one senator only is enough.
    surnames = Counter(name_key(r["ln"]) for r in rows)
    for r in rows:
        key = name_key(r["ln"])
        if surnames[key] == 1:
            index.setdefault(f"surname:{key}", r["id"])
    return index


def lookup(index: dict[str, str], name: str) -> str | None:
    """Person id for "COGNOME NOME": the full name, else the longest leading
    run of words that is a senator's unique surname."""
    key = name_key(name)
    if key in index:
        return index[key]
    words = key.split()
    for n in range(len(words) - 1, 0, -1):
        pid = index.get("surname:" + " ".join(words[:n]))
        if pid:
            return pid
    return None


def parse_date(text: str | None):
    return date.fromisoformat(text) if text else None


def senate_records(path: str) -> dict[str, list[dict]]:
    """numero -> Senate records, oldest first; empty when the file is missing."""
    by_number: dict[str, list[dict]] = {}
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            r = json.loads(line)
            by_number.setdefault(r["numero"], []).append(r)
    for recs in by_number.values():
        recs.sort(key=lambda r: r.get("date") or "")
    return by_number


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Load Senate oversight acts and their signatories")
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    args = ap.parse_args()

    from neo4j import GraphDatabase

    path = os.path.join(REPO, "data", f"senato_{ROMAN[args.legislature]}_aic.jsonl")
    acts = [json.loads(line) for line in open(path, encoding="utf-8")]
    senate = senate_records(os.path.join(REPO, "data", f"senato_{ROMAN[args.legislature]}_sindisp.jsonl"))
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    with driver.session() as s:
        index = senator_index(s, args.legislature)
        act_rows, sign_rows = [], []
        unmatched = Counter()
        for a in acts:
            uri = f"senato:{args.legislature}:aic:{a['numero']}"
            recs = senate.get(a["numero"], [])
            latest = recs[-1] if recs else {}
            family, kind = aic_kind(a["type"]) or (None, None)
            if family is None:
                logger.warning("unknown act type %r (%s): no family label", a["type"], uri)
            act_rows.append({
                "family": family,
                "kind": kind,
                "uri": uri,
                "type": a["type"],
                "number": a["numero"],
                "title": f"{a['type']} {a['numero']}",
                "description": a["text"][:TEXT_CHARS],
                "date": parse_date(a.get("date")),
                "status": "CONCLUSO" if a["concluded"] else "IN CORSO",
                "official_uris": [a["uri"]] + [r["uri"] for r in recs],
                "senato_url": latest.get("url"),
                "outcome": latest.get("outcome"),
            })
            stats["with_senate_record"] += bool(recs)
            signers = [(a["primary"], True)] + [(n, False) for n in a["cosigners"]]
            for name, primary in signers:
                pid = lookup(index, name)
                if pid:
                    sign_rows.append({"uri": uri, "pid": pid, "primary": primary})
                else:
                    unmatched[name] += 1
        for i in range(0, len(act_rows), 2000):
            s.run("""
                UNWIND $rows AS row
                MERGE (a:ParliamentaryAct {uri: row.uri})
                SET a.title_embedding = CASE WHEN a.title = row.title THEN a.title_embedding END,
                    a.description_embedding = CASE WHEN a.description = row.description
                                                   THEN a.description_embedding END
                SET a.chamber = 'senato', a.legislature = $leg, a.type = row.type,
                    a.type_raw = row.type, a.kind = row.kind,
                    a.number = row.number, a.title = row.title,
                    a.description = row.description, a.presentation_date = row.date,
                    a.status = row.status, a.official_uris = row.official_uris,
                    a.senato_url = coalesce(row.senato_url, a.senato_url),
                    a.outcome = coalesce(row.outcome, a.outcome)
            """, rows=act_rows[i:i + 2000], leg=args.legislature)
        by_family = defaultdict(list)
        for r in act_rows:
            if r["family"]:
                by_family[r["family"]].append(r["uri"])
        for family, uris in by_family.items():  # family comes from act_kinds.FAMILIES only
            s.run(f"UNWIND $uris AS u MATCH (a:ParliamentaryAct {{uri: u}}) SET a:{family}", uris=uris)
        for i in range(0, len(sign_rows), 5000):
            s.run("""
                UNWIND $rows AS row
                MATCH (a:ParliamentaryAct {uri: row.uri}) MATCH (p:Person {id: row.pid})
                FOREACH (_ IN CASE WHEN row.primary THEN [1] ELSE [] END |
                    MERGE (p)-[:PRIMARY_SIGNATORY]->(a))
                FOREACH (_ IN CASE WHEN row.primary THEN [] ELSE [1] END |
                    MERGE (p)-[:CO_SIGNATORY]->(a))
            """, rows=sign_rows[i:i + 5000])
    driver.close()
    stats["acts"] = len(act_rows)
    stats["signatures"] = len(sign_rows)
    stats["signatures_unmatched"] = sum(unmatched.values())
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    if unmatched:
        logger.info("unmatched names (top): %s", unmatched.most_common(12))
    return 0


if __name__ == "__main__":
    sys.exit(main())
