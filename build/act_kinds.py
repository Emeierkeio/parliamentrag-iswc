"""
act_kinds.py — family label and `kind` of a parliamentary act (decision D1, 15/10/2026).

Every ParliamentaryAct keeps that label and gets one family label next to it
(Bill, Motion, Resolution, AgendaOrder, OversightAct, ParliamentaryDocument)
plus a closed-vocabulary `kind`. The source wording stays in `type_raw`.
Writers and validate_db import this module, so the mapping lives in one place.

Vocabulary: docs/plans/PLAN_atti_schema.md §3 D1. Two kinds are added to the
table there for Government bills that are neither decree conversions nor the
budget: ddl_ordinario and ddl_costituzionale.
"""

from __future__ import annotations

import re
from typing import Optional

FAMILIES = ("Bill", "Motion", "Resolution", "AgendaOrder", "OversightAct", "ParliamentaryDocument")

KINDS = {
    "Bill": {"pdl_ordinaria", "pdl_costituzionale", "ddl_ordinario", "ddl_costituzionale",
             "ddl_conversione_dl", "ddl_bilancio"},
    "Motion": {"mozione", "mozione_sfiducia"},
    "Resolution": {"risoluzione_assemblea", "risoluzione_commissione", "risoluzione_conclusiva"},
    "AgendaOrder": {"odg_assemblea", "odg_commissione", "odg_bilancio"},
    "OversightAct": {"interrogazione_scritta", "interrogazione_orale", "interrogazione_commissione",
                     "question_time", "interpellanza", "interpellanza_urgente"},
    "ParliamentaryDocument": {"doc"},
}

# dc:type of the Chamber's ocd:aic and the Senate's AIC file (same wording).
_AIC = {
    "INTERROGAZIONE A RISPOSTA SCRITTA": ("OversightAct", "interrogazione_scritta"),
    "INTERROGAZIONE A RISPOSTA ORALE": ("OversightAct", "interrogazione_orale"),
    "INTERROGAZIONE A RISPOSTA IN COMMISSIONE": ("OversightAct", "interrogazione_commissione"),
    "INTERROGAZIONE A RISPOSTA IMMEDIATA IN ASSEMBLEA": ("OversightAct", "question_time"),
    "INTERROGAZIONE A RISPOSTA IMMEDIATA IN COMMISSIONE": ("OversightAct", "question_time"),
    "INTERPELLANZA": ("OversightAct", "interpellanza"),
    "INTERPELLANZA URGENTE": ("OversightAct", "interpellanza_urgente"),
    "MOZIONE": ("Motion", "mozione"),
    "MOZIONE DI SFIDUCIA": ("Motion", "mozione_sfiducia"),
    "RISOLUZIONE IN ASSEMBLEA": ("Resolution", "risoluzione_assemblea"),
    "RISOLUZIONE IN COMMISSIONE": ("Resolution", "risoluzione_commissione"),
    "RISOLUZIONE CONCLUSIVA": ("Resolution", "risoluzione_conclusiva"),
    "RISOLUZIONE IN COMMISSIONE CONCLUSIVA DI DIBATTITO": ("Resolution", "risoluzione_conclusiva"),
    "ODG - ORDINE DEL GIORNO IN ASSEMBLEA": ("AgendaOrder", "odg_assemblea"),
    "ODG - ORDINE DEL GIORNO IN COMMISSIONE": ("AgendaOrder", "odg_commissione"),
    "ODG IN ASSEMBLEA SU P.D.L.": ("AgendaOrder", "odg_assemblea"),
    "ODG IN ASSEMBLEA SU MOZIONI O ALTRI ATTI": ("AgendaOrder", "odg_assemblea"),
    "ODG IN COMMISSIONE": ("AgendaOrder", "odg_commissione"),
}

_DL_RE = re.compile(r"conversione in legge,?\s+(con modificazioni,\s+)?del decreto-legge", re.I)
_BUDGET_RE = re.compile(r"bilancio di previsione dello stato", re.I)


def aic_kind(type_raw: Optional[str]) -> Optional[tuple[str, str]]:
    """(family, kind) of an oversight act, motion, resolution or agenda order."""
    t = (type_raw or "").strip().upper()
    if t in _AIC:
        return _AIC[t]
    if t.startswith("ODG") and "BILANCIO" in t:
        return ("AgendaOrder", "odg_bilancio")
    return None


