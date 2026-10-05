"use client";

import { useState, useId } from "react";
import React from "react";
import { useLocale, useTranslations } from "next-intl";
import { ChevronRight, Vote } from "lucide-react";

import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { cn, cleanDebateTitle } from "@/lib/utils";
import { DebateSheet } from "./DebateSheet";
import { SessionVotesSheet } from "./SessionVotesSheet";
import type { TimelineSession } from "@/types/timeline";

interface SessionCardProps {
  session: TimelineSession;
  searchTerm?: string;
}

function highlightText(text: string, term: string): React.ReactNode {
  if (!term) return text;
  const escaped = term.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const parts = text.split(new RegExp(`(${escaped})`, "gi"));
  return parts.map((part, i) =>
    part.toLowerCase() === term.toLowerCase() ? (
      <mark key={i} className="rounded-xs bg-highlight px-0.5 text-fg">
        {part}
      </mark>
    ) : (
      part
    ),
  );
}

/* Recaps open with a fixed formula ("Nella sessione parlamentare del ...
   sono stati trattati i seguenti argomenti: a; b; c. Rest."): the topics
   become a list and whatever follows the list stays as prose. */
const RECAP_LEAD = /^.*?(?:seguenti argomenti|following (?:topics|items))\s*:\s*/i;

function parseRecap(recap: string): { topics: string[]; rest: string } {
  const lead = recap.match(RECAP_LEAD);
  if (!lead) return { topics: [], rest: recap };
  const body = recap.slice(lead[0].length);
  const stop = body.search(/\.\s+(?=[A-ZÀ-Ý])/);
  const list = stop === -1 ? body.replace(/\.$/, "") : body.slice(0, stop);
  const rest = stop === -1 ? "" : body.slice(stop + 1).trim();
  const topics = list
    .split(/;\s*/)
    .map((x) => x.trim())
    .filter(Boolean)
    .map((x) => x.charAt(0).toUpperCase() + x.slice(1));
  return { topics, rest };
}

const TOPICS_SHOWN = 4;

