"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useLocale, useTranslations } from "next-intl";
import { Fraunces } from "next/font/google";
import { ArrowLeft, ArrowUpRight, Download } from "lucide-react";
import { useKgStats } from "@/hooks/use-kg-stats";
import { useLastUpdate } from "@/hooks/use-last-update";

const fraunces = Fraunces({
  subsets: ["latin"],
  style: ["normal", "italic"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-display",
  display: "swap",
});

/* ── Long-term archive of the dumps (published record) ───────────
   Concept DOI: always resolves to the LATEST version of the dataset.
   The paper cites the version DOI (…21560332) for reproducibility. */
const ZENODO_DOI = "10.5281/zenodo.21560331";
const ZENODO_URL = `https://doi.org/${ZENODO_DOI}`;
// Date the dataset was last published to Zenodo. Rewritten by
// build/zenodo_update.py on a successful publish, NOT by make update-data:
// the archive is a frozen snapshot and lags the live graph on purpose.
const ZENODO_UPDATED = "2026-07-26";

/* ── Graph numbers — live from /api/data/stats, static fallback ── */
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

/* ── Real triples from the dump, for the sampled deputy ────────── */
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

/* ── Ontology alignment — vocab column is not translated ───────── */
const MAPPING_ROWS = [
  { n: "r1", vocab: "foaf:Person + ocd:deputato" },
  { n: "r2", vocab: "org:Organization (W3C)" },
  { n: "r3", vocab: "org:Membership" },
  { n: "r4", vocab: "skos:Concept — EuroVoc" },
  { n: "r5", vocab: "≈ Akoma Ntoso" },
  { n: "r6", vocab: "ocd:votazione / ocd:voto" },
  { n: "r7", vocab: "PROV-O" },
] as const;

/* ── Random real deputy for the hero figure ────────────────────── */
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

function useGraphSample(): { sample: GraphSample; loaded: boolean } {
  const [sample, setSample] = useState<GraphSample>(GRAPH_SAMPLE_FALLBACK);
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/data/graph-sample", { cache: "no-store" })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        if (data?.person?.id) {
          setSample({ ...GRAPH_SAMPLE_FALLBACK, ...data, person: data.person });
        }
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { sample, loaded };
}

