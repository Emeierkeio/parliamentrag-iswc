"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, Check, Copy, FileText } from "lucide-react";
import { CentroPage, PageIntro } from "@/components/centro/CentroPage";
import { PAPER_DEMO_PDF, PAPER_DEMO_TITLE, PAPER_IN_USE_ARXIV, PAPER_IN_USE_PDF, PAPER_IN_USE_TITLE } from "@/components/centro/systems";

const AUTHORS = "Mirko Tritella, Riccardo Pozzi, Matteo Palmonari";

/* From README.md (Citation), with the DOI and series of the published chapter. */
const BIBTEX = `@inproceedings{tritella2026whospeaksmatters,
  author    = {Tritella, Mirko and Pozzi, Riccardo and Palmonari, Matteo},
  title     = {Who Speaks Matters: Authority-Aware Multi-View Retrieval-Augmented Generation over Italian Parliamentary Proceedings},
  booktitle = {Proceedings of the 25th International Semantic Web Conference (ISWC 2026), In-Use Track},
  series    = {Lecture Notes in Computer Science},
  volume    = {17128},
  publisher = {Springer},
  year      = {2026},
  doi       = {10.1007/978-3-032-42029-9_24}
}`;

function Action({ href, children, primary = false }: { href: string; children: ReactNode; primary?: boolean }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={
        primary
          ? "inline-flex h-11 items-center gap-2 rounded-full bg-brand px-5 text-sm font-medium text-on-brand transition-colors hover:bg-brand-hover"
          : "inline-flex h-11 items-center gap-2 rounded-full border border-line-strong bg-surface px-5 text-sm font-medium text-fg transition-colors hover:bg-surface-muted"
      }
    >
      {children}
    </a>
  );
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="grid gap-5 border-t border-line pt-8 pb-12 lg:grid-cols-12 lg:gap-10 lg:pb-16">
      <h2 className="label-mono lg:col-span-3 lg:pt-1.5">{title}</h2>
      <div className="grid gap-4 lg:col-span-9">{children}</div>
    </section>
  );
}

/* Event visuals share the Milano Digital Week logo's proportions (432:267),
   so the ISWC and Milano Digital Week logos line up across cards. */
const VISUAL = "aspect-[432/267] w-28 shrink-0 self-start overflow-hidden rounded-md sm:w-36";

/* The ISWC site renders the list client-side and has no per-paper URL, so a text
   fragment cannot land on our row: link the accepted-papers page itself. */
const ISWC_ACCEPTED = "https://iswc2026.semanticweb.org/#/program/acceptedpapers";
const MDW_EVENT = "https://www.milanodigitalweek.com/event/parliamentrag-navigare-gli-atti-parlamentari-con-lia-affidabile";

function VisualLink({ href, label, children }: { href: string; label: string; children: ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      aria-label={label}
      className="shrink-0 self-start rounded-md transition-opacity hover:opacity-85 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand"
    >
      {children}
    </a>
  );
}

function IswcBadge() {
  return (
    <VisualLink href={ISWC_ACCEPTED} label="ISWC 2026">
      <div className={`${VISUAL} flex items-center justify-center border border-line bg-white p-2`}>
        {/* eslint-disable-next-line @next/next/no-img-element -- the official conference logo, shown as is */}
        <img src="/loghi/iswc-2026-bari.png" alt="ISWC 2026 Bari" width={640} height={486} className="h-full w-auto object-contain" />
      </div>
    </VisualLink>
  );
}

function Entry({
  meta,
  title,
  byline,
  visual,
  children,
}: {
  meta: string;
  title: string;
  byline?: string;
  visual?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <article className="flex flex-col gap-5 rounded-lg border border-line bg-surface p-5 sm:flex-row sm:gap-7 sm:p-7">
      {visual}
      <div className="min-w-0 flex-1">
        <p className="text-sm text-fg-muted">{meta}</p>
        <h3 className="serif-display mt-2 text-[clamp(1.375rem,4.5vw,1.75rem)] leading-snug text-fg">{title}</h3>
        {byline && <p className="mt-3 text-[15px] text-fg-secondary">{byline}</p>}
        {children && <div className="mt-5 flex flex-wrap gap-2.5">{children}</div>}
      </div>
    </article>
  );
}

