#!/bin/bash
# Daily PostgreSQL backup → Amazon S3. Install as /opt/backup/pg_backup.sh (chmod 700), then cron:
#   0 3 * * * /opt/backup/pg_backup.sh >> /var/log/pg_backup.log 2>&1
# Needs: AWS CLI v2 configured (`aws configure`) with an IAM user allowed only s3:PutObject on the prefix.
set -euo pipefail
# cron's PATH is only /usr/bin:/bin; AWS CLI v2 lives in /usr/local/bin.
export PATH=/usr/local/bin:/usr/bin:/bin

APP_DIR="/opt/wikischolar"
COMPOSE="docker compose -f $APP_DIR/docker-compose.prod.yml --project-directory $APP_DIR"
S3_URI="s3://CHANGE-ME-bucket/postgres"
BACKUP_DIR="/opt/backup/files"
KEEP_LOCAL_DAYS=3
# healthchecks.io ping URL (emails you when a daily run is missed or fails). Empty = off.
HC_URL=""

ping_hc() { [ -n "$HC_URL" ] && curl -fsS -m 10 --retry 3 -o /dev/null "$HC_URL$1" || true; }
trap 'echo "$(date -Is) backup FAILED"; ping_hc /fail' ERR

DB_NAME=$(grep -E '^DB_NAME=' "$APP_DIR/.env" | cut -d= -f2-)
DB_USER=$(grep -E '^DB_USER=' "$APP_DIR/.env" | cut -d= -f2-)
STAMP=$(date +%Y-%m-%d_%H-%M)
FILE="$BACKUP_DIR/${DB_NAME}_$STAMP.dump"

mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"
umask 077

ping_hc /start
# No -t: a pseudo-terminal can mangle the binary custom-format dump.
$COMPOSE exec -T db pg_dump -U "$DB_USER" -Fc "$DB_NAME" > "$FILE.part"
# A dump that pg_restore can't list is corrupt; an empty one means pg_dump failed silently.
[ -s "$FILE.part" ] || { echo "empty dump"; false; }
$COMPOSE exec -T db pg_restore --list < "$FILE.part" > /dev/null
mv "$FILE.part" "$FILE"

aws s3 cp "$FILE" "$S3_URI/" --sse AES256 --only-show-errors

find "$BACKUP_DIR" -name "*.dump" -mtime +"$KEEP_LOCAL_DAYS" -delete
find "$BACKUP_DIR" -name "*.part" -delete
echo "$(date -Is) backup OK: $(basename "$FILE") ($(du -h "$FILE" | cut -f1))"
ping_hc ""
