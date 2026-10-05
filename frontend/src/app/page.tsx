"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowRight, ArrowUpRight, FileText } from "lucide-react";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { fetchNewsletterEnabled } from "@/components/feedback/api";
import { PageDots } from "@/components/centro/PageDots";
import { SoonBadge } from "@/components/centro/SystemCard";
import { CentroPage, SectionTitle } from "@/components/centro/CentroPage";
import { SystemCard } from "@/components/centro/SystemCard";
import { PAPER_DEMO_PDF, PAPER_DEMO_TITLE, PAPER_IN_USE_PDF, PAPER_IN_USE_TITLE, SYSTEMS } from "@/components/centro/systems";
import { useKgStats } from "@/hooks/use-kg-stats";
import { useLastUpdate } from "@/hooks/use-last-update";

const PILLARS = ["pillar1", "pillar2", "pillar3"] as const;

function useNumber() {
  const locale = useLocale();
  return (n: number, compact = false) =>
    new Intl.NumberFormat(locale, {
      useGrouping: "always",
      ...(compact ? { notation: "compact" as const, maximumFractionDigits: 1 } : {}),
    }).format(n);
}

function useNewsletterEnabled() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    let alive = true;
    fetchNewsletterEnabled().then((on) => alive && setEnabled(on));
    return () => {
      alive = false;
    };
  }, []);
  return enabled;
}

/*
 * Desktop scrolls as one long page. Below md the same content becomes six
 * snapped screens (hero, one per system, papers, newsletter): the parts that
 * would overfill a phone screen (stats, pillars, open data) are desktop-only.
 */
export default function HomePage() {
  const t = useTranslations("Centro");
  const newsletter = useNewsletterEnabled();
  const screens = useMemo(
    () => [
      { id: "s-intro", label: "ParliamentRAG" },
      ...SYSTEMS.map((s) => ({ id: `s-${s.id}`, label: s.name })),
      { id: "s-pubblicazioni", label: t("navPublications") },
      ...(newsletter ? [{ id: "s-newsletter", label: t("navUpdates") }] : []),
    ],
    [t, newsletter],
  );
  return (
    <CentroPage reveal>
      <Hero />
      <StatsStrip />
      <Systems />
      <SystemScreens />
      <Publications />
      <OpenData />
      {newsletter && (
        <section id="s-newsletter" className="container-page snap-screen pb-16 md:pb-24">
          <NewsletterSignup source="landing" />
        </section>
      )}
      <PageDots screens={screens} />
    </CentroPage>
  );
}

function Hero() {
  const t = useTranslations("Centro");
  return (
    <section id="s-intro" className="container-page snap-screen grid content-center gap-10 pt-10 pb-14 sm:pt-16 md:content-start lg:grid-cols-12 lg:gap-12 lg:pt-24 lg:pb-20">
      <div className="lg:col-span-7">
        <p className="label-mono rise">{t("homeKicker")}</p>
        <h1 className="serif-display rise mt-5 text-[clamp(2.375rem,9vw,4.25rem)] leading-[1.04] text-fg" style={{ "--i": 1 } as React.CSSProperties}>
          {t("homeTitle")}
        </h1>
        <p className="rise mt-6 max-w-[38rem] text-[17px] leading-relaxed text-fg-secondary sm:text-lg" style={{ "--i": 2 } as React.CSSProperties}>
          {t("homeLead")}
        </p>
        <div className="rise mt-8 flex flex-col gap-3 sm:flex-row" style={{ "--i": 3 } as React.CSSProperties}>
          <Link
            href="/sistemi"
            className="group inline-flex h-12 items-center justify-center gap-2 rounded-full bg-brand px-6 text-[15px] font-medium text-on-brand transition-colors hover:bg-brand-hover"
          >
            {t("homeCtaSystems")}
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
          <Link
            href="/pubblicazioni"
            className="hidden h-12 items-center justify-center gap-2 rounded-full border border-line-strong bg-surface px-6 text-[15px] font-medium text-fg transition-colors hover:bg-surface-muted md:inline-flex"
          >
            {t("homeCtaPapers")}
          </Link>
        </div>
      </div>

      <aside className="rise hidden md:block lg:col-span-5 lg:pt-3" style={{ "--i": 4 } as React.CSSProperties} aria-label={t("pillarsLabel")}>
        <ol className="divide-y divide-line rounded-lg border border-line bg-surface">
          {PILLARS.map((p, i) => (
            <li key={p} className="flex gap-4 p-5 sm:p-6">
              <span className="tabular font-mono text-caption leading-6 text-fg-muted">{String(i + 1).padStart(2, "0")}</span>
              <div>
                <p className="font-semibold leading-6 text-fg">{t(`${p}Title`)}</p>
                <p className="mt-1 text-[15px] leading-relaxed text-fg-secondary">{t(`${p}Body`)}</p>
              </div>
            </li>
          ))}
        </ol>
      </aside>
    </section>
  );
}

