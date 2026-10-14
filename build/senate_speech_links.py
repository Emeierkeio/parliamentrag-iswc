#!/usr/bin/env python3
"""
Links to the exact speech on senato.it for Senate Speech nodes.

A sitting record on senato.it (show-doc?leg=19&tipodoc=Resaula&id=<BGT id>)
has a table of contents listing every intervention of the stenographic
record in document order, each with its own anchor:

    ...&part=doc_dc-ressten_rs-<section>-intervento_<speaker slug>[:N]

The AKN file of the same sitting lists the same interventions as <an:speech>
elements, without ids. Graph Speech ids come from senate_parser.py, so
re-parsing the AKN file tells which element each graph Speech starts at, and
the element's position gives the TOC part.

Modes (each idempotent):

  sittings  no network. Session.record_url = sitting page (from bgt_index.json);
            Speech.url = record_url for every Senate speech without an exact link.
  toc       fetches the sitting page of up to --limit sittings whose TOC is not
            cached (data/senate_toc/<bgt>.json), newest first. senato.it sits
            behind AWS WAF and blocks an IP after ~400 requests: stops at the
            first refusal and exits 3, the next run resumes.
  anchor    no network. Speech.url = sitting page + &part=... for every speech
            whose sitting has a cached TOC that lines up with the AKN file.

    build/senate_speech_links.py sittings --neo4j-uri bolt://localhost:7692
    build/senate_speech_links.py toc --limit 40
    build/senate_speech_links.py anchor --neo4j-uri bolt://localhost:7692
"""

from __future__ import annotations

import argparse
import glob
import html
import json
import logging
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from build_config import load_config  # noqa: E402
from senate_parser import AKN_NS, SenateStenograficoParser  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(REPO, "build", "config.yaml")
XML_DIR = os.path.join(REPO, "data", "senate_xml")
TOC_DIR = os.path.join(REPO, "data", "senate_toc")

SITTING_URL = "https://www.senato.it/show-doc?leg={leg}&tipodoc=Resaula&id={bgt}&idoggetto=0"
RECORD_PREFIX = "doc_dc-ressten_rs"
EXIT_BLOCKED = 3
# A sitting whose TOC and AKN speakers agree less than this is misaligned:
# its speeches keep the sitting link.
MIN_SITTING_AGREEMENT = 0.9

_PART_RE = re.compile(r'class="toc-link"\s+data-part="([^"]*)"')
_FILE_RE = re.compile(r"resaula_leg(\d+)_(\d+)\.(akn|html)$")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def letters(text: str) -> str:
    """Lowercase ASCII letters only, as in senato.it part slugs."""
    text = unicodedata.normalize("NFKD", text)
    return re.sub(r"[^a-z]", "", text.encode("ascii", "ignore").decode().lower())


def part_url(sitting_url: str, part: str) -> str:
    return f"{sitting_url}&part={quote(part, safe='-_')}"


def speaker_slug(part: str) -> str:
    """'...-intervento_gaudianom5s:1' -> 'gaudianom5s'."""
    return part.rsplit("-", 1)[-1].split(":", 1)[0].removeprefix("intervento_")


def load_sittings(xml_dir: str, legislature: int) -> dict[int, dict]:
    """{sitting number: {bgt, file}} from bgt_index.json."""
    path = os.path.join(xml_dir, "bgt_index.json")
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    sittings: dict[int, dict] = {}
    for bgt, filename in index.items():
        m = _FILE_RE.search(filename)
        if not m or int(m.group(1)) != legislature:
            continue
        sittings[int(m.group(2))] = {"bgt": bgt, "file": os.path.join(xml_dir, filename)}
    return sittings


def session_id(legislature: int, number: int) -> str:
    return f"sen_leg{legislature}_sed{number}"


