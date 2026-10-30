#!/bin/bash
# Sets up JobDesk on an Ubuntu 24.04 server (Oracle Cloud Always Free). Run as root; deploy.sh does it:
#
#   deploy/deploy.sh ubuntu@<server-ip> --setup     first time, or to change the login password
#   deploy/deploy.sh ubuntu@<server-ip>             later code updates (runs this with --update)
#
# Layout on the server (all owned by the "jobdesk" system user, except the code):
#   /srv/jobdesk/app      this repo, copied by deploy.sh (no git, no GitHub key on the server)
#   /srv/jobdesk/cv       clone of the public cv repo, pulled every 10 minutes
#   /srv/jobdesk/data     jobdesk.db (mode 700)
#   /srv/jobdesk/backups  one copy of the database per day, 14 days kept (mode 700)
#
# Caddy serves https://<domain> with a login (HTTP basic auth over HTTPS) and passes requests to
# JobDesk on 127.0.0.1:8765. Without JOBDESK_DOMAIN the domain is <ip-with-dashes>.sslip.io.
set -euo pipefail

ROOT=/srv/jobdesk
APP=$ROOT/app
CV_URL=https://github.com/david-adegbola/cv.git

install_units() {
  install -m 644 "$APP"/deploy/systemd/*.service "$APP"/deploy/systemd/*.timer /etc/systemd/system/
  systemctl daemon-reload
  systemctl enable --now jobdesk.service jobdesk-pull.timer jobdesk-backup.timer
  systemctl restart jobdesk.service
}

if [ "${1:-}" = "--update" ]; then
  install_units
  echo "JobDesk updated and restarted."
  exit 0
fi

echo "== Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 git sqlite3 curl caddy unattended-upgrades >/dev/null

echo "== Firewall"
# Oracle's Ubuntu images reject everything but SSH in iptables. Open 80 (certificate check and
# redirect) and 443. Ports must also be open in the instance's VCN security list (see README).
for port in 80 443; do
  iptables -C INPUT -p tcp --dport "$port" -j ACCEPT 2>/dev/null ||
    iptables -I INPUT 1 -p tcp --dport "$port" -j ACCEPT
done
if command -v netfilter-persistent >/dev/null; then netfilter-persistent save >/dev/null; fi

echo "== User and folders"
id jobdesk >/dev/null 2>&1 || useradd --system --home-dir "$ROOT" --shell /usr/sbin/nologin jobdesk
install -d -o jobdesk -g jobdesk -m 700 "$ROOT/data" "$ROOT/backups"
if [ ! -d "$ROOT/cv/.git" ]; then
  install -d -o jobdesk -g jobdesk -m 755 "$ROOT/cv"
  sudo -u jobdesk git clone -q "$CV_URL" "$ROOT/cv"
fi

echo "== Login"
DOMAIN=${JOBDESK_DOMAIN:-}
if [ -z "$DOMAIN" ]; then
  DOMAIN="$(curl -fsS https://api.ipify.org | tr . -).sslip.io"
fi
read -r -p "Login name [david]: " LOGIN
LOGIN=${LOGIN:-david}
while :; do
  read -r -s -p "Password (at least 16 characters): " PW; echo
  [ "${#PW}" -ge 16 ] || { echo "Too short."; continue; }
  read -r -s -p "Again: " PW2; echo
  [ "$PW" = "$PW2" ] && break
  echo "They don't match."
done
HASH=$(caddy hash-password --plaintext "$PW")
unset PW PW2
sed -e "s|{{DOMAIN}}|$DOMAIN|" -e "s|{{LOGIN}}|$LOGIN|" -e "s|{{HASH}}|$HASH|" \
  "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null

echo "== Services"
install_units
systemctl reload-or-restart caddy

echo
echo "JobDesk: https://$DOMAIN  (login: $LOGIN)"
echo "Copy your data up once with: deploy/upload-data.sh <ssh-host>"
