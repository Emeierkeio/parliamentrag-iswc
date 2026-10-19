"""Published law of a parliamentary act, from the Normattiva ingest.

An act is a reading of a legislative process: (act)-[:PART_OF]->
(:LegislativeProcess)-[:BECAME_LAW]->(:Law), written by
build/ingest_laws.py. Every reading of the process (C.2822, S.1971,
C.2822-B) resolves to the same law; acts outside a concluded process
have none.
"""
from __future__ import annotations

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
