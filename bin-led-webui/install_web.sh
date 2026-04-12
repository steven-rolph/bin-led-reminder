#!/bin/bash
set -e

echo "Installing Bin LED Web UI..."

if [[ $EUID -eq 0 ]]; then
    echo "Error: Don't run this script as root. Run as your regular user."
    exit 1
fi

if [[ ! -f "main.py" ]]; then
    echo "Error: Please run this script from the bin-led-webui directory"
    exit 1
fi

if [[ ! -d "../blinkt-env" ]]; then
    echo "Error: blinkt-env virtual environment not found"
    echo "Please ensure you're in ~/blinkt-projects/bin-led-webui/"
    exit 1
fi

echo "Environment checks passed"

echo "Installing Python dependencies..."
source ../blinkt-env/bin/activate
# Install one package at a time to keep peak memory low on the Pi Zero 2.
# Prefer piwheels (pre-built ARM wheels) to avoid on-device compilation.
PIWHEELS="--extra-index-url https://www.piwheels.org/simple"
pip install --no-cache-dir $PIWHEELS fastapi
pip install --no-cache-dir $PIWHEELS uvicorn

echo "Installing systemd service..."
sudo cp bin-led-webui.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bin-led-webui.service

echo ""
echo "Installation complete!"
echo ""
echo "The web UI is enabled but not started."
echo "Start it manually when needed:"
echo "  ./manage.sh webui start"
echo "  # or: sudo systemctl start bin-led-webui"
echo ""
echo "Access via: http://$(hostname -I | awk '{print $1}'):8000"
