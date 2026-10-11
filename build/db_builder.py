"""
db_builder.py — Neo4j database builder for the ParliamentRAG pipeline.

Takes parsed data from xml_parser.py and chunks from chunker.py and writes
everything to Neo4j using the clean English-only schema.

Schema conventions:
  - Labels: PascalCase (Session, Debate, Phase, Speech, Chunk, Deputy, …)
  - Properties: camelCase (speakingRole, phaseType, inFavor, …)
  - Relationships: SCREAMING_SNAKE_CASE (HAS_DEBATE, CONTAINS_SPEECH, …)

All write operations use UNWIND batch writes with batch_size from BuildConfig.
All transactions use execute_read/execute_write managed transactions (no auto-commit).
"""

from __future__ import annotations

import os
import re
import unicodedata
from typing import Optional

import pandas as pd
from neo4j.time import Date as Neo4jDate

from build_config import BuildConfig
from chunker import chunk_speech
from ner import enrich_chunks_with_ner, load_ner_model

# ---------------------------------------------------------------------------
# Legislature mapping: legislature number → roman suffix used in CSV/XML names
# Intentionally not imported from download_deputies_csv.py to keep build/
# scripts standalone (no cross-script coupling — see Phase 01-04 decision).
# ---------------------------------------------------------------------------

ROMAN_MAP = {17: "xvii", 18: "xviii", 19: "xix", 20: "xx"}

# ---------------------------------------------------------------------------
# App-config import (optional — roles won't load if missing)
# ---------------------------------------------------------------------------
try:
    from app_config import (
        GOVERNMENT_ROLES,
        PARLIAMENT_ROLES,
        CAPIGRUPPO,
        COMMISSION_ROLES,
    )
    _ROLES_AVAILABLE = True
except (ImportError, SystemExit):
    _ROLES_AVAILABLE = False


# ---------------------------------------------------------------------------
# Module-level utility helpers (ported from build_and_update.py)
# ---------------------------------------------------------------------------

def clean_generic_label(label) -> Optional[str]:
    """Remove trailing date ranges from committee/group labels."""
    if pd.isna(label):
        return None
    return re.sub(r'\s*\([^)]*\d{2}\.\d{2}\.\d{4}.*$', '', str(label)).strip()


def extract_group_info(raw_label) -> tuple[Optional[str], Optional[str]]:
    """Return (name, acronym) from a raw group label string."""
    clean_label = clean_generic_label(raw_label)
    if not clean_label:
        return None, None
    if "NM(N-C-U-I)M-CP" in clean_label:
        return clean_label.replace("(NM(N-C-U-I)M-CP)", "").strip(), "NM(N-C-U-I)M-CP"
    match = re.search(r'^(.*?)\s+\(([^)]+)\)$', clean_label)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return clean_label, None


from csv_loader import parse_date_to_neo4j  # single definition (was duplicated here)


