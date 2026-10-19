#!/usr/bin/env python3
"""
Schema v2 invariant validation suite (PLAN_db_schema_v2 §5).

Gate obbligatorio post-build: exit code 0 = tutti gli invarianti rispettati,
exit code 1 = build respinta (dettaglio dei fallimenti su stdout).

Usage:
    NEO4J_URI=bolt://localhost:7692 NEO4J_PASSWORD=... python build/validate_db.py
    # oppure con argomenti CLI:
    python build/validate_db.py --neo4j-uri bolt://localhost:7692 --neo4j-password ...
"""
import argparse
import os
import random
import sys

from neo4j import GraphDatabase

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"

# Pattern URI dei dataset LOD sorgente (C10)
URI_PATTERNS = {
    # Senate bills by their dati.senato.it URI; Senate control acts by
    # <assembly>:<term>:<type>:<key>, PLAN_data_platform 9.3 and decision D9.
    "ParliamentaryAct": ("uri", ("http://dati.camera.it/", "placeholder:",
                                 "http://dati.senato.it/ddl/", "senato:")),
    "EurovocConcept": ("uri", ("http://eurovoc.europa.eu/",)),
    "TeseoConcept": ("uri", ("http://dati.senato.it/teseo/",)),
}

EMBEDDING_PROPS = [
    ("Chunk", "embedding"),
    ("Speech", "text_embedding"),
    ("Deputy", "profession_embedding"),
    ("Deputy", "education_embedding"),
    ("Committee", "embedding"),
    ("ParliamentaryAct", "title_embedding"),
    ("ParliamentaryAct", "description_embedding"),
    ("EurovocConcept", "embedding"),
]

VECTOR_INDEXES = [
    "chunk_embedding_index",
    "act_description_embedding_index",
    "act_title_embedding_index",
]

DATE_PROPS = [
    ("Session", "date"),
    ("Deputy", "term_of_office_start"),
    ("ParliamentaryAct", "presentation_date"),
    ("Government", "start_date"),
]

# Proprietà v1 che NON devono esistere nello schema v2
FORBIDDEN_PROPS = [
    ("Session", "year"), ("Session", "month"), ("Session", "day"),
    ("Session", "complete_date"),
    ("Debate", "originalId"), ("Phase", "originalId"),
    ("Chunk", "start_char_raw"), ("Chunk", "end_char_raw"),
    ("Chunk", "char_count"), ("Speech", "char_count"),
    ("Speech", "preprocessed_text"),
    ("ParliamentaryAct", "eurovoc"), ("ParliamentaryAct", "eurovoc_embedding"),
    ("GovernmentMember", "is_government"),
    ("Deputy", "role_type"), ("Deputy", "committee_role"),
    ("GovernmentMember", "role_type"), ("GovernmentMember", "committee_role"),
]

# Label che non devono esistere (schema morto).
# NB: IndividualVote NON è qui — rettifica §2.4 del piano (2026-07-22): il
# modello IndividualVote/VOTED/ON_VOTE resta, la Fase 8+14 ci è costruita sopra.
FORBIDDEN_LABELS = ["AttoParlamentare", "Deputato",
                    "MembroGoverno", "GruppoParlamentare", "Commissione"]


