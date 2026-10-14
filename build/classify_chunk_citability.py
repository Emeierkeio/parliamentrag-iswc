"""
classify_chunk_citability.py — index-time citability classification (PLAN_citation_quality Fase 1).

Batch-classifies every Chunk with gpt-4o-mini and writes back:
  - c.citability_score : float [0,1]
  - c.citability_class : string {substance | procedural | rhetoric | meta}
  - c.best_quote       : string (verbatim best-citable sentence, only if exact substring)
  - c.citability_v     : int (classifier version — checkpoint for selective re-runs)

Idempotent and resumable: only chunks WHERE citability_v IS NULL OR < CITABILITY_V
are processed. best_quote is accepted ONLY if it maps back to an exact substring
of c.text (whitespace-flexible match, exact raw span stored); otherwise only
score/class are kept.

Runs on the v2 DB only (PLAN_master [G]) — no backfill on the old schema.

Chunks whose text lives in the Postgres archive (Senate XIX, decision of
2026-10-12) have no c.text in Neo4j: with --archive-url (or ARCHIVE_URL) the
text is read from the archive's chunk table. Scores are still written to the
Chunk node, where the retrieval channels read them.

Usage:
    python build/classify_chunk_citability.py --dry-run
    NEO4J_URI=bolt://localhost:7692 python build/classify_chunk_citability.py --concurrency 10
    python build/classify_chunk_citability.py --limit 200   # smoke test
    ARCHIVE_URL=postgresql://... python build/classify_chunk_citability.py   # + Senato
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CITABILITY_V = 1
MODEL = "gpt-4o-mini"

# gpt-4o-mini pricing (per million tokens)
COST_INPUT_PER_M = 0.15
COST_OUTPUT_PER_M = 0.60

VALID_CLASSES = {"substance", "procedural", "rhetoric", "meta"}

SYSTEM_PROMPT = """Sei un analista parlamentare. Per ogni frammento di intervento \
alla Camera o al Senato classifica se contiene:
- "substance": una posizione politica o argomentazione di merito su un tema
- "procedural": formule procedurali, ringraziamenti, gestione d'aula, annunci di voto senza motivazione
- "rhetoric": retorica auto-celebrativa o di schieramento senza contenuto sul tema
- "meta": meta-commento sul dibattito stesso (importanza della discussione, appelli all'unità)

Assegna anche uno score di citabilità [0,1]: quanto il frammento contiene frasi \
degne di essere citate verbatim in un'analisi delle posizioni dei partiti. Usa \
TUTTA la scala, non solo gli estremi:
- 0.9-1.0: posizione netta E argomentata nel merito
- 0.6-0.8: posizione chiara ma poco argomentata, o argomentazione senza posizione netta
- 0.4-0.6: contenuto misto (merito diluito in procedura/retorica)
- 0.1-0.3: prevalentemente formule, un accenno di contenuto
- 0.0: solo procedura o retorica vuota

Estrai infine "best_quote": la singola frase (o 2 frasi consecutive) VERBATIM più \
citabile del frammento, se esiste. Criteri: autosufficiente (pronomi con referente \
chiaro nella frase stessa), sintatticamente completa, senza «…», non inizia con \
connettivi (quindi, ma, e, infatti...), esprime una posizione di merito. Copia \
ESATTAMENTE carattere per carattere DAL FRAMMENTO CON QUELL'INDICE (mai da un \
altro frammento), inclusi maiuscole e punteggiatura originali: se la frase inizia \
con un connettivo, copiala dal primo token utile SENZA cambiare la maiuscola. \
MAI scegliere come best_quote testo che l'oratore sta LEGGENDO da un documento: \
riformulazioni di impegni, testi di emendamenti/mozioni/pareri (spesso tra \
virgolette nel resoconto o introdotti da "con questa riformulazione:", "così \
riformulato", "il parere è favorevole/contrario") — è il testo del documento, \
non la posizione dell'oratore. Se nessuna frase è citabile: null.

Rispondi SOLO con JSON valido:
{"results": [{"i": <indice>, "class": "<classe>", "score": <float>, "best_quote": <string|null>}, ...]}
Un oggetto per ogni frammento, nello stesso ordine."""


SENTENCE_FINAL = (".", "!", "?", "»")


def _complete_sentence_span(chunk_text: str, start: int, end: int) -> str | None:
    """Extend [start, end) to a sentence-final boundary within chunk_text.

    Il modello spesso tronca la frase a una virgola: una best_quote monca
    fallisce poi i criteri del quote picker («sintatticamente completa»).
    Estende in avanti fino a . ! ? » (max 250 char); se il chunk finisce
    prima, arretra all'ultimo terminale dentro lo span. None se non esiste
    una frase completa di almeno 40 char.
    """
    span = chunk_text[start:end].rstrip()
    if span.endswith(SENTENCE_FINAL):
        return span
    tail = chunk_text[end : end + 250]
    for i, ch in enumerate(tail):
        if ch in SENTENCE_FINAL:
            return chunk_text[start : end + i + 1].strip()
    last = max(span.rfind(ch) for ch in SENTENCE_FINAL)
    if last >= 40:
        return span[: last + 1].strip()
    return None


def _find_verbatim_span(chunk_text: str, quote: str) -> str | None:
    """Map the model's quote back to an exact substring of chunk_text.

    Direct substring first; otherwise whitespace-flexible regex match
    (the model sometimes collapses newlines/double spaces). Returns the
    exact raw span from chunk_text, or None if no match.
    """
    if not quote or len(quote.strip()) < 20:
        return None
    quote = quote.strip().strip("«»\"'")
    pos = chunk_text.find(quote)
    if pos >= 0:
        return _complete_sentence_span(chunk_text, pos, pos + len(quote))
    tokens = quote.split()
    if len(tokens) < 4:
        return None
    # Whitespace-flexible, case-insensitive: il modello a volte cambia la
    # maiuscola iniziale (rimozione del connettivo di apertura) o collassa
    # gli spazi. Lo span restituito è comunque il testo RAW del chunk.
    pattern = r"\s+".join(re.escape(t) for t in tokens)
    m = re.search(pattern, chunk_text, re.IGNORECASE)
    if m:
        return _complete_sentence_span(chunk_text, m.start(), m.end())
    # Punctuation-tolerant: lo stenografico ha spazi prima della punteggiatura
    # («muri .») che il modello normalizza («muri.»). Match sulla sola sequenza
    # di parole, poi lo span raw viene completato al confine di frase.
    words = re.findall(r"\w+", quote)
    if len(words) < 5:
        return None
    pattern = r"\W+".join(re.escape(w) for w in words)
    m = re.search(pattern, chunk_text, re.IGNORECASE)
    if not m:
        return None
    return _complete_sentence_span(chunk_text, m.start(), m.end())


class CitabilityClassifier:
    def __init__(self, driver, openai_client, concurrency: int = 10, batch_size: int = 20,
                 archive_url: str | None = None):
        self._driver = driver
        self._archive_url = archive_url
        self._client = openai_client
        self._sem = asyncio.Semaphore(concurrency)
        self._batch_size = batch_size
        self.stats = {
            "chunks_classified": 0,
            "quotes_stored": 0,
            "quotes_rejected_non_verbatim": 0,
            "batches_failed": 0,
            "chunks_without_text": 0,
            "api_calls": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }

    # ------------------------------------------------------------------
    # Neo4j
    # ------------------------------------------------------------------

    def count_pending(self) -> int:
        with self._driver.session() as s:
            return s.run(
                "MATCH (c:Chunk) WHERE c.citability_v IS NULL OR c.citability_v < $v "
                "RETURN count(c) AS n",
                v=CITABILITY_V,
            ).single()["n"]

    def fetch_pending_page(self, page_size: int, skip_ids: set[str]) -> list[dict]:
        """Fetch a page of unclassified chunks, excluding in-run failures.

        Chunks without text in Neo4j take it from the archive; those found in
        neither are added to skip_ids and stay unclassified.
        """
        while True:
            rows = self._fetch_rows(page_size, skip_ids)
            missing = [r["id"] for r in rows if not r["text"]]
            if missing:
                archived = self._archive_texts(missing)
                for r in rows:
                    if not r["text"]:
                        r["text"] = archived.get(r["id"])
            page = [{"id": r["id"], "text": r["text"]} for r in rows if r["text"]]
            no_text = {r["id"] for r in rows if not r["text"]}
            if no_text:
                logger.warning("%d chunks without text in Neo4j or archive — skipped", len(no_text))
                self.stats["chunks_without_text"] += len(no_text)
                skip_ids.update(no_text)
            # A page made only of text-less chunks would end the run early.
            if page or not rows:
                return page

    def _fetch_rows(self, page_size: int, skip_ids: set[str]) -> list[dict]:
        text_filter = "" if self._archive_url else "AND c.text IS NOT NULL "
        with self._driver.session() as s:
            return s.run(
                "MATCH (c:Chunk) WHERE (c.citability_v IS NULL OR c.citability_v < $v) "
                + text_filter
                + "AND NOT c.id IN $skip "
                "RETURN c.id AS id, c.text AS text LIMIT $n",
                v=CITABILITY_V,
                skip=list(skip_ids),
                n=page_size,
            ).data()

    def _archive_texts(self, ids: list[str]) -> dict[str, str]:
        import psycopg

        with psycopg.connect(self._archive_url, connect_timeout=10) as conn:
            return dict(conn.execute(
                "SELECT id, text FROM chunk WHERE id = ANY(%s)", [ids]).fetchall())

    def write_batch(self, records: list[dict]) -> None:
        # execute_write retries transient errors (deadlocks with the nightly
        # job, which strips text from the same Chunk nodes).
        with self._driver.session() as s:
            s.execute_write(lambda tx: tx.run(
                """
                UNWIND $records AS rec
                MATCH (c:Chunk {id: rec.id})
                SET c.citability_score = rec.score,
                    c.citability_class = rec.class,
                    c.citability_v = $v
                FOREACH (_ IN CASE WHEN rec.best_quote IS NULL THEN [] ELSE [1] END |
                    SET c.best_quote = rec.best_quote)
                """,
                records=records,
                v=CITABILITY_V,
            ).consume())

    # ------------------------------------------------------------------
    # OpenAI
    # ------------------------------------------------------------------

    async def classify_batch(self, chunks: list[dict]) -> list[dict] | None:
        """One LLM call for a batch of chunks. Returns write-ready records or None."""
        fragments = "\n\n".join(
            f"=== FRAMMENTO [{i}] ===\n{c['text'][:2500]}" for i, c in enumerate(chunks)
        )
        async with self._sem:
            for attempt in range(2):
                try:
                    response = await self._client.chat.completions.create(
                        model=MODEL,
                        messages=[
                            {"role": "system", "content": SYSTEM_PROMPT},
                            {"role": "user", "content": f"FRAMMENTI:\n\n{fragments}"},
                        ],
                        temperature=0.0,
                        response_format={"type": "json_object"},
                        timeout=120.0,
                    )
                    self.stats["api_calls"] += 1
                    usage = response.usage
                    if usage:
                        self.stats["input_tokens"] += usage.prompt_tokens
                        self.stats["output_tokens"] += usage.completion_tokens
                    payload = json.loads(response.choices[0].message.content or "{}")
                    results = payload.get("results", [])
                    return self._validate(chunks, results)
                except Exception as exc:
                    if attempt == 0:
                        logger.warning("Batch failed (retrying): %s", exc)
                        await asyncio.sleep(2)
                    else:
                        logger.error("Batch failed permanently: %s", exc)
                        self.stats["batches_failed"] += 1
        return None

    def _validate(self, chunks: list[dict], results: list[dict]) -> list[dict] | None:
        """Accept every valid per-index result; invalid/missing indices stay
        unclassified (citability_v assente) and get retried on the next run.
        All-or-nothing rejection looped forever on batches where the model
        stably returned 19/20 results (observed on sed73 int00140)."""
        by_index = {}
        for r in results:
            try:
                by_index[int(r.get("i"))] = r
            except (TypeError, ValueError):
                continue
        records = []
        for i, chunk in enumerate(chunks):
            r = by_index.get(i)
            if r is None:
                logger.warning("Missing result for index %d (%s) — skipped", i, chunk["id"])
                continue
            cls = str(r.get("class", "")).lower().strip()
            if cls not in VALID_CLASSES:
                logger.warning("Invalid class %r for %s — skipped", cls, chunk["id"])
                continue
            try:
                score = max(0.0, min(1.0, float(r.get("score", 0.0))))
            except (TypeError, ValueError):
                continue
            quote = r.get("best_quote")
            verbatim = _find_verbatim_span(chunk["text"], quote) if quote else None
            if quote and not verbatim:
                self.stats["quotes_rejected_non_verbatim"] += 1
            if verbatim:
                self.stats["quotes_stored"] += 1
            records.append(
                {
                    "id": chunk["id"],
                    "score": score,
                    "class": cls,
                    "best_quote": verbatim,
                }
            )
        return records

    # ------------------------------------------------------------------
    # Orchestration
    # ------------------------------------------------------------------

    async def run(self, limit: int | None = None) -> dict:
        start = time.time()
        pending_total = self.count_pending()
        target = min(pending_total, limit) if limit else pending_total
        logger.info("Pending chunks: %d (processing %d)", pending_total, target)

        try:
            from tqdm import tqdm
            pbar = tqdm(total=target, unit="chunk")
        except ImportError:
            pbar = None

        failed_ids: set[str] = set()
        processed = 0
        # page = enough chunks to feed all workers a few rounds
        page_size = self._batch_size * 50

        while processed < target:
            page = self.fetch_pending_page(
                min(page_size, target - processed), failed_ids
            )
            if not page:
                break
            batches = [
                page[i : i + self._batch_size]
                for i in range(0, len(page), self._batch_size)
            ]
            results = await asyncio.gather(
                *(self.classify_batch(b) for b in batches)
            )
            for batch, records in zip(batches, results):
                if records is None:
                    failed_ids.update(c["id"] for c in batch)
                    continue
                # I chunk saltati dal modello (indice mancante/invalido) vanno
                # esclusi dal resto del run — altrimenti la fetch li ripropone
                # all'infinito. Restano senza citability_v: riprendibili.
                written_ids = {r["id"] for r in records}
                failed_ids.update(c["id"] for c in batch if c["id"] not in written_ids)
                if records:
                    self.write_batch(records)
                    self.stats["chunks_classified"] += len(records)
                processed += len(batch)
                if pbar:
                    pbar.update(len(batch))
            if all(r is None for r in results):
                logger.error("Entire page failed — aborting to avoid burn")
                break

        if pbar:
            pbar.close()
        self.stats["elapsed_seconds"] = time.time() - start
        self.stats["failed_chunk_ids"] = len(failed_ids)
        self.stats["cost_usd"] = (
            self.stats["input_tokens"] / 1e6 * COST_INPUT_PER_M
            + self.stats["output_tokens"] / 1e6 * COST_OUTPUT_PER_M
        )
        return self.stats

    def dry_run(self) -> None:
        pending = self.count_pending()
        with self._driver.session() as s:
            avg_len = s.run(
                "MATCH (c:Chunk) WHERE (c.citability_v IS NULL OR c.citability_v < $v) "
                "AND c.text IS NOT NULL RETURN avg(size(c.text)) AS a",
                v=CITABILITY_V,
            ).single()["a"] or 0
        # input: chunk text + prompt overhead; output: ~60 tokens per chunk
        est_input = pending * (avg_len / 4 + 40) + (pending / self._batch_size) * 450
        est_output = pending * 60
        cost = est_input / 1e6 * COST_INPUT_PER_M + est_output / 1e6 * COST_OUTPUT_PER_M
        print(f"\nDRY RUN — no data written\n{'=' * 50}")
        print(f"Pending chunks   : {pending:,} (avg {avg_len:.0f} chars)")
        print(f"API calls        : ~{pending // self._batch_size:,} (batch={self._batch_size})")
        print(f"Estimated tokens : {est_input:,.0f} in + {est_output:,.0f} out")
        print(f"Estimated cost   : ${cost:.2f} ({MODEL})")
        print(f"{'=' * 50}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Classify chunk citability (index-time)")
    parser.add_argument("--neo4j-uri", default=os.environ.get("NEO4J_URI", "bolt://localhost:7692"))
    parser.add_argument("--neo4j-user", default=os.environ.get("NEO4J_USER", "neo4j"))
    parser.add_argument("--neo4j-password", default=os.environ.get("NEO4J_PASSWORD", ""))
    parser.add_argument("--dry-run", action="store_true", help="Estimate cost without writing")
    parser.add_argument("--concurrency", type=int, default=10, help="Max parallel OpenAI calls")
    parser.add_argument("--batch-size", type=int, default=20, help="Chunks per LLM call")
    parser.add_argument("--limit", type=int, default=None, help="Max chunks to process (smoke test)")
    parser.add_argument("--archive-url", default=os.environ.get("ARCHIVE_URL") or None,
                        help="Postgres archive with the text of archived chunks (Senate XIX)")
    args = parser.parse_args()

    try:
        from neo4j import GraphDatabase
    except ImportError:
        print("Error: neo4j package not installed", file=sys.stderr)
        sys.exit(1)
    try:
        from openai import AsyncOpenAI
    except ImportError:
        print("Error: openai package not installed", file=sys.stderr)
        sys.exit(1)

    driver = GraphDatabase.driver(args.neo4j_uri, auth=(args.neo4j_user, args.neo4j_password))

    openai_api_key = os.environ.get("OPENAI_API_KEY")
    if not openai_api_key and not args.dry_run:
        print("Error: OPENAI_API_KEY not set", file=sys.stderr)
        driver.close()
        sys.exit(1)
    client = AsyncOpenAI(api_key=openai_api_key, max_retries=3)

    classifier = CitabilityClassifier(
        driver, client, concurrency=args.concurrency, batch_size=args.batch_size,
        archive_url=args.archive_url,
    )
    try:
        if args.dry_run:
            classifier.dry_run()
        else:
            stats = asyncio.run(classifier.run(limit=args.limit))
            print(
                f"\nCitability classification complete\n"
                f"  Chunks classified   : {stats['chunks_classified']:,}\n"
                f"  Quotes stored       : {stats['quotes_stored']:,}\n"
                f"  Quotes non-verbatim : {stats['quotes_rejected_non_verbatim']:,}\n"
                f"  Without text        : {stats['chunks_without_text']:,}\n"
                f"  Failed batches      : {stats['batches_failed']} ({stats['failed_chunk_ids']} chunks, re-run to retry)\n"
                f"  API calls           : {stats['api_calls']:,}\n"
                f"  Tokens              : {stats['input_tokens']:,} in / {stats['output_tokens']:,} out\n"
                f"  Cost                : ${stats['cost_usd']:.2f}\n"
                f"  Elapsed             : {stats['elapsed_seconds']:.0f}s\n"
            )
    finally:
        driver.close()


if __name__ == "__main__":
    main()
