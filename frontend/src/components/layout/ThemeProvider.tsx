"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";

// Follows the device until the visitor picks a theme; the choice persists and
// next-themes applies it before first paint. data-theme matches Stenografo.
export function ThemeProvider({ children }: { children: React.ReactNode }) {
  return (
    <NextThemesProvider attribute="data-theme" defaultTheme="system" enableSystem disableTransitionOnChange>
      {children}
    </NextThemesProvider>
  );
}
