"use client";

import { useState, useEffect } from "react";
import { useTranslations, useLocale } from "next-intl";
import { X, Globe } from "lucide-react";

const DISMISS_KEY = "translationBannerDismissed";

interface TranslationBannerProps {
  hasCitations: boolean;
}

export function TranslationBanner({ hasCitations }: TranslationBannerProps) {
  const locale = useLocale();
  const t = useTranslations("TranslationBanner");
  const [dismissed, setDismissed] = useState(true); // Start true to avoid flash

  useEffect(() => {
    setDismissed(localStorage.getItem(DISMISS_KEY) === "true");
  }, []);

  // Only show for non-Italian locale when citations exist
  if (locale === "it" || !hasCitations || dismissed) return null;

  const handleDismiss = () => {
    localStorage.setItem(DISMISS_KEY, "true");
    setDismissed(true);
  };

  return (
    <div className="flex items-center gap-2 px-4 py-2 mb-2 rounded-md bg-info-soft text-sm text-info-fg">
      <Globe className="h-4 w-4 flex-shrink-0" />
      <p className="flex-1">{t("message")}</p>
      <button
        onClick={handleDismiss}
        className="text-xs text-info-fg whitespace-nowrap underline underline-offset-2 decoration-info-fg/40 hover:decoration-info-fg"
      >
        {t("dontShowAgain")}
      </button>
      <button
        onClick={() => setDismissed(true)}
        className="inline-flex size-7 items-center justify-center rounded-full hover:bg-brand-soft-strong transition-colors"
        aria-label="Close"
      >
        <X className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
