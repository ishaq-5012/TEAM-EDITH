#!/usr/bin/env bash
# VerifyFlow restore from a backup made by deploy/backup.sh. DESTRUCTIVE for the target database and storage.
#
#   CONFIRM_RESTORE=yes DATABASE_URL=postgresql://user:pass@host:5432/verifyflow \
#   STORAGE_DIR=/var/lib/verifyflow/storage deploy/restore.sh /srv/backups/verifyflow/verifyflow-20261023T020000Z
#
# Stop the api and worker first (docker compose stop api worker) so nothing writes during the restore.
# Afterwards run the post-restore checks printed at the end, then start the services again.
#
# PG_RESTORE may be overridden, e.g. PG_RESTORE="docker compose -f deploy/docker-compose.yml exec -T db pg_restore".
set -euo pipefail
umask 077

src="${1:?usage: restore.sh <backup directory>}"
: "${DATABASE_URL:?set DATABASE_URL}"
: "${STORAGE_DIR:?set STORAGE_DIR}"
PG_RESTORE="${PG_RESTORE:-pg_restore}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

[ -f "$src/MANIFEST" ] || { echo "Not a complete backup (no MANIFEST): $src" >&2; exit 1; }
echo "[1/4] Verifying checksums"
( cd "$src" && grep -E '^[0-9a-f]{64} ' MANIFEST | sha256sum --check --strict )

if [ "${CONFIRM_RESTORE:-}" != "yes" ]; then
  echo "Checksums are valid. Re-run with CONFIRM_RESTORE=yes to REPLACE the database and storage contents." >&2
  exit 2
fi

echo "[2/4] Restoring database (existing objects are dropped first)"
$PG_RESTORE --clean --if-exists --no-owner --no-privileges --single-transaction --dbname="$URL" < "$src/database.dump"

echo "[3/4] Restoring document storage"
mkdir -p "$STORAGE_DIR"
if [ -n "$(ls -A "$STORAGE_DIR" 2>/dev/null)" ]; then
  aside="$STORAGE_DIR.before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
  echo "Storage is not empty; moving current contents to $aside"
  mkdir -p "$aside" && find "$STORAGE_DIR" -mindepth 1 -maxdepth 1 -exec mv -t "$aside" -- {} +
fi
tar -C "$STORAGE_DIR" -xzf "$src/storage.tar.gz"

echo "[4/4] Restore finished. Now verify before reopening the service:"
echo "  python -m app.cli verify-audit      # audit hash chain intact"
echo "  python -m app.cli verify-storage    # every document present and matching its SHA-256"
echo "  alembic current                     # schema revision (run 'alembic upgrade head' if the code is newer)"
