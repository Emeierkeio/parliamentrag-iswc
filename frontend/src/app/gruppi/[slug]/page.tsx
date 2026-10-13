"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft } from "lucide-react";
import { Sidebar, MobileMenuButton } from "@/components/layout";
import { useSidebar } from "@/hooks";
import { GroupMemberAvatar } from "@/components/entities/GroupMemberAvatar";
import { GroupLogo } from "@/components/entities/GroupLogo";
import { graphQuery, deputySlug } from "@/lib/graph";
import { config, getGroupAbbrev } from "@/config";
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
  "MATCH (g:ParliamentaryGroup {chamber: 'camera'})<-[m:MEMBER_OF_GROUP]-(d:Deputy) " +
  "WHERE m.end_date IS NULL " +
  "RETURN g.name AS name, count(DISTINCT d) AS members ORDER BY members DESC";

function groupLabel(name: string): string {
  const known = (
    config.politicalGroups as Record<string, { label: string }>
  )[name];
  return known?.label ?? toTitleCase(name);
}

/** Nome canonico per slug: il gruppo il cui abbreviativo coincide; a parità
 * di slug vince quello con più componenti (le righe sono già ordinate). */
function resolveGroup(rows: GroupRow[], slug: string): GroupRow | null {
  return (
    rows.find((r) => getGroupAbbrev(r.name).toLowerCase() === slug) ?? null
  );
}

