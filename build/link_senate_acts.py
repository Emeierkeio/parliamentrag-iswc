#!/usr/bin/env python3
"""
Senate bills in the graph, linked to signatories, debates and roll-call votes.

Reads data/senato_{roman}_ddl*.csv (download_senate_ddl.py) and the sitting
transcripts in data/senate_xml (Akoma Ntoso); no network.

  (:ParliamentaryAct {uri: Ddl URI, chamber: 'senato'})
  (:Person)-[:PRIMARY_SIGNATORY|CO_SIGNATORY]->(act)   from osr:iniziativa
  (:Debate)-[:DISCUSSES]->(act)                         from the section's <block name="Atto">
  (:Vote)-[:ON_ACT]->(act)                              see vote_act()

osr:Votazione carries no link to the bill, only a label ("Em. 1.3, Parrini e
altri", "Articolo 21", "Votazione finale"). The transcript announces each vote
inside the section of the bill under discussion ("Indìco la votazione nominale
con scrutinio simultaneo dell'emendamento 1.3, presentato dal senatore
Parrini"), which gives the bill.
"""

import argparse
import logging
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csv_loader import parse_date_to_neo4j  # noqa: E402
from senate_parser import _slug  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROMAN = {18: "xviii", 19: "xix"}
ACT_TYPE = "Disegno di legge"

VOTE_ANNOUNCE_RE = re.compile(r"Ind[iì]co la votazione", re.IGNORECASE)
BILL_NUMBER_RE = re.compile(
    r"(?:disegno di legge|d\.d\.l\.|ddl)\s*n\.\s*(\d+(?:-[A-Za-z]+)?)", re.IGNORECASE
)
# Amendment / agenda-item identifiers: 1.3, 26-bis.100, G1.100, S18.200,
# 18.0.6 (new article after 18), 5.0.100/102 (sub-amendment)
ITEM_RE = re.compile(r"\b([A-Za-z]{0,2}\d+(?:-[a-z]+)?(?:\.\d+)+(?:/\d+)?)")
ARTICLE_RE = re.compile(r"\barticolo\s+(\d+(?:-[a-z]+)?)", re.IGNORECASE)
FINAL_RE = re.compile(r"votazione finale|nel suo complesso", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Transcript parsing
# ---------------------------------------------------------------------------

def vote_keys(text: str) -> set[str]:
    """Keys shared by a vote label and its announcement in the transcript."""
    keys = {f"item:{m}" for m in ITEM_RE.findall(text)}
    if not keys:
        keys |= {f"art:{m.lower()}" for m in ARTICLE_RE.findall(text)}
    if FINAL_RE.search(text):
        keys.add("final")
    return keys


def parse_sitting(path: str) -> dict:
    """Bills by section slug, and vote announcements with their bills.

    Returns {"sections": {slug: [bill numbers]}, "events": [(keys, [bill numbers])]}.
    """
    root = ET.parse(path).getroot()
    ns = root.tag.split("}")[0] + "}"
    body = root.find(f".//{ns}debateBody")
    sections: dict[str, list[str]] = defaultdict(list)
    events: list[tuple[set[str], list[str]]] = []
    if body is None:
        return {"sections": {}, "events": []}
    for sec in body.findall(f"{ns}debateSection"):
        bills = [
            (b.findtext(f"{ns}docNumber") or "").strip()
            for b in sec.iter(f"{ns}block")
            if b.get("name") == "Atto" and (b.findtext(f"{ns}docType") or "").strip() == "DDL"
        ]
        bills = [b for b in bills if b]
        slug = _slug(sec.get("name", ""))
        for b in bills:
            if b not in sections[slug]:
                sections[slug].append(b)
        for p in sec.iter(f"{ns}p"):
            text = " ".join("".join(p.itertext()).split())
            if not VOTE_ANNOUNCE_RE.search(text):
                continue
            explicit = BILL_NUMBER_RE.findall(text)
            events.append((vote_keys(text), explicit or bills))
    return {"sections": dict(sections), "events": events}


def vote_act(label: str, sitting: dict) -> Optional[str]:
    """Bill number settled by the label or the sitting alone, else None.

    1. a bill number in the label ("Disegno di legge n. 1272. Votazione
       questione di fiducia.");
    2. the only bill voted on in the sitting, if every vote was on it.
    """
    events = sitting["events"]
    explicit = BILL_NUMBER_RE.findall(label or "")
    if explicit:
        return explicit[0]
    # Only when every announcement sits in a bill's section: otherwise a
    # motion voted in the same sitting would be attributed to the bill.
    voted = {b for _, bills in events for b in bills}
    if len(voted) == 1 and all(bills for _, bills in events):
        return next(iter(voted))
    return None


def align(vote_key_sets: list[set[str]], events: list[tuple[set[str], list[str]]]) -> dict[int, int]:
    """Order-preserving alignment of votes to announcements sharing a key.

    Votes are numbered in the order they are announced, but some votes are
    announced with other words ("Passiamo alla votazione finale") and some
    announcements are not roll calls, so neither list is a subsequence of
    the other. Maximising the matched pairs (LCS) keeps one missing
    announcement from shifting every later vote, and tells apart
    "Articolo 6" of two bills voted in the same sitting.
    """
    m, n = len(vote_key_sets), len(events)
    best = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m - 1, -1, -1):
        for j in range(n - 1, -1, -1):
            hit = 1 + best[i + 1][j + 1] if vote_key_sets[i] & events[j][0] else 0
            best[i][j] = max(hit, best[i + 1][j], best[i][j + 1])
    pairs: dict[int, int] = {}
    i = j = 0
    while i < m and j < n:
        if vote_key_sets[i] & events[j][0] and best[i][j] == 1 + best[i + 1][j + 1]:
            pairs[i] = j
            i, j = i + 1, j + 1
        elif best[i + 1][j] >= best[i][j + 1]:
            i += 1
        else:
            j += 1
    return pairs


