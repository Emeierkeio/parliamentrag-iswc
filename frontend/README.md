# ParliamentRAG, centro di ricerca

Il sito di www.parliamentrag.it: il centro di ricerca e i suoi sistemi (Fascicoli, Stenografo, Scranno), le pubblicazioni, il metodo e i dati aperti.

È un sito Next.js senza backend. Le uniche parti dinamiche sono due route:

- `/api/newsletter/subscribe`: iscrizione alla newsletter con doppio consenso su Brevo. L'indirizzo non viene salvato qui.
- `/api/feedback/booth`: risposte al questionario della demo ISWC 2026 (`/iswc`), salvate in Postgres.

I numeri del grafo, la data dell'ultimo aggiornamento e gli esempi della pagina `/data` stanno in `src/data/`. Si aggiornano dal sistema ParliamentRAG prima di pubblicare:

```bash
node scripts/snapshot-data.mjs
```

I dump RDF si scaricano da Zenodo (DOI 10.5281/zenodo.21560331).

Il sistema di ricerca, con la demo presentata a ISWC 2026, è nel repository [Emeierkeio/ParliamentRAG](https://github.com/Emeierkeio/ParliamentRAG) (tag `iswc2026-demo`).

## Sviluppo

```bash
npm install
cp .env.example .env.local
npm run dev
```

Variabili d'ambiente in `.env.example`. Pubblicato su Railway a ogni push su `main`.
