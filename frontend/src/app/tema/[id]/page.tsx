import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getLocale, getTranslations } from "next-intl/server";
import { ArrowUpRight } from "lucide-react";
import { BLOC_ORDER, buildDossier, compassSides, rescoreVoices, type AuthorityWeights, type SavedAnswer } from "@/lib/dossier";
import { AppBar } from "@/components/shell/AppBar";
import { GroupPositions } from "@/components/dossier/GroupPositions";
import { VoicesMatrix } from "@/components/dossier/VoicesMatrix";
import { CompassAxis } from "@/components/dossier/CompassAxis";
import { SaidAndVoted } from "@/components/dossier/SaidAndVoted";
import { CopyLink } from "@/components/dossier/CopyLink";
import { FullTextReader } from "@/components/dossier/FullTextReader";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { formatDay, formatLongDay, listFormat } from "@/components/dossier/format";

const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";

/* XIX legislature groups as abbreviated by getGroupAbbrev, for the coverage
   line: a group missing from the debate is a finding, not a gap to hide. */
const XIX_GROUPS = ["FdI", "Lega", "FI", "NM", "PD", "M5S", "AVS", "Az", "IV", "Misto"];

async function loadAnswer(id: string): Promise<SavedAnswer | null> {
  const res = await fetch(`${BACKEND_URL}/api/history/${encodeURIComponent(id)}`, {
    next: { revalidate: 3600 },
  });
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`history ${res.status}`);
  return res.json();
}

async function loadWeights(): Promise<AuthorityWeights | null> {
  try {
    const res = await fetch(`${BACKEND_URL}/api/config`, { cache: "no-store" });
    return res.ok ? ((await res.json()).authority?.weights ?? null) : null;
  } catch {
    return null;
  }
}

export async function generateMetadata({ params }: { params: Promise<{ id: string }> }): Promise<Metadata> {
  const { id } = await params;
  const raw = await loadAnswer(id).catch(() => null);
  if (!raw) return {};
  const dossier = buildDossier(raw);
  return { title: dossier.topic, description: dossier.intro ?? undefined };
}

