"""
Timeline service — Neo4j queries for the parliamentary timeline API.

Provides three async functions consumed by the timeline router:
  - get_sessions():       paginated session list with nested debate summaries
  - get_debate_detail():  phases, speakers, votes, and acts for one debate
  - get_speaker_summary(): AI-generated speaker position summary

All functions accept a Neo4jClient instance (injected by FastAPI Depends) and
a locale string ("it" or "en") to select the correct recap/summary field.

Implementation notes:
  - Neo4j returns dates as neo4j.time.Date objects → convert with str(record["date"])
  - Speakers can be Deputy OR GovernmentMember nodes → use coalesce(d, g) pattern
  - Fetch limit+1 rows to detect whether more pages exist (cursor-based pagination)
"""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor

from ..models.timeline import (
    ActInfo,
    DebateDetailResponse,
    DebateSummary,
    InterventionInfo,
    PhaseInfo,
    SearchMatch,
    SessionCard,
    SpeakerInfo,
    SpeakerSummaryResponse,
    SpeechText,
    TimelineResponse,
    VoteActRef,
    VoteActTextResponse,
    VoteAmendment,
    VoteDetailResponse,
    VoteInfo,
    VoteParticipant,
    VotePartyBreakdown,
)
from .archive import fill_rows, get_archive
from .laws import acts_of_law, laws_for_acts
from .links import act_public_url, act_text_url, https
from .neo4j_client import Neo4jClient


_act_public_url = act_public_url


# Senate sittings: the stenographic record of a sequence of amendment votes
# is split at every outcome, and the ingest turned each "È approvato." into a
# debate of its own. They continue the debate before them.
_OUTCOME_FRAGMENT = re.compile(r"^(?:non\s+)?(?:è|e')?\s*(?:approvat|respint)[oa]\.?$", re.IGNORECASE)
# Titles cut where the record names the act: "Discussione del disegno di
# legge:", "Ripresa della discussione del disegno di legge n."
_TRUNCATED = re.compile(r"(?::|\bn\.)\s*$")
_RESUMED = re.compile(r"^Si riprende la discussione\.?$", re.IGNORECASE)
_CLOCK = re.compile(r"\s*\(ore \d{1,2}[,.]\d{2}\)\.?")


def is_outcome_fragment(title: str | None) -> bool:
    return bool(_OUTCOME_FRAGMENT.match((title or "").strip()))


def clean_debate_title(title: str | None, act: dict | None = None, chamber: str | None = None) -> str:
    """Readable debate title.

    The Camera record repeats the time of the sitting ("(ore 9,08). (ore
    9,08) (ore 9,08)") and pads some titles with dots; Senate titles that
    stop where the act is named get the discussed act appended. `act` is
    {number, title} of an act the debate DISCUSSES.
    """
    t = (title or "").strip()
    clocks = _CLOCK.findall(t)
    if len(clocks) > 1:
        t = _CLOCK.sub("", t).rstrip(" .") + " " + clocks[0].strip().rstrip(".")
    t = re.sub(r"(?:\s*\.){2,}\s*$", ".", t)
    if act and act.get("number"):
        if _TRUNCATED.search(t):
            base = _TRUNCATED.sub("", t).rstrip(" ,")
            name = (act.get("title") or "").strip()
            if len(name) > 160:
                name = name[:160].rsplit(" ", 1)[0] + "…"
            t = f"{base} n. {act['number']}" + (f": {name}" if name else "")
        elif _RESUMED.match(t):
            code = "A.S." if chamber == "senato" else "A.C."
            t = f"Si riprende la discussione ({code} {act['number']})"
    return t


def fold_fragments(debates: list[dict]) -> list[dict]:
    """Merge outcome fragments into the debate before them, in sitting order.

    Each debate is {id, title, speech_count, ...}; a fragment adds its
    speeches to its parent and its id to the parent's `continuation_ids`. A
    fragment with nothing before it stays, titled as what it is.
    """
    out: list[dict] = []
    for d in debates:
        if is_outcome_fragment(d.get("title")) and out:
            parent = out[-1]
            parent["speech_count"] = parent.get("speech_count", 0) + (d.get("speech_count") or 0)
            parent.setdefault("continuation_ids", []).append(d["id"])
            continue
        out.append({**d, "continuation_ids": list(d.get("continuation_ids") or [])})
    return out


_QUORUM_CHECK = re.compile(r"^\s*verifica del numero legale", re.IGNORECASE)


def is_quorum_check(subject: str | None) -> bool:
    """A Senate roll call to count who is present: it decides nothing, the
    source records it with zero votes and outcome "rejected"."""
    return bool(_QUORUM_CHECK.match(subject or ""))


def _absorbed(act: dict) -> bool:
    return (act.get("status") or "").lower().startswith("assorbit")


def _bill_label(act: dict) -> str | None:
    """'ddl n. 1903: Delega al Governo …' for a Senate bill, the code and the
    subject for a motion or resolution."""
    number, title = act.get("number"), (act.get("title") or "").strip()
    if "legge" in (act.get("type") or "").lower() and number:
        return f"ddl n. {number}" + (f": {title}" if title else "")
    subject = (act.get("subject") or "").strip()
    if title and subject and subject.lower() not in title.lower():
        return f"{title}: {subject}"
    return title or subject or None


def _main_act(acts: list[dict]) -> dict | None:
    acts = [a for a in acts or [] if a and (a.get("number") or a.get("title"))]
    return sorted(acts, key=lambda a: (_absorbed(a), str(a.get("number") or "")))[0] if acts else None


def senate_vote_description(acts: list[dict]) -> str | None:
    """What a Senate roll call decided on, from its linked acts: the source
    gives only the label ("Votazione finale", "Em. 3.3, Gaudiano e altri").
    The main act comes first; bills absorbed into it are listed after."""
    acts = [a for a in acts if a and (a.get("number") or a.get("title"))]
    if not acts:
        return None
    main = sorted(acts, key=lambda a: (_absorbed(a), str(a.get("number") or "")))
    label = _bill_label(main[0])
    absorbed = sorted({str(a["number"]) for a in main[1:] if _absorbed(a) and a.get("number")},
                      key=lambda n: (len(n), n))
    if label and absorbed:
        label += f" (assorbiti i ddl n. {', '.join(absorbed)})"
    return label[:1].upper() + label[1:] if label else None


def _vote_kind_fields(subject: str | None, outcome: str | None, description: str | None,
                      present: int | None = None) -> dict:
    """kind, outcome and description of a vote, quorum checks told apart."""
    if is_quorum_check(subject):
        text = "Verifica del numero legale: conta i presenti, non è una votazione su un atto"
        if present:
            text += f" (presenti {present})"
        return {"kind": "quorum_check", "outcome": None, "description": description or text}
    return {"kind": None, "outcome": outcome, "description": description}


# ---------------------------------------------------------------------------
# Sittings search
# ---------------------------------------------------------------------------

# Full-text indexes behind the sittings search, all with the italian analyzer
# (plurals and elisions fold: "giochi" finds "gioco"). db_builder creates
# them (create_search_indexes: timeline_vote/act/debate/session_fulltext);
# chunk_fulltext is the speech index the retrieval already uses.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
_LUCENE_WORDS = {"and", "or", "not", "to"}

SESSION_FILTER = """
  s.legislature = $legislature
  AND ($chambers IS NULL OR coalesce(s.chamber, 'camera') IN $chambers)"""

