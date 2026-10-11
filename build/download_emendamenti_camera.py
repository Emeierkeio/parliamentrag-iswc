"""
download_emendamenti_camera.py — download Chamber of Deputies amendment XMLs.

The Chamber publishes one file per bill:
    https://documenti.camera.it/leg19/emendamenti/xml/leg.19.eme.ac.{N}.xml
There is no index, so every AC number is tried. A 404 means the bill has no
amendments (usually it never reached examination).

Resumable: skips files already saved and numbers recorded as 404 in
missing.txt. Files change when a bill goes back to committee or to the floor
while their internal timeStamp does not, so the nightly mode (--recenti N)
re-downloads the bills whose status changed in the last N days, read from the
Senate SPARQL readings with ramo C, plus numbers never probed. --refresh
re-downloads everything.

Usage:
    python build/download_emendamenti_camera.py [--recenti 14] [--start 1] [--end 3200] [--delay 0.5]
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import requests

from download_emendamenti_senato import changed_since, fetch_fasi

URL = "https://documenti.camera.it/leg{leg}/emendamenti/xml/leg.{leg}.eme.ac.{n}.xml"
REPO_ROOT = Path(__file__).resolve().parent.parent
# Bills presented after the last run must be probed even before any SPARQL
# reading shows them: probe this many numbers past the highest known one.
PROBE_AHEAD = 30


def nightly_targets(leg: int, days: int, have: set[int], missing: set[int]) -> tuple[list[int], int]:
    """AC numbers with a status change in the last `days` days, plus unprobed ones."""
    fasi = fetch_fasi(leg, ramo="C")
    numbers = {int(f["numeroFase"]): f for f in fasi if f["numeroFase"].isdigit()}
    top = max(numbers) + PROBE_AHEAD if numbers else max(have | missing | {0}) + PROBE_AHEAD
    recent = {n for n, f in numbers.items() if changed_since(f, days)}
    unprobed = {n for n in range(1, top + 1) if n not in have and n not in missing}
    return sorted(recent | unprobed), top


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--start", type=int, default=1)
    ap.add_argument("--end", type=int, default=3200)
    ap.add_argument("--delay", type=float, default=0.5)
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "downloads" / "emendamenti_camera")
    ap.add_argument("--recenti", type=int, metavar="GIORNI",
                    help="nightly mode: bills whose status changed in the last N days plus unprobed numbers")
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    out = args.out / f"leg{args.leg}"
    out.mkdir(parents=True, exist_ok=True)
    missing_file = out / "missing.txt"
    missing = set() if args.refresh or not missing_file.exists() else {int(x) for x in missing_file.read_text().split()}
    have = {int(p.stem.split(".")[1]) for p in out.glob("ac.*.xml")}

    if args.recenti is not None:
        targets, top = nightly_targets(args.leg, args.recenti, have, missing)
        print(f"Modalità notturna: {len(targets)} atti da controllare (fino ad AC {top})", flush=True)
    else:
        targets = [n for n in range(args.start, args.end + 1)
                   if args.refresh or (n not in have and n not in missing)]

    http = requests.Session()
    http.headers["User-Agent"] = "ParliamentRAG/1.0 (ricerca; parliamentrag.it)"

    found = errors = 0
    total_bytes = 0
    for i, n in enumerate(targets, 1):
        target = out / f"ac.{n}.xml"
        r = None
        for attempt in range(3):
            try:
                r = http.get(URL.format(leg=args.leg, n=n), timeout=120)
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    print(f"AC {n}: errore di rete ({exc})", flush=True)
                time.sleep(5 * (attempt + 1))
        if r is None:
            errors += 1
        elif r.status_code == 200 and r.content.lstrip().startswith((b"<?xml", b"\xef\xbb\xbf<?xml")):
            changed = not target.exists() or target.read_bytes() != r.content
            if changed:
                tmp = target.with_suffix(".xml.tmp")
                tmp.write_bytes(r.content)
                tmp.replace(target)
                found += 1
                total_bytes += len(r.content)
                print(f"AC {n}: {len(r.content) / 1e6:.2f} MB", flush=True)
            missing.discard(n)
        elif r.status_code == 404:
            if not target.exists():
                missing.add(n)
        else:
            errors += 1
            print(f"AC {n}: HTTP {r.status_code}", flush=True)
        if i % 100 == 0:
            missing_file.write_text("\n".join(str(x) for x in sorted(missing)))
            print(f"-- {i}/{len(targets)}: {found} file nuovi o cambiati, {total_bytes / 1e6:.0f} MB", flush=True)
        time.sleep(args.delay)

    missing_file.write_text("\n".join(str(x) for x in sorted(missing)))
    print(f"Fine: {len(targets)} atti controllati, {found} file nuovi o cambiati ({total_bytes / 1e6:.0f} MB), "
          f"{len(missing)} senza emendamenti, {errors} errori", flush=True)
    raise SystemExit(1 if errors else 0)


if __name__ == "__main__":
    main()
