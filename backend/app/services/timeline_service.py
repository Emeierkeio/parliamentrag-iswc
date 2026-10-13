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

import re
import urllib.parse

from ..models.timeline import (
    ActInfo,
    DebateDetailResponse,
    DebateSummary,
    InterventionInfo,
    PhaseInfo,
    SessionCard,
    SpeakerInfo,
    SpeakerSummaryResponse,
    SpeechText,
    TimelineResponse,
    VoteActRef,
    VoteActTextResponse,
    VoteDetailResponse,
    VoteInfo,
    VoteParticipant,
    VotePartyBreakdown,
)
from .archive import fill_rows
from .neo4j_client import Neo4jClient


def _act_public_url(uri: str | None) -> str | None:
    """Public camera.it page for a ParliamentaryAct URI, when derivable.

    - attocamera.rdf/ac19_2735          → act page (PDL/DDL bills)
    - aic.rdf/aic9_01492_027_19         → AIC page (ODG/motion/resolution)
      with the full text; the number is rebuilt from the URI segments
      ("9_02911_A_028" → "9/02911-A/028": letters are suffixes of the
      previous segment).
    """
    if not uri:
        return None
    m = re.search(r"/attocamera\.rdf/ac(\d+)_(\w+)$", uri)
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

    Search matches debate titles, recap text, and speaker names.
    """
    recap_field = "recapEn" if locale == "en" else "recapIt"

    # Map chamber param to list (or None for no filter)
    if chamber == "both":
        chambers = None
    else:
        chambers = [chamber]

    # Build search subquery condition (added to WHERE at debate level)
    search_clause = ""
    if search:
        search_clause = """
  AND EXISTS {
    MATCH (s)-[:HAS_DEBATE]->(sd)
    WHERE toLower(sd.title) CONTAINS toLower($search)
       OR toLower(s.recapIt) CONTAINS toLower($search)
       OR toLower(s.recapEn) CONTAINS toLower($search)
       OR EXISTS {
         MATCH (sd)-[:HAS_PHASE]->(p2)-[:CONTAINS_SPEECH]->(sp2)-[:SPOKEN_BY]->(spk2)
         WHERE (spk2:Deputy OR spk2:GovernmentMember)
           AND toLower(spk2.first_name + ' ' + spk2.last_name) CONTAINS toLower($search)
       }
  }"""

    # When searching, compute a relevance flag per debate so matching debates sort first
    relevance_expr = "0 AS relevance"
    order_debates = "d.id"
    if search:
        relevance_expr = (
            "CASE WHEN toLower(d.title) CONTAINS toLower($search) THEN 1 ELSE 0 END AS relevance"
        )
        order_debates = "relevance DESC, d.id"

    cypher = f"""
MATCH (s:Session)
WHERE ($chambers IS NULL OR coalesce(s.chamber, 'camera') IN $chambers)
  AND s.legislature = $legislature
  AND ($before IS NULL OR s.date < date($before))
  AND ($from_date IS NULL OR s.date >= date($from_date))
  AND ($to_date IS NULL OR s.date <= date($to_date)){search_clause}
WITH s ORDER BY s.date DESC LIMIT $fetch_limit
OPTIONAL MATCH (s)-[:HAS_DEBATE]->(d)
OPTIONAL MATCH (d)-[:HAS_PHASE]->(p)-[:CONTAINS_SPEECH]->(sp)
WITH s, d, count(DISTINCT sp) AS dSpeechCount, {relevance_expr}
ORDER BY s.date DESC, {order_debates}
WITH s, collect(DISTINCT {{id: d.id, title: d.title, speechCount: dSpeechCount}}) AS debates
OPTIONAL MATCH (s)-[:HAS_VOTE]->(v)
WITH s, debates, count(DISTINCT v) AS voteCount
RETURN s.id AS id,
       toString(s.date) AS date,
       s.chamber AS chamber,
       s.number AS number,
       s.{recap_field} AS recap,
       debates,
       voteCount,
       size(debates) AS debateCount,
       reduce(total = 0, d IN debates | total + d.speechCount) AS speechCount