SEARCH_HITS = {
    "vote": f"""
CALL db.index.fulltext.queryNodes('timeline_vote_fulltext', $q) YIELD node AS v, score
WITH v, score ORDER BY score DESC LIMIT 2000
MATCH (s:Session)-[:HAS_VOTE]->(v)
WHERE {SESSION_FILTER}
RETURN s.id AS sid, v.id AS vote_id, v.number AS vote_number,
       v.subject AS subject, v.description AS description, score""",
    "act": f"""
CALL db.index.fulltext.queryNodes('timeline_act_fulltext', $q) YIELD node AS a, score
WITH a, score ORDER BY score DESC LIMIT 300
CALL {{
  WITH a
  MATCH (s:Session)-[:HAS_VOTE]->(v)-[:ON_ACT]->(a)
  RETURN s, count(v) AS n, min(v.number) AS first_vote,
         min(CASE WHEN v.finalVote THEN v.number END) AS final_vote
  UNION
  WITH a
  MATCH (s:Session)-[:HAS_DEBATE]->()-[:DISCUSSES]->(a)
  RETURN s, 0 AS n, null AS first_vote, null AS final_vote
}}
WITH s, a, score, sum(n) AS votes, coalesce(min(final_vote), min(first_vote)) AS vote_number
WHERE {SESSION_FILTER}
OPTIONAL MATCH (s)-[:HAS_VOTE]->(v {{number: vote_number}})-[:ON_ACT]->(a)
RETURN s.id AS sid, a.title AS title, a.description AS description, a.status AS status,
       head(collect(v.id)) AS vote_id, vote_number, votes, score""",
    "speaker": f"""
MATCH (spk)
WHERE (spk:Deputy OR spk:Senator OR spk:GovernmentMember) AND size($search) >= 3
  AND toLower(coalesce(spk.first_name, '') + ' ' + coalesce(spk.last_name, '')) CONTAINS toLower($search)
MATCH (s:Session)-[:HAS_DEBATE]->()-[:HAS_PHASE]->()-[:CONTAINS_SPEECH]->(sp)-[:SPOKEN_BY]->(spk)
WHERE {SESSION_FILTER}
WITH s, spk, count(DISTINCT sp) AS n
RETURN s.id AS sid, trim(coalesce(spk.first_name, '') + ' ' + coalesce(spk.last_name, '')) AS speaker,
       n AS score""",
    "debate": f"""
CALL db.index.fulltext.queryNodes('timeline_debate_fulltext', $q) YIELD node AS d, score
WITH d, score ORDER BY score DESC LIMIT 2000
MATCH (s:Session)-[:HAS_DEBATE]->(d)
WHERE {SESSION_FILTER}
RETURN s.id AS sid, d.id AS debate_id, d.title AS text, score""",
    "recap": f"""
CALL db.index.fulltext.queryNodes('timeline_session_fulltext', $q) YIELD node AS s, score
WITH s, score ORDER BY score DESC LIMIT 1000
WHERE {SESSION_FILTER}
RETURN s.id AS sid, CASE WHEN $locale = 'en' THEN s.recapEn ELSE s.recapIt END AS text, score""",
    "speech": f"""
CALL db.index.fulltext.queryNodes('chunk_fulltext', $q) YIELD node AS c, score
WITH c, score ORDER BY score DESC LIMIT 3000
MATCH (sp)-[:HAS_CHUNK]->(c)
MATCH (s:Session)-[:HAS_DEBATE]->()-[:HAS_PHASE]->()-[:CONTAINS_SPEECH]->(sp)
WHERE {SESSION_FILTER}
WITH s, head(collect({{c: c, sp: sp, score: score}})) AS top
WITH s, top.sp AS sp, top.c AS c, top.score AS score
OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(spk)
RETURN s.id AS sid, c.text AS text, score,
       trim(coalesce(spk.first_name, '') + ' ' + coalesce(spk.last_name, '')) AS speaker""",
}

# Speeches whose text lives in the Postgres archive (the Senate): Neo4j has
# their Chunk nodes without text, so chunk_fulltext cannot see them. The
# archive finds the chunk ids, the graph places them in their sitting.
ARCHIVE_SPEECH_HITS = f"""
MATCH (c:Chunk) WHERE c.id IN $ids
MATCH (sp)-[:HAS_CHUNK]->(c)
MATCH (s:Session)-[:HAS_DEBATE]->()-[:HAS_PHASE]->()-[:CONTAINS_SPEECH]->(sp)
WHERE {SESSION_FILTER}
WITH s, head(collect({{c: c.id, sp: sp}})) AS top
WITH s, top.c AS chunk_id, top.sp AS sp
OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(spk)
RETURN s.id AS sid, chunk_id,
       trim(coalesce(spk.first_name, '') + ' ' + coalesce(spk.last_name, '')) AS speaker"""

# Motions, resolutions, orders of the day and questions of the Camera carry
# a bare title ("RISOLUZIONE IN ASSEMBLEA 6/00300 presentata da ..."): what
# they are about is in the description.
# "Conversione in legge, con modificazioni, del decreto-legge 7 agosto 2026,
# n. 143, recante disposizioni urgenti in materia di ..." → "Decreto-legge
# n. 143/2026: ...", short enough for the two lines of the list.
_DL_TITLE = re.compile(
    r"^Conversione in legge(?:, con modificazioni,)? del decreto-legge \d{1,2} \w+ (\d{4}), n\. (\d+),"
    r" recante (?:(?:misure|disposizioni) urgenti (?:in materia di|per|di) )?(.+)$", re.IGNORECASE)
_LIST_WIDTH = 110  # characters that fit in the two lines of a row

_BARE_ACT_TITLE = re.compile(r"^[A-ZÀ-Ù'. ]{6,}\s\d")


def archive_speech_rows(neo4j: Neo4jClient, search: str, chambers: list[str] | None,
                        legislature: int) -> list[dict]:
    """Speech hits from the text archive, one per sitting, shaped like the
    rows of SEARCH_HITS["speech"] (sid, text, speaker, score)."""
    archive = get_archive()
    if archive is None:
        return []
    out: list[dict] = []
    for pair in archive.scopes:
        if pair[1] != legislature or (chambers is not None and pair[0] not in chambers):
            continue
        ids = [h["id"] for h in archive.text_search(search.strip(), pair, limit=3000)]
        if not ids:
            continue
        rows = neo4j.query(ARCHIVE_SPEECH_HITS, {"ids": ids, "chambers": chambers, "legislature": legislature})
        with archive.pool.connection() as conn:
            texts = dict(conn.execute("SELECT id, text FROM chunk WHERE id = ANY(%s)",
                                      [[r["chunk_id"] for r in rows]]).fetchall())
        out += [{"sid": r["sid"], "text": texts.get(r["chunk_id"]) or "", "speaker": r.get("speaker"),
                 "score": 1.0} for r in rows]
    return out


# What a sitting shows for a search, in this order: the votes first.
_MATCH_ORDER = ("vote", "act", "debate", "speaker", "speech", "recap")
_MATCH_CAP = {"vote": 3, "act": 1, "debate": 1, "speaker": 1, "speech": 1, "recap": 1}
_MATCHES_PER_SESSION = 4


def lucene_query(text: str | None) -> str | None:
    """Every word of the query, escaped, all required; with more words the
    exact phrase scores higher ("legge di bilancio")."""
    words = [w for w in re.split(r"\s+", (text or "").strip().strip('"')) if w]
    terms = []
    for w in words:
        w = _LUCENE_SPECIAL.sub(r"\\\1", w)
        if w.lower() in _LUCENE_WORDS:
            w = f'"{w}"'
        terms.append(w)
    if len(terms) > 1:
        phrase = " ".join(_LUCENE_SPECIAL.sub(r"\\\1", w) for w in words)
        return f'"{phrase}"^4 OR ({" AND ".join(terms)})'
    return terms[0] if terms else None


