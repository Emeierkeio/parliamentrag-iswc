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
# 30 giorni, ~10 per i DDL). Gli atti di controllo arrivano dallo SPARQL della
# Camera (ramo Senato, ~27 query), esito e link da una query a dati.senato.it.
# Exit 3 = il Senato ha cominciato a rifiutare le richieste: i passi verso
# senato.it si saltano e si recuperano al giro dopo, gli altri girano.
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
# si saltano, e i passi che non lo interrogano (SPARQL Camera, collegamenti
# offline, embedding, archivio) girano comunque.
senato_step() {
	if [ "$blocked" -eq 1 ]; then echo "── Senato: $1 saltato (senato.it bloccato)"; return; fi
	step "$@"
}
# Componenti del Gruppo Misto (AVS, Azione, Avanti PSI): una pagina di
# senato.it. Senza, i senatori del Misto finirebbero sotto il «Misto» intero.
senato_step "componenti del Gruppo Misto (senato.it)" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_misto_senato.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL"
# Presidenti, vice, segretari e tesorieri dei gruppi: una richiesta a
# dati.senato.it, role sulla MEMBER_OF_GROUP aperta come per la Camera.
senato_step "cariche nei gruppi (dati.senato.it)" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_group_offices.py --chamber senato --neo4j-uri "$URI" --neo4j-user "$USER_VAL"
senato_step "voti aggregati (sedute nuove e ultimi 30 giorni)" votes --aggregate-only
senato_step "voti individuali (votazioni che non li hanno ancora)" votes --individual-only
senato_step "motivo dell'assenza (votazioni caricate prima: missione, presente non votante)" votes --reasons-only
# Offline: i senatori in carica che la fonte non nomina in una votazione.
step "assenti nelle votazioni" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/senate_absent.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
step "interrogazioni, mozioni, ordini del giorno (SPARQL Camera)" \
	"$PY" build/download_senate_aic.py --legislature 19
# Senza questo passo l'ingest tiene l'esito e il link dell'ultimo giro.
senato_step "esito e link degli atti di controllo (dati.senato.it)" \
	"$PY" build/download_senate_aic.py --legislature 19 --source senato
step "atti di controllo e indirizzo → grafo" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_senate_aic.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
senato_step "disegni di legge e firmatari" "$PY" build/download_senate_ddl.py --legislature 19
step "collegamenti DDL ↔ firmatari, dibattiti, votazioni" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/link_senate_acts.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
# Le riprese e i dibattiti sui ddl che l'Akoma Ntoso non collega: il numero
# dal titolo («n. 180-1041», «(274)»). Senza rete, prima dei relatori.
step "dibattiti ripresi → ddl" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/link_resumed_debates.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato
# Documenti (Doc.): quattro query a dati.senato.it (copia in data/), poi i
# nodi, i dibattiti dal titolo e dall'Akoma Ntoso, i voti da osr:relativoA.
# Dopo i collegamenti dei ddl: un voto su un ddl resta al ddl. Con senato.it
# bloccato gira sulla copia; prima dei relatori dai resoconti.
docs_download="--download"
if [ "$blocked" -eq 1 ]; then docs_download=""; fi
step "documenti (Doc.)" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_documents.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato $docs_download
# Relatori dei ddl (una query a dati.senato.it, copia in data/).
senato_step "relatori dei ddl (dati.senato.it)" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_reporters.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato
# Commissioni dei ddl, di merito e consultive (una query per anno a
# dati.senato.it, copia in data/): solo gli archi nuovi o cambiati.
senato_step "commissioni dei ddl (dati.senato.it)" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_bill_committees.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato
# Chi il resoconto chiama relatore e dati.senato.it non elenca. Senza rete.
step "relatori dai resoconti" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/ingest_reporters.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato --source resoconto
# Offline: il ddl dal numero dell'ODG, l'esito dagli emendamenti di tipo G
# (JSONL di parse_emendamenti.py, rigenerato da update_data.sh prima di qui).
step "ordini del giorno → ddl ed esito" env NEO4J_PASSWORD="$PASS_VAL" \
	"$PY" build/link_agenda_orders.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" --chamber senato
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

# Riassunti delle sedute nuove: come per la Camera si parte dalla frontiera
# (data più recente del Senato con recap) e non si recupera l'arretrato.
# Il testo lo legge dall'archivio Postgres, quindi gira dopo lo strip.
OPENAI_VAL="${OPENAI_API_KEY:-$(grep '^OPENAI_API_KEY=' .env | cut -d= -f2-)}"
SUM_FRONTIER=$(env NEO4J_PASSWORD="$PASS_VAL" "$PY" -c '
import os, sys
from neo4j import GraphDatabase
d = GraphDatabase.driver(sys.argv[1], auth=(sys.argv[2], os.environ["NEO4J_PASSWORD"]))
m = d.execute_query("MATCH (n:Session {chamber: \"senato\"}) WHERE n.recapIt IS NOT NULL "
                    "RETURN toString(max(n.date)) AS m").records[0]["m"]
print(m or "")
d.close()' "$URI" "$USER_VAL" 2>/dev/null)
if [ -z "$OPENAI_VAL" ] || [ -z "$SUM_FRONTIER" ] || [ -z "$ARCHIVE_VAL" ]; then
	echo "── Senato: riassunti saltati (manca OPENAI_API_KEY o ARCHIVE_URL, o nessuna seduta ha un recap)"
else
	step "riassunti delle sedute dal $SUM_FRONTIER" env OPENAI_API_KEY="$OPENAI_VAL" \
		ARCHIVE_URL="$ARCHIVE_VAL" ARCHIVE_SCOPES=senato_19 NEO4J_PASSWORD="$PASS_VAL" \
		"$PY" build/generate_summaries.py --neo4j-uri "$URI" --neo4j-user "$USER_VAL" \
		--from-date "$SUM_FRONTIER" --chamber senato
fi

# Link al singolo intervento su senato.it: la pagina della seduta per tutti,
# l'ancora dell'intervento dove l'indice della seduta è in cache
# (data/senate_toc, 80 pagine a giro finché non è completa).
links() {
	env NEO4J_PASSWORD="$PASS_VAL" "$PY" build/senate_speech_links.py "$@" \
		--neo4j-uri "$URI" --neo4j-user "$USER_VAL" --legislature 19
}
step "link alle sedute su senato.it" links sittings
senato_step "indici delle sedute (senato.it)" links toc --limit 80 --delay "$SENATO_DELAY"
step "link ai singoli interventi" links anchor

exit "$rc_all"
