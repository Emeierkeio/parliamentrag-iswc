import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';

// The operational tool moved to Fascicoli; temporary until that domain is live.
const FASCICOLI_URL = 'https://www.fascicoli.it';
const MOVED_TO_FASCICOLI = [
  '/home',
  '/chat',
  '/tema',
  '/timeline',
  '/parlamentari',
  '/gruppi',
  '/ranking',
  '/compass',
  '/search',
  '/explorer',
  '/valutazione',
];

const nextConfig: NextConfig = {
  async headers() {
    return process.env.NOINDEX === "1"
      ? [{ source: "/:path*", headers: [{ key: "X-Robots-Tag", value: "noindex, nofollow" }] }]
      : [];
  },
  output: 'standalone',
  async redirects() {
    return [
      // Canonical host: the apex domain redirects to www
      {
        source: '/:path*',
        has: [{ type: 'host', value: 'parliamentrag.it' }],
        destination: 'https://www.parliamentrag.it/:path*',
        permanent: true,
      },
      // Hand-off links from Stenografo still landing on the root belong to
      // Fascicoli now; the query string (q, utm_*) is carried over.
      {
        source: '/',
        has: [{ type: 'query', key: 'q' }],
        destination: `${FASCICOLI_URL}/home`,
        permanent: false,
      },
      // `:path*` also matches the bare route.
      ...MOVED_TO_FASCICOLI.map((route) => ({
        source: `${route}/:path*`,
        destination: `${FASCICOLI_URL}${route}/:path*`,
        permanent: false,
      })),
    ];
  },
};

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');
export default withNextIntl(nextConfig);
