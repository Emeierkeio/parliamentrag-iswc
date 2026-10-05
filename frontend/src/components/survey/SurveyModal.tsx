"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Textarea } from "@/components/ui/textarea";
import { Separator } from "@/components/ui/separator";
import { Card, CardContent } from "@/components/ui/card";
import {
  ClipboardCheck,
  ChevronRight,
  ChevronLeft,
  Check,
  AlertCircle,
  Loader2,
  ThumbsUp,
  MessageSquare,
  Quote,
  Scale,
  Star,
  RefreshCw,
  CheckCircle2,
  UserCheck,
  BookOpen,
} from "lucide-react";
import type { Expert } from "@/types/chat";
import { ExpertModal } from "@/components/chat/ExpertCard";
import { cn } from "@/lib/utils";
import { config } from "@/config";
import { StarRating } from "./StarRating";
import { CitationReviewStep } from "./CitationReviewStep";
import {
  SURVEY_QUESTIONS,
  AB_DIMENSIONS,
  SIMPLE_DIMENSIONS,
  SIMPLE_DIMENSION_LABELS,
  type SurveyFormState,
  type ABRating,
  type PendingChat,
  type ABDimension,
  type SimpleRatingFormState,
  type BaselineCitation,
  getInitialSurveyFormState,
  getInitialSimpleRatingFormState,
  getInitialCitationEvaluation,
} from "@/types/survey";
import type { Citation } from "@/types/chat";
import {
  getPendingChats,
  createSurvey,
  createSimpleRating,
  getEvaluatedChatIds,
} from "@/lib/survey-api";
import { useLastUpdate, formatLastUpdateShort } from "@/hooks/use-last-update";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { adminFetch } from "@/lib/admin-fetch";

interface SurveyModalProps {
  isOpen: boolean;
  onClose: () => void;
  evaluatorId?: string;
  fullScreen?: boolean;
}

interface ChatDetails {
  id: string;
  query: string;
  answer: string;
  citations: any[];
  experts: Expert[];
  balance: any;
  compass: any;
  timestamp: string;
}

type SurveyStep = "select" | "form" | "simple_form" | "citations" | "success";

const toTitleCase = (s: string) =>
  s.split(" ").map(w => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase()).join(" ");

const CATEGORY_ICONS: Record<string, React.ReactNode> = {
  "Qualità Risposta": <MessageSquare className="w-3.5 h-3.5" />,
  "Citazioni": <Quote className="w-3.5 h-3.5" />,
  "Bilanciamento Politico": <Scale className="w-3.5 h-3.5" />,
  "Autorità Esperti": <UserCheck className="w-3.5 h-3.5" />,
  "Valutazione Complessiva": <Star className="w-3.5 h-3.5" />,
};

const CATEGORY_SHORT_LABELS: Record<string, string> = {
  "Qualità Risposta": "Qualità",
  "Citazioni": "Citazioni",
  "Bilanciamento Politico": "Bilanciamento",
  "Autorità Esperti": "Autorità",
  "Valutazione Complessiva": "Complessiva",
};

// ─── Known political groups ordered by coalition ──────────────────────────────

const POLITICAL_GROUPS_ORDERED = [
  // Maggioranza
  { key: "FRATELLI D'ITALIA", label: "Fratelli d'Italia", coalition: "maggioranza" },
  { key: "LEGA - SALVINI PREMIER", label: "Lega - Salvini Premier", coalition: "maggioranza" },
  { key: "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE", label: "Forza Italia", coalition: "maggioranza" },
  { key: "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC, ITALIA AL CENTRO)-MAIE", label: "Noi Moderati", coalition: "maggioranza" },
  // Opposizione
  { key: "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA", label: "Partito Democratico", coalition: "opposizione" },
  { key: "MOVIMENTO 5 STELLE", label: "Movimento 5 Stelle", coalition: "opposizione" },
  { key: "ALLEANZA VERDI E SINISTRA", label: "Alleanza Verdi e Sinistra", coalition: "opposizione" },
  { key: "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE", label: "Azione", coalition: "opposizione" },
  { key: "ITALIA VIVA-CASA RIFORMISTA (IV-CR)", label: "Italia Viva", coalition: "opposizione" },
  { key: "MISTO", label: "Gruppo Misto", coalition: "altro" },
];

/**
 * Resolve an expert's raw group name to the canonical key used in POLITICAL_GROUPS_ORDERED.
 * Handles DB variations like extra suffixes or slightly different punctuation.
 */
