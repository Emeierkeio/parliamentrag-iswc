"use client";

import { useTranslations } from "next-intl";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";

const SECTIONS = ["s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"] as const;

// Anchor targeted by the consent checkbox in the answer feedback dialog
const ANCHORS: Partial<Record<(typeof SECTIONS)[number], string>> = { s9: "newsletter" };

export default function PrivacyPage() {
  const t = useTranslations("Privacy");

  return (
    <div className="min-h-screen bg-bg">
      <AppBar />

      <main className="container-page py-14 md:py-20">
        <article className="max-w-reading">
          <h1 className="serif-display text-4xl leading-[1.08] text-fg sm:text-5xl">
            {t("title")}
          </h1>
          <p className="mt-4 font-mono text-caption text-fg-muted">{t("updated")}</p>

          <div className="mt-10 rounded-md bg-surface-muted p-5">
            <p className="label-mono">{t("introTitle")}</p>
            <p className="mt-2 leading-relaxed text-fg-secondary">{t("intro")}</p>
          </div>

          <div className="mt-12 space-y-10">
            {SECTIONS.map((s) => (
              <section key={s} id={ANCHORS[s]} className="scroll-mt-8">
                <h2 className="text-xl font-semibold tracking-[var(--tracking-heading)] text-fg">
                  {t(`${s}t`)}
                </h2>
                <p className="mt-3 leading-relaxed text-fg-secondary">{t(`${s}b`)}</p>
              </section>
            ))}
          </div>
        </article>
      </main>
      <SiteFooter />
    </div>
  );
}
