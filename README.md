<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/logo-lockup-cream.svg">
    <img src="assets/logo-lockup-blue.svg" alt="ParliamentRAG" width="380">
  </picture>
</p>

<p align="center">
  <a href="https://truthful-amazement-production.up.railway.app"><img alt="ISWC 2026 live demo" src="https://img.shields.io/badge/Live_demo-ISWC_2026-1E3A5F?style=flat-square"></a>
  <a href="https://doi.org/10.5281/zenodo.23173703"><img alt="Source code on Zenodo" src="https://img.shields.io/badge/Code-Zenodo_DOI-1682D4?style=flat-square&logo=zenodo&logoColor=white"></a>
  <a href="https://iswc2026.semanticweb.org"><img alt="Two papers accepted at ISWC 2026" src="https://img.shields.io/badge/ISWC_2026-In--Use_%2B_Demo_papers-6A4C93?style=flat-square"></a>
  <a href="https://doi.org/10.5281/zenodo.21560331"><img alt="RDF dataset on Zenodo" src="https://img.shields.io/badge/Dataset-Zenodo_DOI-1682D4?style=flat-square&logo=zenodo&logoColor=white"></a>
  <a href="https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19"><img alt="Dataset on Hugging Face" src="https://img.shields.io/badge/Dataset-Hugging_Face-FFD21E?style=flat-square&logo=huggingface&logoColor=black"></a>
  <a href="LICENSE"><img alt="Code license Apache 2.0" src="https://img.shields.io/badge/Code-Apache_2.0-0969DA?style=flat-square"></a>
  <a href="https://creativecommons.org/licenses/by-sa/4.0/"><img alt="Data license CC BY-SA 4.0" src="https://img.shields.io/badge/Data-CC_BY--SA_4.0-97CA00?style=flat-square&logo=creativecommons&logoColor=white"></a>
</p>

