"use client";

import { useState, useEffect, useId } from "react";
import { useTranslations } from "next-intl";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { InterventionRow } from "./InterventionRow";
import { getDebateDetail } from "@/lib/timeline-api";
import type { DebateDetailResponse } from "@/types/timeline";

interface DebateDetailProps {
  debateId: string;
  debateTitle: string;
  sessionDate: string;
}

type DetailState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; data: DebateDetailResponse }
  | { status: "error" };

/* Section order tells the story of a debate: what was discussed (recap),
   who spoke (speakers). Votes are recorded per sitting, so they live at
   session level (SessionVotesSheet), not here. The order of business is
   procedural minutiae and sits collapsed at the bottom. */
export function DebateDetail({
  debateId,
}: DebateDetailProps) {
  const t = useTranslations("Timeline");
  const phasesId = useId();
  const [detail, setDetail] = useState<DetailState>({ status: "idle" });
  const [phasesOpen, setPhasesOpen] = useState(false);

  useEffect(() => {
    if (detail.status !== "idle") return;
    setDetail({ status: "loading" });
    getDebateDetail(debateId)
      .then((data) => setDetail({ status: "loaded", data }))
      .catch(() => setDetail({ status: "error" }));
  }, [debateId, detail.status]);

  if (detail.status === "loading" || detail.status === "idle") {
    return (
      <div className="py-4 mt-2 space-y-2">
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-full" />
        <Skeleton className="h-3 w-1/2" />
      </div>
    );
  }

  if (detail.status === "error") {
    return (
      <div className="py-4 mt-2">
        <p className="text-sm text-fg-muted">
          Unable to load debate details
        </p>
      </div>
    );
  }

  const { data } = detail;

  const substantivePhases = data.phases.filter((p) => p.speech_count > 0);
  const emptyPhaseCount = data.phases.length - substantivePhases.length;

  return (
    <div className="py-4">
      {/* 1. Context: acts under discussion */}
      {data.acts.length > 0 && (
        <div className="mb-3 flex flex-wrap gap-1">
          {data.acts.map((act) => (
            <Badge key={act.id} variant="outline" className="text-xs">
              {act.title || act.type || act.id}
            </Badge>
          ))}
        </div>
      )}

      {/* 2. What was discussed */}
      {data.recap ? (
        <p className="text-sm leading-relaxed text-fg-secondary">{data.recap}</p>
      ) : (
        <p className="text-xs text-fg-muted italic">
          {data.phases.reduce((sum, p) => sum + p.speech_count, 0) < 3
            ? t("shortDebateNoSummary")
            : t("summaryNotYetGenerated")}
        </p>
      )}

      {/* 3. Who spoke, chronological: one row per speech slot, so a
          deputy who takes the floor twice appears twice, in order */}
      {data.interventions.length > 0 && (
        <section className="mt-6">
          <h4 className="label-mono mb-2">
            {t("interventionsHeading")} ({data.interventions.length})
          </h4>
          <div>
            {data.interventions.map((intervention) => (
              <InterventionRow
                key={intervention.speech_id}
                intervention={intervention}
                debateId={debateId}
              />
            ))}
          </div>
        </section>
      )}

      {/* 4. Order of business: procedural detail, collapsed by default */}
      {data.phases.length > 0 && (
        <section className="mt-6">
          <Collapsible open={phasesOpen} onOpenChange={setPhasesOpen}>
            <CollapsibleTrigger
              className="inline-flex min-h-8 items-center gap-1 text-sm font-medium text-fg-secondary hover:text-fg transition-colors"
              aria-expanded={phasesOpen}
              aria-controls={phasesId}
            >
              <ChevronRight
                className={cn("h-4 w-4 transition-transform duration-200", phasesOpen && "rotate-90")}
                aria-hidden
              />
              {t("phasesHeading")}
            </CollapsibleTrigger>
            <CollapsibleContent id={phasesId} role="region">
              <div className="mt-2 space-y-1">
                {substantivePhases.map((phase) => (
                  <div
                    key={phase.id}
                    className="flex items-baseline justify-between gap-3 text-xs"
                  >
                    <span className="text-fg-secondary leading-snug">{phase.title}</span>
                    <span className="tabular shrink-0 text-fg-muted">
                      {t("speechCount", { count: phase.speech_count })}
                    </span>
                  </div>
                ))}
                {emptyPhaseCount > 0 && (
                  <p className="text-xs text-fg-muted">
                    {t("phasesNoSpeeches", { count: emptyPhaseCount })}
                  </p>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        </section>
      )}
    </div>
  );
}
