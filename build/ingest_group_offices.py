#!/usr/bin/env python3
"""Group offices (direttivo) onto MEMBER_OF_GROUP.role, Camera or Senato.

Camera: the OCD graph exposes office nodes linked to the parliamentary group
via ocd:rif_gruppoParlamentare, with an rdfs:label of the form
"VICEPRESIDENTE del gruppo LEGA - SALVINI PREMIER, ALBERTO BAGNAI
(18.10.2022-15.09.2026)". No structured role property exists, so role,
person and period are parsed from the label.

Senato (--chamber senato): dati.senato.it puts the office on the group
membership itself (ocd:aderisce -> osr:carica: "Presidente", "Vicepresidente
Vicario", "Membro", ...), with the senator's URI.

Only offices without an end date are applied, on the ACTIVE membership rel
of that chamber; the chamber's existing role values are replaced
(idempotent).
"""
import argparse
import csv
import json
import logging
import os
import re
import sys
import urllib.parse
import urllib.request

from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("group_offices")

SPARQL_ENDPOINT = "https://dati.camera.it/sparql"

ROLE_MAP = {
    "PRESIDENTE": "president",
    "VICEPRESIDENTE": "vice_president",
    "TESORIERE": "treasurer",
    "SEGRETARIO": "secretary",
}

QUERY = """
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?lab WHERE {
  # rif_gruppoParlamentare also hangs off ~14.4M ocd:voto nodes (2026-09-30):
  # without the class the REGEX scans them all and the endpoint returns 504
  ?u a ocd:incarico ; ocd:rif_gruppoParlamentare ?g ; rdfs:label ?lab .
  ?g ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_%(leg)s> .
  FILTER(REGEX(STR(?lab), "^(PRESIDENTE|VICEPRESIDENTE|TESORIERE|SEGRETARIO) del gruppo"))
}
"""

# "RUOLO del gruppo NOME GRUPPO, NOME PERSONA (dd.mm.yyyy[-dd.mm.yyyy])"
LABEL_RE = re.compile(
    r"^(PRESIDENTE|VICEPRESIDENTE|TESORIERE|SEGRETARIO) del gruppo (.+), ([^,(]+) "
    r"\((\d{2}\.\d{2}\.\d{4})(?:-(\d{2}\.\d{2}\.\d{4}))?\)$"
)


def sparql(query: str) -> list[dict]:
    url = SPARQL_ENDPOINT + "?" + urllib.parse.urlencode(
        {"query": query, "format": "application/sparql-results+json"}
    )
    req = urllib.request.Request(
        url, headers={"User-Agent": "ParliamentRAG/1.0", "Accept": "application/sparql-results+json"}
    )
    return json.loads(urllib.request.urlopen(req, timeout=120).read())["results"]["bindings"]


SENATE_ROLES = {
    "Presidente": "president",
    "Vicepresidente Vicario": "vice_president",
    "Vicepresidente": "vice_president",
    "Segretario": "secretary",
    "Segretario d'Aula": "secretary",
    "Tesoriere": "treasurer",
}
# MEMBER_OF_GROUP.role holds one office: a senator who is both Vicepresidente
# and Tesoriere (Germanà, Lega, 2025) keeps the one that weighs more in the
# authority score.
ROLE_RANK = ["president", "vice_president", "secretary", "treasurer"]

SENATE_QUERY = """
SELECT DISTINCT ?senatore ?gruppo ?carica WHERE {
  ?senatore <http://dati.camera.it/ocd/aderisce> ?a .
  ?a <http://dati.senato.it/osr/legislatura> %(leg)d ; <http://dati.senato.it/osr/gruppo> ?gruppo ;
     <http://dati.senato.it/osr/carica> ?carica .
  OPTIONAL { ?a <http://dati.senato.it/osr/fine> ?fine }
  FILTER(!bound(?fine))
}
"""


def senate_offices(rows: list[dict]) -> dict[str, dict]:
    """{senator URI: {"role", "group"}}, the highest current office of each senator."""
    out: dict[str, dict] = {}
    for r in rows:
        role = SENATE_ROLES.get(r["carica"].strip())
        if role is None:
            continue
        held = out.get(r["senatore"])
        if held is None or ROLE_RANK.index(role) < ROLE_RANK.index(held["role"]):
            out[r["senatore"]] = {"role": role, "group": r["gruppo"]}
    return out


