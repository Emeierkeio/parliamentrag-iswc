# Knowledge Graph Construction Pipeline

Builds the parliamentary knowledge graph (schema v2) in Neo4j from official
open data: Camera/Senato verbatim transcripts (Akoma Ntoso XML), deputy and
senator registries (CSV), parliamentary acts, EuroVoc subjects, and roll-call
votes (SPARQL endpoints of dati.camera.it and dati.senato.it).

## Entry points

Everything is orchestrated by the CLI:

```bash
python build/build_and_update.py build    # full build from scratch
python build/build_and_update.py update   # incremental update (new sessions)
```

or via the Makefile targets at repo root (credentials read from `.env`):

```bash
make db-populate        # full DB build
make db-update-all      # incremental: Camera + Senato + votes + summaries + citability
make enrich-sparql      # votes and committee roles from SPARQL
make generate-summaries # AI recaps for sessions/debates/speakers (resumable)
```

## Nightly update

`build/nightly.sh` runs `update_data.sh` on the VPS that hosts Neo4j: it
resets the checkout to `origin/main`, talks to Neo4j on localhost, skips the
local snapshot and the Hugging Face upload, and keeps 30 days of logs in
`build/logs/`. Cron entry (03:30 Europe/Rome):

```cron
CRON_TZ=Europe/Rome
30 3 * * * /opt/parliamentrag-job/build/nightly.sh >> /var/log/parliamentrag-nightly.log 2>&1
```

## Validation gate

Every build/update ends with the invariant suite:

```bash
python build/validate_db.py --neo4j-uri bolt://localhost:7689 \
  --neo4j-user neo4j --neo4j-password $NEO4J_PASSWORD
```

Hard invariants (build fails otherwise): native (non-string) embeddings and
dates, populated vector indexes, every Chunk an exact substring of its Speech,
every Speech linked to a speaker, Linked Data URIs conforming to the source
dataset patterns (dati.camera.it/ocd/…, eurovoc.europa.eu/…).

## Module map

| Module | Role |
|---|---|
| `build_and_update.py` | CLI orchestrator (build / update) |
| `xml_parser.py`, `senate_parser.py` | Akoma Ntoso / stenographic XML parsing |
| `chunker.py`, `ner.py` | text segmentation and entity extraction |
| `csv_loader.py` | deputy/senator registry loading + date helpers |
| `db_builder.py` | all Neo4j writes (nodes, relationships, indexes) |
| `sparql_ingester.py`, `senate_sparql_ingester.py` | aggregate + individual votes, committee roles |
| `ingest_atti_parlamentari.py` | parliamentary acts + EuroVoc subjects |
| `repair_bills.py` | presentation dates and topic embeddings (from the title) for Chamber bills |
| `ingest_misto_componenti.py` | political components of the Gruppo Misto |
| `classify_chunk_citability.py` | LLM batch classification of chunk citability |
| `generate_summaries.py` | AI recaps (IT/EN) for timeline |
| `precalculate_embeddings.py`, `embedding_service.py` | OpenAI embeddings with local cache |
| `validate_db.py` | post-build invariant gate |
| `export_rdf.py` | RDF export of the KG (Linked Data deliverable, `make export-rdf`) |
| `download_emendamenti_camera.py` | Chamber amendment XMLs, one file per bill |
| `download_emendamenti_senato.py` | Senate readings (SPARQL) and committee amendment pages |
| `download_esiti_senato.py` | Senate amendment outcomes and the floor texts missing from Akoma Ntoso |
| `parse_emendamenti.py` | both chambers' amendments in one JSONL (`downloads/emendamenti/`) |

## Notes

- Embeddings are cached in a local SQLite database (`embeddings_cache.db`,
  git-ignored): rebuilding with unchanged texts costs ~zero API calls.
- Credentials are never hardcoded: set `NEO4J_PASSWORD` and `OPENAI_API_KEY`
  in `.env` or the environment.
- Amendments (XIX): `make update-data` downloads only bills that are new or
  whose status changed in the last 14 days, pulls the Senate Akoma Ntoso bulk
  data ([SenatoDellaRepubblica/AkomaNtosoBulkData](https://github.com/SenatoDellaRepubblica/AkomaNtosoBulkData))
  and rebuilds the JSONL. The files stay in `downloads/` (not versioned) and
  are not loaded into the graph yet. senato.it is behind an AWS WAF challenge,
  solved with Playwright (`playwright install chromium`), and blocks the IP
  for a few hours if requests come too fast: keep at least 2 s between them.
- Tests: `pytest build/tests/` (integration tests need a running Neo4j and
  `NEO4J_PASSWORD` set).
