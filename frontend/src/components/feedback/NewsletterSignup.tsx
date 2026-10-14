"use client";

import { useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Loader2, Mail } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchNewsletterEnabled,
  isSubscribed,
  markSubscribed,
  subscribeNewsletter,
  type NewsletterSource,
} from "./api";

type Variant = "section" | "card" | "compact";

/*
 * Opt-in form for project news, usable anywhere. It sends only the address and
 * where the form was shown: never a chat, a question or a feedback id (see
 * backend/app/routers/newsletter.py). Renders nothing until the backend says the
 * list is configured, and after a subscription on this device it shows the
 * confirmation instead of the form.
 */
export function NewsletterSignup({
  source,
  variant = "card",
  className,
}: {
  source: NewsletterSource;
  variant?: Variant;
  className?: string;
}) {
  const t = useTranslations("Newsletter");
  const ids = useId();
  const [enabled, setEnabled] = useState(false);
  const [done, setDone] = useState(false);
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    // localStorage is client-only: read it with the status, not during render.
    fetchNewsletterEnabled().then((on) => {
      if (!alive) return;
      setDone(isSubscribed());
      setEnabled(on);
    });
    return () => {
      alive = false;
    };
  }, []);

  if (!enabled) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) return setError(t("errorEmail"));
    if (!consent) return setError(t("errorConsent"));
    setSending(true);
    const ok = await subscribeNewsletter(address, source);
    setSending(false);
    if (!ok) return setError(t("errorServer"));
    markSubscribed();
    setDone(true);
  };

  const compact = variant === "compact";

  const intro = (
    <div className={cn(variant === "section" && "md:max-w-md")}>
      <h2
        className={cn(
          "flex items-center gap-2 font-medium text-foreground",
          variant === "section" ? "text-xl sm:text-2xl tracking-tight" : "text-[15px]"
        )}
      >
        {!compact && <Mail className="h-4 w-4 shrink-0 text-primary" strokeWidth={1.75} aria-hidden />}
        {t("title")}
      </h2>
      <p className={cn("mt-1.5 leading-relaxed text-muted-foreground", compact ? "text-[13px]" : "text-sm")}>
        {t("body")}
      </p>
    </div>
  );

  if (done) {
    return (
      <div className={cn(frame(variant), className)}>
        {intro}
        <p role="status" className="flex items-start gap-2 text-sm text-foreground">
          <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden />
          {t("checkInbox")}
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} noValidate className={cn(frame(variant), className)}>
      {intro}
      <div className="grid gap-2.5 content-start w-full">
        <label htmlFor={`${ids}-email`} className="text-[13px] font-medium text-foreground">
          {t("emailLabel")}
        </label>
        <div className={cn("flex gap-2", compact && "flex-col")}>
          <input
            id={`${ids}-email`}
            type="email"
            inputMode="email"
            autoComplete="email"
            value={email}
            onChange={(e) => {
              setEmail(e.target.value);
              setError(null);
            }}
            maxLength={254}
            placeholder={t("emailPlaceholder")}
            aria-invalid={error === t("errorEmail") || undefined}
            aria-describedby={error ? `${ids}-error` : undefined}
            className={cn(compact ? "w-full" : "flex-1", "h-10 min-w-0 rounded-md border border-input bg-background px-3 text-base sm:text-sm text-foreground placeholder:text-muted-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring")}
          />
          <button
            type="submit"
            disabled={sending}
            className="inline-flex h-10 shrink-0 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-60"
          >
            {sending && <Loader2 className="h-4 w-4 motion-safe:animate-spin" aria-hidden />}
            {sending ? t("sending") : t("submit")}
          </button>
        </div>
        <label
          htmlFor={`${ids}-consent`}
          className="flex cursor-pointer items-start gap-2.5 text-[12px] leading-5 text-muted-foreground"
        >
          <input
            id={`${ids}-consent`}
            type="checkbox"
            checked={consent}
            onChange={(e) => {
              setConsent(e.target.checked);
              setError(null);
            }}
            className="mt-[3px] h-3.5 w-3.5 shrink-0 cursor-pointer accent-[var(--primary)]"
          />
          <span>
            {t.rich("consent", {
              link: (chunks) => (
                <a
                  href="/privacy#newsletter"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-foreground underline underline-offset-2 hover:text-primary"
                >
                  {chunks}
                </a>
              ),
            })}
          </span>
        </label>
        {error && (
          <p id={`${ids}-error`} role="alert" className="text-[13px] text-destructive">
            {error}
          </p>
        )}
      </div>
    </form>
  );
}

function frame(variant: Variant) {
  switch (variant) {
    case "section":
      return "grid gap-6 md:grid-cols-[1fr_1.1fr] md:gap-12 items-start";
    case "compact":
      return "grid gap-3";
    default:
      return "grid gap-4 rounded-lg border border-border bg-card p-5";
  }
}
