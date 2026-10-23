#!/usr/bin/env python3
"""
build_and_update.py — Unified CLI for full build and incremental update of the Neo4j database.

Produces the English-only schema identical to the production database:
  Labels: Deputy, GovernmentMember, ParliamentaryGroup, Committee,
          Session, Debate, Phase, Speech, Chunk, ParliamentaryAct, Vote
  Relationships: SPOKEN_BY, HAS_CHUNK, HAS_DEBATE, HAS_PHASE, CONTAINS_SPEECH,
                 MEMBER_OF_GROUP, MEMBER_OF_COMMITTEE, PRIMARY_SIGNATORY,
                 CO_SIGNATORY, NEXT, IS_PRESIDENT, IS_VICE_PRESIDENT,
                 IS_SECRETARY, GOVERNMENT_REFERENCE, HAS_VOTE, DISCUSSES

Modes:
  build   — Rebuild the DB from scratch (nuke + full ingestion).
  update  — Incremental update: new XMLs, updated CSVs, new atti parlamentari.

Usage:
    python build/build_and_update.py build [--neo4j-uri bolt://localhost:7689]
    python build/build_and_update.py update [--neo4j-uri bolt://localhost:7689] \\
        [--skip-download] [--skip-atti] [--skip-embeddings]
"""

import argparse
import glob
import html as _html
import logging
import os
import re
import subprocess
import sys
import time
from datetime import timedelta

from neo4j import GraphDatabase

# ---------------------------------------------------------------------------
# Path setup — build/ is the scripts dir, project root is one level up
# ---------------------------------------------------------------------------
SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(SCRIPTS_DIR)
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
sys.path.insert(0, SCRIPTS_DIR)
sys.path.insert(0, BACKEND_DIR)

from build_config import load_config
from xml_parser import StenograficoParser
from db_builder import DatabaseBuilder
from download import download_new_xmls
from ingest_atti_parlamentari import AttiParlamentariIngester
from senate_parser import SenateStenograficoParser
from download_senate import download_senate_xmls
from download_senators_csv import main as download_senators_csv_main
from download_deputies_csv import main as download_deputies_csv_main
from senate_html_parser import SenateHtmlParser
from download_camera_seats import main as download_camera_seats_main
from download_governments_csv import ROMAN, main as download_governments_csv_main
from download_person_crosswalk import main as download_person_crosswalk_main

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_NEO4J_URI = "bolt://localhost:7689"
DEFAULT_NEO4J_USER = "neo4j"
DEFAULT_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD", "")

CURRENT_LEGISLATURE = 19

DATA_DIR = os.path.join(BASE_DIR, "data")
XML_DIR = os.path.join(DATA_DIR, "xml")
SENATE_XML_DIR = os.path.join(DATA_DIR, "senate_xml")
CONFIG_PATH = os.path.join(SCRIPTS_DIR, "config.yaml")


# ---------------------------------------------------------------------------
# Subprocess helper
# ---------------------------------------------------------------------------

def run_subprocess(
    script_name: str,
    neo4j_uri: str | None = None,
    neo4j_user: str | None = None,
    neo4j_password: str | None = None,
) -> int:
    """Run a build sub-script as a child process, forwarding Neo4j credentials."""
    script_path = os.path.join(SCRIPTS_DIR, script_name)
    env = os.environ.copy()
    env["PYTHONPATH"] = (
        SCRIPTS_DIR + os.pathsep + BACKEND_DIR + os.pathsep + env.get("PYTHONPATH", "")
    )
    if neo4j_uri:
        env["NEO4J_URI"] = neo4j_uri
    if neo4j_user:
        env["NEO4J_USER"] = neo4j_user
    if neo4j_password:
        env["NEO4J_PASSWORD"] = neo4j_password
    start = time.time()
    result = subprocess.run([sys.executable, script_path], check=True, env=env)
    logger.info("%s completed in %.1fs", script_name, time.time() - start)
    return result.returncode


# ---------------------------------------------------------------------------
# Atti parlamentari ingestion helper
# ---------------------------------------------------------------------------

