"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { AppBar } from "@/components/shell/AppBar";
import { FeedbackPulse } from "@/components/feedback/FeedbackPulse";
import { DeputySelector, Deputy } from "@/components/search/DeputySelector";
import { deputyUriFromSlug } from "@/lib/graph";
import { GroupSelector } from "@/components/search/GroupSelector";
import { ResultsList, ResultsSkeleton, SearchResultItem } from "@/components/search/ResultsList";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
    Sheet,
    SheetContent,
    SheetHeader,
    SheetTitle,
    SheetFooter,
    SheetClose,
} from "@/components/ui/sheet";
import {
    Search as SearchIcon,
    Loader2,
    FilterX,
    FileText,
    MessageSquareQuote,
    ChevronLeft,
    ChevronRight,
    User,
    Calendar,
    SlidersHorizontal,
    History,
    Clock,
    X,
    ArrowUpDown,
    ArrowUp,
    ArrowDown,
    ArrowRight,
} from "lucide-react";
import { cn, formatDate } from "@/lib/utils";
import { config } from "@/config";
import { useLocalHistory } from "@/hooks/use-local-history";
import {
    Popover,
    PopoverContent,
    PopoverTrigger,
} from "@/components/ui/popover";

const PAGE_SIZE = 20;

// Entity/topic examples for the empty state: the tool searches WHO and WHAT
// gets named in acts and speeches, so the suggestions are real entities, not
// the political themes used by the other tools. Italian terms on purpose:
// the corpus is Italian regardless of the UI language.
const SUGGESTED_SEARCHES = [
    "Eni",
    "Enel",
    "YouTrend",
    "energia nucleare",
    "intelligenza artificiale",
    "Stellantis",
    "terzo settore",
] as const;

