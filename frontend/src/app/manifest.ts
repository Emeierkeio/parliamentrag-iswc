import type { MetadataRoute } from "next";

export default function manifest(): MetadataRoute.Manifest {
  return {
    name: "ParliamentRAG",
    short_name: "ParliamentRAG",
    description:
      "Risposte bilanciate e verificabili sui dibattiti della Camera dei Deputati, con citazioni testuali dai resoconti stenografici.",
    id: "/",
    start_url: "/",
    scope: "/",
    display: "standalone",
    // paper-50 from tokens/ecosystem.css: Android paints its splash and the
    // first frame with these, and the launch screen takes over on the same colour
    background_color: "#f7f8f5",
    theme_color: "#f7f8f5",
    icons: [
      { src: "/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      { src: "/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
