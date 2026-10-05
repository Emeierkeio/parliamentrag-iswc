"use client";

import { useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import { getGroupAbbrev } from "@/config";
import { getVoteDetail } from "@/lib/timeline-api";
import { voteTitle } from "@/lib/vote-utils";
import { OutcomeShape, type Outcome } from "@/components/timeline/outcomes";
import { SeatPlanHemicycle, useSeatPlan } from "@/components/timeline/SeatPlanHemicycle";
import type { TopicVote, VoteDetailResponse } from "@/types/timeline";
import { formatDay } from "@/components/dossier/format";

export interface SaidQuote {
  abbrev: string;
  text: string;
  speaker: string;
}

const OUTCOMES: Outcome[] = ["favor", "against", "abstain", "absent"];

interface GroupTally {
  abbrev: string;
  counts: Record<Outcome, number>;
}

/* The roll call a reader most likely wants first: the latest final vote if
   an act reached one, otherwise the one with the most votes cast. */
function defaultVote(votes: TopicVote[]): string | null {
  if (!votes.length) return null;
  const final = votes.findLast((v) => v.final_vote);
  if (final) return final.id;
  const cast = (v: TopicVote) => (v.in_favor ?? 0) + (v.against ?? 0) + (v.abstained ?? 0);
  return [...votes].sort((a, b) => cast(b) - cast(a))[0].id;
}

const KNOWN_GROUPS = new Set(["FdI", "PD", "M5S", "AVS", "FI", "Az", "IV", "NM", "Lega", "Misto"]);

/* The breakdown names Misto deputies by component ("+EUROPA", "MINORANZE
   LINGUISTICHE"); they fold into one Misto row, as in the positions list. */
function tallies(detail: VoteDetailResponse, order: string[]): GroupTally[] {
  const byAbbrev = new Map<string, GroupTally>();
  for (const row of detail.breakdown) {
    const short = getGroupAbbrev(row.party);
    const abbrev = KNOWN_GROUPS.has(short) ? short : "Misto";
    const t = byAbbrev.get(abbrev) ?? { abbrev, counts: { favor: 0, against: 0, abstain: 0, absent: 0 } };
    t.counts.favor += row.favor;
    t.counts.against += row.against;
    t.counts.abstain += row.abstain;
    t.counts.absent += row.absent;
    byAbbrev.set(abbrev, t);
  }
  const rank = (a: string) => {
    const i = order.indexOf(a);
    return i === -1 ? order.length : i;
  };
  return [...byAbbrev.values()].sort((a, b) => rank(a.abbrev) - rank(b.abbrev));
}

export function SaidAndVoted({
  topic,
  acts,
  speechIds,
  quotes,
}: {
  topic: string;
  acts: string[];
  speechIds: string[];
  quotes: SaidQuote[];
}) {
  const t = useTranslations("Dossier");
  const locale = useLocale();
  const [votes, setVotes] = useState<TopicVote[] | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const plan = useSeatPlan();
  const voteId = picked ?? (votes ? defaultVote(votes) : null);

  useEffect(() => {
    const ctrl = new AbortController();
    fetch("/api/timeline/dossier-votes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speech_ids: speechIds, topic: topic.toLowerCase(), acts }),
      signal: ctrl.signal,
    })
      .then((r) => (r.ok ? r.json() : []))
      .then(setVotes)
      .catch(() => {
        if (!ctrl.signal.aborted) setVotes([]);
      });
    return () => ctrl.abort();
  }, [topic, acts, speechIds]);
  const [state, setState] = useState<{ id: string; detail?: VoteDetailResponse; error?: boolean } | null>(null);

  useEffect(() => {
    if (!voteId) return;
    let live = true;
    getVoteDetail(voteId)
      .then((detail) => live && setState({ id: voteId, detail }))
      .catch(() => live && setState({ id: voteId, error: true }));
    return () => {
      live = false;
    };
  }, [voteId]);

  const order = useMemo(() => quotes.map((q) => q.abbrev), [quotes]);
  const quoteOf = useMemo(() => new Map(quotes.map((q) => [q.abbrev, q])), [quotes]);
  const current = votes?.find((v) => v.id === voteId);
  const ready = state?.id === voteId ? state : null;

  if (votes === null) {
    return (
      <div className="flex flex-col gap-2" aria-busy="true" aria-label={t("svLoading")}>
        {Array.from({ length: 4 }, (_, i) => (
          <div key={i} className="h-12 rounded-md bg-surface-sunken motion-safe:animate-skeleton" />
        ))}
      </div>
    );
  }
  if (!votes.length) {
    return <p className="rounded-lg border border-line bg-surface p-5 text-sm text-fg-secondary">{t("svEmpty")}</p>;
  }

  return (
    <div className="flex flex-col gap-5">
      {votes.every((v) => v.relation === "session") && (
        <p className="rounded-md bg-notice-soft px-4 py-3 text-sm text-notice-fg">{t("svSessionNote")}</p>
      )}
      <div className="flex flex-col gap-2">
        <label htmlFor="sv-vote" className="label-mono text-fg-muted">
          {t("svPick")} · {t("svOtherVotes", { n: votes.length })}
        </label>
        <select
          id="sv-vote"
          value={voteId ?? ""}
          onChange={(e) => setPicked(e.target.value)}
          className="h-11 w-full max-w-2xl rounded-md border border-line-control bg-surface px-3 text-sm text-fg outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          {[true, false].map((final) => {
            const group = votes.filter((v) => v.final_vote === final);
            if (!group.length) return null;
            return (
              <optgroup key={String(final)} label={final ? t("svFinal") : t("svOther")}>
                {group.map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.date ? formatDay(v.date, locale) : ""} · {v.description?.trim() || voteTitle(v)}
                    {v.outcome === "approved" ? ` · ${t("approved")}` : v.outcome === "rejected" ? ` · ${t("rejected")}` : ""}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </select>
      </div>

      {current && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 rounded-lg border border-line bg-surface px-5 py-4 text-sm">
          {(
            [
              ["favor", current.in_favor],
              ["against", current.against],
              ["abstain", current.abstained],
            ] as [Outcome, number | null][]
          ).map(([o, n]) => (
            <span key={o} className="inline-flex items-center gap-2">
              <OutcomeShape outcome={o} />
              <b className="font-semibold tabular-nums">{n ?? 0}</b> {t(o)}
            </span>
          ))}
          <span className="inline-flex items-center gap-2 text-fg-secondary">
            <OutcomeShape outcome="absent" />
            {t("absent")}
          </span>
          {current.outcome && (
            <span className="rounded-sm border border-line-control px-2.5 py-1 text-[13px] font-medium">
              {current.outcome === "approved" ? t("approved") : t("rejected")}
            </span>
          )}
          {ready?.detail?.acts?.[0]?.url && (
            <a
              href={ready.detail.acts[0].url}
              target="_blank"
              rel="noreferrer"
              className="ml-auto inline-flex items-center gap-1 text-[13px] text-brand-fg hover:underline"
            >
              {t("svOnCamera")}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </a>
          )}
        </div>
      )}

      {!ready && (
        <div className="flex flex-col gap-2" aria-busy="true" aria-label={t("svLoading")}>
          {Array.from({ length: 6 }, (_, i) => (
            <div key={i} className="h-14 animate-skeleton rounded-md bg-surface-sunken" />
          ))}
        </div>
      )}
      {ready?.error && <p className="text-sm text-danger-fg">{t("svError")}</p>}
      {ready?.detail?.secret_vote && <p className="text-sm text-fg-secondary">{t("svSecret")}</p>}

      {ready?.detail &&
        !ready.detail.secret_vote &&
        plan &&
        ready.detail.participants.filter((p) => p.seat != null).length >= ready.detail.participants.length * 0.8 && (
          <div className="rounded-lg border border-line bg-surface px-4 py-5 md:px-8">
            <SeatPlanHemicycle
              plan={plan}
              participants={ready.detail.participants}
              activeKey={null}
              keyOf={(party) => party ?? ""}
              className="mx-auto max-w-3xl"
            />
          </div>
        )}

      {ready?.detail && !ready.detail.secret_vote && (
        <div className="flex flex-col">
          <div className="hidden grid-cols-[3.5rem_minmax(0,20rem)_minmax(0,1fr)_9rem] gap-5 px-1 pb-2 lg:grid">
            <span className="label-mono text-fg-muted">{t("svColGroup")}</span>
            <span className="label-mono text-fg-muted">{t("svColSaid")}</span>
            <span className="label-mono text-fg-muted">{t("svColVoted")}</span>
            <span className="label-mono text-right text-fg-muted">{t("svColResult")}</span>
          </div>
          <ul className="divide-y divide-line border-y border-line">
            {tallies(ready.detail, order).map((g) => {
              const said = quoteOf.get(g.abbrev);
              const total = OUTCOMES.reduce((s, o) => s + g.counts[o], 0);
              return (
                <li
                  key={g.abbrev}
                  className="grid grid-cols-[3.5rem_minmax(0,1fr)] items-start gap-x-4 gap-y-2 px-1 py-3.5 lg:grid-cols-[3.5rem_minmax(0,20rem)_minmax(0,1fr)_9rem] lg:items-center lg:gap-x-5"
                >
                  <span className="text-sm font-semibold">{g.abbrev}</span>
                  <p className="line-clamp-3 font-serif text-sm italic leading-[1.45] text-fg" title={said ? `${said.speaker}: «${said.text}»` : undefined}>
                    {said ? `«${said.text}»` : <span className="font-sans not-italic text-fg-muted">·</span>}
                  </p>
                  <div
                    className="col-start-2 flex max-w-[560px] flex-wrap gap-[3px] lg:col-start-auto"
                    role="img"
                    aria-label={OUTCOMES.filter((o) => g.counts[o]).map((o) => `${g.counts[o]} ${t(o)}`).join(", ")}
                  >
                    {OUTCOMES.flatMap((o) =>
                      Array.from({ length: g.counts[o] }, (_, i) => <OutcomeShape key={`${o}${i}`} outcome={o} size={9} />),
                    )}
                  </div>
                  <span className="col-start-2 font-mono text-xs tabular-nums text-fg-secondary lg:col-start-auto lg:text-right">
                    {OUTCOMES.filter((o) => g.counts[o])
                      .map((o) => `${g.counts[o]} ${t(o).split(" ")[0]}`)
                      .join(" · ")}
                    <span className="sr-only"> / {total}</span>
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="pt-3 text-caption text-fg-muted">{t("svNote")}</p>
        </div>
      )}
    </div>
  );
}
