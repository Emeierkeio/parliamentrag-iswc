#!/usr/bin/env bash
# Nightly data update on the VPS that hosts Neo4j (cron entry in build/README.md).
#
# The checkout is deploy-only: it is reset to origin/main before every run, so
# local edits (the README stats that update_data.sh rewrites) are discarded.
# Neo4j is reached on localhost, no SSH tunnel; the local snapshot sync stays on
# the developer machine (LOCAL_SYNC=0). The Hugging Face upload runs here too,
# with the hf CLI in /opt/hf-cli (symlink in /usr/local/bin, `hf auth login`).
set -u -o pipefail
cd "$(dirname "$0")/.."

LOCK=/tmp/parliamentrag-nightly.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -Is) another run is in progress, skipping"; exit 0; }

git fetch --quiet origin main && git reset --quiet --hard origin/main \
	|| echo "$(date -Is) git update failed, running the current checkout"

# The centro site checkout must be on main with push rights (deploy key with write access).
DEMO_NEO4J="${DEMO_NEO4J:-bolt://localhost:7687}" CENTRO_DIR="${CENTRO_DIR:-/opt/parliamentrag-centro}" LOCAL_SYNC=0 \
	bash build/update_data.sh
status=$?

# Demo di ISWC (Bari): nei giorni della demo la cache delle risposte di Fascicoli,
# invalidata dalla nuova versione dei dati, si riscalda con le domande della demo.
DEMO_CACHE_GIORNI="${DEMO_CACHE_GIORNI:-2026-10-26 2026-10-27 2026-10-28 2026-10-29}"
oggi="$(date -u +%F)"
if [[ " $DEMO_CACHE_GIORNI " == *" $oggi "* ]]; then
	# Se l'aggiornamento è fallito la versione dei dati non cambia: si scalda subito.
	attendi=(); [ "$status" -eq 0 ] && attendi=(--attendi-dati "$oggi")
	python3 build/scalda_cache_fascicoli.py "${attendi[@]}" \
		>>"build/logs/scalda-cache-$oggi.log" 2>&1 \
		|| echo "$(date -Is) cache della demo non completa: vedi build/logs/scalda-cache-$oggi.log"
fi

find build/logs -name 'update-data-*.log' -mtime +30 -delete 2>/dev/null
exit $status
