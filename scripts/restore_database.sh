#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "Usage: bash scripts/restore_database.sh BACKUP.dump EMPTY_TARGET_DATABASE" >&2
  exit 2
fi

backup_path="$1"
target_database="$2"
source_database="${POSTGRES_DB:-knowledge_agent}"
if [[ ! -f "$backup_path" ]]; then
  echo "Backup file does not exist: $backup_path" >&2
  exit 2
fi
if [[ "$target_database" == "$source_database" ]]; then
  echo "Refusing to restore over the source database; restore to a new database." >&2
  exit 2
fi
if [[ ! "$target_database" =~ ^[A-Za-z][A-Za-z0-9_]{0,62}$ ]]; then
  echo "Target database name must be a simple PostgreSQL identifier." >&2
  exit 2
fi
if ! docker compose exec -T db pg_restore --list < "$backup_path" >/dev/null; then
  echo "Backup archive validation failed." >&2
  exit 2
fi

docker compose exec -T db createdb \
  -U "${POSTGRES_USER:-knowledge_agent}" "$target_database"
docker compose exec -T db pg_restore \
  --exit-on-error --no-owner --no-acl \
  -U "${POSTGRES_USER:-knowledge_agent}" \
  -d "$target_database" < "$backup_path"
echo "Restored to new database: $target_database"