def _excerpt(text: str, query: str, width: int = 180) -> str:
    """The stretch of a speech around the first searched word."""
    text = re.sub(r"\s+", " ", text or "").strip()
    low = text.lower()
    pos = low.find(" ".join(query.lower().split()))
    for w in [] if pos >= 0 else re.findall(r"\w+", query.lower()):
        stem = w if len(w) <= 4 else w[: max(4, len(w) - 2)]
        pos = low.find(stem)
        if pos >= 0:
            break
    if pos < 0 or len(text) <= width:
        return text[:width].rstrip() + ("…" if len(text) > width else "")
    # a third of the width before the word, or the whole last stretch when the word is near the end
    start = max(0, min(pos - width // 3, len(text) - width))
    if start:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < pos else start
    end = min(len(text), start + width)
    if end < len(text):
        space = text.rfind(" ", pos, end)
        end = space if space > pos else end
    return ("…" if start else "") + text[start:end].strip() + ("…" if end < len(text) else "")


def search_hits(neo4j: Neo4jClient, search: str, chambers: list[str] | None,
                legislature: int, locale: str) -> dict[str, list[SearchMatch]] | None:
    """Sittings whose votes, acts, debates, speeches or recap contain the
    words, each with what matched. None when the indexes are missing, so the
    caller falls back to the plain substring search."""
    q = lucene_query(search)
    if not q:
        return {}
    params = {"q": q, "search": search.strip(), "chambers": chambers, "legislature": legislature,
              "locale": locale}
    def run(cypher: str) -> list[dict] | None:
        try:
            return neo4j.query(cypher, params)
        except Exception:
            return None

    def archived() -> list[dict]:
        try:
            return archive_speech_rows(neo4j, search, chambers, legislature)
        except Exception:
            return []

    with ThreadPoolExecutor(max_workers=len(SEARCH_HITS) + 1) as pool:
        from_archive = pool.submit(archived)
        results = dict(zip(SEARCH_HITS, pool.map(run, SEARCH_HITS.values())))
        results["speech"] = (results["speech"] or []) + from_archive.result()
    if results["vote"] is None:
        return None

    found: dict[str, dict[str, list[tuple[float, SearchMatch]]]] = {}
    for kind, rows in results.items():
        for r in rows or []:
            if kind == "vote":
                text = " · ".join(t for t in (r.get("subject"), r.get("description")) if t)
                m = SearchMatch(kind=kind, text=text, vote_id=r.get("vote_id"), vote_number=r.get("vote_number"))
            elif kind == "act":
                # Questions and motions have a bare title ("INTERROGAZIONE A
                # RISPOSTA ORALE 3/02563"): their subject is the description.
                title, desc = r.get("title") or "", r.get("description") or ""
                if desc and (not title or title.isupper() or _BARE_ACT_TITLE.match(title)):
                    name = re.sub(r"\s+presentat[ao]\s+da\b.*$", "", title, flags=re.IGNORECASE).strip()
                    text = (name.capitalize() + ": " if name else "") + _excerpt(desc, search, _LIST_WIDTH - len(name))
                else:
                    dl = _DL_TITLE.match(title.strip())
                    if dl:
                        title = f"Decreto-legge n. {dl.group(2)}/{dl.group(1)}: {dl.group(3)}"
                    # Long titles around the searched word, so the list shows it
                    text = _excerpt(title, search, _LIST_WIDTH)
                m = SearchMatch(kind=kind, text=re.sub(r"\s+", " ", text).strip(), vote_id=r.get("vote_id"),
                                vote_number=r.get("vote_number"))
            elif kind == "speaker":
                name = _display_case(r.get("speaker"))
                m = SearchMatch(kind=kind, text=name, speaker=name)
            elif kind == "speech":
                m = SearchMatch(kind=kind, text=_excerpt(r.get("text") or "", search, _LIST_WIDTH),
                                speaker=_display_case(r.get("speaker")) or None)
            elif kind == "debate":
                if is_outcome_fragment(r.get("text")):
                    continue
                m = SearchMatch(kind=kind, text=re.sub(r"\s+", " ", r.get("text") or "").strip())
            else:
                m = SearchMatch(kind=kind, text=_excerpt(r.get("text") or "", search, 220))
            if not m.text:
                continue
            rank = r.get("score") or 0.0
            if kind == "act":
                # The bill the sitting voted on, not the ones absorbed into it
                # (the Senate links its votes to those too)
                rank += 1000 * (r.get("votes") or 0)
                if "assorbit" in (r.get("status") or "").lower():
                    rank -= 500
            found.setdefault(r["sid"], {}).setdefault(kind, []).append((rank, m))

    hits: dict[str, list[SearchMatch]] = {}
    for sid, by_kind in found.items():
        out: list[SearchMatch] = []
        for kind in _MATCH_ORDER:
            seen: set[str] = set()
            ranked = sorted(by_kind.get(kind, []), key=lambda x: -x[0])
            if kind == "vote":
                ranked.sort(key=lambda x: (-x[0], x[1].vote_number or 0))
            for _, m in ranked:
                key = m.vote_id or m.text
                if key in seen:
                    continue
                seen.add(key)
                out.append(m)
                if len(seen) >= _MATCH_CAP[kind]:
                    break
        hits[sid] = out[:_MATCHES_PER_SESSION]
    return hits


async def get_sessions(
    neo4j: Neo4jClient,
    locale: str,
    before: str | None = None,
    limit: int = 20,
    chamber: str = "both",
    legislature: int = 19,
    search: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    with_votes: bool = False,
) -> TimelineResponse:
    """
    Return a paginated list of sessions ordered most-recent-first.

    Pagination uses cursor-based approach: `before` is an ISO date string.
    Fetches limit+1 rows — if more than limit rows returned, has_more=True
    and next_cursor is set to the ISO date of the last included session.

    Chamber mapping:
      "both"   → no chamber filter (returns all chambers)
      "camera" → ["camera"]
      "senato" → ["senato"]

    Search matches, through the full-text indexes (italian analyzer), vote
    subjects, act titles, debate titles, speeches and recaps, plus speaker
    names; each sitting carries what matched in `matches`. Without the
    indexes it falls back to substring matching on titles and recaps.
    with_votes keeps only the sittings with at least one vote.
    """
    recap_field = "recapEn" if locale == "en" else "recapIt"

    # Map chamber param to list (or None for no filter)
    if chamber == "both":
        chambers = None
    else:
        chambers = [chamber]

    # A query naming a published law ("legge 180/2026") also finds the
    # sittings that debated or voted any reading of it.
    law_acts = acts_of_law(neo4j, search) if search else []

    hits = search_hits(neo4j, search, chambers, legislature, locale) if search else None

    search_clause = ""
    if search and hits is not None:
        search_clause = """
  AND (s.id IN $hit_ids
    OR EXISTS { MATCH (s)-[:HAS_DEBATE]->()-[:DISCUSSES]->(la) WHERE la.uri IN $law_acts }
    OR EXISTS { MATCH (s)-[:HAS_VOTE]->()-[:ON_ACT]->(la) WHERE la.uri IN $law_acts })"""
    elif search:
        search_clause = """
  AND (EXISTS {
    MATCH (s)-[:HAS_DEBATE]->(sd)
    WHERE toLower(sd.title) CONTAINS toLower($search)
       OR toLower(s.recapIt) CONTAINS toLower($search)
       OR toLower(s.recapEn) CONTAINS toLower($search)
       OR EXISTS {
         MATCH (sd)-[:HAS_PHASE]->(p2)-[:CONTAINS_SPEECH]->(sp2)-[:SPOKEN_BY]->(spk2)
         WHERE (spk2:Deputy OR spk2:GovernmentMember)
           AND toLower(spk2.first_name + ' ' + spk2.last_name) CONTAINS toLower($search)
       }
  } OR EXISTS { MATCH (s)-[:HAS_DEBATE]->()-[:DISCUSSES]->(la) WHERE la.uri IN $law_acts }
    OR EXISTS { MATCH (s)-[:HAS_VOTE]->()-[:ON_ACT]->(la) WHERE la.uri IN $law_acts })"""

    # When searching, matching debates sort first
    relevance_expr = "0 AS relevance"
    if search:
        relevance_expr = (
            "CASE WHEN toLower(d.title) CONTAINS toLower($search) "
            "OR EXISTS { MATCH (d)-[:DISCUSSES]->(la) WHERE la.uri IN $law_acts } "
            "THEN 1 ELSE 0 END AS relevance"
        )

    cypher = f"""
MATCH (s:Session)
WHERE ($chambers IS NULL OR coalesce(s.chamber, 'camera') IN $chambers)
  AND s.legislature = $legislature
  AND ($before IS NULL OR s.date < date($before))
  AND ($from_date IS NULL OR s.date >= date($from_date))
  AND ($to_date IS NULL OR s.date <= date($to_date))
  AND (NOT $with_votes OR EXISTS {{ (s)-[:HAS_VOTE]->() }}){search_clause}
WITH s ORDER BY s.date DESC LIMIT $fetch_limit
OPTIONAL MATCH (s)-[:HAS_DEBATE]->(d)
OPTIONAL MATCH (d)-[:HAS_PHASE]->(p)-[:CONTAINS_SPEECH]->(sp)
WITH s, d, count(DISTINCT sp) AS dSpeechCount, {relevance_expr}
WITH s, collect(DISTINCT {{
       id: d.id, title: d.title, speechCount: dSpeechCount, ord: d.order, relevance: relevance,
       act: COLLECT {{ MATCH (d)-[:DISCUSSES]->(a:ParliamentaryAct)
                       RETURN {{number: a.number, title: a.title}} ORDER BY a.number LIMIT 1 }}[0]
     }}) AS debates
OPTIONAL MATCH (s)-[:HAS_VOTE]->(v)
WITH s, debates, count(DISTINCT v) AS voteCount
RETURN s.id AS id,
       toString(s.date) AS date,
       s.chamber AS chamber,
       s.number AS number,
       s.{recap_field} AS recap,
       debates,
       voteCount
ORDER BY date DESC
"""

    params: dict = {
        "chambers": chambers,
        "legislature": legislature,
        "before": before,
        "from_date": from_date,
        "to_date": to_date,
        "fetch_limit": limit + 1,
        "with_votes": with_votes,
    }
    if search:
        params["search"] = search
        params["law_acts"] = law_acts
        params["hit_ids"] = list(hits or {})

    rows = neo4j.query(cypher, params)

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: str | None = rows[-1]["date"] if (has_more and rows) else None

    sessions = []
    for row in rows:
        raw = sorted(
            (d for d in (row["debates"] or []) if d.get("id")),
            key=lambda d: (d.get("ord") if d.get("ord") is not None else 10**6, d["id"]),
        )
        folded = fold_fragments([
            {"id": d["id"], "speech_count": d.get("speechCount") or 0, "relevance": d.get("relevance") or 0,
             "title": d.get("title") or "", "act": d.get("act")}
            for d in raw
        ])
        session_hits = (hits or {}).get(row["id"], [])
        if search:
            matched = {m.text for m in session_hits if m.kind == "debate"}
            for d in folded:
                if " ".join(d["title"].split()) in matched:
                    d["relevance"] = 1
            folded.sort(key=lambda d: -d["relevance"])
        debates = [
            DebateSummary(
                id=d["id"],
                title=clean_debate_title(d["title"], d.get("act"), row["chamber"]),
                speech_count=d["speech_count"],
                continuation_ids=d["continuation_ids"],
            )
            for d in folded
        ]
        sessions.append(
            SessionCard(
                id=row["id"],
                date=str(row["date"]),
                chamber=row["chamber"] or "",
                number=row["number"] or 0,
                recap=row["recap"],
                debate_count=len(debates),
                vote_count=row["voteCount"] or 0,
                speech_count=sum(d.speech_count for d in debates),
                debates=debates,
                matches=session_hits,
            )
        )

    return TimelineResponse(sessions=sessions, next_cursor=next_cursor, has_more=has_more)


def _display_case(name: str | None) -> str:
    """Government members keep the Camera's upper-case names (WANDA FERRO)."""
    name = (name or "").strip()
    return name.title() if name.isupper() else name


# Party of a speaker at the sitting date: the group (in the sitting's
# chamber when there is one: a deputy in the Government speaking in the
# Senate keeps the Camera group), or its Mixed Group component when the
# speaker sat in the Misto, never the Misto as a whole.
SPEAKER_PARTY = """
        OPTIONAL MATCH (spk)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
          WHERE mg.start_date <= sess.date
            AND (mg.end_date IS NULL OR mg.end_date >= sess.date)
        OPTIONAL MATCH (spk)-[mc:MEMBER_OF_COMPONENT]->(mcomp:MistoComponent)
          WHERE mc.start_date <= sess.date
            AND (mc.end_date IS NULL OR mc.end_date >= sess.date)
            AND coalesce(mcomp.chamber, 'camera') = coalesce(sess.chamber, 'camera')
"""


MISTO_WITHOUT_COMPONENT = "Misto (non iscritto a una componente)"


def _party(group: str | None, component: str | None) -> tuple[str | None, str | None]:
    """(party, parliamentary_group): the component replaces the Misto; a
    member of the Misto in no component says so (the Camera's "altre
    componenti del gruppo")."""
    if "misto" in (group or "").lower():
        return component or MISTO_WITHOUT_COMPONENT, group
    return group, None


async def get_debate_detail(
    neo4j: Neo4jClient,
    debate_id: str,
    locale: str,
) -> DebateDetailResponse:
    """
    Return full detail for a single debate.

    Senate outcome fragments that follow the debate in the sitting ("È
    approvato.") are part of it: their speeches are included. Votes are the
    sitting's roll calls on the acts the debate discusses (or on their
    amendments, agenda orders and later readings); a debate that discusses
    no act lists none, get_session_votes has them all.
    """
    recap_field = "recapEn" if locale == "en" else "recapIt"

    debate_row = neo4j.query_single(
        f"""
        MATCH (d:Debate {{id: $debate_id}})
        OPTIONAL MATCH (sess:Session)-[:HAS_DEBATE]->(d)
        RETURN d.id AS id,
               d.title AS title,
               d.{recap_field} AS recap,
               coalesce(sess.chamber, 'camera') AS chamber,
               [(sess)-[:HAS_DEBATE]->(o:Debate) | {{id: o.id, title: o.title, ord: o.order}}] AS siblings
        """,
        {"debate_id": debate_id},
    )
    if not debate_row:
        return DebateDetailResponse(
            id=debate_id, title="", recap=None,
            phases=[], speakers=[], votes=[], acts=[],
        )

    siblings = sorted(
        (o for o in (debate_row.get("siblings") or []) if o.get("id")),
        key=lambda o: (o.get("ord") if o.get("ord") is not None else 10**6, o["id"]),
    )
    folded = fold_fragments([{"id": o["id"], "title": o.get("title") or ""} for o in siblings])
    group = next((f for f in folded if f["id"] == debate_id), None)
    continuation_ids = group["continuation_ids"] if group else []
    title = debate_row["title"] or ""
    if not group:
        parent = next((f for f in folded if debate_id in f["continuation_ids"]), None)
        if parent:
            title = f"{clean_debate_title(parent['title'])} (seguito)"
    debate_ids = [debate_id, *continuation_ids]
    params = {"debate_id": debate_id, "debate_ids": debate_ids}

    phase_rows = neo4j.query(
        """
        MATCH (d:Debate)-[:HAS_PHASE]->(p:Phase)
        WHERE d.id IN $debate_ids
        OPTIONAL MATCH (p)-[:CONTAINS_SPEECH]->(sp:Speech)
        WITH d, p, count(DISTINCT sp) AS speechCount
        RETURN p.id AS id,
               p.title AS title,
               p.phaseType AS phase_type,
               speechCount
        ORDER BY coalesce(d.order, 0), p.id
        """,
        params,
    )
    phases = [
        PhaseInfo(
            id=r["id"],
            title=r["title"] or "",
            phase_type=r["phase_type"],
            speech_count=r["speechCount"] or 0,
        )
        for r in phase_rows
    ]

    # speakingRole lives on Speech, not on the speaker node. A deputy who is
    # also in the Government (labels Deputy and GovernmentMember) speaks for
    # the Government when the speech says so (speaker_in_government).
    speaker_rows = neo4j.query(
        f"""
        MATCH (sess:Session)-[:HAS_DEBATE]->(d:Debate)-[:HAS_PHASE]->(p:Phase)
              -[:CONTAINS_SPEECH]->(sp:Speech)-[:SPOKEN_BY]->(spk)
        WHERE d.id IN $debate_ids AND (spk:Deputy OR spk:GovernmentMember)
        WITH spk, sess,
             collect(DISTINCT p.title) AS participatedPhases,
             count(DISTINCT sp) AS speechCount,
             min(sp.id) AS firstSpeechId,
             head(collect(DISTINCT sp.speakingRole)) AS speakingRole,
             any(x IN collect(coalesce(sp.speaker_in_government,
                                       spk:GovernmentMember AND NOT spk:Deputy)) WHERE x) AS isGov
        {SPEAKER_PARTY}
        WITH spk, isGov, participatedPhases, speechCount, firstSpeechId, speakingRole,
             coalesce(head(collect(DISTINCT CASE WHEN coalesce(mg.chamber, sess.chamber, 'camera')
                                               = coalesce(sess.chamber, 'camera') THEN g.name END)),
                      head(collect(DISTINCT g.name))) AS party,
             head(collect(DISTINCT mcomp.name)) AS component
        RETURN spk.id AS id,
               spk.first_name AS first_name,
               spk.last_name AS last_name,
               party, component,
               speakingRole AS speaking_role,
               isGov AS is_government_member,
               speechCount,
               participatedPhases AS phases,
               firstSpeechId
        ORDER BY firstSpeechId
        """,
        params,
    )
    speakers = []
    for r in speaker_rows:
        party, group_name = _party(r["party"], r.get("component"))
        speakers.append(SpeakerInfo(
            id=r["id"],
            first_name=_display_case(r["first_name"]),
            last_name=_display_case(r["last_name"]),
            party=party,
            parliamentary_group=group_name,
            speaking_role=r["speaking_role"],
            is_government_member=bool(r["is_government_member"]),
            speech_count=r["speechCount"] or 0,
            phases=[ph for ph in (r["phases"] or []) if ph],
        ))

    # One row per speech slot: a deputy who takes the floor twice appears twice, in order.
    intervention_rows = neo4j.query(
        f"""
        MATCH (sess:Session)-[:HAS_DEBATE]->(d:Debate)-[:HAS_PHASE]->(p:Phase)
              -[:CONTAINS_SPEECH]->(sp:Speech)-[:SPOKEN_BY]->(spk)
        WHERE d.id IN $debate_ids AND (spk:Deputy OR spk:GovernmentMember)
        {SPEAKER_PARTY}
        WITH sp, p, spk,
             coalesce(sp.speaker_in_government, spk:GovernmentMember AND NOT spk:Deputy) AS isGov,
             coalesce(head(collect(DISTINCT CASE WHEN coalesce(mg.chamber, sess.chamber, 'camera')
                                               = coalesce(sess.chamber, 'camera') THEN g.name END)),
                      head(collect(DISTINCT g.name))) AS party,
             head(collect(DISTINCT mcomp.name)) AS component
        RETURN sp.id AS speech_id,
               spk.id AS speaker_id,
               spk.first_name AS first_name,
               spk.last_name AS last_name,
               party, component,
               sp.speakingRole AS speaking_role,
               isGov AS is_government_member,
               p.title AS phase_title
        ORDER BY sp.id
        """,
        params,
    )
    interventions = []
    for r in intervention_rows:
        party, group_name = _party(r["party"], r.get("component"))
        interventions.append(InterventionInfo(
            speech_id=r["speech_id"],
            speaker_id=r["speaker_id"],
            first_name=_display_case(r["first_name"]),
            last_name=_display_case(r["last_name"]),
            party=party,
            parliamentary_group=group_name,
            speaking_role=r["speaking_role"],
            is_government_member=bool(r["is_government_member"]),
            phase_title=r["phase_title"],
        ))

    # Votes hang off the Session; a vote belongs to the debate when it is on
    # one of the discussed acts, directly or through an agenda order
    # (REFERS_TO), an amendment (AMENDS) or an earlier reading of the act.
    vote_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})<-[:HAS_DEBATE]-(s:Session)-[:HAS_VOTE]->(v:Vote)
        WITH s, v, [(dd:Debate)-[:DISCUSSES]->(x:ParliamentaryAct) WHERE dd.id IN $debate_ids | x] AS mine
        WHERE size(mine) > 0
          AND (any(t IN [(v)-[:ON_ACT]->(a) | a] WHERE t IN mine)
               OR any(t IN [(v)-[:ON_ACT]->()-[:REFERS_TO]->(b) | b] WHERE t IN mine)
               OR any(t IN [(v)-[:ON_ACT]->()-[:NEXT_READING*1..3]->(c) | c] WHERE t IN mine)
               OR any(t IN [(v)-[:ON_AMENDMENT]->()-[:AMENDS]->(e) | e] WHERE t IN mine))
        RETURN v.id AS id,
               v.number AS number,
               v.subject AS subject,
               v.description AS description,
               v.finalVote AS final_vote,
               v.outcome AS outcome,
               v.inFavor AS in_favor,
               v.against AS against,
               v.abstained AS abstained,
               v.present AS present,
               coalesce(s.chamber, 'camera') AS chamber,
               COLLECT { MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct) WHERE a.subject IS NOT NULL
                         RETURN a.subject }[0] AS act_subject,
               COLLECT { MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct)
                         RETURN {number: a.number, title: a.title, type: a.type,
                                 status: a.status, subject: a.subject} } AS acts
        ORDER BY v.number
        """,
        params,
    )
    votes = [v for v in (_vote_info(r) for r in vote_rows) if v.kind != "quorum_check"]

    # Acts discussed, and the joint bills absorbed into them that the
    # debate's votes name too.
    act_rows = neo4j.query(
        """
        MATCH (d:Debate)-[:DISCUSSES]->(a:ParliamentaryAct)
        WHERE d.id IN $debate_ids
        WITH collect(DISTINCT a) AS discussed
        OPTIONAL MATCH (v:Vote) WHERE v.id IN $vote_ids
        OPTIONAL MATCH (v)-[:ON_ACT]->(j:ParliamentaryAct)
          WHERE NOT j IN discussed AND toLower(coalesce(j.status, '')) STARTS WITH 'assorbit'
            AND any(m IN [(v)-[:ON_ACT]->(x) | x] WHERE m IN discussed)
        WITH discussed, collect(DISTINCT j) AS joint
        UNWIND discussed + joint AS a
        RETURN DISTINCT coalesce(a.id, a.uri) AS id,
               a.uri AS uri,
               a.title AS title,
               a.subject AS subject,
               a.type AS type,
               a.number AS number,
               a.status AS status,
               a.url AS url
        """,
        {**params, "vote_ids": [v.id for v in votes]},
    )
    laws = laws_for_acts(neo4j, (r["id"] for r in act_rows))
    acts = sorted(
        (
            ActInfo(
                id=r["id"],
                title=r["title"],
                subject=r["subject"],
                type=r["type"],
                number=r.get("number"),
                status=r.get("status"),
                url=act_public_url(r.get("uri") or r["id"], r.get("url")),
                law=laws.get(r["id"]),
            )
            for r in act_rows
            if r["id"]
        ),
        key=lambda a: (_absorbed({"status": a.status}), a.title or ""),
    )

    main_act = next(({"number": a.number, "title": a.title} for a in acts), None)
    return DebateDetailResponse(
        id=debate_row["id"],
        title=clean_debate_title(title, main_act, debate_row.get("chamber")),
        recap=debate_row["recap"],
        continuation_ids=continuation_ids,
        phases=phases,
        speakers=speakers,
        interventions=interventions,
        votes=votes,
        acts=acts,
    )


def _vote_info(r: dict) -> VoteInfo:
    """VoteInfo from a vote row; Senate votes get their description from the
    linked acts, quorum checks are marked."""
    description = r.get("description")
    if not description and r.get("chamber") == "senato" and not is_quorum_check(r.get("subject")):
        description = senate_vote_description(r.get("acts") or [])
    fields = _vote_kind_fields(r.get("subject"), r.get("outcome"), description, r.get("present"))
    main = _main_act(r.get("acts") or [])
    return VoteInfo(
        id=r["id"],
        number=r["number"] or 0,
        subject=r["subject"],
        description=fields["description"],
        final_vote=bool(r["final_vote"]),
        outcome=fields["outcome"],
        in_favor=r["in_favor"],
        against=r["against"],
        abstained=r["abstained"],
        act_subject=r["act_subject"],
        kind=fields["kind"],
        act_number=(main or {}).get("number"),
        act_title=((main or {}).get("title") or "").strip() or None,
    )


async def get_session_votes(
    neo4j: Neo4jClient,
    session_id: str,
) -> list[VoteInfo]:
    """Return every roll-call vote of a sitting.

    Votes hang off the Session (the Camera XML records them per sitting,
    not per debate), so this is the one honest place to list them without
    the duplication of repeating the full list in each debate detail.
    """
    vote_rows = neo4j.query(
        """
        MATCH (s:Session {id: $session_id})-[:HAS_VOTE]->(v:Vote)
        RETURN v.id AS id,
               v.number AS number,
               v.subject AS subject,
               v.description AS description,
               v.finalVote AS final_vote,
               v.outcome AS outcome,
               v.inFavor AS in_favor,
               v.against AS against,
               v.abstained AS abstained,
               v.present AS present,
               coalesce(s.chamber, 'camera') AS chamber,
               COLLECT { MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct) WHERE a.subject IS NOT NULL
                         RETURN a.subject }[0] AS act_subject,
               COLLECT { MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct)
                         RETURN {number: a.number, title: a.title, type: a.type,
                                 status: a.status, subject: a.subject} } AS acts,
               COLLECT { MATCH (v)-[:ON_AMENDMENT]->(am:Amendment)
                         RETURN {id: am.id, number: am.number,
                                 first: COLLECT { MATCH (p)-[f:SIGNED_AMENDMENT]->(am) WHERE f.first
                                                  RETURN {name: trim(coalesce(p.first_name, '') + ' ' + coalesce(p.last_name, '')),
                                                          id: p.id} }[0],
                                 signers: COUNT { (p2)-[:SIGNED_AMENDMENT]->(am) }} } AS amendments
        ORDER BY v.number
        """,
        {"session_id": session_id},
    )
    texts = _amendment_texts([a["id"] for r in vote_rows for a in (r.get("amendments") or []) if a.get("id")])
    out = []
    for r in vote_rows:
        info = _vote_info(r)
        info.amendment = _vote_amendment(r.get("amendments") or [], texts)
        out.append(info)
    return out


def _amendment_texts(ids: list[str]) -> dict[str, str]:
    """{amendment id: text} from the archive, in one query for the whole sitting."""
    archive = get_archive()
    if archive is None or not ids:
        return {}
    try:
        with archive.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, coalesce(text, text_presented) FROM amendment WHERE id = ANY(%s)", [list(set(ids))]
            ).fetchall()
    except Exception:
        return {}
    return {r[0]: r[1] for r in rows if r[1]}


def _vote_amendment(amendments: list[dict], texts: dict[str, str]) -> VoteAmendment | None:
    """The amendment of a vote: numbers, first signatory and the start of the text."""
    amendments = [a for a in amendments if a.get("number")]
    if not amendments:
        return None
    amendments.sort(key=lambda a: [int(x) if x.isdigit() else 0 for x in re.split(r"\D+", a["number"]) if x] or [0])
    first = amendments[0]
    text = next((texts[a["id"]] for a in amendments if texts.get(a["id"])), None)
    excerpt = None
    if text:
        flat = re.sub(r"\s+", " ", text).strip()
        excerpt = flat if len(flat) <= 240 else flat[:240].rsplit(" ", 1)[0] + "…"
    signer = first.get("first") or {}
    name = (signer.get("name") or "").strip()
    tail = re.search(r"(\d+)$", signer.get("id") or "")
    return VoteAmendment(
        numbers=list(dict.fromkeys(a["number"] for a in amendments)),
        first_signer=name.title() if name.isupper() else (name or None),
        first_signer_id=tail.group(1) if tail else None,
        signers=int(first.get("signers") or 0),
        excerpt=excerpt,
    )


ACT_REF_MAP = """{
    uri: a.uri, title: a.title, subject: a.subject, text_pdf: a.textPdfUrl, url: a.url,
    number: a.number, status: a.status, type: a.type,
    version_url: COLLECT { MATCH (a)-[:HAS_VERSION]->(t) WHERE t.url IS NOT NULL
                           RETURN t.url ORDER BY t.date, t.code LIMIT 1 }[0]
}"""

# Reading codes in a Camera vote description: "PDL 2822-B - ARTICOLO 8".
# "-A" is the committee text of the same reading, not another reading.
_READING_CODE = re.compile(r"\b(\d+(?:-\d+)*-[B-H])\b")


def _later_readings(neo4j: Neo4jClient, acts: list[dict], description: str | None) -> list[dict]:
    """Swap an act for its later reading when the vote is on that reading.

    dati.camera.it links the votes of a second reading (C.2822-B) to the
    first one (C.2822); the description names the reading voted, and
    NEXT_READING leads to it.
    """
    codes = sorted(set(_READING_CODE.findall(description or "")))
    stale = [a["uri"] for a in acts if codes and a.get("number") and a["number"] not in codes]
    if not stale:
        return acts
    rows = neo4j.query(
        f"""
        UNWIND $uris AS uri
        MATCH (:ParliamentaryAct {{uri: uri}})-[:NEXT_READING*1..4]->(a:ParliamentaryAct)
        WHERE a.number IN $codes
        RETURN uri, {ACT_REF_MAP} AS act
        """,
        {"uris": stale, "codes": codes},
    )
    later = {r["uri"]: r["act"] for r in rows if r.get("act")}
    out, seen = [], set()
    for a in acts:
        a = later.get(a["uri"], a)
        if a["uri"] not in seen:
            seen.add(a["uri"])
            out.append(a)
    return out


async def get_vote_detail(
    neo4j: Neo4jClient,
    vote_id: str,
) -> VoteDetailResponse:
    """
    Return full roll-call detail: vote metadata, per-party breakdown, and the
    complete participant list with individual outcomes.

    Individual votes live in the graph as:
      (Person)-[:VOTED]->(IndividualVote {outcome})-[:ON_VOTE]->(Vote)
    with outcome in {"favor", "against", "abstain", "absent", "secret"}. In
    secret ballots the source data publishes participation only ("Ha
    votato"): those records are "secret", and the frontend shows a dedicated
    notice instead of the seat map.

    Party attribution is date-aware via MEMBER_OF_GROUP; deputies in the
    Gruppo Misto are attributed to their political component
    (MEMBER_OF_COMPONENT → MistoComponent) when one is active at vote date.
    """
    meta = neo4j.query_single(
        f"""
        MATCH (s:Session)-[:HAS_VOTE]->(v:Vote {{id: $vote_id}})
        OPTIONAL MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct)
        WITH s, v, a
        RETURN v.id AS id,
               v.number AS number,
               v.subject AS subject,
               v.description AS description,
               collect(DISTINCT {ACT_REF_MAP}) AS acts,
               v.secretVote AS secret_vote,
               v.outcome AS outcome,
               v.type AS vote_type,
               v.inFavor AS in_favor,
               v.against AS against,
               v.abstained AS abstained,
               v.present AS present,
               v.voters AS voters,
               v.majority AS majority,
               v.onMission AS on_mission,
               s.date AS session_date,
               s.number AS session_number,
               s.legislature AS legislature,
               s.record_url AS record_url,
               coalesce(s.chamber, 'camera') AS chamber
        """,
        {"vote_id": vote_id},
    )
    if not meta:
        return VoteDetailResponse(
            id=vote_id, number=0, breakdown=[], participants=[],
        )

    participant_rows = neo4j.query(
        """
        MATCH (s:Session)-[:HAS_VOTE]->(v:Vote {id: $vote_id})
        MATCH (v)<-[:ON_VOTE]-(iv:IndividualVote)<-[:VOTED]-(p:Person)
        OPTIONAL MATCH (p)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
          WHERE mg.start_date <= s.date
            AND (mg.end_date IS NULL OR mg.end_date >= s.date)
        OPTIONAL MATCH (p)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent)
          WHERE mc.start_date <= s.date
            AND (mc.end_date IS NULL OR mc.end_date >= s.date)
        WITH p, iv,
             head(collect(DISTINCT g.name)) AS groupName,
             head(collect(DISTINCT c.name)) AS componentName
        RETURN p.id AS id,
               p.first_name AS first_name,
               p.last_name AS last_name,
               CASE
                 WHEN toLower(coalesce(groupName, '')) CONTAINS 'misto'
                      AND componentName IS NOT NULL
                 THEN componentName
                 ELSE groupName
               END AS party,
               iv.outcome AS outcome,
               p.senato_id AS senato_id
        ORDER BY last_name, first_name
        """,
        {"vote_id": vote_id},
    )

    participants = [
        VoteParticipant(
            id=r["id"],
            first_name=r["first_name"] or "",
            last_name=r["last_name"] or "",
            party=r["party"],
            outcome=r["outcome"] or "absent",
            senato_id=r["senato_id"] if meta["chamber"] == "senato" else None,
        )
        for r in participant_rows
    ]

    # Aggregate per-party counts in Python (one graph roundtrip total).
    counts: dict[str, dict[str, int]] = {}
    for p in participants:
        party = p.party or "—"
        bucket = counts.setdefault(
            party, {"favor": 0, "against": 0, "abstain": 0, "absent": 0, "secret": 0}
        )
        # Unknown outcome values count as absent instead of silently vanishing
        # (pydantic would drop an unexpected key at model construction).
        bucket[p.outcome if p.outcome in bucket else "absent"] += 1
    breakdown = sorted(
        (
            VotePartyBreakdown(party=party, **b)
            for party, b in counts.items()
        ),
        key=lambda b: b.favor + b.against + b.abstain + b.absent + b.secret,
        reverse=True,
    )

    # Linked acts: the voted object first (ODG/motion via aic.rdf), then the
    # main bill, then the joint bills absorbed into it. Titles from the acts
    # ingest carry padding. AICs without a dc:title in the dataset also lack
    # a page on aic.camera.it (the link would give "FILE NON TROVATO"): no
    # title, no link.
    raw_acts = _later_readings(neo4j, [a for a in meta["acts"] if a.get("uri")], meta["description"])
    act_refs = []
    laws = laws_for_acts(neo4j, (a.get("uri") for a in raw_acts))
    for a in raw_acts:
        title = (a["title"] or "").strip() or None
        url = act_public_url(a["uri"], a.get("url"))
        if url and "aic.camera.it" in url and not title:
            url = None
        act_refs.append(VoteActRef(
            uri=a["uri"], title=title, subject=a.get("subject"), number=a.get("number"), status=a.get("status"),
            url=url, text_url=act_text_url(a["uri"], a.get("text_pdf"), a.get("version_url")),
            law=laws.get(a["uri"]),
        ))
    acts = sorted(
        act_refs,
        key=lambda a: (0 if a.url and "aic.camera.it" in a.url else 1, _absorbed({"status": a.status}),
                       a.number or ""),
    )

    description = meta["description"]
    if not description and meta["chamber"] == "senato" and not is_quorum_check(meta["subject"]):
        description = senate_vote_description(raw_acts)
    kind_fields = _vote_kind_fields(meta["subject"], meta["outcome"], description, meta["present"])

    annex_url = (_annex_url(meta["chamber"], meta["legislature"], meta["session_number"])
                 or https(meta.get("record_url")))

    return VoteDetailResponse(
        id=meta["id"],
        number=meta["number"] or 0,
        chamber=meta["chamber"],
        subject=meta["subject"],
        description=kind_fields["description"],
        kind=kind_fields["kind"],
        acts=[a for a in acts if a.title or a.url or a.text_url or a.law],
        session_annex_url=annex_url,
        secret_vote=bool(meta["secret_vote"]),
        outcome=kind_fields["outcome"],
        vote_type=meta["vote_type"],
        in_favor=meta["in_favor"],
        against=meta["against"],
        abstained=meta["abstained"],
        present=meta["present"],
        voters=meta["voters"],
        majority=meta["majority"],
        on_mission=meta["on_mission"],
        breakdown=breakdown,
        participants=participants,
    )


# Voted text (Allegato A of the sitting record)

def _annex_url(chamber: str | None, legislature: int | None, session_number: int | None) -> str | None:
    """URL of Allegato A on documenti.camera.it: full texts of amendments,
    articles and agenda items voted in the sitting. Derivable from
    legislature + sitting number (zero-padded to 4 digits); Camera only."""
    if chamber != "camera" or not session_number:
        return None
    leg = legislature or 19
    return (
        "https://documenti.camera.it/apps/commonServices/getDocumento.ashx"
        f"?idLegislatura={leg}&sezione=assemblea&tipoDoc=documenti_seduta"
        f"&idSeduta={int(session_number):04d}&nomefile=allegato_a"
    )


# Parsed Allegato A, keyed by URL. Few entries (400-700 KB each): short FIFO.
_ANNEX_CACHE: dict[str, list[tuple[str | None, str]]] = {}
_ANNEX_CACHE_MAX = 8


def _fetch_annex_paragraphs(url: str) -> list[tuple[str | None, str]]:
    """Download Allegato A and reduce it to [(id, text)] per <p>.

    The document is well-formed static HTML: flat paragraphs, with anchored
    ids ("eme.6.21._ac.2987-A", "ac.80-A.art_2") in recent sittings.
    """
    import html as html_mod
    import urllib.request

    if url in _ANNEX_CACHE:
        return _ANNEX_CACHE[url]
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 ParliamentRAG"})
    with urllib.request.urlopen(req, timeout=12) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    start = raw.find('id="allegato_a"')
    if start > 0:
        raw = raw[start:]
    paras: list[tuple[str | None, str]] = []
    for m in re.finditer(r"<p([^>]*)>(.*?)</p>", raw, re.S):
        attrs, body = m.group(1), m.group(2)
        idm = re.search(r'id="([^"]+)"', attrs)
        text = re.sub(r"<[^>]+>", " ", body)
        text = html_mod.unescape(re.sub(r"\s+", " ", text)).strip()
        paras.append((idm.group(1) if idm else None, text))
    if len(_ANNEX_CACHE) >= _ANNEX_CACHE_MAX:
        _ANNEX_CACHE.pop(next(iter(_ANNEX_CACHE)))
    _ANNEX_CACHE[url] = paras
    return paras


def _annex_target(subject: str | None, description: str | None) -> tuple[str, str] | None:
    """(kind, number) of what the vote decides, from subject/description.

    kind: "amendment" (amendments, additional/premissive articles,
    sub-amendments — all are "eme" blocks in Allegato A) or "article".
    None for everything else (agenda items, final votes, motions...).
    """
    s = f"{subject or ''} {description or ''}"
    up = s.upper()
    num = re.search(r"\d+(?:\.\d+)+", s)
    # Also match the dotless abbreviations of recent sittings: ART AGG, SUBEM, ART PREM.
    if num and (
        "EMENDAMENTO" in up
        or "SUBEM" in up
        or re.search(r"\bEM\.?\s*\d", up)
        or re.search(r"ART\.?\s*AGG", up)
        or "ARTICOLO AGGIUNTIVO" in up
        or re.search(r"ART\.?\s*PREM", up)
        or "PREMISSIVO" in up
    ):
        return ("amendment", num.group(0))
    art = re.search(r"ARTICOLO\s+(\d+|UNICO)", up)
    if art and "AGGIUNTIVO" not in up:
        return ("article", art.group(1).lower())
    return None


def _extract_amendment(paras: list[tuple[str | None, str]], num: str) -> list[str] | None:
    esc = re.escape(num)
    # The block ends with "6.21. Proponenti." (often after a <br> in the same
    # paragraph), so the terminator may appear anywhere in the text.
    term = re.compile(rf"(?:^|\s){esc}\.\s+[A-ZÀ-Ù]")
    id_re = re.compile(rf"^eme\.{esc}\._")
    start = next((i for i, (p, _) in enumerate(paras) if p and id_re.match(p)), None)
    if start is not None:
        seg: list[str] = []
        for _, text in paras[start:start + 60]:
            if text:
                seg.append(text)
            if term.search(text):
                return seg
        return None
    # Old format (no per-amendment id): find the terminator and walk back to
    # the boundary of the previous block.
    ti = next((i for i, (_, t) in enumerate(paras) if term.search(t)), None)
    if ti is None:
        return None
    boundary = re.compile(
        r"^(\d+(?:\.\d+)+\.\s|A\.C\.|ARTICOLO|EMENDAMENT|SUBEMENDAMENT|"
        r"ORDINI DEL GIORNO|MOZION|RISOLUZION)"
    )
    j = ti - 1
    while j >= 0 and not (
        paras[j][0]
        or boundary.match(paras[j][1])
        or re.search(r"(?:^|\s)\d+(?:\.\d+)+\.\s+[A-ZÀ-Ù][a-zà-ù]", paras[j][1])
    ):
        j -= 1
    return [t for _, t in paras[j + 1:ti + 1] if t]


def _extract_article(paras: list[tuple[str | None, str]], num: str, act: str | None = None) -> list[str] | None:
    """Article block, anchored "ac.2822-B.art_8". With the act code only that
    bill's article matches: one Allegato A can carry several bills."""
    prefix = rf"(?:^|\.)ac\.{re.escape(act)}" if act else ""
    id_re = re.compile(rf"{prefix}\.art_{re.escape(num)}$")
    start = next((i for i, (p, _) in enumerate(paras) if p and id_re.search(p)), None)
    if start is None:
        return None
    seg: list[str] = []
    for k, (pid, text) in enumerate(paras[start:start + 80]):
        if k > 0 and (pid or _ARTICLE_END.match(text)):  # next block starts
            break
        if text:
            seg.append(text)
    return seg or None


