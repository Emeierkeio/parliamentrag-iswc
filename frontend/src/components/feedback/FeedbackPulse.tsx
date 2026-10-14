"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ThumbsUp, ThumbsDown, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { FeedbackDialog } from "./FeedbackDialog";
import { AnswerFeedbackDialog, type AnswerFeedbackPayload } from "./AnswerFeedbackDialog";
import {
  fetchNewsletterEnabled, isSubscribed, markSubscribed, postDetails, postVote, subscribeNewsletter,
  type Vote,
} from "./api";

// Feedback per strumento: il pollice registra subito il voto, poi un
// dialog (la versione compatta del survey /iswc) raccoglie il resto da
// chi ha voglia. Il widget riappare dopo 60 giorni (voto) o 14 (chiusura).

const GIVEN_TTL_MS = 60 * 24 * 60 * 60 * 1000;
const DISMISSED_TTL_MS = 14 * 24 * 60 * 60 * 1000;

function storageKey(tool: string) {
  return `prag-feedback:${tool}`;
}

function isSnoozed(tool: string): boolean {
  try {
    const raw = localStorage.getItem(storageKey(tool));
    if (!raw) return false;
    const { status, at } = JSON.parse(raw);
    const ttl = status === "given" ? GIVEN_TTL_MS : DISMISSED_TTL_MS;
    return Date.now() - at < ttl;
  } catch {
    return false;
  }
}

function snooze(tool: string, status: "given" | "dismissed") {
  try {
    localStorage.setItem(storageKey(tool), JSON.stringify({ status, at: Date.now() }));
  } catch {
    // storage pieno o bloccato: il widget si ripresenterà, pazienza
  }
}

interface FeedbackPulseProps {
  tool: "chat" | "search" | "ranking" | "compass" | "timeline" | "explorer" | "data";
  context?: string;
  className?: string;
}

export function FeedbackPulse({ tool, context, className }: FeedbackPulseProps) {
  const t = useTranslations("Feedback");
  const locale = useLocale();
  const [stage, setStage] = useState<"idle" | "dialog" | "thanks" | "hidden">("hidden");

  useEffect(() => {
    setStage(isSnoozed(tool) ? "hidden" : "idle");
  }, [tool]);

  useEffect(() => {
    if (stage !== "thanks") return;
    const timer = setTimeout(() => setStage("hidden"), 2500);
    return () => clearTimeout(timer);
  }, [stage]);

  const vote = useCallback((value: "up" | "down") => {
    snooze(tool, "given");
    setStage("dialog");
    void postVote(tool, value, context, locale);
  }, [tool, context, locale]);

  const dismiss = useCallback(() => {
    snooze(tool, "dismissed");
    setStage("hidden");
  }, [tool]);

  if (stage === "hidden") return null;

  return (
    <div
      className={cn(
        "group/fb mt-6 pt-3 border-t border-border/60 text-[13px] text-muted-foreground",
        className,
      )}
    >
      {(stage === "idle" || stage === "dialog") && (
        <div className="flex items-center gap-4">
          <span className="text-foreground">{t("prompt")}</span>
          <div className="flex items-center gap-2.5">
            <button
              onClick={() => vote("up")}
              aria-label={t("voteUpAria")}
              className="p-1 -m-1 text-muted-foreground hover:text-primary transition-all duration-150 hover:-translate-y-0.5 cursor-pointer"
            >
              <ThumbsUp className="h-4 w-4" strokeWidth={1.75} />
            </button>
            <button
              onClick={() => vote("down")}
              aria-label={t("voteDownAria")}
              className="p-1 -m-1 text-muted-foreground hover:text-primary transition-all duration-150 hover:translate-y-0.5 cursor-pointer"
            >
              <ThumbsDown className="h-4 w-4" strokeWidth={1.75} />
            </button>
          </div>
          <button
            onClick={dismiss}
            aria-label={t("dismissAria")}
            className="ml-auto p-1 -m-1 text-muted-foreground/0 group-hover/fb:text-muted-foreground/60 hover:!text-foreground transition-colors cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>
      )}

      {stage === "thanks" && (
        <p className="animate-in fade-in duration-300">{t("thanks")}</p>
      )}

      <FeedbackDialog
        open={stage === "dialog"}
        onClose={() => setStage("thanks")}
        tool={tool}
        context={context}
      />
    </div>
  );
}

// Pollici per risposta nella chat: sempre visibili, senza snooze. Il
// dialog si apre da solo quando chi legge arriva in fondo a una risposta
// appena generata; se lo chiude senza votare né iscriversi, per il resto
// della sessione resta manuale.

const AUTO_OPEN_KEY = "prag-answer-feedback-declined";

function autoOpenDeclined(): boolean {
  try {
    return sessionStorage.getItem(AUTO_OPEN_KEY) === "1";
  } catch {
    return true;
  }
}

function markAutoOpenDeclined() {
  try {
    sessionStorage.setItem(AUTO_OPEN_KEY, "1");
  } catch {
    // without storage the dialog stays manual
  }
}

