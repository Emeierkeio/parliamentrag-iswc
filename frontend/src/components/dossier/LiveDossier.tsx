"use client";

import { useLocale, useTranslations } from "next-intl";
import { buildDossier, compassSides, BLOC_ORDER, type SavedAnswer } from "@/lib/dossier";
import type { Message, ProcessingProgress } from "@/types";
import { GroupPositions } from "@/components/dossier/GroupPositions";
import { VoicesMatrix } from "@/components/dossier/VoicesMatrix";
import { CompassAxis } from "@/components/dossier/CompassAxis";
import { formatDay, listFormat } from "@/components/dossier/format";

function Pending({ label, lines = 3 }: { label: string; lines?: number }) {
  return (
    <div className="flex flex-col gap-2" aria-busy="true">
      <p className="text-sm text-fg-muted">{label}</p>
      {Array.from({ length: lines }, (_, i) => (
        <span
          key={i}
          className="block h-3 rounded-xs bg-surface-sunken motion-safe:animate-skeleton"
          style={{ width: `${92 - i * 14}%` }}
        />
      ))}
    </div>
  );
}

/*
 * The dossier while the pipeline builds it: the same page as /tema/[id],
 * each part filled the moment its event arrives (committees, voices,
 * statistics, compass, then the group sections as the text streams). When
 * the answer is saved the home view moves to the permanent dossier.
 */
export function LiveDossier({
  query,
  answer,
  progress,
  onCancel,
}: {
  query: string;
  answer: Message | undefined;
  progress: ProcessingProgress | null;
  onCancel: () => void;
}) {
  const t = useTranslations("Dossier");
  const th = useTranslations("Home");
  const locale = useLocale();

  const raw: SavedAnswer = {
    id: "live",
    query,
    answer: answer?.content ?? "",
    timestamp: new Date().toISOString(),
    citations: answer?.citations as SavedAnswer["citations"],
    experts: answer?.experts as SavedAnswer["experts"],
    compass: (answer?.compass ?? null) as SavedAnswer["compass"],
    topic_stats: (answer?.topicStats ?? null) as SavedAnswer["topic_stats"],
    commissioni: answer?.commissioni as SavedAnswer["commissioni"],
  };
  const dossier = buildDossier(raw);
  const sides = dossier.compass ? compassSides(dossier.compass) : null;
  const total = progress?.totalSteps ?? 8;
  const step = Math.min(progress?.currentStep ?? 1, total);
  const blocCounts = BLOC_ORDER.map((bloc) => ({
    bloc,
    n: dossier.groups.filter((g) => g.bloc === bloc).reduce((s, g) => s + g.interventions, 0),
  })).filter((b) => b.n > 0);

  return (
    <div className="container-page pb-24">
      <div className="sticky top-0 z-raised -mx-4 border-b border-line bg-bg/90 px-4 py-3 backdrop-blur-xl md:-mx-6 md:px-6">
        <div className="flex items-center gap-4">
          <p className="min-w-0 flex-1 truncate text-sm text-fg-secondary" role="status" aria-live="polite">
            {progress?.isWaiting
              ? progress.waitingMessage
              : th("liveStatus", { n: step, total, label: progress?.stepLabel ?? "" })}
          </p>
          <button type="button" onClick={onCancel} className="shrink-0 text-sm text-fg-muted hover:text-fg">
            {th("cancel")}
          </button>
        </div>
        <ol className="mt-2.5 grid gap-1" style={{ gridTemplateColumns: `repeat(${total}, minmax(0, 1fr))` }} aria-hidden>
          {Array.from({ length: total }, (_, i) => (
            <li
              key={i}
              className={
                i + 1 < step
                  ? "h-1 rounded-full bg-brand"
                  : i + 1 === step
                    ? "h-1 rounded-full bg-brand/40 motion-safe:animate-skeleton"
                    : "h-1 rounded-full bg-surface-sunken"
              }
            />
          ))}
        </ol>
      </div>

      <div className="grid grid-cols-[minmax(0,1fr)] gap-x-14 gap-y-10 pt-10 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-8">
          <div className="flex flex-col gap-4">
            <p className="label-mono text-fg-muted">
              {t("scope")}
              {dossier.commission && ` · ${dossier.commission}`}
            </p>
            <h1 className="serif-display text-[2.75rem] leading-[1.05] md:text-display-l">{dossier.topic}</h1>
            {dossier.interventions > 0 ? (
              <p className="text-sm text-fg-secondary">
                {t("stats", { interventions: dossier.interventions, speakers: dossier.speakers })}
                {dossier.firstDate && dossier.lastDate && (
                  <>
                    {" · "}
                    {t("period", { from: formatDay(dossier.firstDate, locale), to: formatDay(dossier.lastDate, locale) })}
                  </>
                )}
              </p>
            ) : (
              <span className="block h-3 w-64 rounded-xs bg-surface-sunken motion-safe:animate-skeleton" />
            )}
          </div>

          <section className="flex flex-col gap-4 rounded-lg border border-line bg-surface p-5 md:p-7">
            <h2 className="label-mono text-fg-muted">{t("inBrief")}</h2>
            {sides && (sides.negative.length > 0 || sides.positive.length > 0) ? (
              <p className="text-lg leading-relaxed md:text-xl motion-safe:animate-rise">
                {sides.negative.length > 0 &&
                  `${t("sides", { label: dossier.compass!.negative, groups: listFormat(sides.negative, locale) })} `}
                {sides.positive.length > 0 &&
                  t("sides", { label: dossier.compass!.positive, groups: listFormat(sides.positive, locale) })}
              </p>
            ) : (
              <Pending label={th("pendingCompass")} lines={2} />
            )}
            {dossier.intro && <p className="max-w-prose text-[15px] leading-relaxed text-fg-secondary">{dossier.intro}</p>}
            {blocCounts.length > 0 && (
              <p className="border-t border-line pt-4 text-[13px] text-fg-muted">
                {blocCounts.map((b) => `${t(`bloc_${b.bloc}`)} ${t("blocCount", { n: b.n })}`).join(" · ")}
              </p>
            )}
          </section>

          <section aria-label={t("navPositions")}>
            {dossier.groups.length > 0 ? (
              <GroupPositions groups={dossier.groups} locale={locale} />
            ) : (
              <Pending label={th("pendingPositions")} lines={6} />
            )}
          </section>
        </div>

        <aside className="flex flex-col gap-6 lg:sticky lg:top-24 lg:self-start">
          <section className="rounded-lg border border-line bg-surface p-5">
            <h2 className="label-mono pb-3 text-fg-muted">{t("voicesTitle")}</h2>
            {dossier.voices.length > 0 ? (
              <div className="motion-safe:animate-rise">
                <VoicesMatrix voices={dossier.voices.slice(0, 6)} weights={null} pool={dossier.voices.length} />
              </div>
            ) : (
              <Pending label={th("pendingVoices")} lines={5} />
            )}
          </section>
          <section className="rounded-lg border border-line bg-surface p-5">
            <h2 className="label-mono pb-3 text-fg-muted">{t("compassTitle")}</h2>
            {dossier.compass ? (
              <div className="motion-safe:animate-rise">
                <CompassAxis compass={dossier.compass} />
              </div>
            ) : (
              <Pending label={th("pendingCompass")} lines={5} />
            )}
          </section>
        </aside>
      </div>
    </div>
  );
}
