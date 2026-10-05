import { config, getGroupAbbrev } from "@/config";
import { toTitleCase } from "@/lib/utils";

const LABELS = config.politicalGroups as Record<string, { label?: string }>;

/** Display name for a graph group name. The graph spelling of some groups
    (Noi Moderati) differs from every config key, so after the exact lookup
    the shortest label sharing the same abbreviation wins. */
export function groupLabel(name: string): string {
  const exact = LABELS[name]?.label;
  if (exact) return exact;
  const abbrev = getGroupAbbrev(name);
  let best: string | null = null;
  for (const [key, value] of Object.entries(LABELS)) {
    if (!value.label || getGroupAbbrev(key) !== abbrev) continue;
    if (!best || value.label.length < best.length) best = value.label;
  }
  return best ?? toTitleCase(name);
}

export function groupSlug(name: string): string {
  return getGroupAbbrev(name).toLowerCase();
}

export type Coalition = "maggioranza" | "opposizione" | "misto";

export const COALITION_ORDER: Coalition[] = ["maggioranza", "opposizione", "misto"];

/* XIX legislature: the Meloni government is backed by FdI, Lega, FI and NM.
   Keys are getGroupAbbrev outputs; the labels live in Dossier.bloc_*. */
const MAJORITY = new Set(["FdI", "Lega", "FI", "NM"]);

export function coalitionOf(name: string): Coalition {
  const abbrev = getGroupAbbrev(name);
  if (abbrev === "Misto") return "misto";
  return MAJORITY.has(abbrev) ? "maggioranza" : "opposizione";
}
