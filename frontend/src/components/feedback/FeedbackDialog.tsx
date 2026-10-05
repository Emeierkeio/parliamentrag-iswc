"use client";

// Dialog post-voto: la versione compatta del survey /iswc. Si apre al
// click sul pollice; tutto è facoltativo, chiudere è sempre gratis.

import { useCallback, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { config } from "@/config";
import { cn } from "@/lib/utils";

const QUESTION_KEYS = ["q1", "q2", "q3", "q4"] as const;

type Answers = Partial<Record<(typeof QUESTION_KEYS)[number], number>>;

interface FeedbackDialogProps {
  open: boolean;
  onClose: () => void;
  tool: string;
  context?: string;
}

export function FeedbackDialog({ open, onClose, tool, context }: FeedbackDialogProps) {
  const tb = useTranslations("Booth");
  const tf = useTranslations("Feedback");
  const locale = useLocale();
  const [answers, setAnswers] = useState<Answers>({});
  const [comment, setComment] = useState("");

  const hasContent = Object.keys(answers).length > 0 || comment.trim().length > 0;

  const submit = useCallback(async () => {
    if (hasContent) {
      try {
        await fetch(`${config.api.baseUrl}/feedback/booth`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...answers,
            comment: comment.trim() || null,
            source: "widget",
            tool,
            context,
            locale,
          }),
        });
      } catch {
        // mai bloccare l'utente per un feedback
      }
    }
    onClose();
  }, [answers, comment, hasContent, tool, context, locale, onClose]);

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        className={cn(
          "sm:max-w-md gap-0 p-6 max-h-[88dvh] overflow-y-auto",
          // Sotto i 640px: bottom sheet, non modale centrato: con la
          // tastiera aperta un dialog centrato balla, il sheet no
          "max-sm:!top-auto max-sm:!bottom-0 max-sm:!left-0 max-sm:!right-0",
          "max-sm:!translate-x-0 max-sm:!translate-y-0 max-sm:!max-w-full",
          "max-sm:!rounded-b-none max-sm:rounded-t-lg max-sm:border-x-0 max-sm:border-b-0",
          "max-sm:data-[state=open]:!slide-in-from-bottom-6 max-sm:data-[state=open]:!zoom-in-100",
          "max-sm:pb-[calc(1.5rem+env(safe-area-inset-bottom))]",
        )}
      >
        <DialogHeader className="mb-4">
          <DialogTitle className="serif-display text-2xl text-fg text-left">
            {tf("dialogTitle")}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-5">
          {QUESTION_KEYS.map((key, i) => (
            <fieldset key={key}>
              <legend className="text-[13px] leading-5 text-fg mb-2">
                <span className="font-mono text-xs text-fg-muted mr-1.5">{i + 1}.</span>
                {tb(key)}
              </legend>
              <div>
                <div className="flex justify-between gap-1.5">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      onClick={() => setAnswers((a) =>
                        a[key] === v ? { ...a, [key]: undefined } : { ...a, [key]: v })}
                      aria-label={`${v}/5`}
                      className={cn(
                        "h-10 sm:h-9 flex-1 rounded-full border font-mono text-[13px] tabular transition-[background-color,border-color,color,transform] duration-[var(--duration-fast)] active:scale-[0.98] cursor-pointer",
                        answers[key] === v
                          ? "border-brand bg-brand text-on-brand"
                          : "border-line-strong text-fg-secondary hover:border-fg hover:text-fg",
                      )}
                    >
                      {v}
                    </button>
                  ))}
                </div>
                <div className="mt-1 flex justify-between text-[11px] text-fg-muted">
                  <span>{tb("scaleLow")}</span>
                  <span>{tb("scaleHigh")}</span>
                </div>
              </div>
            </fieldset>
          ))}

          <textarea
            value={comment}
            onChange={(e) => setComment(e.target.value)}
            maxLength={1000}
            rows={2}
            placeholder={tb("commentPlaceholder")}
            className="w-full rounded-md bg-surface border border-line-control p-2.5 text-[13px] leading-5 text-fg placeholder:text-fg-muted focus:outline-none focus:border-focus transition-colors resize-none"
          />

          <div className="flex items-center gap-3">
            <button
              onClick={submit}
              className={cn(
                "flex-1 rounded-full py-3 sm:py-2.5 text-sm font-medium transition-[background-color,color,transform] duration-200 active:scale-[0.98] cursor-pointer",
                hasContent
                  ? "bg-brand text-on-brand hover:bg-brand-hover"
                  : "bg-surface-muted text-fg-secondary hover:bg-surface-sunken",
              )}
            >
              {hasContent ? tb("submit") : tf("skip")}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
