"""
download_esiti_senato.py — outcomes of Senate amendments, committee and floor.

The Akoma Ntoso bulk data (SenatoDellaRepubblica/AkomaNtosoBulkData) carry
the amendment text and presentation date but no outcome. The bill page lists
every amendment with its outcome:
    https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl?tab=testiEmendamenti&did={idFase}
Each entry links to tipodoc=EMEND (floor) or EMENDC (committee) with the same
numeric id used in the Akoma Ntoso file names (01521763-em.akn.xml ↔ 1521763).

Writes esiti.csv (id_fase, sede, id_testo, numero, esito). Resumable through
done.txt; --refresh starts over; --recenti N re-fetches the readings whose
status changed in the last N days (the nightly mode). Reads fasi.csv written
by download_emendamenti_senato.py.

Then fetches the single amendment page (tipodoc=EMEND/EMENDC) for every
empty Akoma Ntoso file, into singoli/{id_testo}.html, for parse_emendamenti.py.

senato.it sits behind an AWS WAF JS challenge that kicks in after a burst of
requests (HTTP 202). On a challenge the script solves it with headless
Playwright (download_senate._get_waf_token) and retries with the token.

Usage:
    python build/download_esiti_senato.py [--delay 0.5]
"""

from __future__ import annotations

import argparse
import csv
import html
import re
import time
from pathlib import Path

import requests

from download_senate import _get_waf_token, _is_challenge, _make_session

REPO_ROOT = Path(__file__).resolve().parent.parent
TAB_URL = ("https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl"
           "?tab=testiEmendamenti&did={id_fase}")
USER_AGENT = "ParliamentRAG/1.0 (ricerca; parliamentrag.it)"
ENTRY_RE = re.compile(
    r'tipodoc=(EMENDC?)&amp;id=(\d+)[^"]*">([^<]+)</a>\s*</dt>\s*<dd>(.*?)</dd>', re.S)
FIELDS = ["id_fase", "sede", "id_testo", "numero", "esito"]


def parse_entries(page: str, id_fase: str) -> list[dict]:
    rows = []
    for tipodoc, id_testo, numero, dd in ENTRY_RE.findall(page):
        esito = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", dd)).split()) or None
        rows.append({
            "id_fase": id_fase,
            "sede": "assemblea" if tipodoc == "EMEND" else "commissione",
            "id_testo": id_testo,
            "numero": " ".join(html.unescape(numero).split()),
            "esito": esito,
        })
    return rows


class SenateFetcher:
    """GET with retries that solves the AWS WAF challenge when it appears."""

    def __init__(self, max_failed_refreshes: int = 3):
        self.http = requests.Session()
        self.http.headers["User-Agent"] = USER_AGENT
        self.refreshes = 0
        # The token expires every few dozen pages, so refreshes are routine.
        # Give up only when fresh tokens keep getting challenged with no
        # successful page in between.
        self.failed_refreshes = 0
        self.max_failed_refreshes = max_failed_refreshes

    def get(self, url: str, label: str) -> requests.Response | None:
        r = None
        for attempt in range(3):
            try:
                r = self.http.get(url, timeout=120)
            except requests.RequestException as exc:
                if attempt == 2:
                    print(f"{label}: errore di rete ({exc})", flush=True)
                time.sleep(5 * (attempt + 1))
                continue
            if r.status_code == 403:
                # A rate-based WAF block: every page, the home page included, answers
                # 403 for a while. Retrying only extends it.
                raise SystemExit("Senato: accesso bloccato (403), riprovare più tardi")
            if not _is_challenge(r):
                self.failed_refreshes = 0
                return r
            if self.failed_refreshes >= self.max_failed_refreshes:
                raise SystemExit("WAF: challenge ripetuta anche con token nuovi, interrotto")
            self.failed_refreshes += 1
            token = _get_waf_token()
            self.refreshes += 1
            if not token:
                raise SystemExit("WAF: challenge non risolta (Playwright installato?)")
            self.http = _make_session(token)
            print(f"-- token WAF rinnovato ({self.refreshes})", flush=True)
        return r