function titleCase(name: string) {
  return name
    .toLowerCase()
    .replace(/(^|[\s'-])\p{L}/gu, (c) => c.toUpperCase());
}

/* ── Manifest of dumps actually present on this server ─────────── */
type RdfFile = { filename: string; bytes: number; modified?: string };

function useRdfManifest() {
  const [files, setFiles] = useState<Record<string, RdfFile>>({});
  const [loaded, setLoaded] = useState(false);
  useEffect(() => {
    let cancelled = false;
    fetch("/api/data/rdf")
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => {
        if (cancelled) return;
        const map: Record<string, RdfFile> = {};
        for (const f of (data?.files ?? []) as RdfFile[]) map[f.filename] = f;
        setFiles(map);
        setLoaded(true);
      })
      .catch(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  return { files, loaded };
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
    <div
      className={`${fraunces.variable} min-h-screen bg-primary text-primary-foreground`}
    >
      {/* ── Masthead — dark ────────────────────────────────────── */}
      <header className="border-b border-primary-foreground/20">
        <div className="max-w-6xl mx-auto px-6 flex items-center justify-between py-5">
          <Link href="/" className="flex items-center gap-3">
            <Image src="/logo.svg" alt="" width={46} height={32} />
            <span className="[font-family:var(--font-display)] text-xl sm:text-2xl font-semibold tracking-tight">
              ParliamentRAG
            </span>
          </Link>
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 text-xs text-primary-foreground/60 hover:text-primary-foreground transition-colors"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            {t("backHome")}
          </Link>
        </div>
      </header>

      {/* ── Hero ───────────────────────────────────────────────── */}
      <section className="px-6 pt-14 sm:pt-20 pb-14">
        <div className="max-w-6xl mx-auto grid lg:grid-cols-12 gap-12 lg:gap-8 items-center">
          <div className="lg:col-span-7">
            <p className="font-mono text-[11px] uppercase tracking-[0.25em] text-chart-3">
              {t("heroKicker")}
            </p>
            <h1 className="mt-5 [font-family:var(--font-display)] text-4xl sm:text-6xl font-medium tracking-tight leading-[1.06] text-balance">
              {t("heroTitle")}
            </h1>
            <p className="mt-6 text-lg leading-relaxed text-primary-foreground/70 max-w-2xl">
              {t.rich("heroSub", {
                strong: (chunks) => (
                  <span className="text-primary-foreground">{chunks}</span>
                ),
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
            <figcaption className="mt-2 text-center font-mono text-[10px] text-primary-foreground/40">
              {t("heroGraphNote", { id: graphSample.person.id })}
            </figcaption>
          </figure>
        </div>
      </section>

      {/* ── 01 · The graph in numbers ──────────────────────────── */}
      <section className="px-6 py-14 sm:py-16">
        <div className="max-w-6xl mx-auto">
          <TermRule index="01" title={t("sec1Title")} />
          <div className="mt-10 grid grid-cols-2 md:grid-cols-4 border-t border-l border-primary-foreground/15">
            {STATS.map((s) => (
              <div
                key={s.key}
                className="border-b border-r border-primary-foreground/15 p-5 sm:p-6"
              >
                <p className="font-mono text-2xl sm:text-3xl font-medium tracking-tight tabular-nums">
                  {formatStat(stats[s.field] ?? 0, locale, "compact" in s && s.compact)}
                </p>
                <p className="mt-2 text-[13px] text-primary-foreground/55 leading-snug">
                  {t(s.key)}
                </p>
              </div>
            ))}
          </div>
          <p className="mt-6 font-mono text-xs text-primary-foreground/45 max-w-2xl leading-relaxed">
            {t("sec1Note")}
          </p>
        </div>
      </section>

      {/* ── 02 · The semantic web, in three ideas ──────────────── */}
      <section className="px-6 py-14 sm:py-16">
        <div className="max-w-6xl mx-auto">
          <TermRule index="02" title={t("sec2Title")} />
          <div className="mt-10 grid md:grid-cols-3 border-t border-l border-primary-foreground/15">
            {(["idea1", "idea2", "idea3"] as const).map((idea, i) => (
              <div
                key={idea}
                className="border-b border-r border-primary-foreground/15 p-6 sm:p-7"
              >
                <p className="font-mono text-xs text-chart-3">
                  [{String.fromCharCode(97 + i)}]
                </p>
                <h3 className="mt-3 [font-family:var(--font-display)] text-xl font-medium">
                  {t(`${idea}Title`)}
                </h3>
                <p className="mt-2.5 text-sm leading-relaxed text-primary-foreground/65">
                  {t(`${idea}Body`)}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── 03 · A deputy, in triples ──────────────────────────── */}
      <section className="px-6 py-14 sm:py-16">
        <div className="max-w-6xl mx-auto">
          <TermRule index="03" title={t("sec3Title")} />
          <p className="mt-6 text-primary-foreground/65 max-w-2xl">
            {t("sec3Intro", {
              name: titleCase(
                `${graphSample.person.first_name} ${graphSample.person.last_name}`
              ),
            })}
          </p>

          <div className="mt-10 grid lg:grid-cols-12 gap-10 lg:gap-8 items-start">
            <figure
              className={`lg:col-span-7 min-w-0 transition-opacity duration-500 motion-reduce:transition-none ${
                graphLoaded ? "opacity-100" : "opacity-0"
              }`}
              aria-hidden={!graphLoaded}
            >
              <div className="border border-primary-foreground/20 bg-black/25">
                <div className="flex items-center gap-2 px-4 py-2.5 border-b border-primary-foreground/15 font-mono text-[11px] text-primary-foreground/45">
                  <span className="inline-block h-2 w-2 rounded-full bg-chart-4/70" />
                  parliamentrag_kg.ttl
                </div>
                <pre className="overflow-x-auto px-5 py-4 text-[12.5px] leading-[1.75] font-mono">
                  {buildTurtleLines(graphSample).map((line, i) => (
                    <code
                      key={i}
                      className={`block whitespace-pre ${
                        line.hl === "uri"
                          ? "text-chart-3"
                          : line.hl === "lit"
                            ? "text-chart-4"
                            : line.hl === "pred"
                              ? "text-primary-foreground/90"
                              : line.hl === "dim"
                                ? "text-primary-foreground/35"
                                : "text-primary-foreground/70"
                      }`}
                    >
                      {line.text || " "}
                    </code>
                  ))}
                </pre>
              </div>
              <figcaption className="mt-3 font-mono text-[11px] text-primary-foreground/45">
                {t("exCaption")}
              </figcaption>
            </figure>

            <div className="lg:col-span-5 lg:pl-8 lg:border-l border-primary-foreground/15 space-y-6">
              {(["ex1", "ex2", "ex3"] as const).map((ex, i) => (
                <div key={ex} className="flex gap-4">
                  <span className="font-mono text-sm text-chart-3 leading-6 select-none">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <p className="text-sm leading-relaxed">
                    <span className="font-medium">{t(`${ex}Title`)}</span>
                    <span className="text-primary-foreground/60">
                      {" "}
                      — {t(`${ex}Body`)}
                    </span>
                  </p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      {/* ── 04 · Speaking the language of official data ────────── */}
      <section className="px-6 py-14 sm:py-16">
        <div className="max-w-6xl mx-auto">
          <TermRule index="04" title={t("sec4Title")} />
          <p className="mt-6 text-primary-foreground/65 max-w-2xl">
            {t("sec4Intro")}
          </p>

          <div className="mt-10 overflow-x-auto">
            <table className="w-full min-w-[640px] text-sm">
              <thead>
                <tr className="border-b border-primary-foreground/40 text-left">
                  <th className="py-3 pr-6 font-mono font-normal text-[11px] uppercase tracking-[0.2em] text-primary-foreground/50">
                    {t("mapCol1")}
                  </th>
                  <th className="py-3 pr-6 font-mono font-normal text-[11px] uppercase tracking-[0.2em] text-primary-foreground/50">
                    {t("mapCol2")}
                  </th>
                  <th className="py-3 font-mono font-normal text-[11px] uppercase tracking-[0.2em] text-primary-foreground/50">
                    {t("mapCol3")}
                  </th>
                </tr>
              </thead>
              <tbody>
                {MAPPING_ROWS.map((row) => (
                  <tr
                    key={row.n}
                    className="border-b border-primary-foreground/15 align-top"
                  >
                    <td className="py-3.5 pr-6 font-medium">{t(`${row.n}c`)}</td>
                    <td className="py-3.5 pr-6 font-mono text-[12.5px] text-chart-3 whitespace-nowrap">
                      {row.vocab}
                    </td>
                    <td className="py-3.5 text-primary-foreground/60 leading-relaxed">
                      {t(`${row.n}m`)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>

      {/* ── 05 · Download & reuse ──────────────────────────────── */}
      <section className="px-6 pt-14 pb-24">
        <div className="max-w-6xl mx-auto">
          <TermRule index="05" title={t("sec5Title")} />
          <p className="mt-6 text-primary-foreground/65 max-w-2xl">
            {t("sec5Intro")}
          </p>
          <p className="mt-4 inline-flex items-center gap-2 font-mono text-[11px] uppercase tracking-wide text-primary-foreground/60">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-chart-4" />
            {liveEditionLabel}
          </p>

          <div className="mt-10 grid md:grid-cols-2 gap-6">
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

          <p className="mt-8 text-xs text-primary-foreground/45 max-w-3xl leading-relaxed">
            {t("licenseNote")}{" "}
            <a
              href="https://github.com/Emeierkeio/ParliamentRAG"
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex items-baseline gap-0.5 text-primary-foreground/70 border-b border-primary-foreground/30 hover:border-primary-foreground hover:text-primary-foreground transition-colors"
            >
              GitHub
              <ArrowUpRight className="h-3 w-3 self-center" />
            </a>{" "}
            · {t("archiveLabel")}{" "}
            <a
              href={ZENODO_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="group inline-flex items-baseline gap-0.5 text-primary-foreground/70 border-b border-primary-foreground/30 hover:border-primary-foreground hover:text-primary-foreground transition-colors"
            >
              Zenodo · DOI {ZENODO_DOI}
              <ArrowUpRight className="h-3 w-3 self-center" />
            </a>
          </p>
        </div>
      </section>
    </div>
  );
}

/* ── Hero graph — a random real deputy and their neighbours ────── */
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
              className="stroke-primary-foreground/25"
              strokeWidth="1"
              strokeDasharray="3 4"
            />
            <rect
              x={mx - e.label.length * 2.7 - 4}
              y={my - 7}
              width={e.label.length * 5.4 + 8}
              height={14}
              className="fill-primary"
            />
            <text
              x={mx}
              y={my + 3}
              textAnchor="middle"
              className="fill-chart-3/90 font-mono"
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
              className="fill-none stroke-chart-3/40 animate-pulse motion-reduce:animate-none"
              strokeWidth="1"
            />
          )}
          <circle
            cx={n.x}
            cy={n.y}
            r={n.r}
            className={
              "accent" in n && n.accent
                ? "fill-chart-3/15 stroke-chart-3"
                : "fill-primary stroke-primary-foreground/55"
            }
            strokeWidth="1.25"
          />
          <text
            x={n.x}
            y={n.y - n.r - 8}
            textAnchor="middle"
            className="fill-primary-foreground font-mono"
            fontSize="11"
            fontWeight="500"
          >
            {n.label}
          </text>
          <text
            x={n.x}
            y={n.y + n.r + 14}
            textAnchor="middle"
            className="fill-primary-foreground/40 font-mono"
            fontSize="8.5"
          >
            {n.sub}
          </text>
        </g>
      ))}
    </svg>
  );
}

/* ── Terminal section rule — mono index instead of roman numeral ── */
function TermRule({ index, title }: { index: string; title: string }) {
  return (
    <div className="flex items-baseline gap-4 border-b border-primary-foreground/30 pb-3">
      <span className="font-mono text-sm text-chart-3">{index} /</span>
      <h2 className="[font-family:var(--font-display)] text-2xl sm:text-3xl font-medium tracking-tight">
        {title}
      </h2>
    </div>
  );
}

/* ── File card — real download when the dump exists on the server ── */
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
    <div className="border border-primary-foreground/20 px-6 py-5 flex flex-col">
      <div className="flex items-start justify-between gap-4">
        <h3 className="[font-family:var(--font-display)] text-xl font-medium tracking-tight">
          {title}
        </h3>
        <span className="text-right font-mono text-[11px] uppercase tracking-wide text-primary-foreground/45 shrink-0 mt-2 leading-relaxed">
          {format} · {size}
          {archivedNote ? (
            <>
              <br />
              <span className="normal-case tracking-normal text-primary-foreground/40">
                {archivedNote}
              </span>
            </>
          ) : null}
        </span>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-primary-foreground/60 flex-1">
        {body}
      </p>
      {!resolved ? (
        <div className="mt-5 h-10" aria-hidden />
      ) : file ? (
        <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
          <a
            href={`/api/data/rdf/${file.filename}`}
            download={file.filename}
            className="group inline-flex items-center gap-2.5 bg-primary-foreground text-primary px-5 py-2.5 text-[13px] font-medium tracking-wide hover:bg-chart-3 transition-colors cursor-pointer"
          >
            <Download className="h-3.5 w-3.5" />
            {downloadLabel}
          </a>
          <span className="inline-flex items-center gap-2 font-mono text-[11px] text-primary-foreground/45">
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-chart-4" />
            {readyNote}
            {updatedNote ? ` · ${updatedNote}` : null}
          </span>
        </div>
      ) : (
        <div className="mt-5">
          <a
            href={ZENODO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="group inline-flex items-center gap-2.5 bg-primary-foreground text-primary px-5 py-2.5 text-[13px] font-medium tracking-wide hover:bg-chart-3 transition-colors cursor-pointer"
          >
            <Download className="h-3.5 w-3.5" />
            {zenodoLabel}
            <ArrowUpRight className="h-3.5 w-3.5" />
          </a>
        </div>
      )}
    </div>
  );
}