def extract_interventions(page: str) -> Optional[list[str]]:
    """Intervention parts of the stenographic record, in document order.

    None when the page has no table of contents (not a sitting record).
    """
    start = page.find("block-showdoc-toc")
    if start < 0:
        return None
    parts = [html.unescape(p) for p in _PART_RE.findall(page[start:])]
    if not parts:
        return None
    return [
        p for p in parts
        if p.startswith(RECORD_PREFIX + "-") and p.rsplit("-", 1)[-1].startswith("intervento_")
    ]


def akn_interventions(root) -> list:
    """<an:speech> elements that open an intervention, in document order.

    Blocks with an empty speaker (by="#p") continue the previous speech after
    an interruption and have no entry of their own in the TOC.
    """
    return [
        el for el in root.iter(f"{{{AKN_NS}}}speech")
        if el.get("by", "").lstrip("#") not in ("", "p")
    ]


def akn_surname(el) -> str:
    """Normalized speaker label of an AKN speech: 'DE CRISTOFARO' -> 'decristofaro'."""
    frm = el.find(f"{{{AKN_NS}}}from")
    text = "".join(frm.itertext()) if frm is not None else ""
    return letters(text.split(",", 1)[0])


class _TrackingParser(SenateStenograficoParser):
    """senate_parser with each speech tagged by the element it starts at."""

    debate_root = None

    def _build_lookups(self, debate_elem):
        # Called once per file, before any speech: the <an:debate> element
        # whose <an:speech> descendants the parser walks.
        self.debate_root = debate_elem
        return super()._build_lookups(debate_elem)

    def _parse_speech(self, speech_elem, *args, **kwargs):
        speech = super()._parse_speech(speech_elem, *args, **kwargs)
        if speech is not None:
            speech["_elem"] = speech_elem
        return speech


def speech_parts(akn_path: str, toc: list[str], parser: _TrackingParser) -> tuple[dict, dict]:
    """{graph speech id: (part, akn surname)} for one sitting, plus stats."""
    stats = {"akn": 0, "toc": len(toc), "agree": 0, "aligned": False}
    parsed = parser.parse_xml_file(akn_path)
    elems = akn_interventions(parser.debate_root)
    stats["akn"] = len(elems)
    if len(elems) != len(toc):
        return {}, stats
    surnames = [akn_surname(el) for el in elems]
    agree = [bool(s) and speaker_slug(p).startswith(s) for s, p in zip(surnames, toc)]
    stats["agree"] = sum(agree)
    if not toc or stats["agree"] / len(toc) < MIN_SITTING_AGREEMENT:
        return {}, stats
    stats["aligned"] = True
    position = {id(el): i for i, el in enumerate(elems)}
    result = {}
    for speech in parsed["speeches"]:
        i = position.get(id(speech.pop("_elem", None)))
        if i is not None and agree[i]:
            result[speech["id"]] = (toc[i], surnames[i])
    return result, stats


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def _driver(args):
    from neo4j import GraphDatabase

    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD is required")
    return GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))


def _write(driver, cypher: str, rows: list[dict], batch: int = 2000) -> int:
    done = 0
    with driver.session() as s:
        for i in range(0, len(rows), batch):
            done += s.run(cypher, rows=rows[i:i + batch]).single()["n"]
    return done


def graph_sittings(driver, legislature: int) -> dict[int, str]:
    with driver.session() as s:
        return {
            r["number"]: r["id"]
            for r in s.run(
                "MATCH (s:Session {chamber: 'senato', legislature: $leg}) "
                "RETURN s.number AS number, s.id AS id",
                leg=legislature,
            )
        }


def graph_speeches(driver, legislature: int) -> list[dict]:
    with driver.session() as s:
        return [
            dict(r) for r in s.run(
                "MATCH (sp:Speech) WHERE sp.id STARTS WITH $prefix "
                "RETURN sp.id AS id, sp.url AS url, sp.cognomeNome AS name",
                prefix=f"sen_leg{legislature}_sed",
            )
        ]


