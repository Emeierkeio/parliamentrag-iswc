#!/usr/bin/env python3
"""
Text archive on Postgres + pgvector: chunks of the speeches with their
embedding and the filter columns copied on the row, plus the full text of
every speech, so that a filtered vector
search is one query (PLAN_data_platform.md, section 9.3; decision of
2026-10-12: the Senate XIX text goes here instead of Neo4j).

  python build/pg_archive.py schema --pg postgresql://...
  python build/pg_archive.py load --pg postgresql://... --neo4j-uri bolt://localhost:7692 \
      --assembly senato --term 19

load copies the chunks of one assembly and term from Neo4j (text, embedding,
speech, sitting, speaker and the group the speaker belonged to on that day)
and the text of their speeches. The backend reads both through
backend/app/services/archive.py.
Idempotent: rows are upserted by chunk id.

  python build/pg_archive.py strip --pg postgresql://... --neo4j-uri bolt://... \
      --assembly senato --term 19

strip removes from Neo4j what the archive now holds: text and embedding of
each chunk whose archived text is identical, and the text of each speech that
is archived and already has its text_embedding (authority needs it). The
nodes and relations stay. load skips stripped chunks (no embedding left), so
the nightly sequence ingest -> embeddings -> load -> strip only moves the new
sittings. --sessions limits load and strip to some sitting numbers.

  python build/pg_archive.py meta --pg postgresql://... --neo4j-uri bolt://...

meta copies again speaker, group on the day and government flag of every
archived chunk from the graph, where they changed (a speech relinked to
another speaker after it was archived).
"""

import argparse
import logging
import os
import sys
import time

import psycopg

logger = logging.getLogger(__name__)

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS chunk (
    id            text PRIMARY KEY,
    assembly      text NOT NULL,          -- 'camera' | 'senato' | ...
    term          integer NOT NULL,       -- legislature
    session_id    text NOT NULL,
    session_date  date NOT NULL,
    debate_id     text,
    speech_id     text NOT NULL,
    chunk_index   integer,
    speaker_id    text,
    group_name    text,                   -- group of the speaker on session_date
    in_government boolean NOT NULL DEFAULT false,
    text          text NOT NULL,
    embedding     halfvec(1536) NOT NULL
);

CREATE INDEX IF NOT EXISTS chunk_scope_date ON chunk (assembly, term, session_date);
CREATE INDEX IF NOT EXISTS chunk_speech ON chunk (speech_id);
CREATE INDEX IF NOT EXISTS chunk_speaker ON chunk (speaker_id);

CREATE TABLE IF NOT EXISTS speech (
    id            text PRIMARY KEY,
    assembly      text NOT NULL,
    term          integer NOT NULL,
    session_date  date NOT NULL,
    text          text NOT NULL
);
"""

HNSW = """
CREATE INDEX IF NOT EXISTS chunk_embedding_hnsw
    ON chunk USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

EXPORT = """
MATCH (s:Session {chamber: $assembly, legislature: $term})
WHERE s.number IN $numbers
MATCH (s)-[:HAS_DEBATE]->(d:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
      -[:HAS_CHUNK]->(c:Chunk)
WHERE c.embedding IS NOT NULL
OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(p)
OPTIONAL MATCH (p)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
WHERE m.start_date <= s.date AND (m.end_date IS NULL OR m.end_date >= s.date)
  AND coalesce(m.chamber, 'camera') = $assembly
WITH s, d, sp, c, p, head(collect(g.name)) AS group_name
RETURN c.id AS id, s.id AS session_id, s.date AS session_date, d.id AS debate_id,
       sp.id AS speech_id, c.index AS chunk_index, p.id AS speaker_id, group_name,
       coalesce(sp.speaker_in_government, p:GovernmentMember AND NOT p:Deputy, false) AS in_government,
       c.text AS text, c.embedding AS embedding
"""

SPEECHES = """
MATCH (s:Session {chamber: $assembly, legislature: $term})
WHERE s.number IN $numbers
MATCH (s)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
WHERE sp.text IS NOT NULL AND EXISTS { (sp)-[:HAS_CHUNK]->() }
RETURN DISTINCT sp.id AS id, s.date AS session_date, sp.text AS text
"""

NEO4J_TEXT = """
MATCH (s:Session {chamber: $assembly, legislature: $term})
WHERE s.number IN $numbers
MATCH (s)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
OPTIONAL MATCH (sp)-[:HAS_CHUNK]->(c:Chunk)
WHERE c.text IS NOT NULL OR c.embedding IS NOT NULL
RETURN sp.id AS speech_id, sp.text AS speech_text,
       sp.text_embedding IS NOT NULL AS has_speech_embedding,
       collect([c.id, c.text]) AS chunks
"""

