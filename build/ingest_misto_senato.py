#!/usr/bin/env python3
"""
ingest_misto_senato.py — componenti politiche del Gruppo Misto del Senato (leg. 19).

Come alla Camera (build/ingest_misto_componenti.py), il Misto del Senato
raccoglie senatori di partiti diversi: Alleanza Verdi e Sinistra (Cucchi,
De Cristofaro, Magni), Azione (Calenda, Lombardo), Avanti PSI (Nave) e i
senatori a vita senza componente. Senza la componente un discorso di Cucchi
finisce sotto il «Misto» invece che sotto AVS.

dati.senato.it non pubblica le componenti: la fonte è la pagina «Composizione
storica» del Gruppo Misto su senato.it (una sola richiesta, dietro il WAF AWS:
la apre Chromium headless con Playwright). Ogni riga ha la sigla della
componente con le date («AVS dal 24 ottobre 2022», «Az fino al 17 settembre
2024») e l'ingresso/uscita dal gruppo; in fondo la legenda delle componenti.

Date di un'adesione: inizio = la più tarda tra «dal …», ingresso nel gruppo e
costituzione della componente; fine = «fino al …»/«al …», altrimenti uscita
dal gruppo, altrimenti aperta.

Schema scritto (lo stesso della Camera, con chamber = 'senato'):
  (:MistoComponent {uri, name, short_name, chamber, legislature, start_date})
  (Senator)-[:MEMBER_OF_COMPONENT {start_date, end_date, chamber, source}]->(:MistoComponent)
  Senator.misto_page_seen = data dell'ultimo giro in cui la pagina lo elencava

Idempotente (MERGE). Exit 3 = senato.it rifiuta la richiesta (WAF), come gli
altri passi di update_senato.sh: si riprova al giro dopo con l'ultima pagina
scaricata, se c'è.

Usage:
    build/ingest_misto_senato.py --neo4j-uri bolt://localhost:7692 [--offline]
"""

from __future__ import annotations

import argparse
import html as html_lib
import logging
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from ingest_misto_componenti import display_case

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / "data" / "senate_misto"
# did=9 = Gruppo Misto della XIX legislatura
PAGE_URL = ("https://www.senato.it/composizione/gruppi-parlamentari/riepilogo-della-composizione/"
            "composizione?did=9&tipo=storica")
LEGISLATURE = 19

# Sigla della pagina → componente, solo dove il nome della legenda non basta:
# il nome è quello che il backend e il verificatore riconducono al partito (AVS
# e Azione hanno un gruppo alla Camera); la sigla più vecchia fa da chiave
# stabile dell'URI. Le componenti nuove della legenda entrano da sole (vedi
# component_for), senza toccare questa tabella.
COMPONENTS: Dict[str, Dict[str, str]] = {
    "AVS": {"key": "AVS", "name": "Alleanza Verdi e Sinistra", "short_name": "AVS"},
    "Az": {"key": "Az", "name": "Azione-Renew Europe", "short_name": "Az-RE"},
    "Az-RE": {"key": "Az", "name": "Azione-Renew Europe", "short_name": "Az-RE"},
    "Avanti PSI": {"key": "Avanti-PSI", "name": "Avanti PSI", "short_name": "Avanti PSI"},
}

MONTHS = {m: i for i, m in enumerate(
    ["gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio",
     "agosto", "settembre", "ottobre", "novembre", "dicembre"], start=1)}
_DATE = r"(\d{1,2})[º°]?\s+([a-zà]+)\s+(\d{4})"


def parse_it_date(text: str) -> Optional[str]:
    m = re.search(_DATE, text, re.IGNORECASE)
    if not m or m.group(2).lower() not in MONTHS:
        return None
    return date(int(m.group(3)), MONTHS[m.group(2).lower()], int(m.group(1))).isoformat()


def component_uri(key: str) -> str:
    return f"{PAGE_URL}#{key}"


