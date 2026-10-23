"""
Text of the Senate's bills from the Akoma Ntoso bulk data, for load_act_texts.py.

The Senate publishes every bill of the term as Akoma Ntoso in the git repository
SenatoDellaRepubblica/AkomaNtosoBulkData, one folder per bill phase
(Leg19/Atto00059859 is S. 1779, http://dati.senato.it/ddl/59859 in the graph):

  ddlpres   the text as presented (or as transmitted by the Chamber)
  ddlcomm   the text proposed by the committee (-A), side by side with the
            text it starts from
  ddlmess   the text approved by the Senate (the «messaggio» sent on)

build/update_data.sh (akn_pull) keeps a sparse checkout of these folders in
downloads/akn_senato. This module turns each file into the same two sections
as the Chamber's documents: «articolato» (articles with their heading and
paragraphs, the decree-law and the changes made to it for a conversion bill)
and, for the text as presented, «relazione» (the proposers' report).
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "{http://docs.oasis-open.org/legaldocml/ns/akn/3.0/CSD03}"

# Version label as Stenografo reads it: None for the text as presented, the
# Senate's own suffix for the committee text (S. 1779-A), «approvato» for the
# text the Senate approved, which has no suffix of its own.
VERSIONS = {"ddlpres": None, "ddlcomm": "A", "ddlmess": "approvato"}
TIPODOC = {"ddlpres": "DDLPRES", "ddlcomm": "DDLCOMM", "ddlmess": "DDLMESS"}
# The page senato.it links from the bill's card (tab «Testi ed emendamenti»),
# checked on 2026-10-23 for S. 1779: same id without the leading zeros, idoggetto=0.
DOC_URL = "https://www.senato.it/show-doc?leg={leg}&tipodoc={tipodoc}&id={id}&idoggetto=0"

README_NUMBER = re.compile(r"Atto Senato n\.\s*([\w-]+)")
README_ID = re.compile(r"Link OpenData:\s*http://dati\.senato\.it/ddl/(\d+)")
FILE_ID = re.compile(r"^(\d+)-ft\.akn\.xml$")

# A proposers' report that is only its salutation («Onorevoli Senatori. –»):
# the rest was published as images.
MIN_REPORT = 200

_LABEL = r"(?:\d+(?:\.\d+)*(?:-\w+)?[.)]|[a-z]{1,2}(?:-\w+)?\))"
IDENTICAL = re.compile(rf"^\s*(?:{_LABEL}\s*)?identic[oaei]»?\s*[.;:,]?\s*$", re.I)
SUPPRESSED = re.compile(rf"^\s*(?:{_LABEL}\s*)?soppress[oaei]»?\s*[.;:,]?\s*$", re.I)

BLOCKS = {"chapter", "section", "part", "title", "book", "subsection", "subchapter", "hcontainer", "article"}
NUMBERED = {"paragraph", "point", "subparagraph", "indent", "alinea", "clause", "list"}
INLINE = {"eol", "i", "b", "u", "span", "sup", "sub", "ref", "mref", "date", "a", "docNumber", "docTitle"}
SKIP_INLINE = {"del", "noteRef", "img", "componentRef", "authorialNote"}


def _tag(e: ET.Element) -> str:
    return e.tag.replace(NS, "")


# The files are pretty-printed: a line break and its indentation sit between an
# inline element and the text around it («23<i>-ter</i>», «Identico</i>:»). A
# break before punctuation or after an opening mark joins; any other is a space.
_JOIN_AFTER = set("(«[‘'-/")
_JOIN_BEFORE = set(",.;:)]’-")


def _squash(s: str) -> str:
    def rep(m: re.Match) -> str:
        if "\n" not in m.group():
            return " "
        before = s[m.start() - 1] if m.start() else ""
        after = s[m.end()] if m.end() < len(s) else ""
        return "" if before in _JOIN_AFTER or after in _JOIN_BEFORE else " "

    s = s.replace("\xa0", " ")
    return re.sub(r"\s+", rep, s).strip()


def _raw(e: ET.Element) -> str:
    parts = [e.text or ""]
    for c in e:
        t = _tag(c)
        if t == "eol":
            parts.append(" ")
        elif t not in SKIP_INLINE:
            parts.append(_raw(c))
        parts.append(c.tail or "")
    return "".join(parts)


def inline(e: ET.Element | None) -> str:
    return _squash(_raw(e)) if e is not None else ""


def _cells(tr: ET.Element) -> list[str]:
    return ["\n".join(_lines(td)) for td in tr.findall(NS + "td")]


def side_by_side(table: ET.Element) -> list[str]:
    """The right column of a two-column table (the committee's text, the text the
    Chamber approved), the left one where the right says «Identico», nothing where
    it says «Soppresso» or is empty."""
    out = []
    for tr in table.iter(NS + "tr"):
        cells = _cells(tr)
        if len(cells) == 1:
            out.append(cells[0])
            continue
        if len(cells) != 2:
            continue
        left, right = cells
        if IDENTICAL.match(right):
            out.append(left)
        elif right.strip() and not SUPPRESSED.match(right):
            lines, kept = right.split("\n"), left.split("\n")
            if len(lines) == len(kept):
                # A quoted article rewritten in one cell: «1-bis. Identico.» line by line.
                lines = [k if IDENTICAL.match(r.lstrip("«“ ")) else r for r, k in zip(lines, kept)]
            out.append("\n".join(lines))
    return [x for x in out if x.strip()]


def _table(table: ET.Element) -> list[str]:
    return [" | ".join(c.replace("\n", " ") for c in cells if c) for tr in table.iter(NS + "tr")
            if (cells := _cells(tr)) and any(cells)]


def _lines(e: ET.Element) -> list[str]:
    """Lines of a block: «Art. 6.», «(Linee guida …)», «1. Text of the paragraph.», «a) …»."""
    t = _tag(e)
    if t in SKIP_INLINE or t in ("meta", "num", "heading"):
        return []
    if t in BLOCKS:
        out = [x for x in (inline(e.find(NS + "num")), inline(e.find(NS + "heading"))) if x]
        for c in e:
            out += _lines(c)
        return out
    if t in NUMBERED:
        num = inline(e.find(NS + "num"))
        rest = [x for c in e for x in _lines(c)]
        if num:
            rest = [f"{num} {rest[0]}".strip()] + rest[1:] if rest else [num]
        return rest
    if t == "table":
        return _table(e)
    if not any(_tag(c) not in INLINE and _tag(c) not in SKIP_INLINE for c in e):
        text = inline(e)
        return [text] if text else []
    out = [_squash(e.text or "")]
    for c in e:
        out += _lines(c) + [_squash(c.tail or "")]
    return [x for x in out if x]


def articles(body: ET.Element | None) -> list[str]:
    if body is None:
        return []
    if not any(True for _ in body.iter(NS + "article")):
        tables = list(body.iter(NS + "table"))
        if tables and max((len(tr.findall(NS + "td")) for tr in tables[0].iter(NS + "tr")), default=0) == 2:
            return [x for tb in tables for x in side_by_side(tb)]
    return [x for c in body for x in _lines(c)]


def _doc_text(doc: ET.Element) -> str:
    main = doc.find(NS + "mainBody")
    return "\n".join(_lines(main)) if main is not None else ""


def _attr(e: ET.Element, path: str, name: str) -> str | None:
    found = e.find(path)
    return found.get(name) if found is not None else None


def parse_akn(raw: bytes | str) -> dict:
    """{'articolato', 'relazione', 'kind', 'number', 'title', 'date'} of one Senate bill text."""
    root = ET.fromstring(raw)
    bill = root.find(NS + "bill")
    if bill is None:
        bill = root[0]
    meta = {"number": _attr(bill, f".//{NS}FRBRWork/{NS}FRBRnumber", "value"),
            "date": _attr(bill, f".//{NS}FRBRWork/{NS}FRBRdate", "date")}
    cover = bill.find(NS + "coverPage")
    titles = [inline(t) for t in (cover.iter(NS + "docTitle") if cover is not None else []) if inline(t)]
    meta["title"] = titles[0] if titles else _attr(bill, NS + "body", "title")

    presented = _attr(bill, f".//{NS}FRBRWork/{NS}FRBRsubtype", "value") == "DDLPRES"
    lines = articles(bill.find(NS + "body"))
    report = ""
    attachments = bill.find(NS + "attachments")
    for att in attachments if attachments is not None else []:
        name = (att.get("name") or "").strip()
        if _tag(att) == "act":
            # The decree-law a conversion bill converts.
            head = [inline(t) for t in att.iter(NS + "docTitle") if inline(t)]
            body = articles(att.find(NS + "body"))
            if body:
                lines += (["DECRETO-LEGGE " + head[0]] if head else ["DECRETO-LEGGE"]) + body
        elif _tag(att) == "doc":
            text = _doc_text(att)
            if re.match(r"(?i)allegato\s+modificazioni apportate", " ".join(text.split()[:3])):
                # «Modificazioni apportate in sede di conversione / dalla Commissione».
                lines.append(text)
            elif (name in ("RelPres", "Relazione", "Relazione illustrativa") and presented and not report
                  and len(text) >= MIN_REPORT):
                # Only the proposers' report: a committee file's report is the rapporteur's.
                report = text
    text = "\n".join(x for x in lines if x.strip())
    # A committee file whose body only refers to the Chamber's printed text, or a
    # text published as images, has no articles.
    if not re.search(r"(?m)^(Art\.|Articolo)\s", text):
        text = text if len(text) >= MIN_REPORT else ""
    kind = "testo" if text else "relazione" if report else "altro"
    return {"articolato": text, "relazione": report, "kind": kind, **meta}


def readme(folder: Path) -> dict | None:
    """Bill number and dati.senato.it id from a folder's README.MD."""
    path = folder / "README.MD"
    if not path.exists():
        return None
    raw = path.read_text(encoding="utf-8", errors="replace")
    num, ident = README_NUMBER.search(raw), README_ID.search(raw)
    if not ident:
        return None
    return {"number": num.group(1) if num else None, "id_fase": ident.group(1)}


