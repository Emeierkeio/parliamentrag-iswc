"""Published law of a parliamentary act, from the Normattiva ingest.

An act is a reading of a legislative process: (act)-[:PART_OF]->
(:LegislativeProcess)-[:BECAME_LAW]->(:Law), written by
build/ingest_laws.py. Every reading of the process (C.2822, S.1971,
C.2822-B) resolves to the same law; acts outside a concluded process
have none.
"""
from __future__ import annotations

import re
from typing import Iterable

from ..models.timeline import LawRef
from .neo4j_client import Neo4jClient

LAW_BY_ACT = """
UNWIND $uris AS uri
MATCH (:ParliamentaryAct {uri: uri})-[:PART_OF]->(:LegislativeProcess)-[:BECAME_LAW]->(l:Law)
RETURN uri,
       l.kind AS kind,
       l.number AS number,
       toString(l.date) AS date,
       l.eli AS eli,
       l.normattiva_url AS normattiva_url,
       l.gu_number AS gu_number,
       toString(l.gu_date) AS gu_date,
       l.title AS title
"""

_MONTHS = (
    "gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno",
    "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre",
)
_KIND = {"legge": "Legge", "legge_costituzionale": "Legge costituzionale"}


def italian_date(iso: str | None) -> str | None:
    """'2026-10-09' → '9 ottobre 2026'."""
    try:
        y, m, d = (int(x) for x in (iso or "")[:10].split("-"))
        return f"{d} {_MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return None


def law_ref(row: dict) -> LawRef:
    """Build the response model from a LAW_BY_ACT row."""
    day = italian_date(row.get("date"))
    label = f"{_KIND.get(row.get('kind'), 'Legge')} n. {row['number']}"
    return LawRef(
        kind=row.get("kind") or "legge",
        number=row["number"],
        date=row.get("date"),
        label=f"{label} del {day}" if day else label,
        eli=row.get("eli"),
        normattiva_url=row.get("normattiva_url"),
        gu_number=row.get("gu_number"),
        gu_date=row.get("gu_date"),
        title=row.get("title"),
    )


def laws_for_acts(neo4j: Neo4jClient, uris: Iterable[str | None]) -> dict[str, LawRef]:
    """Map each act URI that became law to its law; others are absent."""
    wanted = sorted({u for u in uris if u})
    if not wanted:
        return {}
    rows = neo4j.query(LAW_BY_ACT, {"uris": wanted})
    return {r["uri"]: law_ref(r) for r in rows if r.get("number") is not None}


# "legge 180/2026", "L. 180/2026", "legge n. 180 del 2026", "legge 9 ottobre
# 2026, n. 180", "legge costituzionale n. 1 del 2026"
_NUM_YEAR = re.compile(
    r"\b(?P<kind>legge|l\.)\s*(?P<cost>costituzionale\s*)?(?:n\.?|numero)?\s*(?P<num>\d{1,4})\s*"
    r"(?:/\s*|del(?:l['’])?\s+(?:\d{1,2}\s+[a-z]+\s+)?)(?P<year>(?:19|20)\d{2})\b",
    re.IGNORECASE,
)
_DATE_NUM = re.compile(
    r"\blegge\s*(?P<cost>costituzionale\s*)?\d{1,2}\s+[a-z]+\s+(?P<year>(?:19|20)\d{2}),?\s*n\.?\s*(?P<num>\d{1,4})\b",
    re.IGNORECASE,
)


def parse_law_reference(text: str | None) -> tuple[int, int, str | None] | None:
    """(number, year, kind) of a law cited in a search query, else None.
    kind is "legge_costituzionale" when the query says so, else None (any)."""
    if not text:
        return None
    m = _NUM_YEAR.search(text) or _DATE_NUM.search(text)
    if not m:
        return None
    kind = "legge_costituzionale" if m.group("cost") else None
    return int(m.group("num")), int(m.group("year")), kind


ACTS_OF_LAW = """
MATCH (l:Law {number: $number})
WHERE l.date.year = $year AND ($kind IS NULL OR l.kind = $kind)
MATCH (a:ParliamentaryAct)-[:PART_OF]->(:LegislativeProcess)-[:BECAME_LAW]->(l)
RETURN DISTINCT a.uri AS uri
"""


def acts_of_law(neo4j: Neo4jClient, text: str | None) -> list[str]:
    """URIs of every reading of the law a query names ("legge 180/2026"),
    or [] when the query names no law or the law is not in the graph."""
    ref = parse_law_reference(text)
    if not ref:
        return []
    number, year, kind = ref
    return [r["uri"] for r in neo4j.query(ACTS_OF_LAW, {"number": number, "year": year, "kind": kind})
            if r.get("uri")]
