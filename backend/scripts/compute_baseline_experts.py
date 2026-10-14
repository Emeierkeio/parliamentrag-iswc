"""
compute_baseline_experts.py

Enriches evaluation_set.json with fully pre-computed baseline data for every topic.
Replaces any previously written baseline_metrics (from enrich_evaluation_set.py)
with a superset that also includes query-specific authority scores.

For each topic the script computes:

  baseline_experts
    One expert per parliamentary group (top by query-specific authority score).
    Format mirrors ChatHistory.experts from the system pipeline so the evaluation
    dashboard and A/B survey panel can compare system vs. baseline on equal footing.
    Fields per expert: id, first_name, last_name, group, coalition,
                       authority_score, components, institutional_role,
                       intervention_count (# of citations in baseline for that deputy).

  baseline_metrics
    baseline_party_coverage        – unique canonical parties cited / 10 (citation-based)
    baseline_citation_fidelity     – verbatim-verified citations / total citations
    baseline_response_completeness – parties mentioned anywhere in text / 10 (text-based)
    parties_cited                  – sorted list of canonical party names
    citations_total / citations_verified
    citations                      – full list with verbatim-match details + speaker_id

All metrics are computed with the same logic as evaluation.py so they are
directly comparable to the system pipeline metrics.

Usage (run from backend/ directory with venv active):
    python scripts/compute_baseline_experts.py [--dry-run] [--topic "Partial name"]

Options:
    --dry-run       Print results without writing to disk
    --topic NAME    Process only the topic whose name contains NAME (for testing)
"""

import sys
import re
import json
import unicodedata
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple

# Add backend/ to sys.path so app.* imports work when called from any directory
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.config import get_settings
from app.services.neo4j_client import Neo4jClient
from app.services.authority.scorer import AuthorityScorer
from app.services.authority.coalition_logic import CoalitionLogic
from app.services.retrieval.engine import RetrievalEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("compute_baseline_experts")

EVAL_SET_PATH = Path(__file__).parent.parent / "evaluation_set.json"
ALL_PARTIES = 10

# ── Party name mapping ────────────────────────────────────────────────────────
# Maps raw group labels from citation text to the full canonical party names
# used in Neo4j (matching KNOWN_PARTIES in evaluation.py).
# Order is significant: more specific patterns must precede shorter ones.
PARTY_KEYWORDS: List[Tuple[str, List[str]]] = [
    (
        "Fratelli d'Italia",
        ["Fratelli d'Italia", "FdI"],
    ),
    (
        "Lega - Salvini Premier",
        ["Lega - Salvini Premier", "Lega"],
    ),
    (
        "Forza Italia - Berlusconi Presidente - PPE",
        ["Forza Italia - Berlusconi Presidente", "Forza Italia - Berlusconi", "Forza Italia"],
    ),
    (
        "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare",
        ["Noi Moderati"],
    ),
    (
        "Partito Democratico - Italia Democratica e Progressista",
        ["Partito Democratico - Italia", "Partito Democratico", "PD"],
    ),
    (
        "Movimento 5 Stelle",
        ["Movimento 5 Stelle", "M5S"],
    ),
    (
        "Alleanza Verdi e Sinistra",
        ["Alleanza Verdi e Sinistra", "Alleanza Verdi", "AVS", "Verdi e Sinistra"],
    ),
    (
        "Azione - Popolari Europeisti Riformatori - Renew Europe",
        ["Azione - Popolari Europeisti", "Azione"],
    ),
    (
        "Italia Viva - Il Centro - Renew Europe",
        ["Italia Viva - Il Centro", "Italia Viva"],
    ),
    (
        "Misto",
        ["Misto"],
    ),
]

# Keyword lists for text-based party presence detection (response_completeness).
# One hit from any keyword in a row counts that party as present.
TEXT_PARTY_KEYWORDS: List[List[str]] = [
    ["Fratelli d'Italia", "FdI"],
    ["Lega"],
    ["Forza Italia"],
    ["Noi Moderati"],
    ["Partito Democratico", "PD"],
    ["Movimento 5 Stelle", "M5S"],
    ["Azione"],
    ["Italia Viva"],
    ["Alleanza Verdi", "AVS", "Verdi e Sinistra"],
    ["Misto"],
]

