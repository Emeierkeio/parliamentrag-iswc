import type { ReactNode } from "react";

/*
 * The ParliamentRAG family as the shared footer shows it: one mark per site
 * (a pen stroke in the theme foreground plus a dot that never changes colour)
 * and the author's profiles. Kept identical in ParliamentRAG, fascicoli and stenografo.
 */

type MarkProps = { size?: number; className?: string };

/* Each viewBox is the mark's measured ink bounds (stroke caps and dot included,
   rasterised 2026-10-03), so every mark fills the same `size` square edge to edge
   on its longer side and the four read as one size in a list. */
function MarkSvg({ viewBox, size, className, children }: { viewBox: string; size: number; className?: string; children: ReactNode }) {
  return (
    <svg
      viewBox={viewBox}
      width={size}
      height={size}
      aria-hidden
      focusable="false"
      className={`shrink-0 overflow-visible text-fg ${className ?? ""}`}
    >
      {children}
    </svg>
  );
}

export function ParliamentragMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="15 15 194 153" size={size} className={className}>
      <path d="M 35.91 139.73 A 81 81 0 1 1 188.09 139.73" fill="none" stroke="currentColor" strokeWidth={32} strokeLinecap="round" />
      <circle cx="112" cy="146" r="22" fill="#2D5F8F" />
    </MarkSvg>
  );
}

export function StenografoMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="6 8.5 50.5 48" size={size} className={className}>
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
    <MarkSvg viewBox="-5.8 5.5 57.8 55" size={size} className={className}>
      <g transform="rotate(-30 28 32)">
        <path d="M14 14V44a14 14 0 0 0 28 0V18a7 7 0 0 0-14 0V40" fill="none" stroke="currentColor" strokeWidth={8} strokeLinecap="round" strokeLinejoin="round" />
        <circle cx="14" cy="2" r="6.6" fill="#167A68" />
      </g>
    </MarkSvg>
  );
}

export function ScrannoMark({ size = 40, className }: MarkProps) {
  return (
    <MarkSvg viewBox="14.3 8.3 36.5 45.5" size={size} className={className}>
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

export const FAMILY = [
  { id: "parliamentrag", name: "ParliamentRAG", url: "https://www.parliamentrag.it", Mark: ParliamentragMark },
  { id: "stenografo", name: "Stenografo", url: "https://www.stenografo.it", Mark: StenografoMark },
  { id: "fascicoli", name: "Fascicoli", url: "https://www.fascicoli.it", Mark: FascicoliMark },
  { id: "scranno", name: "Scranno", url: "https://www.scranno.it", Mark: ScrannoMark },
] as const;

export type FamilyId = (typeof FAMILY)[number]["id"];

export const AUTHOR = {
  name: "Mirko Tritella",
  url: "https://emeierkeio.github.io",
  links: [
    { key: "linkedin", label: "LinkedIn", url: "https://www.linkedin.com/in/mirko-tritella-4406951a3" },
    { key: "x", label: "X", url: "https://x.com/tritella_mirko" },
    { key: "github", label: "GitHub", url: "https://github.com/Emeierkeio" },
    { key: "orcid", label: "ORCID", url: "https://orcid.org/0009-0000-8611-8189" },
  ],
} as const;

export const UNIMIB_URL = "https://www.unimib.it/";
export const DATAPACT_GRANT_URL = "https://doi.org/10.3030/101189771";
export const DATAPACT_URL = "https://datapact.eu/";
export const DATA_LICENSE_URL = "https://creativecommons.org/licenses/by-sa/4.0/deed.it";
export const OPEN_DATA_URL = "https://dati.camera.it/";
