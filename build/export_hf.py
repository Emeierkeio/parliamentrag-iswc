"""
Hugging Face export of the ParliamentRAG knowledge graph (schema v2).

Flattens the Neo4j property graph into a set of Parquet tables meant for the
Hugging Face dataset hub (viewer-friendly, loadable with `datasets`). The RDF
dump for Zenodo is produced by the sibling script export_rdf.py; this one
targets tabular consumers instead.

Tables (one Parquet file each, one HF config each):
  persons             one row per Person (deputies + government members)
  organizations       groups, committees, Misto components, governments
  memberships         person <-> organization with start/end dates and roles
                        (MEMBER_OF_GROUP / _COMMITTEE / _COMPONENT + HOLDS_OFFICE)
  sessions            plenary sittings with IT/EN recaps
  debates             agenda items (order-of-business titles) with IT/EN recaps
  speeches            full transcript text, denormalized with session date,
                        debate title, phase and speaker
  votes               roll-call votes with numeric breakdowns and linked acts
  individual_votes    one row per (person, vote) with the individual outcome
  acts                parliamentary acts (bills, motions, interpellations, ...)
  act_subjects        act -> EuroVoc concept (dcterms:subject)
  speech_references   NER-resolved mentions of persons / citations of acts,
                        lifted from Chunk to Speech level (DISTINCT pairs)

Camera and Senato share the tables: every table that mixes them carries a
`chamber` column ('camera', 'senato'; 'bicamerale' for joint committees).
Senate speech text is read from the Postgres text archive (--archive-url or
ARCHIVE_URL, see build/archive_text.py), since the graph no longer holds it.

Deliberately excluded, same policy as export_rdf.py: embeddings (all
`*embedding*` properties), Chunk nodes (retrieval artifacts — speeches keep the
full text), ChatHistory (private), SpeakerDebateSummary (LLM-derived).

License: source data from dati.camera.it is CC BY-SA 4.0, so the derived tables
carry the same license (dati.senato.it is CC BY 3.0, which allows it); keep
`license: cc-by-sa-4.0` in the dataset card.

The dataset card is generated from build/hf_dataset_card.md: {{TOKEN}}
placeholders (row counts, coverage date, recap coverage) are filled with
fresh Cypher counts at export time, so the published card never drifts from
the data. `--card-only` refreshes just the README without re-exporting the
tables.

Usage:
    python export_hf.py [--out DIR] [--skip-individual-votes] [--card-only]
                        [--archive-url postgresql://...] [--repo USER/NAME]

Then upload with (requires `hf auth login`):
    hf upload <user>/<dataset-name> dumps/hf . --repo-type dataset

Connection comes from NEO4J_URI / NEO4J_USER / NEO4J_PASSWORD (repo-root .env
is loaded automatically, same convention as the other build scripts).
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from neo4j import GraphDatabase

from archive_text import TextCoverage, archive_url_from_env, load_speech_texts

REPO_ROOT = Path(__file__).resolve().parent.parent

PARQUET_KWARGS = {"engine": "pyarrow", "compression": "zstd", "index": False}
DEFAULT_REPO = "emeierkeio/parliamentrag-leg19"


def iso(value):
    """neo4j.time.Date/DateTime -> ISO string; None passes through."""
    if value is None:
        return None
    if hasattr(value, "iso_format"):
        return value.iso_format()
    return str(value)


def s(value):
    """Coerce to string (some identifier properties are stored as int)."""
    return None if value is None else str(value)


def senate_speaker(chamber, person_id, senato_id):
    """In the Senate a person is named by the Senate URI, as in Fascicoli.

    The graph has one node per person: for senators who sat in the Chamber
    (Boccia, Gelmini, ...) or in the government the node id is not the Senate
    URI, which is kept in senato_id.
    """
    return senato_id if chamber == "senato" and senato_id else person_id


def source_chamber(props: dict):
    """Chamber of an act or Misto component, falling back on its source URI.

    Camera acts and Misto components were ingested before the Senate and carry
    no `chamber` property (15/10/2026: 37,352 acts, all dati.camera.it URIs or
    Camera placeholders); Senate nodes always have it.
    """
    if props.get("chamber"):
        return props["chamber"]
    uri = str(props.get("uri") or "")
    if "senato.it" in uri:
        return "senato"
    if "camera.it" in uri or uri.startswith("placeholder:"):
        return "camera"
    return None


MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]

# One Cypher count per card token. These mirror the export queries above, so
# the numbers in the published card always match the parquet tables.
CARD_STAT_QUERIES = {
    "ROWS_SPEECHES": ("MATCH (:Session)-[:HAS_DEBATE]->(:Debate)-[:HAS_PHASE]->"
                      "(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech) RETURN count(sp) AS v"),
    "ROWS_SESSIONS": "MATCH (n:Session) RETURN count(n) AS v",
    "SESSIONS_CAMERA": "MATCH (n:Session {chamber: 'camera', legislature: 19}) RETURN count(n) AS v",
    "SESSIONS_SENATO": "MATCH (n:Session {chamber: 'senato', legislature: 19}) RETURN count(n) AS v",
    "SPEECHES_SENATO": ("MATCH (:Session {chamber: 'senato', legislature: 19})-[:HAS_DEBATE]->(:Debate)"
                        "-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech) "
                        "RETURN count(sp) AS v"),
    "VOTES_SENATO": ("MATCH (:Session {chamber: 'senato', legislature: 19})-[:HAS_VOTE]->(v:Vote) "
                     "RETURN count(v) AS v"),
    "ROWS_DEBATES": "MATCH (:Session)-[:HAS_DEBATE]->(d:Debate) RETURN count(d) AS v",
    "ROWS_VOTES": "MATCH (:Session)-[:HAS_VOTE]->(v:Vote) RETURN count(v) AS v",
    "ROWS_INDIVIDUAL_VOTES": ("MATCH (:Person)-[:VOTED]->(iv:IndividualVote)"
                              "-[:ON_VOTE]->(:Vote) RETURN count(iv) AS v"),
    "ROWS_PERSONS": "MATCH (n:Person) RETURN count(n) AS v",
    "ROWS_ORGANIZATIONS": ("MATCH (n) WHERE n:ParliamentaryGroup OR n:Committee "
                           "OR n:MistoComponent OR n:Government RETURN count(n) AS v"),
    "ROWS_MEMBERSHIPS": ("MATCH (:Person)-[r:MEMBER_OF_GROUP|MEMBER_OF_COMMITTEE"
                         "|MEMBER_OF_COMPONENT|HOLDS_OFFICE]->() WHERE r.affiliation IS NULL"
                         " RETURN count(r) AS v"),
    "ROWS_ACTS": "MATCH (n:ParliamentaryAct) RETURN count(n) AS v",
    "ROWS_ACT_SUBJECTS": ("MATCH (:ParliamentaryAct)-[r:HAS_SUBJECT]->"
                          "(:EurovocConcept) RETURN count(r) AS v"),
    "ROWS_SPEECH_REFERENCES": ("MATCH (sp:Speech)-[:HAS_CHUNK]->(:Chunk)"
                               "-[:MENTIONS|CITES]->(t) "
                               "RETURN count(DISTINCT [sp, t]) AS v"),
    "ACTS_PLACEHOLDERS": ("MATCH (n:ParliamentaryAct {isPlaceholder: true}) "
                          "RETURN count(n) AS v"),
    "SPEECHES_NO_SPEAKER": ("MATCH (sp:Speech) WHERE NOT (sp)-[:SPOKEN_BY]->() "
                            "RETURN count(sp) AS v"),
    "SESSIONS_WITH_RECAP": ("MATCH (n:Session) WHERE n.recapIt IS NOT NULL "
                            "RETURN count(n) AS v"),
    "DEBATES_WITH_RECAP": ("MATCH (n:Debate) WHERE n.recapIt IS NOT NULL "
                           "RETURN count(n) AS v"),
}


def render_card(driver, out_dir: Path, repo: str):
    """Fill build/hf_dataset_card.md tokens with live counts -> README.md."""
    template_path = Path(__file__).parent / "hf_dataset_card.md"
    if not template_path.exists():
        print("  hf_dataset_card.md not found — card skipped")
        return
    text = template_path.read_text().replace("{{HF_REPO}}", repo)
    with driver.session() as session:
        for token, cypher in CARD_STAT_QUERIES.items():
            value = session.run(cypher).single()["v"]
            text = text.replace("{{" + token + "}}", f"{value:,}")
        max_date = session.run(
            "MATCH (n:Session) RETURN max(n.date) AS v").single()["v"]
    human = f"{max_date.day} {MONTHS_EN[max_date.month - 1]} {max_date.year}"
    text = text.replace("{{MAX_DATE}}", human)
    leftover = re.findall(r"\{\{[A-Z_]+\}\}", text)
    if leftover:
        sys.exit(f"unfilled card tokens: {leftover}")
    (out_dir / "README.md").write_text(text)
    print(f"  dataset card -> {out_dir / 'README.md'} (through {human})")


class HfExporter:
    def __init__(self, driver, out_dir: Path, archive_texts: dict | None = None):
        self.driver = driver
        self.out_dir = out_dir
        self.archive_texts = archive_texts or {}
        self.text_coverage = TextCoverage()
        self.row_counts = {}

    def rows(self, cypher: str):
        with self.driver.session() as session:
            yield from session.run(cypher)

    def write(self, name: str, records: list):
        frame = pd.DataFrame.from_records(records)
        path = self.out_dir / f"{name}.parquet"
        frame.to_parquet(path, **PARQUET_KWARGS)
        self.row_counts[name] = len(frame)
        size_mb = path.stat().st_size / 1e6
        print(f"  {name}: {len(frame):,} rows -> {path.name} ({size_mb:.1f} MB)")

    # ---- tables ------------------------------------------------------------

    def export_persons(self):
        records = []
        for rec in self.rows(
            "MATCH (n:Person) RETURN elementId(n) AS eid, labels(n) AS labels, n"
        ):
            p = dict(rec["n"])
            records.append({
                "person_id": p["id"],
                "first_name": p.get("first_name"),
                "last_name": p.get("last_name"),
                "gender": p.get("gender"),
                "profession": p.get("profession"),
                "education": p.get("education"),
                "institutional_role": p.get("institutional_role"),
                # :Deputy also marks senators: a deputy holds a Camera mandate
                "is_deputy": "Deputy" in rec["labels"] and any(
                    str(m).startswith("camera_") for m in p.get("mandates") or []),
                "is_senator": "Senator" in rec["labels"],
                "is_government_member": "GovernmentMember" in rec["labels"],
                "camera_id": s(p.get("camera_id")),
                "senato_id": s(p.get("senato_id")),
                "term_of_office_start": iso(p.get("term_of_office_start")),
                "deputy_card": s(p.get("deputy_card")),
                "photo": s(p.get("photo")),
            })
        self.write("persons", records)

    def export_organizations(self):
        records = []
        for label, org_type in [("ParliamentaryGroup", "group"),
                                ("Committee", "committee"),
                                ("MistoComponent", "misto_component"),
                                ("Government", "government")]:
            for rec in self.rows(f"MATCH (n:{label}) RETURN n"):
                p = dict(rec["n"])
                records.append({
                    "org_type": org_type,
                    "chamber": source_chamber(p) if org_type != "government" else None,
                    "name": p["name"],
                    "acronym": p.get("acronym") or p.get("short_name"),
                    "uri": p.get("uri") or p.get("id"),
                    "start_date": iso(p.get("start_date")),
                })
        self.write("organizations", records)

    def export_memberships(self):
        records = []
        for rel, org_type in [("MEMBER_OF_GROUP", "group"),
                              ("MEMBER_OF_COMMITTEE", "committee"),
                              ("MEMBER_OF_COMPONENT", "misto_component")]:
            for rec in self.rows(
                # affiliation: the party area of a non-parliamentarian minister,
                # not a seat in a group; kept out of the public data
                f"MATCH (a:Person)-[r:{rel}]->(b) WHERE r.affiliation IS NULL "
                "RETURN a.id AS person_id, a.senato_id AS senato_id, b.name AS org_name, "
                "b.chamber AS org_chamber, r"
            ):
                r = dict(rec["r"])
                chamber = r.get("chamber") or rec["org_chamber"]
                records.append({
                    "person_id": senate_speaker(chamber, rec["person_id"], rec["senato_id"]),
                    "org_type": org_type,
                    "chamber": chamber,
                    "org_name": rec["org_name"],
                    "role": r.get("officerRole"),
                    "start_date": iso(r.get("start_date")),
                    "end_date": iso(r.get("end_date")),
                })
        # Government offices (ministers, undersecretaries) fold into the same
        # table: org_type 'government', role from HOLDS_OFFICE.
        for rec in self.rows(
            "MATCH (a:Person)-[r:HOLDS_OFFICE]->(b:Government) "
            "RETURN a.id AS person_id, b.name AS org_name, r"
        ):
            r = dict(rec["r"])
            records.append({
                "person_id": rec["person_id"],
                "org_type": "government",
                "chamber": None,
                "org_name": rec["org_name"],
                "role": r.get("role"),
                "start_date": iso(r.get("start_date")),
                "end_date": iso(r.get("end_date")),
            })
        self.write("memberships", records)

    def export_sessions(self):
        records = []
        for rec in self.rows("MATCH (n:Session) RETURN n ORDER BY n.date"):
            p = dict(rec["n"])
            records.append({
                "session_id": p["id"],
                "legislature": p.get("legislature"),
                "chamber": p.get("chamber"),
                "number": p.get("number"),
                "date": iso(p.get("date")),
                "record_url": p.get("record_url"),
                "recap_it": p.get("recapIt"),
                "recap_en": p.get("recapEn"),
            })
        self.write("sessions", records)

    def export_debates(self):
        records = []
        for rec in self.rows(
            "MATCH (s:Session)-[:HAS_DEBATE]->(n:Debate) "
            "RETURN s.id AS session_id, n ORDER BY s.date, n.order"
        ):
            p = dict(rec["n"])
            records.append({
                "debate_id": p["id"],
                "session_id": rec["session_id"],
                "order": p.get("order"),
                "title": p.get("title"),
                "recap_it": p.get("recapIt"),
                "recap_en": p.get("recapEn"),
            })
        self.write("debates", records)

    def export_speeches(self):
        records = []
        for rec in self.rows(
            "MATCH (s:Session)-[:HAS_DEBATE]->(d:Debate)-[:HAS_PHASE]->(ph:Phase)"
            "-[:CONTAINS_SPEECH]->(sp:Speech) "
            "OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(p:Person) "
            "RETURN s.id AS session_id, s.chamber AS chamber, s.date AS date, "
            "d.id AS debate_id, "
            "d.title AS debate_title, ph.id AS phase_id, ph.title AS phase_title, "
            "ph.phaseType AS phase_type, sp, p.id AS speaker_id, p.senato_id AS senato_id "
            "ORDER BY s.date, d.order, ph.order, sp.id"
        ):
            p = dict(rec["sp"])
            text = p.get("text") or self.archive_texts.get(p["id"])
            self.text_coverage.add(rec["chamber"], bool(text))
            records.append({
                "speech_id": p["id"],
                "chamber": rec["chamber"],
                "session_id": rec["session_id"],
                "date": iso(rec["date"]),
                "debate_id": rec["debate_id"],
                "debate_title": rec["debate_title"],
                "phase_id": rec["phase_id"],
                "phase_title": rec["phase_title"],
                "phase_type": rec["phase_type"],
                "speaker_id": senate_speaker(rec["chamber"], rec["speaker_id"], rec["senato_id"]),
                "speaker_name": p.get("cognomeNome"),
                "url": p.get("url"),
                "text": text,
            })
        self.write("speeches", records)
        print(f"  speech text coverage: {self.text_coverage.as_dict()}")

    def export_votes(self):
        records = []
        for rec in self.rows(
            "MATCH (s:Session)-[:HAS_VOTE]->(v:Vote) "
            "OPTIONAL MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct) "
            "RETURN s.id AS session_id, s.chamber AS chamber, s.date AS date, v, "
            "collect(a.uri) AS act_uris ORDER BY s.date, v.number"
        ):
            p = dict(rec["v"])
            records.append({
                "vote_id": p["id"],
                "chamber": rec["chamber"],
                "session_id": rec["session_id"],
                "date": iso(rec["date"]),
                "number": p.get("number"),
                "subject": p.get("subject"),
                "description": p.get("description"),
                "vote_type": p.get("type"),
                "outcome": p.get("outcome"),
                "voters": p.get("voters"),
                "present": p.get("present"),
                "in_favor": p.get("inFavor"),
                "against": p.get("against"),
                "abstained": p.get("abstained"),
                "on_mission": p.get("onMission"),
                "majority": p.get("majority"),
                "secret_vote": p.get("secretVote"),
                "final_vote": p.get("finalVote"),
                "confidence_vote": p.get("confidenceVote"),
                "act_uris": rec["act_uris"] or [],
            })
        self.write("votes", records)

    def export_individual_votes(self):
        records = []
        for rec in self.rows(
            "MATCH (p:Person)-[:VOTED]->(iv:IndividualVote)-[:ON_VOTE]->(v:Vote) "
            "RETURN v.id AS vote_id, p.id AS person_id, iv.outcome AS outcome"
        ):
            records.append({
                "vote_id": rec["vote_id"],
                "person_id": rec["person_id"],
                "outcome": rec["outcome"],
            })
            if len(records) % 1_000_000 == 0:
                print(f"  {len(records):,} individual votes...")
        self.write("individual_votes", records)

    def export_acts(self):
        records = []
        for rec in self.rows("MATCH (n:ParliamentaryAct) RETURN n"):
            p = dict(rec["n"])
            records.append({
                "act_uri": p.get("uri"),
                "chamber": source_chamber(p),
                "number": s(p.get("number")),
                "act_type": p.get("type"),
                "kind": p.get("kind"),
                "title": p.get("title"),
                "description": p.get("description"),
                "presentation_date": iso(p.get("presentation_date")),
                "recipient": p.get("recipient"),
                "is_placeholder": bool(p.get("isPlaceholder")),
            })
        self.write("acts", records)

    def export_act_subjects(self):
        records = []
        for rec in self.rows(
            "MATCH (a:ParliamentaryAct)-[:HAS_SUBJECT]->(c:EurovocConcept) "
            "RETURN a.uri AS act_uri, c.uri AS eurovoc_uri, c.label_it AS label"
        ):
            records.append({
                "act_uri": rec["act_uri"],
                "eurovoc_uri": rec["eurovoc_uri"],
                "eurovoc_label_it": rec["label"],
            })
        self.write("act_subjects", records)

    def export_speech_references(self):
        records = []
        for rel, ref_type in [("MENTIONS", "mentions_person"), ("CITES", "cites_act")]:
            for rec in self.rows(
                f"MATCH (sp:Speech)-[:HAS_CHUNK]->(:Chunk)-[:{rel}]->(t) "
                "RETURN DISTINCT sp.id AS speech_id, "
                "coalesce(t.id, t.uri) AS target_id"
            ):
                records.append({
                    "speech_id": rec["speech_id"],
                    "ref_type": ref_type,
                    "target_id": rec["target_id"],
                })
        self.write("speech_references", records)


def main():
    parser = argparse.ArgumentParser(
        description="Export the ParliamentRAG KG as Parquet tables for Hugging Face")
    parser.add_argument("--out", default=str(REPO_ROOT / "dumps" / "hf"),
                        help="output directory (default: dumps/hf)")
    parser.add_argument("--skip-individual-votes", action="store_true",
                        help="skip the 6.9M-row individual_votes table")
    parser.add_argument("--card-only", action="store_true",
                        help="only regenerate README.md from hf_dataset_card.md")
    parser.add_argument("--archive-url", default=None,
                        help="Postgres text archive for speeches stripped from the "
                             "graph (default: ARCHIVE_URL)")
    parser.add_argument("--allow-missing-text", action="store_true",
                        help="write the tables even if a chamber is mostly without text")
    parser.add_argument("--repo", default=os.environ.get("HF_DATASET_REPO", DEFAULT_REPO),
                        help="dataset id used in the card examples (default: "
                             "HF_DATASET_REPO or %(default)s)")
    args = parser.parse_args()

    load_dotenv(REPO_ROOT / ".env")
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        sys.exit("NEO4J_PASSWORD not set (checked environment and repo-root .env)")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    archive_texts = {}
    if not args.card_only:
        archive_texts = load_speech_texts(archive_url_from_env(args.archive_url))

    driver = GraphDatabase.driver(uri, auth=(user, password))
    exporter = HfExporter(driver, out_dir, archive_texts)
    started = time.time()
    try:
        if not args.card_only:
            print("Exporting tables...")
            exporter.export_speeches()
            broken = exporter.text_coverage.broken_chambers()
            if broken and not args.allow_missing_text:
                sys.exit(f"speech text missing for {broken}: pass --archive-url (or set "
                         "ARCHIVE_URL) to read it from the Postgres archive")
            exporter.export_persons()
            exporter.export_organizations()
            exporter.export_memberships()
            exporter.export_sessions()
            exporter.export_debates()
            exporter.export_votes()
            exporter.export_acts()
            exporter.export_act_subjects()
            exporter.export_speech_references()
            if not args.skip_individual_votes:
                exporter.export_individual_votes()

            meta_path = out_dir / "export_meta.json"
            meta_path.write_text(json.dumps({
                "row_counts": exporter.row_counts,
                "speech_text": exporter.text_coverage.as_dict(),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }, indent=2) + "\n")

        print("Rendering dataset card...")
        render_card(driver, out_dir, args.repo)
    finally:
        driver.close()
    print(f"Done in {time.time() - started:.0f}s")


if __name__ == "__main__":
    main()
