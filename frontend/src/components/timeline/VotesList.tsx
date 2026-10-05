"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { CircleCheck, CircleX } from "lucide-react";
import { KIND_LABEL_KEYS, voteKind, voteTitle } from "@/lib/vote-utils";
import { VoteDetailDialog } from "./VoteDetailDialog";
import { OutcomeShape } from "./outcomes";
import type { VoteInfo } from "@/types/timeline";

interface VotesListProps {
  votes: VoteInfo[];
}

/* Amendment marathons produce 100+ near-identical rejected rows. Above
   the threshold only the votes worth reading stay visible by default:
   approvals, votes with a real subject (serial amendment votes carry a
   bare "Votazione"), knife-edge margins, and the last scrutiny of the
   series (often the final vote). */
const VOTES_COLLAPSE_THRESHOLD = 8;

export function VotesList({ votes }: VotesListProps) {
  const t = useTranslations("Timeline");
  const [showAll, setShowAll] = useState(false);
  const [selectedVote, setSelectedVote] = useState<VoteInfo | null>(null);

  const isKeyVote = (v: VoteInfo, i: number) => {
    if (v.outcome === "approved") return true;
    if (v.final_vote) return true;
    if (v.subject && !/^votazione\.?$/i.test(v.subject.trim())) return true;
    if (
      v.in_favor !== null &&
      v.against !== null &&
      Math.abs(v.in_favor - v.against) <= 10
    )
      return true;
    return i === votes.length - 1;
  };

  const collapse = votes.length > VOTES_COLLAPSE_THRESHOLD && !showAll;
  const visibleVotes = collapse ? votes.filter((v, i) => isKeyVote(v, i)) : votes;
  const approvedCount = votes.filter((v) => v.outcome === "approved").length;
  const rejectedCount = votes.filter((v) => v.outcome === "rejected").length;
  const otherCount = votes.length - approvedCount - rejectedCount;

  return (
    <div>
      {votes.length > VOTES_COLLAPSE_THRESHOLD && (
        <div className="mb-2">
          <div className="tabular flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-fg-secondary">
            <span className="inline-flex items-center gap-1">
              <CircleCheck className="h-3.5 w-3.5" aria-hidden />
              {t("votesApproved", { count: approvedCount })}
            </span>
            <span className="inline-flex items-center gap-1">
              <CircleX className="h-3.5 w-3.5" aria-hidden />
              {t("votesRejected", { count: rejectedCount })}
            </span>
            {otherCount > 0 && (
              <span className="text-fg-muted">
                {t("votesOther", { count: otherCount })}
              </span>
            )}
          </div>
          <div className="mt-1.5 flex h-1 w-full max-w-xs gap-px overflow-hidden rounded-full bg-surface-sunken" aria-hidden>
            {approvedCount > 0 && (
              <div
                className="bg-fg-secondary"
                style={{ width: `${(approvedCount / votes.length) * 100}%` }}
              />
            )}
            {rejectedCount > 0 && (
              <div
                className="bg-line-control"
                style={{ width: `${(rejectedCount / votes.length) * 100}%` }}
              />
            )}
          </div>
        </div>
      )}
      <div className="space-y-0.5">
        {visibleVotes.map((vote) => {
          const kind = voteKind(vote);
          const title = voteTitle(vote);
          return (
          <button
            key={vote.id}
            type="button"
            onClick={() => setSelectedVote(vote)}
            className="group flex w-full flex-wrap items-center gap-2 rounded-md px-2 py-1 -mx-2 text-left text-xs transition-colors hover:bg-surface-muted"
            title={t("voteDetailHint")}
          >
            {kind && (
              <span className="shrink-0 rounded-xs border border-line-strong px-1 py-px font-mono text-[10px] uppercase tracking-[var(--tracking-label)] text-fg-muted">
                {t(KIND_LABEL_KEYS[kind])}
              </span>
            )}
            {title && (
              <span className="text-fg-secondary group-hover:text-fg group-hover:underline underline-offset-2">
                {title}
              </span>
            )}
            {vote.outcome && (
              <span className="inline-flex items-center gap-1 rounded-full border border-line-control px-2 py-px font-medium text-fg">
                {vote.outcome === "approved" ? (
                  <CircleCheck className="h-3 w-3" aria-hidden />
                ) : vote.outcome === "rejected" ? (
                  <CircleX className="h-3 w-3" aria-hidden />
                ) : null}
                {vote.outcome === "approved"
                  ? t("outcomeApproved")
                  : vote.outcome === "rejected"
                    ? t("outcomeRejected")
                    : vote.outcome}
              </span>
            )}
            {(vote.in_favor !== null ||
              vote.against !== null ||
              vote.abstained !== null) && (
              <span className="tabular inline-flex items-center gap-2 text-fg-secondary">
                <span className="inline-flex items-center gap-1" title={t("voteFavor")}>
                  <OutcomeShape outcome="favor" size={8} />
                  <span className="sr-only">{t("voteFavor")}</span>
                  {vote.in_favor ?? "-"}
                </span>
                <span className="inline-flex items-center gap-1" title={t("voteAgainst")}>
                  <OutcomeShape outcome="against" size={8} />
                  <span className="sr-only">{t("voteAgainst")}</span>
                  {vote.against ?? "-"}
                </span>
                <span className="inline-flex items-center gap-1" title={t("voteAbstained")}>
                  <OutcomeShape outcome="abstain" size={8} />
                  <span className="sr-only">{t("voteAbstained")}</span>
                  {vote.abstained ?? "-"}
                </span>
              </span>
            )}
          </button>
          );
        })}
        {votes.length > VOTES_COLLAPSE_THRESHOLD && (
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            className="mt-1 min-h-8 text-xs text-fg-muted underline underline-offset-2 hover:text-fg transition-colors"
          >
            {showAll
              ? t("showFewerVotes")
              : t("showAllVotes", { count: votes.length })}
          </button>
        )}
      </div>

      {selectedVote && (
        <VoteDetailDialog
          vote={selectedVote}
          open={selectedVote !== null}
          onOpenChange={(open) => {
            if (!open) setSelectedVote(null);
          }}
        />
      )}
    </div>
  );
}
