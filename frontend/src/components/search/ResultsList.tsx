"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { MessageSquareQuote, Calendar, FileText, ExternalLink, User, Building2, Tag } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { config } from "@/config";
import { ResultDetailDialog } from "./ResultDetailDialog";

export interface SearchResultItem {
  type: "speech" | "act";
  id: string;
  text: string;
  date: string;
  session_number: number | null;
  /** Pagina ufficiale dell'intervento (Senato); assente per la Camera */
  url?: string | null;
  debate_title: string | null;
  first_name: string;
  last_name: string;
  group: string;
  act_type: string | null;
  act_title: string | null;
  act_number: string | null;
  destinatario: string | null;
  eurovoc: string | null;
  score: number | null;
  match_type: "text" | "semantic";
  is_exact?: boolean;
}

interface ResultsListProps {
  results: SearchResultItem[];
  query: string;
}

// Act type → short label
const ACT_TYPE_SHORT: Record<string, string> = {
  "INTERROGAZIONE A RISPOSTA IN COMMISSIONE": "Interrogazione",
  "INTERROGAZIONE A RISPOSTA SCRITTA": "Interrogazione scritta",
  "INTERROGAZIONE A RISPOSTA IMMEDIATA": "Question time",
  "INTERROGAZIONE A RISPOSTA ORALE": "Interrogazione orale",
  "MOZIONE": "Mozione",
  "ORDINE DEL GIORNO": "OdG",
  "PROPOSTA DI LEGGE": "PDL",
  "RISOLUZIONE IN COMMISSIONE": "Risoluzione",
  "RISOLUZIONE IN ASSEMBLEA": "Risoluzione",
  "INTERPELLANZA URGENTE": "Interpellanza",
  "INTERPELLANZA": "Interpellanza",
};

// Act type → color classes
const ACT_TYPE_COLORS: Record<string, string> = {
  "INTERROGAZIONE": "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
  "MOZIONE": "bg-purple-100 text-purple-800 dark:bg-purple-900/40 dark:text-purple-300",
  "ORDINE DEL GIORNO": "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  "PROPOSTA DI LEGGE": "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
  "RISOLUZIONE": "bg-teal-100 text-teal-800 dark:bg-teal-900/40 dark:text-teal-300",
  "INTERPELLANZA": "bg-indigo-100 text-indigo-800 dark:bg-indigo-900/40 dark:text-indigo-300",
};

export function getActTypeLabel(tipo: string): string {
  if (!tipo) return "Atto";
  const exact = ACT_TYPE_SHORT[tipo.toUpperCase()];
  if (exact) return exact;
  for (const [key, label] of Object.entries(ACT_TYPE_SHORT)) {
    if (tipo.toUpperCase().includes(key) || key.includes(tipo.toUpperCase())) {
      return label;
    }
  }
  return tipo.length > 30 ? tipo.slice(0, 30) + "..." : tipo;
}

export function getActTypeColor(tipo: string): string {
  if (!tipo) return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
  const upper = tipo.toUpperCase();
  for (const [key, color] of Object.entries(ACT_TYPE_COLORS)) {
    if (upper.includes(key)) return color;
  }
  return "bg-gray-100 text-gray-800 dark:bg-gray-800 dark:text-gray-300";
}

export function getGroupColor(groupName: string): string {
  const entry = (config.politicalGroups as Record<string, { color: string }>)[groupName];
  return entry?.color || "#9E9E9E";
}

export function getGroupShortLabel(groupName: string): string {
  if (!groupName) return "";
  const entry = (config.politicalGroups as Record<string, { color: string; label: string }>)[groupName];
  if (entry?.label) {
    const label = entry.label;
    if (label.length > 25) return label.split(" - ")[0].split("(")[0].trim();
    return label;
  }
  if (groupName.length > 25) return groupName.split(" - ")[0].split("(")[0].trim();
  return groupName;
}

