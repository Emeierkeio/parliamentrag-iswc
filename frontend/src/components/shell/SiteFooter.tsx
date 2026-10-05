"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import { Logo, LogoReveal } from "@/components/brand/Logo";

const RESEARCH = [
  { href: "https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf", key: "paperInUse" },
  { href: "https://emeierkeio.github.io/papers/parliamentrag-demo-iswc2026.pdf", key: "paperDemo" },
  { href: "https://github.com/Emeierkeio/ParliamentRAG", label: "GitHub" },
  { href: "https://orkg.org/papers/R1909763", label: "ORKG" },
  { href: "https://doi.org/10.5281/zenodo.21560331", label: "Zenodo" },
  { href: "https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19", label: "Hugging Face" },
] as const;

function Column({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={className}>
      <p className="label-mono text-fg-muted">{title}</p>
      <ul className="mt-4 space-y-2.5 text-sm">{children}</ul>
    </div>
  );
}

function Item({ href, children }: { href: string; children: ReactNode }) {
  const className = "inline-flex items-center gap-1 text-fg-secondary transition-colors hover:text-fg";
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

/* One footer for every page: the landing's link columns plus the
   newsletter, which hides itself when the mailing list is not configured. */
export function SiteFooter({
  reveal = false,
}: {
  /** The large animated lockup, on the landing page only. */
  reveal?: boolean;
}) {
  const t = useTranslations("Landing");
  const ts = useTranslations("Shell");
  const tb = useTranslations("Brand");
  return (
    <footer className="border-t border-line bg-surface">
      {reveal && (
        <div className="container-page overflow-hidden">
          <LogoReveal className="py-14 md:py-20" />
        </div>
      )}
      <div className={`container-page grid gap-10 py-14 md:grid-cols-12 ${reveal ? "border-t border-line" : ""}`}>
        <div className="flex flex-col gap-6 md:col-span-4">
          <div>
            <Logo size={19} />
            <p className="mt-3 max-w-xs text-sm text-fg-secondary">{tb("descriptor")}</p>
          </div>
          <p className="text-sm text-fg-muted">
            {t("footerThesis")}. {t("footerAuthors")},{" "}
            <a href="https://www.unimib.it/" target="_blank" rel="noopener noreferrer" className="link">
              {t("footerUni")}
            </a>
            .
          </p>
        </div>
        <Column title={t("footerColService")} className="md:col-span-2">
          <Item href="/home">{t("ctaPrimary")}</Item>
          <Item href="/timeline">{ts("navAula")}</Item>
          <Item href="/parlamentari">{ts("navDeputies")}</Item>
          <Item href="/gruppi">{ts("navGroups")}</Item>
          <Item href="/method">{t("footerMethod")}</Item>
          <Item href="/data">{t("footerData")}</Item>
        </Column>
        <Column title={t("footerColResearch")} className="md:col-span-2">
          {RESEARCH.map((r) => (
            <Item key={r.href} href={r.href}>
              {"key" in r ? t(r.key) : r.label}
            </Item>
          ))}
          <Item href="/iswc">ISWC 2026</Item>
        </Column>
        <Column title={t("footerNetwork")} className="md:col-span-2">
          <Item href="https://stenografo.it">Stenografo</Item>
        </Column>
        <Column title={t("footerColLegal")} className="md:col-span-2">
          <Item href="/privacy">{t("footerPrivacy")}</Item>
        </Column>
      </div>
      <div className="border-t border-line">
        <p className="container-page py-5 text-caption text-fg-muted">
          {t("footerFunding")}, {t("footerGrants")}{" "}
          <a href="https://doi.org/10.3030/101189771" target="_blank" rel="noopener noreferrer" className="link">
            101189771
          </a>{" "}
          (
          <a href="https://datapact.eu/" target="_blank" rel="noopener noreferrer" className="link">
            DataPACT
          </a>
          )
        </p>
      </div>
    </footer>
  );
}