META = """
MATCH (s:Session {chamber: $assembly, legislature: $term})
WHERE s.number IN $numbers
MATCH (s)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
      -[:HAS_CHUNK]->(c:Chunk)
OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(p)
OPTIONAL MATCH (p)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
WHERE m.start_date <= s.date AND (m.end_date IS NULL OR m.end_date >= s.date)
  AND coalesce(m.chamber, 'camera') = $assembly
WITH sp, c, p, head(collect(g.name)) AS group_name
RETURN c.id AS id, p.id AS speaker_id, group_name,
       coalesce(sp.speaker_in_government, p:GovernmentMember AND NOT p:Deputy, false) AS in_government
"""

STRIP_CHUNKS = "UNWIND $ids AS cid MATCH (c:Chunk {id: cid}) REMOVE c.text, c.embedding"
STRIP_SPEECHES = "UNWIND $ids AS sid MATCH (sp:Speech {id: sid}) REMOVE sp.text"


def _session_numbers(driver, assembly: str, term: int, only=None) -> list:
    with driver.session() as s:
        numbers = sorted(r["n"] for r in s.run(
            "MATCH (x:Session {chamber: $a, legislature: $t}) RETURN x.number AS n",
            a=assembly, t=term))
    if only:
        numbers = [n for n in numbers if n in set(only)]
    return numbers


def cmd_schema(pg: str) -> None:
    with psycopg.connect(pg, autocommit=True) as conn:
        conn.execute(SCHEMA)
    logger.info("schema ready")


def _vector_text(values) -> str:
    return "[" + ",".join(f"{v:.6g}" for v in values) + "]"


def cmd_load(pg: str, neo4j_uri: str, user: str, password: str,
             assembly: str, term: int, sessions_per_batch: int, only=None) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    numbers = _session_numbers(driver, assembly, term, only)
    logger.info("%s %d: %d sittings", assembly, term, len(numbers))

    total = 0
    start = time.time()
    with psycopg.connect(pg) as conn:
        for i in range(0, len(numbers), sessions_per_batch):
            batch = numbers[i:i + sessions_per_batch]
            with driver.session() as s:
                rows = s.run(EXPORT, assembly=assembly, term=term, numbers=batch).data()
                speeches = s.run(SPEECHES, assembly=assembly, term=term, numbers=batch).data()
            with conn.cursor() as cur:
                cur.execute("CREATE TEMP TABLE IF NOT EXISTS chunk_in (LIKE chunk) ON COMMIT DELETE ROWS")
                with cur.copy(
                    "COPY chunk_in (id, assembly, term, session_id, session_date, debate_id, "
                    "speech_id, chunk_index, speaker_id, group_name, in_government, text, embedding) "
                    "FROM STDIN"
                ) as copy:
                    for r in rows:
                        copy.write_row((
                            r["id"], assembly, term, r["session_id"],
                            r["session_date"].to_native(), r["debate_id"], r["speech_id"],
                            r["chunk_index"], r["speaker_id"], r["group_name"],
                            bool(r["in_government"]), r["text"], _vector_text(r["embedding"]),
                        ))
                cur.execute("""
                    INSERT INTO chunk SELECT * FROM chunk_in
                    ON CONFLICT (id) DO UPDATE SET
                        session_date = EXCLUDED.session_date, speaker_id = EXCLUDED.speaker_id,
                        group_name = EXCLUDED.group_name, in_government = EXCLUDED.in_government,
                        text = EXCLUDED.text, embedding = EXCLUDED.embedding
                    WHERE (chunk.session_date, chunk.speaker_id, chunk.group_name,
                           chunk.in_government, chunk.text, chunk.embedding)
                          IS DISTINCT FROM
                          (EXCLUDED.session_date, EXCLUDED.speaker_id, EXCLUDED.group_name,
                           EXCLUDED.in_government, EXCLUDED.text, EXCLUDED.embedding)
                """)
                cur.executemany(
                    "INSERT INTO speech (id, assembly, term, session_date, text) "
                    "VALUES (%s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET session_date = EXCLUDED.session_date, "
                    "text = EXCLUDED.text WHERE (speech.session_date, speech.text) "
                    "IS DISTINCT FROM (EXCLUDED.session_date, EXCLUDED.text)",
                    [(r["id"], assembly, term, r["session_date"].to_native(), r["text"])
                     for r in speeches])
            conn.commit()
            total += len(rows)
            logger.info("  sittings %d-%d: %d chunks (%d total, %.0fs)",
                        batch[0], batch[-1], len(rows), total, time.time() - start)
        logger.info("building HNSW index...")
        t = time.time()
        conn.execute(HNSW)
        conn.commit()
        logger.info("HNSW index built in %.0fs", time.time() - t)
    driver.close()


