import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Source_Serif_4 } from "next/font/google";
import { ThemeProvider } from "@/components/layout/ThemeProvider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NextIntlClientProvider } from 'next-intl';
import { getMessages, getLocale, getTranslations } from 'next-intl/server';
import { cookies } from 'next/headers';
import { SidebarStateProvider } from '@/components/layout/SidebarStateProvider';
import { Suspense } from "react";
import { UrlParamSync } from "@/components/layout/UrlParamSync";
import { LaunchScreen } from "@/components/brand/LaunchScreen";
import "./globals.css";

// ─── Maintenance mode ────────────────────────────────────────────────────────
// Change to true to show the maintenance page. Restart Next.js after changing. MANUTENZIONE SETTA QUI!
const MAINTENANCE_MODE = false;

async function MaintenancePage() {
  const t = await getTranslations('Maintenance');
  return (
    <div className="min-h-screen flex flex-col items-center justify-center bg-bg text-fg px-6">
      <div className="max-w-md text-center space-y-6">
        <h1 className="text-3xl font-semibold tracking-tight">{t('title')}</h1>
        <p className="text-fg-secondary text-base leading-relaxed">
          {t('description')}
        </p>
        <p className="label-mono">ParliamentRAG</p>
      </div>
    </div>
  );
}

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Display headlines and verbatim quotes only (serif-display utility); the
// optical-size axis is pinned to the text cut there, as in Stenografo.
const serif = Source_Serif_4({
  subsets: ["latin"],
  style: ["normal", "italic"],
  axes: ["opsz"],
  variable: "--font-source-serif",
  display: "swap",
});

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  viewportFit: "cover",
  // Paints the iOS/Android browser chrome (status bar area) in the page colour
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f8f5" },
    { media: "(prefers-color-scheme: dark)", color: "#0f1714" },
  ],
};

/*
 * iOS launch images (apple-touch-startup-image), portrait, light and dark by
 * system scheme. Each is the first frame of LaunchScreen at that size, written
 * by scripts/generate_splash.py, whose device list must match this one.
 */
const SPLASH_DEVICES = [
  [440, 956, 3], // 16 Pro Max, 17 Pro Max
  [430, 932, 3], // 14 Pro Max, 15 Plus / Pro Max, 16 Plus
  [428, 926, 3], // 12-13 Pro Max, 14 Plus
  [420, 912, 3], // Air
  [414, 896, 3], // XS Max, 11 Pro Max
  [414, 896, 2], // XR, 11
  [402, 874, 3], // 16 Pro, 17, 17 Pro
  [393, 852, 3], // 14 Pro, 15, 15 Pro, 16
  [390, 844, 3], // 12, 13, 14, 12-13 Pro
  [375, 812, 3], // X, XS, 11 Pro, 12-13 mini
  [375, 667, 2], // SE 2nd and 3rd gen, 8
] as const;

function startupImages() {
  return SPLASH_DEVICES.flatMap(([w, h, dpr]) =>
    (["light", "dark"] as const).map((scheme) => ({
      url: `/splash/apple-splash-${w * dpr}x${h * dpr}-${scheme}.png`,
      media: `(device-width: ${w}px) and (device-height: ${h}px) and (-webkit-device-pixel-ratio: ${dpr}) and (orientation: portrait) and (prefers-color-scheme: ${scheme})`,
    })),
  );
}

export const metadata: Metadata = {
  metadataBase: new URL("https://www.parliamentrag.it"),
  title: {
    default: "ParliamentRAG",
    template: "%s · ParliamentRAG",
  },
  description:
    "Progetto di ricerca dell'Università di Milano-Bicocca sui dati del Parlamento italiano: knowledge graph della Camera dei Deputati, retrieval che tiene conto dell'autorevolezza di chi parla, dati aperti. Casa di Stenografo, Fascicoli e Scranno.",
  keywords: [
    "parlamento italiano",
    "camera dei deputati",
    "dibattiti parlamentari",
    "atti parlamentari",
    "analisi politica",
    "RAG",
    "retrieval augmented generation",
    "NLP",
    "knowledge graph",
    "open data",
    "gruppi parlamentari",
    "interventi parlamentari",
  ],
  authors: [{ name: "Mirko Tritella" }],
  // Installed-app launch on iOS: without startup images the WebView boots on
  // a blank screen (black in dark mode). Light and dark, one per device size.
  // Next emits only the modern mobile-web-app-capable meta; iOS honours the
  // startup images below only with the apple- prefixed one present too
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
  appleWebApp: {
    capable: true,
    title: "ParliamentRAG",
    statusBarStyle: "default",
    startupImage: startupImages(),
  },
  openGraph: {
    title: "ParliamentRAG",
    description:
      "Progetto di ricerca sui dati del Parlamento italiano: knowledge graph della Camera dei Deputati, pubblicazioni, dati aperti e i sistemi Stenografo, Fascicoli e Scranno.",
    siteName: "ParliamentRAG",
    url: "https://www.parliamentrag.it",
    locale: "it_IT",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ParliamentRAG",
    description:
      "Progetto di ricerca sui dati del Parlamento italiano: knowledge graph della Camera dei Deputati, pubblicazioni, dati aperti e i sistemi Stenografo, Fascicoli e Scranno.",
  },
  // NOINDEX=1 marks a preview deployment that search engines must skip.
  robots: process.env.NOINDEX === "1" ? { index: false, follow: false } : { index: true, follow: true },
  icons: {
    icon: [{ url: "/favicon.svg?v=2", type: "image/svg+xml" }],
    apple: "/apple-icon.png",
  },
};

export default async function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  const locale = await getLocale();
  const messages = await getMessages();
  const sidebarCookie = (await cookies()).get("sidebarCollapsed")?.value;
  const initialCollapsed = sidebarCookie === undefined ? null : sidebarCookie === "true";

  return (
    <html
      lang={locale}
      className={`${geistSans.variable} ${geistMono.variable} ${serif.variable}`}
      suppressHydrationWarning
    >
      <body
        // bg-background, NOT bg-white: Safari paints the status-bar /
        // safe-area strip with the body background
        className="antialiased bg-background text-foreground"
      >
        <ThemeProvider>
        <LaunchScreen />
        {MAINTENANCE_MODE ? (
          <MaintenancePage />
        ) : (
          <NextIntlClientProvider messages={messages} locale={locale}>
            <SidebarStateProvider initialCollapsed={initialCollapsed}>
            <Suspense fallback={null}>
              <UrlParamSync />
            </Suspense>
            <TooltipProvider delayDuration={0}>
              {children}
            </TooltipProvider>
            </SidebarStateProvider>
          </NextIntlClientProvider>
        )}
        </ThemeProvider>
      </body>
    </html>
  );
}
