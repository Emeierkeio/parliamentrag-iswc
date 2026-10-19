#!/usr/bin/env python3
"""
Laws the bills of a legislature became, linked to their legislative process (decision D5).

  (:LegislativeProcess)-[:BECAME_LAW]->(:Law {urn, kind, number, date, title, eli, code,
                                              gu_number, gu_date, gu_supplement})

The process is the one of build/migrate_act_identity.py, so every reading of
the bill (C.2822, S.1971, C.2822-B) reaches the law through PART_OF. Sources:

- dati.senato.it: numeroLegge and dataLegge on the osr:Ddl phases of the iter
  (data/senato_{roman}_ddl.csv, written by download_senate_ddl.py). A law not
  yet published carries the placeholder date 2100-01-01: left out.
- dati.camera.it: "Legge 180 del 9 ottobre 2026 pubblicata nella Gazzetta
  Ufficiale n. 235 del 9 ottobre 2026" in the dc:description of the bills.
  One SPARQL query, cached in data/ for the nights the endpoint is down.
- Normattiva: title, ELI, codice redazionale and Gazzetta, one page per law
  and only for laws without an ELI in the graph; parsed pages are cached in
  data/normattiva_{roman}_leggi.json.

The key is the NIR URN by year and number (urn:nir:stato:legge:2026;180).
The Senate's dataLegge is sometimes the Gazzetta date (L. 162/2025 and
L. 11/2026, 19/10/2026), so dates come from Normattiva first, then from the
Camera, then from the Senate.

    python build/ingest_laws.py --neo4j-uri bolt://... [--dry-run] [--no-normattiva]
"""

import argparse
import csv
import html
import json
import logging
import os
import re
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from typing import Optional

logger = logging.getLogger("ingest_laws")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(REPO, "data")
ROMAN = {18: "xviii", 19: "xix"}
NORMATTIVA = "https://www.normattiva.it/uri-res/N2Ls?"
USER_AGENT = "ParliamentRAG-laws/1.0 (+https://www.parliamentrag.it)"
MONTHS = {m: i for i, m in enumerate(
    "gennaio febbraio marzo aprile maggio giugno luglio agosto settembre ottobre novembre dicembre".split(), 1)}
# The Senate's dataLegge may be the Gazzetta date, published up to a few weeks
# after the law (L. 162/2025: law 22/10, Gazzetta and dataLegge 4/11).
DATE_SLACK_DAYS = 60

CAMERA_QUERY = """
SELECT DISTINCT ?a ?desc WHERE {{
  ?a a ocd:atto ; ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}> ;
     dc:description ?desc .
  FILTER(CONTAINS(?desc, "Gazzetta"))
}}"""
_DAY = r"(1°|\d{1,2})\s+(\w+)\s+(\d{4})"
CAMERA_GU_RE = re.compile(
    r"Legge\s+(\d+)\s+del(?:l'|\s)\s*" + _DAY
    + r"\s+pubblicata nella Gazzetta Ufficiale n\.\s*(\d+)\s+del(?:l'|\s)\s*" + _DAY, re.I)

NT_TITLE_RE = re.compile(r"<title>\s*(LEGGE(?: COSTITUZIONALE)?)\s+" + _DAY + r",\s*n\.\s*(\d+)", re.I)
NT_ELI_RE = re.compile(r'about="na:(id/[^"]+)"\s+property="eli:uri_schema"')
NT_CODE_RE = re.compile(r'name="atto\.codiceRedazionale"\s+value="([^"]+)"')
NT_GU_RE = re.compile(r"\(GU n\.\s*(\d+) del (\d{2})-(\d{2})-(\d{4})(?:\s*-\s*(Suppl\.[^)]*?))?\s*\)")
NT_H3_RE = re.compile(r'id="titoloAtto".*?<h3[^>]*>(.*?)</h3>', re.S)
TAG_RE = re.compile(r"<[^>]+>")


def it_date(day: str, month: str, year: str) -> Optional[str]:
    """ISO date from '9', 'ottobre', '2026' (or '1°')."""
    m = MONTHS.get(month.lower())
    if not m:
        return None
    return f"{int(year):04d}-{m:02d}-{int(day.rstrip('°')):02d}"


