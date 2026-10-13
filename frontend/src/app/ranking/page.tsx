"use client";

import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import {useTranslations, useLocale } from "next-intl";
import { graphQuery } from "@/lib/graph";
import { GroupLogo } from "@/components/entities/GroupLogo";
import { Sidebar, MobileMenuButton } from "@/components/layout";
import { useSidebar } from "@/hooks";
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
  const { isCollapsed, toggle, isMobile, isMobileOpen, closeMobile } = useSidebar();
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
      "MATCH (c:Committee) WHERE coalesce(c.chamber, 'camera') IN ['camera', 'bicamerale'] RETURN c.name AS name ORDER BY name"
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

  // ── Render ──
  return (
    <div className="flex h-dvh bg-background overflow-hidden pb-[calc(4.75rem+env(safe-area-inset-bottom))] md:pb-0">
      <Sidebar
        isCollapsed={isCollapsed}
        onToggle={toggle}
        isMobile={isMobile}
        isMobileOpen={isMobileOpen}
        onCloseMobile={closeMobile}
      />

      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* ── Header ── */}
        <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-3 px-4 sm:px-6 h-14">
            <MobileMenuButton onClick={toggle} />
            <h1 className="[font-family:var(--font-display)] text-lg font-medium tracking-tight whitespace-nowrap">{t("headerTitle")}</h1>

            <div className="flex items-center gap-2 ml-auto shrink-0">
              {activeTopic && !loading && (
                <>
                  <Badge variant="secondary" className="max-w-[180px] truncate text-xs">
                    {activeTopic}
                  </Badge>
                  <Button variant="ghost" size="icon-xs" onClick={handleReset} className="h-6 w-6">
                    <RotateCcw className="h-3 w-3" />
                  </Button>
                </>
              )}
              <Popover>
                <PopoverTrigger asChild>
                  <Button variant="ghost" size="icon" className="h-8 w-8 text-muted-foreground hover:text-foreground" title={t("historyTitle")}>
                    <History className="h-4 w-4" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-72 p-2" align="end">
                  <p className="text-[11px] uppercase tracking-[0.2em] px-2 py-1 text-muted-foreground mb-1">{t("historyHeading")}</p>
                  {rankingHistory.entries.length === 0 ? (
                    <p className="text-xs text-center py-4 text-muted-foreground">{t("historyEmpty")}</p>
                  ) : (
                    <div className="space-y-0.5">
                      {rankingHistory.entries.map((entry) => (
                        <div key={entry.id} className="flex items-center gap-1 group rounded-md hover:bg-muted/60">
                          <button
                            className="flex-1 flex items-center gap-2 px-2 py-1.5 text-left min-w-0"
                            onClick={() => restoreRankingEntry(entry)}
                          >
                            <Clock className="h-3 w-3 shrink-0 text-muted-foreground/60" />
                            <span className="text-xs font-medium truncate">{entry.topic}</span>
                          </button>
                          <button
                            className="shrink-0 p-1.5 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
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
            </div>
          </div>
        </header>

        {/* ── Barra filtri persistente (solo quando ci sono risultati) ── */}
        {filtersEnabled && <div className="sticky top-14 z-20 border-b border-border bg-background/95 backdrop-blur-sm px-4 sm:px-6 py-3 shrink-0">
          <div className="flex flex-wrap items-center gap-2 max-w-6xl">
            {/* Coalition toggle */}
            <div className="flex rounded-lg border border-border overflow-hidden text-xs font-medium">
              {(["all", "majority", "opposition"] as CoalitionFilter[]).map((c) => (
                <button
                  key={c}
                  onClick={() => setCoalitionFilter(c)}
                  className={cn(
                    "px-3 py-1.5 transition-colors capitalize",
                    coalitionFilter === c
                      ? "bg-primary text-primary-foreground"
                      : "bg-background hover:bg-muted text-muted-foreground"
                  )}
                >
                  {c === "all" ? t("coalitionAll") : c === "majority" ? t("coalitionMajority") : t("coalitionOpposition")}
                </button>
              ))}
            </div>

            {/* Name search */}
            <div className="relative flex-1 min-w-[160px] max-w-[220px]">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
              <Input
                value={nameSearch}
                onChange={(e) => setNameSearch(e.target.value)}
                placeholder={t("nameSearchPlaceholder")}
                className="pl-8 h-8 text-xs rounded-lg"
              />
              {nameSearch && (
                <button onClick={() => setNameSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                  <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                </button>
              )}
            </div>

            {/* Group filter */}
            <Popover open={groupsOpen} onOpenChange={(open) => { setGroupsOpen(open); if (!open) setGroupSearch(""); }}>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className={cn("h-9 text-xs gap-1.5", selectedGroups.length > 0 && "border-primary bg-primary/10 text-primary hover:bg-primary/15")}>
                  <Users className="h-3.5 w-3.5" />
                  {t("groupFilter")}
                  {selectedGroups.length > 0 && (
                    <Badge className="ml-1 h-4 w-4 p-0 flex items-center justify-center text-[10px] bg-primary text-primary-foreground">
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
                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                    <Input
                      value={groupSearch}
                      onChange={(e) => setGroupSearch(e.target.value)}
                      placeholder={t("groupSearchPlaceholder")}
                      className="pl-8 h-7 text-xs rounded-md"
                      autoFocus
                    />
                    {groupSearch && (
                      <button onClick={() => setGroupSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                        <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                      </button>
                    )}
                  </div>
                  {GROUPS.filter((g) => g.label.toLowerCase().includes(groupSearch.toLowerCase())).map((g) => {
                    const selected = selectedGroups.includes(g.value);
                    const groupConfig = config.politicalGroups[g.value as keyof typeof config.politicalGroups];
                    const color = groupConfig?.color || "#6B7280";
                    return (
                      <button
                        key={g.value}
                        onClick={() => toggleGroup(g.value)}
                        className={cn(
                          "w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md text-xs transition-colors text-left",
                          selected ? "bg-primary/10 text-foreground" : "hover:bg-muted text-muted-foreground"
                        )}
                      >
                        <GroupLogo group={g.value} size={18} />
                        <span className="truncate flex-1">{g.label}</span>
                        {selected && <span className="text-primary text-[10px] font-bold">✓</span>}
                      </button>
                    );
                  })}
                  {selectedGroups.length > 0 && (
                    <button
                      onClick={() => setSelectedGroups([])}
                      className="w-full text-center text-xs text-destructive hover:underline pt-1 border-t border-border mt-1"
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
                  <Button variant="outline" size="sm" className={cn("h-9 text-xs gap-1.5", committeeSearch !== "" && "border-primary bg-primary/10 text-primary hover:bg-primary/15")}>
                    <Landmark className="h-3.5 w-3.5" />
                    {t("committeeFilter")}
                    {committeeSearch && (
                      <Badge className="ml-1 h-4 px-1 text-[10px] bg-primary text-primary-foreground">1</Badge>
                    )}
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </PopoverTrigger>
                <PopoverContent className="w-80 p-2" align="start">
                  <div className="space-y-1">
                    {/* Search input */}
                    <div className="relative mb-2">
                      <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                      <Input
                        value={committeePopoverSearch}
                        onChange={(e) => setCommitteePopoverSearch(e.target.value)}
                        placeholder={t("committeeSearchPlaceholder")}
                        className="pl-8 h-7 text-xs rounded-md"
                        autoFocus
                      />
                      {committeePopoverSearch && (
                        <button onClick={() => setCommitteePopoverSearch("")} className="absolute right-2 top-1/2 -translate-y-1/2">
                          <X className="h-3 w-3 text-muted-foreground hover:text-foreground" />
                        </button>
                      )}
                    </div>
                    <div className="max-h-52 overflow-y-auto space-y-1">
                      {committeeSearch && !committeePopoverSearch && (
                        <button
                          onClick={() => setCommitteeSearch("")}
                          className="w-full text-left px-2.5 py-1.5 rounded-md text-xs text-destructive hover:bg-destructive/10 transition-colors"
                        >
                          ✕ {t("committeeRemoveFilter")}
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
                                ? "bg-primary/10 text-foreground font-medium"
                                : "hover:bg-muted text-muted-foreground"
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
                          ? "bg-primary/10 text-foreground font-medium"
                          : "hover:bg-muted text-muted-foreground"
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
                  className={cn("h-8 text-xs gap-1.5", weightsCustom && "border-primary text-primary")}
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                  {t("weightsButton")}
                  {weightsCustom && (
                    <Badge className="ml-1 h-4 px-1 text-[10px] bg-primary text-primary-foreground">✎</Badge>
                  )}
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-80 p-3" align="end">
                <p className="text-xs font-semibold text-foreground mb-1">{t("weightsPanelTitle")}</p>
                <p className="text-[11px] leading-relaxed text-muted-foreground mb-3">
                  {t("weightsPanelDesc")}{" "}
                  <a
                    href="/method"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary underline underline-offset-2 hover:text-primary/80"
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
                          <span className="text-foreground/80">{t(labelKey)}</span>
                          <span className="tabular-nums text-muted-foreground">
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
                    className="mt-3 w-full text-center text-xs text-primary hover:underline pt-2 border-t border-border"
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
                className="text-xs text-destructive hover:underline whitespace-nowrap"
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
                const color = groupConfig?.color || "#6B7280";
                return (
                  <Badge
                    key={gv}
                    variant="outline"
                    className="text-xs gap-1 pl-2 pr-1 py-0.5 cursor-pointer hover:bg-destructive/10"
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

        {/* ── Content area ── */}
        <div className="flex-1 overflow-y-auto">
          {/* ── Empty state ── */}
          {!hasResults && !loading && (
            <div className="flex flex-col items-center justify-center h-full px-4 pb-16">
              <div className="text-center space-y-5 max-w-lg">
                {/* Prompt-as-question + example placeholder (NN/g: the
                    placeholder shows the format, the question says the job) */}
                {/* Landing-hero register: the tool's distinctive phrase gets
                    the italic primary accent, the shared tail stays plain */}
                <h2 className="[font-family:var(--font-display)] text-2xl sm:text-3xl font-medium tracking-tight text-foreground leading-tight">
                  {t.rich("emptyStateHeading", {
                    em: (chunks) => <span className="italic text-primary">{chunks}</span>,
                  })}
                </h2>
                {/* Search bar */}
                <div className="w-full max-w-md mx-auto">
                  <form onSubmit={(e) => { e.preventDefault(); fetchRanking(topic); }} className="relative">
                    <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-muted-foreground" />
                    <Input
                      value={topic}
                      onChange={(e) => setTopic(e.target.value)}
                      placeholder={t("topicPlaceholder")}
                      className="h-14 text-lg pl-12 pr-24 rounded-md"
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
                <div className="w-full max-w-md mx-auto rounded-lg border border-border bg-card p-4 text-left space-y-4">
                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{t("coalitionLabel")}</p>
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
                            "flex-1 rounded-md border px-2 py-1.5 text-xs transition-colors cursor-pointer",
                            coalitionFilter === c
                              ? "border-primary bg-primary text-primary-foreground"
                              : "border-border text-muted-foreground hover:text-foreground"
                          )}
                        >
                          {c === "all" ? t("coalitionAll") : c === "majority" ? t("coalitionMajority") : t("coalitionOpposition")}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{t("groupFilter")}</p>
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
                                ? "border-border/50 text-muted-foreground/30"
                                : selected
                                  ? "border-primary bg-primary/10 text-primary cursor-pointer"
                                  : "border-border text-muted-foreground hover:text-foreground cursor-pointer"
                            )}
                          >
                            {g.shortLabel}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                  <div>
                    <p className="mb-2 text-[11px] uppercase tracking-[0.14em] text-muted-foreground">{t("committeeFilter")}</p>
                    {committeeSearch ? (
                      <button
                        type="button"
                        onClick={() => setCommitteeSearch("")}
                        title={t("committeeRemoveFilter")}
                        className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary bg-primary/10 px-2.5 py-1 text-xs text-primary cursor-pointer"
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
                          <div className="mt-1.5 max-h-44 overflow-y-auto rounded-md border border-border">
                            {availableCommittees
                              .filter((c) => c.toLowerCase().includes(committeeQuery.trim().toLowerCase()))
                              .slice(0, 30)
                              .map((c) => (
                                <button
                                  key={c}
                                  type="button"
                                  onClick={() => { setCommitteeSearch(c); setCommitteeQuery(""); }}
                                  className="block w-full border-b border-border/60 px-2.5 py-1.5 text-left text-xs text-muted-foreground transition-colors last:border-b-0 hover:bg-muted hover:text-foreground cursor-pointer"
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
                  <p className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground mb-3">
                    {t("suggestedTopicsLabel")}
                  </p>
                  <div className="flex flex-wrap justify-center gap-x-6 gap-y-3">
                    {getTopics(locale).slice(0, 8).map((t) => (
                      <button
                        key={t}
                        className="group inline-flex items-center gap-1.5 border-b border-border pb-1 text-sm text-left text-foreground/80 transition-colors duration-200 hover:border-foreground hover:text-foreground cursor-pointer"
                        onClick={() => handleTopicClick(t)}
                      >
                        <span>{t.charAt(0).toUpperCase() + t.slice(1)}</span>
                        <ArrowRight className="w-3 h-3 text-muted-foreground/40 transition-colors duration-200 group-hover:text-foreground" />
                      </button>
                    ))}
                  </div>
                </div>

                {error && (
                  <div className="mt-4 text-red-500 text-sm bg-red-50 rounded-lg px-4 py-3 border border-red-200">
                    {error}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Loading ── */}
          {loading && (
            <div className="flex flex-col items-center justify-center h-full px-4 gap-6">
              <div className="text-center space-y-2">
                <p className="text-sm font-medium text-foreground">{t("loadingTitle")}</p>
                <p className="text-xs text-muted-foreground">
                  {t("loadingSubtitle", { topic: activeTopic })}
                </p>
              </div>
              {/* Skeleton rows */}
              <div className="w-full max-w-2xl mx-auto space-y-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3 px-4 py-3 border-b border-border animate-pulse">
                    <div className="h-5 w-6 bg-muted/60 rounded shrink-0" />
                    <div className="h-9 w-9 bg-muted rounded-full shrink-0" />
                    <div className="flex-1 space-y-1.5">
                      <div className="h-4 w-36 bg-muted rounded" />
                      <div className="h-3 w-24 bg-muted/50 rounded" />
                    </div>
                    <div className="hidden sm:block h-3 w-20 bg-muted/40 rounded" />
                    <div className="h-5 w-12 bg-muted/60 rounded" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Results table ── */}
          {hasResults && !loading && (
            <div className="px-4 sm:px-6 py-4 max-w-6xl mx-auto w-full">
              {/* Results info */}
              <div className="flex items-center justify-between mb-3">
                <p className="text-xs text-muted-foreground flex items-center gap-2 flex-wrap">
                  {filteredDeputies.length === deputies.length
                    ? t("resultsAll", { count: deputies.length })
                    : t("resultsFiltered", { filtered: filteredDeputies.length, total: deputies.length })}
                  {computationTime > 0 && ` · ${(computationTime / 1000).toFixed(1)}s`}
                  {weightsCustom && (
                    <Badge variant="outline" className="text-[10px] h-4 px-1.5 border-primary/40 text-primary">
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
                <summary className="cursor-pointer list-none inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors">
                  <Info className="h-3.5 w-3.5" />
                  <span className="border-b border-border pb-0.5">{t("methodTitle")}</span>
                </summary>
                <div className="mt-3 max-w-3xl space-y-2 text-[13px] leading-relaxed text-muted-foreground">
                  <p>{t("methodP1")}</p>
                  <p>{t("methodP2")}</p>
                  <p>
                    <a
                      href="/method"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-primary underline underline-offset-2 hover:text-primary/80 transition-colors"
                    >
                      {t("methodMore")}
                    </a>
                  </p>
                </div>
              </details>

              {/* Table header (desktop) */}
              <div className="hidden sm:grid grid-cols-[3rem_1fr_8rem_6rem_5rem] gap-3 px-4 py-2 text-[11px] uppercase tracking-[0.2em] text-muted-foreground border-b border-border">
                <span>{t("colRank")}</span>
                <span>{t("colDeputy")}</span>
                <span>{t("colGroup")}</span>
                <span>{t("colCoalition")}</span>
                <span className="text-right">{t("colScore")}</span>
              </div>

              {/* Rows */}
              {filteredDeputies.length === 0 ? (
                <div className="text-center py-16 text-muted-foreground">
                  <Users className="h-8 w-8 mx-auto mb-3 opacity-30" />
                  <p className="text-sm">{t("noResultsFiltered")}</p>
                </div>
              ) : (
                <div className="divide-y divide-border">
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

// ── Deputy Avatar ──────────────────────────────────────────────
// Falls back to initials when the photo is missing OR fails to load
// (camera.it drops part of the requests when the full list loads).

function DeputyAvatar({ deputy, groupColor }: { deputy: RankingDeputy; groupColor: string }) {
  const [failed, setFailed] = useState(false);

  if (!deputy.photo || failed) {
    return (
      <div
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
        style={{ backgroundColor: groupColor }}
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

// ── Ranking Row ────────────────────────────────────────────────

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

  const scoreLevel =
    displayScore >= config.authorityScore.high
      ? "high"
      : displayScore >= config.authorityScore.medium
      ? "medium"
      : "low";

  const barColorClass =
    scoreLevel === "high" ? "bg-green-500" : scoreLevel === "medium" ? "bg-amber-500" : "bg-gray-400";

  return (
    <>
      {/* Desktop row */}
      <div
        className="hidden sm:grid grid-cols-[3rem_1fr_8rem_6rem_5rem] gap-3 items-center px-4 py-2.5 hover:bg-muted/40 transition-colors cursor-pointer group"
        onClick={() => setIsModalOpen(true)}
      >
        {/* Rank */}
        <div className="flex justify-center">
          <span
            className={cn(
              "[font-family:var(--font-display)] text-lg tabular-nums leading-none",
              index < 3 ? "text-primary" : "text-muted-foreground/60"
            )}
          >
            {index + 1}
          </span>
        </div>

        {/* Deputy */}
        <div className="flex items-center gap-3 min-w-0">
          <DeputyAvatar deputy={deputy} groupColor={groupColor} />
          <p className="[font-family:var(--font-display)] text-[15px] font-medium tracking-tight text-foreground truncate group-hover:text-primary transition-colors">
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
        <span className="text-xs text-muted-foreground capitalize">
          {deputy.coalition === "maggioranza" ? t("coalitionMajority") : t("coalitionOpposition")}
        </span>

        {/* Score */}
        <div className="flex items-center justify-end gap-2">
          <div className="w-12 h-1.5 rounded-full bg-muted overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", barColorClass)}
              style={{ width: `${displayScore * 100}%` }}
            />
          </div>
          <span className="[font-family:var(--font-display)] text-base font-medium text-foreground min-w-[28px] text-right tabular-nums">
            {(displayScore * 100).toFixed(0)}
          </span>
        </div>
      </div>

      {/* Mobile row */}
      <div
        className="sm:hidden flex items-center gap-3 px-3 py-3 active:bg-muted/40 transition-colors cursor-pointer"
        onClick={() => setIsModalOpen(true)}
      >
        <div className="shrink-0 w-8 flex justify-center">
          <span
            className={cn(
              "[font-family:var(--font-display)] text-base tabular-nums leading-none",
              index < 3 ? "text-primary" : "text-muted-foreground/60"
            )}
          >
            {index + 1}
          </span>
        </div>
        <DeputyAvatar deputy={deputy} groupColor={groupColor} />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-foreground truncate">
            {deputy.first_name} {deputy.last_name}
          </p>
          <p className="text-[10px] text-muted-foreground truncate" style={{ color: groupColor }}>
            {groupLabel.length > 22 ? groupLabel.substring(0, 22) + "…" : groupLabel}
          </p>
        </div>
        <span className="[font-family:var(--font-display)] text-lg font-medium text-foreground tabular-nums">
          {(displayScore * 100).toFixed(0)}
        </span>
      </div>

      <ExpertModal expert={deputy} isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </>
  );
}
