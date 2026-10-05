import { useTranslations } from "next-intl";
import type { DossierCompass } from "@/lib/dossier";

/* The compass reduced to its first axis: one line per group, a dot at its
   estimated position. Confidence under 0.7 draws a hollow dot. */
export function CompassAxis({ compass }: { compass: DossierCompass }) {
  const t = useTranslations("Dossier");
  const span = Math.max(...compass.points.map((p) => Math.abs(p.x)), 1);
  const pct = (x: number) => 50 + (x / span) * 46;
  return (
    <div className="flex flex-col gap-3">
      <div className="flex justify-between gap-4 text-caption text-fg-secondary">
        <span className="max-w-[45%]">{compass.negative}</span>
        <span className="max-w-[45%] text-right">{compass.positive}</span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {compass.points.map((p) => (
          <li key={p.abbrev} className="grid grid-cols-[3rem_minmax(0,1fr)] items-center gap-2">
            <span className="font-mono text-xs text-fg-secondary">{p.abbrev}</span>
            <span className="relative h-4">
              <span className="absolute inset-x-0 top-1/2 h-px bg-line-strong" aria-hidden />
              <span className="absolute top-1/2 left-1/2 h-2 w-px -translate-y-1/2 bg-line-control" aria-hidden />
              <span
                className={
                  p.confidence >= 0.7
                    ? "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-brand"
                    : "absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-brand bg-bg"
                }
                style={{ left: `${pct(p.x)}%` }}
                title={`${p.x.toFixed(2)}`}
              />
            </span>
          </li>
        ))}
      </ul>
      <p className="text-caption text-fg-muted">
        {t("compassNote")} {!compass.stable && t("compassUnstable")}
      </p>
    </div>
  );
}
