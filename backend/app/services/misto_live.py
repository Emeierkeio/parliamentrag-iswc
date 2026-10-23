"""
Misto components read from the graph, so a new one needs no config change.

default.yaml lists the components known when it was written (coalitions.misto,
chamber_only_groups). Components are born often (Senate «Civici Marche»,
22/10/2026) and the nightly job writes them as MistoComponent nodes: this
module adds every component with an open membership that the config does not
list, in its own chamber. A component that counts for a group (Senate AVS and
Azione, models/evidence.py MISTO_COMPONENT_PARTY) is not a party of its own.

The graph is read only when the app has a Neo4j client (never from tests or
scripts without one), at most once per TTL; on error the last list stays.
"""

import logging
import time
from typing import Dict, List

logger = logging.getLogger(__name__)

TTL_SECONDS = 3600

_QUERY = """
MATCH (m:MistoComponent)<-[r:MEMBER_OF_COMPONENT]-()
WHERE r.end_date IS NULL AND m.name IS NOT NULL
RETURN DISTINCT m.name AS name, coalesce(m.chamber, 'camera') AS chamber
"""

_cache: Dict[str, object] = {"at": 0.0, "rows": []}


def _client():
    from . import neo4j_client
    return neo4j_client._client


def live_components() -> List[Dict[str, str]]:
    """[{name, chamber}] of the components with a current member (cached)."""
    now = time.monotonic()
    if _cache["at"] and now - float(_cache["at"]) < TTL_SECONDS:
        return list(_cache["rows"])
    client = _client()
    if client is None:
        return list(_cache["rows"])
    try:
        rows = [{"name": r["name"], "chamber": r["chamber"]} for r in client.query(_QUERY)]
        _cache["rows"] = rows
    except Exception as exc:  # the graph is down: keep what we had
        logger.warning("Componenti del Misto dal grafo non lette: %s", exc)
    _cache["at"] = now
    return list(_cache["rows"])


def extra_components(coalitions: Dict[str, List[str]]) -> Dict[str, str]:
    """Display name → chamber of the live components the coalitions miss."""
    from ..models.evidence import MISTO_COMPONENT_PARTY, _party_key, normalize_party_name

    listed = {_party_key(g) for groups in coalitions.values() for g in groups}
    out: Dict[str, str] = {}
    for row in live_components():
        party = MISTO_COMPONENT_PARTY.get(_party_key(row["name"]))
        if party and _party_key(party) != _party_key(row["name"]):
            continue  # counts for a group (AVS, Azione)
        display = normalize_party_name(row["name"])
        if display and _party_key(display) not in listed:
            out[display] = row["chamber"]
    return out


def reset() -> None:
    _cache["at"] = 0.0
    _cache["rows"] = []
