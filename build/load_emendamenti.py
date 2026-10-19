#!/usr/bin/env python3
"""
Amendments of one legislature into the graph (no text) and the text archive.

Input: downloads/emendamenti/emendamenti_leg19.jsonl (parse_emendamenti.py).

Graph:
  (:Amendment {id, chamber, legislature, act, number, version, kind, venue,
               committee, article, outcome, outcome_raw, presented_on,
               sitting_date, group_id, source_url, member_signatories, row_hash,
               outcome_source: "source" | "floor_vote"})
  (Amendment)-[:AMENDS {joint}]->(ParliamentaryAct)
  (Person)-[:SIGNED_AMENDMENT {first}]->(Amendment)
  (Vote)-[:ON_AMENDMENT {method}]->(Amendment)        floor votes only
  (Amendment)-[:SUB_OF]->(Amendment)                  sub-amendment -> parent
  (Amendment)-[:RESUBMITS]->(Amendment)               re-submission -> first of its group

Archive (Postgres, same database as build/pg_archive.py):
  amendment        one row per amendment, with text and filter columns
  amendment_chunk  chunks keyed by testo_hash, with the embedding: a text
                   submitted again in another venue is embedded once

  python build/load_emendamenti.py --neo4j-uri bolt://localhost:7692 \
      --archive-url postgresql://postgres:...@localhost:5433/archivio

Idempotent and incremental: a node or row is written only when the hash of
its source row changed; relations are diffed against what the graph holds
(created when missing, deleted when no longer derived), so a person or vote
loaded after the amendment gets linked at the next run. Embeddings are
computed only for chunks that have none, committed batch by batch, so an
interrupted run resumes where it stopped. Without --neo4j-uri the graph is
skipped, without --archive-url the archive is skipped.

Moving the archive tables to another Postgres without paying the embeddings
again: dump the two tables and restore them, then run this script there; the
row hashes match and only what changed since the dump is written.

  pg_dump -Fc -t amendment -t amendment_chunk archivio > emendamenti.dump
  PGOPTIONS='-c maintenance_work_mem=256MB -c max_parallel_maintenance_workers=0' \\
      pg_restore --no-owner -d archivio emendamenti.dump
"""

from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = REPO_ROOT / "downloads" / "emendamenti" / "emendamenti_leg{leg}.jsonl"

CAMERA_PERSON = "http://dati.camera.it/ocd/persona.rdf/p"
SENATO_PERSON = "http://dati.senato.it/senatore/"
CAMERA_ACT = "http://dati.camera.it/ocd/attocamera.rdf/ac{leg}_"

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIM = 1536
# USD per million input tokens, OpenAI price list for text-embedding-3-small (2026-10).
EMBEDDING_PRICE_PER_M = 0.02
CHUNK_SIZE = 1200
CHUNK_OVERLAP = 250

# Stale amendments are deleted only when the input still holds at least this
# share of what is loaded: a truncated JSONL must not empty the graph.
MIN_INPUT_SHARE = 0.9
# Part of every row hash: bump it when the derived fields change (outcome
# rules, dates) so that the next run rewrites all nodes and rows.
DERIVATION_VERSION = 1


# ----------------------------------------------------------------- outcomes

# Ordered: the first matching prefix wins. Partial outcomes ("respinta la
# parte evidenziata; preclusa la restante parte") take the first verb.
OUTCOME_RULES = [
    (("id. ", "id.em", "sost. id.", "sost.id.", "sost id.", "sot. id."), "identical"),
    (("v. ", "v.", "vedi "), "superseded"),
    (("ritirat", "trasformat"), "withdrawn"),
    (("approvat",), "approved"),
    (("accolto come raccomandazione", "accolto con raccomandazione",
      "accoto come raccomandazione"), "accepted_as_recommendation"),
    (("accolt", "accoto"), "accepted"),
    (("non accolt",), "not_accepted"),
    (("respint", "le parole da"), "rejected"),
    (("preclus",), "precluded"),
    (("inammissibil", "dichiarato inammissibil", "dichiarata inammissibil",
      "irricevibil"), "inadmissible"),
    (("improponibil", "dichiarato improponibil", "dichiarata improponibil"), "improponibile"),
    (("improcedibil",), "improcedibile"),
    (("decadut",), "lapsed"),
    (("assorbit",), "absorbed"),
    (("non posto in votazione",), "not_voted"),
    (("in parte ", "parte ", "votato per parti separate"), "mixed"),
]
REST_RE = re.compile(r"(\w+) per la parte restante")


def normalize_outcome(raw: str | None) -> str | None:
    """Map a source outcome ("Respinto", "V. testo 2", ...) to a closed vocabulary."""
    if not raw or not raw.strip():
        return None
    s = re.sub(r"\s+", " ", raw.strip().lower())
    # "dichiarato inammissibile limitatamente al comma 2, respinto per la parte
    # restante": the amendment was voted, the rest outcome is what happened.
    m = REST_RE.search(s)
    if m and s.startswith(("dichiarat", "inammissibil", "improponibil")):
        rest = normalize_outcome(m.group(1))
        if rest:
            return rest
    for prefixes, value in OUTCOME_RULES:
        if s.startswith(prefixes):
            return value
    return "other"


# ------------------------------------------------------------ source fields

def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    try:
        if len(value) == 8 and value.isdigit():
            return dt.date(int(value[:4]), int(value[4:6]), int(value[6:]))
        return dt.date.fromisoformat(value[:10])
    except ValueError:
        return None


def normalize_version(version: str | None) -> str | None:
    """'Testo 2', 'testo2' -> 'testo 2'."""
    if not version:
        return None
    v = re.sub(r"\s+", " ", version.strip().lower())
    return re.sub(r"^testo\s*(\d)", r"testo \1", v)


def number_key(numero: str) -> str:
    """Comparable amendment number: lower case, no '(già em. ...)' note, single spaces."""
    n = re.sub(r"\s*\(gi[aà][^)]*\)", "", numero or "")
    return re.sub(r"\s+", " ", n.strip().lower())


