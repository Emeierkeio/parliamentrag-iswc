"""
doc_refs.py — references to parliamentary documents ("Doc.") in free text.

Both chambers number their non-legislative documents by series (a Roman
numeral, sometimes with a Latin suffix: IV-ter, XVIII-bis) and number within
the legislature. The references come in many spellings:

  "Doc. IV-ter, n. 13-A"                    the committee report on IV-ter 13
  "Doc. XXII, nn. 11-14-16-19-20-21-22-A"   seven documents, one joint report
  "(DOC. XVIII-BIS, n. 10)", "Doc. LVII, n. 1.bis", "Doc. CCXXXII n. 1"
  "Doc.XXII,n.9-28-29-A", "Doc.LVII,n.1-Annesso-bis"   (dc:identifier on dati.camera.it)
  "Docc. LVII, n. 01-bis e LVII, 01-bis-Integrazione"
  "Relatrice sui documenti LXXXVI, n. 1, e LXXXVII, n. 1"
  "(Doc. XXII, nn. 9, 5, 6 e 11)", "Doc. XXIV, n 16"

Every sheet of a document (text, annexes, errata, the committee report "-A")
belongs to the document; "1-bis" is another document, "01-bis" too.
"""

from __future__ import annotations

import re
from typing import NamedTuple, Optional

LATIN = "bis|ter|quater|quinquies|sexies|septies|octies|novies|decies"

# Roman numerals are matched case-sensitively, so that "e di" never reads as
# the series DI; the Latin suffix and the prefixes in any case.
_SERIES = r"(?P<series>[IVXLCDM]+(?:-(?i:" + LATIN + r"))?)"
_TOKEN = r"\d+(?:\s*[-.]\s*(?i:" + LATIN + r")\b)?"
_NUMS = r"(?P<nums>" + _TOKEN + r"(?:\s*(?:-|,|\be\b|\bed\b)\s*(?:[nN]{1,2}\.\s*)?" + _TOKEN + r")*)"
_REPORT = r"(?:\s*-\s*(?P<report>A(?:/[IVXR]+)?)(?![a-zA-Z]))?"
_REF_RE = re.compile(_SERIES + r"\s*,?\s*(?:[nN]{1,2}\.?\s*)?" + _NUMS + _REPORT)
_PREFIX_RE = re.compile(r"(?i:\bdocc?\s*\.|\bdocument[oi]\b|\bdoc\b)\s*")
# Between two references of one list: "LXXXVI, n. 1, e LXXXVII, n. 1".
_CONTINUE_RE = re.compile(r"\s*,?\s*(?:\b(?:e|ed)\b\s*)?(?:(?i:del\s+)?(?i:docc?\.)\s*)?(?=[IVXLCDM]+(?:-|\s*,|\s+[nN]))")
_TOKEN_RE = re.compile(_TOKEN)


class DocRef(NamedTuple):
    series: str   # "IV-ter"
    number: str   # "13", "1-bis", "01-bis"
    report: Optional[str] = None   # "A", "A/I": the committee report


def norm_series(series: str) -> str:
    """"XVIII-BIS" -> "XVIII-bis"."""
    head, _, tail = series.partition("-")
    return head.upper() + (f"-{tail.lower()}" if tail else "")


def norm_number(token: str) -> str:
    """"1.bis", "1 - BIS" -> "1-bis"; leading zeros stay ("01-bis" is not "1-bis")."""
    m = re.match(r"(\d+)\s*(?:[-.]\s*([a-zA-Z]+))?$", token.strip())
    if not m:
        return token.strip()
    return m.group(1) + (f"-{m.group(2).lower()}" if m.group(2) else "")


def parse_doc_refs(text: Optional[str]) -> list[DocRef]:
    """Every document a text names, in order, without repeats."""
    out: list[DocRef] = []
    text = text or ""
    for prefix in _PREFIX_RE.finditer(text):
        pos = prefix.end()
        while True:
            m = _REF_RE.match(text, pos)
            if not m:
                break
            series = norm_series(m.group("series"))
            for tok in _TOKEN_RE.findall(m.group("nums")):
                ref = DocRef(series, norm_number(tok), m.group("report"))
                if ref not in out:
                    out.append(ref)
            pos = m.end()
            c = _CONTINUE_RE.match(text, pos)
            if not c or c.end() == pos:
                break
            pos = c.end()
    return out


def doc_keys(text: Optional[str]) -> list[tuple[str, str]]:
    """(series, number) of the documents a text names, reports folded into their document."""
    return list(dict.fromkeys((r.series, r.number) for r in parse_doc_refs(text)))


def doc_uri(chamber: str, legislature: int, series: str, number: str) -> str:
    """Synthetic key of a document node: "camera:19:doc:IV-ter:13" (decision D9 style)."""
    return f"{chamber}:{legislature}:doc:{series}:{number}"


def doc_name(series: str, number: str) -> str:
    """"Doc. IV-ter, n. 13", the way both chambers cite it."""
    return f"Doc. {series}, n. {number}"