export function ResultsList({ results, query }: ResultsListProps) {
  const t = useTranslations("SearchPage");
  const locale = useLocale();
  const [selectedItem, setSelectedItem] = useState<SearchResultItem | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const handleCardClick = (item: SearchResultItem) => {
    setSelectedItem(item);
    setDialogOpen(true);
  };

  if (results.length === 0) {
    return (
      <div className="text-center py-12 text-muted-foreground border-2 border-dashed rounded-lg">
        {t("noResults")}
      </div>
    );
  }

  const formatDate = (dateString: string) => {
    try {
      if (!dateString) return "";
      const date = new Date(dateString);
      if (isNaN(date.getTime())) return dateString;
      return date.toLocaleDateString(locale, {
        day: "numeric",
        month: "long",
        year: "numeric"
      });
    } catch {
      return dateString;
    }
  };

  const highlightText = (text: string, highlight: string) => {
    if (!text) return "";
    if (!highlight.trim()) return text;
    try {
      const escaped = highlight.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
      const parts = text.split(new RegExp(`(${escaped})`, 'gi'));
      return (
        <span>
          {parts.map((part, i) =>
            part.toLowerCase() === highlight.toLowerCase() ? (
              <span key={i} className="bg-yellow-200 dark:bg-yellow-900/50 text-foreground font-medium px-0.5 rounded">
                {part}
              </span>
            ) : (
              part
            )
          )}
        </span>
      );
    } catch {
      return text;
    }
  };

  return (
    <>
      <div className="space-y-4">
        {results.map((item, idx) => {
          const showExactHeader = !!item.is_exact && idx === 0;
          const showSemanticHeader = !item.is_exact && (idx === 0 || !!results[idx - 1].is_exact);
          const card = item.type === "act" ? (
            <ActCard item={item} query={query} formatDate={formatDate} highlightText={highlightText} onClick={() => handleCardClick(item)} />
          ) : (
            <SpeechCard item={item} query={query} formatDate={formatDate} highlightText={highlightText} onClick={() => handleCardClick(item)} />
          );
          return (
            <div key={`${item.id}-${idx}`} className="space-y-4">
              {showExactHeader && <SectionHeader label={t("exactSectionTitle")} />}
              {showSemanticHeader && <SectionHeader label={t("semanticSectionTitle")} />}
              {card}
            </div>
          );
        })}
      </div>

      <ResultDetailDialog
        item={selectedItem}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </>
  );
}

/* ─── Loading Skeleton ─── */

