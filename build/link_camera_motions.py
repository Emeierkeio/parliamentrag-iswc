#!/usr/bin/env python3
"""
Chamber motions and resolutions linked to the debate where they are voted.

  (:Debate)-[:DISCUSSES]->(act)   act: kind 'mozione' or 'risoluzione_assemblea',
                                  target of a (:Vote)-[:ON_ACT]

The transcript closes each roll call with "(Vedi votazione n. 2)" inside the
<dibattito> where it happens: that debate discusses the act. Votes often fall
in a bare continuation ("Si riprende la discussione."): the debate it resumes
is the latest earlier one of the sitting that names the act ("n. 6-00186")
and is not itself a continuation, and it is linked too. The ingest already
links the debates whose agenda item lists the act (db_builder act
references); those are left as they are.

Reads data/xml/stenografico_leg{L}_{NNNN}.xml; no network. Idempotent: MERGE.

    python build/link_camera_motions.py --neo4j-uri bolt://... [--dry-run]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Optional

logger = logging.getLogger("link_camera_motions")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML_DIR = os.path.join(REPO, "data", "xml")
KINDS = ["mozione", "risoluzione_assemblea"]

VOTE_REF_RE = re.compile(r"Vedi votazione n\.\s*(\d+)")
ACT_NUMBER_RE = re.compile(r"\b([16])-(\d{5})\b")
# Same family as db_builder.PROCEDURAL_TITLE_PATTERN, as a prefix match.
CONTINUATION_RE = re.compile(r"(si riprende la discussione|ripresa della discussione"
                             r"|seguito della discussione\.?$)", re.IGNORECASE)
# Agenda items, as opposed to procedural sections ("Per un richiamo al
# Regolamento", "Preavviso di votazioni elettroniche", "Sull'ordine dei lavori").
AGENDA_ITEM_RE = re.compile(r"(discussione|seguito della discussione|comunicazioni|esame|informativa)\b",
                            re.IGNORECASE)
# Debates that end with resolutions: the Government's communications and the
# House's examination of a document or report.
RESOLUTION_HOST_RE = re.compile(
    r"(?:(?:seguito della )?discussione (?:sulle |sulla |del |della |dello )?)?"
    r"(?:comunicazioni|esame|informativa|documento|relazione|nota|piano)\b", re.IGNORECASE)


def _text(elem: Optional[ET.Element]) -> str:
    return " ".join("".join(elem.itertext()).split()) if elem is not None else ""


def parse_sections(path: str) -> list[dict]:
    """The <dibattito> sections of a sitting, in order.

    [{"id": "tit00080", "title", "votes": {vote numbers}, "acts": {"6/00186", ...}}]
    """
    root = ET.parse(path).getroot()
    out = []
    for dib in root.iter("dibattito"):
        text = _text(dib)
        out.append({
            "id": dib.get("id"),
            "title": _text(dib.find("titolo")),
            "votes": {int(n) for n in VOTE_REF_RE.findall(text)},
            "acts": {f"{kind}/{n}" for kind, n in ACT_NUMBER_RE.findall(text)},
        })
    return out


def debates_for_vote(sections: list[dict], vote_number: int, act: str) -> list[str]:
    """Section ids that discuss the act voted in vote_number: the one where the
    vote falls and, when that is a continuation, the debate it resumes.

    The resumed debate is the latest earlier agenda item that names the act.
    Resolutions are often tabled after the debate opens, so the Government's
    communications may not name them: then the latest earlier agenda item is
    taken, provided it is one that ends with resolutions.
    """
    at = next((i for i, s in enumerate(sections) if vote_number in s["votes"]), None)
    if at is None:
        return []
    found = [sections[at]["id"]]
    if not CONTINUATION_RE.match(sections[at]["title"]):
        return found
    earlier = [s for s in reversed(sections[:at])
               if AGENDA_ITEM_RE.match(s["title"]) and not CONTINUATION_RE.match(s["title"])]
    named = next((s for s in earlier if act in s["acts"]), None)
    if named:
        found.append(named["id"])
    elif act.startswith("6/") and earlier and RESOLUTION_HOST_RE.match(earlier[0]["title"]):
        found.append(earlier[0]["id"])
    return found


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--dry-run", action="store_true", help="read the graph, write nothing")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    mode = "READ" if args.dry_run else "WRITE"
    with driver.session(default_access_mode=mode) as s:
        votes = [r.data() for r in s.run("""
            MATCH (sess:Session {chamber: 'camera', legislature: $leg})-[:HAS_VOTE]->(v:Vote)
                  -[:ON_ACT]->(a:ParliamentaryAct)
            WHERE a.kind IN $kinds
            RETURN sess.id AS session, sess.number AS sitting, v.number AS number,
                   a.uri AS uri, a.number AS act
            ORDER BY sitting, number
        """, leg=args.legislature, kinds=KINDS)]
        rows, cache = [], {}
        for v in votes:
            n = v["sitting"]
            if n not in cache:
                path = os.path.join(XML_DIR, f"stenografico_leg{args.legislature}_{n:04d}.xml")
                cache[n] = parse_sections(path) if os.path.exists(path) else None
            if cache[n] is None:
                stats["votes_without_transcript"] += 1
                continue
            found = debates_for_vote(cache[n], v["number"], v["act"])
            if not found:
                stats["votes_without_section"] += 1
                continue
            stats["votes_placed"] += 1
            stats["votes_with_resumed_debate"] += len(found) > 1
            rows += [{"debate": f"{v['session']}_{sec}", "uri": v["uri"]} for sec in found]
        rows = [dict(t) for t in sorted({tuple(sorted(r.items())) for r in rows})]
        stats["pairs"] = len(rows)
        stats["pairs_new"] = s.run("""
            UNWIND $rows AS row
            MATCH (d:Debate {id: row.debate}) MATCH (a:ParliamentaryAct {uri: row.uri})
            WHERE NOT (d)-[:DISCUSSES]->(a)
            RETURN count(*) AS n
        """, rows=rows).single()["n"]
        stats["pairs_debate_missing"] = s.run("""
            UNWIND $rows AS row
            OPTIONAL MATCH (d:Debate {id: row.debate})
            WITH row WHERE d IS NULL RETURN count(*) AS n
        """, rows=rows).single()["n"]
        if not args.dry_run:
            stats["discusses_merged"] = s.run("""
                UNWIND $rows AS row
                MATCH (d:Debate {id: row.debate}) MATCH (a:ParliamentaryAct {uri: row.uri})
                MERGE (d)-[r:DISCUSSES]->(a)
                RETURN count(r) AS n
            """, rows=rows).single()["n"]
    driver.close()
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
