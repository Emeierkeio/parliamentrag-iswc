#!/usr/bin/env python3
"""
Download deputy data from dati.camera.it via SPARQL for a given legislature
(default XIX). Produces the 3 CSV files required by build_and_update.py:
  - data/deputati_{roman}.csv
  - data/deputati_{roman}_gruppi.csv
  - data/deputati_{roman}_commissioni.csv

Usage:
    python build/download_deputies_csv.py [--legislature 18]
"""

import argparse
import csv
import os
import re
import sys
import time
import requests

SPARQL_ENDPOINT = "https://dati.camera.it/sparql"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HEADERS = {"Accept": "application/sparql-results+json"}

LEG_URI_TEMPLATE = "http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}"

ROMAN = {17: "xvii", 18: "xviii", 19: "xix", 20: "xx"}


def leg_uri(legislature: int) -> str:
    return LEG_URI_TEMPLATE.format(leg=legislature)


def csv_prefix(legislature: int) -> str:
    return f"deputati_{ROMAN.get(legislature, f'leg{legislature}')}"


def clean_label(label: str) -> str:
    """Remove trailing date parenthetical from labels.

    Examples:
        FRATELLI D'ITALIA (18.10.2022)                    -> FRATELLI D'ITALIA
        FRATELLI D'ITALIA (18.10.2022-02.12.2024)         -> FRATELLI D'ITALIA
        COMITATO PER LA LEGISLAZIONE (10.11.2022          -> COMITATO PER LA LEGISLAZIONE
        I COMMISSIONE (AFFARI COSTITUZIONALI, ...) (09.11.2022  -> I COMMISSIONE (AFFARI COSTITUZIONALI, ...)
    """
    if not label:
        return label
    return re.sub(r"\s*\(?(\d{2}\.\d{2}\.\d{4})(?:-\d{2}\.\d{2}\.\d{4})?\)?$", "", label).strip()


