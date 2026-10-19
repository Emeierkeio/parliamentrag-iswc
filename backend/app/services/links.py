"""Public pages of Chamber and Senate records, built from graph ids.

Camera speech anchors and bill pages were checked against camera.it on
2026-10-02, the Senate bill pages on 2026-10-14 (Stenografo,
apps/api/app/links.py) and 2026-10-19 (Scranno).
"""
from __future__ import annotations

import re
import urllib.parse

_CHUNK_SUFFIX = re.compile(r"_chunk_\d+$")


def https(url: str | None) -> str | None:
    """camera.it and senato.it serve every page on https; the open data
    still publish http links."""
    if url and url.startswith("http://") and re.match(r"http://[\w.-]*(camera|senato)\.it/", url):
        return "https://" + url[len("http://"):]
    return url


def camera_speech_url(record_id: str | None) -> str | None:
    """Stenographic record of a Camera speech, anchored on the speech, from
    its id or the id of one of its chunks (leg19_sed210_tit00020.int00060)."""
    m = re.match(r"leg(\d+)_sed(\d+)_(.+)", _CHUNK_SUFFIX.sub("", record_id or ""))
    if not m:
        return None
    leg, sed, rest = m.group(1), m.group(2).zfill(4), m.group(3)
    return f"https://www.camera.it/leg{leg}/410?idSeduta={sed}&tipo=stenografico#sed{sed}.stenografico.{rest}"


# The bill card on senato.it, by the id of dati.senato.it/ddl/<id> (checked
# by Scranno on 2026-10-19: 59875 is S.1786). Senate acts in the graph are
# all of the XIX legislature.
SENATE_BILL_PAGE = "https://www.senato.it/leg/19/BGT/Schede/Ddliter/{id}.htm"
# The "Testi ed emendamenti" tab of the bill page lists every text of the
# reading (download_esiti_senato.py reads the same tab).
SENATE_BILL_TEXTS = "https://www.senato.it/leggi-e-documenti/disegni-di-legge/scheda-ddl?tab=testiEmendamenti&did={id}"


def act_public_url(uri: str | None, url: str | None = None) -> str | None:
    """Public page of a ParliamentaryAct: its own `url` when it has one,
    else derived from the URI.

    - dati.senato.it/ddl/60149          → Senate bill page
    - attocamera.rdf/ac19_2822-B        → Camera bill page (any reading)
    - aic.rdf/aic9_01492_027_19         → AIC page (ODG/motion/resolution);
      the number is rebuilt from the URI segments ("9_02911_A_028" →
      "9/02911-A/028": letters are suffixes of the previous segment).
    """
    if url:
        return https(url)
    if not uri:
        return None
    m = re.match(r"https?://dati\.senato\.it/ddl/(\d+)$", uri)
    if m:
        return SENATE_BILL_PAGE.format(id=m.group(1))
    m = re.search(r"/attocamera\.rdf/ac(\d+)_([\w-]+)$", uri)
    if m:
        leg, num = m.group(1), m.group(2)
        return f"https://www.camera.it/leg{leg}/126?tab=1&leg={leg}&idDocumento={num}"
    m = re.search(r"/aic\.rdf/aic(.+)_(\d+)$", uri)
    if m:
        body, leg = m.group(1), m.group(2)
        segments: list[str] = []
        for part in body.split("_"):
            if part.isalpha() and segments:
                segments[-1] += f"-{part}"
            else:
                segments.append(part)
        numero = urllib.parse.quote("/".join(segments), safe="")
        return f"https://aic.camera.it/aic/scheda.html?numero={numero}&ramo=CAMERA&leg={leg}"
    return None


def act_text_url(uri: str | None, text_pdf: str | None = None, version_url: str | None = None) -> str | None:
    """Full text of an act: the PDF of the printed bill, else the first
    published version of the text, else (Senate bills) the texts tab."""
    if text_pdf or version_url:
        return https(text_pdf or version_url)
    m = re.match(r"https?://dati\.senato\.it/ddl/(\d+)$", uri or "")
    return SENATE_BILL_TEXTS.format(id=m.group(1)) if m else None
