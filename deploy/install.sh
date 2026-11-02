#!/bin/bash
# Sets up Woodesk on an Ubuntu 24.04 server (Oracle Cloud Always Free). Run as root; deploy.sh does it:
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
# Caddy serves HTTPS and passes requests to Woodesk on 127.0.0.1:8765. Accounts are managed by
# Woodesk; the first administrator is provisioned after the database has been uploaded.
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

configure_caddy() {
  DOMAIN=${JOBDESK_DOMAIN:-}
  if [ -z "$DOMAIN" ] && [ -f /etc/caddy/Caddyfile ]; then
    DOMAIN=$(awk 'NF && $1 !~ /^#/ {gsub(/[{}]/, "", $1); print $1; exit}' /etc/caddy/Caddyfile)
  fi
  if [ -z "$DOMAIN" ]; then
    DOMAIN="$(curl -fsS https://api.ipify.org | tr . -).sslip.io"
  fi
  sed "s|{{DOMAIN}}|$DOMAIN|" "$APP/deploy/Caddyfile" > /etc/caddy/Caddyfile.new
  caddy validate --config /etc/caddy/Caddyfile.new --adapter caddyfile >/dev/null
  install -m 644 /etc/caddy/Caddyfile.new /etc/caddy/Caddyfile
  rm -f /etc/caddy/Caddyfile.new
}

install_latex_packages() {
  if command -v pdflatex >/dev/null && command -v kpsewhich >/dev/null \
    && kpsewhich libertine.sty >/dev/null && kpsewhich fontawesome.sty >/dev/null \
    && kpsewhich tikz.sty >/dev/null && kpsewhich finnish.ldf >/dev/null; then
    return
  fi
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends \
    texlive-latex-extra texlive-fonts-extra texlive-lang-european >/dev/null
}

if [ "${1:-}" = "--update" ]; then
  install_latex_packages
  install_units
  configure_caddy
  systemctl reload-or-restart caddy
  echo "Woodesk updated and restarted."
  exit 0
fi

echo "== Packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
  python3 git sqlite3 curl caddy unattended-upgrades \
  texlive-latex-extra texlive-fonts-extra texlive-lang-european >/dev/null

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

echo "== HTTPS and account login"
configure_caddy

echo "== Services"
install_units
systemctl reload-or-restart caddy

echo
echo "Woodesk: https://$DOMAIN"
echo "Copy your data and set the administrator account with: deploy/upload-data.sh <ssh-host>"
