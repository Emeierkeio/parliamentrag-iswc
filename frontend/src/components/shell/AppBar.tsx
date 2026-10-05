"use client";

import { useEffect, useState, useSyncExternalStore, type ReactNode } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowUpRight, BookOpen, Database, Github, Globe, Mail, Menu, Moon, Search, Settings, Sun } from "lucide-react";
import { Logo, Symbol } from "@/components/brand/Logo";
import { useTheme } from "next-themes";
import { useLocale } from "next-intl";
import { LOCALES } from "@/components/layout/LanguageSelector";
import { SettingsModal } from "@/components/settings/SettingsModal";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useLastUpdate, formatLastUpdateShort } from "@/hooks/use-last-update";
import { cn } from "@/lib/utils";
import { CommandPalette } from "./CommandPalette";
import { NewsletterSignup } from "@/components/feedback/NewsletterSignup";
import { fetchNewsletterEnabled } from "@/components/feedback/api";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

function switchLocale(next: string) {
  document.cookie = `NEXT_LOCALE=${next}; path=/; max-age=31536000; SameSite=Lax`;
  const url = new URL(window.location.href);
  if (next === "it") url.searchParams.delete("lang");
  else url.searchParams.set("lang", next);
  window.location.href = url.toString();
}

const noop = () => () => {};

function ThemeItem({ className }: { className: string }) {
  const t = useTranslations("Sidebar");
  const { resolvedTheme, setTheme } = useTheme();
  // The resolved theme exists only on the client; the server renders "light".
  const mounted = useSyncExternalStore(noop, () => true, () => false);
  const isDark = mounted && resolvedTheme === "dark";
  const Icon = isDark ? Sun : Moon;
  return (
    <button type="button" onClick={() => setTheme(isDark ? "light" : "dark")} className={className}>
      <Icon className="size-4" aria-hidden />
      {isDark ? t("themeLight") : t("themeDark")}
    </button>
  );
}

const NAV = [
  { href: "/timeline", key: "navAula" },
  { href: "/parlamentari", key: "navDeputies" },
  { href: "/gruppi", key: "navGroups" },
] as const;

/*
 * The one piece of chrome every app page shares, in place of the old sidebar
 * and mobile tab bar: brand, the search field that doubles as the question
 * box (and opens with Cmd/Ctrl+K anywhere), the three entity indexes, and a
 * menu for everything secondary. `actions` slots page-specific controls.
 */
