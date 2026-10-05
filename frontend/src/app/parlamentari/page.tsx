"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Search, X } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { DeputyAvatar } from "@/components/entities/DeputyAvatar";
import { PartyLogo } from "@/components/entities/PartyLogo";
import { COALITION_ORDER, coalitionOf, groupLabel } from "@/components/entities/groups";
import { graphQuery, deputySlug } from "@/lib/graph";
import { getGroupAbbrev } from "@/config";
import { toTitleCase } from "@/lib/utils";

interface DeputyRow {
  id: string;
  first_name: string;
  last_name: string;
  photo: string | null;
  profession: string | null;
  group: string | null;
}

// One row per deputy: whoever changed group has several memberships, so
// the current one (no end_date) is collected first and the rest dropped
const DIRECTORY_CYPHER =
  "MATCH (d:Deputy) " +
  "OPTIONAL MATCH (d)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup) " +
  "WITH d, g, m ORDER BY m.end_date IS NOT NULL, m.start_date DESC " +
  "WITH d, collect(g.name)[0] AS group " +
  "RETURN d.id AS id, d.first_name AS first_name, d.last_name AS last_name, " +
  "d.photo AS photo, d.profession AS profession, group " +
  "ORDER BY d.last_name, d.first_name";

const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ".split("");

function lastNameInitial(lastName: string): string {
  return (lastName.trim().charAt(0) || "")
    .normalize("NFD")
    .charAt(0)
    .toUpperCase();
}

