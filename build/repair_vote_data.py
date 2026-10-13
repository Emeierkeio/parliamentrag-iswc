#!/usr/bin/env python3
"""
One-shot repair delle votazioni Camera (leg. 19) già presenti in Neo4j.

Riparazioni indipendenti, attivabili singolarmente:

  --abstentions   Gli IndividualVote degli astenuti sono salvati come "absent":
                  la vecchia OUTCOME_MAP cercava "Astenuto" ma il valore reale
                  di dc:type su dati.camera.it è "Astensione", quindi tutte le
                  astensioni cadevano nel fallback. Rilegge da SPARQL le coppie
                  (deputato, votazione) con dc:type "Astensione" e setta
                  outcome='abstain' sui nodi corrispondenti.

  --secret        Nelle votazioni segrete dati.camera.it pubblica solo la
                  partecipazione (dc:type "Ha votato"), che la vecchia
                  OUTCOME_MAP salvava come "absent": rilegge da SPARQL quelle
                  coppie e setta outcome='secret' (52 votazioni XIX, 2026-10-12).

  --subjects      Backfill di subject/description/finalVote/confidenceVote e
                  della relazione (Vote)-[:ON_ACT]->(ParliamentaryAct) per
                  tutte le votazioni leg 19. Le votazioni delle sedute 1-349
                  (fonte XML) hanno oggetti criptici ("EM. 9.1"); il label
                  SPARQL ("Votazione Emendamento 1.104 PDL n. 0080") è
                  canonico e vince sempre quando presente.

  --government    Backfill dei voti individuali dei ministri-deputati
                  (GovernmentMember con deputy_card): l'ingest storico
                  matchava solo i Deputy e perdeva i loro voti.

Senza flag le esegue tutte. Idempotente: rilanciarlo non cambia il risultato.

Uso:
  python build/repair_vote_data.py --neo4j-uri bolt://localhost:7691  # staging
  python build/repair_vote_data.py --neo4j-uri bolt://localhost:7690  # prod (tunnel)
"""

import argparse
import logging
import os
import re
import sys

