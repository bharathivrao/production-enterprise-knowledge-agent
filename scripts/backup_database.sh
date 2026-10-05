#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: bash scripts/backup_database.sh OUTPUT.dump" >&2
  exit 2
fi

backup_path="$1"
if [[ -e "$backup_path" ]]; then
  echo "Refusing to overwrite existing backup: $backup_path" >&2
  exit 2
fi

mkdir -p "$(dirname "$backup_path")"
umask 077
temporary_path="$(mktemp "${backup_path}.partial.XXXXXX")"
trap 'rm -f "$temporary_path"' EXIT
docker compose exec -T db pg_dump \
  --format=custom --no-owner --no-acl \
  -U "${POSTGRES_USER:-knowledge_agent}" \
  -d "${POSTGRES_DB:-knowledge_agent}" > "$temporary_path"
docker compose exec -T db pg_restore --list < "$temporary_path" >/dev/null
mv -n "$temporary_path" "$backup_path"
if [[ -e "$temporary_path" ]]; then
  echo "Refusing to overwrite a backup created concurrently: $backup_path" >&2
  exit 2
fi
trap - EXIT
echo "Backup created and validated: $backup_path"
