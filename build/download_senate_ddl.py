#!/usr/bin/env python3
"""
Download the Senate bills (osr:Ddl) of a legislature and their signatories.

Produces:
  - data/senato_{roman}_ddl.csv            one row per Ddl (a bill's passage in the Senate)
  - data/senato_{roman}_ddl_firmatari.csv  one row per (Ddl, senator)

Each Ddl URI is one "fase": a bill read twice in the Senate has two
(S.1468, S.1468-B), sharing idDdl. Signatories come from osr:iniziativa,
whose primoFirmatario flag marks the first signer.

The endpoint caps a result at 10,000 rows counting the OFFSET, so the
signatories are fetched per range of bill numbers; a range that hits the cap
is split again.
"""

import argparse
import csv
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from senate_sparql_ingester import _senato_sparql_get  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "xviii", 19: "xix"}
ROW_CAP = 10000
# Bill numbers per signatory request: XIX bills have ~10 signers on average.
NUMBER_STEP = 400

PREFIX = "PREFIX osr: <http://dati.senato.it/osr/>\n"


def _value(binding: dict, key: str) -> str:
    return binding.get(key, {}).get("value", "")


def download_ddl(legislature: int) -> list[dict]:
    query = PREFIX + f"""
SELECT ?ddl ?idDdl ?numero ?titolo ?data ?natura ?stato ?ramo WHERE {{
  ?ddl a osr:Ddl ; osr:legislatura {legislature} ;
       osr:idDdl ?idDdl ; osr:numeroFase ?numero .
  OPTIONAL {{ ?ddl osr:titolo ?titolo }}
  OPTIONAL {{ ?ddl osr:dataPresentazione ?data }}
  OPTIONAL {{ ?ddl osr:natura ?natura }}
  OPTIONAL {{ ?ddl osr:statoDdl ?stato }}
  OPTIONAL {{ ?ddl osr:ramo ?ramo }}
}}
"""
    rows = _senato_sparql_get(query, strict=True)
    if len(rows) >= ROW_CAP:
        raise RuntimeError("Ddl list hit the endpoint's row cap: split the query")
    seen: dict[str, dict] = {}
    for b in rows:
        uri = _value(b, "ddl")
        # A bill may carry more than one title; the first one is kept.
        seen.setdefault(uri, {
            "ddl": uri,
            "idDdl": _value(b, "idDdl"),
            "numero": _value(b, "numero"),
            "titolo": _value(b, "titolo"),
            "dataPresentazione": _value(b, "data")[:10],
            "natura": _value(b, "natura"),
            "stato": _value(b, "stato"),
            "ramo": _value(b, "ramo"),
        })
    return list(seen.values())


def _signers_query(legislature: int, lo: int, hi: int) -> str:
    # numeroFase is a string ("1468", "1468-B"): the integer prefix selects the range
    return PREFIX + f"""
SELECT ?ddl ?senatore ?primo WHERE {{
  ?ddl a osr:Ddl ; osr:legislatura {legislature} ; osr:numeroFase ?numero ;
       osr:iniziativa ?i .
  ?i osr:senatore ?senatore .
  OPTIONAL {{ ?i osr:primoFirmatario ?primo }}
  FILTER(xsd:integer(?numero) >= {lo} && xsd:integer(?numero) < {hi})
}}
"""


def download_signers(legislature: int, max_number: int) -> list[dict]:
    out: list[dict] = []
    ranges = [(lo, lo + NUMBER_STEP) for lo in range(0, max_number + 1, NUMBER_STEP)]
    while ranges:
        lo, hi = ranges.pop(0)
        rows = _senato_sparql_get(_signers_query(legislature, lo, hi), strict=True)
        if len(rows) >= ROW_CAP and hi - lo > 1:
            mid = (lo + hi) // 2
            ranges[:0] = [(lo, mid), (mid, hi)]
            continue
        logger.info("  bills %d-%d: %d signatures", lo, hi - 1, len(rows))
        for b in rows:
            out.append({
                "ddl": _value(b, "ddl"),
                "senatore": _value(b, "senatore"),
                "primoFirmatario": "1" if _value(b, "primo") in ("1", "true") else "0",
            })
    return out


def _number_prefix(numero: str) -> int:
    digits = ""
    for ch in numero:
        if not ch.isdigit():
            break
        digits += ch
    return int(digits) if digits else 0


def write_csv(path: str, rows: list[dict], fields: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    logger.info("Written %d rows -> %s", len(rows), os.path.basename(path))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--legislature", type=int, default=19)
    args = ap.parse_args()
    roman = ROMAN.get(args.legislature, f"leg{args.legislature}")

    ddl = download_ddl(args.legislature)
    write_csv(os.path.join(DATA_DIR, f"senato_{roman}_ddl.csv"), ddl,
              ["ddl", "idDdl", "numero", "titolo", "dataPresentazione", "natura", "stato", "ramo"])
    max_number = max((_number_prefix(d["numero"]) for d in ddl), default=0)
    signers = download_signers(args.legislature, max_number)
    write_csv(os.path.join(DATA_DIR, f"senato_{roman}_ddl_firmatari.csv"), signers,
              ["ddl", "senatore", "primoFirmatario"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
