#!/usr/bin/env python3
"""
Parliamentary documents (Doc.) of both chambers, with their debates, votes and rapporteurs.

  (:ParliamentaryAct:ParliamentaryDocument {uri, id, kind: 'doc', doc_series, number, name,
        doc_type_raw, title, date, presentation_date, chamber, legislature, initiative,
        url, text_urls, textPdfUrl, official_uris})
  (:Debate)-[:DISCUSSES]->(doc)
  (:Vote)-[:ON_ACT]->(doc)
  (doc)-[:REPORTED_BY]->(:Person)                        as for bills (ingest_reporters.py)
  (doc)-[:PART_OF {chamber}]->(:LegislativeProcess {id: 'parlamento:19:doc:LVII:1'})

One node per document and chamber, keyed "camera:19:doc:IV-ter:13": neither
source gives one URI per document (decision D9 style); the official records
go in official_uris. Every sheet of a Camera document (text, annexes, errata,
the committee report "-A") is the same node; "1-bis" is another document.
Which documents: those a debate or a vote of the chamber is about.

Camera (dati.camera.it, one SPARQL query, cached in data/camera_{roman}_documenti.json):
ocd:DOC has 36 of the 85 documents debated in the XIX (19/10/2026); the
others take the title from the debate title or the vote description, and the
Government ones the Senate's record. Debates: the placeholders the debate
ingest creates ("placeholder:doc:Doc. IV-ter, n. 13-A"), moved here by
repair_placeholder_acts.py. Votes: a vote whose description names documents
and that the source gives no act gets ON_ACT to each of them; the act
repair_vote_data.py guessed from the votes around it (inferred 'vicini',
always a bill: 71 votes on inquiry proposals, Doc. XXII) goes. Rapporteurs:
"Relatore: PELLA" in the title of the report.

Senato (dati.senato.it, four queries, cached in data/senato_{roman}_documenti*.csv):
osr:Documento with numeroRomano (petitions have none and are left out),
votes from osr:Votazione -> osr:oggetto -> osr:relativoA, debates from the
title ("Discussione del documento: (Doc. IV-ter, n. 3) - ...") and the
section's <block name="Atto"> of type Doc in the Akoma Ntoso. The Senate
publishes no rapporteur of a document: those come from the transcript labels
(ingest_reporters.py --source resoconto).

Government documents both chambers receive (DEF, PSB and the like, GOV_SERIES)
with the same series and number join one LegislativeProcess.

Idempotent: MERGE; the only deletions are the guessed ON_ACT above.

    python build/ingest_documents.py --neo4j-uri bolt://... --chamber camera|senato
        [--download] [--dry-run] [--dump file.json]

Exit 3 = dati.senato.it refused the request (the cached copy is used).
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from doc_refs import LATIN, doc_keys, doc_name, doc_uri, norm_number, norm_series, parse_doc_refs  # noqa: E402

logger = logging.getLogger("ingest_documents")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(REPO, "data")
ROMAN = {18: "xviii", 19: "xix"}

# Documents the Government sends to both chambers under the same number.
GOV_SERIES = ("LVII", "CCXL", "CCXLIV", "CCXXXII", "LXXXVI")
PROCESS_ID = "parlamento:{leg}:doc:{series}:{number}"

CAMERA_DOCS = """
SELECT ?d ?id ?title ?type ?date ?rel WHERE {{
  ?d a ocd:DOC ; ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}> ; dc:identifier ?id .
  OPTIONAL {{ ?d dc:title ?title }} OPTIONAL {{ ?d dc:type ?type }}
  OPTIONAL {{ ?d dc:date ?date }} OPTIONAL {{ ?d dc:relation ?rel }}
}}"""

# dati.senato.it: short queries, no GROUP_CONCAT (the WAF answered 403 to
# one on 19/10/2026), each under the 10,000-row cap (3,441 documents,
# 2,441 text links, 3,642 initiatives in the XIX).
_SEN_PREFIX = "PREFIX osr: <http://dati.senato.it/osr/>\n"
SENATE_QUERIES = {
    "documenti": ("""SELECT ?d ?r ?num ?suff ?tipo ?titolo ?data WHERE {{
  ?d a osr:Documento ; osr:legislatura {leg} ; osr:numeroRomano ?r .
  OPTIONAL {{ ?d osr:numeroDoc ?num }} OPTIONAL {{ ?d osr:suffissoNumeroDoc ?suff }}
  OPTIONAL {{ ?d osr:tipoDoc ?tipo }} OPTIONAL {{ ?d osr:titolo ?titolo }}
  OPTIONAL {{ ?d osr:dataPresentazione ?data }} }}""",
                  ["d", "r", "num", "suff", "tipo", "titolo", "data"]),
    "documenti_testi": ("""SELECT ?d ?url WHERE {{
  ?d a osr:Documento ; osr:legislatura {leg} ; osr:numeroRomano ?r ; osr:URLTesto ?url }}""",
                        ["d", "url"]),
    "documenti_iniziativa": ("""SELECT ?d ?tipo ?pres WHERE {{
  ?d a osr:Documento ; osr:legislatura {leg} ; osr:numeroRomano ?r ; osr:iniziativa ?i .
  ?i osr:tipoIniziativa ?tipo . OPTIONAL {{ ?i osr:presentatore ?pres }} }}""",
                             ["d", "tipo", "pres"]),
    "voti_documenti": ("""SELECT ?v ?d WHERE {{
  ?v a osr:Votazione ; osr:legislatura {leg} ; osr:oggetto ?o . ?o osr:relativoA ?d .
  ?d a osr:Documento ; osr:numeroRomano ?r }}""",
                       ["v", "d"]),
}
SENATE_INITIATIVE = {"Governativa": "governo", "Parlamentare": "parlamentare"}
SENATE_PAGE = "https://www.senato.it/leg/{leg}/BGT/Schede/docnonleg/{id}.htm"
_NUMBER_RE = re.compile(r"\d+(?:\s*-\s*(?i:" + LATIN + r")\b)?")


# ---------------------------------------------------------------------------
# Titles
# ---------------------------------------------------------------------------

_SPACE_RE = re.compile(r"\s+")
# "Presentato dal Presidente del Consiglio dei ministri: MELONI", "D'iniziativa
# dei deputati: BICCHIELLI ed altri": the presenter, kept out of the title.
_PRESENTER_RE = re.compile(
    r"\s*(?:Presentat[oa] dal(?:la|l')?\s.*?|D'iniziativa de(?:i|l|lla) deputat[oaie]+):\s*"
    r"[A-ZÀ-Ý'][A-ZÀ-Ý']+(?:\s+ed altri)?(?=\s|\(|$)")
_GOV_PRESENTER_RE = re.compile(r"Presentat[oa] dal(?:la|l')?\s+(?:Presidente del Consiglio|Vicepresidente del Consiglio"
                               r"|Ministr|Governo)", re.I)
_MP_PRESENTER_RE = re.compile(r"D'iniziativa de(?:i|l) deputat", re.I)
_REPORTER_RE = re.compile(r"\bRelat(?:ore|rice)(?: per [^:()]{1,60})?:\s*((?:[A-Z][a-zà-ý]+\s+)?[A-ZÀ-Ý][A-ZÀ-Ý']+(?:\s+[A-ZÀ-Ý][A-ZÀ-Ý']+)*)\b")
# A Camera record title that names only a period, a volume or a person
# ("nei confronti del Senatore: ..."), or opens in capitals ("DOCUMENTO
# APPROVATO DALLA XIV COMMISSIONE Proposta di ...").
_WEAK_TITLE_RE = re.compile(r"^(?:(?i:anno\b|periodo\b|volume\b|allegat|relat|n\.\s*\d|annesso)|[a-zà-ý]"
                            r"|[A-ZÀ-Ý]{3,}\s+[A-ZÀ-Ý]{2,}\b)")
_REPORTER_NOTE_RE = re.compile(r"\s*\(Relat(?:ore|rice)[^)]*\)")
_PROCEDURE_RE = re.compile(
    r"^(?:(?:seguito della |ripresa della )?discussione(?: congiunta)?(?: e approvazione)?"
    r"(?: dalla sede redigente)?|esame|si riprende la discussione)\s+"
    r"(?:(?:del|della|dello|dei|delle|degli)\s+)?(?:(?:documento|documenti)\s*:)?\s*", re.I)
_NOT_A_TITLE_RE = re.compile(r"^(?:emendament|articol|identici|subemendament|ordine del giorno|odg|votazione"
                             r"|risoluzione|mozione)", re.I)


def clean(text: Optional[str]) -> Optional[str]:
    import html
    if not text:
        return None
    t = _SPACE_RE.sub(" ", re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(text)))).strip()
    return t or None


def camera_record_title(title: Optional[str]) -> Optional[str]:
    """Title of a dati.camera.it record without the presenter; None when it names only a period."""
    t = clean(title)
    if not t:
        return None
    t = _REPORTER_NOTE_RE.sub("", _PRESENTER_RE.sub(" ", t))
    # "Presentata dalla GIUNTA PER IL REGOLAMENTO (Modifiche al Regolamento ...)"
    t = re.sub(r"^\s*Presentat[oa] dal(?:la|l')?\s+[A-ZÀ-Ý' ]+?\s*\((.*)\)\s*$", r"\1", t)
    t = _SPACE_RE.sub(" ", t).strip(" -")
    if len(t) < 15 or _WEAK_TITLE_RE.match(t):
        return None
    return t


def sentence_case(text: Optional[str]) -> Optional[str]:
    t = clean(text)
    if not t:
        return None
    return t[0].upper() + t[1:].lower() if t.isupper() or t[:20].isupper() else t


def title_before(text: Optional[str], key: tuple[str, str]) -> Optional[str]:
    """What a debate title or vote description says the document is, before its reference.

    "Discussione congiunta dei documenti: Conto consuntivo ... (Doc. VIII, n. 1);
    Progetto di bilancio ... (Doc. VIII, n. 2)" gives each its own clause.
    """
    t = clean(text)
    if not t:
        return None
    for m in re.finditer(r"\(\s*(?i:docc?)\.", t):
        end = t.find(")", m.start())
        if key not in doc_keys(t[m.start():end + 1 if end > 0 else None]):
            continue
        head = t[:m.start()]
        head = re.split(r"[;:]\s", head)[-1]
        head = _PROCEDURE_RE.sub("", head.strip()).strip(" ,.-")
        if len(head) < 15 or _NOT_A_TITLE_RE.match(head):
            return None
        return head[0].upper() + head[1:]
    return None


def reporter_names(title: Optional[str]) -> list[tuple[str, str]]:
    """(surname, given name) named in "Relatore: Enrico COSTA", "Relatrice: FORATTINI"."""
    out = []
    for m in _REPORTER_RE.finditer(clean(title) or ""):
        words = m.group(1).split()
        given = [w for w in words if not w.isupper()]
        surname = [w for w in words if w.isupper()]
        if surname:
            out.append((" ".join(surname), " ".join(given)))
    return out


def iso(raw: Optional[str]) -> Optional[str]:
    s = (raw or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    try:
        return date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def load_camera_records(leg: int, download: bool) -> list[dict]:
    """ocd:DOC rows of the legislature, from dati.camera.it or the cached copy."""
    path = os.path.join(DATA_DIR, f"camera_{ROMAN[leg]}_documenti.json")
    if download:
        from ingest_acts_camera import VIRTUOSO_CAP, Sparql
        try:
            rows = Sparql(1.0).select(CAMERA_DOCS.format(leg=leg))
            if len(rows) >= VIRTUOSO_CAP:
                raise RuntimeError("documenti della Camera oltre il limite di righe")
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=0)
            os.replace(tmp, path)
            logger.info("%d righe ocd:DOC -> %s", len(rows), os.path.basename(path))
            return rows
        except RuntimeError as exc:
            logger.warning("dati.camera.it non risponde (%s): uso la copia in data/", exc)
    if not os.path.exists(path):
        raise SystemExit(f"{path} assente: lanciare con --download")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


_UPPER_SUFFIX_RE = re.compile(r",n\.\d+-(?:BIS|TER|QUATER)\b")


def camera_index(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """(series, number) -> {main, reports, uris, text_urls, type} from the ocd:DOC rows."""
    by_uri: dict[str, dict] = {}
    for r in rows:
        rec = by_uri.setdefault(r["d"], {"uri": r["d"], "id": r["id"], "title": None, "type": None,
                                         "date": None, "rels": []})
        rec["title"] = rec["title"] or r.get("title")
        rec["type"] = rec["type"] or r.get("type")
        rec["date"] = rec["date"] or r.get("date")
        if r.get("rel") and r["rel"] not in rec["rels"]:
            rec["rels"].append(r["rel"])
    out: dict[tuple[str, str], dict] = {}
    for rec in sorted(by_uri.values(), key=lambda x: x["uri"]):
        if _UPPER_SUFFIX_RE.search(rec["id"]):
            # doc19_LVIIn1BIS ("Doc.LVII,n.1-BIS") is the NADEF 2022 of
            # 30/09/2022, cited as Doc. LVII, n. 01-bis (19/10/2026).
            logger.info("Camera: %s (%s) scartato, numero della fonte non affidabile", rec["id"], rec["uri"])
            continue
        for ref in parse_doc_refs(rec["id"]):
            doc = out.setdefault((ref.series, ref.number), {"main": None, "reports": [], "sheets": []})
            # The record of the text itself: identifier without a suffix
            # ("Doc.LVII,n.1") and URI without a sheet number ("doc19_LVIIn1_2").
            plain = ref.report is None and re.fullmatch(r"Doc\.[^,]+,n\.[\w-]+", rec["id"].replace(" ", "")) \
                and norm_number(rec["id"].split(",n.")[-1]) == ref.number
            if ref.report:
                doc["reports"].append(rec)
            elif plain and not re.search(r"_\d+$", rec["uri"]) and doc["main"] is None:
                doc["main"] = rec
            else:
                doc["sheets"].append(rec)
    return out


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
CAMERA_PDF = "https://documenti.camera.it/_dati/leg{leg}/lavori/documentiparlamentari/IndiceETesti/{cat}/{num}/INTERO.pdf"


def roman_to_int(roman: str) -> int:
    values = [_ROMAN_VALUES[c] for c in roman]
    return sum(-v if i + 1 < len(values) and v < values[i + 1] else v for i, v in enumerate(values))


def camera_pdf_url(leg: int, series: str, number: str) -> Optional[str]:
    """Text of a Chamber document by its place in the Chamber's archive.

    IndiceETesti/<series>/<number>/INTERO.pdf: "IV-ter" is 004ter, "13" 013,
    "1-bis" 001bis (the pattern behind the dc:relation links of ocd:DOC,
    which redirect there; checked on Doc. II n. 11 and XXII n. 31, 19/10/2026).
    """
    head, _, latin = series.partition("-")
    m = re.fullmatch(r"(\d+)(?:-([a-z]+))?", number)
    if not m or not head:
        return None
    cat = f"{roman_to_int(head):03d}{latin}"
    return CAMERA_PDF.format(leg=leg, cat=cat, num=f"{int(m.group(1)):03d}{m.group(2) or ''}")


def check_camera_pdfs(leg: int, nodes: list[dict], download: bool, stats: Counter) -> None:
    """Text link of the Chamber documents ocd:DOC does not describe, if camera.it has the file.

    The answers are kept in data/camera_{roman}_documenti_pdf.json: a file
    found is not asked again, a missing one at the next --download.
    """
    import requests
    path = os.path.join(DATA_DIR, f"camera_{ROMAN[leg]}_documenti_pdf.json")
    cache: dict[str, Optional[str]] = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cache = json.load(f)
    http = requests.Session()
    http.headers.update({"User-Agent": "ParliamentRAG-documents/1.0 (+https://www.parliamentrag.it)"})
    asked = 0
    for n in nodes:
        if n["official_uris"]:
            continue
        url = camera_pdf_url(leg, n["series"], n["number"])
        if not url:
            continue
        if url not in cache or (cache[url] is None and download):
            if not download:
                continue
            if asked:
                time.sleep(2)
            asked += 1
            try:
                r = http.get(url, timeout=60, stream=True)
                ok = r.status_code == 200 and "pdf" in r.headers.get("content-type", "")
                r.close()
                cache[url] = url if ok else None
            except requests.RequestException as exc:
                logger.warning("camera.it non risponde per %s: %s", n["name"], exc)
                continue
        if cache.get(url):
            n["text_urls"] = [url]
            n["url"] = url
            stats["camera_pdf_from_archive"] += 1
    if asked:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cache, f, ensure_ascii=False, indent=0, sort_keys=True)
        os.replace(tmp, path)


def senate_download(leg: int) -> None:
    """The four Senate files in data/; raises SenateEndpointBlocked/SenateRequestFailed."""
    import senate_sparql_ingester as ssi
    ssi._POLITENESS_DELAY = max(ssi._POLITENESS_DELAY, 4.0)
    for name, (query, fields) in SENATE_QUERIES.items():
        bindings = ssi._senato_sparql_get(_SEN_PREFIX + query.format(leg=leg), strict=True)
        if len(bindings) >= 10000:
            raise RuntimeError(f"{name}: oltre il limite di righe")
        path = os.path.join(DATA_DIR, f"senato_{ROMAN[leg]}_{name}.csv")
        tmp = path + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows({k: b.get(k, {}).get("value", "") for k in fields} for b in bindings)
        os.replace(tmp, path)
        logger.info("%d righe -> %s", len(bindings), os.path.basename(path))


def read_csv(leg: int, name: str) -> list[dict]:
    path = os.path.join(DATA_DIR, f"senato_{ROMAN[leg]}_{name}.csv")
    if not os.path.exists(path):
        raise SystemExit(f"{path} assente: lanciare con --download")
    with open(path, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def senate_index(leg: int) -> dict[tuple[str, str], dict]:
    """(series, number) -> the Senate record, with text links and initiative."""
    texts: dict[str, list[str]] = defaultdict(list)
    for r in read_csv(leg, "documenti_testi"):
        if r["url"] not in texts[r["d"]]:
            texts[r["d"]].append(r["url"])
    inits: dict[str, dict] = defaultdict(lambda: {"types": set(), "presenters": []})
    for r in read_csv(leg, "documenti_iniziativa"):
        inits[r["d"]]["types"].add(r["tipo"])
        if r.get("pres") and r["pres"] not in inits[r["d"]]["presenters"]:
            inits[r["d"]]["presenters"].append(r["pres"])
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in read_csv(leg, "documenti"):
        if not r.get("num"):
            continue
        raw = r["num"] + (f"-{r['suff']}" if r.get("suff") else "")
        token = _NUMBER_RE.match(raw)
        key = (norm_series(r["r"].replace(" ", "-")), norm_number(token.group(0) if token else raw))
        kinds = {SENATE_INITIATIVE.get(t, re.sub(r"^di ", "", t.lower())) for t in inits[r["d"]]["types"]}
        groups[key].append({
            "uri": r["d"], "title": clean(r.get("titolo")), "type": clean(r.get("tipo")),
            "date": iso(r.get("data")), "text_urls": texts.get(r["d"], []),
            "initiative": kinds.pop() if len(kinds) == 1 else ("mista" if kinds else None),
            # "bis - Integrazione": an addition to 01-bis, not the document.
            "plain": token is not None and token.group(0) == raw,
        })
    out: dict[tuple[str, str], dict] = {}
    for key, recs in groups.items():
        recs.sort(key=lambda x: (not x["plain"], x["date"] or "", x["uri"]))
        main = dict(recs[0])
        main["text_urls"] = list(dict.fromkeys(u for x in recs for u in x["text_urls"]))
        main["uris"] = [x["uri"] for x in recs]
        if sum(x["plain"] for x in recs) > 1:
            logger.info("Senato: %s in più schede: %s", doc_name(*key), main["uris"])
        out[key] = main
    return out


def senate_vote_docs(leg: int, uri_to_key: dict[str, tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
    """{Vote id: [(series, number)]} from osr:relativoA."""
    from senate_sparql_ingester import parse_senate_votazione_uri
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for r in read_csv(leg, "voti_documenti"):
        lg, sitting, number = parse_senate_votazione_uri(r["v"])
        key = uri_to_key.get(r["d"])
        if lg is None or key is None:
            continue
        vid = f"senato_leg{lg}_sed{sitting:03d}_v{number:03d}"
        if key not in out[vid]:
            out[vid].append(key)
    return dict(out)


def akn_section_docs(path: str) -> dict[tuple[str, int], list[tuple[str, str]]]:
    """{(section slug, occurrence): [(series, number)]} of the Doc blocks of a Senate sitting."""
    from senate_parser import _slug
    root = ET.parse(path).getroot()
    ns = root.tag.split("}")[0] + "}"
    body = root.find(f".//{ns}debateBody")
    out: dict[tuple[str, int], list[tuple[str, str]]] = {}
    if body is None:
        return out
    seen: Counter = Counter()
    for sec in body.findall(f"{ns}debateSection"):
        slug = _slug(sec.get("name", ""))
        occ = seen[slug]
        seen[slug] += 1
        keys: list[tuple[str, str]] = []
        for b in sec.iter(f"{ns}block"):
            if b.get("name") == "Atto" and (b.findtext(f"{ns}docType") or "").strip() == "Doc":
                for k in doc_keys(b.findtext(f"{ns}docNumber") or ""):
                    if k not in keys:
                        keys.append(k)
        if keys:
            out[(slug, occ)] = keys
    return out


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------

def doc_row(chamber: str, leg: int, key: tuple[str, str], **props) -> dict:
    uri = doc_uri(chamber, leg, *key)
    return {"uri": uri, "series": key[0], "number": key[1], "name": doc_name(*key), **props}


def plan_camera(leg: int, records: dict, senate: dict, placeholders: list[dict], votes: list[dict],
                debates: list[dict], existing: set[tuple[str, str]], stats: Counter) -> dict:
    """Nodes, ON_ACT, ON_ACT to drop and REPORTED_BY names for the Chamber."""
    wanted: dict[tuple[str, str], None] = {k: None for k in sorted(existing)}
    for p in placeholders:
        keys = doc_keys(p["number"])
        if not keys:
            stats["camera_placeholder_unparsed"] += 1
            logger.warning("segnaposto non leggibile: %r", p["number"])
        wanted.update((k, None) for k in keys)
    on_act, drop = [], []
    for v in votes:
        keys = doc_keys(v["description"])
        if not keys:
            continue
        official = [a for a in v["acts"] if a["uri"] and a["inferred"] != "vicini" and not a["doc"]]
        if official:
            stats["camera_votes_doc_with_act"] += 1
            continue
        stats["camera_votes_doc"] += 1
        wanted.update((k, None) for k in keys)
        on_act += [{"vote": v["id"], "uri": doc_uri("camera", leg, *k)} for k in keys]
        drop += [{"vote": v["id"], "uri": a["uri"]} for a in v["acts"] if a["inferred"] == "vicini"]
    titles: dict[tuple[str, str], list[str]] = defaultdict(list)
    for d in debates:
        for k in doc_keys(d["title"]):
            t = title_before(d["title"], k)
            if t:
                titles[k].append(t)
    for v in votes:
        for k in doc_keys(v["description"]):
            t = title_before(v["description"], k)
            if t:
                titles[(k[0], k[1], "vote")].append(t)

    nodes, reporters = [], []
    for key in wanted:
        rec = records.get(key, {"main": None, "reports": [], "sheets": []})
        sen = senate.get(key) if key[0] in GOV_SERIES else None
        main = rec["main"]
        sheets = [x for x in [main] + rec["sheets"] + rec["reports"] if x]
        title = (sen or {}).get("title") or camera_record_title((main or {}).get("title"))
        source = "senato" if (sen or {}).get("title") else "camera" if title else None
        if not title and titles.get(key):
            title, source = Counter(titles[key]).most_common(1)[0][0], "dibattito"
        if not title and titles.get((key[0], key[1], "vote")):
            title, source = Counter(titles[(key[0], key[1], "vote")]).most_common(1)[0][0], "voto"
        if not title:
            for x in sheets:
                title = camera_record_title(x.get("title"))
                if title:
                    source = "camera"
                    break
        doc_type = next((sentence_case(x["type"]) for x in sheets if x.get("type")), None) \
            or (sen or {}).get("type")
        if not title and doc_type:
            title, source = doc_type, "tipo"
        stats[f"camera_title_{source}"] += 1
        main_title = clean((main or {}).get("title")) or ""
        initiative = (sen or {}).get("initiative") or (
            "governo" if _GOV_PRESENTER_RE.search(main_title)
            else "parlamentare" if _MP_PRESENTER_RE.search(main_title) else None)
        text_urls = [u for x in sheets for u in x["rels"]]
        if not text_urls and sen:
            text_urls = sen["text_urls"]
        day = iso((main or {}).get("date")) or next((iso(x.get("date")) for x in sheets if x.get("date")), None) \
            or (sen or {}).get("date")
        nodes.append(doc_row("camera", leg, key, title=title, title_source=source, doc_type_raw=doc_type,
                             date=day, initiative=initiative,
                             url=(main or {}).get("rels", [None])[0] if main and main["rels"]
                             else (text_urls[0] if text_urls else None),
                             text_urls=list(dict.fromkeys(text_urls)) or None,
                             official_uris=sorted({x["uri"] for x in sheets}) or None))
        stats["camera_with_record"] += bool(sheets)
        # "Relatore: PELLA" on the report (-A), "(Relatore per la III
        # Commissione: LOPERFIDO)" on a committee report (Doc. XVI).
        for x in sheets:
            for name in reporter_names(x.get("title")):
                reporters.append({"doc": doc_uri("camera", leg, *key), "name": name, "date": iso(x.get("date"))})
    stats["camera_docs"] = len(nodes)
    return {"nodes": nodes, "on_act": on_act, "drop": drop, "reporters": reporters}


def plan_senate(leg: int, senate: dict, vote_docs: dict[str, list[tuple[str, str]]], votes: set[str],
                bill_votes: set[str], sittings: dict[int, list[dict]], existing: set[tuple[str, str]],
                stats: Counter, akn_dir: Optional[str]) -> dict:
    """Nodes, DISCUSSES and ON_ACT for the Senate.

    bill_votes: votes on a bill. The source lists the documents examined
    with a bill among the objects of its votes (the European delegation law
    with Doc. LXXXVI and LXXXVII: 185 votes, 19/10/2026): those votes stay
    on the bill alone.
    """
    from link_senate_acts import resumed_debate, section_debates
    discusses = []
    for num, debates in sorted(sittings.items()):
        session_id = debates[0]["session"] if debates else None
        by_debate: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for d in debates:
            for k in doc_keys(d["title"]):
                by_debate[d["id"]].append(k)
        path = os.path.join(akn_dir, f"resaula_leg{leg}_{num:04d}.akn") if akn_dir else None
        if path and os.path.exists(path):
            sections = akn_section_docs(path)
            where = section_debates(session_id, [(d["id"], d["order"] or 0) for d in debates])
            for sec, keys in sections.items():
                did = where.get(sec)
                if did:
                    for k in keys:
                        if k not in by_debate[did]:
                            by_debate[did].append(k)
                            stats["senato_debate_from_akn"] += 1
        ordered = [(d["id"], d["title"], d["order"] or 0) for d in debates]
        for d in debates:
            if by_debate.get(d["id"]):
                continue
            other = resumed_debate(d["id"], ordered)
            if other and by_debate.get(other):
                by_debate[d["id"]] = list(by_debate[other])
                stats["senato_debate_resumed"] += 1
        for did, keys in by_debate.items():
            for k in keys:
                if k in senate:
                    discusses.append({"debate": did, "key": k})
                else:
                    stats["senato_debate_doc_unknown"] += 1
                    logger.info("Senato: %s di %s non tra i documenti della fonte", doc_name(*k), did)
    on_act = []
    for vid, keys in sorted(vote_docs.items()):
        if vid not in votes:
            stats["senato_vote_missing"] += 1
            continue
        if vid in bill_votes:
            stats["senato_vote_on_bill"] += 1
            continue
        on_act += [{"vote": vid, "key": k} for k in keys]
    wanted = sorted(set(existing) | {x["key"] for x in discusses} | {x["key"] for x in on_act})
    nodes = []
    for key in wanted:
        sen = senate.get(key)
        if not sen:
            stats["senato_existing_without_record"] += 1
            continue
        nodes.append(doc_row("senato", leg, key, title=sen["title"], title_source="senato",
                             doc_type_raw=sen["type"], date=sen["date"], initiative=sen["initiative"],
                             url=SENATE_PAGE.format(leg=leg, id=sen["uri"].rsplit("/", 1)[-1]),
                             text_urls=sen["text_urls"] or None, official_uris=sen["uris"]))
    known = {n["series"] + ":" + n["number"] for n in nodes}
    stats["senato_docs"] = len(nodes)
    return {
        "nodes": nodes,
        "discusses": [{"debate": x["debate"], "uri": doc_uri("senato", leg, *x["key"])}
                      for x in discusses if ":".join(x["key"]) in known],
        "on_act": [{"vote": x["vote"], "uri": doc_uri("senato", leg, *x["key"])}
                   for x in on_act if ":".join(x["key"]) in known],
    }


def plan_processes(leg: int, docs: list[dict], stats: Counter) -> list[dict]:
    """PART_OF rows for the Government documents present in both chambers with the same date."""
    by_key: dict[tuple[str, str], dict[str, dict]] = defaultdict(dict)
    for d in docs:
        if d["series"] in GOV_SERIES:
            by_key[(d["series"], d["number"])][d["chamber"]] = d
    rows = []
    for key, pair in sorted(by_key.items()):
        if set(pair) != {"camera", "senato"}:
            continue
        cam, sen = pair["camera"], pair["senato"]
        if cam.get("date") and sen.get("date") and \
                abs((date.fromisoformat(cam["date"]) - date.fromisoformat(sen["date"])).days) > 10:
            # Both chambers receive the document within days (NADEF 2022:
            # Senate 28/09, Camera 30/09/2022); months apart means another
            # document under the same number.
            stats["process_date_mismatch"] += 1
            logger.warning("%s: data Camera %s, Senato %s: non li unisco", doc_name(*key), cam["date"], sen["date"])
            continue
        pid = PROCESS_ID.format(leg=leg, series=key[0], number=key[1])
        title = sen.get("title") or cam.get("title")
        rows += [{"process": pid, "uri": d["uri"], "chamber": ch, "title": title} for ch, d in pair.items()]
    stats["processes"] = len(rows) // 2
    return rows


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

WRITE_NODES = """
UNWIND $rows AS row
MERGE (a:ParliamentaryAct {uri: row.uri})
SET a:ParliamentaryDocument, a.id = row.uri, a.kind = 'doc', a.type = 'doc', a.type_raw = 'doc',
    a.chamber = $chamber, a.legislature = $leg, a.doc_series = row.series, a.number = row.number,
    a.name = row.name, a.title = row.title, a.title_source = row.title_source,
    a.doc_type_raw = row.doc_type_raw, a.initiative = row.initiative, a.url = row.url,
    a.text_urls = row.text_urls, a.textPdfUrl = head(coalesce(row.text_urls, [])),
    a.official_uris = row.official_uris,
    a.date = CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END,
    a.presentation_date = CASE WHEN row.date IS NULL THEN null ELSE date(row.date) END
