"use client";

import { useState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import {
  ArrowRight,
  ArrowUpRight,
  Award,
  BarChart3,
  CalendarDays,
  Check,
  Compass,
  CornerDownRight,
  Globe,
  Loader2,
  MessageSquare,
  Quote,
  Scale,
  Search,
  ShieldCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { config } from "@/config";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { Logo, Symbol } from "@/components/brand/Logo";
import { ThemeToggle } from "@/components/layout/ThemeToggle";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LOCALES } from "@/components/layout/LanguageSelector";
import { useKgStats } from "@/hooks/use-kg-stats";
import { useLastUpdate } from "@/hooks/use-last-update";

const STENOGRAFO_URL = "https://stenografo.it";

/* Rotating topics, in step with QUOTES */
const TOPIC_KEYS = ["t1","t2","t3","t4","t5","t6","t7","t8","t9","t10","t11","t12"] as const;

function useSyncedRotation(length: number, intervalMs = 7000) {
  const [index, setIndex] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);

  useEffect(() => {
    // The rotation is the hero's only motion; reduced motion keeps topic one.
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let swap: ReturnType<typeof setTimeout>;
    const id = setInterval(() => {
      setIsAnimating(true);
      swap = setTimeout(() => {
        setIndex((i) => (i + 1) % length);
        setIsAnimating(false);
      }, 320);
    }, intervalMs);
    return () => {
      clearInterval(id);
      clearTimeout(swap);
    };
  }, [length, intervalMs]);

  return { index, isAnimating };
}

/* Real quotes from the DB, verbatim, aligned 1:1 with TOPIC_KEYS. `group`
   must match a key of config.politicalGroups (aliases included). */
const QUOTES = [
  {
    text: "«[…] il PNRR rappresentava un'occasione straordinaria, forse irripetibile, per colmare finalmente il divario che ci separa dagli altri Paesi europei.»",
    who: "Valentina Grippo",
    group: "Azione",
    meta: "Azione - Popolari Europeisti Riformatori - Renew Europe · Camera, seduta n. 608 · 4 febbraio 2026",
  },
  {
    text: "«[…] il sistema non riesce ad intercettarli, […] le liste di attesa scoraggiano, […] la consapevolezza della patologia è ancora insufficiente, […] lo stigma sociale frena ogni richiesta di aiuto.»",
    who: "Ilenia Malavasi",
    group: "Partito Democratico",
    meta: "Partito Democratico · Camera, seduta n. 668 · 3 giugno 2026",
  },
  {
    text: "«[…] la discussione sull'atomo in Italia non è onesta, non è competente ed è soprattutto surreale. Si parla, deliberatamente, di tecnologie che addirittura non saranno in commercio se non tra più di 30, 40 anni.»",
    who: "Marco Grimaldi",
    group: "Alleanza Verdi e Sinistra",
    meta: "Alleanza Verdi e Sinistra · Camera, seduta n. 665 · 26 maggio 2026",
  },
  {
    text: "«Sono tantissimi i lavoratori il cui reddito è al di sotto della soglia di povertà, pur essendo regolarmente occupati. […] Noi pensiamo che tutto questo sia veramente inaccettabile per uno Stato civile.»",
    who: "Davide Aiello",
    group: "Movimento 5 Stelle",
    meta: "MoVimento 5 Stelle · Camera, seduta n. 15 · 29 novembre 2022",
  },
  {
    text: "«[…] oggi non è in gioco solo la sovranità del popolo ucraino, ma gli stessi fondamenti della nostra civiltà: diritto, sapere, umanesimo del lavoro, solidarietà, socialità, radici giudaico-cristiane, democrazia.»",
    who: "Fabio Rampelli",
    group: "Fratelli d'Italia",
    meta: "Fratelli d'Italia · Camera, seduta n. 673 · 11 giugno 2026",
  },
  {
    text: "«[…] la pressione fiscale ai massimi da 11 anni. La colpa non è di Bruxelles, la colpa è del vostro Governo di centrodestra. Dovete assumervene le responsabilità.»",
    who: "Piero De Luca",
    group: "Partito Democratico",
    meta: "Partito Democratico · Camera, seduta n. 683 · 30 giugno 2026",
  },
  {
    text: "«[…] oggi il vostro Governo ha presentato una proposta di riforma dell'autonomia differenziata che va esattamente nella direzione opposta a quella da lei auspicata.»",
    who: "Maria Elena Boschi",
    group: "Italia Viva",
    meta: "Italia Viva · Camera, seduta n. 683 · 30 giugno 2026",
  },
  {
    text: "«L'aspettavano gli avvocati, ma l'aspettavano soprattutto […] 500.000 cittadini che tutti gli anni vengono prosciolti, assolti in Italia, con fascicoli archiviati.»",
    who: "Gianluca Vinci",
    group: "Fratelli d'Italia",
    meta: "Fratelli d'Italia · Camera, seduta n. 667 · 28 maggio 2026",
  },
  {
    text: "«[…] una strategia molto più ampia che il Governo sta portando avanti fin dall'inizio della legislatura per restituire allo Stato la capacità di governare i flussi migratori e di far rispettare le proprie regole.»",
    who: "Simona Bordonali",
    group: "Lega",
    meta: "Lega · Camera, seduta n. 676 · 16 giugno 2026",
  },
  {
    text: "«È una scelta che rischia di snaturare la funzione di un investimento finanziato con risorse pubbliche e pensato per garantire il diritto allo studio.»",
    who: "Roberto Giachetti",
    group: "Italia Viva",
    meta: "Italia Viva · Camera, seduta n. 684 · 1 luglio 2026",
  },
  {
    text: "«Nel solo 2025 si stima che il cambiamento climatico abbia portato a 24.400 decessi in Europa a causa del caldo estremo. Di questi, ben 4.597 sono attribuiti all'Italia.»",
    who: "Patrizia Prestipino",
    group: "Partito Democratico",
    meta: "Partito Democratico · Camera, seduta n. 675 · 15 giugno 2026",
  },
  {
    text: "«Poi avete proposto il Ponte sullo Stretto, e lì veramente c'è stata la prima pietra tombale di un qualcosa che non si farà.»",
    who: "Agostino Santillo",
    group: "Movimento 5 Stelle",
    meta: "MoVimento 5 Stelle · Camera, seduta n. 681 · 23 giugno 2026",
  },
];

