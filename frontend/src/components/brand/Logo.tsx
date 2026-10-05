"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/*
 * Brand lockup with Stenografo's structure (symbol, wordmark, one-line
 * descriptor) and the same wordmark type (UI sans, semibold, tight). The
 * mark is a pen stroke, as in Stenografo: the hemicycle as one thin arc
 * (radius 81, round caps) drawn left to right, then the Speaker's seat as
 * the full stop in the product accent.
 */
const ARC = "M 35.91 139.73 A 81 81 0 1 1 188.09 139.73";
const DOT = { cx: 112, cy: 146, r: 22 };
const NAME = "ParliamentRAG";
const EASE_PEN = "cubic-bezier(0.55, 0, 0.25, 1)";
const EASE_OUT = "cubic-bezier(0.16, 1, 0.3, 1)";
const SESSION_KEY = "logoDrawn";

const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms));

/* Stenotype rhythm, same generator and seed as Stenografo: chord bursts of
   1-3 letters, 35-45 ms inside a burst and 90-140 ms between, identical on
   every play. */
function stenotypeGaps(length: number, seed = 19): number[] {
  const rand = () => {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
  const gaps: number[] = [];
  let first = true;
  while (gaps.length < length) {
    const burst = Math.min(length - gaps.length, 1 + Math.floor(rand() * 3));
    for (let i = 0; i < burst; i++) {
      gaps.push(first ? 0 : i === 0 ? Math.round(90 + rand() * 50) : Math.round(35 + rand() * 10));
      first = false;
    }
  }
  return gaps;
}

function finished(a: Animation): Promise<void> {
  return a.finished.then(
    () => undefined,
    () => undefined,
  );
}

/* Hidden state before a draw. A round-capped stroke with a zero-length dash
   still paints a dot, so the arc is hidden by opacity, not by the dash. */
function arm(root: Element) {
  root.querySelectorAll<SVGElement>(".logo-arc").forEach((el) => (el.style.strokeOpacity = "0"));
  root.querySelectorAll<SVGElement | HTMLElement>(".logo-dome, .logo-char").forEach((el) => (el.style.opacity = "0"));
}

function reset(root: Element) {
  root.querySelectorAll<SVGElement | HTMLElement>(".logo-arc, .logo-dome, .logo-char").forEach((el) => {
    el.style.removeProperty("stroke-opacity");
    el.style.removeProperty("opacity");
  });
  root.querySelector("[data-caret]")?.remove();
}

/**
 * Pen stroke, then the pen lifts at the right foot, hops to the centre and
 * presses the full stop, then (with `type`) the name is printed letter by
 * letter behind a caret that blinks twice and goes.
 */
export async function drawLogo(root: Element, signal: AbortSignal, type = false): Promise<void> {
  const arc = root.querySelector<SVGPathElement>(".logo-arc");
  const dot = root.querySelector<SVGCircleElement>(".logo-dome");
  if (!arc || !dot) return;
  const running: Animation[] = [];
  signal.addEventListener("abort", () => running.forEach((a) => a.cancel()), { once: true });
  arm(root);
  if (!type) root.querySelectorAll<HTMLElement>(".logo-char").forEach((el) => el.style.removeProperty("opacity"));

  try {
    arc.style.removeProperty("stroke-opacity");
    const a = arc.animate(
      [
        { strokeDasharray: "1", strokeDashoffset: 1, strokeOpacity: 0 },
        { strokeDasharray: "1", strokeDashoffset: 0.98, strokeOpacity: 1, offset: 0.02 },
        { strokeDasharray: "1", strokeDashoffset: 0, strokeOpacity: 1 },
      ],
      { duration: 900, easing: EASE_PEN },
    );
    running.push(a);
    await finished(a);
    if (signal.aborted) return;

    dot.style.removeProperty("opacity");
    const d = dot.animate(
      [
        { offset: 0, opacity: 0.7, transform: "translate(76px, -6px) scale(0.4)", easing: "cubic-bezier(0.3, 0, 0.4, 1)" },
        { offset: 0.45, opacity: 0.55, transform: "translate(36px, -44px) scale(0.4)", easing: "cubic-bezier(0.55, 0, 0.8, 0.45)" },
        { offset: 0.68, opacity: 1, transform: "translate(0px, 0px) scale(0.45)", easing: EASE_OUT },
        { offset: 0.84, opacity: 1, transform: "translate(0px, 0px) scale(1.22, 1.1)", easing: "ease-in-out" },
        { offset: 1, opacity: 1, transform: "translate(0px, 0px) scale(1)" },
      ],
      { duration: 760 },
    );
    running.push(d);
    await finished(d);
    if (signal.aborted || !type) return;

    const word = root.querySelector<HTMLElement>(".logo-word");
    const chars = [...root.querySelectorAll<HTMLElement>(".logo-char")];
    if (!word || !chars.length) return;
    const caret = document.createElement("span");
    caret.dataset.caret = "";
    caret.setAttribute("aria-hidden", "true");
    Object.assign(caret.style, {
      position: "absolute",
      left: "0",
      top: "16%",
      height: "68%",
      width: "max(2px, 0.045em)",
      background: "var(--brand)",
      pointerEvents: "none",
    });
    word.style.position = "relative";
    word.appendChild(caret);
    const gaps = stenotypeGaps(chars.length);
    for (let i = 0; i < chars.length; i++) {
      if (gaps[i]) await sleep(gaps[i]);
      if (signal.aborted) return;
      chars[i].style.removeProperty("opacity");
      caret.style.transform = `translateX(calc(${chars[i].offsetLeft + chars[i].offsetWidth}px + 0.06em))`;
    }
    for (const on of [false, true, false, true, false]) {
      await sleep(120);
      if (signal.aborted) return;
      caret.style.opacity = on ? "1" : "0";
    }
  } finally {
    if (!signal.aborted) reset(root);
  }
}

export function Symbol({ size = 32, className, animated = false }: { size?: number; className?: string; animated?: boolean }) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    const svg = ref.current;
    if (!animated || !svg || reducedMotion()) return;
    let current: AbortController | null = null;
    const draw = () => {
      if (current) return;
      const c = new AbortController();
      current = c;
      void drawLogo(svg, c.signal).finally(() => {
        if (current === c) current = null;
      });
    };
    let first = false;
    try {
      first = !sessionStorage.getItem(SESSION_KEY);
      sessionStorage.setItem(SESSION_KEY, "1");
    } catch {}
    if (first) draw();
    const host = svg.closest("a, button") ?? svg;
    host.addEventListener("pointerenter", draw);
    host.addEventListener("focus", draw);
    return () => {
      host.removeEventListener("pointerenter", draw);
      host.removeEventListener("focus", draw);
      current?.abort();
      reset(svg);
    };
  }, [animated]);

  return (
    <svg
      ref={ref}
      aria-hidden
      focusable="false"
      viewBox="0 8 224 166"
      width={size}
      height={Math.round((size * 166) / 224)}
      className={cn("shrink-0", className)}
    >
      <path className="logo-arc" d={ARC} pathLength={1} fill="none" stroke="var(--fg)" strokeWidth={32} strokeLinecap="round" />
      <circle className="logo-dome" cx={DOT.cx} cy={DOT.cy} r={DOT.r} fill="var(--brand)" style={{ transformBox: "fill-box", transformOrigin: "center" }} />
    </svg>
  );
}