def sparql_query(query: str) -> list[dict]:
    """Execute SPARQL query and return list of result dicts."""
    resp = requests.get(SPARQL_ENDPOINT, params={"query": query}, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    bindings = data["results"]["bindings"]
    return [{k: v["value"] for k, v in row.items()} for row in bindings]


def download_deputies(legislature: int = 19) -> list[dict] | None:
    """Download deputy biographical data."""
    print("Downloading deputies...")
    query = f"""
    SELECT DISTINCT ?deputato ?nome ?cognome ?gender ?foto
           ?mandatoCamera ?mandatoStart ?mandatoEnd ?descrizione
    WHERE {{
      ?deputato a <http://xmlns.com/foaf/0.1/Person> ;
               <http://xmlns.com/foaf/0.1/firstName> ?nome ;
               <http://xmlns.com/foaf/0.1/surname> ?cognome ;
               <http://dati.camera.it/ocd/rif_mandatoCamera> ?mandatoCamera .

      ?mandatoCamera <http://dati.camera.it/ocd/rif_leg> <{leg_uri(legislature)}> .

      OPTIONAL {{ ?deputato <http://xmlns.com/foaf/0.1/gender> ?gender }}
      OPTIONAL {{ ?deputato <http://xmlns.com/foaf/0.1/depiction> ?foto }}
      OPTIONAL {{ ?mandatoCamera <http://dati.camera.it/ocd/startDate> ?mandatoStart }}
      OPTIONAL {{ ?mandatoCamera <http://dati.camera.it/ocd/endDate> ?mandatoEnd }}
      OPTIONAL {{ ?deputato <http://purl.org/dc/elements/1.1/description> ?descrizione }}
    }}
    ORDER BY ?cognome ?nome
    """
    try:
        results = sparql_query(query)
        print(f"  Got {len(results)} rows")
        # Derive schedaCamera from URI: persona.rdf/p308421 -> 308421
        for r in results:
            uri = r.get("deputato", "")
            r["schedaCamera"] = uri.rsplit("/", 1)[-1].lstrip("p") if "/persona.rdf/" in uri else ""
        return results
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        return None


def download_groups(legislature: int = 19) -> list[dict] | None:
    """Download parliamentary group membership via ocd:deputato -> ocd:aderisce."""
    print("Downloading parliamentary groups...")
    query = f"""
    SELECT DISTINCT ?deputato ?gruppoLabel ?gruppoStart ?gruppoEnd
    WHERE {{
      ?mandato <http://dati.camera.it/ocd/rif_leg> <{leg_uri(legislature)}> ;
               <http://dati.camera.it/ocd/rif_deputato> ?dep .

      ?dep <http://dati.camera.it/ocd/aderisce> ?adesione .
      ?adesione <http://www.w3.org/2000/01/rdf-schema#label> ?gruppoLabel .

      OPTIONAL {{ ?adesione <http://dati.camera.it/ocd/startDate> ?gruppoStart }}
      OPTIONAL {{ ?adesione <http://dati.camera.it/ocd/endDate> ?gruppoEnd }}

      # Get the persona URI for this deputy
      ?dep <http://dati.camera.it/ocd/rif_mandatoCamera> ?mandato2 .
      ?persona <http://dati.camera.it/ocd/rif_mandatoCamera> ?mandato2 .
      ?persona a <http://xmlns.com/foaf/0.1/Person> .

      BIND(STR(?persona) AS ?deputato)
    }}
    ORDER BY ?deputato ?gruppoStart
    """
    try:
        results = sparql_query(query)
        for r in results:
            r["gruppoLabel"] = clean_label(r.get("gruppoLabel", ""))
        print(f"  Got {len(results)} rows")
        return results
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        # Fallback: simpler query linking via persona directly
        print("  Trying fallback query...")
        query_fallback = f"""
        SELECT DISTINCT ?deputato ?gruppoLabel ?gruppoStart ?gruppoEnd
        WHERE {{
          ?deputato a <http://xmlns.com/foaf/0.1/Person> ;
                   <http://dati.camera.it/ocd/rif_mandatoCamera> ?mandato .
          ?mandato <http://dati.camera.it/ocd/rif_leg> <{leg_uri(legislature)}> ;
                   <http://dati.camera.it/ocd/rif_deputato> ?dep .

          ?dep <http://dati.camera.it/ocd/aderisce> ?adesione .
          ?adesione <http://www.w3.org/2000/01/rdf-schema#label> ?gruppoLabel .

          OPTIONAL {{ ?adesione <http://dati.camera.it/ocd/startDate> ?gruppoStart }}
          OPTIONAL {{ ?adesione <http://dati.camera.it/ocd/endDate> ?gruppoEnd }}
        }}
        ORDER BY ?deputato ?gruppoStart
        """
        try:
            results = sparql_query(query_fallback)
            for r in results:
                r["gruppoLabel"] = clean_label(r.get("gruppoLabel", ""))
            print(f"  Got {len(results)} rows")
            return results
        except Exception as e2:
            print(f"  Fallback also failed: {e2}")
            return None


def download_committees(legislature: int = 19) -> list[dict] | None:
    """Download committee membership via ocd:deputato -> ocd:membro."""
    print("Downloading committee memberships...")
    query = f"""
    SELECT DISTINCT ?deputato ?organoLabel ?membroStart ?membroEnd
    WHERE {{
      ?deputato a <http://xmlns.com/foaf/0.1/Person> ;
               <http://dati.camera.it/ocd/rif_mandatoCamera> ?mandato .
      ?mandato <http://dati.camera.it/ocd/rif_leg> <{leg_uri(legislature)}> ;
               <http://dati.camera.it/ocd/rif_deputato> ?dep .

      ?dep <http://dati.camera.it/ocd/membro> ?membro .
      ?membro <http://www.w3.org/2000/01/rdf-schema#label> ?organoLabel .

      OPTIONAL {{ ?membro <http://dati.camera.it/ocd/startDate> ?membroStart }}
      OPTIONAL {{ ?membro <http://dati.camera.it/ocd/endDate> ?membroEnd }}
    }}
    ORDER BY ?deputato ?membroStart
    """
    try:
        results = sparql_query(query)
        for r in results:
            r["organoLabel"] = clean_label(r.get("organoLabel", ""))
        print(f"  Got {len(results)} rows")
        return results
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        return None


def write_csv(filepath: str, data: list[dict], fieldnames: list[str]):
    """Write list of dicts to CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"  Written {len(data)} rows -> {os.path.basename(filepath)}")


def main(legislature: int = 19):
    os.makedirs(DATA_DIR, exist_ok=True)
    prefix = csv_prefix(legislature)
    print(f"Legislature {legislature} -> {prefix}*.csv")

    # Deputies
    deps = download_deputies(legislature)
    if deps:
        write_csv(
            os.path.join(DATA_DIR, f"{prefix}.csv"),
            deps,
            ["deputato", "nome", "cognome", "gender", "foto",
             "schedaCamera", "mandatoCamera", "mandatoStart", "mandatoEnd", "descrizione"],
        )
    else:
        print(f"FAILED: {prefix}.csv")

    time.sleep(1)

    # Groups
    groups = download_groups(legislature)
    if groups:
        write_csv(
            os.path.join(DATA_DIR, f"{prefix}_gruppi.csv"),
            groups,
            ["deputato", "gruppoLabel", "gruppoStart", "gruppoEnd"],
        )
    else:
        print(f"FAILED: {prefix}_gruppi.csv")

    time.sleep(1)

    # Committees
    comms = download_committees(legislature)
    if comms:
        write_csv(
            os.path.join(DATA_DIR, f"{prefix}_commissioni.csv"),
            comms,
            ["deputato", "organoLabel", "membroStart", "membroEnd"],
        )
    else:
        print(f"FAILED: {prefix}_commissioni.csv")

    # Summary
    expected = [f"{prefix}.csv", f"{prefix}_gruppi.csv", f"{prefix}_commissioni.csv"]
    missing = [f for f in expected if not os.path.exists(os.path.join(DATA_DIR, f))]
    if missing:
        print(f"\nMissing: {', '.join(missing)}")
        sys.exit(1)
    else:
        print(f"\nAll 3 CSV files saved to {DATA_DIR}/")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislature", type=int, default=19)
    main(ap.parse_args().legislature)