const groupColor = (g: string) =>
  (config.politicalGroups as Record<string, { color: string }>)[g]?.color ?? "var(--line-strong)";

function useFormattedLastUpdate() {
  const locale = useLocale();
  const iso = useLastUpdate();
  if (!iso) return null;
  return new Intl.DateTimeFormat(locale, { day: "numeric", month: "long", year: "numeric" }).format(
    new Date(`${iso}T12:00:00`)
  );
}

export default function LandingPage() {
  const t = useTranslations("Landing");
  const { index: topicIndex, isAnimating } = useSyncedRotation(TOPIC_KEYS.length);
  // Entering the app loads the full tool bundle and can take seconds: the CTA
  // shows a spinner at once. pageshow clears it when iOS restores from bfcache.
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    const clear = () => setLeaving(false);
    window.addEventListener("pageshow", clear);
    return () => window.removeEventListener("pageshow", clear);
  }, []);

  return (
    <div className="min-h-dvh bg-bg text-fg">
      {leaving && (
        <div className="fixed inset-x-0 top-0 z-dialog h-0.5" role="progressbar" aria-label="loading">
          <div className="h-full w-full bg-brand origin-left motion-safe:animate-[nav-progress_2.5s_cubic-bezier(0.15,0.6,0.3,1)_forwards]" />
        </div>
      )}

      <a
        href="#contenuto"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-full focus:bg-surface focus:px-4 focus:py-2 focus:shadow-float"
      >
        {t("skipToContent")}
      </a>

      <AccoladeBanner />
      <SiteHeader leaving={leaving} onLeave={() => setLeaving(true)} />

      <main id="contenuto">
        <Hero topicIndex={topicIndex} isAnimating={isAnimating} leaving={leaving} onLeave={() => setLeaving(true)} />
        <StatsStrip />
        <Tools onLeave={() => setLeaving(true)} />
        <Guarantees />
        <Iter />
        <Network />
        <OpenResearch />
        <Closing leaving={leaving} onLeave={() => setLeaving(true)} />
      </main>

      <div id="aggiornamenti" className="container-page scroll-mt-20 pb-16">
        <NewsletterSignup source="landing" variant="panel" />
      </div>
      <SiteFooter reveal />
    </div>
  );
}

