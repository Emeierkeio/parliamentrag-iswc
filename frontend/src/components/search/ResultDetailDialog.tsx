"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
// DialogTitle is used as a hidden accessibility label at the top level of ResultDetailDialog
import { Badge } from "@/components/ui/badge";
import { config } from "@/config";
import {
  MessageSquareQuote,
  Calendar,
  FileText,
  ExternalLink,
  User,
  Building2,
  Tag,
  Loader2,
} from "lucide-react";
import { SearchResultItem } from "./ResultsList";
import {
  getActTypeLabel,
  getActTypeColor,
  getGroupColor,
  getGroupShortLabel,
} from "./ResultsList";

interface SpeechDetail {
  type: "speech";
  id: string;
  speech_id: string;
  full_text: string;
  chunk_text: string;
  date: string;
  session_number: number | null;
  debate_title: string;
  first_name: string;
  last_name: string;
  group: string;
}

interface ActDetail {
  type: "act";
  id: string;
  act_type: string;
  act_title: string;
  description: string;
  date: string;
  act_number: string;
  destinatario: string;
  eurovoc: string;
  first_name: string;
  last_name: string;
  group: string;
}

type DetailData = SpeechDetail | ActDetail;

interface ResultDetailDialogProps {
  item: SearchResultItem | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function formatDate(dateString: string, locale: string) {
  try {
    if (!dateString) return "";
    const date = new Date(dateString);
    if (isNaN(date.getTime())) return dateString;
    return date.toLocaleDateString(locale, {
      day: "numeric",
      month: "long",
      year: "numeric",
    });
  } catch {
    return dateString;
  }
}

export function ResultDetailDialog({
  item,
  open,
  onOpenChange,
}: ResultDetailDialogProps) {
  const t = useTranslations("SearchPage");
  const [detail, setDetail] = useState<DetailData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !item) {
      setDetail(null);
      setError(null);
      return;
    }

    const fetchDetail = async () => {
      setLoading(true);
      setError(null);
      try {
        const endpoint =
          item.type === "speech"
            ? `${config.api.baseUrl}/search/speech/${encodeURIComponent(item.id)}`
            : `${config.api.baseUrl}/search/act/${encodeURIComponent(item.id)}`;

        const res = await fetch(endpoint);
        if (!res.ok) throw new Error(t("detailLoadError"));
        const data = await res.json();
        setDetail(data);
      } catch (e) {
        setError(e instanceof Error ? e.message : t("detailLoadError"));
      } finally {
        setLoading(false);
      }
    };

    fetchDetail();
  }, [open, item]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-2xl max-h-[85vh] overflow-y-auto overflow-x-hidden">
        <DialogTitle className="sr-only">{t("detailTitle")}</DialogTitle>
        {loading && (
          <div className="flex flex-col items-center justify-center py-12 space-y-3">
            <Loader2 className="h-8 w-8 animate-spin text-fg-faint" aria-hidden />
            <p className="text-sm text-fg-muted">{t("loading")}</p>
          </div>
        )}

        {error && (
          <div role="alert" className="rounded-md bg-danger-soft px-4 py-6 text-center text-sm text-danger-fg">
            <p>{error}</p>
          </div>
        )}

        {!loading && !error && detail && detail.type === "speech" && (
          <SpeechDetailContent detail={detail as SpeechDetail} item={item!} />
        )}

        {!loading && !error && detail && detail.type === "act" && (
          <ActDetailContent detail={detail as ActDetail} item={item!} />
        )}
      </DialogContent>
    </Dialog>
  );
}

