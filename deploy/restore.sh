#!/usr/bin/env sh
set -eu

DATABASE_URL="${DATABASE_URL:?DATABASE_URL is required}"
SQL_BACKUP="${1:?Informe o arquivo postgres-*.sql.gz}"
FILES_BACKUP="${2:-}"
DATA_DIR="${DATA_DIR:-/data}"

gunzip -c "$SQL_BACKUP" | psql "$DATABASE_URL"

if [ -n "$FILES_BACKUP" ]; then
  mkdir -p "$DATA_DIR"
  tar -C "$DATA_DIR" -xzf "$FILES_BACKUP"
fi

echo "Restore concluido"
