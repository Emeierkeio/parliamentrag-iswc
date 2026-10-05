"use client";

import { useState, useEffect } from "react";
import { useTranslations } from 'next-intl';
import { cn } from "@/lib/utils";
import { config } from "@/config";
import type { ProcessingProgress } from "@/types";
import {
  Check,
  Loader2,
  CheckCircle2,
  Search,
  Landmark,
  Users,
  MessageSquare,
  BarChart3,
  Compass,
  PenTool,
  Target,
} from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

interface ProgressIndicatorProps {
  progress: ProcessingProgress | null;
  className?: string;
}

/** Render rich step result details based on step type */
function StepResultDetails({ step, result, details, tPi }: { step: number; result?: string; details?: Record<string, unknown>; tPi: ReturnType<typeof useTranslations> }) {
  // Step 2: Commissioni, show commission name
  if (step === 2) {
    const commList = Array.isArray(details?.commissioni) ? details.commissioni as Array<Record<string, unknown>> : [];
    const topComm = commList[0];
    const topCommName = topComm ? (typeof topComm.nome === "string" ? topComm.nome : typeof topComm.name === "string" ? topComm.name : undefined) : undefined;
    if (topCommName) {
      return (
        <p className="text-[11px] text-brand-fg font-medium mt-1">
          {tPi('stepResultCommissione')}: {topCommName}
        </p>
      );
    }
    if (result) {
      return (
        <p className="text-[11px] text-brand-fg font-medium mt-1">
          {result}
        </p>
      );
    }
  }

  // Default: show result string; nothing to add when the step produced no result
  if (!result) return null;
  return (
    <p className="text-[11px] text-brand-fg font-medium mt-1">
      {tPi('stepResultResult')}: {result}
    </p>
  );
}

/**
 * Sticky banner shown after the response text is visible (step 7+).
 * Rendered separately in ChatArea as a sticky element.
 */
export function ProgressBanner({ progress, className }: ProgressIndicatorProps) {
  const tPi = useTranslations('ProgressIndicator');
  if (!progress) return null;

  const textIsVisible = progress.stepResults?.some(r => r.step === 7);
  if (!textIsVisible || progress.isComplete) return null;

  const statusText = progress.currentStep <= 7
    ? tPi('writingCompletion')
    : tPi('waiting');

  return (
    <div className={cn(
      "sticky top-0 z-20 w-full bg-surface/95 backdrop-blur-md border-b border-brand/10",
      "animate-in slide-in-from-top-2 duration-300",
      className
    )}></div>
  );
}