function resolveGroupKey(groupName: string): string {
  const upper = (groupName || "MISTO").toUpperCase().trim();
  // 1. Exact match
  for (const { key } of POLITICAL_GROUPS_ORDERED) {
    if (upper === key) return key;
  }
  // 2. The expert's group starts with the canonical key (expert has extra suffix)
  for (const { key } of POLITICAL_GROUPS_ORDERED) {
    if (upper.startsWith(key)) return key;
  }
  // 3. The canonical key starts with the expert's group (expert has abbreviated name)
  for (const { key } of POLITICAL_GROUPS_ORDERED) {
    if (key.startsWith(upper)) return key;
  }
  // 4. Prefix match: strip everything after the first dash or parenthesis
  for (const { key } of POLITICAL_GROUPS_ORDERED) {
    const keyPrefix = key.split(/[-\(]/)[0].trim();
    if (keyPrefix.length >= 4 && upper.startsWith(keyPrefix)) return key;
    const expertPrefix = upper.split(/[-\(]/)[0].trim();
    if (expertPrefix.length >= 4 && key.startsWith(expertPrefix)) return key;
  }
  return upper;
}

/** Pick the best expert (highest authority_score) per political group. */
function pickOnePerGroup(experts: Expert[]): Record<string, Expert> {
  const result: Record<string, Expert> = {};
  for (const e of experts) {
    const g = resolveGroupKey(e.group || "MISTO");
    if (!result[g] || e.authority_score > result[g].authority_score) {
      result[g] = e;
    }
  }
  return result;
}

// ─── Group-by-group authority comparison panel ───────────────────────────────

function AuthorityGroupComparisonPanel({
  expertsA,
  expertsB,
  isLoadingA,
  isLoadingB,
  groupRatings,
  onGroupRatingChange,
}: {
  expertsA: Expert[];
  expertsB: Expert[];
  isLoadingA: boolean;
  isLoadingB: boolean;
  groupRatings: Record<string, number>;
  onGroupRatingChange: (group: string, value: number) => void;
}) {
  const [expertModal, setExpertModal] = useState<Expert | null>(null);

  const byGroupA = useMemo(() => pickOnePerGroup(expertsA), [expertsA]);
  const byGroupB = useMemo(() => pickOnePerGroup(expertsB), [expertsB]);

  // Canonical authority scores: same deputy → same score across A and B (use max)
  const canonicalScores: Record<string, number> = {};
  [...expertsA, ...expertsB].forEach(e => {
    const nameKey = `${e.first_name} ${e.last_name}`.toLowerCase();
    if (!canonicalScores[nameKey] || e.authority_score > canonicalScores[nameKey]) {
      canonicalScores[nameKey] = e.authority_score;
    }
  });
  const getScore = (e: Expert) =>
    canonicalScores[`${e.first_name} ${e.last_name}`.toLowerCase()] ?? e.authority_score;

  // Auto-set rating for groups that don't need manual evaluation.
  // No guard: re-runs on each data change so async-loaded experts are corrected.
  const isSamePerson = (a: Expert | null, b: Expert | null) =>
    !!a && !!b && a.id === b.id;

  useEffect(() => {
    POLITICAL_GROUPS_ORDERED.forEach(({ key }) => {
      const eA = byGroupA[key] ?? null;
      const eB = byGroupB[key] ?? null;
      if (isSamePerson(eA, eB)) {
        onGroupRatingChange(key, 0);   // same deputy → Pari
      } else if (eA && !eB) {
        onGroupRatingChange(key, -1);  // only A cited → A migliore
      } else if (!eA && eB) {
        onGroupRatingChange(key, 1);   // only B cited → B migliore
      }
    });
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [byGroupA, byGroupB]);

  if (isLoadingA || isLoadingB) {
    return (
      <div className="flex flex-1 w-full flex-col items-center justify-center text-fg-muted gap-3 min-h-0">
        <Loader2 className="w-8 h-8 animate-spin text-brand" />
        <p className="text-xs text-fg-muted">Ricerca deputati nel testo...</p>
      </div>
    );
  }

  // Classify groups: active (need manual rating) vs auto (no evaluator action needed)
  const activeGroups = POLITICAL_GROUPS_ORDERED.filter(({ key }) => {
    const eA = byGroupA[key] ?? null;
    const eB = byGroupB[key] ?? null;
    return eA && eB && !isSamePerson(eA, eB);
  });
  const autoGroups = POLITICAL_GROUPS_ORDERED.filter(({ key }) => {
    const eA = byGroupA[key] ?? null;
    const eB = byGroupB[key] ?? null;
    if (!eA && !eB) return false;
    return isSamePerson(eA, eB) || !eA || !eB;
  });

  // Progress only on groups requiring manual rating
  const ratedCount = activeGroups.filter(({ key }) => groupRatings[key] !== undefined).length;
  const allRated = ratedCount === activeGroups.length && activeGroups.length > 0;

  return (
    <div className="flex flex-col h-full min-h-0">
      {/* ── Instruction header (fixed, non-scrollable) ── */}
      <div className="px-3 py-2.5 bg-surface-muted border-b shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="flex-1 min-w-0">
            <p className="text-xs font-semibold text-fg leading-tight mb-0.5">
              Confronta gli esperti per gruppo politico
            </p>
            <p className="text-[11px] text-fg-muted leading-snug">
              Leggi i deputati citati in A e B, poi indica quale risposta ha scelto l'esperto più autorevole.
            </p>
          </div>
          {/* Progress badge */}
          <div className={cn(
            "shrink-0 flex items-center gap-1 px-2 py-1 rounded-sm text-[11px] font-semibold whitespace-nowrap",
            allRated
              ? "bg-brand-soft-strong text-brand-fg"
              : "bg-surface-muted text-fg-secondary"
          )}>
            {allRated
              ? <><Check className="w-3 h-3" /> Completo</>
              : <>{ratedCount}/{activeGroups.length} gruppi</>
            }
          </div>
        </div>
      </div>

      {/* ── Column labels ── */}
      <div className="grid grid-cols-2 gap-1 px-3 pt-2 pb-1 shrink-0 border-b bg-surface">
        <div className="text-center">
          <span className="text-xs font-semibold text-brand-fg bg-brand-soft px-3 py-0.5 rounded-sm border border-brand/25">
            Risposta A
          </span>
        </div>
        <div className="text-center">
          <span className="text-xs font-semibold text-notice-fg bg-notice-soft px-3 py-0.5 rounded-sm border border-notice/25">
            Risposta B
          </span>
        </div>
      </div>

      {/* ── Scrollable group list ── */}
      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1">
        {expertModal && (
          <ExpertModal
            expert={expertModal}
            isOpen={!!expertModal}
            onClose={() => setExpertModal(null)}
            hideScore
          />
        )}

        {/* ── Active groups: both sides have different experts ── */}
        {activeGroups.map(({ key, label }) => {
          const expertA = byGroupA[key] ?? null;
          const expertB = byGroupB[key] ?? null;
          return (
            <div key={key} className="rounded-lg mb-2 bg-surface border border-line">
              <div className="flex justify-center pt-2 pb-0.5">
                <span className="text-[11px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-sm text-fg-secondary bg-surface-muted">
                  {label}
                </span>
              </div>
              <div className="grid grid-cols-[1fr_1fr] gap-1 px-2 pt-1">
                <div className="min-w-0 overflow-hidden">
                  <AuthorityExpertMini expert={expertA!} side="A" score={getScore(expertA!)} onExpertClick={setExpertModal} />
                </div>
                <div className="min-w-0 overflow-hidden">
                  <AuthorityExpertMini expert={expertB!} side="B" score={getScore(expertB!)} onExpertClick={setExpertModal} />
                </div>
              </div>
              <div className="mx-2 mb-2 rounded-md overflow-hidden">
                <MiniGroupSlider
                  value={groupRatings[key]}
                  onChange={(v) => onGroupRatingChange(key, v)}
                />
              </div>
            </div>
          );
        })}

        {/* ── Auto-assigned groups: no evaluator action needed ── */}
        {autoGroups.length > 0 && (
          <>
            <div className="flex items-center gap-2 py-1 px-1">
              <div className="flex-1 h-px bg-surface-sunken" />
              <span className="text-[10px] text-fg-muted uppercase tracking-wider whitespace-nowrap">
                Assegnati automaticamente
              </span>
              <div className="flex-1 h-px bg-surface-sunken" />
            </div>

            {autoGroups.map(({ key, label }) => {
              const expertA = byGroupA[key] ?? null;
              const expertB = byGroupB[key] ?? null;
              const same = isSamePerson(expertA, expertB);
              const autoBadge = same
                ? "= Stesso deputato"
                : expertA
                  ? "✓ Punto a A"
                  : "✓ Punto a B";
              const badgeColor = same
                ? "bg-surface-muted text-fg-muted"
                : expertA
                  ? "bg-brand-soft text-brand-fg"
                  : "bg-notice-soft text-notice-fg";

              return (
                <div key={key} className="rounded-lg mb-2 bg-surface-muted opacity-60">
                  <div className="flex justify-center items-center gap-1.5 pt-2 pb-0.5">
                    <span className="text-[11px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-sm text-fg-muted bg-surface-muted">
                      {label}
                    </span>
                  </div>
                  <div className="grid grid-cols-[1fr_1fr] gap-1 px-2 pt-1 pb-2">
                    <div className="min-w-0 overflow-hidden">
                      {expertA
                        ? <AuthorityExpertMini expert={expertA} side="A" score={getScore(expertA)} />
                        : <ExpertAbsent side="A" />}
                    </div>
                    <div className="min-w-0 overflow-hidden">
                      {expertB
                        ? <AuthorityExpertMini expert={expertB} side="B" score={getScore(expertB)} />
                        : <ExpertAbsent side="B" />}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

/** Compact expert display for the group comparison panel. */
function AuthorityExpertMini({ expert, side, score, onExpertClick }: {
  expert: Expert;
  side: "A" | "B";
  score: number;
  onExpertClick?: (expert: Expert) => void;
}) {
  const groupConfig = config.politicalGroups[expert.group as keyof typeof config.politicalGroups];
  const groupColor = groupConfig?.color || "var(--ink-600)";
  const isA = side === "A";

  const primaryCommittee = expert.committees?.[0] || expert.committee || null;
  const displayName = `${toTitleCase(expert.first_name || "")} ${toTitleCase(expert.last_name || "")}`.trim();

  return (
    <div
      className={cn(
        "flex items-start gap-2 py-2 px-2 rounded-md w-full transition-colors",
        isA ? "flex-row-reverse text-right" : "flex-row text-left",
        onExpertClick && "cursor-pointer hover:bg-surface-muted"
      )}
      onClick={() => onExpertClick?.({ ...expert, authority_score: score })}
    >
      {/* Avatar */}
      {expert.photo ? (
        <img
          src={expert.photo}
          alt={displayName}
          className="h-11 w-11 shrink-0 rounded-full object-cover ring-2 ring-surface"
        />
      ) : (
        <div
          className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white ring-2 ring-surface"
          style={{ backgroundColor: groupColor }}
        >
          {expert.first_name[0]}{expert.last_name[0]}
        </div>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        {/* Name */}
        <p className="text-sm font-bold text-fg leading-snug truncate">
          {displayName}
        </p>

        {/* Authority signals */}
        <div className={cn("mt-1 flex flex-col gap-0.5", isA ? "items-end" : "items-start")}>
          {expert.institutional_role && (
            <span className="text-[11px] font-semibold text-fg-secondary leading-none truncate max-w-full inline-block">
              {expert.institutional_role}
            </span>
          )}
          {primaryCommittee && (
            <span className="text-[11px] text-fg-muted leading-snug truncate max-w-full block">
              {primaryCommittee.length > 32 ? primaryCommittee.slice(0, 31) + "…" : primaryCommittee}
            </span>
          )}
          {expert.profession && (
            <span className="text-[11px] text-fg-muted leading-snug truncate max-w-full block italic">
              {expert.profession.length > 36 ? expert.profession.slice(0, 35) + "…" : expert.profession}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}

/** Placeholder shown when no expert was cited for a given side. */
function ExpertAbsent({ side }: { side: "A" | "B" }) {
  const isA = side === "A";
  return (
    <div className={cn(
      "flex items-center justify-center py-3 px-2 rounded-md w-full h-full",
      "border border-dashed border-line",
      isA ? "text-right" : "text-left",
    )}>
      <span className="text-[11px] text-fg-muted italic">
        Nessun esperto citato
      </span>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

// ─── Mini per-group A/B preference toggle ─────────────────────────────────────

// -1 = A migliore, 0 = Equivalenti, 1 = B migliore
function MiniGroupSlider({
  value,
  onChange,
}: {
  value: number | undefined;
  onChange: (v: number) => void;
}) {
  const options = [
    { v: -1, label: "A migliore", activeClass: "bg-brand text-on-brand border-brand" },
    { v:  0, label: "Pari",       activeClass: "bg-brand text-on-brand border-brand" },
    { v:  1, label: "B migliore", activeClass: "bg-brand text-on-brand border-brand" },
  ] as const;

  const isUnanswered = value === undefined;

  return (
    <div className={cn(
      "w-full px-2 pt-2 pb-2 border-t border-dashed transition-colors",
      isUnanswered
        ? "border-line-strong"
        : "border-line"
    )}>
      <p className="text-[10px] text-center mb-1.5 leading-tight text-fg-muted">
        {isUnanswered ? "Qual è il deputato più autorevole su questo tema?" : "Valutazione assegnata:"}
      </p>
      <div className="flex items-stretch gap-1.5">
        {options.map((opt) => {
          const isActive = value === opt.v;
          return (
            <button
              key={opt.v}
              type="button"
              onClick={() => onChange(opt.v)}
              className={cn(
                "flex-1 py-2 rounded-full border text-xs font-semibold text-center",
                "transition-all duration-150 cursor-pointer select-none",
                isActive
                  ? opt.activeClass
                  : "bg-surface border-line-strong text-fg-secondary hover:border-line-control hover:bg-surface-muted"
              )}
            >
              {opt.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────

// ─── Per-category instruction text ────────────────────────────────────────────
const CATEGORY_INSTRUCTIONS: Record<string, { title: string; description: string }> = {
  "Qualità Risposta": {
    title: "Come valutare la qualità",
    description: "Assegna da 1 a 5 stelle sia alla Risposta A che alla Risposta B. Il punteggio riflette la qualità percepita di quella risposta per questa dimensione specifica.",
  },
  "Citazioni": {
    title: "Come valutare le citazioni",
    description: "Confronta le citazioni parlamentari: considera se supportano la risposta, se l'attribuzione a deputato, data e commissione è corretta.",
  },
  "Bilanciamento Politico": {
    title: "Come valutare il bilanciamento",
    description: "Considera se ciascuna risposta dà voce in modo equo alle diverse posizioni politiche tra maggioranza e opposizione.",
  },
  "Autorità Esperti": {
    title: "Questa sezione richiede due azioni",
    description: "",
  },
  "Valutazione Complessiva": {
    title: "Valutazione finale",
    description: "Esprimi un giudizio complessivo su ciascuna risposta. Indica poi se consiglieresti questo sistema ai tuoi colleghi.",
  },
};


// ─── Section splitting ────────────────────────────────────────────────────────

interface TextSection {
  heading: string;
  content: string;
}

/** Normalize a heading string for comparison (lowercase, trim, normalise apostrophes). */
function normH(h: string): string {
  return h.toLowerCase().trim().replace(/['\u2019\u2018\u02bc]/g, "'").replace(/\s+/g, " ");
}

/** Known canonical section titles in display order. */
const CANONICAL_TITLES = [
  "Introduzione",
  "Posizione del Governo",
  "Posizioni della Maggioranza",
  "Posizioni dell\u2019Opposizione",
  "Analisi Trasversale",
];
const CANONICAL_NORMS = CANONICAL_TITLES.map(normH);

/**
 * Split a response text into sections by the known canonical titles.
 * Works regardless of whether the title is formatted as `## Title`, `**Title**`,
 * or plain text on its own line — because the user confirmed titles are always
 * the same fixed set.
 */
function parseIntoSections(text: string): TextSection[] {
  const sections: TextSection[] = [];
  const lines = text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n");

  let currentHeading = "Introduzione"; // default first section
  let currentContent: string[] = [];
  let foundFirst = false;

  for (const line of lines) {
    const trimmed = line.trim();
    // Strip any markdown prefix to get the bare title candidate
    const bare = trimmed.replace(/^#{1,6}\s+/, "").replace(/^\*\*(.+)\*\*$/, "$1").trim();
    const isKnownTitle = CANONICAL_NORMS.includes(normH(bare));

    if (isKnownTitle) {
      if (foundFirst) {
        // Save previous section
        sections.push({ heading: currentHeading, content: currentContent.join("\n").trim() });
      }
      // Resolve display heading from canonical list (preserves correct apostrophe)
      const canonical = CANONICAL_TITLES[CANONICAL_NORMS.indexOf(normH(bare))];
      currentHeading = canonical ?? bare;
      currentContent = [];
      foundFirst = true;
    } else {
      if (!foundFirst && trimmed) foundFirst = true; // pre-heading content → treat as intro
      currentContent.push(line);
    }
  }
  if (currentContent.join("\n").trim() || foundFirst) {
    sections.push({ heading: currentHeading, content: currentContent.join("\n").trim() });
  }
  return sections;
}

/**
 * Align two section arrays side-by-side by heading name.
 * Rows follow canonical order; missing sections show a placeholder.
 */
function alignSections(
  sectionsA: TextSection[],
  sectionsB: TextSection[],
): Array<{ a: TextSection | null; b: TextSection | null; heading: string }> {
  const mapA = new Map(sectionsA.map((s) => [normH(s.heading), s]));
  const mapB = new Map(sectionsB.map((s) => [normH(s.heading), s]));

  const seen = new Set<string>();
  const rows: Array<{ a: TextSection | null; b: TextSection | null; heading: string }> = [];

  const add = (k: string, display: string) => {
    if (seen.has(k)) return;
    seen.add(k);
    rows.push({ a: mapA.get(k) ?? null, b: mapB.get(k) ?? null, heading: display });
  };

  // Canonical order first
  CANONICAL_TITLES.forEach((t) => {
    const k = normH(t);
    if (mapA.has(k) || mapB.has(k)) add(k, t);
  });
  // Any extra sections not in canonical list
  [...sectionsA, ...sectionsB].forEach((s) => add(normH(s.heading), s.heading));

  return rows;
}

export function SurveyModal({ isOpen, onClose, evaluatorId, fullScreen }: SurveyModalProps) {
  const [step, setStep] = useState<SurveyStep>("select");
  const [pendingChats, setPendingChats] = useState<PendingChat[]>([]);
  const [evaluatedIds, setEvaluatedIds] = useState<Set<string>>(new Set());
  const [selectedChat, setSelectedChat] = useState<PendingChat | null>(null);
  const [chatDetails, setChatDetails] = useState<ChatDetails | null>(null);

  // A/B form state
  const [formState, setFormState] = useState<SurveyFormState>(getInitialSurveyFormState());
  const [localAbAssignment, setLocalAbAssignment] = useState<Record<string, string> | null>(null);
  const [currentCategory, setCurrentCategory] = useState(0);

  // Simple rating form state
  const [simpleFormState, setSimpleFormState] = useState<SimpleRatingFormState>(getInitialSimpleRatingFormState());

  const [baselineExperts, setBaselineExperts] = useState<Expert[]>([]);
  const [isLoadingBaselineExperts, setIsLoadingBaselineExperts] = useState(false);
  const [systemExperts, setSystemExperts] = useState<Expert[]>([]);
  const [isLoadingSystemExperts, setIsLoadingSystemExperts] = useState(false);
  const [sampledCitationsA, setSampledCitationsA] = useState<Citation[]>([]);
  const [groupAuthorityRatings, setGroupAuthorityRatings] = useState<Record<string, number>>({});

  const [isLoading, setIsLoading] = useState(false);
  const [isLoadingDetails, setIsLoadingDetails] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [mobileSimpleTab, setMobileSimpleTab] = useState<"response" | "form">("response");
  const [mobileABTab, setMobileABTab] = useState<"A" | "B" | "valuta">("A");
  const [hasConfirmedReading, setHasConfirmedReading] = useState(false);

  // Same date/cache as the Sidebar footer: last `make update-data` run
  const lastUpdate = formatLastUpdateShort(useLastUpdate());


  // Group A/B questions by category (exclude overall_satisfaction - handled separately)
  const categories = SURVEY_QUESTIONS.filter(q => q.id !== "overall_satisfaction").reduce((acc, q) => {
    if (!acc.find((c) => c.name === q.category)) {
      acc.push({ name: q.category, questions: [] });
    }
    acc.find((c) => c.name === q.category)?.questions.push(q);
    return acc;
  }, [] as { name: string; questions: typeof SURVEY_QUESTIONS }[]);

  categories.push({
    name: "Valutazione Complessiva",
    questions: SURVEY_QUESTIONS.filter(q => q.id === "overall_satisfaction"),
  });

  // Get response A and B based on localAbAssignment
  const getResponseA = (): string => {
    if (!chatDetails || !localAbAssignment || !selectedChat) return chatDetails?.answer || "";
    return localAbAssignment["A"] === "system"
      ? chatDetails.answer
      : (selectedChat.baseline_answer || "");
  };

  const getResponseB = (): string => {
    if (!chatDetails || !localAbAssignment || !selectedChat) return "";
    return localAbAssignment["B"] === "system"
      ? chatDetails.answer
      : (selectedChat.baseline_answer || "");
  };

  // Get citation data for a given assignment slot ("system" | "baseline")
  const getCitationsForAssignment = (
    slot: string,
  ): { quote: string; verbatim_verified?: boolean }[] => {
    if (slot === "baseline") {
      return (selectedChat?.baseline_citations ?? []).map((c: BaselineCitation) => ({
        quote: c.quote,
        verbatim_verified: c.verbatim_verified,
      }));
    }
    // system: citations are verified by design (surgeon.py validates before including them)
    return (chatDetails?.citations ?? [])
      .map((c) => ({ quote: c.quote_text ?? "", verbatim_verified: true }))
      .filter((c) => c.quote.length > 0);
  };

  const getCitationsA = () =>
    localAbAssignment ? getCitationsForAssignment(localAbAssignment["A"]) : [];
  const getCitationsB = () =>
    localAbAssignment ? getCitationsForAssignment(localAbAssignment["B"]) : [];

  // Load pending chats
  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [pendingRes, evaluatedRes] = await Promise.all([
        getPendingChats(evaluatorId),
        getEvaluatedChatIds(evaluatorId),
      ]);
      setPendingChats(pendingRes.pending);
      setEvaluatedIds(new Set(evaluatedRes.chat_ids));
    } catch (err) {
      setError("Errore nel caricamento delle conversazioni");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, [evaluatorId]);

  // Load chat details (system answer text)
  const loadChatDetails = useCallback(async (chatId: string) => {
    setIsLoadingDetails(true);
    try {
      const res = await fetch(`${config.api.baseUrl}/history/${chatId}`);
      if (!res.ok) throw new Error("Failed to load chat details");
      const data = await res.json();
      setChatDetails(data);
      return data;
    } catch (err) {
      console.error(err);
      setError("Errore nel caricamento dei dettagli");
      return null;
    } finally {
      setIsLoadingDetails(false);
    }
  }, []);

  // Load system experts: deputies actually mentioned in the system response text.
  // Reuses the same baseline-experts endpoint for consistency.
  const loadSystemExperts = useCallback(async (chatId: string, answerText: string) => {
    setIsLoadingSystemExperts(true);
    setSystemExperts([]);
    try {
      const res = await adminFetch(`${config.api.baseUrl}/history/${chatId}/baseline-experts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseline_text: answerText }),
      });
      if (!res.ok) throw new Error("Failed to load system experts");
      const data = await res.json();
      setSystemExperts(data.experts ?? []);
    } catch (err) {
      console.error("Failed to load system experts:", err);
      setSystemExperts([]);
    } finally {
      setIsLoadingSystemExperts(false);
    }
  }, []);

  // Load baseline experts: deputies mentioned in baseline text with their authority scores.
  // Passes the baseline text in the POST body so the backend can always find names,
  // even for older chats where c.baseline_answer may be empty in Neo4j.
  const loadBaselineExperts = useCallback(async (chatId: string, baselineText: string) => {
    setIsLoadingBaselineExperts(true);
    setBaselineExperts([]);
    try {
      const res = await adminFetch(`${config.api.baseUrl}/history/${chatId}/baseline-experts`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ baseline_text: baselineText }),
      });
      if (!res.ok) throw new Error("Failed to load baseline experts");
      const data = await res.json();
      setBaselineExperts(data.experts ?? []);
    } catch (err) {
      console.error("Failed to load baseline experts:", err);
      setBaselineExperts([]);
    } finally {
      setIsLoadingBaselineExperts(false);
    }
  }, []);

  useEffect(() => {
    if (isOpen) {
      loadData();
      setStep("select");
      setSelectedChat(null);
      setChatDetails(null);
      setBaselineExperts([]);
      setSystemExperts([]);
      setFormState(getInitialSurveyFormState());
      setSimpleFormState(getInitialSimpleRatingFormState());
      setLocalAbAssignment(null);
      setCurrentCategory(0);
      setSampledCitationsA([]);
    }
  }, [isOpen, loadData]);

  // Handle chat selection — branch on evaluation_type
  const handleSelectChat = async (chat: PendingChat) => {
    setSelectedChat(chat);
    setError(null);

    if (chat.evaluation_type === "ab") {
      // Generate a random A/B assignment for this session
      const assignment = Math.random() < 0.5
        ? { A: "system", B: "baseline" }
        : { A: "baseline", B: "system" };
      setLocalAbAssignment(assignment);
      setFormState(getInitialSurveyFormState());
      setCurrentCategory(0);
      setMobileABTab("A");
      setHasConfirmedReading(false);
      setBaselineExperts([]);
      setSystemExperts([]);
      setStep("form");
      // Load system response details first (we need the answer text to extract system experts).
      // Baseline experts: use pre-computed cache if available, otherwise fall back to API.
      let chatData: { answer?: string; experts?: Expert[]; citations?: any[] } | null = null;
      if (chat.baseline_experts && chat.baseline_experts.length > 0) {
        setBaselineExperts(chat.baseline_experts as Expert[]);
        chatData = await loadChatDetails(chat.id);
      } else {
        [chatData] = await Promise.all([
          loadChatDetails(chat.id),
          loadBaselineExperts(chat.id, chat.baseline_answer || ""),
        ]);
      }
      // System experts: match cited deputies (from chatData.citations) to stored experts
      // by name so the authority panel shows the authority of the deputy ACTUALLY CITED,
      // not the top-retrieved expert for that party.
      if (chatData?.experts && chatData.experts.length > 0) {
        // Build "firstname_lastname" → Expert lookup from query-specific stored experts.
        const expertByName = new Map<string, Expert>();
        for (const e of chatData.experts as Expert[]) {
          const key = `${(e.first_name || "").toLowerCase()}_${(e.last_name || "").toLowerCase()}`;
          if (key !== "_") expertByName.set(key, e);
        }

        // Match each unique cited deputy to a stored expert by name.
        const citedExperts: Expert[] = [];
        const seenKeys = new Set<string>();
        for (const cit of (chatData.citations ?? []) as any[]) {
          const key = `${(cit.deputy_first_name || "").toLowerCase()}_${(cit.deputy_last_name || "").toLowerCase()}`;
          if (key !== "_" && !seenKeys.has(key)) {
            seenKeys.add(key);
            const expert = expertByName.get(key);
            if (expert) citedExperts.push(expert);
          }
        }

        // For cited groups that have no matched expert (cited deputy not in chatData.experts),
        // add the stored top expert for that group as a proxy. This keeps the survey panel
        // consistent with the detail view, which also falls back to the stored top expert.
        const coveredGroupKeys = new Set(
          citedExperts.map((e) => resolveGroupKey(e.group || "MISTO"))
        );
        const supplementaryExperts: Expert[] = [];
        const uniqueCitedGroupKeys = new Set(
          (chatData.citations ?? [])
            .map((c: any) => resolveGroupKey(c.group || c.party || "MISTO"))
            .filter((k: string) => k !== "" && k !== "GOVERNO")
        );
        for (const groupKey of uniqueCitedGroupKeys) {
          if (!coveredGroupKeys.has(groupKey)) {
            const proxy = (chatData.experts as Expert[])
              .filter((e) => resolveGroupKey(e.group || "MISTO") === groupKey)
              .sort((a, b) => b.authority_score - a.authority_score)[0];
            if (proxy) supplementaryExperts.push(proxy);
          }
        }

        const allSystemExperts = [...citedExperts, ...supplementaryExperts];
        if (allSystemExperts.length > 0) {
          setSystemExperts(allSystemExperts);
        } else {
          // Final fallback: use any expert from cited parties.
          const citedGroups = new Set(
            (chatData.citations ?? [])
              .map((c: any) => c.group || c.party || "")
              .filter(Boolean)
          );
          setSystemExperts(
            citedGroups.size > 0
              ? (chatData.experts as Expert[]).filter((e) => citedGroups.has(e.group))
              : (chatData.experts as Expert[])
          );
        }
      } else if (chatData?.answer) {
        // Fallback: text-match + authority computation for older chats without stored experts.
        await loadSystemExperts(chat.id, chatData.answer);
      }
    } else {
      // Simple Likert rating
      setSimpleFormState(getInitialSimpleRatingFormState());
      setMobileSimpleTab("response");
      setStep("simple_form");
      await loadChatDetails(chat.id);
    }
  };

  // A/B form helpers
  const inferPreference = (a: number, b: number): "A" | "B" | "equal" | "" => {
    if (a === 0 || b === 0) return "";
    if (a > b) return "A";
    if (b > a) return "B";
    return "equal";
  };

  const handleABRatingChange = (
    dimension: ABDimension,
    field: keyof ABRating,
    value: number | string
  ) => {
    setFormState((prev) => {
      const cur = prev[dimension];
      const newA = field === "rating_a" ? (value as number) : cur.rating_a;
      const newB = field === "rating_b" ? (value as number) : cur.rating_b;
      return {
        ...prev,
        [dimension]: {
          ...cur,
          [field]: value,
          // Auto-infer preference when a numeric rating changes
          preference: (field === "rating_a" || field === "rating_b")
            ? inferPreference(newA, newB)
            : cur.preference,
        },
      };
    });
  };

  const isABRatingComplete = (rating: ABRating): boolean => {
    return rating.rating_a > 0 && rating.rating_b > 0;
  };

  const isCategoryComplete = (catIndex: number) => {
    const cat = categories[catIndex];
    if (cat.name === "Valutazione Complessiva") {
      return formState.overall_satisfaction_a > 0 &&
             formState.overall_satisfaction_b > 0;
    }
    const ratingsComplete = cat.questions.every((q) => {
      const rating = formState[q.id as ABDimension];
      return isABRatingComplete(rating);
    });
    if (cat.name === "Autorità Esperti") {
      const expA = localAbAssignment?.["A"] === "system" ? (systemExperts) : baselineExperts;
      const expB = localAbAssignment?.["B"] === "system" ? (systemExperts) : baselineExperts;
      const byGroupA = pickOnePerGroup(expA);
      const byGroupB = pickOnePerGroup(expB);
      const groupsWithExperts = POLITICAL_GROUPS_ORDERED
        .filter(({ key }) => byGroupA[key] || byGroupB[key])
        .map(({ key }) => key);
      const groupRatingsComplete = groupsWithExperts.every(
        (key) => groupAuthorityRatings[key] !== undefined
      );
      return ratingsComplete && groupRatingsComplete;
    }
    return ratingsComplete;
  };

  const isFormComplete = () => {
    const dimensionsComplete = AB_DIMENSIONS.every((dim) =>
      isABRatingComplete(formState[dim])
    );
    const overallComplete = formState.overall_satisfaction_a > 0 &&
                           formState.overall_satisfaction_b > 0;
    return dimensionsComplete && overallComplete;
  };

  const completionPercentage = () => {
    const total = AB_DIMENSIONS.length + 1;
    let filled = 0;
    for (const dim of AB_DIMENSIONS) {
      if (isABRatingComplete(formState[dim])) filled++;
    }
    if (formState.overall_satisfaction_a > 0 && formState.overall_satisfaction_b > 0) {
      filled++;
    }
    return Math.round((filled / total) * 100);
  };

  const goToNextCategory = () => {
    if (currentCategory < categories.length - 1) {
      setCurrentCategory((prev) => prev + 1);
    }
  };

  const goToPrevCategory = () => {
    if (currentCategory > 0) {
      setCurrentCategory((prev) => prev - 1);
    }
  };

  const handleGoToCitations = () => {
    if (!isFormComplete()) return;
    // Always use system citations (chatDetails.citations), ignoring A/B assignment.
    // Sample up to 3 random citations to keep the evaluation short.
    const allSystemCitations: Citation[] = chatDetails?.citations ?? [];
    const sampled = allSystemCitations.length <= 3
      ? allSystemCitations
      : [...allSystemCitations].sort(() => Math.random() - 0.5).slice(0, 3);
    setSampledCitationsA(sampled);
    if (formState.citation_evaluations_a.length === 0 && sampled.length > 0) {
      setFormState(prev => ({
        ...prev,
        citation_evaluations_a: sampled.map(c => getInitialCitationEvaluation(c.chunk_id)),
        citation_evaluations_b: [],
      }));
    }
    setStep("citations");
  };

  // Submit A/B survey
  const handleSubmit = async () => {
    if (!selectedChat || !isFormComplete()) return;

    setIsSubmitting(true);
    setError(null);

    try {
      const validCitEvalsA = formState.citation_evaluations_a.filter(
        ce => ce.relevance > 0 && ce.faithfulness > 0 && ce.informativeness > 0 && ce.attribution !== ""
      );
      const validCitEvalsB = formState.citation_evaluations_b.filter(
        ce => ce.relevance > 0 && ce.faithfulness > 0 && ce.informativeness > 0 && ce.attribution !== ""
      );

      // Compute baseline authority avg from baseline experts
      const baselineExpertList = baselineExperts.filter(e => e.authority_score > 0);
      const baselineAuthAvg = baselineExpertList.length > 0
        ? baselineExpertList.reduce((sum, e) => sum + e.authority_score, 0) / baselineExpertList.length
        : undefined;

      await createSurvey({
        chat_id: selectedChat.id,
        answer_quality: formState.answer_quality,
        answer_clarity: formState.answer_clarity,
        answer_completeness: formState.answer_completeness,
        citations_relevance: formState.citations_relevance,
        balance_perception: formState.balance_perception,
        balance_fairness: formState.balance_fairness,
        source_relevance: formState.source_relevance,
        source_authority: formState.source_authority,
        source_coverage: formState.source_coverage,
        overall_satisfaction_a: formState.overall_satisfaction_a,
        overall_satisfaction_b: formState.overall_satisfaction_b,
        overall_preference: formState.overall_preference as "A" | "B" | "equal",
        would_recommend: formState.would_recommend,
        feedback_positive: formState.feedback_positive || undefined,
        feedback_improvement: formState.feedback_improvement || undefined,
        citation_evaluations_a: validCitEvalsA,
        citation_evaluations_b: validCitEvalsB,
        // Pass evaluation_set assignment for de-blinding
        ab_assignment: localAbAssignment || undefined,
        evaluation_set_topic: selectedChat.matched_topic || undefined,
        evaluator_id: evaluatorId || undefined,
        baseline_authority_avg: baselineAuthAvg,
        // Per-group authority votes from the Autorità panel
        group_authority_votes: Object.keys(groupAuthorityRatings).length > 0 ? groupAuthorityRatings : undefined,
      });

      setStep("success");
    } catch (err: any) {
      setError(err.message || "Errore nell'invio della valutazione");
    } finally {
      setIsSubmitting(false);
    }
  };

  // Submit simple Likert rating
  const handleSimpleSubmit = async () => {
    if (!selectedChat) return;
    const { answer_clarity, answer_quality, balance_perception, balance_fairness } = simpleFormState;
    if (!answer_clarity || !answer_quality || !balance_perception || !balance_fairness) {
      setError("Compila tutte le valutazioni prima di inviare");
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await createSimpleRating({
        chat_id: selectedChat.id,
        answer_clarity,
        answer_quality,
        balance_perception,
        balance_fairness,
        feedback: simpleFormState.feedback || undefined,
        evaluator_id: evaluatorId || undefined,
      });
      setStep("success");
    } catch (err: any) {
      setError(err.message || "Errore nell'invio della valutazione");
    } finally {
      setIsSubmitting(false);
    }
  };

  const isSimpleFormComplete = () => {
    const { answer_clarity, answer_quality, balance_perception, balance_fairness } = simpleFormState;
    return answer_clarity > 0 && answer_quality > 0 && balance_perception > 0 && balance_fairness > 0;
  };

  // Render inline markdown: bold names + citation highlighting.
  const renderInline = (
    text: string,
    verifiedSet: Set<string>,
    unverifiedSet: Set<string>,
    hasCitationData: boolean,
    allVerbatim?: boolean,
  ): React.ReactNode => {
    const parts: React.ReactNode[] = [];
    // Match: **bold**, [«quote»](url), «quote»[CIT:id], or bare «quote»
    const pattern = /\*\*([^*]+)\*\*|\[«([^»]+)»\]\([^)]+\)|«([^»]+)»(?:\s*\[CIT:[^\]]+\])?/g;
    let lastIndex = 0;
    let key = 0;
    let match: RegExpExecArray | null;
    while ((match = pattern.exec(text)) !== null) {
      if (match.index > lastIndex) {
        parts.push(<span key={key++}>{text.slice(lastIndex, match.index)}</span>);
      }
      if (match[1] !== undefined) {
        // **bold** → deputy name
        parts.push(
          <strong key={key++} className="font-semibold text-fg">
            {match[1]}
          </strong>
        );
      } else {
        // citation (group 2 = link form, group 3 = bare/CIT form)
        const quote = match[2] ?? match[3];
        const isVerified = allVerbatim || verifiedSet.has(quote.toLowerCase().trim());
        const isUnverified = !allVerbatim && unverifiedSet.has(quote.toLowerCase().trim());
        if (isVerified) {
          parts.push(
            <span
              key={key++}
              className="underline decoration-brand decoration-2 underline-offset-2"
              title="Verbatim: testo identico al verbale parlamentare"
            >
              «{quote}»
            </span>
          );
        } else if (isUnverified) {
          parts.push(
            <span
              key={key++}
              className="underline decoration-notice decoration-2 decoration-dashed underline-offset-2"
              title="Parafrasi: attribuita al deputato, ma rielaborata, non corrisponde parola per parola al verbale"
            >
              «{quote}»
            </span>
          );
        } else if (hasCitationData) {
          parts.push(
            <span
              key={key++}
              className="underline decoration-line-control decoration-1 underline-offset-2"
              title="Citazione"
            >
              «{quote}»
            </span>
          );
        } else {
          parts.push(<span key={key++}>«{quote}»</span>);
        }
      }
      lastIndex = match.index + match[0].length;
    }
    if (lastIndex < text.length) {
      parts.push(<span key={key++}>{text.slice(lastIndex)}</span>);
    }
    return parts.length === 1 ? parts[0] : <>{parts}</>;
  };

  // Render a response text with rich inline formatting.
  // side: "a" = blue headings, "b" = amber headings (omit for neutral)
  // citations: list of {quote, verbatim_verified}
  // allVerbatim: if true, every «quote» in the text is rendered green without text matching
  //              (used for system responses, which are all verified by design)
  const renderContent = (
    text: string,
    citations?: { quote: string; verbatim_verified?: boolean }[],
    side?: "a" | "b",
    allVerbatim?: boolean,
  ) => {
    // Normalize keys to lowercase+trim so case differences (e.g. "Siamo" vs "siamo") don't break lookups
    const normQ = (s: string) => s.toLowerCase().trim();
    const verifiedSet = new Set(
      citations?.filter((c) => c.verbatim_verified === true).map((c) => normQ(c.quote)) ?? []
    );
    const unverifiedSet = new Set(
      citations?.filter((c) => c.verbatim_verified === false).map((c) => normQ(c.quote)) ?? []
    );
    const hasCitationData = (citations?.length ?? 0) > 0;

    const headingClass = side === "a"
      ? "text-[11px] font-semibold uppercase tracking-wide text-brand-fg mt-4 mb-2 pb-1 border-b border-brand/20 first:mt-0"
      : side === "b"
      ? "text-[11px] font-semibold uppercase tracking-wide text-notice-fg mt-4 mb-2 pb-1 border-b border-notice/20 first:mt-0"
      : "text-[11px] font-semibold uppercase tracking-wide text-fg-muted mt-4 mb-2 pb-1 border-b border-line first:mt-0";

    // Normalise line endings; remove technical refs
    const lines = text
      .replace(/\r\n/g, "\n").replace(/\r/g, "\n")
      .replace(/\(leg\d+_[^)]+\)/g, "")
      .replace(/^[-*]\s+/gm, "• ")
      .split("\n");

    const elements: React.ReactNode[] = [];
    let i = 0;
    while (i < lines.length) {
      const raw = lines[i];
      const trimmed = raw.trim();

      if (!trimmed) {
        if (elements.length > 0) {
          elements.push(<div key={`sp-${i}`} className="h-2" />);
        }
      } else {
        // Detect ## heading OR standalone **bold** heading line
        const hashMatch = trimmed.match(/^#{1,6}\s+(.+)/);
        const boldMatch = !hashMatch ? trimmed.match(/^\*\*([^*]+)\*\*\s*$/) : null;
        const headingText = hashMatch?.[1]?.trim() ?? boldMatch?.[1]?.trim() ?? null;

        if (headingText) {
          elements.push(
            <p key={i} className={headingClass}>
              {headingText}
            </p>
          );
        } else {
          // Strip single-star italic markers but preserve double-star bold markers
          const cleaned = trimmed.replace(/(?<!\*)\*(?!\*)([^*]+?)(?<!\*)\*(?!\*)/g, "$1");
          elements.push(
            <p key={i} className="text-sm text-foreground leading-relaxed mb-1">
              {renderInline(cleaned, verifiedSet, unverifiedSet, hasCitationData, allVerbatim)}
            </p>
          );
        }
      }
      i++;
    }
    return <>{elements}</>;
  };

  // Determine dialog title based on step
  const dialogTitle = () => {
    switch (step) {
      case "simple_form": return "Valutazione Risposta";
      case "citations": return "Valutazione Citazioni";
      default: return "Valutazione A/B";
    }
  };

  return (
    <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
      <DialogContent
        showCloseButton={!fullScreen}
        className={cn(
          "p-0 gap-0 overflow-hidden flex flex-col",
          fullScreen
            ? "!fixed !top-0 !left-0 !translate-x-0 !translate-y-0 !w-screen !max-w-none !h-screen !max-h-none !rounded-none !border-0 !m-0"
            : (step === "form" || step === "citations") && "sm:!max-w-[95vw]"
        )}
        style={
          fullScreen
            ? undefined
            : step === "form"
            ? { width: "1600px", maxWidth: "95vw", height: "95vh", maxHeight: "95vh" }
            : step === "simple_form"
            ? { width: "900px", maxWidth: "95vw", height: "90vh", maxHeight: "90vh" }
            : step === "citations"
            ? { width: "700px", maxWidth: "95vw", height: "95vh", maxHeight: "95vh" }
            : { maxWidth: "42rem", maxHeight: "90vh" }
        }
      >
        <DialogHeader className={cn(
          "border-b shrink-0",
          fullScreen && step === "select"
            ? "px-8 py-4 bg-surface border-line"
            : "px-6 py-4 bg-surface border-line"
        )}>
          {fullScreen && step === "select" ? (
            /* ── Full-screen select: branded navbar ── */
            <div className="flex items-center justify-between">
              {/* Logo + brand */}
              <DialogTitle className="flex items-center gap-3 text-fg">
                <svg viewBox="56 184 400 224" className="w-10 h-6 shrink-0 text-brand" aria-hidden="true">
                  <path d="M 80 384 A 176 176 0 0 1 432 384" fill="none" stroke="white" strokeWidth="32" strokeLinecap="round" opacity="0.4"/>
                  <path d="M 136 384 A 120 120 0 0 1 376 384" fill="none" stroke="white" strokeWidth="32" strokeLinecap="round" opacity="0.65"/>
                  <path d="M 192 384 A 64 64 0 0 1 320 384" fill="none" stroke="white" strokeWidth="32" strokeLinecap="round" opacity="0.9"/>
                </svg>
                <span className="text-lg font-semibold tracking-tight">Parliament<span className="text-brand-fg">RAG</span></span>
                <span className="text-fg-faint font-light text-xl select-none">·</span>
                <span className="text-sm font-normal text-fg-muted">Valutazione Sistema</span>
              </DialogTitle>
              {/* Greeting */}
              <div className="flex flex-col items-end gap-0.5">
                {evaluatorId && (
                  <p className="text-sm text-fg-muted">
                    Valutatore: <span className="font-semibold text-fg">{toTitleCase(evaluatorId)}</span>
                  </p>
                )}
                <p className="text-xs text-fg-muted">I dati parlamentari sono aggiornati al <strong className="text-fg-secondary">{lastUpdate ?? "…"}</strong></p>
              </div>
            </div>
          ) : (
            /* ── Normal modal header ── */
            <>
              <DialogTitle className="flex items-center gap-2 text-lg">
                <ClipboardCheck className="w-5 h-5 text-brand" />
                {dialogTitle()}
              </DialogTitle>
              {step === "form" && (
                <div className="flex items-center gap-3 mt-2">
                  <div className="flex-1 h-2 bg-surface-sunken rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full bg-brand transition-all duration-300"
                      style={{ width: `${completionPercentage()}%` }}
                    />
                  </div>
                  <span className="text-sm font-medium text-fg-secondary">
                    {completionPercentage()}%
                  </span>
                </div>
              )}
              {step === "citations" && (
                <p className="text-sm text-fg-muted mt-1">
                  Valuta ogni citazione singolarmente (opzionale - puoi saltare)
                </p>
              )}
            </>
          )}
        </DialogHeader>

        {/* Step: Select Chat */}
        {step === "select" && (
          <div className={cn("flex flex-col", fullScreen ? "flex-1 min-h-0" : "h-[60vh]")}>
            {/* Greeting / refresh bar — hidden in fullScreen (greeting already in header) */}
            {!fullScreen && (
              <div className="px-6 py-3 bg-surface-muted border-b">
                <div className="flex items-center justify-between">
                  <p className="text-sm text-fg-secondary">
                    {evaluatorId ? (
                      <>Ciao <span className="font-semibold text-fg">{toTitleCase(evaluatorId)}</span>, seleziona una conversazione da valutare</>
                    ) : (
                      "Seleziona una conversazione da valutare"
                    )}
                  </p>
                  <Button variant="ghost" size="sm" onClick={loadData} disabled={isLoading}>
                    <RefreshCw className={cn("w-4 h-4 mr-1", isLoading && "animate-spin")} />
                    Aggiorna
                  </Button>
                </div>
              </div>
            )}

            {/* How-to instructions — fullScreen: rich card grid; normal: compact strip */}
            {fullScreen ? (
              <div className="shrink-0 border-b bg-surface-muted px-8 py-5">
                <div className="grid grid-cols-3 gap-4">
                    {/* Step 1 */}
                    <div className="flex gap-3 p-3.5 rounded-lg bg-surface border border-line">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft-strong text-brand-fg text-sm font-semibold tabular">1</span>
                      <div>
                        <p className="text-sm font-semibold text-fg mb-0.5">Seleziona</p>
                        <p className="text-xs text-fg-muted leading-snug">Scegli una delle conversazioni da valutare dalla lista</p>
                      </div>
                    </div>
                    {/* Step 2 */}
                    <div className="flex gap-3 p-3.5 rounded-lg bg-surface border border-line">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft-strong text-brand-fg text-sm font-semibold tabular">2</span>
                      <div>
                        <p className="text-sm font-semibold text-fg mb-0.5">Leggi A, poi B</p>
                        <p className="text-xs text-fg-muted leading-snug">Leggi entrambe le risposte con attenzione, nell'ordine indicato</p>
                      </div>
                    </div>
                    {/* Step 3 */}
                    <div className="flex gap-3 p-3.5 rounded-lg bg-surface border border-line">
                      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-brand-soft-strong text-brand-fg text-sm font-semibold tabular">3</span>
                      <div>
                        <p className="text-sm font-semibold text-fg mb-0.5">Valuta</p>
                        <p className="text-xs text-fg-muted leading-snug">Esprimi un giudizio su ogni dimensione. Puoi rileggere le risposte in qualsiasi momento.</p>
                      </div>
                    </div>
                  </div>
                </div>
            ) : (
              <div className="px-6 py-3 bg-surface-brand border-b border-line">
                <p className="label-mono mb-2">Come funziona la valutazione</p>
                <div className="flex gap-4">
                  {[
                    { n: "1", label: "Seleziona una conversazione" },
                    { n: "2", label: "Leggi Risposta A, poi Risposta B" },
                    { n: "3", label: "Valuta: puoi rileggere in ogni momento" },
                  ].map(({ n, label }) => (
                    <div key={n} className="flex items-start gap-2 flex-1">
                      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand text-[10px] font-semibold tabular mt-0.5">{n}</span>
                      <p className="text-[11px] text-fg-secondary leading-snug">{label}</p>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <ScrollArea className="flex-1 px-6 py-4">
              <div>
                {fullScreen && (
                  <div className="flex items-center justify-between mb-3">
                    <p className="text-sm font-semibold text-fg-secondary">
                      Conversazioni da valutare
                    </p>
                    <Button variant="ghost" size="sm" onClick={loadData} disabled={isLoading} className="h-7 text-xs">
                      <RefreshCw className={cn("w-3.5 h-3.5 mr-1", isLoading && "animate-spin")} />
                      Aggiorna
                    </Button>
                  </div>
                )}
                {isLoading ? (
                  <div className="flex items-center justify-center h-40">
                    <Loader2 className="w-8 h-8 animate-spin text-brand-fg" />
                  </div>
                ) : error ? (
                  <div className="flex flex-col items-center justify-center h-40 text-danger-fg">
                    <AlertCircle className="w-8 h-8 mb-2" />
                    <p>{error}</p>
                  </div>
                ) : pendingChats.length === 0 ? (
                  <div className="flex flex-col items-center justify-center h-40 text-fg-muted">
                    {evaluatedIds.size > 0 ? (
                      <>
                        <CheckCircle2 className="w-12 h-12 mb-3 text-brand" />
                        <p className="text-lg font-medium">Tutte le conversazioni sono state valutate!</p>
                        <p className="text-sm mt-1">Grazie per il tuo contributo.</p>
                      </>
                    ) : (
                      <>
                        <AlertCircle className="w-12 h-12 mb-3 text-fg-muted" />
                        <p className="text-lg font-medium">Nessuna conversazione disponibile</p>
                        <p className="text-sm mt-1 text-center max-w-xs">
                          Non ci sono ancora conversazioni da valutare. Usa la chat per generarne.
                        </p>
                      </>
                    )}
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    {pendingChats.map((chat, idx) => (
                      <Card
                        key={chat.id}
                        className={cn(
                          "cursor-pointer transition-colors duration-200 hover:border-brand/40 hover:bg-surface-muted"
                        )}
                        onClick={() => handleSelectChat(chat)}
                      >
                        <CardContent className="px-3 py-1.5">
                          <div className="flex items-center gap-2.5">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-surface-muted text-[11px] font-bold text-fg-muted">
                              {idx + 1}
                            </span>
                            <p className="text-sm font-medium text-fg leading-snug">
                              {chat.query}
                            </p>
                          </div>
                        </CardContent>
                      </Card>
                    ))}
                  </div>
                )}
                <NewsletterSignup source="valutazione" className="mt-6" />
              </div>
            </ScrollArea>

            <div className="border-t bg-surface-muted px-6 py-3">
              <div className="flex items-center justify-between text-sm text-fg-muted">
                <span>
                  {pendingChats.filter(c => c.evaluation_type === "ab").length} A/B
                  {" · "}
                  {pendingChats.filter(c => c.evaluation_type === "simple").length} Likert
                  {" da valutare"}
                </span>
                <span>{evaluatedIds.size} già valutate</span>
              </div>
            </div>
          </div>
        )}

        {/* Step: A/B Survey Form */}
        {step === "form" && selectedChat && (
          <div className="flex flex-col flex-1 min-h-0">

            {/* ── MOBILE LAYOUT (hidden on md+) ── */}
            <div className="md:hidden flex flex-col flex-1 min-h-0">
              {/* Question header */}
              <div className="px-4 py-2.5 bg-surface-brand border-b shrink-0">
                <p className="text-sm font-medium text-fg line-clamp-2">
                  <span className="text-brand-fg">Domanda:</span> {selectedChat.query}
                </p>
                {selectedChat.matched_topic && (
                  <p className="text-xs text-brand-fg mt-0.5">Confronto su: {selectedChat.matched_topic}</p>
                )}
              </div>

              {/* 3-tab bar */}
              <div className="flex shrink-0 border-b bg-surface">
                {(["A", "B", "valuta"] as const).map((tab) => (
                  <button
                    key={tab}
                    onClick={() => setMobileABTab(tab)}
                    className={cn(
                      "flex-1 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px inline-flex items-center justify-center gap-1",
                      mobileABTab === tab
                        ? tab === "B"
                          ? "border-notice text-notice-fg"
                          : "border-brand text-brand-fg"
                        : "border-transparent text-fg-muted hover:text-fg-secondary"
                    )}
                  >
                    {tab === "A" && "Risposta A"}
                    {tab === "B" && "Risposta B"}
                    {tab === "valuta" && (
                      <>
                        Valuta
                        {completionPercentage() === 100 && <Check className="w-3.5 h-3.5 text-brand-fg" />}
                      </>
                    )}
                  </button>
                ))}
              </div>

              {/* Response tabs content */}
              {(mobileABTab === "A" || mobileABTab === "B") && (
                <div className="flex flex-col flex-1 min-h-0">
                  {/* Legend */}
                  <div className="flex flex-wrap items-center gap-1.5 px-3 py-2 bg-surface border-b shrink-0">
                    <span className="label-mono">Legenda</span>
                    <span className="inline-flex items-center gap-1 bg-surface-muted px-1.5 py-0.5 rounded-sm border border-line text-[10px]">
                      <strong className="font-bold text-fg">Deputato</strong>
                    </span>
                    <span title="Testo identico al verbale parlamentare" className="inline-flex items-center gap-1 bg-brand-soft px-1.5 py-0.5 rounded-sm border border-brand/25 text-[10px]">
                      <span className="underline decoration-brand decoration-2 underline-offset-2 text-fg-secondary">«cit»</span>
                      <span className="font-semibold text-brand-fg">✓ verbatim</span>
                    </span>
                    <span title="Attribuita al deputato, ma il testo è rielaborato, non corrisponde parola per parola al verbale" className="inline-flex items-center gap-1 bg-notice-soft px-1.5 py-0.5 rounded-sm border border-notice/25 text-[10px]">
                      <span className="underline decoration-notice decoration-2 decoration-dashed underline-offset-2 text-fg-secondary">«cit»</span>
                      <span className="font-semibold text-notice-fg">~ parafrasi</span>
                    </span>
                    <span className="inline-flex items-center gap-1 bg-surface-muted px-1.5 py-0.5 rounded-sm border border-line text-[10px]">
                      <span className="underline decoration-line-control decoration-1 underline-offset-2 text-fg-secondary">«cit»</span>
                      <span className="font-semibold text-fg-secondary">citata</span>
                    </span>
                  </div>
                  <ScrollArea className="flex-1 min-h-0 px-4 py-4">
                    {isLoadingDetails ? (
                      <div className="flex items-center justify-center h-40">
                        <Loader2 className={cn("w-6 h-6 animate-spin", mobileABTab === "A" ? "text-brand" : "text-notice")} />
                      </div>
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
                        {mobileABTab === "A"
                          ? renderContent(getResponseA(), getCitationsA(), undefined, localAbAssignment?.["A"] === "system")
                          : renderContent(getResponseB(), getCitationsB(), undefined, localAbAssignment?.["B"] === "system")}
                      </div>
                    )}
                  </ScrollArea>
                </div>
              )}

              {/* Valuta tab content */}
              {mobileABTab === "valuta" && (
                <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                  {/* Category progress: numbered dots + current category name */}
                  <div className="px-4 py-3 bg-surface border-b shrink-0">
                    <div className="flex items-center gap-3">
                      <div className="flex gap-1.5 shrink-0">
                        {categories.map((_, idx) => (
                          <button
                            key={idx}
                            onClick={() => setCurrentCategory(idx)}
                            className={cn(
                              "w-6 h-6 rounded-full text-xs font-semibold transition-colors flex items-center justify-center",
                              idx === currentCategory
                                ? "bg-brand text-on-brand"
                                : isCategoryComplete(idx)
                                ? "bg-brand-soft-strong text-brand-fg ring-1 ring-brand/40"
                                : "bg-surface-sunken text-fg-muted"
                            )}
                          >
                            {isCategoryComplete(idx)
                              ? <Check className="w-3 h-3" />
                              : idx + 1}
                          </button>
                        ))}
                      </div>
                      <div className="flex items-center gap-1.5 text-sm font-medium text-fg-secondary min-w-0">
                        <span className="shrink-0">{CATEGORY_ICONS[categories[currentCategory]?.name]}</span>
                        <span className="truncate">{categories[currentCategory]?.name}</span>
                      </div>
                    </div>
                  </div>

                  <ScrollArea className="flex-1 min-h-0 px-4 py-4">
                    <div className="space-y-4">
                      {/* Category instruction box — uniform across all categories (mobile) */}
                      <div className="p-3 bg-surface-brand rounded-md">
                        <p className="text-xs font-bold text-fg flex items-center gap-1.5 mb-1.5">
                          {CATEGORY_ICONS[categories[currentCategory].name]}
                          {CATEGORY_INSTRUCTIONS[categories[currentCategory].name]?.title ?? categories[currentCategory].name}
                        </p>
                        {categories[currentCategory].name === "Autorità Esperti" ? (
                          <>
                            <p className="text-xs text-fg-secondary leading-relaxed">
                              Dai un voto stelle alle 3 dimensioni di autorità per ciascuna risposta.
                            </p>
                            <p className="text-[10px] text-fg-muted mt-1.5 leading-snug">
                              Torna sulle schede <strong>Risposta A</strong> e <strong>Risposta B</strong> per confrontare gli esperti citati.
                            </p>
                          </>
                        ) : (
                          <p className="text-xs text-fg-secondary leading-snug">
                            {CATEGORY_INSTRUCTIONS[categories[currentCategory].name]?.description}
                          </p>
                        )}
                      </div>
                      {categories[currentCategory].name !== "Valutazione Complessiva" ? (
                        categories[currentCategory].questions.map((question) => {
                          const dim = question.id as ABDimension;
                          const rating = formState[dim];
                          return (
                            <div key={question.id} className="space-y-3 p-4 bg-surface rounded-lg border border-line">
                              <div>
                                <p className="font-semibold text-sm text-fg">{question.question}</p>
                                <p className="text-xs text-fg-muted mt-0.5 leading-snug">{question.description}</p>
                              </div>
                              <div className="space-y-2">
                                <div className="flex flex-col gap-1">
                                  <span className="text-xs font-semibold text-brand-fg">Risposta A</span>
                                  <StarRating value={rating.rating_a} onChange={(val) => handleABRatingChange(dim, "rating_a", val)} size="md" />
                                </div>
                                <div className="flex flex-col gap-1">
                                  <span className="text-xs font-semibold text-notice-fg">Risposta B</span>
                                  <StarRating value={rating.rating_b} onChange={(val) => handleABRatingChange(dim, "rating_b", val)} size="md" />
                                </div>
                              </div>
                            </div>
                          );
                        })
                      ) : (
                        <>
                          <div className="space-y-3 p-4 bg-surface rounded-lg border">
                            <p className="font-medium text-sm text-fg">Soddisfazione complessiva</p>
                            <div className="space-y-2.5">
                              <div className="flex flex-col gap-1">
                                <span className="text-xs font-semibold text-brand-fg">Risposta A</span>
                                <StarRating value={formState.overall_satisfaction_a}
                                  onChange={(val) => setFormState(prev => ({
                                    ...prev,
                                    overall_satisfaction_a: val,
                                    overall_preference: inferPreference(val, prev.overall_satisfaction_b),
                                  }))} size="md" />
                              </div>
                              <div className="flex flex-col gap-1">
                                <span className="text-xs font-semibold text-notice-fg">Risposta B</span>
                                <StarRating value={formState.overall_satisfaction_b}
                                  onChange={(val) => setFormState(prev => ({
                                    ...prev,
                                    overall_satisfaction_b: val,
                                    overall_preference: inferPreference(prev.overall_satisfaction_a, val),
                                  }))} size="md" />
                              </div>
                            </div>
                          </div>
                          <div className="p-4 bg-surface rounded-lg border">
                            <p className="font-medium text-sm text-fg mb-3">
                              Consiglieresti questo sistema?
                            </p>
                            <div className="flex gap-3">
                              <Button type="button"
                                variant={formState.would_recommend ? "default" : "outline"}
                                onClick={() => setFormState(prev => ({ ...prev, would_recommend: true }))}
                                className="flex-1">
                                <ThumbsUp className="w-4 h-4 mr-1" /> Sì
                              </Button>
                              <Button type="button"
                                variant={!formState.would_recommend ? "default" : "outline"}
                                onClick={() => setFormState(prev => ({ ...prev, would_recommend: false }))}
                                className="flex-1">
                                No
                              </Button>
                            </div>
                          </div>
                          <div className="p-4 bg-surface rounded-lg border space-y-4">
                            <div className="space-y-2">
                              <label className="text-sm font-medium text-fg">Cosa ha funzionato bene? (opzionale)</label>
                              <Textarea placeholder="Aspetti positivi..." value={formState.feedback_positive}
                                onChange={(e) => setFormState(prev => ({ ...prev, feedback_positive: e.target.value }))}
                                className="min-h-[70px] resize-none" />
                            </div>
                            <div className="space-y-2">
                              <label className="text-sm font-medium text-fg">Suggerimenti? (opzionale)</label>
                              <Textarea placeholder="Come migliorare..." value={formState.feedback_improvement}
                                onChange={(e) => setFormState(prev => ({ ...prev, feedback_improvement: e.target.value }))}
                                className="min-h-[70px] resize-none" />
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  </ScrollArea>
                </div>
              )}

              {/* Mobile footer */}
              <div className="px-4 py-3 border-t bg-surface shrink-0">
                {error && (
                  <div className="mb-2 p-2 bg-danger-soft text-danger-fg text-xs rounded-md flex items-center gap-2">
                    <AlertCircle className="w-4 h-4" /> {error}
                  </div>
                )}
                <div className="flex items-center justify-between">
                  <Button variant="ghost" size="sm"
                    onClick={() => {
                      if (mobileABTab === "A") {
                        setStep("select");
                      } else if (mobileABTab === "B") {
                        setMobileABTab("A");
                      } else if (currentCategory === 0) {
                        setMobileABTab("B");
                      } else {
                        goToPrevCategory();
                      }
                    }}>
                    <ChevronLeft className="w-4 h-4 mr-1" />
                    {mobileABTab === "A" ? "Indietro" : mobileABTab === "B" ? "Risposta A" : currentCategory === 0 ? "Risposta B" : "Precedente"}
                  </Button>
                  {mobileABTab === "A" ? (
                    <Button size="sm" onClick={() => setMobileABTab("B")}>
                      Risposta B <ChevronRight className="w-4 h-4 ml-1" />
                    </Button>
                  ) : mobileABTab === "B" ? (
                    <Button size="sm" onClick={() => setMobileABTab("valuta")}>
                      Inizia a valutare <ChevronRight className="w-4 h-4 ml-1" />
                    </Button>
                  ) : currentCategory < categories.length - 1 ? (
                    <Button size="sm" onClick={goToNextCategory} disabled={!isCategoryComplete(currentCategory)}>
                      Avanti <ChevronRight className="w-4 h-4 ml-1" />
                    </Button>
                  ) : (
                    <Button size="sm" onClick={handleGoToCitations} disabled={!isFormComplete()}>
                      Citazioni <ChevronRight className="w-4 h-4 ml-1" />
                    </Button>
                  )}
                </div>
              </div>
            </div>

            {/* ── DESKTOP LAYOUT (hidden on mobile) ── */}
            <div className="hidden md:flex flex-row flex-1 min-h-0">
              {/* Left Panel: Side-by-side A/B Responses */}
              <div className="md:w-3/5 md:border-r flex flex-col bg-surface min-h-0 overflow-hidden">
                <div className="px-4 py-3 bg-surface-brand border-b">
                  <p className="text-sm font-medium text-fg line-clamp-2">
                    <span className="text-brand-fg">Domanda:</span> {selectedChat.query}
                  </p>
                </div>
                <div className="flex flex-1 min-h-0 overflow-hidden">
                  {categories[currentCategory]?.name === "Autorità Esperti" ? (
                    <AuthorityGroupComparisonPanel
                      expertsA={localAbAssignment?.["A"] === "system" ? (systemExperts) : baselineExperts}
                      expertsB={localAbAssignment?.["B"] === "system" ? (systemExperts) : baselineExperts}
                      isLoadingA={localAbAssignment?.["A"] === "system" ? isLoadingSystemExperts : isLoadingBaselineExperts}
                      isLoadingB={localAbAssignment?.["B"] === "system" ? isLoadingSystemExperts : isLoadingBaselineExperts}
                      groupRatings={groupAuthorityRatings}
                      onGroupRatingChange={(group, value) => setGroupAuthorityRatings(prev => ({ ...prev, [group]: value }))}
                    />
                  ) : (
                    <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                      {/* Legend */}
                      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-3 py-2.5 bg-surface border-b shrink-0">
                        <span className="label-mono">Legenda</span>
                        {/* Green: verbatim */}
                        <span className="inline-flex flex-col bg-brand-soft px-2.5 py-1 rounded-md border border-brand/25 text-[11px]">
                          <span className="flex items-center gap-1.5">
                            <span className="underline decoration-brand decoration-2 underline-offset-2 text-fg-secondary">«citazione»</span>
                            <span className="font-semibold text-brand-fg">✓ verbatim</span>
                          </span>
                          <span className="text-fg-muted text-[10px] leading-tight mt-0.5">
                            testo identico al verbale parlamentare
                          </span>
                        </span>
                        {/* Amber: paraphrased */}
                        <span className="inline-flex flex-col bg-notice-soft px-2.5 py-1 rounded-md border border-notice/25 text-[11px]">
                          <span className="flex items-center gap-1.5">
                            <span className="underline decoration-notice decoration-2 decoration-dashed underline-offset-2 text-fg-secondary">«citazione»</span>
                            <span className="font-semibold text-notice-fg">~ parafrasata</span>
                          </span>
                          <span className="text-fg-muted text-[10px] leading-tight mt-0.5">
                            attribuita al deputato, ma non riscontrabile parola per parola nei verbali (rielaborazione o parafrasi)
                          </span>
                        </span>
                      </div>

                      {/* Sticky column headers */}
                      <div className="grid grid-cols-2 shrink-0 border-b">
                        <div className="px-3 py-2 bg-brand-soft text-center border-r border-line">
                          <span className="font-semibold text-brand-fg text-sm">Risposta A</span>
                        </div>
                        <div className="px-3 py-2 bg-notice-soft text-center">
                          <span className="font-semibold text-notice-fg text-sm">Risposta B</span>
                        </div>
                      </div>

                      {/* Section-aligned columns — sections match by canonical title */}
                      {isLoadingDetails ? (
                        <div className="flex items-center justify-center flex-1">
                          <Loader2 className="w-6 h-6 animate-spin text-fg-muted" />
                        </div>
                      ) : (
                        <div className="flex-1 overflow-y-auto">
                          {(() => {
                            const citA = getCitationsA();
                            const citB = getCitationsB();
                            const aligned = alignSections(
                              parseIntoSections(getResponseA()),
                              parseIntoSections(getResponseB()),
                            );
                            return aligned.map(({ a, b, heading }) => (
                              <div key={heading} className="border-b last:border-b-0">
                                {/* Shared section heading */}
                                <div className="grid grid-cols-2 bg-surface-muted border-b border-line">
                                  <div className="px-3 py-1.5 border-r border-line">
                                    <p className="text-[11px] font-semibold uppercase tracking-wide text-brand-fg">{heading}</p>
                                  </div>
                                  <div className="px-3 py-1.5">
                                    <p className="text-[11px] font-semibold uppercase tracking-wide text-notice-fg">{heading}</p>
                                  </div>
                                </div>
                                {/* Section content */}
                                <div className="grid grid-cols-2">
                                  <div className="px-4 py-3 border-r border-line">
                                    {a
                                      ? renderContent(a.content, citA, "a", localAbAssignment?.["A"] === "system")
                                      : <p className="text-sm text-fg-muted italic">—</p>}
                                  </div>
                                  <div className="px-4 py-3">
                                    {b
                                      ? renderContent(b.content, citB, "b", localAbAssignment?.["B"] === "system")
                                      : <p className="text-sm text-fg-muted italic">—</p>}
                                  </div>
                                </div>
                              </div>
                            ));
                          })()}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Right Panel: A/B Survey Form */}
              <div className="md:w-2/5 flex flex-col bg-surface-muted min-h-0 overflow-hidden relative">
                {/* Reading phase overlay */}
                {!hasConfirmedReading && (
                  <div className="absolute inset-0 z-10 flex flex-col items-center justify-center bg-surface px-8 py-6 text-center gap-6">
                    <div className="w-16 h-16 rounded-lg bg-brand-soft flex items-center justify-center">
                      <BookOpen className="w-8 h-8 text-brand-fg" />
                    </div>
                    <div className="space-y-2">
                      <h3 className="text-lg font-semibold text-fg">Prima leggi entrambe le risposte</h3>
                      <p className="text-sm text-fg-muted leading-relaxed max-w-xs mx-auto">
                        Nel pannello a sinistra trovi la{" "}
                        <span className="font-semibold text-brand-fg">Risposta A</span> e la{" "}
                        <span className="font-semibold text-notice-fg">Risposta B</span> affiancate.
                        Leggile entrambe prima di iniziare a valutare.
                      </p>
                      <p className="text-xs text-fg-muted mt-2 leading-relaxed">
                        Potrai rileggere le risposte in qualsiasi momento durante la valutazione.
                      </p>
                    </div>
                    <Button
                      onClick={() => setHasConfirmedReading(true)}
                      className="gap-2 px-6"
                      size="lg"
                    >
                      Ho letto entrambe, inizia a valutare
                      <ChevronRight className="w-4 h-4" />
                    </Button>
                  </div>
                )}
                {/* Category tabs — short labels + icons to avoid overflow */}
                <div className="px-3 py-2 border-b bg-surface flex gap-1 overflow-x-auto shrink-0 items-center">
                  {categories.map((cat, idx) => (
                    <button
                      key={cat.name}
                      onClick={() => setCurrentCategory(idx)}
                      className={cn(
                        "flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-semibold transition-all whitespace-nowrap",
                        currentCategory === idx
                          ? "bg-brand-soft-strong text-brand-fg"
                          : "text-fg-muted hover:bg-surface-muted",
                        isCategoryComplete(idx) && "ring-1 ring-brand/40"
                      )}
                    >
                      {CATEGORY_ICONS[cat.name]}
                      {CATEGORY_SHORT_LABELS[cat.name] ?? cat.name}
                      {isCategoryComplete(idx) && <Check className="w-3 h-3 text-brand-fg" />}
                    </button>
                  ))}
                </div>

                <ScrollArea className="flex-1 min-h-0 px-4 py-4">
                  <div className="space-y-5">
                    {/* Category instruction box — uniform across all categories */}
                    <div className="p-3.5 bg-surface-brand rounded-md">
                      <p className="text-xs font-bold text-fg flex items-center gap-1.5 mb-1.5">
                        {CATEGORY_ICONS[categories[currentCategory].name]}
                        {CATEGORY_INSTRUCTIONS[categories[currentCategory].name]?.title ?? categories[currentCategory].name}
                      </p>
                      {categories[currentCategory].name === "Autorità Esperti" ? (
                        <div className="space-y-2">
                          <div className="flex items-start gap-2">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand text-[10px] font-semibold tabular mt-0.5">1</span>
                            <p className="text-xs text-fg-secondary leading-snug">
                              <span className="font-semibold text-fg-secondary">Pannello sinistro:</span> per ogni gruppo politico, clicca quale risposta ha citato l'esperto più autorevole secondo te.
                            </p>
                          </div>
                          <div className="flex items-start gap-2">
                            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand text-on-brand text-[10px] font-semibold tabular mt-0.5">2</span>
                            <p className="text-xs text-fg-secondary leading-snug">
                              <span className="font-semibold text-fg-secondary">Qui sotto:</span> assegna un voto stelle alle 3 dimensioni globali di autorità.
                            </p>
                          </div>
                        </div>
                      ) : (
                        <p className="text-xs text-fg-secondary leading-snug">
                          {CATEGORY_INSTRUCTIONS[categories[currentCategory].name]?.description}
                        </p>
                      )}
                    </div>
                    {categories[currentCategory].name !== "Valutazione Complessiva" ? (
                      categories[currentCategory].questions.map((question) => {
                        const dim = question.id as ABDimension;
                        const rating = formState[dim];
                        return (
                          <div key={question.id} className="space-y-3 p-4 bg-surface rounded-lg border border-line">
                            <div>
                              <p className="font-semibold text-sm text-fg">{question.question}</p>
                              <p className="text-xs text-fg-muted mt-0.5 leading-snug">{question.description}</p>
                            </div>
                            <div className="space-y-2">
                              <div className="flex items-center gap-3">
                                <span className="text-xs font-semibold text-brand-fg w-20 shrink-0">Risposta A</span>
                                <StarRating value={rating.rating_a} onChange={(val) => handleABRatingChange(dim, "rating_a", val)} size="md" />
                              </div>
                              <div className="flex items-center gap-3">
                                <span className="text-xs font-semibold text-notice-fg w-20 shrink-0">Risposta B</span>
                                <StarRating value={rating.rating_b} onChange={(val) => handleABRatingChange(dim, "rating_b", val)} size="md" />
                              </div>
                            </div>
                          </div>
                        );
                      })
                    ) : (
                      <>
                        <div className="space-y-3 p-4 bg-surface rounded-lg border border-line">
                          <div>
                            <p className="font-semibold text-sm text-fg">Soddisfazione complessiva</p>
                            <p className="text-xs text-fg-muted mt-0.5">Valutazione generale dell'esperienza</p>
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-xs font-semibold text-brand-fg w-20 shrink-0">Risposta A</span>
                            <StarRating value={formState.overall_satisfaction_a}
                              onChange={(val) => setFormState(prev => ({
                                ...prev,
                                overall_satisfaction_a: val,
                                overall_preference: inferPreference(val, prev.overall_satisfaction_b),
                              }))} size="md" />
                          </div>
                          <div className="flex items-center gap-3">
                            <span className="text-xs font-semibold text-notice-fg w-20 shrink-0">Risposta B</span>
                            <StarRating value={formState.overall_satisfaction_b}
                              onChange={(val) => setFormState(prev => ({
                                ...prev,
                                overall_satisfaction_b: val,
                                overall_preference: inferPreference(prev.overall_satisfaction_a, val),
                              }))} size="md" />
                          </div>
                        </div>

                        <Separator className="my-4" />

                        <div className="space-y-3 p-4 bg-surface rounded-lg border border-line">
                          <p className="font-semibold text-sm text-fg">
                            Consiglieresti questo tipo di sistema ai tuoi colleghi?
                          </p>
                          <div className="flex gap-3">
                            <Button type="button"
                              variant={formState.would_recommend ? "default" : "outline"}
                              onClick={() => setFormState(prev => ({ ...prev, would_recommend: true }))}
                              className="flex-1">
                              <ThumbsUp className="w-4 h-4 mr-2" />
                              Si
                            </Button>
                            <Button type="button"
                              variant={!formState.would_recommend ? "default" : "outline"}
                              onClick={() => setFormState(prev => ({ ...prev, would_recommend: false }))}
                              className="flex-1">
                              No
                            </Button>
                          </div>
                        </div>

                        <div className="space-y-4 p-4 bg-surface rounded-lg border border-line">
                          <div className="space-y-2">
                            <label className="text-sm font-medium text-fg">Cosa ha funzionato bene? (opzionale)</label>
                            <Textarea placeholder="Descrivi gli aspetti positivi..." value={formState.feedback_positive}
                              onChange={(e) => setFormState(prev => ({ ...prev, feedback_positive: e.target.value }))}
                              className="min-h-[80px] resize-none" />
                          </div>
                          <div className="space-y-2">
                            <label className="text-sm font-medium text-fg">Suggerimenti per migliorare? (opzionale)</label>
                            <Textarea placeholder="Come potremmo migliorare il sistema..." value={formState.feedback_improvement}
                              onChange={(e) => setFormState(prev => ({ ...prev, feedback_improvement: e.target.value }))}
                              className="min-h-[80px] resize-none" />
                          </div>
                        </div>
                      </>
                    )}
                  </div>
                </ScrollArea>

                <div className="px-4 py-4 border-t bg-surface">
                  {error && (
                    <div className="mb-3 p-2 bg-danger-soft text-danger-fg text-sm rounded-md flex items-center gap-2">
                      <AlertCircle className="w-4 h-4" />
                      {error}
                    </div>
                  )}
                  <div className="flex items-center justify-between">
                    <Button variant="ghost" onClick={() => currentCategory === 0 ? setStep("select") : goToPrevCategory()}>
                      <ChevronLeft className="w-4 h-4 mr-1" />
                      {currentCategory === 0 ? "Indietro" : "Precedente"}
                    </Button>
                    {currentCategory < categories.length - 1 ? (
                      <Button onClick={goToNextCategory} disabled={!isCategoryComplete(currentCategory)}>
                        Avanti <ChevronRight className="w-4 h-4 ml-1" />
                      </Button>
                    ) : (
                      <Button onClick={handleGoToCitations} disabled={!isFormComplete()}>
                        Valuta Citazioni <ChevronRight className="w-4 h-4 ml-1" />
                      </Button>
                    )}
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        {/* Step: Simple Likert Form */}
        {step === "simple_form" && selectedChat && (
          <div className="flex flex-col flex-1 min-h-0">

            {/* ── MOBILE: tab layout ── */}
            <div className="md:hidden flex flex-col flex-1 min-h-0">
              {/* Question header */}
              <div className="px-4 py-2.5 bg-surface-brand border-b shrink-0">
                <p className="text-sm font-medium text-fg line-clamp-2">
                  <span className="text-brand-fg">Domanda:</span> {selectedChat.query}
                </p>
              </div>

              {/* Tab bar */}
              <div className="flex shrink-0 border-b bg-surface">
                <button
                  onClick={() => setMobileSimpleTab("response")}
                  className={cn(
                    "flex-1 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px",
                    mobileSimpleTab === "response"
                      ? "border-brand text-brand-fg"
                      : "border-transparent text-fg-muted hover:text-fg-secondary"
                  )}
                >
                  Risposta
                </button>
                <button
                  onClick={() => setMobileSimpleTab("form")}
                  className={cn(
                    "flex-1 py-2.5 text-sm font-semibold transition-colors border-b-2 -mb-px inline-flex items-center justify-center gap-1.5",
                    mobileSimpleTab === "form"
                      ? "border-brand text-brand-fg"
                      : "border-transparent text-fg-muted hover:text-fg-secondary"
                  )}
                >
                  Valuta
                  {isSimpleFormComplete() && <Check className="w-3.5 h-3.5 text-brand-fg" />}
                </button>
              </div>

              {/* Tab content */}
              <ScrollArea className="flex-1 min-h-0">
                {mobileSimpleTab === "response" ? (
                  <div className="px-4 py-4">
                    {isLoadingDetails ? (
                      <div className="flex items-center justify-center h-40">
                        <Loader2 className="w-6 h-6 animate-spin text-brand-fg" />
                      </div>
                    ) : (
                      <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
                        {chatDetails ? renderContent(chatDetails.answer) : null}
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="px-4 py-4 space-y-4">
                    {SIMPLE_DIMENSIONS.map((dim) => (
                      <div key={dim} className="p-4 bg-surface rounded-lg border space-y-2">
                        <p className="font-medium text-fg">
                          {SIMPLE_DIMENSION_LABELS[dim]}
                        </p>
                        <StarRating
                          value={simpleFormState[dim]}
                          onChange={(val) => setSimpleFormState(prev => ({ ...prev, [dim]: val }))}
                          size="lg"
                        />
                      </div>
                    ))}
                    <div className="p-4 bg-surface rounded-lg border space-y-2">
                      <label className="text-sm font-medium text-fg">
                        Commento libero (opzionale)
                      </label>
                      <Textarea
                        placeholder="Osservazioni sulla risposta..."
                        value={simpleFormState.feedback}
                        onChange={(e) => setSimpleFormState(prev => ({ ...prev, feedback: e.target.value }))}
                        className="min-h-[80px] resize-none"
                      />
                    </div>
                  </div>
                )}
              </ScrollArea>
            </div>

            {/* ── DESKTOP: side-by-side layout ── */}
            <div className="hidden md:flex flex-1 min-h-0">
              {/* Left: System Response */}
              <div className="w-1/2 border-r flex flex-col bg-surface min-h-0 overflow-hidden">
                <div className="px-4 py-2 bg-surface-brand border-b shrink-0">
                  <p className="text-sm font-medium text-fg line-clamp-2">
                    <span className="text-brand-fg">Domanda:</span> {selectedChat.query}
                  </p>
                </div>
                <ScrollArea className="flex-1 px-4 py-4">
                  {isLoadingDetails ? (
                    <div className="flex items-center justify-center h-40">
                      <Loader2 className="w-6 h-6 animate-spin text-brand-fg" />
                    </div>
                  ) : (
                    <div className="prose prose-sm dark:prose-invert max-w-none text-sm">
                      {chatDetails ? renderContent(chatDetails.answer) : null}
                    </div>
                  )}
                </ScrollArea>
              </div>

              {/* Right: Simple Rating Form */}
              <div className="w-1/2 flex flex-col bg-surface-muted min-h-0 overflow-hidden">
                <div className="px-4 py-3 border-b bg-surface shrink-0">
                  <p className="text-sm font-medium text-fg-secondary">
                    Valuta la risposta del sistema su 4 dimensioni
                  </p>
                </div>
                <ScrollArea className="flex-1 px-4 py-4">
                  <div className="space-y-4">
                    {SIMPLE_DIMENSIONS.map((dim) => (
                      <div key={dim} className="p-4 bg-surface rounded-lg border space-y-2">
                        <p className="font-medium text-fg">
                          {SIMPLE_DIMENSION_LABELS[dim]}
                        </p>
                        <StarRating
                          value={simpleFormState[dim]}
                          onChange={(val) => setSimpleFormState(prev => ({ ...prev, [dim]: val }))}
                          size="lg"
                        />
                      </div>
                    ))}
                    <div className="p-4 bg-surface rounded-lg border space-y-2">
                      <label className="text-sm font-medium text-fg">
                        Commento libero (opzionale)
                      </label>
                      <Textarea
                        placeholder="Osservazioni sulla risposta..."
                        value={simpleFormState.feedback}
                        onChange={(e) => setSimpleFormState(prev => ({ ...prev, feedback: e.target.value }))}
                        className="min-h-[80px] resize-none"
                      />
                    </div>
                  </div>
                </ScrollArea>
              </div>
            </div>

            {/* Footer — sempre visibile su mobile e desktop */}
            <div className="px-4 py-4 border-t bg-surface shrink-0">
              {error && (
                <div className="mb-3 p-2 bg-danger-soft text-danger-fg text-sm rounded-md flex items-center gap-2">
                  <AlertCircle className="w-4 h-4" />
                  {error}
                </div>
              )}
              <div className="flex items-center justify-between">
                <Button variant="ghost" onClick={() => setStep("select")}>
                  <ChevronLeft className="w-4 h-4 mr-1" />
                  Indietro
                </Button>
                <Button
                  onClick={handleSimpleSubmit}
                  disabled={!isSimpleFormComplete() || isSubmitting}
                >
                  {isSubmitting ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : null}
                  Invia Valutazione
                </Button>
              </div>
            </div>
          </div>
        )}

        {/* Step: Citation Review */}
        {step === "citations" && (
          <div className="flex flex-col h-[80vh]">
            <CitationReviewStep
              citationsA={sampledCitationsA}
              citationsB={[]}
              responseTextA={getResponseA()}
              responseTextB={getResponseB()}
              evaluationsA={formState.citation_evaluations_a}
              evaluationsB={formState.citation_evaluations_b}
              onUpdateEvaluationA={(index, evaluation) => {
                setFormState(prev => {
                  const updated = [...prev.citation_evaluations_a];
                  updated[index] = evaluation;
                  return { ...prev, citation_evaluations_a: updated };
                });
              }}
              onUpdateEvaluationB={(index, evaluation) => {
                setFormState(prev => {
                  const updated = [...prev.citation_evaluations_b];
                  updated[index] = evaluation;
                  return { ...prev, citation_evaluations_b: updated };
                });
              }}
              onSubmit={handleSubmit}
              onSkip={() => {
                setFormState(prev => ({
                  ...prev,
                  citation_evaluations_a: [],
                  citation_evaluations_b: [],
                }));
                handleSubmit();
              }}
              onBack={() => {
                setStep("form");
                setCurrentCategory(categories.length - 1);
              }}
              isSubmitting={isSubmitting}
            />
            {error && (
              <div className="px-4 py-2 bg-danger-soft text-danger-fg text-sm flex items-center gap-2 border-t">
                <AlertCircle className="w-4 h-4" />
                {error}
              </div>
            )}
          </div>
        )}

        {/* Step: Success */}
        {step === "success" && (
          <div className="flex flex-col items-center justify-center min-h-[40vh] px-6 py-8">
            <div className="w-16 h-16 rounded-full bg-brand-soft flex items-center justify-center mb-4">
              <CheckCircle2 className="w-10 h-10 text-brand-fg" />
            </div>
            <h3 className="text-xl font-semibold text-fg mb-2">
              Grazie per la tua valutazione!
            </h3>
            <p className="text-fg-muted text-center max-w-sm mb-6">
              Il tuo feedback è prezioso per migliorare il sistema.
            </p>
            <div className="flex gap-3">
              <Button variant="outline" onClick={() => { setStep("select"); loadData(); }}>
                Valuta altra conversazione
              </Button>
              <Button onClick={onClose}>Chiudi</Button>
            </div>
            <NewsletterSignup source="survey_done" className="mt-8 w-full max-w-lg text-left" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
