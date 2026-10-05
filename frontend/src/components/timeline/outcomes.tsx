import type { CSSProperties, ReactNode } from "react";
import { Check, CircleDashed, Minus, X, type LucideIcon } from "lucide-react";

export type Outcome = "favor" | "against" | "abstain" | "absent";

/*
 * Same mapping as Stenografo (aulachiara civic/outcomes.ts): favour = filled
 * circle, against = filled square, abstain = diamond, did not vote = hollow
 * ring. Colour is never the only carrier, and none of the colours is a party
 * colour or a good/bad pair.
 */
export const OUTCOME: Record<Outcome, { icon: LucideIcon; text: string; fill: string; color: string }> = {
  favor: { icon: Check, text: "text-vote-favor", fill: "bg-vote-favor", color: "var(--vote-favor)" },
  against: { icon: X, text: "text-vote-against", fill: "bg-vote-against", color: "var(--vote-against)" },
  abstain: { icon: Minus, text: "text-vote-abstain", fill: "bg-vote-abstain", color: "var(--vote-abstain)" },
  absent: { icon: CircleDashed, text: "text-vote-absent", fill: "bg-vote-absent", color: "var(--vote-absent)" },
};

export function toOutcome(value: string | null | undefined): Outcome {
  return value === "favor" || value === "against" || value === "abstain" ? value : "absent";
}

/** Legend glyph: the same shape the hemicycle draws for that seat. */
export function OutcomeShape({
  outcome,
  size = 10,
  className,
}: {
  outcome: Outcome;
  size?: number;
  className?: string;
}) {
  const c = OUTCOME[outcome].color;
  return (
    <svg aria-hidden viewBox="0 0 12 12" width={size} height={size} className={className} focusable="false">
      {outcome === "favor" && <circle cx="6" cy="6" r="5" fill={c} />}
      {outcome === "against" && <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" fill={c} />}
      {outcome === "abstain" && <path d="M6 0.5L11.5 6L6 11.5L0.5 6Z" fill={c} />}
      {outcome === "absent" && <circle cx="6" cy="6" r="4.2" fill="none" stroke={c} strokeWidth="1.6" />}
    </svg>
  );
}

/** One seat of the hemicycle, centred on (cx, cy) with radius r. */
export function SeatShape({
  outcome,
  cx,
  cy,
  r,
  className,
  style,
  children,
}: {
  outcome: Outcome;
  cx: number;
  cy: number;
  r: number;
  className?: string;
  style?: CSSProperties;
  children?: ReactNode;
}) {
  const c = OUTCOME[outcome].color;
  const common = { className, style };
  if (outcome === "against") {
    const s = r * 1.7;
    return (
      <rect x={cx - s / 2} y={cy - s / 2} width={s} height={s} rx={r * 0.25} fill={c} {...common}>
        {children}
      </rect>
    );
  }
  if (outcome === "abstain") {
    const d = r * 1.25;
    return (
      <path d={`M${cx} ${cy - d}L${cx + d} ${cy}L${cx} ${cy + d}L${cx - d} ${cy}Z`} fill={c} {...common}>
        {children}
      </path>
    );
  }
  if (outcome === "absent") {
    return (
      <circle cx={cx} cy={cy} r={r * 0.8} fill="none" stroke={c} strokeWidth={r * 0.35} {...common}>
        {children}
      </circle>
    );
  }
  return (
    <circle cx={cx} cy={cy} r={r} fill={c} {...common}>
      {children}
    </circle>
  );
}
