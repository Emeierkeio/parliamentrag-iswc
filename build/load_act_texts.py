#!/usr/bin/env python3
"""
Text of the Chamber's bills (every version) into the text archive.

The graph knows each version of a Chamber bill as a TextVersion node, whose id
carries the document code (vta19_leg.19.pdl.camera.2715_A.19PDL0217670), but
not its text. documenti.camera.it serves every version as HTML; this script
downloads it, keeps two sections and writes them to the archive:

  articolato   the articles; for a committee text (-A) the committee column
               of the side-by-side table, the proposers' column where the
               committee wrote «Identico», nothing where it wrote «Soppresso»
  relazione    the report that introduces the bill (RL)

Committee opinions, technical reports and supplements (impact analyses) are
left out. Archive (Postgres, same database as build/pg_archive.py):

  act_text        one row per version and section, with the text
  act_text_chunk  chunks keyed by text_hash, with the embedding

  python build/load_act_texts.py --neo4j-uri bolt://localhost:7690 \\
      --archive-url postgresql://...@localhost:5433/archivio --dry-run
  python build/load_act_texts.py --acts 2715,3131 --dry-run    # no graph needed

Versions come from the graph (--neo4j-uri) or, with --acts, from the act pages
on camera.it. Downloads are cached in downloads/testi_atti/camera/, so a run
fetches only versions it has not seen. Rows are written only when their hash
changed; embeddings only for chunks that have none.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from load_emendamenti import EMBEDDING_DIM, EMBEDDING_PRICE_PER_M, Embedder, _vector_text, chunk_text  # noqa: E402

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE = REPO_ROOT / "downloads" / "testi_atti" / "camera"
DOC_URL = ("https://documenti.camera.it/apps/commonServices/getDocumento.ashx"
           "?sezione=lavori&tipoDoc=testo_pdl&idlegislatura={leg}&codice={code}")
ACT_PAGE = "https://www.camera.it/leg{leg}/126?tab=1&leg={leg}&idDocumento={number}"
# documenti.camera.it answers an empty body to a browser-like user agent
# without its cookies (2026-10-22); a plain project agent gets the page.
USER_AGENT = "ParliamentRAG/1.0 (+https://www.parliamentrag.it)"
REQUEST_PAUSE = 1.0
# Part of every row hash: bump it when the parser changes, so that the next run
# rewrites the rows and re-embeds the texts that changed.
PARSER_VERSION = 1

CODE_RE = re.compile(r"leg\.(\d+)\.pdl\.camera\.([^.]+?)(?:_([^.]+))?\.(\d+PDL\w+)$")


# ------------------------------------------------------------------ parsing

def _clean(fragment: str) -> str:
    t = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", fragment)
    t = re.sub(r"(?i)<br\s*/?>", "\n", t)
    t = re.sub(r"(?i)</(p|div|tr|li|h\d)>", "\n", t)
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).replace("\xa0", " ")
    t = re.sub(r"[ \t]+", " ", t)
    return "\n".join(line.strip() for line in t.split("\n") if line.strip())


IDENTICAL = re.compile(r"^\s*(?:\d+\.\s*)?identic[oa]\.?\s*$", re.I)
SUPPRESSED = re.compile(r"^\s*(?:\d+\.\s*)?soppress[oa]\.?\s*$", re.I)
CELL = re.compile(r'(?is)<td\b[^>]*width="50%"[^>]*>(.*?)</td>')


def side_by_side(fragment: str) -> str:
    """The committee text of a two-column table (proposers | committee)."""
    out = []
    for row in re.findall(r"(?is)<tr\b[^>]*>(.*?)</tr>", fragment):
        cells = CELL.findall(row)
        if len(cells) != 2:
            continue
        left, right = _clean(cells[0]), _clean(cells[1])
        if IDENTICAL.match(right):
            out.append(left)
        elif not right or SUPPRESSED.match(right):
            continue
        else:
            out.append(right)
    return "\n".join(x for x in out if x)


SECTION_ID = re.compile(r'<div\b[^>]*\sid="([^"]+)"')
TOP_SECTIONS = re.compile(r"^(FR|RL|RT|PD|TFPD|AI(_\d+)?|AL\.\d+|pareri\.\d+|note|metadati)$")


def _body(raw: str) -> str:
    """The document between the table of contents and the site footer."""
    start = raw.find('id="telecomando"')
    if start >= 0:
        end_toc = raw.find("</div>", start)
        raw = raw[end_toc + 6:] if end_toc >= 0 else raw[start:]
    for marker in ("Per tornare alla pagina di provenienza", 'id="tree_menu', 'id="free_code'):
        cut = raw.find(marker)
        if cut >= 0:
            raw = raw[:cut]
    return raw


def sections(raw: str) -> dict[str, str]:
    """Top-level sections of a document, by div id, in document order."""
    body = _body(raw)
    starts = [(m.start(), m.group(1)) for m in SECTION_ID.finditer(body) if TOP_SECTIONS.match(m.group(1))]
    out: dict[str, str] = {}
    for i, (pos, name) in enumerate(starts):
        end = starts[i + 1][0] if i + 1 < len(starts) else len(body)
        out.setdefault(name, body[pos:end])
    return out


def parse_document(raw: str) -> dict:
    """{'articolato', 'relazione', 'kind'} of one Chamber bill version."""
    secs = sections(raw)
    body = _body(raw)
    articles = ""
    if "TFPD" in secs or CELL.search(secs.get("PD", "")):
        articles = side_by_side(secs.get("TFPD") or secs["PD"])
    elif "PD" in secs:
        articles = _clean(secs["PD"])
    else:
        first = re.search(r'<div\b[^>]*class="articolo"', body)
        if first:
            articles = _clean(body[first.start():])
    report = _clean(secs["RL"]) if "RL" in secs else ""
    if articles:
        kind = "testo"
    elif report:
        kind = "relazione"
    elif any(re.match(r"AI(_\d+)?$|RT$", s) for s in secs):
        kind = "supplemento"
    else:
        kind = "altro"
    return {"articolato": articles, "relazione": report, "kind": kind}


def version_of(code: str) -> dict | None:
    """Act number, version label and document id from a document code."""
    m = CODE_RE.search(code)
    if not m:
        return None
    return {"leg": int(m.group(1)), "number": m.group(2), "label": m.group(3), "doc": m.group(4)}


# ------------------------------------------------------------------ sources

def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read().decode("utf-8", "replace")


def versions_from_graph(uri: str, user: str, password: str, leg: int) -> list[dict]:
    from neo4j import GraphDatabase

    query = """
    MATCH (a)-[:HAS_VERSION]->(v:TextVersion)
    WHERE v.id CONTAINS $prefix
    RETURN a.uri AS act, v.id AS id, v.label AS label, v.date AS date, v.title AS title
    """
    with GraphDatabase.driver(uri, auth=(user, password)) as driver:
        rows = driver.execute_query(query, prefix=f"leg.{leg}.pdl.camera.").records
    out = []
    for r in rows:
        code = r["id"].split(f"vta{leg}_", 1)[-1]
        if version_of(code):
            out.append({"act": r["act"], "id": r["id"], "code": code, "label": r["label"],
                        "date": str(r["date"]) if r["date"] else None, "title": r["title"]})
    return out


def versions_from_pages(numbers: list[str], leg: int) -> list[dict]:
    out = []
    for n in numbers:
        page = fetch(ACT_PAGE.format(leg=leg, number=n))
        codes = sorted(set(re.findall(r"tipoDoc=testo_pdl&(?:amp;)?idlegislatura=\d+&(?:amp;)?codice=([^\"&]+)", page)))
        for code in codes:
            out.append({"act": f"http://dati.camera.it/ocd/attocamera.rdf/ac{leg}_{n}",
                        "id": f"http://dati.camera.it/ocd/versioneTestoAtto.rdf/vta{leg}_{code}",
                        "code": code, "label": (version_of(code) or {}).get("label"), "date": None, "title": None})
        time.sleep(REQUEST_PAUSE)
    return out


def document(code: str, leg: int, stats: Counter, offline: bool = False) -> str | None:
    path = CACHE / f"{code}.html"
    if path.exists() and path.stat().st_size > 0:
        stats["docs.cached"] += 1
        return path.read_text(encoding="utf-8")
    if offline:
        stats["docs.missing"] += 1
        return None
    try:
        raw = fetch(DOC_URL.format(leg=leg, code=code))
    except Exception as e:  # noqa: BLE001 - urllib raises several types for one failed request
        logger.warning("%s: %s", code, e)
        stats["docs.failed"] += 1
        return None
    finally:
        time.sleep(REQUEST_PAUSE)
    if not raw.strip():
        stats["docs.empty"] += 1
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    stats["docs.downloaded"] += 1
    return raw


def rows_for(version: dict, parsed: dict, leg: int) -> list[dict]:
    meta = version_of(version["code"]) or {}
    out = []
    for section in ("articolato", "relazione"):
        text = parsed[section]
        if not text:
            continue
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        row = {"id": f"{version['id']}#{section}", "version_id": version["id"], "chamber": "camera", "term": leg,
               "act": version["act"], "act_number": meta.get("number"), "version_label": meta.get("label"),
               "version_code": version["code"], "section": section, "kind": parsed["kind"],
               "title": version.get("title"), "date": version.get("date"), "text": text, "text_hash": text_hash,
               "source_url": DOC_URL.format(leg=leg, code=version["code"])}
        row["row_hash"] = hashlib.sha256(json.dumps(
            [PARSER_VERSION] + [row[k] for k in ROW_COLUMNS if k != "row_hash"], default=str).encode()).hexdigest()
        out.append(row)
    return out


# ------------------------------------------------------------------ archive

ROW_COLUMNS = ("id", "version_id", "chamber", "term", "act", "act_number", "version_label", "version_code",
               "section", "kind", "title", "date", "text", "text_hash", "source_url", "row_hash")

ARCHIVE_SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS act_text (
    id             text PRIMARY KEY,       -- TextVersion id + '#articolato' | '#relazione'
    version_id     text NOT NULL,
    chamber        text NOT NULL,
    term           integer NOT NULL,
    act            text,                   -- act URI in the graph
    act_number     text,                   -- '2715'
    version_label  text,                   -- 'A', 'A-bis', NULL for the text as presented
    version_code   text NOT NULL,
    section        text NOT NULL,          -- 'articolato' | 'relazione'
    kind           text,
    title          text,
    date           date,
    text           text NOT NULL,
    text_hash      text NOT NULL,
    source_url     text,
    row_hash       text NOT NULL
);

CREATE INDEX IF NOT EXISTS act_text_act ON act_text (chamber, term, act);
CREATE INDEX IF NOT EXISTS act_text_hash ON act_text (text_hash);

CREATE TABLE IF NOT EXISTS act_text_chunk (
    text_hash   text NOT NULL,
    chunk_index integer NOT NULL,
    text        text NOT NULL,
    embedding   halfvec({EMBEDDING_DIM}),
    PRIMARY KEY (text_hash, chunk_index)
);
"""

