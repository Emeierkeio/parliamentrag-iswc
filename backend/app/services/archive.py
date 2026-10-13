"""Text archive on Postgres + pgvector (decision of 2026-10-12).

For the scopes it covers (today the Senate XIX) the archive holds the text
and the embedding of every chunk and the full text of every speech; Neo4j
keeps the Chunk and Speech nodes with their relations but not the text.
Tables and loader: build/pg_archive.py.

The archive is on when ARCHIVE_URL (a Postgres connection string) is set and
at least one scope is listed, in `archive.scopes` of default.yaml or in the
ARCHIVE_SCOPES environment variable ("senato_19,camera_18"). With the archive
off every function here is a no-op and retrieval is the Neo4j one.

Similarities are returned on the Neo4j vector-index scale, (1+cos)/2, so the
merger compares archive and Neo4j candidates directly.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

ScopePair = Tuple[str, int]


def archive_scopes() -> Tuple[ScopePair, ...]:
    """(chamber, legislature) pairs whose text lives in the archive."""
    if not os.environ.get("ARCHIVE_URL", "").strip():
        return ()
    env = os.environ.get("ARCHIVE_SCOPES", "").strip()
    if env:
        names = [s.strip() for s in env.split(",") if s.strip()]
    else:
        from ..config import get_config
        names = (get_config().load_config().get("archive") or {}).get("scopes") or []
    pairs = []
    for name in names:
        chamber, _, legislature = name.rpartition("_")
        if chamber and legislature.isdigit():
            pairs.append((chamber, int(legislature)))
        else:
            logger.warning("Archive scope %r ignored: expected <chamber>_<legislature>", name)
    return tuple(pairs)


def _vector(values: Sequence[float]) -> str:
    return "[" + ",".join(f"{v:.6g}" for v in values) + "]"


class TextArchive:
    """Vector search and text lookups on the Postgres archive."""

    def __init__(self, url: str, scopes: Iterable[ScopePair]):
        from pgvector.psycopg import register_vector
        from psycopg_pool import ConnectionPool

        self.scopes = tuple(scopes)
        self.pool = ConnectionPool(url, min_size=1, max_size=8, open=True,
                                   kwargs={"autocommit": True}, configure=register_vector)
        atexit.register(self.pool.close)

    def covers(self, pair: ScopePair) -> bool:
        return tuple(pair) in self.scopes

    def search(
        self,
        query_embedding: Sequence[float],
        pair: ScopePair,
        top_k: int,
        threshold: float = 0.0,
        date_start: Optional[str] = None,
        date_end: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Top-k chunks of one scope by cosine similarity, best first:
        [{"id", "similarity"}]. The date bounds are applied inside the index
        scan (iterative scan), so a narrow date range still returns k rows."""
        where = ["assembly = %s", "term = %s"]
        params: List[Any] = [pair[0], pair[1]]
        if date_start:
            where.append("session_date >= %s")
            params.append(date_start)
        if date_end:
            where.append("session_date <= %s")
            params.append(date_end)
        vec = _vector(query_embedding)
        sql = (
            "SELECT id, 1 - (embedding <=> %s::halfvec) AS cos FROM chunk "
            f"WHERE {' AND '.join(where)} "
            "ORDER BY embedding <=> %s::halfvec LIMIT %s"
        )
        with self.pool.connection() as conn:
            with conn.transaction():
                conn.execute("SET LOCAL hnsw.ef_search = 200")
                conn.execute("SET LOCAL hnsw.iterative_scan = relaxed_order")
                rows = conn.execute(sql, [vec, *params, vec, top_k]).fetchall()
        hits = [{"id": r[0], "similarity": (1.0 + float(r[1])) / 2.0} for r in rows]
        # relaxed_order may return rows slightly out of order
        hits.sort(key=lambda h: h["similarity"], reverse=True)
        return [h for h in hits if h["similarity"] >= threshold]

    def chunks(self, ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """{chunk_id: {"text", "embedding", "speech_id"}} for the ids in the archive."""
        ids = list({i for i in ids if i})
        if not ids:
            return {}
        # Binary transfer: half-precision vectors are 3 KB per chunk instead of
        # ~13 KB as text, which matters over the link to the VPS.
        with self.pool.connection() as conn:
            rows = conn.cursor(binary=True).execute(
                "SELECT id, text, embedding, speech_id FROM chunk WHERE id = ANY(%s)",
                [ids]).fetchall()
        return {r[0]: {"text": r[1], "embedding": r[2].to_list() if r[2] is not None else None,
                       "speech_id": r[3]}
                for r in rows}

    def speeches(self, ids: Iterable[str]) -> Dict[str, str]:
        """{speech_id: full text} for the ids in the archive."""
        ids = list({i for i in ids if i})
        if not ids:
            return {}
        with self.pool.connection() as conn:
            rows = conn.execute("SELECT id, text FROM speech WHERE id = ANY(%s)", [ids]).fetchall()
        return {r[0]: r[1] for r in rows}

    def fill(
        self,
        rows: List[Dict[str, Any]],
        chunk_fields: Optional[Dict[str, str]] = None,
        speech_fields: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """Overwrite text and embedding of archived chunks in Neo4j rows.

        chunk_fields maps a chunk-id key of the row to {row key: archive
        field} pairs, e.g. {"chunk_id": {"chunk_text": "text", "embedding":
        "embedding"}}; speech_fields maps a speech-id key to the row key that
        takes the speech text. The archive wins over whatever Neo4j returned,
        so the same rows come out whether or not Neo4j still has the text.
        """
        chunk_fields = chunk_fields or {}
        speech_fields = speech_fields or {}
        chunk_ids = [r.get(k) for r in rows for k in chunk_fields]
        speech_ids = [r.get(k) for r in rows for k in speech_fields]
        chunks = self.chunks(chunk_ids) if chunk_ids else {}
        speeches = self.speeches(speech_ids) if speech_ids else {}
        for row in rows:
            for id_key, mapping in chunk_fields.items():
                hit = chunks.get(row.get(id_key))
                if hit:
                    for row_key, field in mapping.items():
                        row[row_key] = hit[field]
            for id_key, row_key in speech_fields.items():
                text = speeches.get(row.get(id_key))
                if text is not None:
                    row[row_key] = text
        return rows


_ARCHIVE: Optional[TextArchive] = None
_ARCHIVE_KEY: Optional[tuple] = None
_LOCK = threading.Lock()


def get_archive() -> Optional[TextArchive]:
    """The configured archive, or None when it is off."""
    global _ARCHIVE, _ARCHIVE_KEY
    scopes = archive_scopes()
    if not scopes:
        return None
    key = (os.environ["ARCHIVE_URL"], scopes)
    with _LOCK:
        if _ARCHIVE is None or _ARCHIVE_KEY != key:
            _ARCHIVE = TextArchive(key[0], scopes)
            _ARCHIVE_KEY = key
            logger.info("Text archive on for %s", ", ".join(f"{c}_{l}" for c, l in scopes))
        return _ARCHIVE


def fill_rows(rows: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
    """TextArchive.fill when the archive is on, rows unchanged otherwise."""
    archive = get_archive()
    if archive is None or not rows:
        return rows
    return archive.fill(rows, **kwargs)


# The usual shape of a retrieval row: chunk text and embedding by chunk_id,
# speech text by speech_id.
RETRIEVAL_ROW = {
    "chunk_fields": {"chunk_id": {"chunk_text": "text", "embedding": "embedding"}},
    "speech_fields": {"speech_id": "text"},
}
