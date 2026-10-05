"use client";

import React from "react";
import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/* ─── RadarChart ─── */

interface RadarChartProps {
  metrics: number[];
  labels: string[];
  secondaryMetrics?: number[];
  secondaryLabel?: string;
  size?: number;
}

export function RadarChart({
  metrics,
  labels,
  secondaryMetrics,
  secondaryLabel,
  size = 300,
}: RadarChartProps) {
  const n = metrics.length;
  const cx = size / 2;
  const cy = size / 2;
  const r = (size / 2) - 50;

  const getPoint = (index: number, value: number) => {
    const angle = (2 * Math.PI * index) / n - Math.PI / 2;
    return {
      x: cx + r * value * Math.cos(angle),
      y: cy + r * value * Math.sin(angle),
    };
  };

  const polygon = (values: number[]) =>
    values.map((v, i) => getPoint(i, v)).map((p) => `${p.x},${p.y}`).join(" ");

  const gridLevels = [0.2, 0.4, 0.6, 0.8, 1.0];

  return (
    <div className="flex flex-col items-center">
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Grid */}
        {gridLevels.map((level) => (
          <polygon
            key={level}
            points={Array.from({ length: n }, (_, i) => getPoint(i, level))
              .map((p) => `${p.x},${p.y}`)
              .join(" ")}
            fill="none"
            strokeWidth="1"
            className="stroke-line-strong"
          />
        ))}

        {/* Axes */}
        {Array.from({ length: n }, (_, i) => {
          const p = getPoint(i, 1);
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={p.x}
              y2={p.y}
              strokeWidth="1"
              className="stroke-line-strong"
            />
          );
        })}

        {/* Secondary data polygon */}
        {secondaryMetrics && (
          <polygon
            points={polygon(secondaryMetrics)}
            strokeWidth="2"
            className="fill-chart-3/15 stroke-chart-3"
            strokeDasharray="6 3"
          />
        )}

        {/* Primary data polygon */}
        <polygon
          points={polygon(metrics)}
          strokeWidth="2.5"
          className="fill-chart-1/20 stroke-chart-1"
        />

        {/* Data points */}
        {metrics.map((v, i) => {
          const p = getPoint(i, v);
          return (
            <circle
              key={i}
              cx={p.x}
              cy={p.y}
              r="4"
              strokeWidth="2"
              className="fill-chart-1 stroke-surface"
            />
          );
        })}

        {/* Labels */}
        {labels.map((label, i) => {
          const p = getPoint(i, 1.25);
          return (
            <text
              key={i}
              x={p.x}
              y={p.y}
              textAnchor="middle"
              dominantBaseline="middle"
              className="fill-fg-muted text-[11px]"
            >
              {label}
            </text>
          );
        })}
      </svg>

      {/* Legend */}
      <div className="flex items-center gap-6 mt-2 text-sm">
        <div className="flex items-center gap-2">
          <div className="w-4 h-0.5 bg-chart-1 rounded-full" />
          <span className="text-fg-muted">Automatiche</span>
        </div>
        {secondaryMetrics && (
          <div className="flex items-center gap-2">
            <div className="w-4 border-t-2 border-dashed border-chart-3" />
            <span className="text-fg-muted">
              {secondaryLabel || "Umane"}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── HorizontalBarChart ─── */

interface BarItem {
  label: string;
  value: number;
  max?: number;
  ci?: [number, number];
}

interface HorizontalBarChartProps {
  items: BarItem[];
  colorClass?: string;
}

export function HorizontalBarChart({
  items,
  colorClass = "bg-chart-1",
}: HorizontalBarChartProps) {
  return (
    <div className="space-y-4">
      {items.map((item) => {
        const max = item.max ?? 1;
        const pct = (item.value / max) * 100;
        return (
          <div key={item.label} className="space-y-1">
            <div className="flex items-center justify-between text-sm">
              <span className="text-fg-secondary font-medium">
                {item.label}
              </span>
              <span className="font-mono text-fg-muted">
                {(item.value * 100).toFixed(1)}%
              </span>
            </div>
            <div className="relative h-6 bg-surface-sunken rounded-full overflow-hidden">
              <div
                className={cn(
                  "h-full rounded-full transition-all duration-500",
                  colorClass
                )}
                style={{ width: `${Math.min(pct, 100)}%` }}
              />
              {/* CI markers */}
              {item.ci && (
                <>
                  <div
                    className="absolute top-0 h-full w-0.5 bg-fg-faint"
                    style={{ left: `${(item.ci[0] / max) * 100}%` }}
                  />
                  <div
                    className="absolute top-0 h-full w-0.5 bg-fg-faint"
                    style={{ left: `${(item.ci[1] / max) * 100}%` }}
                  />
                </>
              )}
            </div>
            {item.ci && (
              <div className="text-xs text-fg-muted">
                IC 95%: [{(item.ci[0] * 100).toFixed(1)}%, {(item.ci[1] * 100).toFixed(1)}%]
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── ScoreDistribution ─── */

interface ScoreDistributionProps {
  label: string;
  distribution: Record<number, number>;
  average?: number;
}

// One hue in rising intensity: a score is a quantity, not a good/bad signal.
const SCORE_COLORS = [
  "bg-brand/20",
  "bg-brand/40",
  "bg-brand/60",
  "bg-brand/80",
  "bg-brand",
];

const SCORE_LABELS = ["1", "2", "3", "4", "5"];

export function ScoreDistribution({
  label,
  distribution,
  average,
}: ScoreDistributionProps) {
  const maxCount = Math.max(...Object.values(distribution), 1);

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-fg-secondary">
          {label}
        </span>
        {average !== undefined && (
          <span className="text-sm font-mono text-fg-muted">
            {average.toFixed(2)} / 5
          </span>
        )}
      </div>
      <div className="space-y-1">
        {SCORE_LABELS.map((scoreLabel, idx) => {
          const score = idx + 1;
          const count = distribution[score] || 0;
          const pct = (count / maxCount) * 100;
          return (
            <div key={score} className="flex items-center gap-2">
              <span className="w-4 text-xs text-fg-muted text-right">
                {scoreLabel}
              </span>
              <div className="flex-1 h-4 bg-surface-sunken rounded overflow-hidden">
                <div
                  className={cn(
                    "h-full rounded transition-all duration-300",
                    SCORE_COLORS[idx]
                  )}
                  style={{ width: `${pct}%` }}
                />
              </div>
              <span className="w-6 text-xs text-fg-muted text-right">
                {count}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/* ─── MetricCard ─── */

interface MetricCardProps {
  label: string;
  value: number;
  ci?: [number, number];
  icon: React.ReactNode;
  format?: "percent" | "decimal" | "count";
  description?: string;
  baselineValue?: number;
  baselineCi?: [number, number];
  /** For metrics where neither higher nor lower is inherently better. */
  isNeutral?: boolean;
}

export function MetricCard({
  label,
  value,
  ci,
  icon,
  format = "percent",
  description,
  baselineValue,
  baselineCi,
  isNeutral = false,
}: MetricCardProps) {
  const formattedValue =
    format === "percent"
      ? `${(value * 100).toFixed(1)}%`
      : format === "count"
      ? String(value)
      : value.toFixed(3);

  const getColorClass = (v: number) => {
    if (isNeutral) return "text-brand-fg";
    if (v >= 0.6) return "text-fg";
    return "text-fg-secondary";
  };

  const getBarColor = (v: number) => {
    if (isNeutral) return "bg-brand";
    if (v >= 0.8) return "bg-brand";
    if (v >= 0.6) return "bg-brand/65";
    return "bg-brand/35";
  };

  const isDegenerate = ci && ci[0] === ci[1];
  const hasBaseline = baselineValue != null;
  const delta = hasBaseline ? value - baselineValue! : 0;

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center gap-2 text-muted-foreground mb-2">
          {icon}
          <span className="text-sm font-medium">{label}</span>
        </div>
        <div className={cn("text-2xl font-semibold tabular mb-1", getColorClass(value))}>
          {formattedValue}
        </div>
        {hasBaseline && (
          <div className="flex items-center gap-1.5 mb-1">
            <span className="text-xs text-muted-foreground">Baseline:</span>
            <span className="text-xs font-mono text-notice-fg">
              {format === "percent" ? `${(baselineValue! * 100).toFixed(1)}%` : baselineValue!.toFixed(3)}
            </span>
            <span className={cn(
              "text-xs font-semibold ml-0.5",
              delta > 0.005 ? "text-brand-fg" :
              delta < -0.005 ? "text-fg-secondary" :
              "text-fg-muted"
            )}>
              {delta > 0.005 ? "▲" : delta < -0.005 ? "▼" : "≈"}
              {format === "percent"
                ? ` ${delta >= 0 ? "+" : ""}${(delta * 100).toFixed(1)}pp`
                : ` ${delta >= 0 ? "+" : ""}${delta.toFixed(3)}`}
            </span>
          </div>
        )}
        {format === "percent" && (
          <div className="space-y-1 mb-1">
            <div className="flex items-center gap-1">
              <span className="text-[10px] text-brand-fg w-14 shrink-0">Sistema</span>
              <div className="flex-1 bg-surface-sunken rounded-full h-1.5">
                <div
                  className={cn("h-1.5 rounded-full transition-all", getBarColor(value))}
                  style={{ width: `${Math.min(value * 100, 100)}%` }}
                />
              </div>
            </div>
            {hasBaseline && (
              <div className="flex items-center gap-1">
                <span className="text-[10px] text-notice-fg w-14 shrink-0">Baseline</span>
                <div className="flex-1 bg-surface-sunken rounded-full h-1.5">
                  <div
                    className="h-1.5 rounded-full bg-chart-3 transition-all"
                    style={{ width: `${Math.min(baselineValue! * 100, 100)}%` }}
                  />
                </div>
              </div>
            )}
          </div>
        )}
        {description && (
          <div className="text-xs text-muted-foreground mb-1">{description}</div>
        )}
        {ci && format === "percent" && (
          <div className="text-xs text-muted-foreground">
            IC 95%: [{(ci[0] * 100).toFixed(1)}%, {(ci[1] * 100).toFixed(1)}%]
            {isDegenerate && (
              <span className="ml-1 text-notice-fg" title="Basato su un singolo campione">
                (n=1)
              </span>
            )}
          </div>
        )}
        {hasBaseline && baselineCi && format === "percent" && (
          <div className="text-xs text-muted-foreground">
            Baseline IC 95%: [{(baselineCi[0] * 100).toFixed(1)}%, {(baselineCi[1] * 100).toFixed(1)}%]
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/* ─── MiniMetricBars ─── */

interface MiniMetricBarsProps {
  values: { label: string; value: number; color: string }[];
}

export function MiniMetricBars({ values }: MiniMetricBarsProps) {
  return (
    <div className="flex items-center gap-1">
      {values.map((v) => (
        <div
          key={v.label}
          className="relative group"
          title={`${v.label}: ${(v.value * 100).toFixed(0)}%`}
        >
          <div className="w-8 h-2 bg-surface-sunken rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full", v.color)}
              style={{ width: `${v.value * 100}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ─── ABComparisonChart ─── */

interface ABComparisonItem {
  label: string;
  systemValue: number;
  baselineValue: number;
}

interface ABComparisonChartProps {
  items: ABComparisonItem[];
  maxValue?: number;
}

export function ABComparisonChart({ items, maxValue = 5 }: ABComparisonChartProps) {
  return (
    <div className="space-y-4">
      {items.map((item) => {
        const sysPct = (item.systemValue / maxValue) * 100;
        const basePct = (item.baselineValue / maxValue) * 100;
        const delta = item.systemValue - item.baselineValue;
        return (
          <div key={item.label} className="space-y-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-fg-secondary font-medium">
                {item.label}
              </span>
              <span className={cn(
                "text-xs font-semibold",
                delta > 0 ? "text-brand-fg" : delta < 0 ? "text-fg-secondary" : "text-fg-muted"
              )}>
                {delta > 0 ? "+" : ""}{delta.toFixed(2)}
              </span>
            </div>
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <span className="w-20 text-xs text-brand-fg">Sistema</span>
                <div className="flex-1 h-5 bg-surface-sunken rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-chart-1 transition-all duration-500"
                    style={{ width: `${Math.min(sysPct, 100)}%` }}
                  />
                </div>
                <span className="w-10 text-xs font-mono text-right text-fg-muted">
                  {item.systemValue.toFixed(2)}
                </span>
              </div>
              <div className="flex items-center gap-2">
                <span className="w-20 text-xs text-notice-fg">Baseline</span>
                <div className="flex-1 h-5 bg-surface-sunken rounded-full overflow-hidden">
                  <div
                    className="h-full rounded-full bg-chart-3 transition-all duration-500"
                    style={{ width: `${Math.min(basePct, 100)}%` }}
                  />
                </div>
                <span className="w-10 text-xs font-mono text-right text-fg-muted">
                  {item.baselineValue.toFixed(2)}
                </span>
              </div>
            </div>
          </div>
        );
      })}
      <div className="flex items-center gap-4 mt-2 text-xs text-muted-foreground">
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-xs bg-chart-1" />
          ParliamentRAG
        </div>
        <div className="flex items-center gap-1">
          <div className="w-3 h-3 rounded-xs bg-chart-3" />
          Baseline RAG
        </div>
      </div>
    </div>
  );
}

/* ─── WinRateChart ─── */

interface WinRateChartProps {
  systemWinRate: number;
  baselineWinRate: number;
  tieRate: number;
  totalEvaluations: number;
}

export function WinRateChart({ systemWinRate, baselineWinRate, tieRate, totalEvaluations }: WinRateChartProps) {
  const sysW = Math.round(systemWinRate);
  const baseW = Math.round(baselineWinRate);
  const tieW = Math.round(tieRate);

  return (
    <div className="space-y-4">
      <div className="flex items-center h-10 rounded-full overflow-hidden bg-surface-sunken">
        {sysW > 0 && (
          <div
            className="h-full bg-chart-1 flex items-center justify-center text-on-brand text-xs font-semibold tabular"
            style={{ width: `${sysW}%` }}
          >
            {sysW > 8 ? `${sysW}%` : ""}
          </div>
        )}
        {tieW > 0 && (
          <div
            className="h-full bg-line-strong flex items-center justify-center text-fg-secondary text-xs font-semibold tabular"
            style={{ width: `${tieW}%` }}
          >
            {tieW > 8 ? `${tieW}%` : ""}
          </div>
        )}
        {baseW > 0 && (
          <div
            className="h-full bg-chart-3 flex items-center justify-center text-on-brand text-xs font-semibold tabular"
            style={{ width: `${baseW}%` }}
          >
            {baseW > 8 ? `${baseW}%` : ""}
          </div>
        )}
      </div>
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-xs bg-chart-1" />
          <span className="text-fg-muted">
            ParliamentRAG preferito ({sysW}%)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-xs bg-line-strong" />
          <span className="text-fg-muted">
            Pari ({tieW}%)
          </span>
        </div>
        <div className="flex items-center gap-2">
          <div className="w-3 h-3 rounded-xs bg-chart-3" />
          <span className="text-fg-muted">
            Baseline preferito ({baseW}%)
          </span>
        </div>
      </div>
      <p className="text-xs text-center text-muted-foreground">
        Basato su {totalEvaluations} valutazioni blind A/B
      </p>
    </div>
  );
}