ARCHIVE_HNSW = """
CREATE INDEX IF NOT EXISTS act_text_chunk_embedding_hnsw
    ON act_text_chunk USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""


def load_archive(rows: list[dict], args, stats: Counter) -> None:
    import psycopg

    with psycopg.connect(args.archive_url) as conn:
        conn.execute(ARCHIVE_SCHEMA)
        conn.commit()
        existing = dict(conn.execute("SELECT id, row_hash FROM act_text WHERE chamber = 'camera' AND term = %s",
                                     [args.leg]).fetchall())
        changed = [r for r in rows if existing.get(r["id"]) != r["row_hash"]]
        stats["archive.rows_written"] = len(changed)
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS act_text_in (LIKE act_text) ON COMMIT DELETE ROWS")
            with cur.copy(f"COPY act_text_in ({', '.join(ROW_COLUMNS)}) FROM STDIN") as copy:
                for r in changed:
                    copy.write_row([r[c] for c in ROW_COLUMNS])
            updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in ROW_COLUMNS if c != "id")
            cur.execute(f"INSERT INTO act_text SELECT * FROM act_text_in ON CONFLICT (id) DO UPDATE SET {updates}")
            cur.execute("""
                SELECT DISTINCT ON (t.text_hash) t.text_hash, t.text FROM act_text t
                WHERE NOT EXISTS (SELECT 1 FROM act_text_chunk c WHERE c.text_hash = t.text_hash)
            """)
            missing = cur.fetchall()
            with cur.copy("COPY act_text_chunk (text_hash, chunk_index, text) FROM STDIN") as copy:
                for h, text in missing:
                    for k, chunk in enumerate(chunk_text(text)):
                        copy.write_row((h, k, chunk))
            stats["archive.chunk_hashes_added"] = len(missing)
        conn.commit()
        if not args.skip_embeddings:
            embed_missing(conn, args, stats)
        conn.execute("SET max_parallel_maintenance_workers = 0")
        conn.execute(ARCHIVE_HNSW)
        conn.commit()


def embed_missing(conn, args, stats: Counter) -> None:
    keys = [k.strip() for k in (os.environ.get("OPENAI_API_KEY") or "").split(",") if k.strip()]
    todo = conn.execute("SELECT text_hash, chunk_index, text FROM act_text_chunk WHERE embedding IS NULL "
                        "ORDER BY text_hash, chunk_index").fetchall()
    stats["embed.chunks_todo"] = len(todo)
    if not todo or not keys:
        if todo:
            logger.warning("OPENAI_API_KEY missing: %d chunks left without embedding", len(todo))
        return
    embedder = Embedder(keys, args.embed_workers)
    per_request = 200
    for i in range(0, len(todo), per_request * args.embed_workers):
        block = todo[i:i + per_request * args.embed_workers]
        batches = [block[j:j + per_request] for j in range(0, len(block), per_request)]
        vectors = embedder.embed([[t for _, _, t in b] for b in batches])
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS act_emb_in "
                        f"(text_hash text, chunk_index integer, embedding halfvec({EMBEDDING_DIM})) "
                        "ON COMMIT DELETE ROWS")
            with cur.copy("COPY act_emb_in FROM STDIN") as copy:
                for b, vs in zip(batches, vectors):
                    for (h, k, _), vec in zip(b, vs):
                        copy.write_row((h, k, _vector_text(vec)))
            cur.execute("UPDATE act_text_chunk c SET embedding = e.embedding FROM act_emb_in e "
                        "WHERE c.text_hash = e.text_hash AND c.chunk_index = e.chunk_index")
        conn.commit()
    stats["embed.tokens"] = embedder.tokens
    logger.info("embeddings: %d chunks, %d tokens, USD %.4f", len(todo), embedder.tokens,
                embedder.tokens / 1e6 * EMBEDDING_PRICE_PER_M)


def mark_graph(rows: list[dict], args) -> None:
    """TextVersion.text_sections: which sections the archive holds."""
    from neo4j import GraphDatabase

    by_version: dict[str, list[str]] = {}
    for r in rows:
        by_version.setdefault(r["version_id"], []).append(r["section"])
    batch = [{"id": k, "sections": sorted(v)} for k, v in by_version.items()]
    with GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password)) as driver:
        driver.execute_query("UNWIND $rows AS row MATCH (v:TextVersion {id: row.id}) "
                             "SET v.text_sections = row.sections", rows=batch)


# --------------------------------------------------------------------- main

def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--neo4j-uri", help="read the versions from the graph")
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--acts", help="comma-separated Chamber act numbers, read from camera.it instead of the graph")
    ap.add_argument("--archive-url", help="Postgres archive; omitted, nothing is written")
    ap.add_argument("--dry-run", action="store_true", help="download and parse, write nothing")
    ap.add_argument("--limit", type=int, help="only the first N versions")
    ap.add_argument("--offline", action="store_true", help="use the cache only")
    ap.add_argument("--skip-embeddings", action="store_true")
    ap.add_argument("--embed-workers", type=int, default=4)
    args = ap.parse_args()

    if args.acts:
        versions = versions_from_pages([a.strip() for a in args.acts.split(",") if a.strip()], args.leg)
    elif args.neo4j_uri:
        if not args.neo4j_password:
            ap.error("--neo4j-password or NEO4J_PASSWORD needed")
        versions = versions_from_graph(args.neo4j_uri, args.neo4j_user, args.neo4j_password, args.leg)
    else:
        ap.error("give --neo4j-uri or --acts")
    versions.sort(key=lambda v: v["code"])
    if args.limit:
        versions = versions[:args.limit]
    logger.info("%d versions", len(versions))

    stats: Counter = Counter()
    rows: list[dict] = []
    for i, v in enumerate(versions, 1):
        raw = document(v["code"], args.leg, stats, args.offline)
        if raw is None:
            continue
        parsed = parse_document(raw)
        stats[f"kind.{parsed['kind']}"] += 1
        rows.extend(rows_for(v, parsed, args.leg))
        if i % 100 == 0:
            logger.info("%d/%d versions", i, len(versions))

    chunks = sum(len(chunk_text(t)) for t in {r["text_hash"]: r["text"] for r in rows}.values())
    chars = sum(len(r["text"]) for r in rows)
    stats["rows"] = len(rows)
    stats["chunks"] = chunks
    # ~4 characters per token for Italian prose with this tokenizer (2026-10, amendments archive).
    stats["est_usd"] = round(chars / 4 / 1e6 * EMBEDDING_PRICE_PER_M, 4)
    logger.info("%d rows, %.1fM characters, %d chunks, ~USD %.2f to embed", len(rows), chars / 1e6, chunks,
                stats["est_usd"])
    if args.archive_url and not args.dry_run:
        load_archive(rows, args, stats)
        if args.neo4j_uri:
            mark_graph(rows, args)
    logger.info("done%s: %s", " (dry run)" if args.dry_run else "", json.dumps(dict(sorted(stats.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