def _ingest_atti(
    driver, uri: str, user: str, password: str, legislature: int = 19,
    since: str | None = None,
) -> None:
    """Ingest parliamentary acts using AttiParlamentariIngester.

    since ("YYYYMMDD"): limit the per-deputy SPARQL to acts presented from
    that date on (incremental update). None = full sweep.
    """
    ingester = AttiParlamentariIngester(uri, user, password, legislature=legislature)
    try:
        ingester.create_constraints()
        ingester.create_indexes()

        with driver.session() as neo_session:
            result = neo_session.run(
                "MATCH (d:Deputy) "
                "WHERE ('camera_' + toString($legislature)) IN coalesce(d.mandates, []) "
                "RETURN d.id AS uri, d.first_name AS nome, d.last_name AS cognome",
                legislature=legislature,
            )
            deputati = [dict(r) for r in result]

        logger.info("Found %d deputies for atti ingestion.", len(deputati))
        total_primo = 0
        total_altro = 0
        atti_unici: set[str] = set()

        for i, dep in enumerate(deputati):
            dep_uri = dep["uri"]
            dep_nome = f"{dep.get('nome', '')} {dep.get('cognome', '')}"
            logger.debug("[%d/%d] %s...", i + 1, len(deputati), dep_nome)

            atti = ingester.get_atti_deputato(dep_uri, since=since)
            n_primo = len(atti["primo_firmatario"])
            n_altro = len(atti["altro_firmatario"])

            if n_primo > 0 or n_altro > 0:
                logger.info(
                    "[%d/%d] %s -> %d primo, %d altro",
                    i + 1, len(deputati), dep_nome, n_primo, n_altro,
                )

            for atto in atti["primo_firmatario"] + atti["altro_firmatario"]:
                atti_unici.add(atto["uri"])
            _save_atti_batch(driver, atti["primo_firmatario"], dep_uri, "PRIMARY_SIGNATORY")
            _save_atti_batch(driver, atti["altro_firmatario"], dep_uri, "CO_SIGNATORY")
            total_primo += n_primo
            total_altro += n_altro

        logger.info(
            "Atti unici: %d, Primo: %d, Altro: %d",
            len(atti_unici), total_primo, total_altro,
        )
    finally:
        ingester.close()