def link_sitting_votes(votes: list[tuple[str, str]], sitting: dict) -> dict[str, str]:
    """{vote id: bill number} for the votes of a sitting, given in vote order.

    vote_act() first; the rest through align(). A "Controprova" repeats the
    previous vote, so it takes the same bill. Joint bills: the first
    <block name="Atto"> of the section is the base text voted on.
    """
    events = sitting["events"]
    pairs = align([vote_keys(label or "") for _, label in votes], events)
    out: dict[str, str] = {}
    previous = None
    for i, (vote_id, label) in enumerate(votes):
        if (label or "").strip().lower().startswith("controprova"):
            bill = previous
        else:
            bill = vote_act(label, sitting)
            if bill is None and i in pairs and events[pairs[i]][1]:
                bill = events[pairs[i]][1][0]
        if bill:
            out[vote_id] = bill
        previous = bill
    return out


# ---------------------------------------------------------------------------
# Bill numbers -> Ddl URIs
# ---------------------------------------------------------------------------

def bill_index(ddl: pd.DataFrame) -> dict[str, str]:
    """Senate bill number -> Ddl URI. Joint bills ("93-338-353-B") are also
    reachable from each of their numbers when that is unambiguous."""
    senate = ddl[ddl["ramo"] == "S"]
    index = dict(zip(senate["numero"], senate["ddl"]))
    parts = Counter()
    by_part: dict[str, str] = {}
    for numero, uri in index.items():
        for part in numero.split("-"):
            if part.isdigit() and part not in index:
                parts[part] += 1
                by_part[part] = uri
    for part, n in parts.items():
        if n == 1:
            index[part] = by_part[part]
    return index


# ---------------------------------------------------------------------------
# Graph writes
# ---------------------------------------------------------------------------

def write_acts(session, ddl: pd.DataFrame, legislature: int) -> int:
    rows = [{
        "uri": r.ddl,
        "number": r.numero,
        "title": r.titolo if isinstance(r.titolo, str) else None,
        "date": parse_date_to_neo4j(str(r.dataPresentazione).replace("-", "")),
        "idDdl": r.idDdl,
        "status": r.stato if isinstance(r.stato, str) else None,
        "nature": r.natura if isinstance(r.natura, str) else None,
    } for r in ddl[ddl["ramo"] == "S"].itertuples()]
    session.run("""
        UNWIND $rows AS row
        MERGE (a:ParliamentaryAct {uri: row.uri})
        SET a.chamber = 'senato', a.legislature = $leg, a.type = $type,
            a.number = row.number, a.title = row.title,
            a.presentation_date = row.date, a.id_ddl = row.idDdl,
            a.status = row.status, a.nature = row.nature
    """, rows=rows, leg=legislature, type=ACT_TYPE)
    return len(rows)


