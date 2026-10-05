"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowLeft, ArrowRight, ExternalLink } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { DeputyAvatar } from "@/components/entities/DeputyAvatar";
import { PartyLogo } from "@/components/entities/PartyLogo";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { groupLabel, groupSlug } from "@/components/entities/groups";
import { graphQuery, deputyUriFromSlug } from "@/lib/graph";
import { getGroupAbbrev } from "@/config";
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
    "OPTIONAL MATCH (d)-[m:MEMBER_OF_GROUP]->(g:ParliamentaryGroup) " +
    "WITH d, g, m ORDER BY m.end_date IS NOT NULL, m.start_date DESC " +
    "WITH d, collect(g.name)[0] AS group " +
    "OPTIONAL MATCH (d)-[mc:MEMBER_OF_COMPONENT]->(c:MistoComponent) WHERE group = 'MISTO' AND mc.end_date IS NULL " +
    "WITH d, group, collect(c.name)[0] AS component " +
    "OPTIONAL MATCH (s:Speech)-[:SPOKEN_BY]->(d) WITH d, group, component, count(s) AS speeches " +
    "OPTIONAL MATCH (d)-[:PRIMARY_SIGNATORY]->(a:ParliamentaryAct) " +
    "RETURN d.first_name AS first_name, d.last_name AS last_name, d.photo AS photo, " +
    "d.deputy_card AS deputy_card, d.profession AS profession, d.education AS education, " +
    "d.institutional_role AS institutional_role, group, component, speeches, count(a) AS acts"
  );
}

