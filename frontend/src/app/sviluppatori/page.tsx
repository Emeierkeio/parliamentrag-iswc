"use client";

import { useState, type ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import { ArrowRight, ArrowUpRight, Check, Copy, KeyRound, Mail } from "lucide-react";
import { CentroPage, PageIntro } from "@/components/centro/CentroPage";
import { GITHUB_URL, HF_URL, MCP_ENDPOINT, MCP_README, ZENODO_URL } from "@/components/centro/systems";

/* Tool names exposed by mcp/server.py, as listed in mcp/README.md. */
const MCP_TOOLS = [
  "search_parliament",
  "list_sessions",
  "get_session_votes",
  "get_vote_details",
  "get_voted_text",
  "get_debate",
  "get_vote_hemicycle",
] as const;

const API_OFFER = ["apiOffer1", "apiOffer2", "apiOffer3", "apiOffer4"] as const;

const API_CONTACT = "contatti@parliamentrag.it";
const API_MAILTO = `mailto:${API_CONTACT}?subject=${encodeURIComponent("Richiesta token API ParliamentRAG")}`;

const LOCAL_CMD = "claude mcp add parliamentrag -- uv run /path/to/ParliamentRAG/mcp/server.py";

function CodeLine({ code, label }: { code: string; label: string }) {
  const t = useTranslations("Centro");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };
  return (
    <div>
      <p className="mb-2 text-sm text-fg-muted">{label}</p>
      <div className="flex items-start gap-1 rounded-md border border-line bg-surface-muted py-1 pr-1 pl-4">
        <code className="min-w-0 flex-1 py-2.5 font-mono text-[13px] leading-relaxed break-all text-fg">{code}</code>
        <button
          type="button"
          onClick={copy}
          aria-label={copied ? t("copied") : t("copy")}
          className="inline-flex size-11 shrink-0 items-center justify-center rounded-md text-fg-secondary transition-colors hover:bg-surface hover:text-fg"
        >
          {copied ? <Check className="size-4 text-brand-fg" aria-hidden /> : <Copy className="size-4" aria-hidden />}
        </button>
      </div>
    </div>
  );
}

function Block({ id, kicker, title, children }: { id: string; kicker: string; title: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="grid gap-6 border-t border-line pt-8 pb-14 lg:grid-cols-12 lg:gap-10 lg:pb-20">
      <div className="lg:col-span-4">
        <p className="label-mono">{kicker}</p>
        <h2 id={`${id}-title`} className="serif-display mt-3 text-[clamp(1.75rem,5vw,2.25rem)] leading-[1.12] text-fg">
          {title}
        </h2>
      </div>
      <div className="min-w-0 lg:col-span-8">{children}</div>
    </section>
  );
}

const outLink = "group inline-flex min-h-11 items-center gap-1.5 text-[15px] font-medium text-brand-fg";

export default function SviluppatoriPage() {
  const t = useTranslations("Centro");
  return (
    <CentroPage>
      <PageIntro
        kicker={t("devKicker")}
        title={t("devTitle")}
        lead={t("devLead")}
        aside={
          <ul className="flex flex-wrap gap-2">
            {[
              { href: "#mcp", label: t("mcpTitle") },
              { href: "#api", label: t("apiTitle") },
              { href: "#dump", label: t("dumpTitle") },
            ].map((l) => (
              <li key={l.href}>
                <a href={l.href} className="inline-flex h-11 items-center rounded-full border border-line-strong bg-surface px-4 text-sm font-medium text-fg hover:bg-surface-muted">
                  {l.label}
                </a>
              </li>
            ))}
          </ul>
        }
      />

      <div className="container-page">
        <Block id="mcp" kicker="Model Context Protocol" title={t("mcpTitle")}>
          <p className="max-w-prose text-base leading-relaxed text-fg-secondary sm:text-[17px]">{t("mcpBody")}</p>
          <div className="mt-8 grid gap-6">
            <CodeLine label={t("mcpRemoteLabel")} code={MCP_ENDPOINT} />
            <CodeLine label={t("mcpLocalLabel")} code={LOCAL_CMD} />
          </div>
          <p className="mt-8 text-sm text-fg-muted">{t("mcpToolsLabel")}</p>
          <ul className="mt-3 flex flex-wrap gap-2">
            {MCP_TOOLS.map((tool) => (
              <li key={tool} className="rounded-sm bg-surface-muted px-2 py-1 font-mono text-[13px] text-fg-secondary">
                {tool}
              </li>
            ))}
          </ul>
          <a href={MCP_README} target="_blank" rel="noopener noreferrer" className={`${outLink} mt-6`}>
            {t("mcpGuide")}
            <ArrowUpRight className="size-4" aria-hidden />
          </a>
        </Block>

        <Block id="api" kicker="HTTP · JSON" title={t("apiTitle")}>
          <p className="max-w-prose text-base leading-relaxed text-fg-secondary sm:text-[17px]">{t("apiBody")}</p>
          <ul className="mt-6 grid gap-3 sm:grid-cols-2">
            {API_OFFER.map((k) => (
              <li key={k} className="flex gap-3 rounded-lg border border-line bg-surface p-4 text-[15px] leading-relaxed text-fg-secondary">
                <span className="mt-2 size-1.5 shrink-0 rounded-full bg-brand" aria-hidden />
                {t(k)}
              </li>
            ))}
          </ul>
          <div className="mt-6 flex flex-col gap-5 rounded-lg border border-brand-soft-strong bg-surface-brand p-5 sm:p-6 md:flex-row md:items-center md:justify-between">
            <div className="flex gap-3">
              <KeyRound className="mt-0.5 size-5 shrink-0 text-brand-fg" aria-hidden />
              <div>
                <h3 className="font-semibold text-fg">{t("accessTitle")}</h3>
                <p className="mt-1 text-[15px] leading-relaxed text-fg-secondary">{t("accessBody")}</p>
              </div>
            </div>
            <a
              href={API_MAILTO}
              className="inline-flex h-12 shrink-0 items-center justify-center gap-2 rounded-full bg-brand px-6 text-[15px] font-medium text-on-brand transition-colors hover:bg-brand-hover"
            >
              <Mail className="size-4" aria-hidden />
              {t("accessCta")}
            </a>
          </div>
        </Block>

        <Block id="dump" kicker="RDF · Turtle" title={t("dumpTitle")}>
          <p className="max-w-prose text-base leading-relaxed text-fg-secondary sm:text-[17px]">{t("dumpBody")}</p>
          <ul className="mt-6 divide-y divide-line border-y border-line">
            <li>
              <Link href="/data" className="flex min-h-14 items-center justify-between gap-4 text-[15px] text-fg hover:text-brand-fg">
                {t("dumpRdf")}
                <ArrowRight className="size-4 text-fg-muted" aria-hidden />
              </Link>
            </li>
            {[
              { href: ZENODO_URL, label: t("dumpZenodo") },
              { href: HF_URL, label: t("dumpHf") },
              { href: GITHUB_URL, label: t("dumpCode") },
            ].map((l) => (
              <li key={l.href}>
                <a href={l.href} target="_blank" rel="noopener noreferrer" className="flex min-h-14 items-center justify-between gap-4 text-[15px] text-fg hover:text-brand-fg">
                  {l.label}
                  <ArrowUpRight className="size-4 shrink-0 text-fg-muted" aria-hidden />
                </a>
              </li>
            ))}
          </ul>
          <p className="mt-6 max-w-prose text-sm leading-relaxed text-fg-muted">{t("license")}</p>
        </Block>
      </div>
    </CentroPage>
  );
}
