"use client";

import { useEffect, useState } from "react";
import graphSamples from "@/data/graph-samples.json";
import { useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, Download } from "lucide-react";
import { CentroBar } from "@/components/shell/CentroBar";
import { SiteFooter } from "@/components/shell/SiteFooter";
import { Button } from "@/components/ui/button";
import { useKgStats } from "@/hooks/use-kg-stats";
import { useLastUpdate } from "@/hooks/use-last-update";

/* Concept DOI: always resolves to the LATEST version of the dataset.
   The paper cites the version DOI (…21560332) for reproducibility. */
const ZENODO_DOI = "10.5281/zenodo.21560331";
const ZENODO_URL = `https://doi.org/${ZENODO_DOI}`;
// Date the dataset was last published to Zenodo. Rewritten by
// build/zenodo_update.py on a successful publish, NOT by make update-data:
// the archive is a frozen snapshot and lags the live graph on purpose.
const ZENODO_UPDATED = "2026-07-26";

const STATS = [
  { field: "people", key: "stPeople" },
  { field: "speeches", key: "stSpeeches" },
  { field: "sessions", key: "stSessions" },
  { field: "acts", key: "stActs" },
  { field: "votes", key: "stVotes" },
  { field: "individual_votes", key: "stIndVotes", compact: true },
  { field: "eurovoc_concepts", key: "stEurovoc" },
  { field: "triples", key: "stTriples" },
] as const;

function formatStat(value: number, locale: string, compact?: boolean) {
  return new Intl.NumberFormat(locale, {
    useGrouping: "always", // Italian CLDR skips grouping on 4-digit numbers
    ...(compact ? { notation: "compact" as const, maximumFractionDigits: 1 } : {}),
  }).format(value);
}

function formatBytes(bytes: number, locale: string) {
  const nf = new Intl.NumberFormat(locale, { maximumFractionDigits: 1 });
  return bytes >= 1e9
    ? `${nf.format(bytes / 1e9)} GB`
    : `${nf.format(Math.round(bytes / 1e6))} MB`;
}

type TurtleLine = { text: string; hl?: "uri" | "pred" | "lit" | "dim" };

function buildTurtleLines(s: GraphSample): TurtleLine[] {
  const pid = s.person.id;
  const start = s.membership_start ?? "";
  return [
    { text: "@prefix foaf: <http://xmlns.com/foaf/0.1/> .", hl: "dim" },
    { text: "@prefix ocd:  <http://dati.camera.it/ocd/> .", hl: "dim" },
    { text: "@prefix org:  <http://www.w3.org/ns/org#> .", hl: "dim" },
    { text: "@prefix pr:   <https://w3id.org/parliamentrag/ontology#> .", hl: "dim" },
    { text: "" },
    { text: `<http://dati.camera.it/ocd/persona.rdf/${pid}>`, hl: "uri" },
    { text: "    a foaf:Person, ocd:deputato ;", hl: "pred" },
    { text: `    foaf:givenName  "${s.person.first_name}" ;`, hl: "lit" },
    { text: `    foaf:familyName "${s.person.last_name}" ;`, hl: "lit" },
    { text: `    ocd:rif_mandatoCamera <…/mandatoCamera.rdf/${s.mandate ?? ""}> .` },
    { text: "" },
    { text: `<…/membership/${pid}_${s.group_slug}_${start}>`, hl: "uri" },
    { text: "    a org:Membership ;", hl: "pred" },
    { text: `    org:member       <…/persona.rdf/${pid}> ;` },
    { text: `    org:organization <…/group/${s.group_slug}> ;` },
    { text: `    pr:startDate "${start}"^^xsd:date .`, hl: "lit" },
  ];
}

// The vocab column is not translated.
const MAPPING_ROWS = [
  { n: "r1", vocab: "foaf:Person + ocd:deputato" },
  { n: "r2", vocab: "org:Organization (W3C)" },
  { n: "r3", vocab: "org:Membership" },
  { n: "r4", vocab: "skos:Concept (EuroVoc)" },
  { n: "r5", vocab: "≈ Akoma Ntoso" },
  { n: "r6", vocab: "ocd:votazione / ocd:voto" },
  { n: "r7", vocab: "PROV-O" },
] as const;

type GraphSample = {
  person: { id: string; first_name: string; last_name: string };
  group: string | null;
  group_slug: string;
  membership_start: string | null;
  mandate: string | null;
  speech: string | null;
  act: string | null;
  topic: string | null;
  vote: string | null;
};

