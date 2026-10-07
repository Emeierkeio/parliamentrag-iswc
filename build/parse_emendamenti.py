"""
parse_emendamenti.py — Chamber and Senate amendments in one JSONL.

Sources:
  - Chamber: one XML per bill from download_emendamenti_camera.py
    (committee and floor, sitting date, outcome when published);
  - Senate: Akoma Ntoso files from SenatoDellaRepubblica/AkomaNtosoBulkData
    (downloads/akn_senato, folders emendc = committee, emend = floor) with
    presentation date and signatories; outcomes from download_esiti_senato.py
    (esiti.csv), joined on the text id shared by both sources. Two fallbacks
    cover gaps in Akoma Ntoso: ListEmendc HTML pages for bills with no emendc
    folder, and single EMEND pages for the empty files the Senate publishes.

One row per amendment, same schema for both chambers:

    id, ramo, atto, atti_congiunti, id_ddl, id_testo, sede, sede_esame,
    commissione, seduta_data, data_presentazione, numero, versione, tipo,
    articolo, esito, decreto, documento, firmatari, testo, testo_presentato,
    testo_hash, gruppo_id, fonte

Cleaning:
  1. Senate bills examined jointly carry the same amendment files; one row
     per text id is kept and the other bills go in atti_congiunti;
  2. exact duplicates (same chamber, bill, venue, sitting, number, version
     and text) are dropped;
  3. Chamber reformulations (same number, sitting and signatories listed
     twice) become one row with the approved text and testo_presentato;
  4. re-submissions (same bill, same normalised text, same signatories in a
     different venue or sitting) stay as separate rows sharing one gruppo_id.

Senate rows use the Senate text id as id: the Senate restarts numbering when
a new base text is adopted, so a number can repeat within one bill.

id_ddl is the Senate osr:idDdl, which identifies the whole bill across both
chambers. Chamber bills get it from the Senate SPARQL readings with ramo C
(cached in downloads/emendamenti/fasi_camera_leg{N}.csv).

Usage:
    python build/parse_emendamenti.py [--leg 19]
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
DOWNLOADS = REPO_ROOT / "downloads"
SPARQL = "https://dati.senato.it/sparql"

FASI_CAMERA_QUERY = """
PREFIX osr: <http://dati.senato.it/osr/>
SELECT ?numeroFase ?idDdl WHERE {{
  ?d a osr:Ddl ; osr:legislatura ?l ; osr:ramo ?ramo ;
     osr:numeroFase ?numeroFase ; osr:idDdl ?idDdl .
  FILTER(str(?l) = "{leg}" && str(?ramo) = "C")
}}
"""

# "1.5 (testo 2)", "G/2036/1/6 (testo corretto)", "Emendamento n. 2.1 (testo 2)"
VERSION_RE = re.compile(r"^(.*?)\s*\((testo[^)]*)\)\s*$", re.I)
DOCNUMBER_PREFIX_RE = re.compile(r"^(emendamento|ordine del giorno|subemendamento)\s+n\.\s*", re.I)


def normalize_space(text: str) -> str:
    lines = (re.sub(r"[ \t\xa0]+", " ", line).strip() for line in text.split("\n"))
    return "\n".join(line for line in lines if line)


def text_hash(text: str) -> str:
    """Hash of the text ignoring whitespace, punctuation and case."""
    key = re.sub(r"[\W_]+", "", text.lower())
    return hashlib.sha1(key.encode()).hexdigest()[:16]


def split_version(numero: str) -> tuple[str, str | None]:
    m = VERSION_RE.match(numero.strip())
    if m:
        return m.group(1).strip(), m.group(2).strip()
    return numero.strip(), None


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def flat(el: ET.Element) -> str:
    return " ".join("".join(el.itertext()).split())


def block_text(container: ET.Element | None) -> str:
    """One line per paragraph; tables become one line per row, cells joined by " | "."""
    if container is None:
        return ""
    lines = []
    for el in container:
        rows = [r for r in el.iter() if local(r.tag) == "tr"]
        if rows:
            lines.extend(" | ".join(flat(cell) for cell in tr) for tr in rows)
        else:
            lines.append(flat(el))
    if not lines:
        lines = [flat(container)]
    return normalize_space("\n".join(lines))


# --------------------------------------------------------------------- Camera

def camera_id_ddl(leg: int) -> dict[str, str]:
    cache = DOWNLOADS / "emendamenti" / f"fasi_camera_leg{leg}.csv"
    if not cache.exists():
        r = requests.get(SPARQL, params={"query": FASI_CAMERA_QUERY.format(leg=leg)},
                         headers={"Accept": "application/sparql-results+json"}, timeout=180)
        r.raise_for_status()
        cache.parent.mkdir(parents=True, exist_ok=True)
        with open(cache, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["numeroFase", "idDdl"])
            for b in r.json()["results"]["bindings"]:
                w.writerow([b["numeroFase"]["value"], b["idDdl"]["value"]])
    with open(cache) as f:
        return {row["numeroFase"]: row["idDdl"] for row in csv.DictReader(f)}


def parse_camera(path: Path, id_ddl: dict[str, str], leg: int):
    numero_atto = path.stem.split(".", 1)[1]
    root = ET.parse(path).getroot()
    for ses in root.findall("proposteEmendativeInSeduta"):
        sed = ses.find("seduta")
        commissioni = sed.find("commissioni")
        comm = sed.find(".//commissione")
        sede = "assemblea" if sed.get("tipo") == "assemblea" else "commissione"
        for gruppo in ses.findall("gruppo"):
            for pe in gruppo.iter("propostaEmendativa"):
                testo_el = pe.find("testoPropostaEmendativa")
                if testo_el is None:  # cross-reference inside proposteEmendativeIdentiche
                    continue
                firmatari = []
                for p in testo_el.iter("proponente"):
                    persona = p.find("persona")
                    nome = " ".join(filter(None, [p.findtext(".//nome"), p.findtext(".//cognome")])) or None
                    firmatari.append({
                        "id": f"C:{p.get('idProponente')}" if p.get("idProponente") else None,
                        "nome": nome,
                        "tipo": p.get("tipoProponente"),
                        "primo": persona is not None and persona.get("primoFirmatario") == "1",
                    })
                numero, versione = split_version((pe.get("numero") or "").rstrip("."))
                yield {
                    "ramo": "C",
                    "atto": f"C.{numero_atto}",
                    "atti_congiunti": [],
                    "id_ddl": id_ddl.get(numero_atto),
                    "id_testo": None,
                    "sede": sede,
                    "sede_esame": commissioni.get("sedeEsame") if commissioni is not None else None,
                    "commissione": comm.get("idCommissione") if comm is not None else None,
                    "seduta_data": sed.get("data"),
                    "data_presentazione": None,
                    "numero": numero,
                    "versione": versione,
                    "tipo": pe.get("tipo"),
                    "articolo": pe.findtext("partizione/riferimento"),
                    "esito": (pe.findtext(".//esitoPropostaEmendativa/esito") or "").strip() or None,
                    "decreto": pe.get("numeroDecretoLegge"),
                    "documento": pe.get("anchorDocumentoOrigine"),
                    "firmatari": firmatari,
                    "testo": block_text(testo_el.find("xhtml")),
                    "fonte": f"https://documenti.camera.it/leg{leg}/emendamenti/xml/leg.{leg}.eme.ac.{numero_atto}.xml",
                }


# --------------------------------------------------------------------- Senato

def load_esiti_senato(path: Path) -> tuple[dict[str, str], dict[tuple, str]]:
    """Outcomes by text id, and by (id_fase, sede, numero) for the HTML fallback."""
    by_id, by_num = {}, {}
    if path.exists():
        with open(path) as f:
            for r in csv.DictReader(f):
                if r.get("esito"):
                    by_id[r["id_testo"]] = r["esito"]
                    by_num[(r["id_fase"], r["sede"], r["numero"])] = r["esito"]
    return by_id, by_num


def senato_signer_type(name: str) -> str:
    low = name.lower()
    if "relat" in low:
        return "relatore"
    if "governo" in low:
        return "governo"
    if "commission" in low or "comitato" in low:
        return "commissione"
    return "altro"


def parse_senato_akn(path: Path, fase: dict, sede: str, esiti: dict[str, str], leg: int) -> dict | None:
    """None for the empty <akomaNtoso/> files the Senate publishes for some texts."""
    root = ET.parse(path).getroot()
    if len(root) == 0:
        return None
    nodes = {local(el.tag): el for el in root.iter() if local(el.tag) in (
        "FRBRWork", "references", "preface", "amendmentContent")}
    work = nodes.get("FRBRWork")
    get = lambda name, attr: next((el.get(attr) for el in work if local(el.tag) == name), None)  # noqa: E731
    doc_number = next((flat(el) for el in root.iter() if local(el.tag) == "docNumber"), "")
    numero, versione = split_version(DOCNUMBER_PREFIX_RE.sub("", doc_number) or get("FRBRnumber", "value") or "")

    persons = {}
    for el in nodes.get("references", []):
        if local(el.tag) == "TLCPerson":
            persons[el.get("id")] = (el.get("href", "").rsplit("/", 1)[-1], el.get("showAs", ""))
    firmatari = []
    for el in root.iter():
        if local(el.tag) != "docProponent":
            continue
        sid, show = persons.get((el.get("refersTo") or "").lstrip("#"), ("", flat(el)))
        if sid and sid != "0":
            firmatari.append({"id": f"S:{sid}", "nome": show, "tipo": "senatore", "primo": not firmatari})
        else:
            firmatari.append({"id": None, "nome": show or flat(el), "tipo": senato_signer_type(show or flat(el)),
                              "primo": not firmatari})

    id_testo = str(int(path.name.split("-", 1)[0]))
    name = (get("FRBRname", "value") or "").lower()
    tipo = "ordine_del_giorno" if "ordine" in name or numero.startswith("G") else (
        "subemendamento" if "sub" in name else "emendamento")
    tipodoc = "EMEND" if sede == "assemblea" else "EMENDC"
    return {
        "ramo": "S",
        "atto": fase["fase"],
        "atti_congiunti": [],
        "id_ddl": fase["idDdl"],
        "id_testo": id_testo,
        "sede": sede,
        "sede_esame": None,
        "commissione": None,
        "seduta_data": None,
        "data_presentazione": get("FRBRdate", "date"),
        "numero": numero,
        "versione": versione,
        "tipo": tipo,
        "articolo": numero.split(".")[0] if tipo != "ordine_del_giorno" else None,
        "esito": esiti.get(id_testo),
        "decreto": None,
        "documento": None,
        "firmatari": firmatari,
        "testo": block_text(nodes.get("amendmentContent")),
        "fonte": f"https://www.senato.it/show-doc?leg={leg}&tipodoc={tipodoc}&id={id_testo}",
    }


def parse_senato(akn_dir: Path, fasi: dict[str, dict], esiti: dict[str, str], leg: int,
                 empty: list[dict]):
    """Yield one row per text id; jointly examined bills share files.

    Empty Akoma Ntoso files are appended to `empty` so their text can be
    fetched from senato.it.
    """
    seen: dict[str, dict] = {}
    for atto_dir in sorted(akn_dir.glob("Atto*")):
        id_fase = str(int(atto_dir.name[4:]))
        fase = fasi.get(id_fase)
        if fase is None:
            continue
        for sub, sede in (("emendc", "commissione"), ("emend", "assemblea")):
            folder = atto_dir / sub
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.akn.xml")):
                id_testo = str(int(path.name.split("-", 1)[0]))
                if id_testo in seen:
                    if fase["fase"] not in seen[id_testo]["atti_congiunti"] and fase["fase"] != seen[id_testo]["atto"]:
                        seen[id_testo]["atti_congiunti"].append(fase["fase"])
                    continue
                row = parse_senato_akn(path, fase, sede, esiti, leg)
                if row is None:
                    empty.append({"id_testo": id_testo, "id_fase": id_fase, "atto": fase["fase"], "sede": sede})
                    continue
                seen[id_testo] = row
    yield from seen.values()


# Fallback for texts missing from Akoma Ntoso: ListEmendc pages (whole bill,
# committee) and single EMEND pages share the same block markup.
HTML_BLOCK_RE = re.compile(r'<p style="text-align:justify" ><b>([^<]+)</b></p>')
HTML_FIRM_RE = re.compile(r'<p class="firm".*?</p>', re.S)
HTML_SIGNER_RE = re.compile(r'SANASEN&amp;id=(\d+)"[^>]*>(.*?)</a>', re.S | re.I)
HTML_ESITO_RE = re.compile(r'\s*<p><b>([^<]+)</b></p>(?:</b>)?')


def html_to_text(fragment: str) -> str:
    fragment = re.sub(r"</p>|<br\s*/?>", "\n", fragment, flags=re.I)
    return normalize_space(html.unescape(re.sub(r"<[^>]+>", "", fragment)))


def html_signers(firm_html: str) -> list[dict]:
    signers = [
        {"id": f"S:{sid}", "nome": html_to_text(nome), "tipo": "senatore", "primo": i == 0}
        for i, (sid, nome) in enumerate(HTML_SIGNER_RE.findall(firm_html))
    ]
    plain = html_to_text(re.sub(r"<a\b[^>]*>.*?</a>", "", firm_html, flags=re.S | re.I))
    for nome in (n.strip() for n in plain.split(",")):
        if nome:
            signers.append({"id": None, "nome": nome, "tipo": senato_signer_type(nome), "primo": not signers})
    return signers


def parse_senato_html(page: str, fase: dict, sede: str, esiti_by_num: dict, leg: int,
                      id_testo: str | None = None):
    body = page[page.find('class="bgt"'):]
    body = body[:body.find("</section>")]
    parts = HTML_BLOCK_RE.split(body)
    for raw_numero, block in zip(parts[1::2], parts[2::2]):
        firm = HTML_FIRM_RE.search(block)
        rest = block[firm.end():] if firm else block
        esito_m = HTML_ESITO_RE.match(rest)
        if esito_m:
            rest = rest[esito_m.end():]
        numero, versione = split_version(html.unescape(raw_numero))
        tipo = "ordine_del_giorno" if numero.startswith("G") else "emendamento"
        tipodoc = "EMEND" if sede == "assemblea" else "EMENDC"
        yield {
            "ramo": "S", "atto": fase["fase"], "atti_congiunti": [], "id_ddl": fase["idDdl"],
            "id_testo": id_testo, "sede": sede, "sede_esame": None, "commissione": None,
            "seduta_data": None, "data_presentazione": None, "numero": numero, "versione": versione,
            "tipo": tipo, "articolo": numero.split(".")[0] if tipo != "ordine_del_giorno" else None,
            "esito": (esito_m.group(1).strip() if esito_m else None)
                     or esiti_by_num.get((fase["idFase"], sede, html.unescape(raw_numero).strip())),
            "decreto": None, "documento": None,
            "firmatari": html_signers(firm.group(0) if firm else ""),
            "testo": html_to_text(rest),
            "fonte": (f"https://www.senato.it/show-doc?leg={leg}&tipodoc={tipodoc}&id={id_testo}" if id_testo
                      else f"https://www.senato.it/show-doc?leg={leg}&tipodoc=ListEmendc&id={fase['idFase']}"),
        }


# --------------------------------------------------------------------- main

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    args = ap.parse_args()

    camera_dir = DOWNLOADS / "emendamenti_camera" / f"leg{args.leg}"
    senato_dir = DOWNLOADS / "emendamenti_senato" / f"leg{args.leg}"
    akn_dir = DOWNLOADS / "akn_senato" / f"Leg{args.leg}"
    out_dir = DOWNLOADS / "emendamenti"
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    id_ddl = camera_id_ddl(args.leg)
    for path in sorted(camera_dir.glob("ac.*.xml"), key=lambda p: int(p.stem.split(".")[1])):
        rows.extend(parse_camera(path, id_ddl, args.leg))
    with open(senato_dir / "fasi.csv") as f:
        fasi = {r["idFase"]: r for r in csv.DictReader(f)}
    esiti, esiti_by_num = load_esiti_senato(senato_dir / "esiti.csv")
    akn_vuoti: list[dict] = []
    rows.extend(parse_senato(akn_dir, fasi, esiti, args.leg, akn_vuoti))

    # Bills whose committee amendments are missing from Akoma Ntoso
    akn_comm = {str(int(d.name[4:])) for d in akn_dir.glob("Atto*") if (d / "emendc").is_dir()}
    html_fallback = 0
    for path in sorted(senato_dir.glob("emendc.*.html")):
        id_fase = path.stem.split(".", 1)[1]
        if id_fase in akn_comm or id_fase not in fasi:
            continue
        for row in parse_senato_html(path.read_text(encoding="utf-8"), fasi[id_fase], "commissione",
                                     esiti_by_num, args.leg):
            rows.append(row)
            html_fallback += 1

    # Empty Akoma Ntoso files: single pages fetched by download_esiti_senato.py --singoli
    singoli_dir = senato_dir / "singoli"
    recuperati = 0
    for v in akn_vuoti:
        page = singoli_dir / f"{v['id_testo']}.html"
        if page.exists() and v["id_fase"] in fasi:
            for row in parse_senato_html(page.read_text(encoding="utf-8"), fasi[v["id_fase"]], v["sede"],
                                         esiti_by_num, args.leg, id_testo=v["id_testo"]):
                row["esito"] = row["esito"] or esiti.get(v["id_testo"])
                rows.append(row)
                recuperati += 1
    with open(senato_dir / "akn_vuoti.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id_testo", "id_fase", "atto", "sede"])
        w.writeheader()
        w.writerows(akn_vuoti)
    letti = len(rows)

    seen, unique, duplicati = set(), [], 0
    for r in rows:
        r["testo_hash"] = text_hash(r["testo"])
        key = (r["ramo"], r["atto"], r["sede"], r["seduta_data"], r["numero"], r["versione"], r["testo_hash"])
        if key in seen:
            duplicati += 1
            continue
        seen.add(key)
        unique.append(r)

    # Chamber: the same number in the same sitting with the same signatories is
    # one amendment listed twice, as presented and as reformulated/approved.
    # Keep the row with the outcome and remember the presented text.
    signer_set = lambda r: tuple(sorted(f["id"] or f["tipo"] or "" for f in r["firmatari"]))  # noqa: E731
    merged, riformulazioni = [], 0
    by_slot = collections.defaultdict(list)
    for r in unique:
        r["testo_presentato"] = None
        if r["ramo"] == "C":
            by_slot[(r["atto"], r["sede"], r["seduta_data"], r["numero"], r["versione"], signer_set(r))].append(r)
        else:
            merged.append(r)
    for members in by_slot.values():
        if len(members) > 1:
            keep = next((m for m in reversed(members) if m["esito"]), members[-1])
            keep["testo_presentato"] = next((m["testo"] for m in members if m is not keep and m["testo"] != keep["testo"]), None)
            riformulazioni += len(members) - 1
            merged.append(keep)
        else:
            merged.append(members[0])
    unique = merged

    # Stable id. Senate texts have their own id; for the Chamber the same number
    # with different signatories in the same sitting gets a #n suffix.
    id_count = collections.Counter()
    for r in unique:
        if r["ramo"] == "S" and r["id_testo"]:
            r["id"] = f"S|{r['id_testo']}"
            continue
        base = "|".join(str(x or "") for x in (r["ramo"], r["atto"], r["sede"], r["seduta_data"], r["numero"], r["versione"]))
        id_count[base] += 1
        r["id"] = base if id_count[base] == 1 else f"{base}#{id_count[base]}"
    stesso_numero = collections.Counter(base.split("|", 1)[0] for base, n in id_count.items() if n > 1)
    senato_numero_ripetuto = sum(n - 1 for n in collections.Counter(
        (r["atto"], r["sede"], r["numero"], r["versione"]) for r in unique if r["ramo"] == "S").values() if n > 1)

    def group_key(r):
        return (r["ramo"], r["atto"], r["testo_hash"], signer_set(r))

    groups = collections.defaultdict(list)
    for r in unique:
        groups[group_key(r)].append(r)
    for members in groups.values():
        for r in members:
            r["gruppo_id"] = members[0]["id"]

    fields = ["id", "ramo", "atto", "atti_congiunti", "id_ddl", "id_testo", "sede", "sede_esame",
              "commissione", "seduta_data", "data_presentazione", "numero", "versione", "tipo",
              "articolo", "esito", "decreto", "documento", "firmatari", "testo", "testo_presentato",
              "testo_hash", "gruppo_id", "fonte"]
    out = out_dir / f"emendamenti_leg{args.leg}.jsonl"
    tmp = out.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in unique:
            f.write(json.dumps({k: r.get(k) for k in fields}, ensure_ascii=False) + "\n")
    os.replace(tmp, out)

    report = {
        "righe_lette": letti,
        "doppioni_esatti_rimossi": duplicati,
        "emendamenti_scritti": len(unique),
        "gruppi_distinti": len(groups),
        "gruppi_ripresentati": sum(1 for m in groups.values() if len(m) > 1),
        "camera_riformulazioni_unite": riformulazioni,
        "camera_stesso_numero_firmatari_diversi": dict(stesso_numero),
        "senato_numero_ripetuto_in_giri_diversi": senato_numero_ripetuto,
        "per_ramo_sede": dict(collections.Counter(f"{r['ramo']}:{r['sede']}" for r in unique)),
        "per_tipo": dict(collections.Counter(r["tipo"] for r in unique)),
        "con_esito": dict(collections.Counter(r["ramo"] for r in unique if r["esito"])),
        "con_data_presentazione": sum(1 for r in unique if r["data_presentazione"]),
        "senato_congiunti": sum(1 for r in unique if r["atti_congiunti"]),
        "senza_id_ddl": sum(1 for r in unique if not r["id_ddl"]),
        "senza_testo": sum(1 for r in unique if not r["testo"]),
        "senza_firmatari": sum(1 for r in unique if not r["firmatari"]),
        "senato_akn_vuoti": dict(collections.Counter(x["sede"] for x in akn_vuoti)),
        "senato_akn_vuoti_recuperati": recuperati,
        "senato_da_html_commissione": html_fallback,
    }
    (out_dir / f"report_leg{args.leg}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Scritto {out}")


if __name__ == "__main__":
    main()
