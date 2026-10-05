"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";

export type DocSection = { id: string; title: string };

/**
 * Long-form page: the text column (about 70ch) with a sticky rail on the
 * right from lg up, holding the section index and an optional card. Below lg
 * the index folds into a disclosure above the text and the card follows it.
 */
export function DocLayout({
  header,
  sections,
  rail,
  children,
}: {
  header: ReactNode;
  sections: DocSection[];
  rail?: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("Centro");
  const links = (
    <ul className="divide-y divide-line border-y border-line lg:divide-y-0 lg:border-y-0">
      {sections.map((s) => (
        <li key={s.id}>
          <a
            href={`#${s.id}`}
            className="flex min-h-12 items-center text-[15px] text-fg-secondary transition-colors hover:text-fg lg:min-h-0 lg:py-1.5 lg:text-sm"
          >
            {s.title}
          </a>
        </li>
      ))}
    </ul>
  );

  return (
    <div className="container-page grid gap-10 pt-10 pb-16 sm:pt-16 md:pb-24 lg:grid-cols-12 lg:gap-12 lg:pt-20">
      <div className="min-w-0 lg:col-span-8">
        <div className="max-w-[70ch]">
          {header}

          <details className="group mt-8 rounded-lg border border-line bg-surface lg:hidden">
            <summary className="flex min-h-12 cursor-pointer list-none items-center justify-between px-4 text-[15px] font-medium text-fg [&::-webkit-details-marker]:hidden">
              {t("onThisPage")}
              <ChevronDown className="size-4 text-fg-muted transition-transform group-open:rotate-180" aria-hidden />
            </summary>
            <nav aria-label={t("onThisPage")} className="px-4 pb-2">
              {links}
            </nav>
          </details>
          {rail && <div className="mt-6 lg:hidden">{rail}</div>}

          <div className="mt-10 lg:mt-12">{children}</div>
        </div>
      </div>

      <aside className="hidden lg:col-span-4 lg:block">
        <div className="sticky top-[calc(var(--header-h)+2rem)] flex flex-col gap-6">
          <nav aria-label={t("onThisPage")}>
            <p className="label-mono">{t("onThisPage")}</p>
            <div className="mt-3 border-l border-line pl-4">{links}</div>
          </nav>
          {rail}
        </div>
      </aside>
    </div>
  );
}
