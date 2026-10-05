"""
Seats in the Camera chamber, from https://www.camera.it/deputati/.

The page embeds the sitting deputies with their seat number
(`var deputati = [{"idAulDeputato": 306176, ..., "posto": 77}, ...]`) and the
floor plan as an SVG where every seat is a circle whose id is the seat number,
grouped by sector (S1..S11, Presidenza, Ministri, Banco_dei_Nove, ...).

Writes:
- data/seggi_camera_<leg>.csv: persona URI, seat number, group label as shown
  on the plan;
- data/aula_camera_layout.json: every seat with its coordinates and sector,
  used to draw the chamber.

Only the current legislature is published: the page shows today's seating.
"""

import argparse
import csv
import json
import os
import re
import sys

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")
PAGE_URL = "https://www.camera.it/deputati/"
ROMAN = {18: "xviii", 19: "xix", 20: "xx"}
USER_AGENT = "Mozilla/5.0 (ParliamentRAG research; +https://www.parliamentrag.it)"

_DEPUTIES_RE = re.compile(r"var deputati = (\[.*?\]);", re.S)
_LEGISLATURE_RE = re.compile(r"var legislatura = (\d+);")
_CIRCLE_RE = re.compile(r'<circle id="([^"]+)" cx="([\d.]+)" cy="([\d.]+)" r="([\d.]+)"')
_VIEWBOX_RE = re.compile(r'<svg[^>]*viewBox="([^"]+)"')


def parse_page(page: str) -> tuple[int, list[dict], dict]:
    """(legislature, deputies with seats, layout) from the page source."""
    leg = _LEGISLATURE_RE.search(page)
    deps = _DEPUTIES_RE.search(page)
    if not leg or not deps:
        raise ValueError("camera.it/deputati no longer embeds the seating data")
    deputies = [
        {
            "persona": f"http://dati.camera.it/ocd/persona.rdf/p{d['idAulDeputato']}",
            "posto": int(d["posto"]),
            "gruppo": d.get("siglaGruppo", ""),
        }
        for d in json.loads(deps.group(1))
        if d.get("posto")
    ]

    # Sector of each circle: the innermost <g id> open before it.
    seats = []
    sector = None
    stack: list[str] = []
    for m in re.finditer(r'<g id="([^"]+)"|</g>|' + _CIRCLE_RE.pattern, page):
        token = m.group(0)
        if token.startswith("<g "):
            stack.append(m.group(1))
        elif token == "</g>":
            if stack:
                stack.pop()
        else:
            seat_id = m.group(2)
            if seat_id == "blank" or not seat_id.isdigit():
                continue
            sector = stack[-1] if stack else None
            seats.append({
                "seat": int(seat_id),
                "x": float(m.group(3)),
                "y": float(m.group(4)),
                "r": float(m.group(5)),
                "sector": sector,
            })
    viewbox = _VIEWBOX_RE.search(page)
    layout = {"viewBox": viewbox.group(1) if viewbox else None, "seats": seats}
    return int(leg.group(1)), deputies, layout


def main() -> None:
    resp = requests.get(PAGE_URL, headers={"User-Agent": USER_AGENT}, timeout=60)
    resp.raise_for_status()
    legislature, deputies, layout = parse_page(resp.text)

    seats_csv = os.path.join(DATA_DIR, f"seggi_camera_{ROMAN.get(legislature, legislature)}.csv")
    with open(seats_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["persona", "posto", "gruppo"])
        w.writeheader()
        w.writerows(deputies)
    layout_json = os.path.join(DATA_DIR, "aula_camera_layout.json")
    with open(layout_json, "w", encoding="utf-8") as f:
        json.dump({"legislature": legislature, **layout}, f, ensure_ascii=False)

    print(f"Legislature {legislature}: {len(deputies)} deputies with a seat -> {seats_csv}")
    print(f"{len(layout['seats'])} seats in the floor plan -> {layout_json}")


if __name__ == "__main__":
    argparse.ArgumentParser(description=__doc__.split("\n\n")[0]).parse_args()
    try:
        main()
    except (requests.RequestException, ValueError) as exc:
        print(f"Seat download failed: {exc}", file=sys.stderr)
        sys.exit(1)
