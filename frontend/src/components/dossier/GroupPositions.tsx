import { useTranslations } from "next-intl";
import { SourceLink } from "@/components/dossier/SourceLink";
import { BLOC_ORDER, type DossierGroup } from "@/lib/dossier";
import { formatDay } from "@/components/dossier/format";

/* One row per group, grouped by bloc: the stance in one sentence, the
   strongest verbatim quote, the number of speeches behind it. */
export function GroupPositions({ groups, locale }: { groups: DossierGroup[]; locale: string }) {
  const t = useTranslations("Dossier");
  return (
    <div className="flex flex-col">
      {BLOC_ORDER.map((bloc) => {
        const rows = groups.filter((g) => g.bloc === bloc);
        if (!rows.length) return null;
        return (
          <section key={bloc} aria-labelledby={`bloc-${bloc}`} className="pt-6 first:pt-0">
            <h3 id={`bloc-${bloc}`} className="label-mono pb-2 text-fg-muted">
              {t(`bloc_${bloc}`)}
            </h3>
            <ul className="divide-y divide-line border-y border-line">
              {rows.map((g) => (
                <li
                  key={g.abbrev}
                  className="grid grid-cols-[3.5rem_minmax(0,1fr)] gap-x-4 gap-y-3 py-4 md:grid-cols-[3.5rem_minmax(0,1fr)_minmax(0,1.35fr)_3rem] md:gap-x-5"
                >
                  <span className="pt-0.5 text-[15px] font-semibold" title={g.name}>
                    {g.abbrev === "Gov" ? t("bloc_governo") : g.abbrev}
                  </span>
                  <div className="flex flex-col gap-1.5">
                    <p className="text-sm leading-relaxed text-fg">{g.gist}</p>
                    <details className="group text-sm">
                      <summary className="cursor-pointer list-none text-[13px] text-brand-fg underline-offset-4 hover:underline [&::-webkit-details-marker]:hidden">
                        {t("readSummary")}
                      </summary>
                      <p className="mt-2 max-w-prose leading-relaxed text-fg-secondary">{g.paragraph}</p>
                    </details>
                  </div>
                  <figure className="col-span-2 flex flex-col gap-2 md:col-span-1">
                    {g.quote ? (
                      <>
                        <blockquote className="font-serif text-[15px] italic leading-[1.5] text-fg">
                          «{g.quote.text}»
                        </blockquote>
                        <figcaption className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs text-fg-muted">
                          <span>{g.quote.speaker}</span>
                          {g.quote.date && (
                            <>
                              <span aria-hidden>·</span>
                              <time dateTime={g.quote.date}>{formatDay(g.quote.date, locale)}</time>
                            </>
                          )}
                          <SourceLink id={g.quote.interventionId ?? g.quote.chunkId} verified={g.quote.verified} />
                        </figcaption>
                      </>
                    ) : (
                      <p className="text-sm text-fg-muted">{t("noQuote")}</p>
                    )}
                  </figure>
                  <span className="hidden pt-1 text-right font-mono text-xs tabular-nums text-fg-muted md:block">
                    {g.interventions > 0 && t("interventionsShort", { n: g.interventions })}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
