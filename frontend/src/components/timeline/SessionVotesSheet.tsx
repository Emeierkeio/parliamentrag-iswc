"use client";

import { useState, useEffect } from "react";
import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { VotesList } from "./VotesList";
import { getSessionVotes } from "@/lib/timeline-api";
import type { VoteInfo } from "@/types/timeline";

interface SessionVotesSheetProps {
  open: boolean;
  sessionId: string;
  sessionNumber: number | null;
  sessionDate: string;
  voteCount: number;
  onOpenChange: (open: boolean) => void;
}

type VotesState =
  | { status: "loading" }
  | { status: "loaded"; votes: VoteInfo[] }
  | { status: "error" };

/* Votes are recorded per sitting in the Camera data, so they get their own
   panel at session level instead of being repeated inside every debate. */
export function SessionVotesSheet({
  open,
  sessionId,
  sessionNumber,
  sessionDate,
  voteCount,
  onOpenChange,
}: SessionVotesSheetProps) {
  const t = useTranslations("Timeline");
  const [state, setState] = useState<VotesState>({ status: "loading" });

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setState({ status: "loading" });
    getSessionVotes(sessionId)
      .then((votes) => {
        if (!cancelled) setState({ status: "loaded", votes });
      })
      .catch(() => {
        if (!cancelled) setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [open, sessionId]);

  const formattedDate = new Date(sessionDate).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 p-0 sm:max-w-xl lg:max-w-2xl"
      >
        <SheetHeader className="border-b border-line px-6 py-4">
          <SheetDescription className="label-mono">
            {sessionNumber !== null
              ? t("sessionRef", { number: sessionNumber, date: formattedDate })
              : formattedDate}
          </SheetDescription>
          <SheetTitle className="text-base leading-snug pr-6">
            {t("votesLabel", { count: voteCount })}
          </SheetTitle>
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-6 py-4 pb-8">
          {state.status === "loading" && (
            <div className="space-y-2">
              <Skeleton className="h-3 w-48" />
              <Skeleton className="h-1 w-full max-w-xs" />
              <div className="pt-2 space-y-2">
                {Array.from({ length: 10 }, (_, i) => (
                  <Skeleton key={i} className="h-5 w-full" />
                ))}
              </div>
            </div>
          )}
          {state.status === "error" && (
            <p className="py-10 text-sm text-fg-muted text-center">
              {t("voteLoadError")}
            </p>
          )}
          {state.status === "loaded" && <VotesList votes={state.votes} />}
        </div>
      </SheetContent>
    </Sheet>
  );
}
