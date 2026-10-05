import { useTranslations } from "next-intl";
import type { AuthorityWeights, DossierVoice } from "@/lib/dossier";

function displayName(name: string): string {
  if (name !== name.toUpperCase()) return name;
  return name.toLowerCase().replace(/(^|[\s'-])(\p{L})/gu, (_, sep, c) => sep + c.toUpperCase());
}

const pct = (v: number) => Math.round(v * 100);

/* Authority per deputy: the overall score as a number and a bar, the two
   criteria that weigh most in words, and all six on demand. */
export function VoicesMatrix({ voices, weights, pool }: { voices: DossierVoice[]; weights: AuthorityWeights | null; pool: number }) {
  const t = useTranslations("Dossier");
  if (!voices.length) return null;
  return (
    <div className="flex flex-col gap-1">
      <ol className="flex flex-col divide-y divide-line">
        {voices.map((v) => {
          const top = [...v.breakdown].sort((a, b) => b.value - a.value).slice(0, 2);
          return (
            <li key={v.id} className="py-3 first:pt-0">
              <details className="group">
                <summary className="flex cursor-pointer list-none flex-col gap-1.5 [&::-webkit-details-marker]:hidden">
                  <span className="flex items-baseline gap-2">
                    <span className="min-w-0 flex-1 truncate text-sm text-fg">
                      {displayName(v.name)} <span className="font-mono text-xs text-fg-muted">{v.abbrev}</span>
                    </span>
                    <span className="font-mono text-sm font-medium tabular-nums text-fg" title={t("voicesScore")}>
                      {pct(v.score)}
                    </span>
                  </span>
                  <span className="block h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                    <span className="block h-full rounded-full bg-brand" style={{ width: `${pct(v.score)}%` }} />
                  </span>
                  <span className="text-xs text-fg-muted">
                    {top.map((b) => `${t(`dim_${b.key}`)} ${pct(b.value)}`).join(" · ")}
                    <span className="ml-1.5 text-brand-fg group-open:hidden">{t("voicesMore")}</span>
                  </span>
                </summary>
                <dl className="mt-3 grid grid-cols-[6.5rem_minmax(0,1fr)_2rem] items-center gap-x-2 gap-y-1.5 text-xs">
                  {v.breakdown.map((b) => (
                    <div key={b.key} className="contents">
                      <dt className="text-fg-secondary">{t(`dim_${b.key}`)}</dt>
                      <dd className="h-1.5 overflow-hidden rounded-full bg-surface-sunken">
                        <span className="block h-full rounded-full bg-brand/70" style={{ width: `${pct(b.value)}%` }} />
                      </dd>
                      <dd className="text-right font-mono tabular-nums text-fg-secondary">{pct(b.value)}</dd>
                    </div>
                  ))}
                </dl>
                {v.profileUrl && (
                  <a href={v.profileUrl} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-brand-fg hover:underline">
                    {t("voicesProfile")}
                  </a>
                )}
              </details>
            </li>
          );
        })}
      </ol>
      <p className="pt-2 text-caption text-fg-muted">{t("voicesLegend")}</p>
      {weights && (
        <p className="text-caption text-fg-muted">
          {t("voicesWeights", {
            n: pool,
            weights: Object.entries(weights)
              .sort((a, b) => b[1] - a[1])
              .map(([k, w]) => `${t(`dim_${k === "interventions" ? "speeches" : k}`)} ${Math.round(w * 100)}`)
              .join(", "),
          })}
        </p>
      )}
    </div>
  );
}