# ── Citation regexes (mirrored from enrich_evaluation_set.py) ────────────────
# Pattern: **Name** (Group, DD/MM/YYYY) ... «quote»
# Bold markers are optional; name must start with a capital letter.
_CITATION_RE = re.compile(
    r'\*{0,2}'
    r'([A-ZÀÈÉÌÎÒÓÙÚ][a-zA-ZÀ-öø-ÿ\']*(?:\s+[A-ZÀÈÉÌÎÒÓÙÚ][a-zA-ZÀ-öø-ÿ\']*)*)'
    r'\*{0,2}'
    r'\s*\(([^()]*(?:\([^)]*\)[^()]*)*),\s*(\d{2}/\d{2}/\d{4})\)[^«]*«([^»]+)»'
)

# Fallback pattern for role-based citations starting with a definite article:
#   La deputata (PD, DD/MM/YYYY) ... «quote»
#   Il legislatore (Lega, DD/MM/YYYY) ... «quote»
_CITATION_ROLE_RE = re.compile(
    r"((?:Il|La|L'|Lo|I|Gli|Le)\s+[^(«\n]+?)"
    r'\s*\(([^()]*(?:\([^)]*\)[^()]*)*),\s*(\d{2}/\d{2}/\d{4})\)[^«]*«([^»]+)»'
)

# Italian parliamentary role tokens that signal the captured "name" is NOT a
# deputy surname but a role description (prevents false positives in citations).
_ROLE_TOKENS = frozenset({
    "onorevole", "esponente", "legislatore", "legislatrice",
    "deputata", "deputato", "parlamentare", "senatore", "senatrice",
    "consigliere", "consigliera", "presidente", "vicepresidente",
    "ministro", "ministra", "sottosegretario", "sottosegretaria",
    "consiglio",
})


