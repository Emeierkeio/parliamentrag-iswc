import { getGroupAbbrev } from "@/config";

/*
 * A topic dossier is a saved answer (GET /api/history/{id}) read as a page:
 * the generator already writes one section per bloc and one paragraph per
 * group ("Per <gruppo>, ...", with the quote as a markdown link to its
 * chunk), so the dossier is parsed out of that markdown instead of asking the
 * pipeline for a second format.
 */

export type Bloc = "governo" | "maggioranza" | "opposizione" | "misto";

export const BLOC_ORDER: Bloc[] = ["governo", "maggioranza", "opposizione", "misto"];

export interface DossierQuote {
  text: string;
  speaker: string;
  role: string | null;
  date: string | null;
  chunkId: string;
  interventionId: string | null;
  verified: boolean;
  photo: string | null;
}

export interface DossierGroup {
  abbrev: string;
  name: string;
  bloc: Bloc;
  gist: string | null;
  paragraph: string;
  quote: DossierQuote | null;
  interventions: number;
}

export interface DossierVoice {
  id: string;
  name: string;
  abbrev: string;
  score: number;
  breakdown: { key: string; value: number }[];
  profileUrl: string | null;
}

export interface CompassPoint {
  abbrev: string;
  x: number;
  confidence: number;
}

export interface DossierCompass {
  positive: string;
  negative: string;
  points: CompassPoint[];
  stable: boolean;
}

export interface Dossier {
  id: string;
  topic: string;
  query: string;
  timestamp: string;
  intro: string | null;
  groups: DossierGroup[];
  interventions: number;
  speakers: number;
  firstDate: string | null;
  lastDate: string | null;
  commission: string | null;
  voices: DossierVoice[];
  compass: DossierCompass | null;
  actNumbers: string[];
}

/* Saved-answer payload, only the fields the dossier reads. */
export interface SavedAnswer {
  id: string;
  query: string;
  answer: string;
  timestamp: string;
  citations?: {
    chunk_id: string;
    deputy_first_name: string;
    deputy_last_name: string;
    quote_text?: string;
    group: string;
    coalition: string;
    date?: string;
    intervention_id?: string;
    verified?: boolean;
    institutional_role?: string | null;
    photo?: string | null;
  }[];
  experts?: {
    id: string;
    first_name: string;
    last_name: string;
    group: string;
    authority_score: number;
    camera_profile_url?: string | null;
    score_breakdown?: Record<string, number>;
  }[];
  commissioni?: { nome: string; score: number }[];
  compass?: {
    meta?: { is_stable?: boolean };
    axes?: { x?: { positive_side?: { label: string }; negative_side?: { label: string } } };
    groups?: { group_id: string; position_x: number; stats?: { confidence?: number } }[];
  } | null;
  topic_stats?: {
    intervention_count: number;
    speaker_count: number;
    first_date?: string;
    last_date?: string;
    interventions_detail?: { party: string; coalition: string; speech_id: string }[];
  } | null;
}

const TOPIC_RE = /sul tema:\s*(.+?)\s*\??$/i;
const QUOTE_LINK_RE = /\[«([^»]+)»\]\(([^)\s]+)\)/;
const ACT_RE = /\b(?:A\.?\s?C\.?|PDL\s+n\.)\s*(\d{2,5})\b/g;

export function topicOf(query: string): string {
  const m = query.match(TOPIC_RE);
  const topic = (m ? m[1] : query).trim();
  return topic.charAt(0).toUpperCase() + topic.slice(1);
}

function blocOf(heading: string): Bloc | null {
  const h = heading.toLowerCase();
  if (h.includes("governo")) return "governo";
  if (h.includes("maggioranza")) return "maggioranza";
  if (h.includes("opposizion")) return "opposizione";
  if (h.includes("misto")) return "misto";
  return null;
}

function stripMarkdown(text: string): string {
  return text
    .replace(/\[«([^»]+)»\]\([^)]+\)/g, "«$1»")
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/\s+/g, " ")
    .trim();
}

/* Sentence split that keeps «...» quotes whole: the generator never ends a
   sentence inside a quote, but quotes contain full stops. */
function sentences(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let start = 0;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c === "«") depth++;
    else if (c === "»") depth = Math.max(0, depth - 1);
    else if (depth === 0 && (c === "." || c === "!" || c === "?") && text[i + 1] === " " && /[A-ZÀ-Ý]/.test(text[i + 2] ?? "")) {
      out.push(text.slice(start, i + 1).trim());
      start = i + 2;
    }
  }
  const tail = text.slice(start).trim();
  if (tail) out.push(tail);
  return out;
}

/* The group's stance: the paragraph minus the speaker sentence and the
   opening scene-setter. The generator closes each paragraph with the
   position ("La Lega sostiene quindi..."), so the last sentence wins. */
function gistOf(body: string): string | null {
  const plain = sentences(stripMarkdown(body)).filter((s) => !s.includes("«"));
  return plain.length ? plain[plain.length - 1] : null;
}

