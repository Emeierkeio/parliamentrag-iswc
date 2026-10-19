"""Scalda la cache delle risposte di Fascicoli con le domande della demo.

    python3 build/scalda_cache_fascicoli.py [domande.json] [--attendi-dati AAAA-MM-GG]

La cache ha come chiave la versione dei dati: il giro notturno la cambia e le
risposte salvate non valgono più. nightly.sh lo lancia dopo il giro notturno nei giorni della demo di ISWC
(DEMO_CACHE_GIORNI); a mano si lancia dopo ogni deploy di Fascicoli.

- Con --attendi-dati aspetta che /api/config/last-update dia quella data
  (il giro notturno ha segnato la nuova versione), poi altri 11 minuti: il
  backend rilegge la versione dei dati al massimo ogni 10 minuti
  (response_cache._DATA_VERSION_TTL_S), e una risposta salvata prima finirebbe
  sotto la versione vecchia.
- Le domande partono con le impostazioni del browser del booth: italiano,
  Camera e Senato. Lingua e camere fanno parte della chiave.
- Ogni domanda si chiede due volte: la seconda deve tornare dalla cache
  (evento «cached»), altrimenti lo script esce con codice 1.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = "https://www.fascicoli.it"
SCOPE = [{"chamber": "camera", "legislature": 19}, {"chamber": "senato", "legislature": 19}]
HEADERS = {
    "Accept-Language": "it-IT,it;q=0.9",
    "User-Agent": "fascicoli-scalda-cache",
    "Sec-Fetch-Site": "same-origin",
    "Origin": BASE,
}
ATTESA_VERSIONE_S = 11 * 60


def _get(path: str) -> dict:
    req = urllib.request.Request(BASE + path, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def attendi_dati(giorno: str, massimo_s: int = 4 * 3600) -> None:
    inizio = time.time()
    while True:
        try:
            ultimo = _get("/api/config/last-update").get("last_update")
        except Exception as e:  # il backend può essere in riavvio
            ultimo = None
            print(f"last-update non risponde: {e}", flush=True)
        if ultimo == giorno:
            break
        if time.time() - inizio > massimo_s:
            sys.exit(f"i dati non sono del {giorno} dopo {massimo_s // 60} minuti (ultimo: {ultimo})")
        time.sleep(120)
    print(f"dati del {giorno}: aspetto {ATTESA_VERSIONE_S // 60} minuti che il backend legga la nuova versione", flush=True)
    time.sleep(ATTESA_VERSIONE_S)


def chiedi(domanda: str) -> tuple[float, set[str], str | None]:
    """Pone la domanda come il sito; restituisce durata, tipi di evento, errore."""
    corpo = json.dumps({"query": domanda, "task_id": str(uuid.uuid4()), "scope": SCOPE}).encode()
    req = urllib.request.Request(
        BASE + "/api/chat", data=corpo, method="POST",
        headers={**HEADERS, "Content-Type": "application/json", "Accept": "text/event-stream"},
    )
    t0 = time.time()
    tipi: set[str] = set()
    errore = None
    try:
        r = urllib.request.urlopen(req, timeout=400)
    except Exception as e:  # HTTP 4xx/5xx, rete
        return time.time() - t0, tipi, repr(e)
    with r:
        resto = b""
        while blocco := r.read1(65536):
            resto += blocco
            while b"\n\n" in resto:
                messaggio, resto = resto.split(b"\n\n", 1)
                for riga in messaggio.decode("utf-8", "replace").splitlines():
                    if not riga.startswith("data:"):
                        continue
                    try:
                        evento = json.loads(riga[5:].strip())
                    except json.JSONDecodeError:
                        continue
                    tipi.add(evento.get("type"))
                    if evento.get("type") == "error":
                        errore = evento.get("message") or evento.get("code") or "errore"
    return time.time() - t0, tipi, errore


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("domande", nargs="?", default=str(Path(__file__).with_name("domande_demo_iswc.json")),
                   help="file JSON con la lista delle domande, testo esatto")
    p.add_argument("--attendi-dati", metavar="AAAA-MM-GG", help="aspetta i dati di questo giorno")
    a = p.parse_args(argv)

    domande = json.loads(Path(a.domande).read_text(encoding="utf-8"))
    if a.attendi_dati:
        attendi_dati(a.attendi_dati)

    falliti = 0
    for d in domande:
        durata, tipi, errore = chiedi(d)
        if errore or "error" in tipi:
            print(f"ERRORE  {d}: {errore}", flush=True)
            falliti += 1
            continue
        stato = "già in cache" if "cached" in tipi else f"calcolata in {durata:.0f} s"
        durata2, tipi2, errore2 = chiedi(d)
        if errore2 or "cached" not in tipi2:
            print(f"NO CACHE {d}: la seconda richiesta non arriva dalla cache ({errore2 or sorted(t for t in tipi2 if t)})", flush=True)
            falliti += 1
            continue
        print(f"ok  {d}  ({stato}; dalla cache in {durata2:.1f} s)", flush=True)
    print(f"{len(domande) - falliti}/{len(domande)} domande pronte", flush=True)
    return 1 if falliti else 0


if __name__ == "__main__":
    sys.exit(main())
