"use client";

import { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { getGroupAbbrev } from "@/config";
import type { VoteParticipant } from "@/types/timeline";
import { OutcomeShape, SeatShape, toOutcome } from "./outcomes";

export interface SeatPlan {
  legislature: number;
  seats: { seat: number; x: number; y: number; r: number; sector: string | null }[];
}

/* Floor plan of the Camera from camera.it/deputati (build/download_camera_seats.py),
   served as a static file: it changes only when the chamber is refurbished. */
let planPromise: Promise<SeatPlan | null> | null = null;
export function fetchSeatPlan(): Promise<SeatPlan | null> {
  planPromise ??= fetch("/aula/camera-xix.json")
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  return planPromise;
}

export function useSeatPlan(): SeatPlan | null {
  const [plan, setPlan] = useState<SeatPlan | null>(null);
  useEffect(() => {
    let live = true;
    fetchSeatPlan().then((p) => live && setPlan(p));
    return () => {
      live = false;
    };
  }, []);
  return plan;
}

/* Seats with deputies: the eleven sectors. Presidency, government benches,
   Comitato dei nove and extra seats are drawn as context only. */
const isDeputySector = (sector: string | null) => !!sector && /^S\d+$/.test(sector);

/**
 * Each deputy at their own seat in the Aula, marked with the outcome shape.
 * The seating is today's, so deputies who have left the Camera have no
 * seat; they are counted below the plan.
 */
export function SeatPlanHemicycle({
  plan,
  participants,
  activeKey,
  keyOf,
  className,
}: {
  plan: SeatPlan;
  participants: VoteParticipant[];
  activeKey: string | null;
  keyOf: (party: string | null) => string;
  className?: string;
}) {
  const t = useTranslations("Timeline");
  const { seats, viewBox, bySeat, unseated } = useMemo(() => {
    const xs = plan.seats.map((s) => s.x);
    const ys = plan.seats.map((s) => s.y);
    const pad = 40;
    const minX = Math.min(...xs) - pad;
    const minY = Math.min(...ys) - pad;
    const viewBox = `${minX} ${minY} ${Math.max(...xs) - minX + pad} ${Math.max(...ys) - minY + pad}`;
    const bySeat = new Map<number, VoteParticipant>();
    const unseated: VoteParticipant[] = [];
    for (const p of participants) {
      if (p.seat != null) bySeat.set(p.seat, p);
      else unseated.push(p);
    }
    return { seats: plan.seats, viewBox, bySeat, unseated };
  }, [plan, participants]);

  const outcomeLabel = (outcome: string) =>
    outcome === "favor"
      ? t("voteFavor")
      : outcome === "against"
        ? t("voteAgainst")
        : outcome === "abstain"
          ? t("voteAbstained")
          : t("voteAbsent");

  return (
    <div className={cn("flex flex-col gap-2", className)}>
      <svg viewBox={viewBox} role="img" aria-label={t("seatPlanLabel")} className="w-full">
        {seats.map((s) => {
          const p = bySeat.get(s.seat);
          if (!p) {
            return (
              <circle
                key={s.seat}
                cx={s.x}
                cy={s.y}
                r={s.r * 0.55}
                className={isDeputySector(s.sector) ? "fill-line-strong" : "fill-line"}
              />
            );
          }
          const dimmed = activeKey !== null && keyOf(p.party) !== activeKey;
          return (
            <SeatShape
              key={s.seat}
              outcome={toOutcome(p.outcome)}
              cx={s.x}
              cy={s.y}
              r={s.r * 0.8}
              className={cn("transition-opacity duration-150", dimmed && "opacity-15")}
            >
              <title>
                {`${p.first_name} ${p.last_name}${p.party ? ` (${getGroupAbbrev(p.party)})` : ""}: ${outcomeLabel(p.outcome)}`}
              </title>
            </SeatShape>
          );
        })}
      </svg>
      <div className="flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-caption text-fg-muted">
        <span>{t("seatPlanNote")}</span>
        {unseated.length > 0 && (
          <span className="inline-flex items-center gap-1.5">
            <OutcomeShape outcome="absent" size={8} />
            {t("seatPlanUnseated", { count: unseated.length })}
          </span>
        )}
      </div>
    </div>
  );
}