function CiteBlock() {
  const t = useTranslations("Centro");
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(BIBTEX);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {}
  };
  return (
    <div id="cita" className="overflow-hidden rounded-lg border border-line bg-surface-muted">
      <div className="flex items-center justify-between gap-3 border-b border-line py-1 pr-1 pl-4">
        <p className="font-mono text-caption text-fg-muted">BibTeX · {t("citeLabel")}</p>
        <button
          type="button"
          onClick={copy}
          className="inline-flex h-11 items-center gap-2 rounded-full px-4 text-sm font-medium text-fg transition-colors hover:bg-surface"
        >
          {copied ? <Check className="size-4 text-brand-fg" aria-hidden /> : <Copy className="size-4" aria-hidden />}
          <span aria-live="polite">{copied ? t("copied") : t("copy")}</span>
        </button>
      </div>
      <pre className="px-4 py-4 font-mono text-[12.5px] leading-[1.7] [overflow-wrap:anywhere] whitespace-pre-wrap text-fg-secondary sm:px-5 sm:text-[13px]">
        {BIBTEX}
      </pre>
    </div>
  );
}

export default function PubblicazioniPage() {
  const t = useTranslations("Centro");
  return (
    <CentroPage>
      <PageIntro
        kicker={t("pubKicker")}
        title={t("pubsTitle")}
        lead={t("pubLead")}
        aside={
          <dl className="grid grid-cols-2 gap-x-6 border-t border-line pt-4 text-sm">
            <div>
              <dt className="text-fg-muted">{t("pubConfLabel")}</dt>
              <dd className="mt-1 font-medium text-fg">ISWC 2026 · Bari</dd>
            </div>
            <div>
              <dt className="text-fg-muted">{t("pubDatesLabel")}</dt>
              <dd className="mt-1 font-medium text-fg">{t("iswcDates")}</dd>
            </div>
          </dl>
        }
      />

      <div className="container-page pb-8">
        <Group title={t("groupPapers")}>
          <Entry meta={t("pub1Meta")} title={PAPER_IN_USE_TITLE} byline={AUTHORS} visual={<IswcBadge />}>
            <Action href={PAPER_IN_USE_PDF} primary>
              <FileText className="size-4" aria-hidden />
              PDF
            </Action>
            <Action href={PAPER_IN_USE_ARXIV}>
              arXiv
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Action>
            <Action href={ISWC_ACCEPTED}>
              {t("iswcProgram")}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Action>
            <a href="#cita" className="inline-flex h-11 items-center rounded-full px-4 text-sm font-medium text-brand-fg hover:bg-surface-muted">
              {t("cite")}
            </a>
          </Entry>
          <Entry meta={t("pub2Meta")} title={PAPER_DEMO_TITLE} byline={AUTHORS} visual={<IswcBadge />}>
            <Action href={PAPER_DEMO_PDF} primary>
              <FileText className="size-4" aria-hidden />
              PDF
            </Action>
            <Action href={ISWC_ACCEPTED}>
              {t("iswcProgram")}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Action>
          </Entry>
          <div className="mt-4">
            <h3 className="mb-3 text-[15px] font-semibold text-fg">{t("citeTitle")}</h3>
            <CiteBlock />
          </div>
        </Group>

        <Group title={t("groupTalks")}>
          <Entry
            meta={t("talkMeta")}
            title="ParliamentRAG"
            byline={t("talkPlace")}
            visual={
              <VisualLink href={MDW_EVENT} label="Milano Digital Week">
                {/* eslint-disable-next-line @next/next/no-img-element -- the official SVG file, shown as is */}
                <img src="/loghi/milano-digital-week.svg" alt="Milano Digital Week" width={432} height={267} className={`${VISUAL} block`} />
              </VisualLink>
            }
          >
            <Action href={MDW_EVENT}>
              {t("eventPage")}
              <ArrowUpRight className="size-3.5" aria-hidden />
            </Action>
          </Entry>
        </Group>
      </div>
    </CentroPage>
  );
}
