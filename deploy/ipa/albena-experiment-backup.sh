#!/bin/sh
set -eu

umask 077
backup_dir=/var/backups/albena-experiment
timestamp=$(date -u +%Y%m%dT%H%M%SZ)
database_file="$backup_dir/albena_experiment_$timestamp.dump"
results_file="$backup_dir/albena_results_$timestamp.tar.gz"

mkdir -p "$backup_dir"
runuser -u postgres -- pg_dump --dbname=albena_experiment --format=custom > "$database_file"
if [ -d /var/lib/albena-experiment/completed ]; then
    tar -C /var/lib/albena-experiment -czf "$results_file" completed
else
    tar -C /var/lib/albena-experiment -czf "$results_file" --files-from /dev/null
fi
sha256sum "$database_file" "$results_file" > "$backup_dir/albena_$timestamp.sha256"
find "$backup_dir" -type f -mtime +30 -delete
