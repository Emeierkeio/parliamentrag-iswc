"use client";

import { useState, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { useLocale, useTranslations } from "next-intl";
import { BookOpenText } from "lucide-react";
import { SourceLink } from "@/components/dossier/SourceLink";
import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { formatDay } from "@/components/dossier/format";

export interface ReaderCitation {
  chunkId: string;
  speaker: string;
  date: string | null;
  verified: boolean;
}

function slug(text: string): string {
  return text
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}

function plain(children: ReactNode): string {
  if (typeof children === "string") return children;
  if (Array.isArray(children)) return children.map(plain).join("");
  return "";
}

/*
 * The generated answer in full, as a reading view over the dossier: section
 * index on the side, quotes set like the rest of the page with speaker, date
 * and verification. Quote links in the markdown point to chunk ids, not URLs.
 */
export function FullTextReader({
  answer,
  citations,
  title,
  initialOpen = false,
  triggerClassName,
}: {
  answer: string;
  citations: ReaderCitation[];
  title: string;
  initialOpen?: boolean;
  triggerClassName?: string;
}) {
  const t = useTranslations("Dossier");
  const locale = useLocale();
  const [open, setOpen] = useState(initialOpen);
  const byChunk = new Map(citations.map((c) => [c.chunkId, c]));
  // A quote renders as its own block, so punctuation right after it would
  // be left alone on a line.
  const text = answer.replace(/(\]\([^)\s]+\))\s*[.,;:](?=\s|$)/g, "$1");
  const sections = Array.from(answer.matchAll(/^## (.+)$/gm), (m) => m[1].trim());

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className={triggerClassName}>
        <BookOpenText className="size-4" aria-hidden />
        {t("fullAnswer")}
      </button>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-[min(64rem,92vw)]">
          <div className="flex items-center gap-3 border-b border-line px-5 py-4 md:px-8">
            <div className="min-w-0">
              <SheetTitle className="label-mono text-fg-muted">{t("fullAnswer")}</SheetTitle>
              <SheetDescription className="truncate text-sm text-fg">{title}</SheetDescription>
            </div>
          </div>
          <div className="grid min-h-0 flex-1 md:grid-cols-[13rem_minmax(0,1fr)]">
            <nav aria-label={t("readerIndex")} className="hidden border-r border-line p-5 md:block">
              <p className="label-mono pb-3 text-fg-muted">{t("readerIndex")}</p>
              <ol className="flex flex-col gap-1 text-sm">
                {sections.map((s) => (
                  <li key={s}>
                    <a href={`#r-${slug(s)}`} className="block rounded-md px-2 py-1.5 text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg">
                      {s}
                    </a>
                  </li>
                ))}
              </ol>
            </nav>
            <article className="min-h-0 overflow-y-auto px-5 py-8 md:px-12">
              <div className="mx-auto flex max-w-[68ch] flex-col gap-4 text-[16px] leading-[1.75] text-fg">
                <ReactMarkdown
                  components={{
                    h2: ({ children }) => (
                      <h2 id={`r-${slug(plain(children))}`} className="serif-display mt-8 scroll-mt-6 text-[1.75rem] leading-tight first:mt-0">
                        {children}
                      </h2>
                    ),
                    h3: ({ children }) => <h3 className="mt-4 text-lg font-semibold">{children}</h3>,
                    hr: () => null,
                    p: ({ children }) => <p className="text-fg">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold text-fg">{children}</strong>,
                    a: ({ href, children }) => {
                      const cited = href ? byChunk.get(href) : undefined;
                      if (href && /^https?:/.test(href)) {
                        return (
                          <a href={href} target="_blank" rel="noreferrer" className="text-brand-fg underline underline-offset-2">
                            {children}
                          </a>
                        );
                      }
                      return (
                        <span className="my-1 block border-l-2 border-brand/40 pl-4">
                          <span className="block font-serif text-[17px] italic leading-[1.55]">{children}</span>
                          {cited && (
                            <span className="mt-1 flex flex-wrap items-center gap-x-2 font-mono text-xs not-italic text-fg-muted">
                              <span>{cited.speaker}</span>
                              {cited.date && <span>· {formatDay(cited.date, locale)}</span>}
                              <SourceLink id={cited.chunkId} verified={cited.verified} />
                            </span>
                          )}
                        </span>
                      );
                    },
                  }}
                >
                  {text}
                </ReactMarkdown>
                <p className="mt-6 border-t border-line pt-4 text-caption text-fg-muted">{t("sourceNote")}</p>
              </div>
            </article>
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
