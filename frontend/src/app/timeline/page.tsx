"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { useTranslations } from "next-intl";
import { Loader2, ArrowUp, ArrowUpRight, CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { FeedbackPulse } from "@/components/feedback/FeedbackPulse";
import { SessionCard } from "@/components/timeline/SessionCard";
import { TimelineSearch } from "@/components/timeline/TimelineSearch";
import { TimelineSkeleton } from "@/components/timeline/TimelineSkeleton";
import { useTimeline } from "@/hooks/use-timeline";

export default function TimelinePage() {
  const t = useTranslations("Timeline");
  const td = useTranslations("Dossier");
  const mainRef = useRef<HTMLElement | null>(null);
  const {
    sessions,
    isLoading,
    isFetchingMore,
    hasMore,
    error,
    filters,
    setFilters,
    loadMoreRef,
    resultCount,
    clearFilters,
    hasActiveFilters,
  } = useTimeline({ scrollContainerRef: mainRef });

  const totals = sessions.reduce(
    (acc, s) => ({
      debates: acc.debates + s.debate_count,
      votes: acc.votes + s.vote_count,
      speeches: acc.speeches + s.speech_count,
    }),
    { debates: 0, votes: 0, speeches: 0 },
  );

  // Back to top — tracks scroll on the main container, not window
  const [showBackToTop, setShowBackToTop] = useState(false);

  useEffect(() => {
    const el = mainRef.current;
    if (!el) return;
    const handleScroll = () => setShowBackToTop(el.scrollTop > 400);
    el.addEventListener("scroll", handleScroll, { passive: true });
    return () => el.removeEventListener("scroll", handleScroll);
  }, []);

  const scrollToTop = useCallback(() => {
    mainRef.current?.scrollTo({ top: 0, behavior: "smooth" });
  }, []);

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg pb-[env(safe-area-inset-bottom)]">
      <AppBar />

      {/* relative: l'aria-live sr-only in fondo alla lista è position:absolute:
          senza un antenato posizionato scappa dal clip di overflow-y e allunga
          il documento, rendendo scrollabile la pagina intera (banda bianca). */}
      <main ref={mainRef} className="relative flex-1 min-h-0 flex flex-col overflow-y-auto overscroll-contain">
        <div className="container-page flex flex-1 flex-col pt-8 pb-16 md:pt-12">
          <div className="max-w-3xl">
            <p className="label-mono text-fg-muted">{t("pageTitle")}</p>
            <h1 className="mt-2 serif-display text-3xl leading-tight text-fg sm:text-4xl">{t("actionTitle")}</h1>
            <p className="mt-3 text-[15px] leading-relaxed text-fg-secondary">{t("lead")}</p>
          </div>

          <div className="mt-8 grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="min-w-0">
              <TimelineSearch
                filters={filters}
                onFiltersChange={setFilters}
                onClear={clearFilters}
                hasActiveFilters={hasActiveFilters}
              />

              <div className="mt-6">
                {isLoading ? (
                  <TimelineSkeleton />
                ) : error ? (
                  <Alert variant="destructive">
                    <AlertTitle>{t("errorHeading")}</AlertTitle>
                    <AlertDescription>{t("errorBody")}</AlertDescription>
                  </Alert>
                ) : sessions.length === 0 ? (
                  <div className="flex flex-col items-center justify-center gap-4 rounded-lg border border-line bg-surface py-16 text-center">
                    <CalendarDays className="h-10 w-10 text-fg-faint" aria-hidden />
                    <h2 className="text-lg font-semibold text-fg">{t("noSessionsFound")}</h2>
                    <p className="text-sm text-fg-muted">{t("noSessionsBody")}</p>
                    <Button variant="outline" size="sm" onClick={clearFilters}>
                      {t("clearFilters")}
                    </Button>
                  </div>
                ) : (
                  <ol className="divide-y divide-line border-y border-line">
                    {sessions.map((session) => (
                      <li key={session.id}>
                        <SessionCard session={session} searchTerm={filters.search} />
                      </li>
                    ))}
                  </ol>
                )}

                <div ref={loadMoreRef} className="h-4" />

                {isFetchingMore && (
                  <div className="flex justify-center py-4">
                    <Loader2 className="mr-2 h-4 w-4 animate-spin text-fg-muted" aria-hidden />
                    <span className="text-sm text-fg-muted">{t("loadingMore")}</span>
                  </div>
                )}

                <div aria-live="polite" className="sr-only">
                  {isLoading
                    ? t("loadingMore")
                    : sessions.length > 0
                      ? `${resultCount} sessions`
                      : t("noSessionsFound")}
                </div>
              </div>
            </div>

            <aside className="flex flex-col gap-4 lg:sticky lg:top-6 lg:self-start">
              {sessions.length > 0 && (
                <section className="rounded-lg border border-line bg-surface p-5">
                  <h2 className="label-mono text-fg-muted">{t("railTitle")}</h2>
                  <dl className="mt-4 grid grid-cols-2 gap-x-4 gap-y-4">
                    {[
                      { n: sessions.length, label: t("railSittings", { count: sessions.length }) },
                      { n: totals.debates, label: t("debateCount", { count: totals.debates }) },
                      { n: totals.votes, label: t("voteCount", { count: totals.votes }) },
                      { n: totals.speeches, label: t("speechCount", { count: totals.speeches }) },
                    ].map((s) => (
                      <div key={s.label} className="flex flex-col">
                        <dt className="sr-only">{s.label}</dt>
                        <dd className="font-mono text-2xl font-medium tabular-nums text-fg">{s.n.toLocaleString()}</dd>
                        <dd className="text-xs text-fg-muted">{s.label.replace(/^[\d.,]+\s*/, "")}</dd>
                      </div>
                    ))}
                  </dl>
                  {hasMore && <p className="mt-4 text-xs leading-snug text-fg-muted">{t("railLoadedNote")}</p>}
                </section>
              )}
              <section className="hidden rounded-lg bg-surface-inverse p-5 text-fg-inverse lg:block">
                <p className="label-mono opacity-70">{td("ecoTitle")}</p>
                <p className="mt-2 text-sm leading-relaxed">{td("ecoBody")}</p>
                <a
                  href="https://stenografo.it"
                  className="mt-4 inline-flex h-9 items-center gap-1.5 rounded-full bg-fg-inverse px-3.5 text-sm font-medium text-surface-inverse hover:opacity-90"
                >
                  {td("ecoCta")}
                  <ArrowUpRight className="size-4" aria-hidden />
                </a>
              </section>
              <FeedbackPulse tool="timeline" className="hidden lg:block" />
            </aside>
          </div>
        </div>
        <SiteFooter />

        {/* Back to top button */}
        <Button
          variant="secondary"
          size="icon"
          className={`fixed bottom-4 right-4 z-20 transition-opacity duration-200 ${
            showBackToTop ? "opacity-100" : "opacity-0 pointer-events-none"
          }`}
          onClick={scrollToTop}
          aria-label={t("backToTop")}
        >
          <ArrowUp className="h-4 w-4" />
        </Button>
      </main>
    </div>
  );
}
