"use client";

import { useState, useEffect, useRef } from "react";
import { useTranslations, useLocale } from "next-intl";
import Link from "next/link";
import Image from "next/image";
import { Fraunces } from "next/font/google";
import { ArrowRight, ArrowUpRight, Globe, Check, Award, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { config } from "@/config";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { LOCALES } from "@/components/layout/LanguageSelector";
import { useKgStats } from "@/hooks/use-kg-stats";
import { useLastUpdate } from "@/hooks/use-last-update";

/* ── Display typeface — editorial serif with optical sizing ────── */
const fraunces = Fraunces({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

/* ── Rotating topics ───────────────────────────────────────────── */
const TOPIC_KEYS = ["t1","t2","t3","t4","t5","t6","t7","t8","t9","t10","t11","t12"] as const;

function useSyncedRotation(length: number, intervalMs = 7000) {
  const [index, setIndex] = useState(0);
  const [isAnimating, setIsAnimating] = useState(false);

  useEffect(() => {
    const id = setInterval(() => {
      setIsAnimating(true);
      setTimeout(() => {
        setIndex((i) => (i + 1) % length);
        setIsAnimating(false);
      }, 380);
    }, intervalMs);
    return () => clearInterval(id);
  }, [length, intervalMs]);

  return { index, isAnimating };
}

/* ── Real quotes from the DB — verbatim, aligned 1:1 with ROTATING_TOPICS.
   `group` must match a key of config.politicalGroups (aliases included) so
   the quote rule picks up the official group color used across the app. ── */
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
  (config.politicalGroups as Record<string, { color: string }>)[g]?.color ?? "#9E9E9E";

/* ── Scroll reveal — IntersectionObserver, fires once per element.
   Reduced-motion users get the content immediately, no hidden state. ── */
function useInView<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);
  const [inView, setInView] = useState(false);

  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setInView(true);
      return;
    }
    const el = ref.current;
    if (!el) {
      setInView(true);
      return;
    }
    const io = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setInView(true);
          io.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.05 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return { ref, inView };
}

function Reveal({
  children,
  className = "",
  delay = 0,
}: {
  children: React.ReactNode;
  className?: string;
  delay?: number;
}) {
  const { ref, inView } = useInView<HTMLDivElement>();
  return (
    <div
      ref={ref}
      style={{ transitionDelay: inView ? `${delay}ms` : undefined }}
      className={cn(
        "transition-[opacity,transform] duration-700 ease-out",
        inView ? "opacity-100 translate-y-0" : "opacity-0 translate-y-4",
        className
      )}
    >
      {children}
    </div>
  );
}

/* ── Data freshness line (masthead) — latest session in the DB ── */
function useEditionDate() {
  const t = useTranslations("Landing");
  const locale = useLocale();
  const iso = useLastUpdate();
  const formatted = new Intl.DateTimeFormat(locale, {
    day: "numeric",
    month: "long",
    year: "numeric",
  }).format(new Date(`${iso}T12:00:00`));
  return t("edition", { date: formatted });
}

