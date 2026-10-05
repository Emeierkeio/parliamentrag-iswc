"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import { useTheme } from "next-themes";
import * as Dialog from "@radix-ui/react-dialog";
import { Check, Globe, Menu, Moon, Sun, X } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { LOCALES } from "@/components/layout/LanguageSelector";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export const CENTRO_NAV = [
  { href: "/sistemi", key: "navSystems" },
  { href: "/pubblicazioni", key: "navPublications" },
  { href: "/data", key: "navData" },
  { href: "/sviluppatori", key: "navDevelopers" },
  { href: "/method", key: "navMethod" },
  { href: "/aggiornamenti", key: "navUpdates" },
] as const;

function switchLocale(next: string) {
  document.cookie = `NEXT_LOCALE=${next}; path=/; max-age=31536000; SameSite=Lax`;
  const url = new URL(window.location.href);
  if (next === "it") url.searchParams.delete("lang");
  else url.searchParams.set("lang", next);
  window.location.href = url.toString();
}

const noop = () => () => {};

function useIsDark() {
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme exists only on the client; the server renders "light".
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  const isDark = mounted && resolvedTheme === "dark";
  return { isDark, toggle: () => setTheme(isDark ? "light" : "dark") };
}

function isActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** Header of the research site: brand, six sections, theme and language. */
export function CentroBar() {
  const t = useTranslations("Centro");
  const ts = useTranslations("Sidebar");
  const locale = useLocale();
  const pathname = usePathname();
  const { isDark, toggle } = useIsDark();
  const [open, setOpen] = useState(false);
  const [openedAt, setOpenedAt] = useState(pathname);
  // Closing on navigation: the sheet records the path it was opened on.
  if (open && openedAt !== pathname) {
    setOpen(false);
  }
  const ThemeIcon = isDark ? Sun : Moon;
  const themeLabel = isDark ? ts("themeLight") : ts("themeDark");
  const current = LOCALES.find((l) => l.code === locale) ?? LOCALES[0];

  return (
    <header className="sticky top-0 z-header border-b border-line bg-bg/90 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
      <div className="container-page flex h-[var(--header-h)] items-center gap-4">
        <Link
          href="/"
          aria-label={t("homeLabel")}
          className="-ml-1 flex h-11 shrink-0 items-center rounded-md px-1 outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          <Logo size={21} animated />
        </Link>

        <nav aria-label={t("navLabel")} className="ml-auto hidden items-center lg:flex">
          {CENTRO_NAV.map((n) => {
            const active = isActive(pathname, n.href);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "inline-flex h-11 items-center rounded-full px-3 text-sm transition-colors xl:px-3.5",
                  active ? "font-medium text-fg" : "text-fg-secondary hover:bg-surface-muted hover:text-fg",
                )}
              >
                {t(n.key)}
              </Link>
            );
          })}
        </nav>

        <div className="hidden items-center gap-0.5 border-l border-line pl-3 lg:flex">
          <Popover>
            <PopoverTrigger asChild>
              <button
                type="button"
                aria-label={t("language")}
                className="inline-flex h-11 items-center gap-1.5 rounded-full px-3 font-mono text-caption uppercase tracking-[0.06em] text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
              >
                <Globe className="size-3.5" aria-hidden />
                {current.code}
              </button>
            </PopoverTrigger>
            <PopoverContent side="bottom" align="end" className="w-44 p-1.5">
              {LOCALES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  onClick={() => l.code !== locale && switchLocale(l.code)}
                  aria-pressed={l.code === locale}
                  className={cn(
                    "flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-[13px] transition-colors",
                    l.code === locale ? "bg-surface-muted font-medium text-fg" : "text-fg-secondary hover:bg-surface-muted hover:text-fg",
                  )}
                >
                  <span className="label-mono w-6">{l.code}</span>
                  <span className="flex-1 text-left">{l.label}</span>
                  {l.code === locale && <Check className="size-3.5" aria-hidden />}
                </button>
              ))}
            </PopoverContent>
          </Popover>
          <button
            type="button"
            onClick={toggle}
            aria-label={themeLabel}
            title={themeLabel}
            className="inline-flex size-11 items-center justify-center rounded-full text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
          >
            <ThemeIcon className="size-4" aria-hidden />
          </button>
        </div>

        <Dialog.Root
          open={open}
          onOpenChange={(o) => {
            setOpen(o);
            if (o) setOpenedAt(pathname);
          }}
        >
          <Dialog.Trigger asChild>
            <button
              type="button"
              aria-label={t("menuOpen")}
              className="-mr-2 ml-auto inline-flex size-11 items-center justify-center rounded-full text-fg transition-colors hover:bg-surface-muted lg:hidden"
            >
              <Menu className="size-5" aria-hidden />
            </button>
          </Dialog.Trigger>
          <Dialog.Portal>
            <Dialog.Overlay className="fixed inset-0 z-overlay bg-scrim data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:animate-in data-[state=open]:fade-in-0" />
            <Dialog.Content
              aria-describedby={undefined}
              className="fixed inset-x-0 top-0 z-dialog max-h-[100dvh] overflow-y-auto rounded-b-2xl border-b border-line bg-bg pt-[env(safe-area-inset-top)] pb-[max(1rem,env(safe-area-inset-bottom))] shadow-overlay outline-none data-[state=closed]:animate-out data-[state=closed]:slide-out-to-top data-[state=open]:animate-in data-[state=open]:slide-in-from-top motion-reduce:animate-none"
            >
              <Dialog.Title className="sr-only">{t("menuTitle")}</Dialog.Title>
              <div className="container-page flex h-[var(--header-h)] items-center justify-between">
                <Logo size={21} />
                <Dialog.Close asChild>
                  <button
                    type="button"
                    aria-label={t("menuClose")}
                    className="-mr-2 inline-flex size-11 items-center justify-center rounded-full text-fg transition-colors hover:bg-surface-muted"
                  >
                    <X className="size-5" aria-hidden />
                  </button>
                </Dialog.Close>
              </div>
              <nav aria-label={t("navLabel")} className="container-page pt-2">
                <ul className="divide-y divide-line border-y border-line">
                  <li>
                    <Link
                      href="/"
                      onClick={() => setOpen(false)}
                      aria-current={pathname === "/" ? "page" : undefined}
                      className={cn(
                        "flex min-h-14 items-center text-[17px] transition-colors",
                        pathname === "/" ? "font-semibold text-fg" : "text-fg-secondary",
                      )}
                    >
                      {t("navHome")}
                    </Link>
                  </li>
                  {CENTRO_NAV.map((n) => {
                    const active = isActive(pathname, n.href);
                    return (
                      <li key={n.href}>
                        <Link
                          href={n.href}
                          onClick={() => setOpen(false)}
                          aria-current={active ? "page" : undefined}
                          className={cn(
                            "flex min-h-14 items-center justify-between text-[17px] transition-colors",
                            active ? "font-semibold text-fg" : "text-fg-secondary",
                          )}
                        >
                          {t(n.key)}
                          {active && <span className="size-2 rounded-full bg-brand" aria-hidden />}
                        </Link>
                      </li>
                    );
                  })}
                </ul>
              </nav>
              <div className="container-page mt-5 flex flex-col gap-4">
                <button
                  type="button"
                  onClick={toggle}
                  className="flex min-h-12 w-full items-center gap-3 rounded-lg border border-line bg-surface px-4 text-[15px] text-fg"
                >
                  <ThemeIcon className="size-4 text-fg-secondary" aria-hidden />
                  {themeLabel}
                </button>
                <div role="group" aria-label={t("language")}>
                  <p className="label-mono mb-2">{t("language")}</p>
                  <div className="grid grid-cols-3 gap-2">
                    {LOCALES.map((l) => (
                      <button
                        key={l.code}
                        type="button"
                        onClick={() => l.code !== locale && switchLocale(l.code)}
                        aria-pressed={l.code === locale}
                        lang={l.code}
                        className={cn(
                          "min-h-12 rounded-lg border px-2 text-sm transition-colors",
                          l.code === locale
                            ? "border-fg bg-surface-inverse font-medium text-fg-inverse"
                            : "border-line bg-surface text-fg-secondary",
                        )}
                      >
                        {l.label}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
            </Dialog.Content>
          </Dialog.Portal>
        </Dialog.Root>
      </div>
    </header>
  );
}