def _parse_yyyymmdd(raw: str):
    """YYYYMMDD string -> ISO date string for Cypher date(), or None (C1/C3)."""
    s = (raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _save_atti_batch(driver, atti: list[dict], deputato_uri: str, rel_type: str) -> None:
    """Upsert a deputy's ParliamentaryAct nodes and signatory relationships in
    one UNWIND query (atto + EuroVoc SKOS + relazione firmatario).

    Batched per deputato: on a remote DB behind an SSH tunnel (~200ms RTT) the
    previous per-atto version cost ~2000 round-trips per deputy (~7 min each).

    Schema v2: presentation_date come date nativa (C1, mai stringa vuota — C3,
    preservato dal FOREACH condizionale), concetti EuroVoc come nodi SKOS con
    HAS_SUBJECT invece della stringa appiattita (C10).
    """
    if not atti:
        return
    rows = [
        {
            "uri": atto.get("uri", ""),
            "type": atto.get("tipo", ""),
            # La fonte Camera contiene entità HTML (&#8212; ecc.) che finivano
            # grezze in UI (21.574 description bonificate one-shot 2026-07-24)
            "title": _html.unescape(atto.get("titolo", "")),
            "description": _html.unescape(atto.get("descrizione", "")),
            "number": atto.get("numero", ""),
            "recipient": atto.get("destinatario", ""),
            "presentation_iso": _parse_yyyymmdd(atto.get("dataPresentazione", "")),
            "concepts": atto.get("eurovoc_concepts") or [],
        }
        for atto in atti
    ]
    with driver.session() as neo_session:
        neo_session.run(
            f"""
            MATCH (d:Deputy {{id: $dep_uri}})
            UNWIND $rows AS row
            MERGE (a:ParliamentaryAct {{uri: row.uri}})
            SET a.type = row.type, a.title = row.title,
                a.description = row.description,
                a.number = row.number, a.recipient = row.recipient
            FOREACH (_ IN CASE WHEN row.presentation_iso IS NULL THEN [] ELSE [1] END |
                SET a.presentation_date = date(row.presentation_iso))
            MERGE (d)-[:{rel_type}]->(a)
            FOREACH (ev IN row.concepts |
                MERGE (c:EurovocConcept {{uri: ev.uri}})
                SET c.label_it = ev.label
                MERGE (a)-[:HAS_SUBJECT]->(c))
            """,
            dep_uri=deputato_uri,
            rows=rows,
        )


def _prepare_people(builder: DatabaseBuilder, legislature: int, skip_download: bool) -> None:
    """Scope legacy data, then load government offices before any person
    loader: they give legacy government nodes their camera_id, which the
    deputy and senator loaders resolve against."""
    builder.create_indexes()
    builder.backfill_legacy_scope()
    if not skip_download:
        # Both sources are public SPARQL endpoints that fail for minutes at a
        # time; the files from the previous run are good enough to go on.
        for name, step, path in (
            ("governments", lambda: download_governments_csv_main(legislature),
             os.path.join(DATA_DIR, f"governi_{ROMAN.get(legislature, legislature)}.csv")),
            ("person crosswalk", download_person_crosswalk_main,
             os.path.join(DATA_DIR, "persone_camera_senato.csv")),
        ):
            try:
                step()
            except Exception as exc:
                if not os.path.exists(path):
                    raise
                logger.warning("%s download failed (%s); keeping %s", name, exc, path)
    builder.sync_governments(DATA_DIR)
    if builder.merge_duplicate_people():
        # Offices were written once per duplicate; rewrite them on the survivors.
        builder.sync_governments(DATA_DIR)


def _finish_people(builder: DatabaseBuilder, legislature: int, chamber: str) -> None:
    builder.create_scope_vector_index(chamber, legislature)
    builder.merge_duplicate_people()
    builder.drop_duplicate_memberships()
    builder.link_orphan_speeches()
    builder.relink_mismatched_speakers()
    builder.normalize_person_labels()
    builder.mark_party_affiliations()
    # In a closed legislature every mandate ends with it, and the last
    # memberships are flagged final instead (mark_final_memberships).
    if chamber == "camera" and legislature == CURRENT_LEGISLATURE:
        builder.close_memberships_at_mandate_end(DATA_DIR, legislature)
        try:
            download_camera_seats_main()
        except Exception as exc:
            logger.warning("Seat download failed (%s); keeping the previous seating", exc)
        builder.load_camera_seats(DATA_DIR, legislature)
    builder.mark_final_memberships()
    builder.annotate_speech_government_roles(legislature, chamber)


# ---------------------------------------------------------------------------
# BUILD mode
# ---------------------------------------------------------------------------

def do_build(
    uri: str,
    user: str,
    password: str,
    skip_download: bool = False,
    skip_atti: bool = False,
    skip_embeddings: bool = False,
    legislature: int = 19,
) -> None:
    """Rebuild the database from scratch (nuke + full ingestion)."""
    config = load_config(CONFIG_PATH)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    builder = DatabaseBuilder(driver, config)
    parser = StenograficoParser(config)

    try:
        # 1. Nuke
        logger.info("Step 1: Clearing database")
        builder.nuke_database()

        # 2. Constraints + indexes
        logger.info("Step 2: Creating constraints and indexes")
        builder.create_constraints()
        builder.create_indexes()
        _prepare_people(builder, legislature, skip_download)

        # 3. Download XMLs
        if skip_download:
            logger.info("Step 3: Skipping XML download (--skip-download)")
        else:
            logger.info("Step 3: Downloading new XMLs")
            download_new_xmls(XML_DIR, legislature=legislature)

        # 4. Load CSVs (deputies, groups, committees, government members)
        logger.info("Step 4: Loading CSV data")
        builder.load_deputies(DATA_DIR, legislature=legislature)
        builder.load_groups(DATA_DIR, legislature=legislature)
        builder.load_committees(DATA_DIR, legislature=legislature)
        if legislature == CURRENT_LEGISLATURE:
            # GOVERNMENT_GROUPS lists the sitting government only.
            builder.load_government_members_from_path(DATA_DIR, legislature=legislature)

        # 5. Ingest stenografici
        logger.info("Step 5: Ingesting stenografici")
        logger.info("  NER enrichment will run on chunks (requires it_core_news_lg)")
        xml_files = sorted(glob.glob(os.path.join(XML_DIR, f"stenografico_leg{legislature}_*.xml")))
        logger.info("  Found %d XML files", len(xml_files))
        for i, xml_path in enumerate(xml_files, 1):
            logger.info("  [%d/%d] %s", i, len(xml_files), os.path.basename(xml_path))
            parsed = parser.parse_xml_file(xml_path)
            builder.ingest_session(parsed)

        # 5b. Substring invariant report (C8)
        if builder.invariant_violations > 0:
            logger.error(
                "C8: %d chunk scartati per violazione dell'invariante substring "
                "— indagare prima del cutover", builder.invariant_violations
            )
        else:
            logger.info("C8: invariante substring rispettata da tutti i chunk")

        # 6. Load roles
        logger.info("Step 6: Loading roles")
        builder.load_roles()
        _finish_people(builder, legislature, "camera")

        # 7. Atti parlamentari
        if skip_atti:
            logger.info("Step 7: Skipping atti parlamentari (--skip-atti)")
        else:
            logger.info("Step 7: Ingesting atti parlamentari")
            _ingest_atti(driver, uri, user, password, legislature=legislature)

        # 7b. Continuation titles (schema v2 §2.2 — needs DISCUSSES edges)
        logger.info("Step 7b: Resolving continuation debate titles")
        builder.resolve_continuation_titles()

        # 8. Vector index
        logger.info("Step 8: Creating vector indexes")
        builder.create_vector_index()

        # 8b. Full-text index for BM25 sparse retrieval
        logger.info("Step 8b: Creating full-text index")
        builder.create_fulltext_index()
        builder.create_search_indexes()

        # 9. Embeddings
        if skip_embeddings:
            logger.info("Step 9: Skipping embeddings (--skip-embeddings)")
        else:
            logger.info("Step 9: Pre-calculating embeddings")
            run_subprocess("precalculate_embeddings.py", uri, user, password)

        # 10. SPOKEN_BY hard check (schema v2: ogni Speech DEVE avere un oratore)
        logger.info("Step 10: Verifying SPOKEN_BY coverage")
        with driver.session() as neo_session:
            orphans = neo_session.run(
                "MATCH (sp:Speech) WHERE NOT (sp)-[:SPOKEN_BY]->() RETURN count(sp) AS c"
            ).single()["c"]
        if orphans > 0:
            logger.warning(
                "%d Speech senza SPOKEN_BY — tentativo repair_spoken_by.py", orphans
            )
            run_subprocess("repair_spoken_by.py", uri, user, password)
            with driver.session() as neo_session:
                orphans = neo_session.run(
                    "MATCH (sp:Speech) WHERE NOT (sp)-[:SPOKEN_BY]->() RETURN count(sp) AS c"
                ).single()["c"]
        if orphans > 0:
            logger.error(
                "INVARIANTE VIOLATA: %d Speech ancora senza SPOKEN_BY dopo il repair. "
                "La build è INCOMPLETA — eseguire validate_db.py per il dettaglio.",
                orphans,
            )

        # 11. SchemaMeta (v2 C9)
        logger.info("Step 11: Writing SchemaMeta")
        commit = None
        try:
            import subprocess as _sp
            commit = _sp.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True,
                cwd=os.path.dirname(os.path.abspath(__file__)),
            ).stdout.strip() or None
        except Exception:
            pass
        builder.write_schema_meta(build_tool_commit=commit)

        logger.info("Build complete!")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# UPDATE mode
