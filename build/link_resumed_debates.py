#!/usr/bin/env python3
"""
Resumed debates and debates on a split bill, linked to the bills they discuss.

  (:Debate)-[:DISCUSSES {via}]->(:Bill|:ParliamentaryDocument)

The ingest links a debate to the acts its agenda item lists (Camera XML
argomenti, Senate <block name="Atto">). A floor debate interrupted and
resumed in the same sitting opens a new section that lists none:

  via 'titolo'   the title names the bill: "Si riprende la discussione del
                 disegno di legge n. 1660-A" (Camera), "Ripresa della
                 discussione del disegno di legge n. 180-1041", "(274)"
                 (Senato). A Chamber "-A" or "-A/R" is a text version of the
                 bill (decision D2), "-B" a bill of its own, "-bis", "-ter"
                 a bill split off from another (C. 1532-ter, C. 643-bis).
                 Those split bills are debated under the parent's agenda
                 item: a title "(A.C. 1532-ter-A)" also links the split
                 bill, and the parent link stays.
  via 'ripresa'  the bare "Si riprende la discussione." resumes the latest
                 earlier agenda item of the sitting and gets its bills, or
                 its documents (Doc.) when it is about documents;
                 "e abbinate" in a numbered title adds the bills of the
                 latest earlier debate on the same bill. The Senate's
                 "Ripresa della discussione sulle comunicazioni ..." resumes
                 the debate link_senate_acts.resumed_debate finds.

Bills, and documents through a bare resumption: motions and resolutions
are placed by their votes (link_camera_motions.py, link_senate_acts.py),
documents by ingest_documents.py. Reads the graph only, no network.
Idempotent: MERGE, never deletes.

    python build/link_resumed_debates.py --neo4j-uri bolt://... --chamber camera|senato [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from link_camera_motions import AGENDA_ITEM_RE  # noqa: E402
from link_senate_acts import resumed_debate  # noqa: E402

logger = logging.getLogger("link_resumed_debates")

CAMERA_BILL_URI = "http://dati.camera.it/ocd/attocamera.rdf/ac{leg}_{key}"

# "(ore 15,05)", "(16,40)": the time of the section, repeated in some titles.
_TIME_RE = re.compile(r"\((?:ore\s*\d{1,2}(?:[,.]\d{2})?|\d{1,2}[,.]\d{2})\)")
_SPLIT = "bis|ter|quater|quinquies|sexies|septies|octies|novies|decies"
_NUMBER = r"\d+(?:-\d+)*(?:-(?:" + _SPLIT + r"))?(?:-[A-Z](?:/R)?)?"
# "n. 1660-A", "nn. 1532 e 1533", "n. 180-1041"
_NUMBERED_RE = re.compile(r"\bnn?\.\s*(" + _NUMBER + r"(?:\s*(?:,|e|ed)\s*(?:n\.\s*)?" + _NUMBER + r")*)")
_NUMBER_RE = re.compile(_NUMBER)
# Senate titles: "del disegno di legge: (274) - Benefici ..."
_SENATE_PAREN_RE = re.compile(r"\((\d+(?:-\d+)*(?:-[A-Z])?)\)")
# Chamber titles name the bill under debate as "(A.C. 1532-ter-A)".
_AC_SPLIT_RE = re.compile(r"\bA\.\s?C\.\s*(\d+-(?:" + _SPLIT + r"))(?:-[A-Z](?:/R)?)?\b")
_JOINED_RE = re.compile(r"\babbinat[ae]\b", re.IGNORECASE)
_BILL_WORD_RE = re.compile(r"disegn[oi] di legge|propost[ae] di legge|testo unificato|d\.d\.l\.", re.IGNORECASE)
# "Si riprende la discussione", "Si riprende l'esame", "Si riprende il seguito della discussione"
RESUMPTION_RE = re.compile(r"^(?:si riprende\b|ripresa della discussione|seguito della discussione$)", re.IGNORECASE)
# A motion to send the bill under debate back to committee: "Sul rinvio in
# Commissione del disegno di legge n. 1665".
RECOMMITTAL_RE = re.compile(r"^(?:sul(?:la richiesta di)? )?rinvio in commissione\b", re.IGNORECASE)
_SENATE_AGENDA_RE = re.compile(r"^(?:ripresa della |seguito della )?discussione\b", re.IGNORECASE)


def clean_title(title: Optional[str]) -> str:
    """Title without the times and the non-breaking spaces of the Chamber XML."""
    t = (title or "").replace("\xa0", " ")
    t = _TIME_RE.sub(" ", t)
    return " ".join(t.split()).strip(" .")


def is_bare_resumption(title: str) -> bool:
    """A continuation section whose title names nothing: "Si riprende la discussione."."""
    t = clean_title(title)
    return bool(RESUMPTION_RE.match(t)) and not re.search(r"\d", t) and len(t) < 60


def camera_key(number: str) -> str:
    """Bill key in the Chamber URI: "1660-A" -> "1660", "643-bis-A/R" -> "643-bis", "2822-B" -> "2822-B"."""
    parts = number.split("/")[0].split("-")
    split = [p for p in parts[1:] if p in _SPLIT.split("|")]
    reading = [p for p in parts[1:] if p.isalpha() and p.isupper() and p != "A"]
    return "-".join([parts[0]] + split[:1] + reading[-1:])


def title_numbers(title: str) -> list[str]:
    """Bill numbers after "n." / "nn." in a title, as written."""
    out: list[str] = []
    for group in _NUMBERED_RE.findall(clean_title(title)):
        out += _NUMBER_RE.findall(group)
    return list(dict.fromkeys(out))


def camera_title_keys(title: str) -> list[str]:
    """Chamber bill keys a resumption or recommittal title names ("Si riprende la discussione ... n. 1660-A")."""
    t = clean_title(title)
    if not ((RESUMPTION_RE.match(t) or RECOMMITTAL_RE.match(t)) and _BILL_WORD_RE.search(t)):
        return []
    return list(dict.fromkeys(camera_key(n) for n in title_numbers(t)))


def camera_split_keys(title: str) -> list[str]:
    """Split bills a Chamber agenda title debates: "(A.C. 1532-ter-A)" -> ["1532-ter"]."""
    return list(dict.fromkeys(_AC_SPLIT_RE.findall(clean_title(title))))


def senate_title_numbers(title: str) -> list[str]:
    """Senate bill numbers a bill debate names: "n. 180-1041", "(274)"."""
    t = clean_title(title)
    if not (_SENATE_AGENDA_RE.match(t) and _BILL_WORD_RE.search(t)):
        return []
    return list(dict.fromkeys(title_numbers(t) + _SENATE_PAREN_RE.findall(t)))


def senate_lookup(number: str, index: dict[str, str]) -> list[str]:
    """Senate bill URIs for a number; "180-1041" names two bills when no joint bill has it."""
    if number in index:
        return [index[number]]
    parts = number.split("-")
    if len(parts) > 1 and all(p.isdigit() for p in parts) and all(p in index for p in parts):
        return [index[p] for p in parts]
    return []


def senate_index(bills: list[tuple[str, str]]) -> dict[str, str]:
    """Senate bill number -> URI; a joint bill ("93-338-353-B") also by each unambiguous number."""
    index = {n: u for u, n in bills if n}
    parts: Counter = Counter()
    by_part: dict[str, str] = {}
    for n, u in list(index.items()):
        for p in n.split("-"):
            if p.isdigit() and p not in index:
                parts[p] += 1
                by_part[p] = u
    index.update({p: by_part[p] for p, c in parts.items() if c == 1})
    return index


def resumed_anchor(debates: list[dict], at: int) -> Optional[dict]:
    """The agenda item a bare resumption at position at resumes: the latest earlier one of the sitting.

    Procedural sections in between (missions, rulings, question time,
    "Sull'ordine dei lavori") are skipped; so are other bare resumptions,
    which resume the same item.
    """
    for d in reversed(debates[:at]):
        t = clean_title(d["title"])
        if is_bare_resumption(t):
            continue
        if AGENDA_ITEM_RE.match(t) or RESUMPTION_RE.match(t):
            return d
    return None


def plan_camera(sittings: dict[str, list[dict]], leg: int, uris: set[str], stats: Counter) -> list[dict]:
    """DISCUSSES rows for the Chamber; each debate dict has id, title, order, bills (linked URIs)."""
    rows: list[dict] = []
    # bill URI -> bills of the debates that discuss it, in sitting order
    history: dict[str, list[list[str]]] = defaultdict(list)
    ordered = sorted(sittings.items(), key=lambda kv: kv[1][0]["sitting"] if kv[1] else 0)
    for _, debates in ordered:
        debates.sort(key=lambda d: d["order"] or 0)
        for i, d in enumerate(debates):
            title = d["title"] or ""
            add: list[tuple[str, str]] = []
            for key in camera_split_keys(title):
                uri = CAMERA_BILL_URI.format(leg=leg, key=key)
                if uri in uris:
                    add.append((uri, "titolo"))
                    stats["camera_split_titles"] += 1
                else:
                    stats["camera_split_bill_missing"] += 1
            if not d["linked"]:
                keys = camera_title_keys(title)
                if keys:
                    stats["camera_numbered_resumptions"] += 1
                    found = [CAMERA_BILL_URI.format(leg=leg, key=k) for k in keys]
                    missing = [u for u in found if u not in uris]
                    stats["camera_numbered_bill_missing"] += len(missing)
                    for u in missing:
                        logger.warning("%s: %r, atto %s non nel grafo", d["id"], clean_title(title), u)
                    found = [u for u in found if u in uris]
                    add += [(u, "titolo") for u in found]
                    if found and _JOINED_RE.search(title) and history.get(found[0]):
                        add += [(u, "ripresa") for u in history[found[0]][-1] if u not in found]
                        stats["camera_joined_from_earlier_debate"] += 1
                elif is_bare_resumption(title):
                    stats["camera_bare_resumptions"] += 1
                    anchor = resumed_anchor(debates, i)
                    if anchor and (anchor["bills"] or anchor.get("docs")):
                        add += [(u, "ripresa") for u in anchor["bills"] or anchor["docs"]]
                    else:
                        stats["camera_bare_without_bill"] += 1
            new = [(u, via) for u, via in dict(add).items() if u not in d["bills"]]
            if new:
                stats["camera_debates_linked"] += 1
                rows += [{"debate": d["id"], "uri": u, "via": via} for u, via in new]
                d["bills"] = d["bills"] + [u for u, _ in new]
            if d["bills"] and not RESUMPTION_RE.match(clean_title(title)):
                for u in d["bills"]:
                    history[u].append(d["bills"])
    return rows


def plan_senate(sittings: dict[str, list[dict]], index: dict[str, str], stats: Counter) -> list[dict]:
    """DISCUSSES rows for the Senate debates on a bill that link none."""
    rows: list[dict] = []
    for debates in sittings.values():
        debates.sort(key=lambda d: d["order"] or 0)
        ordered = [(d["id"], d["title"], d["order"] or 0) for d in debates]
        by_id = {d["id"]: d for d in debates}
        for d in debates:
            if d["bills"] or d["linked"]:
                continue
            add: list[tuple[str, str]] = []
            numbers = senate_title_numbers(d["title"])
            if numbers:
                stats["senato_numbered_debates"] += 1
                for n in numbers:
                    found = senate_lookup(n, index)
                    if not found:
                        stats["senato_numbered_bill_missing"] += 1
                        logger.warning("%s: %r, ddl %s non nel grafo", d["id"], clean_title(d["title"]), n)
                    add += [(u, "titolo") for u in found]
            else:
                other = resumed_debate(d["id"], ordered)
                if other and by_id[other]["bills"]:
                    stats["senato_resumed_with_bill"] += 1
                    add += [(u, "ripresa") for u in by_id[other]["bills"]]
            new = list(dict(add).items())
            if new:
                stats["senato_debates_linked"] += 1
                rows += [{"debate": d["id"], "uri": u, "via": via} for u, via in new]
                d["bills"] = [u for u, _ in new]
    return rows


DEBATES = """
MATCH (s:Session)-[:HAS_DEBATE]->(d:Debate)
WHERE coalesce(s.chamber, 'camera') = $chamber AND coalesce(s.legislature, 19) = $leg
RETURN s.id AS session, s.number AS sitting, d.id AS id, d.title AS title, d.order AS order,
       [(d)-[:DISCUSSES]->(b:Bill) | b.uri] AS bills, EXISTS { (d)-[:DISCUSSES]->() } AS linked,
       [(d)-[:DISCUSSES]->(x:ParliamentaryDocument) | x.uri] AS docs