def bill_kind(nature: Optional[str], title: Optional[str]) -> tuple[str, str]:
    """(family, kind) of a Chamber bill from ocd:rif_natura (last path segment) and its title."""
    n = (nature or "").rsplit("/", 1)[-1]
    if n.startswith("disegno_legge"):
        if _DL_RE.search(title or ""):
            return ("Bill", "ddl_conversione_dl")
        if _BUDGET_RE.search(title or ""):
            return ("Bill", "ddl_bilancio")
        return ("Bill", "ddl_costituzionale" if n.endswith("costituzionale") else "ddl_ordinario")
    return ("Bill", "pdl_costituzionale" if n.endswith("costituzionale") else "pdl_ordinaria")


# osr:natura of Senate bills; "ordinaria" and "costituzionale" split on who
# presented the bill, like ocd:rif_natura on the Chamber.
_SENATE_NATURE = {
    "di conversione di decreto-legge": "ddl_conversione_dl",
    "di approvazione di bilancio": "ddl_bilancio",
}


def senate_bill_kind(nature: Optional[str], initiative: Optional[str]) -> tuple[str, str]:
    """(family, kind) of a Senate bill from osr:natura and its initiative."""
    n = (nature or "").strip().lower()
    if n in _SENATE_NATURE:
        return ("Bill", _SENATE_NATURE[n])
    constitutional = n == "costituzionale"
    if initiative == "governo":
        return ("Bill", "ddl_costituzionale" if constitutional else "ddl_ordinario")
    return ("Bill", "pdl_costituzionale" if constitutional else "pdl_ordinaria")


# First digit of a Chamber oversight act number (aic<d>_..._19): the Chamber's
# numbering of act types. Checked on 31,063 described acts (18/10/2026): each
# digit maps to one kind.
_AIC_DIGIT = {
    "0": ("AgendaOrder", "odg_commissione"), "1": ("Motion", "mozione"),
    "2": ("OversightAct", "interpellanza"), "3": ("OversightAct", "interrogazione_orale"),
    "4": ("OversightAct", "interrogazione_scritta"), "5": ("OversightAct", "interrogazione_commissione"),
    "6": ("Resolution", "risoluzione_assemblea"), "7": ("Resolution", "risoluzione_commissione"),
    "8": ("Resolution", "risoluzione_conclusiva"), "9": ("AgendaOrder", "odg_assemblea"),
}
_AIC_URI_RE = re.compile(r"/aic\.rdf/aic(\d)_")


def act_kind(uri: str, type_raw: Optional[str], nature: Optional[str] = None,
             initiative: Optional[str] = None) -> Optional[tuple[str, str]]:
    """(family, kind) of any act node, for nodes whose writer does not set
    them: Senate bills, document placeholders and Chamber agenda orders known
    only by the URI a vote cites."""
    t = (type_raw or "").strip()
    if t == "Disegno di legge":
        return senate_bill_kind(nature, initiative)
    if t == "pdl":  # placeholder of a Chamber bill, nature unknown until resolved
        return ("Bill", "pdl_ordinaria")
    if t == "doc" or uri.startswith("placeholder:doc:"):
        return ("ParliamentaryDocument", "doc")
    fk = aic_kind(t)
    if fk:
        return fk
    m = _AIC_URI_RE.search(uri)
    if m and not t:
        return _AIC_DIGIT[m.group(1)]
    return None


def valid(family: Optional[str], kind: Optional[str]) -> bool:
    return family in KINDS and kind in KINDS[family]


# ocd:iniziativa of Chamber bills -> initiative (decision D3).
_CAMERA_INITIATIVE = {
    "Parlamentare": "parlamentare", "Governo": "governo", "Regioni": "regionale",
    "CNEL": "cnel", "Popolare": "popolare",
}


def camera_initiative(raw: Optional[str]) -> Optional[str]:
    raw = (raw or "").strip()
    if raw.startswith("Mista"):
        return "mista"
    return _CAMERA_INITIATIVE.get(raw)


_TITLE_INITIATIVE = (
    ("popolare", re.compile(r"iniziativa popolare", re.I)),
    ("regionale", re.compile(r"consiglio regionale|assemblea regionale|iniziativa (del|della|dell.)\s*(consiglio|assemblea) regional", re.I)),
    ("cnel", re.compile(r"\bCNEL\b|consiglio nazionale dell.economia", re.I)),
    ("parlamentare", re.compile(r"\bed altri\b|\bsenatori\b|\bdeputat[oi]\b", re.I)),
)


def initiative_from_title(title: Optional[str]) -> Optional[str]:
    """Initiative named in a bill title, for the few bills without ocd:iniziativa
    (AC 2149, a Senate text unifying senators' and a regional bill)."""
    found = {kind for kind, rx in _TITLE_INITIATIVE if rx.search(title or "")}
    if not found:
        return None
    return found.pop() if len(found) == 1 else "mista"
