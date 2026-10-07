---
license: cc-by-sa-4.0
language:
  - it
pretty_name: "ParliamentRAG — Italian Chamber of Deputies, 19th legislature"
size_categories:
  - 1M<n<10M
task_categories:
  - text-retrieval
  - question-answering
tags:
  - parliament
  - politics
  - italy
  - legal
  - knowledge-graph
  - rag
configs:
  - config_name: speeches
    data_files: speeches.parquet
    default: true
  - config_name: sessions
    data_files: sessions.parquet
  - config_name: debates
    data_files: debates.parquet
  - config_name: votes
    data_files: votes.parquet
  - config_name: individual_votes
    data_files: individual_votes.parquet
  - config_name: persons
    data_files: persons.parquet
  - config_name: organizations
    data_files: organizations.parquet
  - config_name: memberships
    data_files: memberships.parquet
  - config_name: acts
    data_files: acts.parquet
  - config_name: act_subjects
    data_files: act_subjects.parquet
  - config_name: speech_references
    data_files: speech_references.parquet
---

# ParliamentRAG — Italian Chamber of Deputies, 19th legislature

Full proceedings of the Italian Chamber of Deputies (Camera dei deputati) for the 19th legislature, from the first sitting on 13 October 2022 through {{MAX_DATE}}: verbatim speech transcripts, roll-call votes with every individual ballot, parliamentary acts with EuroVoc subjects, and the deputies' group, committee and government memberships over time. The dataset is refreshed as new sittings are ingested.

The tables are the flattened form of the ParliamentRAG knowledge graph, built from the official open data of the Chamber ([dati.camera.it](https://dati.camera.it)) and the stenographic reports of each sitting. The same graph powers the live system at [parliamentrag.it](https://www.parliamentrag.it) and the paper *Who Speaks Matters: Authority-Aware Multi-View RAG over Italian Parliamentary Proceedings* ([arXiv:2608.13410](https://arxiv.org/abs/2608.13410)). An RDF version of the graph is archived on Zenodo: [10.5281/zenodo.21560331](https://doi.org/10.5281/zenodo.21560331).

All content is in Italian, except the session and debate recaps, which exist in both Italian and English.

## Tables

| Table | Rows | Contents |
| --- | ---: | --- |
| `speeches` | {{ROWS_SPEECHES}} | Verbatim transcript of every speech, with date, debate title, phase and speaker |
| `sessions` | {{ROWS_SESSIONS}} | Plenary sittings, with Italian and English recaps |
| `debates` | {{ROWS_DEBATES}} | Agenda items of each sitting, with recaps |
| `votes` | {{ROWS_VOTES}} | Roll-call votes: subject, outcome, numeric breakdown, linked acts |
| `individual_votes` | {{ROWS_INDIVIDUAL_VOTES}} | One row per (deputy, vote) with the individual ballot |
| `persons` | {{ROWS_PERSONS}} | Deputies and government members: profession, education, roles |
| `organizations` | {{ROWS_ORGANIZATIONS}} | Parliamentary groups, committees, Gruppo Misto components, government |
| `memberships` | {{ROWS_MEMBERSHIPS}} | Person–organization spells with start/end dates and offices held |
| `acts` | {{ROWS_ACTS}} | Bills, motions, interpellations, resolutions and other acts |
| `act_subjects` | {{ROWS_ACT_SUBJECTS}} | Act → EuroVoc concept links |
| `speech_references` | {{ROWS_SPEECH_REFERENCES}} | NER-resolved mentions of persons and citations of acts in speeches |

Row identifiers are shared across tables: `session_id` (e.g. `leg19_sed1`), `vote_id`, `speech_id`, `person_id` (the dati.camera.it person URI) and `act_uri` join the tables together. Speeches are ordered as delivered (session date, debate order, phase order).

Individual ballot outcomes in `individual_votes` are `favor`, `against`, `abstain`, `absent`. For secret ballots (`secret_vote = true` in `votes`) only participation is recorded (`absent`, `abstain`): who voted for or against is not public, so those votes carry aggregate numbers only.

## Example

```python
from datasets import load_dataset

speeches = load_dataset("emeierkeio/parliamentrag-camera-leg19", "speeches", split="train")
votes = load_dataset("emeierkeio/parliamentrag-camera-leg19", "votes", split="train")
```

## Provenance and construction

Sources:

- [dati.camera.it](https://dati.camera.it) SPARQL endpoint (OCD ontology): deputies, mandates, groups, committees, acts, votes — CC BY-SA 4.0.
- Stenographic reports of the Chamber (XML): speech transcripts, debate structure.
- [EuroVoc](https://eurovoc.europa.eu): multilingual subject thesaurus of the EU.

The build pipeline (download, parsing, entity resolution, NER linking) is open source: [github.com/Emeierkeio/parliamentrag-iswc](https://github.com/Emeierkeio/parliamentrag-iswc). This export is produced by `build/export_hf.py` in that repository. Session and debate recaps are LLM-generated summaries and are marked as such; everything else comes from the official record.

Known limits:

- Chamber of Deputies only; Senate sittings are not included.
- {{ACTS_PLACEHOLDERS}} acts are placeholders (`is_placeholder = true`): they are referenced by debates or votes but not yet resolved to their full record (mostly number-format variants and committee versions of bills; a small share of chamber documents has no machine-readable record at the source).
- Speaker attribution is missing for {{SPEECHES_NO_SPEAKER}} speeches where the stenographic report does not identify the speaker.
- Recaps are generated for sessions ingested after summarization was introduced (mid-2026): {{SESSIONS_WITH_RECAP}} of {{ROWS_SESSIONS}} sessions and {{DEBATES_WITH_RECAP}} of {{ROWS_DEBATES}} debates have them; the rest have `null` recaps.

## License and attribution

[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), inherited from the source data of the Camera dei deputati (ShareAlike: derivatives of this dataset must keep the same license). If you use this dataset, attribute both the Chamber (source data) and ParliamentRAG (derived dataset), and cite:

```bibtex
@inproceedings{tritella2026parliamentrag,
  title     = {Who Speaks Matters: Authority-Aware Multi-View RAG over Italian Parliamentary Proceedings},
  author    = {Tritella, Mirko and Pozzi, Riccardo and Palmonari, Matteo},
  booktitle = {The Semantic Web -- ISWC 2026},
  year      = {2026}
}
```
