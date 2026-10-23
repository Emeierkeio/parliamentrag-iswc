#!/usr/bin/env bash
# Orchestratore di `make update-data`. L'output completo di ogni step finisce in
# build/logs/update-data-<timestamp>.log; a terminale restano solo l'avanzamento
# (una riga live con l'ultima riga di output dello step in corso), l'esito ✓/✗
# con la durata, e le righe WARNING/ERROR estratte dal log.
#
# Variabili (passate dal Makefile, con default identici):
#   V2_DIR, DEMO_NEO4J, BACKEND_DIR, LOCAL_BOLT_PORT, LOCAL_SYNC, HF_DATASET_REPO
#   SENATO_NEO4J (facoltativa: DB con il Senato da aggiornare, vedi update_senato.sh)
#   EMENDAMENTI_GRAFO=1 (facoltativa: emendamenti nel grafo e nell'archivio)
#   SOLO (facoltativa: regex sui nomi dei passi; gli altri si saltano, vedi build/recupero.sh)
set -u -o pipefail

cd "$(dirname "$0")/.."

: "${V2_DIR:=.}"
: "${DEMO_NEO4J:=bolt://localhost:7690}"
: "${BACKEND_DIR:=backend}"
: "${LOCAL_BOLT_PORT:=7691}"
: "${LOCAL_SYNC:=1}"
: "${HF_DATASET_REPO:=emeierkeio/parliamentrag-leg19}"

PY="$BACKEND_DIR/venv/bin/python"
LOCAL_NEO4J="bolt://localhost:$LOCAL_BOLT_PORT"

LOG_DIR="build/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/update-data-$(date +%Y%m%d-%H%M%S).log"
: >"$LOG"

if [ -t 1 ]; then
	BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; RESET=$'\033[0m'
	TTY=1
else
	BOLD=; DIM=; RED=; GREEN=; YELLOW=; RESET=; TTY=
fi

STEP=0
WARNINGS=0
CURRENT_PID=

trap 'if [ -n "$CURRENT_PID" ]; then kill "$CURRENT_PID" 2>/dev/null; fi; printf "\nInterrotto. Log completo: %s\n" "$LOG"; exit 130' INT TERM

note() { printf '%s\n' "$*"; printf '%s\n' "$*" >>"$LOG"; }

warn() {
	WARNINGS=$((WARNINGS + 1))
	printf '  %s! %s%s\n' "$YELLOW" "$*" "$RESET"
	printf '! %s\n' "$*" >>"$LOG"
}

fmt_dur() {
	local s=$1
	if [ "$s" -ge 60 ]; then printf '%dm%02ds' $((s / 60)) $((s % 60)); else printf '%ds' "$s"; fi
}

# run "label" cmd... — esegue cmd con stdout+stderr sul log; a terminale mostra
# una riga live (ultima riga di output, aggiornata ogni secondo) e poi ✓/✗ con
# la durata. Rilancia le righe WARNING/ERROR dello step. Ritorna l'rc di cmd.
run() {
	local label="$1"; shift
	# Recupero (build/recupero.sh): solo i passi il cui nome corrisponde a $SOLO.
	if [ -n "${SOLO:-}" ] && ! printf '%s' "$label" | grep -qiE -- "$SOLO"; then
		return 0
	fi
	STEP=$((STEP + 1))
	local start=$SECONDS
	{ echo; echo "════ [$STEP] $label"; } >>"$LOG"
	local from
	from=$(wc -l <"$LOG")
	"$@" >>"$LOG" 2>&1 &
	CURRENT_PID=$!
	if [ -n "$TTY" ]; then
		while kill -0 "$CURRENT_PID" 2>/dev/null; do
			local last
			last=$(tail -c 4096 "$LOG" | tr '\r' '\n' | grep -v '^[[:space:]]*$' | tail -n 1 | cut -c1-110)
			printf '\r\033[K%s… [%d] %s%s  %s%s%s' "$BOLD" "$STEP" "$label" "$RESET" "$DIM" "$last" "$RESET"
			sleep 1
		done
		printf '\r\033[K'
	fi
	wait "$CURRENT_PID"
	local rc=$?
	CURRENT_PID=
	local dur
	dur=$(fmt_dur $((SECONDS - start)))
	if [ "$rc" -eq 0 ]; then
		printf '%s✓%s [%d] %s %s(%s)%s\n' "$GREEN" "$RESET" "$STEP" "$label" "$DIM" "$dur" "$RESET"
	else
		printf '%s✗ [%d] %s (rc=%d, %s)%s\n' "$RED" "$STEP" "$label" "$rc" "$dur" "$RESET"
	fi
	sed -n "$((from + 1)),\$p" "$LOG" | grep -aE 'WARNING|ERROR|Traceback' | head -8 \
		| while IFS= read -r l; do printf '  %s! %s%s\n' "$YELLOW" "$l" "$RESET"; done
	return "$rc"
}

