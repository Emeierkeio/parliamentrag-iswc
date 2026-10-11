
import logging
import os
import time
from dotenv import load_dotenv

# Carica .env dalla root del progetto
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

from neo4j_helper import get_neo4j_client
from embedding_service import EmbeddingService

# Configurazione logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
# Silenzia i warning di Neo4j relativi alle property mancanti
# (Utile quando lanciamo la query per trovare nodi SENZA property)
logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

logger = logging.getLogger("PreCalculateEmbeddings")

def main():
    # Arguments win over the environment: without them the .env loaded above
    # points at the production tunnel, and --neo4j-uri used to be ignored
    # silently (2026-10-11: a run meant for staging wrote to production).
    import argparse
    ap = argparse.ArgumentParser(description="Fill missing embeddings")
    ap.add_argument("--neo4j-uri")
    ap.add_argument("--neo4j-user")
    ap.add_argument("--neo4j-password")
    args, _ = ap.parse_known_args()

    logger.info("=== INIZIO PRE-CALCOLO EMBEDDINGS UNIFICATO ===")

    neo4j = get_neo4j_client(args.neo4j_uri, args.neo4j_user, args.neo4j_password)
    logger.info("Neo4j: %s", args.neo4j_uri or os.environ.get("NEO4J_URI"))
    embedder = EmbeddingService()

    # ---------------------------------------------------------
    # 1. Committees
    # ---------------------------------------------------------
    logger.info("\n--- FASE 1: COMMITTEES ---")
    res = neo4j.query("MATCH (c:Committee) RETURN c.name as name")

    if res:
        logger.info(f"Trovate {len(res)} commissioni. Verifica e aggiornamento...")
        names = [r['name'] for r in res if r['name']]

        # Per le commissioni (pochi dati), ricalcoliamo sempre per sicurezza/semplicità
        embeddings = embedder.embed_texts(names)

        updates_count = 0
        for name, emb in zip(names, embeddings):
            # Schema v2 (C2): embedding SEMPRE come lista nativa di float,
            # mai JSON string — abilita vector index e evita parse a runtime.
            neo4j.query(
                "MATCH (c:Committee {name: $name}) SET c.embedding = $emb",
                {'name': name, 'emb': emb.tolist()}
            )
            updates_count += 1

        logger.info(f"Aggiornate {updates_count} commissioni.")
    else:
        logger.info("Nessuna commissione trovata.")

    # ---------------------------------------------------------
    # 2. Parliamentary Acts (Title & Description)
    # ---------------------------------------------------------
    # Schema v2: l'embedding EuroVoc per-atto non esiste più — i concetti
    # EuroVoc sono nodi EurovocConcept con embedding proprio (Fase 2b).
    logger.info("\n--- FASE 2: PARLIAMENTARY ACTS (Title & Description) ---")
    BATCH_SIZE_ATTI = 100
    processed_atti = 0

    while True:
        query_fetch = """
            MATCH (a:ParliamentaryAct)
            WHERE (a.title IS NOT NULL AND a.title <> '' AND a.title_embedding IS NULL)
               OR (a.description IS NOT NULL AND a.description <> '' AND a.description_embedding IS NULL)
            RETURN elementId(a) as id, a.title as title, a.description as description
            LIMIT $limit
        """

        batch_acts = neo4j.query(query_fetch, {'limit': BATCH_SIZE_ATTI})

        if not batch_acts:
            logger.info("Nessun altro atto da elaborare (tutti completi).")
            break

        texts_to_embed = set()
        for r in batch_acts:
            if r['title']: texts_to_embed.add(r['title'])
            if r['description']: texts_to_embed.add(r['description'])

        list_texts = list(texts_to_embed)
        if not list_texts:
            logger.warning("Batch atti vuoto (strano). Skip.")
            continue

        try:
            embeddings_list = embedder.embed_texts(list_texts)
            emb_map = dict(zip(list_texts, embeddings_list))
        except Exception as e:
            logger.error(f"Errore durante embedding batch atti: {e}")
            time.sleep(5)
            continue

        updates_in_batch = 0

        for r in batch_acts:
            sets = []
            params = {'id': r['id']}

            # Title
            if r['title'] and r['title'] in emb_map:
                 emb_val = emb_map[r['title']]
                 if any(emb_val):
                     params['e_tit'] = emb_val.tolist()
                     sets.append("a.title_embedding = $e_tit")

            # Description
            if r['description'] and r['description'] in emb_map:
                 emb_val = emb_map[r['description']]
                 if any(emb_val):
                     params['e_desc'] = emb_val.tolist()
                     sets.append("a.description_embedding = $e_desc")

            if sets:
                q_upd = f"MATCH (a:ParliamentaryAct) WHERE elementId(a) = $id SET {', '.join(sets)}"
                neo4j.query(q_upd, params)
                updates_in_batch += 1

        processed_atti += len(batch_acts)
        logger.info(f"Atti processati finora: {processed_atti} (Batch: {updates_in_batch} updates)")

    # ---------------------------------------------------------
    # 2b. EurovocConcept (un embedding per concetto, non per atto)
    # ---------------------------------------------------------
    logger.info("\n--- FASE 2b: EUROVOC CONCEPTS ---")
    ev_rows = neo4j.query("""
        MATCH (ev:EurovocConcept)
        WHERE ev.label_it IS NOT NULL AND ev.label_it <> '' AND ev.embedding IS NULL
        RETURN ev.uri AS uri, ev.label_it AS label
    """)
    if ev_rows:
        logger.info(f"Embedding di {len(ev_rows)} concetti EuroVoc...")
        ev_embeddings = embedder.embed_texts([r['label'] for r in ev_rows])
        ev_updates = 0
        for r, emb in zip(ev_rows, ev_embeddings):
            if any(emb):
                neo4j.query(
                    "MATCH (ev:EurovocConcept {uri: $uri}) SET ev.embedding = $emb",
                    {'uri': r['uri'], 'emb': emb.tolist()}
                )
                ev_updates += 1
        logger.info(f"Aggiornati {ev_updates} concetti EuroVoc.")
    else:
        logger.info("Nessun concetto EuroVoc da embeddare.")

    # ---------------------------------------------------------
    # 3. Chunks (Vector Index)
    # ---------------------------------------------------------
    logger.info("\n--- FASE 3: CHUNKS (RAG Vector Index) ---")
    BATCH_SIZE_CHUNKS = 500
    processed_chunks = 0

    # Check totali per info
    try:
        total_chunks = neo4j.query_single("MATCH (c:Chunk) RETURN count(c) as cnt")['cnt']
        done_chunks = neo4j.query_single("MATCH (c:Chunk) WHERE c.embedding IS NOT NULL RETURN count(c) as cnt")['cnt']
        logger.info(f"Stato Chunks: {done_chunks}/{total_chunks} completati.")
    except Exception as e:
        logger.warning(f"Impossibile contare chunks: {e}")

    while True:
        # Recupera chunk senza embedding
        query_chunk = """
            MATCH (c:Chunk)
            WHERE c.embedding IS NULL
            RETURN c.id as id, c.text as text
            LIMIT $limit
        """

        batch_chunks = neo4j.query(query_chunk, {'limit': BATCH_SIZE_CHUNKS})

        if not batch_chunks:
            logger.info("Nessun altro chunk da elaborare.")
            break

        texts = [r['text'] for r in batch_chunks]
        ids = [r['id'] for r in batch_chunks]

        if not texts:
            continue

        try:
            # Embedder gestisce batching interno API, cache, retries...
            embeddings = embedder.embed_texts(texts)

            batch_updates = 0
            for cid, emb_arr in zip(ids, embeddings):
                if any(emb_arr):
                    # IMPORTANTE: Per Vector Index Neo4j vuole una LISTA DI FLOAT, non una stringa JSON
                    emb_list = emb_arr.tolist()

                    neo4j.query(
                        "MATCH (c:Chunk {id: $id}) SET c.embedding = $emb",
                        {'id': cid, 'emb': emb_list}
                    )
                    batch_updates += 1

            processed_chunks += len(batch_chunks)
            logger.info(f"Chunks processati finora: {processed_chunks} (Batch: {batch_updates} updates)")

        except Exception as e:
            logger.error(f"Errore embedding chunks: {e}")
            time.sleep(5)

    # ---------------------------------------------------------
    # 4. Deputies (Profession & Education)
    # ---------------------------------------------------------
    logger.info("\n--- FASE 4: DEPUTIES (Profession & Education) ---")
    BATCH_SIZE_DEP = 100
    processed_dep = 0

    while True:
        # Recupera deputati che mancano di profession_embedding O education_embedding
        # (solo se il campo testuale esiste)
        query_fetch = """
            MATCH (d:Deputy)
            WHERE (d.profession IS NOT NULL AND d.profession <> '' AND d.profession_embedding IS NULL)
               OR (d.education IS NOT NULL AND d.education <> '' AND d.education_embedding IS NULL)
            RETURN elementId(d) as id, d.profession as profession, d.education as education
            LIMIT $limit
        """

        batch_dep = neo4j.query(query_fetch, {'limit': BATCH_SIZE_DEP})

        if not batch_dep:
            logger.info("Nessun altro deputato da elaborare.")
            break

        texts_to_embed = set()
        for r in batch_dep:
            if r['profession']: texts_to_embed.add(r['profession'])
            if r['education']: texts_to_embed.add(r['education'])

        list_texts = list(texts_to_embed)
        if not list_texts:
            logger.warning("Batch deputati vuoto (strano). Skip.")
            continue

        try:
            embeddings_list = embedder.embed_texts(list_texts)
            emb_map = dict(zip(list_texts, embeddings_list))
        except Exception as e:
            logger.error(f"Errore durante embedding batch deputati: {e}")
            time.sleep(5)
            continue

        updates_in_batch = 0
        for r in batch_dep:
            sets = []
            params = {'id': r['id']}

            # Profession
            if r['profession'] and r['profession'] in emb_map:
                 emb_val = emb_map[r['profession']]
                 if any(emb_val):
                     params['e_prof'] = emb_val.tolist()
                     sets.append("d.profession_embedding = $e_prof")

            # Education
            if r['education'] and r['education'] in emb_map:
                 emb_val = emb_map[r['education']]
                 if any(emb_val):
                     params['e_edu'] = emb_val.tolist()
                     sets.append("d.education_embedding = $e_edu")

            if sets:
                q_upd = f"MATCH (d:Deputy) WHERE elementId(d) = $id SET {', '.join(sets)}"
                neo4j.query(q_upd, params)
                updates_in_batch += 1

        processed_dep += len(batch_dep)
        logger.info(f"Deputati processati finora: {processed_dep} (Batch: {updates_in_batch} updates)")

    # ---------------------------------------------------------
    # 5. Speeches (text_embedding for authority scoring)
    # ---------------------------------------------------------
    logger.info("\n--- FASE 5: SPEECHES (text_embedding per authority scoring) ---")
    BATCH_SIZE_SPEECH = 100
    # Max chars to embed per speech: enough to capture the topic, affordable in tokens.
    SPEECH_TEXT_LIMIT = 2000
    processed_speech = 0

    try:
        total_speech = neo4j.query_single(
            "MATCH (sp:Speech) WHERE sp.text IS NOT NULL AND sp.text <> '' RETURN count(sp) as cnt"
        )['cnt']
        done_speech = neo4j.query_single(
            "MATCH (sp:Speech) WHERE sp.text_embedding IS NOT NULL RETURN count(sp) as cnt"
        )['cnt']
        logger.info(f"Stato Speech: {done_speech}/{total_speech} con text_embedding.")
    except Exception as e:
        logger.warning(f"Impossibile contare Speech: {e}")

    while True:
        batch_speeches = neo4j.query(
            """
            MATCH (sp:Speech)
            WHERE sp.text IS NOT NULL AND sp.text <> '' AND sp.text_embedding IS NULL
            RETURN elementId(sp) AS eid, sp.text AS text
            LIMIT $limit
            """,
            {'limit': BATCH_SIZE_SPEECH}
        )

        if not batch_speeches:
            logger.info("Nessun altro Speech da elaborare.")
            break

        # Truncate each text to SPEECH_TEXT_LIMIT chars before embedding.
        # Parliamentary speeches can be very long; the first portion already
        # carries the topical signal needed for authority scoring.
        texts_to_embed = [r['text'][:SPEECH_TEXT_LIMIT] for r in batch_speeches]

        try:
            embeddings_list = embedder.embed_texts(texts_to_embed)
        except Exception as e:
            logger.error(f"Errore embedding Speech batch: {e}")
            time.sleep(5)
            continue

        updates_in_batch = 0
        for r, emb_arr in zip(batch_speeches, embeddings_list):
            if any(emb_arr):
                # Schema v2 (C2): lista nativa, non JSON string
                neo4j.query(
                    "MATCH (sp:Speech) WHERE elementId(sp) = $eid SET sp.text_embedding = $emb",
                    {'eid': r['eid'], 'emb': emb_arr.tolist()}
                )
                updates_in_batch += 1

        processed_speech += len(batch_speeches)
        logger.info(
            f"Speeches processati finora: {processed_speech} "
            f"(Batch: {updates_in_batch} updates)"
        )

    logger.info("=== PRE-CALCOLO COMPLETATO ===")

if __name__ == "__main__":
    main()
