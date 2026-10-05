"use client";

import { useState, useCallback } from "react";
import { AppBar } from "@/components/shell/AppBar";
import { FeedbackPulse } from "@/components/feedback/FeedbackPulse";
import { useLocalHistory } from "@/hooks/use-local-history";
import { CompassCard } from "@/components/chat/CompassCard";
import type { CompassData } from "@/components/chat/CompassCard";
import { config } from "@/config";
import { getTopics } from "@/lib/constants";
import {
  Compass,
  Search,
  RotateCcw,
  Loader2,
  ArrowRight,
  AlertTriangle,
  History,
  Clock,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {useTranslations, useLocale } from "next-intl";

// ── Page ───────────────────────────────────────────────────────

export default function CompassPage() {
  const compassHistory = useLocalHistory<{ compassData: CompassData; computationTime: number }>(
    "parliamentrag-compass-history"
  );

  const [compassData, setCompassData] = useState<CompassData | null>(null);
  const [topic, setTopic] = useState("");
  const [activeTopic, setActiveTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [computationTime, setComputationTime] = useState(0);

  const t = useTranslations("CompassPage");
  const locale = useLocale();

  const fetchCompass = useCallback(async (topicText: string) => {
    if (!topicText.trim()) return;
    setLoading(true);
    setError("");
    setActiveTopic(topicText);

    try {
      const res = await fetch(`${config.api.baseUrl}/compass`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "Accept-Language": locale },
        body: JSON.stringify({ query: topicText }),
      });
      if (!res.ok) throw new Error(t("errorFetch"));
      const data = await res.json();
      const ct = data.computation_time_ms || 0;
      setCompassData(data);
      setComputationTime(ct);
      compassHistory.addEntry(topicText, { compassData: data, computationTime: ct });
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t("errorUnknown"));
      setCompassData(null);
    } finally {
      setLoading(false);
    }
  }, [locale, t]);

  const restoreCompassEntry = useCallback(
    (entry: { topic: string; data: { compassData: CompassData; computationTime: number } }) => {
      setActiveTopic(entry.topic);
      setTopic(entry.topic);
      setCompassData(entry.data.compassData);
      setComputationTime(entry.data.computationTime);
      setError("");
    },
    []
  );

  const handleTopicClick = (t: string) => {
    setTopic(t);
    fetchCompass(t);
  };

  const handleReset = () => {
    setCompassData(null);
    setActiveTopic("");
    setTopic("");
    setError("");
  };

  const hasResults = compassData !== null;
  const dimensionality = compassData?.meta?.dimensionality ?? 2;

  const historyAction = (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="size-10 shrink-0 rounded-full text-fg-secondary hover:text-fg" title={t("historyTitle")} aria-label={t("historyTitle")}>
          <History className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2" align="end">
        <p className="label-mono px-2 py-1 mb-1">{t("historyHeading")}</p>
        {compassHistory.entries.length === 0 ? (
          <p className="text-xs text-center py-4 text-fg-muted">{t("historyEmpty")}</p>
        ) : (
          <div className="space-y-0.5">
            {compassHistory.entries.map((entry) => (
              <div key={entry.id} className="flex items-center gap-1 group rounded-md hover:bg-surface-muted">
                <button
                  className="flex-1 flex items-center gap-2 px-2 py-1.5 text-left min-w-0"
                  onClick={() => restoreCompassEntry(entry)}
                >
                  <Clock className="h-3 w-3 shrink-0 text-fg-muted" />
                  <span className="text-xs font-medium text-fg truncate">{entry.topic}</span>
                </button>
                <button
                  className="shrink-0 p-1.5 opacity-0 group-hover:opacity-100 text-fg-muted hover:text-danger-fg transition-opacity"
                  onClick={() => compassHistory.removeEntry(entry.id)}
                  title={t("historyRemove")}
                >
                  <X className="h-3 w-3" />
                </button>
              </div>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
  );

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg pb-[env(safe-area-inset-bottom)]">
      <AppBar actions={historyAction} />

      <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {activeTopic && (loading || hasResults) && (
          <div className="container-page shrink-0 flex flex-wrap items-center gap-x-3 gap-y-2 pt-4 pb-3">
            <h1 className="label-mono text-fg-muted">{t("pageTitle")}</h1>
            <div className="flex items-center gap-2 ml-auto shrink-0">
              {hasResults && !loading && (
                <>
                  <span className="text-[11px] text-fg-muted hidden sm:inline">
                    {t("groupsCount", { count: compassData.groups.length })}
                    {computationTime > 0 && ` · ${(computationTime / 1000).toFixed(1)}s`}
                  </span>
                  <Badge variant="secondary" className="max-w-[180px] truncate text-xs">
                    {activeTopic}
                  </Badge>
                  {compassData.meta.warnings && compassData.meta.warnings.length > 0 && (
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <div className="flex h-7 w-7 items-center justify-center rounded-full bg-notice-soft text-notice-fg" aria-label={t("warningWeakAlignment")}>
                          <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
                        </div>
                      </TooltipTrigger>
                      <TooltipContent side="bottom" className="max-w-xs text-xs">
                        {compassData.meta.warnings.map((w, i) => (
                          <p key={i}>
                            {w.includes("WEAK_ALIGNMENT")
                              ? t("warningWeakAlignment")
                              : w}
                          </p>
                        ))}
                      </TooltipContent>
                    </Tooltip>
                  )}
                  <form
                    onSubmit={(e) => { e.preventDefault(); fetchCompass(topic); }}
                    className="hidden sm:flex items-center gap-1.5 ml-2"
                  >
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-muted" aria-hidden />
                      <Input
                        value={topic}
                        onChange={(e) => setTopic(e.target.value)}
                        placeholder={t("placeholderNew")}
                        className="h-8 w-44 text-xs pl-7 pr-2"
                      />
                    </div>
                    <Button type="submit" size="sm" disabled={!topic.trim()} className="h-8 px-3 text-xs gap-1">
                      {t("buttonAnalyze")}
                      <ArrowRight className="h-3 w-3" />
                    </Button>
                  </form>
                  <Button variant="ghost" size="sm" onClick={handleReset} className="h-8 text-xs gap-1 px-2.5">
                    <RotateCcw className="h-3 w-3" />
                    <span className="hidden sm:inline">Reset</span>
                  </Button>
                </>
              )}

              {activeTopic && loading && (
                <>
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-fg" aria-hidden />
                  <span className="text-xs text-fg-muted">{t("analyzingHeader")}</span>
                </>
              )}
            </div>
          </div>
        )}

        {/* Content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Empty state */}
          {!hasResults && !loading && (
            <div className="flex flex-col items-center justify-center h-full px-4 pb-16 overflow-y-auto">
              <div className="text-center space-y-5 max-w-lg">
                {/* Prompt-as-question + example placeholder (NN/g: the
                    placeholder shows the format, the question says the job) */}
                {/* Landing-hero register: the tool's distinctive phrase gets
                    the italic primary accent, the shared tail stays plain */}
                <h1 className="serif-display text-2xl sm:text-3xl text-fg leading-tight">
                  {t.rich("promptHeading", {
                    em: (chunks) => <span className="italic text-brand-fg">{chunks}</span>,
                  })}
                </h1>
                {/* Search bar */}
                <div className="w-full max-w-md mx-auto">
                  <form onSubmit={(e) => { e.preventDefault(); fetchCompass(topic); }} className="relative">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-fg-muted" aria-hidden />
                    <Input
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                      placeholder={t("placeholderSearch")}
                      className="h-14 text-lg pl-12 pr-28 rounded-xl"
                    />
                    <Button
                      type="submit"
                      disabled={!topic.trim()}
                      className="absolute right-2 top-1/2 -translate-y-1/2 h-10 px-4"
                    >
                      {t("buttonAnalyze")}
                    </Button>
                  </form>
                </div>

                {/* Topic chips */}
                <div className="pt-3">
                  <p className="label-mono mb-3">{t("suggestedTopicsLabel")}</p>
                  <div className="flex flex-wrap justify-center gap-2">
                    {getTopics(locale).slice(0, 8).map((t) => (
                      <button
                        key={t}
                        className="group inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-sm text-left text-fg-secondary transition-colors duration-200 hover:border-line-control hover:text-fg active:scale-[0.98] cursor-pointer"
                        onClick={() => handleTopicClick(t)}
                      >
                        <span>{t.charAt(0).toUpperCase() + t.slice(1)}</span>
                        <ArrowRight className="w-3 h-3 text-fg-faint transition-colors duration-200 group-hover:text-fg" aria-hidden />
                      </button>
                    ))}
                  </div>
                </div>

                {error && (
                  <div role="alert" className="mt-4 rounded-md bg-danger-soft px-4 py-3 text-sm text-danger-fg">
                    {error}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Loading */}
          {loading && (
            <div className="flex flex-col items-center justify-center h-full px-4 gap-6">
              <div className="relative">
                <div className="h-16 w-16 rounded-full border border-line flex items-center justify-center">
                  <Compass className="h-8 w-8 text-fg-faint motion-safe:animate-spin" style={{ animationDuration: "3s" }} aria-hidden />
                </div>
              </div>
              <div className="text-center space-y-2">
                <p className="text-sm font-medium text-fg">{t("loadingHeading")}</p>
                <p className="text-xs text-fg-muted">
                  {t("loadingSubtext", { topic: activeTopic })}
                </p>
              </div>
              {/* Skeleton compass */}
              <div className="w-full max-w-lg mx-auto">
                <div className="aspect-square max-w-[400px] mx-auto rounded-lg bg-surface-sunken animate-skeleton" />
                <div className="flex justify-center gap-4 mt-4">
                  {Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <div className="h-3 w-3 rounded-full bg-surface-sunken animate-skeleton" />
                      <div className="h-3 w-8 bg-surface-sunken rounded-xs animate-skeleton" />
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}

          {/* Results - full screen layout */}
          {hasResults && !loading && (
            <div className="flex-1 flex flex-col overflow-hidden animate-in fade-in duration-500">
              {/* Axis summary bar */}
              <div className="shrink-0 border-y border-line bg-surface-muted py-2.5">
                <div className="container-page flex flex-wrap items-center gap-x-6 gap-y-2">
                  {/* Axis 1 / PC1 */}
                  {compassData.axes.x && (compassData.axes.x.negative_side || compassData.axes.x.positive_side) && (
                    <AxisSummary
                      axisKey="x"
                      label={compassData.meta.axis_method === "pca" ? "PC1" : t("axis1Label")}
                      negLabel={compassData.axes.x.negative_side?.label}
                      posLabel={compassData.axes.x.positive_side?.label}
                      negKeywords={compassData.axes.x.negative_side?.keywords}
                      posKeywords={compassData.axes.x.positive_side?.keywords}
                    />
                  )}
                  {/* Axis 2 / PC2 */}
                  {dimensionality !== 1 && compassData.axes.y && (compassData.axes.y.negative_side || compassData.axes.y.positive_side) && (
                    <>
                      <div className="hidden sm:block w-px h-5 bg-line" />
                      <AxisSummary
                        axisKey="y"
                        label={compassData.meta.axis_method === "pca" ? "PC2" : t("axis2Label")}
                        negLabel={compassData.axes.y.negative_side?.label}
                        posLabel={compassData.axes.y.positive_side?.label}
                        negKeywords={compassData.axes.y.negative_side?.keywords}
                        posKeywords={compassData.axes.y.positive_side?.keywords}
                      />
                    </>
                  )}
                  {/* Method badge */}
                  <Badge variant="outline" className="text-[10px] ml-auto hidden sm:inline-flex">
                    {dimensionality === 1
                      ? "1D Spectrum"
                      : compassData.meta.axis_method === "pca"
                        ? "2D PCA"
                        : t("anchoredBadge")}
                  </Badge>

                  {/* Micro-feedback inline nella barra assi (issue #21) */}
                  <FeedbackPulse tool="compass" context={activeTopic} className="mt-0 pt-0 border-t-0 hidden lg:block" />
                </div>
              </div>

              {/* Compass visualization - fills remaining space */}
              <div className="container-page flex-1 min-h-0 py-3 sm:py-4">
                <div className="h-full w-full">
                  <CompassCard data={compassData} fill />
                </div>
              </div>

              {/* Mobile search bar */}
              <div className="sm:hidden shrink-0 border-t border-line px-4 py-2">
                <form
                  onSubmit={(e) => { e.preventDefault(); fetchCompass(topic); }}
                  className="flex items-center gap-2"
                >
                  <Input
                    value={topic}
                    onChange={(e) => setTopic(e.target.value)}
                    placeholder={t("placeholderNew")}
                    className="h-8 text-xs flex-1"
                  />
                  <Button type="submit" size="sm" disabled={!topic.trim()} className="h-8 px-3 text-xs">
                    <ArrowRight className="h-3 w-3" />
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleReset} className="h-8 px-2">
                    <RotateCcw className="h-3 w-3" />
                  </Button>
                </form>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

function AxisSummary({ axisKey, label, negLabel, posLabel, negKeywords, posKeywords }: {
  axisKey: "x" | "y";
  label: string;
  negLabel?: string;
  posLabel?: string;
  negKeywords?: string[];
  posKeywords?: string[];
}) {
  const t = useTranslations("CompassPage");
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="font-mono text-caption font-medium text-fg" title={axisKey === "x" ? t("axisX") : t("axisY")}>{label}</span>
      <div className="flex items-center gap-1.5 min-w-0">
        {negLabel && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-[11px] text-fg-secondary cursor-help border-b border-dotted border-line-control truncate max-w-[280px]">
                {negLabel}
              </span>
            </TooltipTrigger>
            {negKeywords && negKeywords.length > 0 && (
              <TooltipContent side="bottom" className="text-xs max-w-xs">
                <p className="font-medium mb-1">{t("keywordsNeg")}</p>
                <p>{negKeywords.slice(0, 6).join(" · ")}</p>
              </TooltipContent>
            )}
          </Tooltip>
        )}
        <span className="text-fg-faint" aria-hidden>↔</span>
        {posLabel && (
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-[11px] text-fg-secondary cursor-help border-b border-dotted border-line-control truncate max-w-[280px]">
                {posLabel}
              </span>
            </TooltipTrigger>
            {posKeywords && posKeywords.length > 0 && (
              <TooltipContent side="bottom" className="text-xs max-w-xs">
                <p className="font-medium mb-1">{t("keywordsPos")}</p>
                <p>{posKeywords.slice(0, 6).join(" · ")}</p>
              </TooltipContent>
            )}
          </Tooltip>
        )}
      </div>
    </div>
  );
}
