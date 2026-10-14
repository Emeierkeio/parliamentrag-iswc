"""
ingest_misto_componenti.py — componenti politiche del Gruppo Misto (leg. 19).

Il Gruppo Misto contiene componenti politicamente OPPOSTE (es. +Europa e
Futuro Nazionale Vannacci): attribuire una posizione al "Misto" monolitico
è un errore di attribuzione. La Camera pubblica le componenti come
ocd:componenteGruppoMisto con adesioni datate (ocd:siComponeDi).

Schema scritto:
  (:MistoComponent {uri, name, short_name, start_date, end_date})
  (Deputy)-[:MEMBER_OF_COMPONENT {start_date, end_date}]->(:MistoComponent)

Mapping deputato→persona: deputato.rdf/d{N}_19 ↔ persona.rdf/p{N}
(stesso id numerico — i nostri Deputy.id sono le URI persona).

Idempotente (MERGE ovunque); pensato per girare in db-update-all.

Usage:
    NEO4J_URI=bolt://localhost:7692 python build/ingest_misto_componenti.py
"""

from __future__ import annotations

import logging
import os
import re
import sys

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

SPARQL_ENDPOINT = "https://dati.camera.it/sparql"
LEG_URI = "http://dati.camera.it/ocd/legislatura.rdf/repubblica_19"

QUERY = """
PREFIX ocd: <http://dati.camera.it/ocd/>
SELECT DISTINCT ?comp ?title ?short ?dep ?adInizio ?adFine
WHERE {
  ?comp a ocd:componenteGruppoMisto .
  ?comp ocd:rif_leg <LEG_URI> .
  ?comp <http://purl.org/dc/elements/1.1/title> ?title .
  OPTIONAL { ?comp <http://purl.org/dc/terms/alternative> ?short }
  ?comp ocd:siComponeDi ?ad .
  ?ad ocd:rif_deputato ?dep .
  OPTIONAL { ?ad ocd:startDate ?adInizio }
  OPTIONAL { ?ad ocd:endDate ?adFine }
}
""".replace("LEG_URI", LEG_URI)


def parse_ocd_date(value: str | None) -> str | None:
    """'20221019' → '2022-10-19' (ISO, castabile a date in Cypher)."""
    if not value or len(value) != 8 or not value.isdigit():
        return None
    return f"{value[:4]}-{value[4:6]}-{value[6:8]}"


_LOWER_WORDS = {
    "di", "del", "della", "dello", "dei", "degli", "delle", "e", "ed",
    "al", "allo", "alla", "ai", "agli", "alle", "da", "dal", "con", "per", "in",
}
_ACRONYMS = {"MAIE", "UDC", "USEI", "AVS", "PPE", "SVP"}


def display_case(name: str) -> str:
    """Titolo SPARQL (MAIUSCOLO) → display case coerente coi nomi dei gruppi.

    '+EUROPA - STATI UNITI D'EUROPA' → '+Europa - Stati Uniti d'Europa'
    'NOI MODERATI -MAIE'             → 'Noi Moderati - MAIE'
    """
    name = re.sub(r"\s*-\s*", " - ", name).strip()
    out = []
    for i, tok in enumerate(name.split()):
        if tok == "-":
            out.append(tok)
            continue
        if tok.upper().strip("+") in _ACRONYMS:
            out.append(tok.upper())
            continue
        low = tok.lower()
        m = re.match(r"^([dl]')(.+)$", low)  # d'europa → d'Europa
        if m:
            out.append(m.group(1) + m.group(2).capitalize())
            continue
        if i > 0 and low in _LOWER_WORDS:
            out.append(low)
            continue
        if low.startswith("+"):
            out.append("+" + low[1:].capitalize())
        else:
            out.append(low.capitalize())
    return " ".join(out)


def clean_name(title: str) -> str:
    """Titolo OCD → nome leggibile della componente.

    'MISTO-+EUROPA - STATI UNITI D'EUROPA (MISTO-+EU-SUEU) (19.10.2022'
    → '+Europa - Stati Uniti d'Europa' non serve: teniamo il maiuscolo
    originale, togliamo solo prefisso MISTO- e parentesi (sigle e date).
    """
    name = title
    # parentesi annidate: rimuovi ripetutamente le più interne
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"\([^()]*\)", "", name)
    # parentesi aperta non chiusa in coda (titoli troncati: '(19.10.2022')
    name = re.sub(r"\([^()]*$", "", name)
    if name.upper().startswith("MISTO-"):
        name = name[6:]
    name = re.sub(r"[\s\-–]+$", "", name).strip()
    return display_case(name)


def dep_to_persona(dep_uri: str) -> str | None:
    """deputato.rdf/d301531_19 → persona.rdf/p301531 (= Deputy.id)."""
    m = re.search(r"/deputato\.rdf/d(\d+)_\d+$", dep_uri)
    if not m:
        return None
    return f"http://dati.camera.it/ocd/persona.rdf/p{m.group(1)}"


def fetch_componenti() -> list[dict]:
    resp = requests.get(
        SPARQL_ENDPOINT,
        params={"query": QUERY},
        headers={"Accept": "application/sparql-results+json"},
        timeout=90,
    )
    resp.raise_for_status()
    rows = []
    for b in resp.json()["results"]["bindings"]:
        persona = dep_to_persona(b["dep"]["value"])
        if not persona:
            logger.warning("URI deputato non mappabile: %s", b["dep"]["value"])
            continue
        rows.append({
            "comp_uri": b["comp"]["value"],
            "name": clean_name(b["title"]["value"]),
            "short_name": (b.get("short") or {}).get("value", "").strip() or None,
            "deputy_id": persona,
            "start_date": parse_ocd_date((b.get("adInizio") or {}).get("value")),
            "end_date": parse_ocd_date((b.get("adFine") or {}).get("value")),
        })
    return rows


def ingest(rows: list[dict], driver) -> None:
    with driver.session() as s:
        s.run("""
            UNWIND $rows AS row
            MERGE (mc:MistoComponent {uri: row.comp_uri})
            SET mc.name = row.name,
                mc.short_name = row.short_name
            WITH mc, row
            MATCH (d:Deputy {id: row.deputy_id})
            MERGE (d)-[m:MEMBER_OF_COMPONENT {start_date: date(row.start_date)}]->(mc)
            SET m.end_date = CASE WHEN row.end_date IS NULL THEN NULL
                                  ELSE date(row.end_date) END
        """, rows=[r for r in rows if r["start_date"]])
        stats = s.run("""
            MATCH (mc:MistoComponent)
            OPTIONAL MATCH (d:Deputy)-[m:MEMBER_OF_COMPONENT]->(mc)
            RETURN mc.name AS name, count(m) AS adesioni
            ORDER BY name
        """).data()
    logger.info("Componenti nel grafo:")
    for r in stats:
        logger.info("  - %s: %d adesioni", r["name"], r["adesioni"])


def main() -> None:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j package not installed", file=sys.stderr)
        sys.exit(1)

    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7692")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD", "")

    rows = fetch_componenti()
    logger.info("Adesioni a componenti del Misto (leg 19): %d", len(rows))
    if not rows:
        logger.error("Nessuna adesione dallo SPARQL — endpoint giù o query rotta")
        sys.exit(1)

    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        ingest(rows, driver)
    finally:
        driver.close()
    logger.info("Done.")


if __name__ == "__main__":
    main()