# ---------------------------------------------------------------------------

def do_update(
    uri: str,
    user: str,
    password: str,
    skip_download: bool = False,
    skip_atti: bool = False,
    skip_embeddings: bool = False,
    legislature: int = 19,
    full_atti: bool = False,
) -> None:
    """Incremental update: new XMLs, refreshed CSVs, new atti parlamentari."""
    config = load_config(CONFIG_PATH)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    builder = DatabaseBuilder(driver, config)
    parser = StenograficoParser(config)

    try:
        # 1. Refresh CSV data
        if skip_download:
            logger.info("Step 1: Skipping deputy CSV download (--skip-download)")
        else:
            # Without this the CSVs on disk go stale and group switches never reach the graph.
            logger.info("Step 1: Refreshing deputy CSV data from dati.camera.it")
            download_deputies_csv_main(legislature)
        builder.create_constraints()
        _prepare_people(builder, legislature, skip_download)
        builder.load_deputies(DATA_DIR, legislature=legislature)
        builder.load_groups(DATA_DIR, legislature=legislature)
        builder.load_committees(DATA_DIR, legislature=legislature)
        if legislature == CURRENT_LEGISLATURE:
            # GOVERNMENT_GROUPS lists the sitting government only.
            builder.load_government_members_from_path(DATA_DIR, legislature=legislature)

        # 2. Download new XMLs
        if skip_download:
            logger.info("Step 2: Skipping XML download (--skip-download)")
        else:
            logger.info("Step 2: Downloading new XMLs")
            download_new_xmls(XML_DIR, legislature=legislature)

        # 3. Ingest new stenografici only
        logger.info("Step 3: Ingesting new stenografici")
        existing = builder.get_existing_session_numbers(chamber="camera", legislature=legislature)
        first_ingest = not existing
        xml_files = sorted(glob.glob(os.path.join(XML_DIR, f"stenografico_leg{legislature}_*.xml")))
        new_files = []
        for f in xml_files:
            match = re.search(rf'stenografico_leg{legislature}_(\d+)\.xml$', f)
            if match:
                num = int(match.group(1))
                if num not in existing:
                    new_files.append(f)
        if new_files:
            logger.info("  Found %d new XML files to ingest", len(new_files))
            for i, xml_path in enumerate(new_files, 1):
                logger.info("  [%d/%d] %s", i, len(new_files), os.path.basename(xml_path))
                parsed = parser.parse_xml_file(xml_path)
                builder.ingest_session(parsed)
        else:
            logger.info("  No new stenografici found.")

        # 4. Atti parlamentari — incremental by default: only acts presented
        # since the previous update run (7-day margin for late-arriving data).
        # --full-atti forces the full per-deputy sweep, e.g. to pick up
        # corrections to older acts.
        if skip_atti:
            logger.info("Step 4: Skipping atti parlamentari (--skip-atti)")
        else:
            since = None
            if not full_atti and not first_ingest:
                with driver.session() as neo_session:
                    rec = neo_session.run(
                        "MATCH (m:SchemaMeta {id: 'singleton'}) RETURN m.updated_at AS u"
                    ).single()
                if rec and rec["u"]:
                    prev = rec["u"].to_native()
                    since = (prev - timedelta(days=7)).strftime("%Y%m%d")
            if since:
                logger.info("Step 4: Updating atti parlamentari (incremental since %s)", since)
            else:
                logger.info("Step 4: Updating atti parlamentari (full sweep)")
            _ingest_atti(driver, uri, user, password, legislature=legislature, since=since)

        # 5. Roles
        logger.info("Step 5: Updating roles")
        builder.load_roles()
        _finish_people(builder, legislature, "camera")

        # 5b. Full-text index for BM25 sparse retrieval (idempotent: IF NOT EXISTS)
        logger.info("Step 5b: Ensuring full-text index exists")
        builder.create_fulltext_index()
        builder.create_search_indexes()

        # 6. Embeddings
        if skip_embeddings:
            logger.info("Step 6: Skipping embeddings (--skip-embeddings)")
        else:
            logger.info("Step 6: Pre-calculating embeddings (incremental)")
            run_subprocess("precalculate_embeddings.py", uri, user, password)

        # 7. Stamp the update run (shown as "data updated at" in the UI/README,
        #    which would otherwise display the stale max(Session.date))
        logger.info("Step 7: Stamping SchemaMeta.updated_at")
        with driver.session() as neo_session:
            neo_session.execute_write(lambda tx: tx.run(
                "MERGE (m:SchemaMeta {id: 'singleton'}) SET m.updated_at = datetime()"
            ))

        logger.info("Update complete!")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# BUILD-SENATE mode