/* ── Header ─────────────────────────────────────────────────────── */

function AccoladeBanner() {
  const t = useTranslations("Landing");
  return (
    <a
      href="https://iswc2026.semanticweb.org"
      target="_blank"
      rel="noopener noreferrer"
      className="block border-b border-line bg-surface-muted text-center text-caption text-fg-secondary hover:text-fg transition-colors"
    >
      <span className="container-page inline-flex items-center justify-center gap-2 py-2">
        <Award className="h-3.5 w-3.5 text-brand-fg shrink-0" aria-hidden />
        <span className="font-medium text-fg">ISWC 2026</span>
        <span>{t("iswcBadge")}</span>
      </span>
    </a>
  );
}

function SiteHeader({ leaving, onLeave }: { leaving: boolean; onLeave: () => void }) {
  const t = useTranslations("Landing");
  return (
    <header className="sticky top-0 z-header border-b border-line bg-bg/85 backdrop-blur-xl pt-[env(safe-area-inset-top)]">
      <div className="container-page flex h-[var(--header-h)] items-center gap-6">
        <Link
          href="/"
          aria-label="ParliamentRAG"
          className="shrink-0 rounded-md outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          <span className="hidden sm:inline-flex">
            <Logo size={21} animated />
          </span>
          <span className="inline-flex sm:hidden">
            <Symbol size={38} animated />
          </span>
        </Link>
        <nav className="hidden md:flex items-center gap-6 text-sm text-fg-secondary">
          <a href="#strumenti" className="hover:text-fg transition-colors">{t("navTools")}</a>
          <Link href="/method" className="hover:text-fg transition-colors">{t("footerMethod")}</Link>
          <Link href="/data" className="hover:text-fg transition-colors">{t("dataBandKicker")}</Link>
        </nav>
        <div className="ml-auto flex items-center gap-1">
          <LanguageMenu />
          <div className="hidden sm:block w-9">
            <ThemeToggle isCollapsed />
          </div>
          <PrimaryCta href="/home" size="sm" leaving={leaving} onLeave={onLeave} className="ml-2 hidden sm:inline-flex">
            {t("ctaPrimary")}
          </PrimaryCta>
        </div>
      </div>
    </header>
  );
}

function PrimaryCta({
  href,
  children,
  leaving,
  onLeave,
  size = "lg",
  className,
}: {
  href: string;
  children: React.ReactNode;
  leaving: boolean;
  onLeave: () => void;
  size?: "sm" | "lg";
  className?: string;
}) {
  const Icon = leaving ? Loader2 : ArrowRight;
  return (
    <Link
      href={href}
      onClick={onLeave}
      className={cn(
        "group inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-full bg-brand font-medium text-on-brand transition-[background-color,transform] duration-200 hover:bg-brand-hover active:scale-[0.98]",
        size === "lg" ? "h-12 px-6 text-[15px]" : "h-9 px-4 text-sm",
        className
      )}
    >
      {children}
      <Icon
        aria-hidden
        className={cn(
          size === "lg" ? "h-4 w-4" : "h-3.5 w-3.5",
          leaving ? "motion-safe:animate-spin" : "transition-transform group-hover:translate-x-0.5"
        )}
      />
    </Link>
  );
}

/* ── Hero ───────────────────────────────────────────────────────── */

function Hero({
  topicIndex,
  isAnimating,
  leaving,
  onLeave,
}: {
  topicIndex: number;
  isAnimating: boolean;
  leaving: boolean;
  onLeave: () => void;
}) {
  const t = useTranslations("Landing");
  return (
    <section className="container-page grid gap-12 pt-14 pb-16 md:pt-20 lg:grid-cols-12 lg:gap-10 lg:pb-20">
      <div className="lg:col-span-7">
        <p className="label-mono rise">{t("mastheadInstitution")}</p>
        <RotatingHeadline index={topicIndex} isAnimating={isAnimating} />
        <p className="rise mt-6 max-w-[34rem] text-lg leading-relaxed text-fg-secondary" style={{ "--i": 1 } as React.CSSProperties}>
          {t.rich("heroSub", { strong: (chunks) => <span className="font-medium text-fg">{chunks}</span> })}
        </p>
        <div className="rise mt-8" style={{ "--i": 2 } as React.CSSProperties}>
          <PrimaryCta href="/home" leaving={leaving} onLeave={onLeave} className="w-full sm:w-auto">
            {t("ctaPrimary")}
          </PrimaryCta>
        </div>
      </div>

      <aside className="lg:col-span-5 lg:pt-10" aria-label={t("fromTranscript")}>
        <QuoteCard index={topicIndex} isAnimating={isAnimating} />
      </aside>
    </section>
  );
}