ORDER BY date DESC
"""

    params: dict = {
        "chambers": chambers,
        "legislature": legislature,
        "before": before,
        "from_date": from_date,
        "to_date": to_date,
        "fetch_limit": limit + 1,
    }
    if search:
        params["search"] = search

    rows = neo4j.query(cypher, params)

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    next_cursor: str | None = rows[-1]["date"] if (has_more and rows) else None

    sessions = []
    for row in rows:
        debates = [
            DebateSummary(
                id=d["id"] or "",
                title=d["title"] or "",
                speech_count=d["speechCount"] or 0,
            )
            for d in (row["debates"] or [])
            if d.get("id")  # skip null entries from OPTIONAL MATCH
        ]
        sessions.append(
            SessionCard(
                id=row["id"],
                date=str(row["date"]),
                chamber=row["chamber"] or "",
                number=row["number"] or 0,
                recap=row["recap"],
                debate_count=row["debateCount"] or 0,
                vote_count=row["voteCount"] or 0,
                speech_count=row["speechCount"] or 0,
                debates=debates,
            )
        )

    return TimelineResponse(sessions=sessions, next_cursor=next_cursor, has_more=has_more)


async def get_debate_detail(
    neo4j: Neo4jClient,
    debate_id: str,
    locale: str,
) -> DebateDetailResponse:
    """
    Return full detail for a single debate.

    Queries:
      - Debate recap (locale-aware)
      - Phases with speech counts
      - Speakers (Deputy or GovernmentMember) in chronological order
      - Votes via session (Session-[:HAS_VOTE]->Vote)
      - Parliamentary acts (Debate-[:DISCUSSES]->ParliamentaryAct)
    """
    recap_field = "recapEn" if locale == "en" else "recapIt"

    debate_row = neo4j.query_single(
        f"""
        MATCH (d:Debate {{id: $debate_id}})
        RETURN d.id AS id,
               d.title AS title,
               d.{recap_field} AS recap
        """,
        {"debate_id": debate_id},
    )
    if not debate_row:
        return DebateDetailResponse(
            id=debate_id, title="", recap=None,
            phases=[], speakers=[], votes=[], acts=[],
        )

    phase_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})-[:HAS_PHASE]->(p:Phase)
        OPTIONAL MATCH (p)-[:CONTAINS_SPEECH]->(sp:Speech)
        WITH p, count(DISTINCT sp) AS speechCount
        RETURN p.id AS id,
               p.title AS title,
               p.phaseType AS phase_type,
               speechCount
        ORDER BY p.id
        """,
        {"debate_id": debate_id},
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

    # Party comes from the MEMBER_OF_GROUP relationship (not a direct property).
    # speakingRole lives on Speech, not on the speaker node — collect the first distinct role.
    speaker_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})<-[:HAS_DEBATE]-(sess:Session)
        WITH d, sess
        MATCH (d)-[:HAS_PHASE]->(p:Phase)
              -[:CONTAINS_SPEECH]->(sp:Speech)
        OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(dep:Deputy)
        OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(gov:GovernmentMember)
        WITH coalesce(dep, gov) AS spk,
             (dep IS NULL AND gov IS NOT NULL) AS isGov,
             p, sp, sess
        WHERE spk IS NOT NULL
        WITH spk, isGov, sess,
             collect(DISTINCT p.title) AS participatedPhases,
             count(DISTINCT sp) AS speechCount,
             min(sp.id) AS firstSpeechId,
             head(collect(DISTINCT sp.speakingRole)) AS speakingRole
        OPTIONAL MATCH (spk)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
          WHERE mg.start_date <= sess.date
            AND (mg.end_date IS NULL OR mg.end_date >= sess.date)
        WITH spk, isGov, participatedPhases, speechCount, firstSpeechId, speakingRole,
             head(collect(g.name)) AS party
        RETURN spk.id AS id,
               spk.first_name AS first_name,
               spk.last_name AS last_name,
               party,
               speakingRole AS speaking_role,
               isGov AS is_government_member,
               speechCount,
               participatedPhases AS phases,
               firstSpeechId
        ORDER BY firstSpeechId
        """,
        {"debate_id": debate_id},
    )
    speakers = [
        SpeakerInfo(
            id=r["id"],
            first_name=r["first_name"] or "",
            last_name=r["last_name"] or "",
            party=r["party"],
            speaking_role=r["speaking_role"],
            is_government_member=bool(r["is_government_member"]),
            speech_count=r["speechCount"] or 0,
            phases=[ph for ph in (r["phases"] or []) if ph],
        )
        for r in speaker_rows
    ]

    # One row per speech slot: a deputy who takes the floor twice appears twice, in order.
    intervention_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})<-[:HAS_DEBATE]-(sess:Session)
        MATCH (d)-[:HAS_PHASE]->(p:Phase)-[:CONTAINS_SPEECH]->(sp:Speech)
        OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(dep:Deputy)
        OPTIONAL MATCH (sp)-[:SPOKEN_BY]->(gov:GovernmentMember)
        WITH sp, p, sess,
             coalesce(dep, gov) AS spk,
             (dep IS NULL AND gov IS NOT NULL) AS isGov
        WHERE spk IS NOT NULL
        OPTIONAL MATCH (spk)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
          WHERE mg.start_date <= sess.date
            AND (mg.end_date IS NULL OR mg.end_date >= sess.date)
        WITH sp, p, spk, isGov, head(collect(g.name)) AS party
        RETURN sp.id AS speech_id,
               spk.id AS speaker_id,
               spk.first_name AS first_name,
               spk.last_name AS last_name,
               party,
               sp.speakingRole AS speaking_role,
               isGov AS is_government_member,
               p.title AS phase_title
        ORDER BY sp.id
        """,
        {"debate_id": debate_id},
    )
    interventions = [
        InterventionInfo(
            speech_id=r["speech_id"],
            speaker_id=r["speaker_id"],
            first_name=r["first_name"] or "",
            last_name=r["last_name"] or "",
            party=r["party"],
            speaking_role=r["speaking_role"],
            is_government_member=bool(r["is_government_member"]),
            phase_title=r["phase_title"],
        )
        for r in intervention_rows
    ]

    # Votes hang off the Session, not the Debate.
    vote_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})<-[:HAS_DEBATE]-(s:Session)-[:HAS_VOTE]->(v:Vote)
        RETURN v.id AS id,
               v.number AS number,
               v.subject AS subject,
               v.description AS description,
               v.finalVote AS final_vote,
               v.outcome AS outcome,
               v.inFavor AS in_favor,
               v.against AS against,
               v.abstained AS abstained
        ORDER BY v.number
        """,
        {"debate_id": debate_id},
    )
    votes = [
        VoteInfo(
            id=r["id"],
            number=r["number"] or 0,
            subject=r["subject"],
            description=r["description"],
            final_vote=bool(r["final_vote"]),
            outcome=r["outcome"],
            in_favor=r["in_favor"],
            against=r["against"],
            abstained=r["abstained"],
        )
        for r in vote_rows
    ]

    act_rows = neo4j.query(
        """
        MATCH (d:Debate {id: $debate_id})-[:DISCUSSES]->(a:ParliamentaryAct)
        RETURN a.id AS id,
               a.title AS title,
               a.type AS type
        ORDER BY a.title
        """,
        {"debate_id": debate_id},
    )
    acts = [
        ActInfo(
            id=r["id"],
            title=r["title"],
            type=r["type"],
        )
        for r in act_rows
        if r["id"]  # skip null entries from OPTIONAL MATCH
    ]

    return DebateDetailResponse(
        id=debate_row["id"],
        title=debate_row["title"] or "",
        recap=debate_row["recap"],
        phases=phases,
        speakers=speakers,
        interventions=interventions,
        votes=votes,
        acts=acts,
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
               v.abstained AS abstained
        ORDER BY v.number
        """,
        {"session_id": session_id},
    )
    return [
        VoteInfo(
            id=r["id"],
            number=r["number"] or 0,
            subject=r["subject"],
            description=r["description"],
            final_vote=bool(r["final_vote"]),
            outcome=r["outcome"],
            in_favor=r["in_favor"],
            against=r["against"],
            abstained=r["abstained"],
        )
        for r in vote_rows
    ]


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
        """
        MATCH (s:Session)-[:HAS_VOTE]->(v:Vote {id: $vote_id})
        OPTIONAL MATCH (v)-[:ON_ACT]->(a:ParliamentaryAct)
        RETURN v.id AS id,
               v.number AS number,
               v.subject AS subject,
               v.description AS description,
               collect(DISTINCT {uri: a.uri, title: a.title, text_pdf: a.textPdfUrl}) AS acts,
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
               iv.outcome AS outcome
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
    # context bill. Titles from the acts ingest carry padding. AICs without a
    # dc:title in the dataset also lack a page on aic.camera.it (the link
    # would give "FILE NON TROVATO"): no title, no link.
    act_refs = []
    for a in meta["acts"]:
        if not a.get("uri"):
            continue
        title = (a["title"] or "").strip() or None
        url = _act_public_url(a["uri"])
        if url and "aic.camera.it" in url and not title:
            url = None
        act_refs.append(VoteActRef(title=title, url=url, text_url=a.get("text_pdf")))
    acts = sorted(
        act_refs,
        key=lambda a: 0 if a.url and "aic.camera.it" in a.url else 1,
    )

    annex_url = _annex_url(meta["chamber"], meta["legislature"], meta["session_number"])

    return VoteDetailResponse(
        id=meta["id"],
        number=meta["number"] or 0,
        chamber=meta["chamber"],
        subject=meta["subject"],
        description=meta["description"],
        acts=[a for a in acts if a.title or a.url or a.text_url],
        session_annex_url=annex_url,
        secret_vote=bool(meta["secret_vote"]),
        outcome=meta["outcome"],
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
    with urllib.request.urlopen(req, timeout=25) as resp:
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


def _extract_article(paras: list[tuple[str | None, str]], num: str) -> list[str] | None:
    id_re = re.compile(rf"\.art_{re.escape(num)}$")
    start = next((i for i, (p, _) in enumerate(paras) if p and id_re.search(p)), None)
    if start is None:
        return None
    seg: list[str] = []
    for k, (pid, text) in enumerate(paras[start:start + 80]):
        if k > 0 and pid:  # next anchored block starts
            break
        if text:
            seg.append(text)
    return seg or None


async def get_vote_act_text(
    neo4j: Neo4jClient,
    vote_id: str,
) -> VoteActTextResponse | None:
    """Extract the text of the voted amendment/article from Allegato A.

    None when the vote does not decide an amendment/article, the sitting has
    no reachable Allegato A, or the block cannot be found (old formats
    without anchors, unpublished texts)."""
    meta = neo4j.query_single(
        """
        MATCH (s:Session)-[:HAS_VOTE]->(v:Vote {id: $vote_id})
        RETURN v.subject AS subject,
               v.description AS description,
               s.number AS session_number,
               s.legislature AS legislature,
               coalesce(s.chamber, 'camera') AS chamber
        """,
        {"vote_id": vote_id},
    )
    if not meta:
        return None
    target = _annex_target(meta["subject"], meta["description"])
    url = _annex_url(meta["chamber"], meta["legislature"], meta["session_number"])
    if not target or not url:
        return None
    try:
        paras = _fetch_annex_paragraphs(url)
    except Exception:
        return None
    kind, num = target
    seg = (
        _extract_amendment(paras, num)
        if kind == "amendment"
        else _extract_article(paras, num)
    )
    if not seg:
        return None
    return VoteActTextResponse(paragraphs=seg, source_url=url)


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