function escapeCypherString(s: string): string {
  return s.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

type State =
  | { phase: "loading" }
  | { phase: "error" }
  | { phase: "notFound" }
  | { phase: "ready"; group: GroupRow; members: MemberRow[] };

export default function GruppoDettaglioPage() {
  const { isCollapsed, toggle, isMobile, isMobileOpen, closeMobile } = useSidebar();
  const t = useTranslations("Entities");
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
          `MATCH (g:ParliamentaryGroup {name: "${escapeCypherString(group.name)}", chamber: 'camera'})` +
          "<-[mm:MEMBER_OF_GROUP]-(d:Deputy) " +
          "WHERE mm.end_date IS NULL " +
          "OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent) " +
          "WHERE mc.end_date IS NULL " +
          "RETURN DISTINCT d.id AS id, d.first_name AS first_name, d.last_name AS last_name, " +
          "d.photo AS photo, c.name AS component, mm.role AS role " +
          "ORDER BY d.last_name, d.first_name";
        return graphQuery<MemberRow>(membersQuery).then((members) =>
          setState({ phase: "ready", group, members })
        );
      })
      .catch(() => setState({ phase: "error" }));
  }, [slug]);

  useEffect(() => {
    load();
  }, [load]);

  const label =
    state.phase === "ready" ? groupLabel(state.group.name) : null;

  return (
    <div className="flex h-dvh overflow-hidden bg-background pb-[calc(4.75rem+env(safe-area-inset-bottom))] md:pb-0">
      <Sidebar
        isCollapsed={isCollapsed}
        onToggle={toggle}
        isMobile={isMobile}
        isMobileOpen={isMobileOpen}
        onCloseMobile={closeMobile}
      />
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur-sm shrink-0">
          <div className="flex items-center gap-3 px-4 sm:px-6 h-14">
            <MobileMenuButton onClick={toggle} />
            <h1 className="[font-family:var(--font-display)] text-lg font-medium tracking-tight whitespace-nowrap">{t("groupsTitle")}</h1>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 py-8">
          <Link
            href="/gruppi"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            {t("backToList")}
          </Link>

          {state.phase === "error" && (
            <div className="mt-10 border-b py-10 text-center">
              <p className="text-muted-foreground">{t("errorLoad")}</p>
              <button
                type="button"
                onClick={load}
                className="mt-3 text-sm underline underline-offset-4 hover:text-foreground"
              >
                {t("retry")}
              </button>
            </div>
          )}

          {state.phase === "notFound" && (
            <div className="mt-10 border-b py-10 text-center">
              <p className="text-muted-foreground">{t("noResults")}</p>
              <Link
                href="/gruppi"
                className="mt-3 inline-block text-sm underline underline-offset-4 hover:text-foreground"
              >
                {t("backToList")}
              </Link>
            </div>
          )}

          {state.phase === "loading" && (
            <div className="mt-8" aria-hidden>
              <div className="flex items-center gap-3">
                <span className="h-3 w-3 rounded-full bg-muted animate-pulse" />
                <span className="h-8 w-64 rounded bg-muted animate-pulse" />
              </div>
              <span className="mt-3 block h-4 w-28 rounded bg-muted animate-pulse" />
              <div className="mt-8 grid gap-x-8 sm:grid-cols-2">
                {Array.from({ length: 8 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3 border-b py-3">
                    <span className="h-8 w-8 rounded-full bg-muted animate-pulse" />
                    <span className="h-4 w-40 rounded bg-muted animate-pulse" />
                  </div>
                ))}
              </div>
            </div>
          )}

          {state.phase === "ready" && label && (
            <>
              <header className="mt-8">
                <div className="flex items-center gap-3">
                  <GroupLogo group={state.group.name} size={36} />
                  <h1 className="[font-family:var(--font-display)] text-3xl sm:text-4xl font-semibold tracking-tight">
                    {label}
                  </h1>
                </div>
                <p className="mt-2 font-mono text-sm text-muted-foreground tabular-nums">
                  {t("membersCount", { count: state.members.length })}
                </p>
              </header>


              <section className="mt-10">
                {state.members.length === 0 ? (
                  <p className="mt-4 border-b py-8 text-center text-muted-foreground">
                    {t("noResults")}
                  </p>
                ) : (
                  (() => {
                    const ROLE_ORDER = ["president", "vice_president", "treasurer", "secretary"];
                    const officers = state.members
                      .filter((m) => m.role && ROLE_ORDER.includes(m.role))
                      .sort((a, b) => ROLE_ORDER.indexOf(a.role as string) - ROLE_ORDER.indexOf(b.role as string));
                    const others = state.members.filter((m) => !officers.includes(m));
                    const renderList = (items: MemberRow[]) => (
                      <ul className="mt-3 grid gap-x-8 sm:grid-cols-2">
                        {items.map((m) => {
                          const name = toTitleCase(
                            `${m.first_name} ${m.last_name}`.trim()
                          );
                          return (
                            <li key={m.id}>
                              <Link
                                href={`/parlamentari/${deputySlug(m.id)}`}
                                className="group flex items-center gap-3 border-b py-3 transition-colors hover:bg-muted/40"
                              >
                                <GroupMemberAvatar photo={m.photo} name={name} />
                                <span className="min-w-0 truncate group-hover:underline underline-offset-4">
                                  {name}
                                </span>
                              </Link>
                            </li>
                          );
                        })}
                      </ul>
                    );
                    // Solo il Misto ha componenti: per gli altri gruppi tutte
                    // le righe hanno component null e la lista resta piatta
                    const withComponent = others.filter((m) => m.component);
                    
                    const sections = new Map<string, MemberRow[]>();
                    for (const m of withComponent) {
                      const list = sections.get(m.component as string) ?? [];
                      list.push(m);
                      sections.set(m.component as string, list);
                    }
                    const rest = others.filter((m) => !m.component);
                    return (
                      <>
                        {officers.length > 0 && (
                          <div className="mt-4">
                            <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              {t("boardTitle")}
                            </h3>
                            <ul className="mt-3 grid gap-x-8 sm:grid-cols-2">
                              {officers.map((m) => {
                                const name = toTitleCase(`${m.first_name} ${m.last_name}`.trim());
                                return (
                                  <li key={m.id}>
                                    <Link
                                      href={`/parlamentari/${deputySlug(m.id)}`}
                                      className="group flex items-center gap-3 border-b py-3 transition-colors hover:bg-muted/40"
                                    >
                                      <GroupMemberAvatar photo={m.photo} name={name} />
                                      <span className="min-w-0 truncate group-hover:underline underline-offset-4">{name}</span>
                                      <span className="ml-auto shrink-0 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                                        {t(`role_${m.role}` as never) as string}
                                      </span>
                                    </Link>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}
                        {withComponent.length === 0 ? (
                          <div className="mt-6">
                            <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              {t("membersTitle")}
                            </h3>
                            {renderList(others)}
                          </div>
                        ) : (
                          <>
                        {[...sections.entries()]
                          .sort((a, b) => b[1].length - a[1].length)
                          .map(([cname, items]) => (
                            <div key={cname} className="mt-6">
                              <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                                {toTitleCase(cname)}
                                <span className="ml-1.5 font-mono tabular-nums">{items.length}</span>
                              </h3>
                              {renderList(items)}
                            </div>
                          ))}
                        {rest.length > 0 && (
                          <div className="mt-6">
                            <h3 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                              {t("noComponent")}
                              <span className="ml-1.5 font-mono tabular-nums">{rest.length}</span>
                            </h3>
                            {renderList(rest)}
                          </div>
                        )}
                          </>
                        )}
                      </>
                    );
                  })()
                )}
              </section>
            </>
          )}
        </div>
        </div>
      </main>
    </div>
  );
}