die() {
	echo
	printf '%sFAILED.%s Ultime 30 righe del log:\n' "$RED" "$RESET"
	tail -n 30 "$LOG" | sed 's/^/  /'
	echo
	echo "Log completo: $LOG"
	exit 1
}

# ── Preflight ────────────────────────────────────────────────────────────────
[ -f "$V2_DIR/build/build_and_update.py" ] || {
	echo "ERROR: v2 pipeline not found at $V2_DIR/build — set V2_DIR=<path to ParliamentRAG repo>"; exit 1; }
[ -x "$V2_DIR/backend/venv/bin/python" ] || {
	echo "ERROR: v2 backend venv missing — run 'make db-install' inside $V2_DIR first"; exit 1; }

NEO4J_USER_VAL=$(grep '^NEO4J_USER=' .env | cut -d= -f2-)
NEO4J_PASS_VAL=$(grep '^NEO4J_PASSWORD=' .env | cut -d= -f2-)
OPENAI_KEY_VAL=$(grep '^OPENAI_API_KEY=' .env | cut -d= -f2-)
[ -n "$NEO4J_PASS_VAL" ] || { echo "ERROR: NEO4J_PASSWORD not found in .env"; exit 1; }

note "Updating demo DB at $DEMO_NEO4J (pipeline: $V2_DIR/build)"
note "Log completo: $LOG"
echo

# Query Cypher one-shot che restituiscono un valore (frontiera recap, numero di
# seduta di partenza per i voti).
cypher_scalar() { # $1 = uri, $2 = query python inline
	NEO4J_PASSWORD="$NEO4J_PASS_VAL" NEO4J_TARGET="$1" "$PY" -c "$2" 2>>"$LOG"
}

# --skip-atti: gli atti della Camera arrivano da ingest_acts_camera.py (sotto).
v2_ingest() { # $1 = neo4j uri
	(cd "$V2_DIR" && backend/venv/bin/python build/build_and_update.py update --skip-atti \
		--neo4j-uri "$1" --neo4j-user "${NEO4J_USER_VAL:-neo4j}" --neo4j-password "$NEO4J_PASS_VAL")
}

# ── Atti della Camera, per atto ──────────────────────────────────────────────
# Sostituisce lo step 4 di build_and_update.py update, che leggeva gli atti
# deputato per deputato e perdeva i ddl del governo, gli atti di regioni, CNEL,
# iniziativa popolare ed ex deputati. Gira prima dell'ingest v2 perché è il
# suo step 6 a calcolare gli embedding degli atti nuovi o con titolo cambiato.
acts_camera() { # $1 = neo4j uri
	NEO4J_PASSWORD="$NEO4J_PASS_VAL" "$PY" build/ingest_acts_camera.py --neo4j-uri "$1" --since-meta
}
run "Atti Camera per atto (ods:modified)" acts_camera "$DEMO_NEO4J" \
	|| warn "Atti Camera per atto non riuscito: restano quelli del giro precedente"

# ── Ingest incrementale (remoto) ─────────────────────────────────────────────
run "Ingest v2 pipeline → $DEMO_NEO4J" v2_ingest "$DEMO_NEO4J" || die

# Il v2 ingest attacca i nuovi interventi ai duplicati di persona.rdf.
run "Repair speaker links" "$PY" "$BACKEND_DIR/scripts/repair_speaker_links.py" "$DEMO_NEO4J" || die

# ── AI summaries (sedute senza recap) ─────────────────────────────────────────
# generate_summaries.py prende solo le sedute con recapIt nullo, quindi un giro
# senza --from-date recupera l'arretrato e poi fa solo le sedute nuove. Dal
# 17/10/2026 l'arretrato storico della Camera si recupera (decisione di Mirko).
# Solo Camera: il Senato ha il suo passo in update_senato.sh, perché le sue
# sedute arrivano più tardi nel giro.
# Gira PRIMA del replay locale così sync_local_snapshot.py copia anche i recap.
if [ -z "$OPENAI_KEY_VAL" ]; then
	warn "OPENAI_API_KEY not found in .env — summaries skipped."
else
	gen_summaries() {
		OPENAI_API_KEY="$OPENAI_KEY_VAL" "$PY" build/generate_summaries.py \
			--neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j --neo4j-password "$NEO4J_PASS_VAL" \
			--chamber camera
	}
	run "AI summaries Camera (sedute senza recap)" gen_summaries \
		|| warn "riassunti Camera incompleti: riprendono al prossimo giro"
fi

# ── Cache topic della landing ────────────────────────────────────────────────
# Ricalcolata ora che i dati sono cambiati, così nessun visitatore aspetta la
# computazione Neo4j+LLM. La curl sveglia anche il backend prod, che dal 5/10
# non sta più dietro www.parliamentrag.it (ora sito del centro).
: "${BACKEND_URL:=https://thesis-parliamentrag-production.up.railway.app}"
for L in it en; do
	run "Warm recent-topics cache (lang=$L)" \
		curl -sf -m 120 "$BACKEND_URL/api/config/recent-topics?lang=$L&refresh=1" -o /dev/null \
		|| warn "recent-topics lang=$L FAILED (will recompute on first visit)"