> [!NOTE]
> **You are looking at the code of the ISWC 2026 papers.** The papers cite `github.com/Emeierkeio/ParliamentRAG`; since 6 October 2026 that name points to the project website ([Emeierkeio/ParliamentRAG](https://github.com/Emeierkeio/ParliamentRAG), [parliamentrag.it](https://www.parliamentrag.it)). Tag [`iswc2026-eval`](https://github.com/Emeierkeio/parliamentrag-iswc/tree/iswc2026-eval) holds the code that generated the evaluated answers, tag [`iswc2026-demo`](https://github.com/Emeierkeio/parliamentrag-iswc/tree/iswc2026-demo) the demo. Zenodo archives both under DOI [10.5281/zenodo.23173703](https://doi.org/10.5281/zenodo.23173703). For the tools built on this code, see [Fascicoli](https://www.fascicoli.it), [Stenografo](https://www.stenografo.it) and [Scranno](https://www.scranno.it).

**Balanced, verifiable answers about Italian parliamentary debate, grounded in what was actually said and by whom.**

ParliamentRAG is an authority-aware, multi-view Retrieval-Augmented Generation system over the stenographic records of the Camera dei Deputati (XIX Legislature). Ask a policy question and get an answer that covers every parliamentary group, majority and opposition alike, with verbatim citations checked against the original transcripts.

<!-- screenshot: chat view with expert cards, citations, and ideological compass -->

- **176k+ text chunks** from **716 plenary sessions**, updated through 2026-09-30
- **17.5k roll-call votes** with **7M individual vote records** linked to deputies
- **Verified citations**: every quote is checked verbatim against its source chunk; unverifiable quotes are removed
- **Topic-aware authority scoring**: the system picks the most credible speaker per party for the specific question asked
- **6 languages** (IT / EN / FR / DE / ES / PT), editorial newspaper-style UI

---

## Why

LLM summaries of parliamentary activity tend to favour dominant actors, quote out of context, and flatten disagreement. ParliamentRAG treats what is said and who says it as equally important: retrieval, generation, and presentation all have to cover the whole range of parliamentary groups, and every claim points to a verifiable span of the official record.

---

## System architecture

<p align="center"><img src="assets/architecture.svg" alt="System architecture — Next.js frontend, FastAPI backend, Neo4j graph store" width="860"/></p>

### Query pipeline

Each question runs through a single streamed pipeline; the frontend renders progress as an 8-step stepper.

<p align="center"><img src="assets/pipeline.svg" alt="Query pipeline — 8 steps" width="920"/></p>

1. **Query analysis**: the question is classified and, if short or ambiguous, rewritten for retrieval.
2. **Committee matching**: the query is mapped to the relevant parliamentary committees.
3. **Expert selection**: for each parliamentary group, the top speaker is chosen by a **query-specific authority score** with six components: profession, education, committee membership, legislative acts, speech interventions, institutional role (semantic components use the query embedding; activity components are time-decayed).
4. **Multi-view retrieval**: a dense channel (vector similarity over `text-embedding-3-small` embeddings) and a graph channel (lexical + semantic matching over the knowledge graph) are fused by a weighted merger balancing relevance, party coverage, speaker diversity, and political salience.
5. **Balance metrics**: coverage and balance statistics are computed over the retrieved evidence.
6. **Ideological compass**: parliamentary groups are placed on two axes anchored to the question. The opposing poles of each axis (e.g. "more public spending" vs. "budget rigour") are generated per query and embedded with the same model as the evidence, so the axes are readable by construction and stable across recomputations.
7. **Generation**: a multi-stage writer produces a narrative that explicitly represents both majority and opposition positions. Quotes are picked from a deterministic set of verbatim candidates, and the final assembly preserves citation markers by construction.
8. **Citation verification**: every quotation is matched verbatim against its source chunk and coherence-scored; anything that cannot be verified is stripped from the answer.

### Models

| Role | Model |
|---|---|
| Writer / Integrator | `gpt-4.1` |
| Analyst (claim decomposition) | `gpt-4.1-mini` |
| Quote picker (verbatim candidate selection) | `gpt-5.6-luna` |
| Query rewriter / compass poles | `gpt-5.6-luna` |
| UI translations | `gpt-4.1-nano` |
| Embeddings (all semantic operations) | `text-embedding-3-small` (1536-d, Neo4j native vector index) |

---

## Features

| Page | What it does |
|---|---|
| `/` | Landing page |
| `/home` (chat) | Ask questions; streamed 8-step progress, per-party sections, **verified citation cards** with full stenographic text in a modal, **expert cards** with authority-score breakdown, inline ideological compass |
| `/search` | Search acts and records; filter by deputy or group, or browse an author's full record without a query |
| `/parlamentari` | Deputy directory (alphabetical index) and profiles: group history with periods, committees and offices, floor activity, recent speeches expandable in place |
| `/gruppi` | Parliamentary groups with official logos, membership counts, and per-group member lists |
| `/ranking` | Topic-dependent authority rankings of deputies |
| `/compass` | Standalone ideological compass for any topic |
| `/timeline` | **Lavori d'Aula**: browse sessions → debates → phases → speakers, with AI-generated IT/EN recaps per session and debate, per-speaker position summaries, roll-call detail (per-group breakdown + individual votes, searchable), infinite scroll, and search + date filters |
| `/valutazione` | Evaluation dashboard: automated metrics and blind A/B comparison vs. a baseline LLM |
| `/explorer` | Interactive knowledge-graph exploration |
| `/data` | Open-data page: live graph statistics, ontology alignment for non-specialists, RDF dumps |

**UI**: editorial newspaper-style design (Fraunces serif), light/dark themes, mobile bottom navigation, and full internationalization in 6 languages (`frontend/messages/{it,en,fr,de,es,pt}.json` via `next-intl`).

---

## Knowledge graph

The graph (schema v2) is built from **official open data**: stenographic XML
reports (Akoma Ntoso) and the SPARQL endpoints of
[dati.camera.it](https://dati.camera.it/) (deputies, groups, committees, acts,
roles, votes), with EuroVoc subject links for parliamentary acts.

- **XIX Legislature, data as of 2026-09-30** (updated incrementally): 716 sessions · 47.4k speeches · 176k+ chunks · 36.5k acts · 17.5k roll calls with 7M individual votes
- **Speaker model**: every speaker is a `Person` (labels `Deputy` / `GovernmentMember`), with date-aware group membership; deputies in the Gruppo Misto are attributed to their political component
- **Native types throughout**: embeddings as float arrays in Neo4j vector indexes, dates as `date()` values; every `Chunk` is an exact substring of its `Speech` (verified invariant)
- **Linked Data**: entity URIs conform to the source datasets (dati.camera.it/ocd/…, eurovoc.europa.eu/…) and are dereferenceable
- Every build/update ends with an **invariant validation gate** (`build/validate_db.py`): string embeddings, orphan speeches, broken chunk offsets or malformed URIs fail the build
- **RDF export**: the whole graph is serialized back to RDF (`make export-rdf`; Turtle, plus the 6.3M individual votes in N-Triples) and archived on Zenodo under CC BY-SA 4.0 with DOI [10.5281/zenodo.21560331](https://doi.org/10.5281/zenodo.21560331); project terms use the [w3id.org/parliamentrag](https://w3id.org/parliamentrag/) namespace
- **Hugging Face dataset**: the corpus is also published in tabular form as [emeierkeio/parliamentrag-camera-leg19](https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19) (CC BY-SA 4.0), refreshed via `make export-hf`

The construction pipeline lives in [`build/`](build/README.md):

```bash
make db-populate        # full build from scratch
make db-update-all      # incremental: new sessions + votes + summaries + citability
make update-data        # demo-oriented incremental update + graph repairs
```

<p align="center"><img src="assets/kg-schema.svg" alt="Knowledge graph schema v2" width="820"/></p>

<p align="center"><img src="assets/kg-instance.svg" alt="Real neighbourhood from the live knowledge graph" width="820"/></p>

---

## Quickstart

**Prerequisites**: Python 3.13+, Node.js 20+, Docker (for a local Neo4j), an OpenAI API key, and a populated Neo4j database.

```bash
# 1. Configure environment
cp .env.example .env   # set OPENAI_API_KEY, NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

# 2. Install backend (venv) + frontend deps
make install

# 3. Run backend (:8000) + frontend (:3000) together
make dev
```

`make dev` picks the next free ports automatically if the defaults are busy; `Ctrl+C` stops both. API docs are served at `http://localhost:8000/docs`.

Other useful targets:

```bash
make dev-backend / make dev-frontend   # run one side only
make stop                              # free the dev ports
make build                             # production build of the frontend
make update-data                       # incremental data ingestion + graph repairs
make db-backup                         # dated dump of the production Neo4j
make db-pull                           # restore latest dump into a local Neo4j (:7691)
make db-use-local / db-use-remote      # switch NEO4J_URI between local copy and production
```

The production instance at [parliamentrag.it](https://www.parliamentrag.it/) auto-deploys from `main` (Railway).

---

## Configuration

### Environment (`.env`)

| Variable | Description |
|---|---|
| `NEO4J_URI` | Bolt connection URI |
| `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j credentials |
| `OPENAI_API_KEY` | Single key, or comma-separated list for rate-limit distribution |
| `LOG_LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `NEXT_PUBLIC_API_URL` | Backend API URL as seen from the browser |

### Algorithmic parameters (`backend/config/default.yaml`)

| Section | Controls |
|---|---|
| `retrieval.dense_channel` / `retrieval.graph_channel` | top-k, similarity thresholds, lexical matching |
| `retrieval.merger` | fusion weights: relevance 0.35, salience 0.25, coverage 0.20, diversity 0.15, authority 0.05 |
| `authority.weights` | interventions 0.25, committee 0.25, acts 0.20, profession 0.15, education 0.10, role 0.05 |
| `authority.time_decay` | half-life for acts and speeches |
| `generation.models` | per-stage model selection |
| `query_rewriting` | short-query expansion (model, word threshold) |
| `coalitions` | majority / opposition group lists |

`backend/config/commissioni_topics.yaml` maps committee names to topic areas for committee-based filtering.

---

## API overview

All routes are mounted under `/api` (interactive docs at `/docs`).

| Endpoint | Description |
|---|---|
| `POST /api/chat` | Streaming query pipeline (SSE: `progress`, `experts`, `citations`, `section`, `compass`, `complete`) |
| `GET /api/evidence/{id}` | Full evidence item with source transcript |
| `GET /api/search` | Parliamentary acts and record search |
| `GET /api/authority` | Topic-dependent authority rankings |
| `POST /api/compass` | Standalone ideological compass |
| `GET /api/timeline` | Sessions, debates, phases, speaker summaries |
| `GET /api/history` | Chat history |
| `GET /api/evaluation/dashboard` | Automated metrics + A/B results |
| `POST /api/surveys` | Submit A/B evaluation |
| `GET /api/graph` | Knowledge-graph exploration |

---

## MCP connector (Claude, ChatGPT and compatible clients)

ParliamentRAG is also a [Model Context Protocol](https://modelcontextprotocol.io)
server: assistants get direct, read-only access to the official records:
hybrid search over speeches and acts, sittings with recaps, roll-call votes
with per-deputy outcomes (filterable by deputy or group), the exact text of
voted amendments, and hemicycle charts rendered as images in the conversation.

**Zero-install (claude.ai, ChatGPT and any remote-MCP client):** add the
hosted endpoint to your assistant's connectors:

```
https://mcp.parliamentrag.it/mcp
```

**Local (Claude Code, Cursor, VS Code, Gemini CLI):**

```bash
claude mcp add parliamentrag -- uv run /path/to/ParliamentRAG/mcp/server.py
```

Ask things like *"come hanno votato i deputati del PD sul voto finale del
DDL 2961?"* or *"mostrami l'emiciclo di quel voto"*, and the answer comes
from the official records instead of model memory. Full setup for every
client: [`mcp/README.md`](mcp/README.md).

---

## Evaluation

The system ships with a two-level evaluation framework over 15 predefined policy topics (`backend/evaluation_set.json`, with pre-computed query-specific baseline experts):

- **Automated metrics** (`/api/evaluation/dashboard`): parliamentary-group coverage, citation relevance and faithfulness, coalition balance, authority distribution, computed for both the system and the baseline on the same topics.
- **Blind A/B protocol** (`/valutazione`): side-by-side comparison of system vs. baseline responses, rated on 9 dimensions on a 1–5 Likert scale. Analysis uses Mann–Whitney U, Cohen's *d*, and Krippendorff's *α* for inter-rater agreement.

In the original study against Google NotebookLM (6 domain experts), the system scored higher on group coverage (97% vs. 95%) and citation faithfulness (100% vs. 95%), with human ratings favouring it on source and balance dimensions (Cohen's *d* up to 0.35) and overall satisfaction at parity. Full details in the paper (see [Citation](#citation)).

---

## Data attribution

Parliamentary data are sourced from the **Camera dei Deputati open data** program ([dati.camera.it](https://dati.camera.it/)), released under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/); the derived RDF and Hugging Face datasets keep the same license. The texts of stenographic reports are official acts of the Italian State and as such are not subject to copyright (art. 5, L. 633/1941). ParliamentRAG is an independent project and is not affiliated with or endorsed by the Camera dei Deputati.

---

## Repository layout

```
backend/    FastAPI app — retrieval, authority scoring, generation, citation verification
frontend/   Next.js app — chat, search, rankings, compass, timeline, evaluation
build/      knowledge-graph construction pipeline + validation gate (see build/README.md)
docs/       LLM prompt reference (papers are served from parliamentrag.it, see Citation)
mcp/        MCP server exposing the public API as Claude tools (see mcp/README.md)
```

---

## Citation

If you use this system or build on this work in academic contexts, please cite
([accepted manuscript](https://www.parliamentrag.it/who-speaks-matters-iswc2026.pdf)):

Accepted at the **In-Use Track of the 25th International Semantic Web Conference (ISWC 2026)**.

```bibtex
@inproceedings{tritella2026whospeaksmatters,
  author    = {Tritella, Mirko and Pozzi, Riccardo and Palmonari, Matteo},
  title     = {Who Speaks Matters: Authority-Aware Multi-View Retrieval-Augmented Generation over Italian Parliamentary Proceedings},
  booktitle = {Proceedings of the 25th International Semantic Web Conference (ISWC 2026), In-Use Track},
  publisher = {Springer},
  year      = {2026},
  note      = {To appear}
}
```

A companion **demo paper** on the live system was accepted at the ISWC 2026 Posters & Demos track; we will add its CEUR-WS citation here once the proceedings are out.

The **RDF dataset** can be cited via its Zenodo DOI: [10.5281/zenodo.21560332](https://doi.org/10.5281/zenodo.21560332) (version used in the paper) or [10.5281/zenodo.21560331](https://doi.org/10.5281/zenodo.21560331) (always the latest version). The same data are also on Hugging Face in tabular form: [emeierkeio/parliamentrag-camera-leg19](https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19).

A machine-readable **semantic description** of the paper (approach, knowledge graph, evaluation, comparison with related systems) is available in the [Open Research Knowledge Graph](https://orkg.org/papers/R1909763).

---

## Acknowledgments

This work was supported by the **EU Horizon Europe** programme through grant
No. [101189771](https://doi.org/10.3030/101189771) ([**DataPACT**](https://datapact.eu/)).

---

## License

[Apache 2.0](LICENSE)
