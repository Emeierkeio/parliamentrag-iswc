#!/usr/bin/env python3
"""
Download the Senate's oversight and policy acts (interrogazioni, interpellanze,
mozioni, risoluzioni, ordini del giorno) of a legislature.

dati.senato.it does not publish them. The Camera's search engine on these acts
(aic.camera.it, "Fascicolo elettronico degli atti di sindacato ispettivo")
covers both chambers since 1976 and answers JSON at map/aic/simple.json:
legRomano and ramo filter, an empty text matches everything, _start is a
1-based page of 500 results. Its act types are the Camera ones, so Senate and
Camera acts weigh the same in the authority score.

Writes data/senato_{roman}_aic.jsonl, one act per line.
"""

import argparse
import json
import logging
import os
import sys
import time

import requests

logger = logging.getLogger(__name__)

ENDPOINT = "https://aic.camera.it/aic/map/aic/simple.json"
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "XVIII", 19: "XIX"}
PAGE_SIZE = 500  # fixed by the endpoint
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
FIELDS = ["id", "numero", "tipologia", "tipoAtto", "dataPresentazione", "dataConclusione",
          "primoFirmatario", "idPrimoFirmatario", "coFirmatario", "gruppo", "destinatario",
          "stato", "eurovoc_descrizione", "testo"]


def fetch_page(legislature: int, page: int, retries: int = 3) -> list[dict]:
    params = {"legRomano": ROMAN[legislature], "ramo": "SENATO", "_default": "", "testo": "",
              "_start": page, "_rows": PAGE_SIZE}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(ENDPOINT, params=params, headers=HEADERS, timeout=180)
            r.raise_for_status()
            return [x["values"] for x in r.json()["results"]]
        except (requests.RequestException, ValueError, KeyError) as exc:
            if attempt == retries:
                raise
            logger.warning("page %d failed (%s), retrying", page, exc)
            time.sleep(10 * attempt)
    return []


def flatten(values: dict) -> dict:
    """Solr returns every field as a list; keep lists only where they are lists."""
    out = {}
    for k in FIELDS:
        v = values.get(k)
        if v is None:
            continue
        out[k] = v if k in ("coFirmatario", "eurovoc_descrizione", "gruppo", "destinatario") else v[0]
    return out


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--delay", type=float, default=2.0)
    args = ap.parse_args()

    out_path = os.path.join(DATA_DIR, f"senato_{ROMAN[args.legislature].lower()}_aic.jsonl")
    tmp = out_path + ".tmp"
    seen: set[str] = set()
    page = 1
    with open(tmp, "w", encoding="utf-8") as f:
        while True:
            rows = fetch_page(args.legislature, page)
            for v in rows:
                act = flatten(v)
                if act.get("id") and act["id"] not in seen:
                    seen.add(act["id"])
                    f.write(json.dumps(act, ensure_ascii=False) + "\n")
            logger.info("page %d: %d acts (%d total)", page, len(rows), len(seen))
            if len(rows) < PAGE_SIZE:
                break
            page += 1
            time.sleep(args.delay)
    os.replace(tmp, out_path)
    logger.info("Written %d acts -> %s", len(seen), os.path.basename(out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