export function AppBar({ actions, className }: { actions?: ReactNode; className?: string }) {
  const t = useTranslations("Shell");
  const tn = useTranslations("Newsletter");
  const locale = useLocale();
  const pathname = usePathname();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [newsletterOpen, setNewsletterOpen] = useState(false);
  const [newsletterOn, setNewsletterOn] = useState(false);
  const lastUpdate = formatLastUpdateShort(useLastUpdate());

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setPaletteOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // The menu entry exists only when the mailing list is configured, like the form itself.
  useEffect(() => {
    let alive = true;
    fetchNewsletterEnabled().then((on) => alive && setNewsletterOn(on));
    return () => {
      alive = false;
    };
  }, []);

  const menuItem =
    "flex w-full items-center gap-2.5 rounded-md px-2.5 py-2 text-left text-[13px] text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg";

  return (
    <header
      className={cn(
        "sticky top-0 z-header shrink-0 border-b border-line bg-bg/85 backdrop-blur-xl pt-[env(safe-area-inset-top)]",
        className,
      )}
    >
      <div className="mx-auto flex h-[var(--header-h)] w-full max-w-[calc(var(--container-page)+3rem)] items-center gap-2 px-4 md:gap-4 md:px-6">
        <Link
          href="/home"
          aria-label={t("home")}
          className="shrink-0 rounded-md outline-none focus-visible:outline-2 focus-visible:outline-focus"
        >
          <span className="hidden sm:inline-flex">
            <Logo size={21} animated />
          </span>
          <span className="inline-flex sm:hidden">
            <Symbol size={38} animated />
          </span>
        </Link>

        <button
          type="button"
          onClick={() => setPaletteOpen(true)}
          className="group mx-auto flex h-10 min-w-0 flex-1 items-center gap-2.5 rounded-full border border-line-strong bg-surface px-3.5 text-left text-sm text-fg-muted transition-colors hover:border-line-control md:max-w-md"
        >
          <Search className="size-4 shrink-0" aria-hidden />
          <span className="flex-1 truncate">{t("searchTrigger")}</span>
          <kbd className="hidden rounded-xs border border-line px-1.5 font-mono text-[11px] text-fg-muted md:inline">⌘K</kbd>
        </button>

        <nav className="hidden items-center gap-0.5 xl:flex" aria-label={t("menu")}>
          {NAV.map((n) => {
            const active = pathname === n.href || pathname.startsWith(`${n.href}/`);
            return (
              <Link
                key={n.href}
                href={n.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "rounded-full px-3 py-2 text-sm transition-colors",
                  active ? "bg-surface-muted text-fg" : "text-fg-secondary hover:bg-surface-muted hover:text-fg",
                )}
              >
                {t(n.key)}
              </Link>
            );
          })}
        </nav>

        {actions}

        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-label={t("menu")}
              className="inline-flex size-10 shrink-0 items-center justify-center rounded-full text-fg-secondary transition-colors hover:bg-surface-muted hover:text-fg"
            >
              <Menu className="size-[18px]" aria-hidden />
            </button>
          </PopoverTrigger>
          <PopoverContent align="end" sideOffset={8} className="w-72 p-1.5">
            <div className="flex flex-col xl:hidden">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className={menuItem}>
                  {t(n.key)}
                </Link>
              ))}
              <div className="my-1 h-px bg-line" />
            </div>
            <Link href="/method" className={menuItem}>
              <BookOpen className="size-4" aria-hidden />
              {t("method")}
            </Link>
            <Link href="/data" className={menuItem}>
              <Database className="size-4" aria-hidden />
              {t("data")}
            </Link>
            <a href="https://stenografo.it" target="_blank" rel="noopener" className={menuItem}>
              <ArrowUpRight className="size-4" aria-hidden />
              {t("stenografo")}
            </a>
            <div className="my-1 h-px bg-line" />
            <ThemeItem className={menuItem} />
            <div className="flex items-center gap-2.5 px-2.5 py-2 text-[13px] text-fg-secondary">
              <Globe className="size-4 shrink-0" aria-hidden />
              <div className="flex flex-wrap gap-1" role="group" aria-label={t("language")}>
                {LOCALES.map((l) => (
                  <button
                    key={l.code}
                    type="button"
                    onClick={() => switchLocale(l.code)}
                    aria-pressed={l.code === locale}
                    title={l.label}
                    className={cn(
                      "rounded-xs px-1.5 py-0.5 font-mono text-[11px] uppercase transition-colors",
                      l.code === locale ? "bg-surface-inverse text-fg-inverse" : "text-fg-muted hover:bg-surface-muted hover:text-fg",
                    )}
                  >
                    {l.code}
                  </button>
                ))}
              </div>
            </div>
            <button type="button" onClick={() => setSettingsOpen(true)} className={menuItem}>
              <Settings className="size-4" aria-hidden />
              {t("settings")}
            </button>
            <a href="https://github.com/Emeierkeio/ParliamentRAG" target="_blank" rel="noopener" className={menuItem}>
              <Github className="size-4" aria-hidden />
              {t("docs")}
            </a>
            {newsletterOn && (
              <button type="button" onClick={() => setNewsletterOpen(true)} className={menuItem}>
                <Mail className="size-4" aria-hidden />
                {tn("menuLabel")}
              </button>
            )}
            <div className="my-1 h-px bg-line" />
            <p className="px-2.5 pt-2 pb-1 font-mono text-[11px] text-fg-muted">{t("dataAt", { date: lastUpdate ?? "" })}</p>
          </PopoverContent>
        </Popover>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
      <SettingsModal open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      {/* The same signup block as the pages, in a dialog: the menu is too narrow for it. */}
      <Dialog open={newsletterOpen} onOpenChange={setNewsletterOpen}>
        <DialogContent className="max-h-[calc(100dvh-2rem)] overflow-y-auto border-0 bg-transparent p-0 shadow-none sm:max-w-5xl">
          <DialogTitle className="sr-only">{tn("menuLabel")}</DialogTitle>
          <NewsletterSignup source="menu" />
        </DialogContent>
      </Dialog>
    </header>
  );
}
