#!/usr/bin/env python3
"""
Senate bills in the graph, linked to signatories, debates and roll-call votes.

Reads data/senato_{roman}_ddl*.csv (download_senate_ddl.py) and the sitting
transcripts in data/senate_xml (Akoma Ntoso); no network.

  (:ParliamentaryAct {uri: Ddl URI, chamber: 'senato', initiative})
  (:Person)-[:PRIMARY_SIGNATORY|CO_SIGNATORY]->(act)   senators, from osr:iniziativa
  (act)-[:PRESENTED_BY]->(:Government)                  government bills (decision D3)
  (:Person)-[:PRESENTED {role}]->(act)                  ministers and deputies who
                                                        presented it: kept apart from
                                                        the signatures, which feed
                                                        the authority score
  (:Debate)-[:DISCUSSES]->(act)                         from the section's <block name="Atto">
  (:Vote)-[:ON_ACT]->(act)                              official link, else vote_act()

The official link is osr:Votazione -> osr:oggetto -> osr:relativoA
(senato_{roman}_voti_atti.csv); it replaces any other ON_ACT of that vote.
Votes it does not cover are matched through the transcript: the label alone
("Em. 1.3, Parrini e altri", "Articolo 21", "Votazione finale") does not name
the bill, but the transcript announces each vote inside the section of the
bill under discussion ("Indìco la votazione nominale con scrutinio simultaneo
dell'emendamento 1.3, presentato dal senatore Parrini").
"""

import argparse
import logging
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from typing import Optional

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from csv_loader import parse_date_to_neo4j  # noqa: E402
from senate_parser import _slug  # noqa: E402
from senate_sparql_ingester import parse_senate_votazione_uri  # noqa: E402

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
# Initiative and presenters (decision D3)
# ---------------------------------------------------------------------------

INITIATIVE = {
    "Parlamentare": "parlamentare", "Governativa": "governo", "Regionale": "regionale",
    "CNEL": "cnel", "Popolare": "popolare",
}
GOV_SUFFIX_RE = re.compile(r"\(Gov\.[^)]*\)\s*$")
DEPUTY_URI_RE = re.compile(r"/deputato\.rdf/d(\d+)_\d+$")


def initiative_of(types) -> Optional[str]:
    """osr:tipoIniziativa values of a bill -> initiative; 'mista' when they differ."""
    kinds = {INITIATIVE[t] for t in types if t in INITIATIVE}
    if not kinds:
        return None
    return kinds.pop() if len(kinds) == 1 else "mista"


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^A-Z ]", " ", text.upper()).split()


def match_minister(presenter: str, members: list[dict]) -> Optional[str]:
    """Id of the government member named in an osr:presentatore string.

    "Ministro della giustizia Carlo Nordio (Gov. Meloni-I)": the person is
    whoever of the members of that government has every surname token and the
    first given name in the string. None when nobody or more than one does.
    """
    text = set(_tokens(GOV_SUFFIX_RE.sub("", presenter)))
    hits = [m["id"] for m in members
            if set(_tokens(m["last_name"])) <= text and _tokens(m["first_name"])[:1]
            and _tokens(m["first_name"])[0] in text]
    return hits[0] if len(hits) == 1 else None


def deputy_persona(uri: str) -> Optional[str]:
    """ocd:rif_deputato (d302838_19) -> the persona URI kept as camera_id."""
    m = DEPUTY_URI_RE.search(uri or "")
    return f"http://dati.camera.it/ocd/persona.rdf/p{m.group(1)}" if m else None


def government_on(governments: list[dict], day: str) -> Optional[dict]:
    """The government in office on an ISO day (start <= day < end)."""
    for g in governments:
        if g["start"] <= day and (not g["end"] or day < g["end"]):
            return g
    return None


def official_vote_acts(rows: pd.DataFrame, senate_uris: set[str]) -> dict[str, list[str]]:
    """{Vote id: [Ddl URIs]} from osr:relativoA, Senate-branch bills only."""
    out: dict[str, list[str]] = defaultdict(list)
    for vz, atto in zip(rows["votazione"], rows["atto"]):
        leg, sitting, number = parse_senate_votazione_uri(vz or "")
        if leg is None or atto not in senate_uris:
            continue
        vote_id = f"senato_leg{leg}_sed{sitting:03d}_v{number:03d}"
        if atto not in out[vote_id]:
            out[vote_id].append(atto)
    return dict(out)


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

