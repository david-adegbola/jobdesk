#!/bin/sh
# Copies data/jobdesk.db from this Mac to the server. Use once, after the first deploy.sh --setup.
# It refuses to overwrite data already on the server unless you add --replace.
#
#   deploy/upload-data.sh ubuntu@<server-ip> [--replace]
set -eu
[ $# -ge 1 ] || { echo "usage: deploy/upload-data.sh <ssh-host> [--replace]"; exit 1; }
HOST=$1
DB="$(dirname "$0")/../data/jobdesk.db"
[ -f "$DB" ] || { echo "No $DB on this Mac."; exit 1; }
if ssh "$HOST" sudo test -s /srv/jobdesk/data/jobdesk.db && [ "${2:-}" != "--replace" ]; then
  echo "The server already has a jobdesk.db. Download it first (deploy/backup.sh), then add --replace."
  exit 1
fi
sqlite3 "$DB" "PRAGMA wal_checkpoint(TRUNCATE);" >/dev/null
scp -q "$DB" "$HOST:/tmp/jobdesk-upload.db"
ssh "$HOST" '
  set -e
  sudo systemctl stop jobdesk
  sudo install -o jobdesk -g jobdesk -m 600 /tmp/jobdesk-upload.db /srv/jobdesk/data/jobdesk.db
  sudo rm -f /tmp/jobdesk-upload.db /srv/jobdesk/data/jobdesk.db-wal /srv/jobdesk/data/jobdesk.db-shm
  sudo systemctl start jobdesk'
echo "Uploaded. The server copy is now the one to use."
