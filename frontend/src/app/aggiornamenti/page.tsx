"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight } from "lucide-react";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { CentroPage, PageIntro } from "@/components/centro/CentroPage";

const NEWS = [
  { key: "news1", href: "/pubblicazioni" },
  { key: "news3", href: "/sistemi" },
  { key: "news2", href: "/pubblicazioni" },
] as const;

export default function AggiornamentiPage() {
  const t = useTranslations("Centro");
  return (
    <CentroPage>
      <PageIntro kicker={t("updKicker")} title={t("updTitle")} lead={t("updLead")} />

      <div className="container-page pb-12 md:pb-16">
        <NewsletterSignup source="landing" />
      </div>

      <section className="container-page pb-16 md:pb-24" aria-labelledby="novita-title">
        <div className="grid gap-6 border-t border-line pt-8 lg:grid-cols-12 lg:gap-10">
          <h2 id="novita-title" className="label-mono lg:col-span-3 lg:pt-1.5">
            {t("latestTitle")}
          </h2>
          <ol className="grid gap-4 lg:col-span-9">
            {NEWS.map((n) => (
              <li key={n.key}>
                <Link
                  href={n.href}
                  className="group grid gap-2 rounded-lg border border-line bg-surface p-5 transition-colors hover:border-line-strong sm:p-7 md:grid-cols-[11rem_1fr] md:gap-8"
                >
                  <p className="text-sm text-fg-muted">
                    <span className="block font-medium text-fg-secondary">{t(`${n.key}When`)}</span>
                    {t(`${n.key}Tag`)}
                  </p>
                  <div>
                    <h3 className="text-xl font-semibold tracking-[-0.02em] text-fg">{t(`${n.key}Title`)}</h3>
                    <p className="mt-2 text-[15px] leading-relaxed text-fg-secondary sm:text-base">{t(`${n.key}Body`)}</p>
                    <span className="mt-4 inline-flex items-center gap-1.5 text-sm font-medium text-brand-fg">
                      {t(`${n.key}Cta`)}
                      <ArrowRight className="size-4 transition-transform group-hover:translate-x-0.5" aria-hidden />
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ol>
        </div>
      </section>
    </CentroPage>
  );
}
