"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import { AppBar } from "@/components/shell/AppBar";
import { SiteFooter } from "@/components/shell/SiteFooter";

// Mirror di backend/config/default.yaml → authority.weights.
// Se i pesi cambiano lato backend vanno aggiornati anche qui.
const WEIGHTS = [
  { name: "wInterventions", desc: "dInterventions", weight: 0.25 },
  { name: "wCommittee", desc: "dCommittee", weight: 0.25 },
  { name: "wActs", desc: "dActs", weight: 0.2 },
  { name: "wProfession", desc: "dProfession", weight: 0.15 },
  { name: "wEducation", desc: "dEducation", weight: 0.1 },
  { name: "wRole", desc: "dRole", weight: 0.05 },
] as const;

const PAPER_LINKS = [
  { label: "linkPaper", href: "https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf" },
  { label: "linkArxiv", href: "https://arxiv.org/abs/2608.13410" },
  { label: "linkOrkg", href: "https://orkg.org/papers/R1909763" },
] as const;

export default function MethodPage() {
  const t = useTranslations("Method");

  return (
    <div className="min-h-screen bg-bg">
      <AppBar />

      <main className="container-page py-14 md:py-20">
        <article className="max-w-reading">
          <h1 className="serif-display text-4xl leading-[1.08] text-fg sm:text-5xl">
            {t("title")}
          </h1>
          <p className="mt-4 text-lg text-fg-secondary">{t("tagline")}</p>

          <div className="mt-10 rounded-md bg-surface-muted p-5">
            <p className="label-mono">{t("introTitle")}</p>
            <p className="mt-2 leading-relaxed text-fg-secondary">{t("intro")}</p>
          </div>

          <div className="mt-12 space-y-12">
            <Section title={t("pipelineTitle")}>
              <p>{t("pipelineP1")}</p>
              <p>{t("pipelineP2")}</p>
            </Section>

            <Section title={t("authorityTitle")}>
              <p>{t("authorityP1")}</p>

              <table className="w-full border-t border-line text-sm">
                <thead>
                  <tr className="text-left">
                    <th scope="col" className="py-2.5 font-medium text-fg-muted">{t("thComponent")}</th>
                    <th scope="col" className="py-2.5 text-right font-medium text-fg-muted">{t("thWeight")}</th>
                  </tr>
                </thead>
                <tbody>
                  {WEIGHTS.map((w) => (
                    <tr key={w.name} className="border-t border-line">
                      <td className="py-3 pr-4">
                        <p className="font-medium text-fg">{t(w.name)}</p>
                        <p className="text-fg-muted">{t(w.desc)}</p>
                      </td>
                      <td className="py-3">
                        <div className="flex items-center justify-end gap-3">
                          <div className="hidden h-1.5 w-24 overflow-hidden rounded-full bg-surface-sunken sm:block">
                            <div
                              className="h-full rounded-full bg-brand"
                              style={{ width: `${w.weight * 100 * 2.5}%` }}
                            />
                          </div>
                          <span className="tabular min-w-[2.6rem] text-right font-semibold text-fg">
                            {Math.round(w.weight * 100)}%
                          </span>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <p>
                {t.rich("authorityP2", {
                  ranking: (chunks) => (
                    <Link href="/ranking" className="link">
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            </Section>

            <Section title={t("citationsTitle")}>
              <p>{t("citationsP1")}</p>
              <p>{t("citationsP2")}</p>
            </Section>

            <Section title={t("limitsTitle")}>
              <p>{t("limitsP1")}</p>
            </Section>

            <Section title={t("compassTitle")}>
              <p>{t("compassP1")}</p>
              <p>{t("compassP2")}</p>
            </Section>

            <Section title={t("linksTitle")}>
              <p>{t("linksIntro")}</p>
              <ul className="flex flex-wrap gap-x-6 gap-y-2">
                {PAPER_LINKS.map((l) => (
                  <li key={l.href}>
                    <a
                      href={l.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="link inline-flex items-center gap-1.5"
                    >
                      {t(l.label)}
                      <ExternalLink className="h-3.5 w-3.5" aria-hidden />
                    </a>
                  </li>
                ))}
              </ul>
            </Section>
          </div>
        </article>
      </main>
      <SiteFooter />
    </div>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-semibold tracking-[var(--tracking-heading)] text-fg">{title}</h2>
      <div className="mt-3 space-y-4 leading-relaxed text-fg-secondary">{children}</div>
    </section>
  );
}