# Unanchored headings that open the block after an article: its amendments,
# the next article ("ART. 1."), the agenda orders.
_ARTICLE_END = re.compile(r"^(?:(?:SUB)?EMENDAMENTI\b|ORDINI DEL GIORNO\b|ART\.\s*\d+[\w-]*\.$)")


# A bill's articles are printed in Allegato A of the sitting where their
# examination starts; the votes can come sittings later (C.2822-B: articles
# in sitting 720, article 8 voted in 722). The candidates are the earlier
# sittings that discussed the bill, newest first. camera.it answers Railway
# in seconds per page: the walk has a time budget.
_ANNEX_CANDIDATES = 4
_ANNEX_BUDGET_S = 30.0
_ACT_CODE = re.compile(r"\b(?:PDL|DDL|A\.?C\.?)\s*(\d+(?:-\d+)*(?:-[A-Z]+)?)\b", re.IGNORECASE)


def _annex_block(meta: dict, kind: str, num: str) -> tuple[list[str], str] | None:
    """(paragraphs, url) of the voted block in the sitting's Allegato A or,
    for an article of a named bill, in an earlier sitting that discussed it
    (meta["earlier_sittings"])."""
    import time

    code = _ACT_CODE.search(f"{meta.get('subject') or ''} {meta.get('description') or ''}")
    act = code.group(1).upper() if code else None
    number = int(meta.get("session_number") or 0)
    sittings = [(number, None)]
    if kind == "article" and act:
        sittings += [(int(n), act) for n in (meta.get("earlier_sittings") or [])[:_ANNEX_CANDIDATES]]
    deadline = time.monotonic() + _ANNEX_BUDGET_S
    for n, bill in sittings:
        if time.monotonic() > deadline:
            break
        url = _annex_url(meta["chamber"], meta["legislature"], n)
        if not url:
            return None
        try:
            paras = _fetch_annex_paragraphs(url)
        except Exception:
            continue
        seg = _extract_amendment(paras, num) if kind == "amendment" else _extract_article(paras, num, bill)
        if seg:
            return seg, url
    return None


