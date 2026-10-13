"use client";

import React, { useState, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import { useLocale, useTranslations } from 'next-intl';
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { Badge } from "@/components/ui/badge";
import { CitationCard } from "./CitationCard";
import { ScopePicker } from "./ScopePicker";
import { getGroupColor, getGroupShortLabel } from "@/components/search/ResultsList";
import { ExpertCard, ExpertRow } from "./ExpertCard";
import { TraceButton } from "./TraceCard";
import type { TraceData } from "@/types";
import { CompassCard } from "./CompassCard";
import { TopicStatsModal } from "./TopicStatsModal";
import { AnswerFeedback } from "@/components/feedback/FeedbackPulse";
import type { Message } from "@/types";
import { config } from "@/config";
import {
  Bot,
  ChevronDown,
  ChevronUp,
  Quote,
  Users,
  PieChart,
  Loader2,
  AlertCircle,
  Compass,
  Sparkles,
  Trophy,
  Info,
  Share2,
  Languages,
  ArrowRight,
  SearchX,
  History,
  Check as CheckIcon,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

interface SpeakerInfo {
  name: string;
  group: string;
  role?: string;
}

/**
 * Parse markdown content to extract bold names (**Name**) grouped by section (## heading),
 * and resolve their parliamentary group from experts/citations data.
 * For government members, resolves institutional role instead of party.
 */
function extractSpeakersBySection(
  content: string,
  experts?: import("@/types").Expert[],
  citations?: import("@/types").Citation[],
): Record<string, SpeakerInfo[]> {
  // Build a name → group lookup from experts and citations
  const nameToGroup: Record<string, string> = {};
  const nameToRole: Record<string, string> = {};
  if (experts) {
    for (const e of experts) {
      const fullName = `${e.first_name} ${e.last_name}`;
      nameToGroup[fullName] = e.group;
      if (e.institutional_role) nameToRole[fullName] = e.institutional_role;
    }
  }
  if (citations) {
    for (const c of citations) {
      const fullName = `${c.deputy_first_name} ${c.deputy_last_name}`;
      if (!nameToGroup[fullName]) {
        nameToGroup[fullName] = c.group;
      }
      if (c.institutional_role && !nameToRole[fullName]) {
        nameToRole[fullName] = c.institutional_role;
      }
    }
  }

  const result: Record<string, SpeakerInfo[]> = {};
  let currentSection = "";

  for (const line of content.split("\n")) {
    const headingMatch = line.match(/^#{1,3}\s+(.+)/);
    if (headingMatch) {
      currentSection = headingMatch[1].trim();
      if (!result[currentSection]) result[currentSection] = [];
      continue;
    }
    if (currentSection) {
      const boldNames = line.match(/\*\*([A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+(?:\s+[A-Z\u00C0-\u024F][a-z\u00C0-\u024F]+)+)\*\*/g);
      if (boldNames) {
        for (const match of boldNames) {
          const name = match.replace(/\*\*/g, "");
          if (!result[currentSection].some(s => s.name === name)) {
            result[currentSection].push({
              name,
              group: nameToGroup[name] || "",
              role: nameToRole[name],
            });
          }
        }
      }
    }
  }
  return result;
}

/** Tooltip showing speakers grouped by parliamentary group (or role for government members) */
function SpeakersTooltip({ speakers, iconSize, sectionTitle }: { speakers: SpeakerInfo[]; iconSize: string; sectionTitle?: string }) {
  const t = useTranslations('MessageBubble');
  const isGovernoSection = sectionTitle?.toLowerCase().includes("governo");

  if (isGovernoSection) {
    // Government section: show names with roles, no parliamentary groups
    return (
      <Tooltip delayDuration={0}>
        <TooltipTrigger asChild>
          <span className="inline-flex cursor-help">
            <Info className={cn(iconSize, "text-muted-foreground/60 hover:text-primary transition-colors")} />
          </span>
        </TooltipTrigger>
        <TooltipContent side="right" className="max-w-[350px]">
          <p className="font-semibold text-xs mb-2">{t('governoSection')}</p>
          <div className="space-y-1.5">
            {speakers.map((s) => (
              <div key={s.name}>
                <p className="text-xs font-medium text-foreground">{s.name}</p>
                {s.role && <p className="text-[11px] text-muted-foreground">{s.role}</p>}
              </div>
            ))}
          </div>
        </TooltipContent>
      </Tooltip>
    );
  }

  // Regular section: group speakers by parliamentary group
  const grouped: Record<string, string[]> = {};
  for (const s of speakers) {
    const label = s.group || t('altro');
    if (!grouped[label]) grouped[label] = [];
    grouped[label].push(s.name);
  }
  const groups = Object.entries(grouped);

  return (
    <Tooltip delayDuration={0}>
      <TooltipTrigger asChild>
        <span className="inline-flex cursor-help">
          <Info className={cn(iconSize, "text-muted-foreground/60 hover:text-primary transition-colors")} />
        </span>
      </TooltipTrigger>
      <TooltipContent side="right" className="max-w-[350px]">
        <p className="font-semibold text-xs mb-2">{t('deputiesSection')}</p>
        <div className="space-y-2">
          {groups.map(([group, names]) => (
            <div key={group} className="flex items-start gap-2">
              <span
                className="mt-[5px] h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: getGroupColor(group) }}
                aria-hidden="true"
              />
              <div className="min-w-0">
                <p className="text-xs font-medium text-foreground">{names.join(", ")}</p>
                <p className="text-[11px] text-muted-foreground">{getGroupShortLabel(group)}</p>
              </div>
            </div>
          ))}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}

/** Share button that copies the chat URL to clipboard */
function ShareButton({ chatId }: { chatId: string }) {
  const [copied, setCopied] = useState(false);
  const t = useTranslations('MessageBubble');

  const handleShare = async () => {
    const url = `${window.location.origin}/chat/${chatId}`;
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Fallback for older browsers
      const input = document.createElement("input");
      input.value = url;
      document.body.appendChild(input);
      input.select();
      document.execCommand("copy");
      document.body.removeChild(input);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  return (
    <button
      onClick={handleShare}
      aria-label={copied ? t('linkCopied') : t('share')}
      className={cn(
        "inline-flex items-center gap-2 px-3.5 py-1.5 rounded-md text-sm font-medium transition-all shrink-0",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        copied
          ? "text-green-600 bg-green-50 dark:bg-green-950/30"
          : "text-muted-foreground hover:text-primary hover:bg-muted/50"
      )}
    >
      {copied ? (
        <>
          <CheckIcon className="h-4 w-4" />
          <span className="hidden sm:inline">{t('linkCopied')}</span>
        </>
      ) : (
        <>
          <Share2 className="h-4 w-4" />
          <span className="hidden sm:inline">{t('share')}</span>
        </>
      )}
    </button>
  );
}

interface MessageBubbleProps {
  message: Message;
  className?: string;
  chatId?: string;
  /** Trace della risposta associata: mostrato come bottone accanto a Condividi */
  answerTrace?: TraceData;
  /** Statistiche del tema della risposta associata: la scala dell'evidenza
      (interventi, deputati, periodo) va nell'header della ricerca, non solo
      in fondo alla risposta */
  answerStats?: Message["topicStats"];
  progressSlot?: React.ReactNode;
  onSuggestionClick?: (query: string) => void;
  queryText?: string;
}

export function MessageBubble({ message, className, chatId, answerTrace, answerStats, progressSlot, onSuggestionClick, queryText }: MessageBubbleProps) {
  const isUser = message.role === "user";
  const isStreaming = message.status === "streaming";
  const isError = message.status === "error";
  const [highlightedChunkId, setHighlightedChunkId] = useState<string | null>(null);
  const [statsModalView, setStatsModalView] = useState<"interventions" | "speakers" | "sessions" | null>(null);
  const t = useTranslations('MessageBubble');
  const locale = useLocale();
  // Reloaded chats mount already complete: only live answers auto-open feedback
  const [generatedHere] = useState(() => message.status !== "complete");

  if (isUser) {
    const formatDay = (iso?: string | null) => {
      if (!iso) return "";
      try {
        return new Intl.DateTimeFormat(locale, {
          day: "2-digit", month: "2-digit", year: "numeric",
        }).format(new Date(iso));
      } catch {
        return String(iso);
      }
    };
    const hasScale = !!answerStats && (answerStats.intervention_count ?? 0) > 0;
    return (
      <div className={cn("py-6 border-b border-border/50", className)}>
        <div className="flex items-start justify-between gap-2 min-w-0">
          <h2 className="[font-family:var(--font-display)] text-2xl sm:text-[1.75rem] font-semibold tracking-tight leading-tight text-foreground mb-2.5 break-words min-w-0 [text-wrap:balance]">
            {message.content}
          </h2>
          <div className="flex items-center gap-1 shrink-0">
            <TraceButton trace={answerTrace} />
            {chatId && <ShareButton chatId={chatId} />}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <ScopePicker variant="meta" />
          {hasScale ? (
            <>
              <span className="tabular-nums">
                {t('evidenceScale', {
                  interventions: answerStats!.intervention_count,
                  deputies: answerStats!.speaker_count,
                })}
              </span>
              {answerStats!.first_date && answerStats!.last_date && (
                <>
                  <span className="text-muted-foreground/40" aria-hidden="true">·</span>
                  <span className="tabular-nums">
                    {formatDay(String(answerStats!.first_date))} → {formatDay(String(answerStats!.last_date))}
                  </span>
                </>
              )}
            </>
          ) : (
            <>
              <span className="tabular-nums">
                {message.timestamp.toLocaleTimeString("it-IT", {
                  hour: "2-digit",
                  minute: "2-digit",
                })}
              </span>
            </>
          )}
        </div>
        {progressSlot}
      </div>
    );
  }

  return (
    <div className={cn("py-6", className)}>
      <div className="flex flex-col gap-4">
        {/* Error State */}
        {isError && (
          <div className="rounded-lg border border-destructive/50 bg-destructive/10 p-4">
            <div className="flex items-center gap-2 text-destructive mb-2">
              <AlertCircle className="h-4 w-4" />
              <span className="font-medium">
                {t('errorTitle')}
              </span>
            </div>
            {message.content && (
              <p className="text-sm text-destructive/90">{message.content}</p>
            )}
          </div>
        )}

        {/* Relevance gate: tema non trovato nel corpus */}
        {message.gate && (
          <div className="py-2">
            <div className="flex items-center gap-2.5 mb-3">
              <SearchX className="h-5 w-5 text-muted-foreground shrink-0" strokeWidth={1.5} />
              <h2 className="[font-family:var(--font-display)] text-2xl font-medium tracking-tight text-foreground">
                {message.gate.title}
              </h2>
            </div>
            <p className="text-[15px] leading-7 text-muted-foreground max-w-prose">
              {message.gate.body}
            </p>
            {message.gate.suggestions.length > 0 && (
              <div className="mt-7 pt-5 border-t border-border">
                <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground mb-4">
                  {message.gate.suggestions_label}
                </p>
                <div className="flex flex-wrap gap-x-6 gap-y-3">
                  {message.gate.suggestions.map((topic) => (
                    <button
                      key={topic}
                      onClick={() => onSuggestionClick?.(topic)}
                      className="group inline-flex items-center gap-1.5 border-b border-border pb-1 text-sm text-left text-foreground/80 transition-colors duration-200 hover:border-primary hover:text-primary cursor-pointer"
                    >
                      <span>{topic}</span>
                      <ArrowRight className="w-3 h-3 shrink-0 text-muted-foreground/40 transition-all duration-200 group-hover:text-primary group-hover:translate-x-0.5" />
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* Replay dall'archivio: spiega perché la risposta è apparsa subito */}
        {message.cached && !isError && message.content && (
          <div className="flex items-start gap-2.5 rounded-lg border border-border bg-muted/40 px-3.5 py-2.5 text-[13px] leading-5 text-muted-foreground max-w-[70ch]">
            <History className="h-4 w-4 shrink-0 mt-0.5" strokeWidth={1.75} aria-hidden="true" />
            <span>
              {(() => {
                const iso = message.cached?.generatedAt;
                if (!iso) return t('cachedNoticeNoDate');
                try {
                  const when = new Intl.DateTimeFormat(locale, {
                    day: "numeric", month: "long",
                    hour: "2-digit", minute: "2-digit",
                  }).format(new Date(iso));
                  return t('cachedNotice', { date: when });
                } catch {
                  return t('cachedNoticeNoDate');
                }
              })()}
            </span>
          </div>
        )}

        {/* Content */}
        {message.content && (
          <div className="prose prose-sm max-w-[70ch] prose-neutral dark:prose-invert overflow-hidden break-words [overflow-wrap:anywhere]">
            <ReactMarkdown
              components={{
                p: ({ children }) => (
                  <p className="mb-4 text-[15px] leading-7 last:mb-0">{children}</p>
                ),
                ul: ({ children }) => (
                  <ul className="mb-4 ml-4 list-disc space-y-1">{children}</ul>
                ),
                ol: ({ children }) => (
                  <ol className="mb-4 ml-4 list-decimal space-y-1">
                    {children}
                  </ol>
                ),
                li: ({ children }) => <li className="">{children}</li>,
                strong: ({ children }) => {
                  const text = typeof children === "string" ? children : String(children);
                  // Build name → URL lookup from citations and experts
                  const nameToUrl: Record<string, string> = {};
                  if (message.experts) {
                    for (const e of message.experts) {
                      const fullName = `${e.first_name} ${e.last_name}`;
                      if (e.camera_profile_url) nameToUrl[fullName] = e.camera_profile_url;
                    }
                  }
                  if (message.citations) {
                    for (const c of message.citations) {
                      const fullName = `${c.deputy_first_name} ${c.deputy_last_name}`;
                      if (c.camera_profile_url && !nameToUrl[fullName]) nameToUrl[fullName] = c.camera_profile_url;
                    }
                  }
                  const url = nameToUrl[text];
                  if (url) {
                    return (
                      <a
                        href={url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="font-semibold text-foreground hover:text-primary hover:underline underline-offset-2 transition-colors"
                      >
                        {children}
                      </a>
                    );
                  }
                  return (
                    <strong className="font-semibold text-foreground">
                      {children}
                    </strong>
                  );
                },
                h1: ({ children }) => (
                  <h1 className="[font-family:var(--font-display)] text-2xl font-semibold tracking-tight mb-4 mt-8 first:mt-0">{children}</h1>
                ),
                h2: ({ children }) => {
                  const title = typeof children === "string" ? children : String(children);
                  const speakersBySection = extractSpeakersBySection(message.content, message.experts, message.citations);
                  const speakers = speakersBySection[title] || [];
                  return (
                    <h2 className="[font-family:var(--font-display)] text-[1.4rem] font-semibold tracking-tight mb-3 mt-8 first:mt-0 flex items-center gap-2">
                      <span>{children}</span>
                      {speakers.length > 0 && (
                        <SpeakersTooltip speakers={speakers} iconSize="h-4 w-4" sectionTitle={title} />
                      )}
                    </h2>
                  );
                },
                h3: ({ children }) => {
                  const title = typeof children === "string" ? children : String(children);
                  const speakersBySection = extractSpeakersBySection(message.content, message.experts, message.citations);
                  const speakers = speakersBySection[title] || [];
                  return (
                    <h3 className="[font-family:var(--font-display)] text-lg font-semibold tracking-tight mb-2 mt-6 flex items-center gap-2">
                      <span>{children}</span>
                      {speakers.length > 0 && (
                        <SpeakersTooltip speakers={speakers} iconSize="h-3.5 w-3.5" sectionTitle={title} />
                      )}
                    </h3>
                  );
                },
                code: ({ children }) => (
                  <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm">
                    {children}
                  </code>
                ),
                blockquote: ({ children }) => (
                  <blockquote className="[font-family:var(--font-display)] border-l-2 border-primary/30 pl-4 py-1 italic text-muted-foreground my-4 overflow-hidden break-words">
                    {children}
                  </blockquote>
                ),
                a: ({ href, children }) => {
                  // Suggested-topic chip (relevance gate): clicking launches
                  // the suggested query as a new message
                  if (href?.startsWith("suggest:")) {
                    const topic = decodeURIComponent(href.slice("suggest:".length));
                    return (
                      <button
                        onClick={() => onSuggestionClick?.(topic)}
                        className="group inline-flex items-center gap-1.5 mr-5 mb-2 border-b border-border pb-1 text-sm text-left text-foreground/80 transition-colors duration-200 hover:border-primary hover:text-primary cursor-pointer"
                      >
                        <span>{children}</span>
                        <ArrowRight className="w-3 h-3 shrink-0 text-muted-foreground/40 transition-all duration-200 group-hover:text-primary group-hover:translate-x-0.5" />
                      </button>
                    );
                  }

                  // Check if it's a stats link (#stats-interventions, #stats-speakers, #stats-sessions)
                  if (href?.startsWith("#stats-")) {
                    const view = href.replace("#stats-", "") as "interventions" | "speakers" | "sessions";
                    return (
                      <span
                        role="button"
                        tabIndex={0}
                        className="inline cursor-pointer rounded-[3px] px-0.5 text-primary font-medium underline decoration-primary/35 decoration-[1.5px] underline-offset-[3px] hover:bg-primary/10 hover:decoration-primary/70 transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => setStatsModalView(view)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setStatsModalView(view);
                          }
                        }}
                        title={t('clickForDetail')}
                      >
                        {children}
                      </span>
                    );
                  }

                  // Check if it's a citation link (evidence_id patterns)
                  const isCitationLink = href && (
                    href.includes("chunk_") ||
                    href.startsWith("cit_") ||
                    href.startsWith("leg19_") ||
                    href.startsWith("leg18_") ||
                    href.startsWith("sen_leg")
                  );

                  if (isCitationLink) {
                    // Find original Italian text for tooltip (when viewing in English)
                    const matchedCitation = message.citations?.find(
                      (c) => c.chunk_id === href
                    );
                    const originalQuote = matchedCitation?.is_translated
                      ? matchedCitation.quote_text || matchedCitation.text
                      : null;

                    // Evidence mark, not a hyperlink: primary-source words get
                    // the display serif in italic (same register as
                    // blockquotes) over a faint tint, so synthesis (sans) and
                    // evidence (serif) read as two distinct semantic layers.
                    const citationSpan = (
                      <span
                        role="button"
                        tabIndex={0}
                        className={cn(
                          "inline cursor-pointer rounded-[3px] px-1 -mx-px",
                          "[font-family:var(--font-display)] italic",
                          "bg-primary/[0.06] text-foreground/90 border-b border-primary/30",
                          "hover:bg-primary/10 hover:border-primary/60",
                          "transition-colors duration-150",
                          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                          highlightedChunkId === href && "bg-yellow-400/30 border-yellow-500 text-yellow-800 dark:text-yellow-300"
                        )}
                        onClick={() => {
                          setHighlightedChunkId(href);
                        }}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" || e.key === " ") {
                            e.preventDefault();
                            setHighlightedChunkId(href);
                          }
                        }}
                        title={originalQuote ? undefined : t('clickHighlight')}
                      >
                        {children}
                        {originalQuote && (
                          <Languages className="inline h-3 w-3 ml-0.5 align-[-1px] text-muted-foreground/60" aria-hidden="true" />
                        )}
                      </span>
                    );

                    if (!originalQuote) return citationSpan;

                    return (
                      <Tooltip delayDuration={300}>
                        <TooltipTrigger asChild>{citationSpan}</TooltipTrigger>
                        <TooltipContent side="bottom" className="max-w-[400px] p-3">
                          <p className="text-[10px] font-semibold text-muted-foreground/70 mb-1 uppercase tracking-wider">
                            {t('originalLabel')}
                          </p>
                          <p className="text-xs leading-relaxed italic">
                            &ldquo;{originalQuote}&rdquo;
                          </p>
                        </TooltipContent>
                      </Tooltip>
                    );
                  }

                  return (
                    <a
                      href={href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline underline-offset-2"
                    >
                      {children}
                    </a>
                  );
                }
              }}
            >
              {message.topicStats
                ? injectStatsLinks(message.content)
                : message.content}
            </ReactMarkdown>
          </div>
        )}

        {isStreaming && message.content && (
          <div className="flex items-center gap-2 mt-2">
            <span className="inline-block w-2 h-4 bg-primary animate-pulse" />
          </div>
        )}

        {/* Pollici per risposta (issue #21): a fine prosa, PRIMA delle
            sezioni di approfondimento — a fondo pagina non li vede nessuno */}
        {!isUser && message.status === "complete" && !message.gate && message.content && (
          <AnswerFeedback
            fresh={generatedHere}
            context={
              message.chatId || chatId ||
              (queryText ? `q:${queryText.slice(0, 280)}` : undefined)
            }
          />
        )}
        {/* Disclaimer contenuti generati: le quote sono verificate, la
            selezione e la sintesi no — va detto dove l'utente legge */}
        {!isUser && message.status === "complete" && !message.gate && message.content && (
          <p className="text-[11px] leading-relaxed text-muted-foreground/70">
            {t('aiDisclaimer')}{" "}
            <a
              href="/method"
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-primary transition-colors whitespace-nowrap"
            >
              {t('aiDisclaimerLink')}
            </a>
          </p>
        )}
        {/* Additional metadata for assistant messages — show progressively once text is visible */}
        {!isUser && message.content && (message.status === "complete" || message.status === "streaming") && (
          <AssistantMetadata
            message={message}
            highlightedChunkId={highlightedChunkId}
          />
        )}
        {/* Topic Stats Modal */}
        {message.topicStats && statsModalView && (
          <TopicStatsModal
            stats={message.topicStats}
            isOpen={!!statsModalView}
            onClose={() => setStatsModalView(null)}
            defaultView={statsModalView}
          />
        )}
      </div>
    </div>
  );
}

/**
 * Preprocesses markdown content to inject #stats- links for clickable stats.
 * Wraps patterns like "81 interventi", "52 deputati", "N. 8, 15, 26, 69, 73"
 * with markdown links [text](#stats-view) that ReactMarkdown renders as <a>.
 */
function injectStatsLinks(content: string): string {
  // Only process the introduction section to avoid false positives
  // in party sections with citation links.
  // The intro text lives UNDER the first ## heading (e.g. "## Introduzione"),
  // so we extract from the first heading up to the second heading.
  const firstHeading = content.search(/^##\s/m);
  let secondHeading = -1;
  if (firstHeading !== -1) {
    const afterFirst = content.slice(firstHeading + 1).search(/^##\s/m);
    secondHeading = afterFirst !== -1 ? firstHeading + 1 + afterFirst : -1;
  }

  let before: string;
  let intro: string;
  let rest: string;

  if (firstHeading === -1) {
    // No headings at all — treat everything as intro
    before = "";
    intro = content;
    rest = "";
  } else if (secondHeading === -1) {
    // Only one heading — everything after it is intro
    before = content.slice(0, firstHeading);
    intro = content.slice(firstHeading);
    rest = "";
  } else {
    // Multiple headings — intro is from first heading to second heading
    before = content.slice(0, firstHeading);
    intro = content.slice(firstHeading, secondHeading);
    rest = content.slice(secondHeading);
  }

  let result = intro;

  // Pattern for "N interventi" / "N interventions" (also handles "analizzati" suffix)
  // Handles optional bold markers: **N interventi**, **N** interventi, or plain
  result = result.replace(
    /\*{0,2}(\d+)\*{0,2}\s+\*{0,2}(intervent[oi](?:\s+analizzat[oi])?|interventions?(?:\s+analy[sz]ed)?)\*{0,2}/gi,
    "[$1 $2](#stats-interventions)"
  );

  // Pattern for "N deputati" / "N deputies" or "N parlamentari" / "N parliamentarians"
  // Handles optional bold markers: **N deputati**, **N** deputati, or plain
  result = result.replace(
    /\*{0,2}(\d+)\*{0,2}\s+\*{0,2}(deputat[oi]|parlamentar[ie]|deput(?:y|ies)|parliamentarians?)\*{0,2}/gi,
    "[$1 $2](#stats-speakers)"
  );

  // Pattern for session numbers: "N. 8, 15, 26, 69, 73 e altre 30" or "N. 8, 15, 26, 69, 73 e 80"
  // Handles optional bold markers around the whole expression
  result = result.replace(
    /\*{0,2}(N\.\s*\d+(?:,\s*\d+)*(?:,?\s+e\s+(?:altr[eiao]\s+)?\d+)?)\*{0,2}/g,
    "[$1](#stats-sessions)"
  );

  // Strip any remaining bold markers from the intro section.
  // The LLM often wraps entire phrases in bold (e.g. "**analizzando un totale di 95 interventi**"),
  // and the regexes above only strip ** immediately around the matched patterns, leaving outer
  // markers intact. Speaker names don't appear in the intro so this is safe.
  result = result.replace(/\*\*/g, "");

  return before + result + rest;
}

interface AssistantMetadataProps {
  message: Message;
  highlightedChunkId?: string | null;
}

function AssistantMetadata({ message, highlightedChunkId }: AssistantMetadataProps) {
  const t = useTranslations('MessageBubble');
  const hasCitations = message.citations && message.citations.length > 0;
  const hasExperts = message.experts && message.experts.length > 0;
  const hasBalance = message.balanceMetrics;
  const hasHQMetaData = !!message.hqMetadata;
  const hasCompass = !!message.compass;

  // During streaming, only show if we have at least some data
  const hasAnyData = hasCitations || hasExperts || hasBalance || hasHQMetaData || hasCompass;
  if (!hasAnyData) return null;

  return (
    <div className={cn(
      "flex flex-col gap-2 w-full min-w-0",
      // Add visual separator only when content is visible above
      message.content && "mt-6 border-t border-border pt-6"
    )}>
      {/* Experts — shown first to explain the curation logic behind the response */}
      {hasExperts && (
        <CollapsibleSection
          icon={Users}
          title={t('expertsTitle')}
          count={message.experts!.length}
          defaultOpen={false}
          infoTooltip={t('expertsTooltip')}
        >
            <div className="pt-1 px-1 pb-2">
              <p className="text-[11px] text-muted-foreground/70 leading-relaxed mb-4">
                {t.rich('expertsSectionDesc', {
                  method: (chunks) => (
                    <a
                      href="/method"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline underline-offset-2 hover:text-primary transition-colors"
                    >
                      {chunks}
                    </a>
                  ),
                  ranking: (chunks) => (
                    <a
                      href="/ranking"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="underline underline-offset-2 hover:text-primary transition-colors"
                    >
                      {chunks}
                    </a>
                  ),
                })}
              </p>
              {message.experts && (
               <div className="space-y-6">
                 {(() => {
                    const groupedExperts = message.experts!.reduce((acc, expert) => {
                         if (!acc[expert.group]) acc[expert.group] = [];
                         acc[expert.group].push(expert);
                         return acc;
                    }, {} as Record<string, typeof message.experts>);

                    return Object.entries(groupedExperts).map(([group, experts]) => (
                        <div key={group}>
                             <div className="flex items-center gap-3 mb-3 px-1">
                                <span className="text-[10px] font-bold text-muted-foreground/60 uppercase tracking-widest whitespace-nowrap">{group}</span>
                                <div className="h-px flex-1 bg-border/40"></div>
                             </div>
                             <div className="grid gap-2 w-full">
                                 {experts!.map(expert => (
                                     <ExpertRow key={expert.id} expert={expert} />
                                 ))}
                             </div>
                        </div>
                    ));
                 })()}
               </div>
              )}
            </div>
        </CollapsibleSection>
      )}

      {/* High Quality Variants Analysis */}
      {hasHQMetaData && (
        <CollapsibleSection
          icon={Sparkles}
          title={t('hqTitle')}
          count={message.hqMetadata!.variants.length}
          defaultOpen={false}
          infoTooltip={t('hqTooltip')}
        >
          <div className="pt-2 px-1">
            <div className="bg-primary/5 border border-primary/10 rounded-lg p-4 mb-4">
              <div className="flex items-center gap-2 mb-2">
                <Trophy className="h-4 w-4 text-primary" />
                <span className="text-sm font-semibold">{t('hqJudgeReason')}</span>
              </div>
              <p className="text-xs text-muted-foreground italic leading-relaxed">
                "{message.hqMetadata!.judge_reason}"
              </p>
            </div>

            <Tabs defaultValue="winner" className="w-full">
              <TabsList className="grid w-full grid-cols-3 h-9">
                <TabsTrigger value="winner" className="text-xs">🏆 {t('winnerTab')}</TabsTrigger>
                <TabsTrigger value="var0" className="text-xs">{t('variantA')}</TabsTrigger>
                <TabsTrigger value="var1" className="text-xs">{t('variantB')}</TabsTrigger>
              </TabsList>
              
              {(() => {
                const winner = message.hqMetadata!.variants.find(v => v.is_best);
                const others = message.hqMetadata!.variants.filter(v => !v.is_best);
                
                return (
                  <>
                    <TabsContent value="winner" className="mt-4">
                      {winner && <VariantCard variant={winner} />}
                    </TabsContent>
                    <TabsContent value="var0" className="mt-4">
                      {others[0] && <VariantCard variant={others[0]} />}
                    </TabsContent>
                    <TabsContent value="var1" className="mt-4">
                      {others[1] && <VariantCard variant={others[1]} />}
                    </TabsContent>
                  </>
                );
              })()}
            </Tabs>
          </div>
        </CollapsibleSection>
      )}

      {/* Citations */}
      {hasCitations && (
        <CollapsibleSection
          icon={Quote}
          title={t('citationsTitle')}
          count={message.citations!.length}
          defaultOpen={false}
          forceOpen={!!highlightedChunkId}
          infoTooltip={t('citationsTooltip')}
        >
          <div className="grid gap-2 w-full min-w-0">
            {Array.from(new Map(message.citations!.map(c => [c.chunk_id, c])).values()).map((citation, index) => (
              <CitationCard
                key={citation.chunk_id}
                citation={citation}
                index={index}
                isHighlighted={highlightedChunkId === citation.chunk_id}
              />
            ))}
          </div>
        </CollapsibleSection>
      )}

      {/* Balance metrics */}
      {hasBalance && <BalanceSection metrics={message.balanceMetrics!} />}

      {/* Compass */}
      {message.compass && (
        <CollapsibleSection
            icon={Compass}
            title={t('compassTitle')}
            count={message.compass?.groups?.length ?? 0}
            defaultOpen={false}
            infoTooltip={t('compassTooltip')}
        >
             <CompassCard data={message.compass} />
        </CollapsibleSection>
      )}

    </div>
  );
}

interface CollapsibleSectionProps {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  count: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
  forceOpen?: boolean;
  infoTooltip?: string;
}

function CollapsibleSection({
  icon: Icon,
  title,
  count,
  defaultOpen = false,
  children,
  forceOpen = false,
  infoTooltip,
}: CollapsibleSectionProps) {
  const [isOpen, setIsOpen] = useState(defaultOpen);

  useEffect(() => {
    if (forceOpen) {
      setIsOpen(true);
    }
  }, [forceOpen]);

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between h-auto py-2 px-3 hover:bg-muted/50"
        >
          <div className="flex items-center gap-2">
            <Icon className="h-4 w-4 text-primary" />
            <span className="[font-family:var(--font-display)] text-base font-semibold tracking-tight">{title}</span>
            {infoTooltip && (
              <Tooltip delayDuration={0}>
                <TooltipTrigger asChild onClick={(e) => e.stopPropagation()}>
                  <span className="inline-flex cursor-help">
                    <Info className="h-3.5 w-3.5 text-muted-foreground/50 hover:text-primary transition-colors" />
                  </span>
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[300px]">
                  <p className="text-[11px]">{infoTooltip}</p>
                </TooltipContent>
              </Tooltip>
            )}
            <Badge variant="secondary" className="text-xs">
              {count}
            </Badge>
          </div>
          {isOpen ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 pb-2 px-2 w-full">{children}</CollapsibleContent>
    </Collapsible>
  );
}

interface BalanceSectionProps {
  metrics: NonNullable<Message["balanceMetrics"]>;
}

function BalanceSection({ metrics }: BalanceSectionProps) {
  const t = useTranslations('MessageBubble');
  const [isOpen, setIsOpen] = useState(false);

  // biasScore: -1 = tutto opposizione, 0 = bilanciato, 1 = tutto maggioranza
  const balancePercentage = Math.round((1 - Math.abs(metrics.biasScore)) * 100);
  const isBalanced = balancePercentage >= 60;

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <CollapsibleTrigger asChild>
        <Button
          variant="ghost"
          className="w-full justify-between h-auto py-2 px-3 hover:bg-muted/50"
        >
          <div className="flex items-center gap-2">
            <PieChart className="h-4 w-4 text-primary" />
            <span className="[font-family:var(--font-display)] text-base font-semibold tracking-tight">{t('balanceTitle')}</span>
            <Tooltip delayDuration={0}>
              <TooltipTrigger asChild onClick={(e) => e.stopPropagation()}>
                <span className="inline-flex cursor-help">
                  <Info className="h-3.5 w-3.5 text-muted-foreground/50 hover:text-primary transition-colors" />
                </span>
              </TooltipTrigger>
              <TooltipContent side="right" className="max-w-[300px]">
                <p className="text-[11px]">{t('balanceTooltip')}</p>
              </TooltipContent>
            </Tooltip>
            <Badge
              variant={isBalanced ? "default" : "secondary"}
              className={cn(
                "text-xs",
                isBalanced && "bg-green-500/15 text-green-700 dark:text-green-400",
              )}
            >
              {balancePercentage}%
            </Badge>
          </div>
          {isOpen ? (
            <ChevronUp className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          )}
        </Button>
      </CollapsibleTrigger>
      <CollapsibleContent className="pt-2 px-3">
        <div className="rounded-lg border border-border bg-card/50 p-3 space-y-3">
          <div className="space-y-2">
            {/* Maggioranza */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-blue-400">{t('maggioranza')}</span>
                <span className="text-muted-foreground">
                  {Math.round(metrics.maggioranzaPercentage)}%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-muted">
                <div
                  className="h-full rounded-full transition-all bg-blue-500"
                  style={{ width: `${metrics.maggioranzaPercentage}%` }}
                />
              </div>
            </div>

            {/* Opposizione */}
            <div className="space-y-1">
              <div className="flex items-center justify-between text-xs">
                <span className="text-red-400">{t('opposizione')}</span>
                <span className="text-muted-foreground">
                  {Math.round(metrics.opposizionePercentage)}%
                </span>
              </div>
              <div className="h-1.5 w-full rounded-full bg-muted">
                <div
                  className="h-full rounded-full transition-all bg-red-500"
                  style={{ width: `${metrics.opposizionePercentage}%` }}
                />
              </div>
            </div>
          </div>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

function VariantCard({ variant }: { variant: any }) {
  return (
    <div className="relative group">
      <div className="absolute top-2 right-2 flex items-center gap-2 z-10">
        <Badge variant="outline" className="text-[10px] bg-background/80 backdrop-blur-sm border-primary/20">
          Score: {variant.score}/10
        </Badge>
        <Badge variant="outline" className="text-[10px] bg-background/80 backdrop-blur-sm border-border/50">
          Temp: {variant.temperature}
        </Badge>
      </div>
      <div className="text-[11px] text-muted-foreground bg-muted/20 border border-border/40 rounded-lg p-4 pt-10 overflow-y-auto max-h-[350px] whitespace-pre-wrap leading-relaxed custom-scrollbar">
        {variant.text}
      </div>
    </div>
  );
}
