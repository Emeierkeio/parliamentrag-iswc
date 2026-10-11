#!/usr/bin/env python3
"""
Download senator data from dati.senato.it via SPARQL for XIX Legislature.
Produces the 3 CSV files required by build_and_update.py do_build_senate():
  - data/senatori_xix.csv
  - data/senatori_xix_gruppi.csv
  - data/senatori_xix_commissioni.csv

Senate ontology differs from Camera:
  - Person URI: http://dati.senato.it/senatore/{id}
  - Bio link:   osr:mandato -> mandatoSenato (not ocd:rif_mandatoCamera)
  - Legislature filter: osr:legislatura 19 (integer literal)
  - Name: rdfs:label only (no firstName/surname split — split on first space)
  - Dates: YYYY-MM-DD strings (not YYYYMMDD integers)
  - Groups: ocd:aderisce -> blank adesioneGruppo -> osr:gruppo -> osr:denominazione -> osr:titolo
  - Committees: osr:afferisce -> Afferenza -> osr:commissione -> osr:titolo
"""

import csv
import os
import re
import sys
import time
import requests

SPARQL_ENDPOINT = "https://dati.senato.it/sparql"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Virtuoso endpoint at dati.senato.it requires a browser-like User-Agent
# (returns 403 for the default Python requests User-Agent).
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ParliamentRAG/1.0; "
        "+https://github.com/Emeierkeio/ParliamentRAG)"
    )
}

# Virtuoso responds to format= param rather than Accept header for JSON output
SPARQL_PARAMS_BASE = {"format": "json"}


ROMAN = {17: "xvii", 18: "xviii", 19: "xix", 20: "xx"}


def csv_prefix(legislature: int) -> str:
    return f"senatori_{ROMAN.get(legislature, f'leg{legislature}')}"