# ── Text helpers ──────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    """Verbatim-match normalisation (must match evaluation.py _normalize_for_verbatim)."""
    text = unicodedata.normalize("NFKC", text)
    text = text.lower()
    text = re.sub(r'[^\w\s]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _normalize_apostrophes(text: str) -> str:
    """Collapse all apostrophe variants to a plain ASCII apostrophe."""
    for ch in ("\u2019", "\u2018", "\u02BC", "\u0060", "\u00B4"):
        text = text.replace(ch, "'")
    return text


def _canonical_party(group_text: str) -> Optional[str]:
    """Map a raw group label from citation text to the full canonical party name."""
    g = _normalize_apostrophes(group_text.strip())
    g_lower = g.lower()
    for canonical, keywords in PARTY_KEYWORDS:
        for kw in keywords:
            if _normalize_apostrophes(kw).lower() in g_lower:
                return canonical
    return None


def _date_to_iso(date_str: str) -> Optional[str]:
    """Convert DD/MM/YYYY to YYYY-MM-DD for Neo4j date() comparisons."""
    try:
        return datetime.strptime(date_str, "%d/%m/%Y").strftime("%Y-%m-%d")
    except ValueError:
        return None


def _count_parties_in_text(text: str) -> int:
    """Count how many of the 10 parliamentary groups are mentioned anywhere in text."""
    text_norm = _normalize_apostrophes(unicodedata.normalize("NFKC", text)).lower()
    return sum(
        1
        for keywords in TEXT_PARTY_KEYWORDS
        if any(_normalize_apostrophes(kw).lower() in text_norm for kw in keywords)
    )


# ── Citation parsing ──────────────────────────────────────────────────────────

def _parse_citations(baseline_answer: str) -> List[dict]:
    """
    Extract structured citations from a baseline answer.

    Handles two formats:
      1. Name-based:  **Surname** (Group, DD/MM/YYYY) ... «quote»
      2. Role-based:  La deputata (Group, DD/MM/YYYY) ... «quote»

    Each citation dict contains:
      speaker_name, role_text, group_raw, group_canonical, date, quote,
      chunk_id, verbatim_verified, speaker_id, deputy_first_name, deputy_last_name
    """
    citations: List[dict] = []
    covered: List[Tuple[int, int]] = []

    def _overlaps(span: Tuple[int, int]) -> bool:
        return any(span[0] < s[1] and s[0] < span[1] for s in covered)

    def _make(speaker_name, role_text, group_raw, date_raw, quote_raw) -> dict:
        return {
            "speaker_name": speaker_name,
            "role_text": role_text,
            "group_raw": group_raw.strip(),
            "group_canonical": _canonical_party(group_raw),
            "date": date_raw.strip(),
            "quote": quote_raw.strip(),
            "chunk_id": None,
            "verbatim_verified": False,
            "speaker_id": None,
            "deputy_first_name": None,
            "deputy_last_name": None,
        }

    # Pass 1: name-based citations (capitalised surnames / full names)
    for m in _CITATION_RE.finditer(baseline_answer):
        name_raw, group_raw, date_raw, quote_raw = m.groups()
        name_clean = re.sub(r'\*+', '', name_raw).strip()
        last_word = re.sub(r"['\-]", " ", name_clean.lower()).split()[-1]
        is_role = last_word in _ROLE_TOKENS
        covered.append(m.span())
        citations.append(_make(
            speaker_name=None if is_role else name_clean,
            role_text=name_clean if is_role else None,
            group_raw=group_raw,
            date_raw=date_raw,
            quote_raw=quote_raw,
        ))

    # Pass 2: role-based citations not already captured
    for m in _CITATION_ROLE_RE.finditer(baseline_answer):
        if _overlaps(m.span()):
            continue
        role_raw, group_raw, date_raw, quote_raw = m.groups()
        covered.append(m.span())
        citations.append(_make(
            speaker_name=None,
            role_text=role_raw.strip(),
            group_raw=group_raw,
            date_raw=date_raw,
            quote_raw=quote_raw,
        ))

    return citations


# ── Neo4j helpers ─────────────────────────────────────────────────────────────

def _fetch_speaker_profiles(
    client: Neo4jClient, speaker_ids: List[str]
) -> Dict[str, dict]:
    """
    Batch-fetch profile data for a list of deputy IDs.
    Returns {speaker_id: {profession, education, camera_profile_url, photo, committee}}.
    """
    if not speaker_ids:
        return {}

    results = client.query(
        """
        UNWIND $ids AS sid
        MATCH (d:Deputy {id: sid})
        OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMMITTEE]->(c:Committee)
        WHERE mc.end_date IS NULL OR mc.end_date >= date()
        WITH d, collect(c.name)[0] AS current_committee
        RETURN d.id            AS id,
               d.profession    AS profession,
               d.education     AS education,
               d.deputy_card   AS camera_profile_url,
               d.photo         AS photo,
               current_committee
        """,
        {"ids": speaker_ids},
    )
    return {
        r["id"]: {
            "profession": r.get("profession"),
            "education": r.get("education"),
            "camera_profile_url": r.get("camera_profile_url"),
            "photo": r.get("photo"),
            "committee": r.get("current_committee"),
        }
        for r in results
    }


def _find_chunks_for_speaker_date(
    client: Neo4jClient, last_name: str, date_iso: str
) -> List[dict]:
    """Return all chunks from the speaker's speeches on the given session date.

    Handles compound surnames like "Del Barba" by matching either the full
    last_name token or the last word of speaker.last_name (e.g. "Barba" matches
    "DEL BARBA" via split()[-1]).
    """
    last_token = last_name.split()[-1]
    results = client.query(
        """
        MATCH (c:Chunk)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(speaker)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)
              <-[:HAS_DEBATE]-(s:Session)
        WHERE (toLower(speaker.last_name) = toLower($last_name)
               OR toLower(split(speaker.last_name, ' ')[-1]) = toLower($last_name))
          AND s.date = date($date_iso)
        RETURN c.id AS chunk_id, c.text AS chunk_text
        """,
        {"last_name": last_token, "date_iso": date_iso},
    )
    return [{"chunk_id": r["chunk_id"], "chunk_text": r["chunk_text"]} for r in results]


def _find_chunks_for_date(client: Neo4jClient, date_iso: str) -> List[dict]:
    """Return all chunks from any speech on the given session date (role-citation fallback)."""
    results = client.query(
        """
        MATCH (c:Chunk)<-[:HAS_CHUNK]-(i:Speech)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)
              <-[:HAS_DEBATE]-(s:Session)
        WHERE s.date = date($date_iso)
        RETURN c.id AS chunk_id, c.text AS chunk_text
        LIMIT 600
        """,
        {"date_iso": date_iso},
    )
    return [{"chunk_id": r["chunk_id"], "chunk_text": r["chunk_text"]} for r in results]


def _verify_citation(client: Neo4jClient, cit: dict) -> dict:
    """
    Verify a citation's quote against source chunks in Neo4j.
    Sets cit["chunk_id"] and cit["verbatim_verified"] in-place and returns the dict.
    """
    date_iso = _date_to_iso(cit["date"])
    if not date_iso:
        return cit

    if cit["speaker_name"] is None:
        chunks = _find_chunks_for_date(client, date_iso)
    else:
        chunks = _find_chunks_for_speaker_date(client, cit["speaker_name"], date_iso)

    if not chunks:
        return cit

    norm_quote = _normalize(cit["quote"])
    for chunk in chunks:
        norm_chunk = _normalize(chunk["chunk_text"] or "")
        if norm_quote == norm_chunk or norm_quote in norm_chunk or norm_chunk in norm_quote:
            cit["chunk_id"] = chunk["chunk_id"]
            cit["verbatim_verified"] = True
            return cit

    # Record the first candidate chunk for inspection even when quote doesn't match verbatim
    cit["chunk_id"] = chunks[0]["chunk_id"]
    return cit


def _find_speaker_by_name_date(
    client: Neo4jClient, speaker_name: str, date_iso: str
) -> Optional[dict]:
    """
    Look up a speaker's Neo4j ID by surname (+ optional date).

    Strategy:
      1. Match speaker whose speech appears on the given date with matching last_name.
         Uses the last token of the name to handle compound surnames (e.g. "Della Vedova").
      2. Fallback: match any Deputy by last name alone (ignores date).

    Returns {id, first_name, last_name} or None.
    """
    last_token = speaker_name.split()[-1]

    # Primary: look for a speech on the citation date
    results = client.query(
        """
        MATCH (i:Speech)-[:SPOKEN_BY]->(speaker)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(d:Debate)
              <-[:HAS_DEBATE]-(s:Session)
        WHERE toLower(speaker.last_name) = toLower($last_token)
          AND s.date = date($date_iso)
        RETURN DISTINCT
               speaker.id        AS id,
               speaker.first_name AS first_name,
               speaker.last_name  AS last_name
        LIMIT 1
        """,
        {"last_token": last_token, "date_iso": date_iso},
    )
    if results:
        r = results[0]
        return {"id": r["id"], "first_name": r["first_name"], "last_name": r["last_name"]}

    # Fallback: Deputy node by last name (no date constraint)
    results = client.query(
        """
        MATCH (d:Deputy)
        WHERE toLower(d.last_name) = toLower($last_token)
           OR (size(split(d.last_name, ' ')) > 1
               AND toLower(split(d.last_name, ' ')[-1]) = toLower($last_token))
        RETURN d.id AS id, d.first_name AS first_name, d.last_name AS last_name
        LIMIT 1
        """,
        {"last_token": last_token},
    )
    if results:
        r = results[0]
        return {"id": r["id"], "first_name": r["first_name"], "last_name": r["last_name"]}

    return None


def _enrich_citations_with_speaker_ids(
    client: Neo4jClient, citations: List[dict]
) -> List[dict]:
    """
    For each name-based citation, look up the speaker_id in Neo4j and add it
    to the citation dict (deputy_first_name, deputy_last_name, speaker_id).

    Results are cached by (normalised_name, date_iso) to avoid redundant DB calls.
    """
    cache: Dict[Tuple[str, str], Optional[dict]] = {}

    for cit in citations:
        name = cit.get("speaker_name")
        if not name:
            continue
        date_iso = _date_to_iso(cit["date"]) or ""
        key = (name.lower(), date_iso)
        if key not in cache:
            cache[key] = _find_speaker_by_name_date(client, name, date_iso)
        speaker = cache[key]
        if speaker:
            cit["speaker_id"] = speaker["id"]
            cit["deputy_first_name"] = speaker["first_name"]
            cit["deputy_last_name"] = speaker["last_name"]
        else:
            logger.debug(f"  Speaker not found in Neo4j: {name!r} on {date_iso}")

    return citations


# ── Authority scoring ─────────────────────────────────────────────────────────

def _compute_experts_for_topic(
    citations: List[dict],
    query_embedding: List[float],
    authority_scorer: AuthorityScorer,
    coalition_logic: CoalitionLogic,
    client: Neo4jClient,
) -> List[dict]:
    """
    Compute baseline_experts for one topic.

    For each canonical party present in citations:
      1. Collect all deputies cited from that party who have a resolved speaker_id.
      2. Compute their authority scores in a single batch call.
      3. Pick the top expert (highest authority_score) per party.

    Government citations (group_canonical=None) are automatically excluded
    because they don't map to any canonical party.

    Returns a list of expert dicts sorted by authority_score descending.
    Each dict mirrors the format used in ChatHistory.experts by the system pipeline.
    """
    # Build: party → {speaker_id → {first_name, last_name, count}}
    party_speakers: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for cit in citations:
        group = cit.get("group_canonical")
        speaker_id = cit.get("speaker_id")
        if not group or not speaker_id:
            continue
        if group not in party_speakers:
            party_speakers[group] = {}
        if speaker_id not in party_speakers[group]:
            party_speakers[group][speaker_id] = {
                "first_name": cit.get("deputy_first_name") or "",
                "last_name": cit.get("deputy_last_name") or "",
                "count": 0,
            }
        party_speakers[group][speaker_id]["count"] += 1

    if not party_speakers:
        logger.warning("  No cited deputies with resolved speaker_id found.")
        return []

    # Batch authority computation for all unique speakers
    all_speaker_ids = list({sid for sids in party_speakers.values() for sid in sids})
    logger.info(f"  Computing authority for {len(all_speaker_ids)} speaker(s)…")
    authority_all = authority_scorer.compute_all_authority(all_speaker_ids, query_embedding)

    # Batch profile fetch (photo, profession, education, committee, camera_profile_url)
    profiles = _fetch_speaker_profiles(client, all_speaker_ids)

    # Pick the top-authority expert per party
    experts: List[dict] = []
    for group, speakers in party_speakers.items():
        best_sid = max(
            speakers,
            key=lambda sid: authority_all.get(sid, {}).get("total_score", 0.0),
        )
        auth = authority_all.get(best_sid, {})
        score = round(auth.get("total_score", 0.0), 6)
        components = {k: round(v, 6) for k, v in auth.get("components", {}).items()}
        institutional_role = auth.get("institutional_role")
        coalition = coalition_logic.get_coalition(group)
        fn = speakers[best_sid]["first_name"] or ""
        ln = speakers[best_sid]["last_name"] or ""
        profile = profiles.get(best_sid, {})

        # score_breakdown maps component names to the Expert.score_breakdown schema
        # expected by ExpertModal: speeches / acts / committee / profession / education / role
        score_breakdown = {
            "speeches":   round(components.get("interventions", 0.0), 2),
            "acts":       round(components.get("acts", 0.0), 2),
            "committee":  round(components.get("committee", 0.0), 2),
            "profession": round(components.get("profession", 0.0), 2),
            "education":  round(components.get("education", 0.0), 2),
            "role":       round(components.get("role", 0.0), 2),
        }

        experts.append({
            "id": best_sid,
            "first_name": fn,
            "last_name": ln,
            "group": group,
            "coalition": coalition,
            "authority_score": score,
            "components": components,
            "score_breakdown": score_breakdown,
            "institutional_role": institutional_role,
            "profession": profile.get("profession"),
            "education": profile.get("education"),
            "committee": profile.get("committee"),
            "camera_profile_url": profile.get("camera_profile_url"),
            "photo": profile.get("photo"),
            "relevant_speeches_count": speakers[best_sid]["count"],
            "intervention_count": speakers[best_sid]["count"],
        })

    experts.sort(key=lambda e: e["authority_score"], reverse=True)
    return experts


# ── Per-topic orchestration ───────────────────────────────────────────────────

def process_topic(
    client: Neo4jClient,
    authority_scorer: AuthorityScorer,
    coalition_logic: CoalitionLogic,
    retrieval: RetrievalEngine,
    topic: str,
    baseline_answer: str,
) -> dict:
    """
    Run the full computation pipeline for one topic.

    Returns an enriched entry dict containing:
      baseline_answer, baseline_experts, baseline_metrics
    """
    logger.info(f"\n{'─'*60}")
    logger.info(f"Topic: {topic}")
    logger.info(f"{'─'*60}")

    # ── Step 1: parse inline citations ──────────────────────────────────────
    citations = _parse_citations(baseline_answer)
    logger.info(f"  Parsed {len(citations)} citation(s)")

    # ── Step 2: verbatim verification against Neo4j ──────────────────────────
    for cit in citations:
        cit = _verify_citation(client, cit)
        status = "✓" if cit["verbatim_verified"] else "✗"
        label = cit["speaker_name"] or cit.get("role_text", "?")
        logger.info(
            f"  {status} {label!r:30s} ({cit['group_raw']}, {cit['date']})  "
            f"chunk={cit['chunk_id']}"
        )

    # ── Step 3: resolve speaker IDs ──────────────────────────────────────────
    citations = _enrich_citations_with_speaker_ids(client, citations)
    resolved = sum(1 for c in citations if c.get("speaker_id"))
    logger.info(f"  Speaker IDs resolved: {resolved}/{len(citations)}")

    # ── Step 4: citation-based metrics ───────────────────────────────────────
    unique_groups_cited = {
        c["group_canonical"]
        for c in citations
        if c["group_canonical"] is not None
    }
    total_citations = len(citations)
    verified_count = sum(1 for c in citations if c["verbatim_verified"])
    baseline_party_coverage = round(min(len(unique_groups_cited) / ALL_PARTIES, 1.0), 4)
    baseline_citation_fidelity = (
        round(verified_count / total_citations, 4) if total_citations > 0 else 0.0
    )

    # ── Step 5: text-based response completeness ─────────────────────────────
    parties_in_text = _count_parties_in_text(baseline_answer)
    baseline_response_completeness = round(min(parties_in_text / ALL_PARTIES, 1.0), 4)

    logger.info(
        f"  party_coverage={baseline_party_coverage} ({len(unique_groups_cited)}/{ALL_PARTIES})"
        f"  citation_fidelity={baseline_citation_fidelity} ({verified_count}/{total_citations})"
        f"  response_completeness={baseline_response_completeness} ({parties_in_text}/{ALL_PARTIES})"
    )

    # ── Step 6: embed topic query ─────────────────────────────────────────────
    logger.info(f"  Embedding topic query: {topic[:60]}…")
    query_embedding = retrieval.embed_query(topic)

    # ── Step 7: compute experts with query-specific authority scores ──────────
    baseline_experts = _compute_experts_for_topic(
        citations, query_embedding, authority_scorer, coalition_logic, client
    )

    if baseline_experts:
        logger.info(f"  {len(baseline_experts)} baseline expert(s):")
        for e in baseline_experts:
            logger.info(
                f"    [{e['group'][:35]:35s}]  "
                f"{e['first_name']} {e['last_name']:20s}  "
                f"auth={e['authority_score']:.4f}"
            )
    else:
        logger.warning("  No baseline experts computed (no speaker IDs could be resolved).")

    # ── Assemble result ───────────────────────────────────────────────────────
    return {
        "baseline_answer": baseline_answer,
        "baseline_experts": baseline_experts,
        "baseline_metrics": {
            "baseline_party_coverage": baseline_party_coverage,
            "baseline_citation_fidelity": baseline_citation_fidelity,
            "baseline_response_completeness": baseline_response_completeness,
            "parties_cited": sorted(unique_groups_cited),
            "citations_total": total_citations,
            "citations_verified": verified_count,
            "citations": [
                {
                    "speaker": c["speaker_name"] or c.get("role_text"),
                    "group": c["group_raw"],
                    "group_canonical": c["group_canonical"],
                    "date": c["date"],
                    "quote": c["quote"],
                    "chunk_id": c["chunk_id"],
                    "verbatim_verified": c["verbatim_verified"],
                    "speaker_id": c.get("speaker_id"),
                    "deputy_first_name": c.get("deputy_first_name"),
                    "deputy_last_name": c.get("deputy_last_name"),
                }
                for c in citations
            ],
        },
    }


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    dry_run = "--dry-run" in sys.argv

    topic_filter: Optional[str] = None
    if "--topic" in sys.argv:
        idx = sys.argv.index("--topic")
        if idx + 1 < len(sys.argv):
            topic_filter = sys.argv[idx + 1]

    logger.info(f"Loading evaluation set from {EVAL_SET_PATH}")
    with open(EVAL_SET_PATH, encoding="utf-8") as f:
        data: dict = json.load(f)

    settings = get_settings()
    logger.info(f"Connecting to Neo4j at {settings.neo4j_uri}")
    client = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)

    authority_scorer = AuthorityScorer(client)
    coalition_logic = CoalitionLogic()
    retrieval = RetrievalEngine(client)

    enriched: dict = {}
    for topic, entry in data.items():
        # Apply optional single-topic filter (for smoke-testing)
        if topic_filter and topic_filter.lower() not in topic.lower():
            enriched[topic] = entry
            continue

        # Normalise old-format entries (plain string → dict)
        baseline_answer: str
        if isinstance(entry, str):
            baseline_answer = entry
        elif isinstance(entry, dict):
            baseline_answer = entry.get("baseline_answer", "")
        else:
            logger.warning(f"[{topic}] Unexpected entry type {type(entry)}, skipping.")
            enriched[topic] = entry
            continue

        if not baseline_answer:
            logger.warning(f"[{topic}] Empty baseline_answer, skipping.")
            enriched[topic] = entry if isinstance(entry, dict) else {"baseline_answer": ""}
            continue

        try:
            enriched[topic] = process_topic(
                client, authority_scorer, coalition_logic, retrieval, topic, baseline_answer
            )
        except Exception as exc:
            logger.error(f"[{topic}] Processing failed: {exc}", exc_info=True)
            # Keep existing data on failure rather than losing it
            enriched[topic] = (
                entry if isinstance(entry, dict) else {"baseline_answer": baseline_answer}
            )

    if dry_run:
        logger.info("\n── DRY-RUN SUMMARY (not writing to disk) ──")
        for topic, entry in enriched.items():
            if not isinstance(entry, dict):
                continue
            experts = entry.get("baseline_experts", [])
            m = entry.get("baseline_metrics", {})
            print(f"\n{topic}")
            print(
                f"  party_coverage={m.get('baseline_party_coverage')}  "
                f"citation_fidelity={m.get('baseline_citation_fidelity')}  "
                f"completeness={m.get('baseline_response_completeness')}"
            )
            print(f"  experts ({len(experts)}): " + ", ".join(
                f"{e['first_name']} {e['last_name']} [{e['group'][:20]}] {e['authority_score']:.4f}"
                for e in experts
            ))
        return

    with open(EVAL_SET_PATH, "w", encoding="utf-8") as f:
        json.dump(enriched, f, indent=2, ensure_ascii=False)

    logger.info(f"\nSaved enriched evaluation_set to {EVAL_SET_PATH}")

    # Print summary table
    logger.info("\n── SUMMARY ──")
    logger.info(f"{'Topic':<45} {'#Experts':>8} {'Coverage':>8} {'Fidelity':>9} {'Complet.':>9}")
    logger.info("─" * 80)
    for topic, entry in enriched.items():
        if not isinstance(entry, dict):
            continue
        m = entry.get("baseline_metrics", {})
        n_experts = len(entry.get("baseline_experts", []))
        print(
            f"{topic[:44]:<45} {n_experts:>8} "
            f"{m.get('baseline_party_coverage', 0):>8.2%} "
            f"{m.get('baseline_citation_fidelity', 0):>9.2%} "
            f"{m.get('baseline_response_completeness', 0):>9.2%}"
        )


if __name__ == "__main__":
    main()