const GRAPH_SAMPLE_FALLBACK: GraphSample = {
  person: { id: "p307394", first_name: "DAVIDE", last_name: "AIELLO" },
  group: "M5S",
  group_slug: "m5s",
  membership_start: "2022-10-18",
  mandate: "mc19_307394_20220930",
  speech: "leg19_sed2_tit00030.int00020",
  act: "aic1_00004_19",
  topic: "prestazione di servizi",
  vote: "leg19_sed43_vot_11",
};

/* Real neighbourhoods taken from the graph by scripts/snapshot-data.mjs:
   one is picked at random after hydration, so server and client markup match. */
function useGraphSample(): { sample: GraphSample; loaded: boolean } {
  const [sample, setSample] = useState<GraphSample>(GRAPH_SAMPLE_FALLBACK);
  useEffect(() => {
    const samples = graphSamples as GraphSample[];
    const pick = samples[Math.floor(Math.random() * samples.length)];
    if (pick?.person?.id) setSample({ ...GRAPH_SAMPLE_FALLBACK, ...pick, person: pick.person });
  }, []);
  return { sample, loaded: true };
}

function titleCase(name: string) {
  return name
    .toLowerCase()
    .replace(/(^|[\s'-])\p{L}/gu, (c) => c.toUpperCase());
}

type RdfFile = { filename: string; bytes: number; modified?: string; url: string };

/* The dumps are served by Zenodo (latest version of the DOI record): the site
   has no backend of its own. Sizes and date from the Zenodo record 21602327. */
const ZENODO_FILES = "https://zenodo.org/records/21602327/files";
const RDF_FILES: Record<string, RdfFile> = {
  "parliamentrag_kg.ttl": {
    filename: "parliamentrag_kg.ttl",
    bytes: 184497234,
    modified: "2026-07-26",
    url: `${ZENODO_FILES}/parliamentrag_kg.ttl?download=1`,
  },
  "parliamentrag_votes.nt": {
    filename: "parliamentrag_votes.nt",
    bytes: 4112098532,
    modified: "2026-07-26",
    url: `${ZENODO_FILES}/parliamentrag_votes.nt?download=1`,
  },
};

function useRdfManifest() {
  return { files: RDF_FILES, loaded: true };
}

export default function DataPage() {
  const t = useTranslations("DataPage");
  const tl = useTranslations("Landing");
  const locale = useLocale();
  const { files: manifest, loaded: manifestLoaded } = useRdfManifest();
  const stats = useKgStats();
  const { sample: graphSample, loaded: graphLoaded } = useGraphSample();
  const lastUpdate = useLastUpdate();
  const formatLongDate = (iso: string) =>
    new Intl.DateTimeFormat(locale, {
      day: "numeric",
      month: "long",
      year: "numeric",
    }).format(new Date(`${iso}T12:00:00`));
  // The cards offer the Zenodo archive, which lags the live graph on
  // purpose: the label must say "snapshot", not "updated", while the live
  // freshness is stated once at section level.
  const zenodoUpdatedLabel = t("archivedSnapshot", {
    date: formatLongDate(ZENODO_UPDATED),
  });
  const liveEditionLabel = tl("edition", { date: formatLongDate(lastUpdate) });
  const updatedNote = (file?: RdfFile) =>
    file?.modified
      ? t("updatedAt", {
          date: new Intl.DateTimeFormat(locale, {
            day: "numeric",
            month: "short",
            year: "numeric",
          }).format(new Date(`${file.modified}T12:00:00`)),
        })
      : undefined;

  return (
    <div className="min-h-[100dvh] bg-bg text-fg">
      <CentroBar />

      <section className="pt-14 pb-14 sm:pt-20">
        <div className="container-page grid items-center gap-12 lg:grid-cols-12 lg:gap-8">
          <div className="lg:col-span-7">
            <p className="label-mono">{t("heroKicker")}</p>
            <h1 className="mt-5 serif-display text-4xl leading-[1.06] text-fg sm:text-6xl">
              {t("heroTitle")}
            </h1>
            <p className="mt-6 max-w-prose text-lg leading-relaxed text-fg-secondary">
              {t.rich("heroSub", {
                strong: (chunks) => <span className="font-medium text-fg">{chunks}</span>,
              })}
            </p>
          </div>
          <figure
            className={`lg:col-span-5 transition-opacity duration-500 motion-reduce:transition-none ${
              graphLoaded ? "opacity-100" : "opacity-0"
            }`}
            aria-hidden={!graphLoaded}
          >
            <GraphFigure sample={graphSample} />
            <figcaption className="mt-2 text-center font-mono text-caption text-fg-muted">
              {t("heroGraphNote", { id: graphSample.person.id })}
            </figcaption>
          </figure>
        </div>
      </section>

      <section className="py-14 sm:py-16">
        <div className="container-page">
          <SectionHeading title={t("sec1Title")} />
          <dl className="mt-8 grid grid-cols-2 gap-x-6 md:grid-cols-4">
            {STATS.map((s) => (
              <div key={s.key} className="border-t border-line py-5">
                <dd className="tabular text-2xl font-semibold tracking-[var(--tracking-heading)] text-fg sm:text-3xl">
                  {formatStat(stats[s.field] ?? 0, locale, "compact" in s && s.compact)}
                </dd>
                <dt className="mt-1.5 text-sm leading-snug text-fg-muted">{t(s.key)}</dt>
              </div>
            ))}
          </dl>
          <p className="mt-4 max-w-prose text-sm leading-relaxed text-fg-muted">
            {t("sec1Note")}
          </p>
        </div>
      </section>

      <section className="py-14 sm:py-16">
        <div className="container-page">
          <SectionHeading title={t("sec2Title")} />
          <div className="mt-8 grid gap-8 md:grid-cols-3 md:gap-6">
            {(["idea1", "idea2", "idea3"] as const).map((idea) => (
              <div key={idea}>
                <h3 className="text-lg font-semibold text-fg">{t(`${idea}Title`)}</h3>
                <p className="mt-2 leading-relaxed text-fg-secondary">{t(`${idea}Body`)}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="py-14 sm:py-16">
        <div className="container-page">
          <SectionHeading title={t("sec3Title")} />
          <p className="mt-6 max-w-prose leading-relaxed text-fg-secondary">
            {t("sec3Intro", {
              name: titleCase(
                `${graphSample.person.first_name} ${graphSample.person.last_name}`
              ),
            })}
          </p>

          <div className="mt-10 grid items-start gap-10 lg:grid-cols-12 lg:gap-8">
            <figure
              className={`min-w-0 transition-opacity duration-500 motion-reduce:transition-none lg:col-span-7 ${
                graphLoaded ? "opacity-100" : "opacity-0"
              }`}
              aria-hidden={!graphLoaded}
            >
              <div className="overflow-hidden rounded-md bg-surface-muted">
                <div className="border-b border-line px-4 py-2.5 font-mono text-caption text-fg-muted">
                  parliamentrag_kg.ttl
                </div>
                <pre className="overflow-x-auto px-5 py-4 font-mono text-[12.5px] leading-[1.75]">
                  {buildTurtleLines(graphSample).map((line, i) => (
                    <code
                      key={i}
                      className={`block whitespace-pre ${
                        line.hl === "uri"
                          ? "text-brand-fg"
                          : line.hl === "lit"
                            ? "text-notice-fg"
                            : line.hl === "pred"
                              ? "text-fg"
                              : line.hl === "dim"
                                ? "text-fg-muted"
                                : "text-fg-secondary"
                      }`}
                    >
                      {line.text || " "}
                    </code>
                  ))}
                </pre>
              </div>
              <figcaption className="mt-3 font-mono text-caption text-fg-muted">
                {t("exCaption")}
              </figcaption>
            </figure>

            <ul className="space-y-6 lg:col-span-5 lg:border-l lg:border-line lg:pl-8">
              {(["ex1", "ex2", "ex3"] as const).map((ex) => (
                <li key={ex} className="text-sm leading-relaxed">
                  <p className="font-medium text-fg">{t(`${ex}Title`)}</p>
                  <p className="mt-1 text-fg-secondary">{t(`${ex}Body`)}</p>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      <section className="py-14 sm:py-16">
        <div className="container-page">
          <SectionHeading title={t("sec4Title")} />
          <p className="mt-6 max-w-prose leading-relaxed text-fg-secondary">{t("sec4Intro")}</p>

          <div className="mt-10 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-line-strong text-left">
                  <th scope="col" className="py-3 pr-6 font-medium text-fg-muted">{t("mapCol1")}</th>
                  <th scope="col" className="py-3 pr-6 font-medium text-fg-muted">{t("mapCol2")}</th>
                  <th scope="col" className="py-3 font-medium text-fg-muted">{t("mapCol3")}</th>
                </tr>
              </thead>
              <tbody>
                {MAPPING_ROWS.map((row) => (
                  <tr key={row.n} className="border-b border-line align-top">
                    <td className="py-3.5 pr-6 font-medium text-fg">{t(`${row.n}c`)}</td>
                    <td className="whitespace-nowrap py-3.5 pr-6 font-mono text-[12.5px] text-brand-fg">
                      {row.vocab}
                    </td>
                    <td className="py-3.5 leading-relaxed text-fg-secondary">{t(`${row.n}m`)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="pt-14 pb-24">
        <div className="container-page">
          <SectionHeading title={t("sec5Title")} />
          <p className="mt-6 max-w-prose leading-relaxed text-fg-secondary">{t("sec5Intro")}</p>
          <p className="mt-3 font-mono text-caption text-fg-muted">{liveEditionLabel}</p>

          <div className="mt-10 grid gap-6 md:grid-cols-2">
            <FileCard
              title={t("fileKgTitle")}
              format="Turtle"
              body={t("fileKgDesc")}
              file={manifest["parliamentrag_kg.ttl"]}
              resolved={manifestLoaded}
              fallbackSize="172 MB"
              locale={locale}
              downloadLabel={t("downloadCta")}
              readyNote={t("readyNote")}
              updatedNote={updatedNote(manifest["parliamentrag_kg.ttl"])}
              archivedNote={zenodoUpdatedLabel}
              zenodoLabel={t("zenodoCta")}
            />
            <FileCard
              title={t("fileVotesTitle")}
              format="N-Triples"
              body={t("fileVotesDesc")}
              file={manifest["parliamentrag_votes.nt"]}
              resolved={manifestLoaded}
              fallbackSize={`${formatStat(3.8, locale)} GB`}
              locale={locale}
              downloadLabel={t("downloadCta")}
              readyNote={t("readyNote")}
              updatedNote={updatedNote(manifest["parliamentrag_votes.nt"])}
              archivedNote={zenodoUpdatedLabel}
              zenodoLabel={t("zenodoCta")}
            />
          </div>

          <p className="mt-8 max-w-prose text-sm leading-relaxed text-fg-muted">
            {t("licenseNote")}{" "}
            <a
              href="https://github.com/Emeierkeio/ParliamentRAG"
              target="_blank"
              rel="noopener noreferrer"
              className="link inline-flex min-h-11 items-center gap-0.5"
            >
              GitHub
              <ArrowUpRight className="h-3 w-3 self-center" aria-hidden />
            </a>{" "}
            · {t("archiveLabel")}{" "}
            <a
              href={ZENODO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="link inline-flex min-h-11 items-center gap-0.5"
            >
              Zenodo · DOI {ZENODO_DOI}
              <ArrowUpRight className="h-3 w-3 self-center" aria-hidden />
            </a>
          </p>
        </div>
      </section>
      <SiteFooter />
    </div>
  );
}

const GRAPH_EDGES = [
  { from: "speech", to: "person", label: "pr:spokenBy", t: 0.5 },
  { from: "person", to: "group", label: "org:member", t: 0.5 },
  { from: "person", to: "act", label: "pr:primarySignatoryOf", t: 0.45 },
  { from: "person", to: "vote", label: "pr:voter", t: 0.5 },
  { from: "act", to: "topic", label: "dcterms:subject", t: 0.68 },
] as const;

function clip(text: string, max: number) {
  return text.length > max ? text.slice(0, max - 1).trimEnd() + "…" : text;
}

function GraphFigure({ sample }: { sample: GraphSample }) {
  const speechSub = (sample.speech ?? "").split("_tit")[0] || "leg19";
  const nodes = [
    { id: "person", x: 240, y: 170, r: 17, accent: true,
      label: clip(sample.person.last_name, 14), sub: `persona.rdf/${sample.person.id}` },
    { id: "speech", x: 84, y: 62, r: 11, accent: false,
      label: "Speech", sub: speechSub },
    { id: "group", x: 404, y: 76, r: 13, accent: false,
      label: clip(sample.group ?? "Gruppo", 16), sub: "gruppoParlamentare" },
    { id: "act", x: 106, y: 296, r: 11, accent: false,
      label: "Atto", sub: sample.act ?? "atto" },
    { id: "vote", x: 404, y: 268, r: 11, accent: false,
      label: "Votazione", sub: sample.vote ?? "votazione" },
    { id: "topic", x: 268, y: 344, r: 11, accent: false,
      label: "EuroVoc", sub: clip(sample.topic ?? "skos:Concept", 26) },
  ];
  const byId = Object.fromEntries(nodes.map((n) => [n.id, n]));
  return (
    <svg
      viewBox="0 0 480 400"
      className="w-full max-w-md mx-auto"
      role="img"
      aria-hidden
    >
      {GRAPH_EDGES.map((e) => {
        const a = byId[e.from];
        const b = byId[e.to];
        const mx = a.x + (b.x - a.x) * e.t;
        const my = a.y + (b.y - a.y) * e.t;
        return (
          <g key={e.label}>
            <line
              x1={a.x}
              y1={a.y}
              x2={b.x}
              y2={b.y}
              className="stroke-line-control"
              strokeWidth="1"
              strokeDasharray="3 4"
            />
            <rect
              x={mx - e.label.length * 2.7 - 4}
              y={my - 7}
              width={e.label.length * 5.4 + 8}
              height={14}
              className="fill-bg"
            />
            <text
              x={mx}
              y={my + 3}
              textAnchor="middle"
              className="fill-fg-muted font-mono"
              fontSize="9"
            >
              {e.label}
            </text>
          </g>
        );
      })}
      {nodes.map((n) => (
        <g key={n.id}>
          {"accent" in n && n.accent && (
            <circle
              cx={n.x}
              cy={n.y}
              r={n.r + 7}
              className="fill-none stroke-brand/40"
              strokeWidth="1"
            />
          )}
          <circle
            cx={n.x}
            cy={n.y}
            r={n.r}
            className={
              "accent" in n && n.accent
                ? "fill-brand-soft stroke-brand"
                : "fill-surface stroke-line-control"
            }
            strokeWidth="1.25"
          />
          <text
            x={n.x}
            y={n.y - n.r - 8}
            textAnchor="middle"
            className="fill-fg font-mono"
            fontSize="11"
            fontWeight="500"
          >
            {n.label}
          </text>
          <text
            x={n.x}
            y={n.y + n.r + 14}
            textAnchor="middle"
            className="fill-fg-muted font-mono"
            fontSize="8.5"
          >
            {n.sub}
          </text>
        </g>
      ))}
    </svg>
  );
}

function SectionHeading({ title }: { title: string }) {
  return (
    <h2 className="border-b border-line pb-3 text-2xl font-semibold tracking-[var(--tracking-heading)] text-fg sm:text-3xl">
      {title}
    </h2>
  );
}

function FileCard({
  title,
  format,
  body,
  file,
  resolved,
  fallbackSize,
  locale,
  downloadLabel,
  readyNote,
  updatedNote,
  archivedNote,
  zenodoLabel,
}: {
  title: string;
  format: string;
  body: string;
  file?: RdfFile;
  resolved: boolean;
  fallbackSize: string;
  locale: string;
  downloadLabel: string;
  readyNote: string;
  updatedNote?: string;
  archivedNote?: string;
  zenodoLabel: string;
}) {
  const size = file ? formatBytes(file.bytes, locale) : fallbackSize;
  return (
    <div className="flex flex-col rounded-lg border border-line bg-surface p-5 sm:p-6">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between sm:gap-4">
        <h3 className="text-lg font-semibold text-fg">{title}</h3>
        <span className="mt-1 font-mono sm:shrink-0 sm:text-right text-caption leading-relaxed text-fg-muted">
          {format} · {size}
          {archivedNote ? (
            <>
              <br />
              {archivedNote}
            </>
          ) : null}
        </span>
      </div>
      <p className="mt-3 flex-1 text-sm leading-relaxed text-fg-secondary">{body}</p>
      {!resolved ? (
        <div className="mt-5 h-11" aria-hidden />
      ) : file ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <Button asChild className="h-11">
            <a href={file.url} download={file.filename}>
              <Download aria-hidden />
              {downloadLabel}
            </a>
          </Button>
          <span className="font-mono text-caption text-fg-muted">
            {readyNote}
            {updatedNote ? ` · ${updatedNote}` : null}
          </span>
        </div>
      ) : (
        <div className="mt-5">
          <Button asChild className="h-11">
            <a href={ZENODO_URL} target="_blank" rel="noopener noreferrer">
              <Download aria-hidden />
              {zenodoLabel}
              <ArrowUpRight aria-hidden />
            </a>
          </Button>
        </div>
      )}
    </div>
  );
}
