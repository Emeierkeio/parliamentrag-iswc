#!/usr/bin/env python3
"""
Download government composition from dati.camera.it: data/governi_{roman}.csv.

One row per office held (ocd:membroGoverno): government, Camera persona URI,
office label, office type and dates. Every member has a Camera persona URI,
parliamentarian or not, and it is the same id the stenographic XML carries in
<nominativo id>, so speeches by non-parliamentarian ministers can be linked.

Usage:
    python build/download_governments_csv.py --legislature 18
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time

import requests

SPARQL_ENDPOINT = "https://dati.camera.it/sparql"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {17: "xvii", 18: "xviii", 19: "xix", 20: "xx"}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ParliamentRAG/1.0)"}

QUERY = """
PREFIX ocd: <http://dati.camera.it/ocd/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
PREFIX foaf: <http://xmlns.com/foaf/0.1/>
SELECT DISTINCT ?governo ?governoLabel ?governoEnd ?membro ?persona ?nome ?cognome
                ?carica ?tipo ?start ?end WHERE {
  ?governo a ocd:governo ;
           ocd:rif_leg <http://dati.camera.it/ocd/legislatura.rdf/repubblica_%(leg)d> ;
           rdfs:label ?governoLabel ;
           ocd:rif_membroGoverno ?membro .
  OPTIONAL { ?governo ocd:endDate ?governoEnd }
  ?membro ocd:rif_persona ?persona ;
          rdfs:label ?carica ;
          ocd:membroGoverno ?tipo ;
          ocd:startDate ?start .
  OPTIONAL { ?membro ocd:endDate ?end }
  OPTIONAL { ?membro foaf:firstName ?nome }
  OPTIONAL { ?membro foaf:surname ?cognome }
}
"""

# Labels end with the office dates: "Vice Ministro dell'Economia (26.04.2021)"
_DATES_SUFFIX = re.compile(r"\s*\([\d.\s-]+\)\s*$")
# Government labels carry the start date: "I Governo Draghi (12.02.2021 - 21.10.2022)"
_GOV_START = re.compile(r"\((\d{2})\.(\d{2})\.(\d{4})")

FIELDS = [
    "governo", "governoLabel", "governoStart", "governoEnd", "membro", "persona",
    "nome", "cognome", "carica", "tipo", "start", "end",
]


def fetch(legislature: int, retries: int = 4) -> list[dict]:
    params = {"query": QUERY % {"leg": legislature}, "format": "json"}
    for attempt in range(retries):
        try:
            resp = requests.get(SPARQL_ENDPOINT, params=params, headers=HEADERS, timeout=180)
            resp.raise_for_status()
            return [
                {k: v["value"] for k, v in b.items()}
                for b in resp.json()["results"]["bindings"]
            ]
        except (requests.RequestException, ValueError):
            # dati.camera.it answers 502/504 under load; it recovers within minutes.
            if attempt == retries - 1:
                raise
            time.sleep(30 * (attempt + 1))
    return []


def main(legislature: int) -> str:
    rows = fetch(legislature)
    out: list[dict] = []
    for r in rows:
        m = _GOV_START.search(r["governoLabel"])
        out.append({
            "governo": r["governo"],
            "governoLabel": _DATES_SUFFIX.sub("", r["governoLabel"]),
            "governoStart": f"{m.group(3)}{m.group(2)}{m.group(1)}" if m else "",
            "governoEnd": r.get("governoEnd", ""),
            "membro": r["membro"],
            "persona": r["persona"],
            "nome": r.get("nome", ""),
            "cognome": r.get("cognome", ""),
            "carica": _DATES_SUFFIX.sub("", r["carica"]),
            "tipo": r["tipo"],
            "start": r["start"],
            "end": r.get("end", ""),
        })
    out.sort(key=lambda r: (r["governo"], r["start"], r["cognome"], r["carica"]))
    path = os.path.join(DATA_DIR, f"governi_{ROMAN[legislature]}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(out)
    print(f"Wrote {len(out)} offices -> {path}")
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislature", type=int, default=19)
    main(ap.parse_args().legislature)