/* ── Page ──────────────────────────────────────────────────────── */
export default function LandingPage() {
  const t = useTranslations("Landing");
  const locale = useLocale();
  const edition = useEditionDate();
  const { index: topicIndex, isAnimating } = useSyncedRotation(
    TOPIC_KEYS.length
  );
  // Entering the app loads the full tool bundle and can take seconds:
  // without instant feedback the tap feels dead. pageshow clears the
  // state when iOS restores the landing from bfcache.
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    const clear = () => setLeaving(false);
    window.addEventListener("pageshow", clear);
    return () => window.removeEventListener("pageshow", clear);
  }, []);
  const goCta = (className: string) =>
    leaving ? (
      <Loader2 className={`${className} motion-safe:animate-spin`} />
    ) : (
      <ArrowRight className={className} />
    );

  return (
    <div
      className={`${fraunces.variable} min-h-screen bg-background text-foreground`}
    >
      {/* Progress line while the app document loads after a CTA tap */}
      {leaving && (
        <div className="fixed inset-x-0 top-0 z-[100] h-0.5" role="progressbar" aria-label="loading">
          <div className="h-full w-full bg-primary origin-left motion-safe:animate-[nav-progress_2.5s_cubic-bezier(0.15,0.6,0.3,1)_forwards]" />
        </div>
      )}

      {/* ── Masthead ───────────────────────────────────────────── */}
      <header className="border-b-2 border-foreground">
        <div className="max-w-6xl mx-auto px-6">
          {/* Edition line */}
          <div className="flex items-center justify-between gap-3 py-2 text-[10px] sm:text-[11px] uppercase tracking-[0.14em] sm:tracking-[0.2em] text-muted-foreground border-b border-border">
            <span className="min-w-0">{edition || " "}</span>
            <span className="inline-flex shrink-0 items-center whitespace-nowrap">
              <LanguageMenu />
            </span>
          </div>
          {/* Wordmark row */}
          <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3 py-5">
            <div className="flex items-center gap-3">
              <Image src="/logo-blue.svg" alt="" width={46} height={32} />
              <span className="[font-family:var(--font-display)] text-2xl sm:text-3xl font-semibold tracking-tight">
                ParliamentRAG
              </span>
            </div>
            <Link
              href="/home"
              onClick={() => setLeaving(true)}
              className="group hidden sm:inline-flex w-auto justify-center items-center gap-2 whitespace-nowrap bg-primary text-primary-foreground px-4 py-2.5 text-[13px] font-medium tracking-wide hover:bg-foreground transition-colors cursor-pointer"
            >
              {t("ctaPrimary")}
              {goCta("h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5")}
            </Link>
          </div>
        </div>
        {/* Accolade band — newspaper-style credential under the masthead */}
        <a
          href="https://iswc2026.semanticweb.org"
          target="_blank"
          rel="noopener noreferrer"
          className="group block border-t border-border bg-primary/[0.05] hover:bg-primary/[0.09] transition-colors cursor-pointer"
        >
          <span className="flex flex-wrap items-center justify-center gap-x-2.5 gap-y-0.5 py-2 px-4 sm:px-6 text-[11px] uppercase tracking-[0.14em] sm:tracking-[0.2em] text-center text-foreground/60 group-hover:text-foreground transition-colors">
            <Award className="h-3.5 w-3.5 text-primary shrink-0" />
            <span className="[font-family:var(--font-display)] normal-case tracking-normal text-[13px] font-semibold text-primary whitespace-nowrap">
              ISWC 2026
            </span>
            <span aria-hidden className="hidden sm:inline text-border">|</span>
            <span>{t("iswcBadge")}</span>
          </span>
        </a>
      </header>

      <SideTOC />

      {/* ── Front page ─────────────────────────────────────────── */}
      <section id="hero" className="px-6 pt-14 sm:pt-20 pb-16">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-12 gap-12 lg:gap-8 items-start motion-safe:animate-in motion-safe:fade-in motion-safe:slide-in-from-bottom-2 motion-safe:duration-700">
          {/* Headline column */}
          <div className="lg:col-span-7">
            <RotatingHero index={topicIndex} isAnimating={isAnimating} />

            <p className="mt-6 sm:mt-8 text-lg leading-relaxed text-muted-foreground max-w-xl">
              {t.rich("heroSub", {
                strong: (chunks) => <span className="text-foreground">{chunks}</span>,
              })}
            </p>

            <div className="mt-8 sm:mt-10">
              <Link
                href="/home"
                onClick={() => setLeaving(true)}
                className="group inline-flex w-full sm:w-auto justify-center items-center gap-3 bg-primary text-primary-foreground px-7 py-3.5 text-[15px] font-medium tracking-wide hover:bg-foreground transition-colors cursor-pointer"
              >
                {t("ctaPrimary")}
                {goCta("h-4 w-4 transition-transform group-hover:translate-x-1")}
              </Link>
              <div className="mt-5 flex w-full sm:w-auto flex-wrap items-center justify-between sm:justify-start gap-x-3 gap-y-1 sm:gap-x-8">
                <a
                  href="https://github.com/Emeierkeio/ParliamentRAG"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-baseline gap-1 py-1.5 text-[13px] sm:text-sm whitespace-nowrap text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  <span className="border-b border-border group-hover:border-foreground pb-0.5 transition-colors">
                    {t("sourceCode")}
                  </span>
                  <ArrowUpRight className="hidden sm:block h-3.5 w-3.5 self-center" />
                </a>
                <a
                  href="https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-baseline gap-1 py-1.5 text-[13px] sm:text-sm whitespace-nowrap text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  <span className="border-b border-border group-hover:border-foreground pb-0.5 transition-colors">
                    {t("paperInUse")}
                  </span>
                  <ArrowUpRight className="hidden sm:block h-3.5 w-3.5 self-center" />
                </a>
                <a
                  href="https://emeierkeio.github.io/papers/parliamentrag-demo-iswc2026.pdf"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-baseline gap-1 py-1.5 text-[13px] sm:text-sm whitespace-nowrap text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  <span className="border-b border-border group-hover:border-foreground pb-0.5 transition-colors">
                    {t("paperDemo")}
                  </span>
                  <ArrowUpRight className="hidden sm:block h-3.5 w-3.5 self-center" />
                </a>
                <a
                  href={`https://mcp.parliamentrag.it/?lang=${locale}`}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="group inline-flex items-baseline gap-1 py-1.5 text-[13px] sm:text-sm whitespace-nowrap text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                >
                  <span className="border-b border-border group-hover:border-foreground pb-0.5 transition-colors">
                    {t("mcpConnector")}
                  </span>
                  <ArrowUpRight className="hidden sm:block h-3.5 w-3.5 self-center" />
                </a>
              </div>
            </div>
          </div>

          {/* Column of record */}
          <aside className="lg:col-span-5 lg:pl-8 lg:border-l border-border">
            <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground mb-4">
              {t("fromTranscript")}
            </p>
            {/* All quotes share one grid cell: the column reserves the height
                of the tallest quote, so rotation never shifts the layout. */}
            <div className="grid">
              {QUOTES.map((q, i) => {
                const active = i === topicIndex;
                return (
                  <figure
                    key={q.who + i}
                    aria-hidden={active ? undefined : true}
                    className={`[grid-area:1/1] [font-family:var(--font-display)] transition-opacity duration-300 ease-out motion-reduce:transition-none ${
                      active ? "" : "pointer-events-none select-none"
                    }`}
                    style={{
                      opacity: active && !isAnimating ? 1 : 0,
                      visibility: active ? "visible" : "hidden",
                    }}
                  >
                    <div
                      className="border-l-[3px] pl-5"
                      style={{ borderColor: groupColor(q.group) }}
                    >
                      <blockquote className="text-lg sm:text-xl leading-[1.55] text-foreground/90">
                        {locale === "it" ? q.text : t(`q${i + 1}`)}
                      </blockquote>
                      <figcaption className="mt-4 text-sm not-italic font-sans">
                        <span className="font-medium text-foreground">{q.who}</span>
                        <span className="text-muted-foreground"> · {q.meta}</span>
                        {locale !== "it" && (
                          <span className="text-muted-foreground/60"> · {t("quoteTranslatedNote")}</span>
                        )}
                      </figcaption>
                    </div>
                  </figure>
                );
              })}
            </div>
            <div className="mt-6 pt-4 border-t border-border text-xs text-muted-foreground">
              <span>{t("quoteLinkNote")}</span>
            </div>
            <p className="mt-8 text-sm leading-relaxed text-muted-foreground">
              {t("quotesExplainer")}
            </p>
          </aside>
        </div>
      </section>

      {/* ── Indice — the five instruments ──────────────────────── */}
      <section id="strumenti" className="px-6 py-14 sm:py-20">
        <div className="max-w-6xl mx-auto">
          <SectionRule numeral="I" title={t("sec1Title")} />

          <Reveal className="mt-2">
            <IndexRow
              numeral="01"
              title={t("idx1Title")}
              question={t("idx1Question")}
              description={t("idx1Desc")}
              href="/home"
              onNavigate={() => setLeaving(true)}
            />
            <IndexRow
              numeral="02"
              title={t("idx2Title")}
              question={t("idx2Question")}
              description={t("idx2Desc")}
              href="/search"
              onNavigate={() => setLeaving(true)}
            />
            <IndexRow
              numeral="03"
              title={t("idx3Title")}
              question={t("idx3Question")}
              description={t("idx3Desc")}
              href="/ranking"
              onNavigate={() => setLeaving(true)}
            />
            <IndexRow
              numeral="04"
              title={t("idx4Title")}
              question={t("idx4Question")}
              description={t("idx4Desc")}
              href="/compass"
              onNavigate={() => setLeaving(true)}
            />
            <IndexRow
              numeral="05"
              title={t("idx5Title")}
              question={t("idx5Question")}
              description={t("idx5Desc")}
              href="/timeline"
              onNavigate={() => setLeaving(true)}
              last
            />
          </Reveal>
        </div>
      </section>

      {/* ── Garanzie — typeset clauses, the page's single ink band is §IV ── */}
      <section id="garanzie" className="px-6 py-14 sm:py-20">
        <div className="max-w-6xl mx-auto">
          <SectionRule numeral="II" title={t("sec2Title")} />

          <div className="mt-12 max-w-3xl space-y-10 sm:space-y-12">
            {(["g1", "g2", "g3"] as const).map((g, i) => (
              <Reveal key={g} delay={i * 120}>
                <div className="flex gap-5 sm:gap-6">
                  <span className="[font-family:var(--font-display)] italic text-2xl text-primary/60 leading-8 select-none">
                    {String.fromCharCode(97 + i)})
                  </span>
                  <div>
                    <h3 className="[font-family:var(--font-display)] text-xl sm:text-2xl font-medium tracking-tight mb-2">
                      {t(`${g}Title`)}
                    </h3>
                    <p className="text-[15px] leading-relaxed text-muted-foreground max-w-[62ch]">
                      {t(`${g}Body`)}
                    </p>
                  </div>
                </div>
              </Reveal>
            ))}
          </div>

          {/* Colophon line */}
          <p className="mt-14 pt-6 border-t border-border text-sm text-muted-foreground leading-relaxed">
            {t("colophonStats")}
          </p>
        </div>
      </section>

      {/* ── L'iter di ogni domanda — three acts instead of a flat list ── */}
      <section id="pipeline" className="px-6 py-14 sm:py-20">
        <div className="max-w-6xl mx-auto">
          <SectionRule numeral="III" title={t("sec3Title")} />
          <p className="mt-6 text-muted-foreground max-w-xl">
            {t("iterIntro")}
          </p>

          <div className="mt-12 grid gap-12 lg:grid-cols-3 lg:gap-10">
            {(
              [
                { key: "iterActResearch", steps: [1, 2, 3, 4] },
                { key: "iterActAnalysis", steps: [5, 6] },
                { key: "iterActWriting", steps: [7, 8] },
              ] as const
            ).map((act, ai) => (
              <Reveal key={act.key} delay={ai * 120}>
                <div className="flex items-baseline gap-3 border-b border-foreground/70 pb-2.5">
                  <span className="[font-family:var(--font-display)] italic text-lg text-primary/60 select-none">
                    {ai + 1}.
                  </span>
                  <h3 className="[font-family:var(--font-display)] text-xl font-medium tracking-tight">
                    {t(act.key as never) as string}
                  </h3>
                </div>
                <ol className="mt-5 space-y-5">
                  {act.steps.map((n) => (
                    <li key={n} className="flex gap-4">
                      <span className="[font-family:var(--font-display)] text-base text-primary/40 tabular-nums leading-6 select-none">
                        {String(n).padStart(2, "0")}
                      </span>
                      <div>
                        <p className="text-[15px] font-medium leading-6">
                          {t(`iter${n}Title` as never) as string}
                        </p>
                        <p className="mt-0.5 text-sm leading-relaxed text-muted-foreground">
                          {t(`iter${n}Desc` as never) as string}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ── IV. Dati aperti — the graph behind the answers ─────── */}
      <section id="dati" className="px-6 py-14 sm:py-20 bg-primary text-primary-foreground">
        <div className="max-w-6xl mx-auto">
          <SectionRule numeral="IV" title={t("dataBandKicker")} inverted />
          <Reveal className="mt-10 grid lg:grid-cols-12 gap-10 lg:gap-8 items-start">
            <div className="lg:col-span-7">
              <h3 className="[font-family:var(--font-display)] text-3xl sm:text-4xl font-medium tracking-tight leading-[1.12] text-balance">
                {t("dataBandTitle")}
              </h3>
              <p className="mt-4 leading-relaxed text-primary-foreground/70 max-w-xl">
                {t("dataBandBody")}
              </p>
              <div className="mt-8">
                <Link
                  href="/data"
                  className="group inline-flex w-full sm:w-auto justify-center items-center gap-3 bg-primary-foreground text-primary px-7 py-3.5 text-[15px] font-medium tracking-wide hover:bg-chart-3 transition-colors cursor-pointer"
                >
                  {t("dataBandCta")}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                </Link>
              </div>
            </div>
            <aside className="lg:col-span-5 lg:pl-8 lg:border-l border-primary-foreground/15">
              <DataStats inverted />
            </aside>
          </Reveal>
        </div>
      </section>

      {/* ── Chiusura ───────────────────────────────────────────── */}
      <section id="inizia" className="px-6 pt-8 pb-24">
        <div className="max-w-6xl mx-auto border-t-2 border-foreground pt-14">
          <div className="grid lg:grid-cols-12 gap-8 items-end">
            <h2 className="lg:col-span-8 [font-family:var(--font-display)] text-4xl sm:text-5xl font-medium tracking-tight leading-[1.08] text-balance">
              {t("closingHeadline")}
            </h2>
            <div className="lg:col-span-4 lg:text-right">
              <Link
                href="/home"
                onClick={() => setLeaving(true)}
                className="group inline-flex w-full sm:w-auto justify-center items-center gap-3 bg-primary text-primary-foreground px-7 py-3.5 text-[15px] font-medium tracking-wide hover:bg-foreground transition-colors cursor-pointer"
              >
                {t("ctaPrimary")}
                {goCta("h-4 w-4 transition-transform group-hover:translate-x-1")}
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* ── Colophon ───────────────────────────────────────────── */}
      <footer className="px-6 py-10 border-t border-border">
        <div className="max-w-6xl mx-auto">
          {/* Brand + resource links */}
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-x-8 gap-y-5">
            <div className="flex items-center gap-2.5 shrink-0">
              <Image src="/logo-blue.svg" alt="" width={26} height={18} />
              <span className="[font-family:var(--font-display)] text-sm font-medium text-foreground">
                ParliamentRAG
              </span>
            </div>
            <nav className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground">
              <FooterLink href="https://github.com/Emeierkeio/ParliamentRAG" external>
                GitHub
              </FooterLink>
              <FooterLink href="https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf" external>
                {t("paperInUse")}
              </FooterLink>
              <FooterLink href="https://emeierkeio.github.io/papers/parliamentrag-demo-iswc2026.pdf" external>
                {t("paperDemo")}
              </FooterLink>
              <FooterLink href="https://orkg.org/papers/R1909763" external>
                ORKG
              </FooterLink>
              <FooterLink href="https://doi.org/10.5281/zenodo.21560331" external>
                Zenodo
              </FooterLink>
              <FooterLink href="https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19" external>
                Hugging Face
              </FooterLink>
              <FooterLink href="/method">{t("footerMethod")}</FooterLink>
              <FooterLink href="/data">{t("footerData")}</FooterLink>
              <FooterLink href="/privacy">{t("footerPrivacy")}</FooterLink>
            </nav>
          </div>
          {/* Credits */}
          <div className="mt-6 pt-5 border-t border-border flex flex-col md:flex-row md:items-baseline justify-between gap-x-8 gap-y-2 text-xs text-muted-foreground leading-relaxed">
            <p>
              {t("footerThesis")} · {t("footerAuthors")} ·{" "}
              <a
                href="https://www.unimib.it/"
                target="_blank"
                rel="noopener noreferrer"
                className="border-b border-border hover:border-foreground hover:text-foreground transition-colors"
              >
                {t("footerUni")}
              </a>
            </p>
            <p className="text-muted-foreground/80 md:text-right">
              {t("footerFunding")}
              <br />
              {t("footerGrants")}{" "}
              <a
                href="https://doi.org/10.3030/101189771"
                target="_blank"
                rel="noopener noreferrer"
                className="border-b border-border hover:border-foreground hover:text-foreground transition-colors"
              >
                101189771
              </a>{" "}
              (
              <a
                href="https://datapact.eu/"
                target="_blank"
                rel="noopener noreferrer"
                className="border-b border-border hover:border-foreground hover:text-foreground transition-colors"
              >
                DataPACT
              </a>
              )
            </p>
          </div>
        </div>
      </footer>
    </div>
  );
}

/* ── Footer link — internal or external resource ───────────────── */
function FooterLink({
  href,
  external = false,
  children,
}: {
  href: string;
  external?: boolean;
  children: React.ReactNode;
}) {
  const className =
    "inline-block pt-1 pb-0.5 border-b border-border hover:border-foreground hover:text-foreground transition-colors cursor-pointer whitespace-nowrap";
  if (external) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
        {children}
      </a>
    );
  }
  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

/* ── Data stats — live graph numbers, labels shared with /data ─── */
function DataStats({ inverted = false }: { inverted?: boolean }) {
  const td = useTranslations("DataPage");
  const locale = useLocale();
  const kg = useKgStats();
  const stats = [
    { value: kg.triples ?? 0, key: "stTriples" },
    { value: kg.individual_votes, key: "stIndVotes", compact: true },
    { value: kg.speeches, key: "stSpeeches" },
  ] as const;
  const fmt = (value: number, compact?: boolean) =>
    new Intl.NumberFormat(locale, {
      useGrouping: "always",
      ...(compact ? { notation: "compact" as const, maximumFractionDigits: 1 } : {}),
    }).format(value);
  return (
    <div>
      {stats.map((s, i) => (
        <div
          key={s.key}
          className={`flex items-baseline justify-between gap-4 py-4 ${
            i === 0 ? "" : `border-t ${inverted ? "border-primary-foreground/15" : "border-border"}`
          }`}
        >
          <span className={`[font-family:var(--font-display)] text-2xl sm:text-3xl font-medium tracking-tight tabular-nums ${inverted ? "text-primary-foreground" : "text-primary"}`}>
            {fmt(s.value, "compact" in s && s.compact)}
          </span>
          <span className={`text-sm text-right leading-snug ${inverted ? "text-primary-foreground/60" : "text-muted-foreground"}`}>
            {td(s.key)}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ── Section rule — newspaper divider with roman numeral ───────── */
function SectionRule({
  numeral,
  title,
  inverted = false,
}: {
  numeral: string;
  title: string;
  inverted?: boolean;
}) {
  return (
    <div
      className={`flex items-baseline gap-4 border-b pb-3 ${
        inverted ? "border-primary-foreground/30" : "border-foreground"
      }`}
    >
      <span
        className={`[font-family:var(--font-display)] italic text-lg ${
          inverted ? "text-primary-foreground/60" : "text-primary/60"
        }`}
      >
        {numeral}.
      </span>
      <h2 className="[font-family:var(--font-display)] text-2xl sm:text-3xl font-medium tracking-tight">
        {title}
      </h2>
    </div>
  );
}

/* ── Index row — table-of-contents entry ───────────────────────── */
function IndexRow({
  numeral,
  title,
  question,
  description,
  href,
  last = false,
  onNavigate,
}: {
  numeral: string;
  title: string;
  question: string;
  description: string;
  href: string;
  last?: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={href}
      onClick={onNavigate}
      className={`group grid sm:grid-cols-12 gap-x-6 gap-y-2 py-7 px-2 -mx-2 items-baseline border-border transition-colors hover:bg-accent/60 cursor-pointer ${
        last ? "" : "border-b"
      }`}
    >
      <span className="sm:col-span-1 [font-family:var(--font-display)] text-lg text-primary/40 tabular-nums group-hover:text-primary transition-colors">
        {numeral}
      </span>
      <div className="sm:col-span-3">
        <h3 className="[font-family:var(--font-display)] text-xl font-medium tracking-tight">
          {title}
        </h3>
      </div>
      <div className="sm:col-span-7">
        <p className="[font-family:var(--font-display)] italic text-[15px] text-foreground/80 mb-1.5">
          «{question}»
        </p>
        <p className="text-sm leading-relaxed text-muted-foreground">
          {description}
        </p>
      </div>
      <span className="sm:col-span-1 justify-self-end self-center hidden sm:block">
        <ArrowRight className="h-4 w-4 text-muted-foreground/40 transition-all group-hover:text-primary group-hover:translate-x-1" />
      </span>
    </Link>
  );
}

/* ── Rotating headline — typeset fill-in on a ruled line ───────── */
/* All topics are stacked in the same grid cell so the headline always
   reserves the height of the tallest one — no layout shift on rotation. */
function RotatingHero({
  index,
  isAnimating,
}: {
  index: number;
  isAnimating: boolean;
}) {
  const t = useTranslations("Landing");

  return (
    <h1 className="[font-family:var(--font-display)] text-[clamp(2rem,10.5vw,2.75rem)] sm:text-6xl lg:text-[4.25rem] font-medium tracking-tight leading-[1.06]">
      {t("heroLine1")}
      <br />
      {t("heroLine2")}
      <br />
      <span className="inline-grid max-w-full align-top">
        {TOPIC_KEYS.map((key, i) => {
          const active = i === index;
          return (
            <span
              key={key}
              aria-hidden={active ? undefined : true}
              className={`[grid-area:1/1] justify-self-start italic text-primary transition-opacity duration-300 ease-out motion-reduce:transition-none ${
                active ? "" : "pointer-events-none select-none"
              }`}
              style={{
                opacity: active && !isAnimating ? 1 : 0,
                visibility: active ? "visible" : "hidden",
              }}
            >
              <span className="[box-decoration-break:clone] border-b-[3px] border-primary/25">
                {t(`topics.${key}` as never) as string}?
              </span>
            </span>
          );
        })}
      </span>
    </h1>
  );
}

/* ── Side TOC — roman numerals in the margin ───────────────────── */
const TOC_ITEMS = [
  { id: "hero", labelKey: "tocFirstPage", numeral: "·" },
  { id: "strumenti", labelKey: "tocInstruments", numeral: "I" },
  { id: "garanzie", labelKey: "tocGuarantees", numeral: "II" },
  { id: "pipeline", labelKey: "tocIter", numeral: "III" },
  { id: "dati", labelKey: "tocData", numeral: "IV" },
  { id: "inizia", labelKey: "tocStart", numeral: "→" },
] as const;

function SideTOC() {
  const t = useTranslations("Landing");
  const navRef = useRef<HTMLElement | null>(null);
  const [active, setActive] = useState<string>("hero");
  const [visible, setVisible] = useState(false);
  // Per-item inversion: at the edges of the ink band part of the TOC sits
  // on navy and part on paper, so a single boolean can never color all
  // items right. Fine-grained thresholds on the band report its viewport
  // rect at ~1%-of-height granularity without any scroll listener.
  const [invertedIds, setInvertedIds] = useState<Set<string>>(new Set());

  useEffect(() => {
    const sectionEls = TOC_ITEMS.map(({ id }) =>
      document.getElementById(id)
    ).filter(Boolean) as HTMLElement[];

    // Active section: the one crossing the upper third of the viewport
    const activeIO = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) setActive(entry.target.id);
        }
      },
      { rootMargin: "-25% 0px -65% 0px" }
    );
    sectionEls.forEach((el) => activeIO.observe(el));

    // TOC appears once the hero has mostly scrolled away
    const hero = document.getElementById("hero");
    const visibleIO = new IntersectionObserver(
      ([entry]) => setVisible(!entry.isIntersecting),
      { rootMargin: "-200px 0px 0px 0px" }
    );
    if (hero) visibleIO.observe(hero);

    const dark = document.getElementById("dati");
    const invertedIO = dark
      ? new IntersectionObserver(
          ([entry]) => {
            const rect = entry.boundingClientRect;
            const nav = navRef.current;
            if (!nav) return;
            const next = new Set<string>();
            if (entry.isIntersecting) {
              nav
                .querySelectorAll<HTMLElement>("[data-toc-id]")
                .forEach((el) => {
                  const r = el.getBoundingClientRect();
                  const cy = r.top + r.height / 2;
                  if (cy >= rect.top && cy <= rect.bottom) {
                    next.add(el.dataset.tocId as string);
                  }
                });
            }
            setInvertedIds((prev) =>
              prev.size === next.size && [...next].every((id) => prev.has(id))
                ? prev
                : next
            );
          },
          { threshold: Array.from({ length: 101 }, (_, i) => i / 100) }
        )
      : null;
    if (dark && invertedIO) invertedIO.observe(dark);

    return () => {
      activeIO.disconnect();
      visibleIO.disconnect();
      invertedIO?.disconnect();
    };
  }, []);

  const scrollTo = (id: string) => {
    const el = document.getElementById(id);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

  return (
    <nav
      ref={navRef}
      className="fixed left-6 top-1/2 -translate-y-1/2 z-40 hidden xl:flex flex-col items-start gap-0.5 transition-opacity duration-300"
      style={{ opacity: visible ? 1 : 0, pointerEvents: visible ? "auto" : "none" }}
      aria-label="Navigazione sezioni"
    >
      {TOC_ITEMS.map(({ id, labelKey, numeral }) => {
        const label = t(labelKey as never) as string;
        const isActive = active === id;
        const inverted = invertedIds.has(id);
        return (
          <button
            key={id}
            data-toc-id={id}
            onClick={() => scrollTo(id)}
            className="group flex items-center gap-3 py-1.5 cursor-pointer"
            aria-current={isActive ? "true" : undefined}
          >
            <span
              className={`[font-family:var(--font-display)] italic w-5 text-right text-sm transition-colors duration-200 ${
                isActive
                  ? inverted
                    ? "text-primary-foreground"
                    : "text-primary"
                  : inverted
                    ? "text-primary-foreground/40 group-hover:text-primary-foreground/80"
                    : "text-muted-foreground/40 group-hover:text-muted-foreground"
              }`}
            >
              {numeral}
            </span>
            <span
              className={`text-[11px] font-medium transition-all duration-200 ${
                isActive
                  ? `opacity-100 translate-x-0 ${inverted ? "text-primary-foreground" : "text-foreground"}`
                  : `opacity-0 -translate-x-1 group-hover:opacity-100 group-hover:translate-x-0 ${
                      inverted
                        ? "text-primary-foreground/60"
                        : "text-muted-foreground/60"
                    }`
              }`}
            >
              {label}
            </span>
          </button>
        );
      })}
    </nav>
  );
}


/* ── Language menu — compact editorial dropdown for the masthead ── */
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
          className="inline-flex items-center gap-1.5 uppercase tracking-[0.2em] text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
          aria-label="Language"
        >
          <Globe className="h-3 w-3" />
          {current.code}
        </button>
      </PopoverTrigger>
      <PopoverContent side="bottom" align="end" className="w-[170px] p-1.5">
        {LOCALES.map((l) => (
          <button
            key={l.code}
            onClick={() => switchTo(l.code)}
            className={`flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors cursor-pointer ${
              l.code === locale
                ? "bg-accent text-foreground font-medium"
                : "text-muted-foreground hover:bg-accent/60 hover:text-foreground"
            }`}
          >
            <span className="w-6 text-[10px] uppercase tracking-wide text-muted-foreground/60">{l.code}</span>
            <span className="flex-1 text-left">{l.label}</span>
            {l.code === locale && <Check className="h-3.5 w-3.5" />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
