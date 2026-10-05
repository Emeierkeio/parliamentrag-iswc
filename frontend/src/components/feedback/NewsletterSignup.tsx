"use client";

import { useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, Loader2, Lock } from "lucide-react";
import { ParliamentragMark } from "@/components/brand/family";
import { cn } from "@/lib/utils";
import {
  fetchNewsletterEnabled,
  isSubscribed,
  markSubscribed,
  subscribeNewsletter,
  type NewsletterSource,
} from "./api";

/*
 * Opt-in form for project news, usable anywhere. It sends only the address and
 * where the form was shown: never a chat, a question or a feedback id (see
 * backend/app/routers/newsletter.py). Renders nothing until the backend says the
 * list is configured, and after a subscription on this device it shows the
 * confirmation instead of the form.
 *
 * One design across the ParliamentRAG family (same as Stenografo's block, titled «Resta aggiornato» here): the
 * pitch on the left, the form card on the right, on a rounded panel. Columns
 * follow the width of the container, so it also stacks inside dialogs.
 */
export function NewsletterSignup({
  source,
  className,
}: {
  source: NewsletterSource;
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
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(address)) {
      setError(t("errorEmail"));
      document.getElementById(`${ids}-email`)?.focus();
      return;
    }
    if (!consent) {
      setError(t("errorConsent"));
      document.getElementById(`${ids}-consent`)?.focus();
      return;
    }
    setSending(true);
    const ok = await subscribeNewsletter(address, source);
    setSending(false);
    if (!ok) return setError(t("errorServer"));
    markSubscribed();
    setDone(true);
  };

  const emailError = error === t("errorEmail");
  const consentError = error === t("errorConsent");

  return (
    <div className={cn("@container", className)}>
      <div className="rounded-[2rem] bg-stage px-6 py-[min(2.5rem,4svh)] @lg:px-10 md:rounded-[2.5rem] md:py-14">
        <section
          data-newsletter=""
          aria-labelledby={`${ids}-title`}
          className="mx-auto grid w-full max-w-5xl gap-[min(2.5rem,4svh)] py-2 @4xl:grid-cols-2 @4xl:items-center @4xl:gap-14"
        >
          <div>
            <ParliamentragMark size={44} />
            <h2
              id={`${ids}-title`}
              className="mt-[min(1.25rem,2.4svh)] text-[2rem] leading-[2.5rem] font-semibold tracking-[-0.03em] text-fg @lg:text-display-m @lg:leading-[1.05]"
            >
              {t("panelTitle")}
            </h2>
            <p className="mt-[min(1rem,2svh)] max-w-md text-lg leading-7 text-fg-secondary max-md:text-base max-md:leading-6">
              {t("panelLead")}
            </p>
            <ul className="mt-7 flex flex-col gap-3 max-md:hidden">
              {(["panelPoint1", "panelPoint2", "panelPoint3"] as const).map((k) => (
                <li key={k} className="flex items-center gap-3 text-base leading-6 text-fg">
                  <span
                    aria-hidden
                    className="grid size-7 shrink-0 place-items-center rounded-full bg-brand-soft text-brand-fg"
                  >
                    <Check size={16} strokeWidth={2.25} />
                  </span>
                  {t(k)}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-[1.5rem] border border-line bg-surface p-[min(1.5rem,3svh)] shadow-[0_1px_0_var(--line),0_18px_40px_-28px_rgba(20,32,28,0.35)] max-md:px-5 @lg:p-10">
            <div aria-live="polite" role="status">
              {done && (
                <p className="mt-4 flex items-start gap-2 rounded-md bg-brand-soft p-3 text-sm text-fg">
                  <Check aria-hidden size={18} strokeWidth={2} className="mt-px shrink-0 text-brand-fg" />
                  {t("checkInbox")}
                </p>
              )}
              {error && !emailError && !consentError && (
                <p className="mt-4 text-sm text-danger-fg">{error}</p>
              )}
            </div>

            {!done && (
              <form noValidate onSubmit={submit} className="mt-4">
                <label htmlFor={`${ids}-email`} className="block text-sm font-medium text-fg">
                  {t("emailLabel")}
                </label>
                <div className="mt-1.5 flex flex-col gap-2 @sm:flex-row">
                  <input
                    id={`${ids}-email`}
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    spellCheck={false}
                    value={email}
                    onChange={(e) => {
                      setEmail(e.target.value);
                      setError(null);
                    }}
                    maxLength={254}
                    placeholder={t("emailPlaceholder")}
                    aria-invalid={emailError || undefined}
                    aria-describedby={emailError ? `${ids}-error` : undefined}
                    className={cn(
                      "min-h-11 w-full min-w-0 flex-1 rounded-full border bg-surface px-4 text-base text-fg outline-none placeholder:text-fg-muted focus-visible:border-focus focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                      emailError ? "border-danger" : "border-line-control",
                    )}
                  />
                  <button
                    type="submit"
                    disabled={sending}
                    className="inline-flex h-11 shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-full bg-brand px-5 text-sm font-medium text-on-brand transition-[background-color,transform] hover:bg-brand-hover active:scale-[0.98] disabled:pointer-events-none disabled:opacity-45"
                  >
                    {sending && <Loader2 aria-hidden size={16} strokeWidth={2} className="motion-safe:animate-spin" />}
                    {sending ? t("sending") : t("submit")}
                  </button>
                </div>
                {emailError && (
                  <p id={`${ids}-error`} className="mt-1.5 text-label text-danger-fg">
                    {error}
                  </p>
                )}
                <div className="mt-3 flex items-start gap-3">
                  <input
                    id={`${ids}-consent`}
                    type="checkbox"
                    checked={consent}
                    onChange={(e) => {
                      setConsent(e.target.checked);
                      setError(null);
                    }}
                    aria-invalid={consentError || undefined}
                    aria-describedby={consentError ? `${ids}-error` : undefined}
                    className="mt-0.5 size-5 shrink-0 cursor-pointer accent-[var(--brand)] max-md:mt-0 max-md:size-6"
                  />
                  <label
                    htmlFor={`${ids}-consent`}
                    className="min-h-6 cursor-pointer text-sm text-fg-secondary max-md:min-h-11"
                  >
                    {t.rich("consent", {
                      link: (chunks) => (
                        <a href="/privacy#newsletter" target="_blank" rel="noopener noreferrer" className="link">
                          {chunks}
                        </a>
                      ),
                    })}
                  </label>
                </div>
                {consentError && (
                  <p id={`${ids}-error`} className="mt-1.5 text-label text-danger-fg">
                    {error}
                  </p>
                )}
              </form>
            )}

            <p className="mt-6 flex items-start gap-2 border-t border-line pt-5 text-label text-fg-muted max-md:hidden">
              <Lock aria-hidden size={14} strokeWidth={1.75} className="mt-0.5 shrink-0" />
              {t("panelPrivacy")}
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