def urn(kind: str, year: str, number: int) -> str:
    return f"urn:nir:stato:{'legge.costituzionale' if kind == 'legge_costituzionale' else 'legge'}:{year};{number}"


def _days(a: str, b: str) -> int:
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def senate_laws(phases: list[dict], leg: int) -> tuple[list[dict], list[dict]]:
    """One record per law from the Senate phases, and the placeholder phases left out.

    phases: rows of data/senato_{roman}_ddl.csv. Every phase of an iter carries
    the law, the Senate and the Chamber branch alike.
    """
    laws: dict[tuple, dict] = {}
    placeholders = []
    for p in phases:
        number, day = (p.get("numeroLegge") or "").strip(), (p.get("dataLegge") or "")[:10]
        if not number:
            continue
        if not day or day >= "2100":
            placeholders.append(p)
            continue
        kind = "legge_costituzionale" if p.get("natura") == "costituzionale" else "legge"
        law = laws.setdefault((kind, int(number), day), {
            "kind": kind, "number": int(number), "senate_date": day, "iters": set()})
        law["iters"].add(p["idDdl"])
    out = []
    for law in laws.values():
        law["processes"] = sorted(f"senato:{leg}:iter:{i}" for i in law.pop("iters"))
        out.append(law)
    return out, placeholders


def camera_gazette(rows: list[dict]) -> list[dict]:
    """Law and Gazzetta from the dc:description of the Chamber's bills."""
    out = []
    for r in rows:
        m = CAMERA_GU_RE.search(r.get("desc") or "")
        if not m:
            continue
        law_date, gu_date = it_date(*m.group(2, 3, 4)), it_date(*m.group(6, 7, 8))
        if law_date and gu_date:
            out.append({"bill": r["a"], "number": int(m.group(1)), "date": law_date,
                        "gu_number": int(m.group(5)), "gu_date": gu_date})
    return out


def merge_sources(senate: list[dict], camera: list[dict], bill_process: dict[str, str]) -> tuple[list[dict], int]:
    """Laws keyed by URN, each with the process it came from.

    A Chamber row joins the Senate law with its number and the closest date
    (the Camera does not say whether a law is constitutional: 1/2023 is). The
    Camera also marks the bills merged into the law's text (abbinati): they
    sit in processes of their own and are only counted, not linked.
    Returns the laws and the number of such merged bills.
    """
    by_number: dict[int, list[dict]] = defaultdict(list)
    for law in senate:
        law["camera"] = []
        by_number[law["number"]].append(law)
    camera_only: dict[tuple, dict] = {}
    for row in camera:
        near = [law for law in by_number.get(row["number"], [])
                if abs(_days(law["senate_date"], row["date"])) <= DATE_SLACK_DAYS]
        if near:
            min(near, key=lambda law: abs(_days(law["senate_date"], row["date"])))["camera"].append(row)
        else:
            camera_only.setdefault((row["number"], row["date"]), {
                "kind": "legge", "number": row["number"], "senate_date": None, "processes": [],
                "camera": []})["camera"].append(row)
    merged = 0
    out = []
    for law in senate + list(camera_only.values()):
        cam = law.pop("camera")
        first = min(cam, key=lambda r: r["date"]) if cam else None
        law["date"] = first["date"] if first else law["senate_date"]
        law["gu_number"] = first["gu_number"] if first else None
        law["gu_date"] = first["gu_date"] if first else None
        if not law["processes"]:
            # Camera only: the process of the bill whose reading the Senate does not list.
            law["processes"] = sorted({bill_process[r["bill"]] for r in cam if r["bill"] in bill_process})[:1]
        merged += sum(1 for r in cam if bill_process.get(r["bill"]) not in (None, *law["processes"]))
        law["urn"] = urn(law["kind"], law["date"][:4], law["number"])
        out.append(law)
    return out, merged