function StatsStrip() {
  const t = useTranslations("Centro");
  const tl = useTranslations("Landing");
  const locale = useLocale();
  const kg = useKgStats();
  const iso = useLastUpdate();
  const fmt = useNumber();
  const date = new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" }).format(new Date(`${iso}T12:00:00`));
  const items = [
    { value: fmt(kg.sessions), label: tl("statsSessions") },
    { value: fmt(kg.speeches), label: tl("statsSpeeches") },
    { value: fmt(kg.individual_votes, true), label: tl("statsVotes") },
  ];
  return (
    <div className="hidden border-y border-line bg-surface md:block">
      <div className="container-page flex flex-wrap items-baseline gap-x-8 gap-y-2 py-5 text-[15px]">
        <p className="label-mono w-full sm:w-auto">{t("statsLabel")}</p>
        {items.map((it) => (
          <p key={it.label}>
            <span className="tabular font-semibold text-fg">{it.value}</span> <span className="text-fg-secondary">{it.label}</span>
          </p>
        ))}
        <p className="text-sm text-fg-muted sm:ml-auto">{tl("statsAsOf", { date })}</p>
      </div>
    </div>
  );
}

function Systems() {
  const t = useTranslations("Centro");
  return (
    <section className="container-page hidden py-16 md:block md:py-24" aria-labelledby="sistemi-title">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <SectionTitle id="sistemi-title" title={t("systemsTitle")} lead={t("systemsLead")} />
        <Link href="/sistemi" className="group inline-flex min-h-11 shrink-0 items-center gap-1.5 text-[15px] font-medium text-brand-fg">
          {t("systemsMore")}
          <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
        </Link>
      </div>
      <ul className="mt-10 grid gap-4 md:grid-cols-3 md:gap-5">
        {SYSTEMS.map((s) => (
          <li key={s.id} className="flex">
            <SystemCard system={s} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Phone-only: one screen per system, with a single action each. */
function SystemScreens() {
  const t = useTranslations("Centro");
  return (
    <div className="md:hidden">
      {SYSTEMS.map((s, i) => {
        const { Mark } = s;
        const action = "mt-8 inline-flex h-12 w-full items-center justify-center gap-2 rounded-full text-[15px] font-medium";
        return (
          <section key={s.id} id={`s-${s.id}`} className="snap-screen border-t border-line" aria-labelledby={`s-${s.id}-name`}>
            <p className="label-mono">{t("systemOf", { n: i + 1, total: SYSTEMS.length })}</p>
            <div className="mt-8 flex items-center justify-between gap-4">
              <Mark size={64} />
              {!s.live && <SoonBadge />}
            </div>
            <h2 id={`s-${s.id}-name`} className="serif-display mt-6 text-[2.5rem] leading-none text-fg">
              {s.name}
            </h2>
            <p className="mt-4 text-[17px] leading-relaxed text-fg-secondary">{t(`${s.id}Job`)}</p>
            <p className="mt-3 font-mono text-sm text-fg-muted">{s.domain}</p>
            {s.live ? (
              <a href={s.url} target="_blank" rel="noopener" className={`${action} bg-brand text-on-brand`}>
                {t("visitDomain", { domain: s.domain })}
                <ArrowUpRight className="size-4" aria-hidden />
              </a>
            ) : (
              <Link href={`/sistemi#${s.id}`} className={`${action} border border-line-strong bg-surface text-fg`}>
                {t("readMore")}
                <ArrowRight className="size-4" aria-hidden />
              </Link>
            )}
          </section>
        );
      })}
    </div>
  );
}

function Publications() {
  const t = useTranslations("Centro");
  const papers = [
    { href: PAPER_IN_USE_PDF, title: PAPER_IN_USE_TITLE, venue: t("pub1Venue") },
    { href: PAPER_DEMO_PDF, title: PAPER_DEMO_TITLE, venue: t("pub2Venue") },
  ];
  return (
    <section id="s-pubblicazioni" className="snap-screen border-y border-line bg-surface-muted" aria-labelledby="pub-title">
      <div className="grid gap-10 md:container-page md:py-24 lg:grid-cols-12 lg:gap-12">
        <div className="lg:col-span-5">
          <p className="label-mono">ISWC 2026 · Bari</p>
          <div className="mt-4">
            <SectionTitle id="pub-title" title={t("pubsTitle")} lead={t("pubsLead")} />
          </div>
          <Link
            href="/pubblicazioni"
            className="mt-8 inline-flex h-12 items-center gap-2 rounded-full bg-surface-inverse px-6 text-[15px] font-medium text-fg-inverse transition-opacity hover:opacity-90"
          >
            {t("pubsAll")}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
        </div>
        <ul className="hidden gap-4 md:grid lg:col-span-7">
          {papers.map((p) => (
            <li key={p.href}>
              <a
                href={p.href}
                target="_blank"
                rel="noopener noreferrer"
                className="group flex flex-col gap-4 rounded-lg border border-line bg-surface p-6 transition-colors hover:border-line-strong sm:p-7"
              >
                <p className="label-mono">{p.venue}</p>
                <p className="serif-display text-[1.375rem] leading-snug text-fg sm:text-[1.625rem]">{p.title}</p>
                <p className="text-sm text-fg-secondary">{t("authorsShort")}</p>
                <span className="inline-flex items-center gap-1.5 text-sm font-medium text-brand-fg">
                  <FileText className="size-4" aria-hidden />
                  {t("readPdf")}
                  <ArrowUpRight className="size-3.5" aria-hidden />
                </span>
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function OpenData() {
  const t = useTranslations("Centro");
  const td = useTranslations("DataPage");
  const kg = useKgStats();
  const fmt = useNumber();
  const stats = [
    { value: fmt(kg.acts), label: td("stActs") },
    { value: fmt(kg.votes), label: td("stVotes") },
    { value: fmt(kg.eurovoc_concepts), label: td("stEurovoc") },
    { value: fmt(kg.triples ?? 0), label: td("stTriples") },
  ];
  return (
    <section className="container-page hidden gap-10 py-16 md:grid md:py-24 lg:grid-cols-12 lg:gap-12" aria-labelledby="dati-title">
      <div className="lg:col-span-5">
        <SectionTitle id="dati-title" title={t("dataTitle")} lead={t("dataLead")} />
        <div className="mt-8 flex flex-col gap-3 sm:flex-row">
          <Link
            href="/data"
            className="inline-flex h-12 items-center justify-center gap-2 rounded-full bg-brand px-6 text-[15px] font-medium text-on-brand transition-colors hover:bg-brand-hover"
          >
            {t("dataCta")}
            <ArrowRight className="size-4" aria-hidden />
          </Link>
          <Link
            href="/sviluppatori"
            className="inline-flex h-12 items-center justify-center rounded-full border border-line-strong bg-surface px-6 text-[15px] font-medium text-fg transition-colors hover:bg-surface-muted"
          >
            {t("devCta")}
          </Link>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-x-6 lg:col-span-7">
        {stats.map((s) => (
          <div key={s.label} className="border-t border-line py-5">
            <dd className="tabular text-[clamp(1.5rem,6vw,2rem)] font-semibold tracking-[-0.02em] text-fg">{s.value}</dd>
            <dt className="mt-1 text-sm leading-snug text-fg-muted">{s.label}</dt>
          </div>
        ))}
      </dl>
    </section>
  );
}
