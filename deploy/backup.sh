#!/usr/bin/env bash
# VerifyFlow backup: PostgreSQL dump + private document storage + checksummed manifest, with retention pruning.
#
#   DATABASE_URL=postgresql://user:pass@host:5432/verifyflow \
#   STORAGE_DIR=/var/lib/verifyflow/storage BACKUP_DIR=/srv/backups/verifyflow RETENTION_DAYS=35 \
#   deploy/backup.sh
#
# Order matters: the database is dumped FIRST, then storage is archived. Documents are never deleted, so every file
# a dumped row refers to is already in storage when the archive is taken (later uploads only add orphan files).
#
# Backups contain personal data from documents. Keep BACKUP_DIR on encrypted storage, copy each backup off-site
# (encrypted, e.g. with age or gpg), and restrict access like the production database.
#
# PG_DUMP may be overridden, e.g. PG_DUMP="docker compose -f deploy/docker-compose.yml exec -T db pg_dump".
set -euo pipefail
umask 077

: "${DATABASE_URL:?set DATABASE_URL (postgresql://...; the +psycopg driver suffix is removed automatically)}"
: "${STORAGE_DIR:?set STORAGE_DIR to the private document storage directory}"
: "${BACKUP_DIR:?set BACKUP_DIR to where backups are written}"
RETENTION_DAYS="${RETENTION_DAYS:-35}"
PG_DUMP="${PG_DUMP:-pg_dump}"
URL="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

[ -d "$STORAGE_DIR" ] || { echo "Storage directory not found: $STORAGE_DIR" >&2; exit 1; }
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="$BACKUP_DIR/verifyflow-$stamp"
mkdir -p "$target.partial"

echo "[1/3] Dumping database"
$PG_DUMP --format=custom --no-owner --no-privileges --dbname="$URL" > "$target.partial/database.dump"

echo "[2/3] Archiving document storage"
tar -C "$STORAGE_DIR" --exclude='*.part' --exclude='.probe-*' -czf "$target.partial/storage.tar.gz" .

echo "[3/3] Writing manifest"
(
  cd "$target.partial"
  {
    echo "created_utc=$stamp"
    echo "storage_files=$(find "$STORAGE_DIR" -type f ! -name '*.part' ! -name '.probe-*' | wc -l | tr -d ' ')"
    sha256sum database.dump storage.tar.gz
  } > MANIFEST
)
mv "$target.partial" "$target"   # a backup directory without .partial is complete
echo "Backup written to $target"

if [ "$RETENTION_DAYS" -gt 0 ]; then
  find "$BACKUP_DIR" -maxdepth 1 -type d -name 'verifyflow-*' ! -name '*.partial' -mtime +"$RETENTION_DAYS" -print \
    | while read -r old; do echo "Pruning $old (older than $RETENTION_DAYS days)"; rm -rf -- "$old"; done
fi
