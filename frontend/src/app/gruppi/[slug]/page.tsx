"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { DeputyAvatar } from "@/components/entities/DeputyAvatar";
import { PartyLogo } from "@/components/entities/PartyLogo";
import { coalitionOf, groupLabel, groupSlug } from "@/components/entities/groups";
import { graphQuery, deputySlug } from "@/lib/graph";
import { getGroupAbbrev } from "@/config";
import { toTitleCase } from "@/lib/utils";

interface GroupRow {
  name: string;
  members: number;
}

interface MemberRow {
  id: string;
  first_name: string;
  last_name: string;
  photo: string | null;
  component: string | null;
  role: string | null;
}

// Stessa regola dell'elenco: contano solo le membership correnti
const DIRECTORY_QUERY =
  "MATCH (g:ParliamentaryGroup)<-[m:MEMBER_OF_GROUP]-(d:Deputy) " +
  "WHERE m.end_date IS NULL " +
  "RETURN g.name AS name, count(DISTINCT d) AS members ORDER BY members DESC";

const ROLE_ORDER = ["president", "vice_president", "treasurer", "secretary"];

/** Nome canonico per slug: il gruppo il cui abbreviativo coincide; a parità
 * di slug vince quello con più componenti (le righe sono già ordinate). */
function resolveGroup(rows: GroupRow[], slug: string): GroupRow | null {
  return rows.find((r) => groupSlug(r.name) === slug) ?? null;
}

function escapeCypherString(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function componentAnchor(name: string): string {
  return `c-${name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`;
}

type State =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "notFound" }
  | { phase: "ready"; group: GroupRow; members: MemberRow[]; all: GroupRow[] };

function MemberCard({ m, badge }: { m: MemberRow; badge?: string }) {
  const name = toTitleCase(`${m.first_name} ${m.last_name}`.trim());
  return (
    <li className="min-w-0">
      <Link
        href={`/parlamentari/${deputySlug(m.id)}`}
        className="flex h-full items-center gap-3 rounded-lg border border-line bg-surface px-3.5 py-3 transition-colors hover:border-line-strong hover:bg-surface-muted"
      >
        <DeputyAvatar photo={m.photo} firstName={m.first_name} lastName={m.last_name} size={40} />
        <span className="flex min-w-0 flex-1 flex-col gap-0.5">
          <span className="truncate text-sm font-medium text-fg">{name}</span>
          {badge && <span className="truncate text-[13px] text-fg-muted">{badge}</span>}
        </span>
      </Link>
    </li>
  );
}

function MemberSection({ id, title, count, children }: { id?: string; title: string; count?: number; children: ReactNode }) {
  return (
    <section id={id} className="flex scroll-mt-24 flex-col gap-3">
      <h2 className="flex items-baseline gap-2 border-b border-line pb-2">
        <span className="label-mono text-fg-muted">{title}</span>
        {count != null && <span className="tabular font-mono text-xs text-fg-muted">{count}</span>}
      </h2>
      <ul className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{children}</ul>
    </section>
  );
}

