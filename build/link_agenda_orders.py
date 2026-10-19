#!/usr/bin/env python3
"""
Agenda orders linked to the bill they were tabled on, with their outcome.

  (:AgendaOrder)-[:REFERS_TO {version, via}]->(:Bill)
  (:AgendaOrder {outcome, outcome_source, outcome_raw?, outcome_url?})

Neither source has a predicate for the bill, but the agenda order's number
holds it: 9/02911-A/028 is the 28th order on AC 2911 in the committee text A,
0/01980/001/07 the first one in committee 07 on AC 1980. Orders the Chamber
cites in votes but never describes have only a URI (aic9_02753_001_19),
which spells the same number. The reading (-B) picks the Bill node; the text
version (-A, -AR) is kept on the relationship, since versions are TextVersion
nodes of the same reading (decision D2). Orders on documents (9/DOC.VIII,N.6)
and on motions are left unlinked.

Outcome, Camera: the roll-call votes on the order (Vote-[:ON_ACT]->), since the
source has no outcome; orders accepted by the Government without a vote stay
without one (the Allegato A would have it). Outcome, Senate: the esito of the
same order in the Senate's amendment files (type G), from the JSONL written
by parse_emendamenti.py, matched by bill, venue and text.

No network. Idempotent: MERGE on the relationship, SET of values computed
from the graph and the JSONL.

    python build/link_agenda_orders.py --neo4j-uri bolt://... [--chamber camera|senato|both] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from typing import Iterable, Optional

from neo4j import GraphDatabase

logger = logging.getLogger("link_agenda_orders")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EMEND_JSONL = os.path.join(REPO, "downloads", "emendamenti", "emendamenti_leg19.jsonl")
CAMERA_BILL = "http://dati.camera.it/ocd/attocamera.rdf/ac{leg}_{number}"
CAMERA_AIC = "http://dati.camera.it/ocd/aic.rdf/"

# <number>[-bis][-B][-A|-AR|-A-R|-R]: number of the act, numbered sub-bill
# (stralcio), reading, text version. "R" alone appears only in URIs
# (aic9_00889_R_007_19 for 9/00889-AR/007).
_MID_RE = re.compile(
    r"^0*(?P<n>\d+)"
    r"(?:-(?P<sub>bis|ter|quater|quinquies|sexies|septies|octies))?"
    r"(?:-(?P<reading>[B-H]))?"
    r"(?:-?(?P<version>A-R|AR|A|R))?$",
    re.I,
)
# aic<venue>_<act>_<seq>[_<committee>]_<legislature>; Senate-branch URIs end in _S.
_URI_RE = re.compile(r"/aic\.rdf/aic[09]_(?P<body>.+?)_\d{3}(?:_\d{2,4})?_\d{2}$")


def _bill_number(mid: str) -> Optional[tuple[str, Optional[str]]]:
    """('2911', 'A') from '02911-A'; None for documents, motions and anything else."""
    m = _MID_RE.match(mid.strip())
    if not m:
        return None
    number = m["n"]
    if m["sub"]:
        number += "-" + m["sub"].lower()
    if m["reading"]:
        number += "-" + m["reading"].upper()
    version = m["version"].upper().replace("-", "") if m["version"] else None
    return number, ("AR" if version == "R" else version)


def bill_of_number(number: Optional[str]) -> Optional[tuple[str, Optional[str]]]:
    """Bill number and text version from an agenda order number (either chamber)."""
    parts = (number or "").split("/")
    if len(parts) < 3 or parts[0] not in ("0", "9"):
        return None
    return _bill_number(parts[1])


def bill_of_camera_uri(uri: str) -> Optional[tuple[str, Optional[str]]]:
    """Bill number and text version from a Chamber agenda order URI.

    aic9_02911_A_028_19, aic9_00643_bis_AR_185_19, aic9_01928_A_R_002_19,
    aic9_1633A_119_19, aic0_01980_001_07_19 (committee 07).
    """
    m = _URI_RE.search(uri or "")
    if not m:
        return None
    tokens = m["body"].split("_")
    lead = re.match(r"^(\d+)(A|AR)?$", tokens[0], re.I)
    if not lead:
        return None
    mid = lead[1] + "".join(f"-{t}" for t in tokens[1:])
    if lead[2]:
        mid += f"-{lead[2]}"
    mid = mid.replace("-A-R", "-AR")
    return _bill_number(mid)


def outcome_from_votes(outcomes: Iterable[Optional[str]]) -> Optional[str]:
    """Outcome of an agenda order from its roll-call votes (several when voted in parts)."""
    seen = {o for o in outcomes if o in ("approved", "rejected")}
    if seen == {"approved"}:
        return "approvato"
    if seen == {"rejected"}:
        return "respinto"
    if seen:
        return "approvato_in_parte"
    return None


# Senate esito strings, as written by the committees' and the Assembly's
# offices (amendment JSONL, 08/10/2026): 40 variants, typos included.
_SENATE_OUTCOMES = [
    (re.compile(r"^(v\.|vedi|ritirat\w*\.? *v|ritirat\w*\.? *vedi|ritirat\w* \(vedi)", re.I), "riformulato"),
    (re.compile(r"^accolt\w* (come|con) raccomandazione|^acco\w* come raccomandazione", re.I),
     "accolto_come_raccomandazione"),
    (re.compile(r"^accolt", re.I), "accolto"),
    (re.compile(r"^non accolt", re.I), "non_accolto"),
    (re.compile(r"^respint", re.I), "respinto"),
    (re.compile(r"^approvat", re.I), "approvato"),
    (re.compile(r"^ritirat", re.I), "ritirato"),
    (re.compile(r"^preclus", re.I), "precluso"),
    (re.compile(r"^decadut", re.I), "decaduto"),
    (re.compile(r"^(improponibile|inammissibile)\s*$", re.I), "inammissibile"),
    (re.compile(r"^non posto in votazione", re.I), "non_posto_in_votazione"),
    (re.compile(r"^id\. ", re.I), "assorbito"),
]


def senate_outcome(raw: Optional[str]) -> Optional[str]:
    """Normalised outcome of a Senate esito string; 'altro' for split or partial outcomes."""
    s = " ".join((raw or "").split())
    if not s:
        return None
    for rx, value in _SENATE_OUTCOMES:
        if rx.search(s):
            return value
    return "altro"


def _words(text: Optional[str]) -> frozenset[str]:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return frozenset(re.findall(r"[a-z0-9]{4,}", t))


# Jaccard floor and margin over the runner-up, set on the XIX on 19/10/2026:
# true pairs score 0.85-0.97, orders on the same bill rarely above 0.4.
MATCH_FLOOR = 0.5
MATCH_MARGIN = 0.1


def match_senate_outcomes(orders: list[dict], g_records: list[dict]) -> tuple[dict[str, dict], Counter]:
    """Esito of each Senate agenda order from the G records of the same bill and venue.

    orders: {uri, number, text}; g_records: amendment JSONL rows of type
    ordine_del_giorno, Senate branch. When the best candidates are too close
    (a text re-tabled as "testo 2"), the outcome is kept only if they agree.
    """
    by_key: dict[tuple[str, str], list[tuple[frozenset, dict]]] = defaultdict(list)
    for r in g_records:
        venue = "assemblea" if r.get("sede") == "assemblea" else "commissione"
        words = _words(r.get("testo"))
        for act in [r.get("atto")] + list(r.get("atti_congiunti") or []):
            if act and act.startswith("S."):
                by_key[(act[2:].lower(), venue)].append((words, r))
    out: dict[str, dict] = {}
    stats: Counter = Counter()
    for o in orders:
        parsed = bill_of_number(o["number"])
        if not parsed:
            stats["senato_no_bill"] += 1
            continue
        venue = "assemblea" if o["number"].startswith("9/") else "commissione"
        cands = by_key.get((parsed[0].lower(), venue))
        if not cands or not o.get("text"):
            stats["senato_no_candidates"] += 1
            continue
        words = _words(o["text"])
        scored = sorted(((len(words & w) / max(1, len(words | w)), r) for w, r in cands),
                        key=lambda x: -x[0])
        best = scored[0][0]
        if best < MATCH_FLOOR:
            stats["senato_no_match"] += 1
            continue
        close = [r for s, r in scored if best - s < MATCH_MARGIN]
        outcomes = {senate_outcome(r.get("esito")) for r in close}
        if len(outcomes) != 1:
            stats["senato_ambiguous"] += 1
            continue
        outcome = outcomes.pop()
        if outcome is None:
            stats["senato_matched_no_esito"] += 1
            continue
        top = close[0]
        out[o["uri"]] = {"uri": o["uri"], "outcome": outcome,
                         "raw": " ".join(top["esito"].split()), "url": top.get("fonte")}
    # One record, one order: a record claimed by two orders was matched on a shared boilerplate.
    claims = Counter(m["url"] for m in out.values())
    for uri in [u for u, m in out.items() if claims[m["url"]] > 1]:
        del out[uri]
        stats["senato_shared_record"] += 1
    stats["senato_outcome"] = len(out)
    return out, stats


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

WRITE_REFERS_TO = """
UNWIND $rows AS row
MATCH (o:ParliamentaryAct {uri: row.odg}) WHERE o:AgendaOrder
MATCH (b:ParliamentaryAct {uri: row.bill}) WHERE b:Bill
MERGE (o)-[r:REFERS_TO]->(b)
SET r.version = row.version, r.via = row.via
"""

# Only outcomes this script owns are overwritten.
WRITE_OUTCOME = """
UNWIND $rows AS row
MATCH (o:ParliamentaryAct {uri: row.uri})
WHERE o:AgendaOrder AND (o.outcome IS NULL OR o.outcome_source IN ['voto', 'esito_senato'])
SET o.outcome = row.outcome, o.outcome_source = row.source,
    o.outcome_raw = row.raw, o.outcome_url = row.url
