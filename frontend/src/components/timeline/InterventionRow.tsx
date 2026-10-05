"use client";

import { useState, useId } from "react";
import { useTranslations } from "next-intl";
import { Shield, ChevronDown, Loader2 } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn } from "@/lib/utils";
import { getSpeakerSummary } from "@/lib/timeline-api";
import type { InterventionInfo, SpeakerSummaryResponse } from "@/types/timeline";

interface InterventionRowProps {
  intervention: InterventionInfo;
  debateId: string;
}

/* One row per speech slot, in the order the floor was taken. Speech texts
   come from the per-speaker summary endpoint; the promise is cached per
   (debate, speaker) so a deputy with several interventions is fetched once. */
const summaryCache = new Map<string, Promise<SpeakerSummaryResponse>>();

function fetchSummary(debateId: string, speakerId: string) {
  const key = `${debateId}|${speakerId}`;
  let p = summaryCache.get(key);
  if (!p) {
    p = getSpeakerSummary(debateId, speakerId);
    summaryCache.set(key, p);
    p.catch(() => summaryCache.delete(key));
  }
  return p;
}

type TextState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "loaded"; text: string }
  | { status: "error" };

export function InterventionRow({ intervention, debateId }: InterventionRowProps) {
  const t = useTranslations("Timeline");
  const contentId = useId();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState<TextState>({ status: "idle" });

  const handleOpenChange = async (isOpen: boolean) => {
    setOpen(isOpen);
    if (isOpen && text.status === "idle") {
      setText({ status: "loading" });
      try {
        const data = await fetchSummary(debateId, intervention.speaker_id);
        const speech = data.speeches.find((s) => s.id === intervention.speech_id);
        if (speech) setText({ status: "loaded", text: speech.text });
        else setText({ status: "error" });
      } catch {
        setText({ status: "error" });
      }
    }
  };

  const fullName = `${intervention.first_name} ${intervention.last_name}`;

  return (
    <Collapsible open={open} onOpenChange={handleOpenChange}>
      <CollapsibleTrigger
        className={cn(
          "group flex w-full items-start gap-3 py-2.5 px-3 -mx-3 rounded-md text-left transition-colors",
          "hover:bg-surface-muted",
          open && "bg-surface-muted"
        )}
        aria-expanded={open}
        aria-controls={contentId}
      >
        <div className="flex-1 min-w-0 space-y-0.5">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-semibold leading-tight text-fg">
              {fullName}
            </span>
            {intervention.party && (
              <Badge
                variant="outline"
                className="text-[10px] px-1.5 py-0 font-medium shrink-0"
              >
                {intervention.party}
              </Badge>
            )}
            {intervention.is_government_member && (
              <Badge
                variant="default"
                className="text-[10px] px-1.5 py-0 gap-0.5 shrink-0"
              >
                <Shield className="h-2.5 w-2.5" />
              </Badge>
            )}
          </div>
          {(intervention.speaking_role || intervention.phase_title) && (
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              {intervention.speaking_role && (
                <span className="font-medium shrink-0">
                  {intervention.speaking_role}
                </span>
              )}
              {intervention.speaking_role && intervention.phase_title && (
                <span className="text-fg-faint">·</span>
              )}
              {intervention.phase_title && (
                <span className="truncate">{intervention.phase_title}</span>
              )}
            </div>
          )}
        </div>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-fg-faint transition-transform duration-200 mt-1",
            open && "rotate-180"
          )}
        />
      </CollapsibleTrigger>

      <CollapsibleContent id={contentId} role="region" aria-label={fullName}>
        <div className="ml-3 pl-3 border-l-2 border-line pb-2">
          {text.status === "loading" && (
            <div className="flex items-center gap-2 py-3 text-sm text-fg-muted">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              <span>{t("speakerSummaryLoading")}</span>
            </div>
          )}
          {text.status === "error" && (
            <p className="py-2 text-xs text-fg-muted">
              {t("speakerSummaryUnavailable")}
            </p>
          )}
          {text.status === "loaded" && (
            <p className="serif-display text-[15px] leading-relaxed text-fg-secondary whitespace-pre-line">
              {text.text}
            </p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