def write_signatories(session, signers: pd.DataFrame, senate_uris: set[str]) -> int:
    rows = [
        {"uri": r.ddl, "sen": r.senatore, "primary": r.primoFirmatario == "1"}
        for r in signers.itertuples() if r.ddl in senate_uris
    ]
    result = session.run("""
        UNWIND $rows AS row
        MATCH (a:ParliamentaryAct {uri: row.uri})
        MATCH (p:Person {senato_id: row.sen})
        FOREACH (_ IN CASE WHEN row.primary THEN [1] ELSE [] END |
            MERGE (p)-[:PRIMARY_SIGNATORY]->(a))
        FOREACH (_ IN CASE WHEN row.primary THEN [] ELSE [1] END |
            MERGE (p)-[:CO_SIGNATORY]->(a))
        RETURN count(*) AS n
    """, rows=rows)
    return result.single()["n"]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Link Senate bills to signatories, debates and votes")
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    args = ap.parse_args()

    from neo4j import GraphDatabase

    roman = ROMAN.get(args.legislature, f"leg{args.legislature}")
    data = os.path.join(REPO, "data")
    ddl = pd.read_csv(os.path.join(data, f"senato_{roman}_ddl.csv"), dtype=str)
    signers = pd.read_csv(os.path.join(data, f"senato_{roman}_ddl_firmatari.csv"), dtype=str)
    index = bill_index(ddl)
    senate_uris = set(ddl.loc[ddl["ramo"] == "S", "ddl"])

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    with driver.session() as s:
        stats["acts"] = write_acts(s, ddl, args.legislature)
        stats["signatures"] = write_signatories(s, signers, senate_uris)

        sittings = {r["n"]: r["id"] for r in s.run(
            "MATCH (x:Session {chamber: 'senato', legislature: $leg}) RETURN x.number AS n, x.id AS id",
            leg=args.legislature)}
        discusses, on_act = [], []
        for num, session_id in sorted(sittings.items()):
            path = os.path.join(data, "senate_xml", f"resaula_leg{args.legislature}_{num:04d}.akn")
            if not os.path.exists(path):
                stats["sittings_without_transcript"] += 1
                continue
            sitting = parse_sitting(path)

            for r in s.run("MATCH (:Session {id: $sid})-[:HAS_DEBATE]->(d:Debate) RETURN d.id AS id",
                           sid=session_id):
                slug = r["id"][len(session_id) + 1:]
                bills = sitting["sections"].get(slug) or sitting["sections"].get(
                    re.sub(r"_\d+$", "", slug), [])
                for b in bills:
                    if b in index:
                        discusses.append({"debate": r["id"], "uri": index[b]})
                    else:
                        stats["debate_bill_unknown"] += 1

            votes = [(r["id"], r["label"]) for r in s.run("""
                MATCH (:Session {id: $sid})-[:HAS_VOTE]->(v:Vote)
                WHERE v.type <> 'verifica numero legale' OR v.type IS NULL
                RETURN v.id AS id, v.subject AS label ORDER BY v.number
            """, sid=session_id)]
            linked = link_sitting_votes(votes, sitting)
            stats["votes_unresolved"] += len(votes) - len(linked)
            for vote_id, bill in linked.items():
                if bill in index:
                    on_act.append({"vote": vote_id, "uri": index[bill]})
                else:
                    stats["votes_bill_unknown"] += 1

        s.run("""
            UNWIND $rows AS row
            MATCH (d:Debate {id: row.debate}) MATCH (a:ParliamentaryAct {uri: row.uri})
            MERGE (d)-[:DISCUSSES]->(a)
        """, rows=discusses)
        s.run("""
            UNWIND $rows AS row
            MATCH (v:Vote {id: row.vote}) MATCH (a:ParliamentaryAct {uri: row.uri})
            MERGE (v)-[:ON_ACT]->(a)
        """, rows=on_act)
        stats["debates_linked"] = len(discusses)
        stats["votes_linked"] = len(on_act)
    driver.close()
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