def _sitting_of(speech_id: str) -> Optional[int]:
    m = re.match(r"sen_leg\d+_sed(\d+)_", speech_id)
    return int(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def cmd_sittings(args) -> int:
    sittings = load_sittings(args.xml_dir, args.legislature)
    driver = _driver(args)
    try:
        in_graph = graph_sittings(driver, args.legislature)
        rows = [
            {"id": sid, "url": SITTING_URL.format(leg=args.legislature, bgt=sittings[n]["bgt"])}
            for n, sid in in_graph.items() if n in sittings
        ]
        missing = sorted(n for n in in_graph if n not in sittings)
        n = _write(driver, "UNWIND $rows AS row MATCH (s:Session {id: row.id}) "
                           "SET s.record_url = row.url RETURN count(s) AS n", rows)
        logger.info("Sessions with record_url: %d (no BGT id: %s)", n, missing or "none")

        record = {r["id"]: r["url"] for r in rows}
        speech_rows = []
        for sp in graph_speeches(driver, args.legislature):
            if sp["url"] and "&part=" in sp["url"]:
                continue
            number = _sitting_of(sp["id"])
            url = record.get(session_id(args.legislature, number)) if number else None
            if url and sp["url"] != url:
                speech_rows.append({"id": sp["id"], "url": url})
        n = _write(driver, "UNWIND $rows AS row MATCH (sp:Speech {id: row.id}) "
                           "SET sp.url = row.url RETURN count(sp) AS n", speech_rows)
        logger.info("Speeches linked to their sitting page: %d", n)
    finally:
        driver.close()
    return 0


def cmd_toc(args) -> int:
    import download_senate as ds

    sittings = load_sittings(args.xml_dir, args.legislature)
    os.makedirs(args.toc_dir, exist_ok=True)
    pending = [
        (n, s) for n, s in sorted(sittings.items(), reverse=True)
        if s["file"].endswith(".akn")
        and not os.path.exists(os.path.join(args.toc_dir, f"{s['bgt']}.json"))
    ]
    logger.info("TOC cached for %d sittings, %d to fetch, limit %d",
                len([s for s in sittings.values() if os.path.exists(
                    os.path.join(args.toc_dir, f"{s['bgt']}.json"))]),
                len(pending), args.limit)
    if not pending or args.limit <= 0:
        return 0

    # The WAF does not always challenge: with no token cookie the pages may
    # still load, and a challenge or refusal stops the loop below.
    token = ds._get_waf_token()
    session = ds._make_session(token or "")
    if not token:
        session.cookies.clear()

    fetched = 0
    for number, s in pending[: args.limit]:
        if fetched:
            time.sleep(args.delay)
        url = SITTING_URL.format(leg=args.legislature, bgt=s["bgt"])
        try:
            response = session.get(url, timeout=60)
        except Exception as exc:  # network error: not a block, try the next run
            logger.warning("Sitting %d: %s — stopping", number, exc)
            return 1
        if response.status_code == 403 or ds._is_challenge(response):
            logger.warning("Sitting %d: senato.it refused the request (HTTP %d) — stopping, "
                           "resume on the next run", number, response.status_code)
            return EXIT_BLOCKED
        if response.status_code != 200:
            logger.warning("Sitting %d: HTTP %d — skipped", number, response.status_code)
            continue
        interventions = extract_interventions(response.text)
        if interventions is None:
            logger.warning("Sitting %d: no table of contents on the page — skipped", number)
            continue
        with open(os.path.join(args.toc_dir, f"{s['bgt']}.json"), "w", encoding="utf-8") as f:
            json.dump({
                "bgt": s["bgt"],
                "legislature": args.legislature,
                "sitting": number,
                "fetched": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "interventions": interventions,
            }, f, ensure_ascii=False, indent=1)
        fetched += 1
        logger.info("Sitting %d (BGT %s): %d interventions", number, s["bgt"], len(interventions))
    logger.info("TOC fetched: %d", fetched)
    return 0


def cmd_anchor(args) -> int:
    sittings = load_sittings(args.xml_dir, args.legislature)
    parser = _TrackingParser(load_config(CONFIG_PATH), legislature=args.legislature)

    exact: dict[str, dict] = {}
    report = {"cached": 0, "aligned": 0, "count_mismatch": [], "disagree": []}
    for number, s in sorted(sittings.items()):
        toc_path = os.path.join(args.toc_dir, f"{s['bgt']}.json")
        if not s["file"].endswith(".akn") or not os.path.exists(toc_path):
            continue
        report["cached"] += 1
        with open(toc_path, encoding="utf-8") as f:
            toc = json.load(f)["interventions"]
        parts, stats = speech_parts(s["file"], toc, parser)
        if not stats["aligned"]:
            key = "count_mismatch" if stats["akn"] != stats["toc"] else "disagree"
            report[key].append((number, stats["akn"], stats["toc"], stats["agree"]))
            continue
        report["aligned"] += 1
        sitting_url = SITTING_URL.format(leg=args.legislature, bgt=s["bgt"])
        for speech_id, (part, surname) in parts.items():
            exact[speech_id] = {"url": part_url(sitting_url, part), "slug": speaker_slug(part)}

    logger.info("Sittings with cached TOC: %d, aligned: %d", report["cached"], report["aligned"])
    for number, akn, toc, _ in report["count_mismatch"]:
        logger.warning("Sitting %d: %d AKN interventions vs %d in the TOC — sitting link kept",
                       number, akn, toc)
    for number, akn, toc, agree in report["disagree"]:
        logger.warning("Sitting %d: speakers agree on %d/%d — sitting link kept", number, agree, toc)

    driver = _driver(args)
    try:
        rows, checked, name_ok, samples = [], 0, 0, []
        for sp in graph_speeches(driver, args.legislature):
            hit = exact.get(sp["id"])
            if hit is None:
                continue
            checked += 1
            surname = letters(sp["name"] or "")
            if surname and hit["slug"].startswith(surname):
                name_ok += 1
            elif len(samples) < 10:
                samples.append((sp["id"], sp["name"], hit["slug"]))
            if sp["url"] != hit["url"]:
                rows.append({"id": sp["id"], "url": hit["url"]})
        n = _write(driver, "UNWIND $rows AS row MATCH (sp:Speech {id: row.id}) "
                           "SET sp.url = row.url RETURN count(sp) AS n", rows)
        with driver.session() as s:
            total = s.run(
                "MATCH (sp:Speech) WHERE sp.id STARTS WITH $p "
                "RETURN count(sp) AS all, count(CASE WHEN sp.url CONTAINS '&part=' THEN 1 END) AS exact",
                p=f"sen_leg{args.legislature}_sed",
            ).single()
    finally:
        driver.close()

    rate = name_ok / checked if checked else 0.0
    logger.info("Graph speeches in aligned sittings: %d; slug starts with the graph surname: "
                "%d (%.1f%%)", checked, name_ok, 100 * rate)
    for sample in samples:
        logger.info("  surname differs from slug: %s %r -> %s", *sample)
    logger.info("Exact links written now: %d; Senate speeches with an exact link: %d/%d",
                n, total["exact"], total["all"])
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    ap = argparse.ArgumentParser(description="Exact senato.it links for Senate speeches")
    ap.add_argument("mode", choices=["sittings", "toc", "anchor"])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    help="default: $NEO4J_PASSWORD")
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--xml-dir", default=XML_DIR)
    ap.add_argument("--toc-dir", default=TOC_DIR)
    ap.add_argument("--limit", type=int, default=40, help="toc: sitting pages per run")
    ap.add_argument("--delay", type=float, default=4.0, help="toc: seconds between pages")
    args = ap.parse_args()
    if args.mode == "toc" and args.delay < 4:
        ap.error("--delay must be at least 4 seconds")
    return {"sittings": cmd_sittings, "toc": cmd_toc, "anchor": cmd_anchor}[args.mode](args)


if __name__ == "__main__":
    sys.exit(main())