export function SessionCard({ session, searchTerm }: SessionCardProps) {
  const t = useTranslations("Timeline");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [proceduralOpen, setProceduralOpen] = useState(false);
  const [votesSheetOpen, setVotesSheetOpen] = useState(false);
  const [selectedDebate, setSelectedDebate] = useState<{
    id: string;
    title: string;
  } | null>(null);
  const contentId = useId();
  const proceduralId = useId();

  const when = new Date(session.date);
  const day = when.getDate();
  const monthYear = when.toLocaleDateString(locale, { month: "short", year: "numeric" });
  const recap = parseRecap(session.recap ?? "");
  const formattedDate = when.toLocaleDateString(locale, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  // Substantive debates open the detail panel; procedural items (no
  // recorded speeches) are folded behind one line so they stop competing
  // with the actual debates for attention.
  const substantive = session.debates.filter((d) => d.speech_count > 0);
  const procedural = session.debates.filter(
    (d) => d.speech_count === 0 && d.title.trim(),
  );

  const stats = [
    { count: session.debate_count, label: t("debateCount", { count: session.debate_count }) },
    { count: session.vote_count, label: t("voteCount", { count: session.vote_count }) },
    { count: session.speech_count, label: t("speechCount", { count: session.speech_count }) },
  ].filter((s) => s.count > 0);

  return (
    <div>
      <Collapsible open={open} onOpenChange={setOpen}>
        <div className="grid grid-cols-[3.25rem_minmax(0,1fr)] gap-x-4 py-5 sm:grid-cols-[4rem_minmax(0,1fr)] sm:gap-x-6">
          <div className="flex flex-col items-start pt-0.5" aria-hidden>
            <span className="font-mono text-2xl font-medium leading-none tabular-nums text-fg sm:text-[1.75rem]">{day}</span>
            <span className="mt-1 label-mono text-[10px] text-fg-muted">{monthYear}</span>
          </div>

          <div className="min-w-0">
            <CollapsibleTrigger
              className="group flex w-full items-baseline gap-3 text-left"
              aria-expanded={open}
              aria-controls={contentId}
            >
              <h3 className="text-base font-semibold leading-snug tracking-[var(--tracking-heading)] text-fg first-letter:uppercase group-hover:text-brand-fg">
                {formattedDate}
              </h3>
              <span className="font-mono text-xs text-fg-muted">{t("sessionNumber", { n: session.number })}</span>
              {session.chamber === "senato" && (
                <span className="label-mono text-[10px] text-fg-muted">{session.chamber}</span>
              )}
              <ChevronRight
                className={cn(
                  "ml-auto h-4 w-4 shrink-0 self-center text-fg-faint transition-transform duration-200",
                  open && "rotate-90",
                )}
                aria-hidden
              />
            </CollapsibleTrigger>

            {session.recap ? (
              recap.topics.length > 0 ? (
                <div className="mt-3">
                  <ul className="flex flex-col gap-1.5 text-sm leading-snug text-fg-secondary">
                    {(open ? recap.topics : recap.topics.slice(0, TOPICS_SHOWN)).map((topic, i) => (
                      <li key={i} className="flex gap-2.5">
                        <span className="mt-[0.55em] h-1 w-1 shrink-0 rounded-full bg-fg-faint" aria-hidden />
                        <span>{searchTerm ? highlightText(topic, searchTerm) : topic}</span>
                      </li>
                    ))}
                  </ul>
                  {!open && recap.topics.length > TOPICS_SHOWN && (
                    <button
                      type="button"
                      onClick={() => setOpen(true)}
                      className="mt-1.5 pl-3.5 text-xs text-brand-fg hover:underline"
                    >
                      {t("moreTopics", { count: recap.topics.length - TOPICS_SHOWN })}
                    </button>
                  )}
                  {recap.rest && (
                    <p className={cn("mt-2.5 text-sm leading-relaxed text-fg-muted", !open && "line-clamp-2")}>
                      {searchTerm ? highlightText(recap.rest, searchTerm) : recap.rest}
                    </p>
                  )}
                </div>
              ) : (
                <p className={cn("mt-3 text-sm leading-relaxed text-fg-secondary", !open && "line-clamp-3")}>
                  {searchTerm ? highlightText(session.recap, searchTerm) : session.recap}
                </p>
              )
            ) : (
              <p className="mt-3 text-xs italic text-fg-muted">{t("summaryNotYetGenerated")}</p>
            )}

            {stats.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-1.5">
                {stats.map((s, i) => (
                  <span
                    key={i}
                    className="inline-flex items-center rounded-full bg-surface-muted px-2.5 py-1 text-xs tabular-nums text-fg-secondary"
                  >
                    {s.label}
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Expanded debate list */}
        <CollapsibleContent id={contentId} role="region" aria-label={`${formattedDate} debates`}>
          <div className="mb-5 ml-[4.25rem] border-t border-line pt-1 sm:ml-[5.5rem]">
            {/* Votes are recorded per sitting, so their entry point lives
                here rather than repeated inside every debate panel. */}
            {session.vote_count > 0 && (
              <button
                type="button"
                onClick={() => setVotesSheetOpen(true)}
                className="group flex w-full items-center gap-2.5 py-2.5 px-3 -mx-3 rounded-md text-left hover:bg-surface-muted transition-colors"
              >
                <Vote className="h-3.5 w-3.5 shrink-0 text-fg-muted" aria-hidden />
                <span className="text-sm flex-1 leading-snug font-medium text-fg">
                  {t("votesLabel", { count: session.vote_count })}
                </span>
                <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform group-hover:translate-x-0.5" />
              </button>
            )}

            <div className="space-y-0.5">
              {substantive.map((debate) => {
                const title = cleanDebateTitle(debate.title);
                return (
                  <button
                    key={debate.id}
                    type="button"
                    onClick={() => setSelectedDebate({ id: debate.id, title })}
                    className="group flex w-full items-center gap-2.5 py-2.5 px-3 -mx-3 rounded-md text-left hover:bg-surface-muted transition-colors"
                  >
                    <span className="text-sm flex-1 leading-snug text-fg">
                      {searchTerm ? highlightText(title, searchTerm) : title}
                    </span>
                    <span className="tabular text-xs text-fg-muted shrink-0">
                      {t("speechCount", { count: debate.speech_count })}
                    </span>
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-fg-faint transition-transform group-hover:translate-x-0.5" />
                  </button>
                );
              })}
            </div>

            {procedural.length > 0 && (
              <Collapsible open={proceduralOpen} onOpenChange={setProceduralOpen}>
                <CollapsibleTrigger
                  className="mt-1 py-1.5 px-3 -mx-3 text-xs text-fg-muted hover:text-fg transition-colors"
                  aria-expanded={proceduralOpen}
                  aria-controls={proceduralId}
                >
                  {proceduralOpen
                    ? t("proceduralItemsHide")
                    : t("proceduralItems", { count: procedural.length })}
                </CollapsibleTrigger>
                <CollapsibleContent id={proceduralId} role="region">
                  <div className="space-y-1 pb-1">
                    {procedural.map((d) => (
                      <p
                        key={d.id}
                        className="text-xs leading-snug text-fg-muted"
                      >
                        {searchTerm
                          ? highlightText(cleanDebateTitle(d.title), searchTerm)
                          : cleanDebateTitle(d.title)}
                      </p>
                    ))}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}
          </div>
        </CollapsibleContent>
      </Collapsible>

      <DebateSheet
        debate={selectedDebate}
        sessionNumber={session.number}
        sessionDate={session.date}
        onOpenChange={(isOpen) => {
          if (!isOpen) setSelectedDebate(null);
        }}
      />

      <SessionVotesSheet
        open={votesSheetOpen}
        sessionId={session.id}
        sessionNumber={session.number}
        sessionDate={session.date}
        voteCount={session.vote_count}
        onOpenChange={setVotesSheetOpen}
      />
    </div>
  );
}