def forget(out: Path, ids: set[str]) -> None:
    """Drop readings from esiti.csv and done.txt so they are fetched again."""
    esiti_path, done_path = out / "esiti.csv", out / "done.txt"
    if esiti_path.exists():
        with open(esiti_path) as f:
            keep = [r for r in csv.DictReader(f) if r["id_fase"] not in ids]
        with open(esiti_path, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(keep)
    if done_path.exists():
        done_path.write_text("".join(f"{i}\n" for i in done_path.read_text().split() if i not in ids))


def download_esiti(fetcher: SenateFetcher, out: Path, fasi: list[dict], delay: float, refresh: bool,
                   recenti: int | None = None) -> int:
    esiti_path, done_path = out / "esiti.csv", out / "done.txt"
    if refresh:
        esiti_path.unlink(missing_ok=True)
        done_path.unlink(missing_ok=True)
    elif recenti is not None:
        from download_emendamenti_senato import changed_since
        stale = {f["idFase"] for f in fasi if changed_since(f, recenti)}
        forget(out, stale)
        print(f"Esiti da riscaricare per stato cambiato negli ultimi {recenti} giorni: {len(stale)}", flush=True)
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    new_file = not esiti_path.exists()
    total = errors = 0
    with open(esiti_path, "a", newline="") as fout, open(done_path, "a") as fdone:
        writer = csv.DictWriter(fout, fieldnames=FIELDS)
        if new_file:
            writer.writeheader()
        for i, fase in enumerate(fasi, 1):
            id_fase = fase["idFase"]
            if id_fase in done:
                continue
            r = fetcher.get(TAB_URL.format(id_fase=id_fase), f"{fase['fase']} ({id_fase})")
            if r is None or r.status_code != 200:
                errors += 1
                print(f"{fase['fase']} ({id_fase}): HTTP {getattr(r, 'status_code', '-')}", flush=True)
            else:
                rows = parse_entries(r.text, id_fase)
                writer.writerows(rows)
                fout.flush()
                fdone.write(id_fase + "\n")
                fdone.flush()
                total += len(rows)
                if rows:
                    aula = sum(1 for x in rows if x["sede"] == "assemblea")
                    print(f"{fase['fase']} ({id_fase}): {len(rows)} voci, {aula} d'Aula", flush=True)
            if i % 100 == 0:
                print(f"-- {i}/{len(fasi)}: {total} voci", flush=True)
            time.sleep(delay)
    print(f"Esiti: {total} voci scritte, {errors} errori", flush=True)
    return errors


def empty_akn_files(akn_dir: Path) -> list[tuple[str, str, str]]:
    """(id_testo, tipodoc, id_fase) for the empty <akomaNtoso/> files in the bulk data."""
    found = []
    for path in akn_dir.glob("Atto*/emend*/*.akn.xml"):
        if path.stat().st_size < 600 and "<an:amendment" not in path.read_text(encoding="utf-8", errors="ignore"):
            tipodoc = "EMEND" if path.parent.name == "emend" else "EMENDC"
            found.append((str(int(path.name.split("-", 1)[0])), tipodoc, str(int(path.parent.parent.name[4:]))))
    return sorted(found)


IDOGGETTO_RE = re.compile(r"tipodoc=EMENDC?&amp;id=(\d+)&amp;idoggetto=(\d+)")


def download_singoli(fetcher: SenateFetcher, out: Path, akn_dir: Path, leg: int, delay: float) -> int:
    """Single amendment pages need the idoggetto the bill page links them with."""
    singoli = out / "singoli"
    singoli.mkdir(exist_ok=True)
    todo = [t for t in empty_akn_files(akn_dir) if not (singoli / f"{t[0]}.html").exists()]
    print(f"Testi singoli da scaricare: {len(todo)}", flush=True)
    by_fase: dict[str, list[tuple[str, str]]] = {}
    for id_testo, tipodoc, id_fase in todo:
        by_fase.setdefault(id_fase, []).append((id_testo, tipodoc))
    errors = done = 0
    for id_fase, items in by_fase.items():
        r = fetcher.get(TAB_URL.format(id_fase=id_fase), f"scheda {id_fase}")
        if r is None or r.status_code != 200:
            errors += len(items)
            print(f"scheda {id_fase}: HTTP {getattr(r, 'status_code', '-')}", flush=True)
            continue
        idoggetto = dict(IDOGGETTO_RE.findall(r.text))
        time.sleep(delay)
        for id_testo, tipodoc in items:
            if id_testo not in idoggetto:
                errors += 1
                print(f"{tipodoc} {id_testo}: non elencato nella scheda {id_fase}", flush=True)
                continue
            url = (f"https://www.senato.it/show-doc?leg={leg}&tipodoc={tipodoc}"
                   f"&id={id_testo}&idoggetto={idoggetto[id_testo]}")
            page = fetcher.get(url, f"{tipodoc} {id_testo}")
            if page is not None and page.status_code == 200 and 'class="bgt"' in page.text:
                (singoli / f"{id_testo}.html").write_text(page.text, encoding="utf-8")
                done += 1
            else:
                errors += 1
                print(f"{tipodoc} {id_testo}: HTTP {getattr(page, 'status_code', '-')}", flush=True)
            if (done + errors) % 100 == 0:
                print(f"-- singoli {done + errors}/{len(todo)}", flush=True)
            time.sleep(delay)
    print(f"Singoli: {done} scaricati, {errors} errori", flush=True)
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--dir", type=Path, default=REPO_ROOT / "downloads" / "emendamenti_senato")
    ap.add_argument("--akn-dir", type=Path, default=REPO_ROOT / "downloads" / "akn_senato")
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--recenti", type=int, metavar="GIORNI",
                    help="re-fetch readings whose status changed in the last N days")
    ap.add_argument("--solo-singoli", action="store_true",
                    help="download only the single pages for empty Akoma Ntoso files")
    args = ap.parse_args()

    out = args.dir / f"leg{args.leg}"
    with open(out / "fasi.csv") as f:
        fasi = list(csv.DictReader(f))
    fetcher = SenateFetcher()
    errors = 0
    if not args.solo_singoli:
        errors += download_esiti(fetcher, out, fasi, args.delay, args.refresh, args.recenti)
    errors += download_singoli(fetcher, out, args.akn_dir / f"Leg{args.leg}", args.leg, args.delay)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
