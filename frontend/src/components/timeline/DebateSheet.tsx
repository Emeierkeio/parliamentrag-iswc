"use client";

import { useTranslations } from "next-intl";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { DebateDetail } from "./DebateDetail";

interface DebateSheetProps {
  debate: { id: string; title: string } | null;
  sessionNumber: number | null;
  sessionDate: string;
  onOpenChange: (open: boolean) => void;
}

/* The debate detail lives in a side panel instead of an inline accordion:
   the timeline stays a scannable list and the session/debate context is
   pinned at the top while long speeches scroll underneath. */
export function DebateSheet({
  debate,
  sessionNumber,
  sessionDate,
  onOpenChange,
}: DebateSheetProps) {
  const t = useTranslations("Timeline");

  const formattedDate = new Date(sessionDate).toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <Sheet open={debate !== null} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="w-full gap-0 p-0 sm:max-w-xl lg:max-w-2xl"
      >
        {debate && (
          <>
            <SheetHeader className="border-b border-line px-6 py-4">
              <SheetDescription className="label-mono">
                {sessionNumber !== null
                  ? t("sessionRef", { number: sessionNumber, date: formattedDate })
                  : formattedDate}
              </SheetDescription>
              <SheetTitle className="text-base leading-snug pr-6">
                {debate.title}
              </SheetTitle>
            </SheetHeader>
            <div className="flex-1 overflow-y-auto px-6 pb-8">
              <DebateDetail
                debateId={debate.id}
                debateTitle={debate.title}
                sessionDate={sessionDate}
              />
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
