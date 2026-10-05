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
import { BackendWakeGate } from "@/components/layout/BackendWakeGate";
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

export const metadata: Metadata = {
  metadataBase: new URL("https://www.parliamentrag.it"),
  title: {
    default: "ParliamentRAG",
    template: "%s | ParliamentRAG",
  },
  description:
    "Esplora i dibattiti della Camera dei Deputati: ricerca atti, confronta posizioni politiche e visualizza il posizionamento ideologico dei gruppi parlamentari su qualsiasi tema.",
  keywords: [
    "parlamento italiano",
    "camera dei deputati",
    "dibattiti parlamentari",
    "atti parlamentari",
    "analisi politica",
    "RAG",
    "retrieval augmented generation",
    "NLP",
    "posizionamento politico",
    "compasso ideologico",
    "gruppi parlamentari",
    "interventi parlamentari",
  ],
  authors: [{ name: "Mirko Tritella" }],
  // Installed-app launch on iOS: without startup images the WebView boots on
  // a blank screen (black in dark mode). One cream splash per device size.
  // Next emits only the modern mobile-web-app-capable meta; iOS honours the
  // startup images below only with the apple- prefixed one present too
  other: {
    "apple-mobile-web-app-capable": "yes",
  },
  appleWebApp: {
    capable: true,
    title: "ParliamentRAG",
    statusBarStyle: "default",
    startupImage: [
      { url: "/splash/apple-splash-750x1334.png", media: "(device-width: 375px) and (device-height: 667px) and (-webkit-device-pixel-ratio: 2)" },
      { url: "/splash/apple-splash-828x1792.png", media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 2)" },
      { url: "/splash/apple-splash-1125x2436.png", media: "(device-width: 375px) and (device-height: 812px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1242x2688.png", media: "(device-width: 414px) and (device-height: 896px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1170x2532.png", media: "(device-width: 390px) and (device-height: 844px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1284x2778.png", media: "(device-width: 428px) and (device-height: 926px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1179x2556.png", media: "(device-width: 393px) and (device-height: 852px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1290x2796.png", media: "(device-width: 430px) and (device-height: 932px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1206x2622.png", media: "(device-width: 402px) and (device-height: 874px) and (-webkit-device-pixel-ratio: 3)" },
      { url: "/splash/apple-splash-1320x2868.png", media: "(device-width: 440px) and (device-height: 956px) and (-webkit-device-pixel-ratio: 3)" },
    ],
  },
  openGraph: {
    title: "ParliamentRAG",
    description:
      "Esplora i dibattiti della Camera dei Deputati. Ricerca atti, confronta posizioni e visualizza il posizionamento ideologico dei gruppi parlamentari.",
    siteName: "ParliamentRAG",
    url: "https://www.parliamentrag.it",
    locale: "it_IT",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "ParliamentRAG",
    description:
      "Esplora i dibattiti della Camera dei Deputati. Ricerca atti, confronta posizioni e visualizza il posizionamento ideologico dei gruppi parlamentari.",
  },
  robots: {
    index: true,
    follow: true,
  },
  icons: {
    icon: "/favicon.svg",
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
        {MAINTENANCE_MODE ? (
          <MaintenancePage />
        ) : (
          <NextIntlClientProvider messages={messages} locale={locale}>
            <SidebarStateProvider initialCollapsed={initialCollapsed}>
            <Suspense fallback={null}>
              <UrlParamSync />
            </Suspense>
            <TooltipProvider delayDuration={0}>
              <BackendWakeGate />
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