/** One span per letter so the stenotype reveal prints whole letters. */
export function Wordmark({ size = 18, className }: { size?: number; className?: string }) {
  return (
    <span
      className={cn("logo-word relative inline-block font-sans leading-[1.1] font-semibold tracking-[-0.035em] whitespace-nowrap text-fg", className)}
      style={{ fontSize: size }}
    >
      <span className="sr-only">{NAME}</span>
      <span aria-hidden>
        {[...NAME].map((c, i) => (
          <span key={i} className="logo-char">
            {c}
          </span>
        ))}
      </span>
    </span>
  );
}

export function Logo({
  size = 18,
  descriptor = false,
  animated = false,
  className,
}: {
  size?: number;
  descriptor?: boolean;
  animated?: boolean;
  className?: string;
}) {
  const t = useTranslations("Brand");
  return (
    <span className={cn("inline-flex items-center gap-2.5", className)}>
      <Symbol size={Math.round(size * (descriptor ? 2.1 : 1.9))} animated={animated} />
      <span className="flex flex-col gap-0.5">
        <Wordmark size={size} />
        {descriptor && <span className="text-caption text-fg-secondary whitespace-nowrap">{t("descriptor")}</span>}
      </span>
    </span>
  );
}

/**
 * The large closing lockup, as at the end of every Stenografo page: hidden
 * until it is at least 60% in view, then drawn in full; re-armed once it has
 * left the screen. With reduced motion it is simply shown.
 */
export function LogoReveal({ className, children }: { className?: string; children?: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = ref.current;
    if (!root || reducedMotion()) return;
    let current: AbortController | null = null;
    arm(root);
    const io = new IntersectionObserver(
      ([e]) => {
        if (!e) return;
        if (e.intersectionRatio >= 0.6 && !current) {
          const c = new AbortController();
          current = c;
          void drawLogo(root, c.signal, true);
        } else if (e.intersectionRatio < 0.1 && current) {
          current.abort();
          current = null;
          reset(root);
          arm(root);
        }
      },
      { threshold: [0, 0.1, 0.6] },
    );
    io.observe(root);
    return () => {
      io.disconnect();
      current?.abort();
      reset(root);
    };
  }, []);

  return (
    <div ref={ref} className={cn("flex justify-center", className)}>
      <span aria-hidden className="flex items-center gap-[0.22em] pb-[0.1em] text-[clamp(2.5rem,10vw,8.5rem)]">
        <Symbol size={160} className="h-[0.9em] w-auto" />
        <Wordmark size={160} className="text-[length:inherit]! leading-[1.15]!" />
      </span>
      {children}
    </div>
  );
}
