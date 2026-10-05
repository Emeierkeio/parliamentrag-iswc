"use client";

// Booth survey per ISWC 2026 (issue #21): raggiunta via QR al banchetto
// della demo. Mobile-first, una schermata, quattro affermazioni su scala
// 1-5, ruolo opzionale, commento libero.

import { useCallback, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";
import { config } from "@/config";
import { cn } from "@/lib/utils";
import { CentroBar } from "@/components/shell/CentroBar";
import { Button } from "@/components/ui/button";

const QUESTION_KEYS = ["q1", "q2", "q3", "q4"] as const;
const ROLE_KEYS = ["researcher", "journalist", "student", "citizen", "other"] as const;

type Answers = Partial<Record<(typeof QUESTION_KEYS)[number], number>>;

export default function IswcBoothPage() {
  const t = useTranslations("Booth");
  const locale = useLocale();
  const [answers, setAnswers] = useState<Answers>({});
  const [role, setRole] = useState<string | null>(null);
  const [comment, setComment] = useState("");
  const [sending, setSending] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  const complete = QUESTION_KEYS.every((k) => answers[k] !== undefined);

  const submit = useCallback(async () => {
    if (!complete || sending) return;
    setSending(true);
    try {
      await fetch(`${config.api.baseUrl}/feedback/booth`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          q1: answers.q1, q2: answers.q2, q3: answers.q3, q4: answers.q4,
          comment: comment.trim() || null,
          role,
          locale,
        }),
      });
      setSubmitted(true);
    } catch {
      // rete del centro congressi: si ringrazia comunque, il banchetto
      // raccoglie il resto a voce
      setSubmitted(true);
    }
  }, [answers, comment, role, locale, complete, sending]);

  if (submitted) {
    return (
      <div className="min-h-dvh bg-bg">
      <CentroBar />
      <main className="container-page pt-16 pb-20 md:pt-24">
        <div className="max-w-sm space-y-4">
          <Check className="h-8 w-8 text-brand-fg" strokeWidth={1.5} aria-hidden />
          <h1 className="serif-display text-3xl text-fg">
            {t("thanksTitle")}
          </h1>
          <p className="text-[15px] leading-7 text-fg-secondary">{t("thanksBody")}</p>
          <Link
            href="/sistemi"
            className="link group inline-flex items-center gap-1.5 text-sm"
          >
            {t("tryCta")}
            <ArrowRight className="w-3.5 h-3.5 transition-transform group-hover:translate-x-0.5" />
          </Link>
        </div>
      </main>
      </div>
    );
  }

  return (
    <div className="min-h-dvh overflow-x-hidden bg-bg">
      <CentroBar />
      <main className="container-page py-10">
      <div className="max-w-md">
        <header className="mb-8">
          <p className="label-mono mb-2">
            ISWC 2026 · Bari
          </p>
          <h1 className="serif-display text-3xl leading-tight text-fg">
            {t("title")}
          </h1>
          <p className="mt-3 text-[15px] leading-7 text-fg-secondary">{t("intro")}</p>
        </header>

        <div className="space-y-7">
          {QUESTION_KEYS.map((key, i) => (
            <fieldset key={key}>
              <legend className="mb-3 text-[15px] leading-6 text-fg">
                <span className="tabular mr-2 text-fg-muted">{i + 1}.</span>
                {t(key)}
              </legend>
              <div>
                <div className="flex justify-between gap-1.5">
                  {[1, 2, 3, 4, 5].map((v) => (
                    <button
                      key={v}
                      onClick={() => setAnswers((a) => ({ ...a, [key]: v }))}
                      aria-label={`${v}/5`}
                      className={cn(
                        "tabular h-11 flex-1 cursor-pointer rounded-full border text-sm transition-colors active:scale-[0.98]",
                        answers[key] === v
                          ? "border-brand bg-brand text-on-brand"
                          : "border-line-control text-fg-secondary hover:border-fg hover:text-fg",
                      )}
                    >
                      {v}
                    </button>
                  ))}
                </div>
                <div className="mt-1.5 flex justify-between text-caption text-fg-muted">
                  <span>{t("scaleLow")}</span>
                  <span>{t("scaleHigh")}</span>
                </div>
              </div>
            </fieldset>
          ))}

          <fieldset>
            <legend className="mb-3 text-label text-fg-muted">{t("roleLabel")}</legend>
            <div className="flex flex-wrap gap-2">
              {ROLE_KEYS.map((r) => (
                <button
                  key={r}
                  onClick={() => setRole(role === r ? null : r)}
                  className={cn(
                    "h-11 cursor-pointer rounded-full border px-4 text-sm transition-colors active:scale-[0.98]",
                    role === r
                      ? "border-brand bg-brand-soft text-brand-fg"
                      : "border-line-strong text-fg-secondary hover:border-line-control hover:text-fg",
                  )}
                >
                  {t(`role_${r}`)}
                </button>
              ))}
            </div>
          </fieldset>

          <div>
            <label htmlFor="booth-comment" className="mb-2 block text-label text-fg-muted">
              {t("commentLabel")}
            </label>
            <textarea
              id="booth-comment"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              maxLength={1000}
              rows={3}
              placeholder={t("commentPlaceholder")}
              className="w-full resize-none rounded-md border border-line-control bg-surface p-3 text-[15px] leading-6 text-fg transition-colors placeholder:text-fg-muted focus:border-fg focus:outline-none"
            />
          </div>

          <Button
            onClick={submit}
            disabled={!complete || sending}
            size="lg"
            variant={complete ? "default" : "secondary"}
            className={cn("w-full", !complete && "text-fg-muted disabled:opacity-100")}
          >
            {complete ? t("submit") : t("submitIncomplete")}
          </Button>
        </div>
      </div>
      </main>
    </div>
  );
}