"""


def _batched(rows: list[dict], size: int = 2000):
    for i in range(0, len(rows), size):
        yield rows[i:i + size]


def camera_links(session, leg: int, stats: Counter) -> list[dict]:
    bills = {r["uri"] for r in session.run(
        "MATCH (b:Bill {chamber: 'camera'}) RETURN b.uri AS uri")}
    rows = []
    for r in session.run(f"""
        MATCH (o:AgendaOrder)
        WHERE o.chamber = 'camera' OR (o.chamber IS NULL AND o.uri STARTS WITH '{CAMERA_AIC}'
                                       AND o.uri ENDS WITH '_{leg}')
        RETURN o.uri AS uri, o.number AS number"""):
        via = "numero" if r["number"] else "uri"
        parsed = bill_of_number(r["number"]) if r["number"] else bill_of_camera_uri(r["uri"])
        stats[f"camera_{via}"] += 1
        if not parsed:
            stats[f"camera_{via}_not_a_bill"] += 1
            continue
        bill = CAMERA_BILL.format(leg=leg, number=parsed[0])
        if bill not in bills:
            stats[f"camera_{via}_bill_missing"] += 1
            logger.debug("bill %s of %s not in the graph", bill, r["uri"])
            continue
        stats[f"camera_{via}_linked"] += 1
        rows.append({"odg": r["uri"], "bill": bill, "version": parsed[1], "via": via})
    return rows


def camera_outcomes(session, leg: int, stats: Counter) -> list[dict]:
    rows = []
    for r in session.run(f"""
        MATCH (o:AgendaOrder)<-[:ON_ACT]-(v:Vote)
        WHERE o.chamber = 'camera' OR (o.chamber IS NULL AND o.uri STARTS WITH '{CAMERA_AIC}'
                                       AND o.uri ENDS WITH '_{leg}')
        RETURN o.uri AS uri, collect(v.outcome) AS outcomes"""):
        outcome = outcome_from_votes(r["outcomes"])
        if outcome:
            stats[f"camera_outcome_{outcome}"] += 1
            rows.append({"uri": r["uri"], "outcome": outcome, "source": "voto", "raw": None, "url": None})
    return rows


def senate_links(session, stats: Counter) -> tuple[list[dict], list[dict]]:
    bills = {r["number"].lower(): r["uri"] for r in session.run(
        "MATCH (b:Bill {chamber: 'senato'}) WHERE b.number IS NOT NULL RETURN b.uri AS uri, b.number AS number")}
    orders = [dict(r) for r in session.run(
        "MATCH (o:AgendaOrder {chamber: 'senato'}) RETURN o.uri AS uri, o.number AS number")]
    rows = []
    for o in orders:
        stats["senato"] += 1
        parsed = bill_of_number(o["number"])
        if not parsed:
            stats["senato_not_a_bill"] += 1
            continue
        bill = bills.get(parsed[0].lower())
        if not bill:
            stats["senato_bill_missing"] += 1
            continue
        stats["senato_linked"] += 1
        rows.append({"odg": o["uri"], "bill": bill, "version": parsed[1], "via": "numero"})
    return rows, orders


def load_senate_g(path: str) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if '"ordine_del_giorno"' not in line:
                continue
            r = json.loads(line)
            if r.get("tipo") == "ordine_del_giorno" and r.get("ramo") == "S":
                out.append(r)
    return out


def load_senate_texts(path: str) -> dict[str, str]:
    """Text of each Senate agenda order by graph URI, from download_senate_aic.py's file."""
    texts = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("type", "").startswith("ODG") and r.get("text"):
                texts[f"senato:19:aic:{r['numero']}"] = r["text"]
    return texts


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--chamber", choices=("camera", "senato", "both"), default="both")
    ap.add_argument("--emendamenti", default=EMEND_JSONL, help="amendment JSONL (Senate outcomes)")
    ap.add_argument("--senate-aic", default=os.path.join(REPO, "data", "senato_xix_aic.jsonl"),
                    help="Senate agenda order texts (download_senate_aic.py)")
    ap.add_argument("--dry-run", action="store_true", help="count, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD non impostata")

    stats: Counter = Counter()
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        with driver.session() as session:
            links, outcomes = [], []
            if args.chamber in ("camera", "both"):
                links += camera_links(session, args.leg, stats)
                outcomes += camera_outcomes(session, args.leg, stats)
            if args.chamber in ("senato", "both"):
                senate_rows, orders = senate_links(session, stats)
                links += senate_rows
                if os.path.exists(args.emendamenti) and os.path.exists(args.senate_aic):
                    texts = load_senate_texts(args.senate_aic)
                    for o in orders:
                        o["text"] = texts.get(o["uri"])
                    matched, mstats = match_senate_outcomes(orders, load_senate_g(args.emendamenti))
                    stats.update(mstats)
                    outcomes += [{**m, "source": "esito_senato"} for m in matched.values()]
                else:
                    logger.warning("JSONL degli emendamenti o testi degli ODG del Senato assenti: "
                                   "esiti del Senato non aggiornati")
            if not args.dry_run:
                for batch in _batched(links):
                    session.run(WRITE_REFERS_TO, rows=batch).consume()
                for batch in _batched(outcomes):
                    session.run(WRITE_OUTCOME, rows=batch).consume()
    finally:
        driver.close()
    stats["refers_to_rows"] = len(links)
    stats["outcome_rows"] = len(outcomes)
    for k in sorted(stats):
        logger.info("%s: %d", k, stats[k])
    return 0


if __name__ == "__main__":
    sys.exit(main())
