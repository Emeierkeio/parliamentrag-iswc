"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import {useTranslations, useLocale } from "next-intl";
import { graphQuery } from "@/lib/graph";
import { GroupLogo } from "@/components/entities/GroupLogo";
import { AppBar } from "@/components/shell/AppBar";
import { useLocalHistory } from "@/hooks/use-local-history";
import { ExpertModal } from "@/components/chat/ExpertCard";
import { FeedbackPulse } from "@/components/feedback/FeedbackPulse";
import { config } from "@/config";
import { cn, toTitleCase } from "@/lib/utils";
import { getTopics } from "@/lib/constants";
import type { Expert } from "@/types";
import {
  Search,
  ArrowUpDown,
  SlidersHorizontal,
  X,
  Users,
  ChevronDown,
  RotateCcw,
  Landmark,
  ArrowRight,
  History,
  Clock,
  Info,
  Check,
  Pencil,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

// ── Types ──────────────────────────────────────────────────────

interface RankingDeputy extends Expert {
  committees?: string[];
  relevant_speeches_count: number;
}

type SortKey =
  | "authority_score"
  | "speeches"
  | "acts"
  | "committee"
  | "profession"
  | "education"
  | "role";

type CoalitionFilter = "all" | "majority" | "opposition";

type ComponentKey = Exclude<SortKey, "authority_score">;

// Pesi ufficiali: mirror di backend/config/default.yaml → authority.weights
// (speeches nel breakdown corrisponde a "interventions" nel config)
const DEFAULT_WEIGHTS: Record<ComponentKey, number> = {
  speeches: 0.25,
  committee: 0.25,
  acts: 0.2,
  profession: 0.15,
  education: 0.1,
  role: 0.05,
};

// coalition mirrors backend/config/default.yaml; Misto is mixed by nature
// and stays selectable under either coalition
const GROUPS: { value: string; label: string; shortLabel: string; coalition: "majority" | "opposition" | "mixed" }[] = [
  { value: "FRATELLI D'ITALIA", label: "Fratelli d'Italia", shortLabel: "FdI", coalition: "majority" },
  { value: "LEGA - SALVINI PREMIER", label: "Lega - Salvini Premier", shortLabel: "Lega", coalition: "majority" },
  { value: "FORZA ITALIA - BERLUSCONI PRESIDENTE - PPE", label: "Forza Italia", shortLabel: "FI", coalition: "majority" },
  { value: "NOI MODERATI (NOI CON L'ITALIA, CORAGGIO ITALIA, UDC E ITALIA AL CENTRO)-MAIE-CENTRO POPOLARE", label: "Noi Moderati", shortLabel: "NM", coalition: "majority" },
  { value: "PARTITO DEMOCRATICO - ITALIA DEMOCRATICA E PROGRESSISTA", label: "PD", shortLabel: "PD", coalition: "opposition" },
  { value: "MOVIMENTO 5 STELLE", label: "M5S", shortLabel: "M5S", coalition: "opposition" },
  { value: "ALLEANZA VERDI E SINISTRA", label: "AVS", shortLabel: "AVS", coalition: "opposition" },
  { value: "AZIONE-POPOLARI EUROPEISTI RIFORMATORI-RENEW EUROPE", label: "Azione", shortLabel: "Azione", coalition: "opposition" },
  { value: "ITALIA VIVA-CASA RIFORMISTA (IV-CR)", label: "Italia Viva", shortLabel: "IV", coalition: "opposition" },
  { value: "MISTO", label: "Misto", shortLabel: "Misto", coalition: "mixed" },
];

function groupAllowedInCoalition(value: string, coalition: CoalitionFilter): boolean {
  if (coalition === "all") return true;
  const entry = GROUPS.find((g) => g.value === value);
  return !entry || entry.coalition === "mixed" || entry.coalition === coalition;
}

// ── Page ───────────────────────────────────────────────────────

export default function RankingPage() {
  const t = useTranslations("RankingsPage");
  const locale = useLocale();
  const rankingHistory = useLocalHistory<{ deputies: RankingDeputy[]; computationTime: number }>(
    "parliamentrag-ranking-history"
  );

  // Data state
  const [deputies, setDeputies] = useState<RankingDeputy[]>([]);
  const [topic, setTopic] = useState("");
  const [activeTopic, setActiveTopic] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [computationTime, setComputationTime] = useState(0);

  // Filter state
  const [nameSearch, setNameSearch] = useState("");
  const [coalitionFilter, setCoalitionFilter] = useState<CoalitionFilter>("all");
  const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
  const [committeeSearch, setCommitteeSearch] = useState("");
  // Panel combobox: typing filters, picking sets committeeSearch
  const [committeeQuery, setCommitteeQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("authority_score");
  const [sortOpen, setSortOpen] = useState(false);
  const [weights, setWeights] = useState<Record<ComponentKey, number>>(DEFAULT_WEIGHTS);
  const [groupsOpen, setGroupsOpen] = useState(false);
  const [groupSearch, setGroupSearch] = useState("");
  const [committeePopoverSearch, setCommitteePopoverSearch] = useState("");

  const SORT_OPTIONS: { value: SortKey; label: string }[] = [
    { value: "authority_score", label: "Authority Score" },
    { value: "speeches", label: t("sortSpeeches") },
    { value: "acts", label: t("sortActs") },
    { value: "committee", label: t("sortCommittee") },
    { value: "profession", label: t("sortProfession") },
    { value: "education", label: t("sortEducation") },
    { value: "role", label: t("sortRole") },
  ];

  // ── Fetch ranking ──
  // The backend computes for minutes and caches per topic, but intermediate
  // proxies drop the connection after ~30s (HTTP 499/502). The computation
  // keeps running server-side, so we retry until the cached result is ready;
  // in-flight dedup on the backend makes retries free.
  const requestIdRef = useRef(0);

  const fetchRanking = useCallback(async (topicText: string) => {
    if (!topicText.trim()) return;
    const reqId = ++requestIdRef.current;
    setLoading(true);
    setError("");
    setActiveTopic(topicText);
    setNameSearch("");
    setCoalitionFilter("all");
    setSelectedGroups([]);
    setCommitteeSearch("");
    setSortBy("authority_score");

    const deadline = Date.now() + 10 * 60 * 1000;

    try {
      let data: any = null;
      for (;;) {
        try {
          const res = await fetch(`${config.api.baseUrl}/authority-ranking`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ topic: topicText }),
          });
          if (res.ok) {
            data = await res.json();
            break;
          }
          // Client errors are final; 5xx means a dropped proxy hop — retry
          if (res.status < 500) throw new Error(t("errorFetch"));
        } catch (err) {
          if (err instanceof Error && err.message === t("errorFetch")) throw err;
          // network/proxy drop — fall through to retry
        }
        if (requestIdRef.current !== reqId) return;
        if (Date.now() >= deadline) throw new Error(t("errorFetch"));
        await new Promise((r) => setTimeout(r, 15_000));
        if (requestIdRef.current !== reqId) return;
      }
      if (requestIdRef.current !== reqId) return;
      const mapped: RankingDeputy[] = data.deputies.map((d: any) => ({
        ...d,
        relevant_speeches_count: 0,
      }));
      const ct = data.computation_time_ms || 0;
      setDeputies(mapped);
      setComputationTime(ct);
      rankingHistory.addEntry(topicText, { deputies: mapped, computationTime: ct });
    } catch (e: unknown) {
      if (requestIdRef.current !== reqId) return;
      setError(e instanceof Error ? e.message : t("errorUnknown"));
      setDeputies([]);
    } finally {
      if (requestIdRef.current === reqId) setLoading(false);
    }
  }, [t]);

  const restoreRankingEntry = useCallback(
    (entry: { topic: string; data: { deputies: RankingDeputy[]; computationTime: number } }) => {
      setActiveTopic(entry.topic);
      setTopic(entry.topic);
      setDeputies(entry.data.deputies);
      setComputationTime(entry.data.computationTime);
      setError("");
      setNameSearch("");
      setCoalitionFilter("all");
      setSelectedGroups([]);
      setCommitteeSearch("");
      setSortBy("authority_score");
    },
    []
  );

  const handleTopicClick = (t: string) => {
    setTopic(t);
    fetchRanking(t);
  };

  const handleReset = () => {
    setDeputies([]);
    setActiveTopic("");
    setTopic("");
    setError("");
  };

  // ── Available committees ──
  // Before the first query there are no result-derived committees, so the
  // full list comes from the graph and result-derived names replace it later
  const [allCommittees, setAllCommittees] = useState<string[]>([]);
  useEffect(() => {
    graphQuery<{ name: string }>(
      "MATCH (c:Committee) RETURN c.name AS name ORDER BY name"
    )
      .then((rows) => setAllCommittees(rows.map((r) => r.name)))
      .catch(() => {});
  }, []);
  const availableCommittees = useMemo(() => {
    const set = new Set<string>();
    deputies.forEach((d) => {
      d.committees?.forEach((c) => set.add(c));
      if (d.committee) set.add(d.committee);
    });
    const derived = Array.from(set).sort();
    return derived.length > 0 ? derived : allCommittees;
  }, [deputies, allCommittees]);

  // ── Pesi personalizzati ──
  // Con i pesi ufficiali si usa il punteggio calcolato dal backend; con pesi
  // custom si ricombinano le sei componenti del breakdown (normalizzando la
  // somma), così la classifica reagisce senza rifare la query.
  const weightsCustom = useMemo(
    () =>
      (Object.keys(DEFAULT_WEIGHTS) as ComponentKey[]).some(
        (k) => Math.abs(weights[k] - DEFAULT_WEIGHTS[k]) > 1e-9
      ),
    [weights]
  );

  const effectiveScore = useCallback(
    (d: RankingDeputy) => {
      if (!weightsCustom) return d.authority_score;
      const total = (Object.keys(weights) as ComponentKey[]).reduce((a, k) => a + weights[k], 0);
      if (total <= 0) return 0;
      let s = 0;
      for (const k of Object.keys(weights) as ComponentKey[]) {
        s += weights[k] * (d.score_breakdown?.[k] ?? 0);
      }
      return s / total;
    },
    [weights, weightsCustom]
  );

  // ── Filtered and sorted deputies ──
  const filteredDeputies = useMemo(() => {
    let list = [...deputies];

    if (coalitionFilter !== "all") {
      // Map local filter values to backend wire values
      const wireCoalition = coalitionFilter === "majority" ? "maggioranza" : "opposizione";
      list = list.filter((d) => d.coalition === wireCoalition);
    }

    if (selectedGroups.length > 0) {
      list = list.filter((d) => {
        const groupUpper = d.group.toUpperCase();
        return selectedGroups.some((g) => groupUpper === g.toUpperCase() || groupUpper.includes(g.toUpperCase()));
      });
    }

    if (nameSearch.trim()) {
      const q = nameSearch.toLowerCase();
      list = list.filter(
        (d) =>
          d.first_name.toLowerCase().includes(q) ||
          d.last_name.toLowerCase().includes(q) ||
          `${d.first_name} ${d.last_name}`.toLowerCase().includes(q)
      );
    }

    if (committeeSearch) {
      list = list.filter((d) => {
        if (d.committees?.includes(committeeSearch)) return true;
        if (d.committee === committeeSearch) return true;
        return false;
      });
    }

    list.sort((a, b) => {
      if (sortBy === "authority_score") {
        return effectiveScore(b) - effectiveScore(a);
      }
      const aVal = a.score_breakdown?.[sortBy] ?? 0;
      const bVal = b.score_breakdown?.[sortBy] ?? 0;
      return bVal - aVal;
    });

    return list;
  }, [deputies, coalitionFilter, selectedGroups, nameSearch, committeeSearch, sortBy, effectiveScore]);

  const hasResults = deputies.length > 0;
  const hasActiveFilters = coalitionFilter !== "all" || selectedGroups.length > 0 || nameSearch.trim() !== "" || committeeSearch !== "";
  // Pre-query filtering lives in the structured panel inside the empty
  // state; the sticky bar appears only alongside results
  const filtersEnabled = hasResults && !loading;

  const toggleGroup = (value: string) => {
    setSelectedGroups((prev) =>
      prev.includes(value) ? prev.filter((g) => g !== value) : [...prev, value]
    );
  };

  const historyAction = (
    <Popover>
      <PopoverTrigger asChild>
        <Button variant="ghost" size="icon" className="size-10 shrink-0 rounded-full text-fg-secondary hover:text-fg" title={t("historyTitle")} aria-label={t("historyTitle")}>
          <History className="h-4 w-4" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-72 p-2" align="end">
        <p className="label-mono px-2 py-1 mb-1">{t("historyHeading")}</p>
        {rankingHistory.entries.length === 0 ? (
          <p className="text-xs text-center py-4 text-fg-muted">{t("historyEmpty")}</p>
        ) : (
          <div className="space-y-0.5">
            {rankingHistory.entries.map((entry) => (
              <div key={entry.id} className="flex items-center gap-1 group rounded-md hover:bg-surface-muted">
                <button
                  className="flex-1 flex items-center gap-2 px-2 py-1.5 text-left min-w-0"
                  onClick={() => restoreRankingEntry(entry)}
                >
                  <Clock className="h-3 w-3 shrink-0 text-fg-muted" />
                  <span className="text-xs font-medium text-fg truncate">{entry.topic}</span>
                </button>
                <button
                  className="shrink-0 p-1.5 opacity-0 group-hover:opacity-100 text-fg-muted hover:text-danger-fg transition-opacity"
                  onClick={() => rankingHistory.removeEntry(entry.id)}
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

  // ── Render ──
  return (
    <div className="flex h-dvh flex-col overflow-hidden bg-bg pb-[env(safe-area-inset-bottom)]">
      <AppBar actions={historyAction} />

      <main className="flex-1 min-h-0 flex flex-col overflow-hidden">
        {activeTopic && (
          <div className="container-page shrink-0 flex items-center gap-3 pt-4 pb-3">
            <h1 className="label-mono text-fg-muted">{t("headerTitle")}</h1>
            {!loading && (
              <div className="flex items-center gap-2 ml-auto shrink-0">
                <Badge variant="secondary" className="max-w-[180px] truncate text-xs">
                  {activeTopic}
                </Badge>
                <Button variant="ghost" size="icon-sm" onClick={handleReset} aria-label={t("newSearch")}>
                  <RotateCcw className="h-3.5 w-3.5" />
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Barra filtri persistente (solo quando ci sono risultati) */}
        {filtersEnabled && <div className="shrink-0 border-y border-line bg-bg py-3">
          <div className="container-page flex flex-wrap items-center gap-2">
            {/* Coalition toggle */}
            <div className="flex rounded-full border border-line-strong bg-surface p-0.5 text-xs font-medium">
              {(["all", "majority", "opposition"] as CoalitionFilter[]).map((c) => (
                <button
                  key={c}
                  onClick={() => setCoalitionFilter(c)}
                  className={cn(
                    "min-h-7 rounded-full px-3 py-1 transition-colors capitalize",
                    coalitionFilter === c
                      ? "bg-brand text-on-brand"
                      : "text-fg-secondary hover:text-fg"
                  )}
                >
                  {c === "all" ? t("coalitionAll") : c === "majority" ? t("coalitionMajority") : t("coalitionOpposition")}
                </button>
              ))}
            </div>

            {/* Name search */}
            <div className="relative flex-1 min-w-[160px] max-w-[220px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-muted" />
              <Input
                value={nameSearch}
                onChange={(e) => setNameSearch(e.target.value)}
                placeholder={t("nameSearchPlaceholder")}
                className="pl-8 h-8 text-xs"
              />
              {nameSearch && (
                <button onClick={() => setNameSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                  <X className="h-3 w-3 text-fg-muted hover:text-fg" />
                </button>
              )}
            </div>

            {/* Group filter */}
            <Popover open={groupsOpen} onOpenChange={(open) => { setGroupsOpen(open); if (!open) setGroupSearch(""); }}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className={cn("h-9 text-xs gap-1.5", selectedGroups.length > 0 && "border-brand bg-brand-soft text-brand-fg hover:bg-brand-soft-strong")}>
                  <Users className="h-3.5 w-3.5" />
                  {t("groupFilter")}
                  {selectedGroups.length > 0 && (
                    <Badge className="ml-1 h-4 w-4 p-0 flex items-center justify-center text-[10px] bg-brand text-on-brand">
                      {selectedGroups.length}
                    </Badge>
                  )}
                  <ChevronDown className="h-3 w-3" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-64 p-2" align="start">
                <div className="space-y-1">
                  {/* Search input */}
                  <div className="relative mb-2">
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-muted" />
                    <Input
                      value={groupSearch}
                      onChange={(e) => setGroupSearch(e.target.value)}
                      placeholder={t("groupSearchPlaceholder")}
                      className="pl-8 h-7 text-xs rounded-md"
                      autoFocus
                    />
                    {groupSearch && (
                      <button onClick={() => setGroupSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                        <X className="h-3 w-3 text-fg-muted hover:text-fg" />
                      </button>
                    )}
                  </div>
                  {GROUPS.filter((g) => g.label.toLowerCase().includes(groupSearch.toLowerCase())).map((g) => {
                    const selected = selectedGroups.includes(g.value);
                    return (
                      <button
                        key={g.value}
                        aria-pressed={selected}
                        onClick={() => toggleGroup(g.value)}
                        className={cn(
                          "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs transition-colors text-left",
                          selected ? "bg-brand-soft text-fg" : "hover:bg-surface-muted text-fg-muted"
                        )}
                      >
                        <GroupLogo group={g.value} size={18} />
                        <span className="truncate flex-1">{g.label}</span>
                        {selected && <Check className="h-3.5 w-3.5 text-brand-fg" aria-hidden />}
                      </button>
                    );
                  })}
                  {selectedGroups.length > 0 && (
                    <button
                      onClick={() => setSelectedGroups([])}
                      className="w-full text-center text-xs text-danger-fg hover:underline pt-1 border-t border-line mt-1"
                    >
                      {t("groupClearFilters")}
                    </button>
                  )}
                </div>
              </PopoverContent>
            </Popover>

            {/* Committee filter */}
            {availableCommittees.length > 0 && (
              <Popover onOpenChange={(open) => { if (!open) setCommitteePopoverSearch(""); }}>
                <PopoverTrigger asChild>
                  <Button variant="outline" size="sm" className={cn("h-9 text-xs gap-1.5", committeeSearch !== "" && "border-brand bg-brand-soft text-brand-fg hover:bg-brand-soft-strong")}>
                    <Landmark className="h-3.5 w-3.5" />
                    {t("committeeFilter")}
                    {committeeSearch && (
                      <Badge className="ml-1 h-4 px-1 text-[10px] bg-brand text-on-brand">1</Badge>
                    )}
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 p-2" align="start">
                  <div className="space-y-1">
                    {/* Search input */}
                    <div className="relative mb-2">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-fg-muted" />
                      <Input
                        value={committeePopoverSearch}
                        onChange={(e) => setCommitteePopoverSearch(e.target.value)}
                        placeholder={t("committeeSearchPlaceholder")}
                        className="pl-8 h-7 text-xs rounded-md"
                        autoFocus
                      />
                      {committeePopoverSearch && (
                        <button onClick={() => setCommitteePopoverSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                          <X className="h-3 w-3 text-fg-muted hover:text-fg" />
                        </button>
                      )}
                    </div>
                    <div className="max-h-52 overflow-y-auto space-y-1">
                      {committeeSearch && !committeePopoverSearch && (
                        <button
                          onClick={() => setCommitteeSearch("")}
                          className="w-full text-left px-2.5 py-1.5 rounded-md text-xs text-danger-fg hover:bg-danger-soft transition-colors"
                        >
                          <X className="mr-1 inline h-3 w-3 align-[-2px]" aria-hidden />
                          {t("committeeRemoveFilter")}
                        </button>
                      )}
                      {availableCommittees
                        .filter((c) => c.toLowerCase().includes(committeePopoverSearch.toLowerCase()))
                        .map((c) => (
                          <button
                            key={c}
                            onClick={() => setCommitteeSearch(committeeSearch === c ? "" : c)}
                            className={cn(
                              "w-full text-left px-2.5 py-1.5 rounded-md text-xs transition-colors",
                              committeeSearch === c
                                ? "bg-brand-soft text-fg font-medium"
                                : "hover:bg-surface-muted text-fg-muted"
                            )}
                          >
                            {c}
                          </button>
                        ))}
                    </div>
                  </div>
                </PopoverContent>
              </Popover>
            )}

            {/* Sort */}
            <Popover open={sortOpen} onOpenChange={setSortOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-8 text-xs gap-1.5 ml-auto">
                  <ArrowUpDown className="h-3.5 w-3.5" />
                  {SORT_OPTIONS.find((s) => s.value === sortBy)?.label || t("sortDefault")}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-48 p-2" align="end">
                <div className="space-y-1">
                  {SORT_OPTIONS.map((opt) => (
                    <button
                      key={opt.value}
                      onClick={() => { setSortBy(opt.value); setSortOpen(false); }}
                      className={cn(
                        "w-full text-left px-2.5 py-1.5 rounded-md text-xs transition-colors",
                        sortBy === opt.value
                          ? "bg-brand-soft text-fg font-medium"
                          : "hover:bg-surface-muted text-fg-muted"
                      )}
                    >
                      {opt.label}
                    </button>
                  ))}
                </div>
              </PopoverContent>
            </Popover>

            {/* Weights editor: la policy di autorità è editabile, non solo dichiarata */}
            <Popover>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  size="sm"
                  className={cn("h-8 text-xs gap-1.5", weightsCustom && "border-brand text-brand-fg")}
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  {t("weightsButton")}
                  {weightsCustom && (
                    <Pencil className="ml-0.5 h-3 w-3" aria-hidden />
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80 p-3" align="end">
                <p className="text-xs font-semibold text-fg mb-1">{t("weightsPanelTitle")}</p>
                <p className="text-[11px] leading-relaxed text-fg-muted mb-3">
                  {t("weightsPanelDesc")}{" "}
                  <a
                    href="/method"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="link"
                  >
                    {t("methodMore")}
                  </a>
                </p>
                <div className="space-y-2.5">
                  {(Object.keys(DEFAULT_WEIGHTS) as ComponentKey[]).map((k) => {
                    const labelKey = {
                      speeches: "sortSpeeches",
                      acts: "sortActs",
                      committee: "sortCommittee",
                      profession: "sortProfession",
                      education: "sortEducation",
                      role: "sortRole",
                    }[k] as string;
                    return (
                      <div key={k}>
                        <div className="flex items-center justify-between text-[11px] mb-0.5">
                          <span className="text-fg-secondary">{t(labelKey)}</span>
                          <span className="tabular text-fg-muted">
                            {Math.round(weights[k] * 100)}%
                          </span>
                        </div>
                        <Slider
                          min={0}
                          max={50}
                          step={1}
                          value={[Math.round(weights[k] * 100)]}
                          onValueChange={([v]) =>
                            setWeights((prev) => ({ ...prev, [k]: v / 100 }))
                          }
                          className="py-1"
                        />
                      </div>
                    );
                  })}
                </div>
                {weightsCustom && (
                  <button
                    onClick={() => setWeights(DEFAULT_WEIGHTS)}
                    className="mt-3 w-full text-center text-xs text-brand-fg hover:underline pt-2 border-t border-line"
                  >
                    {t("weightsReset")}
                  </button>
                )}
              </PopoverContent>
            </Popover>

            {/* Clear all filters */}
            {hasActiveFilters && (
              <button
                onClick={() => {
                  setCoalitionFilter("all");
                  setSelectedGroups([]);
                  setNameSearch("");
                  setCommitteeSearch("");
                }}
                className="min-h-8 rounded-full px-2.5 text-xs text-fg-muted hover:bg-surface-muted hover:text-fg whitespace-nowrap"
              >
                {t("clearAllFilters")}
              </button>
            )}
          </div>

          {/* Selected group badges */}
          {selectedGroups.length > 0 && (
            <div className="flex flex-wrap gap-1.5 mt-2">
              {selectedGroups.map((gv) => {
                const g = GROUPS.find((gr) => gr.value === gv);
                const groupConfig = config.politicalGroups[gv as keyof typeof config.politicalGroups];
                const color = groupConfig?.color || "var(--fg-muted)";
                return (
                  <Badge
                    key={gv}
                    variant="outline"
                    className="text-xs gap-1 pl-2 pr-1 py-0.5 cursor-pointer hover:bg-danger-soft"
                    style={{ borderColor: color, color }}
                    onClick={() => toggleGroup(gv)}
                  >
                    {g?.shortLabel || gv}
                    <X className="h-3 w-3" />
                  </Badge>
                );
              })}
            </div>
          )}
        </div>}

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          {/* Empty state */}
          {!hasResults && !loading && (
            <div className="flex flex-col items-center justify-center h-full px-4 pb-16">
              <div className="text-center space-y-5 max-w-lg">
                {/* Prompt-as-question + example placeholder (NN/g: the
                    placeholder shows the format, the question says the job) */}
                {/* Landing-hero register: the tool's distinctive phrase gets
                    the italic primary accent, the shared tail stays plain */}
                <h1 className="serif-display text-2xl sm:text-3xl text-fg leading-tight">
                  {t.rich("emptyStateHeading", {
                    em: (chunks) => <span className="italic text-brand-fg">{chunks}</span>,
                  })}
                </h1>
                {/* Search bar */}
                <div className="w-full max-w-md mx-auto">
                  <form onSubmit={(e) => { e.preventDefault(); fetchRanking(topic); }} className="relative">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-fg-muted" aria-hidden />
                    <Input
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                      placeholder={t("topicPlaceholder")}
                      className="h-14 text-lg pl-12 pr-28 rounded-xl"
                    />
                    <Button
                      type="submit"
                      disabled={!topic.trim()}
                      className="absolute right-2 top-1/2 -translate-y-1/2 h-10 px-4"
                    >
                      {t("searchButton")}
                    </Button>
                  </form>
                </div>

                {/* Filtri strutturati prima della query, stessa grammatica di
                    /search: la classifica arriva già filtrata */}
                <div className="w-full max-w-md mx-auto rounded-lg border border-line bg-surface p-4 text-left space-y-4">
                  <div>
                    <p className="mb-2 text-sm font-medium text-fg">{t("coalitionLabel")}</p>
                    <div className="flex gap-1.5">
                      {(["all", "majority", "opposition"] as const).map((c) => (
                        <button
                          key={c}
                          type="button"
                          onClick={() => {
                            setCoalitionFilter(c);
                            setSelectedGroups(selectedGroups.filter((v) => groupAllowedInCoalition(v, c)));
                          }}
                          className={cn(
                            "flex-1 min-h-8 rounded-full border px-2 py-1.5 text-xs transition-colors cursor-pointer",
                            coalitionFilter === c
                              ? "border-brand bg-brand text-on-brand"
                              : "border-line-strong text-fg-secondary hover:text-fg"
                          )}
                        >
                          {c === "all" ? t("coalitionAll") : c === "majority" ? t("coalitionMajority") : t("coalitionOpposition")}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-sm font-medium text-fg">{t("groupFilter")}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {GROUPS.map((g) => {
                        const selected = selectedGroups.includes(g.value);
                        const allowed = groupAllowedInCoalition(g.value, coalitionFilter);
                        return (
                          <button
                            key={g.value}
                            type="button"
                            disabled={!allowed}
                            onClick={() =>
                              setSelectedGroups(
                                selected
                                  ? selectedGroups.filter((v) => v !== g.value)
                                  : [...selectedGroups, g.value]
                              )
                            }
                            className={cn(
                              "rounded-full border px-2.5 py-1 text-xs transition-colors",
                              !allowed
                                ? "border-line text-fg-faint"
                                : selected
                                  ? "border-brand bg-brand-soft text-brand-fg cursor-pointer"
                                  : "border-line-strong text-fg-secondary hover:text-fg cursor-pointer"
                            )}
                          >
                            {g.shortLabel}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-sm font-medium text-fg">{t("committeeFilter")}</p>
                    {committeeSearch ? (
                      <button
                        type="button"
                        onClick={() => setCommitteeSearch("")}
                        title={t("committeeRemoveFilter")}
                        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-brand bg-brand-soft px-2.5 py-1 text-xs text-brand-fg cursor-pointer"
                      >
                        <span className="truncate">{toTitleCase(committeeSearch)}</span>
                        <X className="h-3 w-3 shrink-0" />
                      </button>
                    ) : (
                      <>
                        <Input
                          value={committeeQuery}
                          onChange={(e) => setCommitteeQuery(e.target.value)}
                          placeholder={t("committeeSearchPlaceholder")}
                          className="h-9 text-sm"
                        />
                        {committeeQuery.trim() && (
                          <div className="mt-1.5 max-h-44 overflow-y-auto rounded-md border border-line">
                            {availableCommittees
                              .filter((c) => c.toLowerCase().includes(committeeQuery.trim().toLowerCase()))
                              .slice(0, 30)
                              .map((c) => (
                                <button
                                  key={c}
                                  type="button"
                                  onClick={() => { setCommitteeSearch(c); setCommitteeQuery(""); }}
                                  className="block w-full border-b border-line px-2.5 py-1.5 text-left text-xs text-fg-muted transition-colors last:border-b-0 hover:bg-surface-muted hover:text-fg cursor-pointer"
                                >
                                  {toTitleCase(c)}
                                </button>
                              ))}
                          </div>
                        )}
                      </>
                    )}
                  </div>
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
              <div className="text-center space-y-2">
                <p className="text-sm font-medium text-fg">{t("loadingTitle")}</p>
                <p className="text-xs text-fg-muted">
                  {t("loadingSubtitle", { topic: activeTopic })}
                </p>
              </div>
              {/* Skeleton rows */}
              <div className="w-full max-w-2xl mx-auto space-y-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3 border-b border-line animate-skeleton">
                    <div className="h-5 w-6 bg-surface-sunken rounded-xs shrink-0" />
                    <div className="h-9 w-9 bg-surface-sunken rounded-full shrink-0" />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-4 w-36 bg-surface-sunken rounded-xs" />
                      <div className="h-3 w-24 bg-surface-sunken rounded-xs" />
                    </div>
                    <div className="hidden sm:block h-3 w-20 bg-surface-sunken rounded-xs" />
                    <div className="h-5 w-12 bg-surface-sunken rounded-xs" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Results table */}
          {hasResults && !loading && (
            <div className="container-page py-4">
              {/* Results info */}
              <div className="flex items-center justify-between mb-3">
                <p className="tabular text-xs text-fg-muted flex items-center gap-2 flex-wrap">
                  {filteredDeputies.length === deputies.length
                    ? t("resultsAll", { count: deputies.length })
                    : t("resultsFiltered", { filtered: filteredDeputies.length, total: deputies.length })}
                  {computationTime > 0 && ` · ${(computationTime / 1000).toFixed(1)}s`}
                  {weightsCustom && (
                    <Badge className="text-[10px] h-4 px-1.5">
                      {t("weightsCustom")}
                    </Badge>
                  )}
                </p>
                <FeedbackPulse tool="ranking" context={activeTopic} className="mt-0 pt-0 border-t-0 hidden sm:block" />
                <Button variant="ghost" size="sm" onClick={handleReset} className="h-7 text-xs gap-1.5 sm:hidden">
                  <RotateCcw className="h-3 w-3" />
                  {t("newSearch")}
                </Button>
              </div>

              {/* Methodology note (issue #18, from the ISWC demo reviews) */}
              <details className="mb-4">
                <summary className="cursor-pointer list-none inline-flex items-center gap-1.5 text-xs text-fg-muted hover:text-fg transition-colors">
                  <Info className="h-3.5 w-3.5" aria-hidden />
                  <span className="underline decoration-line-control underline-offset-4">{t("methodTitle")}</span>
                </summary>
                <div className="mt-3 max-w-prose space-y-2 rounded-md bg-surface-muted p-4 text-sm leading-relaxed text-fg-secondary">
                  <p>{t("methodP1")}</p>
                  <p>{t("methodP2")}</p>
                  <p>
                    <a
                      href="/method"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link"
                    >
                      {t("methodMore")}
                    </a>
                  </p>
                </div>
              </details>

              {/* Table header (desktop) */}
              <div className="label-mono hidden sm:grid grid-cols-[3rem_1fr_8rem_6rem_5rem] gap-3 px-4 py-2 border-b border-line">
                <span>{t("colRank")}</span>
                <span>{t("colDeputy")}</span>
                <span>{t("colGroup")}</span>
                <span>{t("colCoalition")}</span>
                <span className="text-right">{t("colScore")}</span>
              </div>

              {/* Rows */}
              {filteredDeputies.length === 0 ? (
                <div className="text-center py-16 text-fg-muted">
                  <Users className="h-8 w-8 mx-auto mb-3 text-fg-faint" aria-hidden />
                  <p className="text-sm">{t("noResultsFiltered")}</p>
                </div>
              ) : (
                <div className="divide-y divide-line">
                  {filteredDeputies.map((deputy, index) => (
                    <RankingRow
                      key={deputy.id}
                      deputy={deputy}
                      index={index}
                      sortBy={sortBy}
                      sortLabel={SORT_OPTIONS.find((s) => s.value === sortBy)?.label || ""}
                      scoreOverride={weightsCustom ? effectiveScore(deputy) : undefined}
                    />
                  ))}
                </div>
              )}

              {/* Micro-feedback a fondo lista solo su mobile (issue #21) */}
              <FeedbackPulse tool="ranking" context={activeTopic} className="max-w-md sm:hidden" />
            </div>
          )}
        </div>
      </main>
    </div>
  );
}

// Falls back to initials when the photo is missing OR fails to load
// (camera.it drops part of the requests when the full list loads).

function DeputyAvatar({ deputy, groupColor }: { deputy: RankingDeputy; groupColor: string }) {
  const [failed, setFailed] = useState(false);

  if (!deputy.photo || failed) {
    return (
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
        style={{ backgroundColor: `${groupColor}1f`, color: groupColor }}
      >
        {deputy.first_name[0]}{deputy.last_name[0]}
      </div>
    );
  }

  return (
    <img
      src={deputy.photo}
      alt={`${deputy.first_name} ${deputy.last_name}`}
      loading="lazy"
      onError={() => setFailed(true)}
      className="h-9 w-9 shrink-0 rounded-full object-cover"
    />
  );
}

interface RankingRowProps {
  deputy: RankingDeputy;
  index: number;
  sortBy: SortKey;
  sortLabel: string;
  /** Punteggio ricombinato con pesi custom; il modal mostra sempre quello ufficiale */
  scoreOverride?: number;
}

function RankingRow({ deputy, index, sortBy, sortLabel, scoreOverride }: RankingRowProps) {
  const t = useTranslations("RankingsPage");
  const [isModalOpen, setIsModalOpen] = useState(false);

  const groupConfig =
    config.politicalGroups[deputy.group as keyof typeof config.politicalGroups];
  const groupColor = groupConfig?.color || "#6B7280";
  const groupLabel = groupConfig?.label || deputy.group;

  const displayScore =
    sortBy === "authority_score"
      ? scoreOverride ?? deputy.authority_score
      : deputy.score_breakdown?.[sortBy] ?? 0;

  return (
    <>
      {/* Desktop row */}
      <div
        className="hidden sm:grid grid-cols-[3rem_1fr_8rem_6rem_5rem] gap-3 items-center px-4 py-2.5 hover:bg-surface-muted transition-colors cursor-pointer group"
        onClick={() => setIsModalOpen(true)}
      >
        {/* Rank */}
        <div className="flex justify-center">
          <span
            className={cn(
              "tabular text-base font-semibold leading-none",
              index < 3 ? "text-fg" : "text-fg-muted"
            )}
          >
            {index + 1}
          </span>
        </div>

        {/* Deputy */}
        <div className="flex items-center gap-3 min-w-0">
          <DeputyAvatar deputy={deputy} groupColor={groupColor} />
          <p className="text-sm font-medium text-fg truncate group-hover:text-brand-fg transition-colors">
            {deputy.first_name} {deputy.last_name}
          </p>
        </div>

        {/* Group */}
        <Badge
          variant="outline"
          className="text-[10px] px-1.5 py-0 h-5 font-medium border truncate justify-center"
          style={{ color: groupColor, borderColor: groupColor }}
        >
          {groupLabel.length > 18 ? groupLabel.substring(0, 18) + "…" : groupLabel}
        </Badge>

        {/* Coalition */}
        <span className="text-xs text-fg-muted capitalize">
          {deputy.coalition === "maggioranza" ? t("coalitionMajority") : t("coalitionOpposition")}
        </span>

        {/* Score */}
        <div className="flex items-center justify-end gap-2">
          <div className="w-12 h-1.5 rounded-full bg-surface-sunken overflow-hidden" aria-hidden>
            <div
              className="h-full rounded-full bg-brand"
              style={{ width: `${displayScore * 100}%` }}
            />
          </div>
          <span className="tabular text-sm font-semibold text-fg min-w-[28px] text-right">
            {(displayScore * 100).toFixed(0)}
          </span>
        </div>
      </div>

      {/* Mobile row */}
      <div
        className="sm:hidden flex items-center gap-3 px-3 py-3 active:bg-surface-muted transition-colors cursor-pointer"
        onClick={() => setIsModalOpen(true)}
      >
        <div className="shrink-0 w-8 flex justify-center">
          <span
            className={cn(
              "tabular text-sm font-semibold leading-none",
              index < 3 ? "text-fg" : "text-fg-muted"
            )}
          >
            {index + 1}
          </span>
        </div>
        <DeputyAvatar deputy={deputy} groupColor={groupColor} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-fg truncate">
            {deputy.first_name} {deputy.last_name}
          </p>
          <p className="text-[10px] text-fg-muted truncate" style={{ color: groupColor }}>
            {groupLabel.length > 22 ? groupLabel.substring(0, 22) + "…" : groupLabel}
          </p>
        </div>
        <span className="tabular text-base font-semibold text-fg">
          {(displayScore * 100).toFixed(0)}
        </span>
      </div>

      <ExpertModal expert={deputy} isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </>
  );
}
