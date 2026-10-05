"use client";

import { useTranslations } from "next-intl";
import { Check, ChevronDown, Info, Landmark } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";

// Rows are plain divs, not options: the corpus is a single (chamber,
// legislature) pair today, and the popover exists to state that scope
// explicitly and to reserve the spot where the real selector will land.
function ScopeRow({
  label,
  sub,
  active,
  soonLabel,
}: {
  label: string;
  sub?: string;
  active?: boolean;
  soonLabel?: string;
}) {
  return (
    <div
      aria-disabled={!active || undefined}
      className={cn(
        "flex items-center justify-between gap-3 rounded-md px-2.5 py-2",
        active ? "bg-surface-brand" : "opacity-70"
      )}
    >
      <div className="min-w-0">
        <p
          className={cn(
            "text-sm leading-snug",
            active ? "font-medium text-fg" : "text-fg-muted"
          )}
        >
          {label}
        </p>
        {sub && <p className="text-xs text-fg-muted">{sub}</p>}
      </div>
      {active ? (
        <Check className="h-4 w-4 shrink-0 text-brand-fg" aria-hidden="true" />
      ) : (
        soonLabel && (
          <span className="shrink-0 rounded-sm border border-line-strong px-2 py-0.5 text-[11px] text-fg-muted">
            {soonLabel}
          </span>
        )
      )}
    </div>
  );
}

export function ScopePicker({
  variant = "hero",
}: {
  /** "hero" is the welcome-screen eyebrow: selector affordance (chevron,
      option rows) because the scope will become choosable there. "meta"
      sits in a report metadata row where the answer is already built on a
      fixed corpus, so it must read as provenance: Info icon, no option
      rows, plain disclosure text. "sidebar" is the app-wide placement in
      the dark rail: same selector semantics as "hero", sidebar tokens. */
  variant?: "hero" | "meta" | "sidebar";
}) {
  const t = useTranslations("WelcomeScreen");
  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          aria-label={t("scopeAria")}
          className={cn(
            "group inline-flex items-center transition-colors cursor-pointer",
            variant === "hero" &&
              "label-mono gap-2 rounded-full border border-line-strong px-3.5 py-1.5 hover:border-fg-faint hover:text-fg",
            variant === "meta" &&
              "gap-1.5 rounded-full border border-line-strong px-2.5 py-0.5 text-xs font-medium text-fg-muted hover:border-fg-faint hover:text-fg",
            variant === "sidebar" &&
              "w-full gap-2 rounded-md border border-sidebar-border px-2.5 py-1.5 text-[10px] uppercase tracking-[0.12em] text-sidebar-foreground/60 hover:border-sidebar-foreground/30 hover:text-sidebar-foreground"
          )}
        >
          <Landmark
            className={variant === "meta" ? "h-3 w-3" : "h-3.5 w-3.5 shrink-0"}
            aria-hidden="true"
          />
          <span className={variant === "sidebar" ? "truncate" : undefined}>
            {variant === "sidebar" ? t("badgeShort") : t("badge")}
          </span>
          {variant === "meta" ? (
            <Info className="h-3 w-3 opacity-60" aria-hidden="true" />
          ) : (
            <ChevronDown
              className={cn(
                "h-3 w-3 opacity-60 transition-transform duration-200 motion-reduce:transition-none group-data-[state=open]:rotate-180",
                variant === "sidebar" && "ml-auto shrink-0"
              )}
              aria-hidden="true"
            />
          )}
        </button>
      </PopoverTrigger>
      {variant !== "meta" ? (
        <PopoverContent
          align="center"
          sideOffset={8}
          className="w-80 overflow-hidden p-0 text-left"
        >
          <div className="px-2 pb-1 pt-2.5">
            <p className="label-mono px-2.5 pb-1.5">
              {t("scopeBranch")}
            </p>
            <ScopeRow
              active
              label={t("scopeCamera")}
              sub={t("scopeCameraSub")}
            />
            <ScopeRow label={t("scopeSenate")} soonLabel={t("scopeSoon")} />
          </div>
          <div className="px-2 pb-2.5 pt-1.5">
            <p className="label-mono px-2.5 pb-1.5">
              {t("scopeLegislature")}
            </p>
            <ScopeRow active label={t("scopeLeg19")} sub={t("scopeLeg19Sub")} />
            <ScopeRow label={t("scopeLegPast")} soonLabel={t("scopeSoon")} />
          </div>
          <p className="border-t border-line bg-surface-muted px-4 py-3 text-xs leading-relaxed text-fg-muted">
            {t("scopeNote")}
          </p>
        </PopoverContent>
      ) : (
        <PopoverContent
          align="start"
          sideOffset={8}
          className="w-72 p-4 text-left"
        >
          <p className="mb-1.5 text-sm font-medium text-fg">
            {t("scopeMetaTitle")}
          </p>
          <p className="text-xs leading-relaxed text-fg-muted">
            {t("scopeMetaNote")}
          </p>
        </PopoverContent>
      )}
    </Popover>
  );
}