/* All topics share one grid cell, so the headline reserves the height of the
   longest one and rotation never shifts the layout. */
function RotatingHeadline({ index, isAnimating }: { index: number; isAnimating: boolean }) {
  const t = useTranslations("Landing");
  return (
    <h1 className="serif-display mt-4 text-[clamp(2.25rem,9vw,2.75rem)] leading-[1.08] text-fg sm:text-display-l lg:text-display-xl">
      {t("heroLine1")} {t("heroLine2")}{" "}
      <span className="inline-grid max-w-full align-top">
        {TOPIC_KEYS.map((key, i) => {
          const active = i === index;
          return (
            <span
              key={key}
              aria-hidden={active ? undefined : true}
              className={cn(
                "[grid-area:1/1] justify-self-start pb-1 italic text-brand-fg transition-opacity duration-300 ease-out",
                !active && "pointer-events-none select-none"
              )}
              style={{ opacity: active && !isAnimating ? 1 : 0, visibility: active ? "visible" : "hidden" }}
            >
              {t(`topics.${key}` as never) as string}?
            </span>
          );
        })}
      </span>
    </h1>
  );
}

function QuoteCard({ index, isAnimating }: { index: number; isAnimating: boolean }) {
  const t = useTranslations("Landing");
  const locale = useLocale();
  return (
    <figure className="rounded-lg border border-line bg-surface p-6 sm:p-7">
      <figcaption className="flex items-center gap-2 label-mono">
        <Quote className="h-3.5 w-3.5" aria-hidden />
        {t("fromTranscript")}
      </figcaption>
      <div className="mt-5 grid">
        {QUOTES.map((q, i) => {
          const active = i === index;
          return (
            <div
              key={q.who + i}
              aria-hidden={active ? undefined : true}
              className={cn(
                "[grid-area:1/1] transition-opacity duration-300 ease-out",
                !active && "pointer-events-none select-none"
              )}
              style={{ opacity: active && !isAnimating ? 1 : 0, visibility: active ? "visible" : "hidden" }}
            >
              <blockquote
                className="serif-display border-l-2 pl-4 text-[1.1875rem] italic leading-[1.55] text-fg"
                style={{ borderColor: groupColor(q.group) }}
              >
                {locale === "it" ? q.text : t(`q${i + 1}` as never)}
              </blockquote>
              <p className="mt-4 text-sm text-fg-muted">
                <span className="font-medium text-fg">{q.who}</span>
                <span> · {q.meta}</span>
                {locale !== "it" && <span> · {t("quoteTranslatedNote")}</span>}
              </p>
            </div>
          );
        })}
      </div>
      <p className="mt-6 flex items-start gap-2 border-t border-line pt-4 text-sm text-fg-secondary">
        <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-fg" aria-hidden />
        {t("quotesExplainer")}
      </p>
    </figure>
  );
}

/* ── Stats ──────────────────────────────────────────────────────── */

function StatsStrip() {
  const t = useTranslations("Landing");
  const locale = useLocale();
  const kg = useKgStats();
  const date = useFormattedLastUpdate();
  const fmt = (n: number, compact = false) =>
    new Intl.NumberFormat(locale, compact ? { notation: "compact", maximumFractionDigits: 1 } : { useGrouping: "always" }).format(n);
  const items = [
    { value: fmt(kg.sessions), label: t("statsSessions") },
    { value: fmt(kg.speeches), label: t("statsSpeeches") },
    { value: fmt(kg.individual_votes, true), label: t("statsVotes") },
  ];
  return (
    <div className="border-y border-line bg-surface">
      <div className="container-page flex flex-wrap items-baseline gap-x-8 gap-y-2 py-5 text-sm">
        {items.map((it) => (
          <p key={it.label}>
            <span className="tabular font-semibold text-fg">{it.value}</span>{" "}
            <span className="text-fg-secondary">{it.label}</span>
          </p>
        ))}
        {date && <p className="text-fg-muted sm:ml-auto">{t("statsAsOf", { date })}</p>}
      </div>
    </div>
  );
}