export default function DeputyProfilePage() {
  const t = useTranslations("Entities");
  const td = useTranslations("Dossier");
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

  const card = "rounded-lg border border-line bg-surface p-5";

  return (
    <div className="flex min-h-dvh flex-col bg-bg">
      <AppBar />
      <main className="container-page flex-1 pb-[calc(4rem+env(safe-area-inset-bottom))]">
        <div className="pt-8 md:pt-10">
          <Link
            href="/parlamentari"
            className="inline-flex items-center gap-1.5 text-sm text-fg-muted transition-colors hover:text-fg"
          >
            <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
            {t("backToList")}
          </Link>
        </div>

        {error ? (
          <div className="mt-8 rounded-lg border border-line bg-surface py-12 text-center">
            <p className="text-sm text-fg-muted">{t("errorLoad")}</p>
            {validSlug && (
              <button
                type="button"
                onClick={load}
                className="mt-4 inline-flex h-9 items-center rounded-full border border-line-strong bg-surface px-4 text-sm text-fg transition-colors hover:bg-surface-muted"
              >
                {t("retry")}
              </button>
            )}
          </div>
        ) : loading || !profile ? (
          <div aria-hidden>
            <div className="mt-6 flex items-center gap-6">
              <div className="h-24 w-24 shrink-0 rounded-full bg-surface-sunken animate-skeleton" />
              <div className="flex flex-1 flex-col gap-3">
                <div className="h-3 w-40 rounded-xs bg-surface-sunken animate-skeleton" />
                <div className="h-10 w-full max-w-md rounded-md bg-surface-sunken animate-skeleton" />
                <div className="h-4 w-64 rounded-xs bg-surface-sunken animate-skeleton" />
              </div>
            </div>
            <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
              <div className="flex flex-col gap-3">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="h-24 rounded-lg bg-surface-sunken animate-skeleton" />
                ))}
              </div>
              <div className="h-64 rounded-lg bg-surface-sunken animate-skeleton" />
            </div>
          </div>
        ) : (
          <>
            <header className="mt-6 flex items-center gap-5 sm:gap-7">
              <DeputyAvatar
                photo={profile.photo}
                firstName={profile.first_name}
                lastName={profile.last_name}
                size={104}
              />
              <div className="flex min-w-0 flex-col gap-2">
                <p className="label-mono text-fg-muted">{td("scope")}</p>
                <h1 className="serif-display text-[2.25rem] leading-[1.05] text-fg md:text-display-l">{fullName}</h1>
                {profile.group && (
                  <p className="flex flex-wrap items-center gap-x-2 text-[15px] text-fg-secondary">
                    <PartyLogo group={profile.group} size={18} />
                    <Link
                      href={`/gruppi/${groupSlug(profile.group)}`}
                      className="font-semibold text-fg underline-offset-4 hover:underline"
                    >
                      {getGroupAbbrev(profile.group)}
                    </Link>
                    <span className="min-w-0">
                      {groupLabel(profile.group)}
                      {profile.component && <> · {profile.component}</>}
                    </span>
                  </p>
                )}
                {profile.institutional_role && (
                  <p className="text-sm text-fg-muted">{profile.institutional_role}</p>
                )}
              </div>
            </header>

            <div className="mt-10 grid grid-cols-[minmax(0,1fr)] gap-x-12 gap-y-6 lg:grid-cols-[minmax(0,1fr)_22rem] lg:grid-rows-[auto_1fr]">
              <section aria-labelledby="facts-h" className={`${card} lg:col-start-2 lg:row-start-1`}>
                <h2 id="facts-h" className="label-mono text-fg-muted">{t("factsTitle")}</h2>
                <dl className="mt-4 grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-0.5">
                    <dt className="text-[13px] text-fg-muted">{t("statSpeeches")}</dt>
                    <dd className="tabular text-2xl font-semibold text-fg">{profile.speeches}</dd>
                  </div>
                  <div className="flex flex-col gap-0.5">
                    <dt className="text-[13px] text-fg-muted">{t("statActs")}</dt>
                    <dd className="tabular text-2xl font-semibold text-fg">{profile.acts}</dd>
                  </div>
                </dl>
                {(profile.profession || profile.education) && (
                  <dl className="mt-4 flex flex-col divide-y divide-line border-t border-line">
                    {profile.profession && (
                      <div className="flex flex-col gap-0.5 py-3">
                        <dt className="text-[13px] text-fg-muted">{t("profession")}</dt>
                        <dd className="text-sm text-fg">{profile.profession}</dd>
                      </div>
                    )}
                    {profile.education && (
                      <div className="flex flex-col gap-0.5 py-3">
                        <dt className="text-[13px] text-fg-muted">{t("education")}</dt>
                        <dd className="text-sm text-fg">{profile.education}</dd>
                      </div>
                    )}
                  </dl>
                )}
                {profile.deputy_card && (
                  <a
                    href={profile.deputy_card}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="mt-2 inline-flex h-9 items-center gap-1.5 rounded-full border border-line-strong px-3.5 text-[13px] text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
                  >
                    {t("officialCard")}
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                  </a>
                )}
              </section>

              <section aria-labelledby="speeches-h" className="flex min-w-0 flex-col gap-4 lg:col-start-1 lg:row-span-2 lg:row-start-1">
                <h2 id="speeches-h" className="serif-display text-[1.75rem] leading-tight text-fg">
                  {t("recentSpeeches")}
                </h2>
                {recent.length > 0 && (
                  <ul className="flex flex-col divide-y divide-line overflow-hidden rounded-lg border border-line bg-surface">
                    {recent.map((s) => {
                      const expanded = expandedId === s.id;
                      return (
                        <li key={s.id}>
                          <button
                            type="button"
                            aria-expanded={expanded}
                            onClick={() => setExpandedId(expanded ? null : s.id)}
                            className="block w-full cursor-pointer px-5 py-4 text-left transition-colors hover:bg-surface-muted"
                          >
                            <span className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                              <span className="tabular font-mono text-xs text-fg-muted">
                                {formatDate(s.date)}
                                {s.session_number != null && (
                                  <> · {t("sessionTitle", { number: s.session_number })}</>
                                )}
                              </span>
                            </span>
                            {s.debate_title && (
                              <span className="mt-1 line-clamp-1 text-[13px] font-medium text-fg-secondary">
                                {s.debate_title}
                              </span>
                            )}
                            {s.text && (
                              <span
                                className={`serif-display mt-2 text-[15px] leading-relaxed text-fg ${
                                  expanded ? "block whitespace-pre-line" : "line-clamp-3"
                                }`}
                              >
                                {s.text}
                              </span>
                            )}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                )}
                <a
                  href={searchHref}
                  className="inline-flex min-h-10 items-center gap-1.5 self-start text-sm font-medium text-brand-fg transition-colors hover:underline"
                >
                  {t("viewAllSpeeches")}
                  <ArrowRight className="h-3.5 w-3.5" aria-hidden />
                </a>
              </section>

              {(groupHistory.length > 0 || committees.length > 0) && (
                <div className="flex flex-col gap-6 lg:col-start-2 lg:row-start-2 lg:self-start">
                  {groupHistory.length > 0 && (
                    <section aria-labelledby="groups-h" className={card}>
                      <h2 id="groups-h" className="label-mono text-fg-muted">{t("groupHistoryTitle")}</h2>
                      <ul className="mt-3 flex flex-col divide-y divide-line">
                        {groupHistory.map((g, i) => {
                          const current = !g.end_date;
                          return (
                            <li key={`${g.name}-${i}`} className="grid grid-cols-[4.25rem_minmax(0,1fr)] gap-x-3 py-3 first:pt-0 last:pb-0">
                              <Link
                                href={`/gruppi/${groupSlug(g.name)}`}
                                className={`flex items-center gap-1.5 self-start text-sm font-semibold underline-offset-4 hover:underline ${current ? "text-fg" : "text-fg-muted"}`}
                              >
                                <PartyLogo group={g.name} size={14} />
                                {getGroupAbbrev(g.name)}
                              </Link>
                              <span className="flex min-w-0 flex-col gap-0.5">
                                <span className={`text-sm ${current ? "text-fg" : "text-fg-muted"}`}>
                                  {groupLabel(g.name)}
                                  {g.component && <span className="text-fg-muted"> · {g.component}</span>}
                                </span>
                                <span className="tabular font-mono text-xs text-fg-muted">{membershipPeriod(g)}</span>
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </section>
                  )}

                  {committees.length > 0 && (
                    <section aria-labelledby="committees-h" className={card}>
                      <h2 id="committees-h" className="label-mono text-fg-muted">{t("committeesTitle")}</h2>
                      <ul className="mt-3 flex flex-col divide-y divide-line">
                        {committees.map((c, i) => {
                          const current = !c.end_date;
                          return (
                            <li key={`${c.name}-${i}`} className="flex flex-col gap-1 py-3 first:pt-0 last:pb-0">
                              <span className={`text-sm leading-snug ${current ? "text-fg" : "text-fg-muted"}`}>
                                {toTitleCase(c.name)}
                              </span>
                              <span className="flex flex-wrap items-center gap-2">
                                {c.officer_role && (
                                  <span className="rounded-sm border border-line-strong px-1.5 py-px text-[11px] text-fg-secondary">
                                    {toTitleCase(c.officer_role)}
                                  </span>
                                )}
                                <span className="tabular font-mono text-xs text-fg-muted">{membershipPeriod(c)}</span>
                              </span>
                            </li>
                          );
                        })}
                      </ul>
                    </section>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </main>
      <SiteFooter />
    </div>
  );
}