def versions_from_akn(akn_dir: Path, leg: int) -> list[dict]:
    """One entry per text file: ddlpres, ddlcomm, ddlmess of every bill of the term."""
    out = []
    for folder in sorted((akn_dir / f"Leg{leg}").glob("Atto*")):
        info = readme(folder)
        if not info:
            continue
        for kind, label in VERSIONS.items():
            for f in sorted((folder / kind).glob("*-ft.akn.xml")):
                m = FILE_ID.match(f.name)
                if not m:
                    continue
                doc = m.group(1)
                out.append({
                    "act": f"http://dati.senato.it/ddl/{info['id_fase']}",
                    "id": f"senato:{leg}:ddl:{info['id_fase']}:{kind}:{doc}",
                    "code": f"{kind}/{doc}",
                    "number": info["number"],
                    "label": label,
                    "tipodoc": kind,
                    "path": f,
                    "url": DOC_URL.format(leg=leg, tipodoc=TIPODOC[kind], id=int(doc)),
                })
    return out


def version_label(version: dict, parsed: dict) -> str | None:
    """The committee text's suffix from its own number: 1779-A, 17-B-A for S. 17-B."""
    label = version["label"]
    if version["tipodoc"] == "ddlcomm" and parsed.get("number") and version.get("number"):
        n = parsed["number"].replace("N. ", "").strip()
        if m := re.search(r"-([A-Z](?:/R)?)$", n):
            # A unified text keeps the numbers of all its bills: 797-584-A for S. 797 and S. 584.
            label = m.group(1)
        elif n.startswith(version["number"] + "-"):
            label = n[len(version["number"]) + 1:] or label
    return label
