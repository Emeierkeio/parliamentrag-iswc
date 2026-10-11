"""Retrieval scope: which chamber and legislature a query searches.

A scope is a tuple of (chamber, legislature) pairs. Channels restrict Session
nodes to it, and the dense channel queries one vector index per pair
(chunk_embedding_<chamber>_<legislature>, built by db_builder), so that adding
a legislature never changes the candidates of another.
"""

from __future__ import annotations

import logging
import os
import re
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


CURRENT_LEGISLATURE = 19

# A chamber named in the question. "Camera" alone is not enough ("camera di
# commercio", "camera iperbarica"): it needs a preposition or "dei deputati".
_SENATE_RE = re.compile(r"\b(senato|senator[ei]|senatric[ei]|palazzo madama)\b", re.IGNORECASE)
_CAMERA_RE = re.compile(
    r"\b((all[ao']|nell[ao']|dell[ao']|in)\s*camera\b(?!\s+di\s+commercio)"
    r"|camera dei deputati|deputat[ie]|montecitorio)",
    re.IGNORECASE,
)


def loaded_chambers() -> Tuple[str, ...]:
    """Chambers whose sittings the graph holds: chambers in default.yaml, or
    the CHAMBERS environment variable ("camera,senato") for a deployment on a
    graph with the Senate, such as the staging one."""
    from ...config import get_config
    env = os.environ.get("CHAMBERS", "").strip()
    chambers = [c.strip() for c in env.split(",") if c.strip()] if env else (
        get_config().load_config().get("chambers") or ["camera"])
    return tuple(c for c in CHAMBERS if c in chambers)


def default_scope() -> Scope:
    """Every loaded chamber of the current legislature: answers mix Camera and
    Senate citations unless the question names one chamber."""
    return tuple((c, CURRENT_LEGISLATURE) for c in loaded_chambers())


def chambers_in_question(query: str) -> Tuple[str, ...]:
    """Chambers the question names explicitly, in CHAMBERS order."""
    found = set()
    if _SENATE_RE.search(query or ""):
        found.add("senato")
    if _CAMERA_RE.search(query or ""):
        found.add("camera")
    return tuple(c for c in CHAMBERS if c in found)


def resolve_scope(raw: Optional[Iterable[Any]], query: str = "") -> Scope:
    """Scope of a request: the explicit one if given; else the loaded chambers
    the question names, if it names exactly one; else default_scope()."""
    if raw:
        return normalize_scope(raw)
    named = [c for c in chambers_in_question(query) if c in loaded_chambers()]
    if len(named) == 1:
        return ((named[0], CURRENT_LEGISLATURE),)
    return default_scope()


def normalize_scope(raw: Optional[Iterable[Any]]) -> Scope:
    """Accept None, [{"chamber": "camera", "legislature": 19}, ...] or
    [("camera", 19), ...]; return a sorted, deduplicated scope."""
    if not raw:
        return default_scope()
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