done

run "Refresh README data stats" "$PY" build/update_readme_stats.py --neo4j-uri "$DEMO_NEO4J" || die

run "Sync ORKG entry statistics" "$PY" build/update_orkg_stats.py --neo4j-uri "$DEMO_NEO4J" \
	|| warn "ORKG sync FAILED (non-blocking): orkg.org slow or unreachable, retry at next update"

# ── Replay sullo snapshot locale ─────────────────────────────────────────────
# Stesso update incrementale sullo snapshot locale (:$LOCAL_BOLT_PORT) così la
# copia non deriva mai dal demo DB. Download e embeddings colpiscono le cache
# del giro remoto, quindi il replay è economico. Tutto ciò che arriva al remoto
# per altre vie (recap, citability, ChatHistory/survey) NON
# passa dalla pipeline: lo copia sync_local_snapshot.py subito dopo.
LOCAL_UP=
if [ "$LOCAL_SYNC" = "0" ] || [ "$DEMO_NEO4J" = "$LOCAL_NEO4J" ]; then
	note "Local snapshot sync skipped."
elif nc -z -w 2 localhost "$LOCAL_BOLT_PORT" >/dev/null 2>&1; then
	LOCAL_UP=1
	run "Atti Camera per atto (locale)" acts_camera "$LOCAL_NEO4J" \
		|| warn "Atti Camera per atto (locale) non riuscito"
	run "Replay ingest → snapshot locale (:$LOCAL_BOLT_PORT)" v2_ingest "$LOCAL_NEO4J" || die
	run "Repair speaker links (locale)" "$PY" "$BACKEND_DIR/scripts/repair_speaker_links.py" "$LOCAL_NEO4J" || die
	run "Sync dati remote-only → snapshot locale" \
		"$PY" "$BACKEND_DIR/scripts/sync_local_snapshot.py" "$DEMO_NEO4J" "$LOCAL_NEO4J" || die
else
	note "Local snapshot not running on :$LOCAL_BOLT_PORT — sync skipped (make db-pull to recreate it)."
fi

# ── Voti aggregati/individuali da dati.camera.it ─────────────────────────────
# I voti aggregati vivono solo nella SPARQL (gli XML non portano più il blocco
# raccoltaVotazioni) e l'endpoint pubblica con qualche giorno di lag. Il
# confronto copre tutta la legislatura votazione per votazione (due query
# SPARQL più le sole votazioni mancanti): riprende anche le sedute XML rimaste
# senza voti o senza l'ultimo voto. I voti individuali delle ultime ~10 sedute
# si ripassano comunque, perché possono arrivare dopo gli aggregati.
run "Voti Camera mancanti rispetto a dati.camera.it" \
	"$PY" build/sparql_ingester.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
	--neo4j-password "$NEO4J_PASS_VAL" --fill-gaps --legislature 19 \
	|| warn "vote gap fill failed (SPARQL flaky?) — will retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Voti Camera mancanti (locale)" \
		"$PY" build/sparql_ingester.py --neo4j-uri "$LOCAL_NEO4J" --neo4j-user neo4j \
		--neo4j-password "$NEO4J_PASS_VAL" --fill-gaps --legislature 19 \
		|| warn "vote gap fill failed on local snapshot"
