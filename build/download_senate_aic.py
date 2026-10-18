#!/usr/bin/env python3
"""
Download the Senate's oversight and policy acts (interrogazioni, interpellanze,
mozioni, risoluzioni, ordini del giorno) of a legislature.

Two sources, decision D9 (18/10/2026):

  --source camera  dati.camera.it SPARQL, ocd:aic with ocd:ramo "Senato della
                   Repubblica": type, number, dates, signatories, full text.
                   Same vocabulary as the Chamber's own acts, so Senate and
                   Camera acts weigh the same in the authority score.
                   -> data/senato_{roman}_aic.jsonl
  --source senato  dati.senato.it SPARQL, osr:SindacatoIspettivo: outcome and
                   the senato.it page. No text, no agenda orders; a reformulated
                   act is a new record, so one number can have several URIs.
                   -> data/senato_{roman}_sindisp.jsonl

aic.camera.it, the previous source, disallows every path in its robots.txt.

Exit 3 = dati.senato.it refused the requests (--source senato only).
"""

import argparse
import json
import logging
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ingest_acts_camera import VIRTUOSO_CAP, Sparql  # noqa: E402
from senate_sparql_ingester import SenateEndpointBlocked, SenateRequestFailed, _senato_sparql_get  # noqa: E402

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
ROMAN = {18: "XVIII", 19: "XIX"}
LEG_URI = "<http://dati.camera.it/ocd/legislatura.rdf/repubblica_{leg}>"
GROUP_RE = re.compile(r"\s*\(.*$", re.S)

ACTS_QUERY = """
SELECT DISTINCT ?a ?id ?type ?start ?end ?concluso ?creator ?descr ?rel WHERE {{
  ?a a ocd:aic ; ocd:ramo "Senato della Repubblica" ; ocd:rif_leg {leg} ;
     dc:identifier ?id ; dc:type ?type ; dc:creator ?creator .
  FILTER(STRSTARTS(?id, "{prefix}"))
  OPTIONAL {{ ?a ocd:startDate ?start }} OPTIONAL {{ ?a ocd:endDate ?end }}
  OPTIONAL {{ ?a ocd:concluso ?concluso }} OPTIONAL {{ ?a dc:description ?descr }}
  OPTIONAL {{ ?a dc:relation ?rel }}
}}"""

COSIGNERS_QUERY = """
SELECT DISTINCT ?a ?c WHERE {{
  ?a a ocd:aic ; ocd:ramo "Senato della Repubblica" ; ocd:rif_leg {leg} ;
     dc:identifier ?id ; dc:contributor ?c .
  FILTER(STRSTARTS(?id, "{prefix}"))
}}"""

SINDISP_QUERY = """
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?s ?numero ?esito ?url ?data WHERE {{
  ?s a osr:SindacatoIspettivo ; osr:legislatura {leg} ; osr:numero ?numero .
  OPTIONAL {{ ?s osr:esito ?esito }} OPTIONAL {{ ?s osr:URLTesto ?url }}
  OPTIONAL {{ ?s osr:dataPresentazione ?data }}
}}"""


def iso(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) < 8:
        return None
    return f"{yyyymmdd[:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def signer(text: str) -> str:
    """'PAROLI ADRIANO ( FORZA ITALIA - ...)' -> 'PAROLI ADRIANO'."""
    return GROUP_RE.sub("", text).strip()


def select_partitioned(sparql: Sparql, template: str, leg: int, ids: list[str], prefix: str) -> list[dict]:
    """Rows for the acts whose number starts with prefix. A partition that
    reaches the endpoint's row cap is split on the next character of the
    numbers already known."""
    rows = sparql.select(template.format(leg=LEG_URI.format(leg=leg), prefix=prefix))
    if len(rows) < VIRTUOSO_CAP:
        return rows
    nexts = sorted({i[len(prefix)] for i in ids if i.startswith(prefix) and len(i) > len(prefix)})
    if not nexts:
        raise RuntimeError(f"{prefix}: {len(rows)} rows and nothing left to split on")
    return [r for c in nexts for r in select_partitioned(sparql, template, leg, ids, prefix + c)]


def download_camera(leg: int, delay: float) -> list[dict]:
    sparql = Sparql(delay)
    acts: dict[str, dict] = {}
    for digit in "0123456789":
        rows = sparql.select(ACTS_QUERY.format(leg=LEG_URI.format(leg=leg), prefix=f"{digit}/"))
        if len(rows) >= VIRTUOSO_CAP:
            raise RuntimeError(f"{digit}/: {len(rows)} acts reach the row cap, split the query")
        for r in rows:
            acts.setdefault(r["a"], {
                "uri": r["a"],
                "numero": r["id"],
                "type": r["type"],
                "date": iso(r.get("start")),
                "end_date": iso(r.get("end")),
                "concluded": r.get("concluso") == "1",
                "primary": signer(r["creator"]),
                "cosigners": [],
                "text": " ".join((r.get("descr") or "").split()),
                "url": r.get("rel"),
            })
        logger.info("%s/: %d acts", digit, len(rows))
    ids = sorted(a["numero"] for a in acts.values())
    for digit in "0123456789":
        for r in select_partitioned(sparql, COSIGNERS_QUERY, leg, ids, f"{digit}/"):
            act = acts.get(r["a"])
            name = signer(r["c"])
            if act and name != act["primary"] and name not in act["cosigners"]:
                act["cosigners"].append(name)
    logger.info("%d acts, %d SPARQL calls", len(acts), sparql.calls)
    return sorted(acts.values(), key=lambda a: a["numero"])


def download_senato(leg: int) -> list[dict]:
    rows = _senato_sparql_get(SINDISP_QUERY.format(leg=leg), strict=True)
    if not rows:
        raise SenateRequestFailed("no osr:SindacatoIspettivo records")
    out = {}
    for b in rows:
        r = {k: v["value"] for k, v in b.items()}
        out[r["s"]] = {
            "uri": r["s"],
            # "4-03088" on the Senate, "4/03088" on the Chamber.
            "numero": r["numero"].replace("-", "/", 1),
            "outcome": r.get("esito") or None,
            "url": r.get("url"),
            "date": r.get("data"),
        }
    logger.info("%d Senate records", len(out))
    return sorted(out.values(), key=lambda r: (r["numero"], r["date"] or ""))


def write_jsonl(rows: list[dict], path: str) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    logger.info("Written %d rows -> %s", len(rows), os.path.basename(path))


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--legislature", type=int, default=19)
    ap.add_argument("--source", choices=("camera", "senato"), default="camera")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between Chamber SPARQL calls")
    args = ap.parse_args()

    roman = ROMAN[args.legislature].lower()
    if args.source == "camera":
        rows = download_camera(args.legislature, args.delay)
        if not rows:
            logger.error("no acts from dati.camera.it")
            return 1
        write_jsonl(rows, os.path.join(DATA_DIR, f"senato_{roman}_aic.jsonl"))
        return 0
    try:
        rows = download_senato(args.legislature)
    except (SenateEndpointBlocked, SenateRequestFailed) as exc:
        logger.error("dati.senato.it: %s", exc)
        return 3
    write_jsonl(rows, os.path.join(DATA_DIR, f"senato_{roman}_sindisp.jsonl"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