def sparql_query(query: str) -> list[dict]:
    """Execute SPARQL query and return list of result dicts."""
    params = {**SPARQL_PARAMS_BASE, "query": query}
    resp = requests.get(SPARQL_ENDPOINT, params=params, headers=HEADERS, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    bindings = data["results"]["bindings"]
    return [{k: v["value"] for k, v in row.items()} for row in bindings]


def _split_name(label: str) -> tuple[str, str]:
    """Split 'First Last' or 'First Middle Last' label into (nome, cognome).

    The Senate stores names as 'First [Middle] Last'. We split at the last
    word boundary: everything before the final token is nome (first names),
    the final token is cognome (last name).

    Example:
        'Alberto Balboni'       -> ('Alberto', 'Balboni')
        'Maria Elena Boschi'    -> ('Maria Elena', 'Boschi')
    """
    parts = label.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    # Last token = cognome (common convention for dati.senato.it labels)
    return " ".join(parts[:-1]), parts[-1]


def _iso_to_yyyymmdd(date_str: str) -> str:
    """Convert 'YYYY-MM-DD' ISO date to 'YYYYMMDD' integer string.

    Returns original string unchanged if it does not match ISO format.
    csv_loader.parse_date_to_neo4j expects YYYYMMDD.
    """
    if not date_str:
        return date_str
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', date_str)
    if m:
        return f"{m.group(1)}{m.group(2)}{m.group(3)}"
    return date_str


def download_senators(legislature: int = 19) -> list[dict] | None:
    """Download senator biographical data for XIX legislature."""
    print("Downloading senators...")
    query = """
    SELECT DISTINCT ?senatore ?label ?gender ?foto ?mandatoStart ?mandatoEnd
    WHERE {
      ?senatore a <http://xmlns.com/foaf/0.1/Person> .
      ?senatore <http://dati.senato.it/osr/mandato> ?mandato .
      ?mandato a <http://dati.camera.it/ocd/mandatoSenato> .
      ?mandato <http://dati.senato.it/osr/legislatura> {legislature} .
      ?senatore <http://www.w3.org/2000/01/rdf-schema#label> ?label .

      OPTIONAL { ?senatore <http://xmlns.com/foaf/0.1/gender> ?gender }
      OPTIONAL { ?senatore <http://xmlns.com/foaf/0.1/depiction> ?foto }
      OPTIONAL { ?mandato <http://dati.senato.it/osr/inizio> ?mandatoStart }
      OPTIONAL { ?mandato <http://dati.senato.it/osr/fine> ?mandatoEnd }
    }
    ORDER BY ?label
    """
    try:
        results = sparql_query(query.replace("{legislature}", str(legislature)))
        print(f"  Got {len(results)} rows")

        # Deduplicate by senatore URI (keep row with earliest mandatoStart)
        seen: dict[str, dict] = {}
        for r in results:
            uri = r["senatore"]
            if uri not in seen:
                seen[uri] = r
            else:
                # Prefer row with a start date
                if not seen[uri].get("mandatoStart") and r.get("mandatoStart"):
                    seen[uri] = r

        deduped = list(seen.values())

        # Add derived fields
        for r in deduped:
            uri = r["senatore"]
            # Extract numeric senatore ID from URI
            r["schedaCamera"] = uri.rsplit("/", 1)[-1] if "/senatore/" in uri else ""
            # Split full name into nome/cognome
            label = r.get("label", "")
            nome, cognome = _split_name(label)
            r["nome"] = nome
            r["cognome"] = cognome
            # Convert ISO dates to YYYYMMDD for csv_loader compatibility
            if r.get("mandatoStart"):
                r["mandatoStart"] = _iso_to_yyyymmdd(r["mandatoStart"])
            if r.get("mandatoEnd"):
                r["mandatoEnd"] = _iso_to_yyyymmdd(r["mandatoEnd"])

        print(f"  Deduplicated to {len(deduped)} senators")
        return deduped
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        return None


def download_senator_groups(legislature: int = 19) -> list[dict] | None:
    """Download parliamentary group memberships for XIX legislature senators.

    Uses a subquery to select the denominazione whose date range overlaps the
    adesioneGruppo start date, avoiding duplicates from historical name changes.
    """
    print("Downloading senator parliamentary groups...")
    query = """
    SELECT DISTINCT ?senatore ?gruppo ?gruppoLabel ?gruppoBreve ?gruppoStart ?gruppoEnd
    WHERE {
      ?senatore a <http://xmlns.com/foaf/0.1/Person> .
      ?senatore <http://dati.senato.it/osr/mandato> ?mandato .
      ?mandato a <http://dati.camera.it/ocd/mandatoSenato> .
      ?mandato <http://dati.senato.it/osr/legislatura> {legislature} .

      ?senatore <http://dati.camera.it/ocd/aderisce> ?ades .
      ?ades <http://dati.senato.it/osr/legislatura> {legislature} .
      ?ades <http://dati.senato.it/osr/gruppo> ?gruppo .
      ?ades <http://dati.senato.it/osr/inizio> ?gruppoStart .
      OPTIONAL { ?ades <http://dati.senato.it/osr/fine> ?gruppoEnd }

      ?gruppo <http://dati.senato.it/osr/denominazione> ?den .
      ?den <http://dati.senato.it/osr/titolo> ?gruppoLabel .
      ?den <http://dati.senato.it/osr/titoloBreve> ?gruppoBreve .
      ?den <http://dati.senato.it/osr/inizio> ?denInizio .
      OPTIONAL { ?den <http://dati.senato.it/osr/fine> ?denFine }

      FILTER(?denInizio <= ?gruppoStart)
      FILTER(!bound(?denFine) || ?denFine >= ?gruppoStart)
    }
    ORDER BY ?senatore ?gruppoStart
    """
    try:
        results = sparql_query(query.replace("{legislature}", str(legislature)))
        print(f"  Got {len(results)} rows")

        # Deduplicate: same (senatore, gruppoStart) may appear with multiple
        # overlapping denominazioni — keep only one per (senatore, gruppoStart)
        seen: set[tuple] = set()
        deduped: list[dict] = []
        for r in results:
            key = (r["senatore"], r.get("gruppoStart", ""))
            if key not in seen:
                seen.add(key)
                # Convert ISO dates
                if r.get("gruppoStart"):
                    r["gruppoStart"] = _iso_to_yyyymmdd(r["gruppoStart"])
                if r.get("gruppoEnd"):
                    r["gruppoEnd"] = _iso_to_yyyymmdd(r["gruppoEnd"])
                r["gruppoUri"] = r.pop("gruppo", "")
                deduped.append(r)

        print(f"  Deduplicated to {len(deduped)} group membership rows")
        _add_current_group_names(deduped, legislature)
        return deduped
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        return None


def _add_current_group_names(rows: list[dict], legislature: int) -> None:
    """Add the group's latest name to every membership row.

    gruppoLabel is the name in force when the senator joined, so after a
    rename (Forza Italia -> "... - PPE", Azione-IV -> "Italia Viva - Il
    Centro") members who joined earlier keep the old label and one group
    would split into two nodes. gruppoAttuale is the same for all of them;
    gruppoAlias lists the names the group had during this legislature,
    separated by "|": a group URI spans legislatures (Lega goes back to "Lega
    Padana"), so older names are dropped.
    """
    query = """
    SELECT DISTINCT ?gruppo ?titolo ?breve ?inizio ?fine WHERE {
      ?ades <http://dati.senato.it/osr/legislatura> {legislature} ;
            <http://dati.senato.it/osr/gruppo> ?gruppo .
      ?gruppo <http://dati.senato.it/osr/denominazione> ?den .
      ?den <http://dati.senato.it/osr/titolo> ?titolo ;
           <http://dati.senato.it/osr/titoloBreve> ?breve ;
           <http://dati.senato.it/osr/inizio> ?inizio .
      OPTIONAL { ?den <http://dati.senato.it/osr/fine> ?fine }
    }
    """
    try:
        names = sparql_query(query.replace("{legislature}", str(legislature)))
    except Exception as e:
        print(f"  Group names query failed, keeping the names at join date: {e}")
        return
    by_group: dict[str, list[dict]] = {}
    for n in names:
        by_group.setdefault(n["gruppo"], []).append(n)
    # gruppoStart is YYYYMMDD here, denominazione dates are ISO
    first_start = {}
    for r in rows:
        start = f"{r['gruppoStart'][:4]}-{r['gruppoStart'][4:6]}-{r['gruppoStart'][6:8]}"
        first_start[r["gruppoUri"]] = min(first_start.get(r["gruppoUri"], start), start)
    for r in rows:
        since = first_start[r["gruppoUri"]]
        dens = sorted(
            (n for n in by_group.get(r["gruppoUri"], [])
             if not n.get("fine") or n["fine"][:10] >= since),
            key=lambda n: n["inizio"],
        )
        if not dens:
            continue
        r["gruppoAttuale"] = dens[-1]["titolo"]
        r["gruppoAttualeBreve"] = dens[-1]["breve"]
        r["gruppoAlias"] = "|".join(dict.fromkeys(n["titolo"] for n in dens))
    print(f"  Current names for {len(by_group)} groups")


def download_senator_committees(legislature: int = 19) -> list[dict] | None:
    """Download committee memberships for XIX legislature senators.

    Uses osr:titolo (single per commissione) to avoid titoloBreve duplicates.
    """
    print("Downloading senator committee memberships...")
    query = """
    SELECT DISTINCT ?senatore ?organoLabel ?membroStart ?membroEnd
    WHERE {
      ?senatore a <http://xmlns.com/foaf/0.1/Person> .
      ?senatore <http://dati.senato.it/osr/mandato> ?mandato .
      ?mandato a <http://dati.camera.it/ocd/mandatoSenato> .
      ?mandato <http://dati.senato.it/osr/legislatura> {legislature} .

      ?senatore <http://dati.senato.it/osr/afferisce> ?afferenza .
      ?afferenza <http://dati.senato.it/osr/legislatura> {legislature} .
      ?afferenza <http://dati.senato.it/osr/commissione> ?commissione .
      ?commissione <http://dati.senato.it/osr/titolo> ?organoLabel .
      OPTIONAL { ?afferenza <http://dati.senato.it/osr/inizio> ?membroStart }
      OPTIONAL { ?afferenza <http://dati.senato.it/osr/fine> ?membroEnd }
    }
    ORDER BY ?senatore ?membroStart
    """
    try:
        results = sparql_query(query.replace("{legislature}", str(legislature)))
        print(f"  Got {len(results)} rows")
        for r in results:
            if r.get("membroStart"):
                r["membroStart"] = _iso_to_yyyymmdd(r["membroStart"])
            if r.get("membroEnd"):
                r["membroEnd"] = _iso_to_yyyymmdd(r["membroEnd"])
        return results
    except Exception as e:
        print(f"  SPARQL query failed: {e}")
        return None


def write_csv(filepath: str, data: list[dict], fieldnames: list[str]) -> None:
    """Write list of dicts to CSV."""
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in data:
            writer.writerow({k: row.get(k, "") for k in fieldnames})
    print(f"  Written {len(data)} rows -> {os.path.basename(filepath)}")


def main(legislature: int = 19) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)

    # Senators bio
    senators = download_senators(legislature)
    if senators:
        write_csv(
            os.path.join(DATA_DIR, f"{csv_prefix(legislature)}.csv"),
            senators,
            ["senatore", "nome", "cognome", "gender", "foto",
             "schedaCamera", "mandatoStart", "mandatoEnd"],
        )
    else:
        print("FAILED: senatori_xix.csv")

    time.sleep(1)

    # Groups
    groups = download_senator_groups(legislature)
    if groups:
        write_csv(
            os.path.join(DATA_DIR, f"{csv_prefix(legislature)}_gruppi.csv"),
            groups,
            ["senatore", "gruppoLabel", "gruppoBreve", "gruppoStart", "gruppoEnd",
             "gruppoUri", "gruppoAttuale", "gruppoAttualeBreve", "gruppoAlias"],
        )
    else:
        print("FAILED: senatori_xix_gruppi.csv")

    time.sleep(1)

    # Committees
    committees = download_senator_committees(legislature)
    if committees:
        write_csv(
            os.path.join(DATA_DIR, f"{csv_prefix(legislature)}_commissioni.csv"),
            committees,
            ["senatore", "organoLabel", "membroStart", "membroEnd"],
        )
    else:
        print("FAILED: senatori_xix_commissioni.csv")

    # Summary
    expected = [
        f"{csv_prefix(legislature)}.csv",
        f"{csv_prefix(legislature)}_gruppi.csv",
        f"{csv_prefix(legislature)}_commissioni.csv",
    ]
    missing = [f for f in expected if not os.path.exists(os.path.join(DATA_DIR, f))]
    if missing:
        print(f"\nMissing: {', '.join(missing)}")
        sys.exit(1)
    else:
        print(f"\nAll 3 CSV files saved to {DATA_DIR}/")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--legislature", type=int, default=19)
    main(ap.parse_args().legislature)