def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_page() -> Optional[str]:
    """The «Composizione storica» page via headless Chromium, or None if the WAF refuses it."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("playwright non installato: pip install playwright && playwright install chromium")
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_context(locale="it-IT").new_page()
            page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60_000)
            # The WAF challenge solves itself and reloads into the real page
            page.wait_for_selector("text=Componenti partitiche", timeout=45_000)
            time.sleep(1)
            content = page.content()
            browser.close()
        return content
    except Exception as exc:
        logger.error("senato.it non ha servito la pagina del Gruppo Misto: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse_legend(page: str) -> Dict[str, Dict[str, Optional[str]]]:
    """Sigla → {name, constituted, base}, from «Componenti partitiche del Gruppo Misto».

    Each component is «<strong>Nome (Sigla)</strong> <span>costituita il …</span>»,
    followed by its renames («dal … muta la sigla in <strong>Az-RE</strong>»).
    A renamed sigla points to the first one (``base``), which keys the URI.
    """
    i = page.find("Componenti partitiche")
    if i < 0:
        raise ValueError("pagina senza «Componenti partitiche del Gruppo Misto»")
    legend = page[i:page.find("</div>", i)]
    titles = list(re.finditer(r"<strong>([^<]*)</strong>\s*<span>(.*?)</span>", legend, re.S))
    out: Dict[str, Dict[str, Optional[str]]] = {}
    for n, m in enumerate(titles):
        title, when = _text(m.group(1)), _text(m.group(2))
        sm = re.search(r"^(.*?)\s*\(([^()]+)\)\s*$", title)
        if not sm:
            continue
        sigla = sm.group(2).strip()
        out[sigla] = {"name": sm.group(1).strip() or sigla, "constituted": parse_it_date(when), "base": sigla}
        tail = legend[m.end():titles[n + 1].start() if n + 1 < len(titles) else len(legend)]
        # «muta la sigla in <strong>Az-RE</strong>» (until 10/2026) or «la
        # denominazione muta in <strong>Nome</strong> (<strong>SIGLA</strong>)»
        for r in re.finditer(r"muta (?:la sigla )?in\s*<strong>([^<]*)</strong>"
                             r"(?:\s*\(\s*<strong>([^<]*)</strong>\s*\))?", tail, re.S):
            name, renamed = (_text(r.group(1)), _text(r.group(2))) if r.group(2) else (None, _text(r.group(1)))
            out.setdefault(renamed, {"name": name, "constituted": None, "base": sigla})
    return out


def component_for(sigla: str, legend: Dict[str, Dict[str, Optional[str]]]) -> Optional[Dict[str, str]]:
    """The component of a row's sigla: COMPONENTS first, then the page legend.

    The legend chain of a component (first sigla and its renames) is looked up
    in COMPONENTS by sigla, then by name: senato.it changes sigle («Avanti PSI»
    became «A-PSI» on 23/10/2026) and the URI must not. A component the table
    does not know is built from the legend (latest name and sigla, URI key from
    the first sigla), so a new one needs no code change. None when the sigla
    is not in the legend either.
    """
    if sigla in COMPONENTS:
        return COMPONENTS[sigla]
    entry = legend.get(sigla)
    if entry is None:
        return None
    base = entry["base"] or sigla
    chain = [s for s, e in legend.items() if e["base"] == base]
    for s in chain:
        if s in COMPONENTS:
            return COMPONENTS[s]
    names = {legend[s]["name"].casefold() for s in chain if legend[s]["name"]}
    for comp in COMPONENTS.values():
        if comp["name"].casefold() in names:
            return comp
    name = next((legend[s]["name"] for s in reversed(chain) if legend[s]["name"]), base)
    if name.isupper():
        name = display_case(name)
    return {"key": re.sub(r"\s+", "-", base), "name": name, "short_name": chain[-1]}


def parse_rows(page: str) -> List[Dict[str, Optional[str]]]:
    """One entry per (senator, component span) found in the table rows.

    A senator appears once per office (Presidente, Vicepresidente, Tesoriere,
    member): spans are deduplicated by the caller.
    """
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        link = re.search(r"scheda-attivita\?did=(\d+)\">\s*(.*?)\s*</a>", tr, re.S)
        if not link or len(tds) < 2:
            continue
        did, name = link.group(1), _text(link.group(2))
        group_info = _text(tds[1])
        entered = re.search(r"Entra nel gruppo (?:il |l')\s*" + _DATE, group_info, re.I)
        left = re.search(r"Esce dal gruppo (?:il |l')\s*" + _DATE, group_info, re.I)
        entered = parse_it_date(entered.group(0)) if entered else None
        left = parse_it_date(left.group(0)) if left else None
        for span in re.findall(r"<span>(.*?)</span>", tds[0], re.S):
            text = _text(span)
            if not text:
                continue
            m = re.match(r"(.+?)(?:\s+(dal|fino al|al)\s.*)?$", text)
            sigla = m.group(1).strip()
            since = re.search(r"\bdal\s+" + _DATE, text)
            until = re.search(r"\b(?:fino al|al)\s+" + _DATE, text)
            rows.append({
                "did": did, "name": name, "sigla": sigla,
                "since": parse_it_date(since.group(0)) if since else None,
                "until": parse_it_date(until.group(0)) if until else None,
                "entered": entered, "left": left,
            })
    return rows


def memberships(page: str) -> List[Dict[str, Optional[str]]]:
    legend = parse_legend(page)
    out: Dict[tuple, Dict[str, Optional[str]]] = {}
    new: set = set()
    for r in parse_rows(page):
        comp = component_for(r["sigla"], legend)
        if comp is None:
            logger.warning("Sigla fuori dalla legenda per %s: %r (ignorata)", r["name"], r["sigla"])
            continue
        if r["sigla"] not in COMPONENTS and r["sigla"] not in new:
            new.add(r["sigla"])
            logger.info("Componente dalla legenda: %r → %s", r["sigla"], comp["name"])
        base = (legend.get(r["sigla"]) or {}).get("base") or r["sigla"]
        constituted = (legend.get(r["sigla"]) or {}).get("constituted") or (legend.get(base) or {}).get("constituted")
        start = max(d for d in (r["since"], r["entered"], constituted) if d) if any(
            (r["since"], r["entered"], constituted)) else None
        if start is None:
            raise ValueError(f"nessuna data d'inizio per {r['name']} ({r['sigla']})")
        end = r["until"] or r["left"]
        key = (r["did"], comp["key"], start)
        prev = out.get(key)
        # The same senator appears as office holder and as member: keep the
        # most informative span (an end date wins over none).
        if prev is None or (end and not prev["end_date"]):
            out[key] = {"senato_id": f"http://dati.senato.it/senatore/{r['did']}", "name": r["name"],
                        "comp_key": comp["key"], "comp_uri": component_uri(comp["key"]),
                        "comp_name": comp["name"], "comp_short": comp["short_name"],
                        "comp_start": (legend.get(base) or {}).get("constituted") or constituted,
                        "start_date": start, "end_date": end}
    return list(out.values())


# ---------------------------------------------------------------------------
# Write
# ---------------------------------------------------------------------------

WRITE = """
UNWIND $rows AS row
MATCH (p:Senator {senato_id: row.senato_id})
MERGE (c:MistoComponent {uri: row.comp_uri})
SET c.name = row.comp_name, c.short_name = row.comp_short, c.chamber = 'senato',
    c.legislature = $legislature,
    c.start_date = CASE WHEN row.comp_start IS NULL THEN c.start_date ELSE date(row.comp_start) END