/* ── Tools: one featured tile and four smaller ones ─────────────── */

const TOOLS = [
  { key: "idx1", href: "/home", icon: MessageSquare },
  { key: "idx2", href: "/search", icon: Search },
  { key: "idx3", href: "/ranking", icon: BarChart3 },
  { key: "idx4", href: "/compass", icon: Compass },
  { key: "idx5", href: "/timeline", icon: CalendarDays },
] as const;

function Tools({ onLeave }: { onLeave: () => void }) {
  const t = useTranslations("Landing");
  const [first, ...rest] = TOOLS;
  return (
    <section id="strumenti" className="container-page scroll-mt-20 py-20 md:py-24">
      <h2 className="serif-display text-h2 leading-tight sm:text-display-m">{t("sec1Title")}</h2>
      <p className="mt-3 max-w-prose text-fg-secondary">{t("toolsSub")}</p>

      <div className="mt-10 grid gap-4 lg:grid-cols-2">
        <ToolTile tool={first} featured onLeave={onLeave} />
        <div className="grid gap-4 sm:grid-cols-2">
          {rest.map((tool) => (
            <ToolTile key={tool.key} tool={tool} onLeave={onLeave} />
          ))}
        </div>
      </div>
    </section>
  );
}

function ToolTile({
  tool,
  featured = false,
  onLeave,
}: {
  tool: (typeof TOOLS)[number];
  featured?: boolean;
  onLeave: () => void;
}) {
  const t = useTranslations("Landing");
  const Icon = tool.icon;
  return (
    <Link
      href={tool.href}
      onClick={onLeave}
      className={cn(
        "group flex flex-col rounded-lg border p-6 transition-colors",
        featured
          ? "border-transparent bg-surface-brand hover:bg-brand-soft-strong sm:p-8"
          : "border-line bg-surface hover:border-line-strong"
      )}
    >
      <span
        className={cn(
          "inline-flex h-9 w-9 items-center justify-center rounded-md",
          featured ? "bg-brand text-on-brand" : "bg-surface-muted text-brand-fg"
        )}
      >
        <Icon className="h-[18px] w-[18px]" aria-hidden />
      </span>
      <h3 className={cn("mt-5 font-semibold tracking-[-0.01em] text-fg", featured ? "text-h4" : "text-base")}>
        {t(`${tool.key}Title` as never) as string}
      </h3>
      <p
        className={cn(
          "serif-display mt-2 italic text-fg",
          featured ? "text-[1.75rem] leading-[1.2] sm:text-[2.25rem] lg:mt-auto lg:pt-10" : "text-[15px] leading-snug"
        )}
      >
        «{t(`${tool.key}Question` as never) as string}»
      </p>
      <p className={cn("mt-3 leading-relaxed text-fg-secondary", featured ? "max-w-md text-[15px]" : "text-sm")}>
        {t(`${tool.key}Desc` as never) as string}
      </p>
      <span className={cn("inline-flex items-center gap-1.5 pt-5 text-sm font-medium text-brand-fg", !featured && "mt-auto")}>
        {t("openTool")}
        <ArrowRight className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" aria-hidden />
      </span>
    </Link>
  );
}

/* ── Guarantees ─────────────────────────────────────────────────── */

const GUARANTEES = [
  { key: "g1", icon: ShieldCheck },
  { key: "g2", icon: Scale },
  { key: "g3", icon: Award },
] as const;

