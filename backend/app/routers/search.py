"""
Search endpoint for parliamentary records.
Supports text search and semantic (vector) search across Speech chunks and ParliamentaryAct nodes.
"""
import logging
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, Query, HTTPException

from ..services.archive import fill_rows, get_archive
from ..services.retrieval.scope import CURRENT_LEGISLATURE, loaded_chambers
from ..services.neo4j_client import Neo4jClient
from ..config import get_settings
from ..key_pool import make_client

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/search", tags=["Search"])

_neo4j_client: Optional[Neo4jClient] = None
_openai_client = None
_act_index_ensured = False


def get_client() -> Neo4jClient:
    """Get or initialize Neo4j client."""
    global _neo4j_client
    if _neo4j_client is None:
        settings = get_settings()
        _neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password
        )
    return _neo4j_client


def _get_openai_client():
    """Get or initialize OpenAI client for embeddings."""
    global _openai_client
    if _openai_client is None:
        _openai_client = make_client()
    return _openai_client


def _generate_embedding(text: str) -> List[float]:
    """Generate embedding for a query using OpenAI."""
    client = _get_openai_client()
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding


def _ensure_act_vector_index():
    """Create vector index on ParliamentaryAct.description_embedding if not exists."""
    global _act_index_ensured
    if _act_index_ensured:
        return
    client = get_client()
    try:
        with client.session() as session:
            session.run("""
                CREATE VECTOR INDEX act_description_embedding_index IF NOT EXISTS
                FOR (a:ParliamentaryAct) ON (a.description_embedding)
                OPTIONS {indexConfig: {
                    `vector.dimensions`: 1536,
                    `vector.similarity_function`: 'cosine'
                }}
            """)
        _act_index_ensured = True
        logger.info("Ensured act_description_embedding_index exists")
    except Exception as e:
        logger.warning(f"Could not create act vector index: {e}")
        _act_index_ensured = True  # Don't retry on failure


SENATE_ACT = "(a.uri STARTS WITH 'http://dati.senato.it/' OR a.uri STARTS WITH 'senato:')"
SPEECH_CHAMBER = "coalesce(s.chamber, 'camera') IN $chambers"


def _resolve_chambers(chamber: Optional[str]) -> tuple:
    """Chambers a search covers: Camera by default (the Camera pages and
    older clients), one chamber, or every loaded chamber for "both"."""
    if chamber in (None, "", "camera"):
        return ("camera",)
    if chamber == "senato":
        return ("senato",)
    return loaded_chambers()


def _act_clause(chambers: tuple) -> str:
    if set(chambers) == {"camera"}:
        return f"NOT {SENATE_ACT}"
    if set(chambers) == {"senato"}:
        return SENATE_ACT
    return "true"


def _graph_chambers(chambers: tuple) -> List[str]:
    """Chambers whose speech text and vectors are in the graph; the others
    are searched in the text archive."""
    archive = get_archive()
    return [c for c in chambers
            if not (archive and archive.covers((c, CURRENT_LEGISLATURE)))]


_ARCHIVE_HITS = """
UNWIND $hits AS hit
MATCH (c:Chunk {{id: hit.id}})<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(d)
WHERE (d:Deputy OR d:GovernmentMember)
MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(dib:Debate)<-[:HAS_DEBATE]-(s:Session)
OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= s.date)
  AND coalesce(mg.chamber, s.chamber, 'camera') = coalesce(s.chamber, 'camera')
WITH c, i, d, s, dib, g, hit.similarity AS score, hit.rank AS rank
WHERE true {group_filter}
RETURN c.id AS chunk_id, coalesce(s.chamber, 'camera') AS chamber, c.text AS text,
       i.id AS speech_id, toString(s.date) AS date, s.number AS session_number,
       dib.title AS debate_title, d.first_name AS first_name, d.last_name AS last_name,
       CASE WHEN 'GovernmentMember' IN labels(d) THEN 'Governo'
            ELSE coalesce(g.name, 'MISTO') END AS group_name,
       score
ORDER BY rank
"""