def normalize_body_name(name: str) -> str:
    """Comparison key for committee labels across chambers: the Camera writes
    "COMUNITA'" in capitals, the Senato "comunità"."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^A-Za-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().upper()


def match_legacy_government_node(first, last, card, people: list[dict]) -> Optional[str]:
    """Persona URI of a legacy gov_* node among the official members
    (dicts with persona, nome, cognome), or None when not unique.

    Legacy names were split from "SURNAME NAME" strings and are often wrong
    ("ALBERTI CASELLATI MARIA" / "ELISABETTA"), and some use a common name
    (Nello vs Sebastiano Musumeci). Tried in order: deputy_card (the persona
    number), token-set inclusion with at least two shared tokens, a surname
    shared with exactly one member.
    """
    def tokens(*parts) -> set[str]:
        return set(normalize_body_name(" ".join(p or "" for p in parts)).split())

    if card:
        for p in people:
            if p["persona"].rsplit("/p", 1)[-1] == str(card):
                return p["persona"]
    mine = tokens(first, last)
    hits = {p["persona"] for p in people
            if len(mine & tokens(p["nome"], p["cognome"])) >= 2
            and (mine <= tokens(p["nome"], p["cognome"]) or tokens(p["nome"], p["cognome"]) <= mine)}
    if len(hits) != 1:
        hits = {p["persona"] for p in people if tokens(p["cognome"]) and tokens(p["cognome"]) <= mine}
    return hits.pop() if len(hits) == 1 else None


def placeholder_act_uri(chamber: str, legislature: int, act_type: str, act_code: str) -> str:
    """Synthetic merge key for an act known only from a transcript reference.

    Act numbers restart every legislature and Camera/Senato number bills
    independently, so the key carries both. Camera XIX keeps the original
    unscoped form: existing DISCUSSES edges and repair_placeholder_acts.py
    match on it.
    """
    if chamber == "camera" and legislature == 19:
        return f"placeholder:{act_type}:{act_code}"
    return f"placeholder:{chamber}:leg{legislature}:{act_type}:{act_code}"


def normalize_photo_url(raw_photo, legislature: int = 19) -> Optional[str]:
    """Normalize Camera photo URLs to the https fotoDefinitivo pattern.

    The CSV carries 'http://documenti.camera.it/apps/nuovosito/deputato/
    getFoto.asp?id=N&legislatura=19' — plain http, blocked as mixed content
    when the frontend is served over https. The stable https equivalent is
    the fotoDefinitivo/big JPEG (verified 200 on 2026-07-23).
    """
    if raw_photo is None or (isinstance(raw_photo, float) and pd.isna(raw_photo)):
        return None
    url = str(raw_photo)
    if 'getFoto.asp?id=' in url:
        num = url.split('id=')[1].split('&')[0]
        return (f"https://documenti.camera.it/_dati/leg{legislature}"
                f"/schededeputatinuovosito/fotoDefinitivo/big/d{num}.jpg")
    return url


# Group RENAME chains: historical label -> canonical current label.
# dati.camera.it models an adesione as one continuous membership: when a group
# RENAMES itself (e.g. Azione-IV joint group -> Azione-PER-RE after the IV split),
# members who stayed keep the old label with no end date, while members who left
# get a fresh adesione. Mapping old labels to the canonical name keeps ONE group
# node per real group (verified 2026-07-23: Richetti vs Faraone rows).
GROUP_RENAMES = {
    "AZIONE - ITALIA VIVA - RENEW EUROPE":
        "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE",
    "ITALIA VIVA-IL CENTRO-RENEW EUROPE":
        "ITALIA VIVA-CASA RIFORMISTA (IV-CR)",
    "NOI MODERATI":
        "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE",
    "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC, ITALIA AL CENTRO)-MAIE":
        "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE",
}

# Government members who are not deputies and have a compound given name: the
# deputy CSV cannot disambiguate them, and "last word = given name" gives e.g.
# "CALDERONE MARINA" + "ELVIRA".
_GOV_NAME_SPLITS = {
    "ALBERTI CASELLATI MARIA ELISABETTA": ("ALBERTI CASELLATI", "MARIA ELISABETTA"),
    "BERNINI ANNA MARIA": ("BERNINI", "ANNA MARIA"),
    "CALDERONE MARINA ELVIRA": ("CALDERONE", "MARINA ELVIRA"),
    "LA PIETRA PATRIZIO GIACOMO": ("LA PIETRA", "PATRIZIO GIACOMO"),
    "SISTO FRANCESCO PAOLO": ("SISTO", "FRANCESCO PAOLO"),
}


def _split_gov_full_name(full_name: str, dep_df=None) -> tuple[str, str]:
    """Split di una chiave GOVERNMENT_GROUPS "COGNOME NOME" in (cognome, nome).

    L'euristica "ultima parola = nome" sbaglia i nomi propri composti:
    "BELLUCCI MARIA TERESA" diventava cognome "BELLUCCI MARIA" + nome
    "TERESA", il lookup sul CSV falliva e la persona finiva nel grafo due
    volte (Deputy + GovernmentMember), coi voti contati doppi. Se c'è il CSV
    dei deputati si prova ogni punto di taglio contro cognome/nome reali;
    l'euristica resta solo come fallback (non-deputati: senatori, tecnici).
    """
    if full_name.upper() in _GOV_NAME_SPLITS:
        return _GOV_NAME_SPLITS[full_name.upper()]
    parts = full_name.split()
    if dep_df is not None and len(parts) > 2:
        csv_pairs = {
            (str(r["cognome"]).strip().upper(), str(r["nome"]).strip().upper())
            for _, r in dep_df.iterrows()
        }
        for cut in range(1, len(parts)):
            last = " ".join(parts[:cut])
            first = " ".join(parts[cut:])
            if (last.upper(), first.upper()) in csv_pairs:
                return last, first
    return " ".join(parts[:-1]), parts[-1]


# Government group membership map: "LAST FIRST" -> group name
GOVERNMENT_GROUPS = {
    "MELONI GIORGIA": "FRATELLI D'ITALIA",
    "FOTI TOMMASO": "FRATELLI D'ITALIA",
    "TAJANI ANTONIO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "SALVINI MATTEO": "LEGA - SALVINI PREMIER",
    "CIRIANI LUCA": "FRATELLI D'ITALIA",
    "ZANGRILLO PAOLO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "CALDEROLI ROBERTO": "LEGA - SALVINI PREMIER",
    "MUSUMECI NELLO": "FRATELLI D'ITALIA",
    "ABODI ANDREA": "MISTO",
    "ROCCELLA EUGENIA": "FRATELLI D'ITALIA",
    "LOCATELLI ALESSANDRA": "LEGA - SALVINI PREMIER",
    "ALBERTI CASELLATI MARIA ELISABETTA": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "PIANTEDOSI MATTEO": "MISTO",
    "NORDIO CARLO": "FRATELLI D'ITALIA",
    "CROSETTO GUIDO": "FRATELLI D'ITALIA",
    "GIORGETTI GIANCARLO": "LEGA - SALVINI PREMIER",
    "URSO ADOLFO": "FRATELLI D'ITALIA",
    "LOLLOBRIGIDA FRANCESCO": "FRATELLI D'ITALIA",
    "PICHETTO FRATIN GILBERTO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "VALDITARA GIUSEPPE": "LEGA - SALVINI PREMIER",
    "BERNINI ANNA MARIA": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "GIULI ALESSANDRO": "FRATELLI D'ITALIA",
    "SCHILLACI ORAZIO": "MISTO",
    "SANTANCHE' DANIELA": "FRATELLI D'ITALIA",
    "CALDERONE MARINA ELVIRA": "MISTO",
    "MANTOVANO ALFREDO": "MISTO",
    "FAZZOLARI GIOVANBATTISTA": "FRATELLI D'ITALIA",
    "BUTTI ALESSIO": "FRATELLI D'ITALIA",
    "BARACHINI ALBERTO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "MORELLI ALESSANDRO": "LEGA - SALVINI PREMIER",
    "SBARRA LUIGI": "MISTO",
    "CASTIELLO GIUSEPPINA": "LEGA - SALVINI PREMIER",
    "SIRACUSANO MATILDE": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "CIRIELLI EDMONDO": "FRATELLI D'ITALIA",
    "SILLI GIORGIO": "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC, ITALIA AL CENTRO)-MAIE",
    "TRIPODI MARIA": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "FERRO WANDA": "FRATELLI D'ITALIA",
    "MOLTENI NICOLA": "LEGA - SALVINI PREMIER",
    "PRISCO EMANUELE": "FRATELLI D'ITALIA",
    "SISTO FRANCESCO PAOLO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "DELMASTRO DELLE VEDOVE ANDREA": "FRATELLI D'ITALIA",
    "OSTELLARI ANDREA": "LEGA - SALVINI PREMIER",
    "PEREGO DI CREMNAGO MATTEO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "RAUTI ISABELLA": "FRATELLI D'ITALIA",
    "LEO MAURIZIO": "FRATELLI D'ITALIA",
    "ALBANO LUCIA": "FRATELLI D'ITALIA",
    "FRENI FEDERICO": "LEGA - SALVINI PREMIER",
    "SAVINO SANDRA": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "VALENTINI VALENTINO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "BERGAMOTTO FAUSTA": "FRATELLI D'ITALIA",
    "IANNONE ANTONIO": "FRATELLI D'ITALIA",
    "D'ERAMO LUIGI": "LEGA - SALVINI PREMIER",
    "LA PIETRA PATRIZIO GIACOMO": "FRATELLI D'ITALIA",
    "GAVA VANNIA": "LEGA - SALVINI PREMIER",
    "BARBARO CLAUDIO": "FRATELLI D'ITALIA",
    "RIXI EDOARDO": "LEGA - SALVINI PREMIER",
    "FERRANTE TULLIO": "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE",
    "BELLUCCI MARIA TERESA": "FRATELLI D'ITALIA",
    "DURIGON CLAUDIO": "LEGA - SALVINI PREMIER",
    "FRASSINETTI PAOLA": "FRATELLI D'ITALIA",
    "MONTARULI AUGUSTA": "FRATELLI D'ITALIA",
    "MAZZI GIANMARCO": "FRATELLI D'ITALIA",
    "BORGONZONI LUCIA": "LEGA - SALVINI PREMIER",
    "GEMMATO MARCELLO": "FRATELLI D'ITALIA",
}

# speakingRole values that name a government office (Camera <emphasis>,
# Senate TLCRole); relatori and committee roles do not match.
GOVERNMENT_ROLE_PATTERN = (
    r"(?i)^(presidente del consiglio|vicepresidente del consiglio|ministr|"
    r"vice ?ministr|sottosegretari).*"
)

SIGLA_FALLBACKS = {
    "FRATELLI D'ITALIA": "FDI",
    "PARTITO DEMOCRATICO": "PD",
    "MOVIMENTO 5 STELLE": "M5S",
    "LEGA": "LEGA",
    "FORZA ITALIA": "FI",
    "AZIONE": "AZ",
    "ITALIA VIVA": "IV",
}


# ---------------------------------------------------------------------------
# DatabaseBuilder
# ---------------------------------------------------------------------------

class DatabaseBuilder:
    """Writes parsed parliamentary data into Neo4j with English-only schema.

    All writes use UNWIND batch pattern and execute_write/execute_read managed
    transactions (no auto-commit calls).

    Args:
        driver: An active neo4j.Driver instance (caller owns lifecycle).
        config: BuildConfig for chunk_size, batch_size, etc.
    """

    def __init__(self, driver, config: Optional[BuildConfig] = None) -> None:
        self._driver = driver
        self._config = config or BuildConfig()
        self._nlp = None  # Lazy-loaded spaCy NER model
        self._ref_linkers = None  # Lazy-loaded (DeputyResolver, ActIndex)
        # Schema v2 (C8): counter of chunks dropped for substring violations
        self.invariant_violations = 0

    def _get_nlp(self):
        """Lazy-load the spaCy NER model.

        Returns the model on success, or None if it is not installed.
        Uses a sentinel value (False) to avoid retrying after a failed load.
        """
        if self._nlp is None:
            try:
                self._nlp = load_ner_model()
            except OSError:
                print("WARNING: spaCy model it_core_news_lg not installed. Skipping NER.")
                self._nlp = False  # Sentinel to avoid retrying
        return self._nlp if self._nlp is not False else None

    def _get_ref_linkers(self):
        """Lazy-load the deputy roster and Camera-bill index for NER linking.

        Loaded once per builder instance: acts ingested later in the same run
        (update mode ingests sessions before atti) resolve on the next run or
        via the link_refs.py backfill.
        """
        if self._ref_linkers is None:
            from link_refs import load_resolver, load_act_index
            with self._driver.session() as neo_session:
                self._ref_linkers = (
                    load_resolver(neo_session), load_act_index(neo_session)
                )
        return self._ref_linkers

    # ------------------------------------------------------------------
    # Schema setup
    # ------------------------------------------------------------------

    def nuke_database(self) -> None:
        """Drop all constraints, indexes, and data from the database."""
        print("NUKE DATABASE...")
        with self._driver.session() as neo_session:
            # Drop constraints first
            try:
                constraints = neo_session.execute_read(
                    lambda tx: list(tx.run("SHOW CONSTRAINTS"))
                )
                for rec in constraints:
                    try:
                        neo_session.execute_write(
                            lambda tx, name=rec['name']: tx.run(f"DROP CONSTRAINT {name}")
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            # Drop non-lookup indexes
            try:
                indexes = neo_session.execute_read(
                    lambda tx: list(tx.run("SHOW INDEXES WHERE type <> 'LOOKUP'"))
                )
                for rec in indexes:
                    try:
                        neo_session.execute_write(
                            lambda tx, name=rec['name']: tx.run(f"DROP INDEX {name}")
                        )
                    except Exception:
                        pass
            except Exception:
                pass
            # Batched delete to avoid OOM
            deleted = 1
            total = 0
            while deleted > 0:
                result = neo_session.execute_write(
                    lambda tx: tx.run("""
                        MATCH (n)
                        WITH n LIMIT 10000
                        DETACH DELETE n
                        RETURN count(*) AS deleted
                    """).single()
                )
                deleted = result["deleted"]
                total += deleted
                if deleted > 0:
                    print(f"  Deleted {total} nodes...")
        print("Database cleared.")

    def create_constraints(self) -> None:
        """Create uniqueness constraints for all English-only node labels.

        Schema v2 (C7): no constraints for labels the builder does not create.
        IndividualVote is gone — individual votes are CAST relationships,
        created by the SPARQL enrichment step which owns its own schema.
        """
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Session) REQUIRE s.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (d:Debate) REQUIRE d.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Phase) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (sp:Speech) REQUIRE sp.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Chunk) REQUIRE c.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Person) REQUIRE p.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (dep:Deputy) REQUIRE dep.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (g:ParliamentaryGroup) REQUIRE g.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (com:Committee) REQUIRE com.name IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gm:GovernmentMember) REQUIRE gm.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (gov:Government) REQUIRE gov.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (v:Vote) REQUIRE v.id IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:ParliamentaryAct) REQUIRE a.uri IS UNIQUE",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (ev:EurovocConcept) REQUIRE ev.uri IS UNIQUE",
        ]
        with self._driver.session() as neo_session:
            for cypher in constraints:
                try:
                    neo_session.execute_write(lambda tx, c=cypher: tx.run(c))
                except Exception:
                    pass
        print("Constraints created.")

    def backfill_legacy_scope(self) -> dict[str, int]:
        """Tag nodes and edges written before multi-legislature support.

        Those graphs hold the XIX legislature only: untagged Camera deputies,
        groups, committees and memberships are Camera XIX, untagged senators
        and their memberships are Senato XIX. Must run before any loader, which
        resolves people through camera_id / senato_id and relies on
        `mandates` / `latest_legislature` being present. Idempotent.
        """
        queries = {
            "camera_ids": """
                MATCH (d:Person)
                WHERE d.camera_id IS NULL AND d.id STARTS WITH 'http://dati.camera.it/ocd/persona.rdf/'
                SET d.camera_id = d.id
                RETURN count(d) AS c""",
            "senato_ids": """
                MATCH (d:Person)
                WHERE d.senato_id IS NULL AND d.id STARTS WITH 'http://dati.senato.it/senatore/'
                SET d.senato_id = d.id
                RETURN count(d) AS c""",
            "mandates": """
                MATCH (d:Deputy) WHERE d.mandates IS NULL
                WITH d, coalesce(d.chamber, 'camera') AS chamber,
                     coalesce(d.legislatures, [19]) AS legs
                SET d.mandates = [l IN legs | chamber + '_' + toString(l)],
                    d.latest_legislature = coalesce(d.latest_legislature, 19)
                REMOVE d.legislatures
                RETURN count(d) AS c""",
            "group_memberships": """
                MATCH (p)-[m:MEMBER_OF_GROUP]->() WHERE m.legislature IS NULL
                SET m.legislature = 19, m.chamber = coalesce(p.chamber, 'camera')
                RETURN count(m) AS c""",
            "committee_memberships": """
                MATCH (p)-[m:MEMBER_OF_COMMITTEE]->() WHERE m.legislature IS NULL
                SET m.legislature = 19, m.chamber = coalesce(p.chamber, 'camera')
                RETURN count(m) AS c""",
            "groups": """
                MATCH (g:ParliamentaryGroup)<-[m:MEMBER_OF_GROUP]-()
                WHERE g.chamber IS NULL
                WITH g, collect(DISTINCT m.chamber)[0] AS chamber
                SET g.chamber = chamber, g.legislatures = [19]
                RETURN count(g) AS c""",
            "committees": """
                MATCH (c:Committee)<-[m:MEMBER_OF_COMMITTEE]-()
                WHERE c.chamber IS NULL
                WITH c, collect(DISTINCT m.chamber)[0] AS chamber
                SET c.chamber = chamber, c.legislatures = [19]
                RETURN count(c) AS c""",
        }
        counts: dict[str, int] = {}
        with self._driver.session() as neo_session:
            for key, cypher in queries.items():
                counts[key] = neo_session.execute_write(
                    lambda tx, q=cypher: tx.run(q).single()["c"]
                )
        print(f"Legacy scope backfill: {counts}")
        return counts

    def create_indexes(self) -> None:
        """Create property indexes for common query patterns.

        Note: Speech.text is intentionally NOT indexed — text values can exceed
        Neo4j RANGE index size limits (55KB+). Semantic search uses the vector
        indexes created by create_vector_index() below.
        """
        indexes = [
            "CREATE INDEX IF NOT EXISTS FOR (dep:Deputy) ON (dep.name)",
            "CREATE INDEX IF NOT EXISTS FOR (s:Session) ON (s.number)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Person) ON (p.camera_id)",
            "CREATE INDEX IF NOT EXISTS FOR (p:Person) ON (p.senato_id)",
        ]
        with self._driver.session() as neo_session:
            for cypher in indexes:
                try:
                    neo_session.execute_write(lambda tx, c=cypher: tx.run(c))
                except Exception:
                    pass
        print("Indexes created.")

    # ------------------------------------------------------------------
    # Session ingestion
    # ------------------------------------------------------------------

    def ingest_session(self, parsed_data: dict) -> None:
        """Ingest one parsed XML file (output of StenograficoParser.parse_xml_file).

        Writes Session, Debate, Phase, Speech, Chunk, Vote nodes and
        Debate-[:DISCUSSES]->ParliamentaryAct edges in a single driver session
        using UNWIND batch writes.
        """
        session_data = parsed_data["session"]
        debates = parsed_data["debates"]
        phases = parsed_data["phases"]
        speeches = parsed_data["speeches"]
        votes = parsed_data["votes"]
        act_refs = parsed_data["act_references"]

        with self._driver.session() as neo_session:
            # 1. Session node
            neo_session.execute_write(self._create_session, session_data)

            # 2. Debates
            self._batch_write(neo_session, self._create_debates, debates)

            # 3. Phases
            self._batch_write(neo_session, self._create_phases, phases)

            # 4. Speeches + chunks
            all_chunks: list[dict] = []
            for speech in speeches:
                chunks = chunk_speech(speech["text"], speech["id"], self._config)
                for chunk in chunks:
                    # Schema v2 (C8) — invariante: ogni chunk deve essere
                    # substring esatta del testo salvato dello Speech (gli offset
                    # a runtime si ricavano con speech.text.find(chunk.text)).
                    # Un chunk violante NON entra nel DB: si scarta e si conta,
                    # validate_db.py fa da gate finale sul totale.
                    if chunk["text"] not in speech["text"]:
                        self.invariant_violations += 1
                        print(
                            f"  [C8 VIOLATION] chunk {chunk['index']} of speech "
                            f"{speech['id']} is not an exact substring — dropped"
                        )
                        continue
                    chunk["speechId"] = speech["id"]
                    all_chunks.append(chunk)

            # NER enrichment (adds lawRefs and personRefs to each chunk dict)
            nlp = self._get_nlp()
            if nlp:
                enrich_chunks_with_ner(all_chunks, nlp)
            else:
                for chunk in all_chunks:
                    chunk["lawRefs"] = []
                    chunk["personRefs"] = []

            # Resolve NER strings to graph entities (mentionIds / citesUris)
            from link_refs import annotate_chunks, write_links
            resolver, act_index = self._get_ref_linkers()
            annotate_chunks(all_chunks, resolver, act_index)

            self._batch_write(neo_session, self._create_speeches, speeches)
            self._batch_write(neo_session, self._create_chunks, all_chunks)

            # MENTIONS / CITES relationships from the resolved NER refs
            write_links(neo_session, all_chunks)

            # 5. SPOKEN_BY relationships
            self._batch_write(neo_session, self._link_speeches_to_speakers, speeches)

            # 6. Votes (Session-[:HAS_VOTE]->Vote)
            for vote in votes:
                vote["sessionId"] = session_data["id"]
            self._batch_write(neo_session, self._create_votes, votes)

            # 7. Act references (Debate-[:DISCUSSES]->ParliamentaryAct)
            chamber = session_data.get("chamber", "camera")
            legislature = session_data["legislature"]
            act_batch: list[dict] = []
            for deb_original_id, acts in act_refs.items():
                debate_id = self._resolve_debate_id(session_data["id"], deb_original_id)
                for act in acts:
                    act_batch.append({
                        "debateId": debate_id,
                        "uri": placeholder_act_uri(chamber, legislature, act["type"], act["code"]),
                        "actCode": act["code"],
                        "actType": act["type"],
                        "chamber": chamber,
                        "legislature": legislature,
                    })
            self._batch_write(neo_session, self._create_act_links, act_batch)

    def _resolve_debate_id(self, session_id: str, original_deb_id: str) -> str:
        """Build the full debate node ID from session ID and original XML debate ID."""
        if original_deb_id.startswith(session_id):
            return original_deb_id
        return f"{session_id}_{original_deb_id}"

    # ------------------------------------------------------------------
    # Generic batch helper
    # ------------------------------------------------------------------

    def _batch_write(self, neo_session, fn, items: list) -> None:
        """Split items into batches and call fn via execute_write for each."""
        batch_size = self._config.batch_size
        for i in range(0, len(items), batch_size):
            neo_session.execute_write(fn, items[i:i + batch_size])

    # ------------------------------------------------------------------
    # Transaction functions — session ingestion
    # ------------------------------------------------------------------

    @staticmethod
    def _create_session(tx, session_data: dict) -> None:
        # Schema v2 (C5): year/month/day derivabili da s.date — non si salvano.
        tx.run("""
            MERGE (s:Session {id: $id})
            SET s.legislature = $legislature,
                s.number = $number,
                s.chamber = $chamber,
                s.date = date($date)
        """,
            id=session_data["id"],
            legislature=session_data["legislature"],
            number=session_data["number"],
            chamber=session_data.get("chamber", "camera"),
            date=session_data["date"],
        )

    @staticmethod
    def _create_debates(tx, batch: list) -> None:
        # Schema v2 (C5): originalId derivabile dall'id gerarchico — non si salva.
        tx.run("""
            UNWIND $batch AS row
            MERGE (d:Debate {id: row.id})
            SET d.title = row.title,
                d.order = row.order
            WITH d, row
            MATCH (s:Session {id: row.sessionId})
            MERGE (s)-[:HAS_DEBATE]->(d)
        """, batch=batch)

    @staticmethod
    def _create_phases(tx, batch: list) -> None:
        # phaseType si tiene: usato da timeline_service.py nel backend.
        tx.run("""
            UNWIND $batch AS row
            MERGE (p:Phase {id: row.id})
            SET p.title = row.title,
                p.phaseType = row.phaseType,
                p.order = row.order
            WITH p, row
            MATCH (d:Debate {id: row.debateId})
            MERGE (d)-[:HAS_PHASE]->(p)
        """, batch=batch)

    @staticmethod
    def _create_speeches(tx, batch: list) -> None:
        tx.run("""
            UNWIND $batch AS row
            MERGE (sp:Speech {id: row.id})
            SET sp.text = row.text,
                sp.speakingRole = row.speakingRole,
                sp.deputatoId = row.deputatoId,
                sp.cognomeNome = row.cognome_nome
            WITH sp, row
            MATCH (p:Phase {id: row.phaseId})
            MERGE (p)-[:CONTAINS_SPEECH]->(sp)
        """, batch=batch)

    @staticmethod
    def _create_chunks(tx, batch: list) -> None:
        tx.run("""
            UNWIND $batch AS row
            MERGE (c:Chunk {id: row.id})
            SET c.text = row.text,
                c.index = row.index,
                c.lawRefs = row.lawRefs,
                c.personRefs = row.personRefs
            WITH c, row
            MATCH (sp:Speech {id: row.speechId})
            MERGE (sp)-[:HAS_CHUNK]->(c)
        """, batch=batch)
        # Archi NEXT tra chunk consecutivi dello stesso speech: usati dalla
        # neighbor expansion del retrieval (e dichiarati nel paper §4).
        # Persi nel primo rebuild v2 — la feature degradava in silenzio
        # («appended 0/100 next chunks» in ogni log, scoperto 2026-07-24).
        tx.run("""
            UNWIND $batch AS row
            MATCH (a:Chunk {id: row.id})
            MATCH (sp:Speech {id: row.speechId})-[:HAS_CHUNK]->(b:Chunk)
            WHERE b.index = row.index + 1
            MERGE (a)-[:NEXT]->(b)
        """, batch=batch)

    @staticmethod
    def _create_votes(tx, batch: list) -> None:
        tx.run("""
            UNWIND $batch AS row
            MERGE (v:Vote {id: row.id})
            SET v.number = row.number,
                v.type = row.type,
                v.subject = row.subject,
                v.present = row.present,
                v.voters = row.voters,
                v.abstained = row.abstained,
                v.majority = row.majority,
                v.inFavor = row.inFavor,
                v.against = row.against,
                v.onMission = row.onMission,
                v.outcome = row.outcome
            WITH v, row
            MATCH (s:Session {id: row.sessionId})
            MERGE (s)-[:HAS_VOTE]->(v)
        """, batch=batch)

    @staticmethod
    def _create_act_links(tx, batch: list) -> None:
        # uri is the canonical merge key for ParliamentaryAct.
        # Placeholder acts (from XML argomenti) get a synthetic URI derived from
        # actType and actCode. SPARQL-enriched acts (from ingest_atti_parlamentari)
        # use the real dati.camera.it URI — they will overwrite the placeholder via
        # MERGE on the same synthetic URI if the number matches, OR exist as
        # separate nodes if the real URI differs (fine — the DISCUSSES edge already
        # points to the placeholder, which carries the act number for retrieval).
        tx.run("""
            UNWIND $batch AS row
            MATCH (d:Debate {id: row.debateId})
            MERGE (a:ParliamentaryAct {uri: row.uri})
            ON CREATE SET a.type = row.actType,
                          a.number = row.actCode,
                          a.isPlaceholder = true,
                          a.chamber = row.chamber,
                          a.legislature = row.legislature
            MERGE (d)-[:DISCUSSES]->(a)
        """, batch=batch)

    @staticmethod
    def _link_speeches_to_speakers(tx, batch: list) -> None:
        """Create SPOKEN_BY relationships from Speech to the speaker's Person.

        The speaker id resolves through camera_id / senato_id, so ministers who
        are not parliamentarians (loaded from the government composition) and
        people who sat in both chambers link like everyone else. Falls back to
        a GovernmentMember name match for the legacy XIX government nodes.
        """
        # Camera XMLs carry a bare numeric nominativo id ("303089"), Senate
        # AKNs the full senatore URI.
        tx.run("""
            UNWIND $batch AS row
            WITH row WHERE row.deputatoId IS NOT NULL
            MATCH (sp:Speech {id: row.id})
            WITH sp, CASE WHEN row.deputatoId STARTS WITH 'http'
                          THEN row.deputatoId
                          ELSE 'http://dati.camera.it/ocd/persona.rdf/p' + row.deputatoId
                     END AS uri
            OPTIONAL MATCH (c:Person {camera_id: uri})
            OPTIONAL MATCH (s:Person {senato_id: uri})
            WITH sp, coalesce(c, s) AS p
            WHERE p IS NOT NULL
            MERGE (sp)-[:SPOKEN_BY]->(p)
        """, batch=batch)

        # Fallback: match GovernmentMember by name for speeches not yet linked
        tx.run("""
            UNWIND $batch AS row
            WITH row WHERE row.cognome_nome IS NOT NULL
            MATCH (sp:Speech {id: row.id})
            WHERE NOT (sp)-[:SPOKEN_BY]->()
            MATCH (gm:GovernmentMember)
            WHERE toUpper(gm.last_name + ' ' + gm.first_name) = toUpper(row.cognome_nome)
               OR toUpper(gm.first_name + ' ' + gm.last_name) = toUpper(row.cognome_nome)
            MERGE (sp)-[:SPOKEN_BY]->(gm)
        """, batch=batch)

    # ------------------------------------------------------------------
    # CSV loaders
    # ------------------------------------------------------------------

    def _build_gov_uri_map(self, data_path: str, legislature: int = 19) -> dict[str, str]:
        # NB: usa _split_gov_full_name (module-level) — mai parts[-1] a mano.
        """Build map of Deputy CSV URI -> GovernmentMember ID for gov deputies.

        Only meaningful for the XIX: GOVERNMENT_GROUPS is the sitting
        government, whose deputies live on legacy gov_* nodes.
        """
        if legislature != 19:
            return {}
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        dep_df = pd.read_csv(os.path.join(data_path, f"deputati_{roman}.csv"))
        gov_uri_map: dict[str, str] = {}
        for full_name in GOVERNMENT_GROUPS:
            last_name, first_name = _split_gov_full_name(full_name, dep_df)
            last_name, first_name = last_name.upper(), first_name.upper()
            match = dep_df[
                (dep_df['cognome'].str.strip().str.upper() == last_name) &
                (dep_df['nome'].str.strip().str.upper() == first_name)
            ]
            if len(match) > 0:
                dep_uri = match.iloc[0]['deputato']
                gov_id = f"gov_{full_name.replace(' ', '_').lower()}"
                gov_uri_map[dep_uri] = gov_id
        return gov_uri_map

    # ------------------------------------------------------------------
    # Person identity
    # ------------------------------------------------------------------
    #
    # One Person node per human being. A node may carry camera_id (Camera
    # persona URI), senato_id (Senato senatore URI) and `mandates`, a list of
    # "<chamber>_<legislature>" strings. Its id is fixed at creation (persona
    # URI, senatore URI, or a legacy gov_* id for XIX ministers) and never
    # rewritten; every loader resolves incoming URIs through camera_id /
    # senato_id first, so a person seen in both chambers stays one node.

    def _person_index(self) -> tuple[dict[str, str], dict[str, str]]:
        """Return (camera_id -> node id, senato_id -> node id)."""
        with self._driver.session() as neo_session:
            rows = neo_session.execute_read(lambda tx: list(tx.run(
                "MATCH (p:Person) WHERE p.camera_id IS NOT NULL OR p.senato_id IS NOT NULL "
                "RETURN p.id AS id, p.camera_id AS cam, p.senato_id AS sen"
            )))
        camera = {r["cam"]: r["id"] for r in rows if r["cam"]}
        senato = {r["sen"]: r["id"] for r in rows if r["sen"]}
        return camera, senato

    @staticmethod
    def _load_crosswalk(data_path: str) -> dict[str, str]:
        """senatore URI -> Camera persona URI (download_person_crosswalk.py)."""
        path = os.path.join(data_path, "persone_camera_senato.csv")
        if not os.path.exists(path):
            print(f"  No crosswalk at {path}: senators will not be merged with deputies")
            return {}
        df = pd.read_csv(path, dtype=str)
        return dict(zip(df["senatore"], df["persona"]))

    def _write_people(self, rows: list[dict]) -> None:
        """Upsert Person rows produced by the deputy and senator loaders.

        Rows targeting a legacy gov_* node only record the mandate and the
        external ids: those nodes keep their labels and profile, which the
        XIX backend reads as they are.
        """
        legacy = [r for r in rows if r["id"].startswith("gov_")]
        regular = [r for r in rows if not r["id"].startswith("gov_")]
        with self._driver.session() as neo_session:
            self._batch_write(neo_session, self._upsert_people, regular)
            self._batch_write(neo_session, self._record_mandates, legacy)

    @staticmethod
    def _upsert_people(tx, batch: list) -> None:
        # Profile fields come from the most recent mandate in either chamber.
        tx.run("""
            UNWIND $batch AS row
            MERGE (d:Person {id: row.id})
            SET d:Deputy,
                d.camera_id = coalesce(row.cameraId, d.camera_id),
                d.senato_id = coalesce(row.senatoId, d.senato_id),
                d.mandates = CASE
                    WHEN row.mandate IN coalesce(d.mandates, []) THEN d.mandates
                    ELSE coalesce(d.mandates, []) + row.mandate END
            FOREACH (_ IN CASE WHEN row.chamber = 'senato' THEN [1] ELSE [] END | SET d:Senator)
            WITH d, row
            WHERE coalesce(d.latest_legislature, 0) <= row.legislature
            SET d.latest_legislature = row.legislature,
                d.chamber = row.chamber,
                d.first_name = row.firstName,
                d.last_name = row.lastName,
                d.gender = row.gender,
                d.education = coalesce(row.education, d.education),
                d.profession = coalesce(row.profession, d.profession),
                d.photo = row.photo,
                d.deputy_card = row.deputyCard,
                d.term_of_office = row.termOfOffice,
                d.term_of_office_start = row.termOfOfficeStart
        """, batch=batch)

    @staticmethod
    def _record_mandates(tx, batch: list) -> None:
        tx.run("""
            UNWIND $batch AS row
            MATCH (d:Person {id: row.id})
            SET d.camera_id = coalesce(d.camera_id, row.cameraId),
                d.senato_id = coalesce(d.senato_id, row.senatoId),
                d.mandates = CASE
                    WHEN row.mandate IN coalesce(d.mandates, []) THEN d.mandates
                    ELSE coalesce(d.mandates, []) + row.mandate END
            // Ministers who sit in the Senate (Salvini, Bernini, ...) keep the
            // gov_* node but must still count as senators
            FOREACH (_ IN CASE WHEN row.chamber = 'senato' THEN [1] ELSE [] END | SET d:Senator)
        """, batch=batch)

    def load_deputies(self, data_path: str, legislature: int = 19) -> None:
        """Load the deputies of a legislature as Person:Deputy nodes."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        dep_df = pd.read_csv(os.path.join(data_path, f"deputati_{roman}.csv"))
        camera_index, _ = self._person_index()
        gov_uri_map = self._build_gov_uri_map(data_path, legislature=legislature)

        rows: list[dict] = []
        for _, r in dep_df.iterrows():
            persona = r['deputato']
            education = None
            profession = None
            desc = r.get('descrizione')
            if pd.notna(desc):
                parts_desc = str(desc).split(";", 1)
                # C3: '' non è un valore — proprietà assente invece di stringa vuota
                education = (parts_desc[0].strip() or None) if parts_desc else None
                profession = (parts_desc[1].strip() or None) if len(parts_desc) > 1 else None

            rows.append({
                "id": camera_index.get(persona) or gov_uri_map.get(persona) or persona,
                "cameraId": persona,
                "senatoId": None,
                "mandate": f"camera_{legislature}",
                "chamber": "camera",
                "legislature": legislature,
                "firstName": r.get('nome'),
                "lastName": r.get('cognome'),
                "gender": r.get('gender'),
                "education": education,
                "profession": profession,
                "photo": normalize_photo_url(r.get('foto'), legislature=legislature),
                "deputyCard": r.get('schedaCamera'),
                "termOfOffice": r.get('mandatoCamera'),
                # Schema v2 (C1): data nativa, non stringa DD/MM/YYYY
                "termOfOfficeStart": parse_date_to_neo4j(r.get('mandatoStart')),
            })

        self._write_people(rows)
        legacy = sum(1 for r in rows if r["id"].startswith("gov_"))
        print(f"Loaded {len(rows)} deputies of legislature {legislature} "
              f"({legacy} on legacy government nodes).")

    def _camera_member_id(self, persona: str, camera_index: dict, gov_uri_map: dict) -> str:
        return camera_index.get(persona) or gov_uri_map.get(persona) or persona

    def load_groups(self, data_path: str, legislature: int = 19) -> None:
        """Load ParliamentaryGroup nodes and MEMBER_OF_GROUP relationships."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        grp_df = pd.read_csv(os.path.join(data_path, f"deputati_{roman}_gruppi.csv"))
        camera_index, _ = self._person_index()
        gov_uri_map = self._build_gov_uri_map(data_path, legislature=legislature)

        with_end: list[dict] = []
        without_end: list[dict] = []

        for _, r in grp_df.iterrows():
            name, acronym = extract_group_info(r.get('gruppoLabel'))
            if not name:
                continue
            # Rename chains: map historical labels to the canonical group name
            name = GROUP_RENAMES.get(name, name)
            if not acronym:
                for key, val in SIGLA_FALLBACKS.items():
                    if key in name:
                        acronym = val
                        break

            start_date = parse_date_to_neo4j(r.get('gruppoStart'))
            end_date = parse_date_to_neo4j(r.get('gruppoEnd'))

            row = {
                "name": name,
                "acronym": acronym,
                "nodeId": self._camera_member_id(r['deputato'], camera_index, gov_uri_map),
                "nodeLabel": "Person",
                "startDate": start_date,
                "legislature": legislature,
                "chamber": "camera",
            }
            if end_date:
                row["endDate"] = end_date
                with_end.append(row)
            else:
                without_end.append(row)

        self._check_cross_chamber_names("ParliamentaryGroup", with_end + without_end)
        with self._driver.session() as neo_session:
            if with_end:
                self._batch_write(neo_session, self._upsert_group_membership_with_end, with_end)
            if without_end:
                self._batch_write(neo_session, self._upsert_group_membership_no_end, without_end)
        print("ParliamentaryGroup nodes and MEMBER_OF_GROUP relationships loaded.")

    @staticmethod
    def _upsert_group_membership_with_end(tx, batch: list) -> None:
        DatabaseBuilder._upsert_membership(tx, batch, "MEMBER_OF_GROUP")

    @staticmethod
    def _upsert_group_membership_no_end(tx, batch: list) -> None:
        DatabaseBuilder._upsert_membership(tx, batch, "MEMBER_OF_GROUP")

    @staticmethod
    def _upsert_membership(tx, batch: list, rel_type: str) -> None:
        """Upsert group or committee memberships, one query per row because
        the member label is dynamic.

        Group and committee nodes are shared across legislatures when the label
        is identical (same political group, same standing committee); the
        membership edge carries legislature and chamber, so scoping happens on
        the edge. A committee reached from both chambers is bicameral. A row
        without endDate is an open membership.
        """
        target = "ParliamentaryGroup" if rel_type == "MEMBER_OF_GROUP" else "Committee"
        for row in batch:
            label = row["nodeLabel"]
            end_clause = "SET m.end_date = $endDate" if row.get("endDate") else "REMOVE m.end_date"
            acronym_clause = (
                "SET g.acronym = coalesce($acronym, g.acronym)"
                if target == "ParliamentaryGroup" else ""
            )
            tx.run(f"""
                MERGE (g:{target} {{name: $name}})
                {acronym_clause}
                SET g.chamber = CASE
                        WHEN g.chamber IS NULL OR g.chamber = $chamber THEN $chamber
                        ELSE 'bicamerale' END,
                    g.legislatures = CASE
                        WHEN $legislature IN coalesce(g.legislatures, []) THEN g.legislatures
                        ELSE coalesce(g.legislatures, []) + $legislature END
                WITH g
                MATCH (d:{label} {{id: $nodeId}})
                MERGE (d)-[m:{rel_type} {{start_date: $startDate}}]->(g)
                SET m.legislature = $legislature, m.chamber = $chamber
                {end_clause}
            """, name=row["name"], acronym=row.get("acronym"), nodeId=row["nodeId"],
                startDate=row["startDate"], endDate=row.get("endDate"),
                legislature=row["legislature"], chamber=row["chamber"])

    def _check_cross_chamber_names(self, label: str, rows: list[dict]) -> None:
        """Refuse to merge a group/committee label into a node owned by the
        other chamber: nodes are keyed by name only, and Camera and Senato
        labels differ today only by spelling and case. Bicameral committees
        are mapped onto one node beforehand and marked `bicameral`."""
        rows = [r for r in rows if not r.get("bicameral")]
        if not rows:
            return
        chamber = rows[0]["chamber"]
        names = sorted({r["name"] for r in rows})
        with self._driver.session() as neo_session:
            clashes = neo_session.execute_read(lambda tx: [
                r["name"] for r in tx.run(
                    f"MATCH (g:{label}) WHERE g.name IN $names "
                    "AND g.chamber IS NOT NULL AND g.chamber <> $chamber "
                    "RETURN g.name AS name",
                    names=names, chamber=chamber,
                )
            ])
        if clashes:
            raise ValueError(
                f"{label} names already used by the other chamber: {clashes}"
            )

    def _bicameral_committee_names(self, names: set[str], chamber: str) -> dict[str, str]:
        """Map incoming committee labels to an existing node of the other
        chamber when both name the same bicameral body.

        Only "parlamentare" bodies (Commissione/Comitato parlamentare, the
        delegations to parliamentary assemblies) are bicameral; bodies such as
        the Giunta per il Regolamento exist separately in each chamber under
        the same name.
        """
        with self._driver.session() as neo_session:
            existing = neo_session.execute_read(lambda tx: [
                r["name"] for r in tx.run(
                    "MATCH (c:Committee) WHERE c.chamber IS NOT NULL AND c.chamber <> $chamber "
                    "RETURN c.name AS name", chamber=chamber,
                )
            ])
        by_key = {normalize_body_name(n): n for n in existing}
        mapping: dict[str, str] = {}
        for name in names:
            key = normalize_body_name(name)
            if "PARLAMENTARE" in key and key in by_key:
                mapping[name] = by_key[key]
        return mapping

    def load_committees(self, data_path: str, legislature: int = 19) -> None:
        """Load Committee nodes and MEMBER_OF_COMMITTEE relationships."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        com_df = pd.read_csv(os.path.join(data_path, f"deputati_{roman}_commissioni.csv"))
        camera_index, _ = self._person_index()
        gov_uri_map = self._build_gov_uri_map(data_path, legislature=legislature)
        self._load_committee_rows(com_df, "deputato", "camera", legislature,
                                  lambda uri: self._camera_member_id(uri, camera_index, gov_uri_map))

    def _load_committee_rows(self, com_df, person_col: str, chamber: str,
                             legislature: int, member_id) -> None:
        names = {clean_generic_label(x) for x in com_df["organoLabel"]} - {None}
        bicameral = self._bicameral_committee_names(names, chamber)

        with_end: list[dict] = []
        without_end: list[dict] = []
        for _, r in com_df.iterrows():
            name = clean_generic_label(r.get("organoLabel"))
            if not name:
                continue
            row = {
                "name": bicameral.get(name, name),
                "bicameral": name in bicameral,
                "nodeId": member_id(r[person_col]),
                "nodeLabel": "Person",
                "startDate": parse_date_to_neo4j(r.get("membroStart")),
                "legislature": legislature,
                "chamber": chamber,
            }
            end_date = parse_date_to_neo4j(r.get("membroEnd"))
            if end_date:
                row["endDate"] = end_date
                with_end.append(row)
            else:
                without_end.append(row)

        self._check_cross_chamber_names("Committee", with_end + without_end)
        with self._driver.session() as neo_session:
            if with_end:
                self._batch_write(neo_session, self._upsert_committee_membership_with_end, with_end)
            if without_end:
                self._batch_write(neo_session, self._upsert_committee_membership_no_end, without_end)
        print(f"Committee memberships loaded ({chamber} {legislature}, "
              f"{len(bicameral)} bicameral bodies shared with the other chamber).")

    @staticmethod
    def _upsert_committee_membership_with_end(tx, batch: list) -> None:
        DatabaseBuilder._upsert_membership(tx, batch, "MEMBER_OF_COMMITTEE")

    @staticmethod
    def _upsert_committee_membership_no_end(tx, batch: list) -> None:
        DatabaseBuilder._upsert_membership(tx, batch, "MEMBER_OF_COMMITTEE")

    # ------------------------------------------------------------------
    # Senate CSV loaders
    # ------------------------------------------------------------------

    def _senator_id_resolver(self, data_path: str):
        """senatore URI -> node id: an existing senator, else the node of the
        same person as a deputy or government member, else the URI itself."""
        camera_index, senato_index = self._person_index()
        crosswalk = self._load_crosswalk(data_path)

        def resolve(senatore: str) -> str:
            if senatore in senato_index:
                return senato_index[senatore]
            persona = crosswalk.get(senatore)
            if persona and persona in camera_index:
                return camera_index[persona]
            return senatore

        return resolve, crosswalk

    def load_senators(self, data_path: str, legislature: int = 19) -> None:
        """Load the senators of a legislature as Person:Deputy:Senator nodes
        (:Deputy kept for the backend queries written for the Camera)."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        csv_path = os.path.join(data_path, f"senatori_{roman}.csv")
        if not os.path.exists(csv_path):
            print(f"  Skipping senators — {csv_path} not found")
            return

        sen_df = pd.read_csv(csv_path)
        resolve, crosswalk = self._senator_id_resolver(data_path)

        rows: list[dict] = []
        for _, r in sen_df.iterrows():
            senatore = r["senatore"]
            card = r.get("schedaCamera")
            rows.append({
                "id": resolve(senatore),
                "cameraId": crosswalk.get(senatore),
                "senatoId": senatore,
                "mandate": f"senato_{legislature}",
                "chamber": "senato",
                "legislature": legislature,
                "firstName": r.get("nome"),
                "lastName": r.get("cognome"),
                "gender": r.get("gender"),
                "education": None,
                "profession": None,
                "photo": r.get("foto"),
                "deputyCard": str(card) if pd.notna(card) else None,
                "termOfOffice": None,
                # Schema v2 (C1): data nativa, non stringa DD/MM/YYYY
                "termOfOfficeStart": parse_date_to_neo4j(r.get("mandatoStart")),
            })

        self._write_people(rows)
        merged = sum(1 for r in rows if r["id"] != r["senatoId"])
        print(f"Loaded {len(rows)} senators of legislature {legislature} "
              f"({merged} merged with an existing person).")

    def load_senator_groups(self, data_path: str, legislature: int = 19) -> None:
        """Load ParliamentaryGroup nodes and MEMBER_OF_GROUP rels for senators."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        csv_path = os.path.join(data_path, f"senatori_{roman}_gruppi.csv")
        if not os.path.exists(csv_path):
            print(f"  Skipping senator groups — {csv_path} not found")
            return

        grp_df = pd.read_csv(csv_path)
        resolve, _ = self._senator_id_resolver(data_path)

        with_end: list[dict] = []
        without_end: list[dict] = []

        for _, r in grp_df.iterrows():
            name = str(r.get("gruppoLabel", "")).strip()
            if not name:
                continue
            acronym = str(r.get("gruppoBreve", "")).strip() or None

            start_date = parse_date_to_neo4j(r.get("gruppoStart"))
            end_date = parse_date_to_neo4j(r.get("gruppoEnd"))

            row = {
                "name": name,
                "acronym": acronym,
                "nodeId": resolve(r["senatore"]),
                "nodeLabel": "Person",
                "startDate": start_date,
                "legislature": legislature,
                "chamber": "senato",
            }
            if end_date:
                row["endDate"] = end_date
                with_end.append(row)
            else:
                without_end.append(row)

        self._check_cross_chamber_names("ParliamentaryGroup", with_end + without_end)
        with self._driver.session() as neo_session:
            if with_end:
                self._batch_write(neo_session, self._upsert_group_membership_with_end, with_end)
            if without_end:
                self._batch_write(neo_session, self._upsert_group_membership_no_end, without_end)
        print("Senator ParliamentaryGroup nodes and MEMBER_OF_GROUP relationships loaded.")

    def load_senator_committees(self, data_path: str, legislature: int = 19) -> None:
        """Load Committee nodes and MEMBER_OF_COMMITTEE rels for senators."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        csv_path = os.path.join(data_path, f"senatori_{roman}_commissioni.csv")
        if not os.path.exists(csv_path):
            print(f"  Skipping senator committees — {csv_path} not found")
            return
        resolve, _ = self._senator_id_resolver(data_path)
        self._load_committee_rows(pd.read_csv(csv_path), "senatore", "senato", legislature, resolve)

    def load_government_members(self) -> None:
        """Create GovernmentMember nodes and link them to ParliamentaryGroups.

        NOTE: This method requires a data_path for CSV lookups. Provide it via
        load_government_members_from_path(data_path) in production code that has
        access to the CSV files. This stub creates nodes without CSV enrichment.
        """
        # Build gov member rows from GOVERNMENT_GROUPS constant
        rows: list[dict] = []
        for full_name, group_name in GOVERNMENT_GROUPS.items():
            last_name, first_name = _split_gov_full_name(full_name)
            fid = f"gov_{full_name.replace(' ', '_').lower()}"
            rows.append({
                "id": fid,
                "firstName": first_name,
                "lastName": last_name,
                "groupName": group_name,
            })

        with self._driver.session() as neo_session:
            self._batch_write(neo_session, self._upsert_government_members, rows)
        print(f"Created {len(rows)} GovernmentMember nodes.")

    def load_government_members_from_path(self, data_path: str, legislature: int = 19) -> None:
        """Create GovernmentMember nodes with CSV enrichment (photo, gender, etc.)."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        dep_df = pd.read_csv(os.path.join(data_path, f"deputati_{roman}.csv"))
        dep_lookup: dict[str, dict] = {}
        for _, r in dep_df.iterrows():
            key = f"{str(r.get('cognome', '')).strip().upper()} {str(r.get('nome', '')).strip().upper()}"
            dep_lookup[key] = dict(r)

        rows: list[dict] = []
        for full_name, group_name in GOVERNMENT_GROUPS.items():
            last_name, first_name = _split_gov_full_name(full_name, dep_df)
            fid = f"gov_{full_name.replace(' ', '_').lower()}"

            csv_data = dep_lookup.get(full_name)
            photo = normalize_photo_url(csv_data.get('foto')) if csv_data and pd.notna(csv_data.get('foto')) else None
            deputy_card = csv_data.get('schedaCamera') if csv_data and pd.notna(csv_data.get('schedaCamera')) else None
            gender = csv_data.get('gender') if csv_data and pd.notna(csv_data.get('gender')) else None
            term_of_office = csv_data.get('mandatoCamera') if csv_data and pd.notna(csv_data.get('mandatoCamera')) else None
            # Schema v2 (C1): data nativa, non stringa DD/MM/YYYY
            tos = parse_date_to_neo4j(csv_data.get('mandatoStart')) if csv_data else None

            rows.append({
                "id": fid,
                "firstName": first_name,
                "lastName": last_name,
                "groupName": group_name,
                "photo": photo,
                "deputyCard": deputy_card,
                "gender": gender,
                "termOfOffice": term_of_office,
                "termOfOfficeStart": tos,
            })

        with self._driver.session() as neo_session:
            self._batch_write(neo_session, self._upsert_government_members_enriched, rows)
        print(f"Created {len(rows)} GovernmentMember nodes (with CSV enrichment).")

    @staticmethod
    def _upsert_government_members(tx, batch: list) -> None:
        # Schema v2 (C5): via is_government — la label GovernmentMember basta.
        tx.run("""
            UNWIND $batch AS row
            MERGE (d:GovernmentMember {id: row.id})
            SET d:Person,
                d.first_name = row.firstName,
                d.last_name = row.lastName
            WITH d, row
            MATCH (g:ParliamentaryGroup {name: row.groupName})
            MERGE (d)-[mg:MEMBER_OF_GROUP]->(g)
            SET mg.start_date = date('2022-10-18'), mg.legislature = 19, mg.chamber = 'camera'
        """, batch=batch)

    @staticmethod
    def _upsert_government_members_enriched(tx, batch: list) -> None:
        tx.run("""
            UNWIND $batch AS row
            MERGE (d:GovernmentMember {id: row.id})
            SET d:Person,
                d.first_name = row.firstName,
                d.last_name = row.lastName,
                d.gender = row.gender,
                d.photo = row.photo,
                d.deputy_card = row.deputyCard,
                d.term_of_office = row.termOfOffice,
                d.term_of_office_start = row.termOfOfficeStart
            WITH d, row
            MATCH (g:ParliamentaryGroup {name: row.groupName})
            MERGE (d)-[mg:MEMBER_OF_GROUP]->(g)
            SET mg.start_date = date('2022-10-18'), mg.legislature = 19, mg.chamber = 'camera'
        """, batch=batch)

    # ------------------------------------------------------------------
    # Governments
    # ------------------------------------------------------------------

    @staticmethod
    def _office_type(role: str) -> str:
        """Classify a government role string into an office_type enum."""
        r = role.lower()
        if "presidente del consiglio" in r and "vicepresidente" not in r:
            return "pm"
        if "vicepresidente del consiglio" in r:
            return "deputy_pm"
        if "sottosegretari" in r:
            return "undersecretary"
        if "viceministr" in r or "vice ministr" in r:
            return "deputy_minister"
        return "minister"

    @staticmethod
    def government_id(label: str) -> str:
        """"II Governo Conte" -> "conte_2". "I Governo Meloni" -> "meloni_1",
        the id the XIX graph already uses."""
        m = re.match(r"^([IVXL]+)\s+Governo\s+(.+)$", label.strip())
        if not m:
            raise ValueError(f"Unexpected government label: {label!r}")
        roman = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8}
        surname = re.sub(r"[^a-z]+", "_", m.group(2).lower()).strip("_")
        return f"{surname}_{roman[m.group(1)]}"

    def sync_governments(self, data_path: str) -> dict[str, int]:
        """Load every data/governi_*.csv (download_governments_csv.py) as
        Government nodes and dated HOLDS_OFFICE edges.

        Members are resolved through camera_id. Legacy XIX gov_* nodes predate
        camera_id and are matched once by name; members with no node yet (a
        minister who is not a parliamentarian, or a deputy of a legislature not
        loaded) get a Person:GovernmentMember node keyed by the persona URI,
        which load_deputies later finds through camera_id. Idempotent: the
        offices of each government are rewritten from the file.
        """
        frames = [
            pd.read_csv(os.path.join(data_path, f), dtype=str).fillna("")
            for f in sorted(os.listdir(data_path))
            if re.fullmatch(r"governi_[a-z]+\.csv", f)
        ]
        if not frames:
            print("  No governi_*.csv found: government offices not loaded")
            return {}
        df = pd.concat(frames, ignore_index=True)

        def iso(yyyymmdd: str):
            return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}" if len(yyyymmdd) == 8 else None

        governments = []
        for (uri, label), g in df.groupby(["governo", "governoLabel"]):
            governments.append({
                "id": self.government_id(label),
                "uri": uri,
                "name": re.sub(r"^([IVXL]+)\s+Governo\s+(.+)$", r"Governo \2 \1", label),
                "start": iso(g["governoStart"].iloc[0]),
                "end": iso(g["governoEnd"].iloc[0]),
            })
        gov_by_uri = {g["uri"]: g["id"] for g in governments}
        # Offices often lack an end date on dati.camera.it when they lasted
        # until the government fell (Draghi undersecretaries, verified 2026-10-02).
        gov_end = {g["uri"]: g["end"] for g in governments}

        people = (
            df.sort_values("start")
              .drop_duplicates("persona", keep="last")[["persona", "nome", "cognome"]]
              .to_dict("records")
        )
        offices = [{
            "uri": r["membro"],
            "persona": r["persona"],
            "governmentId": gov_by_uri[r["governo"]],
            "role": r["carica"],
            "officeType": self._office_type(r["carica"]),
            "start": iso(r["start"]),
            "end": iso(r["end"]) or gov_end[r["governo"]],
        } for r in df.to_dict("records")]

        with self._driver.session() as neo_session:
            neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $govs AS g
                MERGE (gov:Government {id: g.id})
                SET gov.uri = g.uri, gov.name = g.name,
                    gov.start_date = CASE WHEN g.start IS NULL THEN null ELSE date(g.start) END,
                    gov.end_date = CASE WHEN g.end IS NULL THEN null ELSE date(g.end) END
            """, govs=governments))

            self._assign_legacy_camera_ids(neo_session, people)

            created = neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $people AS row
                WITH row WHERE NOT EXISTS { MATCH (:Person {camera_id: row.persona}) }
                MERGE (p:Person {id: row.persona})
                ON CREATE SET p:GovernmentMember, p.camera_id = row.persona,
                              p.first_name = row.nome, p.last_name = row.cognome
                RETURN count(p) AS c
            """, people=people).single()["c"])

            # Legacy gov_* nodes split some names wrongly ("ELVIRA" /
            # "CALDERONE MARINA"); the official list has them right, and
            # surname matching of Senate speeches depends on it.
            neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $people AS row
                MATCH (p:Person {camera_id: row.persona})
                WHERE p.id STARTS WITH 'gov_'
                SET p.first_name = row.nome, p.last_name = row.cognome
            """, people=people))

            neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $govIds AS gid
                MATCH (:Person)-[h:HOLDS_OFFICE]->(:Government {id: gid})
                DELETE h
            """, govIds=list(gov_by_uri.values())))
            written = neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $offices AS o
                MATCH (p:Person {camera_id: o.persona})
                MATCH (gov:Government {id: o.governmentId})
                CREATE (p)-[h:HOLDS_OFFICE]->(gov)
                SET h.uri = o.uri, h.role = o.role, h.office_type = o.officeType,
                    h.start_date = date(o.start),
                    h.end_date = CASE WHEN o.end IS NULL THEN null ELSE date(o.end) END
                RETURN count(h) AS c
            """, offices=offices).single()["c"])

        counts = {"governments": len(governments), "people_created": created,
                  "offices": written, "offices_in_files": len(offices)}
        print(f"Governments synced: {counts}")
        return counts

    @staticmethod
    def _assign_legacy_camera_ids(neo_session, people: list[dict]) -> None:
        """Give legacy gov_* nodes their persona URI (see match_legacy_government_node)."""
        legacy = neo_session.execute_read(lambda tx: [dict(r) for r in tx.run(
            "MATCH (g:GovernmentMember) WHERE g.id STARTS WITH 'gov_' AND g.camera_id IS NULL "
            "RETURN g.id AS id, g.first_name AS first, g.last_name AS last, g.deputy_card AS card"
        )])
        if not legacy:
            return

        assignments = []
        for g in legacy:
            persona = match_legacy_government_node(g["first"], g["last"], g["card"], people)
            if persona:
                assignments.append({"id": g["id"], "persona": persona})
            else:
                print(f"  No official match for legacy government node {g['id']}")
        neo_session.execute_write(lambda tx: tx.run("""
            UNWIND $rows AS row
            MATCH (g:GovernmentMember {id: row.id})
            SET g.camera_id = row.persona
        """, rows=assignments))

    def merge_duplicate_people(self) -> int:
        """Merge Person nodes that share camera_id or senato_id.

        Duplicates arise when one side of a person was created before the id
        that links it was known. The survivor is the legacy gov_* node if any,
        else the node with most relationships; all edges move onto it.
        """
        merged = 0
        with self._driver.session() as neo_session:
            for key in ("camera_id", "senato_id"):
                groups = neo_session.execute_read(lambda tx, k=key: [r["ids"] for r in tx.run(f"""
                    MATCH (p:Person) WHERE p.{k} IS NOT NULL
                    WITH p.{k} AS v, p, COUNT {{ (p)--() }} AS degree
                    ORDER BY CASE WHEN p.id STARTS WITH 'gov_' THEN 0 ELSE 1 END, degree DESC
                    WITH v, collect(p.id) AS ids WHERE size(ids) > 1
                    RETURN ids
                """)])
                for ids in groups:
                    neo_session.execute_write(lambda tx, ids=ids: tx.run("""
                        UNWIND $ids AS id MATCH (p:Person {id: id})
                        WITH collect(p) AS nodes
                        WITH nodes, [n IN nodes | n.mandates] AS mandateLists
                        CALL apoc.refactor.mergeNodes(nodes, {properties: 'discard', mergeRels: true})
                        YIELD node
                        SET node.mandates = apoc.coll.toSet(apoc.coll.flatten(
                            [m IN mandateLists WHERE m IS NOT NULL]))
                        RETURN node
                    """, ids=ids).consume())
                    merged += len(ids) - 1
        print(f"Merged {merged} duplicate Person nodes")
        return merged

    def mark_final_memberships(self) -> int:
        """Flag final_in_legislature on the group memberships still open when
        their legislature ended.

        Retrieval attributes a speech to the group the speaker belongs to at
        the end of the legislature (today, for the current one), so that a
        speech by someone who later switched group follows the new group. For a
        closed legislature every membership has an end date; this flag marks the
        ones that lasted to its last day. Members who left before the end keep
        it false, as an open-ended-today rule would.
        """
        with self._driver.session() as neo_session:
            n = neo_session.execute_write(lambda tx: tx.run("""
                MATCH ()-[m:MEMBER_OF_GROUP]->()
                WHERE m.legislature IS NOT NULL
                WITH m.chamber AS chamber, m.legislature AS leg,
                     max(coalesce(m.end_date, date())) AS lastDay, collect(m) AS ms
                UNWIND ms AS m
                SET m.final_in_legislature =
                    m.end_date IS NULL OR m.end_date >= lastDay - duration({days: 3})
                RETURN sum(CASE WHEN m.final_in_legislature THEN 1 ELSE 0 END) AS c
            """).single()["c"])
        print(f"Group memberships open at the end of their legislature: {n}")
        return n

    def relink_mismatched_speakers(self) -> int:
        """Point SPOKEN_BY at the person the transcript names (deputatoId)
        when an earlier name-based link chose someone else, e.g. Minister
        Marina Calderone's speeches attached to deputy Tommaso Calderone."""
        with self._driver.session() as neo_session:
            result = neo_session.run("""
                CALL apoc.periodic.iterate(
                  "MATCH (sp:Speech)-[r:SPOKEN_BY]->(p:Person)
                   WHERE sp.deputatoId IS NOT NULL
                   WITH sp, r, p, CASE WHEN sp.deputatoId STARTS WITH 'http' THEN sp.deputatoId
                        ELSE 'http://dati.camera.it/ocd/persona.rdf/p' + sp.deputatoId END AS uri
                   WHERE coalesce(p.camera_id, '') <> uri AND coalesce(p.senato_id, '') <> uri
                   RETURN sp, r, uri",
                  "OPTIONAL MATCH (c:Person {camera_id: uri})
                   OPTIONAL MATCH (s:Person {senato_id: uri})
                   WITH sp, r, coalesce(c, s) AS right WHERE right IS NOT NULL
                   DELETE r
                   MERGE (sp)-[:SPOKEN_BY]->(right)",
                  {batchSize: 1000})
                YIELD total RETURN total
            """).single()
        print(f"Speeches relinked to the speaker named in the transcript: {result['total']}")
        return result["total"]

    def normalize_person_labels(self) -> int:
        """GovernmentMember marks people known only through a government office.

        Legacy XIX gov_* nodes keep the label and never carry :Deputy, as the
        XIX backend expects (a merged duplicate can bring :Deputy along).
        """
        with self._driver.session() as neo_session:
            n = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (p:Person:GovernmentMember)
                WHERE NOT p.id STARTS WITH 'gov_' AND (p:Deputy OR p:Senator)
                REMOVE p:GovernmentMember
                RETURN count(p) AS c
            """).single()["c"])
            # Legacy gov_* nodes are deputies only when they hold a Camera
            # mandate (a minister who is also a deputy); the others are not.
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (p:Person) WHERE p.id STARTS WITH 'gov_'
                WITH p, any(m IN coalesce(p.mandates, []) WHERE m STARTS WITH 'camera_') AS deputy
                FOREACH (_ IN CASE WHEN deputy THEN [1] ELSE [] END | SET p:Deputy)
                FOREACH (_ IN CASE WHEN deputy THEN [] ELSE [1] END | REMOVE p:Deputy)
            """))
        print(f"GovernmentMember label removed from {n} parliamentarians")
        return n

    def load_camera_seats(self, data_path: str, legislature: int) -> int:
        """Seat in the Camera chamber of each sitting deputy (camera.it/deputati).

        The seating is today's: deputies who left have no seat, and seats are
        rewritten on every run because they change with group moves.
        """
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        path = os.path.join(data_path, f"seggi_camera_{roman}.csv")
        if not os.path.exists(path):
            print(f"{path} missing; run download_camera_seats.py")
            return 0
        df = pd.read_csv(path, dtype={"persona": str, "posto": int})
        rows = [{"cameraId": r["persona"], "seat": int(r["posto"])} for _, r in df.iterrows()]
        with self._driver.session() as neo_session:
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (p:Person) WHERE p.camera_seat_legislature = $legislature
                REMOVE p.camera_seat, p.camera_seat_legislature
            """, legislature=legislature))
            n = neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $rows AS row
                MATCH (p:Person {camera_id: row.cameraId})
                SET p.camera_seat = row.seat, p.camera_seat_legislature = $legislature
                RETURN count(p) AS c
            """, rows=rows, legislature=legislature).single()["c"])
        print(f"Camera seats loaded (legislature {legislature}): {n} of {len(rows)}")
        return n

    def mark_party_affiliations(self) -> int:
        """Group links of people with no seat in that chamber and legislature
        (ministers from outside Parliament) record their party, not a seat:
        they are flagged and lose the chamber so seat counts ignore them."""
        with self._driver.session() as neo_session:
            n = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (p:Person)-[m:MEMBER_OF_GROUP]->()
                WHERE m.chamber IN ['camera', 'senato'] AND m.legislature IS NOT NULL
                  AND NOT (m.chamber + '_' + toString(m.legislature)) IN coalesce(p.mandates, [])
                SET m.affiliation = true
                REMOVE m.chamber
                RETURN count(m) AS c
            """).single()["c"])
        print(f"Group links marked as party affiliation: {n}")
        return n

    def close_memberships_at_mandate_end(self, data_path: str, legislature: int) -> int:
        """Close group and committee memberships still open for deputies whose
        Camera mandate ended (resignation, election elsewhere, death)."""
        roman = ROMAN_MAP.get(legislature, f"leg{legislature}")
        path = os.path.join(data_path, f"deputati_{roman}.csv")
        df = pd.read_csv(path, dtype=str)
        if "mandatoEnd" not in df.columns:
            print(f"{path} has no mandatoEnd column; re-download the deputies")
            return 0
        ends = [
            {"cameraId": r["deputato"], "end": f"{e[:4]}-{e[4:6]}-{e[6:8]}"}
            for _, r in df.iterrows()
            if isinstance((e := r.get("mandatoEnd")), str) and len(e) >= 8
        ]
        with self._driver.session() as neo_session:
            n = neo_session.execute_write(lambda tx: tx.run("""
                UNWIND $ends AS row
                MATCH (p:Person {camera_id: row.cameraId})-[m:MEMBER_OF_GROUP|MEMBER_OF_COMMITTEE]->()
                WHERE m.end_date IS NULL AND m.legislature = $legislature
                  AND coalesce(m.chamber, 'camera') = 'camera'
                SET m.end_date = date(row.end)
                RETURN count(m) AS c
            """, ends=ends, legislature=legislature).single()["c"])
        print(f"Memberships closed at mandate end (camera {legislature}): {n}")
        return n

    def annotate_speech_government_roles(self, legislature: int, chamber: str) -> int:
        """Store on each Speech the government office its speaker held on the
        sitting date: government_role (office label), government_id, and
        speaker_in_government, always written so that readers can tell an
        annotated non-government speech from one not annotated yet.

        The transcript's own role wins when it names a government office
        (Camera <emphasis>, Senate TLCRole); otherwise the dated HOLDS_OFFICE
        edges decide. A minister who later sits as a plain deputy, or a deputy
        who later joins the government, is therefore classified per speech.
        """
        with self._driver.session() as neo_session:
            result = neo_session.run("""
                CALL apoc.periodic.iterate(
                  "MATCH (s:Session)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
                   WHERE s.legislature = $leg AND coalesce(s.chamber, 'camera') = $chamber
                   RETURN sp, s.date AS day",
                  "OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(:Person)-[h:HOLDS_OFFICE]->(g:Government)
                   WHERE h.start_date <= day AND (h.end_date IS NULL OR h.end_date >= day)
                   WITH sp, day, h, g
                   ORDER BY CASE h.office_type WHEN 'pm' THEN 0 WHEN 'deputy_pm' THEN 1
                            WHEN 'minister' THEN 2 WHEN 'deputy_minister' THEN 3 ELSE 4 END
                   WITH sp, day, collect(h.role)[0] AS office, collect(g.id)[0] AS officeGov
                   OPTIONAL MATCH (cur:Government)
                   WHERE cur.start_date <= day AND (cur.end_date IS NULL OR cur.end_date >= day)
                   WITH sp, office, officeGov, collect(cur.id)[0] AS govOnDay,
                        coalesce(sp.speakingRole, '') =~ $govRolePattern AS spokeAsGov
                   WITH sp, CASE WHEN spokeAsGov THEN sp.speakingRole ELSE office END AS role,
                        coalesce(officeGov, govOnDay) AS gov
                   SET sp.government_role = role,
                       sp.government_id = CASE WHEN role IS NULL THEN null ELSE gov END,
                       sp.speaker_in_government = role IS NOT NULL",
                  {batchSize: 2000, params: {leg: $leg, chamber: $chamber,
                                             govRolePattern: $govRolePattern}})
                YIELD total, failedBatches, errorMessages
                RETURN total, failedBatches, errorMessages
            """, leg=legislature, chamber=chamber, govRolePattern=GOVERNMENT_ROLE_PATTERN).single()
            if result["failedBatches"]:
                raise RuntimeError(f"Speech role annotation failed: {result['errorMessages']}")
            tagged = neo_session.run("""
                MATCH (s:Session)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
                WHERE s.legislature = $leg AND coalesce(s.chamber, 'camera') = $chamber
                  AND sp.government_role IS NOT NULL
                RETURN count(sp) AS c
            """, leg=legislature, chamber=chamber).single()["c"]
        print(f"Speech government roles ({chamber} {legislature}): "
              f"{result['total']} speeches, {tagged} by government members")
        return tagged

    # ------------------------------------------------------------------
    # Roles
    # ------------------------------------------------------------------

    def load_roles(self) -> None:
        """Assign institutional roles (schema v2).

        - Government roles -> (d)-[:HOLDS_OFFICE {role, office_type, start_date}]->(:Government)
          plus GOVERNMENT_REFERENCE to the competent Committee.
        - Committee officer roles -> role property on MEMBER_OF_COMMITTEE
          (org:Membership-style, no separate IS_PRESIDENT/... rel types).
        - Group leadership -> role property on the active MEMBER_OF_GROUP rel.
        - institutional_role stays as a human-readable display property;
          role_type/committee_role are gone (derivable from relationships).
        """
        if not _ROLES_AVAILABLE:
            print("  (skip — app_config.py not available)")
            return

        COMMITTEE_ROLE_MAP = {
            "Presidente": "president",
            "Vicepresidente": "vice_president",
            "Segretario": "secretary",
        }

        with self._driver.session() as neo_session:
            # Clear existing role data (idempotent re-run)
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (d:Person)
                REMOVE d.institutional_role, d.role_type, d.committee_role
            """))
            # HOLDS_OFFICE and Government nodes belong to sync_governments().
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (d:Person)-[r:GOVERNMENT_REFERENCE]->()
                DELETE r
            """))
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (d:Person)-[r:MEMBER_OF_COMMITTEE|MEMBER_OF_GROUP]->()
                REMOVE r.role
            """))

            all_configs = [
                (GOVERNMENT_ROLES, 'governo'),
                (PARLIAMENT_ROLES, 'camera'),
                (CAPIGRUPPO, 'capogruppo'),
                (COMMISSION_ROLES, 'commissione'),
            ]

            matched = 0
            for role_dict, dict_type in all_configs:
                for nome, (ruolo_base, tipo_ruolo, target_entity) in role_dict.items():
                    dep_id = self._find_person(neo_session, nome)
                    if not dep_id:
                        continue
                    matched += 1

                    if tipo_ruolo == 'capogruppo':
                        full_role = f"Presidente del Gruppo {target_entity}"
                        neo_session.execute_write(lambda tx, did=dep_id, r=full_role: tx.run("""
                            MATCH (d:Person {id: $id})
                            SET d.institutional_role = $role
                        """, id=did, role=r))
                        if target_entity:
                            # Group leadership on the ACTIVE membership rel
                            neo_session.execute_write(
                                lambda tx, did=dep_id, t=target_entity: tx.run("""
                                    MATCH (d:Person {id: $id})-[r:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
                                    WHERE g.name CONTAINS $target AND r.end_date IS NULL
                                    SET r.role = 'president'
                                """, id=did, target=t))
                    elif tipo_ruolo == 'commissione':
                        full_role = f"{ruolo_base} {target_entity}"
                        neo_session.execute_write(
                            lambda tx, did=dep_id, r=full_role: tx.run("""
                                MATCH (d:Person {id: $id})
                                SET d.institutional_role = $role
                            """, id=did, role=r))
                        if target_entity:
                            committee_role = None
                            for key, val in COMMITTEE_ROLE_MAP.items():
                                if key in ruolo_base:
                                    committee_role = val
                                    break
                            if committee_role:
                                # Officer role as property on the membership rel
                                # (org:Membership). MERGE creates the rel if the
                                # CSV membership is missing for this person.
                                neo_session.execute_write(
                                    lambda tx, did=dep_id, cr=committee_role, t=target_entity: tx.run("""
                                        MATCH (d:Person {id: $id})
                                        MATCH (c:Committee) WHERE c.name = $target
                                        MERGE (d)-[r:MEMBER_OF_COMMITTEE]->(c)
                                        SET r.role = $crole
                                    """, id=did, target=t, crole=cr))
                    else:
                        neo_session.execute_write(
                            lambda tx, did=dep_id, r=ruolo_base: tx.run("""
                                MATCH (d:Person {id: $id})
                                SET d.institutional_role = $role
                            """, id=did, role=r))
                        if tipo_ruolo == 'governo':
                            if target_entity:
                                neo_session.execute_write(
                                    lambda tx, did=dep_id, t=target_entity: tx.run("""
                                        MATCH (d:Person {id: $id})
                                        MATCH (c:Committee) WHERE c.name = $target
                                        MERGE (d)-[:GOVERNMENT_REFERENCE]->(c)
                                    """, id=did, target=t))

            # Reconcile orphan Speech nodes (no SPOKEN_BY relationship yet)
            neo_session.execute_write(lambda tx: tx.run("""
                MATCH (sp:Speech) WHERE NOT (sp)-[:SPOKEN_BY]->()
                WITH sp, sp.speakingRole AS full_name
                WHERE full_name IS NOT NULL
                MATCH (d) WHERE (d:Deputy OR d:GovernmentMember)
                  AND (toUpper(d.last_name + ' ' + d.first_name) = toUpper(full_name)
                       OR toUpper(d.first_name + ' ' + d.last_name) = toUpper(full_name))
                MERGE (sp)-[:SPOKEN_BY]->(d)
            """))

            print(f"  Roles assigned: {matched}")

    def _find_person(self, neo_session, full_name: str) -> Optional[str]:
        """Find a Deputy or GovernmentMember ID by full name (last first)."""
        parts = full_name.strip().upper().split()
        if len(parts) < 2:
            return None
        for i in range(1, len(parts)):
            cognome = " ".join(parts[:i])
            nome = " ".join(parts[i:])
            result = neo_session.execute_read(
                lambda tx, c=cognome, n=nome: tx.run("""
                    MATCH (d) WHERE (d:Deputy OR d:GovernmentMember)
                      AND toUpper(d.last_name) = $cognome
                      AND toUpper(d.first_name) STARTS WITH $nome
                    RETURN d.id AS id LIMIT 1
                """, cognome=c, nome=n).single()
            )
            if result:
                return result['id']
        return None

    # ------------------------------------------------------------------
    # Vector index and session utilities
    # ------------------------------------------------------------------

    def create_vector_index(self) -> None:
        """Create vector indexes for semantic search.

        Schema v2: gli embedding degli atti sono liste native (C2), quindi
        gli indici vettoriali su title/description funzionano davvero
        (in v1 la proprietà era una stringa JSON e l'indice restava vuoto).
        """
        index_specs = [
            ("chunk_embedding_index", "Chunk", "embedding"),
            ("act_description_embedding_index", "ParliamentaryAct", "description_embedding"),
            ("act_title_embedding_index", "ParliamentaryAct", "title_embedding"),
        ]
        with self._driver.session() as neo_session:
            for name, label, prop in index_specs:
                neo_session.execute_write(lambda tx, n=name, l=label, p=prop: tx.run(f"""
                    CREATE VECTOR INDEX {n} IF NOT EXISTS
                    FOR (x:{l}) ON (x.{p})
                    OPTIONS {{indexConfig: {{
                        `vector.dimensions`: 1536,
                        `vector.similarity_function`: 'cosine'
                    }}}}
                """))
        print("Vector indexes created (chunk + act title/description).")

    @staticmethod
    def scope_label(chamber: str, legislature: int) -> str:
        return f"Scope_{chamber}_{legislature}"

    def create_scope_vector_index(self, chamber: str, legislature: int) -> str:
        """Label the chunks of one chamber and legislature and give them their
        own vector index, chunk_embedding_<chamber>_<legislature>.

        Neo4j 5.15 has no filtered vector search: querying the global index
        and filtering by legislature afterwards would let the larger corpus
        crowd XIX results out of the top-k. With one index per scope, a
        Camera XIX query sees exactly the candidates it saw before.
        """
        label = self.scope_label(chamber, legislature)
        index = f"chunk_embedding_{chamber}_{legislature}"
        with self._driver.session() as neo_session:
            neo_session.run(f"""
                CALL apoc.periodic.iterate(
                  "MATCH (s:Session)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)
                         -[:CONTAINS_SPEECH]->(:Speech)-[:HAS_CHUNK]->(c:Chunk)
                   WHERE s.legislature = $leg AND coalesce(s.chamber, 'camera') = $chamber
                     AND NOT c:{label}
                   RETURN c",
                  "SET c:{label}",
                  {{batchSize: 5000, params: {{leg: $leg, chamber: $chamber}}}})
            """, leg=legislature, chamber=chamber).consume()
            neo_session.run(f"""
                CREATE VECTOR INDEX {index} IF NOT EXISTS
                FOR (c:{label}) ON (c.embedding)
                OPTIONS {{indexConfig: {{
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}}}
            """).consume()
            n = neo_session.run(f"MATCH (c:{label}) RETURN count(c) AS n").single()["n"]
        print(f"Scope index {index}: {n} chunks")
        return index

    # Cypher =~ usa full-match: "seguito della discussione" nudo è procedurale,
    # ma "Seguito della discussione del disegno di legge X" ha contenuto e NON matcha.
    PROCEDURAL_TITLE_PATTERN = (
        r'(?i)(si riprende la discussione.*'
        r'|seguito della discussione\.?'
        r'|ripresa della discussione.*'
        r'|discussione congiunta\.?)'
    )

    def resolve_continuation_titles(self) -> None:
        """Set Debate.parent_debate_title for procedural continuation titles.

        Schema v2 §2.2: sedute con titolo "Si riprende la discussione…" vengono
        collegate al provvedimento reale via l'atto in DISCUSSES (numero/titolo),
        così l'introduzione generata può nominare il provvedimento vero.
        """
        with self._driver.session() as neo_session:
            result = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (d:Debate)
                WHERE d.title =~ $pattern
                OPTIONAL MATCH (d)-[:DISCUSSES]->(a:ParliamentaryAct)
                WITH d, collect(a)[0] AS act
                WHERE act IS NOT NULL
                SET d.parent_debate_title = coalesce(
                    act.title,
                    act.type + ' ' + act.number
                )
                RETURN count(d) AS resolved
            """, pattern=self.PROCEDURAL_TITLE_PATTERN).single())
            print(f"Continuation titles resolved: {result['resolved']}")

    def write_schema_meta(self, build_tool_commit: str | None = None) -> None:
        """Write the SchemaMeta node (v2 C9) — provenance + version check anchor."""
        with self._driver.session() as neo_session:
            neo_session.execute_write(lambda tx: tx.run("""
                MERGE (m:SchemaMeta {id: 'singleton'})
                SET m.version = 2,
                    m.embedding_model = $model,
                    m.embedding_dims = 1536,
                    m.built_at = datetime(),
                    m.updated_at = datetime(),
                    m.build_tool_commit = $commit,
                    m.source_datasets = [
                        'http://dati.camera.it/ocd/',
                        'http://dati.senato.it/',
                        'http://eurovoc.europa.eu/'
                    ]
            """, model=os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small"),
                commit=build_tool_commit))
        print("SchemaMeta written (version 2).")

    def create_fulltext_index(self) -> None:
        """Create full-text index on Chunk.text for BM25 sparse retrieval."""
        with self._driver.session() as neo_session:
            try:
                neo_session.execute_write(lambda tx: tx.run("""
                    CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS
                    FOR (n:Chunk) ON EACH [n.text]
                    OPTIONS {indexConfig: {`fulltext.analyzer`: 'italian'}}
                """))
                print("Full-text index created (italian analyzer).")
            except Exception as e:
                # Fallback if italian analyzer not available in this Neo4j instance
                print(f"Italian analyzer failed ({e}), trying standard analyzer...")
                neo_session.execute_write(lambda tx: tx.run("""
                    CREATE FULLTEXT INDEX chunk_fulltext IF NOT EXISTS
                    FOR (n:Chunk) ON EACH [n.text]
                """))
                print("Full-text index created (standard analyzer).")

    def get_existing_session_numbers(self, chamber: str | None = None, legislature: int = 19) -> set[int]:
        """Return set of session numbers already persisted in Neo4j for a chamber+legislature.

        Session numbers restart per legislature, so BOTH chamber and legislature must
        scope the query — otherwise a leg18 update sees leg19 numbers as already ingested.
        """
        query = "MATCH (s:Session) WHERE s.legislature = $legislature RETURN s.number AS number"
        params: dict = {"legislature": legislature}
        if chamber is not None:
            query = (
                "MATCH (s:Session) "
                "WHERE coalesce(s.chamber, 'camera') = $chamber "
                "AND s.legislature = $legislature "
                "RETURN s.number AS number"
            )
            params = {"chamber": chamber, "legislature": legislature}
        with self._driver.session() as neo_session:
            records = neo_session.execute_read(
                lambda tx: list(tx.run(query, **params))
            )
        return {r['number'] for r in records}

    def relink_senate_speeches(self, legislature: int = 19) -> dict[str, int]:
        """Create missing SPOKEN_BY rels for Senate speeches.

        Handles three cases:
        1. Legacy speeches whose deputatoId is the short form 'sen_XXXX'
           (older parser output) — rewritten to the full senatore URI.
        2. Speeches with a senatore-URI deputatoId not yet linked.
        3. Speeches with only a surname in cognomeNome — linked to the
           unique matching senator of the same legislature, or else to the
           unique person holding a government office on the sitting's date.

        Returns counts per phase for logging.
        """
        prefix = f"sen_leg{legislature}_"
        counts: dict[str, int] = {}
        with self._driver.session() as neo_session:
            # 1. Normalize legacy short-form ids to full URIs
            result = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (sp:Speech)
                WHERE sp.deputatoId STARTS WITH 'sen_'
                SET sp.deputatoId = 'http://dati.senato.it/senatore/'
                    + substring(sp.deputatoId, 4)
                RETURN count(sp) AS c
            """).single())
            counts["normalized_ids"] = result["c"]

            # 2. Link by senatore URI
            result = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (sp:Speech)
                WHERE sp.deputatoId STARTS WITH 'http://dati.senato.it/senatore/'
                  AND NOT (sp)-[:SPOKEN_BY]->()
                MATCH (d:Person {senato_id: sp.deputatoId})
                MERGE (sp)-[:SPOKEN_BY]->(d)
                RETURN count(sp) AS c
            """).single())
            counts["linked_by_uri"] = result["c"]

            # 3a. Fallback: unique senator surname match
            result = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (sp:Speech)
                WHERE sp.id STARTS WITH $prefix
                  AND NOT (sp)-[:SPOKEN_BY]->()
                  AND sp.cognomeNome IS NOT NULL AND sp.cognomeNome <> ''
                MATCH (d:Person)
                WHERE ('senato_' + toString($legislature)) IN coalesce(d.mandates, [])
                  AND toUpper(d.last_name) = toUpper(trim(sp.cognomeNome))
                WITH sp, collect(d) AS matches
                WHERE size(matches) = 1
                WITH sp, matches[0] AS d
                MERGE (sp)-[:SPOKEN_BY]->(d)
                RETURN count(sp) AS c
            """, prefix=prefix, legislature=legislature).single())
            counts["linked_by_surname"] = result["c"]

            # 3b. Fallback: whoever held a government office on the day of the
            # sitting under that surname. Ministers who are also members of
            # either chamber no longer carry the GovernmentMember label.
            result = neo_session.execute_write(lambda tx: tx.run("""
                MATCH (s:Session)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->(:Phase)
                      -[:CONTAINS_SPEECH]->(sp:Speech)
                WHERE sp.id STARTS WITH $prefix
                  AND NOT (sp)-[:SPOKEN_BY]->()
                  AND sp.cognomeNome IS NOT NULL AND sp.cognomeNome <> ''
                MATCH (p:Person)-[o:HOLDS_OFFICE]->(:Government)
                WHERE toUpper(p.last_name) = toUpper(trim(sp.cognomeNome))
                  AND o.start_date <= s.date
                  AND (o.end_date IS NULL OR o.end_date >= s.date)
                WITH sp, collect(DISTINCT p) AS matches
                WHERE size(matches) = 1
                WITH sp, matches[0] AS p
                MERGE (sp)-[:SPOKEN_BY]->(p)
                RETURN count(sp) AS c
            """, prefix=prefix).single())
            counts["linked_gov_by_surname"] = result["c"]

            result = neo_session.execute_read(lambda tx: tx.run("""
                MATCH (sp:Speech)
                WHERE sp.id STARTS WITH $prefix AND NOT (sp)-[:SPOKEN_BY]->()
                RETURN count(sp) AS c
            """, prefix=prefix).single())
            counts["still_orphan"] = result["c"]

        print(f"Senate speech relink: {counts}")
        return counts
