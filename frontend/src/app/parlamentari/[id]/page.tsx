"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Sidebar, MobileMenuButton } from "@/components/layout";
import { useSidebar } from "@/hooks";
import { DeputyAvatar } from "@/components/entities/DeputyAvatar";
import { GroupLogo } from "@/components/entities/GroupLogo";
import { graphQuery, deputyUriFromSlug } from "@/lib/graph";
import { config } from "@/config";
import { formatDate, toTitleCase } from "@/lib/utils";

interface DeputyProfile {
  first_name: string;
  last_name: string;
  photo: string | null;
  deputy_card: string | null;
  profession: string | null;
  education: string | null;
  institutional_role: string | null;
  group: string | null;
  component: string | null;
  speeches: number;
  acts: number;
}

interface RecentSpeech {
  id: string;
  text: string | null;
  date: string;
  session_number: number | null;
  debate_title: string | null;
}

interface GroupMembership {
  name: string;
  component: string | null;
  start_date: string | null;
  end_date: string | null;
}

interface CommitteeMembership {
  name: string;
  start_date: string | null;
  end_date: string | null;
  officer_role: string | null;
}

const SLUG_RE = /^p\d+$/;

function profileCypher(uri: string): string {
  // Current membership only (no end_date, most recent first): deputies who
  // changed group would otherwise produce one row per membership
  return (
    `MATCH (d:Deputy {id: "${uri}"}) ` +
    "OPTIONAL MATCH (d)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup {chamber: 'camera'}) " +
    "WITH d, g, m ORDER BY m.end_date IS NOT NULL, m.start_date DESC " +
    "WITH d, collect(g.name)[0] AS group " +
    "OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent) WHERE group = 'MISTO' AND mc.end_date IS NULL " +
    "WITH d, group, collect(c.name)[0] AS component " +
    "OPTIONAL MATCH (s:Speech)-[:SPOKEN_BY]->(d) WHERE NOT s.id STARTS WITH 'sen_' " +
    "WITH d, group, component, count(s) AS speeches " +
    "OPTIONAL MATCH (d)-[:PRIMARY_SIGNATORY]->(a:ParliamentaryAct) WHERE a.uri STARTS WITH 'http://dati.camera.it/' " +
    "RETURN d.first_name AS first_name, d.last_name AS last_name, d.photo AS photo, " +
    "d.deputy_card AS deputy_card, d.profession AS profession, d.education AS education, " +
    "d.institutional_role AS institutional_role, group, component, speeches, count(a) AS acts"
  );
}