export default function GruppoDettaglioPage() {
  const t = useTranslations("Entities");
  const td = useTranslations("Dossier");
  const params = useParams<{ slug: string }>();
  const slug = (params?.slug ?? "").toLowerCase();
  const [state, setState] = useState<State>({ phase: "loading" });

  const load = useCallback(() => {
    if (!slug) return;
    setState({ phase: "loading" });
    graphQuery<GroupRow>(DIRECTORY_QUERY)
      .then((rows) => {
        const group = resolveGroup(rows, slug);
        if (!group) {
          setState({ phase: "notFound" });
          return null;
        }
        const membersQuery =
          `MATCH (g:ParliamentaryGroup {name: "${escapeCypherString(group.name)}"})` +
          "<-[mm:MEMBER_OF_GROUP]-(d:Deputy) " +
          "WHERE mm.end_date IS NULL " +
          "OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent) " +
          "WHERE mc.end_date IS NULL " +
          "RETURN DISTINCT d.id AS id, d.first_name AS first_name, d.last_name AS last_name, " +
          "d.photo AS photo, c.name AS component, mm.role AS role " +
          "ORDER BY d.last_name, d.first_name";
        return graphQuery<MemberRow>(membersQuery).then((members) =>
          setState({ phase: "ready", group, members, all: rows })
        );
      })
      .catch(() => setState({ phase: "error" }));
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  const view = useMemo(() => {
    if (state.phase !== "ready") return null;
    const officers = state.members
      .filter((m) => m.role && ROLE_ORDER.includes(m.role))
      .sort((a, b) => ROLE_ORDER.indexOf(a.role as string) - ROLE_ORDER.indexOf(b.role as string));
    const others = state.members.filter((m) => !officers.includes(m));
    // Solo il Misto ha componenti: per gli altri gruppi tutte le righe hanno
    // component null e la lista resta piatta
    const sections = new Map<string, MemberRow[]>();
    for (const m of others) {
      if (!m.component) continue;
      const list = sections.get(m.component) ?? [];
      list.push(m);
      sections.set(m.component, list);
    }
    const components = [...sections.entries()].sort((a, b) => b[1].length - a[1].length);
    const rest = others.filter((m) => !m.component);
    const seen = new Set<string>([groupSlug(state.group.name)]);
    const otherGroups = state.all.filter((g) => {
      const s = groupSlug(g.name);
      if (seen.has(s)) return false;
      seen.add(s);
      return true;
    });
    const seats = state.all.reduce((s, g) => s + g.members, 0);
    return { officers, others, components, rest, otherGroups, seats };
  }, [state]);

  const card = "rounded-lg border border-line bg-surface p-5";

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppBar />
      <main className="container-page flex-1 pb-[calc(4rem+env(safe-area-inset-bottom))]">
        <div className="pt-8 md:pt-10">
          <Link
            href="/gruppi"
            className="inline-flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            {t("backToList")}
          </Link>
        </div>

        {state.phase === "error" && (
          <div className="mt-8 rounded-lg border border-line bg-surface py-12 text-center">
            <p className="text-sm text-fg-muted">{t("errorLoad")}</p>
            <button type="button" onClick={load} className="link mt-3 text-sm">
              {t("retry")}
            </button>
          </div>
        )}

        {state.phase === "notFound" && (
          <div className="mt-8 rounded-lg border border-line bg-surface py-12 text-center">
            <p className="text-sm text-fg-muted">{t("noResults")}</p>
            <Link href="/gruppi" className="link mt-3 inline-block text-sm">
              {t("backToList")}
            </Link>
          </div>
        )}

        {state.phase === "loading" && (
          <div aria-hidden>
            <div className="mt-6 flex flex-col gap-3">
              <span className="h-3 w-48 rounded-xs bg-surface-sunken animate-skeleton" />
              <span className="h-12 w-full max-w-lg rounded-md bg-surface-sunken animate-skeleton" />
              <span className="h-4 w-56 rounded-xs bg-surface-sunken animate-skeleton" />
            </div>
            <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                {Array.from({ length: 12 }).map((_, i) => (
                  <div key={i} className="h-16 rounded-lg bg-surface-sunken animate-skeleton" />
                ))}
              </div>
              <div className="h-56 rounded-lg bg-surface-sunken animate-skeleton" />
            </div>
          </div>
        )}

        {state.phase === "ready" && view && (
          <>
            <header className="mt-6 flex items-center gap-5 sm:gap-7">
              <PartyLogo group={state.group.name} size={88} className="hidden rounded-md sm:block" />
              <div className="flex min-w-0 flex-col gap-3">
              <p className="label-mono text-fg-muted">
                {td("scope")} · {td(`bloc_${coalitionOf(state.group.name)}`)}
              </p>
              <h1 className="serif-display max-w-4xl text-[2.25rem] leading-[1.05] text-fg md:text-display-l">
                {groupLabel(state.group.name)}
              </h1>
              <p className="flex flex-wrap items-center gap-x-2 text-[15px] text-fg-secondary">
                <PartyLogo group={state.group.name} size={20} className="sm:hidden" />
                <span className="font-semibold text-fg">{getGroupAbbrev(state.group.name)}</span>
                <span aria-hidden>·</span>
                <span className="tabular">{t("membersCount", { count: state.members.length })}</span>
              </p>
              </div>
            </header>

            <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="flex min-w-0 flex-col gap-10">
                {state.members.length === 0 ? (
                  <p className="rounded-lg border border-line bg-surface py-12 text-center text-sm text-fg-muted">
                    {t("noResults")}
                  </p>
                ) : (
                  <>
                    {view.officers.length > 0 && (
                      <MemberSection title={t("boardTitle")}>
                        {view.officers.map((m) => (
                          <MemberCard key={m.id} m={m} badge={t(`role_${m.role}` as never) as string} />
                        ))}
                      </MemberSection>
                    )}
                    {view.components.length === 0 ? (
                      <MemberSection title={t("membersTitle")} count={view.others.length}>
                        {view.others.map((m) => (
                          <MemberCard key={m.id} m={m} />
                        ))}
                      </MemberSection>
                    ) : (
                      <>
                        {view.components.map(([cname, items]) => (
                          <MemberSection key={cname} id={componentAnchor(cname)} title={toTitleCase(cname)} count={items.length}>
                            {items.map((m) => (
                              <MemberCard key={m.id} m={m} />
                            ))}
                          </MemberSection>
                        ))}
                        {view.rest.length > 0 && (
                          <MemberSection id="c-none" title={t("noComponent")} count={view.rest.length}>
                            {view.rest.map((m) => (
                              <MemberCard key={m.id} m={m} />
                            ))}
                          </MemberSection>
                        )}
                      </>
                    )}
                  </>
                )}
              </div>

              <aside className="flex flex-col gap-6 lg:sticky lg:top-[calc(var(--header-h)+2rem)] lg:self-start">
                <section aria-labelledby="facts-h" className={card}>
                  <h2 id="facts-h" className="label-mono text-fg-muted">{t("factsTitle")}</h2>
                  <dl className="mt-4 grid grid-cols-2 gap-3">
                    <div className="flex flex-col gap-0.5">
                      <dt className="text-[13px] text-fg-muted">{t("membersTitle")}</dt>
                      <dd className="tabular text-2xl font-semibold text-fg">{state.members.length}</dd>
                    </div>
                    <div className="flex flex-col gap-0.5">
                      <dt className="text-[13px] text-fg-muted">{t("coalitionLabel")}</dt>
                      <dd className="text-[15px] font-medium leading-8 text-fg">
                        {td(`bloc_${coalitionOf(state.group.name)}`)}
                      </dd>
                    </div>
                  </dl>
                  {view.seats > 0 && (
                    <div className="mt-4 flex flex-col gap-2 border-t border-line pt-4">
                      <span className="h-1.5 overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
                        <span
                          className="block h-full rounded-full bg-fg-muted"
                          style={{ width: `${(state.group.members / view.seats) * 100}%` }}
                        />
                      </span>
                      <span className="tabular font-mono text-xs text-fg-muted">
                        {t("seatShare", { share: ((state.group.members / view.seats) * 100).toFixed(1) })}
                      </span>
                    </div>
                  )}
                  {view.components.length > 0 && (
                    <div className="mt-4 border-t border-line pt-4">
                      <h3 className="text-[13px] text-fg-muted">{t("componentsTitle")}</h3>
                      <ul className="mt-2 flex flex-col">
                        {view.components.map(([cname, items]) => (
                          <li key={cname}>
                            <a
                              href={`#${componentAnchor(cname)}`}
                              className="-mx-2 flex items-baseline gap-3 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-muted"
                            >
                              <span className="min-w-0 flex-1 text-fg">{toTitleCase(cname)}</span>
                              <span className="tabular text-fg-secondary">{items.length}</span>
                            </a>
                          </li>
                        ))}
                        {view.rest.length > 0 && (
                          <li>
                            <a
                              href="#c-none"
                              className="-mx-2 flex items-baseline gap-3 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-muted"
                            >
                              <span className="min-w-0 flex-1 text-fg-muted">{t("noComponent")}</span>
                              <span className="tabular text-fg-secondary">{view.rest.length}</span>
                            </a>
                          </li>
                        )}
                      </ul>
                    </div>
                  )}
                </section>

                {view.otherGroups.length > 0 && (
                  <nav aria-labelledby="others-h" className={card}>
                    <h2 id="others-h" className="label-mono text-fg-muted">{t("otherGroups")}</h2>
                    <ul className="mt-3 flex flex-col">
                      {view.otherGroups.map((g) => (
                        <li key={g.name}>
                          <Link
                            href={`/gruppi/${groupSlug(g.name)}`}
                            title={groupLabel(g.name)}
                            className="-mx-2 grid grid-cols-[3.25rem_minmax(0,1fr)_auto] items-baseline gap-3 rounded-md px-2 py-1.5 text-sm transition-colors hover:bg-surface-muted"
                          >
                            <span className="font-semibold text-fg">{getGroupAbbrev(g.name)}</span>
                            <span className="truncate text-fg-muted">{groupLabel(g.name)}</span>
                            <span className="tabular text-fg-secondary">{g.members}</span>
                          </Link>
                        </li>
                      ))}
                    </ul>
                  </nav>
                )}
              </aside>
            </div>
          </>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
