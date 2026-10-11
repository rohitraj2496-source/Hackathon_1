#!/usr/bin/env bash
# Set up Haq on a fresh Ubuntu 24.04 server: Python venv, systemd service on 127.0.0.1:8000,
# and Caddy as the HTTPS reverse proxy (free Let's Encrypt certificate) for the given domain.
#
#   ./deploy/setup.sh 44-197-229-105.sslip.io
#
# Safe to run again: every step checks what is already there. Run from inside the cloned repo,
# as the normal login user (it uses sudo where needed). It never prints or copies .env.
set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
  echo "Usage: ./deploy/setup.sh <domain>   e.g. ./deploy/setup.sh 44-197-229-105.sslip.io" >&2
  exit 1
fi

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
SERVICE=haq
step() { echo; echo "==> $*"; }

cd "$APP_DIR"
if [[ "$APP_USER" == "root" ]]; then
  echo "Run this as your normal user (e.g. ubuntu), not root. It uses sudo itself." >&2
  exit 1
fi

step "System packages (Python 3.12, venv, git, curl)"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y python3.12 python3.12-venv git curl ca-certificates \
  debian-keyring debian-archive-keyring apt-transport-https gnupg

step "Swap file (t3.small has 2 GB RAM; 1 GB swap avoids out-of-memory during installs)"
if ! swapon --show | grep -q '/swapfile'; then
  if [[ ! -f /swapfile ]]; then
    sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile
  fi
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
else
  echo "swap already on"
fi

step "Python virtual environment and requirements"
if [[ ! -x .venv/bin/python ]]; then
  python3.12 -m venv .venv
fi
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
sha256sum requirements.txt | cut -d' ' -f1 > .venv/.requirements.sha256
# Playwright / Chromium are NOT installed: the app's fetcher reads official pages with httpx + pypdf.
# Playwright is only used by local test scripts (requirements-dev.txt).

step "Secrets file (.env)"
if [[ -f .env ]]; then
  chmod 600 .env
  if git ls-files --error-unmatch .env >/dev/null 2>&1; then
    echo "WARNING: .env is tracked by git. Remove it from git now: git rm --cached .env" >&2
  fi
  for key in ANTHROPIC_API_KEY NEATLOGS_API_KEY HAQ_LIVE_PASSCODE; do
    grep -q "^${key}=." .env || echo "note: ${key} is not set in .env"
  done
  echo ".env found (permissions set to owner-only)"
else
  echo "No .env yet. The site will run in DEMO mode only (recorded runs, no live checks)."
  echo "Create it later with: nano .env   (see deploy/README.md), then: sudo systemctl restart $SERVICE"
fi
mkdir -p data

step "systemd service ($SERVICE) on 127.0.0.1:8000"
UNIT_FILE="/etc/systemd/system/${SERVICE}.service"
UNIT_CONTENT="[Unit]
Description=Haq — government schemes finder (FastAPI)
After=network-online.target
Wants=network-online.target

[Service]
User=${APP_USER}
WorkingDirectory=${APP_DIR}
Environment=HAQ_PUBLIC=1
Environment=PYTHONUNBUFFERED=1
# One worker: rate limits and the in-memory state cache live in this process.
ExecStart=${APP_DIR}/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=on-failure
RestartSec=5
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
"
if [[ ! -f "$UNIT_FILE" ]] || [[ "$(cat "$UNIT_FILE")" != "$(printf "%s" "$UNIT_CONTENT")" ]]; then
  echo "$UNIT_CONTENT" | sudo tee "$UNIT_FILE" >/dev/null
  sudo systemctl daemon-reload
  echo "service file written"
fi
sudo systemctl enable "$SERVICE" >/dev/null
sudo systemctl restart "$SERVICE"

step "Caddy (HTTPS reverse proxy with automatic Let's Encrypt certificate)"
if ! command -v caddy >/dev/null 2>&1; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -y
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y caddy
else
  echo "caddy already installed"
fi
CADDYFILE="${DOMAIN} {
	encode zstd gzip
	request_body {
		max_size 1MB
	}
	header {
		Strict-Transport-Security \"max-age=31536000\"
		X-Content-Type-Options nosniff
		Referrer-Policy strict-origin-when-cross-origin
		Permissions-Policy \"microphone=(self), camera=(), geolocation=()\"
		-Server
	}
	reverse_proxy 127.0.0.1:8000
	log {
		output file /var/log/caddy/haq-access.log {
			roll_size 10MiB
			roll_keep 5
		}
	}
}
"
if [[ "$(sudo cat /etc/caddy/Caddyfile 2>/dev/null)" != "$(printf "%s" "$CADDYFILE")" ]]; then
  echo "$CADDYFILE" | sudo tee /etc/caddy/Caddyfile >/dev/null
  echo "Caddyfile written for ${DOMAIN}"
fi
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null
sudo systemctl enable caddy >/dev/null
sudo systemctl reload caddy 2>/dev/null || sudo systemctl restart caddy

if command -v ufw >/dev/null 2>&1 && sudo ufw status | grep -q "Status: active"; then
  step "Firewall (ufw is on): allowing SSH, HTTP and HTTPS"
  sudo ufw allow OpenSSH >/dev/null && sudo ufw allow 80/tcp >/dev/null && sudo ufw allow 443/tcp >/dev/null
fi

step "Health check"
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "app is up: $(curl -fsS http://127.0.0.1:8000/health)"
    break
  fi
  sleep 1
  if [[ $i -eq 20 ]]; then
    echo "The app did not answer. See: sudo journalctl -u $SERVICE -n 50 --no-pager" >&2
    exit 1
  fi
done

echo
echo "Done. Open https://${DOMAIN}/"
echo "(The first HTTPS visit can take ~30 seconds while Caddy gets the certificate.)"
echo "Ports 80 and 443 must be open in the AWS security group."
