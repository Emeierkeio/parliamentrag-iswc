"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { CentroBar } from "@/components/shell/CentroBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { cn } from "@/lib/utils";

/** Chrome shared by every page of the research site. */
export function CentroPage({ children, reveal = false }: { children: ReactNode; reveal?: boolean }) {
  const t = useTranslations("Centro");
  return (
    <div className="flex min-h-[100dvh] flex-col bg-bg text-fg">
      <a
        href="#contenuto"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-skip focus:rounded-full focus:bg-surface focus:px-4 focus:py-2 focus:shadow-float"
      >
        {t("skip")}
      </a>
      <CentroBar />
      <main id="contenuto" className="flex-1">
        {children}
      </main>
      <SiteFooter reveal={reveal} />
    </div>
  );
}

/**
 * Page opening: kicker and headline on the left, the lead (and an optional
 * aside) on the right from lg up, so the first screen uses the full width.
 */
export function PageIntro({
  kicker,
  title,
  lead,
  aside,
  className,
}: {
  kicker: string;
  title: ReactNode;
  lead: ReactNode;
  aside?: ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("container-page grid gap-6 pt-10 pb-12 sm:pt-16 md:pb-16 lg:grid-cols-12 lg:gap-10 lg:pt-20", className)}>
      <div className="lg:col-span-7">
        <p className="label-mono">{kicker}</p>
        <h1 className="serif-display mt-4 whitespace-pre-line text-[clamp(2.25rem,8vw,4rem)] leading-[1.06] text-fg">{title}</h1>
      </div>
      <div className="flex flex-col justify-end gap-6 lg:col-span-5">
        <p className="text-[17px] leading-relaxed text-fg-secondary sm:text-lg">{lead}</p>
        {aside}
      </div>
    </section>
  );
}

export function SectionTitle({ title, lead, id }: { title: string; lead?: string; id?: string }) {
  return (
    <div className="max-w-3xl">
      <h2 id={id} className="serif-display text-[clamp(1.75rem,5vw,2.5rem)] leading-[1.12] text-fg">
        {title}
      </h2>
      {lead && <p className="mt-3 text-base leading-relaxed text-fg-secondary sm:text-[17px]">{lead}</p>}
    </div>
  );
}
