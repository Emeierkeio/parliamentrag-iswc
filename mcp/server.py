# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2.0,<2", "httpx>=0.27", "pillow>=10"]
# ///
"""
ParliamentRAG MCP server — Italian Parliament data (Chamber of Deputies and
Senate) as Claude tools.

Exposes the read-only public API of www.parliamentrag.it: semantic search over
floor speeches and parliamentary acts, sitting-by-sitting proceedings, roll-call
votes with per-member outcomes, and the exact text of voted amendments/articles.
All data comes from official sources (dati.camera.it, dati.senato.it,
stenographic records) for the 19th legislature. Contents are in Italian.

Run:  uv run mcp/server.py          (stdio transport, no install needed)
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp import Image as FastMCPImage
from mcp.types import ToolAnnotations

from ui_views import HEMICYCLE_VIEW, VERIFY_VIEW

API_BASE = os.environ.get("PARLIAMENTRAG_API", "https://www.parliamentrag.it/api")
# Verificatore delle tre garanzie: sul backend di Fascicoli con la chiave del
# server MCP; senza chiave (uso locale via stdio) passa dalla route pubblica
# del sito, che ha un limite per IP.
FASCICOLI_API = os.environ.get("FASCICOLI_API_URL", "https://api-production-a731.up.railway.app")
FASCICOLI_API_KEY = os.environ.get("FASCICOLI_API_KEY")
PUBLIC_VERIFY_URL = os.environ.get("PUBLIC_VERIFY_URL", "https://www.parliamentrag.it/api/verifica")
# Base pubblica del server MCP stesso: usata per costruire gli URL stabili
# delle immagini (/vote/{id}/hemicycle.png) restituiti dentro i tool result.
MCP_PUBLIC_BASE = os.environ.get("MCP_PUBLIC_BASE", "https://mcp.parliamentrag.it")

# Icona del server (mostrata dai client accanto al nome del connettore).
# Il tipo Icon esiste solo dalle versioni recenti dell'SDK: senza, si va
# avanti senza logo invece di crashare sui client con mcp vecchio.
try:
    from mcp.types import Icon

    _ICONS = [
        Icon(
            src="https://mcp.parliamentrag.it/icon.png",
            mimeType="image/png",
            sizes=["512x512"],
        )
    ]
except ImportError:
    _ICONS = None

mcp = FastMCP(
    "ParliamentRAG",
    website_url="https://www.parliamentrag.it",
    instructions=(
        "Tools over official Italian Parliament data, Chamber of Deputies and "
        "Senate (19th legislature, via parliamentrag.it). Tools take a `chamber` "
        "argument where it matters: \"camera\", \"senato\" or \"both\"; votes are "
        "never summed across the two houses. Data is in Italian. Every speech and vote links "
        "back to the official record: cite those links when reporting facts. "
        "When you report the results of a specific roll-call vote, also call "
        "get_vote_hemicycle for that vote_id: it returns the numeric breakdown, "
        "a stable public image URL you should cite, and the chart itself. For "
        "secret ballots it returns an explanation instead of a chart. "
        "On hosts with MCP Apps (claude.ai, ChatGPT, Claude Desktop) the "
        "chart and the verification report appear to the user in a view under "
        "the tool call: do not redraw them as artifacts. "
        "Always answer in the language of the conversation (Italian, English, "
        "...): translate summaries and labels, but keep verbatim "
        "quotes in the original Italian. "
        "The backend may cold-start: if a call times out, retry once. "
        "ParliamentRAG makes three guarantees on answers about Parliament: all "
        "groups are heard, the voices quoted are authoritative on the topic, "
        "and every quote is exact, with a link to the record. Whenever your "
        "answer reports or quotes what deputies or senators said, put quotes "
        "in «…» with the speaker's name nearby, then call verify_answer on the "
        "final answer and the user's question. Do not rewrite the answer to "
        "make the checks pass: show the outcome. End the answer with the three "
        "lines of `verdict` from the result, translated into the language of "
        "the conversation, keeping the ✅/❌ marks and the facts as given, and "
        "the closing line about ParliamentRAG with its link.\n"
    ),
    **({"icons": _ICONS} if _ICONS else {}),
)

# Il backend Railway va in sleep: la prima chiamata può metterci decine di
# secondi. Timeout largo + un retry sono parte del contratto, non paranoia.
_TIMEOUT = httpx.Timeout(90.0, connect=30.0)


def _ro(title: str) -> ToolAnnotations:
    """Annotazioni standard: tutti i tool sono letture idempotenti di dati
    pubblici (richiesto dalla directory dei connettori)."""
    return ToolAnnotations(
        title=title,
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )


# Viste MCP Apps: l'host (claude.ai, ChatGPT, Claude Desktop) le mostra sotto
# la chiamata dello strumento. Gli host senza MCP Apps usano il testo.
_UI_MIME = "text/html;profile=mcp-app"
_VERIFY_UI = "ui://parliamentrag/verify-v2.html"
_HEMICYCLE_UI = "ui://parliamentrag/hemicycle-v2.html"


def _ui(uri: str) -> dict:
    # Chiave annidata della specifica 2026-01-26 e chiave piatta delle bozze
    # precedenti, ancora letta da alcuni host.
    return {"ui": {"resourceUri": uri}, "ui/resourceUri": uri}


@mcp.resource(_VERIFY_UI, name="verify_view", title="Verifica delle tre garanzie",
              mime_type=_UI_MIME, meta={"ui": {"prefersBorder": True}})
def _verify_view() -> str:
    return VERIFY_VIEW


@mcp.resource(_HEMICYCLE_UI, name="hemicycle_view", title="Emiciclo di una votazione",
              mime_type=_UI_MIME, meta={"ui": {"prefersBorder": True}})
def _hemicycle_view() -> str:
    return HEMICYCLE_VIEW


async def _get(path: str, params: dict | None = None) -> Any:
    import asyncio

    params = {k: v for k, v in (params or {}).items() if v is not None}
    # UA dedicato: rende l'uso del connettore misurabile nei log del backend.
    headers = {"User-Agent": "parliamentrag-mcp/0.1.0"}
    async with httpx.AsyncClient(
        timeout=_TIMEOUT, follow_redirects=True, headers=headers
    ) as client:
        for attempt in range(1, 4):
            try:
                resp = await client.get(f"{API_BASE}{path}", params=params)
                resp.raise_for_status()
                return resp.json()
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt == 3:
                    raise
                await asyncio.sleep(2 * attempt)
    return None  # unreachable


def _trim(text: Optional[str], limit: int = 600) -> Optional[str]:
    if text and len(text) > limit:
        return text[:limit].rsplit(" ", 1)[0] + "…"
    return text


# Messo nei risultati degli strumenti che restituiscono interventi: il modello
# legge i risultati con più attenzione delle istruzioni del server.
_VERIFY_NEXT = (
    "Before you reply about what deputies or senators said: quote them verbatim in «…» with "
    "the speaker's name nearby, call verify_answer on your final answer and the "
    "user's question, and end the reply with its verdict lines. Do not rewrite "
    "the answer to make the checks pass."
)


@mcp.tool(annotations=_ro("Search parliamentary records"))
async def search_parliament(
    query: str,
    doc_type: str = "all",
    group: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    max_results: int = 10,
    chamber: str = "both",
) -> dict:
    """Search Italian parliamentary records: floor speeches and parliamentary
    acts (bills, motions, written questions) of the Chamber of Deputies and
    the Senate, 19th legislature (Oct 2022 - today). Each result says its
    `chamber`.

    Uses hybrid search (full-text + semantic), so Italian queries work best
    ("salario minimo", "intelligenza artificiale", company names, people).

    Args:
        query: Search query, ideally in Italian.
        doc_type: "all", "speech" (floor speeches) or "act" (parliamentary acts).
        group: Optional parliamentary group name filter (e.g. "MOVIMENTO 5 STELLE").
        start_date: Optional YYYY-MM-DD lower bound.
        end_date: Optional YYYY-MM-DD upper bound.
        max_results: How many results to return (1-30).
        chamber: "both" (default), "camera" (Chamber of Deputies) or
            "senato" (Senate).
    """
    data = await _get(
        "/search/results",
        {
            "chamber": chamber if chamber in ("camera", "senato", "both") else "both",
            "q": query,
            "search_type": "hybrid",
            "doc_type": doc_type,
            "group": group,
            "start_date": start_date,
            "end_date": end_date,
            "page_size": max(1, min(max_results, 30)),
        },
    )
    results = []
    for r in data.get("results", [])[: max(1, min(max_results, 30))]:
        results.append({
            k: (_trim(v) if isinstance(v, str) else v)
            for k, v in r.items()
            if v not in (None, "") and k not in ("embedding",)
        })
    return {"total": data.get("total"), "results": results, "next_step": _VERIFY_NEXT}


_MARK = {"pass": "✅", "fail": "❌", "na": "➖"}


def _verdict(r: dict) -> list[str]:
    """Ready-to-show lines: one per guarantee (mark + the facts behind it), then who checked."""
    s, g, a, q = r["summary"], r["groups"], r["authority"], r["quotes"]

    missing = [x["key"] for x in g["items"] if x["status"] == "missing"]
    groups = f"{g['named']}/{g['total']} groups, Mixed Group components and Government present"
    if missing:
        groups += " — missing: " + ", ".join(missing)
    for m in g.get("mismatches", []):
        groups += f" — {m['name']} is written as ({m['group_written']}) but belongs to {m['voice'] or m['group']}"

    voices = a["voices"]
    if not a["available"]:
        authority = "authority on the topic could not be computed"
    elif not voices:
        authority = "no deputy, senator or member of the Government quoted or named"
    else:
        def why(v: dict) -> str:
            if v.get("role") == "governo":
                return "Government"
            if v.get("role") == "relatore":
                return "rapporteur"
            if v.get("on_topic") is False:
                return "did not speak on the topic"
            if not v.get("rank"):
                return "not ranked"
            size = v.get("pool_size", v.get("group_size"))
            if v.get("pool") == "speakers_on_topic":
                return f"{v['rank']}/{size} among those in the group who spoke on the topic"
            return f"{v['rank']}/{size} in group"
        ok = sum(1 for v in voices if v["authoritative"])
        authority = (f"{ok}/{len(voices)} authoritative (Government, rapporteur or top 5 of their group "
                     "among those who spoke on the topic): ") + \
            "; ".join(f"{v['name']} {why(v)}" + (" (named)" if v.get("source") == "named" else "") for v in voices)

    if not q["total"]:
        quotes = "no quotes of four or more words to check"
    else:
        problems = [x for x in q["items"] if x["status"] != "exact" or not x.get("attributed")]
        quotes = f"{q['exact']}/{q['total']} verbatim in the parliamentary record"
        if problems:
            labels = {"modified": "altered", "omissions": "words cut", "not_found": "not in the record"}
            quotes += " — " + "; ".join(
                f"«{_trim(x['text'], 60)}» " + (labels.get(x["status"]) or "speaker not named nearby")
                for x in problems)

    return [
        f"{_MARK[s['groups']]} All groups: {groups}",
        f"{_MARK[s['authority']]} Authoritative voices: {authority}",
        f"{_MARK[s['quotes']]} Exact quotes: {quotes}",
        "Checked by ParliamentRAG, a research project that checks answers about the Italian "
        "Parliament against official data, without an AI model. Check any answer at "
        "www.parliamentrag.it/verifica",
    ]


@mcp.tool(annotations=_ro("Check an answer against the three guarantees"), meta=_ui(_VERIFY_UI))
async def verify_answer(
    answer: str, question: Optional[str] = None, chamber: str = "both"
) -> dict:
    """Check an answer about the Italian Parliament against ParliamentRAG's
    three guarantees, deterministically and without a language model:

    1. All groups: every parliamentary group in office, every Mixed Group
       component and the Government is named or quoted, for the houses in
       `chamber`.
    2. Authoritative voices: every deputy, senator or member of the
       Government quoted
       exactly or named (full name, or surname without namesakes) speaks for
       the Government, is the rapporteur, or is among the top 5 of their
       group by authority on the question's topic, ranked among the members
       of the group who spoke on that topic.
    3. Exact quotes: every text in «…», “…” or "…" of 4+ words is a
       continuous stretch of one floor speech of the Chamber or the Senate
       in the 19th legislature, and
       the speaker's surname appears near it.

    Call it on the final answer whenever it reports what deputies or
    senators said, and
    end the answer with the `verdict` lines (three checks and a closing line
    about ParliamentRAG), translated. It reports;
    it does not ask you to change the answer.

    Args:
        answer: The full answer, quotes in «…» with the speaker's name nearby.
        question: The user's question; it sets the topic for authority.
        chamber: "both" (default), "camera" or "senato": the houses the
            answer is about.
    """
    chambers = {"camera": ["camera"], "senato": ["senato"]}.get(chamber, ["camera", "senato"])
    payload = {
        "answer": answer[:20000],
        "topic": (question or "")[:500] or None,
        "scope": [{"chamber": c, "legislature": 19} for c in chambers],
    }
    headers = {"User-Agent": "parliamentrag-mcp/0.1.0"}
    if FASCICOLI_API_KEY:
        url, headers["x-api-key"] = f"{FASCICOLI_API}/api/verify", FASCICOLI_API_KEY
    else:
        url = PUBLIC_VERIFY_URL
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=30.0), headers=headers) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        r = resp.json()

    quotes = []
    verdict = _verdict(r)
    for q in r["quotes"]["items"]:
        s = q.get("speech") or {}
        item = {"quote": _trim(q["text"], 200), "status": q["status"]}
        if s:
            item.update(speaker=s.get("name"), group=s.get("group"), date=s.get("date"),
                        record_url=s.get("url"), speaker_named_nearby=q.get("attributed"))
        if q["status"] == "modified":
            item["closest_passage"] = q.get("passage")
        quotes.append(item)
    return {
        "verdict": verdict,
        "scope": r.get("scope"),
        "outcome": r["summary"],
        "groups": {
            "present": [g["key"] for g in r["groups"]["items"] if g["status"] != "missing"],
            "missing": [g["label"] for g in r["groups"]["items"] if g["status"] == "missing"],
        },
        "groups_detail": [
            {k: g[k] for k in ("key", "label", "status")} for g in r["groups"]["items"]
        ],
        "group_mismatches": [
            {k: m.get(k) for k in ("name", "group_written", "voice", "group")}
            for m in r["groups"].get("mismatches", [])
        ],
        "authority": {
            "topic": r["authority"]["topic"],
            "available": r["authority"]["available"],
            "voices": [
                {k: v[k] for k in ("name", "group", "role", "rank", "pool_size", "group_size", "pool", "on_topic",
                                         "authoritative", "source") if k in v}
                for v in r["authority"]["voices"]
            ],
        },
        "quotes": quotes,
        "status_meaning": {
            "exact": "verbatim in the record",
            "omissions": "pieces are in the record but words between them were cut",
            "modified": "not verbatim; closest_passage is what was actually said",
            "not_found": "not in any floor speech of the Chamber or the Senate in the 19th legislature",
        },
        "verify_page": "https://www.parliamentrag.it/verifica",
    }


@mcp.tool(annotations=_ro("List plenary sittings"))
async def list_sessions(
    limit: int = 10,
    before: Optional[str] = None,
    search: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    chamber: str = "both",
) -> dict:
    """List plenary sittings of the Chamber of Deputies and the Senate (each
    says its `chamber`), most recent first,
    each with an AI recap (Italian), its debates and counts of speeches/votes.

    Args:
        limit: Sittings per page (1-30).
        before: ISO date cursor for pagination (returns sittings before it).
        search: Optional keyword filter on debate titles/recaps.
        from_date / to_date: Optional YYYY-MM-DD bounds.
        chamber: "both" (default), "camera" or "senato".
    """
    data = await _get(
        "/timeline",
        {
            "chamber": chamber if chamber in ("camera", "senato", "both") else "both",
            "limit": max(1, min(limit, 30)),
            "before": before,
            "search": search,
            "from_date": from_date,
            "to_date": to_date,
        },
    )
    sessions = []
    for s in data.get("sessions", []):
        sessions.append({
            "id": s["id"],
            "chamber": s.get("chamber") or "camera",
            "number": s["number"],
            "date": s["date"],
            "recap": _trim(s.get("recap"), 800),
            "vote_count": s.get("vote_count"),
            "speech_count": s.get("speech_count"),
            "debates": [
                {"id": d["id"], "title": _trim(d["title"], 200)}
                for d in s.get("debates", [])
            ],
        })
    return {
        "sessions": sessions,
        "next_cursor": data.get("next_cursor"),
        "has_more": data.get("has_more"),
    }


@mcp.tool(annotations=_ro("List roll-call votes of a sitting"))
async def get_session_votes(session_id: str) -> dict:
    """List every roll-call vote of one sitting: subject, description, kind
    (final vote flag), outcome and aggregate counts.

    Args:
        session_id: Session id from list_sessions (e.g. "leg19_sed700").
    """
    votes = await _get(f"/timeline/sessions/{session_id}/votes")
    return {
        "session_id": session_id,
        "votes": [
            {
                "id": v["id"],
                "number": v["number"],
                "subject": v.get("subject"),
                "description": v.get("description"),
                "final_vote": v.get("final_vote"),
                "outcome": v.get("outcome"),
                "in_favor": v.get("in_favor"),
                "against": v.get("against"),
                "abstained": v.get("abstained"),
            }
            for v in votes
        ],
    }


@mcp.tool(annotations=_ro("Get roll-call vote details"))
async def get_vote_details(
    vote_id: str,
    include_individual_votes: bool = False,
    deputy: Optional[str] = None,
    group: Optional[str] = None,
) -> dict:
    """Full detail of one roll-call vote: aggregates, per-group breakdown,
    linked act (with official page and full-text PDF), secret-ballot flag,
    and optionally the individual votes (~400 deputies or ~200 senators;
    `chamber` says which house voted).

    After presenting these results, call get_vote_hemicycle with the same
    vote_id to show the seating chart as well (unless the ballot was secret).

    In secret ballots individual expressions are not public (only abstentions
    are on record) — the "secret_vote" flag tells you when that is the case.

    Args:
        vote_id: Vote id from get_session_votes.
        include_individual_votes: Return the full per-member list (large).
        deputy: Return only individual votes of members whose name contains
            this string (case-insensitive). Overrides include_individual_votes.
        group: Return only individual votes of this parliamentary group
            (substring match). Overrides include_individual_votes.
    """
    d = await _get(f"/timeline/votes/{vote_id}")
    out = {
        "id": d["id"],
        "subject": d.get("subject"),
        "description": d.get("description"),
        "outcome": d.get("outcome"),
        "secret_vote": d.get("secret_vote"),
        "in_favor": d.get("in_favor"),
        "against": d.get("against"),
        "abstained": d.get("abstained"),
        "present": d.get("present"),
        "majority": d.get("majority"),
        "acts": d.get("acts"),
        "breakdown_by_group": d.get("breakdown"),
        "counts_consistency": _counts_consistency(d),
    }
    if not d.get("secret_vote"):
        # The tool docstring alone was not enough: in a 16/10 test on claude.ai
        # the model reported the vote without ever calling the hemicycle tool.
        out = {"next_step": (
            f'Call get_vote_hemicycle with vote_id="{d["id"]}" now, before you reply: '
            "it shows the user the seating chart and gives the public image URL to cite."
        ), **out}
    participants = d.get("participants", [])
    if deputy or group:
        needle_d = (deputy or "").lower()
        needle_g = (group or "").lower()
        filtered = [
            p for p in participants
            if (not needle_d or needle_d in f"{p['first_name']} {p['last_name']}".lower())
            and (not needle_g or needle_g in (p.get("party") or "").lower())
        ]
        out["individual_votes"] = filtered
    elif include_individual_votes:
        out["individual_votes"] = participants
    else:
        out["individual_votes_available"] = len(participants)
    return out


@mcp.tool(annotations=_ro("Get the voted amendment/article text"))
async def get_voted_text(vote_id: str) -> dict:
    """Exact full text of the amendment or article a roll call voted on,
    extracted from the official sitting minutes (Allegato A).

    Only works for votes on amendments and articles; returns a clear message
    for other vote kinds (final votes, agenda items, procedural votes).

    Args:
        vote_id: Vote id from get_session_votes.
    """
    try:
        d = await _get(f"/timeline/votes/{vote_id}/act-text")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            return {
                "available": False,
                "reason": "No extractable text: this vote is not on an "
                          "amendment/article, or the text was not published.",
            }
        raise
    return {"available": True, "paragraphs": d["paragraphs"], "source_url": d["source_url"]}


@mcp.tool(annotations=_ro("Get debate details"))
async def get_debate(debate_id: str) -> dict:
    """Detail of one debate: AI recap (Italian), discussed acts, phases and
    the list of speakers with their groups and speech counts.

    Args:
        debate_id: Debate id from list_sessions.
    """
    d = await _get(f"/timeline/debates/{debate_id}")
    return {
        "next_step": _VERIFY_NEXT,
        "id": d["id"],
        "title": d.get("title"),
        "recap": _trim(d.get("recap"), 1200),
        "acts": d.get("acts"),
        "phases": [
            {"title": p["title"], "speech_count": p["speech_count"]}
            for p in d.get("phases", [])
        ],
        "speakers": [
            {
                "name": f"{s['first_name']} {s['last_name']}",
                "party": s.get("party"),
                "role": s.get("speaking_role"),
                "government_member": s.get("is_government_member"),
                "speech_count": s.get("speech_count"),
            }
            for s in d.get("speakers", [])
        ],
        "votes": [
            {
                "id": v["id"],
                "subject": v.get("subject"),
                "description": v.get("description"),
                "outcome": v.get("outcome"),
            }
            for v in d.get("votes", [])
        ],
    }



@mcp.tool(annotations=_ro("Vote hemicycle: numbers + chart"), meta=_ui(_HEMICYCLE_UI))
async def get_vote_hemicycle(vote_id: str, format: str = "png"):
    """Hemicycle chart of a roll-call vote, together with the numbers behind
    it: one dot per deputy or senator, coloured by outcome (green=in favour, red=against,
    amber=abstained, grey=absent), grouped by parliamentary group as in the
    ParliamentRAG UI. Dots show group totals, not the real seat of each member.

    Returns multiple content blocks, so the information survives clients that
    drop images:
    1. a JSON text block with outcome, official totals, per-group breakdown,
       a counts-consistency check and stable public image URLs
       (https://mcp.parliamentrag.it/vote/{vote_id}/hemicycle.png or .svg) —
       cite the URL when reporting the vote;
    2. the chart: a PNG image block (default), or the SVG markup as a text
       block when format="svg" (lightweight, can be embedded inline).

    Hosts with MCP Apps (claude.ai, ChatGPT, Claude Desktop) show the chart
    to the user in a view under the tool call: do not redraw it. Only if your
    client shows neither the view nor tool-result images, use format="svg"
    and render the markup as an artifact, verbatim and complete.

    For secret ballots there is nothing to draw: individual votes are not
    public (only abstentions are on record), and the tool returns the
    aggregate totals with an explanation instead of a chart.

    Args:
        vote_id: Vote id from get_session_votes.
        format: "png" (image block, default) or "svg" (markup as text).
    """
    if format not in ("png", "svg"):
        return {"error": f'Unsupported format "{format}": use "png" or "svg".'}
    d = await _get(f"/timeline/votes/{vote_id}")
    totals = {
        "in_favor": d.get("in_favor"),
        "against": d.get("against"),
        "abstained": d.get("abstained"),
        "present": d.get("present"),
        "majority": d.get("majority"),
    }
    if d.get("secret_vote"):
        return {
            "available": False,
            "secret_vote": True,
            "reason": (
                "Secret ballot: individual votes are not public, so there is "
                "no hemicycle to draw. Only the aggregate totals below are "
                "official; the only expressions on record are abstentions."
            ),
            "official_totals": totals,
            "outcome": d.get("outcome"),
            "chamber": d.get("chamber"),
        }
    participants = d.get("participants", [])
    if not any(p.get("outcome") in ("favor", "against") for p in participants):
        return {
            "available": False,
            "secret_vote": False,
            "reason": "No individual vote data available for this roll call.",
            "official_totals": totals,
            "outcome": d.get("outcome"),
            "chamber": d.get("chamber"),
        }
    title, sub, note = _hemicycle_captions(d, participants)
    summary = {
        # First key on purpose: on claude.ai the model kept drawing its own
        # hemicycle under the view when this note came last (16/10).
        "display": (
            "IMPORTANT: the user already sees this hemicycle, drawn by ParliamentRAG in "
            "the view right above your reply (claude.ai, ChatGPT, Claude Desktop). Do NOT "
            "draw, render or visualize it again in any form (no chart, SVG, artifact, "
            "widget or image). Report the numbers in words or in a table and cite "
            "image_png_url as the source."
        ),
        "available": True,
        "vote_id": d.get("id"),
        "chamber": d.get("chamber"),
        "subject": d.get("subject"),
        "description": d.get("description"),
        "outcome": d.get("outcome"),
        "official_totals": totals,
        "breakdown_by_group": d.get("breakdown"),
        "counts_consistency": _counts_consistency(d),
        "individual_votes_drawn": len(participants),
        # For the MCP Apps view, which draws the chart: not for the answer.
        # claude.ai does not forward _meta to the view (tested 16/10), so the
        # seats must stay in the text block.
        "seat_map": _seat_payload(participants, d.get("chamber")),
        "image_png_url": f"{MCP_PUBLIC_BASE}/vote/{vote_id}/hemicycle.png?r={_RENDER_V}",
        "image_svg_url": f"{MCP_PUBLIC_BASE}/vote/{vote_id}/hemicycle.svg?r={_RENDER_V}",
        "chart_note": note,
    }
    if format == "svg":
        return [summary, _render_hemicycle_svg(participants, title, sub, note, d.get("chamber"))]
    png = _render_hemicycle_png(participants, title, sub, note, d.get("chamber"))
    return [summary, FastMCPImage(data=png, format="png")]


# Pagina umana sulla radice del dominio: chi apre l'URL nel browser (dal
# post o per curiosità) deve capire cos'è, non vedere un errore JSON-RPC.
# Pagina localizzata: la lingua si sceglie dall'Accept-Language del browser,
# stesse sei lingue del sito principale, fallback italiano.
_LANDING_TEMPLATE = """<!doctype html><html lang="§lang§"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ParliamentRAG MCP</title>
<link rel="icon" type="image/png" href="/icon.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400..700&display=swap" rel="stylesheet">
<style>
:root{--bg:#fbfaf7;--fg:#1c2433;--primary:#1B3A5C;--muted:#6b7280;--border:#e8e5df;--display:'Fraunces',Georgia,serif}
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,'Segoe UI',sans-serif;background:var(--bg);color:var(--fg);margin:0;min-height:100vh;display:flex;flex-direction:column}
a{color:var(--primary)}
header{border-bottom:2px solid var(--fg)}
.shell{max-width:1152px;margin:0 auto;padding:0 24px;width:100%}
.edition{display:flex;justify-content:space-between;gap:12px;padding:8px 0;font-size:11px;letter-spacing:.2em;text-transform:uppercase;color:var(--muted);border-bottom:1px solid var(--border)}
.wordmark{display:flex;align-items:center;justify-content:space-between;gap:24px;padding:20px 0;flex-wrap:wrap}
.brand{display:flex;align-items:center;gap:12px;text-decoration:none;color:var(--fg)}
.brand span{font-family:var(--display);font-size:1.7rem;font-weight:600;letter-spacing:-.02em}
.cta{background:var(--primary);color:#f4f1ea;padding:10px 16px;font-size:13px;letter-spacing:.02em;text-decoration:none}
.cta:hover{background:var(--fg)}
.band{display:block;border-top:1px solid var(--border);background:rgba(27,58,92,.05);text-decoration:none;text-align:center;padding:8px 16px;font-size:11px;letter-spacing:.18em;text-transform:uppercase;color:rgba(28,36,51,.6)}
.band b{font-family:var(--display);text-transform:none;letter-spacing:0;font-size:13px;color:var(--primary)}
main{max-width:1152px;margin:0 auto;padding:48px 24px 64px;width:100%;flex:1}
.intro{max-width:760px}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:16px 64px;margin-top:8px}
@media(max-width:860px){.cols{grid-template-columns:1fr}}
h1{font-family:var(--display);font-size:2rem;font-weight:600;letter-spacing:-.02em;margin:0 0 12px}
h2{font-family:var(--display);font-size:1.2rem;font-weight:600;margin:36px 0 8px}
.cols h2{margin-top:28px}
p,li{font-size:1.0rem;line-height:1.6;color:#4b5563}li{margin:4px 0}
code{background:var(--primary);color:#f4f1ea;padding:3px 8px;border-radius:5px;font-size:.9rem}
li code{background:#edeae2;color:var(--fg)}
footer{border-top:1px solid var(--border);padding:36px 24px;font-size:12px;color:var(--muted)}
footer .row{max-width:1152px;margin:0 auto;display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:16px}
footer .brand span{font-family:var(--display);font-size:.95rem;font-weight:500}
footer nav{display:flex;flex-wrap:wrap;gap:8px 20px}
footer nav a{color:var(--muted);text-decoration:none;border-bottom:1px solid var(--border)}
footer nav a:hover{color:var(--fg);border-color:var(--fg)}
footer .credits{max-width:1152px;margin:20px auto 0;padding-top:16px;border-top:1px solid var(--border);line-height:1.6}
</style></head><body>
<header>
<div class="shell">
<div class="edition"><span>Server MCP</span><span>§institution§</span></div>
<div class="wordmark">
<a class="brand" href="https://www.parliamentrag.it"><img src="https://www.parliamentrag.it/logo-blue.svg" alt="" width="46" height="32"><span>ParliamentRAG</span></a>
<a class="cta" href="https://www.parliamentrag.it/home">§cta§ &rarr;</a>
</div>
</div>
<a class="band" href="https://iswc2026.semanticweb.org"><b>ISWC 2026</b> &nbsp;&middot;&nbsp; §iswc§</a>
</header>
<main>
<h1>ParliamentRAG MCP</h1>
<div class="intro">
<p>§intro§</p>
</div>
<div class="cols">
<section>
<h2>§caps_h§</h2>
<ul>
<li>§cap1§</li>
<li>§cap2§</li>
<li>§cap3§</li>
<li>§cap4§</li>
<li>§cap5§</li>
</ul>
<p>§example§</p>
<p>§source§</p>
</section>
<section>
<h2>§connect_h§</h2>
<p>§endpoint_line§</p>
<p><code>https://mcp.parliamentrag.it/mcp</code></p>
<ul>
<li><b>claude.ai</b>: §settings§ &rarr; §connectors§ &rarr; §add_custom§</li>
<li><b>ChatGPT</b>: §settings§ &rarr; §apps_conn§ (§dev_mode§) &rarr; §create§</li>
<li><b>Claude Code</b>: <code>claude mcp add -t http parliamentrag https://mcp.parliamentrag.it/mcp</code></li>
<li><b>Gemini CLI</b>: <code>gemini mcp add -t http parliamentrag https://mcp.parliamentrag.it/mcp</code></li>
<li><b>Perplexity</b> (§desktop_app§): §settings§ &rarr; §connectors§ &rarr; §add_conn§</li>
<li><b>Le Chat</b> (Mistral): §settings§ &rarr; §connectors§ &rarr; §add_mcp§</li>
<li><b>Cursor</b>: Settings &rarr; MCP &rarr; Add server, §with§ <code>"url"</code> = endpoint</li>
<li><b>VS Code</b> (Copilot): §in§ <code>.vscode/mcp.json</code>, §server_with§ <code>"type": "http"</code></li>
<li><b>Windsurf</b>: §in§ <code>mcp_config.json</code>, §server_with§ <code>"serverUrl"</code> = endpoint</li>
</ul>
</section>
</div>
</main>
<footer>
<div class="row">
<a class="brand" href="https://www.parliamentrag.it"><img src="https://www.parliamentrag.it/logo-blue.svg" alt="" width="26" height="18"><span>ParliamentRAG</span></a>
<nav>
<a href="https://github.com/Emeierkeio/ParliamentRAG">GitHub</a>
<a href="https://orkg.org/papers/R1909763">ORKG</a>
<a href="https://doi.org/10.5281/zenodo.21560331">Zenodo</a>
<a href="https://www.parliamentrag.it/data">§footer_data§</a>
<a href="https://www.parliamentrag.it/privacy">Privacy</a>
</nav>
</div>
<div class="credits">§thesis§ &middot; Prof. Matteo Palmonari &middot; Dott. Riccardo Pozzi &middot;
<a href="https://www.unimib.it/" style="color:inherit">Universit&agrave; di Milano-Bicocca</a></div>
</footer>
</body></html>"""

_MCP_URL_ANCHOR = '<a href="https://www.parliamentrag.it/sviluppatori#mcp">www.parliamentrag.it/sviluppatori</a>'
_MCP_PROTO_ANCHOR = '<a href="https://modelcontextprotocol.io">Model Context Protocol</a>'
_DATI_ANCHOR = ('<a href="https://dati.camera.it">dati.camera.it</a>, '
                '<a href="https://dati.senato.it">dati.senato.it</a>')

_L10N: dict[str, dict[str, str]] = {
    "it": {
        "institution": "Parlamento italiano &middot; XIX Legislatura",
        "cta": "Accedi alla consultazione",
        "iswc": "Accettato &middot; In-Use Track",
        "intro": f"Questo indirizzo è un server {_MCP_PROTO_ANCHOR}. Aperto nel browser "
                 "mostra solo questa pagina; aggiunto a un assistente AI gli dà accesso "
                 "ai dati ufficiali di Camera e Senato (XIX legislatura): votazioni "
                 "nominali, interventi in Aula, testi degli emendamenti votati. Sola "
                 "lettura, senza registrazione, gratuito.",
        "caps_h": "Cosa sa fare",
        "cap1": "Ricerca negli interventi in Aula e negli atti parlamentari",
        "cap2": "Sedute con riassunto, dibattiti e votazioni",
        "cap3": "Dettaglio di ogni voto nominale: aggregati, voti per gruppo e per singolo parlamentare",
        "cap4": "Testo esatto dell'emendamento o articolo votato, dall'Allegato A del resoconto",
        "cap5": "Grafico dell'emiciclo di un voto, come immagine nella chat",
        "example": "Esempio: &laquo;Come hanno votato i deputati del PD sul voto finale "
                   "del DDL 2961?&raquo;. La risposta arriva dai resoconti ufficiali, "
                   "con i numeri reali e i link alle fonti.",
        "source": f"I dati vengono da {_DATI_ANCHOR} e dai resoconti stenografici di "
                  "Camera e Senato. Progetto indipendente, non affiliato al Parlamento. "
                  f"Istruzioni complete e codice: {_MCP_URL_ANCHOR}.",
        "connect_h": "Come collegarlo",
        "endpoint_line": "L'endpoint da aggiungere ai connettori del tuo assistente:",
        "settings": "Impostazioni", "connectors": "Connettori",
        "add_custom": "Aggiungi connettore personalizzato",
        "apps_conn": "App e connettori", "dev_mode": "modalità sviluppatore",
        "create": "Crea", "desktop_app": "app desktop",
        "add_conn": "Aggiungi connettore", "add_mcp": "Aggiungi connettore MCP",
        "with": "con", "in": "in", "server_with": "server con",
        "paper_inuse": "Paper di ricerca", "paper_demo": "Paper demo",
        "footer_data": "Dati aperti (RDF)",
        "thesis": "Un progetto di Mirko Tritella",
    },
    "en": {
        "institution": "Italian Parliament &middot; 19th Legislature",
        "cta": "Start consulting",
        "iswc": "Accepted &middot; In-Use Track",
        "intro": f"This address is a {_MCP_PROTO_ANCHOR} server. Opened in a browser it "
                 "only shows this page; added to an AI assistant it gives it access to "
                 "the official data of the Italian Chamber of Deputies and Senate (19th "
                 "legislature): roll-call votes, floor speeches, the texts of voted "
                 "amendments. Read-only, no sign-up, free.",
        "caps_h": "What it can do",
        "cap1": "Search across floor speeches and parliamentary acts",
        "cap2": "Sittings with summary, debates and votes",
        "cap3": "Detail of every roll-call vote: totals, votes by group and by individual member",
        "cap4": "The exact text of the voted amendment or article, from annex A of the official report",
        "cap5": "The hemicycle chart of a vote, as an image in the chat",
        "example": "Example: &ldquo;How did PD deputies vote on the final vote on bill "
                   "2961?&rdquo;. The answer comes from the official records, with the "
                   "real numbers and links to the sources.",
        "source": f"The data comes from {_DATI_ANCHOR} and the verbatim reports of "
                  "the Chamber and the Senate. Independent project, not affiliated with "
                  f"the Italian Parliament. Full instructions and code: {_MCP_URL_ANCHOR}.",
        "connect_h": "How to connect it",
        "endpoint_line": "The endpoint to add to your assistant's connectors:",
        "settings": "Settings", "connectors": "Connectors",
        "add_custom": "Add custom connector",
        "apps_conn": "Apps &amp; connectors", "dev_mode": "developer mode",
        "create": "Create", "desktop_app": "desktop app",
        "add_conn": "Add connector", "add_mcp": "Add MCP connector",
        "with": "with", "in": "in", "server_with": "server with",
        "paper_inuse": "Research paper", "paper_demo": "Demo paper",
        "footer_data": "Open data (RDF)",
        "thesis": "A project by Mirko Tritella",
    },
}


def _pick_lang(accept_language: str) -> str:
    """Prima lingua supportata nell'Accept-Language, per qualità decrescente."""
    ranked = []
    for i, part in enumerate(accept_language.split(",")):
        code = part.split(";")[0].strip().lower()[:2]
        q = 1.0
        if ";q=" in part:
            try:
                q = float(part.split(";q=")[1].split(",")[0])
            except ValueError:
                q = 0.0
        ranked.append((-q, i, code))
    for _, _, code in sorted(ranked):
        if code in _L10N:
            return code
    return "it"


def _render_landing(accept_language: str) -> str:
    lang = _pick_lang(accept_language)
    html = _LANDING_TEMPLATE.replace("§lang§", lang)
    for key, value in _L10N[lang].items():
        html = html.replace(f"§{key}§", value)
    return html



# ---------------------------------------------------------------------------
# Emiciclo come immagine (stessa disposizione della grafica del sito)
# ---------------------------------------------------------------------------

_WEDGE_ORDER = [
    ("VERDI E SINISTRA", 0), ("PARTITO DEMOCRATICO", 1), ("MOVIMENTO 5 STELLE", 2),
    ("AZIONE", 3), ("ITALIA VIVA", 4), ("MISTO", 5), ("NOI MODERATI", 6),
    ("FORZA ITALIA", 7), ("LEGA", 8), ("FRATELLI D'ITALIA", 9),
]

_OUTCOME_COLOR = {
    "favor": (5, 150, 105),      # verde
    "against": (220, 38, 38),    # rosso
    "abstain": (245, 158, 11),   # ambra
    "absent": (200, 196, 186),   # grigio caldo
}
_OUTCOME_ORDER = {"favor": 0, "against": 1, "abstain": 2, "absent": 3}


def _wedge_rank(party: str | None) -> float:
    up = (party or "").upper()
    if not up:
        return 5.5
    if "MISTO" in up:
        return 5.0
    for needle, rank in _WEDGE_ORDER:
        if needle in up:
            return float(rank)
    if party != up:
        # componenti del Misto (nomi in minuscolo/misto) stanno col Misto;
        # i gruppi del Senato, anch'essi in minuscolo, passano dagli aghi sopra
        return 5.0
    return 5.5


_HEMI_W, _HEMI_H = 1400, 970
# Versione del renderer, nei query string degli URL immagine: i voti sono
# immutabili ma la grafica evolve, e Cloudflare tiene la cache per max-age —
# bump a ogni modifica visiva per non servire render vecchi.
_RENDER_V = "5"
_HEMI_DISCLAIMER = ("Rappresentazione schematica: i punti mostrano i totali di "
                    "voto per gruppo, non il seggio reale dei singoli deputati.")


def _counts_consistency(d: dict) -> Optional[dict]:
    """Confronto tra i totali ufficiali del tabellone e la somma dei conteggi
    per gruppo. Nei dati sorgente occasionalmente divergono: si espongono
    entrambi e si marca l'incoerenza, la scelta di quale citare resta a chi
    consuma il dato."""
    if d.get("secret_vote"):
        # Scrutinio segreto: le espressioni individuali non sono pubbliche
        # (ogni record risulta "absent"), il confronto non ha senso.
        return {
            "applicable": False,
            "reason": "Secret ballot: individual expressions are not public, "
                      "so per-group counts cannot be compared with the "
                      "official totals.",
        }
    groups = d.get("breakdown") or []
    if not groups:
        return None
    sums = {
        "in_favor": sum(g.get("favor") or 0 for g in groups),
        "against": sum(g.get("against") or 0 for g in groups),
        "abstained": sum(g.get("abstain") or 0 for g in groups),
    }
    official = {k: d.get(k) for k in ("in_favor", "against", "abstained")}
    consistent = all(
        official[k] is None or official[k] == sums[k] for k in sums
    )
    out = {
        "official_totals": official,
        "sum_of_group_breakdown": sums,
        "consistent": consistent,
    }
    if not consistent:
        out["note"] = (
            "Official aggregate totals and the sum of per-group counts "
            "disagree. Both come from the official record; cite one "
            "explicitly instead of mixing them."
        )
    return out


def _hemicycle_captions(d: dict, participants: list[dict]) -> tuple[str, str, str]:
    """Titolo, sottotitolo e nota della grafica (condivisi da PNG e SVG)."""
    title = (d.get("subject") or "Votazione") + (
        f" · {d['description']}"
        if d.get("description")
        and d.get("subject") in (None, "Votazione", "Votazione finale")
        else ""
    )
    sub = (f"Favorevoli {d.get('in_favor')} · Contrari {d.get('against')} · "
           f"Astenuti {d.get('abstained')} · voti individuali: {len(participants)}")
    note = _HEMI_DISCLAIMER
    if d.get("chamber") == "senato":
        title = "Senato · " + title
        note = _HEMI_DISCLAIMER_SENATO if _senate_plan() else note.replace("deputati", "senatori")
    cc = _counts_consistency(d)
    if cc and cc.get("consistent") is False:
        note += (" Attenzione: la somma dei conteggi per gruppo non coincide "
                 "con i totali ufficiali del tabellone.")
    return title, sub, note


# ASCII only: the default Pillow font has no accented glyphs.
_HEMI_DISCLAIMER_SENATO = (
    "Pianta reale dell'Aula del Senato (senato.it): ogni punto corrisponde al posto "
    "attuale del senatore; chi ha lasciato l'incarico siede nel posto libero vicino al "
    "suo gruppo. I posti chiari sono senza voto registrato.")


def _senate_plan() -> Optional[dict]:
    """Official Senate floor plan with current seat assignments, or None."""
    global _SENATE_PLAN
    if _SENATE_PLAN is None:
        _SENATE_PLAN = {}
        for candidate in (Path(__file__).parent / "senato_aula.json", Path("senato_aula.json")):
            if candidate.exists():
                _SENATE_PLAN = json.loads(candidate.read_text(encoding="utf-8"))
                break
    return _SENATE_PLAN or None


_SENATE_PLAN: Optional[dict] = None


def _name_key(first: str, last: str) -> str:
    import re
    import unicodedata

    s = unicodedata.normalize("NFKD", f"{first} {last}").encode("ascii", "ignore").decode().lower()
    return " ".join(sorted(re.findall(r"[a-z]+", s)))


def _senate_layout(participants: list[dict], plan: dict):
    """Each senator on their real seat; senators no longer in office (no
    current seat) take the free seat nearest to their group's seats."""
    import math

    # Fit the plan into the area between the caption block and the legend.
    x0, y0, w, h = 150.0, 180.0, 1100.0, 560.0
    xs = [c[1] for c in plan["seats"]]
    ys = [c[2] for c in plan["seats"]]
    k = min(w / (max(xs) - min(xs)), h / (max(ys) - min(ys)))
    ox = x0 + (w - (max(xs) - min(xs)) * k) / 2 - min(xs) * k
    oy = y0 - min(ys) * k
    pos = {c[0]: (ox + c[1] * k, oy + c[2] * k) for c in plan["seats"]}

    taken: dict[int, dict] = {}
    pending: list[dict] = []
    for p in participants:
        pid = (p.get("senato_id") or p.get("id") or "").rstrip("/")
        seat = None
        if "dati.senato.it/senatore/" in pid:
            seat = plan["by_id"].get(pid.rsplit("/", 1)[-1])
        if seat is None:
            seat = plan["by_name"].get(_name_key(p.get("first_name", ""), p.get("last_name", "")))
        if seat is not None and seat in pos and seat not in taken:
            taken[seat] = p
        else:
            pending.append(p)

    centroid: dict[str, tuple[float, float]] = {}
    for party in {p.get("party") for p in taken.values()}:
        pts = [pos[s] for s, p in taken.items() if p.get("party") == party]
        centroid[party] = (sum(x for x, _ in pts) / len(pts), sum(y for _, y in pts) / len(pts))
    middle = (x0 + w / 2, y0 + h / 2)
    for p in sorted(pending, key=lambda q: (q.get("party") or "", q.get("last_name", ""))):
        cx, cy = centroid.get(p.get("party"), middle)
        free = [s for s in pos if s not in taken]
        if not free:
            break
        taken[min(free, key=lambda s: math.hypot(pos[s][0] - cx, pos[s][1] - cy))] = p

    # Order by group position on the plan (left to right), for the group strip.
    mean_x = {party: c[0] for party, c in centroid.items()}
    pairs = sorted(taken.items(), key=lambda sp: (
        mean_x.get(sp[1].get("party"), middle[0]),
        _OUTCOME_ORDER.get(sp[1].get("outcome"), 3),
        pos[sp[0]][0],
    ))
    ordered = [p for _, p in pairs]
    seats = [(pos[s][0], pos[s][1], 0.0, 0) for s, _ in pairs]
    empty = [pos[s] for s in pos if s not in taken]
    dot = plan.get("seatRadius", 5.1) * k * 1.05

    tally = {"favor": 0, "against": 0, "abstain": 0, "absent": 0}
    for p in ordered:
        tally[p.get("outcome") if p.get("outcome") in tally else "absent"] += 1
    return ordered, seats, dot, tally, empty


def _hemicycle_layout(participants: list[dict], chamber: Optional[str] = None):
    """Disposizione dei seggi: stessa geometria per PNG e SVG.

    Ritorna (ordered, seats, dot, tally, empty) con seats allineati a ordered;
    empty sono i posti senza voto (solo nella pianta reale del Senato)."""
    import math

    plan = _senate_plan() if chamber == "senato" else None
    if plan:
        return _senate_layout(participants, plan)

    CX, CY = _HEMI_W // 2, 700
    INNER, OUTER = 220, 500

    ordered = sorted(participants, key=lambda p: (
        _wedge_rank(p.get("party")),
        (p.get("party") or "").upper(),
        _OUTCOME_ORDER.get(p.get("outcome"), 3),
        p.get("last_name", ""),
    ))
    total = len(ordered)
    if total == 0:
        raise ValueError("No individual votes to draw")

    rows = max(4, round(total / 50))
    row_gap = (OUTER - INNER) / (rows - 1)
    radii = [INNER + i * row_gap for i in range(rows)]
    radii_sum = sum(radii)
    exact = [total * r / radii_sum for r in radii]
    counts = [int(v) for v in exact]
    rest = total - sum(counts)
    for _, i in sorted(((v - int(v), i) for i, v in enumerate(exact)), reverse=True)[:rest]:
        counts[i] += 1

    seats = []
    for row, (r, n) in enumerate(zip(radii, counts)):
        for k in range(n):
            ang = math.pi / 2 if n == 1 else math.pi - (math.pi * k) / (n - 1)
            seats.append((CX + r * math.cos(ang), CY - r * math.sin(ang), ang, row))
    seats.sort(key=lambda s: (-s[2], s[3]))

    inner_seats = counts[0] or 1
    arc_spacing = math.pi * INNER / inner_seats
    dot = max(6.0, min(13.0, row_gap * 0.34, arc_spacing * 0.42))

    tally = {"favor": 0, "against": 0, "abstain": 0, "absent": 0}
    for p in ordered:
        tally[p.get("outcome") if p.get("outcome") in tally else "absent"] += 1

    return ordered, seats, dot, tally, []


_SEAT_CODE = {"favor": "f", "against": "c", "abstain": "a"}


def _display_name(p: dict) -> str:
    name = f"{p.get('first_name') or ''} {p.get('last_name') or ''}".strip()
    return name.title() if name.isupper() else name


def _seat_payload(participants: list[dict], chamber: Optional[str]) -> dict:
    """Seats for the MCP Apps view, which draws the hemicycle itself (with a
    label per dot): same geometry as the PNG, cropped to the seats, rounded
    to whole units to keep the result small."""
    ordered, seats, dot, tally, empty = _hemicycle_layout(participants, chamber)
    pts = [(x, y) for x, y, _a, _r in seats] + list(empty)
    x0 = min(x for x, _ in pts) - dot * 2
    y0 = min(y for _, y in pts) - dot * 2
    w = max(x for x, _ in pts) + dot * 2 - x0
    h = max(y for _, y in pts) + dot * 2 - y0
    return {
        "box": [round(w), round(h)],
        "dot": round(dot, 1),
        "seats": [
            [round(x - x0), round(y - y0), _SEAT_CODE.get(p.get("outcome"), "x"),
             _display_name(p), _party_abbr(p.get("party"))]
            for (x, y, _a, _r), p in zip(seats, ordered)
        ],
        # Abbreviation -> full group name, in left-to-right order on the arc.
        "groups": {_party_abbr(p.get("party")): p.get("party") or "" for p in ordered},
        "empty": [[round(x - x0), round(y - y0)] for x, y in empty],
        "tally": tally,
    }


_LEGEND_LABELS = [("favor", "Favorevoli"), ("against", "Contrari"),
                  ("abstain", "Astenuti"), ("absent", "Assenti")]

_PARTY_ABBR = [
    ("FRATELLI D'ITALIA", "FdI"),
    ("PARTITO DEMOCRATICO", "PD"),
    ("LEGA", "Lega"),
    ("FORZA ITALIA", "FI"),
    ("MOVIMENTO 5 STELLE", "M5S"),
    ("AZIONE", "Azione"),
    ("VERDI E SINISTRA", "AVS"),
    ("ITALIA VIVA", "IV"),
    ("CIVICI", "Civici"),
    ("AUTONOMIE", "Aut"),
    ("NOI MODERATI", "NM"),
    ("MINORANZE LINGUISTICHE", "Min.Ling."),
    ("EUROPA", "+Eu"),
    ("VANNACCI", "FN"),
    ("MISTO", "Misto"),
]


def _party_abbr(name: Optional[str]) -> str:
    up = (name or "").upper()
    for needle, abbr in _PARTY_ABBR:
        if needle in up:
            return abbr
    return (name or "Altri").split()[0].title()


def _group_strip(ordered: list[dict]) -> list[tuple[str, dict]]:
    """[(sigla, {outcome: n})] nell'ordine dei cunei (sinistra → destra),
    per la fascia gruppi sotto la legenda: rende leggibile chi è ogni cuneo
    anche quando gruppi adiacenti votano nello stesso modo."""
    strip: list[tuple[str, dict]] = []
    index: dict[str, dict] = {}
    for p in ordered:
        abbr = _party_abbr(p.get("party"))
        if abbr not in index:
            index[abbr] = {"favor": 0, "against": 0, "abstain": 0, "absent": 0}
            strip.append((abbr, index[abbr]))
        o = p.get("outcome")
        index[abbr][o if o in index[abbr] else "absent"] += 1
    return strip


# Componenti del Gruppo Misto alla Camera: nella fascia stanno dentro il Misto,
# non accanto ai gruppi come se lo fossero.
_MISTO_COMPONENTS = ("+Eu", "FN", "Min.Ling.")


def _strip_entries(ordered: list[dict], ink, sep, outcome_color: dict) -> list[list[tuple[str, Any]]]:
    """Voci della fascia gruppi come token (testo, colore), una per gruppo.

    Il Misto è una voce sola con le componenti tra parentesi:
    «Misto (+Eu 3, FN 9, altri 3 3)»; chi non ha componente sta in «altri»."""
    def counts(oc: dict) -> list[tuple[str, Any]]:
        return [(f"{oc[k]} ", outcome_color[k]) for k in ("favor", "against", "abstain") if oc[k]]

    strip = _group_strip(ordered)
    misto = [(a, oc) for a, oc in strip if a in _MISTO_COMPONENTS or a == "Misto"]
    entries: list[list[tuple[str, Any]]] = []
    misto_done = False
    for abbr, oc in strip:
        if abbr in _MISTO_COMPONENTS or (abbr == "Misto" and len(misto) > 1):
            if misto_done:
                continue
            misto_done = True
            tokens: list[tuple[str, Any]] = [("Misto (", ink)]
            parts = [(a, o) for a, o in misto if a != "Misto"] + [("altri", o) for a, o in misto if a == "Misto"]
            for j, (a, o) in enumerate(parts):
                if j:
                    # la virgola si attacca all'ultimo numero: «3, FN», non «3 , FN»
                    last_text, last_color = tokens[-1]
                    tokens[-1] = (last_text.rstrip(), last_color)
                    tokens.append((", ", ink))
                tokens.append((a + " ", ink))
                tokens += counts(o)
            last_text, last_color = tokens[-1]
            tokens[-1] = (last_text.rstrip(), last_color)
            tokens.append((") ", ink))
            entries.append(tokens)
        else:
            entries.append([(abbr + " ", ink)] + counts(oc))
    for i, e in enumerate(entries):
        e.insert(0, ("  ·  " if i else "", sep))
    return entries


def _wrap_note(note: str) -> list[str]:
    """La nota può crescere (avviso incoerenza): a 18px stanno ~120 caratteri
    nella larghezza utile, oltre si va a capo invece di sbordare."""
    import textwrap

    return textwrap.wrap(note, width=120)


def _hemicycle_palette():
    """Palette per la quantizzazione: fondo, colori pieni (voti, testi) e le
    loro sfumature verso il fondo per i bordi antialiasati, più i punti medi
    tra colori di voto adiacenti."""
    from PIL import Image as PILImage

    bg = (247, 243, 236)
    solids = [
        (28, 43, 65),     # navy titoli
        (85, 96, 111),    # grigio sottotitolo
        (141, 135, 121),  # grigio note
        *_OUTCOME_COLOR.values(),
    ]
    colors = [bg]
    for c in solids:
        for t in (0.15, 0.3, 0.45, 0.6, 0.75, 0.9, 1.0):
            colors.append(tuple(round(c[i] * t + bg[i] * (1 - t)) for i in range(3)))
    outcomes = list(_OUTCOME_COLOR.values())
    for i, a in enumerate(outcomes):
        for b in outcomes[i + 1:]:
            colors.append(tuple((a[k] + b[k]) // 2 for k in range(3)))
    flat = [ch for c in colors for ch in c]
    flat += list(bg) * (256 - len(colors))  # pad: mai entry nere spurie
    pal = PILImage.new("P", (1, 1))
    pal.putpalette(flat)
    return pal


def _render_hemicycle_png(
    participants: list[dict], title: str, subtitle: str,
    note: str = _HEMI_DISCLAIMER, chamber: Optional[str] = None,
) -> bytes:
    import io as _io

    from PIL import Image as PILImage, ImageDraw, ImageFont

    W, H = _HEMI_W, _HEMI_H
    CY = 700
    ordered, seats, dot, tally, empty = _hemicycle_layout(participants, chamber)

    img = PILImage.new("RGB", (W, H), (247, 243, 236))
    draw = ImageDraw.Draw(img)
    f_title = ImageFont.load_default(34)
    f_sub = ImageFont.load_default(22)
    f_leg = ImageFont.load_default(24)

    draw.text((40, 34), title, fill=(28, 43, 65), font=f_title)
    draw.text((40, 84), subtitle, fill=(85, 96, 111), font=f_sub)
    for i, line in enumerate(_wrap_note(note)):
        draw.text((40, 118 + i * 24), line, fill=(141, 135, 121),
                  font=ImageFont.load_default(18))

    for x, y in empty:
        draw.circle((x, y), dot, outline=(214, 209, 199), width=2)
    for (x, y, _a, _r), p in zip(seats, ordered):
        color = _OUTCOME_COLOR.get(p.get("outcome"), _OUTCOME_COLOR["absent"])
        draw.circle((x, y), dot, fill=color)

    x = 130
    for key, label in _LEGEND_LABELS:
        if key in ("abstain", "absent") and tally[key] == 0:
            continue
        draw.circle((x, CY + 90), 11, fill=_OUTCOME_COLOR[key])
        text = f"{label} {tally[key]}"
        draw.text((x + 22, CY + 78), text, fill=(28, 43, 65), font=f_leg)
        x += 40 + draw.textlength(text, font=f_leg) + 40

    # Fascia gruppi: sigle nell'ordine dei cunei coi conteggi colorati per
    # esito — senza, i cunei adiacenti con lo stesso voto sono indistinguibili.
    f_grp = ImageFont.load_default(21)
    draw.text((40, CY + 126), "Gruppi, da sinistra a destra dell'arco:",
              fill=(141, 135, 121), font=ImageFont.load_default(18))
    gx, gy = 40.0, CY + 156
    for tokens in _strip_entries(ordered, (28, 43, 65), (176, 170, 156), _OUTCOME_COLOR):
        entry_w = sum(draw.textlength(t, font=f_grp) for t, _ in tokens)
        if gx + entry_w > W - 40:
            gx, gy = 40.0, gy + 34
            tokens[0] = ("", tokens[0][1])
        for t, color in tokens:
            draw.text((gx, gy), t, fill=color, font=f_grp)
            gx += draw.textlength(t, font=f_grp)

    draw.text((40, H - 36), "parliamentrag.it", fill=(141, 135, 121),
              font=ImageFont.load_default(18))

    # Grafica piatta: ridotta a ~1000px e a palette 8 bit pesa una frazione
    # del PNG RGB originale (meno contesto consumato, meno troncamenti lato
    # client). Palette FISSA di colori brand + sfumature verso il fondo: la
    # quantizzazione adattiva sacrificherebbe i colori rari (es. un solo
    # astenuto ambra su 400 punti).
    img = img.resize((1000, round(1000 * H / W)), PILImage.LANCZOS)
    img = img.quantize(palette=_hemicycle_palette(), dither=PILImage.Dither.NONE)

    buf = _io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _render_hemicycle_svg(
    participants: list[dict], title: str, subtitle: str,
    note: str = _HEMI_DISCLAIMER, chamber: Optional[str] = None,
) -> str:
    """Stessa grafica del PNG, come testo SVG: pesa una frazione e un modello
    può reinserirla inline senza perdita."""
    from html import escape

    hexc = {"favor": "#059669", "against": "#dc2626",
            "abstain": "#f59e0b", "absent": "#c8c4ba"}
    CY = 700
    ordered, seats, dot, tally, empty = _hemicycle_layout(participants, chamber)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_HEMI_W} {_HEMI_H}" '
        f'font-family="system-ui, -apple-system, sans-serif">',
        f'<rect width="{_HEMI_W}" height="{_HEMI_H}" fill="#f7f3ec"/>',
        f'<text x="40" y="62" font-size="34" fill="#1c2b41">{escape(title)}</text>',
        f'<text x="40" y="102" font-size="22" fill="#55606f">{escape(subtitle)}</text>',
    ]
    for i, line in enumerate(_wrap_note(note)):
        parts.append(f'<text x="40" y="{132 + i * 24}" font-size="18" '
                     f'fill="#8d8779">{escape(line)}</text>')
    for x, y in empty:
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot:.1f}" fill="none" '
                     f'stroke="#d6d1c7" stroke-width="2"/>')
    for (x, y, _a, _r), p in zip(seats, ordered):
        color = hexc.get(p.get("outcome"), hexc["absent"])
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{dot:.1f}" fill="{color}"/>')
    x = 130.0
    for key, label in _LEGEND_LABELS:
        if key in ("abstain", "absent") and tally[key] == 0:
            continue
        text = f"{label} {tally[key]}"
        parts.append(f'<circle cx="{x:.0f}" cy="{CY + 90}" r="11" fill="{hexc[key]}"/>')
        parts.append(f'<text x="{x + 22:.0f}" y="{CY + 98}" font-size="24" '
                     f'fill="#1c2b41">{escape(text)}</text>')
        x += 40 + len(text) * 13.5 + 40

    parts.append(f'<text x="40" y="{CY + 140}" font-size="18" fill="#8d8779">'
                 "Gruppi, da sinistra a destra dell'arco:</text>")
    gx, gy = 40.0, CY + 172
    est = 12.0  # larghezza media glifo a 21px
    for tokens in _strip_entries(ordered, "#1c2b41", "#b0aa9c", hexc):
        entry_w = sum(len(t) * est for t, _ in tokens)
        if gx + entry_w > _HEMI_W - 40:
            gx, gy = 40.0, gy + 34
            tokens[0] = ("", tokens[0][1])
        for t, color in tokens:
            if t:
                parts.append(f'<text x="{gx:.0f}" y="{gy:.0f}" font-size="21" '
                             f'fill="{color}">{escape(t)}</text>')
            gx += len(t) * est

    parts.append(f'<text x="40" y="{_HEMI_H - 24}" font-size="18" '
                 'fill="#8d8779">parliamentrag.it</text>')
    parts.append("</svg>")
    return "\n".join(parts)


def _install_rate_limit() -> None:
    """Rate limit per IP sull'endpoint remoto.

    Il server è pubblico e senza chiave: i tool sono in sola lettura su dati
    pubblici, quindi l'unico rischio è il martellamento dell'API a monte.
    Finestra scorrevole da 60 richieste/minuto per IP: una conversazione
    tipica di un assistente fa 1-20 chiamate, chi ne fa di più sta facendo
    scraping e può usare direttamente l'API o il dump Zenodo.
    """
    import time
    from collections import deque

    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    WINDOW = 60.0
    LIMIT = int(os.environ.get("MCP_RATE_LIMIT", "60"))
    hits: dict[str, deque] = {}

    class RateLimitMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            if request.url.path in ("/", "/icon.png", "/favicon.ico"):
                return await call_next(request)
            fwd = request.headers.get("x-forwarded-for", "")
            ip = fwd.split(",")[0].strip() or (request.client.host if request.client else "?")
            now = time.monotonic()
            q = hits.setdefault(ip, deque())
            while q and now - q[0] > WINDOW:
                q.popleft()
            if len(q) >= LIMIT:
                return JSONResponse(
                    {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32000,
                               "message": "Rate limit exceeded: max "
                                          f"{LIMIT} requests/minute. For bulk access use "
                                          "the public API or the Zenodo dump."}},
                    status_code=429,
                    headers={"Retry-After": "60"},
                )
            q.append(now)
            if len(hits) > 10000:  # niente crescita illimitata della mappa
                for k in [k for k, v in hits.items() if not v]:
                    hits.pop(k, None)
            return await call_next(request)

    # L'app streamable-http è costruita da FastMCP: il middleware va montato lì.
    original = mcp.streamable_http_app

    def with_middleware(*args, **kwargs):
        app = original(*args, **kwargs)
        app.add_middleware(RateLimitMiddleware)
        return app

    mcp.streamable_http_app = with_middleware


def main() -> None:
    # Due modi di esecuzione:
    # - stdio (default): client locali (Claude Code/Desktop, Cursor, ...)
    # - streamable-http (MCP_TRANSPORT=http): server remoto per i connettori
    #   di ChatGPT e claude.ai; stateless così regge dietro un load balancer.
    transport = os.environ.get("MCP_TRANSPORT", "stdio")
    if transport in ("http", "streamable-http"):
        from mcp.server.transport_security import TransportSecuritySettings

        mcp.settings.host = "0.0.0.0"
        mcp.settings.port = int(os.environ.get("PORT", "8080"))
        mcp.settings.stateless_http = True
        # La protezione DNS-rebinding dell'SDK serve ai server locali: su un
        # dominio pubblico dietro TLS rifiuterebbe l'Host legittimo
        # ("Invalid Host header" per mcp.parliamentrag.it).
        mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

        from starlette.requests import Request
        from starlette.responses import HTMLResponse

        @mcp.custom_route("/", methods=["GET"])
        async def landing(request: Request) -> HTMLResponse:
            # ?lang= vince sull'Accept-Language: il sito principale lo passa
            # per mantenere la lingua scelta dall'utente nella UI.
            lang = request.query_params.get("lang", "").lower()[:2]
            accept = lang if lang in _L10N else request.headers.get("accept-language", "")
            return HTMLResponse(
                _render_landing(accept),
                headers={"Vary": "Accept-Language"},
            )

        # Logo dichiarato negli icons del server: i client lo scaricano da qui.
        # Nel container il file è in /app (cwd), in sviluppo accanto allo script.
        from pathlib import Path

        from starlette.responses import PlainTextResponse, Response

        def _serve_asset(filename: str, media_type: str) -> Response:
            for candidate in (Path(__file__).parent / filename, Path(filename)):
                if candidate.is_file():
                    return Response(
                        candidate.read_bytes(),
                        media_type=media_type,
                        headers={"Cache-Control": "public, max-age=86400"},
                    )
            return PlainTextResponse(f"{filename} not found", status_code=404)

        @mcp.custom_route("/icon.png", methods=["GET"])
        async def icon(_request: Request) -> Response:
            return _serve_asset("icon.png", "image/png")

        # Alcuni client mostrano la favicon del dominio come logo del connettore.
        @mcp.custom_route("/favicon.ico", methods=["GET"])
        async def favicon(_request: Request) -> Response:
            return _serve_asset("favicon.ico", "image/x-icon")

        # URL pubblico stabile dell'emiciclo: funziona su qualunque client,
        # sopravvive alla copia della conversazione, è citabile. I voti sono
        # immutabili, quindi cache lunga.
        async def _hemicycle_response(vote_id: str, fmt: str) -> Response:
            try:
                d = await _get(f"/timeline/votes/{vote_id}")
            except httpx.HTTPStatusError as exc:
                return PlainTextResponse(
                    "vote not found", status_code=exc.response.status_code
                )
            if d.get("secret_vote"):
                return PlainTextResponse(
                    "Secret ballot: individual votes are not public, "
                    "no hemicycle exists for this vote.",
                    status_code=404,
                )
            participants = d.get("participants", [])
            if not any(p.get("outcome") in ("favor", "against") for p in participants):
                return PlainTextResponse(
                    "No individual vote data for this roll call.", status_code=404
                )
            title, sub, note = _hemicycle_captions(d, participants)
            headers = {"Cache-Control": "public, max-age=86400"}
            if fmt == "svg":
                return Response(
                    _render_hemicycle_svg(participants, title, sub, note, d.get("chamber")),
                    media_type="image/svg+xml",
                    headers=headers,
                )
            return Response(
                _render_hemicycle_png(participants, title, sub, note, d.get("chamber")),
                media_type="image/png",
                headers=headers,
            )

        @mcp.custom_route("/vote/{vote_id}/hemicycle.png", methods=["GET"])
        async def hemicycle_png(request: Request) -> Response:
            return await _hemicycle_response(request.path_params["vote_id"], "png")

        @mcp.custom_route("/vote/{vote_id}/hemicycle.svg", methods=["GET"])
        async def hemicycle_svg(request: Request) -> Response:
            return await _hemicycle_response(request.path_params["vote_id"], "svg")

        _install_rate_limit()
        mcp.run(transport="streamable-http")
    else:
        mcp.run()


if __name__ == "__main__":
    main()