fi
START=$(cypher_scalar "$DEMO_NEO4J" 'import os
from neo4j import GraphDatabase
d = GraphDatabase.driver(os.environ["NEO4J_TARGET"], auth=("neo4j", os.environ["NEO4J_PASSWORD"]))
with d.session() as s:
    m = s.run("MATCH (n:Session {chamber: \"camera\"}) RETURN max(toInteger(n.number)) AS m").single()["m"]
print(max(1, (m or 11) - 10))
d.close()')
if [ -z "$START" ]; then
	warn "start-session non calcolabile — refresh voti individuali saltato, retry at next update-data"
else
	run "Voti individuali recenti SPARQL (da seduta $START)" \
		"$PY" build/sparql_ingester.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
		--neo4j-password "$NEO4J_PASS_VAL" --individual-recent --legislature 19 --start-session "$START" \
		|| warn "individual votes refresh failed (SPARQL flaky?) — will retry at next update-data"
	if [ -n "$LOCAL_UP" ]; then
		run "Voti individuali SPARQL (locale)" \
			"$PY" build/sparql_ingester.py --neo4j-uri "$LOCAL_NEO4J" --neo4j-user neo4j \
			--neo4j-password "$NEO4J_PASS_VAL" --individual-recent --legislature 19 --start-session "$START" \
			|| warn "individual votes refresh failed on local snapshot"
	fi
fi

# ── Titoli/atti delle votazioni ──────────────────────────────────────────────
# Le sedute recenti nascono con label generico ("Votazione") e senza
# rif_attoCamera; dati.camera.it li arricchisce solo quando consolida il
# dataset (mesi dopo) e l'ingest aggregati salta le sedute già coperte. Questo
# refresh ripassa TUTTA la legislatura (idempotente, ~1 min). Non blocca.
run "Refresh vote titles/acts (whole legislature)" \
	"$PY" build/repair_vote_data.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
	--neo4j-password "$NEO4J_PASS_VAL" --subjects \
	|| warn "vote titles refresh failed (SPARQL flaky?) — will retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Refresh vote titles/acts (locale)" \
		"$PY" build/repair_vote_data.py --neo4j-uri "$LOCAL_NEO4J" --neo4j-user neo4j \
		--neo4j-password "$NEO4J_PASS_VAL" --subjects \
		|| warn "vote titles refresh failed on local snapshot"
fi

# ── Voti sulla lettura votata ────────────────────────────────────────────────
# dati.camera.it collega i voti di una seconda lettura (C.2822-B) alla prima
# (C.2822), e i due passi sopra li ricollegano così ogni notte: qui l'ON_ACT
# passa alla lettura che la descrizione del voto nomina. Toglie anche l'EuroVoc
# 7816, che la classificazione provvisoria della Camera usa per «Repubblica».
run "Voti sulla lettura votata" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/repair_vote_readings.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
	|| warn "repair_vote_readings failed — will retry at next update-data"

# ── Documenti (Doc.) della Camera ────────────────────────────────────────────
# Un nodo per documento discusso o votato (DEF, relazioni della Giunta,
# inchieste...): titolo e testi da ocd:DOC (una query SPARQL, copia in data/),
# ON_ACT dei voti che nominano il documento, relatori dalla relazione «-A».
# Dopo i voti e prima dei segnaposto, che il passo sotto sposta sul documento.
run "Documenti Camera" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_documents.py --neo4j-uri "$DEMO_NEO4J" --chamber camera --download \
	|| warn "documenti Camera: passo fallito, riprende al prossimo giro"

# ── Atti placeholder ─────────────────────────────────────────────────────────
# L'ingest XML crea placeholder per gli argomenti dei dibattiti (1-00004 vs
# 1/00004, pdl "-A", "Doc. IV-ter, n. 13-A"); l'atto vero arriva dalla SPARQL
# in un giro successivo. Pass idempotente: ripunta DISCUSSES/CITES e cancella
# il placeholder.
run "Resolve placeholder acts" "$PY" build/repair_placeholder_acts.py --neo4j-uri "$DEMO_NEO4J" \
	|| warn "placeholder resolution failed — retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Resolve placeholder acts (locale)" "$PY" build/repair_placeholder_acts.py --neo4j-uri "$LOCAL_NEO4J" \
		|| warn "placeholder resolution failed on local snapshot"
fi

# ── Date ed embedding dei progetti di legge ──────────────────────────────────
# I PDL (ocd:atto) hanno la data in dc:date, non in ocd:startDate, e la
# descrizione vuota: senza questo pass l'autorevolezza li scartava (niente
# data) o li contava con rilevanza neutra su ogni tema (niente embedding).
# Idempotente: riempie solo date ed embedding mancanti (embedding = titolo).
run "Date ed embedding progetti di legge" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/repair_bills.py --neo4j-uri "$DEMO_NEO4J" \
	|| warn "bill dates repair failed — retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Date ed embedding progetti di legge (locale)" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
		"$PY" build/repair_bills.py --neo4j-uri "$LOCAL_NEO4J" \
		|| warn "bill dates repair failed on local snapshot"
fi

# ── Cariche di gruppo (direttivo) ────────────────────────────────────────────
# Presidenti, vice, tesorieri e segretari dei gruppi da dati.camera.it:
# finiscono come role sulla MEMBER_OF_GROUP attiva (wipe & reapply).
run "Group offices (direttivo)" "$PY" build/ingest_group_offices.py \
	--neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j --neo4j-password "$NEO4J_PASS_VAL" \
	|| warn "group offices failed (SPARQL Camera giù?) — retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Group offices (locale)" "$PY" build/ingest_group_offices.py \
		--neo4j-uri "$LOCAL_NEO4J" --neo4j-user neo4j --neo4j-password "$NEO4J_PASS_VAL" \
		|| warn "group offices (locale) failed — snapshot da riallineare al prossimo giro"
fi

# ── Componenti del Gruppo Misto ──────────────────────────────────────────────
# Adesioni datate alle componenti (Futuro Nazionale, +Europa, ...) da
# dati.camera.it. Va dopo l'ingest: la componente si aggancia al Deputy già
# spostato nel Misto dal refresh dei CSV.
misto_ingest() { # $1 = neo4j uri
	NEO4J_URI="$1" NEO4J_USER="${NEO4J_USER_VAL:-neo4j}" NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
		"$PY" build/ingest_misto_componenti.py
}
run "Componenti Misto" misto_ingest "$DEMO_NEO4J" \
	|| warn "componenti Misto failed (SPARQL Camera giù?) — restano quelle di ieri, retry at next update-data"
if [ -n "$LOCAL_UP" ]; then
	run "Componenti Misto (locale)" misto_ingest "$LOCAL_NEO4J" \
		|| warn "componenti Misto (locale) failed — snapshot da riallineare al prossimo giro"
fi

# ── Emendamenti XIX (Camera e Senato) ────────────────────────────────────────
# Scarica solo ciò che è nuovo o con l'iter cambiato negli ultimi giorni, poi
# rigenera downloads/emendamenti/emendamenti_leg19.jsonl (circa un minuto).
# Il caricamento nel grafo e nell'archivio è più sotto, dopo il Senato.
EMEND_DAYS=14
# senato.it blocca l'IP (403 su tutto il sito) dopo qualche ora a 0,5 s tra le
# richieste: di notte le richieste sono poche, quindi si va piano.
SENATO_DELAY=2
AKN_DIR="downloads/akn_senato"
# Emendamenti (emend, emendc) e testo dei disegni di legge: presentato,
# della commissione, approvato (ddlpres, ddlcomm, ddlmess). Il file delle
# cartelle si riscrive a ogni giro, così un clone fatto con un elenco più
# corto prende le cartelle nuove (reapply scarica solo i loro file).
AKN_SPARSE='/Leg19/*/emend/\n/Leg19/*/emendc/\n/Leg19/*/ddlpres/\n/Leg19/*/ddlcomm/\n/Leg19/*/ddlmess/\n/Leg19/*/README.MD\n'
akn_pull() {
	if [ -d "$AKN_DIR/.git" ]; then
		# Clone superficiale in sola lettura: un pull non trova storia comune con
		# il commit giornaliero del Senato, quindi si allinea all'ultimo commit.
		printf "$AKN_SPARSE" >"$AKN_DIR/.git/info/sparse-checkout" \
			&& git -C "$AKN_DIR" fetch --quiet --depth 1 origin master \
			&& git -C "$AKN_DIR" reset --quiet --hard FETCH_HEAD \
			&& git -C "$AKN_DIR" sparse-checkout reapply
	else
		git clone --quiet --filter=blob:none --no-checkout --depth 1 \
			https://github.com/SenatoDellaRepubblica/AkomaNtosoBulkData.git "$AKN_DIR" \
			&& git -C "$AKN_DIR" sparse-checkout init --no-cone \
			&& printf "$AKN_SPARSE" >"$AKN_DIR/.git/info/sparse-checkout" \
			&& git -C "$AKN_DIR" checkout --quiet master
	fi
}
run "Emendamenti Camera (nuovi e cambiati)" "$PY" build/download_emendamenti_camera.py --recenti "$EMEND_DAYS" \
	|| warn "emendamenti Camera: download incompleto, riprova al prossimo giro"
run "Fasi Senato + pagine emendamenti di commissione" \
	"$PY" build/download_emendamenti_senato.py --recenti "$EMEND_DAYS" --delay "$SENATO_DELAY" \
	|| warn "emendamenti Senato (HTML): download incompleto"
run "Akoma Ntoso Senato (git pull)" akn_pull \
	|| warn "Akoma Ntoso Senato: pull fallito"
run "Esiti Senato + testi mancanti" "$PY" build/download_esiti_senato.py --recenti "$EMEND_DAYS" --delay "$SENATO_DELAY" \
	|| warn "esiti Senato: download incompleto"
run "Emendamenti → JSONL unico" "$PY" build/parse_emendamenti.py \
	|| warn "parse emendamenti fallito"

# ── Senato XIX ───────────────────────────────────────────────────────────────
# Solo su un DB che contiene già il Senato: SENATO_NEO4J (ambiente o .env) è
# quel DB; vuoto, il passo si salta. Con ARCHIVE_URL nel .env il testo del
# Senato va nell'archivio Postgres (update_senato.sh).
: "${SENATO_NEO4J:=$(grep '^SENATO_NEO4J=' .env | cut -d= -f2-)}"
if [ -z "$SENATO_NEO4J" ]; then
	note "Senato: SENATO_NEO4J non impostato — saltato."
else
	run "Senato XIX → $SENATO_NEO4J" env BACKEND_DIR="$BACKEND_DIR" build/update_senato.sh "$SENATO_NEO4J" \
		|| warn "Senato: aggiornamento incompleto (rc 3 = dati.senato.it rifiuta le richieste), riprende al prossimo giro"
fi

# ── Famiglia e kind degli atti (decisione D1) ────────────────────────────────
# Dopo tutti i writer di atti: copre segnaposto e ODG noti solo dall'URI.
# Idempotente, senza rete.
run "Famiglia e kind degli atti" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/migrate_act_kinds.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" \
	|| warn "famiglia e kind degli atti: migrazione fallita, riprende al prossimo giro"
# Mozioni e risoluzioni della Camera votate in Aula → il dibattito in cui cade
# il voto («Vedi votazione n.» del resoconto) e quello che riprende. Dopo i
# kind, senza rete, idempotente. Quelle del Senato passano da link_senate_acts.py.
run "Mozioni e risoluzioni Camera → dibattito" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/link_camera_motions.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" \
	|| warn "mozioni e risoluzioni Camera: collegamento fallito, riprende al prossimo giro"
# Dibattiti ripresi («Si riprende la discussione del disegno di legge n. …»,
# «Si riprende la discussione.») e stralci («A.C. 1532-ter-A») → il progetto di
# legge, dal titolo o dal punto all'ordine del giorno che riprendono. Senza
# rete, idempotente, prima dei relatori dai resoconti che leggono DISCUSSES.
run "Dibattiti ripresi Camera → progetto di legge" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/link_resumed_debates.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera \
	|| warn "dibattiti ripresi Camera: collegamento fallito, riprende al prossimo giro"
# Oggetto leggibile di mozioni e risoluzioni (a.subject) dal titolo del
# dibattito o dall'etichetta del voto, mai da testo generato. Dopo i
# collegamenti di entrambe le camere; scrive solo i valori cambiati.
run "Oggetto di mozioni e risoluzioni" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/act_subjects.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" \
	|| warn "oggetto di mozioni e risoluzioni: calcolo fallito, riprende al prossimo giro"
# Letture dello stesso progetto di legge in un LegislativeProcess (decisione
# D2), dalle fasi del Senato che update_senato.sh ha appena scaricato, e
# versioni del testo della Camera (-A, -A/R, testi unificati): una query SPARQL.
run "Letture e processo legislativo" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/migrate_act_identity.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --versions \
	|| warn "processo legislativo: migrazione fallita, riprende al prossimo giro"
# Ordini del giorno della Camera → progetto di legge (dal numero) ed esito
# (dai voti caricati sopra). Senza rete, idempotente. Quelli del Senato
# passano da update_senato.sh.
run "ODG Camera → progetto di legge ed esito" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/link_agenda_orders.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera \
	|| warn "ODG Camera: collegamento fallito, riprende al prossimo giro"
# Relatori dei progetti di legge della Camera (ocd:rif_relatore, due query
# SPARQL). Dopo l'ingest per atto: servono i Bill. I relatori del Senato
# passano da update_senato.sh.
run "Relatori Camera" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_reporters.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera \
	|| warn "relatori Camera: SPARQL non raggiungibile, restano quelli del giro precedente"
# Commissione a cui è assegnato ogni progetto di legge della Camera (ocd:rif_assegnazione,
# sede referente, una query SPARQL per anno): scrive solo gli archi nuovi o
# cambiati. Quelle del Senato passano da update_senato.sh.
run "Commissioni dei progetti di legge Camera" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_bill_committees.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera \
	|| warn "commissioni Camera: SPARQL non raggiungibile, restano quelle del giro precedente"
# Relatori di minoranza e sostituti in Aula che dati.camera.it non elenca, dalla
# scheda dell'atto su camera.it: solo atti nuovi o cambiati (al più 150 pagine,
# 2,5 s l'una), il resto dalla copia in data/camera_xix_relatori_schede.json.
run "Relatori Camera dalle schede di camera.it" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_reporters.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera --source scheda \
	|| warn "relatori Camera dalle schede: camera.it non risponde, restano quelli del giro precedente"
# Chi il resoconto chiama relatore su un atto del dibattito e nessuna fonte
# elenca. Senza rete, dopo le schede.
run "Relatori Camera dai resoconti" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_reporters.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --chamber camera --source resoconto \
	|| warn "relatori Camera dai resoconti: passo fallito, riprende al prossimo giro"
# Leggi pubblicate collegate al processo (decisione D5): numero e data dalle
# fasi del Senato appena scaricate, Gazzetta dallo SPARQL della Camera (una
# query), ELI e codice redazionale da Normattiva solo per le leggi nuove.
run "Leggi" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
	"$PY" build/ingest_laws.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" \
	|| warn "leggi: ingest fallito, riprende al prossimo giro"

# ── Testo dei progetti di legge (Camera e Senato) → archivio ─────────────────
# Articolato e relazione di ogni versione (TextVersion, appena aggiornate dal
# passo «Letture e processo legislativo») da documenti.camera.it, in act_text e
# act_text_chunk dell'archivio. Scarica solo le versioni che non sono in
# downloads/testi_atti/camera/, riscrive le righe con l'hash cambiato e manda a
# OpenAI solo i passaggi senza embedding. Spento di default: si accende con
# TESTI_ATTI=1 (ambiente o .env) dopo il primo caricamento a mano, che scarica
# tutte le versioni (circa 3.800 a ottobre 2026, un secondo l'una).
# Il Senato viene dal checkout Akoma Ntoso aggiornato sopra (akn_pull): niente
# rete, circa 2.800 file a ottobre 2026, pochi secondi senza embedding nuovi.
: "${TESTI_ATTI:=$(grep '^TESTI_ATTI=' .env | cut -d= -f2-)}"
ACT_TEXT_ARCHIVE="${ARCHIVE_URL:-$(grep '^ARCHIVE_URL=' .env | cut -d= -f2-)}"
if [ "${TESTI_ATTI:-0}" != "1" ]; then
	note "Testo dei progetti di legge: TESTI_ATTI non attivo — saltato."
elif [ -z "$ACT_TEXT_ARCHIVE" ]; then
	warn "Testo dei progetti di legge: ARCHIVE_URL mancante — saltato."
else
	act_texts() {
		env NEO4J_PASSWORD="$NEO4J_PASS_VAL" OPENAI_API_KEY="$OPENAI_KEY_VAL" \
			"$PY" build/load_act_texts.py --neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" \
			--neo4j-user "${NEO4J_USER_VAL:-neo4j}" --archive-url "$ACT_TEXT_ARCHIVE"
	}
	run "Testo dei progetti di legge Camera → archivio" act_texts \
		|| warn "testo dei progetti di legge: caricamento incompleto, riprende al prossimo giro"
	act_texts_senato() {
		env NEO4J_PASSWORD="$NEO4J_PASS_VAL" OPENAI_API_KEY="$OPENAI_KEY_VAL" \
			"$PY" build/load_act_texts.py --chamber senato --akn-dir "$AKN_DIR" \
			--neo4j-uri "${SENATO_NEO4J:-$DEMO_NEO4J}" --neo4j-user "${NEO4J_USER_VAL:-neo4j}" \
			--archive-url "$ACT_TEXT_ARCHIVE"
	}
	run "Testo dei disegni di legge Senato → archivio" act_texts_senato \
		|| warn "testo dei disegni di legge del Senato: caricamento incompleto, riprende al prossimo giro"
fi

# ── Emendamenti XIX → grafo e archivio ───────────────────────────────────────
# Spento di default: si accende con EMENDAMENTI_GRAFO=1 (ambiente o .env).
# Dopo il Senato, così le sue votazioni nuove si collegano nello stesso giro.
# Va nel DB che ha entrambe le camere (SENATO_NEO4J se impostato). Con
# ARCHIVE_URL anche testi ed embedding nell'archivio Postgres: solo i testi
# nuovi vanno a OpenAI, il resto si importa una volta dal dump (vedi
# build/load_emendamenti.py). Idempotente: senza novità non scrive nulla.
: "${EMENDAMENTI_GRAFO:=$(grep '^EMENDAMENTI_GRAFO=' .env | cut -d= -f2-)}"
EMEND_JSONL="downloads/emendamenti/emendamenti_leg19.jsonl"
if [ "${EMENDAMENTI_GRAFO:-0}" != "1" ]; then
	note "Emendamenti nel grafo: EMENDAMENTI_GRAFO non attivo — saltato."
elif [ ! -s "$EMEND_JSONL" ]; then
	warn "Emendamenti nel grafo: $EMEND_JSONL mancante — saltato."
else
	EMEND_NEO4J="${SENATO_NEO4J:-$DEMO_NEO4J}"
	EMEND_ARCHIVE="${ARCHIVE_URL:-$(grep '^ARCHIVE_URL=' .env | cut -d= -f2-)}"
	emend_load() {
		env NEO4J_PASSWORD="$NEO4J_PASS_VAL" OPENAI_API_KEY="$OPENAI_KEY_VAL" \
			"$PY" build/load_emendamenti.py --input "$EMEND_JSONL" \
			--neo4j-uri "$EMEND_NEO4J" --neo4j-user "${NEO4J_USER_VAL:-neo4j}" \
			${EMEND_ARCHIVE:+--archive-url "$EMEND_ARCHIVE"}
	}
	run "Emendamenti → $EMEND_NEO4J${EMEND_ARCHIVE:+ + archivio}" emend_load \
		|| warn "emendamenti nel grafo: caricamento incompleto, riprende al prossimo giro"
fi

# ── Citabilità dei chunk nuovi ───────────────────────────────────────────────
# Il merger pesa la citabilità per il 25% del punteggio e Fascicoli scarta i
# chunk procedurali: un chunk senza punteggio vale 0,5 e non viene mai
# scartato. Classifica solo i chunk senza citability_v, di entrambe le camere;
# il testo del Senato lo legge dall'archivio Postgres. Dopo il Senato, così
# prende anche le sue sedute nuove. Non blocca: riprende al giro dopo.
if [ -z "${OPENAI_KEY_VAL:-}" ]; then
	warn "OPENAI_API_KEY not found in .env — citabilità saltata."
else
	CIT_NEO4J="${SENATO_NEO4J:-$DEMO_NEO4J}"
	CIT_ARCHIVE="${ARCHIVE_URL:-$(grep '^ARCHIVE_URL=' .env | cut -d= -f2-)}"
	citability() {
		env NEO4J_PASSWORD="$NEO4J_PASS_VAL" OPENAI_API_KEY="$OPENAI_KEY_VAL" \
			"$PY" build/classify_chunk_citability.py --neo4j-uri "$CIT_NEO4J" \
			--neo4j-user "${NEO4J_USER_VAL:-neo4j}" ${CIT_ARCHIVE:+--archive-url "$CIT_ARCHIVE"}
	}
	run "Citabilità chunk nuovi → $CIT_NEO4J${CIT_ARCHIVE:+ + archivio}" citability \
		|| warn "citabilità: classificazione incompleta, riprende al prossimo giro"
fi

# ── Controllo del grafo ──────────────────────────────────────────────────────
# Dopo tutti i passi che scrivono: un FAIL non ferma il giro, ma il passo esce
# ✗ nel report del mattino con le righe FAIL qui sotto.
validate() {
	env NEO4J_PASSWORD="$NEO4J_PASS_VAL" "$PY" build/validate_db.py --neo4j-uri "$DEMO_NEO4J"
}
if ! run "Controllo del grafo (validate_db)" validate; then
	sed 's/\x1b\[[0-9;]*m//g' "$LOG" | grep '^ *\[FAIL\]' | cut -c1-200 \
		| while IFS= read -r line; do warn "validate_db:$line"; done
fi

# ── Fotografia del grafo per il sito del centro ──────────────────────────────
# www.parliamentrag.it non ha backend: numeri e data del grafo stanno in
# src/data/site-data.json del repo del centro, che Railway pubblica a ogni push
# su main. Commit solo se cambiano i numeri o la data (gli esempi di
# graph-samples.json sono casuali e cambiano a ogni giro). Si salta se il
# checkout non è su main o ha modifiche, per non spingere lavoro altrui.
: "${CENTRO_DIR:=../centro}"
centro_snapshot() {
	local branch
	branch=$(git -C "$CENTRO_DIR" rev-parse --abbrev-ref HEAD) || return 1
	if [ "$branch" != "main" ] || [ -n "$(git -C "$CENTRO_DIR" status --porcelain)" ]; then
		echo "WARNING: $CENTRO_DIR non è su main pulito ($branch), fotografia saltata"
		return 0
	fi
	git -C "$CENTRO_DIR" fetch --quiet origin main \
		&& git -C "$CENTRO_DIR" merge --quiet --ff-only origin/main \
		&& (cd "$CENTRO_DIR" && node scripts/snapshot-data.mjs) || return 1
	if [ -z "$(git -C "$CENTRO_DIR" diff -U0 -- src/data/site-data.json | grep -E '^[+-] ' | grep -v snapshot_at)" ]; then
		echo "numeri invariati, nessun commit"
		git -C "$CENTRO_DIR" checkout --quiet -- src/data
		return 0
	fi
	git -C "$CENTRO_DIR" add src/data/site-data.json src/data/graph-samples.json \
		&& git -C "$CENTRO_DIR" commit --quiet -m "chore(data): fotografia del grafo $(date +%Y-%m-%d)" \
		&& git -C "$CENTRO_DIR" push --quiet origin main
}
if [ -d "$CENTRO_DIR/.git" ] && command -v node >/dev/null 2>&1; then
	run "Fotografia del grafo → sito del centro" centro_snapshot \
		|| warn "fotografia del centro fallita — rilancia 'node scripts/snapshot-data.mjs' in $CENTRO_DIR"
else
	note "Sito del centro: checkout $CENTRO_DIR o node mancanti — fotografia saltata"
fi

# ── Dataset Hugging Face ─────────────────────────────────────────────────────
# A differenza di Zenodo (snapshot congelato) segue il DB vivo: rigenera i
# parquet + card dallo snapshot locale e ricarica il repo. Non blocca.
if ! command -v hf >/dev/null 2>&1; then
	note "HF dataset: hf CLI not installed — skipped (uv tool install huggingface_hub)"
elif ! nc -z -w 2 localhost "$LOCAL_BOLT_PORT" >/dev/null 2>&1; then
	note "HF dataset: local snapshot (:$LOCAL_BOLT_PORT) not running — skipped"
else
	hf_update() {
		"$PY" build/export_hf.py \
			&& hf upload "$HF_DATASET_REPO" dumps/hf . --repo-type dataset \
				--commit-message "Data update $(date +%Y-%m-%d)"
	}
	run "Update Hugging Face dataset ($HF_DATASET_REPO)" hf_update \
		|| warn "HF dataset update failed — retry with 'make export-hf hf-upload'"
fi

# ── Esito ────────────────────────────────────────────────────────────────────
echo
if [ "$WARNINGS" -gt 0 ]; then
	printf '%sDone con %d warning%s (dettagli sopra e nel log).\n' "$YELLOW" "$WARNINGS" "$RESET"
else
	printf '%sDone.%s Sidebar date, landing/data stats, README, ORKG and HF dataset now reflect the updated DB.\n' "$GREEN" "$RESET"
fi
echo "Log completo: $LOG"
