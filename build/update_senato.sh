#!/usr/bin/env bash
# Aggiornamento incrementale del Senato su un DB che lo contiene già.
#
#   build/update_senato.sh <bolt uri>     (make staging-update-senato, o da update_data.sh)
#
# Il Senato non è ancora nel DB di produzione: update_data.sh chiama questo
# script solo se SENATO_NEO4J è impostato. Ogni passo è idempotente e riprende
# da dove si era fermato.
#
# dati.senato.it blocca l'IP dopo circa 400 richieste, a qualunque ritmo
# (11/10/2026): a regime un giro ne fa poche decine (sedute nuove + ultimi
# 30 giorni, ~10 per i DDL). Gli atti di controllo arrivano da aic.camera.it
# (27 pagine), non dal Senato. Exit 3 = il Senato ha cominciato a rifiutare le
# richieste: i passi verso senato.it si saltano e si recuperano al giro dopo,
# gli altri girano.
#
# Con ARCHIVE_URL (ambiente o .env) il testo e i vettori delle sedute nuove
# passano nell'archivio Postgres e poi escono dal grafo (decisione 12/10/2026,
# build/pg_archive.py). Senza, il testo resta in Neo4j come sullo staging.
set -u -o pipefail

cd "$(dirname "$0")/.."

URI="${1:?uso: build/update_senato.sh <bolt uri>}"
: "${BACKEND_DIR:=backend}"
: "${SENATO_DELAY:=4}"
PY="$BACKEND_DIR/venv/bin/python"
USER_VAL=$(grep '^NEO4J_USER=' .env | cut -d= -f2-)
PASS_VAL=$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2-)
USER_VAL="${USER_VAL:-neo4j}"
ARCHIVE_VAL="${ARCHIVE_URL:-$(grep '^ARCHIVE_URL=' .env | cut -d= -f2-)}"

rc_all=0
blocked=0
step() { # label cmd...
	local label="$1"; shift
	echo "── Senato: $label"
	"$@"
	local rc=$?
	if [ "$rc" -eq 3 ]; then
		echo "!! Senato: $label interrotto (dati.senato.it rifiuta le richieste) — riprende al prossimo giro"
		blocked=1
		rc_all=3
	elif [ "$rc" -ne 0 ]; then
		echo "!! Senato: $label fallito (rc=$rc)"
		rc_all=1
	fi
}

votes() {
	"$PY" build/senate_sparql_ingester.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" \
		--neo4j-password "$PASS_VAL" --legislature 19 --delay "$SENATO_DELAY" "$@"
}

step "resoconti nuovi, senatori, gruppi, commissioni" \
	"$PY" build/build_and_update.py update-senate --legislature 19 \
	--neo4j-uri "$URI" --neo4j-user "$USER_VAL" --neo4j-password "$PASS_VAL"
# Dopo un blocco di senato.it le altre richieste allungherebbero il blocco:
# si saltano, e i passi che non lo interrogano (aic.camera.it, collegamenti
# offline, embedding, archivio) girano comunque.
senato_step() {
	if [ "$blocked" -eq 1 ]; then echo "── Senato: $1 saltato (senato.it bloccato)"; return; fi
	step "$@"
}
senato_step "voti aggregati (sedute nuove e ultimi 30 giorni)" votes --aggregate-only
senato_step "voti individuali (votazioni che non li hanno ancora)" votes --individual-only
step "interrogazioni, mozioni, ordini del giorno (aic.camera.it)" \
	"$PY" build/download_senate_aic.py --legislature 19
step "atti di controllo e indirizzo → grafo" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_senate_aic.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
senato_step "disegni di legge e firmatari" "$PY" build/download_senate_ddl.py --legislature 19
step "collegamenti DDL ↔ firmatari, dibattiti, votazioni" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/link_senate_acts.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
# Atti di controllo e DDL appena caricati: senza i loro embedding
# l'autorevolezza li conterebbe a rilevanza neutra (0,5) su ogni tema.
step "embedding di atti e interventi nuovi" env NEO4J_URI="$URI" NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/precalculate_embeddings.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --neo4j-password "$PASS_VAL"

archive() { # load | meta | strip
	env NEO4J_PASSWORD="$PASS_VAL" "$PY" build/pg_archive.py "$1" --pg "$ARCHIVE_VAL" \
		--neo4j-uri "$URI" --neo4j-user "$USER_VAL" --assembly senato --term 19
}
if [ -n "$ARCHIVE_VAL" ]; then
	# load prende solo i chunk che hanno ancora il vettore nel grafo, strip
	# toglie solo ciò che l'archivio ha identico: se un passo prima è fallito,
	# il testo resta nel grafo e passa al giro dopo.
	step "testo e vettori → archivio Postgres" archive load
	step "oratori e gruppi riallineati nell'archivio" archive meta
	step "testo e vettori archiviati tolti dal grafo" archive strip
fi

# Link al singolo intervento su senato.it: la pagina della seduta per tutti,
# l'ancora dell'intervento dove l'indice della seduta è in cache
# (data/senate_toc, 40 pagine a giro finché non è completa).
links() {
	env NEO4J_PASSWORD="$PASS_VAL" "$PY" build/senate_speech_links.py "$@" \
		--neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
}
step "link alle sedute su senato.it" links sittings
senato_step "indici delle sedute (senato.it)" links toc --limit 40 --delay "$SENATO_DELAY"
step "link ai singoli interventi" links anchor

exit "$rc_all"