from neo4j import GraphDatabase

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sparql_ingester import (  # noqa: E402
    _DEPUTATO_URI_RE,
    SparqlIngester,
    _sparql_get,
    clean_sparql_text,
    parse_votazione_uri,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

LEG_URI = "http://dati.camera.it/ocd/legislatura.rdf/repubblica_19"
SPARQL_PAGE = 10_000
NEO4J_BATCH = 1_000


def _count(where_block: str, key_var: str) -> int:
    """COUNT(DISTINCT ?key_var) del blocco WHERE dato.

    DISTINCT è obbligatorio: le triple replicate su più grafi gonfiano
    COUNT(*) (es. 38599 vs 19237 votazioni reali).
    """
    rows = _sparql_get(
        "PREFIX ocd: <http://dati.camera.it/ocd/>\n"
        "PREFIX dc: <http://purl.org/dc/elements/1.1/>\n"
        f"SELECT (COUNT(DISTINCT ?{key_var}) AS ?n) WHERE {{ {where_block} }}"
    )
    return int(rows[0]["n"]["value"]) if rows else -1


def _paged(query_tmpl: str, key_var: str) -> list[dict]:
    """SELECT paginata via keyset sul valore di ?key_var (URI crescente).

    Virtuoso risponde 500 sugli OFFSET grandi, quindi si pagina con
    FILTER (STR(?k) > "ultimo visto"). Una pagina fallita appare come pagina
    vuota (_sparql_get non rilancia): il chiamante DEVE confrontare il totale
    con un COUNT e fermarsi se mancano righe.
    """
    rows: list[dict] = []
    last = ""
    while True:
        key_filter = f'FILTER (STR(?{key_var}) > "{last}")' if last else ""
        bindings = _sparql_get(query_tmpl.format(limit=SPARQL_PAGE, key_filter=key_filter))
        rows.extend(bindings)
        logger.info("  SPARQL keyset page da %r -> %d rows (tot %d)",
                    last[-40:], len(bindings), len(rows))
        if len(bindings) < SPARQL_PAGE:
            return rows
        last = bindings[-1][key_var]["value"]


def repair_abstentions(driver) -> None:
    logger.info("Fetch astensioni leg 19 da SPARQL (~483k righe)...")
    where = """
  ?voto a ocd:voto ;
        dc:type "Astensione" ;
        ocd:rif_votazione ?votazione ;
        ocd:rif_deputato ?deputato .
  ?votazione ocd:rif_leg <""" + LEG_URI + "> ."
    expected = _count(where, key_var="voto")
    rows = _paged("""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT DISTINCT ?voto ?deputato ?votazione WHERE {{""" + where + """
  {key_filter}
}}
ORDER BY STR(?voto)
LIMIT {limit}
""", key_var="voto")
    if len(rows) < expected:
        raise RuntimeError(
            f"Fetch astensioni incompleto: {len(rows)}/{expected} righe — "
            "pagina SPARQL fallita, nessuna scrittura eseguita."
        )

    ids = set()
    for row in rows:
        dep = _DEPUTATO_URI_RE.search(row.get("deputato", {}).get("value", ""))
        sed, vot = parse_votazione_uri(row.get("votazione", {}).get("value", ""))
        if dep and sed is not None:
            ids.add(f"iv_camera_{dep.group(1)}_{sed}_{vot}")
    logger.info("Astensioni: %d righe SPARQL -> %d id univoci", len(rows), len(ids))

    id_list = sorted(ids)
    updated = 0
    with driver.session() as session:
        for i in range(0, len(id_list), NEO4J_BATCH):
            chunk = id_list[i:i + NEO4J_BATCH]
            rec = session.run(
                """
                UNWIND $ids AS ivId
                MATCH (iv:IndividualVote {id: ivId})
                SET iv.outcome = 'abstain'
                RETURN count(iv) AS n
                """,
                ids=chunk,
            ).single()
            updated += rec["n"] if rec else 0
    missing = len(id_list) - updated
    logger.info("Astensioni riparate: %d aggiornate, %d senza nodo in DB "
                "(deputati mai matchati in ingest: atteso)", updated, missing)


def repair_secret_ballots(driver) -> None:
    logger.info("Fetch partecipazioni a voti segreti leg 19 da SPARQL...")
    where = """
  ?voto a ocd:voto ;
        dc:type "Ha votato" ;
        ocd:rif_votazione ?votazione ;
        ocd:rif_deputato ?deputato .
  ?votazione ocd:rif_leg <""" + LEG_URI + "> ."
    expected = _count(where, key_var="voto")
    rows = _paged("""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT DISTINCT ?voto ?deputato ?votazione WHERE {{""" + where + """
  {key_filter}
}}
ORDER BY STR(?voto)
LIMIT {limit}
""", key_var="voto")
    if len(rows) < expected:
        raise RuntimeError(
            f"Fetch voti segreti incompleto: {len(rows)}/{expected} righe — "
            "pagina SPARQL fallita, nessuna scrittura eseguita."
        )

    ids = set()
    for row in rows:
        dep = _DEPUTATO_URI_RE.search(row.get("deputato", {}).get("value", ""))
        sed, vot = parse_votazione_uri(row.get("votazione", {}).get("value", ""))
        if dep and sed is not None:
            ids.add(f"iv_camera_{dep.group(1)}_{sed}_{vot}")
    logger.info("Voti segreti: %d righe SPARQL -> %d id univoci", len(rows), len(ids))

    id_list = sorted(ids)
    updated = 0
    with driver.session() as session:
        for i in range(0, len(id_list), NEO4J_BATCH):
            rec = session.run(
                """
                UNWIND $ids AS ivId
                MATCH (iv:IndividualVote {id: ivId})
                SET iv.outcome = 'secret'
                RETURN count(iv) AS n
                """,
                ids=id_list[i:i + NEO4J_BATCH],
            ).single()
            updated += rec["n"] if rec else 0
    logger.info("Voti segreti riparati: %d aggiornati, %d senza nodo in DB",
                updated, len(id_list) - updated)


def repair_subjects(driver) -> None:
    logger.info("Fetch metadati votazioni leg 19 da SPARQL...")
    expected = _count(
        "?votazione a <http://dati.camera.it/ocd/votazione> ; "
        f"ocd:rif_leg <{LEG_URI}> .",
        key_var="votazione",
    )
    rows = _paged("""
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX dc: <http://purl.org/dc/elements/1.1/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?votazione ?label ?descrizione ?finale ?fiducia ?segreta ?atto ?attoTitolo ?aic ?aicTitolo WHERE {{
  ?votazione a ocd:votazione ;
             ocd:rif_leg <""" + LEG_URI + """> .
  OPTIONAL {{ ?votazione rdfs:label ?label . }}
  OPTIONAL {{ ?votazione dc:description ?descrizione . }}
  OPTIONAL {{ ?votazione ocd:votazioneFinale ?finale . }}
  OPTIONAL {{ ?votazione ocd:richiestaFiducia ?fiducia . }}
  OPTIONAL {{ ?votazione ocd:votazioneSegreta ?segreta . }}
  OPTIONAL {{ ?votazione ocd:rif_attoCamera ?atto .
              OPTIONAL {{ ?atto dc:title ?attoTitolo . }} }}
  OPTIONAL {{ ?votazione ocd:rif_aic ?aic .
              OPTIONAL {{ ?aic dc:title ?aicTitolo . }} }}
  {key_filter}
}}
ORDER BY STR(?votazione)
LIMIT {limit}
""", key_var="votazione")

    # Una riga per votazione (le OPTIONAL possono duplicare).
    act_num_re = re.compile(r"\b(?:TU\s+)?(?:PDL|DDL)(?:\s+COST)?\b\D{0,8}?0*(\d+)")
    by_vote: dict[tuple[int, int], dict] = {}
    for row in rows:
        sed, vot = parse_votazione_uri(row.get("votazione", {}).get("value", ""))
        if sed is None or (sed, vot) in by_vote:
            continue
        by_vote[(sed, vot)] = {
            "sessionNumber": sed,
            "voteNumber": vot,
            "label": clean_sparql_text(row.get("label", {}).get("value")),
            "description": clean_sparql_text(row.get("descrizione", {}).get("value")),
            "finalVote": row.get("finale", {}).get("value") == "1",
            "confidenceVote": row.get("fiducia", {}).get("value") == "1",
            "secretVote": row.get("segreta", {}).get("value") == "1",
            "actUri": row.get("atto", {}).get("value"),
            "actTitle": clean_sparql_text(row.get("attoTitolo", {}).get("value")),
            "aicUri": row.get("aic", {}).get("value"),
            "aicTitle": clean_sparql_text(row.get("aicTitolo", {}).get("value")),
        }
        # Sedute recenti: niente rif_attoCamera, ma la descrizione porta il
        # numero dell'atto ("PDL 2822-A E ABB - VOTO FINALE") e l'URI
        # attocamera è deterministico.
        rec = by_vote[(sed, vot)]
        if not rec["actUri"]:
            m = act_num_re.search(f"{rec['label'] or ''} {rec['description'] or ''}")
            if m:
                rec["actUri"] = f"http://dati.camera.it/ocd/attocamera.rdf/ac19_{m.group(1)}"
    batch = list(by_vote.values())
    logger.info("Votazioni: %d righe SPARQL -> %d votazioni univoche", len(rows), len(batch))
    if len(batch) < expected:
        raise RuntimeError(
            f"Fetch votazioni incompleto: {len(batch)}/{expected} — "
            "pagina SPARQL fallita, nessuna scrittura eseguita."
        )

    updated = 0
    with driver.session() as session:
        for i in range(0, len(batch), NEO4J_BATCH):
            chunk = batch[i:i + NEO4J_BATCH]
            rec = session.run(
                """
                UNWIND $batch AS row
                MATCH (s:Session {number: row.sessionNumber})-[:HAS_VOTE]->(v:Vote {number: row.voteNumber})
                WHERE coalesce(s.chamber, 'camera') = 'camera' AND s.legislature = 19
                SET v.subject = coalesce(row.label, v.subject),
                    v.description = row.description,
                    v.finalVote = row.finalVote,
                    v.confidenceVote = row.confidenceVote,
                    v.secretVote = row.secretVote
                FOREACH (_ IN CASE WHEN row.actUri IS NULL THEN [] ELSE [1] END |
                  MERGE (a:ParliamentaryAct {uri: row.actUri})
                  SET a.title = coalesce(a.title, row.actTitle)
                  MERGE (v)-[:ON_ACT]->(a)
                )
                FOREACH (_ IN CASE WHEN row.aicUri IS NULL THEN [] ELSE [1] END |
                  MERGE (b:ParliamentaryAct {uri: row.aicUri})
                  SET b.title = coalesce(b.title, row.aicTitle)
                  MERGE (v)-[:ON_ACT]->(b)
                )
                RETURN count(v) AS n
                """,
                batch=chunk,
            ).single()
            updated += rec["n"] if rec else 0
    logger.info("Votazioni aggiornate: %d/%d (le mancanti non hanno nodo Vote in DB)",
                updated, len(batch))

    # Arricchimento degli atti votati: titolo (quando manca) e PDF del testo
    # integrale. dc:relation sull'atto elenca gli stampati PDF; il codice più
    # alto nel nome file è la stampa più recente (es. la versione -A votata).
    act_uris = sorted({
        r["actUri"] for r in batch
        if r["actUri"] and "/attocamera.rdf/" in r["actUri"]
    })
    logger.info("Arricchimento %d atti votati (titolo + PDF testo integrale)...", len(act_uris))
    payload = []
    for i in range(0, len(act_uris), 60):
        values = " ".join(f"<{u}>" for u in act_uris[i:i + 60])
        rows2 = _sparql_get(f"""
PREFIX dc: <http://purl.org/dc/elements/1.1/>
SELECT ?atto ?titolo ?rel WHERE {{
  VALUES ?atto {{ {values} }}
  OPTIONAL {{ ?atto dc:title ?titolo . }}
  OPTIONAL {{ ?atto dc:relation ?rel . FILTER(STRENDS(STR(?rel), ".pdf")) }}
}}""")
        by_act: dict[str, dict] = {}
        for r in rows2:
            uri = r["atto"]["value"]
            e = by_act.setdefault(uri, {"uri": uri, "title": None, "pdfs": set()})
            if "titolo" in r and not e["title"]:
                e["title"] = clean_sparql_text(r["titolo"]["value"])
            if "rel" in r:
                e["pdfs"].add(r["rel"]["value"])
        for e in by_act.values():
            latest = max(e["pdfs"], key=lambda u: int((re.search(r"(\d+)\.pdf$", u) or [0, "-1"])[1])) if e["pdfs"] else None
            payload.append({"uri": e["uri"], "title": e["title"], "pdf": latest})
    with driver.session() as session:
        for i in range(0, len(payload), NEO4J_BATCH):
            session.run(
                """
                UNWIND $batch AS row
                MATCH (a:ParliamentaryAct {uri: row.uri})
                SET a.title = coalesce(a.title, row.title),
                    a.textPdfUrl = coalesce(row.pdf, a.textPdfUrl)
                """,
                batch=payload[i:i + NEO4J_BATCH],
            )
    logger.info("Atti arricchiti: %d (con PDF: %d)",
                len(payload), sum(1 for p in payload if p["pdf"]))


def repair_government_votes(driver, legislature: int = 19) -> None:
    """Backfill dei voti individuali dei ministri-deputati.

    I membri del Governo che siedono anche alla Camera (Tajani, Giorgetti, ...)
    esistono nel grafo solo come GovernmentMember: l'ingest storico matchava
    solo i Deputy e i loro voti si perdevano (es. 150 favorevoli in emiciclo
    contro 153 nell'aggregato ufficiale). Riusa il flusso per-deputato
    dell'ingester, che ora accetta anche i GovernmentMember.
    """
    ingester = SparqlIngester(driver)
    gov = ingester._fetch_government_deputies()
    logger.info("Ministri-deputati con deputy_card: %d", len(gov))
    total_written = 0
    for i, g in enumerate(gov, 1):
        uri = f"http://dati.camera.it/ocd/deputato.rdf/d{g['person_id']}_{legislature}"
        written, skipped = ingester._ingest_deputy_votes(
            g["id"], g["person_id"], uri, chamber="camera", legislature=legislature
        )
        total_written += written
        logger.info("  [%d/%d] %s (p%s): %d voti scritti, %d skip",
                    i, len(gov), g["id"], g["person_id"], written, skipped)
    logger.info("Backfill ministri-deputati completo: %d voti scritti", total_written)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--neo4j-uri", default="bolt://localhost:7691")
    parser.add_argument("--neo4j-user", default="neo4j")
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", ""))
    parser.add_argument("--abstentions", action="store_true")
    parser.add_argument("--secret", action="store_true")
    parser.add_argument("--subjects", action="store_true")
    parser.add_argument("--government", action="store_true")
    args = parser.parse_args()

    run_all = not (args.abstentions or args.secret or args.subjects or args.government)
    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    try:
        driver.verify_connectivity()
        if args.abstentions or run_all:
            repair_abstentions(driver)
        if args.secret or run_all:
            repair_secret_ballots(driver)
        if args.subjects or run_all:
            repair_subjects(driver)
        if args.government or run_all:
            repair_government_votes(driver)
    finally:
        driver.close()


if __name__ == "__main__":
    main()
