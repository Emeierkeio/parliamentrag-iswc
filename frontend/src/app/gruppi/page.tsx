"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { graphQuery } from "@/lib/graph";
import { COALITION_ORDER, coalitionOf, groupLabel, groupSlug, type Coalition } from "@/components/entities/groups";
import { getGroupAbbrev } from "@/config";
import { PartyLogo } from "@/components/entities/PartyLogo";

interface GroupRow {
  name: string;
  members: number;
}

// Solo le appartenenze correnti: chi e' transitato da un gruppo a inizio
// legislatura non deve comparire ne' nei conteggi ne' negli elenchi
const DIRECTORY_QUERY =
  "MATCH (g:ParliamentaryGroup)<-[m:MEMBER_OF_GROUP]-(d:Deputy) " +
  "WHERE m.end_date IS NULL " +
  "RETURN g.name AS name, count(DISTINCT d) AS members ORDER BY members DESC";

/** Se due nomi mappano sullo stesso slug tiene quello con più componenti.
 * Le righe arrivano già ordinate per componenti in senso decrescente. */
function dedupeBySlug(rows: GroupRow[]): GroupRow[] {
  const seen = new Set<string>();
  const out: GroupRow[] = [];
  for (const row of rows) {
    const slug = groupSlug(row.name);
    if (seen.has(slug)) continue;
    seen.add(slug);
    out.push(row);
  }
  return out;
}

function percent(n: number, total: number): string {
  return total > 0 ? ((n / total) * 100).toFixed(1) : "0";
}