export default function DeputyProfilePage() {
  const { isCollapsed, toggle, isMobile, isMobileOpen, closeMobile } = useSidebar();
  const t = useTranslations("Entities");
  const params = useParams();
  const slug = typeof params.id === "string" ? params.id : "";
  const validSlug = SLUG_RE.test(slug);

  const [profile, setProfile] = useState<DeputyProfile | null>(null);
  const [loading, setLoading] = useState(validSlug);
  const [error, setError] = useState(!validSlug);
  const [recent, setRecent] = useState<RecentSpeech[]>([]);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [groupHistory, setGroupHistory] = useState<GroupMembership[]>([]);
  const [committees, setCommittees] = useState<CommitteeMembership[]>([]);

  const load = useCallback(async () => {
    if (!validSlug) return;
    setError(false);
    setLoading(true);
    setProfile(null);
    setRecent([]);
    try {
      const uri = deputyUriFromSlug(slug);
      const rows = await graphQuery<DeputyProfile>(profileCypher(uri));
      if (rows.length === 0) {
        setError(true);
        return;
      }
      setProfile(rows[0]);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [slug, validSlug]);

  useEffect(() => {
    load();
  }, [load]);

  // Interventi recenti via Cypher diretto: la ricerca ibrida non puo' farlo,
  // perche' esige una query testuale e il nome del deputato non compare nel
  // testo dei suoi interventi. Se la chiamata fallisce la lista resta vuota
  // e si mostra solo il link alla ricerca completa.
  useEffect(() => {
    if (!profile || !validSlug) return;
    let cancelled = false;
    const uri = deputyUriFromSlug(slug);
    // Full speech text straight from the node: the row expands in place
    // instead of sending the reader to the whole session transcript
    const cypher =
      `MATCH (i:Speech)-[:SPOKEN_BY]->(d:Deputy {id: "${uri}"}) ` +
      "MATCH (i)<-[:CONTAINS_SPEECH]-(:Phase)<-[:HAS_PHASE]-(dib:Debate)<-[:HAS_DEBATE]-(s:Session) " +
      "WHERE coalesce(s.chamber, 'camera') = 'camera' " +
      "WITH i, s, dib ORDER BY s.date DESC LIMIT 5 " +
      "RETURN i.id AS id, i.text AS text, toString(s.date) AS date, " +
      "s.number AS session_number, dib.title AS debate_title " +
      "ORDER BY date DESC";
    graphQuery<RecentSpeech>(cypher)
      .then((rows) => {
        if (!cancelled) setRecent(rows);
      })
      .catch(() => {
        /* lista nascosta, resta il link viewAllSpeeches */
      });

    // Storico gruppi (chi e' uscito da un gruppo ha end_date sulla membership)
    const groupsCypher =
      `MATCH (d:Deputy {id: "${uri}"})-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup) ` +
      // Misto is split into political components: show the one held during this membership
      "OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent) " +
      "WHERE g.name = 'MISTO' AND mc.start_date >= m.start_date " +
      "AND (m.end_date IS NULL OR mc.start_date <= m.end_date) " +
      "WITH g, m, collect(c.name)[0] AS component " +
      "RETURN g.name AS name, component, toString(m.start_date) AS start_date, " +
      "toString(m.end_date) AS end_date " +
      "ORDER BY m.end_date IS NOT NULL, m.start_date DESC";
    graphQuery<GroupMembership>(groupsCypher)
      .then((rows) => {
        if (!cancelled) setGroupHistory(rows);
      })
      .catch(() => {
        /* sezione nascosta */
      });

    const committeesCypher =
      `MATCH (d:Deputy {id: "${uri}"})-[m:MEMBER_OF_COMMITTEE]->(c:Committee) ` +
      "RETURN c.name AS name, toString(m.start_date) AS start_date, " +
      "toString(m.end_date) AS end_date, m.officerRole AS officer_role " +
      "ORDER BY m.end_date IS NOT NULL, m.start_date DESC";
    graphQuery<CommitteeMembership>(committeesCypher)
      .then((rows) => {
        if (!cancelled) setCommittees(rows);
      })
      .catch(() => {
        /* sezione nascosta */
      });

    return () => {
      cancelled = true;
    };
  }, [profile, slug, validSlug]);

  const membershipPeriod = (m: { start_date: string | null; end_date: string | null }) => {
    if (m.start_date && m.end_date)
      return t("periodFromTo", { from: formatDate(m.start_date), to: formatDate(m.end_date) });
    if (m.start_date) return t("sinceDate", { date: formatDate(m.start_date) });
    return null;
  };

  const fullName = profile
    ? toTitleCase(`${profile.first_name} ${profile.last_name}`)
    : "";
  // Deep link into /search with the author filter preset on this deputy;
  // the backend requires a textual query, so the topic stays to be typed
  const searchHref = profile
    ? `/search?deputy=${slug}&fn=${encodeURIComponent(profile.first_name)}&ln=${encodeURIComponent(profile.last_name)}`
    : "/search";

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
            <h1 className="[font-family:var(--font-display)] text-lg font-medium tracking-tight whitespace-nowrap">{t("deputiesTitle")}</h1>
          </div>
        </header>
        <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-4 sm:px-6 py-8">
          {/* Torna all'elenco */}
          <a
            href="/parlamentari"
            className="inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("backToList")}
          </a>

          {error ? (
            <div className="mt-10 border-t border-border py-12 text-center">
              <p className="text-sm text-muted-foreground">{t("errorLoad")}</p>
              {validSlug && (
                <button
                  type="button"
                  onClick={load}
                  className="mt-4 inline-flex h-9 items-center rounded-md border border-border px-4 text-sm transition-colors hover:bg-muted"
                >
                  {t("retry")}
                </button>
              )}
            </div>
          ) : loading || !profile ? (
            <div className="mt-10 space-y-3">
              <div className="h-24 bg-muted motion-safe:animate-pulse rounded-md" />
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 bg-muted motion-safe:animate-pulse rounded-md" />
              ))}
            </div>
          ) : (
            <>
              {/* Intestazione profilo */}
              <header className="mt-8 flex items-start gap-5 sm:gap-6">
                <DeputyAvatar
                  photo={profile.photo}
                  firstName={profile.first_name}
                  lastName={profile.last_name}
                  group={profile.group}
                  size={96}
                />
                <div className="min-w-0 pt-1">
                  <h1 className="[font-family:var(--font-display)] text-3xl sm:text-4xl font-semibold tracking-tight">
                    {fullName}
                  </h1>
                  {profile.group && (
                    <p className="mt-2 flex items-center gap-2 text-sm text-muted-foreground">
                      <GroupLogo group={profile.group} size={18} />
                      <span>
                        {(config.politicalGroups as Record<string, { label?: string }>)[profile.group]?.label ?? toTitleCase(profile.group)}
                        {profile.component && <> · {profile.component}</>}
                      </span>
                    </p>
                  )}
                  {profile.institutional_role && (
                    <p className="mt-1 text-sm text-muted-foreground">
                      {profile.institutional_role}
                    </p>
                  )}
                </div>
              </header>

              {/* Righe di dettaglio */}
              <div className="mt-10">
                {profile.profession && (
                  <div className="flex flex-col gap-1 border-b border-border py-4 sm:flex-row sm:items-baseline sm:gap-6">
                    <span className="w-32 shrink-0 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {t("profession")}
                    </span>
                    <span className="text-sm text-foreground">{profile.profession}</span>
                  </div>
                )}
                {profile.education && (
                  <div className="flex flex-col gap-1 border-b border-border py-4 sm:flex-row sm:items-baseline sm:gap-6">
                    <span className="w-32 shrink-0 text-[11px] uppercase tracking-wide text-muted-foreground">
                      {t("education")}
                    </span>
                    <span className="text-sm text-foreground">{profile.education}</span>
                  </div>
                )}
                {profile.deputy_card && (
                  <div className="border-b border-border py-4">
                    <a
                      href={profile.deputy_card}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-2 text-sm text-foreground underline-offset-4 transition-colors hover:underline"
                    >
                      <span className="inline-block h-2 w-2 bg-current" />
                      {t("officialCard")}
                    </a>
                  </div>
                )}
              </div>

              {/* Attivita in Aula */}
              <p className="mt-6 font-mono text-sm text-muted-foreground">
                {t("speechesCount", { count: profile.speeches })}
                <span className="mx-2 text-muted-foreground/50">·</span>
                {t("actsCount", { count: profile.acts })}
              </p>

              {/* Gruppi parlamentari: appartenenza attuale e storico */}
              {groupHistory.length > 0 && (
                <section className="mt-12">
                  <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {t("groupHistoryTitle")}
                  </h2>
                  <ul className="mt-2 border-t border-border">
                    {groupHistory.map((g, i) => {
                      const current = !g.end_date;
                      return (
                        <li
                          key={`${g.name}-${i}`}
                          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border py-3"
                        >
                          <span className="flex items-center gap-2 text-sm">
                            <GroupLogo group={g.name} size={16} />
                            <span className={current ? "font-medium text-foreground" : "text-muted-foreground"}>
                              {(config.politicalGroups as Record<string, { label?: string }>)[g.name]?.label ?? toTitleCase(g.name)}
                              {g.component && <span className="font-normal text-muted-foreground"> · {g.component}</span>}
                            </span>
                          </span>
                          <span className="font-mono text-xs text-muted-foreground tabular-nums">
                            {membershipPeriod(g)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}

              {/* Commissioni e giunte, con eventuale carica ricoperta */}
              {committees.length > 0 && (
                <section className="mt-12">
                  <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                    {t("committeesTitle")}
                  </h2>
                  <ul className="mt-2 border-t border-border">
                    {committees.map((c, i) => {
                      const current = !c.end_date;
                      return (
                        <li
                          key={`${c.name}-${i}`}
                          className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-border py-3"
                        >
                          <span className="min-w-0 text-sm">
                            <span className={current ? "text-foreground" : "text-muted-foreground"}>
                              {toTitleCase(c.name)}
                            </span>
                            {c.officer_role && (
                              <span className="ml-2 rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">
                                {toTitleCase(c.officer_role)}
                              </span>
                            )}
                          </span>
                          <span className="font-mono text-xs text-muted-foreground tabular-nums">
                            {membershipPeriod(c)}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}

              {/* Interventi recenti */}
              <section className="mt-12">
                <h2 className="text-[11px] uppercase tracking-wide text-muted-foreground">
                  {t("recentSpeeches")}
                </h2>
                {recent.length > 0 && (
                  <div className="mt-2 border-t border-border">
                    {recent.map((s) => {
                      const expanded = expandedId === s.id;
                      return (
                        <button
                          key={s.id}
                          type="button"
                          aria-expanded={expanded}
                          onClick={() => setExpandedId(expanded ? null : s.id)}
                          className="block w-full cursor-pointer border-b border-border py-3.5 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        >
                          <span className="font-mono text-xs text-muted-foreground">
                            {formatDate(s.date)}
                            {s.session_number != null && (
                              <> · {t("sessionTitle", { number: s.session_number })}</>
                            )}
                          </span>
                          {s.debate_title && (
                            <p className="mt-1 line-clamp-1 text-xs text-muted-foreground">
                              {s.debate_title}
                            </p>
                          )}
                          {s.text && (
                            <p
                              className={`mt-1 text-sm leading-relaxed text-foreground ${
                                expanded ? "whitespace-pre-line" : "line-clamp-2"
                              }`}
                            >
                              {s.text}
                            </p>
                          )}
                        </button>
                      );
                    })}
                  </div>
                )}
                <a
                  href={searchHref}
                  className="mt-4 inline-flex items-center gap-1.5 text-sm text-muted-foreground transition-colors hover:text-foreground"
                >
                  {t("viewAllSpeeches")}
                  <ArrowRight className="h-3.5 w-3.5" />
                </a>
              </section>

            </>
          )}
        </div>
        </div>
      </main>
    </div>
  );
}