REMOVE a.isPlaceholder
"""

WRITE_DISCUSSES = """
UNWIND $rows AS row
MATCH (d:Debate {id: row.debate}) MATCH (a:ParliamentaryDocument {uri: row.uri})
MERGE (d)-[:DISCUSSES]->(a)
"""

WRITE_ON_ACT = """
UNWIND $rows AS row
MATCH (v:Vote {id: row.vote}) MATCH (a:ParliamentaryDocument {uri: row.uri})
MERGE (v)-[:ON_ACT]->(a)
"""

DROP_GUESSED = """
UNWIND $rows AS row
MATCH (v:Vote {id: row.vote})-[r:ON_ACT {inferred: 'vicini'}]->(a:ParliamentaryAct {uri: row.uri})
DELETE r
RETURN count(r) AS n
"""

WRITE_PROCESSES = """
UNWIND $rows AS row
MERGE (lp:LegislativeProcess {id: row.process})
SET lp.legislature = $leg, lp.title = row.title, lp.kind = 'doc'
WITH lp, row
MATCH (a:ParliamentaryDocument {uri: row.uri})
MERGE (a)-[r:PART_OF]->(lp)
SET r.chamber = row.chamber
"""

CAMERA_VOTES = """
MATCH (s:Session {chamber: 'camera', legislature: $leg})-[:HAS_VOTE]->(v:Vote)
WHERE v.description =~ '(?is).*\\\\bdoc\\\\b.*'
OPTIONAL MATCH (v)-[r:ON_ACT]->(a:ParliamentaryAct)
RETURN v.id AS id, v.description AS description,
       [x IN collect({uri: a.uri, inferred: r.inferred, doc: a:ParliamentaryDocument}) WHERE x.uri IS NOT NULL] AS acts
