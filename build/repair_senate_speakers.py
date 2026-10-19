#!/usr/bin/env python3
"""
Re-derives the speaker of Senate speeches from the AKN files.

The by attribute of an Akoma Ntoso speech sometimes names someone else than
the surname the record prints before it (seduta 413 of the XIX: by="#p25407",
Matteo Salvini, on "SALVITTI, relatore"). senate_parser.py now trusts the
printed surname; this script re-parses every sitting, and for the speeches
whose deputatoId or cognomeNome differ it updates both, moves SPOKEN_BY to
the senator the URI names and re-annotates the government role of the
chamber's speeches. Speech ids do not change.

A speaker summary (SpeakerDebateSummary) of the old speaker on that debate is
removed when no other speech of his remains in the debate: its text describes
words he did not say. The summary of the new speaker is left as it is and
listed, since rewriting it takes a model call (generate_summaries.py --date).

Dry run by default; --apply writes. Idempotent: a second run finds nothing.

    build/repair_senate_speakers.py --neo4j-uri bolt://localhost:7692
    build/repair_senate_speakers.py --neo4j-uri bolt://localhost:7690 --apply
"""

from __future__ import annotations

import argparse
import glob
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senate_parser import SenateStenograficoParser  # noqa: E402

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
XML_DIR = os.path.join(REPO, "data", "senate_xml")

CURRENT = """
UNWIND $ids AS sid
MATCH (sp:Speech {id: sid})
OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(p:Person)
RETURN sp.id AS id, sp.deputatoId AS dep, sp.cognomeNome AS name, collect(p.id) AS people
"""

TARGETS = """
UNWIND $uris AS uri
MATCH (p:Person {senato_id: uri})
RETURN uri, collect(p.id) AS people
"""

# Summaries of the old speaker on the speech's debate with no other speech
# of his left there once the speech moves.
STALE_SUMMARIES = """
UNWIND $rows AS r
MATCH (d:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech {id: r.id})
MATCH (old:Person {id: r.old})-[:HAS_DEBATE_SUMMARY]->(sds:SpeakerDebateSummary {debateId: d.id})
WHERE NOT EXISTS {
  MATCH (d)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(other:Speech)-[:SPOKEN_BY]->(old)
  WHERE NOT other.id IN $moved
}
RETURN DISTINCT sds.id AS id, sds.summaryIt AS text
"""

NEW_SPEAKER_SUMMARIES = """
UNWIND $rows AS r
MATCH (d:Debate)-[:HAS_PHASE]->(:Phase)-[:CONTAINS_SPEECH]->(sp:Speech {id: r.id})
MATCH (new:Person {id: r.new})-[:HAS_DEBATE_SUMMARY]->(sds:SpeakerDebateSummary {debateId: d.id})
RETURN DISTINCT sds.id AS id, sds.speechCount AS speeches
"""

MOVE = """
UNWIND $rows AS r
MATCH (sp:Speech {id: r.id})
MATCH (new:Person {id: r.new})
SET sp.deputatoId = r.dep, sp.cognomeNome = r.name
WITH sp, new
OPTIONAL MATCH (sp)-[old:SPOKEN_BY]->(p) WHERE p <> new
DELETE old
WITH DISTINCT sp, new
MERGE (sp)-[:SPOKEN_BY]->(new)
RETURN count(sp) AS n
"""

DROP_SUMMARIES = """
UNWIND $ids AS sid
MATCH (sds:SpeakerDebateSummary {id: sid})
DETACH DELETE sds
RETURN count(*) AS n
"""


def parsed_speakers(xml_dir: str, legislature: int) -> dict[str, tuple]:
    """{speech id: (deputatoId, cognome_nome)} from the AKN files."""
    parser = SenateStenograficoParser(legislature=legislature)
    speakers: dict[str, tuple] = {}
    files = sorted(glob.glob(os.path.join(xml_dir, f"resaula_leg{legislature}_*.akn")))
    for path in files:
        try:
            parsed = parser.parse_xml_file(path)
        except Exception as exc:  # one broken file must not stop the others
            logger.warning("%s: %s", os.path.basename(path), exc)
            continue
        for sp in parsed["speeches"]:
            speakers[sp["id"]] = (sp["deputatoId"], sp["cognome_nome"])
    logger.info("%d AKN files, %d speeches", len(files), len(speakers))
    return speakers


def plan_changes(parsed: dict[str, tuple], current: list[dict], targets: dict[str, list]) -> tuple[list, list]:
    """Split the speeches whose speaker differs into (movable rows, rows to check by hand).

    A row is movable when the parsed deputatoId resolves to exactly one Person.
    """
    rows, manual = [], []
    for cur in current:
        dep, name = parsed[cur["id"]]
        if (cur["dep"], cur["name"]) == (dep, name):
            continue
        people = targets.get(dep, []) if dep else []
        row = {"id": cur["id"], "dep": dep, "name": name, "old_dep": cur["dep"], "old_name": cur["name"],
               "old": cur["people"][0] if len(cur["people"]) == 1 else None,
               "new": people[0] if len(people) == 1 else None}
        (rows if row["new"] else manual).append(row)
    return rows, manual


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    help="default: $NEO4J_PASSWORD")
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--xml-dir", default=XML_DIR)
    ap.add_argument("--apply", action="store_true", help="write the changes (default: dry run)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if not args.neo4j_password:
        sys.exit("NEO4J_PASSWORD is required")
    from neo4j import GraphDatabase

    parsed = parsed_speakers(args.xml_dir, args.legislature)
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session(default_access_mode="READ") as s:
        current = s.run(CURRENT, ids=list(parsed)).data()
        uris = sorted({d for d, _ in parsed.values() if d})
        targets = {r["uri"]: r["people"] for r in s.run(TARGETS, uris=uris)}
        rows, manual = plan_changes(parsed, current, targets)
        moved = [r["id"] for r in rows]
        stale = s.run(STALE_SUMMARIES, rows=rows, moved=moved).data()
        incomplete = s.run(NEW_SPEAKER_SUMMARIES, rows=rows).data()

    print(f"Speech nel grafo: {len(current)}/{len(parsed)}; oratore da cambiare: {len(rows)}, "
          f"da vedere a mano: {len(manual)}")
    for r in rows:
        print(f"  {r['id']}: {r['old_name']} [{r['old']}] -> {r['name']} [{r['new']}]")
    for r in manual:
        print(f"  A MANO {r['id']}: {r['old_name']} [{r['old_dep']}] -> {r['name']} [{r['dep']}]")
    print(f"Riassunti per oratore da togliere (oratore precedente): {len(stale)}")
    for r in stale:
        print(f"  {r['id']}: {r['text']}")
    print(f"Riassunti del nuovo oratore che non contano l'intervento spostato: {len(incomplete)}")
    for r in incomplete:
        print(f"  {r['id']} (speechCount {r['speeches']})")

    if not args.apply:
        print("Prova a secco: nessuna scrittura (--apply per scrivere).")
        driver.close()
        return 0
    if not rows:
        driver.close()
        return 0

    from db_builder import DatabaseBuilder

    with driver.session() as s:
        n = s.run(MOVE, rows=rows).single()["n"]
        dropped = s.run(DROP_SUMMARIES, ids=[r["id"] for r in stale]).single()["n"]
    print(f"Scritti: {n} Speech spostati, {dropped} riassunti tolti.")
    DatabaseBuilder(driver).annotate_speech_government_roles(args.legislature, "senato")
    driver.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