class Validator:
    def __init__(self, uri, user, password):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.failures = 0
        self.warnings = 0

    def q(self, query, **params):
        with self.driver.session() as s:
            return [r.data() for r in s.run(query, **params)]

    def check(self, ok: bool, label: str, detail: str = "", warn_only: bool = False):
        if ok:
            print(f"  [{PASS}] {label}")
        elif warn_only:
            self.warnings += 1
            print(f"  [{WARN}] {label} — {detail}")
        else:
            self.failures += 1
            print(f"  [{FAIL}] {label} — {detail}")

    # ------------------------------------------------------------------

    def check_senate(self, n_sessions: int):
        print(f"\n[13] Senato ({n_sessions} sedute)")
        rows = self.q("""
            MATCH (s:Session {chamber: 'senato'})-[*1..3]->(sp:Speech)
            WITH DISTINCT sp WHERE NOT (sp)-[:SPOKEN_BY]->()
            RETURN count(sp) AS c
        """)
        self.check(rows[0]["c"] == 0, "tutti gli interventi del Senato hanno un oratore",
                   f"{rows[0]['c']} senza SPOKEN_BY")

        # The transcript names the speaker by senatore URI; a link to someone
        # with another senatore URI is a surname match gone wrong (13/10/2026:
        # Giorgia Meloni's speeches on senator Marco Meloni).
        rows = self.q("""
            MATCH (sp:Speech)-[:SPOKEN_BY]->(p:Person)
            WHERE sp.deputatoId STARTS WITH 'http://dati.senato.it/senatore/'
              AND p.senato_id IS NOT NULL AND p.senato_id <> sp.deputatoId
            RETURN count(sp) AS c, collect(DISTINCT p.last_name)[..5] AS chi
        """)
        self.check(rows[0]["c"] == 0, "interventi del Senato legati alla persona del resoconto",
                   f"{rows[0]['c']} legati a un'altra persona: {rows[0]['chi']}")

        rows = self.q("""
            MATCH (p:Person) WHERE any(m IN coalesce(p.mandates, []) WHERE m STARTS WITH 'senato_')
              AND NOT p:Senator
            RETURN count(p) AS c
        """)
        self.check(rows[0]["c"] == 0, "chi ha un mandato al Senato ha la label Senator",
                   f"{rows[0]['c']} senza")

        rows = self.q("""
            MATCH (p:Person)-[m:MEMBER_OF_GROUP {chamber: 'senato'}]->()
            WHERE m.end_date IS NULL
            WITH p, m.legislature AS leg, count(m) AS n WHERE n > 1
            RETURN p.last_name AS sen, leg, n LIMIT 10
        """)
        self.check(not rows, "0 senatori con più gruppi aperti nella stessa legislatura",
                   f"{rows}")

        # Gruppo Misto: each senator goes to their political component (AVS,
        # Azione, Avanti PSI), never to the whole Misto. Those without one
        # (senators for life) must at least be listed by the source page
        # (build/ingest_misto_senato.py): otherwise the ingest has not seen them.
        rows = self.q("""
            MATCH (p:Senator)-[m:MEMBER_OF_GROUP {chamber: 'senato'}]->(g:ParliamentaryGroup {name: 'Misto'})
            WHERE m.end_date IS NULL
            OPTIONAL MATCH (p)-[mc:MEMBER_OF_COMPONENT]->(:MistoComponent {chamber: 'senato'})
            WHERE mc.end_date IS NULL
            WITH p, count(mc) AS comps
            RETURN count(p) AS tot, sum(CASE WHEN comps > 0 THEN 1 ELSE 0 END) AS with_comp,
                   [x IN collect(CASE WHEN comps = 0 AND p.misto_page_seen IS NULL
                                      THEN p.last_name END) WHERE x IS NOT NULL] AS unseen,
                   [x IN collect(CASE WHEN comps = 0 AND p.misto_page_seen IS NOT NULL
                                      THEN p.last_name END) WHERE x IS NOT NULL] AS without
        """)
        r = rows[0]
        if r["tot"]:
            self.check(r["with_comp"] > 0 and not r["unseen"],
                       f"senatori del Misto con componente: {r['with_comp']}/{r['tot']}"
                       + (f" (senza componente per la fonte: {', '.join(sorted(r['without']))})"
                          if r["without"] else ""),
                       f"mai visti da build/ingest_misto_senato.py: {r['unseen']}" if r["unseen"]
                       else "nessuna componente: lanciare build/ingest_misto_senato.py")

        # Group offices from osr:carica (build/ingest_group_offices.py
        # --chamber senato): each group with members has its president.
        rows = self.q("""
            MATCH (:Person)-[m:MEMBER_OF_GROUP {chamber: 'senato'}]->(g:ParliamentaryGroup)
            WHERE m.end_date IS NULL
            WITH g, sum(CASE WHEN m.role = 'president' THEN 1 ELSE 0 END) AS presidents
            RETURN count(g) AS tot, sum(CASE WHEN presidents = 1 THEN 1 ELSE 0 END) AS ok,
                   [x IN collect(CASE WHEN presidents <> 1 THEN g.name END) WHERE x IS NOT NULL][..5] AS bad
        """)
        r = rows[0]
        self.check(r["ok"] == r["tot"], f"gruppi del Senato con un presidente {r['ok']}/{r['tot']}",
                   f"senza o con più di uno: {r['bad']} (build/ingest_group_offices.py --chamber senato)",
                   warn_only=True)

        # dati.senato.it publishes both the totals and the per-senator votes;
        # a gap means a half-loaded sitting (the per-sitting resume skips it).
        rows = self.q("""
            MATCH (s:Session {chamber: 'senato'})-[:HAS_VOTE]->(v:Vote)<-[:ON_VOTE]-(iv:IndividualVote)
            WITH v, sum(CASE iv.outcome WHEN 'favor' THEN 1 ELSE 0 END) AS fav,
                    sum(CASE iv.outcome WHEN 'against' THEN 1 ELSE 0 END) AS con,
                    sum(CASE iv.outcome WHEN 'abstain' THEN 1 ELSE 0 END) AS ast
            WITH count(v) AS tot,
                 sum(CASE WHEN fav <> v.inFavor OR con <> v.against
                           OR (v.abstained IS NOT NULL AND ast <> v.abstained)
                      THEN 1 ELSE 0 END) AS diff
            RETURN tot, diff
        """)
        tot, diff = rows[0]["tot"], rows[0]["diff"]
        self.check(diff == 0, f"voti individuali coerenti con gli aggregati ({tot} votazioni)",
                   f"{diff} votazioni con conteggi diversi", warn_only=diff <= tot * 0.01)

        # build/senate_absent.py: who is in office and not named is absent,
        # so those on leave are a subset of the absent.
        rows = self.q("""
            MATCH (s:Session {chamber: 'senato'})-[:HAS_VOTE]->(v:Vote)<-[:ON_VOTE]-(iv:IndividualVote)
            WITH v, sum(CASE iv.outcome WHEN 'absent' THEN 1 ELSE 0 END) AS ab
            WHERE ab < coalesce(v.onMission, 0)
            RETURN count(v) AS c, collect(v.id)[..3] AS ids
        """)
        self.check(rows[0]["c"] == 0, "votazioni del Senato con gli assenti (almeno quelli in missione)",
                   f"{rows[0]['c']} senza: {rows[0]['ids']} (build/senate_absent.py)")

        # Decision D9 (18/10/2026): Senate control acts come from the Chamber's
        # SPARQL (ocd:aic, ramo Senato) and keep its URI; outcome and link from
        # dati.senato.it, which has no agenda orders.
        rows = self.q("""
            MATCH (a:ParliamentaryAct) WHERE a.uri STARTS WITH 'senato:19:aic:'
            RETURN count(a) AS tot,
                   sum(CASE WHEN none(u IN coalesce(a.official_uris, [])
                                      WHERE u STARTS WITH 'http://dati.camera.it/ocd/aic.rdf/')
                        THEN 1 ELSE 0 END) AS no_camera,
                   sum(CASE WHEN coalesce(a.description, '') = '' THEN 1 ELSE 0 END) AS no_text,
                   sum(CASE WHEN a.senato_url IS NOT NULL THEN 1 ELSE 0 END) AS with_url
        """)
        r = rows[0]
        self.check(r["tot"] > 0 and r["no_camera"] == 0,
                   f"atti di controllo del Senato con l'URI ocd:aic della Camera ({r['tot']})",
                   f"{r['no_camera']} senza (build/download_senate_aic.py + ingest_senate_aic.py)")
        self.check(r["no_text"] == 0, "atti di controllo del Senato con il testo", f"{r['no_text']} senza",
                   warn_only=True)
        self.check(r["with_url"] > 0, f"atti di controllo con il link a senato.it ({r['with_url']})",
                   "nessuno: build/download_senate_aic.py --source senato", warn_only=True)

        # Question time and urgent questions: the debate title carries the
        # act number, "(3-02671) - ..." (build/link_senate_acts.py).
        rows = self.q("""
            MATCH (:Session {chamber: 'senato'})-[:HAS_DEBATE]->(d:Debate)
            WHERE d.title =~ '(?s).*\\\\b[1-4]-[0-9]{5}\\\\b.*'
            RETURN count(d) AS tot,
                   sum(CASE WHEN EXISTS { (d)-[:DISCUSSES]->(a:ParliamentaryAct)
                                          WHERE a.uri STARTS WITH 'senato:' } THEN 1 ELSE 0 END) AS linked
        """)
        r = rows[0]
        self.check(r["linked"] == r["tot"],
                   f"dibattiti del Senato su interrogazioni collegati all'atto {r['linked']}/{r['tot']}",
                   f"{r['tot'] - r['linked']} senza DISCUSSES (build/link_senate_acts.py)")

        # Decision D3 (15/10/2026): every Senate bill says who presented it.
        rows = self.q("""
            MATCH (a:ParliamentaryAct {chamber: 'senato', type: 'Disegno di legge'})
            RETURN count(a) AS tot,
                   sum(CASE WHEN a.initiative IS NULL THEN 1 ELSE 0 END) AS no_init,
                   sum(CASE WHEN a.initiative IN ['governo', 'mista']
                             AND NOT (a)-[:PRESENTED_BY]->(:Government) THEN 1 ELSE 0 END) AS gov_no_pres,
                   sum(CASE WHEN NOT ()-[:PRIMARY_SIGNATORY|CO_SIGNATORY|PRESENTED]->(a)
                             AND NOT coalesce(a.initiative, '') IN ['regionale', 'cnel', 'popolare']
                        THEN 1 ELSE 0 END) AS nobody
        """)
        r = rows[0]
        self.check(r["no_init"] == 0, f"ddl del Senato con l'iniziativa ({r['tot']})",
                   f"{r['no_init']} senza (download_senate_ddl.py + link_senate_acts.py)")
        self.check(r["gov_no_pres"] == 0, "ddl del governo con PRESENTED_BY",
                   f"{r['gov_no_pres']} senza")
        self.check(r["nobody"] == 0, "ddl del Senato con firmatari o presentatori",
                   f"{r['nobody']} senza nessuno")

        # TESEO (osr:classificazione, level "Generale"): 2,097 of 2,098 bills
        # on 19/10/2026, 1689/I has none at the source.
        rows = self.q("""
            MATCH (a:ParliamentaryAct {chamber: 'senato', type: 'Disegno di legge'})
            RETURN count(a) AS tot,
                   sum(CASE WHEN (a)-[:HAS_SUBJECT]->(:TeseoConcept) THEN 1 ELSE 0 END) AS with_s
        """)
        r = rows[0]
        self.check(r["with_s"] >= 0.98 * r["tot"], f"ddl del Senato con i temi TESEO {r['with_s']}/{r['tot']}",
                   "sotto il 98% (download_senate_ddl.py + link_senate_acts.py)", warn_only=True)

        # build/link_senate_acts.py. Quorum checks, cancelled votes and
        # re-counts aside, 89 of 8,181 votes had no act on 19/10/2026 (1.1%):
        # Documents that are not nodes yet, Giunta reports, secret elections.
        rows = self.q("""
            MATCH (:Session {chamber: 'senato'})-[:HAS_VOTE]->(v:Vote)
            WHERE coalesce(v.type, '') <> 'verifica numero legale'
              AND NOT toLower(coalesce(v.subject, '')) CONTAINS 'annullata'
              AND NOT toLower(coalesce(v.subject, '')) STARTS WITH 'controprova'
            RETURN count(v) AS tot, sum(CASE WHEN NOT (v)-[:ON_ACT]->() THEN 1 ELSE 0 END) AS loose
        """)
        r = rows[0]
        self.check(r["loose"] <= 0.02 * r["tot"],
                   f"votazioni del Senato con l'atto {r['tot'] - r['loose']}/{r['tot']}",
                   f"{r['loose']} senza ON_ACT, sopra il 2% (build/link_senate_acts.py)", warn_only=True)

    def check_acts_camera(self):
        print("\n[15] Atti della Camera XIX (build/ingest_acts_camera.py)")
        # Acts cited by votes but never described at the source (about 2,755
        # agenda orders, audit 14/10/2026) only have a URI: counted apart.
        rows = self.q("""
            MATCH (a:ParliamentaryAct)
            WHERE a.uri STARTS WITH 'http://dati.camera.it/ocd/attocamera.rdf/ac19_'
               OR (a.uri STARTS WITH 'http://dati.camera.it/ocd/aic.rdf/' AND a.uri ENDS WITH '_19')
            WITH a, a.title IS NOT NULL AS described
            RETURN sum(CASE WHEN described THEN 1 ELSE 0 END) AS tot,
                   sum(CASE WHEN described AND (a.chamber IS NULL OR a.legislature IS NULL OR a.kind IS NULL)
                       THEN 1 ELSE 0 END) AS incomplete,
                   sum(CASE WHEN NOT described THEN 1 ELSE 0 END) AS uri_only
        """)
        r = rows[0]
        self.check(r["incomplete"] == 0, f"atti Camera con chamber, legislature e kind ({r['tot']})",
                   f"{r['incomplete']} senza")
        self.check(r["uri_only"] == 0, "atti Camera con titolo", f"{r['uri_only']} con solo l'URI (assenti alla fonte)",
                   warn_only=True)
        rows = self.q("""
            MATCH (a:Bill {chamber: 'camera'})
            RETURN count(a) AS tot,
                   sum(CASE WHEN a.initiative IS NULL THEN 1 ELSE 0 END) AS no_init,
                   sum(CASE WHEN a.number IS NULL OR a.type IS NULL THEN 1 ELSE 0 END) AS no_number,
                   sum(CASE WHEN a.initiative = 'governo' AND NOT (a)-[:PRESENTED_BY]->(:Government)
                       THEN 1 ELSE 0 END) AS gov_no_pres
        """)
        r = rows[0]
        self.check(r["tot"] > 0, f"progetti di legge della Camera con etichetta Bill ({r['tot']})", "nessuno")
        self.check(r["no_init"] == 0, "progetti di legge della Camera con l'iniziativa", f"{r['no_init']} senza")
        self.check(r["no_number"] == 0, "progetti di legge della Camera con tipo e numero", f"{r['no_number']} senza")
        self.check(r["gov_no_pres"] == 0, "progetti di legge del governo con PRESENTED_BY",
                   f"{r['gov_no_pres']} senza")

    def check_act_kinds(self):
        print("\n[16] Famiglia e kind degli atti (decisione D1, build/act_kinds.py)")
        from act_kinds import FAMILIES, KINDS
        rows = self.q("""
            MATCH (a:ParliamentaryAct)
            WITH a, [l IN labels(a) WHERE l IN $families] AS fam
            RETURN count(a) AS tot,
                   sum(CASE WHEN size(fam) = 0 THEN 1 ELSE 0 END) AS no_family,
                   sum(CASE WHEN size(fam) > 1 THEN 1 ELSE 0 END) AS many,
                   sum(CASE WHEN size(fam) = 1 AND NOT a.kind IN $kinds[fam[0]] THEN 1 ELSE 0 END) AS bad_kind,
                   sum(CASE WHEN a.type IS NOT NULL AND a.type_raw IS NULL THEN 1 ELSE 0 END) AS no_raw
        """, families=list(FAMILIES), kinds={f: sorted(k) for f, k in KINDS.items()})
        r = rows[0]
        self.check(r["no_family"] == 0, f"atti con un'etichetta di famiglia ({r['tot']})",
                   f"{r['no_family']} senza (build/migrate_act_kinds.py)")
        self.check(r["many"] == 0, "atti con una sola famiglia", f"{r['many']} con più etichette")
        self.check(r["bad_kind"] == 0, "kind nel vocabolario della famiglia", f"{r['bad_kind']} fuori")
        self.check(r["no_raw"] == 0, "type_raw dove c'è type", f"{r['no_raw']} senza")

    def check_act_identity(self):
        print("\n[17] Letture e processo legislativo (decisione D2, build/migrate_act_identity.py)")
        rows = self.q("""
            MATCH (a:Bill) WHERE a.chamber IN ['camera', 'senato'] AND a.legislature = 19
            RETURN a.chamber AS ch, count(a) AS tot,
                   sum(CASE WHEN NOT (a)-[:PART_OF]->(:LegislativeProcess) THEN 1 ELSE 0 END) AS loose,
                   sum(CASE WHEN a.number =~ '.*-[B-Z]$' AND NOT ()-[:NEXT_READING]->(a) THEN 1 ELSE 0 END) AS orphan
            ORDER BY ch
        """)
        for r in rows:
            self.check(r["loose"] == 0, f"{r['ch']}: progetti di legge con PART_OF ({r['tot']})",
                       f"{r['loose']} senza processo")
            self.check(r["orphan"] == 0, f"{r['ch']}: letture successive con la lettura precedente",
                       f"{r['orphan']} senza NEXT_READING in arrivo", warn_only=True)
        rows = self.q("""
            MATCH (a:Bill {chamber: 'camera', legislature: 19})
            RETURN count(a) AS tot, sum(CASE WHEN (a)-[:HAS_VERSION]->(:TextVersion) THEN 1 ELSE 0 END) AS with_v
        """)
        r = rows[0]
        self.check(r["with_v"] >= 0.8 * r["tot"], f"progetti della Camera con le versioni del testo {r['with_v']}/{r['tot']}",
                   "sotto l'80%: build/migrate_act_identity.py --versions", warn_only=True)

    def check_agenda_orders(self):
        print("\n[18] Ordini del giorno: atto di riferimento ed esito (build/link_agenda_orders.py)")
        rows = self.q("""
            MATCH (o:AgendaOrder)
            WHERE o.chamber = 'camera' OR (o.chamber IS NULL AND o.uri STARTS WITH 'http://dati.camera.it/ocd/aic.rdf/'
                                           AND o.uri ENDS WITH '_19')
            RETURN count(o) AS tot,
                   sum(CASE WHEN (o)-[:REFERS_TO]->(:Bill) THEN 1 ELSE 0 END) AS linked,
                   sum(CASE WHEN (o)<-[:ON_ACT]-(:Vote) THEN 1 ELSE 0 END) AS voted,
                   sum(CASE WHEN (o)<-[:ON_ACT]-(:Vote) AND o.outcome IS NULL THEN 1 ELSE 0 END) AS voted_no_outcome,
                   sum(CASE WHEN o.outcome IS NOT NULL THEN 1 ELSE 0 END) AS with_outcome
        """)
        r = rows[0]
        # Floors: 9,422 + 2,715 orders whose number or URI names a bill and
        # 6,502 voted orders at the source (audit, 14/10/2026); 13,282 linked
        # and 6,720 with an outcome in production on 19/10/2026.
        self.check(r["linked"] >= 12137, f"Camera: ODG collegati al progetto di legge {r['linked']}/{r['tot']}",
                   "sotto 12.137 (audit 14/10/2026)")
        self.check(r["with_outcome"] >= 6502, f"Camera: ODG con esito dal voto {r['with_outcome']}",
                   "sotto 6.502 (audit 14/10/2026)")
        self.check(r["voted_no_outcome"] == 0, f"Camera: ODG votati con esito ({r['voted']})",
                   f"{r['voted_no_outcome']} senza")
        rows = self.q("""
            MATCH (o:AgendaOrder {chamber: 'senato'})
            RETURN count(o) AS tot, sum(CASE WHEN (o)-[:REFERS_TO]->(:Bill) THEN 1 ELSE 0 END) AS linked,
                   sum(CASE WHEN o.outcome IS NOT NULL THEN 1 ELSE 0 END) AS with_outcome
        """)
        r = rows[0]
        # 5,773 of 6,454 on 19/10/2026: the rest are on documents and motions.
        self.check(r["linked"] >= 0.85 * r["tot"], f"Senato: ODG collegati al ddl {r['linked']}/{r['tot']}",
                   "sotto l'85%", warn_only=True)
        self.check(r["with_outcome"] > 0, f"Senato: ODG con esito {r['with_outcome']}",
                   "nessuno (JSONL degli emendamenti assente?)", warn_only=True)
        rows = self.q("""
            MATCH (o:AgendaOrder)-[:REFERS_TO]->(b) WITH o, count(b) AS n
            RETURN sum(CASE WHEN n > 1 THEN 1 ELSE 0 END) AS many
        """)
        self.check(rows[0]["many"] == 0, "ODG con un solo atto di riferimento", f"{rows[0]['many']} con più di uno")

    def check_reporters(self):
        print("\n[19] Relatori dei progetti di legge (build/ingest_reporters.py)")
        rows = self.q("""
            MATCH (b:Bill)-[r:REPORTED_BY]->(p)
            RETURN b.chamber AS ch, count(DISTINCT b) AS bills, count(r) AS rels,
                   sum(CASE WHEN NOT r.role IN ['relatore', 'maggioranza', 'minoranza', 'facente_funzione', 'sostituto']
                       THEN 1 ELSE 0 END) AS bad_role,
                   sum(CASE WHEN NOT p:Person THEN 1 ELSE 0 END) AS not_person
        """)
        by_ch = {r["ch"]: r for r in rows}
        present = {r["ch"] for r in self.q("MATCH (b:Bill) RETURN DISTINCT b.chamber AS ch")}
        # Bills with a rapporteur at the source on 19/10/2026: Camera 1,059
        # (ocd:rif_relatore), Senato 965 (osr:relatore, ramo S).
        for ch, floor in (("camera", 1000), ("senato", 900)):
            if ch not in present:
                continue
            r = by_ch.get(ch, {"bills": 0, "rels": 0, "bad_role": 0, "not_person": 0})
            self.check(r["bills"] >= floor, f"{ch}: progetti di legge con relatore {r['bills']} ({r['rels']} relatori)",
                       f"sotto {floor}")
            self.check(r["bad_role"] == 0 and r["not_person"] == 0, f"{ch}: REPORTED_BY con ruolo nel vocabolario",
                       f"{r['bad_role']} ruoli fuori vocabolario, {r['not_person']} verso nodi non Person")

    def check_laws(self):
        print("\n[20] Leggi (decisione D5, build/ingest_laws.py)")
        rows = self.q("""
            MATCH (l:Law)
            RETURN count(l) AS tot,
                   sum(CASE WHEN NOT ()-[:BECAME_LAW]->(l) THEN 1 ELSE 0 END) AS loose,
                   sum(CASE WHEN l.date IS NULL OR l.date >= date('2100-01-01') THEN 1 ELSE 0 END) AS bad_date,
                   sum(CASE WHEN l.eli IS NULL THEN 1 ELSE 0 END) AS no_eli
        """)
        r = rows[0]
        self.check(r["tot"] > 0, f"leggi ({r['tot']})", "nessuna", warn_only=True)
        self.check(r["loose"] == 0, "leggi con il processo legislativo", f"{r['loose']} senza BECAME_LAW")
        self.check(r["bad_date"] == 0, "leggi con una data vera", f"{r['bad_date']} senza data o con 2100-01-01")
        self.check(r["no_eli"] == 0, "leggi trovate su Normattiva", f"{r['no_eli']} senza ELI", warn_only=True)
        # «appr. def. non pubbl»: approved, waiting for promulgation and the
        # Gazzetta (constitutional laws also for the referendum): no law yet.
        rows = self.q("""
            MATCH (a:Bill {chamber: 'senato', legislature: 19})
            WHERE a.status IN ['appr. definit. Legge', 'appr. def. non pubbl']
            RETURN a.status AS st, count(a) AS tot,
                   sum(CASE WHEN NOT (a)-[:PART_OF]->(:LegislativeProcess)-[:BECAME_LAW]->(:Law)
                       THEN 1 ELSE 0 END) AS no_law,
                   [x IN collect(CASE WHEN NOT (a)-[:PART_OF]->(:LegislativeProcess)-[:BECAME_LAW]->(:Law)
                       THEN 'S.' + a.number END) WHERE x IS NOT NULL][..10] AS sample
            ORDER BY st
        """)
        for r in rows:
            if r["st"] == "appr. definit. Legge":
                self.check(r["no_law"] == 0, f"ddl «appr. definit. Legge» con la legge ({r['tot']})",
                           f"{r['no_law']} senza BECAME_LAW: {r['sample']}")
            else:
                print(f"  [info] ddl «{r['st']}»: {r['tot']}, senza legge {r['no_law']} {r['sample']}")

    def check_amendments(self, n_amendments: int):
        print(f"\n[14] Emendamenti ({n_amendments} nodi, build/load_emendamenti.py)")
        rows = self.q("""
            MATCH (a:Amendment) WITH a.id AS id, count(*) AS n WHERE n > 1
            RETURN count(id) AS c, collect(id)[..5] AS ids
        """)
        self.check(rows[0]["c"] == 0, "0 id di emendamento duplicati", f"{rows[0]['c']}: {rows[0]['ids']}")

        # Thresholds from the first load on staging (2026-10-14): Chamber 92%
        # of amendments with their bill (49 bills missing from the graph),
        # signatures ~100%, floor votes 87% Chamber and 97% Senate.
        rows = self.q("""
            MATCH (a:Amendment)
            RETURN a.chamber AS ch, count(a) AS n,
                   sum(CASE WHEN EXISTS { (a)-[:AMENDS]->() } THEN 1 ELSE 0 END) AS with_act,
                   sum(a.member_signatories) AS signers,
                   sum(COUNT { (a)<-[:SIGNED_AMENDMENT]-() }) AS signed
        """)
        for r in rows:
            self.check(r["with_act"] >= 0.9 * r["n"], f"{r['ch']}: emendamenti con atto {r['with_act']}/{r['n']}",
                       "sotto il 90%", warn_only=True)
            self.check(r["signed"] >= 0.98 * r["signers"],
                       f"{r['ch']}: firme collegate {r['signed']}/{r['signers']}", "sotto il 98%", warn_only=True)

        rows = self.q("""
            MATCH (s:Session)-[:HAS_VOTE]->(v:Vote)
            WHERE (s.chamber = 'camera' AND (v.subject STARTS WITH 'Votazione Emendamento'
                     OR (v.subject = 'Votazione' AND v.description =~ '(?i)^((DDL|PDL) \\d+\\S* - )?(EM|ART\\.? AGG|SUBEM) .*')))
               OR (s.chamber = 'senato' AND v.subject =~ '^(DDL n\\. ?\\S+\\. )?(Em|Emm|ODG)\\.? .*')
            RETURN s.chamber AS ch, count(v) AS n,
                   sum(CASE WHEN EXISTS { (v)-[:ON_AMENDMENT]->() } THEN 1 ELSE 0 END) AS linked
        """)
        for r in rows:
            self.check(r["linked"] >= 0.8 * r["n"],
                       f"{r['ch']}: votazioni d'Aula su emendamenti collegate {r['linked']}/{r['n']}",
                       "sotto l'80%", warn_only=True)

    def run_all(self):
        print("=== VALIDAZIONE SCHEMA V2 ===\n")

        print("[1] SchemaMeta")
        meta = self.q("MATCH (m:SchemaMeta {id:'singleton'}) RETURN m.version AS v, m.embedding_model AS model")
        self.check(bool(meta) and meta[0]["v"] == 2, "SchemaMeta presente con version=2",
                   f"trovato: {meta}")

        print("\n[2] Embedding nativi (C2) — 0 embedding STRING")
        for label, prop in EMBEDDING_PROPS:
            rows = self.q(f"""
                MATCH (n:`{label}`) WHERE n[$p] IS NOT NULL
                WITH n LIMIT 200
                RETURN sum(CASE WHEN apoc.meta.cypher.type(n[$p]) = 'STRING' THEN 1 ELSE 0 END) AS bad,
                       count(*) AS tot
            """, p=prop)
            bad, tot = rows[0]["bad"], rows[0]["tot"]
            if tot == 0:
                self.check(True, f"{label}.{prop} (0 nodi con proprietà — skip)")
            else:
                self.check(bad == 0, f"{label}.{prop} nativo ({tot} campionati)",
                           f"{bad} STRING trovati")

        print("\n[3] Vector index popolati")
        dummy = [random.uniform(-0.01, 0.01) for _ in range(1536)]
        for idx in VECTOR_INDEXES:
            try:
                rows = self.q(
                    f"CALL db.index.vector.queryNodes('{idx}', 3, $v) YIELD node RETURN count(*) AS c",
                    v=dummy)
                self.check(rows[0]["c"] > 0, f"{idx} restituisce risultati",
                           "indice vuoto (0 risultati)")
            except Exception as e:
                self.check(False, f"{idx} interrogabile", str(e)[:120])

        print("\n[4] SPOKEN_BY obbligatorio")
        rows = self.q("MATCH (sp:Speech) WHERE NOT (sp)-[:SPOKEN_BY]->() RETURN count(sp) AS c")
        n_orphans = rows[0]["c"]
        # Fino a 100 orfani = WARN: sono gli ex-membri del governo senza nodo
        # (Sangiuliano, Sgarbi, senatori alla Camera) — irrisolvibili finché non
        # esiste la config governi storici. Oltre 100 = regressione strutturale.
        self.check(n_orphans == 0, "0 Speech senza SPOKEN_BY",
                   f"{n_orphans} orfani (ex-governo/senatori senza nodo)",
                   warn_only=(0 < n_orphans <= 100))

        print("\n[5] Invariante substring chunk (C8) — campione 5000")
        rows = self.q("""
            MATCH (c:Chunk)<-[:HAS_CHUNK]-(sp:Speech)
            WHERE c.text IS NOT NULL AND sp.text IS NOT NULL
            WITH c, sp, rand() AS rnd ORDER BY rnd LIMIT 5000
            RETURN sum(CASE WHEN sp.text CONTAINS c.text THEN 0 ELSE 1 END) AS bad,
                   count(*) AS tot
        """)
        self.check(rows[0]["bad"] == 0,
                   f"chunk substring esatta dello speech ({rows[0]['tot']} campionati)",
                   f"{rows[0]['bad']} violazioni")

        print("\n[5b] Archi NEXT tra chunk consecutivi")
        rows = self.q("""
            MATCH (c:Chunk) WITH count(c) AS chunks
            MATCH (s:Speech) WITH chunks, count(s) AS speeches
            MATCH ()-[r:NEXT]->() RETURN chunks, speeches, count(r) AS nexts
        """)
        chunks, speeches, nexts = rows[0]["chunks"], rows[0]["speeches"], rows[0]["nexts"]
        expected = chunks - speeches  # ogni speech con N chunk produce N-1 NEXT
        self.check(nexts >= expected * 0.95,
                   f"NEXT presenti ({nexts:,} — attesi ~{expected:,})",
                   "neighbor expansion del retrieval MORTA senza NEXT "
                   "(persi nel primo rebuild v2, scoperto 2026-07-24)")

        print("\n[6] Date native (C1) — 0 date STRING")
        for label, prop in DATE_PROPS:
            rows = self.q(f"""
                MATCH (n:`{label}`) WHERE n[$p] IS NOT NULL
                WITH n LIMIT 500
                RETURN sum(CASE WHEN apoc.meta.cypher.type(n[$p]) = 'STRING' THEN 1 ELSE 0 END) AS bad,
                       count(*) AS tot
            """, p=prop)
            bad, tot = rows[0]["bad"], rows[0]["tot"]
            if tot == 0:
                self.check(True, f"{label}.{prop} (0 nodi — skip)")
            else:
                self.check(bad == 0, f"{label}.{prop} tipo date ({tot} campionati)",
                           f"{bad} STRING")

        print("\n[7] Niente placeholder vuoti (C3)")
        rows = self.q("""
            MATCH (n) WHERE n:ParliamentaryAct OR n:Speech OR n:Chunk OR n:Deputy
            WITH n LIMIT 20000
            UNWIND keys(n) AS k
            WITH n, k WHERE n[k] = ''
            RETURN labels(n)[0] AS label, k, count(*) AS c ORDER BY c DESC LIMIT 10
        """)
        self.check(not rows, "0 proprietà stringa-vuota",
                   f"trovate: {rows}")

        print("\n[8] Proprietà v1 eliminate (C5)")
        for label, prop in FORBIDDEN_PROPS:
            rows = self.q(f"MATCH (n:`{label}`) WHERE n[$p] IS NOT NULL RETURN count(n) AS c", p=prop)
            self.check(rows[0]["c"] == 0, f"{label}.{prop} assente",
                       f"{rows[0]['c']} nodi la hanno ancora")

        print("\n[9] Label morte assenti (C7)")
        for label in FORBIDDEN_LABELS:
            rows = self.q(f"MATCH (n:`{label}`) RETURN count(n) AS c")
            self.check(rows[0]["c"] == 0, f"label {label} assente",
                       f"{rows[0]['c']} nodi")
        # indici/constraint orfani su label senza nodi
        idx_rows = self.q("SHOW INDEXES YIELD name, labelsOrTypes WHERE labelsOrTypes IS NOT NULL RETURN name, labelsOrTypes")
        orphan_idx = [r["name"] for r in idx_rows
                      if r["labelsOrTypes"] and r["labelsOrTypes"][0] in FORBIDDEN_LABELS]
        self.check(not orphan_idx, "0 indici su label morte", f"{orphan_idx}")

        print("\n[10] Linked Data (C10)")
        for label, (prop, prefixes) in URI_PATTERNS.items():
            conds = " AND ".join(f"NOT n[$p] STARTS WITH '{pf}'" for pf in prefixes)
            rows = self.q(f"""
                MATCH (n:`{label}`) WHERE n[$p] IS NOT NULL AND {conds}
                RETURN count(n) AS c
            """, p=prop)
            self.check(rows[0]["c"] == 0,
                       f"{label}.{prop} conforme ai pattern LOD",
                       f"{rows[0]['c']} URI non conformi")
        rows = self.q("""
            MATCH (ev:EurovocConcept) RETURN count(ev) AS concepts
        """)
        n_concepts = rows[0]["concepts"]
        rows = self.q("MATCH (:ParliamentaryAct)-[:HAS_SUBJECT]->(:EurovocConcept) RETURN count(*) AS c")
        self.check(n_concepts > 0 and rows[0]["c"] > 0,
                   f"EurovocConcept popolati ({n_concepts} concetti, {rows[0]['c']} HAS_SUBJECT)",
                   "nessun concetto EuroVoc collegato", warn_only=True)

        print("\n[11] Modello Person")
        rows = self.q("MATCH (d:Deputy) WHERE NOT d:Person RETURN count(d) AS c")
        self.check(rows[0]["c"] == 0, "tutti i Deputy hanno label Person", f"{rows[0]['c']} senza")
        rows = self.q("MATCH (gm:GovernmentMember) WHERE NOT gm:Person RETURN count(gm) AS c")
        self.check(rows[0]["c"] == 0, "tutti i GovernmentMember hanno label Person", f"{rows[0]['c']} senza")
        rows = self.q("MATCH (:Person)-[o:HOLDS_OFFICE]->(:Government) RETURN count(o) AS c")
        self.check(rows[0]["c"] > 0, f"HOLDS_OFFICE presenti ({rows[0]['c']})",
                   "nessuna relazione HOLDS_OFFICE")
        rows = self.q("""
            MATCH (:Person)-[r:MEMBER_OF_COMMITTEE]->(:Committee)
            WHERE r.role IS NOT NULL RETURN count(r) AS c
        """)
        self.check(rows[0]["c"] > 0, f"ruoli commissione su MEMBER_OF_COMMITTEE ({rows[0]['c']})",
                   "nessun role su MEMBER_OF_COMMITTEE", warn_only=True)

        print("\n[11b] Membership gruppo univoca (rename detection)")
        # Un rename del gruppo alla fonte (denominazione nuova = nodo nuovo,
        # perché l'ingest fa MERGE per nome) lascia i deputati con DUE
        # membership aperte e l'attribuzione partito diventa arbitraria
        # (successo con Italia Viva → Casa Riformista, 2026-08: Faraone
        # attribuito al Misto). Cura: build/repair_group_rename.py.
        rows = self.q("""
            MATCH (d:Deputy)-[m:MEMBER_OF_GROUP]->(:ParliamentaryGroup)
            WHERE m.end_date IS NULL
            WITH d, count(m) AS n WHERE n > 1
            RETURN d.last_name AS dep, n LIMIT 10
        """)
        self.check(not rows, "0 deputati con più membership di gruppo aperte",
                   f"probabile rename di gruppo non riconciliato: {rows}")

        print("\n[12] Conteggi base")
        for label in ["Session", "Debate", "Phase", "Speech", "Chunk",
                      "Deputy", "GovernmentMember", "ParliamentaryAct"]:
            rows = self.q(f"MATCH (n:`{label}`) RETURN count(n) AS c")
            c = rows[0]["c"]
            self.check(c > 0, f"{label}: {c} nodi", "0 nodi!")

        rows = self.q("MATCH (s:Session {chamber: 'senato'}) RETURN count(s) AS c")
        if rows[0]["c"]:
            self.check_senate(rows[0]["c"])

        self.check_acts_camera()
        self.check_act_kinds()
        self.check_act_identity()
        self.check_agenda_orders()
        self.check_reporters()
        self.check_laws()

        rows = self.q("MATCH (a:Amendment) RETURN count(a) AS c")
        if rows[0]["c"]:
            self.check_amendments(rows[0]["c"])

        # ------------------------------------------------------------------
        print(f"\n=== ESITO: {self.failures} FAIL, {self.warnings} WARN ===")
        return self.failures == 0


def main():
    p = argparse.ArgumentParser(description="Validate schema v2 invariants")
    p.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    p.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    p.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                   required=os.environ.get("NEO4J_PASSWORD") is None)
    args = p.parse_args()

    v = Validator(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    try:
        ok = v.run_all()
    finally:
        v.driver.close()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
