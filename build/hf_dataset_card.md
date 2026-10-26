---
license: cc-by-sa-4.0
language:
  - it
pretty_name: "ParliamentRAG — Italian Parliament, 19th legislature"
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

# ParliamentRAG — Italian Parliament, 19th legislature

Plenary proceedings of both houses of the Italian Parliament, the Chamber of Deputies (Camera dei deputati) and the Senate (Senato della Repubblica), for the 19th legislature, from the first sittings on 13 October 2022 through {{MAX_DATE}}: verbatim speech transcripts, roll-call votes with every individual ballot, parliamentary acts with EuroVoc subjects, and the members' group, committee and government memberships over time. The Chamber has {{SESSIONS_CAMERA}} sittings, the Senate {{SESSIONS_SENATO}} ({{SPEECHES_SENATO}} speeches, {{VOTES_SENATO}} roll-call votes). The dataset is refreshed as new sittings are ingested.

The tables are the flattened form of the ParliamentRAG knowledge graph, built from the official open data of the two houses ([dati.camera.it](https://dati.camera.it), [dati.senato.it](https://dati.senato.it)) and the stenographic reports of each sitting. The same graph powers the live system at [parliamentrag.it](https://www.parliamentrag.it) and the paper *Who Speaks Matters: Authority-Aware Multi-View RAG over Italian Parliamentary Proceedings* ([arXiv:2608.13410](https://arxiv.org/abs/2608.13410)). An RDF version of the graph is archived on Zenodo: [10.5281/zenodo.21560331](https://doi.org/10.5281/zenodo.21560331).

All content is in Italian, except the session and debate recaps, which exist in both Italian and English.

## Tables

| Table | Rows | Contents |
| --- | ---: | --- |
| `speeches` | {{ROWS_SPEECHES}} | Verbatim transcript of every speech, with date, debate title, phase, speaker and link to the official record |
| `sessions` | {{ROWS_SESSIONS}} | Plenary sittings, with the link to their record and Italian and English recaps |
| `debates` | {{ROWS_DEBATES}} | Agenda items of each sitting, with recaps |
| `votes` | {{ROWS_VOTES}} | Roll-call votes: subject, outcome, numeric breakdown, linked acts |
| `individual_votes` | {{ROWS_INDIVIDUAL_VOTES}} | One row per (member, vote) with the individual ballot |
| `persons` | {{ROWS_PERSONS}} | Deputies, senators and government members: profession, education, roles |
| `organizations` | {{ROWS_ORGANIZATIONS}} | Parliamentary groups, committees, Gruppo Misto components, government |
| `memberships` | {{ROWS_MEMBERSHIPS}} | Person–organization spells with start/end dates and offices held |
| `acts` | {{ROWS_ACTS}} | Bills, motions, interpellations, resolutions and other acts |
| `act_subjects` | {{ROWS_ACT_SUBJECTS}} | Act → EuroVoc concept links |
| `speech_references` | {{ROWS_SPEECH_REFERENCES}} | NER-resolved mentions of persons and citations of acts in speeches |

Row identifiers are shared across tables: `session_id` (e.g. `leg19_sed1` for the Chamber, `sen_leg19_sed1` for the Senate), `vote_id`, `speech_id`, `person_id` (the dati.camera.it or dati.senato.it person URI; `gov_…` for government members; in Senate speeches and memberships a person is always named by the Senate URI, which `persons` gives in `senato_id` for the senators who also sat in the Chamber or in the government) and `act_uri` join the tables together. The `chamber` column (`camera`, `senato`, `bicamerale` for joint committees) tells the two houses apart. Speeches are ordered as delivered (session date, debate order, phase order).

Individual ballot outcomes in `individual_votes` are `favor`, `against`, `abstain`, `absent`. The Senate publishes only the senators who took part in a vote, so Senate ballots have no `absent` rows. For secret ballots (`secret_vote = true` in `votes`) only participation is recorded (`absent`, `abstain`): who voted for or against is not public, so those votes carry aggregate numbers only.

## Example

```python
from datasets import load_dataset

speeches = load_dataset("{{HF_REPO}}", "speeches", split="train")
votes = load_dataset("{{HF_REPO}}", "votes", split="train")
senate_speeches = speeches.filter(lambda row: row["chamber"] == "senato")
```

## Provenance and construction

Sources:

- [dati.camera.it](https://dati.camera.it) SPARQL endpoint (OCD ontology): deputies, mandates, groups, committees, acts, votes — CC BY-SA 4.0.
- Stenographic reports of the Chamber (XML): speech transcripts, debate structure.
- [dati.senato.it](https://dati.senato.it) SPARQL endpoint (OSR ontology): senators, groups, committees, bills, votes — CC BY 3.0.
- Stenographic reports of the Senate (senato.it): speech transcripts, debate structure.
- [EuroVoc](https://eurovoc.europa.eu): multilingual subject thesaurus of the EU.

The build pipeline (download, parsing, entity resolution, NER linking) is open source: [github.com/Emeierkeio/parliamentrag-iswc](https://github.com/Emeierkeio/parliamentrag-iswc). This export is produced by `build/export_hf.py` in that repository. Session and debate recaps are LLM-generated summaries and are marked as such; everything else comes from the official record.

Known limits:

- Plenary sittings only; committee proceedings are not included.
- {{ACTS_PLACEHOLDERS}} acts are placeholders (`is_placeholder = true`): they are referenced by debates or votes but not yet resolved to their full record (mostly number-format variants and committee versions of bills; a small share of chamber documents has no machine-readable record at the source).
- Speaker attribution is missing for {{SPEECHES_NO_SPEAKER}} speeches where the stenographic report does not identify the speaker.
- Recaps are not yet available for every sitting: {{SESSIONS_WITH_RECAP}} of {{ROWS_SESSIONS}} sessions and {{DEBATES_WITH_RECAP}} of {{ROWS_DEBATES}} debates have them; the rest have `null` recaps.

## License and attribution

[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), inherited from the source data of the Camera dei deputati (ShareAlike: derivatives of this dataset must keep the same license). The Senate data are released under CC BY 3.0, which allows this license on the combined dataset. If you use this dataset, attribute the Camera dei deputati and the Senato della Repubblica (source data) and ParliamentRAG (derived dataset), and cite:

```bibtex
@inproceedings{tritella2026parliamentrag,
  title     = {Who Speaks Matters: Authority-Aware Multi-View RAG over Italian Parliamentary Proceedings},
  author    = {Tritella, Mirko and Pozzi, Riccardo and Palmonari, Matteo},
  booktitle = {The Semantic Web -- ISWC 2026},
  publisher = {Springer},
  year      = {2026},
  doi       = {10.1007/978-3-032-42029-9_24}
}
```
