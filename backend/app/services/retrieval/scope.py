"""Retrieval scope: which chamber and legislature a query searches.

A scope is a tuple of (chamber, legislature) pairs. Channels restrict Session
nodes to it, and the dense channel queries one vector index per pair
(chunk_embedding_<chamber>_<legislature>, built by db_builder), so that adding
a legislature never changes the candidates of another.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, List, Literal, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

Scope = Tuple[Tuple[str, int], ...]

DEFAULT_SCOPE: Scope = (("camera", 19),)
CHAMBERS = ("camera", "senato")


class ScopeItem(BaseModel):
    """One chamber and legislature in a request's search scope."""
    chamber: Literal["camera", "senato"]
    legislature: int = Field(ge=1, le=30)


def normalize_scope(raw: Optional[Iterable[Any]]) -> Scope:
    """Accept None, [{"chamber": "camera", "legislature": 19}, ...] or
    [("camera", 19), ...]; return a sorted, deduplicated scope."""
    if not raw:
        return DEFAULT_SCOPE
    pairs = set()
    for item in raw:
        if isinstance(item, dict):
            chamber, legislature = item.get("chamber"), item.get("legislature")
        elif hasattr(item, "chamber"):
            chamber, legislature = item.chamber, item.legislature
        else:
            chamber, legislature = item
        if chamber not in CHAMBERS:
            raise ValueError(f"Unknown chamber: {chamber!r}")
        pairs.add((chamber, int(legislature)))
    return tuple(sorted(pairs))


def session_clause(var: str = "s") -> str:
    """Cypher condition restricting a Session variable to $scope."""
    return f"[coalesce({var}.chamber, 'camera'), {var}.legislature] IN $scope"


def scope_param(scope: Scope) -> List[List[Any]]:
    return [[chamber, legislature] for chamber, legislature in scope]


def scope_key(scope: Scope) -> Optional[str]:
    """Cache-key component; None for the default scope, whose cached
    answers predate scopes and stay valid."""
    if scope == DEFAULT_SCOPE:
        return None
    return ",".join(f"{c}_{l}" for c, l in scope)


def vector_indexes(client, scope: Scope, fallback: str) -> List[str]:
    """Vector indexes to query for a scope.

    Scope indexes that do not exist yet (a graph built before per-scope
    indexes, e.g. the current Camera-XIX-only demo) fall back to the global
    index, which the Session filter then restricts.
    """
    names = _existing_vector_indexes(client)
    wanted = [f"chunk_embedding_{c}_{l}" for c, l in scope]
    chosen = [n for n in wanted if n in names]
    if len(chosen) < len(wanted):
        chosen.append(fallback)
    return chosen


_INDEX_CACHE: Optional[Sequence[str]] = None


def _existing_vector_indexes(client) -> Sequence[str]:
    global _INDEX_CACHE
    if _INDEX_CACHE is None:
        try:
            rows = client.query("SHOW VECTOR INDEXES YIELD name, state WHERE state = 'ONLINE' RETURN name")
            _INDEX_CACHE = tuple(r["name"] for r in rows)
        except Exception as exc:  # unreachable DB: let the query itself fail
            logger.warning("Could not list vector indexes: %s", exc)
            return ()
    return _INDEX_CACHE