MERGE (p)-[m:MEMBER_OF_COMPONENT {start_date: date(row.start_date)}]->(c)
SET m.end_date = CASE WHEN row.end_date IS NULL THEN null ELSE date(row.end_date) END,
    m.chamber = 'senato', m.legislature = $legislature, m.source = $source
RETURN row.senato_id AS sid
"""


# Every senator the page lists, with or without a component (senators for
# life): validate_db tells a member the source has not seen yet from one
# without a component.
MARK_SEEN = """
UNWIND $ids AS sid
MATCH (p:Senator {senato_id: sid})
SET p.misto_page_seen = date()
"""


def page_senators(page: str) -> List[str]:
    return sorted({f"http://dati.senato.it/senatore/{d}"
                   for d in re.findall(r"scheda-attivita\?did=(\d+)", page)})


def write(driver, rows: List[Dict[str, Optional[str]]], seen: List[str]) -> int:
    with driver.session() as s:
        linked = {r["sid"] for r in s.run(WRITE, rows=rows, legislature=LEGISLATURE, source=PAGE_URL)}
        s.run(MARK_SEEN, ids=seen).consume()
    missing = sorted({r["name"] for r in rows if r["senato_id"] not in linked})
    if missing:
        logger.warning("Senatori senza nodo :Senator (non collegati): %s", ", ".join(missing))
    return len(rows) - len(missing)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--offline", action="store_true", help="usa l'ultima pagina scaricata")
    ap.add_argument("--dry-run", action="store_true", help="stampa le adesioni senza scrivere")
    args = ap.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / "composizione_storica.html"
    blocked = False
    page = None if args.offline else download_page()
    if page:
        cached.write_text(page, encoding="utf-8")
    elif not args.offline:
        blocked = True
    if page is None and cached.exists():
        logger.info("Uso la pagina in cache %s", cached)
        page = cached.read_text(encoding="utf-8")
    if page is None:
        logger.error("Nessuna pagina del Gruppo Misto disponibile")
        return 3 if blocked else 1

    rows = memberships(page)
    for r in sorted(rows, key=lambda r: (r["comp_key"], r["name"])):
        logger.info("%-22s %-12s %s → %s", r["name"], r["comp_short"], r["start_date"], r["end_date"] or "")
    if args.dry_run:
        return 3 if blocked else 0

    if not args.neo4j_password:
        logger.error("Manca la password Neo4j (--neo4j-password o NEO4J_PASSWORD)")
        return 1
    from neo4j import GraphDatabase
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        n = write(driver, rows, page_senators(page))
    finally:
        driver.close()
    logger.info("Componenti del Misto del Senato: %d adesioni scritte su %d", n, len(rows))
    return 3 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
