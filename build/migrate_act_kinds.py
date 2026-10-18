#!/usr/bin/env python3
"""
Family label, `kind` and `type_raw` on every ParliamentaryAct (decision D1).

Writers that know the act (ingest_acts_camera, ingest_senate_aic,
link_senate_acts) set them already; this pass covers the rest (document
placeholders, agenda orders known only by the URI a vote cites) and corrects
any node whose label or kind disagrees with build/act_kinds.py. Idempotent:
a second run writes nothing.

    python build/migrate_act_kinds.py --neo4j-uri bolt://... [--dry-run]
"""

import argparse
import logging
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from act_kinds import FAMILIES, act_kind, valid  # noqa: E402

logger = logging.getLogger("migrate_act_kinds")

READ = """
MATCH (a:ParliamentaryAct)
RETURN a.uri AS uri, coalesce(a.type_raw, a.type) AS type_raw, a.nature AS nature,
       a.initiative AS initiative, a.kind AS kind,
       [l IN labels(a) WHERE l IN $families] AS families,
       a.type_raw IS NULL AND a.type IS NOT NULL AS no_raw
"""


def plan(rows: list[dict]) -> tuple[dict[str, list[dict]], Counter]:
    """family -> rows to write, and counts of what is unchanged or unknown."""
    writes: dict[str, list[dict]] = defaultdict(list)
    stats = Counter()
    for r in rows:
        fk = act_kind(r["uri"], r["type_raw"], r["nature"], r["initiative"])
        if fk is None and len(r["families"]) == 1 and valid(r["families"][0], r["kind"]):
            # Chamber bills: the writer reads ocd:rif_natura, which the node lacks.
            fk = (r["families"][0], r["kind"])
        if fk is None:
            stats["unknown"] += 1
            if stats["unknown"] <= 10:
                logger.warning("no family for %s (type %r)", r["uri"], r["type_raw"])
            continue
        family, kind = fk
        if r["families"] == [family] and r["kind"] == kind and not r["no_raw"]:
            stats["unchanged"] += 1
            continue
        writes[family].append({"uri": r["uri"], "kind": kind})
        stats[f"set_{family}"] += 1
    return writes, stats


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")
    ap = argparse.ArgumentParser(description="Family labels and kind on ParliamentaryAct")
    ap.add_argument("--neo4j-uri", required=True)
    ap.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    ap.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD"),
                    required=os.environ.get("NEO4J_PASSWORD") is None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from neo4j import GraphDatabase

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))
    with driver.session() as s:
        rows = s.run(READ, families=list(FAMILIES)).data()
        writes, stats = plan(rows)
        if not args.dry_run:
            for family, items in writes.items():  # family comes from act_kinds.FAMILIES only
                others = ":".join(f for f in FAMILIES if f != family)
                for i in range(0, len(items), 5000):
                    s.run(f"""
                        UNWIND $rows AS row
                        MATCH (a:ParliamentaryAct {{uri: row.uri}})
                        REMOVE a:{others}
                        SET a:{family}, a.kind = row.kind, a.type_raw = coalesce(a.type_raw, a.type)
                    """, rows=items[i:i + 5000]).consume()
    driver.close()
    logger.info("%d acts%s", len(rows), " (dry run)" if args.dry_run else "")
    for k, v in sorted(stats.items()):
        logger.info("  %s: %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
