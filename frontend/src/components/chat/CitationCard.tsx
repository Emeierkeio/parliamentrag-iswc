"use client";

import { useState, useRef, useEffect } from "react";
import { cn, toTitleCase } from "@/lib/utils";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import { Quote, Link as LinkIcon, Calendar, MapPin, ExternalLink, Globe, Languages, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useTranslations } from "next-intl";
import { config } from "@/config";
import type { Citation } from "@/types";

function getCameraUrl(id: string | undefined): string | null {
  if (!id) return null;
  // Match legXX_sedY_... where Y is the seduta number
  // Example: leg19_sed2_tit00040
  // Example: leg19_sed3_tit00080.int00060
  const match = id.match(/leg\d+_sed(\d+)_(.+)/);
  if (!match) return null;
  
  const [_, sedutaStr, rest] = match;
  const sedutaId = sedutaStr.padStart(4, '0');
  
  return `https://www.camera.it/leg19/410?idSeduta=${sedutaId}&tipo=stenografico#sed${sedutaId}.stenografico.${rest}`;
}

interface CitationCardProps {
  citation: Citation;
  index: number;
  className?: string;
  isHighlighted?: boolean;
}

export function CitationCard({ citation, index, className, isHighlighted }: CitationCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const t = useTranslations("CitationCard");

  const isGoverno = citation.group?.toLowerCase() === "governo" || !!citation.institutional_role;
  // "misto": il Gruppo Misto non è ascrivibile a uno schieramento, badge neutro
  const coalitionLabel = isGoverno
    ? t("governo")
    : citation.coalition === "misto" ? "Gruppo Misto" : citation.coalition;

  const displayText = citation.translated_text ?? citation.text ?? citation.quote_text ?? "";
  const originalText = citation.is_translated ? (citation.text ?? citation.quote_text ?? "") : null;

  // Auto-scroll when highlighted
  useEffect(() => {
    if (isHighlighted && cardRef.current) {
        cardRef.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [isHighlighted]);

  return (
    <>
      <Card
        ref={cardRef}
        className={cn(
          "group cursor-pointer gap-0 py-0 rounded-lg border-line bg-surface transition-colors duration-200 w-full max-w-full",
          "hover:border-line-strong",
          isHighlighted && "border-notice ring-1 ring-notice/40",
          className
        )}
        onClick={() => setIsModalOpen(true)}
      >
        <CardContent className="p-4">
          <div className="flex items-start gap-4 max-w-full">
             {/* Icon instead of Index */}
            <div className={cn(
                "flex h-8 w-8 shrink-0 items-center justify-center rounded-sm transition-colors",
                isHighlighted ? "bg-highlight text-notice-fg" : "bg-brand-soft text-brand-fg"
            )}>
              <Quote className="h-4 w-4" />
            </div>

            <div className="flex-1 min-w-0">
              {/* Header */}
              <div className="flex flex-col gap-1 mb-1.5 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                  {citation.camera_profile_url ? (
                      <a 
                          href={citation.camera_profile_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="text-sm font-semibold text-fg truncate flex-1 min-w-0 hover:underline hover:text-brand-fg transition-colors"
                          onClick={(e) => e.stopPropagation()} 
                      >
                          {toTitleCase(citation.deputy_first_name || "")} {toTitleCase(citation.deputy_last_name || "")}
                      </a>
                  ) : (
                      <span className="text-sm font-semibold text-fg break-words flex-1 min-w-0">
                          {toTitleCase(citation.deputy_first_name || "")} {toTitleCase(citation.deputy_last_name || "")}
                      </span>
                  )}
                  <Badge
                    variant="outline"
                    className="shrink-0 text-[10px] px-1.5 py-0 h-5 capitalize"
                  >
                    {coalitionLabel}
                  </Badge>
                </div>
                {!isGoverno && (
                  <span className="text-[11px] text-fg-muted block max-w-full break-words" title={citation.misto_component ? `${citation.group} · ${citation.misto_component}` : citation.group}>
                    {citation.misto_component
                      ? `${citation.group} · ${citation.misto_component}`
                      : citation.group}
                  </span>
                )}
              </div>

              {/* Extracted text preview */}
              {originalText ? (
                <Tooltip delayDuration={300}>
                  <TooltipTrigger asChild>
                    <p className="serif-display italic text-[0.9375rem] text-fg-secondary line-clamp-2 mb-3 leading-relaxed break-words cursor-help">
                      &ldquo;{displayText}&rdquo;
                      <Globe className="inline h-3 w-3 ml-1 text-fg-faint" />
                      {getCameraUrl(citation.intervention_id || citation.intervention_id) && (
                           <a
                              href={getCameraUrl(citation.intervention_id || citation.intervention_id) || "#"}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex align-middle ml-1 text-fg-faint hover:text-brand-fg transition-colors"
                              onClick={(e) => e.stopPropagation()}
                              title={t("goToIntervention")}
                           >
                              <LinkIcon className="h-3 w-3" />
                           </a>
                      )}
                    </p>
                  </TooltipTrigger>
                  <TooltipContent side="bottom" className="max-w-[400px] p-3">
                    <p className="label-mono mb-1">{t("originalLabel")}</p>
                    <p className="serif-display text-sm leading-relaxed italic">{originalText}</p>
                  </TooltipContent>
                </Tooltip>
              ) : (
                <p className="serif-display italic text-[0.9375rem] text-fg-secondary line-clamp-2 mb-3 leading-relaxed break-words">
                  &ldquo;{displayText}&rdquo;
                  {getCameraUrl(citation.intervention_id || citation.intervention_id) && (
                       <a
                          href={getCameraUrl(citation.intervention_id || citation.intervention_id) || "#"}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="inline-flex align-middle ml-1 text-fg-faint hover:text-brand-fg transition-colors"
                          onClick={(e) => e.stopPropagation()}
                          title={t("goToIntervention")}
                       >
                          <LinkIcon className="h-3 w-3" />
                       </a>
                  )}
                </p>
              )}

              {/* Metadata */}
              <div className="flex items-center flex-wrap gap-x-3 gap-y-1 text-[11px] text-fg-muted max-w-full">
                <span className="flex items-center gap-1.5 shrink-0 tabular">
                  <Calendar className="h-3 w-3" />
                  {citation.date}
                </span>
                {citation.debate && (
                  <span className="flex items-center gap-1 min-w-0 flex-wrap max-w-full">
                    <MapPin className="h-3 w-3 shrink-0" />
                    {getCameraUrl(citation.debate_id || citation.debate_id) ? (
                        <a 
                            href={getCameraUrl(citation.debate_id || citation.debate_id) || "#"}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="hover:underline hover:text-fg cursor-pointer transition-colors break-words"
                            onClick={(e) => e.stopPropagation()}
                        >
                            {citation.debate}
                        </a>
                    ) : (
                        <span className="break-words max-w-full">{citation.debate}</span>
                    )}
                  </span>
                )}
              </div>
            </div>

            {/* Expand icon */}
            <ExternalLink className="h-4 w-4 shrink-0 text-fg-faint group-hover:text-brand-fg transition-colors" />
          </div>
        </CardContent>
      </Card>

      {/* Full citation modal */}
      <CitationModal
        citation={citation}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />
    </>
  );
}

interface CitationModalProps {
  citation: Citation;
  isOpen: boolean;
  onClose: () => void;
}

function CitationModal({ citation, isOpen, onClose }: CitationModalProps) {
  const t = useTranslations("CitationCard");
  const isGoverno = citation.group?.toLowerCase() === "governo" || !!citation.institutional_role;
  // "misto": il Gruppo Misto non è ascrivibile a uno schieramento, badge neutro
  const coalitionLabel = isGoverno
    ? t("governo")
    : citation.coalition === "misto" ? "Gruppo Misto" : citation.coalition;
  // On-demand translation state for the full speech text
  const [translatedFull, setTranslatedFull] = useState<string | null>(null);
  const [isTranslating, setIsTranslating] = useState(false);
  const [showTranslated, setShowTranslated] = useState(false);

  // Use pre-translated full_text if available, otherwise use on-demand translation
  const preTranslatedFull = citation.translated_full_text && citation.translated_full_text.length > 0
    ? citation.translated_full_text : null;
  const hasTranslation = !!(preTranslatedFull || translatedFull);
  const displayFullText = (showTranslated && (preTranslatedFull || translatedFull))
    ? (preTranslatedFull || translatedFull)!
    : (citation.full_text ?? citation.text ?? "");
  const originalFullText = (showTranslated && hasTranslation)
    ? (citation.full_text ?? citation.text ?? "") : null;

  const handleTranslate = async () => {
    if (preTranslatedFull || translatedFull) {
      setShowTranslated(true);
      return;
    }
    const textToTranslate = citation.full_text ?? citation.text ?? "";
    if (!textToTranslate) return;

    setIsTranslating(true);
    try {
      const resp = await fetch("/api/config/translate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: textToTranslate }),
      });
      if (resp.ok) {
        const data = await resp.json();
        setTranslatedFull(data.translated || textToTranslate);
        setShowTranslated(true);
      }
    } catch {
      // Silently fail, show original
    } finally {
      setIsTranslating(false);
    }
  };

  // When the UI is in English (citation.is_translated), show the English
  // full text by default: auto-translate on first open.
  useEffect(() => {
    if (isOpen && citation.is_translated && !hasTranslation && !isTranslating) {
      handleTranslate();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);
  const displayText = displayFullText;

  const contextUrl = getCameraUrl(citation.debate_id || citation.debate_id);
  const interventionUrl = getCameraUrl(citation.intervention_id || citation.intervention_id);

  // Highlighting logic: only highlight if we have a specific quote_text that differs from full_text
  // Don't try to highlight the entire chunk - it doesn't make sense
  const quoteText = citation.quote_text || "";
  const hasSpecificQuote = quoteText && citation.full_text &&
    quoteText.length < citation.full_text.length * 0.8; // Quote should be notably shorter than full text

  // Use the active display text for highlighting (translated or original)
  const textForHighlight = displayFullText;
  let parts: string[] = [textForHighlight];
  let highlightText = quoteText;

  // Only highlight in original Italian text (quotes won't match in translated text)
  if (hasSpecificQuote && !showTranslated && citation.full_text) {
    if (citation.full_text.includes(quoteText)) {
      parts = citation.full_text.split(quoteText);
    } else {
      const normalize = (s: string) => s.replace(/\s+/g, ' ').trim();
      const normalizedQuote = normalize(quoteText);
      const normalizedFull = normalize(citation.full_text);

      if (normalizedFull.includes(normalizedQuote)) {
        try {
          const escaped = quoteText.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
          const pattern = escaped.replace(/\s+/g, '\\s+');
          const regex = new RegExp(pattern, 'i');
          parts = citation.full_text.split(regex);
        } catch {
          // Keep parts as [textForHighlight]
        }
      }
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-[95vw] sm:max-w-3xl bg-surface border border-line shadow-overlay p-0 gap-0 overflow-hidden rounded-xl h-[90vh] sm:h-[85vh] flex flex-col">
        
        {/* Header: Title & Close */}
        <DialogHeader className="px-6 py-4 border-b border-line shrink-0">
          <DialogTitle className="label-mono flex items-center gap-2">
             <Quote className="h-4 w-4 text-brand-fg" aria-hidden="true" />
             <span>{t("intervention")}</span>
          </DialogTitle>
        </DialogHeader>

        <div className="flex-1 overflow-hidden flex flex-col relative">
             {/* Sticky Speaker Metadata Bar */}
             <div className="bg-surface z-10 px-6 py-4 flex items-center gap-4 border-b border-line shrink-0">
                 <div className="flex items-center gap-4 min-w-0 flex-1">
                    {citation.photo ? (
                        <img
                            src={citation.photo}
                            alt={`${toTitleCase(citation.deputy_first_name || "")} ${toTitleCase(citation.deputy_last_name || "")}`}
                            className="h-12 w-12 shrink-0 rounded-full object-cover border border-line"
                            onError={(e) => {
                                const target = e.currentTarget;
                                target.style.display = "none";
                                const next = target.nextElementSibling as HTMLElement | null;
                                if (next) next.style.display = "flex";
                            }}
                        />
                    ) : null}
                    <div
                        className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-surface-muted border border-line text-lg font-semibold text-fg-muted"
                        style={{ display: citation.photo ? "none" : "flex" }}
                    >
                        {citation.deputy_first_name?.[0]}{citation.deputy_last_name?.[0]}
                    </div>
                    <div className="flex flex-col min-w-0">
                        {citation.camera_profile_url ? (
                            <a 
                                href={citation.camera_profile_url}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="serif-display text-fg text-xl leading-tight truncate hover:underline hover:text-brand-fg transition-colors"
                            >
                                {toTitleCase(citation.deputy_first_name || "")} {toTitleCase(citation.deputy_last_name || "")}
                            </a>
                        ) : (
                            <div className="serif-display text-fg text-xl leading-tight truncate">
                                {toTitleCase(citation.deputy_first_name || "")} {toTitleCase(citation.deputy_last_name || "")}
                            </div>
                        )}
                        <div className="flex items-center gap-2 mt-1">
                             <Badge
                                variant="outline"
                                className="h-5 text-[10px] px-1.5 font-medium capitalize"
                             >
                                {coalitionLabel}
                             </Badge>
                             {!isGoverno && (
                               <span className="text-xs text-fg-muted truncate max-w-[300px]" title={citation.misto_component ? `${citation.group} · ${citation.misto_component}` : citation.group}>
                                  {citation.misto_component
                                    ? `${citation.group} · ${citation.misto_component}`
                                    : citation.group}
                               </span>
                             )}
                        </div>
                    </div>
                </div>
                
                {/* Date & Meta */}
                <div className="flex flex-col items-end text-xs text-fg-muted gap-1 shrink-0">
                    <div className="flex items-center gap-1.5 bg-surface-muted px-2 py-1 rounded-sm tabular">
                        <Calendar className="w-3 h-3" /> 
                        <span className="font-medium">{citation.date}</span>
                    </div>
                </div>
             </div>

             {/* Content Area */}
             <ScrollArea className="flex-1">
                <div className="p-6 md:p-8 space-y-8">
                    {/* Context Box */}
                    {citation.debate && (
                        <div className="bg-surface-muted rounded-md p-4 text-sm leading-relaxed text-fg-secondary">
                            <div className="label-mono flex items-center gap-2 mb-2">
                                <MapPin className="w-3 h-3" />
                                {t("parliamentaryContext")}
                            </div>
                            {contextUrl ? (
                                <a 
                                    href={contextUrl}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="hover:text-brand-fg hover:underline transition-colors flex items-center gap-1 group/link"
                                >
                                    {citation.debate}
                                    <ExternalLink className="w-3 h-3 opacity-0 group-hover/link:opacity-100 transition-opacity" />
                                </a>
                            ) : (
                                citation.debate
                            )}
                        </div>
                    )}

                    {/* Translation-in-progress banner */}
                    {isTranslating && (
                        <div className="flex items-center gap-2 rounded-md bg-info-soft px-3 py-2 text-xs font-medium text-info-fg">
                            <Loader2 className="h-3.5 w-3.5 animate-spin shrink-0" />
                            Translating to English…
                        </div>
                    )}

                    {/* Speech Text */}
                    <div className={cn(
                        "max-w-none serif-display text-lg leading-loose text-fg",
                        isTranslating && "opacity-50 transition-opacity"
                    )}>
                        {parts.length > 1 ? (
                            <>
                                {parts.map((part, i) => (
                                    <span key={i}>
                                        {part}
                                        {i < parts.length - 1 && (
                                            <mark className="bg-highlight text-fg px-1 -mx-1 rounded-xs border-b-2 border-notice italic [box-decoration-break:clone]">
                                                {highlightText}
                                            </mark>
                                        )}
                                    </span>
                                ))}
                            </>
                        ) : (
                            displayText
                        )}
                        {citation.is_translated && (
                            <Globe className="inline h-4 w-4 ml-2 text-fg-faint align-middle" />
                        )}

                        {interventionUrl && (
                            <a
                                href={interventionUrl}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="inline-flex items-center justify-center ml-2 text-fg-faint hover:text-brand-fg transition-colors align-middle"
                                title={t("goToCamera")}
                            >
                                <LinkIcon className="w-4 h-4" />
                            </a>
                        )}
                    </div>

                    {/* Translate button + original text section */}
                    {citation.is_translated && !isTranslating && (
                        <div className="mt-6 pt-6 border-t border-line">
                            <div className="flex items-center gap-2 mb-3">
                                <Button
                                    variant="outline"
                                    size="sm"
                                    onClick={() => {
                                        if (showTranslated) {
                                            setShowTranslated(false);
                                        } else {
                                            handleTranslate();
                                        }
                                    }}
                                    disabled={isTranslating}
                                    className="text-xs h-7 gap-1.5"
                                >
                                    {isTranslating ? (
                                        <><Loader2 className="h-3 w-3 animate-spin" /> Translating...</>
                                    ) : showTranslated ? (
                                        <><Globe className="h-3 w-3" /> Show original</>
                                    ) : (
                                        <><Languages className="h-3 w-3" /> Translate</>
                                    )}
                                </Button>
                            </div>
                            {originalFullText && (
                                <>
                                    <p className="label-mono mb-2 flex items-center gap-1.5">
                                        <Globe className="h-3 w-3" />
                                        {t("originalLabel")}
                                    </p>
                                    <p className="serif-display text-sm leading-relaxed italic text-fg-secondary">{originalFullText}</p>
                                </>
                            )}
                        </div>
                    )}
                </div>
             </ScrollArea>
        </div>
      </DialogContent>
    </Dialog>
  );
}