"use client";

import { useId, useState } from "react";
import Image from "next/image";
import { useTranslations } from "next-intl";
import { ThumbsUp, ThumbsDown, Lock, Mail, X } from "lucide-react";
import { Dialog, DialogClose, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { REASONS, type Reason, type Vote } from "./api";

export interface AnswerFeedbackPayload {
  reasons: Reason[];
  comment: string;
  email: string | null;
}

interface AnswerFeedbackDialogProps {
  open: boolean;
  vote: Vote | null;
  showNewsletter: boolean;
  onVote: (vote: Vote) => void;
  onSubmit: (payload: AnswerFeedbackPayload) => Promise<"ok" | "email_failed">;
  onClose: () => void;
}

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

// The product accent for "useful" and the danger role for "not useful": green
// in the ecosystem is reserved for the "favorevole" vote outcome.
const VOTE_TONE: Record<Vote, { selected: string; hover: string; iconHover: string }> = {
  up: {
    selected: "border-brand bg-brand-soft text-brand-fg ring-1 ring-brand",
    hover: "hover:border-brand/60 hover:bg-surface-brand",
    iconHover: "group-hover:text-brand-fg group-hover:-translate-y-0.5",
  },
  down: {
    selected: "border-danger bg-danger-soft text-danger-fg ring-1 ring-danger",
    hover: "hover:border-danger/50 hover:bg-danger-soft/60",
    iconHover: "group-hover:text-danger-fg group-hover:translate-y-0.5",
  },
};

const FIELD =
  "w-full rounded-md bg-surface border border-line-control text-sm text-fg placeholder:text-fg-muted focus:outline-none focus:border-focus focus:ring-2 focus:ring-focus/20 transition-[border-color,box-shadow]";

export function AnswerFeedbackDialog({
  open,
  vote,
  showNewsletter,
  onVote,
  onSubmit,
  onClose,
}: AnswerFeedbackDialogProps) {
  const t = useTranslations("AnswerFeedback");
  const ids = useId();
  const [reasons, setReasons] = useState<Reason[]>([]);
  const [comment, setComment] = useState("");
  const [email, setEmail] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  const trimmedEmail = email.trim();
  const canSubmit = !sending && (vote !== null || trimmedEmail.length > 0);
  const submitLabel = sending
    ? t("sending")
    : trimmedEmail
      ? t(vote ? "submitBoth" : "submitSubscribe")
      : t("submit");

  const toggleReason = (r: Reason) =>
    setReasons((cur) => (cur.includes(r) ? cur.filter((x) => x !== r) : [...cur, r]));

  const submit = async () => {
    setError(null);
    if (trimmedEmail) {
      if (!EMAIL_RE.test(trimmedEmail)) {
        setError(t("errorEmail"));
        return;
      }
      if (!consent) {
        setError(t("errorConsent"));
        return;
      }
    }
    setSending(true);
    const result = await onSubmit({
      reasons: vote === "down" ? reasons : [],
      comment: comment.trim(),
      email: trimmedEmail || null,
    });
    setSending(false);
    if (result === "email_failed") {
      setError(t("errorServer"));
      return;
    }
    onClose();
  };

  const voteButton = (value: Vote, delay: string) => {
    const Icon = value === "up" ? ThumbsUp : ThumbsDown;
    const selected = vote === value;
    const dimmed = vote !== null && !selected;
    const tone = VOTE_TONE[value];
    return (
      <button
        type="button"
        onClick={() => onVote(value)}
        aria-pressed={selected}
        className={cn(
          "group flex items-center justify-center gap-3 h-14 rounded-full border text-[15px] font-medium",
          "animate-in fade-in slide-in-from-bottom-2 duration-300 fill-mode-both motion-reduce:animate-none",
          delay,
          "transition-[background-color,border-color,color,opacity,box-shadow] duration-200 cursor-pointer active:scale-[0.98]",
          selected ? tone.selected : cn("border-line-strong bg-surface text-fg", tone.hover),
          dimmed && "opacity-50 hover:opacity-100",
        )}
      >
        <Icon
          className={cn(
            "h-5 w-5 transition-transform duration-300 ease-[cubic-bezier(0.34,1.56,0.64,1)] motion-reduce:transition-none",
            selected
              ? cn("scale-110 fill-current", value === "up" ? "-rotate-12" : "rotate-12")
              : cn("text-fg-muted", tone.iconHover),
          )}
          strokeWidth={1.75}
        />
        {t(value === "up" ? "voteUp" : "voteDown")}
      </button>
    );
  };

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent
        // Focus the panel, not the first vote button: an auto-focused
        // "Useful" reads as a preselected answer
        onOpenAutoFocus={(e) => { e.preventDefault(); (e.currentTarget as HTMLElement).focus(); }}
        className={cn(
          "sm:max-w-2xl gap-0 p-0 max-h-[88dvh] overflow-y-auto overflow-x-hidden outline-none",
          // Below 640px: bottom sheet, a centred modal jumps when the keyboard opens
          "max-sm:!top-auto max-sm:!bottom-0 max-sm:!left-0 max-sm:!right-0",
          "max-sm:!translate-x-0 max-sm:!translate-y-0 max-sm:!max-w-full",
          "max-sm:!rounded-b-none max-sm:rounded-t-lg max-sm:border-x-0 max-sm:border-b-0",
          "max-sm:data-[state=open]:!slide-in-from-bottom-6 max-sm:data-[state=open]:!zoom-in-100",
        )}
        showCloseButton={false}
      >
        <header className="relative isolate overflow-hidden bg-brand px-6 pt-7 pb-6 sm:px-8 text-on-brand">
          <Image
            src="/logo.svg"
            alt=""
            width={224}
            height={156}
            aria-hidden
            className="pointer-events-none absolute -right-10 -bottom-12 -z-10 w-56 opacity-[0.09]"
          />
          <DialogTitle className="pr-8 serif-display text-2xl sm:text-[28px] leading-tight text-left">
            {t("title")}
          </DialogTitle>
          <DialogDescription className="mt-2 text-sm leading-relaxed text-on-brand/80">
            {t("subtitle")}
          </DialogDescription>
          <DialogClose
            className="absolute top-3 right-3 inline-flex size-9 items-center justify-center rounded-full text-on-brand/70 hover:text-on-brand hover:bg-on-brand/10 transition-colors cursor-pointer focus-visible:outline-on-brand"
          >
            <X className="h-4 w-4" />
            <span className="sr-only">{t("close")}</span>
          </DialogClose>
        </header>

        <div className="px-6 pt-6 pb-6 sm:px-8 max-sm:pb-[calc(1.5rem+env(safe-area-inset-bottom))]">
          <div className="grid grid-cols-2 gap-3">
            {voteButton("up", "delay-100")}
            {voteButton("down", "delay-200")}
          </div>

          {vote === "down" && (
            <fieldset className="mt-5 animate-in fade-in slide-in-from-top-1 duration-200">
              <legend className="text-[13px] text-fg mb-2">{t("reasonsLabel")}</legend>
              <div className="flex flex-wrap gap-2">
                {REASONS.map((r) => {
                  const on = reasons.includes(r);
                  return (
                    <button
                      key={r}
                      type="button"
                      onClick={() => toggleReason(r)}
                      aria-pressed={on}
                      className={cn(
                        "min-h-9 rounded-full px-3.5 py-1.5 border text-[13px] transition-[background-color,border-color,color,transform] duration-[var(--duration-fast)] active:scale-[0.98] cursor-pointer",
                        on
                          ? "border-danger bg-danger-soft text-danger-fg"
                          : "border-line-strong text-fg-secondary hover:border-fg hover:text-fg",
                      )}
                    >
                      {t(`reason_${r}`)}
                    </button>
                  );
                })}
              </div>
            </fieldset>
          )}

          {vote && (
            <div className="mt-5 grid gap-2 animate-in fade-in duration-200">
              <label htmlFor={`${ids}-comment`} className="text-[13px] text-fg">
                {t("commentLabel")}
              </label>
              <textarea
                id={`${ids}-comment`}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                maxLength={1000}
                rows={2}
                placeholder={t(vote === "down" ? "commentPlaceholderDown" : "commentPlaceholderUp")}
                className={cn(FIELD, "p-2.5 text-[13px] leading-5 resize-none")}
              />
            </div>
          )}

          {showNewsletter && (
            <section className="mt-6 rounded-md bg-surface-brand px-5 py-5 grid gap-4 sm:grid-cols-[1fr_1.15fr] sm:gap-6">
              <div>
                <h3 className="flex items-center gap-2 text-[15px] font-medium text-fg">
                  <Mail className="h-4 w-4 shrink-0 text-brand-fg" strokeWidth={1.75} aria-hidden />
                  {t("newsletterTitle")}
                </h3>
                <p className="mt-1.5 text-[13px] leading-5 text-fg-secondary">{t("newsletterBody")}</p>
              </div>
              <div className="grid gap-2.5 content-start">
                <div className="grid gap-1.5">
                  <label htmlFor={`${ids}-email`} className="text-[12px] text-fg">
                    {t("emailLabel")}
                  </label>
                  <input
                    id={`${ids}-email`}
                    type="email"
                    inputMode="email"
                    autoComplete="email"
                    value={email}
                    onChange={(e) => { setEmail(e.target.value); setError(null); }}
                    maxLength={254}
                    placeholder={t("emailPlaceholder")}
                    className={cn(FIELD, "h-10 px-3")}
                  />
                </div>
                {/* Consent only matters once there is an address to consent for */}
                {trimmedEmail && (
                  <label htmlFor={`${ids}-consent`} className="flex items-start gap-2.5 text-[12px] leading-5 text-fg-secondary cursor-pointer animate-in fade-in slide-in-from-top-1 duration-200">
                    <input
                      id={`${ids}-consent`}
                      type="checkbox"
                      checked={consent}
                      onChange={(e) => { setConsent(e.target.checked); setError(null); }}
                      className="mt-[3px] h-3.5 w-3.5 shrink-0 accent-[var(--brand)] cursor-pointer"
                    />
                    <span>
                      {t.rich("consent", {
                        link: (chunks) => (
                          <a
                            href="/privacy#newsletter"
                            target="_blank"
                            rel="noopener noreferrer"
                            className="underline underline-offset-2 text-fg hover:text-brand-fg"
                          >
                            {chunks}
                          </a>
                        ),
                      })}
                    </span>
                  </label>
                )}
              </div>
            </section>
          )}

          {error && (
            <p role="alert" className="mt-3 text-[13px] text-danger-fg">{error}</p>
          )}

          <div className="mt-6 flex flex-col-reverse gap-3 sm:flex-row sm:items-center sm:justify-between sm:gap-8">
            <p className="flex items-start gap-1.5 text-xs leading-4 text-fg-muted sm:max-w-sm">
              <Lock className="mt-px h-3 w-3 shrink-0" strokeWidth={1.75} aria-hidden />
              {t("anonNote")}
            </p>
            <button
              type="button"
              onClick={submit}
              disabled={!canSubmit}
              className={cn(
                "h-11 w-full sm:w-auto sm:min-w-40 shrink-0 rounded-full px-8 text-sm font-medium whitespace-nowrap transition-[background-color,color,transform] duration-200",
                canSubmit
                  ? "bg-brand text-on-brand hover:bg-brand-hover cursor-pointer active:scale-[0.98]"
                  : "bg-surface-muted text-fg-muted opacity-45 cursor-not-allowed",
              )}
            >
              {submitLabel}
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