def _archived_amendment(amendment_ids: list[str]) -> tuple[list[str], str | None] | None:
    """(paragraphs, source page) of a voted amendment from the text archive."""
    archive = get_archive()
    if archive is None or not amendment_ids:
        return None
    try:
        with archive.pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, number, coalesce(text, text_presented), source_url FROM amendment "
                "WHERE id = ANY(%s) AND coalesce(text, text_presented) IS NOT NULL ORDER BY number",
                [amendment_ids]).fetchall()
    except Exception:
        return None
    if not rows:
        return None
    paragraphs: list[str] = []
    for _, number, text, _ in rows:
        if len(rows) > 1:
            paragraphs.append(f"{number}")
        paragraphs.extend(p.strip() for p in re.split(r"\n+", text) if p.strip())
    return paragraphs, rows[0][3]


async def get_vote_act_text(
    neo4j: Neo4jClient,
    vote_id: str,
) -> VoteActTextResponse | None:
    """Text of the voted amendment or article.

    Camera: Allegato A of the sitting (articles also from the sittings
    before it). Both chambers: the text of the amendment the vote is linked
    to (ON_AMENDMENT) in the archive. None when the vote decides neither, or
    no text is found (Senate articles: the graph has no article texts)."""
    meta = neo4j.query_single(
        """
        MATCH (s:Session)-[:HAS_VOTE]->(v:Vote {id: $vote_id})
        RETURN v.subject AS subject,
               v.description AS description,
               s.number AS session_number,
               s.legislature AS legislature,
               coalesce(s.chamber, 'camera') AS chamber,
               [(v)-[:ON_AMENDMENT]->(e:Amendment) | e.id] AS amendments,
               COLLECT { MATCH (v)-[:ON_ACT]->()-[:NEXT_READING*0..3]->(a:ParliamentaryAct)
                               <-[:DISCUSSES]-(:Debate)<-[:HAS_DEBATE]-(e:Session)
                         WHERE e.chamber = s.chamber AND e.legislature = s.legislature
                           AND e.number < s.number
                         RETURN DISTINCT e.number AS n ORDER BY n DESC LIMIT 6 } AS earlier_sittings
        """,
        {"vote_id": vote_id},
    )
    if not meta:
        return None
    target = _annex_target(meta["subject"], meta["description"])
    if target and _annex_url(meta["chamber"], meta["legislature"], meta["session_number"]):
        # Blocking downloads: off the event loop, or every request waits.
        found = await asyncio.to_thread(_annex_block, meta, *target)
        if found:
            return VoteActTextResponse(paragraphs=found[0], source_url=found[1])
    archived = await asyncio.to_thread(_archived_amendment, meta.get("amendments") or [])
    if archived and archived[1]:
        return VoteActTextResponse(paragraphs=archived[0], source_url=https(archived[1]))
    return None


