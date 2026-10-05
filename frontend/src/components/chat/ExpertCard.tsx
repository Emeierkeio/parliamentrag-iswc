"use client";

import { useState } from "react";
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
import { Separator } from "@/components/ui/separator";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { config } from "@/config";
import type { Expert } from "@/types";
import { Slider } from "@/components/ui/slider";
import {
  User,
  Award,
  TrendingUp,
  MessageSquare,
  Network,
  Target,
  Layers,
  ChevronRight,
  FileText,
  ExternalLink,
  SlidersHorizontal
} from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { useTranslations } from "next-intl";

interface ExpertCardProps {
  expert: Expert;
  className?: string;
}

type BreakdownKey = "speeches" | "acts" | "committee" | "profession" | "education" | "role";

// Pesi ufficiali: mirror di backend/config/default.yaml → authority.weights
// (speeches nel breakdown corrisponde a "interventions" nel config)
const DEFAULT_WEIGHTS: Record<BreakdownKey, number> = {
  speeches: 0.25,
  committee: 0.25,
  acts: 0.2,
  profession: 0.15,
  education: 0.1,
  role: 0.05,
};

export function ExpertCard({ expert, className }: ExpertCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const t = useTranslations("ExpertCard");

  const groupConfig = config.politicalGroups[expert.group as keyof typeof config.politicalGroups];
  const groupColor = groupConfig?.color || "var(--fg-faint)";
  const groupLabel = groupConfig?.label || expert.group;

  const scoreLevel =
    expert.authority_score >= config.authorityScore.high
      ? "high"
      : expert.authority_score >= config.authorityScore.medium
      ? "medium"
      : "low";

  const scoreLevelConfig = {
    high: { label: t("high"), color: "text-brand-fg" },
    medium: { label: t("medium"), color: "text-fg-secondary" },
    low: { label: t("low"), color: "text-fg-muted" },
  };

  return (
    <>
      <Card
        className={cn(
          "cursor-pointer gap-0 py-0 rounded-lg border-line bg-surface transition-colors duration-200 w-full",
          "hover:border-line-strong",
          className
        )}
        onClick={() => setIsModalOpen(true)}
      >
        <CardContent className="p-4">
          <div className="flex items-start gap-3">
            {/* Avatar */}
            {expert.photo ? (
              <img
                src={expert.photo}
                alt={`${toTitleCase(expert.first_name)} ${toTitleCase(expert.last_name)}`}
                className="h-11 w-11 shrink-0 rounded-full object-cover border border-line"
              />
            ) : (
              <div
                className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full text-sm font-semibold text-white"
                style={{ backgroundColor: groupColor }}
              >
                {expert.first_name[0]}
                {expert.last_name[0]}
              </div>
            )}

            <div className="flex-1 min-w-0">
              {/* Name */}
              {/* Name */}
              {expert.camera_profile_url ? (
                  <a 
                    href={expert.camera_profile_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-sm font-semibold text-fg leading-tight hover:underline hover:text-brand-fg transition-colors block"
                    onClick={(e) => e.stopPropagation()}
                  >
                    {toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}
                  </a>
              ) : (
                  <p className="text-sm font-semibold text-fg leading-tight">
                    {toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}
                  </p>
              )}

              {/* Group badge */}
              <p
                className="text-xs font-medium mt-0.5 leading-tight"
                style={{ color: groupColor }}
              >
                {groupLabel}
              </p>

              {/* Coalizione indicator */}
              <p className="text-xs text-fg-muted mt-1">
                {expert.coalition === "maggioranza" ? t("maggioranza") : t("opposizione")}
              </p>

              {/* Authority score preview */}
              <div className="mt-2 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="label-mono text-[10px]">{t("authorityOnTopic")}</span>
                  <span className={cn("text-[11px] font-medium", scoreLevelConfig[scoreLevel].color)}>
                    {scoreLevelConfig[scoreLevel].label}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Award className={cn("h-3.5 w-3.5 shrink-0", scoreLevelConfig[scoreLevel].color)} />
                  <div className="flex-1 h-1.5 rounded-full bg-surface-sunken">
                    <div
                      className="h-full rounded-full bg-brand"
                      style={{ width: `${expert.authority_score * 100}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium text-fg-muted tabular min-w-[24px] text-right">
                    {Math.round(expert.authority_score * 100)}
                  </span>
                </div>
              </div>
            </div>

            <ChevronRight className="h-4 w-4 shrink-0 text-fg-faint mt-1" />
          </div>
        </CardContent>
      </Card>

      {/* Expert detail modal */}
      <ExpertModal
        expert={expert}
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
      />
    </>
  );
}

export function ExpertRow({ expert, className }: ExpertCardProps) {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const t = useTranslations("ExpertCard");
  const groupConfig = config.politicalGroups[expert.group as keyof typeof config.politicalGroups];
  const groupColor = groupConfig?.color || "var(--fg-faint)";

  return (
    <>
      <div 
        className={cn(
            "flex items-center gap-3 p-2.5 rounded-md bg-surface-muted hover:bg-surface-sunken transition-colors duration-[var(--duration-fast)] cursor-pointer group w-full",
            className
        )}
        onClick={() => setIsModalOpen(true)}
      >
        {/* Avatar */}
        {expert.photo ? (
          <img
            src={expert.photo}
            alt={`${toTitleCase(expert.first_name)} ${toTitleCase(expert.last_name)}`}
            className="h-9 w-9 shrink-0 rounded-full object-cover"
          />
        ) : (
          <div
            className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-white"
            style={{ backgroundColor: groupColor }}
          >
            {expert.first_name[0]}{expert.last_name[0]}
          </div>
        )}

        <div className="flex-1 min-w-0 flex items-center justify-between gap-4">
             <div className="min-w-0 flex flex-col justify-center">
                  <div className="font-semibold text-sm text-fg truncate leading-tight flex items-center gap-2">
                       {expert.camera_profile_url ? (
                           <a 
                             href={expert.camera_profile_url} 
                             target="_blank"
                             rel="noopener noreferrer"
                             className="hover:underline hover:text-brand-fg relative z-10" 
                             onClick={(e) => e.stopPropagation()}
                           >
                              {toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}
                           </a>
                       ) : (
                          <span>{toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}</span>
                       )}
                  </div>
                  {expert.institutional_role && (
                      <span className="text-[11px] text-fg-muted truncate max-w-[200px] block">
                          {expert.institutional_role}
                      </span>
                  )}
             </div>
             
             {/* Score */}
             <div className="flex items-center gap-3 shrink-0">
                   <div className="hidden sm:block w-20 h-1.5 rounded-full bg-line-strong overflow-hidden">
                        <div
                            className="h-full bg-brand"
                            style={{ width: `${expert.authority_score * 100}%` }}
                        />
                   </div>
                   <div className="flex flex-col items-end leading-none">
                        <span className="label-mono text-[10px]">{t("authority")}</span>
                        <span className="text-sm font-semibold text-fg tabular">{Math.round(expert.authority_score * 100)}</span>
                   </div>
             </div>
        </div>
        
        <ChevronRight className="h-4 w-4 shrink-0 text-fg-faint group-hover:text-fg-muted transition-colors" />
      </div>

      <ExpertModal expert={expert} isOpen={isModalOpen} onClose={() => setIsModalOpen(false)} />
    </>
  );
}

interface ExpertModalProps {
  expert: Expert;
  isOpen: boolean;
  onClose: () => void;
  hideScore?: boolean;
}

export function ExpertModal({ expert, isOpen, onClose, hideScore = false }: ExpertModalProps) {
  const t = useTranslations("ExpertCard");
  const groupConfig = config.politicalGroups[expert.group as keyof typeof config.politicalGroups];
  const groupColor = groupConfig?.color || "var(--fg-faint)";
  const groupLabel = groupConfig?.label || expert.group;

  // I pesi rispecchiano backend/config/default.yaml → authority.weights
  // (speeches nel breakdown corrisponde a "interventions" nel config)
  const scoreBreakdown = [
    {
      icon: MessageSquare,
      label: t("speeches"),
      value: expert.score_breakdown?.speeches || 0,
      weight: 0.25,
      description: t("speechesDesc"),
    },
    {
      icon: Target,
      label: t("acts"),
      value: expert.score_breakdown?.acts || 0,
      weight: 0.2,
      description: t("actsDesc"),
    },
    {
      icon: Network,
      label: t("committee"),
      value: expert.score_breakdown?.committee || 0,
      weight: 0.25,
      description: t("committeeDesc"),
      tooltip: (expert.committees && expert.committees.length > 0) ? expert.committees : (expert.committee ? [expert.committee] : [t("committeeNotAssigned")])
    },
    {
      icon: User,
      label: t("profession"),
      value: expert.score_breakdown?.profession || 0,
      weight: 0.15,
      description: t("professionDesc"),
      tooltip: [expert.profession || t("professionNotFound")]
    },
    {
      icon: Layers,
      label: t("education"),
      value: expert.score_breakdown?.education || 0,
      weight: 0.1,
      description: t("educationDesc"),
      tooltip: [expert.education || t("educationNotFound")]
    },
    {
      icon: Award,
      label: t("role"),
      value: expert.score_breakdown?.role || 0,
      weight: 0.05,
      description: t("roleDesc"),
      tooltip: [expert.institutional_role || t("defaultRole")]
    },
  ];

  const [selectedDetail, setSelectedDetail] = useState<"atti" | null>(null);

  // Simulatore pesi: ricombina le sei componenti con pesi scelti dall'utente
  // (somma normalizzata). Con i pesi ufficiali mostra il punteggio del backend.
  const [showSim, setShowSim] = useState(false);
  const [simWeights, setSimWeights] = useState<Record<BreakdownKey, number>>(DEFAULT_WEIGHTS);
  const simCustom = (Object.keys(DEFAULT_WEIGHTS) as BreakdownKey[]).some(
    (k) => Math.abs(simWeights[k] - DEFAULT_WEIGHTS[k]) > 1e-9
  );
  const simTotal = (Object.keys(simWeights) as BreakdownKey[]).reduce((a, k) => a + simWeights[k], 0);
  const simScore = !simCustom
    ? expert.authority_score
    : simTotal <= 0
      ? 0
      : (Object.keys(simWeights) as BreakdownKey[]).reduce(
          (a, k) => a + simWeights[k] * (expert.score_breakdown?.[k] ?? 0),
          0
        ) / simTotal;
  const simDelta = Math.round(simScore * 100) - Math.round(expert.authority_score * 100);

  return (
    <Dialog open={isOpen} onOpenChange={onClose}>
      <DialogContent className="max-w-[95vw] sm:max-w-2xl bg-surface border border-line shadow-overlay p-0 gap-0 overflow-hidden rounded-xl max-h-[90vh] sm:max-h-[85vh] flex flex-col">
        <DialogHeader className="p-4 sm:p-6 pb-2 shrink-0">
          <DialogTitle className="serif-display flex items-center gap-3 text-xl sm:text-2xl text-fg">
             <div className="p-2 bg-brand-soft rounded-sm">
                <TrendingUp className="h-5 w-5 text-brand-fg" aria-hidden="true" />
             </div>
            {t("whyAuthoritative")}
          </DialogTitle>
          <DialogDescription className="text-xs sm:text-sm text-fg-muted">
            {t("authorityCriteria")}
          </DialogDescription>
        </DialogHeader>

        <div className="p-4 sm:p-6 pt-2 space-y-4 sm:space-y-6 overflow-y-auto">
          {/* Header Profile */}
          <div className="flex items-start gap-3 sm:gap-5">
            {expert.photo ? (
              <img
                src={expert.photo}
                alt={`${toTitleCase(expert.first_name)} ${toTitleCase(expert.last_name)}`}
                className="h-12 w-12 sm:h-16 sm:w-16 shrink-0 rounded-full object-cover border border-line"
              />
            ) : (
              <div
                className="flex h-12 w-12 sm:h-16 sm:w-16 shrink-0 items-center justify-center rounded-full text-lg sm:text-xl font-semibold text-white"
                style={{ backgroundColor: groupColor }}
              >
                {expert.first_name[0]}
                {expert.last_name[0]}
              </div>
            )}
            <div className="flex-1 min-w-0 space-y-1">
              {expert.camera_profile_url ? (
                  <a
                    href={expert.camera_profile_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="serif-display text-xl sm:text-2xl text-fg hover:underline hover:text-brand-fg transition-colors block truncate"
                  >
                    {toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}
                  </a>
              ) : (
                  <h3 className="serif-display text-xl sm:text-2xl text-fg truncate">
                    {toTitleCase(expert.first_name)} {toTitleCase(expert.last_name)}
                  </h3>
              )}
              <div className="flex flex-wrap items-center gap-2">
                 <Badge
                  className="px-2 py-0.5 text-xs font-medium bg-transparent border"
                  style={{
                    color: groupColor,
                    borderColor: groupColor,
                  }}
                >
                  {groupLabel}
                </Badge>
                <span className="text-fg-faint text-sm" aria-hidden="true">·</span>
                <span className="text-sm font-medium text-fg-muted">
                    {expert.coalition === "maggioranza" ? t("maggioranza") : t("opposizione")}
                </span>
              </div>
            </div>
          </div>

          {/* Main Score */}
          {!hideScore && (
          <div className="bg-surface-muted rounded-md p-4 sm:p-5">
             <div className="flex justify-between items-end mb-3">
                <span className="label-mono">{t("parliamentaryAuthority")}</span>
                <span className="text-2xl sm:text-3xl font-semibold text-brand-fg tabular">{Math.round(expert.authority_score * 100)}</span>
             </div>
             <div className="h-2 w-full rounded-full bg-surface-sunken overflow-hidden">
                <div
                    className="h-full bg-brand rounded-full"
                    style={{ width: `${expert.authority_score * 100}%` }}
                />
             </div>
          </div>
          )}

          <Separator className="bg-line" />

          {/* Grid Breakdown */}
          <div>
            <h4 className="label-mono mb-4">{t("authorityCriteriaTitle")}</h4>
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
                {scoreBreakdown.map((item) => {
                    const isAtti = item.label === "Atti";
                    const hasDetails = isAtti && expert.acts_detail && expert.acts_detail.length > 0;

                    const content = (
                         <div 
                            className={cn(
                                "p-3 rounded-md bg-surface-muted transition-colors duration-[var(--duration-fast)] h-full",
                                hasDetails ? "hover:bg-surface-sunken cursor-pointer" : "hover:bg-surface-sunken"
                            )}
                            onClick={() => hasDetails && setSelectedDetail("atti")}
                         >
                            <div className="flex items-start gap-2 mb-2">
                                 <item.icon className="w-4 h-4 mt-0.5 shrink-0 text-brand-fg" />
                                 <span className="text-sm font-medium text-fg leading-tight">{item.label}</span>
                                 <span className="ml-auto mt-0.5 font-mono text-[10px] text-fg-muted tabular whitespace-nowrap shrink-0">
                                     {t("weightLabel")} {Math.round(item.weight * 100)}%
                                 </span>
                                 {hasDetails && <ChevronRight className="w-3 h-3 mt-1 shrink-0 text-fg-muted" />}
                            </div>
                            <div className="flex items-end justify-between gap-2 mb-1">
                                <span className="text-xs text-fg-muted">{item.description}</span>
                                {!hideScore && <span className="text-sm font-semibold text-fg tabular">{(item.value * 100).toFixed(0)}%</span>}
                            </div>
                            {!hideScore && (
                             <div className="h-1.5 w-full rounded-full bg-surface-sunken">
                                <div
                                    className="h-full rounded-full bg-brand"
                                    style={{ width: `${item.value * 100}%` }}
                                />
                            </div>
                            )}
                        </div>
                    );

                    if (item.tooltip) {
                        return (
                             <TooltipProvider key={item.label}>
                                <Tooltip delayDuration={300}>
                                    <TooltipTrigger asChild>
                                        <div className="cursor-help h-full">
                                            {content}
                                        </div>
                                    </TooltipTrigger>
                                    <TooltipContent side="top" className="max-w-[260px]">
                                        {item.tooltip.length === 1 ? (
                                            <p className="font-medium text-xs">{item.tooltip[0]}</p>
                                        ) : (
                                            <div className="space-y-1.5">
                                                {item.tooltip.map((t, i) => (
                                                    <div key={i} className="flex items-start gap-1.5">
                                                        <span className="font-mono text-xs shrink-0 mt-px opacity-70">{i + 1}.</span>
                                                        <p className="font-medium text-xs leading-snug">{t}</p>
                                                    </div>
                                                ))}
                                            </div>
                                        )}
                                    </TooltipContent>
                                </Tooltip>
                            </TooltipProvider>
                        );
                    }
                    
                    return <div key={item.label} className="h-full">{content}</div>;
                })}
            </div>
            {/* Simulatore: la policy dei pesi è editabile, non solo dichiarata */}
            {!hideScore && (
              <div className="mt-4 rounded-md bg-surface-muted overflow-hidden">
                <button
                  onClick={() => setShowSim((v) => !v)}
                  className="w-full flex items-center gap-2 px-4 py-3 text-sm font-medium text-fg hover:bg-surface-sunken transition-colors"
                >
                  <SlidersHorizontal className="w-4 h-4 text-brand-fg" />
                  {t("simulateTitle")}
                  <ChevronRight
                    className={cn(
                      "w-4 h-4 ml-auto text-fg-muted transition-transform duration-200 motion-reduce:transition-none",
                      showSim && "rotate-90"
                    )}
                  />
                </button>
                {showSim && (
                  <div className="px-4 pb-4 space-y-3">
                    <p className="text-xs leading-relaxed text-fg-muted">
                      {t("simulateDesc")}
                    </p>
                    <div className="space-y-2.5">
                      {(Object.keys(DEFAULT_WEIGHTS) as BreakdownKey[]).map((k) => (
                        <div key={k}>
                          <div className="flex items-center justify-between text-[11px] mb-0.5">
                            <span className="text-fg-secondary">{t(k === "speeches" ? "speeches" : k)}</span>
                            <span className="tabular text-fg-muted">
                              {Math.round(simWeights[k] * 100)}%
                            </span>
                          </div>
                          <Slider
                            min={0}
                            max={50}
                            step={1}
                            value={[Math.round(simWeights[k] * 100)]}
                            onValueChange={([v]) =>
                              setSimWeights((prev) => ({ ...prev, [k]: v / 100 }))
                            }
                            className="py-1"
                          />
                        </div>
                      ))}
                    </div>
                    <div className="flex items-center justify-between gap-4 rounded-md bg-surface px-3 py-2.5">
                      <div className="flex flex-col">
                        <span className="label-mono text-[10px]">
                          {t("simulateOfficialLabel")}
                        </span>
                        <span className="text-lg font-semibold text-fg-muted tabular">
                          {Math.round(expert.authority_score * 100)}
                        </span>
                      </div>
                      <div className="flex-1 h-2 rounded-full bg-surface-sunken overflow-hidden">
                        <div
                          className="h-full bg-brand rounded-full"
                          style={{ width: `${simScore * 100}%` }}
                        />
                      </div>
                      <div className="flex flex-col items-end">
                        <span className="label-mono text-[10px]">
                          {t("simulateResult")}
                        </span>
                        <span className="text-lg font-semibold text-brand-fg tabular">
                          {Math.round(simScore * 100)}
                          {simCustom && simDelta !== 0 && (
                            <span
                              className={cn(
                                "ml-1.5 font-mono text-xs font-medium text-fg-secondary"
                              )}
                            >
                              {simDelta > 0 ? "+" : ""}
                              {simDelta}
                            </span>
                          )}
                        </span>
                      </div>
                    </div>
                    {simCustom && (
                      <button
                        onClick={() => setSimWeights(DEFAULT_WEIGHTS)}
                        className="link w-full text-center text-xs"
                      >
                        {t("simulateReset")}
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}

            <p className="mt-3 text-xs leading-relaxed text-fg-muted">
                {t("weightsNote")}{" "}
                <a
                  href="/method"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="underline underline-offset-2 decoration-fg-faint hover:text-brand-fg transition-colors whitespace-nowrap"
                >
                    {t("weightsLink")}
                </a>
            </p>
          </div>

          {/* Details Panel (Conditional) */}
          {selectedDetail === "atti" && expert.acts_detail && (
              <div className="space-y-3 sm:space-y-4 motion-safe:animate-rise">
                  <div className="flex items-center justify-between gap-2">
                      <div className="flex items-center gap-2 min-w-0">
                          <FileText className="w-4 h-4 text-brand-fg shrink-0" />
                          <h4 className="text-xs sm:text-sm font-semibold text-fg truncate">{t("actsAuthorityTitle")}</h4>
                      </div>
                      <button
                        onClick={() => setSelectedDetail(null)}
                        className="link text-xs font-medium"
                      >
                          {t("closeDetails")}
                      </button>
                  </div>
                  <ScrollArea className="h-64 rounded-md bg-surface-muted p-3">
                      <div className="space-y-3">
                          {expert.acts_detail.map((atto, idx) => (
                              <div key={idx} className="p-3 bg-surface rounded-sm space-y-2">
                                  <div className="flex items-start justify-between gap-3">
                                      <p className="text-xs font-semibold leading-tight line-clamp-3 flex-1 text-fg">
                                          "{atto.title || t('noTitle')}"
                                      </p>
                                      <Badge variant="default" className="shrink-0 font-mono text-[10px] px-1.5 py-0 h-4 tabular">
                                          {Math.round(atto.similarity * 100)}% Match
                                      </Badge>
                                  </div>
                                  <div className="flex items-center justify-between text-[11px] text-fg-muted">
                                      <div className="flex items-center gap-1.5">
                                          <Badge
                                            variant={atto.is_primary ? "default" : "secondary"}
                                            className="text-[10px] px-1 py-0 h-4 font-normal"
                                          >
                                              {atto.is_primary ? t("primarySigner") : t("coSigner")}
                                          </Badge>
                                          {atto.eurovoc && (
                                              <span className="truncate max-w-[150px]">{t("topic")}: {atto.eurovoc}</span>
                                          )}
                                      </div>
                                  </div>
                              </div>
                          ))}
                      </div>
                  </ScrollArea>
              </div>
          )}

        </div>
      </DialogContent>
    </Dialog>
  );
}
