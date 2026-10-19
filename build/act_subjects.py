#!/usr/bin/env python3
"""
Readable subject for motions and resolutions, from official text only.

  (act {subject, subject_source})   act: kind 'mozione' or 'risoluzione_assemblea',
                                     target of a vote or discussed in a debate

The act's own title is a code ("MOZIONE 1/00039") and its description the
whole text. The subject comes, in this order, from:

  debate   the title of a debate that DISCUSSES the act, without the
           procedure and the act numbers: "Discussione delle mozioni Aiello
           ed altri n. 1-00052, ... concernenti iniziative a favore
           dell'adeguatezza dei trattamenti previdenziali" gives "Iniziative a
           favore dell'adeguatezza dei trattamenti previdenziali". Motions of
           a joint debate share its subject. Titles that name the act come
           before the Government's communications, and the opening debate
           before a "Ripresa della discussione ...".
  vote     the Senate's vote label ("Mozione n. 67 sulle criticità nei
           collegamenti aerei con Catania e la Sicilia"), abbreviated by
           the source;
  fallback "Mozione 1-00039, Boccia e altri": number and first signatory.

No text is generated: every subject is a substring of an official title or
label, apart from the fallback and the "Sfiducia" of a no-confidence motion
(article 115, comma 3, of the Chamber's Rules). No network; idempotent:
only changed values are written.

    python build/act_subjects.py --neo4j-uri bolt://... [--dry-run] [--show N]
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
from collections import Counter
from typing import Optional

logger = logging.getLogger("act_subjects")

KINDS = ["mozione", "risoluzione_assemblea"]
KIND_LABEL = {"mozione": "Mozione", "risoluzione_assemblea": "Risoluzione"}

CLOCK_RE = re.compile(r"\s*\(ore \d{1,2}(?:[,.]\d{2})?\)\.?", re.IGNORECASE)
DOC_CODE_RE = re.compile(r"\s*\(\s*Doc(?:s?\.|umento)[^)]*\)", re.IGNORECASE)
PROCEDURE_PAREN_RE = re.compile(r"\s*\([^)]*(?:Regolamento|procedimento abbreviato|procedura abbreviata)"
                                r"[^)]*\)", re.IGNORECASE)
CONSEQUENT_RE = re.compile(r",?\s+e conseguente discussione\b", re.IGNORECASE)
# "..., ai sensi dell'articolo 86 del regio decreto ... n. 12": procedure.
# When the decree's title follows ("... n. 185, recante «Disposizioni
# urgenti ...»"), that title is the subject and only the reference goes.
UNDER_ARTICLE_RE = re.compile(r",?\s+ai sensi dell[a-z']*\s.*$", re.IGNORECASE)
UNDER_ARTICLE_TITLED_RE = re.compile(r",?\s+ai sensi dell[a-z']*\s.*?,?\s+recante:?\s*(?=«)",
                                     re.IGNORECASE)

# The debate is about an agenda item, not "Per un richiamo al Regolamento"
# or "Sulla votazione della mozione n. 1-00392 effettuata nella seduta
# precedente".
AGENDA_RE = re.compile(r"^(?:(?:si riprende(?: il seguito)?|ripresa|(?:rinvio del )?seguito) della discussione"
                       r"|discussione|esame|comunicazioni|informativa|relazione)\b", re.IGNORECASE)
CONTINUATION_RE = re.compile(r"^(?:si riprende|ripresa)\b", re.IGNORECASE)
PROCEDURAL_PREFIX_RE = re.compile(
    r"^(?:(?:si riprende(?: il seguito)?|ripresa|(?:rinvio del )?seguito) della discussione|discussione|esame)"
    r"(?: congiunta)?(?: e (?:approvazione|reiezione))?(?:,? con modificazioni,?)?"
    r"(?:,? in prima deliberazione,?)?(?: dalla sede redigente)?"
    r"(?:\s+(?:sulle|sulla|sullo|sul|sugli|sui|del|della|dello|dei|delle|degli|dell')\b|\s*$)\s*",
    re.IGNORECASE)
# Senate documents: "documento: (Doc. LVII, n. 2) - DEF 2024".
SENATE_DOC_RE = re.compile(r"^(?:documento|documenti)\s*:?\s*(?:\([^)]*\))?\s*-\s*", re.IGNORECASE)

# Act numbers in a title. Chamber: "Aiello ed altri n. 1-00052, ... e Mari ed
# altri n. 1-00153"; Senate: "della mozione n. 47", "delle mozioni nn. 50
# (testo 2), 52 (testo 2) e 53", "della mozione di sfiducia individuale n. 62".
CAMERA_NUMBER_RE = re.compile(r"\b(?:nn?\.\s*)?[16]-\d{5}\b")
SENATE_NUMBERS_RE = re.compile(
    r"\b(?:mozion[ei]|risoluzion[ei])\b(?P<nc>\s+di\s+sfiducia(?:\s+individuale)?)?\s+nn?\.\s*"
    r"\d+(?:\s*\(testo\s+\d+\))?(?:\s*(?:,|\be\b)\s*\d+(?:\s*\(testo\s+\d+\))?)*", re.IGNORECASE)
CAMERA_NO_CONFIDENCE_RE = re.compile(
    r"^,?\s*presentata,?\s+a norma dell'articolo 115, comma 3, del Regolamento,?\s*", re.IGNORECASE)
CONNECTIVE_RE = re.compile(
    r"^(?:concernent[ei]\s+|in materia di\s+|in ordine all'|in ordine (?:a|al|allo|alla|ai|agli|alle)\s+"
    r"|sull'|(?:sul|sullo|sulla|sui|sugli|sulle|su)\s+)", re.IGNORECASE)

# Senate vote labels: "Mozione n. 45, Speranzon e altri, sul riconoscimento ...",
# "Comunicazioni Ministro difesa. Proposta di risoluzione n. 2, Paita e altri".
LABEL_TOPIC_RE = re.compile(r"(?:^|[\s,)])(?:sull'|(?:sul|sullo|sulla|sui|sugli|sulle|su)\s+)(.+)$",
                            re.IGNORECASE)
LABEL_TAIL_RE = re.compile(r"\.\s*(?:ODG|Votazione|Em{1,2}\.|Punto|Prem)\b.*$", re.IGNORECASE)
LABEL_RESOLUTION_RE = re.compile(r"[.,]?\s*prop(?:osta)?\.?\s*(?:di)?\s*ris", re.IGNORECASE)


def _tidy(text: str) -> str:
    text = " ".join((text or "").split())
    return text.strip(" .,;:-")


def _capital(text: str) -> Optional[str]:
    text = _tidy(text)
    return text[0].upper() + text[1:] if text else None


def _clean(title: str) -> str:
    title = CLOCK_RE.sub("", title or "")
    title = PROCEDURE_PAREN_RE.sub("", title)
    title = CONSEQUENT_RE.sub("", title)
    return _tidy(title)


def topic_from_title(title: str) -> tuple[Optional[str], bool]:
    """(subject, names_the_act) from a debate title; subject None when the
    title is only procedure ("Si riprende la discussione.")."""
    title = _clean(title)
    if not AGENDA_RE.match(title):
        return None, False
    last = None
    for m in list(CAMERA_NUMBER_RE.finditer(title)) + list(SENATE_NUMBERS_RE.finditer(title)):
        if last is None or m.end() > last.end():
            last = m
    if last is not None:
        rest, prefix = title[last.end():], ""
        if CAMERA_NO_CONFIDENCE_RE.match(rest):
            rest, prefix = CAMERA_NO_CONFIDENCE_RE.sub("", rest), "sfiducia "
        elif last.groupdict().get("nc"):
            prefix = _tidy(last.group("nc")).removeprefix("di ") + " "
        rest = CONNECTIVE_RE.sub("", _tidy(rest)) if not prefix else _tidy(rest)
        rest = DOC_CODE_RE.sub("", rest)
        return (_capital(prefix + rest) if _tidy(rest) else None), True
    rest = PROCEDURAL_PREFIX_RE.sub("", title, count=1)
    rest = SENATE_DOC_RE.sub("", rest)
    rest = DOC_CODE_RE.sub("", rest)
    rest = UNDER_ARTICLE_TITLED_RE.sub(": ", rest, count=1)
    rest = UNDER_ARTICLE_RE.sub("", rest)
    return _capital(rest), False


def topic_from_label(label: str, kind: str) -> Optional[str]:
    """Subject in a Senate vote label, abbreviated as the source writes it."""
    label = " ".join((label or "").split())
    if kind == "risoluzione_assemblea":
        head = LABEL_RESOLUTION_RE.split(label, maxsplit=1)
        # "Docc.LXXXVI, n.1 e LXXXVII, n.1. Proposta di risoluzione n.2": a code, not a subject
        if len(head) < 2 or not _tidy(head[0]) or re.match(r"Docc?\.", head[0]):
            return None
        return _capital(DOC_CODE_RE.sub("", head[0]))
    label = LABEL_TAIL_RE.sub("", label)
    m = LABEL_TOPIC_RE.search(label)
    if not m:
        return None
    topic = re.sub(r"\s*\((?:\d|1-\d{5})[^)]*\)\s*,?\s*[^,]*\b(?:e|ed) altri\s*$", "", m.group(1))
    return _capital(topic)


def _surname(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    return name.title() if name.isupper() else name


def fallback_subject(kind: str, number: str, surname: Optional[str], cosigners: int) -> str:
    """'Mozione 1-00039, Boccia e altri'."""
    text = f"{KIND_LABEL.get(kind, 'Atto')} {number.replace('/', '-')}"
    if surname:
        text += f", {_surname(surname)}" + (" e altri" if cosigners else "")
    return text


def choose_subject(act: dict) -> tuple[str, str]:
    """(subject, source) for one act.

    act: kind, number, surname, cosigners, debates [{title, date, order}],
    labels [vote labels].
    """
    ranked = []
    for d in sorted(act.get("debates") or [], key=lambda d: (str(d.get("date") or ""), d.get("order") or 0)):
        topic, named = topic_from_title(d.get("title") or "")
        if topic:
            continuation = bool(CONTINUATION_RE.match(_clean(d.get("title") or "")))
            ranked.append(((not named, continuation), topic))
    if ranked:
        return min(ranked, key=lambda r: r[0])[1], "debate"
    for label in act.get("labels") or []:
        topic = topic_from_label(label, act["kind"])
        if topic:
            return topic, "vote"
    return fallback_subject(act["kind"], act["number"], act.get("surname"), act.get("cosigners") or 0), "fallback"


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--dry-run", action="store_true", help="read the graph, write nothing")
    ap.add_argument("--show", type=int, default=0, help="print N computed subjects")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    stats = Counter()
    mode = "READ" if args.dry_run else "WRITE"
    with driver.session(default_access_mode=mode) as s:
        acts = [r.data() for r in s.run("""
            MATCH (a:ParliamentaryAct)
            WHERE a.kind IN $kinds
              AND (EXISTS { (:Vote)-[:ON_ACT]->(a) } OR EXISTS { (:Debate)-[:DISCUSSES]->(a) })
            OPTIONAL MATCH (p:Person)-[:PRIMARY_SIGNATORY]->(a)
            WITH a, head(collect(p.last_name)) AS surname
            OPTIONAL MATCH (sess:Session)-[:HAS_DEBATE]->(d:Debate)-[:DISCUSSES]->(a)
            WITH a, surname, collect(DISTINCT {title: d.title, date: toString(sess.date), order: d.order}) AS debates
            OPTIONAL MATCH (v:Vote)-[:ON_ACT]->(a)
            WITH a, surname, debates, v ORDER BY v.id
            RETURN a.uri AS uri, a.kind AS kind, a.number AS number, a.chamber AS chamber,
                   a.subject AS current, surname, debates,
                   [x IN collect(v.subject) WHERE x IS NOT NULL] AS labels,
                   COUNT { (:Person)-[:CO_SIGNATORY]->(a) } AS cosigners
        """, kinds=KINDS)]
        rows = []
        for act in acts:
            act["debates"] = [d for d in act["debates"] if d.get("title")]
            subject, source = choose_subject(act)
            stats[f"{act['chamber']}_{source}"] += 1
            if subject != act["current"]:
                rows.append({"uri": act["uri"], "subject": subject, "source": source})
            if args.show and len(rows) <= args.show and subject != act["current"]:
                print(f"{act['chamber']:6} {act['number']:8} [{source}] {subject}")
        stats["acts"] = len(acts)
        stats["changed"] = len(rows)
        if not args.dry_run and rows:
            stats["written"] = s.run("""
                UNWIND $rows AS row
                MATCH (a:ParliamentaryAct {uri: row.uri})
                SET a.subject = row.subject, a.subject_source = row.source
                RETURN count(a) AS n
            """, rows=rows).single()["n"]
    driver.close()
    for k, v in sorted(stats.items()):
        logger.info("%s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