def senate_group_names(path: str) -> dict[str, str]:
    """Senate group URI -> the group's current name, as the graph keeps it
    (data/senatori_{roman}_gruppi.csv, download_senators_csv.py)."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {r["gruppoUri"]: r.get("gruppoAttuale") or r["gruppoLabel"] for r in csv.DictReader(f)}


def apply_senate(session, offices: dict[str, dict], names: dict[str, str]) -> tuple[int, int]:
    """Roles on the senators' open memberships, when they sit in the office's group."""
    session.run("MATCH (:Person)-[m:MEMBER_OF_GROUP {chamber: 'senato'}]->() REMOVE m.role")
    rows = [{"sen": sen, "role": o["role"], "group": names.get(o["group"])} for sen, o in offices.items()]
    applied = set(session.run("""
        UNWIND $rows AS row
        MATCH (p:Person {senato_id: row.sen})-[m:MEMBER_OF_GROUP {chamber: 'senato'}]->(g:ParliamentaryGroup)
        WHERE m.end_date IS NULL AND (row.group IS NULL OR g.name = row.group)
        SET m.role = row.role
        RETURN collect(row.sen) AS sens
    """, rows=rows).single()["sens"])
    for row in rows:
        if row["sen"] not in applied:
            logger.warning("Nessun match per %s (%s, %s)", row["sen"], row["role"], row["group"])
    return len(applied), len(rows) - len(applied)


def senate(args, driver) -> int:
    from senate_sparql_ingester import SenateEndpointBlocked, SenateRequestFailed, _senato_sparql_get

    try:
        raw = _senato_sparql_get(SENATE_QUERY % {"leg": args.legislature}, strict=True)
    except (SenateEndpointBlocked, SenateRequestFailed) as exc:
        logger.warning("dati.senato.it non risponde: %s", exc)
        return 3
    offices = senate_offices([{k: v["value"] for k, v in r.items()} for r in raw])
    logger.info("Cariche correnti nei gruppi del Senato: %d", len(offices))
    roman = {18: "xviii", 19: "xix"}.get(args.legislature, f"leg{args.legislature}")
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    names = senate_group_names(os.path.join(repo, "data", f"senatori_{roman}_gruppi.csv"))
    with driver.session() as s:
        applied, missed = apply_senate(s, offices, names)
    logger.info("Applicate %d cariche, %d senza match.", applied, missed)
    return 0


def camera(args, driver) -> int:
    rows = sparql(QUERY % {"leg": args.legislature})
    offices = []
    for r in rows:
        lab = r["lab"]["value"].strip()
        m = LABEL_RE.match(lab)
        if not m:
            logger.warning("Label non riconosciuta: %s", lab)
            continue
        role_it, group, person, start, end = m.groups()
        if end:  # only current officeholders end up on the active rel
            continue
        offices.append({
            "role": ROLE_MAP[role_it],
            "group": group.strip().upper(),
            "person": person.strip().upper(),
        })
    logger.info("Cariche correnti dal SPARQL: %d", len(offices))

    applied = missed = 0
    with driver.session() as s:
        # Wipe then reapply: officeholders change, stale roles must not survive
        s.run("MATCH (:Person)-[m:MEMBER_OF_GROUP]->() WHERE coalesce(m.chamber, '') <> 'senato' "
              "REMOVE m.role")
        for o in offices:
            res = s.run(
                """
                MATCH (d:Person)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
                WHERE m.end_date IS NULL AND coalesce(m.chamber, '') <> 'senato'
                  AND (toUpper(d.first_name + ' ' + d.last_name) = $person
                       OR toUpper(d.last_name + ' ' + d.first_name) = $person)
                  AND (toUpper(g.name) CONTAINS $group_key OR $group_key CONTAINS toUpper(g.name))
                SET m.role = $role
                RETURN count(m) AS n
                """,
                person=o["person"],
                # first token of the group name survives renames (AZIONE-, LEGA...)
                group_key=o["group"].split(",")[0].split("(")[0].strip(),
                role=o["role"],
            ).single()["n"]
            if not res:
                # Renamed groups (Azione-IV -> Azione, IV-Il Centro -> Casa
                # Riformista): the source keeps the office on the old name,
                # the officeholder presides the successor group they sit in
                res = s.run(
                    """
                    MATCH (d:Person)-[m:MEMBER_OF_GROUP]->(:ParliamentaryGroup)
                    WHERE m.end_date IS NULL AND coalesce(m.chamber, '') <> 'senato'
                      AND (toUpper(d.first_name + ' ' + d.last_name) = $person
                           OR toUpper(d.last_name + ' ' + d.first_name) = $person)
                    SET m.role = $role
                    RETURN count(m) AS n
                    """,
                    person=o["person"], role=o["role"],
                ).single()["n"]
            if res:
                applied += 1
            else:
                missed += 1
                logger.warning("Nessun match per %s (%s, %s)", o["person"], o["role"], o["group"][:40])
    logger.info("Applicate %d cariche, %d senza match.", applied, missed)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default="neo4j")
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--chamber", choices=["camera", "senato"], default="camera")
    args = ap.parse_args()

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        return senate(args, driver) if args.chamber == "senato" else camera(args, driver)
    finally:
        driver.close()


if __name__ == "__main__":
    sys.exit(main())
