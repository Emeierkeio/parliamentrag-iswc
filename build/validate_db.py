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
    "ParliamentaryAct": ("uri", ("http://dati.camera.it/", "placeholder:")),
    "EurovocConcept": ("uri", ("http://eurovoc.europa.eu/",)),
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