function SpeechDetailContent({
  detail,
  item,
}: {
  detail: SpeechDetail;
  item: SearchResultItem;
}) {
  const t = useTranslations("SearchPage");
  const locale = useLocale();
  const groupColor = getGroupColor(detail.group);

  return (
    <>
      <DialogHeader>
        <div className="flex items-center gap-2 mb-1">
          <MessageSquareQuote className="h-5 w-5 text-fg-muted shrink-0" aria-hidden />
          <h2 className="text-lg font-semibold leading-tight tracking-[var(--tracking-heading)] text-fg">
            {t("sessionOf", { number: detail.session_number ?? "", date: formatDate(detail.date, locale) })}
          </h2>
        </div>
        {detail.debate_title && (
          <p className="text-sm text-fg-muted pl-7">
            {detail.debate_title}
          </p>
        )}
      </DialogHeader>

      <div className="space-y-4 mt-2">
        {/* Speaker info */}
        <div className="flex items-center gap-2">
          <User className="h-4 w-4 text-fg-muted shrink-0" />
          <span className="font-semibold text-fg">
            {detail.first_name} {detail.last_name}
          </span>
          <Badge
            variant="secondary"
            className="text-xs px-2 py-0"
            style={{
              backgroundColor: `${groupColor}20`,
              color: groupColor,
              borderColor: `${groupColor}40`,
            }}
          >
            {getGroupShortLabel(detail.group)}
          </Badge>
          {!item.is_exact && item.score != null && (
            <span className="tabular text-xs text-fg-muted whitespace-nowrap ml-auto">
              {t("sortRelevance")} {(item.score * 100).toFixed(0)}%
            </span>
          )}
        </div>

        {/* Full text */}
        <div className="serif-display pl-4 pr-2 border-l-2 border-line-strong text-base leading-relaxed text-fg whitespace-pre-line break-words max-h-[50vh] overflow-y-auto overflow-x-hidden max-w-full">
          {detail.full_text}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-line">
          {detail.date && (
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <Calendar className="h-3 w-3" />
              {formatDate(detail.date, locale)}
            </div>
          )}
          {detail.session_number && (
            <a
              href={`https://www.camera.it/leg19/410?idSeduta=${detail.session_number}&tipo=seduta`}
              target="_blank"
              rel="noopener noreferrer"
              className="link text-xs flex items-center gap-1"
            >
              {t("officialSource")} <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </div>
      </div>
    </>
  );
}

function ActDetailContent({
  detail,
  item,
}: {
  detail: ActDetail;
  item: SearchResultItem;
}) {
  const t = useTranslations("SearchPage");
  const locale = useLocale();
  const groupColor = getGroupColor(detail.group);
  const typeLabel = getActTypeLabel(detail.act_type);
  const typeColor = getActTypeColor(detail.act_type);

  const topics = detail.eurovoc
    ? detail.eurovoc
        .split(";")
        .map((t) => t.trim())
        .filter(Boolean)
    : [];

  return (
    <>
      <DialogHeader>
        <div className="flex items-center gap-2 mb-1">
          <FileText className="h-5 w-5 text-fg-muted shrink-0" aria-hidden />
          <Badge variant="secondary" className={`text-xs font-semibold ${typeColor}`}>
            {typeLabel}
          </Badge>
          {detail.act_number && (
            <span className="text-sm text-fg-muted font-mono">
              n. {detail.act_number}
            </span>
          )}
          {!item.is_exact && item.score != null && (
            <span className="tabular text-xs text-fg-muted whitespace-nowrap ml-auto">
              {t("sortRelevance")} {(item.score * 100).toFixed(0)}%
            </span>
          )}
        </div>
        {detail.act_title && (
          <h2 className="text-base font-semibold leading-snug text-fg pl-7">
            {detail.act_title}
          </h2>
        )}
      </DialogHeader>

      <div className="space-y-4 mt-2">
        {/* Signatory */}
        <div className="flex items-center gap-2">
          <User className="h-4 w-4 text-fg-muted shrink-0" />
          <span className="text-xs text-fg-muted">
            {t("primarySignatory")}
          </span>
          <span className="font-semibold text-sm text-fg">
            {detail.first_name} {detail.last_name}
          </span>
          <Badge
            variant="secondary"
            className="text-xs px-2 py-0"
            style={{
              backgroundColor: `${groupColor}20`,
              color: groupColor,
              borderColor: `${groupColor}40`,
            }}
          >
            {getGroupShortLabel(detail.group)}
          </Badge>
        </div>

        {/* Destinatario */}
        {detail.destinatario && (
          <div className="flex items-center gap-2 text-sm text-fg-muted">
            <Building2 className="h-4 w-4 shrink-0" />
            <span>
              {t("recipient")}{" "}
              <span className="font-medium text-fg">
                {detail.destinatario}
              </span>
            </span>
          </div>
        )}

        {/* Full description */}
        {detail.description && (
          <div className="text-sm leading-relaxed text-fg-secondary whitespace-pre-line break-words max-h-[50vh] overflow-y-auto overflow-x-hidden max-w-full">
            {detail.description}
          </div>
        )}

        {/* EuroVoc topics */}
        {topics.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <Tag className="h-3.5 w-3.5 text-fg-muted shrink-0" />
            {topics.map((topic, i) => (
              <Badge
                key={i}
                variant="secondary"
                className="text-xs px-2 py-0.5 font-normal"
              >
                {topic}
              </Badge>
            ))}
          </div>
        )}

        {/* Footer */}
        {detail.date && (
          <div className="flex items-center justify-between pt-2 border-t border-line">
            <div className="flex items-center gap-2 text-xs text-fg-muted">
              <Calendar className="h-3 w-3" />
              {formatDate(detail.date, locale)}
            </div>
          </div>
        )}
      </div>
    </>
  );
}