def signer_person_key(signer: dict) -> str | None:
    """Graph identifier of a signatory: Person.senato_id for 'S:<id>', the persona URI for 'C:<id>'."""
    sid = signer.get("id") or ""
    if sid.startswith("S:") and sid[2:].isdigit():
        return SENATO_PERSON + sid[2:]
    if sid.startswith("C:") and sid[2:].isdigit():
        return CAMERA_PERSON + sid[2:]
    return None


def name_key(name: str | None) -> str:
    """'Schiano Di Visconti' and 'SCHIANO DI VISCONTI' -> 'schiano di visconti'."""
    return re.sub(r"\s+", " ", (name or "").strip().lower())


def act_number(atto: str | None) -> str | None:
    """'S.1896' -> '1896', 'S.1038-B' -> '1038-B'."""
    if not atto or "." not in atto:
        return None
    return atto.split(".", 1)[1]


def row_hash(row: dict) -> str:
    payload = json.dumps([DERIVATION_VERSION, row], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(payload.encode()).hexdigest()[:16]


def sub_parent(chamber: str, kind: str, numero: str) -> tuple[str, str | None] | None:
    """Number (and version) of the amendment a sub-amendment refers to.

    Senate: '7.0.100/10' -> ('7.0.100', None), '1.1 (testo 2)/3' and '1.1 testo 2/3'
    -> ('1.1', 'testo 2').
    Chamber: '0.15.800.10' -> ('15.800', None); only rows of kind subEmendamento.
    """
    key = number_key(numero)
    if chamber == "senato":
        # "4.1/5ª Commissione" is the opinion of a committee, not a sub-amendment
        m = re.match(r"^(\d.*?)\s*/\s*\d+$", key)
        if not m:
            return None
        # "7.9 (testo 3) e identici/12" sub-amends 7.9 (testo 3) and the
        # amendments identical to it: linked to 7.9 (testo 3).
        parent = re.sub(r"\s*e identici$", "", m.group(1))
        # "1.1 (testo 2)/3" and, in 5 Senate rows of 2026-10, "13.0.400 testo 2/1"
        m = re.match(r"^(.*?)\s*(?:\((testo[^)]*)\)|(testo\s*\d+))$", parent)
        if m:
            return m.group(1).strip(), normalize_version(m.group(2) or m.group(3))
        return parent, None
    if kind != "subEmendamento":
        return None
    m = re.match(r"^0\.(.+)\.\d+$", key)
    return (m.group(1), None) if m else None


# --------------------------------------------------------------- vote labels

ITEM_C_RE = re.compile(r"(?<![\w.])\d+(?:-[a-z]+)?(?:\.\d+)+\b", re.I)
ITEM_S_RE = re.compile(r"(?<![\w.])(G?\d+(?:-[a-z]+)?(?:\.(?:\d+|TAB))+(?:/\d+)?)(?:\s*\((testo[^)]*)\))?",
                       re.I)
C_SUBJECT_RE = re.compile(r"^Votazione Emendamento (.+?),?\s+(?:DDL|PDL) n\.\s*0*(\d+)", re.I)
C_DESC_RE = re.compile(
    r"^(?:(?:DDL|PDL) 0*(\d+)\S* - )?"
    r"(?:EM|ART\.? AGG|ART\.? PREM|SUBEM|Emendament[oi]|Subemendament[oi]|Articol[oi] aggiuntiv[oi]"
    r"|Articol[oi] premissiv[oi]|Identici)\b", re.I)
S_SUBJECT_RE = re.compile(r"^(?:DDL n\.\s*(\S+?)\.\s+)?(?:Em|Emm|ODG|Odg)\.?\s+(.*)$")


def parse_vote_refs(chamber: str, subject: str | None,
                    description: str | None) -> tuple[str | None, list[tuple[str, str | None]]]:
    """Bill number and amendment numbers named by a floor vote's label.

    Chamber: subject "Votazione Emendamento 9.1 DDL n. 0005" (identical
    amendments are listed only in the description), or generic subject
    "Votazione" with description "EM 19.7", "ART AGG 23.04", "DDL 2128 - EM 1.2".
    Senate: subject "Em. 3.215, Zampa e altri", "Emm. 1.91 e 1.92",
    "Em. 2.100 (testo 2), Silvestro", "ODG G1.10, ...", "DDL n. 924-bis. Em. 1.236".
    Returns (bill number or None, [(number key, version)]); no numbers means
    the vote is not on an amendment.
    """
    subject = (subject or "").strip()
    description = (description or "").strip()
    if chamber == "camera":
        m = C_SUBJECT_RE.match(subject)
        if m:
            source = description if description.lower().startswith("identici") else m.group(1)
            items = ITEM_C_RE.findall(source) or ITEM_C_RE.findall(m.group(1))
            return m.group(2), [(i.lower(), None) for i in dict.fromkeys(items)]
        if subject.lower() in ("", "votazione"):
            m = C_DESC_RE.match(description)
            if m:
                items = ITEM_C_RE.findall(description)
                return m.group(1), [(i.lower(), None) for i in dict.fromkeys(items)]
        return None, []
    m = S_SUBJECT_RE.match(subject)
    if not m:
        return None, []
    refs = []
    for number, version in ITEM_S_RE.findall(m.group(2)):
        ref = (number_key(number), normalize_version(version) if version else None)
        if ref not in refs:
            refs.append(ref)
    return m.group(1), refs


# The Senate dates floor amendments by the published file, which can follow
# the vote by a few days (sitting 13, 30/11/2022: votes on S.299 amendments
# dated 1/12/2022). Observed on the 2026-10 data, not a documented rule.
DATE_SLACK = dt.timedelta(days=7)
# A Chamber floor file carries the date of the sitting that votes it: on the
# 2026-10 data 7,371 of 7,391 Chamber matches fall within 5 days; the other 20
# were second readings ("DDL n. 1038-B", 24 days later) whose file is missing
# and matched the first reading.
CAMERA_FILE_WINDOW = dt.timedelta(days=7)


def pick_candidate(cands: list[dict], when: dt.date | None) -> tuple[dict | None, str]:
    """The amendment that rows with the same bill and number designate on date `when`.

    One candidate is taken as is. Among several (the Chamber republishes a
    floor file per sitting, the Senate restarts numbering on a new base text)
    the latest dated up to `when` wins; rows of two bills, or a tie, are
    ambiguous. Returns (row, reason): reason is 'ok', 'missing', 'ambiguous'
    or 'future'.
    """
    if not cands:
        return None, "missing"
    if len(cands) == 1:
        return cands[0], "ok"
    if len({c.get("atto") for c in cands}) > 1 or when is None:
        return None, "ambiguous"
    dated = [c for c in cands if c["_date"] is not None and c["_date"] <= when + DATE_SLACK]
    if not dated:
        return None, "future"
    best = max(c["_date"] for c in dated)
    top = [c for c in dated if c["_date"] == best]
    return (top[0], "ok") if len(top) == 1 else (None, "ambiguous")


# ----------------------------------------------------------------- chunking

def _pieces(text: str, size: int) -> list[str]:
    out = []
    for line in text.split("\n"):
        line = line.strip()
        if not line:
            continue
        if len(line) <= size:
            out.append(line)
            continue
        for sentence in re.split(r"(?<=[.;:])\s+", line):
            while len(sentence) > size:
                cut = sentence.rfind(" ", 0, size)
                cut = cut if cut > size // 2 else size
                out.append(sentence[:cut].strip())
                sentence = sentence[cut:].strip()
            if sentence:
                out.append(sentence)
    return out


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split an amendment into chunks of at most ~size characters.

    Amendment texts are line-structured ("a) al comma 1, ..."), so lines are
    the unit, sentences and then words for longer lines; consecutive chunks
    share up to `overlap` characters of whole pieces, like the speech chunks.
    """
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]
    pieces = _pieces(text, size)
    chunks: list[str] = []
    start = 0
    while start < len(pieces):
        end, length = start, 0
        while end < len(pieces) and (end == start or length + len(pieces[end]) + 1 <= size):
            length += len(pieces[end]) + 1
            end += 1
        chunks.append("\n".join(pieces[start:end]))
        if end >= len(pieces):
            break
        back, tail = end, 0
        while back - 1 > start and tail + len(pieces[back - 1]) <= overlap:
            back -= 1
            tail += len(pieces[back])
        start = back
    return chunks


# -------------------------------------------------------------------- input

def read_rows(path: Path, limit: int | None) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            if limit is not None and len(rows) >= limit:
                break
            row = json.loads(line)
            row["_hash"] = row_hash(row)
            row["_chamber"] = "camera" if row["ramo"] == "C" else "senato"
            row["_number_key"] = number_key(row["numero"])
            row["_version"] = normalize_version(row.get("versione"))
            # Chamber rows are dated by the sitting of their file, Senate rows
            # by presentation.
            row["_date"] = parse_date(row.get("seduta_data")) or parse_date(row.get("data_presentazione"))
            rows.append(row)
    return rows


def node_hash(row: dict, vote_outcome: str | None) -> str:
    """Hash of the node: the source row, plus the outcome read from floor votes when there is one."""
    if not vote_outcome:
        return row["_hash"]
    return hashlib.sha1(f"{row['_hash']}|{vote_outcome}".encode()).hexdigest()[:16]


def node_props(row: dict, leg: int, vote_outcome: str | None = None) -> dict:
    """Node properties; the source outcome wins, the floor-vote outcome fills its absence."""
    members = sum(1 for f in row.get("firmatari") or [] if f.get("tipo") in ("deputato", "senatore"))
    outcome = normalize_outcome(row.get("esito"))
    source = "source" if outcome else None
    if outcome is None and vote_outcome:
        outcome, source = vote_outcome, "floor_vote"
    props = {
        "id": row["id"],
        "chamber": row["_chamber"],
        "legislature": leg,
        "act": row.get("atto"),
        "number": row.get("numero"),
        "version": row.get("versione"),
        "kind": row.get("tipo"),
        "venue": row.get("sede"),
        "committee": row.get("commissione"),
        "article": row.get("articolo"),
        "outcome": outcome,
        "outcome_source": source,
        "outcome_raw": row.get("esito"),
        "presented_on": parse_date(row.get("data_presentazione")),
        "sitting_date": parse_date(row.get("seduta_data")),
        "group_id": row.get("gruppo_id"),
        "source_url": row.get("fonte"),
        "member_signatories": members,
        "row_hash": node_hash(row, vote_outcome),
    }
    return {k: v for k, v in props.items() if v is not None and v != ""}


# -------------------------------------------------------------------- graph

GRAPH_SCHEMA = [
    "CREATE CONSTRAINT amendment_id IF NOT EXISTS FOR (a:Amendment) REQUIRE a.id IS UNIQUE",
    "CREATE INDEX amendment_act IF NOT EXISTS FOR (a:Amendment) ON (a.chamber, a.act)",
    "CREATE INDEX amendment_group IF NOT EXISTS FOR (a:Amendment) ON (a.group_id)",
]

WRITE_NODES = """
UNWIND $rows AS row
MERGE (a:Amendment {id: row.id})
SET a = row
"""

REL_QUERIES = {
    # (read existing, create, delete); each row of a relation is a tuple of keys
    "AMENDS": (
        "MATCH (a:Amendment {legislature: $leg})-[r:AMENDS]->(x:ParliamentaryAct) "
        "RETURN a.id AS a, x.uri AS b, coalesce(r.joint, false) AS p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a}) MATCH (x:ParliamentaryAct {uri: r.b}) "
        "MERGE (a)-[e:AMENDS]->(x) SET e.joint = r.p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a})-[e:AMENDS]->(x:ParliamentaryAct {uri: r.b}) DELETE e",
    ),
    "SIGNED_AMENDMENT": (
        "MATCH (p:Person)-[r:SIGNED_AMENDMENT]->(a:Amendment {legislature: $leg}) "
        "RETURN a.id AS a, p.id AS b, r.first AS p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a}) MATCH (p:Person {id: r.b}) "
        "MERGE (p)-[e:SIGNED_AMENDMENT]->(a) SET e.first = r.p",
        "UNWIND $rows AS r MATCH (p:Person {id: r.b})-[e:SIGNED_AMENDMENT]->(a:Amendment {id: r.a}) DELETE e",
    ),
    "ON_AMENDMENT": (
        "MATCH (v:Vote)-[r:ON_AMENDMENT]->(a:Amendment {legislature: $leg}) "
        "RETURN a.id AS a, v.id AS b, r.method AS p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a}) MATCH (v:Vote {id: r.b}) "
        "MERGE (v)-[e:ON_AMENDMENT]->(a) SET e.method = r.p",
        "UNWIND $rows AS r MATCH (v:Vote {id: r.b})-[e:ON_AMENDMENT]->(a:Amendment {id: r.a}) DELETE e",
    ),
    "SUB_OF": (
        "MATCH (a:Amendment {legislature: $leg})-[:SUB_OF]->(b:Amendment) RETURN a.id AS a, b.id AS b, null AS p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a}) MATCH (b:Amendment {id: r.b}) MERGE (a)-[:SUB_OF]->(b)",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a})-[e:SUB_OF]->(b:Amendment {id: r.b}) DELETE e",
    ),
    "RESUBMITS": (
        "MATCH (a:Amendment {legislature: $leg})-[:RESUBMITS]->(b:Amendment) RETURN a.id AS a, b.id AS b, null AS p",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a}) MATCH (b:Amendment {id: r.b}) MERGE (a)-[:RESUBMITS]->(b)",
        "UNWIND $rows AS r MATCH (a:Amendment {id: r.a})-[e:RESUBMITS]->(b:Amendment {id: r.b}) DELETE e",
    ),
}

VOTES = """
MATCH (s:Session {legislature: $leg})-[:HAS_VOTE]->(v:Vote)
WHERE s.chamber IN ['camera', 'senato']
OPTIONAL MATCH (v)-[:ON_ACT]->(x:ParliamentaryAct)
RETURN v.id AS id, s.id AS session, s.chamber AS chamber, s.date AS date, v.subject AS subject,
       v.description AS description, v.outcome AS outcome, collect(x.uri) AS acts
"""

SESSION_BILLS = """
MATCH (s:Session {legislature: $leg})-[:HAS_DEBATE]->(:Debate)-[:DISCUSSES]->(x:ParliamentaryAct)
WHERE s.chamber IN ['camera', 'senato']
  AND (x.uri STARTS WITH 'http://dati.camera.it/ocd/attocamera.rdf/' OR x.uri STARTS WITH 'http://dati.senato.it/ddl/')
RETURN s.id AS session, collect(DISTINCT x.uri) AS acts
"""


class GraphIndex:
    """Persons, bills and votes of the graph, read once."""

    def __init__(self, session, leg: int):
        self.leg = leg
        self.person_by_key: dict[str, str | None] = {}
        self.deputy_by_name: dict[str, str | None] = {}
        for r in session.run("MATCH (p:Person) RETURN p.id AS id, p.camera_id AS cam, p.senato_id AS sen, "
                             "p.first_name AS first, p.last_name AS last, p.mandates AS mandates"):
            if r["cam"] and f"camera_{leg}" in (r["mandates"] or []) and r["last"]:
                for name in {f"{r['first'] or ''} {r['last']}", r["last"]}:
                    k = name_key(name)
                    self.deputy_by_name[k] = r["id"] if self.deputy_by_name.get(k, r["id"]) == r["id"] else None
            keys = {r["sen"], r["cam"]}
            if r["id"].startswith(CAMERA_PERSON) or r["id"].startswith(SENATO_PERSON):
                keys.add(r["id"])
            for k in keys - {None}:
                # Two persons with one source id (an unmerged duplicate) stay unlinked.
                if k in self.person_by_key and self.person_by_key[k] != r["id"]:
                    self.person_by_key[k] = None
                else:
                    self.person_by_key[k] = r["id"]
        self.camera_acts: set[str] = set()
        self.senate_act_by_number: dict[str, str] = {}
        self.senate_number_by_uri: dict[str, str] = {}
        for r in session.run(
            "MATCH (x:ParliamentaryAct) WHERE x.uri STARTS WITH $cam OR "
            "(x.uri STARTS WITH 'http://dati.senato.it/ddl/' AND x.legislature = $leg) "
            "RETURN x.uri AS uri, x.number AS number",
            cam=CAMERA_ACT.format(leg=leg), leg=leg,
        ):
            if r["uri"].startswith("http://dati.camera.it/"):
                self.camera_acts.add(r["uri"])
            elif r["number"]:
                self.senate_act_by_number[str(r["number"])] = r["uri"]
                self.senate_number_by_uri[r["uri"]] = str(r["number"])
        self.votes = session.run(VOTES, leg=leg).data()
        self.session_acts = {r["session"]: r["acts"] for r in session.run(SESSION_BILLS, leg=leg)}

    def bill_numbers(self, chamber: str, uris: list[str]) -> list[str]:
        """Bill numbers ('1660', '1038-B' for the Senate) of the given act URIs."""
        out = []
        prefix = CAMERA_ACT.format(leg=self.leg)
        for u in uris:
            if chamber == "camera":
                if u.startswith(prefix):
                    out.append(u[len(prefix):].split("-")[0])
            elif u in self.senate_number_by_uri:
                out.append(self.senate_number_by_uri[u])
        return list(dict.fromkeys(out))

    def act_uri(self, chamber: str, atto: str | None) -> str | None:
        number = act_number(atto)
        if not number:
            return None
        if chamber == "camera":
            uri = CAMERA_ACT.format(leg=self.leg) + number
            return uri if uri in self.camera_acts else None
        return self.senate_act_by_number.get(number)


def derive_relations(rows: list[dict], gi: GraphIndex, stats: Counter, unlinked: dict) -> dict[str, set]:
    """Every relation the source supports, as {type: {(amendment id, other key, property)}}."""
    rels: dict[str, set] = {k: set() for k in REL_QUERIES}
    by_id = {r["id"]: r for r in rows}

    for r in rows:
        ch = r["_chamber"]
        uri = gi.act_uri(ch, r.get("atto"))
        if uri:
            rels["AMENDS"].add((r["id"], uri, False))
            stats[f"{ch}.act_linked"] += 1
        else:
            stats[f"{ch}.act_missing"] += 1
            unlinked.setdefault(f"{ch}.act", []).append((r["id"], r.get("atto"), "atto assente nel grafo"))
        for joint in r.get("atti_congiunti") or []:
            juri = gi.act_uri(ch, joint)
            if juri and juri != uri:
                rels["AMENDS"].add((r["id"], juri, True))

        seen = set()
        for f in r.get("firmatari") or []:
            if f.get("tipo") not in ("deputato", "senatore"):
                stats[f"{ch}.sign_not_member"] += 1
                continue
            stats[f"{ch}.sign_total"] += 1
            key = signer_person_key(f)
            if key is None:
                # The Chamber writes idProponente="XXX" for some deputies (83
                # signatures of 8 names, 2026-10): matched by full name or
                # surname when exactly one deputy of the legislature has it.
                pid = gi.deputy_by_name.get(name_key(f.get("nome"))) if ch == "camera" else None
                if pid is None:
                    stats[f"{ch}.sign_bad_id"] += 1
                    unlinked.setdefault(f"{ch}.sign", []).append(
                        (r["id"], f.get("nome"), f"id non valido {f.get('id')!r}"))
                    continue
                stats[f"{ch}.sign_by_name"] += 1
            else:
                pid = gi.person_by_key.get(key)
                if pid is None:
                    reason = "persona ambigua" if key in gi.person_by_key else "persona assente nel grafo"
                    stats[f"{ch}.sign_missing"] += 1
                    unlinked.setdefault(f"{ch}.sign", []).append((r["id"], f.get("nome"), f"{reason} ({key})"))
                    continue
            if pid in seen:
                continue
            seen.add(pid)
            rels["SIGNED_AMENDMENT"].add((r["id"], pid, bool(f.get("primo"))))
            stats[f"{ch}.sign_linked"] += 1

        gid = r.get("gruppo_id")
        if gid and gid != r["id"] and gid in by_id:
            rels["RESUBMITS"].add((r["id"], gid, None))

    # sub-amendment -> parent in the same bill and venue
    index: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        index[(r["_chamber"], r.get("atto"), r.get("sede"), r["_number_key"], r["_version"])].append(r)
    for r in rows:
        parent = sub_parent(r["_chamber"], r.get("tipo"), r.get("numero") or "")
        if not parent:
            continue
        stats[f"{r['_chamber']}.sub_total"] += 1
        key = (r["_chamber"], r.get("atto"))
        # same venue and version, then same venue in any version, then the
        # other venue (a committee amendment that the floor sub-amends)
        cands = (index.get(key + (r.get("sede"), parent[0], parent[1]))
                 or [c for v in ("testo corretto", "testo 2") for c in index.get(key + (r.get("sede"), parent[0], v), [])]
                 or [c for venue in ("commissione", "assemblea") if venue != r.get("sede")
                     for c in index.get(key + (venue, parent[0], parent[1]), [])])
        same = [c for c in cands if c.get("seduta_data") == r.get("seduta_data")] or cands
        target, _ = pick_candidate(same, r["_date"])
        if target and target["id"] != r["id"]:
            rels["SUB_OF"].add((r["id"], target["id"], None))
            stats[f"{r['_chamber']}.sub_linked"] += 1

    link_votes(rows, gi, rels, stats, unlinked)
    return rels


def link_votes(rows: list[dict], gi: GraphIndex, rels: dict, stats: Counter, unlinked: dict) -> None:
    """Floor votes -> amendments, by bill and number; ambiguous matches are left out."""
    floor: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("sede") != "assemblea":
            continue
        for atto in [r.get("atto")] + list(r.get("atti_congiunti") or []):
            floor[(r["_chamber"], act_number(atto), r["_number_key"], r["_version"])].append(r)

    for v in gi.votes:
        ch = v["chamber"]
        bill, refs = parse_vote_refs(ch, v["subject"], v["description"])
        if not refs:
            continue
        when = v["date"].to_native() if v["date"] is not None else None
        # The bill comes from the first source that names one: the vote
        # label, the vote's ON_ACT, and for the Chamber the bills debated in
        # the same sitting (its generic labels "Votazione | EM 19.7" have no
        # ON_ACT). On the Senate the sitting fallback matched the signatory
        # named in the label 10 times out of 19 (2026-10), so it is not used.
        method, bills = "label", [bill] if bill else []
        if not bills:
            method, bills = "act", gi.bill_numbers(ch, v["acts"])
        if not bills and ch == "camera":
            method, bills = "session", gi.bill_numbers(ch, gi.session_acts.get(v["session"], []))
        stats[f"{ch}.vote_total"] += 1
        linked = 0
        reasons = []
        for number, version in refs:
            cands = [c for b in bills for c in floor.get((ch, b, number, version), [])]
            if ch == "camera" and when:
                inside = [c for c in cands if c["_date"] is None
                          or -DATE_SLACK <= when - c["_date"] <= CAMERA_FILE_WINDOW]
                if cands and not inside:
                    reasons.append(f"{number}: fascicolo fuori finestra")
                    continue
                cands = inside
            target, reason = pick_candidate(list({c["id"]: c for c in cands}.values()), when)
            if target:
                rels["ON_AMENDMENT"].add((target["id"], v["id"], method))
                stats[f"{ch}.vote_method_{method}"] += 1
                linked += 1
            else:
                reasons.append(f"{number}{' ' + version if version else ''}: "
                               f"{'nessun atto' if not bills and reason == 'missing' else reason}")
        if linked:
            stats[f"{ch}.vote_linked"] += 1
        else:
            unlinked.setdefault(f"{ch}.vote", []).append(
                (v["id"], v["subject"] if ch == "senato" else f"{v['subject']} | {v['description']}",
                 "; ".join(reasons)))


def vote_outcomes(rels: dict, gi: GraphIndex) -> dict[str, str]:
    """Outcome of each amendment voted on the floor: 'approved', 'rejected', or 'mixed' over several votes.

    The Chamber's open data gives an outcome to 682 of 33,332 floor amendments
    and never 'rejected' (2026-10), so the roll-call result is the only source
    for most of them; amendments not voted by roll call stay without outcome.
    """
    by_vote = {v["id"]: v.get("outcome") for v in gi.votes}
    seen: dict[str, set] = defaultdict(set)
    for amendment, vote, _ in rels["ON_AMENDMENT"]:
        if by_vote.get(vote) in ("approved", "rejected"):
            seen[amendment].add(by_vote[vote])
    return {a: next(iter(o)) if len(o) == 1 else "mixed" for a, o in seen.items()}


def apply_relations(driver, leg: int, rels: dict[str, set], batch: int, dry_run: bool,
                    only_ids: set[str] | None, stats: Counter) -> None:
    """Create missing relations and delete those no longer derived.

    With --limit (only_ids) deletions are restricted to the loaded amendments.
    """
    for rtype, (read_q, create_q, delete_q) in REL_QUERIES.items():
        with driver.session() as s:
            existing = {(r["a"], r["b"], r["p"]) for r in s.run(read_q, leg=leg)}
        want = rels[rtype]
        to_create = want - existing
        to_delete = {e for e in existing - want if only_ids is None or e[0] in only_ids}
        stats[f"rel.{rtype}.total"] = len(want)
        stats[f"rel.{rtype}.created"] = len(to_create)
        stats[f"rel.{rtype}.deleted"] = len(to_delete)
        logger.info("%s: %d derived, %d to create, %d to delete", rtype, len(want), len(to_create),
                    len(to_delete))
        if dry_run:
            continue
        for query, items in ((delete_q, to_delete), (create_q, to_create)):
            items = [{"a": a, "b": b, "p": p} for a, b, p in items]
            for i in range(0, len(items), batch):
                with driver.session() as s:
                    s.execute_write(lambda tx, c=items[i:i + batch]: tx.run(query, rows=c).consume())


def load_graph(rows: list[dict], args, stats: Counter, unlinked: dict) -> None:
    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    leg = args.leg
    with driver.session() as s:
        if not args.dry_run:
            for q in GRAPH_SCHEMA:
                s.run(q).consume()
        existing = {r["id"]: r["h"] for r in s.run(
            "MATCH (a:Amendment {legislature: $leg}) RETURN a.id AS id, a.row_hash AS h", leg=leg)}
        gi = GraphIndex(s, leg)
    logger.info("graph: %d amendments loaded, %d persons, %d Chamber and %d Senate bills, %d votes",
                len(existing), len(gi.person_by_key), len(gi.camera_acts), len(gi.senate_act_by_number),
                len(gi.votes))

    rels = derive_relations(rows, gi, stats, unlinked)
    voted = vote_outcomes(rels, gi)
    for r in rows:
        if r["id"] in voted:
            stats[f"{r['_chamber']}.outcome_from_vote" if not normalize_outcome(r.get("esito"))
                  else f"{r['_chamber']}.outcome_source_and_vote"] += 1
    changed = [r for r in rows if existing.get(r["id"]) != node_hash(r, voted.get(r["id"]))]
    stale: list[str] = []
    if args.limit is None:
        ids = {r["id"] for r in rows}
        stale = [i for i in existing if i not in ids]
        if stale and len(rows) < MIN_INPUT_SHARE * len(existing):
            logger.warning("input has %d rows for %d loaded amendments: %d stale nodes kept",
                           len(rows), len(existing), len(stale))
            stale = []
    stats["node.created"] = sum(1 for r in changed if r["id"] not in existing)
    stats["node.updated"] = len(changed) - stats["node.created"]
    stats["node.deleted"] = len(stale)
    logger.info("amendments: %d new, %d changed, %d stale", stats["node.created"], stats["node.updated"],
                len(stale))
    if not args.dry_run:
        props = [node_props(r, leg, voted.get(r["id"])) for r in changed]
        for i in range(0, len(props), args.batch):
            with driver.session() as s:
                s.execute_write(lambda tx, c=props[i:i + args.batch]: tx.run(WRITE_NODES, rows=c).consume())
        for i in range(0, len(stale), args.batch):
            with driver.session() as s:
                s.execute_write(lambda tx, c=stale[i:i + args.batch]: tx.run(
                    "UNWIND $ids AS i MATCH (a:Amendment {id: i}) DETACH DELETE a", ids=c).consume())

    only_ids = {r["id"] for r in rows} if args.limit is not None else None
    apply_relations(driver, leg, rels, args.batch, args.dry_run, only_ids, stats)
    driver.close()


# ------------------------------------------------------------------ archive

ARCHIVE_SCHEMA = f"""
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS amendment (
    id             text PRIMARY KEY,
    chamber        text NOT NULL,          -- 'camera' | 'senato'
    term           integer NOT NULL,
    act            text,                   -- 'C.1660', 'S.1896'
    joint_acts     text[],
    id_ddl         text,                   -- osr:idDdl, the bill across both chambers
    venue          text,                   -- 'commissione' | 'assemblea'
    committee      text,
    number         text,
    version        text,
    kind           text,
    article        text,
    outcome        text,
    outcome_raw    text,
    presented_on   date,
    sitting_date   date,
    group_id       text,
    text           text,
    text_presented text,
    text_hash      text,
    source_url     text,
    row_hash       text NOT NULL
);

CREATE INDEX IF NOT EXISTS amendment_scope ON amendment (chamber, term, act);
CREATE INDEX IF NOT EXISTS amendment_text_hash ON amendment (text_hash);

CREATE TABLE IF NOT EXISTS amendment_chunk (
    text_hash   text NOT NULL,
    chunk_index integer NOT NULL,
    text        text NOT NULL,
    embedding   halfvec({EMBEDDING_DIM}),  -- NULL until computed
    PRIMARY KEY (text_hash, chunk_index)
);
"""

ARCHIVE_HNSW = """
CREATE INDEX IF NOT EXISTS amendment_chunk_embedding_hnsw
    ON amendment_chunk USING hnsw (embedding halfvec_cosine_ops)
    WITH (m = 16, ef_construction = 64);
"""

AMENDMENT_COLUMNS = ("id", "chamber", "term", "act", "joint_acts", "id_ddl", "venue", "committee",
                     "number", "version", "kind", "article", "outcome", "outcome_raw", "presented_on",
                     "sitting_date", "group_id", "text", "text_presented", "text_hash", "source_url",
                     "row_hash")


def archive_row(row: dict, leg: int) -> tuple:
    return (row["id"], row["_chamber"], leg, row.get("atto"), row.get("atti_congiunti") or None,
            row.get("id_ddl"), row.get("sede"), row.get("commissione"), row.get("numero"),
            row.get("versione"), row.get("tipo"), row.get("articolo"), normalize_outcome(row.get("esito")),
            row.get("esito"), parse_date(row.get("data_presentazione")), parse_date(row.get("seduta_data")),
            row.get("gruppo_id"), row.get("testo"), row.get("testo_presentato"), row.get("testo_hash"),
            row.get("fonte"), row["_hash"])


def _vector_text(values) -> str:
    return "[" + ",".join(f"{v:.6g}" for v in values) + "]"


class Embedder:
    """Batched, threaded calls to the OpenAI embeddings API, one client per key."""

    def __init__(self, keys: list[str], workers: int):
        from openai import OpenAI

        self.clients = [OpenAI(api_key=k, max_retries=0, timeout=120) for k in keys]
        self.workers = workers
        self.tokens = 0
        self._lock = threading.Lock()
        self._n = 0

    def _client(self):
        with self._lock:
            self._n += 1
            return self.clients[self._n % len(self.clients)]

    def _call(self, texts: list[str]) -> list[list[float]]:
        delay = 2.0
        for attempt in range(8):
            try:
                resp = self._client().embeddings.create(model=EMBEDDING_MODEL, input=texts)
                with self._lock:
                    self.tokens += resp.usage.total_tokens
                return [d.embedding for d in resp.data]
            except Exception as e:  # noqa: BLE001 - the SDK raises several transient types
                status = getattr(e, "status_code", None)
                if status is not None and status < 500 and status != 429:
                    raise
                if attempt == 7:
                    raise
                logger.warning("embeddings API error (%s), retry in %.0fs", status or type(e).__name__, delay)
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise RuntimeError("unreachable")

    def embed(self, batches: list[list[str]]) -> list[list[list[float]]]:
        with concurrent.futures.ThreadPoolExecutor(self.workers) as pool:
            return list(pool.map(self._call, batches))


def load_archive(rows: list[dict], args, stats: Counter) -> None:
    import psycopg

    leg = args.leg
    with psycopg.connect(args.archive_url) as conn:
        if not args.dry_run:
            conn.execute(ARCHIVE_SCHEMA)
            conn.commit()
            existing = dict(conn.execute("SELECT id, row_hash FROM amendment WHERE term = %s", [leg]).fetchall())
        else:
            has_table = conn.execute("SELECT to_regclass('amendment') IS NOT NULL").fetchone()[0]
            existing = dict(conn.execute("SELECT id, row_hash FROM amendment WHERE term = %s",
                                         [leg]).fetchall()) if has_table else {}
        changed = [r for r in rows if existing.get(r["id"]) != r["_hash"]]
        stale: list[str] = []
        if args.limit is None:
            ids = {r["id"] for r in rows}
            stale = [i for i in existing if i not in ids]
            if stale and len(rows) < MIN_INPUT_SHARE * len(existing):
                logger.warning("archive: input smaller than loaded rows, %d stale rows kept", len(stale))
                stale = []
        stats["archive.rows_written"] = len(changed)
        stats["archive.rows_deleted"] = len(stale)
        logger.info("archive: %d rows to write, %d stale", len(changed), len(stale))
        if args.dry_run:
            texts = {r["testo_hash"]: r["testo"] for r in rows if r.get("testo")}
            n_chunks = sum(len(chunk_text(t)) for t in texts.values())
            chars = sum(len(c) for t in texts.values() for c in chunk_text(t))
            logger.info("archive (dry run): %d distinct texts, %d chunks, ~%.1fM characters to embed",
                        len(texts), n_chunks, chars / 1e6)
            return

        with conn.cursor() as cur:
            for i in range(0, len(changed), args.batch):
                cur.execute("CREATE TEMP TABLE IF NOT EXISTS amendment_in (LIKE amendment) ON COMMIT DELETE ROWS")
                with cur.copy(f"COPY amendment_in ({', '.join(AMENDMENT_COLUMNS)}) FROM STDIN") as copy:
                    for r in changed[i:i + args.batch]:
                        copy.write_row(archive_row(r, leg))
                updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in AMENDMENT_COLUMNS if c != "id")
                cur.execute(f"INSERT INTO amendment SELECT * FROM amendment_in "
                            f"ON CONFLICT (id) DO UPDATE SET {updates}")
                conn.commit()
            if stale:
                cur.execute("DELETE FROM amendment WHERE id = ANY(%s)", [stale])
            # Chunks follow the texts: new hashes get their chunks, hashes no
            # longer referenced lose them.
            cur.execute("""
                SELECT DISTINCT ON (a.text_hash) a.text_hash, a.text FROM amendment a
                WHERE a.text_hash IS NOT NULL AND coalesce(a.text, '') <> ''
                  AND NOT EXISTS (SELECT 1 FROM amendment_chunk c WHERE c.text_hash = a.text_hash)
            """)
            missing = cur.fetchall()
            with cur.copy("COPY amendment_chunk (text_hash, chunk_index, text) FROM STDIN") as copy:
                for h, text in missing:
                    for k, chunk in enumerate(chunk_text(text)):
                        copy.write_row((h, k, chunk))
            cur.execute("""
                DELETE FROM amendment_chunk c
                WHERE NOT EXISTS (SELECT 1 FROM amendment a WHERE a.text_hash = c.text_hash)
            """)
            stats["archive.chunk_hashes_added"] = len(missing)
            stats["archive.chunks_deleted"] = cur.rowcount
        conn.commit()

        if not args.skip_embeddings:
            embed_missing(conn, args, stats)
        if not args.skip_index:
            t = time.time()
            # Parallel workers share the build memory through /dev/shm, which
            # Docker caps at 64 MB: "could not resize shared memory segment"
            # (2026-10-14, local archive). One process uses ordinary memory.
            conn.execute("SET max_parallel_maintenance_workers = 0")
            conn.execute(f"SET maintenance_work_mem = '{args.index_mem}'")
            conn.execute(ARCHIVE_HNSW)
            conn.commit()
            logger.info("HNSW index ready (%.0fs)", time.time() - t)


def embed_missing(conn, args, stats: Counter) -> None:
    keys = [k.strip() for k in (os.environ.get("OPENAI_API_KEY") or "").split(",") if k.strip()]
    todo = conn.execute("SELECT text_hash, chunk_index, text FROM amendment_chunk WHERE embedding IS NULL "
                        "ORDER BY text_hash, chunk_index").fetchall()
    stats["embed.chunks_todo"] = len(todo)
    if not todo:
        return
    if not keys:
        logger.warning("OPENAI_API_KEY missing: %d chunks left without embedding", len(todo))
        return
    embedder = Embedder(keys, args.embed_workers)
    start = time.time()
    # A request carries at most 2048 inputs and 300k tokens; 200 chunks of
    # <= ~1.3k characters stay far below both.
    per_request = 200
    per_commit = per_request * args.embed_workers * 4
    done = 0
    for i in range(0, len(todo), per_commit):
        block = todo[i:i + per_commit]
        batches = [block[j:j + per_request] for j in range(0, len(block), per_request)]
        vectors = embedder.embed([[t for _, _, t in b] for b in batches])
        with conn.cursor() as cur:
            cur.execute("CREATE TEMP TABLE IF NOT EXISTS emb_in "
                        f"(text_hash text, chunk_index integer, embedding halfvec({EMBEDDING_DIM})) "
                        "ON COMMIT DELETE ROWS")
            with cur.copy("COPY emb_in FROM STDIN") as copy:
                for b, vs in zip(batches, vectors):
                    for (h, k, _), vec in zip(b, vs):
                        copy.write_row((h, k, _vector_text(vec)))
            cur.execute("UPDATE amendment_chunk c SET embedding = e.embedding FROM emb_in e "
                        "WHERE c.text_hash = e.text_hash AND c.chunk_index = e.chunk_index")
        conn.commit()
        done += len(block)
        elapsed = time.time() - start
        logger.info("embeddings %d/%d, %.2fM tokens, %.0fs (ETA %.0fs)", done, len(todo),
                    embedder.tokens / 1e6, elapsed, elapsed / done * (len(todo) - done))
    stats["embed.chunks_done"] = done
    stats["embed.tokens"] = embedder.tokens
    stats["embed.seconds"] = int(time.time() - start)
    logger.info("embeddings: %d chunks, %d tokens, USD %.4f, %.0fs", done, embedder.tokens,
                embedder.tokens / 1e6 * EMBEDDING_PRICE_PER_M, time.time() - start)


# --------------------------------------------------------------------- main

def report(stats: Counter, unlinked: dict, examples: int) -> None:
    for ch in ("camera", "senato"):
        def pct(a, b):
            return f"{stats[a]}/{stats[b]} ({100 * stats[a] / stats[b]:.1f}%)" if stats[b] else "0/0"
        acts = stats[f"{ch}.act_linked"] + stats[f"{ch}.act_missing"]
        stats[f"{ch}.act_total"] = acts
        logger.info("%s: act %s, signatures %s (%d by name), floor votes on amendments %s, sub-amendments %s, "
                    "outcome from floor votes %d",
                    ch, pct(f"{ch}.act_linked", f"{ch}.act_total"), pct(f"{ch}.sign_linked", f"{ch}.sign_total"),
                    stats[f"{ch}.sign_by_name"], pct(f"{ch}.vote_linked", f"{ch}.vote_total"),
                    pct(f"{ch}.sub_linked", f"{ch}.sub_total"), stats[f"{ch}.outcome_from_vote"])
    for key, items in sorted(unlinked.items()):
        reasons = Counter(re.sub(r"\(.*\)|'.*'|\d[\d.\-/a-z]*", "…", i[2]) for i in items)
        logger.info("unlinked %s: %d, reasons %s", key, len(items), reasons.most_common(4))
        for item in items[:examples]:
            logger.info("    %s | %s | %s", *item)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--leg", type=int, default=19)
    ap.add_argument("--input", type=Path)
    ap.add_argument("--neo4j-uri", help="graph to load; omitted, the graph is skipped")
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"))
    ap.add_argument("--archive-url", help="Postgres archive; omitted, the archive is skipped")
    ap.add_argument("--dry-run", action="store_true", help="compute and report, write nothing")
    ap.add_argument("--limit", type=int, help="only the first N rows (no deletions outside them)")
    ap.add_argument("--batch", type=int, default=5000)
    ap.add_argument("--skip-embeddings", action="store_true")
    ap.add_argument("--skip-index", action="store_true", help="do not build the HNSW index")
    ap.add_argument("--embed-workers", type=int, default=4)
    ap.add_argument("--index-mem", default="256MB", help="maintenance_work_mem for the HNSW build")
    ap.add_argument("--examples", type=int, default=5, help="unlinked examples printed per kind")
    args = ap.parse_args()

    path = args.input or Path(str(DEFAULT_INPUT).format(leg=args.leg))
    if not path.exists():
        logger.error("input not found: %s (run build/parse_emendamenti.py)", path)
        return 2
    if not args.neo4j_uri and not args.archive_url:
        ap.error("nothing to do: give --neo4j-uri and/or --archive-url")
    if args.neo4j_uri and not args.neo4j_password:
        ap.error("--neo4j-password or NEO4J_PASSWORD needed")
    if not re.fullmatch(r"\d+[kMG]B", args.index_mem):
        ap.error("--index-mem like 256MB")

    t = time.time()
    rows = read_rows(path, args.limit)
    logger.info("%s: %d rows", path.name, len(rows))
    stats: Counter = Counter()
    unlinked: dict = {}
    if args.neo4j_uri:
        load_graph(rows, args, stats, unlinked)
        report(stats, unlinked, args.examples)
    if args.archive_url:
        load_archive(rows, args, stats)
    logger.info("done in %.0fs%s: %s", time.time() - t, " (dry run)" if args.dry_run else "",
                json.dumps({k: v for k, v in sorted(stats.items()) if not k.startswith(("camera.", "senato."))}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
