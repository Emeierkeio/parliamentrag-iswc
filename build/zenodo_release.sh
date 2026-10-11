#!/usr/bin/env bash
# Orchestratore di `make zenodo-release`: rigenera i dump RDF (voti inclusi),
# li carica su Zenodo e PUBBLICA la nuova versione, senza intervento. Pensato
# per girare di notte: tiene sveglio il Mac con caffeinate e a fine corsa
# manda una notifica.
#
# Il DOI pubblicato è permanente, quindi prima dell'upload un controllo di
# sanità confronta il nuovo export con quello vecchio: i dati crescono e basta,
# un dump più piccolo vuol dire export rotto e lo script si ferma senza
# toccare Zenodo.
#
# Ordine: dry-run Zenodo PRIMA dell'export, così un token scaduto o un account
# sbagliato fanno fallire in pochi secondi invece che dopo un'ora di export.
#
# Variabili (passate dal Makefile): BACKEND_DIR
set -u -o pipefail

cd "$(dirname "$0")/.."

: "${BACKEND_DIR:=backend}"
PY="$BACKEND_DIR/venv/bin/python"
RDF_DIR="dumps/rdf"

LOG_DIR="build/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/zenodo-release-$(date +%Y%m%d-%H%M%S).log"
: >"$LOG"

notify() {
	osascript -e "display notification \"$2\" with title \"$1\" sound name \"Glass\"" 2>/dev/null || true
}

fail() {
	echo "  ✗ $1 — log: $LOG" | tee -a "$LOG"
	notify "Zenodo release fallita" "$1"
	exit 1
}

run_step() {
	local name="$1"; shift
	local start=$SECONDS
	echo "▶ $name  ($(date +%H:%M))" | tee -a "$LOG"
	if "$@" >>"$LOG" 2>&1; then
		echo "  ✓ $name — $(( (SECONDS - start) / 60 )) min" | tee -a "$LOG"
	else
		tail -20 "$LOG"
		fail "$name fallito"
	fi
}

triples() { "$PY" -c "import json;print(json.load(open('$RDF_DIR/export_meta.json'))['triples'])" 2>/dev/null || echo 0; }
size()    { stat -f %z "$RDF_DIR/$1" 2>/dev/null || echo 0; }

echo "Log completo: $LOG"

OLD_TRIPLES=$(triples)
OLD_VOTES=$(size parliamentrag_votes.nt)

run_step "Verifica Zenodo (dry-run)"   "$PY" build/zenodo_update.py --dry-run
run_step "Export RDF con voti"         "$PY" build/export_rdf.py --votes

NEW_TRIPLES=$(triples)
NEW_VOTES=$(size parliamentrag_votes.nt)
echo "  triple KG: $OLD_TRIPLES → $NEW_TRIPLES · file voti: $OLD_VOTES → $NEW_VOTES byte" | tee -a "$LOG"
[ "$NEW_TRIPLES" -ge "$OLD_TRIPLES" ] || fail "KG più piccolo di prima ($NEW_TRIPLES < $OLD_TRIPLES): non pubblico"
[ "$NEW_VOTES" -ge "$OLD_VOTES" ]     || fail "file voti più piccolo di prima: non pubblico"

run_step "Upload e pubblicazione su Zenodo"  "$PY" build/zenodo_update.py --publish

DOI=$(grep -Eo 'DOI 10\.5281/zenodo\.[0-9]+' "$LOG" | tail -1 | cut -d' ' -f2)
echo
echo "Fatto in $(( SECONDS / 60 )) min. Pubblicato: https://doi.org/$DOI"
echo "Resta da committare la data in frontend/src/app/data/page.tsx."
notify "Zenodo pubblicato" "DOI $DOI"