def write_acts(session, ddl: pd.DataFrame, legislature: int,
               initiatives: dict[str, str]) -> int:
    rows = [{
        "uri": r.ddl,
        "number": r.numero,
        "title": r.titolo if isinstance(r.titolo, str) else None,
        "date": parse_date_to_neo4j(str(r.dataPresentazione).replace("-", "")),
        "idDdl": r.idDdl,
        "status": r.stato if isinstance(r.stato, str) else None,
        "nature": r.natura if isinstance(r.natura, str) else None,
        "initiative": initiatives.get(r.ddl),
        "descr": getattr(r, "descrIniziativa", None)
        if isinstance(getattr(r, "descrIniziativa", None), str) else None,
    } for r in ddl[ddl["ramo"] == "S"].itertuples()]
    session.run("""
        UNWIND $rows AS row
        MERGE (a:ParliamentaryAct {uri: row.uri})
        SET a.chamber = 'senato', a.legislature = $leg, a.type = $type,
            a.number = row.number, a.title = row.title,
            a.presentation_date = row.date, a.id_ddl = row.idDdl,
            a.status = row.status, a.nature = row.nature,
            a.initiative = row.initiative, a.initiative_descr = row.descr
    """, rows=rows, leg=legislature, type=ACT_TYPE)
    return len(rows)