export default function SearchPage() {
    const t = useTranslations("SearchPage");

    // Search history
    type SearchHistoryData = {
        query: string;
        authorFilterMode: "all" | "deputy" | "group";
        selectedDeputies: Deputy[];
        selectedGroups: string[];
        startDate: string;
        endDate: string;
        docType: "all" | "speech" | "act";
    };
    const searchHistory = useLocalHistory<SearchHistoryData>("parliamentrag-search-history");

    const restoreSearchEntry = async (data: SearchHistoryData) => {
        setQuery(data.query);
        setAuthorFilterMode(data.authorFilterMode);
        setSelectedDeputies(data.selectedDeputies);
        setSelectedGroups(data.selectedGroups);
        setStartDate(data.startDate);
        setEndDate(data.endDate);
        setDocType(data.docType);
        setHasSearched(true);
        setCurrentPage(1);
        await fetchPage(1, data);
    };

    // Filter state
    const [query, setQuery] = useState("");
    const [selectedDeputies, setSelectedDeputies] = useState<Deputy[]>([]);
    const [selectedGroups, setSelectedGroups] = useState<string[]>([]);
    const [startDate, setStartDate] = useState("");
    const [endDate, setEndDate] = useState("");
    const [docType, setDocType] = useState<"all" | "speech" | "act">("all");
    const [authorFilterMode, setAuthorFilterMode] = useState<"all" | "deputy" | "group">("all");

    // Sort state
    const [sortBy, setSortBy] = useState<"relevance" | "date_desc" | "date_asc">("relevance");

    // Results state
    const [results, setResults] = useState<SearchResultItem[]>([]);
    const [totalResults, setTotalResults] = useState(0);
    const [totalPages, setTotalPages] = useState(0);
    const [currentPage, setCurrentPage] = useState(1);
    const [loading, setLoading] = useState(false);
    const [hasSearched, setHasSearched] = useState(false);

    // Deep link from the entity pages: ?deputy=p123&fn=..&ln=.. preselects
    // the author filter on that deputy, ?group=<name> the group one, and
    // the browse search runs at once (empty query = list by date).
    useEffect(() => {
        const sp = new URLSearchParams(window.location.search);
        const dep = sp.get("deputy");
        const group = sp.get("group");
        if (!dep && !group) return;
        const seeded: SearchHistoryData = dep
            ? {
                  query: "",
                  authorFilterMode: "deputy",
                  selectedDeputies: [
                      {
                          id: deputyUriFromSlug(dep),
                          first_name: sp.get("fn") ?? "",
                          last_name: sp.get("ln") ?? "",
                      },
                  ],
                  selectedGroups: [],
                  startDate: "",
                  endDate: "",
                  docType: "speech",
              }
            : {
                  query: "",
                  authorFilterMode: "group",
                  selectedDeputies: [],
                  selectedGroups: [group as string],
                  startDate: "",
                  endDate: "",
                  docType: "all",
              };
        setAuthorFilterMode(seeded.authorFilterMode);
        setSelectedDeputies(seeded.selectedDeputies);
        setSelectedGroups(seeded.selectedGroups);
        setDocType(seeded.docType);
        setHasSearched(true);
        fetchPage(1, seeded);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Mobile filter sheet state
    const [filterSheetOpen, setFilterSheetOpen] = useState(false);
    const [filterTab, setFilterTab] = useState<"autore" | "tipo" | "periodo">("autore");

    // Mobile history sheet state
    const [historySheetOpen, setHistorySheetOpen] = useState(false);

    const fetchPage = async (
        page: number,
        override?: SearchHistoryData,
        overrideSortBy?: "relevance" | "date_desc" | "date_asc"
    ) => {
        const q = override?.query ?? query;
        const mode = override?.authorFilterMode ?? authorFilterMode;
        const deputies = override?.selectedDeputies ?? selectedDeputies;
        const groups = override?.selectedGroups ?? selectedGroups;
        const sd = override?.startDate ?? startDate;
        const ed = override?.endDate ?? endDate;
        const dt = override?.docType ?? docType;
        const sb = overrideSortBy ?? sortBy;

        // Browse mode: an author filter alone lists that author's record
        const hasAuthor =
            (mode === "deputy" && deputies.length > 0) ||
            (mode === "group" && groups.length > 0);
        if (!q.trim() && !hasAuthor) return;

        setLoading(true);
        setResults([]);

        try {
            const params = new URLSearchParams();
            params.append('q', q);
            params.append('search_type', 'hybrid');
            params.append('doc_type', dt);
            params.append('sort_by', sb);
            params.append('page', String(page));
            params.append('page_size', String(PAGE_SIZE));

            if (deputies.length > 0 && mode === 'deputy') {
                for (const d of deputies) params.append('deputy_id', d.id);
            }
            if (groups.length > 0 && mode === 'group') {
                for (const g of groups) params.append('group', g);
            }
            if (sd) params.append('start_date', sd);
            if (ed) params.append('end_date', ed);

            const res = await fetch(`${config.api.baseUrl}/search/results?${params.toString()}`);
            if (res.ok) {
                const data = await res.json();
                setResults(data.results);
                setTotalResults(data.total);
                setTotalPages(data.total_pages);
                setCurrentPage(data.page);
            }
        } catch (e) {
            console.error(e);
        } finally {
            setLoading(false);
        }
    };

    const hasAuthorFilter =
        (authorFilterMode === "deputy" && selectedDeputies.length > 0) ||
        (authorFilterMode === "group" && selectedGroups.length > 0);

    const handleSearch = async () => {
        setHasSearched(true);
        setCurrentPage(1);
        await fetchPage(1);
        searchHistory.addEntry(query.trim(), {
            query,
            authorFilterMode,
            selectedDeputies,
            selectedGroups,
            startDate,
            endDate,
            docType,
        });
    };

    const runSuggestedSearch = async (topic: string) => {
        const label = topic.charAt(0).toUpperCase() + topic.slice(1);
        setQuery(label);
        setHasSearched(true);
        setCurrentPage(1);
        const snapshot = {
            query: label,
            authorFilterMode,
            selectedDeputies,
            selectedGroups,
            startDate,
            endDate,
            docType,
        };
        await fetchPage(1, snapshot);
        searchHistory.addEntry(label, snapshot);
    };

    const handlePageChange = async (page: number) => {
        await fetchPage(page);
        document.getElementById("search-results")?.scrollIntoView({ behavior: "smooth" });
    };

    const handleSortChange = async (newSort: "relevance" | "date_desc" | "date_asc") => {
        setSortBy(newSort);
        if (hasSearched) {
            setCurrentPage(1);
            await fetchPage(1, undefined, newSort);
        }
    };

    const clearFilters = () => {
        setQuery("");
        setSelectedDeputies([]);
        setSelectedGroups([]);
        setStartDate("");
        setEndDate("");
        setDocType("all");
        setAuthorFilterMode("all");
        setSortBy("relevance");
        setResults([]);
        setTotalResults(0);
        setTotalPages(0);
        setCurrentPage(1);
        setHasSearched(false);
    };

    const handleAuthorModeChange = (mode: "all" | "deputy" | "group") => {
        setAuthorFilterMode(mode);
        if (mode === 'deputy') setSelectedGroups([]);
        if (mode === 'group') setSelectedDeputies([]);
        if (mode === 'all') { setSelectedDeputies([]); setSelectedGroups([]); }
    };

    const getFilterTags = (data: SearchHistoryData): string[] => {
        const tags: string[] = [];
        if (data.authorFilterMode === 'deputy' && data.selectedDeputies.length > 0) {
            tags.push(data.selectedDeputies.length === 1
                ? `${data.selectedDeputies[0].first_name} ${data.selectedDeputies[0].last_name}`
                : t("nDeputies", { count: data.selectedDeputies.length }));
        }
        if (data.authorFilterMode === 'group' && data.selectedGroups.length > 0) {
            tags.push(data.selectedGroups.length === 1 ? data.selectedGroups[0] : t("nGroups", { count: data.selectedGroups.length }));
        }
        if (data.docType !== 'all') {
            tags.push(data.docType === 'speech' ? t("historyTagSpeeches") : t("historyTagActs"));
        }
        if (data.startDate && data.endDate) {
            tags.push(`${formatDate(data.startDate)} → ${formatDate(data.endDate)}`);
        } else if (data.startDate) {
            tags.push(t("historyTagDateFrom", { date: formatDate(data.startDate) }));
        } else if (data.endDate) {
            tags.push(t("historyTagDateTo", { date: formatDate(data.endDate) }));
        }
        return tags;
    };

    // Count of active filters for badge
    const activeFilterCount = [
        authorFilterMode !== "all" && (selectedDeputies.length > 0 || selectedGroups.length > 0),
        docType !== "all",
        !!(startDate || endDate),
    ].filter(Boolean).length;

    const historyAction = (
        <>
            {/* Mobile: apre bottom sheet */}
            <button
                className="md:hidden inline-flex items-center justify-center size-10 shrink-0 rounded-full text-fg-secondary hover:text-fg hover:bg-surface-muted transition-colors"
                title={t("historyButtonTitle")}
                aria-label={t("historyButtonTitle")}
                onClick={() => setHistorySheetOpen(true)}
            >
                <History className="h-4 w-4" />
            </button>

            {/* Desktop: popover */}
            <div className="hidden md:block">
                <Popover>
                    <PopoverTrigger asChild>
                        <button
                            className="inline-flex items-center justify-center size-10 rounded-full text-fg-secondary hover:text-fg hover:bg-surface-muted transition-colors"
                            title={t("historyButtonTitle")}
                            aria-label={t("historyButtonTitle")}
                        >
                            <History className="h-4 w-4" />
                        </button>
                    </PopoverTrigger>
                    <PopoverContent className="w-80 p-2" align="end">
                        <p className="label-mono px-2 py-1 mb-1">{t("historyTitle")}</p>
                        {searchHistory.entries.length === 0 ? (
                            <p className="text-xs text-center py-4 text-fg-muted">{t("noSavedSearches")}</p>
                        ) : (
                            <div className="space-y-0.5">
                                {searchHistory.entries.map((entry) => {
                                    const tags = getFilterTags(entry.data);
                                    return (
                                        <div key={entry.id} className="flex items-start gap-1 group rounded-md hover:bg-surface-muted">
                                            <button
                                                className="flex-1 flex items-start gap-2 px-2 py-2 text-left min-w-0"
                                                onClick={() => restoreSearchEntry(entry.data)}
                                            >
                                                <Clock className="h-3 w-3 shrink-0 text-fg-muted mt-0.5" />
                                                <div className="min-w-0 space-y-1">
                                                    <span className="text-xs font-medium text-fg truncate block">{entry.topic}</span>
                                                    {tags.length > 0 && (
                                                        <div className="flex flex-wrap gap-1">
                                                            {tags.map((tag, i) => (
                                                                <span key={i} className="inline-block text-[10px] px-1.5 py-0.5 rounded-xs bg-surface-sunken text-fg-muted leading-none">
                                                                    {tag}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            </button>
                                            <button
                                                className="shrink-0 p-1.5 mt-0.5 opacity-0 group-hover:opacity-100 text-fg-muted hover:text-danger-fg transition-opacity"
                                                onClick={() => searchHistory.removeEntry(entry.id)}
                                                title={t("removeEntry")}
                                            >
                                                <X className="h-3 w-3" />
                                            </button>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </PopoverContent>
                </Popover>
            </div>
        </>
    );

    return (
        <div className="flex h-dvh flex-col overflow-hidden bg-bg pb-[env(safe-area-inset-bottom)]">
             <AppBar actions={historyAction} />

             <main className="flex-1 min-h-0 flex flex-col overflow-hidden">

                <div className="flex-1 overflow-y-auto py-4 md:py-6">
                    <div className="container-page">
                    <div className={`max-w-4xl space-y-6 md:space-y-8 ${hasSearched ? "pb-20" : "pb-4"}`}>

                        <div className="pt-2">
                            <h1 className="label-mono text-fg-muted">{t("pageTitle")}</h1>
                            {/* Action heading, same register as the other tool
                                pages ("do X"; the eyebrow carries the tool name) */}
                            {!hasSearched && (
                              <h2 className="mt-2 serif-display text-2xl sm:text-3xl text-fg">
                                {t("introDescription")}
                              </h2>
                            )}
                        </div>

                        {/* Search Card */}
                        <div className="rounded-lg border border-line bg-surface overflow-hidden">

                            {/* Search Input */}
                            <div className="p-4 md:p-6 pb-3 md:pb-0">
                                <div className="relative">
                                    <SearchIcon className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-fg-muted" aria-hidden />
                                    <Input
                                        placeholder={t("searchPlaceholder")}
                                        value={query}
                                        onChange={(e) => setQuery(e.target.value)}
                                        onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                                        className="h-14 text-lg pl-12 pr-12 rounded-xl"
                                    />
                                    {query && (
                                        <Button
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => setQuery("")}
                                            className="absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 p-0 text-fg-muted hover:text-fg"
                                        >
                                            <FilterX className="h-4 w-4" />
                                        </Button>
                                    )}
                                </div>
                            </div>

                            {/* Mobile: active-filter chips (the row only exists when
                                 something is set; the Filters button lives in the
                                 action row below) */}
                            <div className={cn("md:hidden px-4 pt-2 pb-0", activeFilterCount === 0 && "hidden")}>
                                <div className="flex items-center gap-2 flex-wrap">
                                    {/* Active filter chips */}
                                    {docType !== "all" && (
                                        <button
                                            onClick={() => setDocType("all")}
                                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-brand-soft text-brand-fg text-xs font-medium"
                                        >
                                            {docType === "speech" ? t("docTypeSpeeches") : t("docTypeActs")}
                                            <X className="h-3 w-3" />
                                        </button>
                                    )}
                                    {authorFilterMode === "deputy" && selectedDeputies.length > 0 && (
                                        <button
                                            onClick={() => { setAuthorFilterMode("all"); setSelectedDeputies([]); }}
                                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-brand-soft text-brand-fg text-xs font-medium"
                                        >
                                            {selectedDeputies.length === 1
                                                ? selectedDeputies[0].last_name
                                                : t("nDeputies", { count: selectedDeputies.length })}
                                            <X className="h-3 w-3" />
                                        </button>
                                    )}
                                    {authorFilterMode === "group" && selectedGroups.length > 0 && (
                                        <button
                                            onClick={() => { setAuthorFilterMode("all"); setSelectedGroups([]); }}
                                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-brand-soft text-brand-fg text-xs font-medium"
                                        >
                                            {selectedGroups.length === 1 ? selectedGroups[0] : t("nGroups", { count: selectedGroups.length })}
                                            <X className="h-3 w-3" />
                                        </button>
                                    )}
                                    {(startDate || endDate) && (
                                        <button
                                            onClick={() => { setStartDate(""); setEndDate(""); }}
                                            className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-brand-soft text-brand-fg text-xs font-medium"
                                        >
                                            {startDate && endDate
                                                ? `${formatDate(startDate)} → ${formatDate(endDate)}`
                                                : startDate
                                                    ? t("historyTagDateFrom", { date: formatDate(startDate) })
                                                    : t("historyTagDateTo", { date: formatDate(endDate) })}
                                            <X className="h-3 w-3" />
                                        </button>
                                    )}

                                </div>
                            </div>

                            {/* Desktop: full filter grid */}
                            <div className="hidden md:block p-6 space-y-5">
                                <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

                                    {/* Left: Author Filter */}
                                    <div className="space-y-3 border-t border-line pt-4">
                                        <div className="flex items-center gap-2 mb-1">
                                            <User className="h-4 w-4 text-fg-muted" aria-hidden />
                                            <Label className="text-sm font-medium text-fg">{t("authorLabel")}</Label>
                                            <span className="text-xs text-fg-muted ml-auto">{t("optional")}</span>
                                        </div>
                                        <div className="inline-flex rounded-full border border-line-strong p-0.5 bg-bg w-full">
                                            {([
                                                { value: "all" as const, label: t("tabAll") },
                                                { value: "deputy" as const, label: t("tabDeputy") },
                                                { value: "group" as const, label: t("tabGroup") },
                                            ]).map((tab) => (
                                                <button
                                                    key={tab.value}
                                                    onClick={() => handleAuthorModeChange(tab.value)}
                                                    className={cn(
                                                        "flex-1 min-h-8 px-3 py-1.5 rounded-full text-sm font-medium transition-colors",
                                                        authorFilterMode === tab.value
                                                            ? "bg-brand text-on-brand"
                                                            : "text-fg-secondary hover:text-fg"
                                                    )}
                                                >
                                                    {tab.label}
                                                </button>
                                            ))}
                                        </div>
                                        <div className="min-h-[42px]">
                                            {authorFilterMode === "all" && (
                                                <p className="text-sm text-fg-muted text-center py-2.5 bg-surface-muted rounded-md">
                                                    {t("allAuthorsPlaceholder")}
                                                </p>
                                            )}
                                            {authorFilterMode === "deputy" && (
                                                <DeputySelector
                                                    selectedDeputies={selectedDeputies}
                                                    onSelect={setSelectedDeputies}
                                                />
                                            )}
                                            {authorFilterMode === "group" && (
                                                <GroupSelector
                                                    selectedGroups={selectedGroups}
                                                    onSelect={setSelectedGroups}
                                                />
                                            )}
                                        </div>
                                    </div>

                                    {/* Right: Doc Type + Date */}
                                    <div className="space-y-5">
                                        <div className="space-y-3 border-t border-line pt-4">
                                            <div className="flex items-center gap-2 mb-1">
                                                <FileText className="h-4 w-4 text-fg-muted" aria-hidden />
                                                <Label className="text-sm font-medium text-fg">{t("docTypeLabel")}</Label>
                                            </div>
                                            <div className="inline-flex rounded-full border border-line-strong p-0.5 bg-bg w-full">
                                                {([
                                                    { value: "all" as const, label: t("tabAll"), icon: null },
                                                    { value: "speech" as const, label: t("docTypeSpeeches"), icon: MessageSquareQuote },
                                                    { value: "act" as const, label: t("docTypeActs"), icon: FileText },
                                                ]).map((tab) => (
                                                    <button
                                                        key={tab.value}
                                                        onClick={() => setDocType(tab.value)}
                                                        className={cn(
                                                            "flex-1 min-h-8 flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-full text-sm font-medium transition-colors",
                                                            docType === tab.value
                                                                ? "bg-brand text-on-brand"
                                                                : "text-fg-secondary hover:text-fg"
                                                        )}
                                                    >
                                                        {tab.icon && <tab.icon className="h-3.5 w-3.5" />}
                                                        {tab.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>

                                        <div className="space-y-3 border-t border-line pt-4">
                                            <div className="flex items-center gap-2 mb-1">
                                                <Calendar className="h-4 w-4 text-fg-muted" aria-hidden />
                                                <Label className="text-sm font-medium text-fg">{t("periodLabel")}</Label>
                                                <span className="text-xs text-fg-muted ml-auto">{t("optional")}</span>
                                            </div>
                                            <div className="grid grid-cols-2 gap-3">
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs text-fg-muted">{t("periodFrom")}</Label>
                                                    <Input
                                                        type="date"
                                                        value={startDate}
                                                        onChange={(e) => setStartDate(e.target.value)}
                                                        className="h-9"
                                                    />
                                                </div>
                                                <div className="space-y-1.5">
                                                    <Label className="text-xs text-fg-muted">{t("periodTo")}</Label>
                                                    <Input
                                                        type="date"
                                                        value={endDate}
                                                        onChange={(e) => setEndDate(e.target.value)}
                                                        className="h-9"
                                                    />
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                            </div>

                            {/* Action Buttons (always visible) */}
                            <div className="px-4 md:px-6 pb-4 md:pb-6 pt-3 flex gap-3">
                                {/* Mobile: Filters beside the CTA instead of on a row of its own */}
                                <Button
                                    variant="outline"
                                    size="lg"
                                    onClick={() => setFilterSheetOpen(true)}
                                    className={cn(
                                        "md:hidden h-12 px-4 shrink-0",
                                        activeFilterCount > 0
                                            ? "border-brand text-brand-fg bg-brand-soft"
                                            : "text-fg-muted"
                                    )}
                                >
                                    <SlidersHorizontal className="h-4 w-4" />
                                    {activeFilterCount > 0 && (
                                        <span className="ml-1.5 inline-flex items-center justify-center w-4 h-4 rounded-full bg-brand text-on-brand text-[10px] font-bold leading-none">
                                            {activeFilterCount}
                                        </span>
                                    )}
                                </Button>
                                <Button
                                    size="lg"
                                    disabled={(!query.trim() && !hasAuthorFilter) || loading}
                                    onClick={handleSearch}
                                    // While searching the button must read "working",
                                    // not "washed out": keep the primary fill
                                    className={cn(
                                        "flex-1 h-12 text-base font-semibold",
                                        loading && "disabled:opacity-100"
                                    )}
                                >
                                    {loading ? <Loader2 className="mr-2 h-5 w-5 animate-spin" /> : <SearchIcon className="mr-2 h-5 w-5" />}
                                    {t("searchButton")}
                                </Button>
                                {hasSearched && (
                                    <Button
                                        variant="outline"
                                        size="lg"
                                        onClick={clearFilters}
                                        className="h-12 px-5 text-fg-muted"
                                    >
                                        <FilterX className="mr-2 h-4 w-4" />
                                        {t("resetButton")}
                                    </Button>
                                )}
                            </div>
                        </div>

                        {/* Suggested searches: the empty page must always offer
                            something tappable, same affordance as the other tools */}
                        {!hasSearched && (
                            <div className="pt-1 text-center">
                                <p className="label-mono mb-3">{t("suggestedTopicsLabel")}</p>
                                <div className="flex flex-wrap justify-center gap-2">
                                    {SUGGESTED_SEARCHES.map((topic) => (
                                        <button
                                            key={topic}
                                            className="group inline-flex min-h-9 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3.5 text-sm text-left text-fg-secondary transition-colors duration-200 hover:border-line-control hover:text-fg active:scale-[0.98] cursor-pointer"
                                            onClick={() => runSuggestedSearch(topic)}
                                        >
                                            <span>{topic.charAt(0).toUpperCase() + topic.slice(1)}</span>
                                            <ArrowRight className="w-3 h-3 text-fg-faint transition-colors duration-200 group-hover:text-fg" />
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Search Stats & Results */}
                        {(hasSearched) && (
                            <div id="search-results" className="animate-in fade-in slide-in-from-bottom-4 duration-500 space-y-4">

                                {/* Results header */}
                                <div className="px-2 space-y-3">
                                    <div className="border-b border-line pb-3 space-y-1">
                                        <div className="flex items-center justify-between gap-4">
                                            <h2 className="text-xl font-semibold tracking-[var(--tracking-heading)] text-fg">{t("resultsHeading")}</h2>
                                            {results.length > 0 && !loading && (
                                                <FeedbackPulse tool="search" context={query} className="mt-0 pt-0 border-t-0 hidden sm:block shrink-0" />
                                            )}
                                        </div>
                                        <p className="text-sm text-fg-muted flex items-center gap-2">
                                            {/* Durante il caricamento niente "0 results": il conteggio
                                                appare solo a ricerca completata */}
                                            <span>{loading ? t("searching") : t("resultsCount", { count: totalResults })}</span>
                                            {results.length > 0 && (
                                                <>
                                                    <span className="text-fg-faint" aria-hidden>·</span>
                                                    <span>{t("paginationInfo", { current: currentPage, total: totalPages })}</span>
                                                </>
                                            )}
                                        </p>
                                    </div>

                                    {/* Sort controls: riga dedicata, label sempre visibili */}
                                    {results.length > 0 && (
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-fg-muted shrink-0">{t("sortLabel")}</span>
                                            <div className="inline-flex rounded-full border border-line-strong p-0.5 bg-surface flex-1 sm:flex-none">
                                                {([
                                                    { value: "relevance" as const, label: t("sortRelevance"), icon: ArrowUpDown },
                                                    { value: "date_desc" as const, label: t("sortNewest"), icon: ArrowDown },
                                                    { value: "date_asc" as const, label: t("sortOldest"), icon: ArrowUp },
                                                ]).map((opt) => (
                                                    <button
                                                        key={opt.value}
                                                        onClick={() => handleSortChange(opt.value)}
                                                        className={cn(
                                                            "flex-1 sm:flex-none min-h-8 inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                                                            sortBy === opt.value
                                                                ? "bg-brand text-on-brand"
                                                                : "text-fg-secondary hover:text-fg"
                                                        )}
                                                    >
                                                        <opt.icon className="h-3.5 w-3.5 shrink-0" />
                                                        {opt.label}
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>

                                {loading ? (
                                    <ResultsSkeleton />
                                ) : (
                                    <>
                                        <ResultsList results={results} query={query} />

                                        {/* Pagination */}
                                        {totalPages > 1 && (
                                            <div className="flex items-center justify-center gap-1 sm:gap-2 pt-4 flex-wrap">
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    disabled={currentPage <= 1}
                                                    onClick={() => handlePageChange(currentPage - 1)}
                                                >
                                                    <ChevronLeft className="h-4 w-4 sm:mr-1" />
                                                    <span className="hidden sm:inline">{t("previousPage")}</span>
                                                </Button>

                                                <div className="flex items-center gap-1">
                                                    {generatePageNumbers(currentPage, totalPages).map((p, i) =>
                                                        p === "..." ? (
                                                            <span key={`ellipsis-${i}`} className="px-1 sm:px-2 text-fg-muted">...</span>
                                                        ) : (
                                                            <Button
                                                                key={p}
                                                                variant={p === currentPage ? "default" : "outline"}
                                                                size="sm"
                                                                className="w-8 h-8 sm:w-9 sm:h-9 p-0"
                                                                onClick={() => handlePageChange(p as number)}
                                                            >
                                                                {p}
                                                            </Button>
                                                        )
                                                    )}
                                                </div>

                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    disabled={currentPage >= totalPages}
                                                    onClick={() => handlePageChange(currentPage + 1)}
                                                >
                                                    <span className="hidden sm:inline">{t("nextPage")}</span>
                                                    <ChevronRight className="h-4 w-4 sm:ml-1" />
                                                </Button>
                                            </div>
                                        )}

                                        {/* Micro-feedback a fondo lista solo su mobile (issue #21) */}
                                        {results.length > 0 && (
                                            <FeedbackPulse tool="search" context={query} className="max-w-md sm:hidden" />
                                        )}
                                    </>
                                )}
                            </div>
                        )}
                    </div>
                    </div>
                </div>
             </main>

            {/* Mobile history sheet */}
            <Sheet open={historySheetOpen} onOpenChange={setHistorySheetOpen}>
                <SheetContent side="bottom" showCloseButton={false} className="rounded-t-2xl max-h-[80vh] flex flex-col p-0">
                    <SheetHeader className="px-4 pt-4 pb-3 shrink-0 border-b border-line">
                        <div className="flex items-center justify-between">
                            <SheetTitle className="flex items-center gap-2 text-base">
                                <History className="h-4 w-4 text-fg-muted" aria-hidden />
                                {t("historyTitle")}
                            </SheetTitle>
                            <SheetClose asChild>
                                <button className="inline-flex items-center justify-center h-9 w-9 rounded-full text-fg-muted hover:text-fg hover:bg-surface-muted">
                                    <X className="h-4 w-4" />
                                </button>
                            </SheetClose>
                        </div>
                    </SheetHeader>
                    <div className="flex-1 overflow-y-auto py-2">
                        {searchHistory.entries.length === 0 ? (
                            <p className="text-sm text-center py-10 text-fg-muted">{t("noSavedSearches")}</p>
                        ) : (
                            <div className="px-4 space-y-0.5 pb-8">
                                {searchHistory.entries.map((entry) => {
                                    const tags = getFilterTags(entry.data);
                                    return (
                                        <div key={entry.id} className="flex items-start gap-1 group rounded-md hover:bg-surface-muted">
                                            <button
                                                className="flex-1 flex items-start gap-3 px-2 py-3 text-left min-w-0"
                                                onClick={() => { restoreSearchEntry(entry.data); setHistorySheetOpen(false); }}
                                            >
                                                <Clock className="h-4 w-4 shrink-0 text-fg-muted mt-0.5" />
                                                <div className="min-w-0 space-y-1">
                                                    <span className="text-sm font-medium text-fg truncate block">{entry.topic}</span>
                                                    {tags.length > 0 && (
                                                        <div className="flex flex-wrap gap-1">
                                                            {tags.map((tag, i) => (
                                                                <span key={i} className="inline-block text-xs px-2 py-0.5 rounded-xs bg-surface-sunken text-fg-muted leading-none">
                                                                    {tag}
                                                                </span>
                                                            ))}
                                                        </div>
                                                    )}
                                                </div>
                                            </button>
                                            <button
                                                className="shrink-0 p-2.5 mt-0.5 text-fg-muted hover:text-danger-fg transition-colors"
                                                onClick={() => searchHistory.removeEntry(entry.id)}
                                                title={t("removeEntry")}
                                            >
                                                <X className="h-4 w-4" />
                                            </button>
                                        </div>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                </SheetContent>
            </Sheet>

            {/* Mobile filter sheet */}
            <Sheet open={filterSheetOpen} onOpenChange={setFilterSheetOpen}>
                <SheetContent side="bottom" showCloseButton={false} className="rounded-t-2xl max-h-[90vh] flex flex-col p-0">
                    <SheetHeader className="px-4 pt-4 pb-0 shrink-0">
                        <div className="flex items-center justify-between">
                            <SheetTitle className="text-base">{t("filterSheetTitle")}</SheetTitle>
                            <SheetClose asChild>
                                <button className="inline-flex items-center justify-center h-9 w-9 rounded-full text-fg-muted hover:text-fg hover:bg-surface-muted">
                                    <X className="h-4 w-4" />
                                </button>
                            </SheetClose>
                        </div>

                        {/* Tab bar */}
                        <div className="flex gap-1 mt-3 border-b border-line pb-0">
                            {([
                                { key: "autore" as const, label: t("filterTabAuthor"), icon: User,
                                  active: authorFilterMode !== "all" && (selectedDeputies.length > 0 || selectedGroups.length > 0) },
                                { key: "tipo" as const, label: t("filterTabType"), icon: FileText,
                                  active: docType !== "all" },
                                { key: "periodo" as const, label: t("filterTabPeriod"), icon: Calendar,
                                  active: !!(startDate || endDate) },
                            ]).map((tab) => (
                                <button
                                    key={tab.key}
                                    onClick={() => setFilterTab(tab.key)}
                                    className={cn(
                                        "flex items-center gap-1.5 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors -mb-px",
                                        filterTab === tab.key
                                            ? "border-brand text-brand-fg"
                                            : "border-transparent text-fg-muted hover:text-fg"
                                    )}
                                >
                                    <tab.icon className="h-3.5 w-3.5" />
                                    {tab.label}
                                    {tab.active && (
                                        <span className="inline-flex items-center justify-center w-1.5 h-1.5 rounded-full bg-brand" />
                                    )}
                                </button>
                            ))}
                        </div>
                    </SheetHeader>

                    {/* Tab content */}
                    <div className="flex-1 overflow-y-auto px-4 py-4">

                        {/* Autore tab */}
                        {filterTab === "autore" && (
                            <div className="space-y-4">
                                <div className="inline-flex rounded-full border border-line-strong p-0.5 bg-bg w-full">
                                    {([
                                        { value: "all" as const, label: t("tabAll") },
                                        { value: "deputy" as const, label: t("tabDeputy") },
                                        { value: "group" as const, label: t("tabGroup") },
                                    ]).map((tab) => (
                                        <button
                                            key={tab.value}
                                            onClick={() => handleAuthorModeChange(tab.value)}
                                            className={cn(
                                                "flex-1 min-h-10 px-3 py-2 rounded-full text-sm font-medium transition-colors",
                                                authorFilterMode === tab.value
                                                    ? "bg-brand text-on-brand"
                                                    : "text-fg-secondary hover:text-fg"
                                            )}
                                        >
                                            {tab.label}
                                        </button>
                                    ))}
                                </div>

                                <div className="min-h-[60px]">
                                    {authorFilterMode === "all" && (
                                        <p className="text-sm text-fg-muted text-center py-4 bg-surface-muted rounded-md">
                                            {t("allAuthorsPlaceholder")}
                                        </p>
                                    )}
                                    {authorFilterMode === "deputy" && (
                                        <DeputySelector
                                            selectedDeputies={selectedDeputies}
                                            onSelect={setSelectedDeputies}
                                        />
                                    )}
                                    {authorFilterMode === "group" && (
                                        <GroupSelector
                                            selectedGroups={selectedGroups}
                                            onSelect={setSelectedGroups}
                                        />
                                    )}
                                </div>
                            </div>
                        )}

                        {/* Tipo tab */}
                        {filterTab === "tipo" && (
                            <div className="space-y-3">
                                <p className="text-sm text-fg-muted">{t("typeTabDescription")}</p>
                                <div className="grid grid-cols-3 gap-3">
                                    {([
                                        { value: "all" as const, label: t("tabAll"), icon: null, desc: t("docTypeAllDesc") },
                                        { value: "speech" as const, label: t("docTypeSpeeches"), icon: MessageSquareQuote, desc: t("docTypeSpeechDesc") },
                                        { value: "act" as const, label: t("docTypeActs"), icon: FileText, desc: t("docTypeActDesc") },
                                    ]).map((opt) => (
                                        <button
                                            key={opt.value}
                                            onClick={() => setDocType(opt.value)}
                                            className={cn(
                                                "flex flex-col items-center gap-2 p-4 rounded-md border transition-colors text-center",
                                                docType === opt.value
                                                    ? "border-brand bg-brand-soft text-brand-fg"
                                                    : "border-line-strong text-fg-secondary hover:border-line-control hover:text-fg"
                                            )}
                                        >
                                            {opt.icon ? (
                                                <opt.icon className="h-5 w-5" />
                                            ) : (
                                                <SearchIcon className="h-5 w-5" />
                                            )}
                                            <span className="text-sm font-semibold">{opt.label}</span>
                                            <span className="text-[11px] text-fg-muted leading-tight">{opt.desc}</span>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        )}

                        {/* Periodo tab */}
                        {filterTab === "periodo" && (
                            <div className="space-y-4">
                                <p className="text-sm text-fg-muted">{t("periodTabDescription")}</p>
                                <div className="grid grid-cols-2 gap-4">
                                    <div className="space-y-1.5">
                                        <Label className="text-sm font-medium">{t("startDateLabel")}</Label>
                                        <Input
                                            type="date"
                                            value={startDate}
                                            onChange={(e) => setStartDate(e.target.value)}
                                            className="h-11"
                                        />
                                    </div>
                                    <div className="space-y-1.5">
                                        <Label className="text-sm font-medium">{t("endDateLabel")}</Label>
                                        <Input
                                            type="date"
                                            value={endDate}
                                            onChange={(e) => setEndDate(e.target.value)}
                                            className="h-11"
                                        />
                                    </div>
                                </div>
                                {(startDate || endDate) && (
                                    <button
                                        onClick={() => { setStartDate(""); setEndDate(""); }}
                                        className="text-xs text-fg-muted hover:text-danger-fg flex items-center gap-1 transition-colors"
                                    >
                                        <X className="h-3 w-3" />
                                        {t("removePeriodFilter")}
                                    </button>
                                )}
                            </div>
                        )}
                    </div>

                    {/* Sheet footer */}
                    <SheetFooter className="px-4 pb-6 pt-3 shrink-0 border-t border-line">
                        <SheetClose asChild>
                            <Button className="w-full h-12 text-base font-semibold">
                                {t("applyFilters")}
                                {activeFilterCount > 0 && (
                                    <span className="ml-2 inline-flex items-center justify-center w-5 h-5 rounded-full bg-on-brand/20 text-[11px] font-bold">
                                        {activeFilterCount}
                                    </span>
                                )}
                            </Button>
                        </SheetClose>
                    </SheetFooter>
                </SheetContent>
            </Sheet>
        </div>
    );
}

function generatePageNumbers(current: number, total: number): (number | "...")[] {
    if (total <= 7) {
        return Array.from({ length: total }, (_, i) => i + 1);
    }

    const pages: (number | "...")[] = [1];

    if (current > 3) {
        pages.push("...");
    }

    const start = Math.max(2, current - 1);
    const end = Math.min(total - 1, current + 1);

    for (let i = start; i <= end; i++) {
        pages.push(i);
    }

    if (current < total - 2) {
        pages.push("...");
    }

    pages.push(total);
    return pages;
}