export default function GruppiPage() {
  const t = useTranslations("Entities");
  const td = useTranslations("Dossier");
  const [groups, setGroups] = useState<GroupRow[] | null>(null);
  const [error, setError] = useState(false);
  const [coalition, setCoalition] = useState<Coalition | null>(null);

  const load = useCallback(() => {
    setError(false);
    setGroups(null);
    graphQuery<GroupRow>(DIRECTORY_QUERY)
      .then((rows) => setGroups(dedupeBySlug(rows)))
      .catch(() => setError(true));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const total = useMemo(() => (groups ?? []).reduce((s, g) => s + g.members, 0), [groups]);
  const byCoalition = useMemo(
    () =>
      COALITION_ORDER.map((c) => {
        const rows = (groups ?? []).filter((g) => coalitionOf(g.name) === c);
        return { c, groups: rows.length, members: rows.reduce((s, g) => s + g.members, 0) };
      }),
    [groups]
  );
  const visible = useMemo(
    () => (groups ?? []).filter((g) => !coalition || coalitionOf(g.name) === coalition),
    [groups, coalition]
  );

  const pill = (active: boolean) =>
    `inline-flex h-9 shrink-0 items-center gap-1.5 rounded-full border px-3.5 text-[13px] transition-colors ${
      active
        ? "border-brand bg-brand text-on-brand"
        : "border-line-strong text-fg-secondary hover:bg-surface hover:text-fg cursor-pointer"
    }`;

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppBar />
      <main className="container-page flex-1 pb-[calc(4rem+env(safe-area-inset-bottom))]">
        <header className="flex flex-col gap-3 pt-10 md:pt-14">
          <p className="label-mono text-fg-muted">{td("scope")}</p>
          <h1 className="serif-display text-[2.5rem] leading-[1.05] text-fg md:text-display-l">{t("groupsTitle")}</h1>
          <p className="max-w-prose text-[15px] text-fg-secondary">{t("groupsIntro")}</p>
        </header>

        <div className="grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-6 pt-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="flex min-w-0 flex-col gap-4">
            <div
              role="group"
              aria-label={t("coalitionLabel")}
              className="-mx-4 flex gap-2 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:px-0 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
            >
              <button type="button" aria-pressed={coalition === null} onClick={() => setCoalition(null)} className={pill(coalition === null)}>
                {t("allGroups")}
              </button>
              {COALITION_ORDER.map((c) => (
                <button
                  key={c}
                  type="button"
                  aria-pressed={coalition === c}
                  onClick={() => setCoalition(coalition === c ? null : c)}
                  className={pill(coalition === c)}
                >
                  {td(`bloc_${c}`)}
                </button>
              ))}
            </div>

            {error ? (
              <div className="rounded-lg border border-line bg-surface py-12 text-center">
                <p className="text-sm text-fg-muted">{t("errorLoad")}</p>
                <button type="button" onClick={load} className="link mt-3 text-sm">
                  {t("retry")}
                </button>
              </div>
            ) : groups === null ? (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
                {Array.from({ length: 9 }).map((_, i) => (
                  <li key={i} className="h-36 rounded-lg bg-surface-sunken animate-skeleton" />
                ))}
              </ul>
            ) : visible.length === 0 ? (
              <p className="rounded-lg border border-line bg-surface py-12 text-center text-sm text-fg-muted">{t("noResults")}</p>
            ) : (
              <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {visible.map((g) => (
                  <li key={g.name} className="min-w-0">
                    <Link
                      href={`/gruppi/${groupSlug(g.name)}`}
                      className="group flex h-full flex-col gap-3 rounded-lg border border-line bg-surface p-5 transition-colors hover:border-line-strong hover:bg-surface-muted"
                    >
                      <span className="flex items-center justify-between gap-3">
                        <span className="flex items-center gap-2.5">
                          <PartyLogo group={g.name} size={28} />
                          <span className="text-2xl font-semibold tracking-[var(--tracking-heading)] text-fg">
                          {getGroupAbbrev(g.name)}
                          </span>
                        </span>
                        <span className="label-mono text-fg-muted">{td(`bloc_${coalitionOf(g.name)}`)}</span>
                      </span>
                      <span className="line-clamp-2 text-sm leading-snug text-fg-secondary group-hover:text-fg">
                        {groupLabel(g.name)}
                      </span>
                      <span className="mt-auto flex flex-col gap-2 pt-1">
                        <span className="h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                          <span className="block h-full rounded-full bg-fg-muted" style={{ width: `${percent(g.members, total)}%` }} />
                        </span>
                        <span className="flex items-baseline justify-between gap-3 text-[13px]">
                          <span className="tabular text-fg">{t("membersCount", { count: g.members })}</span>
                          <span className="tabular font-mono text-xs text-fg-muted">
                            {t("seatShare", { share: percent(g.members, total) })}
                          </span>
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>

          <aside className="order-first flex flex-col gap-6 lg:order-none lg:sticky lg:top-[calc(var(--header-h)+2rem)] lg:self-start">
            <section aria-labelledby="composition-h" className="rounded-lg border border-line bg-surface p-5">
              <h2 id="composition-h" className="label-mono text-fg-muted">{t("compositionTitle")}</h2>
              {groups === null ? (
                <div className="mt-4 h-14 rounded-md bg-surface-sunken animate-skeleton" aria-hidden />
              ) : (
                <>
                  <p className="mt-3 flex items-baseline gap-2">
                    <span className="tabular text-3xl font-semibold text-fg">{total}</span>
                    <span className="text-sm text-fg-muted">{t("membersTitle").toLowerCase()}</span>
                  </p>
                  <div className="mt-4 flex h-2 gap-0.5 overflow-hidden rounded-full" aria-hidden>
                    {byCoalition.map((b, i) => (
                      <span
                        key={b.c}
                        className={i === 0 ? "bg-fg" : i === 1 ? "bg-fg-muted" : "bg-line-strong"}
                        style={{ width: `${percent(b.members, total)}%` }}
                      />
                    ))}
                  </div>
                  <ul className="mt-4 flex flex-col divide-y divide-line">
                    {byCoalition.map((b, i) => (
                      <li key={b.c}>
                        <button
                          type="button"
                          aria-pressed={coalition === b.c}
                          onClick={() => setCoalition(coalition === b.c ? null : b.c)}
                          className={`-mx-2 flex w-[calc(100%+1rem)] cursor-pointer items-center gap-3 rounded-md px-2 py-2.5 text-left text-sm transition-colors ${
                            coalition === b.c ? "bg-brand-soft" : "hover:bg-surface-muted"
                          }`}
                        >
                          <span
                            aria-hidden
                            className={`h-2.5 w-2.5 shrink-0 rounded-full ${i === 0 ? "bg-fg" : i === 1 ? "bg-fg-muted" : "bg-line-strong"}`}
                          />
                          <span className="flex-1 text-fg">{td(`bloc_${b.c}`)}</span>
                          <span className="tabular text-fg">{b.members}</span>
                          <span className="tabular w-12 text-right font-mono text-xs text-fg-muted">{percent(b.members, total)}%</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </section>
            <Link
              href="/parlamentari"
              className="hidden items-center gap-1.5 text-sm font-medium text-brand-fg hover:underline lg:inline-flex"
            >
              {t("deputiesTitle")}
              <ArrowRight className="h-3.5 w-3.5" aria-hidden />
            </Link>
          </aside>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
