#!/bin/sh
set -eu

umask 077
backup_dir=/var/backups/policy-reasoning
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
backup_file="$backup_dir/policy_reasoning_$timestamp.dump"

mkdir -p "$backup_dir"
pg_dump --dbname=policy_reasoning --format=custom --file="$backup_file"
sha256sum "$backup_file" > "$backup_file.sha256"
find "$backup_dir" -type f -mtime +30 -delete