function capitalise(text: string): string {
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function buildDossier(raw: SavedAnswer): Dossier {
  const citations = new Map((raw.citations ?? []).map((c) => [c.chunk_id, c]));
  const knownNames = Array.from(
    new Set([
      ...(raw.citations ?? []).map((c) => c.group),
      ...(raw.topic_stats?.interventions_detail ?? []).map((i) => i.party),
    ]),
  ).sort((a, b) => b.length - a.length);

  const interventionsByAbbrev = new Map<string, number>();
  for (const i of raw.topic_stats?.interventions_detail ?? []) {
    const key = i.coalition === "governo" ? "Gov" : getGroupAbbrev(i.party);
    interventionsByAbbrev.set(key, (interventionsByAbbrev.get(key) ?? 0) + 1);
  }

  let intro: string | null = null;
  const groups: DossierGroup[] = [];

  for (const section of raw.answer.split(/^## /m).slice(1)) {
    const [heading, ...rest] = section.split("\n");
    const body = rest.join("\n");
    const bloc = blocOf(heading);
    if (!bloc) {
      if (/introduzione/i.test(heading)) {
        intro = stripMarkdown(body.split(/\n\s*\n/).find((p) => p.trim()) ?? "") || null;
      }
      continue;
    }
    const paragraphs = body
      .split(/\n\s*\n/)
      .map((p) => p.trim())
      .filter((p) => p && p !== "---");

    for (const paragraph of paragraphs) {
      let name: string;
      let text = paragraph;
      const per = paragraph.match(/^Per\s+/);
      if (per && bloc !== "governo") {
        const after = paragraph.slice(per[0].length);
        const known = knownNames.find((n) => after.startsWith(n + ","));
        if (known) {
          name = known;
          text = capitalise(after.slice(known.length + 1).trim());
        } else {
          const comma = after.indexOf(",");
          name = after.slice(0, comma).trim();
          text = capitalise(after.slice(comma + 1).trim());
        }
      } else {
        name = bloc === "governo" ? "Governo" : "Misto";
      }

      const abbrev = bloc === "governo" ? "Gov" : getGroupAbbrev(name);
      const link = text.match(QUOTE_LINK_RE);
      const cited = link ? citations.get(link[2]) : undefined;
      const quote: DossierQuote | null = link
        ? {
            text: (cited?.quote_text ?? link[1]).trim(),
            speaker: cited ? `${cited.deputy_first_name} ${cited.deputy_last_name}` : "",
            role: cited?.institutional_role ?? null,
            date: cited?.date ?? null,
            chunkId: link[2],
            interventionId: cited?.intervention_id ?? null,
            verified: Boolean(cited?.verified),
            photo: cited?.photo ?? null,
          }
        : null;

      const existing = groups.find((g) => g.abbrev === abbrev);
      if (existing) {
        existing.paragraph += "\n\n" + stripMarkdown(text);
        existing.quote ??= quote;
        continue;
      }
      groups.push({
        abbrev,
        name,
        bloc,
        gist: gistOf(text),
        paragraph: stripMarkdown(text),
        quote,
        interventions: interventionsByAbbrev.get(abbrev) ?? 0,
      });
    }
  }

  groups.sort((a, b) =>
    a.bloc === b.bloc ? b.interventions - a.interventions : BLOC_ORDER.indexOf(a.bloc) - BLOC_ORDER.indexOf(b.bloc),
  );

  const voices: DossierVoice[] = (raw.experts ?? []).map((e) => ({
    id: e.id,
    name: `${e.first_name} ${e.last_name}`,
    abbrev: getGroupAbbrev(e.group),
    score: e.authority_score,
    breakdown: ["speeches", "acts", "committee", "profession", "education", "role"].map((key) => ({
      key,
      value: e.score_breakdown?.[key] ?? 0,
    })),
    profileUrl: e.camera_profile_url ?? null,
  }));

  const axis = raw.compass?.axes?.x;
  const compass: DossierCompass | null =
    axis?.positive_side && axis.negative_side && raw.compass?.groups?.length
      ? {
          positive: axis.positive_side.label,
          negative: axis.negative_side.label,
          stable: raw.compass.meta?.is_stable !== false,
          points: raw.compass.groups
            .map((g) => ({
              abbrev: getGroupAbbrev(g.group_id),
              x: g.position_x,
              confidence: g.stats?.confidence ?? 0,
            }))
            .sort((a, b) => a.x - b.x),
        }
      : null;

  const actNumbers = Array.from(new Set(Array.from(raw.answer.matchAll(ACT_RE), (m) => m[1])));

  return {
    id: raw.id,
    topic: topicOf(raw.query),
    query: raw.query,
    timestamp: raw.timestamp,
    intro,
    groups,
    interventions: raw.topic_stats?.intervention_count ?? 0,
    speakers: raw.topic_stats?.speaker_count ?? 0,
    firstDate: raw.topic_stats?.first_date ?? null,
    lastDate: raw.topic_stats?.last_date ?? null,
    commission: raw.commissioni?.[0]?.nome ?? null,
    voices,
    compass,
    actNumbers,
  };
}

/* Which side of the compass's first axis each group sits on. Groups within
   a fifth of the axis span from the centre are left out of both lists. */
export function compassSides(compass: DossierCompass): { negative: string[]; positive: string[] } {
  const span = Math.max(...compass.points.map((p) => Math.abs(p.x)), 1);
  const dead = span * 0.2;
  return {
    negative: compass.points.filter((p) => p.x < -dead).map((p) => p.abbrev),
    positive: compass.points.filter((p) => p.x > dead).map((p) => p.abbrev).reverse(),
  };
}

/* Authority is a weighted sum of six components (backend authority
   config, keys as in /api/config: "interventions" scores speeches). The
   saved components are re-weighted with the weights in force, so a dossier
   follows the Settings; only the voices saved with it can be re-ranked. */
export type AuthorityWeights = Record<string, number>;

const WEIGHT_KEY: Record<string, string> = { speeches: "interventions" };

export function rescoreVoices(voices: DossierVoice[], weights: AuthorityWeights | null): DossierVoice[] {
  if (!weights) return voices;
  return voices
    .map((v) => ({
      ...v,
      score: v.breakdown.reduce((sum, b) => sum + (weights[WEIGHT_KEY[b.key] ?? b.key] ?? 0) * b.value, 0),
    }))
    .sort((a, b) => b.score - a.score);
}