interface AnswerFeedbackProps {
  context?: string;
  /** True only for an answer generated in this view, not one reloaded from history. */
  fresh?: boolean;
  className?: string;
}

export function AnswerFeedback({ context, fresh = false, className }: AnswerFeedbackProps) {
  const t = useTranslations("Feedback");
  const locale = useLocale();
  const [voted, setVoted] = useState<Vote | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [thanks, setThanks] = useState<"thanks" | "checkInbox" | null>(null);
  const [showNewsletter, setShowNewsletter] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const idRef = useRef<Promise<string | null> | null>(null);
  const postedVoteRef = useRef<Vote | null>(null);

  const ta = useTranslations("AnswerFeedback");
  const subscribedNowRef = useRef(false);

  useEffect(() => {
    if (!thanks) return;
    const timer = setTimeout(() => setThanks(null), thanks === "checkInbox" ? 8000 : 2500);
    return () => clearTimeout(timer);
  }, [thanks]);

  const openDialog = useCallback(async () => {
    const enabled = !isSubscribed() && (await fetchNewsletterEnabled());
    setShowNewsletter(enabled);
    setDialogOpen(true);
  }, []);

  useEffect(() => {
    const el = rootRef.current;
    if (!fresh || !el || autoOpenDeclined()) return;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      if (autoOpenDeclined()) return;
      void openDialog();
    }, { threshold: 1 });
    observer.observe(el);
    return () => observer.disconnect();
  }, [fresh, openDialog]);

  const vote = useCallback((value: Vote) => {
    setVoted(value);
    if (!idRef.current) {
      postedVoteRef.current = value;
      idRef.current = postVote("chat", value, context, locale);
    }
  }, [context, locale]);

  const voteInline = useCallback((value: Vote) => {
    vote(value);
    void openDialog();
  }, [vote, openDialog]);

  const submit = useCallback(async ({ reasons, comment, email }: AnswerFeedbackPayload) => {
    const id = idRef.current ? await idRef.current : null;
    const voteChanged = voted !== null && voted !== postedVoteRef.current;
    if (id && (reasons.length > 0 || comment || voteChanged)) {
      await postDetails(id, {
        vote: voteChanged ? voted : undefined,
        reasons: reasons.length > 0 ? reasons : undefined,
        comment: comment || undefined,
      });
      postedVoteRef.current = voted;
    }
    if (email) {
      if (!(await subscribeNewsletter(email, "feedback"))) return "email_failed";
      markSubscribed();
      subscribedNowRef.current = true;
    }
    return "ok";
  }, [voted]);

  const close = useCallback(() => {
    setDialogOpen(false);
    if (!voted && !subscribedNowRef.current) markAutoOpenDeclined();
    if (subscribedNowRef.current) {
      subscribedNowRef.current = false;
      setThanks("checkInbox");
    } else if (voted) {
      setThanks("thanks");
    }
    if (!voted) return;
    const pending = idRef.current;
    if (pending && voted !== postedVoteRef.current) {
      postedVoteRef.current = voted;
      void pending.then((id) => { if (id) void postDetails(id, { vote: voted }); });
    }
  }, [voted]);

  return (
    <div
      ref={rootRef}
      className={cn(
        "mt-5 inline-block border border-border bg-muted/40 px-4 py-2.5",
        "animate-in fade-in slide-in-from-bottom-1 duration-500",
        className,
      )}
    >
      <div className="flex items-center gap-4">
        {!voted && <span className="text-[13px] text-foreground">{t("prompt")}</span>}
        <div className="flex items-center gap-3">
          <button
            onClick={() => !voted && voteInline("up")}
            disabled={voted !== null}
            aria-label={t("voteUpAria")}
            className={cn(
              "p-1 -m-1 transition-all duration-150",
              voted === "up" ? "text-primary" : "text-muted-foreground",
              !voted && "hover:text-primary hover:-translate-y-0.5 cursor-pointer",
              voted === "down" && "opacity-30",
            )}
          >
            <ThumbsUp className={cn("h-4 w-4", voted === "up" && "fill-current")} strokeWidth={1.75} />
          </button>
          <button
            onClick={() => !voted && voteInline("down")}
            disabled={voted !== null}
            aria-label={t("voteDownAria")}
            className={cn(
              "p-1 -m-1 transition-all duration-150",
              voted === "down" ? "text-primary" : "text-muted-foreground",
              !voted && "hover:text-primary hover:translate-y-0.5 cursor-pointer",
              voted === "up" && "opacity-30",
            )}
          >
            <ThumbsDown className={cn("h-4 w-4", voted === "down" && "fill-current")} strokeWidth={1.75} />
          </button>
        </div>
        {thanks && (
          <span role="status" className="text-[13px] text-muted-foreground animate-in fade-in duration-300">
            {thanks === "checkInbox" ? ta("checkInbox") : t("thanks")}
          </span>
        )}
      </div>

      <AnswerFeedbackDialog
        open={dialogOpen}
        vote={voted}
        showNewsletter={showNewsletter}
        onVote={vote}
        onSubmit={submit}
        onClose={close}
      />
    </div>
  );
}
