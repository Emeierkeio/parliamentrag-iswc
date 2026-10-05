// Refresh the graph figures the site shows (counts, last update, sample
// neighbourhoods for /data) from the ParliamentRAG API. The site has no
// backend: run this before a deploy to publish new figures.
//   node scripts/snapshot-data.mjs [api_base]
import { writeFile } from "node:fs/promises";

const API = process.argv[2] || process.env.PARLIAMENTRAG_API || "https://thesis-parliamentrag-production.up.railway.app";
const HEADERS = { "User-Agent": "parliamentrag-centro snapshot" };
// The RDF export is archived on Zenodo; the live API does not count triples.
const ZENODO_TRIPLES = 863834;

async function get(path) {
  const res = await fetch(`${API}${path}`, { headers: HEADERS });
  if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
  return res.json();
}

const stats = await get("/api/data/stats");
const { last_update } = await get("/api/config/last-update");

const samples = [];
const seen = new Set();
for (let i = 0; i < 80 && samples.length < 24; i++) {
  const s = await get("/api/data/graph-sample").catch(() => null);
  if (s?.person?.id && s.speech && s.act && s.vote && !seen.has(s.person.id)) {
    seen.add(s.person.id);
    samples.push(s);
  }
}

const site = { ...stats, triples: stats.triples ?? ZENODO_TRIPLES, last_update, snapshot_at: new Date().toISOString().slice(0, 10) };
await writeFile(new URL("../src/data/site-data.json", import.meta.url), JSON.stringify(site, null, 2) + "\n");
await writeFile(new URL("../src/data/graph-samples.json", import.meta.url), JSON.stringify(samples, null, 1) + "\n");
console.log(`last_update ${last_update}, ${samples.length} samples, ${stats.people} people`);
