#!/bin/bash
set -e

echo "🗑️  Installing Bin LED Reminder Service..."

# Check if running as root for some operations
if [[ $EUID -eq 0 ]]; then
   echo "⚠️  Don't run this script as root. Run as your regular user."
   exit 1
fi

# Ensure we're in the right directory
if [[ ! -f "bin_led_service.py" ]]; then
    echo "❌ Error: Please run this script from the bin-led-reminder directory"
    exit 1
fi

# Check if virtual environment exists
if [[ ! -d "../blinkt-env" ]]; then
    echo "❌ Error: blinkt-env virtual environment not found"
    echo "Please ensure you're in ~/blinkt-projects/bin-led-reminder/"
    exit 1
fi

echo "✅ Environment checks passed"

# Install Python dependencies
echo "📦 Installing Python dependencies..."
source ../blinkt-env/bin/activate
pip install -r requirements.txt

# Create log directory with correct permissions
echo "📝 Setting up logging..."
sudo mkdir -p /var/log
sudo touch /var/log/bin-led-reminder.log
sudo chown pizero2:pizero2 /var/log/bin-led-reminder.log

# Install systemd service
echo "⚙️  Installing systemd service..."
sudo cp bin-led-reminder.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable the service (but don't start it yet)
sudo systemctl enable bin-led-reminder.service

echo "🎉 Installation complete!"
echo ""
echo "Service commands:"
echo "  Start:   sudo systemctl start bin-led-reminder"
echo "  Stop:    sudo systemctl stop bin-led-reminder"
echo "  Status:  sudo systemctl status bin-led-reminder"
echo "  Logs:    sudo journalctl -u bin-led-reminder -f"
echo "  Log file: tail -f /var/log/bin-led-reminder.log"
echo ""
echo "The service is enabled and will start automatically on boot."
echo "Run 'sudo systemctl start bin-led-reminder' to start it now."