function Guarantees() {
  const t = useTranslations("Landing");
  return (
    <section className="border-y border-line bg-surface-muted">
      <div className="container-page grid gap-10 py-20 md:py-24 lg:grid-cols-12">
        <div className="lg:col-span-5">
          <h2 className="serif-display text-h2 leading-tight sm:text-display-m">{t("sec2Title")}</h2>
          <p className="mt-4 max-w-md text-lg text-fg-secondary">{t("guaranteesLead")}</p>
        </div>
        <ul className="space-y-8 lg:col-span-7">
          {GUARANTEES.map(({ key, icon: Icon }) => (
            <li key={key} className="flex gap-4">
              <Icon className="mt-1 h-5 w-5 shrink-0 text-brand-fg" aria-hidden />
              <div>
                <h3 className="font-semibold text-fg">{t(`${key}Title` as never) as string}</h3>
                <p className="mt-1.5 max-w-prose leading-relaxed text-fg-secondary">{t(`${key}Body` as never) as string}</p>
              </div>
            </li>
          ))}
          <li className="border-t border-line-strong pt-6 text-sm text-fg-muted">{t("colophonStats")}</li>
        </ul>
      </div>
    </section>
  );
}

/* ── Iter: eight real pipeline steps in three acts ──────────────── */

const ACTS = [
  { key: "iterActResearch", steps: [1, 2, 3, 4] },
  { key: "iterActAnalysis", steps: [5, 6] },
  { key: "iterActWriting", steps: [7, 8] },
] as const;

