"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { VoteParticipant, VotePartyBreakdown } from "@/types/timeline";
import { OutcomeShape, SeatShape, toOutcome } from "./outcomes";
import { SeatPlanHemicycle, useSeatPlan } from "./SeatPlanHemicycle";

interface VoteHemicycleProps {
  participants: VoteParticipant[];
  breakdown: VotePartyBreakdown[];
  selectedParty?: string | null;
  onSelectParty?: (party: string | null) => void;
  className?: string;
}

const OUTCOME_ORDER: Record<string, number> = { favor: 0, against: 1, abstain: 2, absent: 3 };

/* Shorthand and hemicycle sector for XIX-legislature groups and Misto
   components. `rank` orders the wedges left→right following the sector
   each group occupies in the Aula by political collocation (sectors are
   assigned by tradition, left of the President for the left, right for
   the right). Unmapped parties
   fall back to the centre and to initials, so a new group never breaks. */
const GROUPS: Array<{ re: RegExp; sigla: string; rank: number }> = [
  [/VERDI E SINISTRA/i, "AVS", 0],
  [/PARTITO DEMOCRATICO/i, "PD", 1],
  [/MOVIMENTO 5 STELLE/i, "M5S", 2],
  [/AZIONE/i, "AZ", 3],
  [/ITALIA VIVA/i, "IV", 4],
  [/^MISTO$/i, "MISTO", 5],
  [/NOI MODERATI/i, "NM", 6],
  [/FORZA ITALIA/i, "FI", 7],
  [/LEGA/i, "LEGA", 8],
  [/FRATELLI D'ITALIA/i, "FDI", 9],
].map(([re, sigla, rank]) => ({ re: re as RegExp, sigla: sigla as string, rank: rank as number }));

const CENTRE_RANK = 5.5;

function groupInfo(party: string): { sigla: string; rank: number } {
  for (const g of GROUPS) if (g.re.test(party)) return g;
  const initials = party
    .split(/[\s\-–]+/)
    .filter((w) => w.length > 2 || /^\d/.test(w))
    .map((w) => w[0])
    .join("")
    .toUpperCase();
  return {
    sigla: initials.slice(0, 4) || party.slice(0, 4).toUpperCase(),
    rank: CENTRE_RANK,
  };
}

/* Misto components (mixed-case names: +Europa, Minoranze Linguistiche,
   FN-Vannacci, …) all sit with the Gruppo Misto in the Aula, so the
   hemicycle collapses them into one MISTO wedge; the participant list
   below still shows each deputy's component. Exported so the dialog can
   filter with the same bucketing the chips use. */
export function wedgeKey(party: string | null): string {
  if (!party) return "N/D";
  if (/MISTO/i.test(party)) return "MISTO";
  if (party !== party.toUpperCase()) return "MISTO";
  return party;
}

/* Left→right sector order of the wedge a party belongs to, for callers
   that want to sort lists the same way the hemicycle is drawn. */
export function wedgeRank(party: string | null): number {
  return groupInfo(wedgeKey(party)).rank;
}

const CX = 100;
const CY = 102;
const INNER_R = 44;
const OUTER_R = 96;

interface Seat {
  x: number;
  y: number;
  angle: number;
  row: number;
}

/* Fallback when the real seating does not apply (Senate, past
   legislatures): a synthetic chamber of concentric arcs filled left to
   right, which keeps each parliamentary group in a contiguous wedge. */
function buildSeats(total: number): Seat[] {
  const rows = Math.max(4, Math.round(total / 50));
  const rowGap = (OUTER_R - INNER_R) / (rows - 1);
  const radii = Array.from({ length: rows }, (_, i) => INNER_R + i * rowGap);
  const radiiSum = radii.reduce((a, b) => a + b, 0);

  // Seats per row proportional to arc length, largest-remainder rounding
  // so the counts sum exactly to the number of deputies.
  const exact = radii.map((r) => (total * r) / radiiSum);
  const counts = exact.map(Math.floor);
  const remainder = total - counts.reduce((a, b) => a + b, 0);
  exact
    .map((v, i) => ({ frac: v - Math.floor(v), i }))
    .sort((a, b) => b.frac - a.frac)
    .slice(0, remainder)
    .forEach(({ i }) => counts[i]++);

  const seats: Seat[] = [];
  radii.forEach((r, row) => {
    const n = counts[row];
    for (let k = 0; k < n; k++) {
      const angle = n === 1 ? Math.PI / 2 : Math.PI - (Math.PI * k) / (n - 1);
      seats.push({
        x: CX + r * Math.cos(angle),
        y: CY - r * Math.sin(angle),
        angle,
        row,
      });
    }
  });

  // Left-to-right by angle so sequential assignment produces group wedges.
  seats.sort((a, b) => b.angle - a.angle || a.row - b.row);
  return seats;
}

export function VoteHemicycle({
  participants,
  breakdown,
  selectedParty = null,
  onSelectParty,
  className,
}: VoteHemicycleProps) {
  const t = useTranslations("Timeline");
  const [hoveredParty, setHoveredParty] = useState<string | null>(null);
  const plan = useSeatPlan();

  const { seats, ordered, dotRadius, labels } = useMemo(() => {
    // Wedges ordered by the group's real sector in the Aula (left→right).
    const rankOf = (p: string | null) => groupInfo(wedgeKey(p)).rank;
    const ordered = [...participants].sort((a, b) => {
      const ra = rankOf(a.party);
      const rb = rankOf(b.party);
      if (ra !== rb) return ra - rb;
      const ka = wedgeKey(a.party);
      const kb = wedgeKey(b.party);
      if (ka !== kb) return ka.localeCompare(kb);
      const oa = OUTCOME_ORDER[a.outcome] ?? 3;
      const ob = OUTCOME_ORDER[b.outcome] ?? 3;
      if (oa !== ob) return oa - ob;
      return a.last_name.localeCompare(b.last_name);
    });

    const seats = buildSeats(ordered.length);
    const rows = Math.max(4, Math.round(ordered.length / 50));
    const rowGap = (OUTER_R - INNER_R) / (rows - 1);
    const innerSeats = seats.filter((s) => s.row === 0).length || 1;
    const arcSpacing = (Math.PI * INNER_R) / innerSeats;
    const dotRadius = Math.min(2.6, Math.max(1.2, Math.min(rowGap * 0.34, arcSpacing * 0.42)));

    // One label per wedge, at the wedge's angular midpoint just outside the
    // outer arc. Neighbouring small wedges collide horizontally, so labels
    // greedily bump to a second, farther ring when too close to the last
    // label placed on their ring.
    const angles = new Map<string, { min: number; max: number }>();
    ordered.forEach((p, i) => {
      const key = wedgeKey(p.party);
      const a = seats[i].angle;
      const cur = angles.get(key);
      if (!cur) angles.set(key, { min: a, max: a });
      else {
        cur.min = Math.min(cur.min, a);
        cur.max = Math.max(cur.max, a);
      }
    });
    // Tooltip counts aggregated per wedge (all Misto components fold into one).
    const byParty = new Map<
      string,
      { favor: number; against: number; abstain: number; absent: number }
    >();
    for (const b of breakdown) {
      const key = wedgeKey(b.party);
      const cur = byParty.get(key) ?? { favor: 0, against: 0, abstain: 0, absent: 0 };
      cur.favor += b.favor;
      cur.against += b.against;
      cur.abstain += b.abstain ?? 0;
      cur.absent += b.absent;
      byParty.set(key, cur);
    }
    // Ring gap must exceed the chip height (~8 viewBox units at 2.2cqw)
    // or staggered neighbours still touch near the apex of the arc.
    const LABEL_R = [OUTER_R + 7, OUTER_R + 18];
    const lastEnd = [-Infinity, -Infinity];
    const labels = [...angles.entries()]
      .map(([party, { min, max }]) => ({ party, mid: (min + max) / 2 }))
      .sort((a, b) => b.mid - a.mid)
      .map(({ party, mid }) => {
        const info = groupInfo(party);
        const halfW = (info.sigla.length * 2.9 + 6) / 2;
        const xAt = (r: number) => CX + r * Math.cos(mid);
        let ring = xAt(LABEL_R[0]) - halfW < lastEnd[0] + 2 ? 1 : 0;
        let x = xAt(LABEL_R[ring]);
        if (ring === 1 && x - halfW < lastEnd[1] + 2) {
          // Both rings taken (many small wedges near the apex): slide the
          // chip right past the previous one on the freer ring instead of
          // stacking it on top: a small drift from the wedge midpoint
          // beats an unreadable overlap.
          ring = lastEnd[0] <= lastEnd[1] ? 0 : 1;
          x = Math.max(xAt(LABEL_R[ring]), lastEnd[ring] + 2 + halfW);
        }
        lastEnd[ring] = Math.max(lastEnd[ring], x + halfW);
        return {
          party,
          sigla: info.sigla,
          x,
          y: CY - LABEL_R[ring] * Math.sin(mid),
          data: byParty.get(party),
        };
      });

    return { seats, ordered, dotRadius, labels };
  }, [participants, breakdown]);

  if (ordered.length === 0) return null;

  const tally = { favor: 0, against: 0, abstain: 0, absent: 0 };
  for (const p of ordered) {
    const k = p.outcome in tally ? (p.outcome as keyof typeof tally) : "absent";
    tally[k]++;
  }

  const outcomeLabel = (outcome: string) =>
    outcome === "favor"
      ? t("voteFavor")
      : outcome === "against"
        ? t("voteAgainst")
        : outcome === "abstain"
          ? t("voteAbstained")
          : t("voteAbsent");

  // Sweep the whole chamber in ~1s regardless of deputy count.
  const stagger = Math.min(3, 1000 / ordered.length);

  const activeParty = hoveredParty ?? selectedParty;

  // Chips live in an HTML overlay so they can use Radix tooltips; their
  // viewBox coordinates are converted to percentages of the container.
  const VB = { x: -20, y: -20, w: 240, h: 128 };
  const pct = (x: number, y: number) => ({
    left: `${((x - VB.x) / VB.w) * 100}%`,
    top: `${((y - VB.y) / VB.h) * 100}%`,
  });

  // Real seats when the floor plan is loaded and the seating covers the vote
  // (Camera, current legislature); the synthetic arc otherwise.
  const seated = ordered.filter((p) => p.seat != null).length;
  if (plan && seated >= ordered.length * 0.8) {
    return (
      <div className={cn("mx-auto flex w-full max-w-2xl flex-col gap-3", className)}>
        <div className="flex flex-wrap justify-center gap-1.5">
          {[...labels]
            .sort((a, b) => a.x - b.x)
            .map((l) => {
              const isSelected = selectedParty === l.party;
              return (
                <button
                  key={l.party}
                  type="button"
                  aria-pressed={isSelected}
                  title={l.party}
                  onMouseEnter={() => setHoveredParty(l.party)}
                  onMouseLeave={() => setHoveredParty(null)}
                  onClick={() => onSelectParty?.(isSelected ? null : l.party)}
                  className={cn(
                    "appearance-none rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
                    isSelected
                      ? "border-fg bg-fg text-bg"
                      : activeParty === l.party
                        ? "border-line-control bg-surface-muted text-fg"
                        : "border-line-strong text-fg-muted hover:bg-surface-muted",
                  )}
                >
                  {l.sigla}
                </button>
              );
            })}
        </div>
        <SeatPlanHemicycle plan={plan} participants={ordered} activeKey={activeParty} keyOf={wedgeKey} />
        <ul className="flex flex-wrap justify-center gap-x-4 gap-y-1 text-caption text-fg-secondary">
          {(["favor", "against", "abstain", "absent"] as const)
            .filter((o) => o !== "abstain" || tally.abstain > 0)
            .map((o) => (
              <li key={o} className="flex items-center gap-1.5">
                <OutcomeShape outcome={o} size={9} />
                {outcomeLabel(o)} <span className="tabular font-medium text-fg">{tally[o]}</span>
              </li>
            ))}
        </ul>
      </div>
    );
  }

  return (
    // Chip size uses container-query units so labels shrink with the arc
    // and the collision estimate in viewBox units stays valid at any width.
    <div className={cn("relative mx-auto w-full max-w-md [container-type:inline-size]", className)}>
      {labels.map((l) => {
        const isActive = activeParty === l.party;
        const isSelected = selectedParty === l.party;
        return (
          <Tooltip key={l.party}>
            <TooltipTrigger asChild>
              <button
                type="button"
                aria-pressed={isSelected}
                onMouseEnter={() => setHoveredParty(l.party)}
                onMouseLeave={() => setHoveredParty(null)}
                onFocus={() => setHoveredParty(l.party)}
                onBlur={() => setHoveredParty(null)}
                onClick={() => onSelectParty?.(isSelected ? null : l.party)}
                style={pct(l.x, l.y)}
                className={cn(
                  // appearance-none: without it iOS 26 Safari restyles bare
                  // buttons as large fixed-size glass circles, wrecking the
                  // chip layout entirely.
                  "absolute z-10 appearance-none -translate-x-1/2 -translate-y-1/2 whitespace-nowrap rounded-full border px-[1.1cqw] py-[0.25cqw] text-[2.2cqw] font-medium tracking-wide transition-colors",
                  isSelected
                    ? "border-fg bg-fg text-bg"
                    : isActive
                      ? "border-line-control bg-surface-muted text-fg"
                      : "border-line-strong bg-bg/80 text-fg-muted hover:bg-surface-muted",
                )}
              >
                {l.sigla}
              </button>
            </TooltipTrigger>
            <TooltipContent side="top" className="text-xs">
              <p className="max-w-56 font-medium">{l.party}</p>
              {l.data && (
                <p className="tabular">
                  {t("voteFavor")}: {l.data.favor} · {t("voteAgainst")}: {l.data.against}
                  {l.data.abstain > 0 && (
                    <> · {t("voteAbstained")}: {l.data.abstain}</>
                  )}{" "}
                  · {t("voteAbsent")}: {l.data.absent}
                </p>
              )}
            </TooltipContent>
          </Tooltip>
        );
      })}
      <svg
        viewBox={`${VB.x} ${VB.y} ${VB.w} ${VB.h}`}
        role="img"
        aria-label={`${t("voteFavor")}: ${tally.favor}, ${t("voteAgainst")}: ${tally.against}, ${t("voteAbstained")}: ${tally.abstain}, ${t("voteAbsent")}: ${tally.absent}`}
      >
        {ordered.map((p, i) => {
          const seat = seats[i];
          const dimmed = activeParty !== null && wedgeKey(p.party) !== activeParty;
          return (
            <SeatShape
              key={p.id + p.outcome}
              outcome={toOutcome(p.outcome)}
              cx={seat.x}
              cy={seat.y}
              r={dotRadius}
              className={cn(
                "hemicycle-dot transition-opacity duration-150",
                dimmed && "opacity-15",
              )}
              style={{ animationDelay: `${i * stagger}ms` }}
            >
              <title>
                {`${p.first_name} ${p.last_name}${p.party ? ` (${p.party})` : ""}: ${outcomeLabel(p.outcome)}`}
              </title>
            </SeatShape>
          );
        })}
      </svg>
      <ul className="mt-1 flex flex-wrap justify-center gap-x-4 gap-y-1 text-caption text-fg-secondary">
        {(["favor", "against", "abstain", "absent"] as const)
          .filter((o) => o !== "abstain" || tally.abstain > 0)
          .map((o) => (
            <li key={o} className="flex items-center gap-1.5">
              <OutcomeShape outcome={o} size={9} />
              {outcomeLabel(o)} <span className="tabular font-medium text-fg">{tally[o]}</span>
            </li>
          ))}
      </ul>
    </div>
  );
}
