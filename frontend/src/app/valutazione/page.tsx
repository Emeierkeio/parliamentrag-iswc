"use client";

import { useState, useEffect, useCallback } from "react";
import { AppBar } from "@/components/shell/AppBar";
import { SurveyModal } from "@/components/survey/SurveyModal";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  HorizontalBarChart,
  MetricCard,
  MiniMetricBars,
  ABComparisonChart,
  WinRateChart,
} from "@/components/evaluation/EvaluationCharts";
import { getDashboardData, getExportCsvUrl } from "@/lib/evaluation-api";
import type { EvaluationDashboardData, CombinedEvaluation } from "@/types/evaluation";
import { AB_DIMENSIONS, SIMPLE_DIMENSION_LABELS } from "@/types/survey";
import type { ABRating, SimpleDimension } from "@/types/survey";
import {
  BarChart3,
  Users,
  Quote,
  Award,
  FileText,
  Download,
  ClipboardCheck,
  Loader2,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  ThumbsUp,
  Target,
  Trophy,
  BarChart2,
  UserCheck,
} from "lucide-react";
import { cn } from "@/lib/utils";

const DIMENSION_LABELS: Record<string, string> = {
  answer_quality: "Qualità risposta",
  answer_clarity: "Chiarezza",
  answer_completeness: "Completezza",
  citations_relevance: "Pertinenza citazioni",
  balance_perception: "Bilanciamento percepito",
  balance_fairness: "Equità",
};

export default function ValutazionePage() {
  const [data, setData] = useState<EvaluationDashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [surveyModalOpen, setSurveyModalOpen] = useState(false);
  // null = not yet determined, undefined = no evaluator, string = evaluator present
  const [evaluatorId, setEvaluatorId] = useState<string | null | undefined>(null);

  // Read ?evaluator= from URL and auto-open the modal
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const evaluator = params.get("evaluator");
    if (evaluator) {
      setEvaluatorId(evaluator);
      setSurveyModalOpen(true);
    } else {
      setEvaluatorId(undefined);
    }
  }, []);

  const loadData = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const result = await getDashboardData();
      setData(result);
    } catch (err) {
      setError("Errore nel caricamento dei dati di valutazione");
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Skip dashboard data loading in evaluator-only mode
  useEffect(() => {
    if (evaluatorId === undefined) {
      loadData();
    }
  }, [loadData, evaluatorId]);

  const handleExportCsv = () => {
    window.open(getExportCsvUrl(), "_blank");
  };

  // Not yet determined — avoid flash of dashboard
  if (evaluatorId === null) return null;

  // Evaluator-only mode: show just the survey modal, no dashboard
  if (evaluatorId) {
    return (
      <div className="h-dvh bg-stage">
        <SurveyModal
          isOpen={true}
          onClose={() => window.location.reload()}
          evaluatorId={evaluatorId}
          fullScreen
        />
      </div>
    );
  }

  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-background pb-[env(safe-area-inset-bottom)]">
      <AppBar />

      <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
        <div className="container-page shrink-0 pt-6 pb-2">
          <div className="flex items-center gap-3">
            <h1 className="serif-display text-2xl sm:text-3xl text-fg whitespace-nowrap">Valutazione</h1>
            <div className="flex gap-1.5 md:gap-2 ml-auto shrink-0">
              <Button
                variant="outline"
                size="sm"
                onClick={loadData}
                disabled={isLoading}
                className="h-8 px-2 md:px-3"
              >
                <RefreshCw className={cn("w-4 h-4", isLoading && "animate-spin")} />
                <span className="hidden md:inline ml-1">Aggiorna</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleExportCsv}
                disabled={!data || data.total_chats === 0}
                className="h-8 px-2 md:px-3 hidden sm:flex"
              >
                <Download className="w-4 h-4" />
                <span className="hidden md:inline ml-1">Esporta CSV</span>
              </Button>
            </div>
          </div>
        </div>

        {/* Content */}
        {isLoading ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-10 h-10 animate-spin text-brand" />
              <p className="text-muted-foreground">Caricamento dati di valutazione...</p>
            </div>
          </div>
        ) : error ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-danger-fg">
              <AlertCircle className="w-10 h-10" />
              <p>{error}</p>
              <Button variant="outline" onClick={loadData}>
                Riprova
              </Button>
            </div>
          </div>
        ) : data && data.total_chats === 0 ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3 text-fg-muted">
              <BarChart3 className="w-12 h-12 opacity-30" />
              <p className="text-lg font-medium">Nessuna conversazione disponibile</p>
              <p className="text-sm">Inizia ad usare il sistema per generare dati di valutazione.</p>
            </div>
          </div>
        ) : data ? (
          <Tabs
            value={activeTab}
            onValueChange={setActiveTab}
            className="flex-1 flex flex-col min-h-0"
          >
            <div className="container-page shrink-0 mt-4">
            <TabsList className="grid w-full grid-cols-4 h-10">
              <TabsTrigger value="overview" className="text-xs md:text-sm gap-1 md:gap-1.5">
                <BarChart3 className="w-4 h-4" />
                <span className="hidden sm:inline">Panoramica</span>
              </TabsTrigger>
              <TabsTrigger value="automated" className="text-xs md:text-sm gap-1 md:gap-1.5">
                <Target className="w-4 h-4" />
                <span className="hidden sm:inline">Metriche</span>
              </TabsTrigger>
              <TabsTrigger value="human" className="text-xs md:text-sm gap-1 md:gap-1.5">
                <Users className="w-4 h-4" />
                <span className="hidden sm:inline">A/B</span>
              </TabsTrigger>
              <TabsTrigger value="details" className="text-xs md:text-sm gap-1 md:gap-1.5">
                <FileText className="w-4 h-4" />
                <span className="hidden sm:inline">Dettaglio</span>
              </TabsTrigger>
            </TabsList>
            </div>

            <div className="flex-1 overflow-y-auto py-4 md:py-6">
              <div className="container-page">
              <TabsContent value="overview" className="mt-0">
                <OverviewTab data={data} />
              </TabsContent>
              <TabsContent value="automated" className="mt-0">
                <AutomatedTab data={data} />
              </TabsContent>
              <TabsContent value="human" className="mt-0">
                <HumanTab data={data} />
              </TabsContent>
              <TabsContent value="details" className="mt-0">
                <DetailsTab data={data} />
              </TabsContent>
              </div>
            </div>
          </Tabs>
        ) : null}
      </main>

      <SurveyModal
        isOpen={surveyModalOpen}
        onClose={() => {
          setSurveyModalOpen(false);
          loadData();
        }}
        evaluatorId={evaluatorId ?? undefined}
      />
    </div>
  );
}

