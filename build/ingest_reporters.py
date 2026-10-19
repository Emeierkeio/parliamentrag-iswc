#!/usr/bin/env python3
"""
Rapporteurs (relatori) of the bills of both chambers.

  (:Bill)-[:REPORTED_BY {role, roles_raw, date, venues, committee, source,
                         sources, attested, session}]->(:Person)

One relationship per bill and person, whatever the number of sources. role is
the strongest standing any source gives the person on the bill: minoranza >
maggioranza > relatore > facente_funzione > sostituto. A plain "relatore" is
the only rapporteur, so he speaks for the committee majority, as the
transcripts' "Relatore" label does. attested keeps "source:role" per source;
source is the first of sources in the order dati.camera.it, dati.senato.it,
scheda_camera, resoconto.

Camera (dati.camera.it, one SPARQL query per field): ocd:rif_relatore of each
ocd:atto, with dc:type "maggioranza"/"minoranza" or none. The record names
the deputy only in its label ("SCHIFONE Marta, relatore per la maggioranza"),
matched to the XIX deputies by surname and first name; no nomination date.
committee is the committee the bill was assigned to in sede referente.

Senato (dati.senato.it, one query, cached in data/senato_{roman}_relatori.csv):
osr:relatore of each Ddl of the Senate branch, with the senator's URI,
tipoRelatore (relatore, facente funzione, sostituto), diMinoranza, organo
(commissione, assemblea) and dataNomina; date is the first nomination.
Exit 3 = dati.senato.it refused the request.

Camera, --source scheda (www.camera.it/leg19/126?idDocumento=N, cached in
data/camera_{roman}_relatori_schede.json): the minority rapporteurs and the
stand-ins on the floor that dati.camera.it leaves out (C. 750, C. 2822-B).
Only bills with a rapporteur or a floor debate, at most --max-pages a run,
new or changed ones first. Exit 3 = camera.it stopped answering.

--source resoconto (both chambers, no network): a speaker labelled
"Relatore ..." in a debate that discusses a bill, with no edge from the other
sources on it, gets one with the side of the label (sostituto when there is
none) and the session; a listed rapporteur with no side gets the label's.

Idempotent: MERGE on (bill, person); each source replaces only its own
entries, and scheda and resoconto withdraw the ones they no longer give.

    python build/ingest_reporters.py --neo4j-uri bolt://... --chamber camera|senato \\
        [--source opendata|scheda|resoconto] [--dry-run]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import html
import json
import logging
import os
import re
import sys
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

import requests
from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_acts_camera import VIRTUOSO_CAP, Sparql  # noqa: E402

logger = logging.getLogger("ingest_reporters")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "xviii", 19: "xix"}
LEG_URI = "<http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}>"

ROLE_RANK = {"minoranza": 5, "maggioranza": 4, "relatore": 3, "facente_funzione": 2, "sostituto": 1}

CAMERA_REPORTERS = """
SELECT DISTINCT ?a ?r ?label ?type WHERE {{
  ?a a ocd:atto ; ocd:rif_leg {leg} ; ocd:rif_relatore ?r .
  OPTIONAL {{ ?r rdfs:label ?label }} OPTIONAL {{ ?r dc:type ?type }}
}}"""

CAMERA_COMMITTEES = """
SELECT DISTINCT ?a ?committee WHERE {{
  ?a a ocd:atto ; ocd:rif_leg {leg} ; ocd:rif_relatore ?r ; ocd:rif_assegnazione ?as .
  ?as ocd:sede ?sede ; ocd:rif_organo ?o . ?o rdfs:label ?committee .
  FILTER(LCASE(STR(?sede)) = "referente")
}}"""

SENATE_REPORTERS = """PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?ddl ?sen ?label ?tipo ?min ?data ?organo WHERE {{
  ?ddl a osr:Ddl ; osr:legislatura {leg} ; osr:ramo ?ramo ; osr:relatore ?r .
  FILTER(str(?ramo) = "S")
  OPTIONAL {{ ?r osr:senatore ?sen }} OPTIONAL {{ ?r rdfs:label ?label }}
  OPTIONAL {{ ?r osr:tipoRelatore ?tipo }} OPTIONAL {{ ?r osr:diMinoranza ?min }}
  OPTIONAL {{ ?r osr:dataNomina ?data }} OPTIONAL {{ ?r osr:organo ?organo }}
}}"""

SENATE_FIELDS = ["ddl", "sen", "label", "tipo", "min", "data", "organo"]


def fold(text: Optional[str]) -> str:
    """Upper case, no accents, apostrophes and hyphens as spaces, single spaces."""
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().upper()
    return " ".join(re.sub(r"['’`\-.]", " ", t).split())


def split_camera_label(label: Optional[str]) -> Optional[tuple[str, str]]:
    """('SCHIFONE', 'MARTA') from 'SCHIFONE Marta, relatore per la maggioranza'.

    The surname is the run of upper-case words before the first name.
    """
    name = (label or "").split(",")[0].strip()
    words = name.split()
    i = 0
    while i < len(words) and words[i] == words[i].upper() and any(c.isalpha() for c in words[i]):
        i += 1
    if i == 0 or i == len(words):
        return None
    return fold(" ".join(words[:i])), fold(" ".join(words[i:]))


def match_deputy(name: tuple[str, str], deputies: dict[tuple[str, str], str]) -> Optional[str]:
    """Person id of a deputy from a folded (surname, first name); None when unknown or ambiguous.

    The registry and the rapporteur records disagree on second names, short
    first names and double surnames ("IEZZI Igor" is IEZZI IGOR GIANCARLO,
    "AMICH Enzo" AMICH VINCENZO, "SACCANI JOTTI Gloria" SACCANI GLORIA): a
    looser match is accepted only when it points to one deputy.
    """
    if name in deputies:
        return deputies[name]
    last, first = name
    same_surname = {pid for (cl, _), pid in deputies.items() if cl == last}
    if len(same_surname) == 1:
        return same_surname.pop()
    first_words = set(first.split())

    def compatible(cand_last: str, cand_first: str) -> bool:
        surname_ok = cand_last == last or (cand_last + " ").startswith(last + " ") \
            or (last + " ").startswith(cand_last + " ")
        return surname_ok and bool(first_words & set(cand_first.split()))

    found = {pid for (cl, cf), pid in deputies.items() if compatible(cl, cf)}
    return found.pop() if len(found) == 1 else None


def camera_role(rtype: Optional[str], label: Optional[str]) -> str:
    t = (rtype or "").strip().lower()
    if t in ("maggioranza", "minoranza"):
        return t
    low = (label or "").lower()
    if "minoranza" in low:
        return "minoranza"
    if "maggioranza" in low:
        return "maggioranza"
    return "relatore"


def senate_role(tipo: Optional[str], minority: Optional[str]) -> str:
    if (minority or "").strip() in ("1", "true"):
        return "minoranza"
    t = (tipo or "").strip().lower()
    if t.startswith("facente"):
        return "facente_funzione"
    if t.startswith("sostitut"):
        return "sostituto"
    return "relatore"


def merge_reports(records: list[dict]) -> list[dict]:
    """One row per (bill, person): strongest role, all raw roles, first date, venues."""
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in records:
        grouped[(r["bill"], r["person"])].append(r)
    out = []
    for (bill, person), rs in sorted(grouped.items()):
        roles = sorted({r["role"] for r in rs}, key=lambda x: -ROLE_RANK[x])
        dates = sorted(r["date"] for r in rs if r.get("date"))
        venues = sorted({r["venue"] for r in rs if r.get("venue")})
        committees = sorted({r["committee"] for r in rs if r.get("committee")})
        sessions = sorted((r.get("date") or "", r["session"]) for r in rs if r.get("session"))
        out.append({
            "bill": bill, "person": person, "role": roles[0], "roles_raw": roles,
            "date": dates[0] if dates else None, "venues": venues or None,
            "committee": "; ".join(committees) or None, "source": rs[0]["source"],
            "session": sessions[0][1] if sessions else None,
        })
    return out


# ---------------------------------------------------------------------------
# Camera
# ---------------------------------------------------------------------------

def camera_records(sp: Sparql, leg: int, deputies: dict[tuple[str, str], str],
                   bills: set[str], stats: Counter) -> list[dict]:
    rows = sp.select(CAMERA_REPORTERS.format(leg=LEG_URI.format(leg=leg)))
    if len(rows) >= VIRTUOSO_CAP:
        raise RuntimeError("relatori della Camera oltre il limite di righe: dividere la query")
    committees: dict[str, set[str]] = defaultdict(set)
    for r in sp.select(CAMERA_COMMITTEES.format(leg=LEG_URI.format(leg=leg))):
        committees[r["a"]].add(" ".join(r["committee"].split()))
    out = []
    for r in rows:
        stats["camera_source_rows"] += 1
        if r["a"] not in bills:
            stats["camera_bill_missing"] += 1
            continue
        name = split_camera_label(r.get("label"))
        person = match_deputy(name, deputies) if name else None
        if person and name not in deputies:
            stats["camera_loose_match"] += 1
            logger.info("relatore %r -> %s", r.get("label"), person)
        if not person:
            stats["camera_person_missing"] += 1
            logger.warning("relatore non trovato tra i deputati: %r (%s)", r.get("label"), r["a"])
            continue
        out.append({"bill": r["a"], "person": person, "role": camera_role(r.get("type"), r.get("label")),
                    "date": None, "venue": None,
                    "committee": "; ".join(sorted(committees.get(r["a"], ()))) or None,
                    "source": "dati.camera.it"})
    return out


# ---------------------------------------------------------------------------
# Camera: bill pages on camera.it
# ---------------------------------------------------------------------------

SCHEDA_URL = "https://www.camera.it/leg{leg}/126?leg={leg}&idDocumento={number}"
PERSON_URI = "http://dati.camera.it/ocd/persona.rdf/p{}"
USER_AGENT = "ParliamentRAG-reporters/1.0 (+https://www.parliamentrag.it)"

_RELATORI_DIV = re.compile(r'<div class="relatori">(.*?)</div>\s*</div>', re.S)
_VENUE_DIV = re.compile(r'<div class="(inCommissione|inAssemblea)">(.*?)(?=<div class="in|\Z)', re.S)
_LI = re.compile(r"<li>(.*?)</li>", re.S)
_PERSON_LINK = re.compile(r'idPersona=(\d+)"[^>]*>([^<]+)</a>')
# An intervention in the iter: "<a ...idPersona=..>NAME</a></span> (GROUP)<em>, LABEL</em> pag. <a href=..sezione=..>"
_SPEAKER = re.compile(r'idPersona=(\d+)"[^>]*>([^<]+)</a></span>\s*(?:\([^)<]*\))?\s*<em>,\s*([^<]+)</em>'
                      r'[^<]*<a href="[^"]*?sezione=(\w+)')


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_scheda(page: str) -> dict:
    """Rapporteurs listed on a camera.it bill page, as found, before any mapping to roles.

    header: the "Relatori in Commissione / in Assemblea" box, each entry with
    the note in brackets ("per la maggioranza", "per la Commissione I ...").
    aula: the labels the floor transcripts give to speakers ("Relatore di
    minoranza", "Relatore per la commissione"), from the iter's list of
    speeches in the Assembly; committee bulletins are left out because
    their "Relatore per la commissione" also names the rapporteurs of the
    advisory opinions.
    """
    header = []
    box = _RELATORI_DIV.search(page)
    if box:
        for venue_class, body in _VENUE_DIV.findall(box.group(1)):
            venue = "commissione" if venue_class == "inCommissione" else "assemblea"
            for li in _LI.findall(body):
                link = _PERSON_LINK.search(li)
                if not link:
                    continue
                note = _text(li[link.end():]).strip(" ()")
                header.append({"venue": venue, "pid": link.group(1), "name": _text(link.group(2)), "note": note})
    aula = []
    seen = set()
    for pid, name, label, section in _SPEAKER.findall(page):
        label = _text(label)
        if section != "assemblea" or not label.lower().startswith("relat"):
            continue
        if (pid, label) not in seen:
            seen.add((pid, label))
            aula.append({"pid": pid, "name": _text(name), "label": label})
    return {"header": header, "aula": aula}


def scheda_roles(parsed: dict) -> list[dict]:
    """(pid, name, role, venue) of each rapporteur of one bill page.

    Header entries are the appointed rapporteurs; a floor label of someone
    the header does not list marks a stand-in ("Relatore per la commissione"
    spoken by a member of the committee in place of the rapporteur).
    """
    out = []
    listed = {h["pid"] for h in parsed["header"]}
    # The floor list marks only the majority side: next to "SCHIFONE Marta
    # (per la maggioranza)" the minority rapporteurs carry no note (C. 1275).
    split_floor = any("maggioranza" in h["note"].lower() for h in parsed["header"] if h["venue"] == "assemblea")
    for h in parsed["header"]:
        note = h["note"].lower()
        role = "minoranza" if "minoranza" in note else "maggioranza" if "maggioranza" in note else "relatore"
        if role == "relatore" and split_floor and h["venue"] == "assemblea":
            role = "minoranza"
        out.append({"pid": h["pid"], "name": h["name"], "role": role, "venue": h["venue"]})
    for a in parsed["aula"]:
        low = a["label"].lower()
        if "minoranza" in low:
            role = "minoranza"
        elif "maggioranza" in low:
            role = "maggioranza"
        elif "f.f." in low or "facente" in low:
            role = "facente_funzione"
        elif a["pid"] in listed:
            role = "relatore"
        else:
            role = "sostituto"
        out.append({"pid": a["pid"], "name": a["name"], "role": role, "venue": "assemblea"})
    return out


def load_cache(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_cache(cache: dict, path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)
    os.replace(tmp, path)


def pages_to_fetch(bills: list[dict], cache: dict, limit: int) -> list[dict]:
    """Bills whose page is not cached or may have changed since it was read.

    A page changes when the record on dati.camera.it does (source_modified)
    or the bill gets a new floor debate; debated bills go first, newest first.
    """
    todo = []
    for b in bills:
        hit = cache.get(b["number"])
        if hit is None:
            todo.append(b)
            continue
        fetched = hit["fetched_at"]
        if (b.get("modified") or "") > fetched or (b.get("last_debate") or "") >= fetched[:10]:
            todo.append(b)
    todo.sort(key=lambda b: b.get("last_debate") or "", reverse=True)
    return todo[:limit]


def fetch_pages(todo: list[dict], cache: dict, path: str, leg: int, delay: float,
                raw_dir: Optional[str], stats: Counter) -> None:
    """Read the bill pages in todo into the cache, saved every 20 pages.

    camera.it answered 503 to one session for minutes while a fresh
    connection loaded the same page (19/10/2026, cause unknown): a failure
    drops the session and the page is tried again after a longer pause;
    five failures in a row stop the run.
    """
    http = requests.Session()
    http.headers.update({"User-Agent": USER_AGENT})
    failures = 0
    queue = list(todo)
    first = True
    while queue:
        b = queue[0]
        if not first:
            time.sleep(delay if failures == 0 else 60 * failures)
        first = False
        url = SCHEDA_URL.format(leg=leg, number=b["number"])
        try:
            r = http.get(url, timeout=60)
            if r.status_code != 200:
                raise requests.HTTPError(f"HTTP {r.status_code}")
        except requests.RequestException as exc:
            failures += 1
            stats["scheda_fetch_error"] += 1
            http.close()
            http = requests.Session()
            http.headers.update({"User-Agent": USER_AGENT})
            logger.warning("scheda %s non letta: %s", b["number"], exc)
            if failures >= 5:
                logger.warning("camera.it non risponde: mi fermo")
                stats["scheda_refused"] += 1
                break
            continue
        failures = 0
        queue.pop(0)
        done = len(todo) - len(queue)
        stats["scheda_fetched"] += 1
        if "Atto Camera" not in r.text:
            stats["scheda_not_a_bill_page"] += 1
            logger.warning("scheda %s: la pagina non descrive un atto", b["number"])
            continue
        if raw_dir:
            with gzip.open(os.path.join(raw_dir, f"{b['number']}.html.gz"), "wt", encoding="utf-8") as f:
                f.write(r.text)
        parsed = parse_scheda(r.text)
        if not parsed["header"] and not parsed["aula"]:
            stats["scheda_without_reporters"] += 1
        cache[b["number"]] = {"fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                              "uri": b["uri"], **parsed}
        if done % 20 == 0:
            save_cache(cache, path)
            logger.info("schede lette: %d/%d", done, len(todo))
    save_cache(cache, path)


def scheda_records(cache: dict, bills: set[str], deputies: dict[tuple[str, str], str],
                   deputy_ids: set[str], stats: Counter) -> list[dict]:
    """REPORTED_BY rows from the cached bill pages.

    The page links each rapporteur to his camera.it person id, the same
    number as the deputy's dati.camera.it URI; the name is the fallback.
    """
    out = []
    for number, page in sorted(cache.items()):
        if page["uri"] not in bills:
            stats["scheda_bill_missing"] += 1
            continue
        for r in scheda_roles(page):
            person = PERSON_URI.format(r["pid"])
            if person not in deputy_ids:
                name = split_camera_label(r["name"])
                person = match_deputy(name, deputies) if name else None
            if not person:
                stats["scheda_person_missing"] += 1
                logger.warning("relatore della scheda %s non trovato tra i deputati: %r", number, r["name"])
                continue
            out.append({"bill": page["uri"], "person": person, "role": r["role"], "date": None,
                        "venue": r["venue"], "committee": None, "source": "scheda_camera"})
    return out


# ---------------------------------------------------------------------------
# Senato
# ---------------------------------------------------------------------------

def download_senate(leg: int, path: str) -> list[dict]:
    from senate_sparql_ingester import _senato_sparql_get
    bindings = _senato_sparql_get(SENATE_REPORTERS.format(leg=leg), strict=True)
    if len(bindings) >= 10000:
        raise RuntimeError("relatori del Senato oltre il limite di righe: dividere la query")
    rows = [{k: b.get(k, {}).get("value", "") for k in SENATE_FIELDS} for b in bindings]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SENATE_FIELDS)
        w.writeheader()
        w.writerows(rows)
    logger.info("%d righe -> %s", len(rows), os.path.basename(path))
    return rows


def senate_records(rows: list[dict], senators: dict[str, str], bills: set[str], stats: Counter) -> list[dict]:
    out = []
    for r in rows:
        stats["senato_source_rows"] += 1
        if r["ddl"] not in bills:
            stats["senato_bill_missing"] += 1
            continue
        person = senators.get(r.get("sen") or "")
        if not person:
            stats["senato_person_missing"] += 1
            logger.warning("relatore non trovato tra i senatori: %r (%s)", r.get("label"), r["ddl"])
            continue
        out.append({"bill": r["ddl"], "person": person, "role": senate_role(r.get("tipo"), r.get("min")),
                    "date": (r.get("data") or "")[:10] or None, "venue": r.get("organo") or None,
                    "committee": None, "source": "dati.senato.it"})
    return out


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

# Sources in order of precedence: r.source is the first one that attests the edge.
SOURCES = ["dati.camera.it", "dati.senato.it", "scheda_camera", "resoconto"]
ROLE_ORDER = sorted(ROLE_RANK, key=lambda x: -ROLE_RANK[x])
# Retractions above this many edges in one run point to a broken source, not to real changes.
MAX_RETRACT = 50

# r.attested holds "source:role" for each role a source gives the edge. Every
# source rewrites only its own entries, so the steps commute and rerun safely;
# role, roles_raw, sources and source are derived from it. Edges written
# before attested existed are read back from source and roles_raw.
_PREV = """CASE WHEN r.attested IS NULL AND r.source IS NOT NULL
     THEN [x IN coalesce(r.roles_raw, [r.role]) | r.source + ':' + x]
     ELSE coalesce(r.attested, []) END"""

_DERIVE = """
SET r.attested = att,
    r.roles_raw = [x IN $roles WHERE any(a IN att WHERE a ENDS WITH ':' + x)],
    r.sources = [s IN $sources WHERE any(a IN att WHERE a STARTS WITH s + ':')]
SET r.role = head(r.roles_raw), r.source = head(r.sources)
"""

WRITE = """
UNWIND $rows AS row
MATCH (b:ParliamentaryAct {uri: row.bill}) WHERE b:Bill
MATCH (p:Person {id: row.person})
MERGE (b)-[r:REPORTED_BY]->(p)
WITH r, row, """ + _PREV + """ AS prev
WITH r, row, [a IN prev WHERE NOT a STARTS WITH row.source + ':']
             + [x IN row.roles_raw | row.source + ':' + x] AS att
""" + _DERIVE + """
FOREACH (_ IN CASE WHEN row.source STARTS WITH 'dati.' THEN [1] ELSE [] END |
  SET r.venues = row.venues, r.committee = row.committee,
      r.date = CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END)
FOREACH (_ IN CASE WHEN row.source STARTS WITH 'dati.' THEN [] ELSE [1] END |
  SET r.venues = coalesce(r.venues, row.venues), r.committee = coalesce(r.committee, row.committee),
      r.date = coalesce(r.date, CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END))
FOREACH (_ IN CASE WHEN row.session IS NULL THEN [] ELSE [1] END | SET r.session = row.session)
"""

# Edges of $source, in scope, that the source no longer gives.
_STALE = """
MATCH (b:Bill {chamber: $chamber})-[r:REPORTED_BY]->(p:Person)
WHERE ($bills IS NULL OR b.uri IN $bills)
  AND any(a IN coalesce(r.attested, []) WHERE a STARTS WITH $source + ':')
  AND NOT b.uri + '|' + p.id IN $keep
WITH b, p, r, [a IN r.attested WHERE NOT a STARTS WITH $source + ':'] AS att
"""
STALE_COUNT = _STALE + "RETURN b.number AS bill, p.id AS person, size(att) = 0 AS orphan"
RETRACT = _STALE + """
FOREACH (_ IN CASE WHEN size(att) = 0 THEN [1] ELSE [] END | DELETE r)
WITH r, att WHERE size(att) > 0
""" + _DERIVE + """
FOREACH (_ IN CASE WHEN $source = 'resoconto' THEN [1] ELSE [] END | REMOVE r.session)
"""


def write_records(session, merged: list[dict], source: str, chamber: str, scope: Optional[list[str]],
                  stats: Counter, dry_run: bool) -> None:
    """Write one source's edges; with a scope, also drop the entries the source no longer gives."""
    params = {"roles": ROLE_ORDER, "sources": SOURCES}
    if scope is not None or source == "resoconto":
        keep = [f"{m['bill']}|{m['person']}" for m in merged]
        stale = list(session.run(STALE_COUNT, chamber=chamber, bills=scope, source=source, keep=keep))
        stats["stale_entries"] = len(stale)
        stats["stale_orphans"] = sum(1 for s in stale if s["orphan"])
        for s in stale[:20]:
            logger.info("%s non dà più %s su %s%s", source, s["person"], s["bill"],
                        " (arco cancellato)" if s["orphan"] else "")
        if len(stale) > MAX_RETRACT:
            logger.error("%d archi da ritirare per %s: oltre %d, non tocco nulla", len(stale), source, MAX_RETRACT)
            stats["retract_skipped"] = 1
        elif stale and not dry_run:
            session.run(RETRACT, chamber=chamber, bills=scope, source=source, keep=keep, **params).consume()
    if not dry_run:
        for i in range(0, len(merged), 1000):
            session.run(WRITE, rows=merged[i:i + 1000], **params).consume()


# ---------------------------------------------------------------------------
# Transcripts: rapporteurs the other sources leave out
# ---------------------------------------------------------------------------

LABELLED_SPEECHES = """
MATCH (s:Session)-[:HAS_DEBATE]->(d:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
      -[:SPOKEN_BY]->(p:Person)
WHERE coalesce(s.chamber, 'camera') = $chamber AND coalesce(s.legislature, 19) = $leg
  AND sp.speakingRole =~ '(?i)relat(ore|rice)([^a-z].*)?'
  AND $mandate IN coalesce(p.mandates, [])
  AND NOT coalesce(sp.speaker_in_government, false)
MATCH (d)-[:DISCUSSES]->(b:Bill)
WITH sp, p, s, collect(DISTINCT {uri: b.uri, number: b.number}) AS bills
RETURN sp.id AS speech, sp.speakingRole AS label, p.id AS person, s.id AS session,
       toString(s.date) AS date, bills
ORDER BY date, speech
"""

OTHER_SOURCES = """
MATCH (b:Bill {chamber: $chamber})-[r:REPORTED_BY]->(p:Person)
WITH b, p, """ + _PREV + """ AS att
WITH b, p, [a IN att WHERE NOT a STARTS WITH 'resoconto:' | split(a, ':')[1]] AS roles
WHERE size(roles) > 0
RETURN b.uri AS bill, b.number AS number, p.id AS person, roles
"""

# "Relatore sul disegno di legge n. 792" in joint debates.
_BILL_NO = re.compile(r"\blegge\s+n\.\s*(\d+(?:-[a-z]+)?)", re.I)


def label_side(label: str) -> Optional[str]:
    low = label.lower()
    if "minoranza" in low:
        return "minoranza"
    if "maggioranza" in low:
        return "maggioranza"
    return None


def resoconto_records(speeches: list[dict], other: dict[tuple[str, str], set[str]], stats: Counter,
                      other_numbers: Optional[set[tuple[str, str]]] = None) -> list[dict]:
    """REPORTED_BY rows for speakers the transcript calls rapporteur and no other source lists.

    A speaker with no edge on the debated bill gets one with the side of his
    label, or sostituto when the label names none (a member standing in for
    the rapporteur). A speaker listed without a side gets the label's side.
    A label that contradicts the side another source gives is only counted.

    other_numbers holds (bill number, person) of the same edges. The debates
    on a bill split off from another (C. 1532-ter, C. 643-bis) discuss the
    parent bill in the graph (19/10/2026): a speaker who reports on a split
    of the debated bill is no rapporteur of the parent, and gets nothing.
    """
    other_numbers = other_numbers or set()
    out = []
    for s in speeches:
        bills = s["bills"]
        if "document" in s["label"].lower():
            # "Relatrice sui documenti LXXXVI, n. 1, e LXXXVII, n. 1": a report on a Doc, not on a bill.
            stats["resoconto_label_on_document"] += 1
            continue
        m = _BILL_NO.search(s["label"])
        if m:
            n = m.group(1).upper()
            targets = [b for b in bills if (b["number"] or "").upper() == n] \
                or [b for b in bills if (b["number"] or "").upper() == n.split("-")[0]]
            if not targets:
                stats["resoconto_numbered_bill_missing"] += 1
                logger.warning("%s: %r, atto non tra quelli del dibattito", s["speech"], s["label"])
                continue
        else:
            targets = bills
        side = label_side(s["label"])
        covered = [b for b in targets if (b["uri"], s["person"]) in other]
        rec = {"person": s["person"], "date": s["date"], "venue": "assemblea", "committee": None,
               "source": "resoconto", "session": s["session"]}
        if not covered and any(num.startswith((b["number"] or "") + "-") and person == s["person"]
                               for b in targets for num, person in other_numbers):
            stats["resoconto_split_bill_speeches"] += 1
            continue
        if not covered:
            if len(targets) > 1:
                stats["resoconto_multi_bill_speeches"] += 1
                logger.info("%s: %r su %d atti del dibattito", s["speech"], s["label"], len(targets))
            stats["resoconto_new_speeches"] += 1
            out += [{**rec, "bill": b["uri"], "role": side or "sostituto"} for b in targets]
            continue
        if side is None:
            continue
        roles = set().union(*(other[(b["uri"], s["person"])] for b in covered))
        if roles & {"maggioranza", "minoranza"}:
            if side not in roles:
                stats["resoconto_side_conflict"] += 1
                logger.warning("%s: %r ma le altre fonti dicono %s", s["speech"], s["label"], sorted(roles))
            continue
        stats["resoconto_side_added_speeches"] += 1
        out += [{**rec, "bill": b["uri"], "role": side} for b in covered]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7690"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--chamber", choices=("camera", "senato"), required=True)
    ap.add_argument("--source", choices=("opendata", "scheda", "resoconto"), default="opendata",
                    help="opendata: dati.camera.it / dati.senato.it; scheda: camera.it bill pages "
                         "(Camera only); resoconto: speaker labels in the transcripts")
    ap.add_argument("--cached", action="store_true",
                    help="Senato: read the cached CSV; scheda: read no page, use the cache")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between Camera SPARQL calls")
    ap.add_argument("--page-delay", type=float, default=2.5, help="seconds between camera.it pages")
    ap.add_argument("--max-pages", type=int, default=150, help="camera.it pages read per run")
    ap.add_argument("--fetch-only", action="store_true", help="scheda: fill the cache, write nothing")
    ap.add_argument("--raw-dir", help="scheda: also keep the pages read, gzipped, in this folder")
    ap.add_argument("--dry-run", action="store_true", help="read the sources, write nothing")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD non impostata")
    if args.source == "scheda" and args.chamber != "camera":
        sys.exit("--source scheda vale solo per la Camera")

    stats: Counter = Counter()
    status = 0
    scope: Optional[list[str]] = None
    source = {"opendata": "dati.camera.it" if args.chamber == "camera" else "dati.senato.it",
              "scheda": "scheda_camera", "resoconto": "resoconto"}[args.source]
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password),
                                  notifications_min_severity="OFF")
    try:
        with driver.session() as session:
            bills = {r["uri"] for r in session.run(
                "MATCH (b:Bill {chamber: $c}) RETURN b.uri AS uri", c=args.chamber)}
            deputies: dict[tuple[str, str], str] = {}
            if args.chamber == "camera" and args.source != "resoconto":
                for r in session.run("""
                        MATCH (p:Person) WHERE $m IN coalesce(p.mandates, [])
                        RETURN p.id AS id, p.last_name AS last, p.first_name AS first""",
                                     m=f"camera_{args.leg}"):
                    deputies[(fold(r["last"]), fold(r["first"]))] = r["id"]
            if args.source == "resoconto":
                rows = list(session.run(OTHER_SOURCES, chamber=args.chamber))
                other = {(r["bill"], r["person"]): set(r["roles"]) for r in rows}
                other_numbers = {(r["number"] or "", r["person"]) for r in rows}
                speeches = [dict(r) for r in session.run(
                    LABELLED_SPEECHES, chamber=args.chamber, leg=args.leg, mandate=f"{args.chamber}_{args.leg}")]
                stats["resoconto_labelled_speeches"] = len(speeches)
                records = resoconto_records(speeches, other, stats, other_numbers)
            elif args.source == "scheda":
                path = os.path.join(DATA_DIR, f"camera_{ROMAN.get(args.leg, args.leg)}_relatori_schede.json")
                cache = load_cache(path)
                if not args.cached:
                    eligible = [dict(r) for r in session.run("""
                        MATCH (b:Bill {chamber: 'camera'})
                        WHERE coalesce(b.legislature, 19) = $leg AND b.number IS NOT NULL
                          AND (EXISTS { (b)-[:REPORTED_BY]->() } OR EXISTS { (:Debate)-[:DISCUSSES]->(b) })
                        OPTIONAL MATCH (s:Session)-[:HAS_DEBATE]->(:Debate)-[:DISCUSSES]->(b)
                        RETURN b.uri AS uri, b.number AS number, b.source_modified AS modified,
                               toString(max(s.date)) AS last_debate""", leg=args.leg)]
                    todo = pages_to_fetch(eligible, cache, args.max_pages)
                    stats["scheda_eligible"] = len(eligible)
                    stats["scheda_to_read"] = len(todo)
                    if args.raw_dir:
                        os.makedirs(args.raw_dir, exist_ok=True)
                    fetch_pages(todo, cache, path, args.leg, args.page_delay, args.raw_dir, stats)
                    if stats["scheda_refused"]:
                        status = 3
                stats["scheda_cached"] = len(cache)
                records = []
                if not args.fetch_only:
                    records = scheda_records(cache, bills, deputies, set(deputies.values()), stats)
                    scope = sorted({p["uri"] for p in cache.values()})
            elif args.chamber == "camera":
                records = camera_records(Sparql(args.delay), args.leg, deputies, bills, stats)
            else:
                path = os.path.join(DATA_DIR, f"senato_{ROMAN.get(args.leg, args.leg)}_relatori.csv")
                if args.cached:
                    with open(path, encoding="utf-8") as f:
                        rows = list(csv.DictReader(f))
                else:
                    from senate_sparql_ingester import SenateEndpointBlocked, SenateRequestFailed
                    try:
                        rows = download_senate(args.leg, path)
                    except (SenateEndpointBlocked, SenateRequestFailed) as exc:
                        logger.warning("dati.senato.it rifiuta la richiesta: %s", exc)
                        return 3
                senators = {r["sid"]: r["id"] for r in session.run(
                    "MATCH (p:Person) WHERE p.senato_id IS NOT NULL RETURN p.senato_id AS sid, p.id AS id")}
                records = senate_records(rows, senators, bills, stats)
            merged = merge_reports(records)
            stats["relationships"] = len(merged)
            stats["bills_with_reporter"] = len({m["bill"] for m in merged})
            for m in merged:
                stats[f"role_{m['role']}"] += 1
            if not args.fetch_only:
                write_records(session, merged, source, args.chamber, scope, stats, args.dry_run)
    finally:
        driver.close()
    for k in sorted(stats):
        logger.info("%s: %d", k, stats[k])
    return status


if __name__ == "__main__":
    sys.exit(main())

