"use client";

import { useEffect, useLayoutEffect, useState } from "react";

/**
 * Live knowledge-graph counts from /api/data/stats.
 *
 * Render order: static fallback (first-ever visit only) -> localStorage cache
 * of the last fetched values (seeded pre-paint, so refreshes don't flash a
 * stale number) -> live fetch. The cache is read in useLayoutEffect rather
 * than in the useState initializer to avoid an SSR hydration mismatch.
 * The fallback snapshot is from the build of 2026-07-26; its Senate figures
 * come from the staging graph of 2026-10-14, the first with the Senate.
 */
export const CHAMBERS = ["camera", "senato"] as const;
export type Chamber = (typeof CHAMBERS)[number];
export type ChamberStats = {
  people: number;
  speeches: number;
  sessions: number;
  acts: number;
  votes: number;
  individual_votes: number;
};
export type ChamberField = keyof ChamberStats;

export type KgStats = {
  people: number;
  speeches: number;
  sessions: number;
  acts: number;
  votes: number;
  individual_votes: number;
  eurovoc_concepts: number;
  chunks: number;
  triples: number | null;
  last_update: string | null;
  by_chamber: Record<Chamber, ChamberStats>;
};

export const KG_STATS_FALLBACK: KgStats = {
  people: 455,
  speeches: 45907,
  sessions: 697,
  acts: 32976,
  votes: 16787,
  individual_votes: 6305481,
  eurovoc_concepts: 1716,
  chunks: 171624,
  triples: 863834,
  last_update: null,
  by_chamber: {
    camera: { people: 433, speeches: 45907, sessions: 697, acts: 32976, votes: 16787, individual_votes: 6305481 },
    senato: { people: 212, speeches: 17904, sessions: 464, acts: 15444, votes: 8338, individual_votes: 1214934 },
  },
};

const CACHE_KEY = "kgStatsCache";

export function useKgStats(): KgStats {
  const [stats, setStats] = useState<KgStats>(KG_STATS_FALLBACK);

  useLayoutEffect(() => {
    try {
      const cached = localStorage.getItem(CACHE_KEY);
      const parsed = cached ? JSON.parse(cached) : null;
      if (parsed?.by_chamber) setStats({ ...KG_STATS_FALLBACK, ...parsed });
    } catch {}
  }, []);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/data/stats")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        // A backend without the per-chamber split keeps the cached one
        if (cancelled || !data?.people || !data.by_chamber) return;
        const fresh = {
          ...KG_STATS_FALLBACK,
          ...data,
          triples: data.triples ?? KG_STATS_FALLBACK.triples,
        };
        try {
          localStorage.setItem(CACHE_KEY, JSON.stringify(fresh));
        } catch {}
        setStats(fresh);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  return stats;
}
