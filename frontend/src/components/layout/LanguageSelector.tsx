"use client";

import { useLocale, useTranslations } from 'next-intl';
import { usePathname, useSearchParams } from 'next/navigation';
import { Globe, Check } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

export const LOCALES = [
  { code: 'it', label: 'Italiano' },
  { code: 'en', label: 'English' },
  { code: 'fr', label: 'Français' },
  { code: 'de', label: 'Deutsch' },
  { code: 'es', label: 'Español' },
  { code: 'pt', label: 'Português' },
] as const;

export function LanguageSelector({ isCollapsed = false }: { isCollapsed?: boolean }) {
  const locale = useLocale();
  const t = useTranslations('LanguageSelector');
  const searchParams = useSearchParams();
  const pathname = usePathname();

  const current = LOCALES.find((l) => l.code === locale) ?? LOCALES[0];

  const switchTo = (nextLocale: string) => {
    if (nextLocale === locale) return;
    // Set cookie for next-intl server-side resolution
    document.cookie = `NEXT_LOCALE=${nextLocale}; path=/; max-age=31536000; SameSite=Lax`;
    // Keep URL param in sync for shareable links
    const params = new URLSearchParams(searchParams.toString());
    if (nextLocale === 'it') {
      params.delete('lang');
    } else {
      params.set('lang', nextLocale);
    }
    const qs = params.toString();
    // Full reload so next-intl re-renders server-side with the new locale
    window.location.href = `${pathname}${qs ? `?${qs}` : ""}`;
  };

  const trigger = (
    <Button
      variant="ghost"
      title={t('switchTo')}
      className={cn(
        "rounded-md transition-colors text-fg-secondary hover:bg-surface hover:text-fg",
        isCollapsed
          ? "w-9 h-9 justify-center px-0 mx-auto"
          : "w-full justify-start gap-2.5 h-8 mb-0.5 text-[13px]"
      )}
    >
      <Globe className="h-4 w-4 shrink-0" />
      {!isCollapsed && (
        <span className="flex-1 truncate text-left">{current.label}</span>
      )}
      {!isCollapsed && (
        <span className="label-mono">{current.code}</span>
      )}
    </Button>
  );

  return (
    <Popover>
      {isCollapsed ? (
        <Tooltip delayDuration={0}>
          <TooltipTrigger asChild>
            <PopoverTrigger asChild>{trigger}</PopoverTrigger>
          </TooltipTrigger>
          <TooltipContent side="right" sideOffset={10}>{current.label}</TooltipContent>
        </Tooltip>
      ) : (
        <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      )}
      <PopoverContent side="top" align="start" className="w-[180px] p-1.5">
        {LOCALES.map((l) => (
          <button
            key={l.code}
            onClick={() => switchTo(l.code)}
            className={cn(
              "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-[13px] transition-colors cursor-pointer",
              l.code === locale
                ? "bg-surface-muted text-fg font-medium"
                : "text-fg-secondary hover:bg-surface-muted hover:text-fg"
            )}
          >
            <span className="w-6 label-mono">{l.code}</span>
            <span className="flex-1 text-left">{l.label}</span>
            {l.code === locale && <Check className="h-3.5 w-3.5" />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