export default async function TopicDossierPage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ leggi?: string }>;
}) {
  const { id } = await params;
  const { leggi } = await searchParams;
  const raw = await loadAnswer(id);
  if (!raw) notFound();

  const t = await getTranslations("Dossier");
  const locale = await getLocale();
  const dossier = buildDossier(raw);
  const weights = await loadWeights();
  const voices = rescoreVoices(dossier.voices, weights).slice(0, 6);
  const blocCounts = BLOC_ORDER.map((bloc) => ({
    bloc,
    n: dossier.groups.filter((g) => g.bloc === bloc).reduce((sum, g) => sum + g.interventions, 0),
  })).filter((b) => b.n > 0);

  const present = new Set(dossier.groups.filter((g) => g.bloc !== "governo").map((g) => g.abbrev));
  const missing = XIX_GROUPS.filter((g) => !present.has(g));
  const sides = dossier.compass ? compassSides(dossier.compass) : null;
  const sectionLink =
    "inline-flex h-9 shrink-0 items-center rounded-full border border-line-strong px-3.5 text-[13px] text-fg-secondary transition-colors hover:bg-surface hover:text-fg";

  return (
    <div className="min-h-[100dvh] bg-bg text-fg">
      <AppBar />

      <main className="container-page pb-24">
        <div className="grid grid-cols-[minmax(0,1fr)] gap-x-14 gap-y-10 pt-10 md:pt-14 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="flex min-w-0 flex-col gap-8">
            <div className="flex flex-col gap-4">
              <p className="label-mono text-fg-muted">
                {t("scope")} · {t("answeredOn", { date: formatLongDay(dossier.timestamp, locale) })}
              </p>
              <h1 className="serif-display text-[2.75rem] leading-[1.05] md:text-display-l">{dossier.topic}</h1>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                <p className="text-sm text-fg-secondary">
                  {t("stats", { interventions: dossier.interventions, speakers: dossier.speakers })}
                  {dossier.firstDate && dossier.lastDate && (
                    <>
                      {" · "}
                      {t("period", {
                        from: formatDay(dossier.firstDate, locale),
                        to: formatDay(dossier.lastDate, locale),
                      })}
                    </>
                  )}
                </p>
                <div className="flex gap-2 sm:ml-auto">
                  <CopyLink />
                </div>
              </div>
            </div>

            <section aria-labelledby="in-breve" className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 md:p-7">
              <h2 id="in-breve" className="label-mono text-fg-muted">
                {t("inBrief")}
              </h2>
              {sides && (sides.negative.length > 0 || sides.positive.length > 0) ? (
                <p className="text-lg leading-relaxed md:text-xl">
                  {sides.negative.length > 0 && (
                    <>
                      {t("sides", { label: dossier.compass!.negative, groups: listFormat(sides.negative, locale) })}{" "}
                    </>
                  )}
                  {sides.positive.length > 0 &&
                    t("sides", { label: dossier.compass!.positive, groups: listFormat(sides.positive, locale) })}
                </p>
              ) : null}
              {dossier.intro && <p className="max-w-prose text-[15px] leading-relaxed text-fg-secondary">{dossier.intro}</p>}
              <p className="flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-4 text-[13px] text-fg-secondary">
                <span>
                  {missing.length === 0
                    ? t("coverageAll", { total: XIX_GROUPS.length })
                    : t("coverageSome", { present: XIX_GROUPS.length - missing.length, total: XIX_GROUPS.length })}
                </span>
                {missing.length > 0 && <span className="text-notice-fg">{t("coverageMissing", { groups: listFormat(missing, locale) })}</span>}
                <span className="text-fg-muted">
                  {blocCounts.map((b) => `${t(`bloc_${b.bloc}`)} ${t("blocCount", { n: b.n })}`).join(" · ")}
                </span>
              </p>
            </section>

            <nav aria-label={t("inBrief")} className="-mx-4 flex gap-2 overflow-x-auto px-4 md:mx-0 md:px-0">
              <a href="#posizioni" className={sectionLink}>{t("navPositions")}</a>
              <a href="#detto-e-votato" className={sectionLink}>{t("navSaidVoted")}</a>
              <a href="#voci" className={sectionLink}>{t("navVoices")}</a>
              {dossier.compass && <a href="#bussola" className={sectionLink}>{t("navCompass")}</a>}
              <FullTextReader
                answer={raw.answer}
                title={dossier.topic}
                initialOpen={leggi === "1"}
                triggerClassName={`${sectionLink} gap-1.5`}
                citations={(raw.citations ?? []).map((c) => ({
                  chunkId: c.chunk_id,
                  speaker: `${c.deputy_first_name} ${c.deputy_last_name}`,
                  date: c.date ?? null,
                  verified: Boolean(c.verified),
                }))}
              />
            </nav>

            <section id="posizioni" aria-labelledby="posizioni-h" className="scroll-mt-20">
              <h2 id="posizioni-h" className="sr-only">{t("navPositions")}</h2>
              <GroupPositions groups={dossier.groups} locale={locale} />
              <p className="pt-4 text-caption text-fg-muted">{t("sourceNote")}</p>
            </section>
          </div>

          <aside className="flex flex-col gap-6 lg:sticky lg:top-[calc(var(--header-h)+2rem)] lg:self-start">
            <section id="voci" aria-labelledby="voci-h" className="scroll-mt-20 rounded-lg border border-line bg-surface p-5">
              <h2 id="voci-h" className="label-mono pb-3 text-fg-muted">{t("voicesTitle")}</h2>
              <VoicesMatrix voices={voices} weights={weights} pool={dossier.voices.length} />
            </section>
            {dossier.compass && (
              <section id="bussola" aria-labelledby="bussola-h" className="scroll-mt-20 rounded-lg border border-line bg-surface p-5">
                <h2 id="bussola-h" className="label-mono pb-3 text-fg-muted">{t("compassTitle")}</h2>
                <CompassAxis compass={dossier.compass} />
              </section>
            )}
          </aside>
        </div>

        <section id="detto-e-votato" aria-labelledby="sv-h" className="mt-16 flex scroll-mt-20 flex-col gap-6 border-t border-line pt-10">
          <div className="flex flex-col gap-2">
            <h2 id="sv-h" className="serif-display text-[2rem] leading-tight md:text-[2.5rem]">{t("svTitle")}</h2>
            <p className="max-w-prose text-[15px] text-fg-secondary">{t("svLead")}</p>
          </div>
          <SaidAndVoted
            topic={dossier.topic}
            acts={dossier.actNumbers}
            speechIds={(raw.topic_stats?.interventions_detail ?? []).map((i) => i.speech_id).filter(Boolean)}
            quotes={dossier.groups
              .filter((g) => g.quote && g.bloc !== "governo")
              .map((g) => ({ abbrev: g.abbrev, text: g.quote!.text, speaker: g.quote!.speaker }))}
          />
        </section>

        <aside className="mt-16 flex flex-col gap-4 rounded-lg bg-surface-inverse p-6 text-fg-inverse md:flex-row md:items-center md:p-8">
          <div className="flex flex-col gap-1.5">
            <p className="label-mono opacity-70">{t("ecoTitle")}</p>
            <p className="max-w-prose text-[15px] leading-relaxed">{t("ecoBody")}</p>
          </div>
          <a
            href="https://stenografo.it"
            className="inline-flex h-10 shrink-0 items-center gap-1.5 self-start rounded-full bg-fg-inverse px-4 text-sm font-medium text-surface-inverse transition-opacity hover:opacity-90 md:ml-auto md:self-center"
          >
            {t("ecoCta")}
            <ArrowUpRight className="size-4" aria-hidden />
          </a>
        </aside>
      </main>
      <div className="container-page pb-16">
        <NewsletterSignup source="dossier" variant="panel" />
      </div>
      <SiteFooter />
    </div>
  );
}
