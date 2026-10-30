#!/bin/sh
# Downloads a fresh copy of the server's database to data/backups/ on this Mac (git-ignored).
#
#   deploy/backup.sh ubuntu@<server-ip>
set -eu
[ $# -ge 1 ] || { echo "usage: deploy/backup.sh <ssh-host>"; exit 1; }
OUT="$(dirname "$0")/../data/backups/jobdesk-$(date +%F-%H%M).db"
mkdir -p "$(dirname "$OUT")"
ssh "$1" 'sudo sqlite3 /srv/jobdesk/data/jobdesk.db ".backup /tmp/jobdesk-download.db" &&
  sudo cat /tmp/jobdesk-download.db && sudo rm -f /tmp/jobdesk-download.db' > "$OUT"
sqlite3 "$OUT" "PRAGMA integrity_check;" | grep -qx ok || { echo "Download failed: $OUT is not a valid database."; exit 1; }
echo "Saved $OUT"
