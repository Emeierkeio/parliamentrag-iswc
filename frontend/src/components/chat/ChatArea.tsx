"use client";

import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { MessageBubble } from "./MessageBubble";
import { ChatInput } from "./ChatInput";
import { ProgressIndicator, ProgressBanner, CompletedProgressStepper, ProgressFullPage } from "@/components/shared/ProgressIndicator";
import { TranslationBanner } from "@/components/shared/TranslationBanner";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import type { Message, ProcessingProgress } from "@/types";
import { ChevronRight, HelpCircle, History } from "lucide-react";
import { TOPICS } from "@/lib/constants";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface ChatAreaProps {
  messages: Message[];
  isLoading: boolean;
  progress: ProcessingProgress | null;
  lastCompletedProgress?: ProcessingProgress | null;
  onSendMessage: (message: string) => void;
  onCancelRequest: () => void;
  onOpenHistory?: () => void;
  className?: string;
  mobileMenuButton?: React.ReactNode;
  /** Inside the AppBar shell the bar's search field asks follow-ups. */
  hideTopBar?: boolean;
}

export function ChatArea({
  messages,
  isLoading,
  progress,
  lastCompletedProgress,
  onSendMessage,
  onCancelRequest,
  onOpenHistory,
  className,
  mobileMenuButton,
  hideTopBar = false,
}: ChatAreaProps) {
  const t = useTranslations("WelcomeScreen");
  const scrollRef = useRef<HTMLDivElement>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to bottom on new messages
  // Auto-scroll to bottom on new messages
  useEffect(() => {
    // Only scroll if loading or if it's a user message (start of convo)
    // If it's the final message update (complete), we don't force scroll to bottom 
    // to allow user to read from top.
    if (isLoading || (messages.length > 0 && messages[messages.length-1].role === 'user')) {
        messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages.length, isLoading]); // Removed 'progress' to avoid jitter, used length to detect new msg

  const hasMessages = messages.length > 0;
  const lastAssistantMessage = messages.findLast((m) => m.role === "assistant");
  const hasCitations = (lastAssistantMessage?.citations?.length ?? 0) > 0;

  return (
    <div className={cn("flex h-full flex-col bg-bg", className)}>
      {/* Top bar: compact search while reading an answer. On the welcome
          screen the input lives inside the hero (the page's one action sits
          under the headline, not detached at the top), so here only the
          mobile menu and history remain. */}
      {!hideTopBar && (
      <div
        className={cn(
          "sticky top-0 z-10",
          hasMessages && "bg-bg/85 backdrop-blur-xl border-b border-line"
        )}
      >
        <div className="mx-auto max-w-3xl px-3 md:px-4 py-2 md:py-2.5">
          <div className="flex items-center gap-2">
            {mobileMenuButton}
            {hasMessages ? (
              <ChatInput
                onSend={onSendMessage}
                onCancel={onCancelRequest}
                isLoading={isLoading}
                placeholder={t("searchPlaceholder")}
                className="flex-1"
              />
            ) : (
              <span className="flex-1" aria-hidden="true" />
            )}
            {onOpenHistory && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onOpenHistory}
                className="h-9 w-9 shrink-0 text-fg-muted hover:text-fg"
                title={t("historyLabel")}
                aria-label={t("historyLabel")}
              >
                <History className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>
      </div>
      )}

      {/* Main Content Area */}
      <ScrollArea className="flex-1" ref={scrollRef}>
        {/* Sticky banner for baseline generation (stays at top while scrolling) */}
        {isLoading && <ProgressBanner progress={progress} />}

        {/* Full-page progress view: shown during pre-streaming steps (1-6) */}
        {isLoading && progress && !progress.isComplete && !progress.stepResults?.some(r => r.step === 7) ? (
          <div className="mx-auto w-full max-w-5xl">
            <ProgressFullPage
              progress={progress}
              query={messages.length > 0 ? messages[messages.length - 1]?.content || messages[messages.length - 2]?.content : undefined}
            />
          </div>
        ) : (
          <div className="mx-auto max-w-3xl px-4 pb-12 overflow-x-hidden">
            <TranslationBanner hasCitations={hasCitations} />
            {!hasMessages ? (
              <WelcomeScreen
                onSendMessage={onSendMessage}
                onCancelRequest={onCancelRequest}
                isLoading={isLoading}
              />
            ) : (
              <div className="space-y-0 min-h-[50vh]">
                {messages.map((message, idx) => {
                  // For user messages, pass chatId and progress slot
                  const nextMsg = messages[idx + 1];

                  // Query bloccata dal gate: niente headline con la query,
                  // resta solo il blocco "tema non trovato" dell'assistente
                  if (message.role === "user" && nextMsg?.gate) return null;
                  const chatId = message.role === "user" && nextMsg?.chatId ? nextMsg.chatId : undefined;
                  const answerTrace = message.role === "user" ? nextMsg?.trace : undefined;
                  const answerStats = message.role === "user" ? nextMsg?.topicStats : undefined;
                  const isLastUserMsg = message.role === "user" && (idx === messages.length - 1 || idx === messages.length - 2);

                  // Progress below the last user message: live stepper while
                  // streaming; once complete, the pipeline is methodology and
                  // collapses behind a quiet disclosure instead of dominating
                  // the finished research page.
                  let progressSlot: React.ReactNode = null;
                  if (isLastUserMsg) {
                    if (isLoading && progress && progress.stepResults?.some(r => r.step === 7)) {
                      progressSlot = (
                        <div className="pt-4">
                          <ProgressIndicator progress={progress} />
                        </div>
                      );
                    } else if (!isLoading && lastCompletedProgress) {
                      progressSlot = (
                        <div className="pt-3">
                          <CompletedMethodDisclosure progress={lastCompletedProgress} />
                        </div>
                      );
                    }
                  }

                  // Domanda che ha generato questa risposta: fallback del
                  // context di feedback se il chatId non è ancora arrivato
                  const prevMsg = messages[idx - 1];
                  const queryText =
                    message.role === "assistant" && prevMsg?.role === "user"
                      ? prevMsg.content
                      : undefined;

                  return (
                    <MessageBubble key={message.id} message={message} chatId={chatId} answerTrace={answerTrace} answerStats={answerStats} progressSlot={progressSlot} onSuggestionClick={onSendMessage} queryText={queryText} />
                  );
                })}

                <div ref={messagesEndRef} className="h-4" />
              </div>
            )}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

/** Completed pipeline behind a quiet disclosure: transparency on demand,
    without the execution log competing with the research result. */
function CompletedMethodDisclosure({ progress }: { progress: ProcessingProgress }) {
  const tPi = useTranslations("ProgressIndicator");
  const [open, setOpen] = useState(false);
  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button
          className="group label-mono inline-flex min-h-9 items-center gap-1.5 rounded-xs transition-colors hover:text-fg"
          aria-expanded={open}
        >
          <ChevronRight
            className={cn("h-3 w-3 transition-transform duration-200 motion-reduce:transition-none", open && "rotate-90")}
            aria-hidden="true"
          />
          {tPi("howBuilt")}
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-3">
        <CompletedProgressStepper progress={progress} />
      </CollapsibleContent>
    </Collapsible>
  );
}

interface WelcomeScreenProps {
  onSendMessage: (message: string) => void;
  onCancelRequest: () => void;
  isLoading: boolean;
}

interface RecentTopics {
  topics: { label: string; query: string }[];
  since: string | null;
  acts: { title: string; date: string; topic?: string | null }[];
}

function formatDate(iso: string | null, locale: string): string {
  if (!iso) return "";
  try {
    return new Intl.DateTimeFormat(locale, {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function WelcomeScreen({ onSendMessage, onCancelRequest, isLoading }: WelcomeScreenProps) {
  // Latest subjects actually on the floor (EuroVoc of recent acts), served in
  // the UI language and cached per locale so the section doesn't pop in on
  // every visit
  const locale = useLocale();
  // null = loading (server HTML and pre-fetch: skeleton chips), [] = resolved
  // empty (collapse to trending only), non-empty = real chips. The layout is
  // two columns in every state except resolved-empty, so a reload never
  // reflows: the server paints the same geometry the client settles on.
  const [recent, setRecent] = useState<RecentTopics | null>(null);
  // Cache seeded pre-paint; not in the useState initializer to avoid an SSR
  // hydration mismatch (same pattern as the Sidebar footer date).
  useLayoutEffect(() => {
    try {
      const cached = sessionStorage.getItem(`recentTopics3:${locale}`);
      if (cached) setRecent(JSON.parse(cached));
    } catch {}
  }, [locale]);
  useEffect(() => {
    const cacheKey = `recentTopics3:${locale}`;
    fetch(`/api/config/recent-topics?lang=${encodeURIComponent(locale)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (Array.isArray(data?.topics) && data.topics.length > 0) {
          sessionStorage.setItem(cacheKey, JSON.stringify(data));
          setRecent(data);
        } else {
          setRecent((prev) => prev ?? { topics: [], since: null, acts: [] });
        }
      })
      .catch(() => setRecent((prev) => prev ?? { topics: [], since: null, acts: [] }));
  }, [locale]);

  const t = useTranslations("WelcomeScreen");
  const hasRecent = recent === null || recent.topics.length > 0;
  const askTopic = (topic: string) => onSendMessage(t("topicQuery", { topic }));
  return (
    <div className="pt-6 sm:pt-14 pb-10 text-left">
      <div className="grid gap-10 lg:grid-cols-12 lg:gap-8 items-start">

        {/* Question + search: the page's one action sits where reading
            starts, top-left, directly under the promise it fulfills */}
        <div className={hasRecent ? "lg:col-span-7" : "lg:col-span-12"}>
          <h1 className="serif-display text-[1.9rem] sm:text-4xl md:text-[2.9rem] text-fg leading-[1.08] max-w-xl [text-wrap:balance]">
            {t.rich("title", {
              em: (chunks) => <span className="italic text-brand-fg">{chunks}</span>,
            })}
          </h1>
          <p className="mt-3 text-fg-secondary text-sm sm:text-base leading-relaxed max-w-md">
            {t.rich("subtitle", {
              bold: (chunks) => <span className="text-fg font-medium">{chunks}</span>,
            })}
          </p>

          <div className="mt-6 max-w-xl">
            <ChatInput
              onSend={onSendMessage}
              onCancel={onCancelRequest}
              isLoading={isLoading}
              placeholder={t("searchPlaceholder")}
            />
            <p className="mt-2 text-xs leading-tight text-fg-muted">
              {t("researchNote")}{" "}
              <a
                href="/privacy"
                className="underline underline-offset-2 decoration-fg-faint hover:text-fg transition-colors"
              >
                Privacy
              </a>
            </p>
          </div>

          <div className="mt-10">
            <p className="label-mono mb-3">
              {t("trendingTopics")}
            </p>
            <div className="flex flex-wrap gap-2 max-w-xl">
              {TOPICS.map((topic) => (
                <TopicPill key={topic} topic={topic} onClick={onSendMessage} />
              ))}
            </div>
          </div>
        </div>

        {/* Live rail: what the floor is actually discussing. The acts used
            to live inside a tooltip; they are real content and read as the
            newspaper's right-hand column instead. */}
        {hasRecent && (
          <aside className="lg:col-span-5 lg:border-l lg:border-line lg:pl-8">
            <p className="label-mono flex items-center gap-2 mb-4">
              {t("lastTopics")}
              {recent !== null && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <button
                      className="text-fg-faint hover:text-fg transition-colors rounded-full"
                      aria-label={t("lastTopicsHint", { date: recent.since ?? "" })}
                    >
                      <HelpCircle className="w-3.5 h-3.5" />
                    </button>
                  </TooltipTrigger>
                  <TooltipContent
                    side="bottom"
                    align="start"
                    className="max-w-sm p-3 text-left normal-case tracking-normal"
                  >
                    <p className="text-[11px] leading-snug">
                      {t("lastTopicsHint", { date: formatDate(recent.since, locale) })}
                    </p>
                  </TooltipContent>
                </Tooltip>
              )}
            </p>
            {recent === null ? (
              <ul className="space-y-5">
                {[0, 1, 2, 3].map((i) => (
                  <li key={i} className="space-y-1.5">
                    <span className="block h-4 w-40 rounded-xs bg-surface-sunken motion-safe:animate-skeleton" />
                    <span className="block h-3 w-full max-w-[16rem] rounded-xs bg-surface-sunken motion-safe:animate-skeleton" />
                  </li>
                ))}
              </ul>
            ) : (
              /* One topic-centric list: the acts are the source of the
                 topics, so listing them separately duplicated the same
                 subjects. Each entry pairs the topic with one act as its
                 provenance line. */
              <ul className="space-y-5">
                {recent.topics.map((topic) => {
                  const act = recent.acts.find(
                    (a) => a.topic?.toLowerCase() === topic.label.toLowerCase()
                  );
                  return (
                    <li key={topic.label}>
                      <button
                        onClick={() => askTopic(topic.query)}
                        className="group block w-full text-left cursor-pointer rounded-xs"
                      >
                        <span className="text-[15px] font-semibold leading-snug tracking-tight text-fg transition-colors group-hover:text-brand-fg">
                          {topic.label.charAt(0).toUpperCase() + topic.label.slice(1)}
                        </span>
                        {act && (
                          <span className="mt-1 block text-xs leading-snug text-fg-muted line-clamp-1">
                            <span className="tabular">{formatDate(act.date, locale)}</span>
                            {" · "}
                            {act.title}
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </aside>
        )}
      </div>
    </div>
  );
}

interface TopicPillProps {
  topic: string;
  onClick: (message: string) => void;
  /** KG-derived topics arrive already localized and have no i18n key */
  raw?: boolean;
  /** Expanded phrase sent as the query (chip shows the short label, the
   *  query carries the act's context: "digital signatures" alone would
   *  lose the electoral meaning) */
  queryText?: string;
  className?: string;
}

/** Sentence case, not Title Case: EuroVoc and curated labels are lowercase
 *  phrases with embedded proper nouns ("conflitto in Ucraina"), so only the
 *  first letter is raised. */
function TopicPill({ topic, onClick, raw = false, queryText, className }: TopicPillProps) {
  const t = useTranslations("WelcomeScreen");
  const label = raw ? topic : (t(`topics.${topic}` as never) as string);
  const displayName = label.charAt(0).toUpperCase() + label.slice(1);
  // The localized label (or the expanded phrase) goes into the query
  const query = t("topicQuery", { topic: queryText ?? label });
  return (
    <button
      className={cn(
        "inline-flex min-h-9 items-center rounded-full border border-line-strong bg-surface px-3.5 py-1.5 text-sm text-left text-fg-secondary transition-[border-color,color,transform] duration-[var(--duration-fast)] hover:border-fg hover:text-fg active:scale-[0.98] cursor-pointer",
        className
      )}
      onClick={() => onClick(query)}
    >
      {displayName}
    </button>
  );
}
