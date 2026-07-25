#!/bin/bash
# Pulls the latest code on europa and restarts affected services if anything
# changed. Installed to run on a schedule via auto-deploy.timer — see
# CLAUDE.md's "Deployment workflow" section. --ff-only means this never
# attempts to merge: if the working tree has diverged (e.g. something was
# edited directly on the Pi), it fails loudly instead of guessing.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_DIR"

BEFORE=$(git rev-parse HEAD)
git pull --ff-only origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
    echo "$(date -Iseconds) No changes."
    exit 0
fi

echo "$(date -Iseconds) Updated $BEFORE -> $AFTER, restarting services."
sudo systemctl restart bin-led-reminder

if systemctl is-active --quiet bin-led-webui; then
    echo "$(date -Iseconds) bin-led-webui is running, restarting it too."
    sudo systemctl restart bin-led-webui
fi
