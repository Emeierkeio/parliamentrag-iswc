"use client";

import { useTranslations } from "next-intl";
import { Mail } from "lucide-react";
import { CentroPage } from "@/components/centro/CentroPage";
import { DocLayout } from "@/components/centro/DocLayout";

type Section = { h: string; id?: string; p: string[] };

const PRIVACY_CONTACT = "privacy@parliamentrag.it";

/* Privacy and terms: the same template on every ParliamentRAG site, read from
   messages as { title, updated, sections: [{ h, id?, p[] }] }. */
export function LegalDoc({ namespace }: { namespace: "Privacy" | "Terms" }) {
  const t = useTranslations(namespace);
  const tc = useTranslations("Centro");
  const sections = (t.raw("sections") as Section[]).map((s, i) => ({ ...s, id: s.id ?? `sezione-${i + 1}` }));

  return (
    <CentroPage>
      <DocLayout
        sections={sections.map((s) => ({ id: s.id, title: s.h }))}
        header={
          <>
            <h1 className="serif-display text-[clamp(2.25rem,8vw,3.5rem)] leading-[1.08] text-fg">{t("title")}</h1>
            <p className="mt-4 font-mono text-caption text-fg-muted">{t("updated")}</p>
          </>
        }
        rail={
          namespace === "Privacy" ? (
            <div className="rounded-lg border border-line bg-surface p-5">
              <p className="label-mono">{tc("privacyContactTitle")}</p>
              <p className="mt-2 text-[15px] leading-relaxed text-fg-secondary">{tc("privacyContactBody")}</p>
              <a
                href={`mailto:${PRIVACY_CONTACT}`}
                className="mt-4 inline-flex min-h-11 max-w-full items-center gap-2 text-[15px] font-medium [overflow-wrap:anywhere] text-brand-fg hover:text-fg"
              >
                <Mail className="size-4 shrink-0" aria-hidden />
                {PRIVACY_CONTACT}
              </a>
            </div>
          ) : undefined
        }
      >
        <div className="space-y-10">
          {sections.map((s) => (
            <section key={s.id} id={s.id} className="scroll-mt-24">
              <h2 className="text-xl font-semibold tracking-[var(--tracking-heading)] text-fg">{s.h}</h2>
              <div className="mt-3 space-y-3 leading-relaxed text-fg-secondary">
                {s.p.map((p, j) => (
                  <p key={j}>{p}</p>
                ))}
              </div>
            </section>
          ))}
        </div>
      </DocLayout>
    </CentroPage>
  );
}
