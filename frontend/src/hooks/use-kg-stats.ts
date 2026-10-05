import siteData from "@/data/site-data.json";

/**
 * Knowledge-graph counts, from the snapshot in src/data/site-data.json
 * (refreshed with scripts/snapshot-data.mjs before a deploy).
 */
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
};

export const KG_STATS: KgStats = siteData;

export function useKgStats(): KgStats {
  return KG_STATS;
}