def _search_speeches_archive(
    client: Neo4jClient,
    chambers: tuple,
    limit: int,
    q: Optional[str] = None,
    embedding: Optional[List[float]] = None,
    threshold: float = 0.5,
    deputy_id: Optional[str] = None,
    group: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Speech search for the chambers whose text is in the archive (the
    Senate): keyword or vector hits from Postgres, speaker, group and sitting
    from the graph. Empty when the archive covers none of the chambers."""
    archive = get_archive()
    if archive is None:
        return []
    pairs = [(c, CURRENT_LEGISLATURE) for c in chambers
             if archive.covers((c, CURRENT_LEGISLATURE))]
    records: List[Dict[str, Any]] = []
    for pair in pairs:
        if embedding is not None:
            # The vector search has no speaker or group filter: take a wider
            # pool when the graph side will filter it.
            k = limit * 4 if (deputy_id or group) else limit
            hits = archive.search(embedding, pair, k, threshold, start_date, end_date)
            match_type = "semantic"
        else:
            hits = archive.text_search(q or "", pair, limit, speaker_id=deputy_id,
                                       date_start=start_date, date_end=end_date)
            match_type = "text"
        for rank, h in enumerate(hits):
            h["rank"] = rank
        params: Dict[str, Any] = {"hits": hits}
        group_filter = ""
        if group:
            group_filter += " AND g.name IN $groups"
            params["groups"] = group
        if deputy_id:
            group_filter += " AND d.id = $deputy_id"
            params["deputy_id"] = deputy_id
        rows = client.query(_ARCHIVE_HITS.format(group_filter=group_filter), params)
        fill_rows(rows, chunk_fields={"chunk_id": {"text": "text"}})
        for r in rows[:limit]:
            records.append({
                "type": "speech",
                "id": r["chunk_id"],
                "chamber": r["chamber"],
                "text": r["text"][:500] if r.get("text") else "",
                "date": r["date"],
                "session_number": r["session_number"],
                "debate_title": r["debate_title"] or "",
                "first_name": r["first_name"] or "",
                "last_name": r["last_name"] or "",
                "group": r["group_name"] or "MISTO",
                "act_type": None,
                "act_title": None,
                "act_number": None,
                "destinatario": None,
                "eurovoc": None,
                "score": round(r["score"], 4) if r.get("score") is not None else None,
                "match_type": match_type,
                "is_exact": match_type == "text",
            })
    return records


def _search_speeches_text(
    client: Neo4jClient,
    q: str,
    limit: int,
    deputy_id: Optional[str] = None,
    group: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    chambers: tuple = ("camera",),
) -> List[Dict[str, Any]]:
    """Text search on Speech chunks; with an empty query it lists the
    author's speeches (first chunk only, or every chunk would be a row)."""
    records = _search_speeches_archive(client, chambers, limit, q=q, deputy_id=deputy_id,
                                       group=group, start_date=start_date, end_date=end_date)
    graph_chambers = _graph_chambers(chambers)
    if not graph_chambers:
        return records
    where_clauses = []
    params: Dict[str, Any] = {"limit": limit}
    if q:
        where_clauses.append("toLower(c.text) CONTAINS toLower($search_text)")
        params["search_text"] = q
    else:
        where_clauses.append("c.index = 0")

    if deputy_id:
        where_clauses.append("d.id = $deputy_id")
        params["deputy_id"] = deputy_id
    if group:
        where_clauses.append("g.name IN $groups")
        params["groups"] = group
    if start_date:
        where_clauses.append("s.date >= date($start_date)")
        params["start_date"] = start_date
    if end_date:
        where_clauses.append("s.date <= date($end_date)")
        params["end_date"] = end_date

    where_clauses.append(SPEECH_CHAMBER)
    params["chambers"] = graph_chambers
    where_clause = " AND ".join(where_clauses)

    cypher = f"""
    MATCH (c:Chunk)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(d)
    WHERE (d:Deputy OR d:GovernmentMember)
    MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(dib:Debate)<-[:HAS_DEBATE]-(s:Session)
    OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
    WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= s.date)
      AND coalesce(mg.chamber, s.chamber, 'camera') = coalesce(s.chamber, 'camera')
    WITH c, i, d, s, dib, g
    WHERE {where_clause}
    RETURN c.id AS chunk_id,
           coalesce(s.chamber, 'camera') AS chamber,
           c.text AS text,
           i.id AS speech_id,
           toString(s.date) AS date,
           s.number AS session_number,
           dib.title AS debate_title,
           d.first_name AS first_name,
           d.last_name AS last_name,
           CASE WHEN 'GovernmentMember' IN labels(d) THEN 'Governo' ELSE coalesce(g.name, 'MISTO') END AS group_name
    ORDER BY s.date DESC
    LIMIT $limit
    """

    with client.session() as session:
        result = session.run(cypher, **params).data()
        for record in result:
            records.append({
                "type": "speech",
                "id": record["chunk_id"],
                "chamber": record["chamber"],
                "text": record["text"][:500] if record["text"] else "",
                "date": record["date"],
                "session_number": record["session_number"],
                "debate_title": record["debate_title"] or "",
                "first_name": record["first_name"] or "",
                "last_name": record["last_name"] or "",
                "group": record["group_name"] or "MISTO",
                "act_type": None,
                "act_title": None,
                "act_number": None,
                "destinatario": None,
                "eurovoc": None,
                "score": None,
                "match_type": "text",
                "is_exact": True,
            })
        return records


def _search_acts_text(
    client: Neo4jClient,
    q: str,
    limit: int,
    deputy_id: Optional[str] = None,
    group: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    chambers: tuple = ("camera",),
) -> List[Dict[str, Any]]:
    """Text search on ParliamentaryAct title and description; with an
    empty query it lists the author's acts."""
    where_clauses = [_act_clause(chambers)]
    params: Dict[str, Any] = {"limit": limit}
    if q:
        where_clauses.append(
            "(toLower(a.title) CONTAINS toLower($search_text) OR toLower(a.description) CONTAINS toLower($search_text))"
        )
        params["search_text"] = q

    if deputy_id:
        where_clauses.append("d.id = $deputy_id")
        params["deputy_id"] = deputy_id

    # presentation_date: date nativa (v2) o 'YYYYMMDD' string (v1) — normalizza
    if start_date:
        where_clauses.append(
            "replace(toString(a.presentation_date), '-', '') >= $start_date_act")
        params["start_date_act"] = start_date.replace("-", "")
    if end_date:
        where_clauses.append(
            "replace(toString(a.presentation_date), '-', '') <= $end_date_act")
        params["end_date_act"] = end_date.replace("-", "")

    # Browse mode with a group-only filter leaves no act-level clause
    where_clause = " AND ".join(where_clauses) if where_clauses else "true"

    # Group filter handled separately since it's on the signatory's group
    group_filter = ""
    if group:
        group_filter = "WHERE g.name IN $groups"
        params["groups"] = group

    cypher = f"""
    MATCH (d)-[:PRIMARY_SIGNATORY]->(a:ParliamentaryAct)
    WHERE (d:Deputy OR d:GovernmentMember)
    AND {where_clause}
    OPTIONAL MATCH (d)-[:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
    {group_filter}
    OPTIONAL MATCH (a)-[:HAS_SUBJECT]->(ev:EurovocConcept)
    WITH a, d, g, collect(ev.label_it) AS eurovoc_labels
    RETURN a.uri AS act_uri,
           a.type AS act_type,
           a.title AS act_title,
           a.description AS description,
           toString(a.presentation_date) AS date_raw,
           a.number AS act_number,
           a.recipient AS destinatario,
           coalesce(a.eurovoc, reduce(s = '', l IN eurovoc_labels |
               CASE WHEN s = '' THEN l ELSE s + '; ' + l END)) AS eurovoc,
           d.first_name AS first_name,
           d.last_name AS last_name,
           coalesce(g.name, 'MISTO') AS group_name
    ORDER BY date_raw DESC
    LIMIT $limit
    """

    with client.session() as session:
        result = session.run(cypher, **params)
        records = []
        for record in result:
            # v1: 'YYYYMMDD' → reformat; v2: toString(date) is already ISO
            date_raw = record["date_raw"] or ""
            if len(date_raw) == 8 and date_raw.isdigit():
                formatted_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
            else:
                formatted_date = date_raw

            records.append({
                "type": "act",
                "id": record["act_uri"] or "",
                "text": (record["description"] or "")[:500],
                "date": formatted_date,
                "session_number": None,
                "debate_title": None,
                "first_name": record["first_name"] or "",
                "last_name": record["last_name"] or "",
                "group": record["group_name"] or "MISTO",
                "act_type": record["act_type"] or "",
                "act_title": record["act_title"] or "",
                "act_number": record["act_number"] or "",
                "destinatario": record["destinatario"] or "",
                "eurovoc": record["eurovoc"] or "",
                "score": None,
                "match_type": "text",
                "is_exact": True,
            })
        return records


def _search_speeches_semantic(
    client: Neo4jClient,
    embedding: List[float],
    limit: int,
    threshold: float = 0.5,
    deputy_id: Optional[str] = None,
    group: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    chambers: tuple = ("camera",),
) -> List[Dict[str, Any]]:
    """Semantic search on Speech chunks using vector index."""
    archived = _search_speeches_archive(client, chambers, limit, embedding=embedding,
                                        threshold=threshold, deputy_id=deputy_id, group=group,
                                        start_date=start_date, end_date=end_date)
    graph_chambers = _graph_chambers(chambers)
    if not graph_chambers:
        return archived
    extra_where = [SPEECH_CHAMBER]
    params: Dict[str, Any] = {
        "top_k": limit * 2,
        "embedding": embedding,
        "threshold": threshold,
        "limit": limit,
        "chambers": graph_chambers,
    }

    if deputy_id:
        extra_where.append("d.id = $deputy_id")
        params["deputy_id"] = deputy_id
    if group:
        extra_where.append("g.name IN $groups")
        params["groups"] = group
    if start_date:
        extra_where.append("s.date >= date($start_date)")
        params["start_date"] = start_date
    if end_date:
        extra_where.append("s.date <= date($end_date)")
        params["end_date"] = end_date

    filter_clause = ("AND " + " AND ".join(extra_where)) if extra_where else ""

    cypher = f"""
    CALL db.index.vector.queryNodes('chunk_embedding_index', $top_k, $embedding)
    YIELD node AS c, score
    WHERE score >= $threshold
    MATCH (c)<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(d)
    WHERE (d:Deputy OR d:GovernmentMember)
    MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(dib:Debate)<-[:HAS_DEBATE]-(s:Session)
    OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
    WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= s.date)
    WITH c, i, d, s, dib, g, score
    WHERE true {filter_clause}
    RETURN c.id AS chunk_id,
           coalesce(s.chamber, 'camera') AS chamber,
           c.text AS text,
           i.id AS speech_id,
           toString(s.date) AS date,
           s.number AS session_number,
           dib.title AS debate_title,
           d.first_name AS first_name,
           d.last_name AS last_name,
           CASE WHEN 'GovernmentMember' IN labels(d) THEN 'Governo' ELSE coalesce(g.name, 'MISTO') END AS group_name,
           score
    ORDER BY score DESC
    LIMIT $limit
    """

    results = client.query(cypher, params)

    records = archived
    for r in results:
        records.append({
            "type": "speech",
            "id": r["chunk_id"],
            "chamber": r["chamber"],
            "text": r["text"][:500] if r.get("text") else "",
            "date": r["date"],
            "session_number": r["session_number"],
            "debate_title": r["debate_title"] or "",
            "first_name": r["first_name"] or "",
            "last_name": r["last_name"] or "",
            "group": r["group_name"] or "MISTO",
            "act_type": None,
            "act_title": None,
            "act_number": None,
            "destinatario": None,
            "eurovoc": None,
            "score": round(r["score"], 4),
            "match_type": "semantic",
            "is_exact": False,
        })
    return records


def _search_acts_semantic(
    client: Neo4jClient,
    embedding: List[float],
    limit: int,
    threshold: float = 0.5,
    deputy_id: Optional[str] = None,
    group: Optional[List[str]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    chambers: tuple = ("camera",),
) -> List[Dict[str, Any]]:
    """Semantic search on ParliamentaryAct using vector index."""
    _ensure_act_vector_index()

    extra_where = []
    params: Dict[str, Any] = {
        "top_k": limit * 2,
        "embedding": embedding,
        "threshold": threshold,
        "limit": limit,
    }

    if deputy_id:
        extra_where.append("d.id = $deputy_id")
        params["deputy_id"] = deputy_id
    if group:
        extra_where.append("g.name IN $groups")
        params["groups"] = group
    # presentation_date: date nativa nel DB v2, stringa 'YYYYMMDD' nel v1.
    # replace(toString(...)) normalizza entrambe a 'YYYYMMDD' per il confronto.
    if start_date:
        extra_where.append(
            "replace(toString(a.presentation_date), '-', '') >= $start_date_act")
        params["start_date_act"] = start_date.replace("-", "")
    if end_date:
        extra_where.append(
            "replace(toString(a.presentation_date), '-', '') <= $end_date_act")
        params["end_date_act"] = end_date.replace("-", "")

    # When filtering by deputy/group, use MATCH instead of OPTIONAL MATCH
    if deputy_id or group:
        signatory_match = "MATCH (d)-[:PRIMARY_SIGNATORY]->(a)\n    WHERE (d:Deputy OR d:GovernmentMember)"
    else:
        signatory_match = "OPTIONAL MATCH (d)-[:PRIMARY_SIGNATORY]->(a)\n    WHERE (d:Deputy OR d:GovernmentMember)"

    if group:
        group_match = "MATCH (d)-[:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)"
    else:
        group_match = "OPTIONAL MATCH (d)-[:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)"

    filter_clause = ("WHERE " + " AND ".join(extra_where)) if extra_where else ""

    cypher = f"""
    CALL db.index.vector.queryNodes('act_description_embedding_index', $top_k, $embedding)
    YIELD node AS a, score
    WHERE score >= $threshold AND {_act_clause(chambers)}
    {signatory_match}
    {group_match}
    WITH a, d, g, score
    {filter_clause}
    OPTIONAL MATCH (a)-[:HAS_SUBJECT]->(ev:EurovocConcept)
    WITH a, d, g, score, collect(ev.label_it) AS eurovoc_labels
    RETURN a.uri AS act_uri,
           a.type AS act_type,
           a.title AS act_title,
           a.description AS description,
           toString(a.presentation_date) AS date_raw,
           a.number AS act_number,
           a.recipient AS destinatario,
           // v1: stringa appiattita sull'atto; v2: nodi EurovocConcept
           coalesce(a.eurovoc, reduce(s = '', l IN eurovoc_labels |
               CASE WHEN s = '' THEN l ELSE s + '; ' + l END)) AS eurovoc,
           d.first_name AS first_name,
           d.last_name AS last_name,
           coalesce(g.name, 'MISTO') AS group_name,
           score
    ORDER BY score DESC
    LIMIT $limit
    """

    results = client.query(cypher, params)

    records = []
    for r in results:
        date_raw = r.get("date_raw") or ""
        # v1: 'YYYYMMDD' string → reformat; v2: native date → toString is already ISO
        if len(date_raw) == 8 and date_raw.isdigit():
            formatted_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
        else:
            formatted_date = date_raw

        records.append({
            "type": "act",
            "id": r["act_uri"] or "",
            "text": (r.get("description") or "")[:500],
            "date": formatted_date,
            "session_number": None,
            "debate_title": None,
            "first_name": r.get("first_name") or "",
            "last_name": r.get("last_name") or "",
            "group": r.get("group_name") or "MISTO",
            "act_type": r.get("act_type") or "",
            "act_title": r.get("act_title") or "",
            "act_number": r.get("act_number") or "",
            "destinatario": r.get("destinatario") or "",
            "eurovoc": r.get("eurovoc") or "",
            "score": round(r["score"], 4),
            "match_type": "semantic",
            "is_exact": False,
        })
    return records


@router.get("/results")
async def search_results(
    q: str = Query("", description="Search query; optional with an author filter (browse mode)"),
    deputy_id: Optional[str] = Query(None, description="Filter by deputy ID"),
    group: Optional[List[str]] = Query(None, description="Filter by parliamentary group(s)"),
    start_date: Optional[str] = Query(None, description="Start date (YYYY-MM-DD)"),
    end_date: Optional[str] = Query(None, description="End date (YYYY-MM-DD)"),
    search_type: str = Query("text", description="Search type: text, semantic, hybrid"),
    doc_type: str = Query("all", description="Document type filter: all, speech, act"),
    sort_by: str = Query("relevance", description="Sort order: relevance, date_desc, date_asc"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Results per page"),
    chamber: Optional[str] = Query(None, pattern="^(camera|senato|both)$",
                                   description="camera (default), senato or both"),
) -> Dict[str, Any]:
    """
    Search parliamentary records (Speech chunks + ParliamentaryAct).

    - text: exact text matching
    - semantic: vector similarity search
    - hybrid: both text and semantic combined

    Returns paginated results with total count.
    """
    client = get_client()
    all_results: List[Dict[str, Any]] = []

    # Browse mode: no query, but an author filter — list that author's
    # record by date. Without any filter the empty query stays rejected.
    q = q.strip()
    if not q:
        if not (deputy_id or group):
            raise HTTPException(status_code=422, detail="A query or an author filter is required")
        search_type = "text"
        if sort_by == "relevance":
            sort_by = "date_desc"

    # Fetch enough results to allow proper pagination
    fetch_limit = 500
    chambers = _resolve_chambers(chamber)

    try:
        search_speeches = doc_type in ("all", "speech")
        search_acts = doc_type in ("all", "act")

        if search_type in ("text", "hybrid"):
            if search_speeches:
                speech_text = _search_speeches_text(client, q, fetch_limit, deputy_id, group, start_date, end_date, chambers=chambers)
                all_results.extend(speech_text)
            if search_acts:
                act_text = _search_acts_text(client, q, fetch_limit, deputy_id, group, start_date, end_date, chambers=chambers)
                all_results.extend(act_text)

        if search_type in ("semantic", "hybrid"):
            try:
                embedding = _generate_embedding(q)
                if search_speeches:
                    speech_sem = _search_speeches_semantic(client, embedding, fetch_limit, deputy_id=deputy_id, group=group, start_date=start_date, end_date=end_date, chambers=chambers)
                    all_results.extend(speech_sem)
                if search_acts:
                    act_sem = _search_acts_semantic(client, embedding, fetch_limit, deputy_id=deputy_id, group=group, start_date=start_date, end_date=end_date, chambers=chambers)
                    all_results.extend(act_sem)
            except Exception as e:
                logger.error(f"Semantic search failed: {e}")
                # Fall back to text-only if semantic fails
                if search_type == "semantic":
                    if search_speeches:
                        speech_text = _search_speeches_text(client, q, fetch_limit, deputy_id, group, start_date, end_date, chambers=chambers)
                        all_results.extend(speech_text)
                    if search_acts:
                        act_text = _search_acts_text(client, q, fetch_limit, deputy_id, group, start_date, end_date, chambers=chambers)
                        all_results.extend(act_text)

        # Deduplicate by id, merging text (exact) and semantic hits for the same item:
        # keep the exact-match flag and the semantic score
        merged: Dict[str, Dict[str, Any]] = {}
        unique_results = []
        for r in all_results:
            existing = merged.get(r["id"])
            if existing is None:
                merged[r["id"]] = r
                unique_results.append(r)
            else:
                existing["is_exact"] = existing.get("is_exact") or r.get("is_exact") or False
                if r["score"] is not None and (existing["score"] is None or r["score"] > existing["score"]):
                    existing["score"] = r["score"]

        # Semantic-only hits whose snippet/title contains the query are exact citations too
        q_lower = q.lower()
        for r in unique_results:
            if not r.get("is_exact") and (
                q_lower in (r.get("text") or "").lower()
                or q_lower in (r.get("act_title") or "").lower()
            ):
                r["is_exact"] = True

        # Sort results: exact citations always come before semantic-only matches,
        # each block ordered by the requested criterion
        exact_first = lambda r: 0 if r.get("is_exact") else 1
        if sort_by == "date_desc":
            unique_results.sort(key=lambda r: r.get("date") or "", reverse=True)
            unique_results.sort(key=exact_first)
        elif sort_by == "date_asc":
            unique_results.sort(key=lambda r: r.get("date") or "")
            unique_results.sort(key=exact_first)
        else:
            # relevance: within each block score desc, date desc as tiebreak
            unique_results.sort(key=lambda r: r.get("date") or "", reverse=True)
            unique_results.sort(key=lambda r: (exact_first(r), -(r["score"] or 0.0)))

        total = len(unique_results)
        exact_count = sum(1 for r in unique_results if r.get("is_exact"))

        start = (page - 1) * page_size
        end = start + page_size
        page_results = unique_results[start:end]

        logger.info(f"Search '{q}' (type={search_type}, doc_type={doc_type}, page={page}): {total} total, returning {len(page_results)}")
        return {
            "results": page_results,
            "total": total,
            "exact_count": exact_count,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
        }

    except Exception as e:
        logger.error(f"Search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/deputies")
async def list_deputies(
    q: Optional[str] = Query(None, description="Filter by name"),
    limit: int = Query(50, ge=1, le=200),
    chamber: str = Query("camera", pattern="^(camera|senato)$"),
) -> List[Dict[str, Any]]:
    """
    List the members of one chamber (deputies by default, senators with
    chamber=senato), optionally filtered by name.
    """
    client = get_client()
    # Senators carry the Deputy label too: membership in a group of the
    # chamber decides. Party affiliations of ministers have no chamber.
    in_chamber = ("EXISTS { (d)-[m:MEMBER_OF_GROUP]->() WHERE m.affiliation IS NULL "
                  "AND coalesce(m.chamber, 'camera') = $chamber }")

    try:
        if q:
            cypher = f"""
            MATCH (d:Deputy)
            WHERE (toLower(d.first_name) CONTAINS toLower($search_text)
               OR toLower(d.last_name) CONTAINS toLower($search_text))
              AND {in_chamber}
            RETURN d.id AS id,
                   d.first_name AS first_name,
                   d.last_name AS last_name,
                   d.photo AS photo
            ORDER BY d.last_name, d.first_name
            LIMIT $limit
            """
            params = {"search_text": q, "limit": limit, "chamber": chamber}
        else:
            cypher = f"""
            MATCH (d:Deputy) WHERE {in_chamber}
            RETURN d.id AS id,
                   d.first_name AS first_name,
                   d.last_name AS last_name,
                   d.photo AS photo
            ORDER BY d.last_name, d.first_name
            LIMIT $limit
            """
            params = {"limit": limit, "chamber": chamber}

        with client.session() as session:
            result = session.run(cypher, **params)
            return [
                {
                    "id": record["id"],
                    "first_name": record["first_name"],
                    "last_name": record["last_name"],
                    "photo": record["photo"],
                }
                for record in result
            ]

    except Exception as e:
        logger.error(f"List deputies failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/groups")
async def list_groups(
    chamber: str = Query("camera", pattern="^(camera|senato)$"),
) -> List[Dict[str, Any]]:
    """
    List the parliamentary groups of one chamber with their current members.
    """
    client = get_client()

    try:
        cypher = """
        MATCH (g:ParliamentaryGroup) WHERE coalesce(g.chamber, 'camera') = $chamber
        OPTIONAL MATCH (d:Deputy)-[m:MEMBER_OF_GROUP]->(g)
        WHERE m.end_date IS NULL AND m.affiliation IS NULL
        WITH g, count(DISTINCT d) AS member_count
        RETURN g.name AS name,
               g.acronym AS acronym,
               member_count
        ORDER BY member_count DESC
        """

        with client.session() as session:
            result = session.run(cypher, chamber=chamber)
            return [
                {
                    "name": record["name"],
                    "acronym": record["acronym"],
                    "member_count": record["member_count"],
                }
                for record in result
            ]

    except Exception as e:
        logger.error(f"List groups failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/speech/{chunk_id}")
async def get_speech_detail(chunk_id: str) -> Dict[str, Any]:
    """
    Get full speech/intervention detail by chunk ID.
    Returns the complete intervention text and all metadata.
    """
    client = get_client()

    try:
        cypher = """
        MATCH (c:Chunk {id: $chunk_id})<-[:HAS_CHUNK]-(i:Speech)-[:SPOKEN_BY]->(d)
        WHERE (d:Deputy OR d:GovernmentMember)
        MATCH (i)<-[:CONTAINS_SPEECH]-(f:Phase)<-[:HAS_PHASE]-(dib:Debate)<-[:HAS_DEBATE]-(s:Session)
        OPTIONAL MATCH (d)-[mg:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        WHERE mg.start_date <= s.date AND (mg.end_date IS NULL OR mg.end_date >= s.date)
        RETURN i.text AS full_text,
               c.id AS chunk_id,
               c.text AS chunk_text,
               i.id AS speech_id,
               toString(s.date) AS date,
               s.number AS session_number,
               dib.title AS debate_title,
               d.first_name AS first_name,
               d.last_name AS last_name,
               CASE WHEN 'GovernmentMember' IN labels(d) THEN 'Governo'
                    ELSE coalesce(g.name, 'MISTO') END AS group_name
        LIMIT 1
        """

        with client.session() as session:
            result = session.run(cypher, chunk_id=chunk_id)
            record = result.single()

            if not record:
                raise HTTPException(status_code=404, detail=f"Speech chunk {chunk_id} not found")
            record = fill_rows(
                [dict(record)],
                chunk_fields={"chunk_id": {"chunk_text": "text"}},
                speech_fields={"speech_id": "full_text"},
            )[0]

            return {
                "type": "speech",
                "id": chunk_id,
                "speech_id": record["speech_id"],
                "full_text": record["full_text"] or "",
                "chunk_text": record["chunk_text"] or "",
                "date": record["date"],
                "session_number": record["session_number"],
                "debate_title": record["debate_title"] or "",
                "first_name": record["first_name"] or "",
                "last_name": record["last_name"] or "",
                "group": record["group_name"] or "MISTO",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get speech detail failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/act/{act_uri:path}")
async def get_act_detail(act_uri: str) -> Dict[str, Any]:
    """
    Get full parliamentary act detail by URI.
    Returns the complete description and all metadata.
    """
    client = get_client()

    try:
        cypher = """
        MATCH (a:ParliamentaryAct {uri: $act_uri})
        OPTIONAL MATCH (d)-[:PRIMARY_SIGNATORY]->(a)
        WHERE (d:Deputy OR d:GovernmentMember)
        OPTIONAL MATCH (d)-[:MEMBER_OF_GROUP]->(g:ParliamentaryGroup)
        OPTIONAL MATCH (a)-[:HAS_SUBJECT]->(ev:EurovocConcept)
        WITH a, d, g, collect(ev.label_it) AS eurovoc_labels
        RETURN a.uri AS act_uri,
               a.type AS act_type,
               a.title AS act_title,
               a.description AS description,
               toString(a.presentation_date) AS date_raw,
               a.number AS act_number,
               a.recipient AS destinatario,
               coalesce(a.eurovoc, reduce(s = '', l IN eurovoc_labels |
                   CASE WHEN s = '' THEN l ELSE s + '; ' + l END)) AS eurovoc,
               d.first_name AS first_name,
               d.last_name AS last_name,
               coalesce(g.name, 'MISTO') AS group_name
        LIMIT 1
        """

        with client.session() as session:
            result = session.run(cypher, act_uri=act_uri)
            record = result.single()

            if not record:
                raise HTTPException(status_code=404, detail=f"Act {act_uri} not found")

            # v1: 'YYYYMMDD' → reformat; v2: toString(date) is already ISO
            date_raw = record["date_raw"] or ""
            if len(date_raw) == 8 and date_raw.isdigit():
                formatted_date = f"{date_raw[:4]}-{date_raw[4:6]}-{date_raw[6:8]}"
            else:
                formatted_date = date_raw

            return {
                "type": "act",
                "id": act_uri,
                "act_type": record["act_type"] or "",
                "act_title": record["act_title"] or "",
                "description": record["description"] or "",
                "date": formatted_date,
                "act_number": record["act_number"] or "",
                "destinatario": record["destinatario"] or "",
                "eurovoc": record["eurovoc"] or "",
                "first_name": record["first_name"] or "",
                "last_name": record["last_name"] or "",
                "group": record["group_name"] or "MISTO",
            }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get act detail failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))