# ---------------------------------------------------------------------------


def do_build_senate(
    uri: str,
    user: str,
    password: str,
    skip_download: bool = False,
    skip_embeddings: bool = False,
    legislature: int = 19,
) -> None:
    """Build Senate portion of the database (additive — no nuke)."""
    config = load_config(CONFIG_PATH)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    builder = DatabaseBuilder(driver, config)
    parser = SenateStenograficoParser(config, legislature=legislature)
    try:
        # 1. Download senator biographical CSVs
        if skip_download:
            logger.info("Skipping senator CSV download")
        else:
            logger.info("Downloading senator biographical data from dati.senato.it")
            download_senators_csv_main(legislature)

        # 2. Load senator CSVs (Deputy nodes with chamber='senato')
        logger.info("Loading senator CSV data")
        builder.create_constraints()
        _prepare_people(builder, legislature, skip_download)
        builder.load_senators(DATA_DIR, legislature=legislature)
        builder.load_senator_groups(DATA_DIR, legislature=legislature)
        builder.load_senator_committees(DATA_DIR, legislature=legislature)

        # 3. Download Senate AKN files
        if skip_download:
            logger.info("Skipping Senate XML download")
        else:
            logger.info("Downloading Senate AKN files")
            os.makedirs(SENATE_XML_DIR, exist_ok=True)
            count = download_senate_xmls(SENATE_XML_DIR, legislature=legislature)
            logger.info("Downloaded %d new Senate files", count)

        # 4. Ingest Senate stenografici
        logger.info("Ingesting Senate stenografici")
        akn_files = sorted(glob.glob(os.path.join(SENATE_XML_DIR, f"resaula_leg{legislature}_*.akn")))
        logger.info("Found %d AKN files", len(akn_files))
        for i, akn_path in enumerate(akn_files, 1):
            logger.info("[%d/%d] %s", i, len(akn_files), os.path.basename(akn_path))
            parsed = parser.parse_xml_file(akn_path)
            builder.ingest_session(parsed)

        # 4b. Link any orphan Senate speeches to senators/government members
        logger.info("Relinking Senate speeches to speakers")
        builder.relink_senate_speeches(legislature)
        _finish_people(builder, legislature, "senato")

        # 5. Embeddings for new Senate chunks
        if skip_embeddings:
            logger.info("Skipping Senate embeddings")
        else:
            logger.info("Pre-calculating Senate embeddings")
            run_subprocess("precalculate_embeddings.py", uri, user, password)

        logger.info("Senate build complete!")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# UPDATE-SENATE mode