function Iter() {
  const t = useTranslations("Landing");
  return (
    <section className="container-page py-20 md:py-24">
      <h2 className="serif-display text-h2 leading-tight sm:text-display-m">{t("sec3Title")}</h2>
      <p className="mt-3 max-w-prose text-fg-secondary">{t("iterIntro")}</p>
      <div className="mt-12 grid gap-10 md:grid-cols-[2fr_1fr_1fr] md:gap-8">
        {ACTS.map((act) => (
          <div key={act.key}>
            <h3 className="border-b border-line-strong pb-3 font-semibold text-fg">{t(act.key as never) as string}</h3>
            <ol className={cn("mt-5 grid gap-5", act.steps.length > 2 && "sm:grid-cols-2 md:grid-cols-1 lg:grid-cols-2")}>
              {act.steps.map((n) => (
                <li key={n} className="flex gap-3">
                  <span className="tabular font-mono text-caption leading-6 text-fg-muted">{String(n).padStart(2, "0")}</span>
                  <div>
                    <p className="font-medium leading-6 text-fg">{t(`iter${n}Title` as never) as string}</p>
                    <p className="mt-0.5 text-sm leading-relaxed text-fg-secondary">{t(`iter${n}Desc` as never) as string}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ── Network: the sister product for factual questions ──────────── */

function Network() {
  const t = useTranslations("Landing");
  return (
    <section className="container-page pb-20 md:pb-24">
      <div className="grid gap-8 rounded-lg bg-surface-sunken p-6 sm:p-10 lg:grid-cols-12 lg:items-center">
        <div className="lg:col-span-7">
          <h2 className="text-h3 font-semibold tracking-[-0.02em] text-fg">{t("reteTitle")}</h2>
          <p className="mt-3 max-w-prose leading-relaxed text-fg-secondary">{t("reteBody")}</p>
          <a
            href={STENOGRAFO_URL}
            target="_blank"
            rel="noopener"
            className="mt-6 inline-flex h-10 items-center gap-2 rounded-full border border-line-strong bg-surface px-5 text-sm font-medium text-fg transition-colors hover:bg-surface-muted"
          >
            {t("reteCta")}
            <ArrowUpRight className="h-4 w-4" aria-hidden />
          </a>
        </div>
        <ul className="space-y-3 lg:col-span-5">
          {(["reteEx1", "reteEx2", "reteEx3"] as const).map((k) => (
            <li key={k}>
              <a
                href={`${STENOGRAFO_URL}/chat?q=${encodeURIComponent(t(k))}`}
                target="_blank"
                rel="noopener"
                className="flex items-start gap-2.5 text-[15px] text-fg-secondary transition-colors hover:text-fg"
              >
                <CornerDownRight className="mt-0.5 h-4 w-4 shrink-0 text-fg-muted" aria-hidden />
                {t(k)}
              </a>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}

/* ── Open research: graph, papers, code ─────────────────────────── */

function OpenResearch() {
  const t = useTranslations("Landing");
  const td = useTranslations("DataPage");
  const locale = useLocale();
  const kg = useKgStats();
  const links = [
    { href: "https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf", label: t("paperInUse") },
    { href: "https://emeierkeio.github.io/papers/parliamentrag-demo-iswc2026.pdf", label: t("paperDemo") },
    { href: "https://github.com/Emeierkeio/ParliamentRAG", label: t("sourceCode") },
    { href: `https://mcp.parliamentrag.it/?lang=${locale}`, label: t("mcpConnector") },
  ];
  const fmt = (n: number) => new Intl.NumberFormat(locale, { useGrouping: "always" }).format(n);
  return (
    <section className="border-t border-line">
      <div className="container-page grid gap-12 py-20 md:py-24 lg:grid-cols-12">
        <div className="lg:col-span-6">
          <h2 className="serif-display text-h2 leading-tight sm:text-display-m">{t("dataBandTitle")}</h2>
          <p className="mt-4 max-w-prose leading-relaxed text-fg-secondary">{t("dataBandBody")}</p>
          <p className="mt-6 flex items-baseline gap-2">
            <span className="tabular text-h3 font-semibold text-fg">{fmt(kg.triples ?? 0)}</span>
            <span className="text-sm text-fg-secondary">{td("stTriples")}</span>
          </p>
          <Link
            href="/data"
            className="mt-8 inline-flex h-11 items-center gap-2 rounded-full bg-surface-inverse px-6 text-[15px] font-medium text-fg-inverse transition-opacity hover:opacity-90"
          >
            {t("dataBandCta")}
            <ArrowRight className="h-4 w-4" aria-hidden />
          </Link>
        </div>
        <div className="lg:col-span-5 lg:col-start-8">
          <h3 className="font-semibold text-fg">{t("researchTitle")}</h3>
          <p className="mt-2 text-sm leading-relaxed text-fg-secondary">{t("researchBody")}</p>
          <ul className="mt-6 divide-y divide-line border-y border-line">
            {links.map((l) => (
              <li key={l.href}>
                <a
                  href={l.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between gap-4 py-3.5 text-[15px] text-fg transition-colors hover:text-brand-fg"
                >
                  {l.label}
                  <ArrowUpRight className="h-4 w-4 text-fg-muted" aria-hidden />
                </a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

/* ── Closing ────────────────────────────────────────────────────── */

function Closing({ leaving, onLeave }: { leaving: boolean; onLeave: () => void }) {
  const t = useTranslations("Landing");
  return (
    <section className="container-page pb-24">
      <div className="flex flex-col gap-8 border-t border-line-strong pt-14 lg:flex-row lg:items-end lg:justify-between">
        <h2 className="serif-display max-w-3xl text-h1 leading-tight sm:text-display-m">{t("closingHeadline")}</h2>
        <PrimaryCta href="/home" leaving={leaving} onLeave={onLeave} className="w-full sm:w-auto">
          {t("ctaPrimary")}
        </PrimaryCta>
      </div>
    </section>
  );
}

/* ── Language menu ──────────────────────────────────────────────── */

function LanguageMenu() {
  const locale = useLocale();
  const current = LOCALES.find((l) => l.code === locale) ?? LOCALES[0];

  const switchTo = (nextLocale: string) => {
    if (nextLocale === locale) return;
    document.cookie = `NEXT_LOCALE=${nextLocale}; path=/; max-age=31536000; SameSite=Lax`;
    const qs = nextLocale === "it" ? "" : `?lang=${nextLocale}`;
    window.location.href = `/${qs}`;
  };

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          className="inline-flex h-9 items-center gap-1.5 rounded-full px-3 font-mono text-caption uppercase tracking-[0.06em] text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
          aria-label="Language"
        >
          <Globe className="h-3.5 w-3.5" aria-hidden />
          {current.code}
        </button>
      </PopoverTrigger>
      <PopoverContent side="bottom" align="end" className="w-[170px] p-1.5">
        {LOCALES.map((l) => (
          <button
            key={l.code}
            onClick={() => switchTo(l.code)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
              l.code === locale ? "bg-surface-muted font-medium text-fg" : "text-fg-secondary hover:bg-surface-muted hover:text-fg"
            )}
          >
            <span className="w-6 label-mono">{l.code}</span>
            <span className="flex-1 text-left">{l.label}</span>
            {l.code === locale && <Check className="h-3.5 w-3.5" aria-hidden />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
