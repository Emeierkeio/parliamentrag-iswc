"""
download_emendamenti_senato.py — Senate readings list and committee amendment pages.

Writes fasi.csv with every Senate reading of the legislature from
https://dati.senato.it/sparql (idFase, idDdl, fase, stato, data): the other
Senate scripts and parse_emendamenti.py read it.

Then downloads, for each reading, the page listing all committee amendments:
    https://www.senato.it/show-doc?leg=19&tipodoc=ListEmendc&id={idFase}
The primary source for Senate amendments is Akoma Ntoso (downloads/akn_senato);
these pages fill the bills missing from it.

Resumable: skips pages already saved and readings recorded in empty.txt.
--recenti N re-checks only readings whose status changed in the last N days
plus readings never checked (the nightly mode); --refresh re-checks all.

Usage:
    python build/download_emendamenti_senato.py [--recenti 14] [--delay 0.5]
"""

from __future__ import annotations

import argparse
import csv
import time
from datetime import date, timedelta
from pathlib import Path

import requests

from download_esiti_senato import SenateFetcher

SPARQL = "https://dati.senato.it/sparql"
LIST_URL = "https://www.senato.it/show-doc?leg={leg}&tipodoc=ListEmendc&id={id_fase}"
REPO_ROOT = Path(__file__).resolve().parent.parent
SPARQL_USER_AGENT = "Mozilla/5.0 (compatible; ParliamentRAG/1.0; +https://www.parliamentrag.it)"

FASI_QUERY = """
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?idFase ?idDdl ?fase ?numeroFase ?stato ?data WHERE {{
  ?d a osr:Ddl ; osr:legislatura ?l ; osr:ramo ?ramo ;
     osr:idFase ?idFase ; osr:idDdl ?idDdl ; osr:fase ?fase ; osr:numeroFase ?numeroFase .
  OPTIONAL {{ ?d osr:statoDdl ?stato }}
  OPTIONAL {{ ?d osr:dataStatoDdl ?data }}
  FILTER(str(?l) = "{leg}" && str(?ramo) = "{ramo}")
}} ORDER BY ?idFase
"""
FASI_FIELDS = ["idFase", "idDdl", "fase", "numeroFase", "stato", "data"]


def fetch_fasi(leg: int, ramo: str = "S") -> list[dict]:
    """Readings of one chamber from the Senate SPARQL (it also covers Chamber bills)."""
    r = requests.get(SPARQL, params={"query": FASI_QUERY.format(leg=leg, ramo=ramo)},
                     headers={"Accept": "application/sparql-results+json",
                              "User-Agent": SPARQL_USER_AGENT}, timeout=180)
    r.raise_for_status()
    return [{k: b[k]["value"] if k in b else "" for k in FASI_FIELDS}
            for b in r.json()["results"]["bindings"]]


def changed_since(fase: dict, days: int) -> bool:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    return bool(fase.get("data")) and fase["data"] >= cutoff


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "downloads" / "emendamenti_senato")
    ap.add_argument("--recenti", type=int, metavar="GIORNI")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    out = args.out / f"leg{args.leg}"
    out.mkdir(parents=True, exist_ok=True)
    fasi = fetch_fasi(args.leg)
    if not fasi:
        raise SystemExit("SPARQL Senato: nessuna fase restituita")
    with open(out / "fasi.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FASI_FIELDS)
        w.writeheader()
        w.writerows(fasi)
    print(f"{len(fasi)} fasi S dal SPARQL", flush=True)

    empty_file = out / "empty.txt"
    empty = set() if args.refresh or not empty_file.exists() else set(empty_file.read_text().split())

    fetcher = SenateFetcher()
    found = errors = checked = 0
    for row in fasi:
        id_fase = row["idFase"]
        target = out / f"emendc.{id_fase}.html"
        never_checked = not target.exists() and id_fase not in empty
        recent = args.recenti is not None and changed_since(row, args.recenti)
        if not (args.refresh or never_checked or recent):
            continue
        checked += 1
        r = fetcher.get(LIST_URL.format(leg=args.leg, id_fase=id_fase), f"{row['fase']} ({id_fase})")
        if r is None:
            errors += 1
        elif r.status_code == 200 and 'class="emen"' in r.text:
            target.write_bytes(r.content)
            empty.discard(id_fase)
            found += 1
            n_emen = r.text.count('class="emen"')
            print(f"{row['fase']} ({id_fase}): {n_emen} emendamenti", flush=True)
        elif r.status_code in (200, 404, 500):
            # The Senate answers 500 or a page without blocks when a bill has no amendments
            if not target.exists():
                empty.add(id_fase)
        else:
            errors += 1
            print(f"{row['fase']} ({id_fase}): HTTP {r.status_code}", flush=True)
        if checked % 100 == 0:
            empty_file.write_text("\n".join(sorted(empty, key=int)))
        time.sleep(args.delay)

    empty_file.write_text("\n".join(sorted(empty, key=int)))
    print(f"Fine: {checked} fasi controllate, {found} pagine scritte, {len(empty)} senza emendamenti, "
          f"{errors} errori", flush=True)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
