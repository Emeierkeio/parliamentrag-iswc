"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowDown, ArrowRight, ArrowUpRight } from "lucide-react";
import { CentroPage, PageIntro } from "@/components/centro/CentroPage";
import { PageDots } from "@/components/centro/PageDots";
import { SoonBadge } from "@/components/centro/SystemCard";
import { SYSTEMS } from "@/components/centro/systems";

const LINKS = ["link1", "link2", "link3"] as const;

export default function SistemiPage() {
  const t = useTranslations("Centro");
  const screens = useMemo(
    () => [
      { id: "intro", label: t("sysTitle") },
      ...SYSTEMS.map((s) => ({ id: s.id, label: s.name })),
      { id: "collegamenti", label: t("linksTitle") },
    ],
    [t],
  );

  return (
    <CentroPage>
      <div id="intro" className="snap-screen">
        <PageIntro
          className="max-md:p-0"
          kicker={t("sysKicker")}
          title={t("sysTitle")}
          lead={t("sysLead")}
          aside={
            <ul className="divide-y divide-line border-y border-line">
              {SYSTEMS.map((s) => {
                const { Mark } = s;
                return (
                  <li key={s.id}>
                    <a href={`#${s.id}`} className="group flex min-h-14 items-center gap-4 text-fg">
                      <span className="flex w-8 justify-center">
                        <Mark size={28} />
                      </span>
                      <span className="flex-1 text-[17px] font-medium">{s.name}</span>
                      {!s.live && <SoonBadge />}
                      <ArrowDown className="size-4 text-fg-muted transition-transform group-hover:translate-y-0.5" aria-hidden />
                    </a>
                  </li>
                );
              })}
            </ul>
          }
        />
      </div>

      {SYSTEMS.map((s) => {
        const { Mark } = s;
        return (
          <section
            key={s.id}
            id={s.id}
            aria-labelledby={`${s.id}-name`}
            className="container-page snap-screen grid gap-6 border-t border-line md:gap-10 md:py-20 lg:grid-cols-12"
          >
            <div className="lg:col-span-5">
              <div className="flex items-center justify-between gap-4 lg:justify-start">
                <Mark size={56} />
                {!s.live && <SoonBadge />}
              </div>
              <h2 id={`${s.id}-name`} className="serif-display mt-5 text-[clamp(2.25rem,8vw,3.25rem)] leading-none text-fg">
                {s.name}
              </h2>
              <p className="mt-4 text-[17px] leading-relaxed text-fg-secondary md:text-lg">{t(`${s.id}Job`)}</p>
              {s.live ? (
                <a
                  href={s.url}
                  target="_blank"
                  rel="noopener"
                  className="mt-6 inline-flex h-12 w-full items-center justify-center gap-2 rounded-full bg-brand px-6 text-[15px] font-medium text-on-brand transition-colors hover:bg-brand-hover sm:w-auto"
                >
                  {t("visitDomain", { domain: s.domain })}
                  <ArrowUpRight className="size-4" aria-hidden />
                </a>
              ) : (
                <p className="mt-6 font-mono text-sm text-fg-muted">{t("soonDomain", { domain: s.domain })}</p>
              )}
            </div>
            <dl className="grid gap-5 text-[15px] leading-relaxed md:gap-8 md:text-base lg:col-span-6 lg:col-start-7 lg:pt-2">
              <div className="border-t border-line pt-4">
                <dt className="label-mono">{t("labelWhat")}</dt>
                <dd className="mt-2 text-fg">{t(`${s.id}What`)}</dd>
              </div>
              <div className="border-t border-line pt-4">
                <dt className="label-mono">{t("labelFor")}</dt>
                <dd className="mt-2 text-fg-secondary">{t(`${s.id}For`)}</dd>
              </div>
            </dl>
          </section>
        );
      })}

      <section
        id="collegamenti"
        aria-labelledby="collegamenti-title"
        className="snap-screen border-t border-line bg-surface-muted md:py-20"
      >
        <div className="md:container-page">
          <h2 id="collegamenti-title" className="serif-display text-[clamp(1.75rem,5vw,2.5rem)] leading-[1.12] text-fg">
            {t("linksTitle")}
          </h2>
          <ol className="mt-6 grid gap-5 md:mt-10 md:grid-cols-3 md:gap-6">
            {LINKS.map((k, i) => (
              <li key={k} className="flex gap-3 md:block md:rounded-lg md:border md:border-line md:bg-surface md:p-6">
                <span className="tabular font-mono text-caption leading-6 text-fg-muted">{String(i + 1).padStart(2, "0")}</span>
                <div className="md:mt-3">
                  <h3 className="font-semibold leading-6 text-fg">{t(`${k}Title`)}</h3>
                  <p className="mt-1 text-[15px] leading-relaxed text-fg-secondary">{t(`${k}Body`)}</p>
                </div>
              </li>
            ))}
          </ol>
          <Link href="/data" className="group mt-6 inline-flex min-h-11 items-center gap-1.5 text-[15px] font-medium text-brand-fg md:mt-8">
            {t("linksCta")}
            <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
          </Link>
        </div>
      </section>

      <PageDots screens={screens} />
    </CentroPage>
  );
}