export default function DeputiesDirectoryPage() {
  const t = useTranslations("Entities");
  const td = useTranslations("Dossier");

  const [deputies, setDeputies] = useState<DeputyRow[] | null>(null);
  const [error, setError] = useState(false);
  const [search, setSearch] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  // 400+ rows with photos are a wall: the index opens on the A surnames,
  // null = the whole directory. Typing in the search bypasses the letter.
  const [letter, setLetter] = useState<string | null>("A");

  const load = useCallback(async () => {
    setError(false);
    setDeputies(null);
    try {
      const rows = await graphQuery<DeputyRow>(DIRECTORY_CYPHER);
      setDeputies(rows);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const groupCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const d of deputies ?? []) {
      if (d.group) counts.set(d.group, (counts.get(d.group) ?? 0) + 1);
    }
    return Array.from(counts, ([name, n]) => ({ name, n })).sort((a, b) => b.n - a.n);
  }, [deputies]);

  const groupOptions = useMemo(
    () => groupCounts.map((g) => g.name).sort((a, b) => groupLabel(a).localeCompare(groupLabel(b), "it")),
    [groupCounts]
  );

  const maxGroup = groupCounts[0]?.n ?? 1;

  const presentLetters = useMemo(() => {
    if (!deputies) return new Set<string>();
    return new Set(deputies.map((d) => lastNameInitial(d.last_name)));
  }, [deputies]);

  const filtered = useMemo(() => {
    if (!deputies) return [];
    const needle = search.trim().toLowerCase();
    return deputies.filter((d) => {
      if (groupFilter && d.group !== groupFilter) return false;
      if (needle) {
        const fullName = `${d.first_name} ${d.last_name}`.toLowerCase();
        const reversed = `${d.last_name} ${d.first_name}`.toLowerCase();
        return fullName.includes(needle) || reversed.includes(needle);
      }
      if (letter) return lastNameInitial(d.last_name) === letter;
      return true;
    });
  }, [deputies, search, groupFilter, letter]);

  const letterBase = "h-8 shrink-0 rounded-full text-sm tabular-nums transition-colors";
  const letterIdle = "text-fg-secondary hover:bg-surface-muted hover:text-fg cursor-pointer";
  const letterActive = "bg-brand font-medium text-on-brand";

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppBar />
      <main className="container-page flex-1 pb-[calc(4rem+env(safe-area-inset-bottom))]">
        <header className="flex flex-col gap-3 pt-10 md:pt-14">
          <p className="label-mono text-fg-muted">{td("scope")}</p>
          <h1 className="serif-display text-[2.5rem] leading-[1.05] text-fg md:text-display-l">{t("deputiesTitle")}</h1>
          <p className="max-w-prose text-[15px] text-fg-secondary">{t("deputiesIntro")}</p>
        </header>

        <div className="grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-6 pt-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="flex min-w-0 flex-col gap-4">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-fg-muted" aria-hidden />
                <input
                  type="search"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t("searchDeputyPlaceholder")}
                  aria-label={t("searchDeputyPlaceholder")}
                  className="h-10 w-full rounded-md border border-line-control bg-surface pl-9 pr-3 text-sm text-fg outline-none transition-colors placeholder:text-fg-muted focus-visible:border-fg"
                />
              </div>
              <select
                value={groupFilter}
                onChange={(e) => setGroupFilter(e.target.value)}
                aria-label={t("allGroups")}
                className="h-10 w-full rounded-md border border-line-control bg-surface px-3 text-sm text-fg outline-none transition-colors focus-visible:border-fg sm:w-64"
              >
                <option value="">{t("allGroups")}</option>
                {groupOptions.map((g) => (
                  <option key={g} value={g}>
                    {getGroupAbbrev(g)} · {groupLabel(g)}
                  </option>
                ))}
              </select>
            </div>

            {/* Surname index; a text search overrides it */}
            <div
              className="-mx-4 flex gap-0.5 overflow-x-auto px-4 sm:mx-0 sm:flex-wrap sm:overflow-visible sm:px-0 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
              role="group"
              aria-label={t("letterIndex")}
            >
              {LETTERS.map((L) => {
                const enabled = presentLetters.has(L);
                const active = letter === L && !search.trim();
                return (
                  <button
                    key={L}
                    type="button"
                    disabled={!enabled}
                    onClick={() => setLetter(L)}
                    aria-pressed={active}
                    className={`${letterBase} w-8 sm:w-7 ${active ? letterActive : enabled ? letterIdle : "text-fg-faint"}`}
                  >
                    {L}
                  </button>
                );
              })}
              <button
                type="button"
                onClick={() => setLetter(null)}
                aria-pressed={letter === null && !search.trim()}
                className={`${letterBase} px-3 ${letter === null && !search.trim() ? letterActive : letterIdle}`}
              >
                {t("allLetters")}
              </button>
            </div>

            {error ? (
              <div className="rounded-lg border border-line bg-surface py-12 text-center">
                <p className="text-sm text-fg-muted">{t("errorLoad")}</p>
                <button
                  type="button"
                  onClick={load}
                  className="mt-4 inline-flex h-9 items-center rounded-full border border-line-strong bg-surface px-4 text-sm text-fg transition-colors hover:bg-surface-muted"
                >
                  {t("retry")}
                </button>
              </div>
            ) : deputies === null ? (
              <div className="grid gap-3 pt-7 sm:grid-cols-2 xl:grid-cols-3" aria-hidden>
                {Array.from({ length: 12 }).map((_, i) => (
                  <div key={i} className="h-[4.5rem] rounded-lg bg-surface-sunken animate-skeleton" />
                ))}
              </div>
            ) : (
              <div>
                <div className="flex items-center justify-between gap-3 border-b border-line pb-2">
                  <p className="tabular font-mono text-caption text-fg-muted">
                    {t("membersCount", { count: filtered.length })}
                  </p>
                  {groupFilter && (
                    <button
                      type="button"
                      onClick={() => setGroupFilter("")}
                      className="inline-flex h-7 items-center gap-1 rounded-full border border-line-strong px-2.5 text-xs text-fg-secondary transition-colors hover:bg-surface hover:text-fg"
                    >
                      <span className="font-semibold">{getGroupAbbrev(groupFilter)}</span>
                      <X className="h-3 w-3" aria-hidden />
                      <span className="sr-only">{t("allGroups")}</span>
                    </button>
                  )}
                </div>
                {filtered.length === 0 ? (
                  <p className="py-12 text-center text-sm text-fg-muted">{t("noResults")}</p>
                ) : (
                  <ul className="grid gap-3 pt-4 sm:grid-cols-2 xl:grid-cols-3">
                    {filtered.map((d) => (
                      <li key={d.id} className="min-w-0">
                        <a
                          href={`/parlamentari/${deputySlug(d.id)}`}
                          className="flex h-full items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-3 transition-colors hover:border-line-strong hover:bg-surface-muted"
                        >
                          <DeputyAvatar photo={d.photo} firstName={d.first_name} lastName={d.last_name} size={44} />
                          <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                            <span className="truncate text-sm font-medium text-fg">
                              {toTitleCase(`${d.first_name} ${d.last_name}`)}
                            </span>
                            <span className="flex min-w-0 items-center gap-1.5 text-[13px] text-fg-muted">
                              {d.group && <PartyLogo group={d.group} size={14} />}
                              {d.group && (
                                <span className="shrink-0 font-semibold text-fg-secondary" title={groupLabel(d.group)}>
                                  {getGroupAbbrev(d.group)}
                                </span>
                              )}
                              {d.group && d.profession && <span aria-hidden>·</span>}
                              {d.profession && <span className="truncate">{d.profession}</span>}
                            </span>
                          </span>
                        </a>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>

          <aside className="order-first flex flex-col gap-6 lg:order-none lg:sticky lg:top-[calc(var(--header-h)+2rem)] lg:self-start">
            <section aria-labelledby="composition-h" className="rounded-lg border border-line bg-surface p-5">
              <h2 id="composition-h" className="label-mono text-fg-muted">{t("compositionTitle")}</h2>
              {deputies === null ? (
                <div className="mt-4 h-14 rounded-md bg-surface-sunken animate-skeleton" aria-hidden />
              ) : (
                <>
                  <dl className="mt-4 grid grid-cols-3 gap-3">
                    {COALITION_ORDER.map((c) => (
                      <div key={c} className="flex flex-col gap-0.5">
                        <dt className="text-[13px] text-fg-muted">{td(`bloc_${c}`)}</dt>
                        <dd className="tabular text-2xl font-semibold text-fg">
                          {groupCounts.filter((g) => coalitionOf(g.name) === c).reduce((s, g) => s + g.n, 0)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                  <div className="mt-5 hidden border-t border-line pt-4 lg:block">
                    <p className="text-[13px] text-fg-muted">{t("filterGroupHint")}</p>
                    <ul className="mt-2 flex flex-col">
                      {groupCounts.map((g) => {
                        const active = groupFilter === g.name;
                        return (
                          <li key={g.name}>
                            <button
                              type="button"
                              aria-pressed={active}
                              onClick={() => setGroupFilter(active ? "" : g.name)}
                              title={groupLabel(g.name)}
                              className={`-mx-2 grid w-[calc(100%+1rem)] cursor-pointer grid-cols-[3.25rem_minmax(0,1fr)_2.5rem] items-center gap-3 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                                active ? "bg-brand-soft text-fg" : "hover:bg-surface-muted"
                              }`}
                            >
                              <span className="font-semibold text-fg">{getGroupAbbrev(g.name)}</span>
                              <span className="h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                                <span
                                  className="block h-full rounded-full bg-fg-muted"
                                  style={{ width: `${(g.n / maxGroup) * 100}%` }}
                                />
                              </span>
                              <span className="tabular text-right text-fg-secondary">{g.n}</span>
                            </button>
                          </li>
                        );
                      })}
                    </ul>
                  </div>
                </>
              )}
            </section>
          </aside>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
