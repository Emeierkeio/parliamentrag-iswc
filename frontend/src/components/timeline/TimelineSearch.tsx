"use client";

import { useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { ArrowRight, Search, X, Calendar } from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { TimelineFilters } from "@/types/timeline";

interface TimelineSearchProps {
  filters: TimelineFilters;
  onFiltersChange: (partial: Partial<TimelineFilters>) => void;
  onClear: () => void;
  hasActiveFilters: boolean;
}

type Preset = "week" | "month" | "3months" | null;

function toISODate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function TimelineSearch({
  filters,
  onFiltersChange,
  onClear,
  hasActiveFilters,
}: TimelineSearchProps) {
  const t = useTranslations("Timeline");
  // The hook mounts the page on the last-month window, so the matching
  // chip starts lit; it goes dark as soon as the dates are edited by hand.
  const [activePreset, setActivePreset] = useState<Preset>("month");
  // On phones the date inputs live behind the calendar toggle: the presets
  // cover the common cases and the sticky filter block must stay short.
  const [showDates, setShowDates] = useState(false);

  const applyPreset = useCallback(
    (preset: Preset, days: number) => {
      const today = new Date();
      const from = new Date(today);
      from.setDate(today.getDate() - days);
      setActivePreset(preset);
      onFiltersChange({ fromDate: toISODate(from), toDate: toISODate(today) });
    },
    [onFiltersChange],
  );

  const handleFromDate = useCallback(
    (value: string) => {
      setActivePreset(null);
      onFiltersChange({ fromDate: value });
    },
    [onFiltersChange],
  );

  const handleToDate = useCallback(
    (value: string) => {
      setActivePreset(null);
      onFiltersChange({ toDate: value });
    },
    [onFiltersChange],
  );

  const handleClear = useCallback(() => {
    // Clearing returns to the default view, which is the last-month window
    setActivePreset("month");
    onClear();
  }, [onClear]);

  const presets: { key: Preset; days: number; label: string }[] = [
    { key: "week", days: 7, label: t("lastWeek") },
    { key: "month", days: 30, label: t("lastMonth") },
    { key: "3months", days: 90, label: t("last3Months") },
  ];

  return (
    <div className="space-y-2.5" role="search" aria-label={t("pageTitle")}>
      {/* Search input */}
      <div className="relative">
        <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted pointer-events-none" />
        <Input
          type="text"
          placeholder={t("searchPlaceholder")}
          value={filters.search}
          onChange={(e) => onFiltersChange({ search: e.target.value })}
          className="pl-9 pr-9 h-11"
          aria-label={t("searchPlaceholder")}
        />
        {filters.search && (
          <button
            type="button"
            onClick={() => onFiltersChange({ search: "" })}
            className="absolute right-1.5 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full text-fg-muted hover:bg-surface-muted hover:text-fg transition-colors"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Presets + date range in a single row */}
      <div className="flex flex-wrap items-center gap-2">
        {/* Preset segmented control: fills the row on phones, inline on larger screens */}
        <div className="flex flex-1 sm:flex-none sm:inline-flex rounded-full border border-line-strong p-0.5 bg-surface">
          {presets.map(({ key, days, label }) => (
            <button
              key={key}
              onClick={() => applyPreset(key, days)}
              aria-pressed={activePreset === key}
              className={cn(
                "flex-1 sm:flex-none min-h-8 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                activePreset === key
                  ? "bg-brand text-on-brand"
                  : "text-fg-secondary hover:text-fg"
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Custom-dates toggle (phones only) */}
        <button
          type="button"
          onClick={() => setShowDates((v) => !v)}
          aria-expanded={showDates}
          aria-label={t("dateFrom")}
          className={cn(
            "sm:hidden flex h-9 w-9 shrink-0 items-center justify-center rounded-full border transition-colors",
            showDates
              ? "border-brand/40 bg-brand-soft text-brand-fg"
              : "border-line-strong bg-surface text-fg-muted"
          )}
        >
          <Calendar className="h-4 w-4" />
        </button>

        {/* Separator */}
        <div className="w-px h-5 bg-line mx-1 hidden sm:block" />

        {/* Compact date range, hidden on phones until the toggle opens it */}
        <div className={cn("items-center gap-1.5 w-full sm:w-auto", showDates ? "flex" : "hidden sm:flex")}>
          <Calendar className="h-3.5 w-3.5 text-fg-muted shrink-0 hidden sm:block" />
          <input
            type="date"
            value={filters.fromDate}
            onChange={(e) => handleFromDate(e.target.value)}
            className="flex-1 sm:flex-none h-8 rounded-md border border-line-control bg-surface px-2.5 text-xs text-fg transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            aria-label={t("dateFrom")}
          />
          <ArrowRight className="h-3 w-3 shrink-0 text-fg-faint" aria-hidden />
          <input
            type="date"
            value={filters.toDate}
            onChange={(e) => handleToDate(e.target.value)}
            className="flex-1 sm:flex-none h-8 rounded-md border border-line-control bg-surface px-2.5 text-xs text-fg transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus"
            aria-label={t("dateTo")}
          />
        </div>

        {/* Clear all: outside the dates row so it stays reachable on phones
            while the dates are collapsed */}
        {hasActiveFilters && (
          <button
            onClick={handleClear}
            className="h-8 px-3 rounded-full text-xs font-medium text-fg-muted hover:text-fg hover:bg-surface-muted transition-colors ml-auto shrink-0"
          >
            {t("clearFilters")}
          </button>
        )}
      </div>

      <div aria-live="polite" className="sr-only" />
    </div>
  );
}