/* ─── Overview Tab ─── */

function OverviewTab({ data }: { data: EvaluationDashboardData }) {
  const agg = data.automated_aggregate;
  const ab = data.ab_comparison;
  const human = data.human_aggregate;

  return (
    <div className="max-w-6xl mx-auto space-y-8">
      {/* Summary stats */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3 md:gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-semibold tabular text-fg">
              {data.total_chats}
            </div>
            <div className="text-sm text-muted-foreground">Conversazioni totali</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-semibold tabular text-fg">
              {data.total_evaluated}
            </div>
            <div className="text-sm text-muted-foreground">Valutate (A/B blind)</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-semibold tabular text-fg">
              {data.total_simple_rated}
            </div>
            <div className="text-sm text-muted-foreground">Valutate (Likert)</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-semibold tabular text-fg">
              {ab ? `${(ab.system_win_rate * 100).toFixed(0)}%` : "—"}
            </div>
            <div className="text-sm text-muted-foreground">Win rate sistema</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <div className="text-3xl font-semibold tabular text-fg">
              {human ? `${human.recommendation_rate.toFixed(0)}%` : "—"}
            </div>
            <div className="text-sm text-muted-foreground">Tasso raccomandazione</div>
          </CardContent>
        </Card>
      </div>

      {/* Automated metrics cards */}
      <div>
        <h2 className="text-lg font-semibold text-fg mb-4">
          Metriche Automatiche
        </h2>
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3 md:gap-4">
          <MetricCard
            label="Gruppi con Citazione"
            value={agg.avg_party_coverage}
            ci={agg.ci_party_coverage}
            icon={<Users className="w-4 h-4" />}
            description="Gruppi parlamentari con almeno una citazione verificabile su 10 totali"
            baselineValue={agg.avg_baseline_party_coverage ?? undefined}
            baselineCi={agg.ci_baseline_party_coverage ?? undefined}
          />
          <MetricCard
            label="Fedeltà Citazioni"
            value={agg.avg_verbatim_match}
            ci={agg.ci_verbatim_match}
            icon={<Quote className="w-4 h-4" />}
            description="Citazioni verificate verbatim sul testo sorgente"
            baselineValue={agg.avg_baseline_citation_fidelity ?? undefined}
            baselineCi={agg.ci_baseline_citation_fidelity ?? undefined}
          />
          <MetricCard
            label="Autorevolezza (media)"
            value={agg.avg_authority_utilization}
            ci={agg.ci_authority_utilization}
            icon={<Award className="w-4 h-4" />}
            description="Score medio degli esperti citati"
            baselineValue={agg.avg_baseline_authority ?? undefined}
            baselineCi={agg.ci_baseline_authority ?? undefined}
          />
          <MetricCard
            label="Autorevolezza (dev. std)"
            value={agg.avg_authority_discrimination}
            ci={agg.ci_authority_discrimination}
            icon={<BarChart2 className="w-4 h-4" />}
            description="Deviazione standard media dei punteggi tra deputati (per tema)"
            isNeutral
          />
          <MetricCard
            label="Completezza"
            value={agg.avg_response_completeness}
            ci={agg.ci_response_completeness}
            icon={<FileText className="w-4 h-4" />}
            description="Gruppi menzionati nel testo della risposta"
            baselineValue={agg.avg_baseline_response_completeness ?? undefined}
            baselineCi={agg.ci_baseline_response_completeness ?? undefined}
          />
        </div>
      </div>

      {/* A/B Win Rate */}
      {ab && ab.total_evaluations > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Trophy className="w-5 h-5 text-fg-muted" />
              Preferenza Complessiva: Valutazione Blind A/B
            </CardTitle>
          </CardHeader>
          <CardContent>
            <WinRateChart
              systemWinRate={ab.system_win_rate}
              baselineWinRate={ab.baseline_win_rate}
              tieRate={ab.tie_rate}
              totalEvaluations={ab.total_evaluations}
            />
          </CardContent>
        </Card>
      )}

      {/* A/B Comparison per dimension */}
      {ab && ab.total_evaluations > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">
              ParliamentRAG vs Baseline RAG: Punteggi Medi per Dimensione
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ABComparisonChart
              items={AB_DIMENSIONS.map((dim) => ({
                label: DIMENSION_LABELS[dim] || dim,
                systemValue: ab.system_avg_ratings[dim] || 0,
                baselineValue: ab.baseline_avg_ratings[dim] || 0,
              }))}
            />
          </CardContent>
        </Card>
      )}

      {/* Overall satisfaction comparison */}
      {ab && ab.total_evaluations > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card>
            <CardContent className="p-6 text-center">
              <div className="text-sm text-muted-foreground mb-2">Soddisfazione Media Sistema</div>
              <div className="text-4xl font-semibold tabular text-brand-fg">
                {ab.system_avg_overall.toFixed(2)}
              </div>
              <div className="text-sm text-muted-foreground">/5</div>
            </CardContent>
          </Card>
          <Card>
            <CardContent className="p-6 text-center">
              <div className="text-sm text-muted-foreground mb-2">Soddisfazione Media Baseline</div>
              <div className="text-4xl font-semibold tabular text-notice-fg">
                {ab.baseline_avg_overall.toFixed(2)}
              </div>
              <div className="text-sm text-muted-foreground">/5</div>
            </CardContent>
          </Card>
        </div>
      )}

      {!ab && (
        <Card>
          <CardContent className="p-8 text-center text-fg-muted">
            <Users className="w-12 h-12 opacity-30 mx-auto mb-3" />
            <p className="text-lg font-medium">Nessuna valutazione A/B disponibile</p>
            <p className="text-sm mt-1">
              Esegui query con baseline e usa &quot;Nuova Valutazione&quot; per confrontare le risposte.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

/* ─── Automated Tab ─── */

function AutomatedTab({ data }: { data: EvaluationDashboardData }) {
  const agg = data.automated_aggregate;

  const metrics: Array<{
    label: string;
    value: number;
    ci: [number, number];
    description: string;
    format: "percent" | "decimal";
    baselineValue: number | undefined;
    baselineCi: [number, number] | undefined;
  }> = [
    {
      label: "Gruppi con Citazione",
      value: agg.avg_party_coverage,
      ci: agg.ci_party_coverage,
      description:
        "Percentuale di gruppi parlamentari con almeno una citazione verificabile nella risposta (target: 100%)",
      format: "percent" as const,
      baselineValue: agg.avg_baseline_party_coverage ?? undefined,
      baselineCi: agg.ci_baseline_party_coverage ?? undefined,
    },
    {
      label: "Fedeltà Citazioni (Citation Fidelity)",
      value: agg.avg_verbatim_match,
      ci: agg.ci_verbatim_match,
      description:
        "Percentuale di citazioni verificate verbatim sul testo sorgente",
      format: "percent" as const,
      baselineValue: agg.avg_baseline_citation_fidelity ?? undefined,
      baselineCi: agg.ci_baseline_citation_fidelity ?? undefined,
    },
    {
      label: "Autorevolezza (Authority Utilization)",
      value: agg.avg_authority_utilization,
      ci: agg.ci_authority_utilization,
      description:
        "Media del punteggio di autorevolezza degli esperti citati",
      format: "percent" as const,
      baselineValue: agg.avg_baseline_authority ?? undefined,
      baselineCi: agg.ci_baseline_authority ?? undefined,
    },
    {
      label: "Discriminazione Autorevolezza (Authority Discrimination)",
      value: agg.avg_authority_discrimination,
      ci: agg.ci_authority_discrimination,
      description:
        "Deviazione standard dei punteggi di autorevolezza (valori alti = maggiore selettivita)",
      format: "decimal" as const,
      baselineValue: undefined,
      baselineCi: undefined,
    },
    {
      label: "Completezza Risposta (Response Completeness)",
      value: agg.avg_response_completeness,
      ci: agg.ci_response_completeness,
      description:
        "Percentuale di sezioni per-partito presenti nella risposta",
      format: "percent" as const,
      baselineValue: agg.avg_baseline_response_completeness ?? undefined,
      baselineCi: agg.ci_baseline_response_completeness ?? undefined,
    },
  ];

  // Metrics that can be compared to baseline
  const comparableMetrics = metrics.filter(m => m.baselineValue != null);

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div>
        <h2 className="text-lg font-semibold text-fg">
          Metriche Automatiche
        </h2>
        <p className="text-sm text-muted-foreground">
          Calcolate da {agg.total_chats} conversazioni
        </p>
      </div>

      {/* Sistema-only bar chart */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm text-muted-foreground font-medium">ParliamentRAG: tutte le metriche</CardTitle>
        </CardHeader>
        <CardContent className="p-6 pt-0">
          <HorizontalBarChart
            items={metrics
              .filter((m) => m.format === "percent")
              .map((m) => ({
                label: m.label,
                value: m.value,
                ci: m.ci,
              }))}
          />
        </CardContent>
      </Card>

      {/* Sistema vs Baseline comparison for metrics that have baseline data */}
      {comparableMetrics.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Award className="w-4 h-4 text-fg-muted" />
              ParliamentRAG vs Baseline: Metriche Confrontabili
            </CardTitle>
          </CardHeader>
          <CardContent className="p-6 pt-0">
            <ABComparisonChart
              items={comparableMetrics
                .filter(m => m.format === "percent")
                .map(m => ({
                  label: m.label,
                  systemValue: m.value,
                  baselineValue: m.baselineValue ?? 0,
                }))}
              maxValue={1}
            />
            <p className="text-xs text-muted-foreground mt-3">
              * Autorevolezza baseline calcolata dagli esperti estratti dal testo della risposta baseline durante le valutazioni A/B.
              Completezza baseline calcolata dal numero di partiti menzionati nel testo della risposta baseline.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Detailed cards */}
      <div className="space-y-4">
        {metrics.map((m) => (
          <Card key={m.label}>
            <CardContent className="p-4">
              <div className="flex items-start justify-between gap-4 mb-2">
                <div className="flex-1">
                  <p className="font-medium text-fg">
                    {m.label}
                  </p>
                  <p className="text-sm text-muted-foreground mt-1">
                    {m.description}
                  </p>
                </div>
                <div className="text-right shrink-0">
                  <div className="text-xl font-bold font-mono">
                    {m.format === "decimal"
                      ? m.value.toFixed(3)
                      : `${(m.value * 100).toFixed(1)}%`}
                  </div>
                  {m.baselineValue != null && (
                    <div className="text-xs text-notice-fg font-mono">
                      Baseline: {m.format === "decimal"
                        ? m.baselineValue.toFixed(3)
                        : `${(m.baselineValue * 100).toFixed(1)}%`}
                      <span className={cn(
                        "ml-1 font-semibold",
                        m.value - m.baselineValue > 0.005 ? "text-brand-fg" :
                        m.value - m.baselineValue < -0.005 ? "text-fg-secondary" : "text-fg-muted"
                      )}>
                        {m.value - m.baselineValue > 0.005 ? "▲" : m.value - m.baselineValue < -0.005 ? "▼" : "≈"}
                        {m.format === "percent"
                          ? ` ${(m.value - m.baselineValue) >= 0 ? "+" : ""}${((m.value - m.baselineValue) * 100).toFixed(1)}pp`
                          : ` ${(m.value - m.baselineValue) >= 0 ? "+" : ""}${(m.value - m.baselineValue).toFixed(3)}`}
                      </span>
                    </div>
                  )}
                  <div className="text-xs text-muted-foreground">
                    {m.format === "decimal"
                      ? `IC 95%: [${m.ci[0].toFixed(3)}, ${m.ci[1].toFixed(3)}]`
                      : `IC 95%: [${(m.ci[0] * 100).toFixed(1)}%, ${(m.ci[1] * 100).toFixed(1)}%]`}
                  </div>
                </div>
              </div>
              {m.format === "percent" && (
                <div className="space-y-1 mt-2">
                  <div className="flex items-center gap-2">
                    <span className="text-xs text-brand-fg w-16 shrink-0">Sistema</span>
                    <div className="flex-1 h-2 bg-surface-muted rounded-full overflow-hidden">
                      <div
                        className={cn("h-full rounded-full", m.value >= 0.8 ? "bg-brand" : m.value >= 0.6 ? "bg-brand/65" : "bg-brand/35")}
                        style={{ width: `${Math.min(m.value * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                  {m.baselineValue != null && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-notice-fg w-16 shrink-0">Baseline</span>
                      <div className="flex-1 h-2 bg-surface-muted rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full bg-chart-3"
                          style={{ width: `${Math.min(m.baselineValue * 100, 100)}%` }}
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

/* ─── Human Tab (A/B Comparison) ─── */

function HumanTab({ data }: { data: EvaluationDashboardData }) {
  const ab = data.ab_comparison;
  const human = data.human_aggregate;

  if (!ab || ab.total_evaluations === 0) {
    return (
      <div className="max-w-4xl mx-auto">
        <div className="flex flex-col items-center justify-center h-60 text-fg-muted">
          <Users className="w-12 h-12 opacity-30 mb-3" />
          <p className="text-lg font-medium">
            Nessuna valutazione A/B disponibile
          </p>
          <p className="text-sm mt-1">
            Usa il bottone &quot;Nuova Valutazione&quot; per iniziare.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="max-w-4xl mx-auto space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-fg">
            Confronto A/B Cieco
          </h2>
          <p className="text-sm text-muted-foreground">
            {ab.total_evaluations} valutazioni blind, risultati de-blindati
          </p>
        </div>
        {human && (
          <Badge
            variant="outline"
            className={cn(
              "text-sm px-3 py-1",
              human.recommendation_rate >= 70
                ? "border-brand/40 text-brand-fg"
                : "border-line-strong text-fg-secondary"
            )}
          >
            <ThumbsUp className="w-4 h-4 mr-1" />
            {human.recommendation_rate.toFixed(0)}% raccomanderebbe
          </Badge>
        )}
      </div>

      {/* Win rate */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <Trophy className="w-5 h-5 text-fg-muted" />
            Preferenza Complessiva
          </CardTitle>
        </CardHeader>
        <CardContent>
          <WinRateChart
            systemWinRate={ab.system_win_rate}
            baselineWinRate={ab.baseline_win_rate}
            tieRate={ab.tie_rate}
            totalEvaluations={ab.total_evaluations}
          />
        </CardContent>
      </Card>

      {/* Per-dimension comparison */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Punteggi Medi per Dimensione (1-5)</CardTitle>
        </CardHeader>
        <CardContent>
          <ABComparisonChart
            items={AB_DIMENSIONS.map((dim) => ({
              label: DIMENSION_LABELS[dim] || dim,
              systemValue: ab.system_avg_ratings[dim] || 0,
              baselineValue: ab.baseline_avg_ratings[dim] || 0,
            }))}
          />
        </CardContent>
      </Card>

      {/* Per-dimension preference breakdown */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Preferenza per Dimensione</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          {AB_DIMENSIONS.map((dim) => {
            const prefs = ab.per_dimension_preference[dim];
            if (!prefs) return null;
            const total = (prefs.system || 0) + (prefs.baseline || 0) + (prefs.equal || 0);
            if (total === 0) return null;
            const sysPct = ((prefs.system || 0) / total) * 100;
            const basePct = ((prefs.baseline || 0) / total) * 100;
            const tiePct = ((prefs.equal || 0) / total) * 100;
            return (
              <div key={dim} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="text-fg-secondary font-medium">
                    {DIMENSION_LABELS[dim] || dim}
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {prefs.system || 0}S / {prefs.equal || 0}= / {prefs.baseline || 0}B
                  </span>
                </div>
                <div className="flex items-center h-6 rounded-full overflow-hidden bg-surface-muted">
                  {sysPct > 0 && (
                    <div
                      className="h-full bg-chart-1"
                      style={{ width: `${sysPct}%` }}
                    />
                  )}
                  {tiePct > 0 && (
                    <div
                      className="h-full bg-line-strong"
                      style={{ width: `${tiePct}%` }}
                    />
                  )}
                  {basePct > 0 && (
                    <div
                      className="h-full bg-chart-3"
                      style={{ width: `${basePct}%` }}
                    />
                  )}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      {/* Per-group authority preference */}
      {ab.group_authority_preference && Object.keys(ab.group_authority_preference).length > 0 && (() => {
        const GROUP_LABELS: Record<string, string> = {
          "FRATELLI D'ITALIA": "Fratelli d'Italia",
          "LEGA - SALVINI PREMIER": "Lega",
          "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE": "Forza Italia",
          "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC, ITALIA AL CENTRO)-MAIE": "Noi Moderati",
          "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA": "Partito Democratico",
          "MOVIMENTO 5 STELLE": "Movimento 5 Stelle",
          "ALLEANZA VERDI E SINISTRA": "All. Verdi e Sinistra",
          "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE": "Azione",
          "ITALIA VIVA-CASA RIFORMISTA (IV-CR)": "Italia Viva",
          "ITALIA VIVA-IL CENTRO-RENEW EUROPE": "Italia Viva",
          "MISTO": "Gruppo Misto",
        };
        const entries = Object.entries(ab.group_authority_preference!)
          .map(([key, counts]) => {
            const sys = counts.system || 0;
            const eq = counts.equal || 0;
            const bas = counts.baseline || 0;
            const total = sys + eq + bas;
            return { key, sys, eq, bas, total };
          })
          .filter(e => e.total > 0)
          .sort((a, b) => (b.sys / b.total) - (a.sys / a.total));

        return (
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <UserCheck className="w-5 h-5 text-fg-muted" />
                Autorità Esperti per Gruppo Politico
              </CardTitle>
              <p className="text-sm text-muted-foreground mt-0.5">
                Quale risposta ha citato l'esperto più autorevole, per gruppo?
              </p>
            </CardHeader>
            <CardContent className="space-y-3">
              {entries.map(({ key, sys, eq, bas, total }) => {
                const sysPct = (sys / total) * 100;
                const eqPct = (eq / total) * 100;
                const basPct = (bas / total) * 100;
                const label = GROUP_LABELS[key] || key;
                return (
                  <div key={key} className="space-y-1">
                    <div className="flex items-center justify-between text-sm">
                      <span className="text-fg-secondary font-medium">{label}</span>
                      <span className="text-xs text-muted-foreground">
                        {sys}S / {eq}= / {bas}B
                      </span>
                    </div>
                    <div className="flex items-center h-6 rounded-full overflow-hidden bg-surface-muted">
                      {sysPct > 0 && (
                        <div className="h-full bg-chart-1" style={{ width: `${sysPct}%` }} />
                      )}
                      {eqPct > 0 && (
                        <div className="h-full bg-line-strong" style={{ width: `${eqPct}%` }} />
                      )}
                      {basPct > 0 && (
                        <div className="h-full bg-chart-3" style={{ width: `${basPct}%` }} />
                      )}
                    </div>
                  </div>
                );
              })}
            </CardContent>
          </Card>
        );
      })()}

      {/* Overall satisfaction comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardContent className="p-6 text-center">
            <div className="text-sm text-muted-foreground mb-2">Soddisfazione Media Sistema</div>
            <div className="text-4xl font-semibold tabular text-brand-fg">
              {ab.system_avg_overall.toFixed(2)}
            </div>
            <div className="text-sm text-muted-foreground">/5</div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 text-center">
            <div className="text-sm text-muted-foreground mb-2">Soddisfazione Media Baseline</div>
            <div className="text-4xl font-semibold tabular text-notice-fg">
              {ab.baseline_avg_overall.toFixed(2)}
            </div>
            <div className="text-sm text-muted-foreground">/5</div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/* ─── Details Tab ─── */

function DetailsTab({ data }: { data: EvaluationDashboardData }) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const avgBaselineAuthority = data.automated_aggregate.avg_baseline_authority ?? undefined;
  const avgBaselineAuthorityByGroup = data.automated_aggregate.avg_baseline_authority_by_group ?? undefined;

  return (
    <div className="max-w-5xl mx-auto space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-fg">
          Dettaglio per Conversazione
        </h2>
        <p className="text-sm text-muted-foreground">
          {data.per_chat.length} conversazioni analizzate
        </p>
      </div>

      <div className="space-y-3">
        {data.per_chat.map((item) => (
          <ChatEvaluationRow
            key={item.chat_id}
            item={item}
            avgBaselineAuthority={avgBaselineAuthority}
            avgBaselineAuthorityByGroup={avgBaselineAuthorityByGroup}
            isExpanded={expandedId === item.chat_id}
            onToggle={() =>
              setExpandedId(
                expandedId === item.chat_id ? null : item.chat_id
              )
            }
          />
        ))}
      </div>
    </div>
  );
}

const PARTY_SHORT_NAMES: Record<string, string> = {
  "Fratelli d'Italia": "FdI",
  "Lega - Salvini Premier": "Lega",
  "Forza Italia - Berlusconi Presidente - PPE": "Forza Italia",
  "Noi Moderati (Noi con l'Italia, Coraggio Italia, UDC e Italia al Centro) - MAIE - Centro Popolare": "Noi Moderati",
  "Partito Democratico - Italia Democratica e Progressista": "PD",
  "Movimento 5 Stelle": "M5S",
  "Alleanza Verdi e Sinistra": "AVS",
  "Azione - Popolari Europeisti Riformatori - Renew Europe": "Azione",
  "Italia Viva - Casa Riformista": "Italia Viva",
  "Italia Viva - Il Centro - Renew Europe": "Italia Viva",
  "Misto": "Misto",
};

function shortParty(name: string): string {
  return PARTY_SHORT_NAMES[name] ?? name.split(" - ")[0].split(" (")[0];
}

function AuthorityByGroupChart({
  systemByGroup,
  baselineByGroup,
  isAggregateBaseline,
}: {
  systemByGroup: Record<string, number>;
  baselineByGroup?: Record<string, number>;
  isAggregateBaseline?: boolean;
}) {
  const hasBaseline = baselineByGroup && Object.keys(baselineByGroup).length > 0;

  // Merge all parties
  const allParties = Array.from(
    new Set([...Object.keys(systemByGroup), ...(hasBaseline ? Object.keys(baselineByGroup!) : [])])
  ).sort((a, b) => (systemByGroup[b] ?? 0) - (systemByGroup[a] ?? 0));

  if (allParties.length === 0) return null;

  const maxVal = Math.max(
    ...Object.values(systemByGroup),
    ...(hasBaseline ? Object.values(baselineByGroup!) : []),
    0.01
  );

  return (
    <div className="mt-4">
      <div className="flex items-center justify-between mb-2">
        <h5 className="label-mono">
          Autorevolezza per gruppo ({Object.keys(systemByGroup).length} gruppi)
        </h5>
        {hasBaseline && (
          <div className="flex items-center gap-3 text-xs text-muted-foreground">
            <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-xs bg-chart-1" />Sistema</span>
            <span className="flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded-xs bg-line-strong" />
              Baseline{isAggregateBaseline ? " (media)" : ""}
            </span>
          </div>
        )}
      </div>
      <div className="space-y-1.5">
        {allParties.map((party) => {
          const sysVal = systemByGroup[party] ?? 0;
          const basVal = hasBaseline ? (baselineByGroup![party] ?? 0) : undefined;
          const sysPct = (sysVal / maxVal) * 100;
          const basPct = basVal !== undefined ? (basVal / maxVal) * 100 : undefined;
          return (
            <div key={party} className="flex items-center gap-2 text-xs">
              <span className="w-20 shrink-0 text-fg-secondary truncate" title={party}>
                {shortParty(party)}
              </span>
              <div className="flex-1 space-y-0.5">
                {/* System bar */}
                <div className="flex items-center gap-1.5">
                  <div className="flex-1 h-2 bg-surface-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-chart-1 rounded-full transition-all"
                      style={{ width: `${sysPct}%` }}
                    />
                  </div>
                  <span className="font-mono w-9 text-right text-fg-secondary">
                    {Math.round(sysVal * 100)}%
                  </span>
                </div>
                {/* Baseline bar */}
                {basPct !== undefined && basVal !== undefined && (
                  <div className="flex items-center gap-1.5">
                    <div className="flex-1 h-2 bg-surface-muted rounded-full overflow-hidden">
                      <div
                        className="h-full bg-line-strong rounded-full transition-all"
                        style={{ width: `${basPct}%` }}
                      />
                    </div>
                    <span className="font-mono w-9 text-right text-muted-foreground">
                      {Math.round(basVal * 100)}%
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ChatEvaluationRow({
  item,
  avgBaselineAuthority,
  avgBaselineAuthorityByGroup,
  isExpanded,
  onToggle,
}: {
  item: CombinedEvaluation;
  avgBaselineAuthority?: number;
  avgBaselineAuthorityByGroup?: Record<string, number>;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const m = item.automated;
  // Per-chat baseline takes priority; fall back to aggregate baseline
  const effectiveBaseline = m.baseline_authority ?? avgBaselineAuthority;
  const isAggregateBaseline = m.baseline_authority == null && avgBaselineAuthority != null;
  // Per-group baseline: use per-chat value if available, otherwise aggregate fallback
  const effectiveBaselineByGroup = m.baseline_authority_by_group ?? avgBaselineAuthorityByGroup;

  const miniMetrics = [
    { label: "Copertura", value: m.party_coverage_score, color: "bg-chart-1" },
    { label: "Fedeltà", value: m.verbatim_match_score, color: "bg-chart-2" },
    { label: "Autorevolezza", value: m.authority_utilization, color: "bg-chart-3" },
    { label: "Completezza", value: m.response_completeness, color: "bg-chart-4" },
  ];

  const formatDate = (ts: string) => {
    try {
      return new Date(ts).toLocaleDateString("it-IT", {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return ts;
    }
  };

  return (
    <Card className="overflow-hidden">
      <div
        className="p-4 cursor-pointer hover:bg-surface-muted transition-colors"
        onClick={onToggle}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex-1 min-w-0">
            <p className="font-medium text-fg line-clamp-1">
              {item.chat_query}
            </p>
            <div className="flex items-center gap-3 mt-2">
              <span className="text-xs text-muted-foreground">
                {formatDate(item.timestamp)}
              </span>
              <MiniMetricBars values={miniMetrics} />
              {item.human && (
                <Badge
                  variant="secondary"
                  className="text-xs bg-brand-soft text-brand-fg"
                >
                  Valutata A/B
                </Badge>
              )}
              {item.human_simple && (
                <Badge
                  variant="secondary"
                  className="text-xs bg-surface-sunken text-fg-secondary"
                >
                  <BarChart2 className="w-3 h-3 mr-1" />
                  Likert
                </Badge>
              )}
            </div>
          </div>
          {isExpanded ? (
            <ChevronUp className="w-5 h-5 text-fg-muted shrink-0" />
          ) : (
            <ChevronDown className="w-5 h-5 text-fg-muted shrink-0" />
          )}
        </div>
      </div>

      {isExpanded && (
        <div className="border-t border-line px-3 md:px-4 py-4 bg-surface-muted">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4 md:gap-6">
            {/* Automated metrics */}
            <div>
              <h4 className="text-sm font-semibold text-fg mb-3">
                Metriche Automatiche
              </h4>
              <div className="space-y-2">
                {/* Standard rows (non-authority) */}
                {(() => {
                  const coveredParties = new Set(Object.keys(m.party_breakdown));
                  const missingParties = Object.keys(PARTY_SHORT_NAMES).filter(
                    (p) => !coveredParties.has(p)
                  );
                  const rows: { label: string; value: number; detail: string; format: "percent" | "decimal"; missing?: string[] }[] = [
                    { label: "Copertura partitica", value: m.party_coverage_score, detail: `${m.parties_represented}/${m.parties_total} partiti`, format: "percent", missing: missingParties },
                    { label: "Fedeltà citazioni", value: m.verbatim_match_score, detail: `${m.verbatim_match_count}/${m.citations_total} verificate`, format: "percent" },
                    { label: "Discriminazione autorevolezza", value: m.authority_discrimination, detail: "std dev", format: "decimal" },
                    { label: "Completezza", value: m.response_completeness, detail: "", format: "percent" },
                  ];
                  return rows.map((row) => (
                    <div key={row.label}>
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-fg-secondary">{row.label}</span>
                        <div className="flex items-center gap-2">
                          {row.detail && (
                            <span className="text-xs text-muted-foreground">{row.detail}</span>
                          )}
                          <span className="font-mono font-medium w-16 text-right">
                            {row.format === "decimal"
                              ? row.value.toFixed(3)
                              : `${(row.value * 100).toFixed(1)}%`}
                          </span>
                        </div>
                      </div>
                      {row.missing && row.missing.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-1 ml-0">
                          <span className="text-xs text-muted-foreground mr-0.5">Mancanti:</span>
                          {row.missing.map((p) => (
                            <span
                              key={p}
                              className="inline-flex items-center px-1.5 py-0.5 rounded-sm text-xs bg-danger-soft text-danger-fg border border-danger/30"
                            >
                              {shortParty(p)}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ));
                })()}

                {/* Authority row with system vs baseline */}
                <div className="flex items-start justify-between text-sm">
                  <span className="text-fg-secondary shrink-0">Autorevolezza</span>
                  <div className="flex flex-col items-end gap-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">{m.experts_count} esp</span>
                      {effectiveBaseline != null && (
                        <span className="text-xs text-muted-foreground">
                          · base{isAggregateBaseline ? " (media)" : ""} {(effectiveBaseline * 100).toFixed(1)}%
                        </span>
                      )}
                      <span className="font-mono font-medium w-16 text-right">
                        {(m.authority_utilization * 100).toFixed(1)}%
                      </span>
                    </div>
                    {effectiveBaseline != null && (() => {
                      const delta = m.authority_utilization - effectiveBaseline;
                      const isUp = delta >= 0;
                      return (
                        <span className={cn(
                          "text-xs font-medium",
                          isUp ? "text-brand-fg" : "text-fg-secondary"
                        )}>
                          {isUp ? "+" : ""}{(delta * 100).toFixed(1)}pp vs baseline{isAggregateBaseline ? " (media)" : ""}
                        </span>
                      );
                    })()}
                  </div>
                </div>
              </div>

              {/* Global authority spread stats */}
              {m.authority_spread_stats && (
                <div className="mt-3 rounded-md bg-surface px-3 py-2.5 text-xs space-y-1.5">
                  <p className="label-mono mb-1.5">
                    Distribuzione autorità: tutti i {m.authority_spread_stats.n} deputati
                  </p>
                  <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Media</span>
                      <span className="font-mono font-medium">{(m.authority_spread_stats.mean * 100).toFixed(1)}%</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-muted-foreground">Dev. std</span>
                      <span className="font-mono font-medium">{(m.authority_spread_stats.std * 100).toFixed(1)}%</span>
                    </div>
                    {m.authority_spread_stats.min_name && (
                      <div className="flex justify-between gap-2 col-span-2">
                        <span className="text-muted-foreground shrink-0">Min</span>
                        <span className="font-medium text-right truncate">
                          {m.authority_spread_stats.min_name}
                          <span className="font-mono text-muted-foreground ml-1">
                            ({(m.authority_spread_stats.min_score! * 100).toFixed(1)}%)
                          </span>
                        </span>
                      </div>
                    )}
                    {m.authority_spread_stats.max_name && (
                      <div className="flex justify-between gap-2 col-span-2">
                        <span className="text-muted-foreground shrink-0">Max</span>
                        <span className="font-medium text-right truncate">
                          {m.authority_spread_stats.max_name}
                          <span className="font-mono text-muted-foreground ml-1">
                            ({(m.authority_spread_stats.max_score! * 100).toFixed(1)}%)
                          </span>
                        </span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Per-group authority chart */}
              {Object.keys(m.authority_by_group).length > 0 && (
                <AuthorityByGroupChart
                  systemByGroup={m.authority_by_group}
                  baselineByGroup={effectiveBaselineByGroup}
                  isAggregateBaseline={isAggregateBaseline}
                />
              )}

              {/* Party breakdown */}
              {Object.keys(m.party_breakdown).length > 0 && (
                <div className="mt-4">
                  <h5 className="label-mono mb-2">
                    Distribuzione per partito
                  </h5>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(m.party_breakdown)
                      .sort(([, a], [, b]) => b - a)
                      .map(([party, count]) => (
                        <Badge key={party} variant="outline" className="text-xs">
                          {shortParty(party)}: {count}
                        </Badge>
                      ))}
                  </div>
                </div>
              )}
            </div>

            {/* Human evaluation metrics */}
            <div>
              <h4 className="text-sm font-semibold text-fg mb-3">
                Valutazione Umana
              </h4>
              {item.human ? (
                <div className="space-y-3">
                  <div className="label-mono mb-1">
                    A/B Blind
                  </div>
                  {AB_DIMENSIONS.map((dim) => {
                    const rating = (item.human as any)[dim] as ABRating | undefined;
                    if (!rating) return null;
                    return (
                      <div key={dim} className="text-sm">
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-fg-secondary">
                            {DIMENSION_LABELS[dim] || dim}
                          </span>
                          <span className="text-xs text-muted-foreground">
                            Pref: {rating.preference === "A" ? "A" : rating.preference === "B" ? "B" : "="}
                          </span>
                        </div>
                        <div className="flex items-center gap-2 text-xs">
                          <span className="w-6 text-brand-fg">A:</span>
                          <div className="flex gap-0.5">
                            {Array.from({ length: 5 }, (_, i) => (
                              <div
                                key={i}
                                className={cn(
                                  "w-2 h-2 rounded-full",
                                  i < rating.rating_a
                                    ? "bg-chart-1"
                                    : "bg-surface-sunken"
                                )}
                              />
                            ))}
                          </div>
                          <span className="font-mono">{rating.rating_a}/5</span>
                          <span className="mx-1 text-line-strong">|</span>
                          <span className="w-6 text-notice-fg">B:</span>
                          <div className="flex gap-0.5">
                            {Array.from({ length: 5 }, (_, i) => (
                              <div
                                key={i}
                                className={cn(
                                  "w-2 h-2 rounded-full",
                                  i < rating.rating_b
                                    ? "bg-chart-3"
                                    : "bg-surface-sunken"
                                )}
                              />
                            ))}
                          </div>
                          <span className="font-mono">{rating.rating_b}/5</span>
                        </div>
                      </div>
                    );
                  })}

                  <div className="mt-2 pt-2 border-t text-sm">
                    <div className="flex justify-between">
                      <span className="text-fg-secondary">Soddisfazione A</span>
                      <span className="font-mono">{item.human.overall_satisfaction_a}/5</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-fg-secondary">Soddisfazione B</span>
                      <span className="font-mono">{item.human.overall_satisfaction_b}/5</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-fg-secondary">Preferenza</span>
                      <span className="font-semibold">{item.human.overall_preference}</span>
                    </div>
                  </div>

                  {item.human.would_recommend && (
                    <div className="mt-2 flex items-center gap-1 text-brand-fg text-sm">
                      <ThumbsUp className="w-3 h-3" />
                      <span>Raccomanderebbe il sistema</span>
                    </div>
                  )}

                  {item.human.feedback_positive && (
                    <div className="mt-3 p-2 bg-brand-soft rounded-sm text-sm text-fg">
                      <span className="font-medium">Positivo: </span>
                      {item.human.feedback_positive}
                    </div>
                  )}
                  {item.human.feedback_improvement && (
                    <div className="mt-2 p-2 bg-notice-soft rounded-sm text-sm text-fg">
                      <span className="font-medium">Da migliorare: </span>
                      {item.human.feedback_improvement}
                    </div>
                  )}
                </div>
              ) : item.human_simple ? (
                <div className="space-y-3">
                  <div className="flex items-center gap-1.5 label-mono mb-1">
                    <BarChart2 className="w-3 h-3" />
                    Likert 1-5
                  </div>
                  {(Object.keys(SIMPLE_DIMENSION_LABELS) as SimpleDimension[]).map((dim) => {
                    const score = item.human_simple![dim] as number;
                    return (
                      <div key={dim} className="flex items-center justify-between text-sm">
                        <span className="text-fg-secondary">
                          {SIMPLE_DIMENSION_LABELS[dim]}
                        </span>
                        <div className="flex items-center gap-2">
                          <div className="flex gap-0.5">
                            {Array.from({ length: 5 }, (_, i) => (
                              <div
                                key={i}
                                className={cn(
                                  "w-2 h-2 rounded-full",
                                  i < score
                                    ? "bg-brand"
                                    : "bg-surface-sunken"
                                )}
                              />
                            ))}
                          </div>
                          <span className="font-mono text-xs w-6 text-right">{score}/5</span>
                        </div>
                      </div>
                    );
                  })}
                  {item.human_simple.feedback && (
                    <div className="mt-2 p-2 bg-surface-sunken rounded-sm text-sm text-fg">
                      <span className="font-medium">Feedback: </span>
                      {item.human_simple.feedback}
                    </div>
                  )}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-32 text-fg-muted">
                  <CheckCircle2 className="w-8 h-8 opacity-30 mb-2" />
                  <p className="text-sm">Non ancora valutata</p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}
