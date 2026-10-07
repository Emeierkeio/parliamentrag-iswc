#!/usr/bin/env bash
# Nightly data update on the VPS that hosts Neo4j (cron entry in build/README.md).
#
# The checkout is deploy-only: it is reset to origin/main before every run, so
# local edits (the README stats that update_data.sh rewrites) are discarded.
# Neo4j is reached on localhost, no SSH tunnel; the local snapshot sync and the
# Hugging Face upload stay on the developer machine (LOCAL_SYNC=0).
set -u -o pipefail
cd "$(dirname "$0")/.."

LOCK=/tmp/parliamentrag-nightly.lock
exec 9>"$LOCK"
flock -n 9 || { echo "$(date -Is) another run is in progress, skipping"; exit 0; }

git fetch --quiet origin main && git reset --quiet --hard origin/main \
	|| echo "$(date -Is) git update failed, running the current checkout"

DEMO_NEO4J="${DEMO_NEO4J:-bolt://localhost:7687}" LOCAL_SYNC=0 bash build/update_data.sh
status=$?

find build/logs -name 'update-data-*.log' -mtime +30 -delete 2>/dev/null
exit $status
