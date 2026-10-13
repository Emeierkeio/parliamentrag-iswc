"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";

/**
 * Syncs URL ?lang= param with the NEXT_LOCALE cookie.
 * If someone visits a shared URL with ?lang=en, this sets the cookie
 * and reloads so next-intl picks up the locale.
 */
export function UrlParamSync() {
  const searchParams = useSearchParams();

  useEffect(() => {
    const urlLang = searchParams.get("lang");
    if (!urlLang || !["it", "en"].includes(urlLang)) return;

    const currentCookie = document.cookie
      .split("; ")
      .find((c) => c.startsWith("NEXT_LOCALE="))
      ?.split("=")[1];

    if (currentCookie !== urlLang) {
      document.cookie = `NEXT_LOCALE=${urlLang}; path=/; max-age=31536000; SameSite=Lax`;
      window.location.reload();
    }
  }, [searchParams]);

  return null;
}
