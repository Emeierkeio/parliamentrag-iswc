"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

/**
 * Phone-only indicator for the paged screens (.snap-screen): one dot per
 * screen on the right edge, each a 44px tap target that scrolls to it.
 */
export function PageDots({ screens }: { screens: { id: string; label: string }[] }) {
  const t = useTranslations("Centro");
  const [active, setActive] = useState(0);
  // Hidden once the screens have scrolled away (the footer), so it never
  // sits on top of the footer links.
  const [shown, setShown] = useState(true);

  const ids = screens.map((s) => s.id).join(" ");

  useEffect(() => {
    const els = ids
      .split(" ")
      .map((id) => document.getElementById(id)).filter((el): el is HTMLElement => !!el);
    if (!els.length) return;
    const ratios = new Map<Element, number>();
    const io = new IntersectionObserver(
      (entries) => {
        for (const e of entries) {
          ratios.set(e.target, e.intersectionRatio);
          if (e.intersectionRatio >= 0.55) {
            const i = els.indexOf(e.target as HTMLElement);
            if (i >= 0) setActive(i);
          }
        }
        setShown([...ratios.values()].some((r) => r >= 0.25));
      },
      { threshold: [0, 0.25, 0.55] },
    );
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [ids]);

  const go = (id: string) => {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    document.getElementById(id)?.scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
  };

  return (
    <nav
      aria-label={t("dotsLabel")}
      className={cn(
        "fixed top-1/2 right-0 z-dock flex -translate-y-1/2 flex-col pr-[env(safe-area-inset-right)] transition-opacity duration-200 md:hidden",
        shown ? "opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      {screens.map((s, i) => (
        <button
          key={s.id}
          type="button"
          onClick={() => go(s.id)}
          aria-label={t("dotsGo", { n: i + 1, total: screens.length, label: s.label })}
          aria-current={i === active ? "step" : undefined}
          className="flex size-11 items-center justify-center"
        >
          <span
            aria-hidden
            className={cn(
              "block w-1.5 rounded-full transition-all duration-200 motion-reduce:transition-none",
              i === active ? "h-5 bg-fg" : "h-1.5 bg-fg-faint",
            )}
          />
        </button>
      ))}
    </nav>
  );
}
