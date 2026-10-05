#!/usr/bin/env python3
"""
Build the Camera <-> Senato person crosswalk: data/persone_camera_senato.csv.

Columns: senatore (dati.senato.it URI), persona (dati.camera.it persona URI),
source ("senato" or "wikidata").

Primary source is dati.senato.it, which records the Camera mandates of every
senator as ocd:mandatoCamera resources with owl:sameAs to the Camera deputato
URI (d{persona}_{legislature}). Wikidata pairs P2549 (Senato ID) with P1341
(Camera ID) and fills senators whose Camera mandate the Senate does not list.
When the two disagree the Senate wins.
"""

from __future__ import annotations

import csv
import os
import re
import sys

import requests

from download_senators_csv import DATA_DIR, sparql_query

OUTPUT = os.path.join(DATA_DIR, "persone_camera_senato.csv")

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
WIKIDATA_HEADERS = {
    "User-Agent": "ParliamentRAG/1.0 (https://github.com/Emeierkeio/ParliamentRAG)",
    "Accept": "application/sparql-results+json",
}

SENATE_QUERY = """
PREFIX osr: <http://dati.senato.it/osr/>
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
SELECT DISTINCT ?senatore ?deputato WHERE {
  ?senatore osr:mandato ?m .
  ?m a ocd:mandatoCamera ; owl:sameAs ?deputato .
}
"""

WIKIDATA_QUERY = """
SELECT DISTINCT ?sen ?cam WHERE { ?p wdt:P2549 ?sen ; wdt:P1341 ?cam . }
"""

# Republic-era deputato URIs: d{persona}_{leg}. Older ones (dd00006_13) do
# not carry the persona number and are skipped.
_DEPUTATO_RE = re.compile(r"deputato\.rdf/d(\d+)_\d+$")

SENATORE_URI = "http://dati.senato.it/senatore/{}"
PERSONA_URI = "http://dati.camera.it/ocd/persona.rdf/p{}"


def senate_pairs() -> dict[str, str]:
    pairs: dict[str, str] = {}
    for row in sparql_query(SENATE_QUERY):
        m = _DEPUTATO_RE.search(row["deputato"])
        if m:
            pairs[row["senatore"]] = PERSONA_URI.format(m.group(1))
    return pairs


def wikidata_pairs() -> dict[str, str]:
    resp = requests.get(
        WIKIDATA_ENDPOINT, params={"query": WIKIDATA_QUERY},
        headers=WIKIDATA_HEADERS, timeout=180,
    )
    resp.raise_for_status()
    pairs: dict[str, str] = {}
    for b in resp.json()["results"]["bindings"]:
        sen, cam = b["sen"]["value"], b["cam"]["value"]
        if sen.isdigit() and cam.isdigit():
            pairs[SENATORE_URI.format(sen)] = PERSONA_URI.format(cam)
    return pairs


def main() -> None:
    senate = senate_pairs()
    print(f"dati.senato.it: {len(senate)} senators with a Camera mandate")
    try:
        wiki = wikidata_pairs()
    except requests.RequestException as exc:
        print(f"Wikidata unavailable ({exc}); writing Senate pairs only", file=sys.stderr)
        wiki = {}
    disagreements = {s for s in senate.keys() & wiki.keys() if senate[s] != wiki[s]}
    if disagreements:
        print(f"Senate and Wikidata disagree on {len(disagreements)} senators; keeping Senate")

    rows = [(s, p, "senato") for s, p in senate.items()]
    rows += [(s, p, "wikidata") for s, p in wiki.items() if s not in senate]

    # A Camera persona mapped to two senators would merge two people.
    by_persona: dict[str, list[str]] = {}
    for s, p, _ in rows:
        by_persona.setdefault(p, []).append(s)
    ambiguous = {p for p, sens in by_persona.items() if len(sens) > 1}
    if ambiguous:
        print(f"Dropping {len(ambiguous)} Camera personas linked to several senators")
    rows = [r for r in rows if r[1] not in ambiguous]

    with open(OUTPUT, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["senatore", "persona", "source"])
        w.writerows(sorted(rows))
    print(f"Wrote {len(rows)} pairs -> {OUTPUT}")


if __name__ == "__main__":
    main()
