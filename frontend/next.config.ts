import type { NextConfig } from "next";
import createNextIntlPlugin from 'next-intl/plugin';

const nextConfig: NextConfig = {
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
      // Hand-off links from Stenografo land on the root; the question box
      // lives on /home. The query string (q, utm_*) is carried over.
      {
        source: '/',
        has: [{ type: 'query', key: 'q' }],
        destination: '/home',
        permanent: false,
      },
    ];
  },
};

const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');
export default withNextIntl(nextConfig);
