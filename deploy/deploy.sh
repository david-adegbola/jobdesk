#!/bin/sh
# Copies the last commit of this repo to the server and restarts Woodesk. Run from your Mac:
#
#   deploy/deploy.sh ubuntu@<server-ip> --setup   first time (packages, login, services)
#   deploy/deploy.sh ubuntu@<server-ip>           after you commit a change
#
# Only committed files are sent (git archive), so data/ and anything uncommitted stay on the Mac.
set -eu
[ $# -ge 1 ] || { echo "usage: deploy/deploy.sh <ssh-host> [--setup]"; exit 1; }
HOST=$1
cd "$(dirname "$0")/.."
[ -z "$(git status --porcelain)" ] || echo "Note: uncommitted changes are not sent, only the last commit."

git archive --format=tar HEAD | ssh "$HOST" '
  set -e
  sudo mkdir -p /srv/jobdesk
  sudo rm -rf /srv/jobdesk/app.new && sudo mkdir /srv/jobdesk/app.new
  sudo tar -x -C /srv/jobdesk/app.new
  sudo rm -rf /srv/jobdesk/app && sudo mv /srv/jobdesk/app.new /srv/jobdesk/app'

if [ "${2:-}" = "--setup" ]; then
  ssh -t "$HOST" sudo bash /srv/jobdesk/app/deploy/install.sh
else
  ssh "$HOST" sudo bash /srv/jobdesk/app/deploy/install.sh --update
fi