def write_presenters(session, ddl: pd.DataFrame, signers: pd.DataFrame,
                     presenters: pd.DataFrame, initiatives: dict[str, str]) -> Counter:
    """PRESENTED_BY the government in office on the presentation day, and
    PRESENTED {role: proponente|concerto} from each minister or deputy.

    Ministers come as strings (presenters file) or, when they are senators,
    as signatures of a government initiative (osr:senatore): those keep their
    PRIMARY_SIGNATORY as before and get PRESENTED too.
    """
    stats = Counter()
    governments = [dict(r) for r in session.run("""
        MATCH (g:Government) RETURN g.id AS id, toString(g.start_date) AS start,
               toString(g.end_date) AS end ORDER BY g.start_date
    """)]
    members: dict[str, list[dict]] = {}
    for r in session.run("""
        MATCH (p:Person)-[:HOLDS_OFFICE]->(g:Government)
        RETURN DISTINCT g.id AS gov, p.id AS id, p.first_name AS first_name, p.last_name AS last_name
    """):
        members.setdefault(r["gov"], []).append(dict(r))

    day = {r.ddl: str(r.dataPresentazione)[:10] for r in ddl.itertuples()
           if isinstance(r.dataPresentazione, str)}
    by_gov, presented = [], []
    for uri, kind in initiatives.items():
        if kind not in ("governo", "mista") or uri not in day:
            continue
        gov = government_on(governments, day[uri])
        if gov is None:
            stats["government_bill_no_government"] += 1
            continue
        by_gov.append({"uri": uri, "gov": gov["id"]})

    gov_of = {row["uri"]: row["gov"] for row in by_gov}
    for r in presenters.itertuples():
        role = "proponente" if r.primoFirmatario == "1" else "concerto"
        if r.tipo == "Governativa":
            person = match_minister(r.presentatore, members.get(gov_of.get(r.ddl), []))
            if person:
                presented.append({"uri": r.ddl, "key": "id", "value": person, "role": role})
            else:
                stats["minister_unmatched"] += 1
                logger.debug("minister not matched: %s (%s)", r.presentatore, r.ddl)
        elif isinstance(r.deputato, str) and deputy_persona(r.deputato):
            presented.append({"uri": r.ddl, "key": "camera_id",
                              "value": deputy_persona(r.deputato), "role": role})
    if "tipo" in signers.columns:
        for r in signers[signers["tipo"] == "Governativa"].itertuples():
            presented.append({"uri": r.ddl, "key": "senato_id", "value": r.senatore,
                              "role": "proponente" if r.primoFirmatario == "1" else "concerto"})

    session.run("""
        UNWIND $rows AS row
        MATCH (a:ParliamentaryAct {uri: row.uri}) MATCH (g:Government {id: row.gov})
        MERGE (a)-[:PRESENTED_BY]->(g)
    """, rows=by_gov)
    for key in ("id", "camera_id", "senato_id"):
        rows = [p for p in presented if p["key"] == key]
        n = session.run(f"""
            UNWIND $rows AS row
            MATCH (a:ParliamentaryAct {{uri: row.uri}}) MATCH (p:Person {{{key}: row.value}})
            MERGE (p)-[r:PRESENTED]->(a) SET r.role = row.role
            RETURN count(r) AS n
        """, rows=rows).single()["n"]
        stats[f"presented_{key}"] = n
        stats[f"presented_{key}_unmatched"] = len(rows) - n
    stats["presented_by_government"] = len(by_gov)
    return stats


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
    presenters_path = os.path.join(data, f"senato_{roman}_ddl_presentatori.csv")
    presenters = (pd.read_csv(presenters_path, dtype=str) if os.path.exists(presenters_path)
                  else pd.DataFrame(columns=["ddl", "presentatore", "tipo", "deputato",
                                             "primoFirmatario"]))
    types: dict[str, set] = defaultdict(set)
    for frame in (signers, presenters):
        if "tipo" in frame.columns:
            for uri, tipo in zip(frame["ddl"], frame["tipo"]):
                if isinstance(tipo, str):
                    types[uri].add(tipo)
    initiatives = {uri: kind for uri, t in types.items() if (kind := initiative_of(t))}
    index = bill_index(ddl)
    senate_uris = set(ddl.loc[ddl["ramo"] == "S", "ddl"])
    official_path = os.path.join(data, f"senato_{roman}_voti_atti.csv")
    official = (official_vote_acts(pd.read_csv(official_path, dtype=str), senate_uris)
                if os.path.exists(official_path) else {})

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    with driver.session() as s:
        stats["acts"] = write_acts(s, ddl, args.legislature, initiatives)
        stats["signatures"] = write_signatories(s, signers, senate_uris)
        stats.update(write_presenters(s, ddl, signers, presenters, initiatives))

        sittings = {r["n"]: r["id"] for r in s.run(
            "MATCH (x:Session {chamber: 'senato', legislature: $leg}) RETURN x.number AS n, x.id AS id",
            leg=args.legislature)}
        discusses, on_act = [], []
        for num, session_id in sorted(sittings.items()):
            votes = [(r["id"], r["label"]) for r in s.run("""
                MATCH (:Session {id: $sid})-[:HAS_VOTE]->(v:Vote)
                WHERE v.type <> 'verifica numero legale' OR v.type IS NULL
                RETURN v.id AS id, v.subject AS label ORDER BY v.number
            """, sid=session_id)]
            for vote_id, _ in votes:
                on_act += [{"vote": vote_id, "uri": uri} for uri in official.get(vote_id, [])]
            stats["votes_linked_official"] += sum(1 for v, _ in votes if v in official)

            path = os.path.join(data, "senate_xml", f"resaula_leg{args.legislature}_{num:04d}.akn")
            if not os.path.exists(path):
                stats["sittings_without_transcript"] += 1
                stats["votes_unresolved"] += sum(1 for v, _ in votes if v not in official)
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

            # The whole sitting goes through the alignment, so that a vote
            # with an official link still anchors the ones around it.
            linked = link_sitting_votes(votes, sitting)
            stats["votes_unresolved"] += sum(1 for v, _ in votes
                                             if v not in official and v not in linked)
            for vote_id, bill in linked.items():
                if vote_id in official:
                    stats["transcript_agrees_official"] += index.get(bill) in official[vote_id]
                    continue
                if bill in index:
                    on_act.append({"vote": vote_id, "uri": index[bill]})
                else:
                    stats["votes_bill_unknown"] += 1

        s.run("""
            UNWIND $rows AS row
            MATCH (d:Debate {id: row.debate}) MATCH (a:ParliamentaryAct {uri: row.uri})
            MERGE (d)-[:DISCUSSES]->(a)
        """, rows=discusses)
        stats["stale_on_act_removed"] = s.run("""
            UNWIND $rows AS row
            MATCH (v:Vote {id: row.vote})-[r:ON_ACT]->(a)
            WHERE NOT a.uri IN row.uris
            DELETE r
            RETURN count(r) AS n
        """, rows=[{"vote": v, "uris": u} for v, u in official.items()]).single()["n"]
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