export function ResultsSkeleton() {
  return (
    <div className="space-y-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <Card key={i} className="overflow-hidden">
          <CardHeader className="bg-muted/30 pb-3 pt-4 px-4">
            <div className="flex justify-between items-start gap-4 flex-wrap">
              <div className="space-y-2 flex-1 min-w-0">
                <Skeleton className="h-4 w-56 max-w-full" />
                <Skeleton className="h-3 w-72 max-w-full" />
              </div>
              <Skeleton className="h-5 w-24 shrink-0" />
            </div>
          </CardHeader>
          <CardContent className="pt-4 px-4 pb-4">
            <div className="flex items-center gap-2 mb-3">
              <Skeleton className="h-4 w-4 rounded-full" />
              <Skeleton className="h-4 w-36" />
              <Skeleton className="h-4 w-20" />
            </div>
            <div className="pl-4 border-l-2 border-muted space-y-2">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-2/3" />
            </div>
            <div className="mt-4 flex items-center justify-between">
              <Skeleton className="h-3 w-24" />
              <Skeleton className="h-3 w-32" />
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}

/* ─── Section Header ─── */

function SectionHeader({ label }: { label: string }) {
  return (
    <div className="flex items-center gap-3 pt-2">
      <span className="text-[11px] uppercase tracking-[0.2em] text-muted-foreground whitespace-nowrap">
        {label}
      </span>
      <div className="flex-1 h-px bg-border" />
    </div>
  );
}

/* ─── Speech Card ─── */

function SpeechCard({
  item,
  query,
  formatDate,
  highlightText,
  onClick,
}: {
  item: SearchResultItem;
  query: string;
  formatDate: (s: string) => string;
  highlightText: (text: string, q: string) => React.ReactNode;
  onClick: () => void;
}) {
  const t = useTranslations("SearchPage");
  const groupColor = getGroupColor(item.group);

  return (
    <Card className="overflow-hidden hover:shadow-md transition-shadow cursor-pointer" onClick={onClick}>
      <CardHeader className="bg-muted/30 pb-3 pt-4 px-4">
        <div className="flex justify-between items-start gap-4 flex-wrap">
          <div className="space-y-1.5 flex-1 min-w-0">
            <div className="flex items-center gap-2 text-base font-medium">
              <MessageSquareQuote className="h-4 w-4 text-primary shrink-0" />
              <span>{t("sessionOf", { number: item.session_number ?? "", date: formatDate(item.date) })}</span>
            </div>
            {item.debate_title && (
              <p className="text-sm text-muted-foreground line-clamp-1 pl-6">
                {item.debate_title}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {!item.is_exact && item.score != null && (
              <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                {t("sortRelevance")} {(item.score * 100).toFixed(0)}%
              </span>
            )}
            <Badge variant="outline" className="whitespace-nowrap gap-1">
              <MessageSquareQuote className="h-3 w-3" />
              {t("speechBadge")}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4 px-4 pb-4">
        {/* Deputy info */}
        <div className="flex items-center gap-2 mb-3">
          <User className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="font-semibold text-sm text-foreground">
            {item.first_name} {item.last_name}
          </span>
          <Badge
            variant="secondary"
            className="text-xs px-2 py-0"
            style={{ backgroundColor: `${groupColor}20`, color: groupColor, borderColor: `${groupColor}40` }}
          >
            {getGroupShortLabel(item.group)}
          </Badge>
        </div>

        {/* Text */}
        <div className="pl-4 pr-1 border-l-2 border-primary/20 text-sm leading-relaxed text-muted-foreground break-words overflow-hidden max-w-full">
          {highlightText(item.text, query)}
        </div>

        {/* Footer */}
        <div className="mt-4 flex items-center justify-between">
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            {formatDate(item.date)}
          </div>
          {(item.url || item.session_number) && (
            <a
              href={item.url || `https://www.camera.it/leg19/410?idSeduta=${item.session_number}&tipo=seduta`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-primary hover:underline flex items-center gap-1"
              onClick={(e) => e.stopPropagation()}
            >
              {t("officialSource")} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

/* ─── Act Card ─── */

function ActCard({
  item,
  query,
  formatDate,
  highlightText,
  onClick,
}: {
  item: SearchResultItem;
  query: string;
  formatDate: (s: string) => string;
  highlightText: (text: string, q: string) => React.ReactNode;
  onClick: () => void;
}) {
  const t = useTranslations("SearchPage");
  const groupColor = getGroupColor(item.group);
  const typeLabel = getActTypeLabel(item.act_type || "");
  const typeColor = getActTypeColor(item.act_type || "");

  // Parse EuroVoc topics
  const topics = item.eurovoc
    ? item.eurovoc.split(";").map(t => t.trim()).filter(Boolean).slice(0, 4)
    : [];

  return (
    <Card className="overflow-hidden hover:shadow-md transition-shadow cursor-pointer" onClick={onClick}>
      <CardHeader className="bg-emerald-50/50 dark:bg-emerald-950/20 pb-3 pt-4 px-4">
        <div className="flex justify-between items-start gap-4 flex-wrap">
          <div className="space-y-1.5 flex-1 min-w-0">
            {/* Act type + number */}
            <div className="flex items-center gap-2 flex-wrap">
              <FileText className="h-4 w-4 text-emerald-600 dark:text-emerald-400 shrink-0" />
              <Badge className={`text-xs font-semibold ${typeColor}`}>
                {typeLabel}
              </Badge>
              {item.act_number && (
                <span className="text-xs text-muted-foreground font-mono">
                  n. {item.act_number}
                </span>
              )}
            </div>
            {/* Act title */}
            {item.act_title && (
              <p className="font-semibold text-sm text-foreground pl-6 line-clamp-2">
                {highlightText(item.act_title, query)}
              </p>
            )}
          </div>
          <div className="flex items-center gap-2 shrink-0">
            {!item.is_exact && item.score != null && (
              <span className="text-xs text-muted-foreground tabular-nums whitespace-nowrap">
                {t("sortRelevance")} {(item.score * 100).toFixed(0)}%
              </span>
            )}
            <Badge variant="outline" className="whitespace-nowrap gap-1 border-emerald-300 dark:border-emerald-700">
              <FileText className="h-3 w-3" />
              {t("actBadge")}
            </Badge>
          </div>
        </div>
      </CardHeader>
      <CardContent className="pt-4 px-4 pb-4">
        {/* Signatory info */}
        <div className="flex items-center gap-2 mb-3">
          <User className="h-4 w-4 text-muted-foreground shrink-0" />
          <span className="text-xs text-muted-foreground">{t("primarySignatory")}</span>
          <span className="font-semibold text-sm text-foreground">
            {item.first_name} {item.last_name}
          </span>
          <Badge
            variant="secondary"
            className="text-xs px-2 py-0"
            style={{ backgroundColor: `${groupColor}20`, color: groupColor, borderColor: `${groupColor}40` }}
          >
            {getGroupShortLabel(item.group)}
          </Badge>
        </div>

        {/* Destinatario */}
        {item.destinatario && (
          <div className="flex items-center gap-2 mb-3 text-sm text-muted-foreground">
            <Building2 className="h-3.5 w-3.5 shrink-0" />
            <span>{t("recipient")} <span className="font-medium text-foreground">{item.destinatario}</span></span>
          </div>
        )}

        {/* Description text */}
        {item.text && (
          <div className="pl-4 pr-1 border-l-2 border-emerald-500/20 text-sm leading-relaxed text-muted-foreground break-words overflow-hidden max-w-full">
            {highlightText(item.text, query)}
          </div>
        )}

        {/* Footer: topics + date */}
        <div className="mt-4 flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-1.5 flex-wrap">
            {topics.length > 0 && <Tag className="h-3 w-3 text-muted-foreground shrink-0" />}
            {topics.map((topic, i) => (
              <Badge key={i} variant="secondary" className="text-[10px] px-1.5 py-0 font-normal">
                {topic}
              </Badge>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs text-muted-foreground">
            <Calendar className="h-3 w-3" />
            {formatDate(item.date)}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
