import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/*
 * The three systems built on the ParliamentRAG graph. Each mark is a pen
 * stroke in ink plus one dot in the system's own colour; the stroke follows
 * the theme foreground, the dot never changes.
 */

type MarkProps = { size?: number; className?: string };

/* `size` is the rendered height: all three marks share it, so their strokes
   (8/58, 8/70, 7.5/60 of the viewBox height) look equally heavy side by side. */
function MarkSvg({ viewBox, size, className, children }: { viewBox: string; size: number; className?: string; children: ReactNode }) {
  const [, , w, h] = viewBox.split(" ").map(Number);
  return (
    <svg
      viewBox={viewBox}
      width={Math.round((size * w) / h)}
      height={size}
      aria-hidden
      focusable="false"
      className={cn("shrink-0 text-fg", className)}
    >
      {children}
    </svg>
  );
}

export function StenografoMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="3 4 56 58" size={size} className={className}>
      <path
        d="M10 42C12 23 29 16 33.5 27C37 36 24 42 27.5 49.5C31 56.5 46 52 48.5 28"
        fill="none"
        stroke="currentColor"
        strokeWidth={8}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="50" cy="15" r="6.6" fill="#167A68" />
    </MarkSvg>
  );
}

export function FascicoliMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="-6 -4 64 70" size={size} className={className}>
      <g transform="rotate(-30 28 32)">
        <path
          d="M14 14V44a14 14 0 0 0 28 0V18a7 7 0 0 0-14 0V40"
          fill="none"
          stroke="currentColor"
          strokeWidth={8}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <circle cx="14" cy="2" r="6.6" fill="#167A68" />
      </g>
    </MarkSvg>
  );
}

export function ScrannoMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="3 1 56 60" size={size} className={className}>
      <path
        d="M18 12C18 24 18 32 20 36C22 40 30 40 42 40C46 40 47 43 47 50M24 40V50"
        fill="none"
        stroke="currentColor"
        strokeWidth={7.5}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="34" cy="24" r="6.4" fill="#167A68" />
    </MarkSvg>
  );
}

export const SYSTEMS = [
  { id: "stenografo", name: "Stenografo", url: "https://www.stenografo.it", domain: "stenografo.it", Mark: StenografoMark, live: true },
  { id: "fascicoli", name: "Fascicoli", url: "https://www.fascicoli.it", domain: "fascicoli.it", Mark: FascicoliMark, live: true },
  { id: "scranno", name: "Scranno", url: "https://www.scranno.it", domain: "scranno.it", Mark: ScrannoMark, live: true },
] as const;

export type SystemId = (typeof SYSTEMS)[number]["id"];

export const PAPER_IN_USE_PDF = "https://emeierkeio.github.io/papers/who-speaks-matters-iswc2026.pdf";
export const PAPER_DEMO_PDF = "https://emeierkeio.github.io/papers/parliamentrag-demo-iswc2026.pdf";
/* Springer assigns the DOI before the volume goes online: it 404s on doi.org until the
   ISWC 2026 proceedings are published (checked 2026-10-03). Swap the button back then. */
export const PAPER_IN_USE_DOI = "https://doi.org/10.1007/978-3-032-42029-9_24";
export const PAPER_IN_USE_ARXIV = "https://arxiv.org/abs/2608.13410";
export const GITHUB_URL = "https://github.com/Emeierkeio/ParliamentRAG";
export const ZENODO_URL = "https://doi.org/10.5281/zenodo.21560331";
export const HF_URL = "https://huggingface.co/datasets/emeierkeio/parliamentrag-camera-leg19";
export const ORKG_URL = "https://orkg.org/papers/R1909763";
export const MCP_ENDPOINT = "https://mcp.parliamentrag.it/mcp";
export const MCP_README = "https://github.com/Emeierkeio/ParliamentRAG/tree/main/mcp";

export const PAPER_IN_USE_TITLE =
  "Who Speaks Matters: Authority-Aware Multi-View Retrieval-Augmented Generation over Italian Parliamentary Proceedings";
export const PAPER_DEMO_TITLE = "ParliamentRAG: An Authority-Aware Multi-View RAG System for Italian Parliamentary Proceedings";
