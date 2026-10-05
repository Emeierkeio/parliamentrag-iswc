"use client";

import { useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import { Check, ChevronDown, Landmark } from "lucide-react";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type Chamber = "camera" | "senato";
export type Legislature = 19 | 18;
export interface Scope {
  chambers: Chamber[];
  legislature: Legislature;
}

/* Pairs with data in production, as "camera_19,senato_19". Set at build time
   so a staging deploy can expose the Senate or the XVIII before production.
   The reader picks only the legislature: every chamber loaded for it is
   searched together. */
const AVAILABLE = new Set((process.env.NEXT_PUBLIC_SCOPES ?? "camera_19").split(",").map((s) => s.trim()));
const CHAMBERS: Chamber[] = ["camera", "senato"];
const LEGISLATURES: Legislature[] = [19, 18];

export const chambersFor = (l: Legislature) => CHAMBERS.filter((c) => AVAILABLE.has(`${c}_${l}`));

const KEY = "legislature";
const DEFAULT_LEG: Legislature = 19;
const listeners = new Set<() => void>();

function readLegislature(): Legislature {
  try {
    const n = Number(localStorage.getItem(KEY));
    if (LEGISLATURES.includes(n as Legislature) && chambersFor(n as Legislature).length) return n as Legislature;
  } catch {}
  return DEFAULT_LEG;
}

function subscribe(cb: () => void) {
  listeners.add(cb);
  window.addEventListener("storage", cb);
  return () => {
    listeners.delete(cb);
    window.removeEventListener("storage", cb);
  };
}

function setLegislature(l: Legislature) {
  try {
    localStorage.setItem(KEY, String(l));
  } catch {}
  listeners.forEach((cb) => cb());
}

/** The (chamber, legislature) pairs every question, dossier and index uses. */
export function useScope(): [Scope, (l: Legislature) => void] {
  const legislature = useSyncExternalStore(subscribe, readLegislature, () => DEFAULT_LEG);
  return [{ legislature, chambers: chambersFor(legislature) }, setLegislature];
}

const ROMAN: Record<Legislature, string> = { 19: "XIX", 18: "XVIII" };

function chamberLabel(t: ReturnType<typeof useTranslations>, chambers: Chamber[]): string {
  if (chambers.length === 2) return t("scopeBoth");
  return chambers[0] === "senato" ? t("scopeSenato") : t("scopeCamera");
}

export function useScopeLabel(): string {
  const t = useTranslations("Shell");
  const [scope] = useScope();
  return `${chamberLabel(t, scope.chambers)} · ${t("scopeLegislature", { n: ROMAN[scope.legislature] })}`;
}

export function ScopeSelector({ className }: { className?: string }) {
  const t = useTranslations("Shell");
  const [scope, choose] = useScope();
  const label = useScopeLabel();

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          className={cn(
            "inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-line-strong bg-surface px-3 text-[13px] text-fg-secondary transition-colors hover:border-line-control hover:text-fg",
            className,
          )}
          aria-label={t("scopeTitle")}
        >
          <Landmark className="size-3.5" aria-hidden />
          <span className="whitespace-nowrap">{label}</span>
          <ChevronDown className="size-3.5" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent align="start" sideOffset={8} className="w-80 p-2">
        <p className="label-mono px-2.5 pt-1.5 pb-2 text-fg-muted">{t("scopeLegislatureTitle")}</p>
        <div role="menu" className="flex flex-col">
          {LEGISLATURES.map((l) => {
            const chambers = chambersFor(l);
            const available = chambers.length > 0;
            const active = scope.legislature === l;
            return (
              <button
                key={l}
                type="button"
                role="menuitemradio"
                aria-checked={active}
                disabled={!available}
                onClick={() => choose(l)}
                className={cn(
                  "flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left transition-colors",
                  active ? "bg-surface-brand" : available ? "hover:bg-surface-muted" : "cursor-not-allowed",
                )}
              >
                <span className="flex min-w-0 flex-1 flex-col">
                  <span className={cn("text-sm", available ? "text-fg" : "text-fg-muted")}>
                    {t("scopeLegislature", { n: ROMAN[l] })}
                  </span>
                  <span className="text-xs text-fg-muted">
                    {t(l === 19 ? "scopeLeg19Sub" : "scopeLeg18Sub")}
                    {available && ` · ${chamberLabel(t, chambers)}`}
                  </span>
                </span>
                {active ? (
                  <Check className="size-4 text-brand-fg" aria-hidden />
                ) : (
                  !available && <span className="label-mono text-[10px] text-fg-muted">{t("scopeSoon")}</span>
                )}
              </button>
            );
          })}
        </div>
        <p className="mt-3 border-t border-line px-2.5 pt-3 pb-1 text-xs leading-relaxed text-fg-muted">
          {chambersFor(scope.legislature).length === 2 ? t("scopeNoteBoth") : t("scopeNoteCamera")}
        </p>
      </PopoverContent>
    </Popover>
  );
}
