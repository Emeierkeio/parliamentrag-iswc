"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import { Logo, LogoReveal } from "@/components/brand/Logo";
import { CENTRO_NAV } from "@/components/shell/CentroBar";
import { AUTHOR, DATA_LICENSE_URL, FAMILY, DATAPACT_GRANT_URL, DATAPACT_URL, OPEN_DATA_URL, UNIMIB_URL } from "@/components/brand/family";
import { GITHUB_URL, HF_URL, ORKG_URL, PAPER_DEMO_PDF, PAPER_IN_USE_PDF, ZENODO_URL } from "@/components/centro/systems";

const RESEARCH = [
  { href: PAPER_IN_USE_PDF, key: "paperInUse" },
  { href: PAPER_DEMO_PDF, key: "paperDemo" },
  { href: GITHUB_URL, label: "GitHub" },
  { href: ORKG_URL, label: "ORKG" },
  { href: ZENODO_URL, label: "Zenodo" },
  { href: HF_URL, label: "Hugging Face" },
] as const;

function Column({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <p className="label-mono text-fg-muted">{title}</p>
      <ul className="mt-2 text-[15px] md:mt-4 md:space-y-2.5 md:text-sm">{children}</ul>
    </div>
  );
}

function Item({ href, children }: { href: string; children: ReactNode }) {
  const className =
    "flex min-h-11 w-full items-center gap-1 text-fg-secondary transition-colors hover:text-fg md:inline-flex md:min-h-0 md:w-auto";
  return (
    <li>
      {href.startsWith("http") ? (
        <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
          {children}
          <ArrowUpRight className="size-3 text-fg-muted" aria-hidden />
        </a>
      ) : (
        <Link href={href} className={className}>
          {children}
        </Link>
      )}
    </li>
  );
}

/* One footer for every page of the research site. */
export function SiteFooter({
  reveal = false,
}: {
  /** The large animated lockup, on the landing page only. */
  reveal?: boolean;
}) {
  const t = useTranslations("Landing");
  const tc = useTranslations("Centro");
  return (
    <footer className="border-t border-line bg-surface">
      {reveal && (
        <div className="container-page overflow-hidden">
          <LogoReveal className="py-14 md:py-20" />
        </div>
      )}
      <div className={`container-page grid grid-cols-2 gap-x-6 gap-y-10 py-12 md:grid-cols-12 md:py-14 ${reveal ? "border-t border-line" : ""}`}>
        <div className="col-span-2 flex flex-col gap-5 md:col-span-4">
          <div>
            <Logo size={19} />
            <p className="mt-3 max-w-xs text-[15px] text-fg-secondary md:text-sm">{tc("descriptor")}</p>
          </div>
          <div>
            <p className="text-sm text-fg-muted">
              {t.rich("footerBy", {
                name: AUTHOR.name,
                link: (chunks) => (
                  <a href={AUTHOR.url} target="_blank" rel="noopener noreferrer" className="link font-medium text-fg">
                    {chunks}
                  </a>
                ),
              })}
              . {t("footerAuthors")},{" "}
              <a href={UNIMIB_URL} target="_blank" rel="noopener noreferrer" className="link">
                {t("footerUni")}
              </a>
              .
            </p>
            <ul className="mt-1 flex flex-wrap gap-x-4">
              {AUTHOR.links.map((l) => (
                <li key={l.key}>
                  <a
                    href={l.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    aria-label={t("footerOn", { name: AUTHOR.name, network: l.label })}
                    className="inline-flex min-h-11 items-center gap-0.5 text-caption text-fg-muted transition-colors hover:text-fg md:min-h-7"
                  >
                    {l.label}
                    <ArrowUpRight className="size-3" aria-hidden />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
        <Column title={tc("colProject")} className="md:col-span-2">
          {CENTRO_NAV.map((n) => (
            <Item key={n.href} href={n.href}>
              {tc(n.key)}
            </Item>
          ))}
        </Column>
        <Column title={tc("colSystems")} className="md:col-span-2">
          {FAMILY.filter((f) => f.id !== "parliamentrag").map(({ Mark, ...f }) => (
            <Item key={f.id} href={f.url}>
              <span className="mr-1.5 flex w-5 justify-center">
                <Mark size={18} />
              </span>
              {f.name}
            </Item>
          ))}
        </Column>
        <Column title={t("footerColResearch")} className="md:col-span-2">
          {RESEARCH.map((r) => (
            <Item key={r.href} href={r.href}>
              {"key" in r ? t(r.key) : r.label}
            </Item>
          ))}
        </Column>
        <Column title={t("footerColLegal")} className="md:col-span-2">
          <Item href="/privacy">{t("footerPrivacy")}</Item>
          <Item href="/termini">{t("footerTerms")}</Item>
          <Item href={DATA_LICENSE_URL}>{t("footerLicense")}</Item>
          <Item href={OPEN_DATA_URL}>dati.camera.it</Item>
        </Column>
      </div>
      <div className="border-t border-line">
        <div className="container-page flex flex-col gap-1 py-5 text-caption text-fg-muted md:flex-row md:justify-between md:gap-6">
          <p>
            {t("footerFunding")}, {t("footerGrants")}{" "}
            <a href={DATAPACT_GRANT_URL} target="_blank" rel="noopener noreferrer" className="link">
              101189771
            </a>{" "}
            (
            <a href={DATAPACT_URL} target="_blank" rel="noopener noreferrer" className="link">
              DataPACT
            </a>
            )
          </p>
          <p className="max-w-xl md:text-right">{t("footerDisclaimer")}</p>
        </div>
      </div>
    </footer>
  );
}