def parse_normattiva(page: str) -> Optional[dict]:
    """Kind, number, date, title, ELI, codice redazionale and Gazzetta of a Normattiva page."""
    t = NT_TITLE_RE.search(page)
    eli = NT_ELI_RE.search(page)
    code = NT_CODE_RE.search(page)
    if not (t and eli and code):
        return None
    gu = NT_GU_RE.search(page)
    h3 = NT_H3_RE.search(page)
    title = None
    if h3:
        title = " ".join(html.unescape(TAG_RE.sub(" ", h3.group(1))).split())
        title = re.sub(r"\s*\(" + re.escape(code.group(1)) + r"\)\s*$", "", title).rstrip(" .") or None
    return {
        "kind": "legge_costituzionale" if "COSTITUZIONALE" in t.group(1).upper() else "legge",
        "number": int(t.group(5)), "date": it_date(*t.group(2, 3, 4)), "title": title,
        "eli": "https://www.normattiva.it/eli/" + eli.group(1), "code": code.group(1),
        "gu_number": int(gu.group(1)) if gu else None,
        "gu_date": f"{gu.group(4)}-{gu.group(3)}-{gu.group(2)}" if gu else None,
        "gu_supplement": " ".join(gu.group(5).split()) if gu and gu.group(5) else None,
    }


def apply_normattiva(law: dict, nt: Optional[dict]) -> bool:
    """Take Normattiva's fields when the page is the same law; False when it is not."""
    if not nt or nt["kind"] != law["kind"] or nt["number"] != law["number"] or not nt["date"]:
        return False
    # The Senate date may be the Gazzetta date, never earlier than the law.
    if not -1 <= _days(law["date"], nt["date"]) <= DATE_SLACK_DAYS:
        return False
    law.update({k: nt[k] for k in ("date", "title", "eli", "code", "gu_supplement")})
    law["gu_number"] = nt["gu_number"] or law["gu_number"]
    law["gu_date"] = nt["gu_date"] or law["gu_date"]
    return True


def fetch_normattiva(laws: list[dict], cache_path: str, limit: int, delay: float) -> Counter:
    """Fill the laws from Normattiva, from the cache or one request per law."""
    import requests

    cache = json.load(open(cache_path, encoding="utf-8")) if os.path.exists(cache_path) else {}
    http = requests.Session()
    http.headers["User-Agent"] = USER_AGENT
    stats = Counter()
    for law in laws:
        if law["urn"] not in cache:
            if stats["requests"] >= limit:
                stats["over limit"] += 1
                continue
            time.sleep(delay)
            stats["requests"] += 1
            try:
                r = http.get(NORMATTIVA + law["urn"], timeout=60)
                r.raise_for_status()
            except requests.RequestException as exc:
                logger.warning("Normattiva %s: %s", law["urn"], exc)
                stats["failed"] += 1
                continue
            parsed = parse_normattiva(r.text)
            if parsed:
                cache[law["urn"]] = parsed
                if stats["requests"] % 25 == 0:
                    _save(cache, cache_path)
        if apply_normattiva(law, cache.get(law["urn"])):
            stats["verified"] += 1
        else:
            logger.warning("Normattiva: no matching page for %s (%s)", law["urn"], law["date"])
            stats["not found"] += 1
    if stats["requests"]:
        _save(cache, cache_path)
    return stats