def cmd_meta(pg: str, neo4j_uri: str, user: str, password: str,
             assembly: str, term: int, sessions_per_batch: int, only=None) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    numbers = _session_numbers(driver, assembly, term, only)
    changed = 0
    with psycopg.connect(pg) as conn:
        for i in range(0, len(numbers), sessions_per_batch):
            batch = numbers[i:i + sessions_per_batch]
            with driver.session() as s:
                rows = s.run(META, assembly=assembly, term=term, numbers=batch).data()
            with conn.cursor() as cur:
                cur.execute("CREATE TEMP TABLE IF NOT EXISTS meta_in "
                            "(id text, speaker_id text, group_name text, in_government boolean) "
                            "ON COMMIT DELETE ROWS")
                with cur.copy("COPY meta_in FROM STDIN") as copy:
                    for r in rows:
                        copy.write_row((r["id"], r["speaker_id"], r["group_name"],
                                        bool(r["in_government"])))
                cur.execute("""
                    UPDATE chunk SET speaker_id = m.speaker_id, group_name = m.group_name,
                                     in_government = m.in_government
                    FROM meta_in m
                    WHERE chunk.id = m.id
                      AND (chunk.speaker_id, chunk.group_name, chunk.in_government)
                          IS DISTINCT FROM (m.speaker_id, m.group_name, m.in_government)
                """)
                changed += cur.rowcount
            conn.commit()
    logger.info("speaker or group updated on %d archived chunks", changed)
    driver.close()


def cmd_strip(pg: str, neo4j_uri: str, user: str, password: str,
              assembly: str, term: int, sessions_per_batch: int, only=None) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(neo4j_uri, auth=(user, password))
    numbers = _session_numbers(driver, assembly, term, only)
    n_chunks = n_speeches = n_kept = 0
    with psycopg.connect(pg) as conn:
        for i in range(0, len(numbers), sessions_per_batch):
            batch = numbers[i:i + sessions_per_batch]
            with driver.session() as s:
                rows = s.run(NEO4J_TEXT, assembly=assembly, term=term, numbers=batch).data()
            chunk_text = {cid: text for r in rows for cid, text in r["chunks"] if cid}
            archived_chunks = dict(conn.execute(
                "SELECT id, text FROM chunk WHERE id = ANY(%s)", [list(chunk_text)]).fetchall())
            archived_speeches = dict(conn.execute(
                "SELECT id, text FROM speech WHERE id = ANY(%s)",
                [[r["speech_id"] for r in rows if r["speech_text"] is not None]]).fetchall())
            # A chunk goes only if the archive has the same text; a speech only
            # if the archive has it and its text_embedding is already computed.
            chunk_ids = [cid for cid, text in chunk_text.items()
                         if cid in archived_chunks and (text is None or archived_chunks[cid] == text)]
            speech_ids = [r["speech_id"] for r in rows
                          if r["speech_text"] is not None and r["has_speech_embedding"]
                          and archived_speeches.get(r["speech_id"]) == r["speech_text"]]
            n_kept += len(chunk_text) - len(chunk_ids)
            with driver.session() as s:
                if chunk_ids:
                    s.run(STRIP_CHUNKS, ids=chunk_ids).consume()
                if speech_ids:
                    s.run(STRIP_SPEECHES, ids=speech_ids).consume()
            n_chunks += len(chunk_ids)
            n_speeches += len(speech_ids)
    logger.info("stripped %d chunks and %d speeches; %d chunks kept (not archived or different)",
                n_chunks, n_speeches, n_kept)
    driver.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("command", choices=["schema", "load", "strip", "meta"])
    ap.add_argument("--pg", required=True, help="Postgres connection string")
    ap.add_argument("--neo4j-uri")
    ap.add_argument("--neo4j-user", default="neo4j")
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--assembly", default="senato")
    ap.add_argument("--term", type=int, default=19)
    ap.add_argument("--sessions-per-batch", type=int, default=10)
    ap.add_argument("--sessions", type=int, nargs="+", help="only these sitting numbers")
    args = ap.parse_args()
    if args.command == "schema":
        cmd_schema(args.pg)
        return 0
    if not args.neo4j_uri:
        ap.error(f"{args.command} needs --neo4j-uri")
    common = (args.pg, args.neo4j_uri, args.neo4j_user, args.neo4j_password,
              args.assembly, args.term, args.sessions_per_batch, args.sessions)
    if args.command == "load":
        cmd_schema(args.pg)
        cmd_load(*common)
    elif args.command == "meta":
        cmd_meta(*common)
    else:
        cmd_strip(*common)
    return 0


if __name__ == "__main__":
    sys.exit(main())
