"""
download_emendamenti_camera.py — download Chamber of Deputies amendment XMLs.

The Chamber publishes one file per bill reading:
    https://documenti.camera.it/leg19/emendamenti/xml/leg.19.eme.ac.{N}.xml
N is the AC number, or the number with a suffix for a later reading
("1038-B", a bill back from the Senate) or a split-off bill ("643-bis", the
budget law after the stralcio). There is no index: plain numbers are all
tried, suffixed ones come from the Senate SPARQL readings with ramo C. A 404
means the reading has no amendments (usually it never reached examination).

Resumable: skips files already saved and numbers recorded as 404 in
missing.txt. --refresh re-downloads everything.

Nightly mode (--recenti N). A file grows with every new committee or floor
sitting while its internal timeStamp does not change, and the bill status in
the Senate SPARQL often stays the same for weeks of examination, so the
status alone misses new amendments. Every night:
  - every file already saved is asked again with If-Modified-Since set to its
    mtime: the server answers 304 when nothing changed, so this costs one
    small request per bill;
  - readings whose status changed in the last N days are downloaded in full;
  - numbers never probed up to the highest known AC (+ PROBE_AHEAD) and
    suffixed readings never probed are tried;
  - one seventh of the numbers recorded as 404 is tried again (a different
    seventh each day), so a bill that gets its first amendments is found
    within a week even when its status does not change.
The readings are also saved to downloads/emendamenti/fasi_camera_leg{N}.csv,
which parse_emendamenti.py reads for id_ddl.

Usage:
    python build/download_emendamenti_camera.py [--recenti 14] [--start 1] [--end 3200] [--delay 0.5]
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import time
from datetime import date
from email.utils import formatdate
from pathlib import Path

import requests

from download_emendamenti_senato import changed_since, fetch_fasi

URL = "https://documenti.camera.it/leg{leg}/emendamenti/xml/leg.{leg}.eme.ac.{n}.xml"
REPO_ROOT = Path(__file__).resolve().parent.parent
# Bills presented after the last run must be probed even before any SPARQL
# reading shows them: probe this many numbers past the highest known one.
PROBE_AHEAD = 30
# Numbers recorded as 404 are probed again over this many nights, a slice per night.
REPROBE_NIGHTS = 7

# "1038-B", "384-446-459-B" (joint bills: the file takes the first number),
# "643-BIS", "2112-quinquies"; "643-BIS/I" is a reading absorbed into another.
SUFFIXED_RE = re.compile(r"^(\d+)(?:-\d+)*-([A-Za-z]+)$")


def camera_key(numero_fase: str) -> str | None:
    """File key of a Chamber reading, as in the act URI: '1038-B', '643-bis'.

    One-letter suffixes (later readings) are upper case, word suffixes
    (split-off bills) lower case; None for readings with no file of their own.
    """
    numero_fase = numero_fase.strip()
    if numero_fase.isdigit():
        return str(int(numero_fase))
    m = SUFFIXED_RE.match(numero_fase)
    if not m:
        return None
    suffix = m.group(2)
    return f"{int(m.group(1))}-{suffix.upper() if len(suffix) == 1 else suffix.lower()}"


def key_order(key: str) -> tuple[int, str]:
    base, _, suffix = key.partition("-")
    return int(base), suffix


def key_base(key: str) -> int:
    return int(key.partition("-")[0])


def select_targets(fasi: list[dict], days: int, have: set[str], missing: set[str],
                   today: date | None = None) -> tuple[list[str], set[str], int]:
    """Nightly targets: (all keys to ask, keys to download in full, top AC).

    Saved files are all asked again (conditionally, see module docstring);
    `full` holds the readings whose status changed in the last `days` days.
    """
    today = today or date.today()
    readings: dict[str, dict] = {}
    for f in fasi:
        key = camera_key(f["numeroFase"])
        if key and (key not in readings or (f.get("data") or "") > (readings[key].get("data") or "")):
            readings[key] = f
    known = set(readings) | have | missing
    top = max((key_base(k) for k in known), default=0) + PROBE_AHEAD
    full = {k for k, f in readings.items() if changed_since(f, days)}
    plain = {str(n) for n in range(1, top + 1)}
    unprobed = {k for k in plain | set(readings) if k not in have and k not in missing}
    reprobe = {k for k in missing if key_base(k) % REPROBE_NIGHTS == today.toordinal() % REPROBE_NIGHTS}
    return sorted(full | unprobed | have | reprobe, key=key_order), full, top


def conditional_headers(target: Path, full: bool) -> dict[str, str]:
    """If-Modified-Since from the file mtime, unless a full download is wanted."""
    if full or not target.exists():
        return {}
    return {"If-Modified-Since": formatdate(target.stat().st_mtime, usegmt=True)}


def save_fasi(fasi: list[dict], path: Path) -> None:
    """numeroFase -> idDdl for parse_emendamenti.py, one row per file key."""
    rows = {}
    for f in sorted(fasi, key=lambda f: f.get("data") or ""):
        key = camera_key(f["numeroFase"])
        if key:
            rows[key] = f["idDdl"]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.tmp")
    with open(tmp, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["numeroFase", "idDdl"])
        w.writerows(sorted(rows.items(), key=lambda kv: key_order(kv[0])))
    tmp.replace(path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=3200)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "downloads" / "emendamenti_camera")
    ap.add_argument("--recenti", type=int, metavar="GIORNI",
                    help="nightly mode: saved files if changed, readings with a recent status change, "
                         "unprobed numbers, a slice of the 404s")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    out = args.out / f"leg{args.leg}"
    out.mkdir(parents=True, exist_ok=True)
    missing_file = out / "missing.txt"
    missing = set() if args.refresh or not missing_file.exists() else set(missing_file.read_text().split())
    have = {p.name[len("ac."):-len(".xml")] for p in out.glob("ac.*.xml")}

    full: set[str] | None = None  # None: every request is a full download
    if args.recenti is not None:
        try:
            fasi = fetch_fasi(args.leg, ramo="C")
        except requests.RequestException as exc:
            # Without the readings the saved files are still checked.
            print(f"SPARQL Senato non raggiungibile ({exc}): controllo solo i file già scaricati", flush=True)
            fasi = []
        if fasi:
            save_fasi(fasi, REPO_ROOT / "downloads" / "emendamenti" / f"fasi_camera_leg{args.leg}.csv")
        targets, full, top = select_targets(fasi, args.recenti, have, missing)
        print(f"Modalità notturna: {len(targets)} atti da controllare (fino ad AC {top}): "
              f"{len(have)} già scaricati chiesti solo se cambiati, {len(full & have)} con lo stato cambiato "
              f"riscaricati per intero", flush=True)
    else:
        targets = [str(n) for n in range(args.start, args.end + 1)
                   if args.refresh or (str(n) not in have and str(n) not in missing)]

    http = requests.Session()
    http.headers["User-Agent"] = "ParliamentRAG/1.0 (ricerca; parliamentrag.it)"

    def write_missing() -> None:
        missing_file.write_text("\n".join(sorted(missing, key=key_order)))

    found = errors = unchanged = 0
    total_bytes = 0
    for i, n in enumerate(targets, 1):
        target = out / f"ac.{n}.xml"
        headers = conditional_headers(target, full is None or n in full)
        r = None
        for attempt in range(3):
            try:
                r = http.get(URL.format(leg=args.leg, n=n), headers=headers, timeout=120)
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    print(f"AC {n}: errore di rete ({exc})", flush=True)
                time.sleep(5 * (attempt + 1))
        if r is None:
            errors += 1
        elif r.status_code == 304:
            unchanged += 1
        elif r.status_code == 200 and r.content.lstrip().startswith((b"<?xml", b"\xef\xbb\xbf<?xml")):
            changed = not target.exists() or target.read_bytes() != r.content
            if changed:
                tmp = target.with_suffix(".xml.tmp")
                tmp.write_bytes(r.content)
                tmp.replace(target)
                found += 1
                total_bytes += len(r.content)
                print(f"AC {n}: {len(r.content) / 1e6:.2f} MB", flush=True)
            else:
                # Same content: move the mtime forward so that tomorrow's
                # If-Modified-Since gets a 304 instead of the whole file again.
                os.utime(target)
            missing.discard(n)
        elif r.status_code == 404:
            if not target.exists():
                missing.add(n)
        else:
            errors += 1
            print(f"AC {n}: HTTP {r.status_code}", flush=True)
        if i % 100 == 0:
            write_missing()
            print(f"-- {i}/{len(targets)}: {found} file nuovi o cambiati, {total_bytes / 1e6:.0f} MB", flush=True)
        time.sleep(args.delay)

    write_missing()
    print(f"Fine: {len(targets)} atti controllati, {found} file nuovi o cambiati ({total_bytes / 1e6:.0f} MB), "
          f"{unchanged} invariati (304), {len(missing)} senza emendamenti, {errors} errori", flush=True)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
