#!/usr/bin/env bash
# Orchestratore di `make update-data`. L'output completo di ogni step finisce in
# build/logs/update-data-<timestamp>.log; a terminale restano solo l'avanzamento
# (una riga live con l'ultima riga di output dello step in corso), l'esito ✓/✗
# con la durata, e le righe WARNING/ERROR estratte dal log.
#
# Variabili (passate dal Makefile, con default identici):
#   V2_DIR, DEMO_NEO4J, BACKEND_DIR, LOCAL_BOLT_PORT, LOCAL_SYNC, HF_DATASET_REPO
set -u -o pipefail

cd "$(dirname "$0")/.."

: "${V2_DIR:=.}"
: "${DEMO_NEO4J:=bolt://localhost:7690}"
: "${BACKEND_DIR:=backend}"
: "${LOCAL_BOLT_PORT:=7691}"
: "${LOCAL_SYNC:=1}"
: "${HF_DATASET_REPO:=emeierkeio/parliamentrag-camera-leg19}"

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

v2_ingest() { # $1 = neo4j uri
	(cd "$V2_DIR" && backend/venv/bin/python build/build_and_update.py update \
		--neo4j-uri "$1" --neo4j-user "${NEO4J_USER_VAL:-neo4j}" --neo4j-password "$NEO4J_PASS_VAL")
}

# ── Ingest incrementale (remoto) ─────────────────────────────────────────────
run "Ingest v2 pipeline → $DEMO_NEO4J" v2_ingest "$DEMO_NEO4J" || die

# Il v2 ingest attacca i nuovi interventi ai duplicati di persona.rdf.
run "Repair speaker links" "$PY" "$BACKEND_DIR/scripts/repair_speaker_links.py" "$DEMO_NEO4J" || die

# ── AI summaries (solo sessioni nuove) ───────────────────────────────────────
# Il DB ha un backlog storico di sessioni senza recap (646 al 2026-07) che NON
# va backfillato: si parte dalla frontiera (data più recente con recap) e
# generate_summaries.py --from-date salta le sessioni già coperte (idempotente).
# Gira PRIMA del replay locale così sync_local_snapshot.py copia anche i recap.
if [ -z "$OPENAI_KEY_VAL" ]; then
	warn "OPENAI_API_KEY not found in .env — summaries skipped."