def _save(cache: dict, path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    json.dump(cache, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def camera_rows(leg: int, cache_path: str) -> list[dict]:
    """The Chamber bills that mention the Gazzetta, from the SPARQL or yesterday's cache."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from ingest_acts_camera import Sparql

    try:
        rows = Sparql(1.0).select(CAMERA_QUERY.format(leg=leg))
    except RuntimeError as exc:
        if not os.path.exists(cache_path):
            raise
        logger.warning("dati.camera.it unreachable (%s): using %s", exc, os.path.basename(cache_path))
        return json.load(open(cache_path, encoding="utf-8"))
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    json.dump(rows, open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
    return rows


WRITE = """
UNWIND $rows AS row
MATCH (lp:LegislativeProcess {id: row.process})
MERGE (l:Law {urn: row.urn})
SET l.kind = row.kind, l.number = row.number, l.legislature = $leg,
    l.normattiva_url = $normattiva + row.urn
FOREACH (_ IN CASE WHEN row.eli IS NOT NULL OR l.eli IS NULL THEN [1] ELSE [] END |
  SET l.date = date(row.date), l.title = row.title, l.eli = row.eli, l.code = row.code,
      l.gu_number = row.gu_number, l.gu_date = date(row.gu_date), l.gu_supplement = row.gu_supplement)
WITH l, lp
OPTIONAL MATCH (lp)-[old:BECAME_LAW]->(other:Law) WHERE other <> l
DELETE old
MERGE (lp)-[:BECAME_LAW]->(l)
"""


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Laws and their legislative process")
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--senate-csv", help="default data/senato_{roman}_ddl.csv")
    ap.add_argument("--no-normattiva", action="store_true")
    ap.add_argument("--normattiva-limit", type=int, default=500, help="max Normattiva requests per run")
    ap.add_argument("--normattiva-delay", type=float, default=2.0)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    leg, roman = args.legislature, ROMAN[args.legislature]
    phases = list(csv.DictReader(open(args.senate_csv or os.path.join(DATA, f"senato_{roman}_ddl.csv"),
                                      encoding="utf-8")))
    if phases and "numeroLegge" not in phases[0]:
        logger.warning("the Senate CSV has no numeroLegge: rerun download_senate_ddl.py")
    senate, placeholders = senate_laws(phases, leg)
    if placeholders:
        logger.info("laws not yet published (placeholder date): %s",
                    sorted({f"{p['ramo']}.{p['numero']}" for p in placeholders}))
    camera = camera_gazette(camera_rows(leg, os.path.join(DATA, f"camera_{roman}_leggi_gu.json")))

    # Before the first run Law and its properties do not exist: the server's
    # notices about them would land among the WARNING lines of update_data.sh.
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password),
                                  notifications_min_severity="OFF")
    with driver.session() as s:
        bill_process = {r["uri"]: r["lp"] for r in s.run(
            "MATCH (a:Bill)-[:PART_OF]->(lp:LegislativeProcess {legislature: $leg}) "
            "RETURN a.uri AS uri, lp.id AS lp", leg=leg)}
        known = {r["id"] for r in s.run(
            "MATCH (lp:LegislativeProcess {legislature: $leg}) RETURN lp.id AS id", leg=leg)}
        with_eli = {r["urn"] for r in s.run("MATCH (l:Law) WHERE l.eli IS NOT NULL RETURN l.urn AS urn")}
        laws, merged = merge_sources(senate, camera, bill_process)
        if not args.no_normattiva:
            todo = [law for law in laws if law["urn"] not in with_eli]
            stats = fetch_normattiva(todo, os.path.join(DATA, f"normattiva_{roman}_leggi.json"),
                                     args.normattiva_limit, args.normattiva_delay)
            logger.info("Normattiva: %d laws without ELI in the graph, %s", len(todo), dict(stats))
        rows, unlinked = [], []
        for law in laws:
            process = next((p for p in law["processes"] if p in known), None)
            if not process:
                unlinked.append(law["urn"])
                continue
            rows.append({k: law.get(k) for k in ("urn", "kind", "number", "date", "title", "eli", "code",
                                                  "gu_number", "gu_date", "gu_supplement")}
                        | {"process": process})
        if not args.dry_run:
            s.run("CREATE CONSTRAINT law_urn IF NOT EXISTS FOR (l:Law) REQUIRE l.urn IS UNIQUE").consume()
            for i in range(0, len(rows), 500):
                s.run(WRITE, rows=rows[i:i + 500], leg=leg, normattiva=NORMATTIVA).consume()
            # A law whose URN changed (a date corrected by a later source) leaves its old node behind.
            gone = s.run("MATCH (l:Law {legislature: $leg}) WHERE NOT ()-[:BECAME_LAW]->(l) "
                         "DETACH DELETE l RETURN count(*) AS n", leg=leg).single()["n"]
            if gone:
                logger.info("Law nodes without a process removed: %d", gone)
    driver.close()
    logger.info("laws: %d from the Senate, %d from the Camera's Gazzetta notes on %d bills; %d to write%s",
                len(senate), len({(r["number"], r["date"]) for r in camera}), len(camera), len(rows),
                " (dry run)" if args.dry_run else "")
    logger.info("by kind and year: %s", dict(sorted(Counter((r["kind"], r["date"][:4]) for r in rows).items())))
    logger.info("Chamber bills merged into a law's text, not linked: %d", merged)
    if unlinked:
        logger.warning("laws whose process is not in the graph: %s", unlinked)
    return 0


if __name__ == "__main__":
    sys.exit(main())
