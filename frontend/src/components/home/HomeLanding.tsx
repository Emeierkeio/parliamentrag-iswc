"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { ChatInput } from "@/components/chat/ChatInput";
import { fetchReadyTopics, type ReadyTopic } from "@/components/shell/CommandPalette";
import { formatDay } from "@/components/dossier/format";
import { ScopeSelector } from "@/components/shell/ScopeSelector";

interface ReadyDossier extends ReadyTopic {
  speakers?: number | null;
  timestamp?: string | null;
}

interface RecentTopics {
  topics: { label: string; query: string }[];
  since: string | null;
  acts: { title: string; date: string; topic?: string | null }[];
}

function capitalise(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/*
 * The app's front door: one field that takes a topic or a question, the
 * index of ready dossiers, and what the floor discussed lately. Opening a
 * topic goes to its dossier when one exists; anything else is composed live.
 */
export function HomeLanding({ onAsk, onAskTopic }: { onAsk: (text: string) => void; onAskTopic: (topic: string) => void }) {
  const t = useTranslations("Home");
  const tw = useTranslations("WelcomeScreen");
  const locale = useLocale();
  const [ready, setReady] = useState<ReadyDossier[] | null>(null);
  const [recent, setRecent] = useState<RecentTopics | null>(null);

  useEffect(() => {
    fetchReadyTopics().then((list) => setReady(list.filter((d) => d.id)));
  }, []);

  useEffect(() => {
    fetch(`/api/config/recent-topics?lang=${encodeURIComponent(locale)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (Array.isArray(data?.topics) && data.topics.length > 0) {
          setRecent(data);
        } else {
          setRecent((prev) => prev ?? { topics: [], since: null, acts: [] });
        }
      })
      .catch(() => setRecent((prev) => prev ?? { topics: [], since: null, acts: [] }));
  }, [locale]);

  return (
    <div className="container-page flex flex-col gap-16 pt-10 pb-20 md:pt-16">
      <section className="grid items-end gap-10 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <ScopeSelector />
          <h1 className="serif-display mt-4 max-w-2xl text-[2.25rem] leading-[1.06] text-fg [text-wrap:balance] sm:text-5xl md:text-display-l">
            {tw.rich("title", { em: (chunks) => <span className="italic text-brand-fg">{chunks}</span> })}
          </h1>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-fg-secondary">
            {tw.rich("subtitle", { bold: (chunks) => <span className="font-medium text-fg">{chunks}</span> })}
          </p>
          <div className="mt-8 max-w-2xl">
            <ChatInput onSend={onAsk} placeholder={tw("searchPlaceholder")} acceptHandoff />
            <p className="mt-2.5 text-xs leading-snug text-fg-muted">
              {t("askHint")} {tw("researchNote")}{" "}
              <a href="/privacy" className="underline decoration-fg-faint underline-offset-2 hover:text-fg">
                Privacy
              </a>
            </p>
          </div>
        </div>
      </section>

      <section aria-labelledby="ready-h" className="flex flex-col gap-5">
        <div className="flex flex-col gap-1">
          <h2 id="ready-h" className="label-mono text-fg-muted">
            {t("readyTitle")}
          </h2>
          <p className="text-sm text-fg-secondary">{t("readyLead")}</p>
        </div>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {ready === null
            ? Array.from({ length: 8 }, (_, i) => (
                <li key={i} className="flex h-36 flex-col gap-3 rounded-lg border border-line bg-surface p-5">
                  <span className="h-6 w-2/3 rounded-xs bg-surface-sunken motion-safe:animate-skeleton" />
                  <span className="h-3 w-1/2 rounded-xs bg-surface-sunken motion-safe:animate-skeleton" />
                </li>
              ))
            : ready.map((d) => (
                <li key={d.topic} className="overflow-hidden rounded-lg border border-line bg-surface transition-colors hover:border-line-control">
                  <Link
                    href={`/tema/${d.id}`}
                    className="group flex h-full min-h-36 flex-col justify-between gap-6 p-5 transition-colors hover:bg-surface-brand"
                  >
                    <span className="serif-display text-[1.6rem] leading-[1.1] text-fg group-hover:text-brand-fg">
                      {capitalise(d.topic)}
                    </span>
                    <span className="flex flex-col gap-0.5 font-mono text-xs text-fg-muted">
                      {d.interventions != null && d.speakers != null && (
                        <span>{t("dossierMeta", { interventions: d.interventions, speakers: d.speakers })}</span>
                      )}
                      {d.timestamp && <span>{t("updated", { date: formatDay(d.timestamp, locale) })}</span>}
                    </span>
                  </Link>
                </li>
              ))}
        </ul>
      </section>

      {recent && recent.topics.length > 0 && (
        <section aria-labelledby="recent-h" className="grid gap-6 border-t border-line pt-10 lg:grid-cols-12">
          <div className="lg:col-span-4">
            <h2 id="recent-h" className="label-mono text-fg-muted">
              {tw("lastTopics")}
            </h2>
            {recent.since && (
              <p className="mt-2 text-sm text-fg-secondary">{tw("lastTopicsHint", { date: formatDay(recent.since, locale) })}</p>
            )}
          </div>
          <ul className="grid gap-x-8 gap-y-5 sm:grid-cols-2 lg:col-span-8">
            {recent.topics.map((topic) => {
              const act = recent.acts.find((a) => a.topic?.toLowerCase() === topic.label.toLowerCase());
              return (
                <li key={topic.label}>
                  <button type="button" onClick={() => onAskTopic(topic.query)} className="group block w-full text-left">
                    <span className="text-[15px] font-semibold tracking-tight text-fg transition-colors group-hover:text-brand-fg">
                      {capitalise(topic.label)}
                    </span>
                    {act && (
                      <span className="mt-1 line-clamp-2 block text-xs leading-snug text-fg-muted">
                        <span className="tabular-nums">{formatDay(act.date, locale)}</span> · {act.title}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </section>
      )}

    </div>
  );
}