export function ProgressIndicator({ progress, className }: ProgressIndicatorProps) {
  const tPi = useTranslations('ProgressIndicator');
  const tPs = useTranslations('ProgressSteps');

  if (!progress || progress.isComplete) return null;

  const steps = config.ui.progressSteps;

  const getStepLabel = (id: number) => tPs(`step${id}.label` as Parameters<typeof tPs>[0]);
  const getStepDescription = (id: number) => tPs(`step${id}.description` as Parameters<typeof tPs>[0]);
  const getStepShortLabel = (id: number) => tPi(`shortLabels.${id}` as Parameters<typeof tPi>[0]);

  const getStepResult = (stepNumber: number) => {
    return progress.stepResults?.find(r => r.step === stepNumber);
  };

  const completedCount = Math.max(0, progress.currentStep - 1);
  const totalSteps = steps.length;
  const progressPercent = (completedCount / Math.max(1, totalSteps - 1)) * 100;

  return (
    <div className={cn("w-full max-w-3xl mx-auto", className)}>
      {/* Mobile layout: compact dots */}
      <div className="sm:hidden">
        <div className="flex items-center gap-1.5 px-1">
          {steps.map((step, index) => {
            const stepNumber = index + 1;
            const isActive = stepNumber === progress.currentStep;
            const isComplete = stepNumber < progress.currentStep;

            return (
              <Tooltip key={step.id} delayDuration={0}>
                <TooltipTrigger asChild>
                  <div
                    className={cn(
                      "h-1.5 rounded-full transition-[background-color,color,opacity] duration-300 flex-1 cursor-pointer",
                      isComplete && "bg-brand",
                      isActive && "bg-brand/50",
                      !isComplete && !isActive && "bg-surface-muted"
                    )}
                  />
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-[250px]">
                  <p className="font-semibold text-xs">{getStepLabel(step.id)}</p>
                  <p className="text-[11px] text-fg-muted mt-0.5">
                    {getStepDescription(step.id)}
                  </p>
                  {isComplete && (
                    <StepResultDetails step={stepNumber} result={getStepResult(stepNumber)?.result} details={getStepResult(stepNumber)?.details} tPi={tPi} />
                  )}
                  {isActive && (
                    <p className="text-[11px] text-brand-fg font-medium mt-1 italic">{tPi('inProgress')}</p>
                  )}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>

      {/* Desktop layout: circles only with progress bar */}
      <div className="hidden sm:block">
        {/* Progress bar */}
        <div className="relative mb-4">
          <div className="h-1 w-full rounded-full bg-surface-muted overflow-hidden">
            <div
              className="h-full w-full origin-left bg-brand rounded-full transition-transform duration-[var(--duration-slow)] ease-out motion-reduce:transition-none"
              style={{ transform: `scaleX(${progressPercent / 100})` }}
            />
          </div>
        </div>

        {/* Step circles with labels */}
        <div className="flex justify-between items-start">
          {steps.map((step, index) => {
            const stepNumber = index + 1;
            const isActive = stepNumber === progress.currentStep;
            const isComplete = stepNumber < progress.currentStep;
            const isPending = stepNumber > progress.currentStep;
            const stepResult = getStepResult(stepNumber);

            return (
              <Tooltip key={step.id} delayDuration={0}>
                <TooltipTrigger asChild>
                  <div className="flex flex-col items-center gap-1.5 cursor-pointer min-w-0 flex-1">
                    <div
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-medium transition-[background-color,color,opacity] duration-300",
                        isComplete && "bg-brand text-on-brand",
                        isActive && "bg-brand/20 text-brand-fg ring-2 ring-brand/50",
                        isPending && "bg-surface-muted text-fg-muted opacity-40"
                      )}
                    >
                      {isComplete ? (
                        <Check className="h-4 w-4" />
                      ) : isActive ? (
                        <Loader2 className="h-4 w-4 animate-spin" />
                      ) : (
                        stepNumber
                      )}
                    </div>
                    <span
                      className={cn(
                        "text-[10px] leading-tight text-center truncate w-full px-0.5 transition-[background-color,color,opacity] duration-300",
                        isComplete && "text-brand-fg font-medium",
                        isActive && "text-brand-fg font-semibold",
                        isPending && "text-fg-muted opacity-40"
                      )}
                    >
                      <span className="lg:hidden">{getStepShortLabel(step.id)}</span>
                      <span className="hidden lg:inline">{getStepLabel(step.id)}</span>
                    </span>
                  </div>
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-[280px]">
                  <p className="font-semibold text-xs">{getStepLabel(step.id)}</p>
                  <p className="text-[11px] text-fg-muted mt-0.5">
                    {getStepDescription(step.id)}
                  </p>
                  {isComplete && (
                    <StepResultDetails step={stepNumber} result={stepResult?.result} details={stepResult?.details} tPi={tPi} />
                  )}
                  {isActive && (
                    <p className="text-[11px] text-brand-fg font-medium mt-1 italic">
                      {tPi('inProgress')}
                    </p>
                  )}
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/**
 * Completed progress stepper: shown after the response is done.
 * All steps appear as completed with hover tooltips showing what was done.
 * A connecting line runs behind the circles.
 */
export function CompletedProgressStepper({ progress, className }: ProgressIndicatorProps) {
  const tPi = useTranslations('ProgressIndicator');
  const tPs = useTranslations('ProgressSteps');

  if (!progress) return null;

  const steps = config.ui.progressSteps;

  const getStepLabel = (id: number) => tPs(`step${id}.label` as Parameters<typeof tPs>[0]);
  const getStepDescription = (id: number) => tPs(`step${id}.description` as Parameters<typeof tPs>[0]);
  const getStepShortLabel = (id: number) => tPi(`shortLabels.${id}` as Parameters<typeof tPi>[0]);

  const getStepResult = (stepNumber: number) => {
    return progress.stepResults?.find(r => r.step === stepNumber);
  };

  // Inline one-liner for the receipt grid; the richer variant with commission
  // details stays in StepResultDetails for the tooltip
  const getStepResultLine = (stepNumber: number): string | undefined => {
    const sr = getStepResult(stepNumber);
    if (stepNumber === 2) {
      const commList = Array.isArray(sr?.details?.commissioni)
        ? (sr.details.commissioni as Array<Record<string, unknown>>)
        : [];
      const top = commList[0];
      const name = top && (typeof top.nome === "string" ? top.nome : typeof top.name === "string" ? top.name : undefined);
      if (name) return name;
    }
    return sr?.result;
  };

  return (
    <div className={cn("w-full", className)}>
      {/* Mobile: progress bar with step labels */}
      <div className="sm:hidden w-full overflow-hidden">
        <div className="flex items-center gap-1 px-1 mb-2">
          {steps.map((step, index) => {
            const stepNumber = index + 1;
            const stepResult = getStepResult(stepNumber);
            return (
              <Tooltip key={step.id} delayDuration={0}>
                <TooltipTrigger asChild>
                  <div className="h-1.5 rounded-full bg-brand flex-1 min-w-0 cursor-pointer" />
                </TooltipTrigger>
                <TooltipContent side="bottom" className="max-w-[250px]">
                  <p className="font-semibold text-xs">{getStepLabel(step.id)}</p>
                  <p className="text-[11px] text-fg-muted mt-0.5">
                    {getStepDescription(step.id)}
                  </p>
                  <StepResultDetails step={stepNumber} result={stepResult?.result} details={stepResult?.details} tPi={tPi} />
                </TooltipContent>
              </Tooltip>
            );
          })}
        </div>
        <div className="flex justify-between px-0.5 overflow-hidden w-full">
          {steps.map((step) => (
            <span
              key={step.id}
              className="text-[8px] leading-tight text-center text-brand-fg font-medium truncate flex-1 min-w-0 px-px"
            >
              {getStepShortLabel(step.id)}
            </span>
          ))}
        </div>
      </div>

      {/* Desktop: receipt grid: the process is over, so each phase reports
          its outcome inline instead of freezing the live-progress stepper */}
      <div className="hidden sm:grid grid-cols-2 lg:grid-cols-4 gap-x-6 gap-y-2.5">
        {steps.map((step, index) => {
          const stepNumber = index + 1;
          const stepResult = getStepResult(stepNumber);
          const resultLine = getStepResultLine(stepNumber);

          return (
            <Tooltip key={step.id} delayDuration={0}>
              <TooltipTrigger asChild>
                <div className="group flex items-start gap-2 cursor-pointer min-w-0">
                  <Check className="mt-[3px] h-3.5 w-3.5 shrink-0 text-brand-fg" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-xs font-medium leading-snug text-fg transition-colors group-hover:text-brand-fg">
                      {getStepLabel(step.id)}
                    </p>
                    {resultLine && (
                      <p className="truncate text-[11px] text-fg-muted">
                        {resultLine}
                      </p>
                    )}
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-[280px]">
                <p className="font-semibold text-xs">{getStepLabel(step.id)}</p>
                <p className="text-[11px] text-fg-muted mt-0.5">
                  {getStepDescription(step.id)}
                </p>
                <StepResultDetails step={stepNumber} result={stepResult?.result} details={stepResult?.details} tPi={tPi} />
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
    </div>
  );
}

/** Map step icon names to Lucide components */
const STEP_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  Search,
  Landmark,
  Users,
  MessageSquare,
  BarChart3,
  Compass,
  PenTool,
  CheckCircle2,
};

/** Map step icon names to Lucide components (moved up) */
type SystemTourFeature = { icon: React.ComponentType<{ className?: string }>; titleKey: string; descKey: string };

const SYSTEM_TOUR_FEATURES_CONFIG: SystemTourFeature[] = [
  { icon: Search, titleKey: "tourSemanticSearch", descKey: "tourSemanticSearchDesc" },
  { icon: Users, titleKey: "tourExpertsPerTopic", descKey: "tourExpertsPerTopicDesc" },
  { icon: Compass, titleKey: "tourIdeologicalCompass", descKey: "tourIdeologicalCompassDesc" },
  { icon: MessageSquare, titleKey: "tourVerifiedCitations", descKey: "tourVerifiedCitationsDesc" },
  { icon: BarChart3, titleKey: "tourBalance", descKey: "tourBalanceDesc" },
  { icon: Landmark, titleKey: "tourCommittees", descKey: "tourCommitteesDesc" },
];

interface ProgressFullPageProps {
  progress: ProcessingProgress;
  query?: string;
  className?: string;
}

/**
 * Full-page progress view shown during pipeline processing (steps 1-6).
 * Uses the entire available space to explain what each step does and why.
 */
export function ProgressFullPage({ progress, query, className }: ProgressFullPageProps) {
  const tPi = useTranslations('ProgressIndicator');
  const tPs = useTranslations('ProgressSteps');

  const getStepLabel = (id: number) => tPs(`step${id}.label` as Parameters<typeof tPs>[0]);
  const getStepDescription = (id: number) => tPs(`step${id}.description` as Parameters<typeof tPs>[0]);
  const getStepWhyDescription = (id: number) => tPs(`step${id}.whyDescription` as Parameters<typeof tPs>[0]);

  // Client-side elapsed counter: starts from backend value, increments every second
  const [localElapsed, setLocalElapsed] = useState(progress.elapsedSeconds ?? 0);

  useEffect(() => {
    if (!progress.isWaiting) return;
    setLocalElapsed(progress.elapsedSeconds ?? 0);
    const interval = setInterval(() => setLocalElapsed(s => s + 1), 1000);
    return () => clearInterval(interval);
  }, [progress.isWaiting, progress.elapsedSeconds]);

  // currentStep: 0 = connecting, first SSE event not yet received
  if (!progress.isWaiting && progress.currentStep === 0) {
    return (
      <div className={cn(
        "flex items-center justify-center w-full min-h-[50vh] md:min-h-[60vh]",
        className
      )}>
        <Loader2 className="h-6 w-6 animate-spin text-brand-fg" />
      </div>
    );
  }

  if (progress.isWaiting) {
    const pos = progress.queuePosition;
    const ahead = progress.aheadCount;
    const active = progress.activeCount ?? 0;

    const formatElapsed = (s: number) =>
      s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;

    // Estimated wait: ~45s per slot ahead (rough average pipeline time)
    const estimatedSec = ahead != null && ahead > 0 ? ahead * 45 : null;
    const formatEstimate = (s: number) =>
      s < 60 ? `~${s}s` : `~${Math.ceil(s / 60)} min`;

    const isNext = ahead === 0;

    return (
      <div className={cn(
        "flex flex-col items-center justify-center w-full min-h-[55vh] md:min-h-[60vh] py-10 px-5",
        className
      )}>
        <div className="w-full max-w-xl">
          {/* The query is the context of the wait: it leads the screen */}
          {query && (
            <div className="text-center mb-7">
              <p className="label-mono mb-2">
                {tPi('yourRequest')}
              </p>
              <p className="serif-display text-xl sm:text-2xl leading-snug text-fg line-clamp-2 [text-wrap:balance]">
                {query}
              </p>
            </div>
          )}

          {/* Status card. The aria-live region wraps only title+description:
              they change on the waiting → next transition, while the facts
              row below ticks every second and must stay out of it, or the
              screen reader would announce the timer continuously. */}
          <div className="rounded-lg border border-line bg-surface px-5 py-4">
            <div role="status" aria-live="polite">
              <div className="flex items-center gap-2.5">
                <span className="relative flex h-2 w-2 shrink-0" aria-hidden="true">
                  <span
                    className={cn(
                      "absolute inline-flex h-full w-full rounded-full opacity-50 motion-safe:animate-ping",
                      isNext ? "bg-brand" : "bg-fg-faint/50"
                    )}
                    style={{ animationDuration: "2s" }}
                  />
                  <span className={cn(
                    "relative inline-flex h-2 w-2 rounded-full",
                    isNext ? "bg-brand" : "bg-fg-faint/70"
                  )} />
                </span>
                <p className="text-sm font-semibold text-fg">
                  {isNext ? tPi('youreNext') : tPi('systemFull')}
                </p>
              </div>
              <p className="text-[13px] text-fg-muted leading-relaxed mt-1.5">
                {isNext ? tPi('youreNextDesc') : tPi('systemFullQueued')}
              </p>
            </div>

            {/* Facts: only values the backend really sent */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 pt-3 border-t border-line text-xs text-fg-muted tabular">
              {pos !== undefined && !isNext && (
                <span>
                  <span className="font-semibold text-fg">#{pos}</span>{" "}
                  {tPi('queuePositionLabel')}
                </span>
              )}
              {ahead != null && ahead > 0 && (
                <span>
                  {ahead === 1
                    ? tPi('systemFullOneAhead', { ahead })
                    : tPi('systemFullManyAhead', { ahead })}
                </span>
              )}
              {active > 0 && <span>{tPi('processingNow', { active })}</span>}
              <span>
                {tPi('waitingFor')}{" "}
                <span className="font-semibold">{formatElapsed(localElapsed)}</span>
              </span>
              {estimatedSec != null && (
                <span>
                  {tPi('estimate')}:{" "}
                  <span className="font-semibold">{formatEstimate(estimatedSec)}</span>
                </span>
              )}
            </div>

            {/* Indeterminate activity line: the system is alive, no fake progress */}
            <div className="mt-3.5 h-[3px] w-full rounded-full bg-surface-muted overflow-hidden" aria-hidden="true">
              <div className="h-full w-1/3 rounded-full bg-brand/50 motion-safe:animate-[queue-slide_2.2s_ease-in-out_infinite] motion-reduce:w-full motion-reduce:bg-brand/20" />
            </div>
          </div>

          <p className="text-[11px] text-fg-muted text-center mt-3 leading-relaxed">
            {tPi('dontClose')}
          </p>

          {/* Capabilities: secondary section, subordinate to the status above */}
          <div className="mt-10 pt-6 border-t border-line">
            <p className="label-mono mb-4">
              {tPi('discoverWhileWaiting')}
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 gap-x-6 gap-y-4 text-left">
              {SYSTEM_TOUR_FEATURES_CONFIG.map((feat) => {
                const Icon = feat.icon;
                return (
                  <div key={feat.titleKey} className="flex items-start gap-2.5">
                    <Icon className="h-3.5 w-3.5 text-brand-fg mt-0.5 shrink-0" aria-hidden="true" />
                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-fg leading-tight">
                        {tPi(feat.titleKey as Parameters<typeof tPi>[0])}
                      </p>
                      <p className="text-[11px] text-fg-muted leading-snug mt-0.5">
                        {tPi(feat.descKey as Parameters<typeof tPi>[0])}
                      </p>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    );
  }

  const steps = config.ui.progressSteps;
  const currentStepConfig = steps.find(s => s.id === progress.currentStep);
  const completedCount = Math.max(0, progress.currentStep - 1);
  const progressPercent = (completedCount / Math.max(1, steps.length - 1)) * 100;

  const getStepResult = (stepNumber: number) => {
    return progress.stepResults?.find(r => r.step === stepNumber);
  };

  const ActiveIcon = currentStepConfig?.icon ? STEP_ICONS[currentStepConfig.icon] : Loader2;

  return (
    <div className={cn("flex flex-col md:flex-row gap-0 md:gap-8 w-full min-h-[50vh] md:min-h-[60vh] py-4 md:py-6 px-3 md:px-8", className)}>

      {/* ===== MOBILE LAYOUT ===== */}
      <div className="md:hidden flex flex-col items-center w-full">
        {/* Mobile progress dots */}
        <div className="w-full mb-5">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[11px] text-fg-muted">{tPi('analysisInProgress')}</span>
            <span className="text-[11px] font-medium text-brand-fg">
              {progress.currentStep} / {steps.length}
            </span>
          </div>
          <div className="flex items-center gap-1">
            {steps.map((step, index) => {
              const stepNumber = index + 1;
              const isActive = stepNumber === progress.currentStep;
              const isComplete = stepNumber < progress.currentStep;
              return (
                <div
                  key={step.id}
                  className={cn(
                    "h-1 rounded-full transition-[background-color,color,opacity] duration-300 flex-1",
                    isComplete && "bg-brand",
                    isActive && "bg-brand/50",
                    !isComplete && !isActive && "bg-surface-muted"
                  )}
                />
              );
            })}
          </div>
        </div>

        {/* Mobile active step card */}
        {currentStepConfig && (
          <div className="w-full text-center space-y-4">
            {/* Icon */}
            <div className="flex justify-center">
              <div className="flex h-14 w-14 items-center justify-center rounded-lg bg-brand-soft text-brand-fg">
                {ActiveIcon ? (
                  <ActiveIcon className="h-7 w-7" />
                ) : (
                  <Loader2 className="h-7 w-7 animate-spin" />
                )}
              </div>
            </div>

            {/* Title */}
            <div>
              <p className="label-mono text-brand-fg mb-0.5">
                Step {progress.currentStep}
              </p>
              <h2 className="serif-display text-xl text-fg">
                {getStepLabel(currentStepConfig.id)}
              </h2>
              <p className="text-xs text-fg-muted mt-0.5">
                {getStepDescription(currentStepConfig.id)}
              </p>
            </div>

            {/* Why */}
            <div className="bg-surface-muted rounded-md px-4 py-3 text-left">
              <p className="text-[13px] text-fg-muted leading-relaxed">
                {getStepWhyDescription(currentStepConfig.id)}
              </p>
            </div>

            {/* Loading */}
            <div className="flex items-center justify-center gap-2 text-sm text-brand-fg">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>{tPi('inProgress')}</span>
            </div>
          </div>
        )}

        {/* Mobile completed results */}
        {progress.stepResults && progress.stepResults.length > 0 && (
          <div className="w-full mt-5 pt-4 border-t border-line">
            <p className="label-mono mb-2">
              {tPi('resultsObtained')}
            </p>
            <div className="space-y-1.5">
              {[...progress.stepResults].sort((a, b) => a.step - b.step).map((sr) => (
                <div key={sr.step} className="flex items-start gap-2">
                  <Check className="h-3.5 w-3.5 text-brand-fg mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <span className="text-[13px] font-medium text-fg">{sr.label}</span>
                    {sr.result && (
                      <p className="text-[11px] text-fg-muted mt-0.5 leading-snug">{sr.result}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Mobile objective */}
        <div className="w-full mt-5 pt-4 border-t border-line">
          <div className="flex items-center gap-1.5 mb-1.5">
            <Target className="h-3 w-3 text-brand-fg" />
            <p className="label-mono">
              {tPi('finalObjective')}
            </p>
          </div>
          <p className="text-[13px] text-fg-muted leading-relaxed">
            {tPi('objectiveText')}
          </p>
        </div>
      </div>

      {/* ===== DESKTOP LAYOUT ===== */}
      {/* LEFT SIDEBAR: Step list + Objective */}
      <div className="hidden md:block w-64 lg:w-72 shrink-0">
        <p className="label-mono mb-4">
          {tPi('analysisPipeline')}
        </p>

        {/* Vertical step list */}
        <div className="space-y-1">
          {steps.map((step, index) => {
            const stepNumber = index + 1;
            const isActive = stepNumber === progress.currentStep;
            const isComplete = stepNumber < progress.currentStep;
            const isPending = stepNumber > progress.currentStep;

            return (
              <div
                key={step.id}
                className={cn(
                  "flex items-center gap-3 px-3 py-2 rounded-md transition-[background-color,color,opacity] duration-300",
                  isActive && "bg-brand-soft",
                  isComplete && "opacity-80",
                  isPending && "opacity-30"
                )}
              >
                {/* Step indicator */}
                <div
                  className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-medium transition-[background-color,color,opacity] duration-300",
                    isComplete && "bg-brand text-on-brand",
                    isActive && "bg-brand/20 text-brand-fg ring-2 ring-brand/40",
                    isPending && "bg-surface-muted text-fg-muted"
                  )}
                >
                  {isComplete ? (
                    <Check className="h-3.5 w-3.5" />
                  ) : isActive ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    stepNumber
                  )}
                </div>

                {/* Label + short result */}
                <div className="min-w-0 flex-1">
                  <p
                    className={cn(
                      "text-sm leading-tight truncate transition-[background-color,color,opacity] duration-300",
                      isComplete && "text-brand-fg font-medium",
                      isActive && "text-brand-fg font-semibold",
                      isPending && "text-fg-muted"
                    )}
                  >
                    {getStepLabel(step.id)}
                  </p>
                  {isComplete && getStepResult(stepNumber)?.result && (
                    <p className="text-[11px] text-fg-muted truncate mt-0.5">
                      {getStepResult(stepNumber)!.result}
                    </p>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Objective */}
        <div className="mt-6 pt-5 border-t border-line">
          <div className="flex items-center gap-2 mb-2">
            <Target className="h-3.5 w-3.5 text-brand-fg" />
            <p className="label-mono">
              {tPi('objective')}
            </p>
          </div>
          <p className="text-sm text-fg-muted leading-relaxed">
            {tPi('objectiveText')}
          </p>
        </div>
      </div>

      {/* DESKTOP MAIN AREA: Active step detail */}
      <div className="hidden md:flex flex-1 flex-col items-center justify-center">
        {/* Progress bar */}
        <div className="w-full max-w-lg mb-8">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-fg-muted">{tPi('progress')}</span>
            <span className="text-xs font-medium text-brand-fg">
              {progress.currentStep} / {steps.length}
            </span>
          </div>
          <div className="h-1.5 w-full rounded-full bg-surface-muted overflow-hidden">
            <div
              className="h-full w-full origin-left bg-brand rounded-full transition-transform duration-[var(--duration-slow)] ease-out motion-reduce:transition-none"
              style={{ transform: `scaleX(${progressPercent / 100})` }}
            />
          </div>
        </div>

        {/* Active step card */}
        {currentStepConfig && (
          <div className="w-full max-w-lg text-center space-y-5">
            {/* Icon */}
            <div className="flex justify-center">
              <div className="flex h-16 w-16 items-center justify-center rounded-lg bg-brand-soft text-brand-fg">
                {ActiveIcon ? (
                  <ActiveIcon className="h-8 w-8" />
                ) : (
                  <Loader2 className="h-8 w-8 animate-spin" />
                )}
              </div>
            </div>

            {/* Step title */}
            <div>
              <p className="label-mono text-brand-fg mb-1">
                Step {progress.currentStep}
              </p>
              <h2 className="serif-display text-2xl lg:text-[1.875rem] text-fg">
                {getStepLabel(currentStepConfig.id)}
              </h2>
              <p className="text-sm text-fg-muted mt-1">
                {getStepDescription(currentStepConfig.id)}
              </p>
            </div>

            {/* Why description */}
            <div className="bg-surface-muted rounded-md px-6 py-4 text-left">
              <p className="text-sm text-fg-muted leading-relaxed">
                {getStepWhyDescription(currentStepConfig.id)}
              </p>
            </div>

            {/* Loading indicator */}
            <div className="flex items-center justify-center gap-2 text-sm text-brand-fg">
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>{tPi('inProgress')}</span>
            </div>
          </div>
        )}

        {/* Completed results summary */}
        {progress.stepResults && progress.stepResults.length > 0 && (
          <div className="w-full max-w-lg mt-8 pt-6 border-t border-line">
            <p className="label-mono mb-3">
              {tPi('resultsObtained')}
            </p>
            <div className="space-y-2">
              {[...progress.stepResults].sort((a, b) => a.step - b.step).map((sr) => (
                <div key={sr.step} className="flex items-start gap-2.5">
                  <Check className="h-4 w-4 text-brand-fg mt-0.5 shrink-0" />
                  <div className="min-w-0">
                    <span className="text-sm font-medium text-fg">{sr.label}</span>
                    {sr.result && (
                      <p className="text-xs text-fg-muted mt-0.5 leading-relaxed">{sr.result}</p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Compact version for inline display
export function ProgressIndicatorCompact({ progress }: ProgressIndicatorProps) {
  if (!progress) return null;

  return (
    <div className="flex items-center gap-3 text-sm text-fg-muted">
      <Loader2 className="h-4 w-4 animate-spin text-brand-fg" />
      <span>
        {progress.stepLabel} ({progress.currentStep}/{progress.totalSteps})
      </span>
    </div>
  );
}
