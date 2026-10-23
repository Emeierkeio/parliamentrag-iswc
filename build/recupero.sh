#!/usr/bin/env bash
# Recupero a mano dei passi falliti del notturno, con il suo report mail.
#
#   build/recupero.sh 'regex sui nomi dei passi'
#   build/recupero.sh 'Atti Camera|Voti|Documenti Camera|placeholder|Senato XIX|Fotografia'
#
# Esegue update_data.sh con SOLO=<regex>: girano solo i passi il cui nome
# corrisponde (senza distinguere maiuscole), gli altri si saltano. Poi
# nightly_report.py --recupero manda la mail «Recupero AAAA-MM-GG HH:MM: esito»,
# che la pagina «Stato del grafo» lega alla notte. Stesso lock del notturno:
# non parte mentre il job gira.
set -u -o pipefail
cd "$(dirname "$0")/.."

[ $# -eq 1 ] && [ -n "$1" ] || { echo "uso: build/recupero.sh 'regex sui nomi dei passi'"; exit 2; }

exec 9>/tmp/parliamentrag-nightly.lock
flock -n 9 || { echo "$(date -Is) job notturno o altro recupero in corso, riprova dopo"; exit 1; }

RECUPERO_LOG=/var/log/parliamentrag-recupero.log
echo "$(date -Is) recupero: $1" >>"$RECUPERO_LOG"
SOLO="$1" DEMO_NEO4J="${DEMO_NEO4J:-bolt://localhost:7687}" CENTRO_DIR="${CENTRO_DIR:-/opt/parliamentrag-centro}" \
	LOCAL_SYNC=0 bash build/update_data.sh >>"$RECUPERO_LOG" 2>&1
status=$?

backend/venv/bin/python build/nightly_report.py --recupero >>/var/log/parliamentrag-report.log 2>&1 \
	|| echo "$(date -Is) report del recupero non inviato: vedi /var/log/parliamentrag-report.log"
exit $status
