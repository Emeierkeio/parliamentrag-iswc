"use client";

import { useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Loader2, Lock, Mail } from "lucide-react";
import { Symbol } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";
import {
  fetchNewsletterEnabled,
  isSubscribed,
  markSubscribed,
  subscribeNewsletter,
  type NewsletterSource,
} from "./api";

type Variant = "section" | "card" | "compact" | "panel";

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

  if (variant === "panel") {
    return (
      <section
        aria-labelledby={`${ids}-title`}
        className={cn(
          "grid items-center gap-10 rounded-2xl bg-surface-muted px-6 py-10 md:grid-cols-[1fr_minmax(0,30rem)] md:gap-16 md:px-14 md:py-14",
          className,
        )}
      >
        <div className="flex flex-col gap-5">
          <Symbol size={44} />
          <h2 id={`${ids}-title`} className="text-3xl font-semibold tracking-[-0.035em] text-fg md:text-[2.5rem] md:leading-[1.1]">
            {t("panelTitle")}
          </h2>
          <p className="max-w-md text-[17px] leading-relaxed text-fg-secondary">{t("panelLead")}</p>
          <ul className="mt-1 flex flex-col gap-3">
            {(["panelPoint1", "panelPoint2", "panelPoint3"] as const).map((k) => (
              <li key={k} className="flex items-center gap-3 text-[15px] text-fg">
                <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-full bg-surface text-brand-fg">
                  <Check className="size-4" aria-hidden />
                </span>
                {t(k)}
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border border-line bg-surface p-6 shadow-float md:p-8">
          {done ? (
            <p role="status" className="flex items-start gap-2.5 text-[15px] text-fg">
              <Check className="mt-0.5 size-4 shrink-0 text-brand-fg" aria-hidden />
              {t("checkInbox")}
            </p>
          ) : (
            <form onSubmit={submit} noValidate className="flex flex-col gap-4">
              <label htmlFor={`${ids}-email`} className="text-sm font-medium text-fg">
                {t("emailLabel")}
              </label>
              <div className="flex flex-col gap-2.5 sm:flex-row">
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
                  className="h-12 min-w-0 flex-1 rounded-full border border-line-control bg-surface px-5 text-base text-fg outline-none placeholder:text-fg-muted focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
                />
                <button
                  type="submit"
                  disabled={sending}
                  className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-brand px-6 text-[15px] font-medium text-on-brand transition-colors hover:bg-brand-hover disabled:opacity-60"
                >
                  {sending && <Loader2 className="size-4 motion-safe:animate-spin" aria-hidden />}
                  {sending ? t("sending") : t("submit")}
                </button>
              </div>
              <label htmlFor={`${ids}-consent`} className="flex cursor-pointer items-start gap-3 text-sm leading-relaxed text-fg-secondary">
                <input
                  id={`${ids}-consent`}
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => {
                    setConsent(e.target.checked);
                    setError(null);
                  }}
                  className="mt-0.5 size-5 shrink-0 cursor-pointer rounded-xs accent-[var(--brand)]"
                />
                <span>
                  {t.rich("consent", {
                    link: (chunks) => (
                      <a
                        href="/privacy#newsletter"
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-brand-fg underline underline-offset-2 hover:text-fg"
                      >
                        {chunks}
                      </a>
                    ),
                  })}
                </span>
              </label>
              {error && (
                <p id={`${ids}-error`} role="alert" className="text-sm text-danger-fg">
                  {error}
                </p>
              )}
              <p className="mt-2 flex items-start gap-2.5 border-t border-line pt-4 text-[13px] leading-relaxed text-fg-muted">
                <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden />
                {t("panelPrivacy")}
              </p>
            </form>
          )}
        </div>
      </section>
    );
  }

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