# ---------------------------------------------------------------------------


def do_update_senate(
    uri: str,
    user: str,
    password: str,
    skip_download: bool = False,
    skip_embeddings: bool = False,
    legislature: int = 19,
) -> None:
    """Incremental Senate update: new AKNs, refreshed senator CSVs, relink."""
    config = load_config(CONFIG_PATH)
    driver = GraphDatabase.driver(uri, auth=(user, password))
    builder = DatabaseBuilder(driver, config)
    parser = SenateStenograficoParser(config, legislature=legislature)
    try:
        # 1. Refresh senator biographical CSVs and load them
        if skip_download:
            logger.info("Step 1: Skipping senator CSV download (--skip-download)")
        else:
            logger.info("Step 1: Refreshing senator biographical data")
            download_senators_csv_main(legislature)
        builder.create_constraints()
        _prepare_people(builder, legislature, skip_download)
        builder.load_senators(DATA_DIR, legislature=legislature)
        builder.load_senator_groups(DATA_DIR, legislature=legislature)
        builder.load_senator_committees(DATA_DIR, legislature=legislature)

        # 2. Download new Senate AKN files
        if skip_download:
            logger.info("Step 2: Skipping Senate AKN download (--skip-download)")
        else:
            logger.info("Step 2: Downloading Senate AKN files")
            os.makedirs(SENATE_XML_DIR, exist_ok=True)
            count = download_senate_xmls(SENATE_XML_DIR, legislature=legislature)
            logger.info("Downloaded %d new Senate files", count)

        # 3. Ingest only sessions not yet in Neo4j
        logger.info("Step 3: Ingesting new Senate stenografici")
        existing = builder.get_existing_session_numbers(chamber="senato", legislature=legislature)
        akn_files = sorted(glob.glob(os.path.join(SENATE_XML_DIR, f"resaula_leg{legislature}_*.akn")))
        new_files = []
        for f in akn_files:
            match = re.search(rf'resaula_leg{legislature}_(\d+)\.akn$', f)
            if match and int(match.group(1)) not in existing:
                new_files.append(f)
        # Sittings with no AKN file are published as web pages only.
        akn_numbers = {
            int(m.group(1)) for f in akn_files
            if (m := re.search(rf'resaula_leg{legislature}_(\d+)\.akn$', f))
        }
        for f in sorted(glob.glob(os.path.join(SENATE_XML_DIR, f"resaula_leg{legislature}_*.html"))):
            match = re.search(rf'resaula_leg{legislature}_(\d+)\.html$', f)
            if match and int(match.group(1)) not in existing | akn_numbers:
                new_files.append(f)
        if new_files:
            logger.info("  Found %d new Senate records to ingest", len(new_files))
            html_parser = SenateHtmlParser(config, legislature=legislature)
            for i, record_path in enumerate(new_files, 1):
                logger.info("  [%d/%d] %s", i, len(new_files), os.path.basename(record_path))
                if record_path.endswith(".html"):
                    parsed = html_parser.parse_html_file(record_path)
                else:
                    parsed = parser.parse_xml_file(record_path)
                builder.ingest_session(parsed)
        else:
            logger.info("  No new Senate stenografici found.")

        # 4. Link orphan Senate speeches (covers legacy ingests too)
        logger.info("Step 4: Relinking Senate speeches to speakers")
        builder.relink_senate_speeches(legislature)
        _finish_people(builder, legislature, "senato")

        # 5. Embeddings for new chunks
        if skip_embeddings:
            logger.info("Step 5: Skipping embeddings (--skip-embeddings)")
        else:
            logger.info("Step 5: Pre-calculating embeddings (incremental)")
            run_subprocess("precalculate_embeddings.py", uri, user, password)

        logger.info("Senate update complete!")
    finally:
        driver.close()


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    arg_parser = argparse.ArgumentParser(
        description=(
            "Full build or incremental update of the Neo4j ParliamentRAG database "
            "(English schema)"
        )
    )
    arg_parser.add_argument(
        "mode",
        choices=["build", "update", "build-senate", "update-senate"],
        help=(
            "build = rebuild from scratch; update = incremental Camera update; "
            "build-senate = additive Senate ingestion; "
            "update-senate = incremental Senate update"
        ),
    )
    arg_parser.add_argument(
        "--neo4j-uri",
        default=DEFAULT_NEO4J_URI,
        help=f"Neo4j URI (default: {DEFAULT_NEO4J_URI})",
    )
    arg_parser.add_argument("--neo4j-user", default=DEFAULT_NEO4J_USER)
    arg_parser.add_argument("--neo4j-password", default=DEFAULT_NEO4J_PASSWORD)
    arg_parser.add_argument(
        "--skip-download", action="store_true", help="Skip XML download step"
    )
    arg_parser.add_argument(
        "--skip-atti", action="store_true", help="Skip atti parlamentari ingestion"
    )
    arg_parser.add_argument(
        "--skip-embeddings", action="store_true", help="Skip embedding pre-calculation"
    )
    arg_parser.add_argument(
        "--legislature", type=int, default=19,
        help="Legislature number to build/update (default: 19)",
    )
    arg_parser.add_argument(
        "--full-atti", action="store_true",
        help="Update mode: full atti sweep instead of incremental since last run",
    )

    args = arg_parser.parse_args()
    start_time = time.time()

    if args.mode == "build":
        do_build(
            args.neo4j_uri,
            args.neo4j_user,
            args.neo4j_password,
            args.skip_download,
            args.skip_atti,
            args.skip_embeddings,
            legislature=args.legislature,
        )
    elif args.mode == "build-senate":
        do_build_senate(
            args.neo4j_uri,
            args.neo4j_user,
            args.neo4j_password,
            args.skip_download,
            args.skip_embeddings,
            legislature=args.legislature,
        )
    elif args.mode == "update-senate":
        do_update_senate(
            args.neo4j_uri,
            args.neo4j_user,
            args.neo4j_password,
            args.skip_download,
            args.skip_embeddings,
            legislature=args.legislature,
        )
    else:
        do_update(
            args.neo4j_uri,
            args.neo4j_user,
            args.neo4j_password,
            args.skip_download,
            args.skip_atti,
            args.skip_embeddings,
            legislature=args.legislature,
            full_atti=args.full_atti,
        )

    total = time.time() - start_time
    logger.info("Total time: %.1fs (%.1f minutes)", total, total / 60)


if __name__ == "__main__":
    main()
