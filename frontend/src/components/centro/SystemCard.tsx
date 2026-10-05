"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { SYSTEMS } from "./systems";

type System = (typeof SYSTEMS)[number];

export function SoonBadge({ className }: { className?: string }) {
  const t = useTranslations("Centro");
  return (
    <span className={cn("inline-flex items-center rounded-sm bg-notice-soft px-2 py-0.5 font-mono text-caption uppercase tracking-[0.06em] text-notice-fg", className)}>
      {t("soon")}
    </span>
  );
}

/**
 * One system as a single tap target. A system that is not live yet links to
 * its section on /sistemi instead of a domain that does not answer.
 */
export function SystemCard({ system }: { system: System }) {
  const t = useTranslations("Centro");
  const { Mark } = system;
  const body = (
    <>
      <div className="flex items-start justify-between gap-4">
        <Mark size={52} />
        {!system.live && <SoonBadge />}
      </div>
      <h3 className="mt-8 text-2xl font-semibold tracking-[-0.025em] text-fg">{system.name}</h3>
      <p className="mt-3 text-base leading-relaxed text-fg-secondary">{t(`${system.id}Job`)}</p>
      <span className="mt-auto flex items-center justify-between gap-3 border-t border-line pt-4 text-sm">
        <span className="font-mono text-fg-muted">{system.domain}</span>
        <span className="inline-flex items-center gap-1 font-medium text-brand-fg">
          {system.live ? t("visit") : t("readMore")}
          {system.live ? (
            <ArrowUpRight className="size-4" aria-hidden />
          ) : (
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
          )}
        </span>
      </span>
    </>
  );
  const className =
    "group flex min-h-full flex-col gap-0 rounded-lg border border-line bg-surface p-6 pb-5 transition-colors hover:border-line-strong focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus sm:p-7 sm:pb-5 [&>p]:mb-8";
  return system.live ? (
    <a href={system.url} target="_blank" rel="noopener" className={className}>
      {body}
    </a>
  ) : (
    <Link href={`/sistemi#${system.id}`} className={className}>
      {body}
    </Link>
  );
}