else
	FRONTIER=$(cypher_scalar "$DEMO_NEO4J" 'import os
from neo4j import GraphDatabase
d = GraphDatabase.driver(os.environ["NEO4J_TARGET"], auth=("neo4j", os.environ["NEO4J_PASSWORD"]))
with d.session() as s:
    m = s.run("MATCH (n:Session) WHERE n.recapIt IS NOT NULL RETURN toString(max(n.date)) AS m").single()["m"]
print(m or "")
d.close()')
	if [ -z "$FRONTIER" ]; then
		warn "no session has a recap yet — summary frontier unknown, skipped (run 'make generate-summaries' for a full pass)."
	else
		gen_summaries() {
			OPENAI_API_KEY="$OPENAI_KEY_VAL" "$PY" build/generate_summaries.py \
				--neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j --neo4j-password "$NEO4J_PASS_VAL" \
				--from-date "$FRONTIER"
		}
		run "AI summaries (frontiera: $FRONTIER)" gen_summaries || die
	fi
fi

# ── Cache topic della landing ────────────────────────────────────────────────
# Ricalcolata ora che i dati sono cambiati, così nessun visitatore aspetta la
# computazione Neo4j+LLM. La curl sveglia anche il backend prod.
for L in it en; do
	run "Warm recent-topics cache (lang=$L)" \
		curl -sf -m 120 "https://www.parliamentrag.it/api/config/recent-topics?lang=$L&refresh=1" -o /dev/null \
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
	run "Replay ingest → snapshot locale (:$LOCAL_BOLT_PORT)" v2_ingest "$LOCAL_NEO4J" || die
	run "Repair speaker links (locale)" "$PY" "$BACKEND_DIR/scripts/repair_speaker_links.py" "$LOCAL_NEO4J" || die
	run "Sync dati remote-only → snapshot locale" \
		"$PY" "$BACKEND_DIR/scripts/sync_local_snapshot.py" "$DEMO_NEO4J" "$LOCAL_NEO4J" || die
else
	note "Local snapshot not running on :$LOCAL_BOLT_PORT — sync skipped (make db-pull to recreate it)."
fi

# ── Voti aggregati/individuali da dati.camera.it ─────────────────────────────
# I voti aggregati vivono solo nella SPARQL (gli XML non portano più il blocco
# raccoltaVotazioni) e l'endpoint pubblica con qualche giorno di lag: si
# ripassano le ultime ~10 sedute Camera a ogni update. MERGE idempotenti.
START=$(cypher_scalar "$DEMO_NEO4J" 'import os
from neo4j import GraphDatabase
d = GraphDatabase.driver(os.environ["NEO4J_TARGET"], auth=("neo4j", os.environ["NEO4J_PASSWORD"]))
with d.session() as s:
    m = s.run("MATCH (n:Session {chamber: \"camera\"}) RETURN max(toInteger(n.number)) AS m").single()["m"]
print(max(1, (m or 11) - 10))
d.close()')
if [ -z "$START" ]; then
	warn "start-session non calcolabile — refresh voti aggregati saltato, retry at next update-data"
else
	run "Voti aggregati SPARQL (da seduta $START)" \
		"$PY" build/sparql_ingester.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
		--neo4j-password "$NEO4J_PASS_VAL" --aggregate-only --legislature 19 --start-session "$START" \
		|| warn "aggregate votes refresh failed (SPARQL flaky?) — will retry at next update-data"
	run "Voti individuali recenti SPARQL (da seduta $START)" \
		"$PY" build/sparql_ingester.py --neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j \
		--neo4j-password "$NEO4J_PASS_VAL" --individual-recent --legislature 19 --start-session "$START" \
		|| warn "individual votes refresh failed (SPARQL flaky?) — will retry at next update-data"
	if [ -n "$LOCAL_UP" ]; then
		run "Voti aggregati SPARQL (locale)" \
			"$PY" build/sparql_ingester.py --neo4j-uri "$LOCAL_NEO4J" --neo4j-user neo4j \
			--neo4j-password "$NEO4J_PASS_VAL" --aggregate-only --legislature 19 --start-session "$START" \
			|| warn "aggregate votes refresh failed on local snapshot"
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

# ── Atti placeholder ─────────────────────────────────────────────────────────
# L'ingest XML crea placeholder per gli argomenti dei dibattiti (1-00004 vs
# 1/00004, pdl "-A"); l'atto vero arriva dalla SPARQL in un giro successivo.
# Pass idempotente: ripunta DISCUSSES/CITES e cancella il placeholder.
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
	run "Date progetti di legge (locale)" env NEO4J_PASSWORD="$NEO4J_PASS_VAL" \
		"$PY" build/repair_bills.py --neo4j-uri "$LOCAL_NEO4J" \
		|| warn "bill dates repair failed on local snapshot"
fi

# ── Cariche di gruppo (direttivo) ────────────────────────────────────────────
# Presidenti, vice, tesorieri e segretari dei gruppi da dati.camera.it:
# finiscono come role sulla MEMBER_OF_GROUP attiva (wipe & reapply).
run "Group offices (direttivo)" "$PY" build/ingest_group_offices.py \
	--neo4j-uri "$DEMO_NEO4J" --neo4j-user neo4j --neo4j-password "$NEO4J_PASS_VAL"
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
run "Componenti Misto" misto_ingest "$DEMO_NEO4J" || die
if [ -n "$LOCAL_UP" ]; then
	run "Componenti Misto (locale)" misto_ingest "$LOCAL_NEO4J" \
		|| warn "componenti Misto (locale) failed — snapshot da riallineare al prossimo giro"
fi

# ── Emendamenti XIX (Camera e Senato) ────────────────────────────────────────
# Scarica solo ciò che è nuovo o con l'iter cambiato negli ultimi giorni, poi
# rigenera downloads/emendamenti/emendamenti_leg19.jsonl (circa un minuto).
# Il caricamento nel DB arriverà con la decisione su dove tenere i testi.
EMEND_DAYS=14
AKN_DIR="downloads/akn_senato"
akn_pull() {
	if [ -d "$AKN_DIR/.git" ]; then
		git -C "$AKN_DIR" pull --quiet --depth 1
	else
		git clone --quiet --filter=blob:none --no-checkout --depth 1 \
			https://github.com/SenatoDellaRepubblica/AkomaNtosoBulkData.git "$AKN_DIR" \
			&& git -C "$AKN_DIR" sparse-checkout init --no-cone \
			&& printf '/Leg19/*/emend/\n/Leg19/*/emendc/\n/Leg19/*/README.MD\n' >"$AKN_DIR/.git/info/sparse-checkout" \
			&& git -C "$AKN_DIR" checkout --quiet master
	fi
}
run "Emendamenti Camera (nuovi e cambiati)" "$PY" build/download_emendamenti_camera.py --recenti "$EMEND_DAYS" \
	|| warn "emendamenti Camera: download incompleto, riprova al prossimo giro"
run "Fasi Senato + pagine emendamenti di commissione" \
	"$PY" build/download_emendamenti_senato.py --recenti "$EMEND_DAYS" \
	|| warn "emendamenti Senato (HTML): download incompleto"
run "Akoma Ntoso Senato (git pull)" akn_pull \
	|| warn "Akoma Ntoso Senato: pull fallito"
run "Esiti Senato + testi mancanti" "$PY" build/download_esiti_senato.py --recenti "$EMEND_DAYS" \
	|| warn "esiti Senato: download incompleto"
run "Emendamenti → JSONL unico" "$PY" build/parse_emendamenti.py \
	|| warn "parse emendamenti fallito"

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