"""

WRITE = """
UNWIND $rows AS row
MATCH (d:Debate {id: row.debate}) MATCH (b:ParliamentaryAct {uri: row.uri}) WHERE b:Bill OR b:ParliamentaryDocument
MERGE (d)-[r:DISCUSSES]->(b)
ON CREATE SET r.via = row.via
RETURN count(r) AS n
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--chamber", choices=["camera", "senato"], required=True)
    ap.add_argument("--dry-run", action="store_true", help="read the graph, write nothing")
    ap.add_argument("--dump", help="write the computed rows to this JSON file")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats: Counter = Counter()
    with driver.session(default_access_mode="READ" if args.dry_run else "WRITE") as s:
        sittings: dict[str, list[dict]] = defaultdict(list)
        for r in s.run(DEBATES, chamber=args.chamber, leg=args.legislature):
            sittings[r["session"]].append(r.data())
        bills = [(r["uri"], r["number"]) for r in s.run(
            "MATCH (b:Bill {chamber: $chamber}) WHERE coalesce(b.legislature, 19) = $leg "
            "RETURN b.uri AS uri, b.number AS number", chamber=args.chamber, leg=args.legislature)]
        if args.chamber == "camera":
            rows = plan_camera(sittings, args.legislature, {u for u, _ in bills}, stats)
        else:
            rows = plan_senate(sittings, senate_index(bills), stats)
        stats["rows"] = len(rows)
        stats.update(f"rows_via_{r['via']}" for r in rows)
        if args.dump:
            with open(args.dump, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=0)
        if rows and not args.dry_run:
            stats["discusses_merged"] = s.run(WRITE, rows=rows).single()["n"]
    driver.close()
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