"""

CAMERA_PLACEHOLDER_DEBATES = """
MATCH (p:ParliamentaryAct {isPlaceholder: true}) WHERE p.type = 'doc' OR p:ParliamentaryDocument
OPTIONAL MATCH (d:Debate)-[:DISCUSSES]->(p)
RETURN p.uri AS uri, p.number AS number, collect(d.title) AS titles
"""


def match_reporters(session, rows: list[dict], leg: int, stats: Counter) -> list[dict]:
    """REPORTED_BY records (ingest_reporters format) for the names in the reports' titles."""
    from ingest_reporters import fold, match_deputy
    deputies = {}
    for r in session.run("""
            MATCH (p:Person) WHERE $m IN coalesce(p.mandates, [])
            RETURN p.id AS id, p.last_name AS last, p.first_name AS first""", m=f"camera_{leg}"):
        deputies[(fold(r["last"]), fold(r["first"]))] = r["id"]
    out = []
    for r in rows:
        person = match_deputy((fold(r["name"][0]), fold(r["name"][1])), deputies)
        if not person:
            stats["camera_reporter_unmatched"] += 1
            logger.warning("relatore %r di %s non trovato tra i deputati", r["name"], r["doc"])
            continue
        out.append({"bill": r["doc"], "person": person, "role": "relatore", "date": r["date"],
                    "venue": "assemblea", "committee": None, "source": "dati.camera.it"})
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--chamber", choices=["camera", "senato"], required=True)
    ap.add_argument("--download", action="store_true", help="read the sources again (else the copies in data/)")
    ap.add_argument("--check-pdfs", action="store_true",
                    help="Camera: look for the missing text links on camera.it (implied by --download)")
    ap.add_argument("--dry-run", action="store_true", help="read the graph, write nothing")
    ap.add_argument("--dump", help="write the planned rows to this JSON file")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    leg = args.legislature
    status = 0
    stats: Counter = Counter()
    senate: dict = {}
    if args.chamber == "senato" and args.download:
        from senate_sparql_ingester import SenateEndpointBlocked, SenateRequestFailed
        try:
            senate_download(leg)
        except (SenateEndpointBlocked, SenateRequestFailed, RuntimeError) as exc:
            logger.warning("dati.senato.it rifiuta la richiesta (%s): uso la copia in data/", exc)
            status = 3
    senate_path = os.path.join(DATA_DIR, f"senato_{ROMAN[leg]}_documenti.csv")
    if args.chamber == "senato" or os.path.exists(senate_path):
        senate = senate_index(leg)

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password),
                                  notifications_min_severity="OFF")
    with driver.session(default_access_mode="READ" if args.dry_run else "WRITE") as s:
        existing = {(r["series"], r["number"]) for r in s.run(
            "MATCH (a:ParliamentaryDocument {chamber: $c, legislature: $leg}) WHERE a.doc_series IS NOT NULL "
            "RETURN a.doc_series AS series, a.number AS number", c=args.chamber, leg=leg)}
        if args.chamber == "camera":
            records = camera_index(load_camera_records(leg, args.download))
            ph = [r.data() for r in s.run(CAMERA_PLACEHOLDER_DEBATES)]
            votes = [r.data() for r in s.run(CAMERA_VOTES, leg=leg)]
            debates = [{"title": t} for p in ph for t in p["titles"]] + [dict(r) for r in s.run("""
                MATCH (d:Debate)-[:DISCUSSES]->(:ParliamentaryDocument {chamber: 'camera'}) RETURN d.title AS title""")]
            plan = plan_camera(leg, records, senate, ph, votes, debates, existing, stats)
            check_camera_pdfs(leg, plan["nodes"], args.download or args.check_pdfs, stats)
            plan["discusses"] = []
        else:
            vote_docs = senate_vote_docs(leg, {u: k for k, v in senate.items() for u in v["uris"]})
            votes = {r["id"] for r in s.run(
                "MATCH (:Session {chamber: 'senato', legislature: $leg})-[:HAS_VOTE]->(v:Vote) RETURN v.id AS id",
                leg=leg)}
            bill_votes = {r["id"] for r in s.run("""
                MATCH (:Session {chamber: 'senato', legislature: $leg})-[:HAS_VOTE]->(v:Vote)-[r:ON_ACT]->(:Bill)
                WHERE r.inferred IS NULL RETURN DISTINCT v.id AS id""", leg=leg)}
            sittings: dict[int, list[dict]] = defaultdict(list)
            for r in s.run("""
                    MATCH (x:Session {chamber: 'senato', legislature: $leg})-[:HAS_DEBATE]->(d:Debate)
                    RETURN x.number AS n, x.id AS session, d.id AS id, d.title AS title, d.order AS order""", leg=leg):
                sittings[r["n"]].append(r.data())
            plan = plan_senate(leg, senate, vote_docs, votes, bill_votes, sittings, existing, stats,
                               os.path.join(DATA_DIR, "senate_xml"))
            plan["drop"], plan["reporters"] = [], []
        stats["discusses"] = len(plan["discusses"])
        stats["on_act"] = len(plan["on_act"])
        stats["on_act_votes"] = len({x["vote"] for x in plan["on_act"]})
        stats["guessed_on_act_to_drop"] = len(plan["drop"])
        reporters = match_reporters(s, plan["reporters"], leg, stats) if plan["reporters"] else []
        stats["reporters"] = len(reporters)

        other = "senato" if args.chamber == "camera" else "camera"
        others = [dict(r) for r in s.run("""
            MATCH (a:ParliamentaryDocument {chamber: $c, legislature: $leg}) WHERE a.doc_series IN $series
            RETURN a.uri AS uri, a.doc_series AS series, a.number AS number, toString(a.date) AS date,
                   a.title AS title, $c AS chamber""", c=other, leg=leg, series=list(GOV_SERIES))]
        mine = [{**n, "chamber": args.chamber} for n in plan["nodes"]]
        processes = plan_processes(leg, mine + others, stats)

        if args.dump:
            with open(args.dump, "w", encoding="utf-8") as f:
                json.dump({**plan, "reporters_matched": reporters, "processes": processes}, f,
                          ensure_ascii=False, indent=1, default=str)
        if not args.dry_run:
            s.run("CREATE CONSTRAINT legislative_process_id IF NOT EXISTS "
                  "FOR (lp:LegislativeProcess) REQUIRE lp.id IS UNIQUE").consume()
            s.run(WRITE_NODES, rows=plan["nodes"], chamber=args.chamber, leg=leg).consume()
            s.run(WRITE_DISCUSSES, rows=plan["discusses"]).consume()
            s.run(WRITE_ON_ACT, rows=plan["on_act"]).consume()
            stats["guessed_on_act_dropped"] = s.run(DROP_GUESSED, rows=plan["drop"]).single()["n"]
            s.run(WRITE_PROCESSES, rows=processes, leg=leg).consume()
            if reporters:
                from ingest_reporters import merge_reports, write_records
                write_records(s, merge_reports(reporters), "dati.camera.it", "camera", None, stats, False)
    driver.close()
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    return status


if __name__ == "__main__":
    sys.exit(main())
