#!/usr/bin/env bash
# Update Haq on the server after a git push: pull, reinstall requirements only if they changed, restart.
#
#   ./deploy/update.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SERVICE=haq
cd "$APP_DIR"

echo "==> Pulling the latest code"
git pull --ff-only

echo "==> Requirements"
NEW_HASH="$(sha256sum requirements.txt | cut -d' ' -f1)"
OLD_HASH="$(cat .venv/.requirements.sha256 2>/dev/null || true)"
if [[ "$NEW_HASH" != "$OLD_HASH" ]]; then
  .venv/bin/pip install --quiet -r requirements.txt
  echo "$NEW_HASH" > .venv/.requirements.sha256
  echo "requirements changed: installed"
else
  echo "unchanged"
fi

echo "==> Restarting the app"
sudo systemctl restart "$SERVICE"
for i in $(seq 1 20); do
  if curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "app is up on commit $(git rev-parse --short HEAD): $(curl -fsS http://127.0.0.1:8000/health)"
    exit 0
  fi
  sleep 1
done
echo "The app did not come back. See: sudo journalctl -u $SERVICE -n 50 --no-pager" >&2
exit 1