async def get_speaker_summary(
    neo4j: Neo4jClient,
    debate_id: str,
    speaker_id: str,
    locale: str,
) -> SpeakerSummaryResponse:
    """
    Return the AI-generated position summary for a speaker in a specific debate.

    Reads from SpeakerDebateSummary node linked via:
      (Deputy|GovernmentMember)-[:HAS_DEBATE_SUMMARY]->(SpeakerDebateSummary)-[:FOR_DEBATE]->(Debate)

    Returns an empty response (summary=None, speech_count=0, phases=[]) if no
    SpeakerDebateSummary node exists for this (debate, speaker) pair.
    """
    summary_field = "summaryEn" if locale == "en" else "summaryIt"

    row = neo4j.query_single(
        f"""
        MATCH (sds:SpeakerDebateSummary)
        WHERE sds.debateId = $debate_id AND sds.speakerId = $speaker_id
        RETURN sds.{summary_field} AS summary,
               sds.speechCount AS speech_count,
               sds.phases AS phases
        """,
        {"debate_id": debate_id, "speaker_id": speaker_id},
    )

    if not row:
        summary_text = None
        s_count = 0
        s_phases: list[str] = []
    else:
        summary_text = row["summary"]
        s_count = row["speech_count"] or 0
        s_phases = [p for p in (row["phases"] or []) if p]

    speech_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})-[:HAS_PHASE]->(p:Phase)
              -[:CONTAINS_SPEECH]->(sp:Speech)-[:SPOKEN_BY]->(spk)
        WHERE spk.id = $speaker_id AND (spk:Deputy OR spk:GovernmentMember)
        RETURN sp.id AS id, sp.text AS text, p.title AS phase_title
        ORDER BY sp.id
        """,
        {"debate_id": debate_id, "speaker_id": speaker_id},
    )
    fill_rows(speech_rows, speech_fields={"id": "text"})
    speeches = [
        SpeechText(
            id=r["id"],
            text=r["text"] or "",
            phase_title=r["phase_title"],
        )
        for r in speech_rows
        if r.get("text")
    ]

    return SpeakerSummaryResponse(
        summary=summary_text,
        speech_count=s_count,
        phases=s_phases,
        speeches=speeches,
    )
