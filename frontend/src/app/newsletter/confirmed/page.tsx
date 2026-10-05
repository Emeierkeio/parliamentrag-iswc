"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, Check } from "lucide-react";
import { CentroBar } from "@/components/shell/CentroBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { Button } from "@/components/ui/button";

// Landing page of the Brevo double opt-in link (redirectionUrl).

const NEXT = [
  { key: "Systems", href: "/sistemi" },
  { key: "Papers", href: "/pubblicazioni" },
  { key: "Data", href: "/data" },
] as const;

export default function NewsletterConfirmedPage() {
  const t = useTranslations("NewsletterConfirmed");
  const tc = useTranslations("Centro");

  return (
    <div className="flex min-h-[100dvh] flex-col bg-bg">
      <CentroBar />

      <main className="flex-1 container-page pt-16 pb-20 md:pt-24">
        <div className="max-w-reading">
          <span
            aria-hidden
            className="flex h-10 w-10 items-center justify-center rounded-full bg-brand-soft text-brand-fg"
          >
            <Check className="h-5 w-5" strokeWidth={2} />
          </span>

          <h1 className="mt-8 serif-display text-4xl leading-[1.08] text-fg md:text-5xl">
            {t("title")}
          </h1>
          <p className="mt-5 max-w-prose text-lg leading-relaxed text-fg-secondary">
            {t("body")}
          </p>

          <Button asChild size="lg" className="group mt-10">
            <Link href="/">
              {t("backHome")}
              <ArrowRight className="transition-transform group-hover:translate-x-0.5" aria-hidden />
            </Link>
          </Button>

          <section className="mt-20 border-t border-line pt-8">
            <h2 className="label-mono">{t("nextTitle")}</h2>
            <ul className="mt-6 grid grid-cols-1 gap-8 sm:grid-cols-3 sm:gap-6">
              {NEXT.map(({ key, href }) => (
                <li key={key}>
                  <Link href={href} className="group block">
                    <span className="flex items-center justify-between gap-2 text-base font-semibold text-fg transition-colors group-hover:text-brand-fg">
                      {tc(`confNext${key}Title`)}
                      <ArrowRight className="h-4 w-4 text-fg-faint transition-transform group-hover:translate-x-0.5 group-hover:text-brand-fg" aria-hidden />
                    </span>
                    <span className="mt-1.5 block text-sm leading-relaxed text-fg-secondary">
                      {tc(`confNext${key}Body`)}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        </div>
      </main>
      <SiteFooter />
    </div>
  );
}
