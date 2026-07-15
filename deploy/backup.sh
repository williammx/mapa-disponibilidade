#!/usr/bin/env sh
set -eu

BACKUP_DIR="${BACKUP_DIR:-/backups/mapa-disponibilidade}"
DATA_DIR="${DATA_DIR:-/data}"
DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

mkdir -p "$BACKUP_DIR"

pg_dump "$DATABASE_URL" | gzip > "$BACKUP_DIR/postgres-$STAMP.sql.gz"
tar -C "$DATA_DIR" -czf "$BACKUP_DIR/files-$STAMP.tar.gz" storage projects 2>/dev/null || tar -C "$DATA_DIR" -czf "$BACKUP_DIR/files-$STAMP.tar.gz" .

find "$BACKUP_DIR" -type f -mtime +30 -delete

echo "Backup criado em $BACKUP_DIR com timestamp $STAMP"
